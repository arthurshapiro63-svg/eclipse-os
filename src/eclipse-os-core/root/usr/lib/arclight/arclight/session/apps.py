"""Apps and games: desktop entries, launching through the compositor, a games catalog."""
import glob
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

from ..rpc import RPCError
from . import hypr

HOME = Path.home()


def _data_dirs():
    dirs = [Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share"))]
    dirs += [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
    dirs += [Path("/var/lib/flatpak/exports/share"), HOME / ".local/share/flatpak/exports/share"]
    return dirs


def _parse_desktop(path):
    entry, section = {}, None
    try:
        for line in Path(path).read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line
                continue
            if section != "[Desktop Entry]" or "=" not in line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            if "[" in k:  # localized key
                continue
            entry[k.strip()] = v.strip()
    except OSError:
        return None
    return entry


def entries():
    seen = {}
    for d in _data_dirs():
        for f in sorted(glob.glob(str(d / "applications" / "**" / "*.desktop"), recursive=True)):
            did = os.path.relpath(f, d / "applications").replace("/", "-")
            if did in seen:
                continue
            e = _parse_desktop(f)
            if not e or e.get("Type", "Application") != "Application":
                continue
            seen[did] = {"id": did[:-8], "name": e.get("Name", did), "exec": e.get("Exec", ""),
                         "comment": e.get("Comment", ""), "categories": [c for c in e.get("Categories", "").split(";") if c],
                         "keywords": e.get("Keywords", ""), "icon": e.get("Icon"), "terminal": e.get("Terminal") == "true",
                         "hidden": e.get("NoDisplay") == "true" or e.get("Hidden") == "true", "file": f,
                         "wm_class": e.get("StartupWMClass")}
    return list(seen.values())


def app_list(query=None, include_hidden=False):
    """Installed applications (desktop entries), optionally filtered."""
    es = [e for e in entries() if include_hidden or not e["hidden"]]
    if query:
        q = query.lower()
        es = [e for e in es if q in e["name"].lower() or q in e["id"].lower() or q in e["keywords"].lower()
              or q in e["comment"].lower()]
    return sorted(({k: e[k] for k in ("id", "name", "comment", "categories", "wm_class", "icon")} for e in es),
                  key=lambda e: e["name"].lower())


def _clean_exec(ex):
    ex = re.sub(r"%[fFuUdDnNickvm]", "", ex)
    return re.sub(r"\s+", " ", ex).strip()


def _resolve_app(name):
    es = entries()
    q = name.lower()
    for test in (lambda e: e["id"].lower() == q, lambda e: e["name"].lower() == q,
                 lambda e: e["id"].lower().endswith("." + q), lambda e: q in e["name"].lower(),
                 lambda e: q in e["id"].lower(), lambda e: q in e["keywords"].lower()):
        hits = [e for e in es if test(e) and not e["hidden"]] or [e for e in es if test(e)]
        if hits:
            return hits[0]
    return None


def wait_window(before, timeout=20, match=None, pid=None):
    """Wait for a new window to map (optionally matching class/title regex)."""
    t0 = time.monotonic()
    rx = re.compile(match, re.I) if match else None
    while time.monotonic() - t0 < timeout:
        for c in hypr.clients():
            if c["address"] in before or not c.get("mapped", True):
                continue
            if rx and not (rx.search(c.get("class") or "") or rx.search(c.get("title") or "")):
                continue
            return hypr.summarize(c)
        time.sleep(0.2)
    return None


def launch(name=None, command=None, workspace=None, silent=True, wait=True, timeout=20, args=None):
    """Launch an app by name/desktop id, or run `command`. Waits for its window and returns it."""
    before = {c["address"] for c in hypr.clients()}
    match = None
    if command:
        cmd = command
    else:
        if not name:
            raise RPCError("give an app name or a command")
        e = _resolve_app(name)
        if not e:
            if shutil.which(name):
                cmd = name
            else:
                raise RPCError(f"no app called {name!r}; try app list")
        else:
            cmd = _clean_exec(e["exec"])
            if e["terminal"]:
                cmd = f"{os.environ.get('TERMINAL', 'ghostty')} -e {cmd}"
            match = re.escape(e["wm_class"]) if e.get("wm_class") else None
    if args:
        cmd += " " + " ".join(shlex.quote(a) for a in args)
    hypr.exec_cmd(cmd, workspace=workspace, silent=silent)
    res = {"launched": cmd}
    if wait:
        w = wait_window(before, timeout=timeout, match=match) or (wait_window(before, timeout=3) if match else None)
        res["window"] = w
        if not w:
            res["note"] = f"no new window within {timeout}s (it may still be loading, or it reused an existing window)"
    return res


def running():
    """Open windows grouped by app."""
    out = {}
    for c in hypr.clients():
        out.setdefault(c.get("class") or "?", []).append(hypr.summarize(c))
    return out


# ---------------------------------------------------------------- games

def _steam_root():
    for p in (HOME / ".local/share/Steam", HOME / ".steam/steam"):
        if (p / "steamapps").exists():
            return p
    return None


def games():
    """Every game Arclight knows how to launch: Steam, Godot projects, desktop entries in the Game category."""
    out = []
    root = _steam_root()
    if root:
        libs = [str(root)]
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.exists():
            libs = re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="replace")) or libs
        for lib in libs:
            for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
                t = Path(acf).read_text(errors="replace")
                get = lambda k: (re.search(rf'"{k}"\s+"([^"]*)"', t) or [None, None])[1]
                name = get("name") or "?"
                if re.search(r"(Proton|Steam Linux Runtime|Steamworks Common)", name):
                    continue
                out.append({"id": f"steam:{get('appid')}", "name": name, "source": "steam",
                            "window_class": f"steam_app_{get('appid')}"})
    godot = shutil.which("godot") or (str(HOME / ".local/bin/godot") if (HOME / ".local/bin/godot").exists() else None)
    for proj in sorted(glob.glob(str(HOME / "Projects/*/project.godot"))):
        d = Path(proj).parent
        m = re.search(r'config/name="([^"]+)"', Path(proj).read_text(errors="replace"))
        out.append({"id": f"godot:{d.name}", "name": m.group(1) if m else d.name, "source": "godot",
                    "path": str(d), "runnable": bool(godot)})
    for e in entries():
        if "Game" in e["categories"] and not e["hidden"] and "steam://" not in e["exec"]:
            out.append({"id": f"app:{e['id']}", "name": e["name"], "source": "desktop", "window_class": e.get("wm_class")})
    return out


def _game(game):
    gs = games()
    q = str(game).lower()
    for test in (lambda g: g["id"].lower() == q, lambda g: g["name"].lower() == q, lambda g: q in g["name"].lower(),
                 lambda g: q in g["id"].lower()):
        hits = [g for g in gs if test(g)]
        if hits:
            return hits[0]
    raise RPCError(f"no game matches {game!r}; known: {', '.join(g['name'] for g in gs[:40])}")


def game_launch(game, workspace=None, timeout=90, args=None):
    """Launch a game and wait for its window. Returns the window so you can screenshot and play it."""
    g = _game(game)
    before = {c["address"] for c in hypr.clients()}
    if g["source"] == "steam":
        appid = g["id"].split(":", 1)[1]
        hypr.exec_cmd(f"steam steam://rungameid/{appid}", workspace=workspace, silent=False)
        w = wait_window(before, timeout=timeout, match=f"^steam_app_{appid}$")
    elif g["source"] == "godot":
        godot = shutil.which("godot") or str(HOME / ".local/bin/godot")
        cmd = f"{shlex.quote(godot)} --path {shlex.quote(g['path'])}"
        if args:
            cmd += " " + " ".join(shlex.quote(a) for a in args)
        hypr.exec_cmd(cmd, workspace=workspace, silent=False)
        w = wait_window(before, timeout=timeout)
    else:
        r = launch(name=g["id"].split(":", 1)[1], workspace=workspace, silent=False, timeout=timeout, args=args)
        w = r.get("window")
    return {"game": g, "window": w, "next": "screenshot target='window:<address>' then use input to play"}


def game_stop(game=None, window=None):
    """Close a running game (by game name or window selector)."""
    if window is None:
        g = _game(game)
        cls = g.get("window_class")
        if not cls:
            raise RPCError("give the game's window selector")
        window = f"class:^{re.escape(cls)}$"
    c = hypr.find_window(window)
    hypr.close_window(c)
    time.sleep(2)
    still = [x for x in hypr.clients() if x["address"] == c["address"]]
    if still and c.get("pid"):
        os.kill(c["pid"], signal.SIGTERM)
    return {"stopped": hypr.summarize(c)}
