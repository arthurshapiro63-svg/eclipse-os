"""Where the Eclipse Store gets its data and does its work.

Root work (install, remove, update) goes through arclightd (pkg.install / pkg.remove / pkg.upgrade), so there
is never a password prompt, the system makes a restore point first (btrfs installs), and the AI sees the same
log. While a job runs the Store polls pkg.status on a second connection for the live pacman / yay output.
Read-only facts (what is installed, sizes, menu entries) come from pacman directly. The AUR is searched with
its RPC; Flathub with `flatpak search` when flatpak is installed (Flatpak installs are per user, no root).

With ARCLIGHT_STORE_FAKE=1 (arclight-store --demo) every call goes to fake.py instead.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from . import catalog
from ..settings import backend as SB

RemoteError = SB.RemoteError
Unavailable = SB.Unavailable
run_async = SB.run_async
AUR_RPC = "https://aur.archlinux.org/rpc/v5"


def fake_mode():
    return os.environ.get("ARCLIGHT_STORE_FAKE") == "1"


def _fake():
    from . import fake
    return fake


def message(err):
    return SB.message(err)


def call(method, **params):
    """Blocking arclightd call on this thread's own connection."""
    if fake_mode():
        return _fake().call(method, **params)
    which = SB.C.target_for(method)
    c, path = SB._client(which)
    try:
        return c.call(method, **params)
    except (ConnectionError, BrokenPipeError):
        SB._local.clients.pop(path, None)
        c, _ = SB._client(which)
        return c.call(method, **params)


# ------------------------------------------------------------------ facts
def has_flatpak():
    if fake_mode():
        return _fake().HAS_FLATPAK
    return shutil.which("flatpak") is not None


def installed():
    """{name: version} for pacman packages and installed Flatpak app ids."""
    if fake_mode():
        return dict(_fake().INSTALLED)
    v = catalog.installed_versions()
    if has_flatpak():
        for a in flatpak_apps():
            v[a["name"]] = a.get("version") or "flatpak"
    return v


def search_repo(query):
    if fake_mode():
        return _fake().search_repo(query)
    rows = call("pkg.search", query=query, aur=False, limit=60)
    return [{"name": r["name"], "source": "repo", "repo": r.get("repo"), "version": r.get("version"),
             "installed": bool(r.get("installed")), "description": r.get("description") or ""}
            for r in rows if r.get("name")]


def search_aur(query):
    if fake_mode():
        return _fake().search_aur(query)
    url = f"{AUR_RPC}/search/{urllib.parse.quote(query)}?by=name-desc"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    if data.get("type") == "error":
        raise RuntimeError(data.get("error") or "AUR search failed")
    res = sorted(data.get("results", []), key=lambda a: -(a.get("Popularity") or 0))[:60]
    return [{"name": a["Name"], "source": "aur", "version": a.get("Version"), "description": a.get("Description") or "",
             "votes": a.get("NumVotes") or 0, "popularity": a.get("Popularity") or 0,
             "out_of_date": bool(a.get("OutOfDate")), "url": a.get("URL"), "maintainer": a.get("Maintainer")}
            for a in res]


def search_flatpak(query):
    if fake_mode():
        return _fake().search_flatpak(query)
    if not has_flatpak():
        return []
    p = subprocess.run(["flatpak", "search", "--columns=application,name,description,version,remotes", query],
                       capture_output=True, text=True, timeout=60, env=catalog.ENV)
    out = []
    for line in p.stdout.splitlines():
        cols = line.split("\t")
        if len(cols) < 3 or "." not in cols[0]:
            continue
        out.append({"name": cols[0], "title": cols[1], "source": "flatpak", "description": cols[2],
                    "version": cols[3] if len(cols) > 3 else "", "remote": (cols[4].split(",")[0] if len(cols) > 4 else "flathub")})
    return out[:40]


def sizes(names):
    if fake_mode():
        return _fake().sizes(names)
    return catalog.repo_sizes(names)


def details(item):
    """More about one app: version, sizes, website, licence, what it needs."""
    if fake_mode():
        return _fake().details(item)
    name, src = item["name"], item.get("source", "repo")
    if src == "flatpak":
        out = {}
        if has_flatpak():
            p = subprocess.run(["flatpak", "remote-info", item.get("remote") or "flathub", name],
                               capture_output=True, text=True, timeout=60, env=catalog.ENV)
            for line in p.stdout.splitlines():
                m = re.match(r"^\s*([A-Za-z ]+?):\s+(.*)$", line)
                if m:
                    out[m.group(1).strip().lower().replace(" ", "_")] = m.group(2).strip()
        return {"version": out.get("version") or item.get("version"), "size": catalog.parse_size(out.get("installed_size", "").replace(" ", " ")),
                "download_size": catalog.parse_size(out.get("download_size", "").replace(" ", " ")),
                "license": out.get("license"), "url": None}
    if src == "aur":
        with urllib.request.urlopen(f"{AUR_RPC}/info?arg[]={urllib.parse.quote(name)}", timeout=15) as r:
            res = (json.load(r).get("results") or [{}])[0]
        return {"version": res.get("Version"), "url": res.get("URL"), "license": " ".join(res.get("License") or []),
                "description": res.get("Description"), "votes": res.get("NumVotes"), "size": None,
                "needs": len(res.get("Depends") or []), "maintainer": res.get("Maintainer"),
                "out_of_date": bool(res.get("OutOfDate"))}
    d = call("pkg.info", name=name)
    return {"version": d.get("version"), "url": d.get("url"), "license": d.get("licenses"),
            "description": d.get("description"), "size": catalog.parse_size(d.get("installed_size")),
            "download_size": catalog.parse_size(d.get("download_size")), "needs": len(d.get("depends_on") or []),
            "repo_version": d.get("repo_version"), "installed": d.get("installed")}


def flatpak_apps():
    if not has_flatpak():
        return []
    p = subprocess.run(["flatpak", "list", "--app", "--columns=application,name,version,description"],
                       capture_output=True, text=True, timeout=60, env=catalog.ENV)
    out = []
    for line in p.stdout.splitlines():
        cols = line.split("\t")
        if len(cols) >= 2 and "." in cols[0]:
            out.append({"name": cols[0], "title": cols[1], "version": cols[2] if len(cols) > 2 else "",
                        "description": cols[3] if len(cols) > 3 else "", "source": "flatpak", "installed": True})
    return out


def installed_apps():
    if fake_mode():
        return _fake().installed_apps()
    apps = catalog.installed_apps()
    apps += flatpak_apps()
    return apps


def updates():
    """Packages with a newer version (same call Settings -> System uses)."""
    if fake_mode():
        return _fake().updates()
    return call("pkg.list", upgradable=True, aur=True) or []


def desktop_entry(item):
    """The menu entry of an installed app (for its icon and Open)."""
    if fake_mode():
        return _fake().desktop_entry(item)
    if item.get("desktop"):
        return catalog.read_desktop(item["desktop"])
    if item.get("source") == "flatpak":
        for d in catalog.APP_DIRS:
            f = d / f"{item['name']}.desktop"
            if f.exists():
                return catalog.read_desktop(f)
        return None
    ents = catalog.desktop_files_of(item["name"])
    return ents[0] if ents else None


# ------------------------------------------------------------------ jobs
class JobError(Exception):
    def __init__(self, message, output=""):
        super().__init__(message)
        self.message = message
        self.output = output


def run_job(action, item=None, on_line=None):
    """Install / remove one app, or update everything. Blocks; calls on_line(text) for every output line
    (from this worker thread). Returns {"snapshot": {...} | None, "result": ...}; raises JobError."""
    if fake_mode():
        return _fake().run_job(action, item, on_line)
    if item and item.get("source") == "flatpak":
        return _flatpak_job(action, item, on_line)
    if action == "install":
        method, params = "pkg.install", {"names": [item["name"]], "aur": item.get("source") == "aur"}
    elif action == "remove":
        method, params = "pkg.remove", {"names": [item["name"]]}
    elif action == "update":
        method, params = "pkg.upgrade", {"aur": True}
    else:
        raise ValueError(action)

    stream = {"ok": True, "job": None, "next": 0, "snapshot": None}
    try:
        stream["job"] = call("pkg.status")["job"]          # the job id before ours
    except Exception:
        stream["ok"] = False                                  # older arclightd: no live log, bar pulses
    box = {}

    def main():
        try:
            box["result"] = call(method, **params)
        except Exception as e:  # delivered below
            box["error"] = e

    t = threading.Thread(target=main, daemon=True)
    t.start()

    def poll():
        mine = stream.get("mine")
        try:
            st = call("pkg.status", since=stream["next"] if mine else 0, job=mine if mine else -1)
        except Exception:
            stream["ok"] = False
            return
        if st["job"] == stream["job"] or (mine and st["job"] != mine):
            return                    # ours has not started yet / a newer job (not ours) replaced it
        stream["mine"] = st["job"]
        stream["next"] = st["next"]
        stream["snapshot"] = st.get("snapshot") or stream["snapshot"]
        for line in st.get("lines") or []:
            if on_line:
                on_line(line)

    while t.is_alive():
        t.join(0.35)
        if stream["ok"]:
            poll()
    if stream["ok"]:
        poll()
    if "error" in box:
        e = box["error"]
        raise JobError(message(e), message(e))
    res = box.get("result")
    snap = (res or {}).get("snapshot") if isinstance(res, dict) else None
    if not stream["ok"] and on_line and isinstance(res, dict):
        for line in (res.get("output") or "\n".join(v.get("output", "") for v in res.values() if isinstance(v, dict))).splitlines():
            on_line(line)
    return {"snapshot": snap or stream["snapshot"], "result": res}


def _flatpak_job(action, item, on_line):
    if action == "install":
        subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub",
                        "https://dl.flathub.org/repo/flathub.flatpakrepo"], capture_output=True, timeout=120)
        cmd = ["flatpak", "install", "--user", "-y", "--noninteractive", item.get("remote") or "flathub", item["name"]]
    elif action == "remove":
        scope = "--user"
        if subprocess.run(["flatpak", "info", "--user", item["name"]], capture_output=True).returncode != 0:
            scope = "--system"
        cmd = ["flatpak", "uninstall", scope, "-y", "--noninteractive", item["name"]]
    else:
        cmd = ["flatpak", "update", "--user", "-y", "--noninteractive"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=catalog.ENV)
    out, buf = [], b""
    while True:
        chunk = p.stdout.read1(65536)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb"\r\n|\r|\n", buf)
        buf = parts.pop()
        for raw in parts:
            line = raw.decode(errors="replace").rstrip()
            if line:
                out.append(line)
                on_line and on_line(line)
    if p.wait() != 0:
        raise JobError("\n".join(out[-6:]) or "flatpak failed", "\n".join(out))
    return {"snapshot": None, "result": {"output": "\n".join(out)}}


# ------------------------------------------------------------------ launching
def _spawn(cmd):
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_app(item, entry=None):
    """Start an installed app. True when something was started."""
    if fake_mode():
        return _fake().open_app(item)
    if item.get("source") == "flatpak":
        _spawn(["flatpak", "run", item["name"]])
        return True
    entry = entry or desktop_entry(item)
    if entry:
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
            info = Gio.DesktopAppInfo.new_from_filename(entry["file"])
            if info and info.launch([], None):
                return True
        except Exception:
            pass
        if shutil.which("gtk-launch"):
            _spawn(["gtk-launch", entry["id"]])
            return True
    if shutil.which(item["name"]):
        _spawn([item["name"]])
        return True
    return False


def ask(prefill):
    """Open the Ask overlay with text already typed."""
    if fake_mode():
        return _fake().ask(prefill)
    _spawn(["arclight-ask", "--prefill", prefill])
    return True
