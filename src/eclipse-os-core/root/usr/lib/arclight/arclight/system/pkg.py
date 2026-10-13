"""Packages: pacman for the repos, yay (as the calling user) for the AUR."""
import json
import os
import pwd
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from ..rpc import RPCError
from ..util import run, run_full, clip_text, which

ENV = {"LANG": "C", "LC_ALL": "C"}
LOCK = Path("/var/lib/pacman/db.lck")


def _names(names):
    if isinstance(names, str):
        names = names.replace(",", " ").split()
    names = [n.strip() for n in names or [] if n and n.strip()]
    for n in names:
        if not re.fullmatch(r"[A-Za-z0-9@._+\-/]+", n):
            raise RPCError(f"not a package name: {n!r}")
    if not names:
        raise RPCError("no package names given")
    return names


# ---- live output of the running package job (install / remove / upgrade), read with pkg.status
_JOB = {"id": 0, "label": None, "active": False, "lines": [], "snapshot": None, "started": None, "ended": None}
_JOB_LOCK = threading.Lock()
_JOB_MAX_LINES = 20000


def _job_start(label):
    with _JOB_LOCK:
        _JOB.update(id=_JOB["id"] + 1, label=label, active=True, lines=[], snapshot=None,
                    started=time.time(), ended=None)


def _job_line(line):
    with _JOB_LOCK:
        if _JOB["active"] and len(_JOB["lines"]) < _JOB_MAX_LINES:
            _JOB["lines"].append(line)


def _job_end():
    with _JOB_LOCK:
        _JOB.update(active=False, ended=time.time())


def _stream(cmd, env=None, timeout=3600):
    """Like util.run_full (same result shape), but every output line also goes to the live job log
    (pkg.status) as it happens. stderr is merged into stdout so the order is kept."""
    e = dict(os.environ)
    e.update(env or {})
    t0 = time.monotonic()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=e)
    except OSError as ex:
        return {"code": 127, "stdout": "", "stderr": str(ex), "seconds": 0}
    killed = []
    timer = threading.Timer(timeout, lambda: (killed.append(True), p.kill()))
    timer.start()
    out, buf = [], b""
    try:
        while True:
            chunk = p.stdout.read1(65536) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            # pacman/yay redraw progress with \r; treat it as a line end too
            parts = re.split(rb"\r\n|\r|\n", buf)
            buf = parts.pop()
            for raw in parts:
                line = raw.decode(errors="replace").rstrip()
                if line:
                    out.append(line)
                    _job_line(line)
        if buf.strip():
            line = buf.decode(errors="replace").rstrip()
            out.append(line)
            _job_line(line)
        code = p.wait()
    finally:
        timer.cancel()
    timed_out = bool(killed)
    return {"code": -1 if timed_out else code, "stdout": "\n".join(out) + ("\n" if out else ""),
            "stderr": f"timed out after {timeout}s" if timed_out else "", "seconds": round(time.monotonic() - t0, 3)}


def status(since=0, job=None):
    """Live output of the running (or last) package job: install, remove or upgrade.

    Poll it while a pkg.install/remove/upgrade call is running: pass since=<next> from the last answer to
    get only new lines. `snapshot` is the restore point made before the job (btrfs installs), if any."""
    since = max(0, int(since or 0))
    with _JOB_LOCK:
        if job is not None and int(job) != _JOB["id"]:
            since = 0
        lines = _JOB["lines"][since:]
        return {"job": _JOB["id"], "label": _JOB["label"], "active": _JOB["active"], "lines": lines,
                "next": since + len(lines), "snapshot": _JOB["snapshot"], "started": _JOB["started"],
                "ended": _JOB["ended"]}


def _check_lock():
    if LOCK.exists():
        holders = run("fuser /var/lib/pacman/db.lck 2>/dev/null || true", check=False).strip()
        if holders:
            raise RPCError(f"pacman is busy (db.lck held by pid {holders}); try again when it finishes")
        LOCK.unlink()  # stale lock left by a crashed pacman


def _parse_info(text):
    info, key = {}, None
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z][A-Za-z ]+?)\s*: (.*)$", line)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            info[key] = m.group(2).strip()
        elif key and line.startswith(" "):
            info[key] += " " + line.strip()
    for k in ("depends_on", "optional_deps", "required_by", "provides", "conflicts_with", "groups", "replaces"):
        if k in info:
            info[k] = [] if info[k] == "None" else info[k].split()
    return info


def _ensure_dbs():
    """Right after an install the package lists may not be downloaded yet (first boot fetches them once the
    network is up). Without them every repo package looks unknown and is wrongly sent to the AUR, so: wait for
    that first-boot download if it is running, else download the lists now."""
    sync = Path("/var/lib/pacman/sync")
    if all((sync / f"{r}.db").exists() for r in ("core", "extra")):
        return
    for _ in range(36):  # up to 3 min for arclight-pacman-sync (it waits for DNS itself)
        st = subprocess.run(["systemctl", "is-active", "arclight-pacman-sync.service"],
                            capture_output=True, text=True).stdout.strip()
        if st not in ("activating", "active"):
            break
        time.sleep(5)
    if not all((sync / f"{r}.db").exists() for r in ("core", "extra")):
        run(["pacman", "-Sy"], env=ENV, timeout=600, check=False)


def search(query, aur=True, limit=40):
    """Search the repos (and the AUR) by name and description."""
    _ensure_dbs()
    out = run(["pacman", "-Ss", query], env=ENV, check=False)
    res, cur = [], None
    for line in out.splitlines():
        if not line.startswith(" "):
            m = re.match(r"^(\S+)/(\S+) (\S+)(.*)$", line)
            if m:
                cur = {"repo": m.group(1), "name": m.group(2), "version": m.group(3),
                       "installed": "[installed" in m.group(4), "description": ""}
                res.append(cur)
        elif cur:
            cur["description"] = line.strip()
    res = res[:limit]
    if aur:
        try:
            url = "https://aur.archlinux.org/rpc/v5/search/" + urllib.parse.quote(query) + "?by=name-desc"
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.load(r)
            aur_res = sorted(data.get("results", []), key=lambda x: -(x.get("Popularity") or 0))[:limit]
            installed = set(run(["pacman", "-Qqm"], check=False).split())
            res += [{"repo": "aur", "name": a["Name"], "version": a["Version"], "installed": a["Name"] in installed,
                     "description": a.get("Description") or "", "votes": a.get("NumVotes"),
                     "out_of_date": bool(a.get("OutOfDate"))} for a in aur_res]
        except Exception as e:
            res.append({"repo": "aur", "error": f"AUR search failed: {e}"})
    return res


def info(name):
    """Details for one package: installed info if installed, else sync/AUR info."""
    name = _names(name)[0]
    q = run_full(["pacman", "-Qi", name], env=ENV)
    if q["code"] == 0:
        d = _parse_info(q["stdout"])
        d["installed"] = True
        s = run_full(["pacman", "-Si", name], env=ENV)
        if s["code"] == 0:
            d["repo_version"] = _parse_info(s["stdout"]).get("version")
        return d
    s = run_full(["pacman", "-Si", name], env=ENV)
    if s["code"] == 0:
        d = _parse_info(s["stdout"])
        d["installed"] = False
        return d
    try:
        with urllib.request.urlopen(f"https://aur.archlinux.org/rpc/v5/info?arg[]={urllib.parse.quote(name)}", timeout=15) as r:
            data = json.load(r)
        if data.get("results"):
            a = data["results"][0]
            return {"name": a["Name"], "version": a["Version"], "description": a.get("Description"),
                    "repository": "aur", "url": a.get("URL"), "depends_on": a.get("Depends", []),
                    "make_depends": a.get("MakeDepends", []), "votes": a.get("NumVotes"), "installed": False}
    except Exception:
        pass
    raise RPCError(f"no package named {name!r} in the repos or the AUR")


def listing(explicit=False, foreign=False, query=None, upgradable=False):
    """Installed packages (optionally explicit-only / foreign-only / filtered / upgradable)."""
    if upgradable:
        r = run_full(["checkupdates", "--nocolor"], env=ENV, timeout=300)
        ups = []
        for line in r["stdout"].splitlines():
            m = re.match(r"^(\S+) (\S+) -> (\S+)", line)
            if m:
                ups.append({"name": m.group(1), "version": m.group(2), "new_version": m.group(3)})
        return ups
    flags = "-Q" + ("e" if explicit else "") + ("m" if foreign else "")
    out = run(["pacman", flags], env=ENV, check=False)
    pk = [dict(zip(("name", "version"), l.split()[:2])) for l in out.splitlines() if l.strip()]
    if query:
        pk = [p for p in pk if query.lower() in p["name"].lower()]
    return pk


def _in_repos(name):
    return run_full(["pacman", "-Si", name], env=ENV, timeout=60)["code"] == 0


def _user_of(peer):
    uid = (peer or {}).get("uid")
    if uid in (None, 0):
        # root caller: pick the first real user for AUR builds
        for pw in pwd.getpwall():
            if 1000 <= pw.pw_uid < 60000:
                return pw.pw_name
        raise RPCError("no regular user to build AUR packages as")
    return pwd.getpwuid(uid).pw_name


def install(names, aur=True, reinstall=False, _peer=None):
    """Install packages. Repo packages via pacman; anything not in the repos via the AUR (yay)."""
    names = _names(names)
    _check_lock()
    _ensure_dbs()
    repo = [n for n in names if _in_repos(n)]
    other = [n for n in names if n not in repo]
    results = {}
    if repo:
        cmd = ["pacman", "-S", "--noconfirm"] + ([] if reinstall else ["--needed"]) + repo
        r = _stream(cmd, env=ENV, timeout=3600)
        results["repo"] = {"packages": repo, "code": r["code"], "output": clip_text(r["stdout"] + r["stderr"], 6000)}
        if r["code"] != 0:
            raise RPCError(f"pacman failed ({r['code']}): {clip_text(r['stderr'] or r['stdout'], 3000)}")
    if other:
        if not aur:
            raise RPCError(f"not in the repos: {', '.join(other)} (pass aur=true to build from the AUR)")
        if not which("yay"):
            raise RPCError("yay is not installed; cannot build AUR packages")
        user = _user_of(_peer)
        cmd = ["runuser", "-u", user, "--", "yay", "-S", "--noconfirm", "--needed", "--answerdiff", "None",
               "--answerclean", "None", "--removemake", "--sudo", "/usr/bin/arclight-asroot"] + other
        r = _stream(cmd, env={**ENV, "HOME": pwd.getpwnam(user).pw_dir}, timeout=7200)
        results["aur"] = {"packages": other, "built_as": user, "code": r["code"],
                          "output": clip_text(r["stdout"] + r["stderr"], 6000)}
        if r["code"] != 0:
            raise RPCError(f"AUR build failed ({r['code']}): {clip_text(r['stderr'] or r['stdout'], 3000)}")
    results["installed"] = {n: (run_full(["pacman", "-Q", n])["stdout"].strip() or None) for n in names}
    return results


def remove(names, recursive=True, nosave=False):
    """Remove packages (with their now-unneeded dependencies when recursive)."""
    names = _names(names)
    _check_lock()
    flags = "-R" + ("s" if recursive else "") + ("n" if nosave else "")
    r = _stream(["pacman", flags, "--noconfirm"] + names, env=ENV, timeout=1800)
    if r["code"] != 0:
        raise RPCError(f"pacman {flags} failed: {clip_text(r['stderr'] or r['stdout'], 3000)}")
    return {"removed": names, "output": clip_text(r["stdout"], 6000)}


def upgrade(aur=False, _peer=None):
    """Full system upgrade (pacman -Syu), optionally AUR packages too."""
    _check_lock()
    r = _stream(["pacman", "-Syu", "--noconfirm"], env=ENV, timeout=7200)
    res = {"code": r["code"], "output": clip_text(r["stdout"] + r["stderr"], 8000)}
    if r["code"] != 0:
        raise RPCError(f"pacman -Syu failed: {clip_text(r['stderr'] or r['stdout'], 3000)}")
    if aur and which("yay"):
        user = _user_of(_peer)
        a = _stream(["runuser", "-u", user, "--", "yay", "-Sua", "--noconfirm", "--answerdiff", "None",
                      "--answerclean", "None", "--sudo", "/usr/bin/arclight-asroot"],
                     env={**ENV, "HOME": pwd.getpwnam(user).pw_dir}, timeout=7200)
        res["aur"] = {"code": a["code"], "output": clip_text(a["stdout"] + a["stderr"], 6000)}
    return res


def refresh():
    """Refresh the package databases (pacman -Sy)."""
    _check_lock()
    return {"output": run(["pacman", "-Sy"], env=ENV, timeout=600)}


def owns(path):
    """Which package owns a file."""
    r = run_full(["pacman", "-Qo", path], env=ENV)
    if r["code"] != 0:
        return {"path": path, "owner": None, "message": (r["stderr"] or r["stdout"]).strip()}
    m = re.search(r"is owned by (\S+) (\S+)", r["stdout"])
    return {"path": path, "owner": m.group(1) if m else None, "version": m.group(2) if m else None}


def files(name):
    """Files installed by a package."""
    name = _names(name)[0]
    out = run(["pacman", "-Qlq", name], env=ENV)
    return [l for l in out.splitlines() if not l.endswith("/")]


def history(lines=60, query=None):
    """Recent package transactions from /var/log/pacman.log."""
    log = Path("/var/log/pacman.log")
    if not log.exists():
        return []
    rows = []
    for line in log.read_text(errors="replace").splitlines()[-20000:]:
        m = re.match(r"^\[([^\]]+)\] \[ALPM\] (installed|removed|upgraded|downgraded|reinstalled) (\S+) \((.*)\)$", line)
        if m and (not query or query in m.group(3)):
            rows.append({"time": m.group(1), "action": m.group(2), "name": m.group(3), "version": m.group(4)})
    return rows[-lines:]


def orphans():
    """Packages installed as dependencies that nothing needs any more."""
    return run(["pacman", "-Qtdq"], env=ENV, check=False).split()


def register(api, hooks):
    pre = hooks.get("pre_pkg")

    def wrap(fn, label):
        def inner(**kw):
            names = kw.get("names")
            _job_start(f"{label} {' '.join(names) if isinstance(names, list) else names or ''}".strip())
            try:
                snap = pre(label, kw) if pre else None
                if snap:
                    with _JOB_LOCK:
                        _JOB["snapshot"] = snap
                res = fn(**kw)
                if snap and isinstance(res, dict):
                    res["snapshot"] = snap
                return res
            finally:
                _job_end()
        inner.__doc__ = fn.__doc__
        inner.__signature__ = __import__("inspect").signature(fn)
        return inner

    api.method("pkg.search")(search)
    api.method("pkg.info")(info)
    api.method("pkg.list")(listing)
    api.method("pkg.install")(wrap(install, "install"))
    api.method("pkg.remove")(wrap(remove, "remove"))
    api.method("pkg.upgrade")(wrap(upgrade, "upgrade"))
    api.method("pkg.refresh")(refresh)
    api.method("pkg.status")(status)
    api.method("pkg.owns")(owns)
    api.method("pkg.files")(files)
    api.method("pkg.history")(history)
    api.method("pkg.orphans")(orphans)
