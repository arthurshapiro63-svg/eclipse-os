"""arclight-mcp: Arclight's machine API as MCP tools (stdio, no dependencies).

Registered for Claude Code (user scope) and Codex on first login, so every agent on the
machine can read and change settings, packages, services, logs and files (as root, no
prompts) and see and drive the whole desktop.
"""
import base64
import json
import os
import sys
import traceback

from . import __version__
from . import client as C

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """Arclight is an AI-native Arch Linux. These tools ARE the machine: use them instead of guessing shell commands.
- Root work (packages, services, /etc, any file, `run` with root=true) needs no password and never prompts.
- Settings: `settings search` finds anything (friendly keys like appearance.gaps_out, audio.volume, plus every
  Hyprland option as hypr.<section>.<option>). `settings set` applies live AND persists.
- Seeing: `screenshot` (target screen | active | window:<address or class> | monitor:NAME | region:X,Y,W,H).
  A window target captures that window even on another workspace. `see` reads text (OCR), finds text, or
  captures a motion burst for games.
- Acting, in order of preference: `ui press` (accessibility, exact, no mouse) > `see find_text` then click its
  center > click coordinates from a screenshot. When clicking from a screenshot pass shot=<id> and use the
  image's own pixel coordinates; the server converts them.
- After acting, verify with a fresh screenshot. Use `input_sequence` for timed game input (hold keys, camera).
- Every action is logged (`history`); file writes keep the previous version (`files history` / `files revert`).
- `stop` releases all keys/buttons. Arthur's panic key Super+Shift+Escape does the same.
"""


def S(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


STR, INT, NUM, BOOL = {"type": "string"}, {"type": "integer"}, {"type": "number"}, {"type": "boolean"}
ANY = {}


def d(desc, base):
    return {**base, "description": desc}


TOOLS = [
    {"name": "system_info", "description": "Overview of the machine: hostname, OS, kernel, uptime, load, memory, disks, GPU, temperatures, network, failed services, focused window.",
     "inputSchema": S({})},
    {"name": "settings", "description": "Read and change ANY setting (applies live and persists). action: search (text) | list (prefix, e.g. 'appearance', 'audio', 'hypr.decoration') | get (key) | set (key, value) | reset (key) | groups.",
     "inputSchema": S({"action": {"type": "string", "enum": ["search", "list", "get", "set", "reset", "groups"]},
                       "key": STR, "value": ANY, "text": STR, "prefix": STR}, ["action"])},
    {"name": "packages", "description": "Packages (pacman + AUR via yay, as root, no prompts). action: search (query) | info (name) | install (names) | remove (names) | upgrade | updates | list (explicit, aur, query) | owns (path) | files (name) | history | orphans | refresh.",
     "inputSchema": S({"action": {"type": "string", "enum": ["search", "info", "install", "remove", "upgrade", "updates", "list", "owns", "files", "history", "orphans", "refresh"]},
                       "query": STR, "name": STR, "names": {"type": "array", "items": STR}, "path": STR,
                       "aur": d("allow AUR (default true)", BOOL), "explicit": BOOL}, ["action"])},
    {"name": "services", "description": "systemd units (system as root, or the user's own with user=true). action: list (query, state) | status (unit) | start | stop | restart | reload | enable | disable | mask | unmask | reset-failed (unit) | daemon-reload.",
     "inputSchema": S({"action": STR, "unit": STR, "query": STR, "state": STR, "user": BOOL, "kind": d("service|timer|socket|all", STR)}, ["action"])},
    {"name": "logs", "description": "The journal. mode=query (unit, user_unit, since like '1h ago', priority 0-7 or err/warning, grep, boot 0/-1, kernel, lines) or mode=errors (failed units + error messages grouped by source + coredumps). user=true reads the user journal.",
     "inputSchema": S({"mode": {"type": "string", "enum": ["query", "errors"]}, "unit": STR, "user_unit": STR, "since": STR,
                       "until": STR, "priority": STR, "grep": STR, "boot": INT, "kernel": BOOL, "lines": INT, "user": BOOL}, [])},
    {"name": "files", "description": "Any file on the machine as root (keeps history so writes/deletes can be reverted). action: read (path) | write (path, content) | edit (path, old, new) | list (path) | stat | delete (path, recursive) | mkdir | copy (src,dst) | move (src,dst) | chmod (path, mode, owner, group) | history (path?) | revert (history_id).",
     "inputSchema": S({"action": STR, "path": STR, "content": STR, "old": STR, "new": STR, "src": STR, "dst": STR,
                       "mode": STR, "owner": STR, "group": STR, "recursive": BOOL, "history_id": STR, "offset": INT, "max_bytes": INT}, ["action"])},
    {"name": "run", "description": "Run a shell command. root=true runs it as root (no password). Returns exit code, stdout, stderr.",
     "inputSchema": S({"command": STR, "root": BOOL, "cwd": STR, "timeout": d("seconds (default 600)", INT), "input": STR}, ["command"])},
    {"name": "screenshot", "description": "See the screen. target: screen (default) | active | window:<address|class|title text> (works on other workspaces) | monitor:NAME | region:X,Y,W,H. grid=true overlays global coordinates. mark=[x,y] draws a crosshair at a global point. Returns the image plus shot id and scale: to click something you see, call input with shot=<id> and the image's pixel coordinates.",
     "inputSchema": S({"target": STR, "grid": BOOL, "max_width": INT, "cursor": BOOL, "mark": {"type": "array", "items": NUM}}, [])},
    {"name": "see", "description": "Read the screen. action: ocr (target) -> all text lines with click centers | find_text (text, target) -> matches with centers | watch (target, frames, interval_ms) -> one image of a burst of frames to see motion in games | pixel (x, y, shot) | wait_stable (target, timeout).",
     "inputSchema": S({"action": {"type": "string", "enum": ["ocr", "find_text", "watch", "pixel", "wait_stable"]}, "target": STR, "text": STR,
                       "exact": BOOL, "frames": INT, "interval_ms": INT, "x": NUM, "y": NUM, "shot": STR, "timeout": NUM}, ["action"])},
    {"name": "input", "description": "Mouse and keyboard (real virtual devices; works in every app and game). action: click (x,y,button,count,mods) | double_click | right_click | move | drag (x,y,x2,y2,duration_ms) | scroll (dy,dx,x,y) | type (text) | key (keys: 'ctrl+s', 'enter', 'super+1'; repeat) | hold (keys, ms) | down/up (key or button) | mouse_rel (dx,dy,duration_ms) for game cameras | release_all | cursor. Coordinates are global unless shot=<id> is given, then they are pixels of that screenshot.",
     "inputSchema": S({"action": STR, "x": NUM, "y": NUM, "x2": NUM, "y2": NUM, "shot": STR, "button": STR, "count": INT,
                       "mods": STR, "dx": NUM, "dy": NUM, "text": STR, "keys": STR, "key": STR, "ms": INT, "repeat": INT,
                       "duration_ms": INT, "hold_ms": INT}, ["action"])},
    {"name": "input_sequence", "description": "Timed input steps in one call (games). steps: list of objects, each one of {key:'space'} {hold:'w',ms:1200} {down:'shift'} {up:'shift'} {wait:300} {click:[x,y]} or {click:true,button:'right'} {mouse_rel:[dx,dy],ms:200} {move:[x,y]} {button_down:'left'} {button_up:'left'} {scroll:3} {type:'text'} {shot:true}. shot steps return screenshots of shot_target.",
     "inputSchema": S({"steps": {"type": "array", "items": {"type": "object"}}, "shot_target": STR}, ["steps"])},
    {"name": "windows", "description": "Windows, workspaces, monitors (Hyprland). action: list (workspace?) | active | focus (window) | close (window) | float | tile | fullscreen | maximize | pin | center | move (x,y) | resize (w,h) | to_workspace (workspace) | workspaces | switch_workspace (workspace) | monitors. window = address, class:REGEX, title:REGEX or plain text.",
     "inputSchema": S({"action": STR, "window": STR, "workspace": STR, "x": INT, "y": INT, "w": INT, "h": INT}, ["action"])},
    {"name": "ui", "description": "Accessibility tree (GTK/Qt/Electron apps): action: tree (window, interactive_only) | find (name, role) | press (name, role, index or path) -> activates the control exactly, no pixel guessing | set_text (name or path, text).",
     "inputSchema": S({"action": STR, "window": STR, "name": STR, "role": STR, "path": STR, "index": INT, "text": STR,
                       "interactive_only": BOOL}, ["action"])},
    {"name": "apps", "description": "Applications. action: list (query) | launch (name or command, workspace) -> waits for and returns the new window | running.",
     "inputSchema": S({"action": STR, "name": STR, "command": STR, "query": STR, "workspace": STR, "args": {"type": "array", "items": STR}}, ["action"])},
    {"name": "games", "description": "Games (Steam, Godot projects, desktop games). action: list | launch (game) -> waits for the game window | stop (game or window) | mode (state: on|off|toggle|status) -> Totality (Super+G, was game mode): everything but the focus window goes eclipse-dark, effects off, other apps paused, performance power profile; restored exactly when off (also automatic while a game is open). Then screenshot the window and play with input/input_sequence.",
     "inputSchema": S({"action": STR, "game": STR, "window": STR, "state": STR, "args": {"type": "array", "items": STR}}, ["action"])},
    {"name": "routines", "description": "Things the AI does by itself on a schedule (systemd user timers; a notification shows each result). Use when Arthur asks for something regularly ('every morning...'). action: list | add (name, schedule: 'daily 09:00' | 'weekdays 08:30' | 'sun 10:00' | 'every 2h' | any systemd OnCalendar, prompt: the request to run) | remove (id) | run (id, now) | enable (id) | disable (id) | log (id).",
     "inputSchema": S({"action": STR, "id": STR, "name": STR, "schedule": STR, "prompt": STR}, ["action"])},
    {"name": "wait", "description": "Wait for something: for=window (match regex) | text (text on screen, OCR) | stable (screen stops changing). timeout seconds.",
     "inputSchema": S({"for": {"type": "string", "enum": ["window", "text", "stable"]}, "match": STR, "text": STR, "target": STR, "timeout": NUM}, ["for"])},
    {"name": "clipboard", "description": "action: get | set (text).", "inputSchema": S({"action": STR, "text": STR}, ["action"])},
    {"name": "notify", "description": "Send Arthur a desktop notification.", "inputSchema": S({"title": STR, "body": STR, "urgency": STR}, ["title"])},
    {"name": "snapshots", "description": "btrfs system snapshots (whole-disk installs): action list | create (label) | rollback (id) | delete (id). Package changes snapshot automatically.",
     "inputSchema": S({"action": STR, "label": STR, "id": STR}, ["action"])},
    {"name": "history", "description": "What has been done: kind=actions (every API call: who/what/result; filter agent) | events (service failures, package transactions) | packages (pacman log).",
     "inputSchema": S({"kind": STR, "n": INT, "agent": STR}, [])},
    {"name": "machine", "description": "Machine-level config as root: action hostname (name?) | timezone (tz?, ntp?) | locale (lang?, keymap?) | cmdline (add?, remove?) -> kernel parameters | sysctl (key?, value?) | users | user_add (name, admin) | user_mod | power (reboot|poweroff|suspend).",
     "inputSchema": S({"action": STR, "name": STR, "tz": STR, "ntp": BOOL, "lang": STR, "keymap": STR, "add": STR, "remove": STR,
                       "key": STR, "value": STR, "admin": BOOL, "add_groups": {"type": "array", "items": STR}, "power": STR}, ["action"])},
    {"name": "hyprland", "description": "Raw compositor access: action dispatch (expr, a Lua dispatcher like 'hl.dsp.focus({ workspace = 2 })') | eval (code, Lua, not persisted) | query (what: clients|monitors|workspaces|layers|devices|version|...) | binds (query).",
     "inputSchema": S({"action": STR, "expr": STR, "code": STR, "what": STR, "query": STR}, ["action"])},
    {"name": "stop", "description": "Release every held key and mouse button and cancel running input sequences.", "inputSchema": S({})},
]


def pick(a, *keys):
    return {k: a[k] for k in keys if k in a and a[k] is not None}


def image_block(path, max_bytes=None):
    data = open(path, "rb").read()
    mime = "image/jpeg" if path.endswith((".jpg", ".jpeg")) else "image/png"
    return {"type": "image", "data": base64.b64encode(data).decode(), "mimeType": mime}


def handle_tool(name, a):
    call = C.call
    act = a.get("action")
    if name == "system_info":
        info = call("sys.info")
        try:
            info["focused_window"] = call("win.active")
        except Exception as e:
            info["focused_window"] = f"(session unavailable: {e})"
        return info
    if name == "settings":
        m = {"search": ("settings.search", ("text",)), "list": ("settings.list", ("prefix",)),
             "get": ("settings.get", ("key",)), "set": ("settings.set", ("key", "value")),
             "reset": ("settings.reset", ("key",)), "groups": ("settings.groups", ())}[act]
        p = pick(a, *m[1])
        if act == "search" and "text" not in p:
            p["text"] = a.get("key") or a.get("prefix") or ""
        return call(m[0], **p)
    if name == "packages":
        if act == "search":
            return call("pkg.search", query=a.get("query") or a.get("name"), aur=a.get("aur", True))
        if act == "info":
            return call("pkg.info", name=a.get("name") or (a.get("names") or [None])[0])
        if act == "install":
            return call("pkg.install", names=a.get("names") or [a["name"]], aur=a.get("aur", True))
        if act == "remove":
            return call("pkg.remove", names=a.get("names") or [a["name"]])
        if act == "upgrade":
            return call("pkg.upgrade", aur=a.get("aur", False))
        if act == "updates":
            return call("pkg.list", upgradable=True)
        if act == "list":
            return call("pkg.list", explicit=a.get("explicit", False), foreign=bool(a.get("aur")) and a.get("aur") is True,
                        query=a.get("query"))
        if act == "owns":
            return call("pkg.owns", path=a["path"])
        if act == "files":
            return call("pkg.files", name=a["name"])
        if act == "history":
            return call("pkg.history")
        if act == "orphans":
            return call("pkg.orphans")
        if act == "refresh":
            return call("pkg.refresh")
    if name == "services":
        user = bool(a.get("user"))
        if act == "list":
            return C.call("svc.list", _user=user, **pick(a, "query", "state", "kind"))
        if act == "status":
            return C.call("svc.status", _user=user, unit=a["unit"])
        if act == "daemon-reload":
            return C.call("svc.daemon_reload", _user=user)
        return C.call("svc.action", _user=user, unit=a["unit"], action=act)
    if name == "logs":
        user = bool(a.get("user"))
        if a.get("mode") == "errors":
            return C.call("log.errors", _user=user)
        p = pick(a, "unit", "user_unit", "since", "until", "priority", "grep", "boot", "kernel", "lines")
        p.setdefault("lines", 150)
        return C.call("log.query", _user=user, **p)
    if name == "files":
        m = {"read": ("file.read", ("path", "offset", "max_bytes")), "write": ("file.write", ("path", "content", "mode", "owner", "group")),
             "edit": ("file.edit", ("path", "old", "new")), "list": ("file.list", ("path",)), "stat": ("file.stat", ("path",)),
             "delete": ("file.delete", ("path", "recursive")), "mkdir": ("file.mkdir", ("path", "mode", "owner", "group")),
             "copy": ("file.copy", ("src", "dst")), "move": ("file.move", ("src", "dst")),
             "chmod": ("file.chmod", ("path", "mode", "owner", "group")), "history": ("file.history", ("path",)),
             "revert": ("file.revert", ("history_id",))}[act]
        return call(m[0], **pick(a, *m[1]))
    if name == "run":
        if a.get("root"):
            return call("exec", cmd=a["command"], cwd=a.get("cwd"), timeout=a.get("timeout", 600), input=a.get("input"))
        from .util import run_full
        return run_full(a["command"], timeout=int(a.get("timeout", 600)), cwd=a.get("cwd"), input=a.get("input"))
    if name == "screenshot":
        r = call("screen.shot", **pick(a, "target", "grid", "max_width", "cursor", "mark"))
        return {"_image": r["path"], **{k: r[k] for k in r if k != "path"}}
    if name == "see":
        if act == "ocr":
            r = call("screen.ocr", **pick(a, "target"))
            return {"lines": [{"text": l["text"], "center": l["center"], "box": l["box"]} for l in r["lines"]],
                    **{k: v for k, v in r.items() if k != "lines"}}
        if act == "find_text":
            return call("screen.find_text", **pick(a, "text", "target", "exact"))
        if act == "watch":
            r = call("screen.watch", **pick(a, "target", "frames", "interval_ms"))
            return {"_image": r["path"], **{k: r[k] for k in r if k != "path"}}
        if act == "pixel":
            return call("screen.pixel", **pick(a, "x", "y", "shot"))
        if act == "wait_stable":
            return call("screen.wait_stable", **pick(a, "target", "timeout"))
    if name == "input":
        xy = pick(a, "x", "y", "shot")
        if act in ("click", "double_click", "right_click"):
            p = {**xy, **pick(a, "button", "count", "mods", "hold_ms")}
            if act == "double_click":
                p["count"] = 2
            if act == "right_click":
                p["button"] = "right"
            return call("input.click", **p)
        if act == "move":
            return call("input.move", **xy)
        if act == "drag":
            return call("input.drag", x1=a["x"], y1=a["y"], x2=a["x2"], y2=a["y2"], **pick(a, "shot", "button", "duration_ms", "mods"))
        if act == "scroll":
            return call("input.scroll", **{**xy, **pick(a, "dx", "dy")})
        if act == "type":
            return call("input.type", text=a["text"])
        if act == "key":
            return call("input.key", keys=a.get("keys") or a.get("key"), **pick(a, "repeat", "hold_ms"))
        if act == "hold":
            return call("input.hold", keys=a.get("keys") or a.get("key"), ms=a.get("ms", 500))
        if act == "down":
            return call("input.down", key=a.get("key") or a.get("keys"), button=a.get("button"))
        if act == "up":
            return call("input.up", key=a.get("key") or a.get("keys"), button=a.get("button"))
        if act == "mouse_rel":
            return call("input.mouse_rel", dx=a.get("dx", 0), dy=a.get("dy", 0), duration_ms=a.get("duration_ms", 0))
        if act == "release_all":
            return call("input.release_all")
        if act == "cursor":
            return call("input.cursor")
    if name == "input_sequence":
        r = call("input.sequence", steps=a["steps"], shot_target=a.get("shot_target"))
        imgs = [s["shot"]["path"] for s in r if "shot" in s]
        return {"_images": imgs, "steps": [{k: v for k, v in s.items() if k != "shot"} | ({"shot": s["shot"]["shot"]} if "shot" in s else {}) for s in r]}
    if name == "windows":
        if act == "list":
            return call("win.list", **pick(a, "workspace"))
        if act == "active":
            return call("win.active")
        if act == "focus":
            return call("win.focus", window=a["window"])
        if act == "close":
            return call("win.close", window=a.get("window", "active"))
        if act == "workspaces":
            return call("ws.list")
        if act == "switch_workspace":
            return call("ws.switch", workspace=a["workspace"])
        if act == "monitors":
            return call("mon.list")
        return call("win.action", action=act, **pick(a, "window", "x", "y", "w", "h", "workspace"))
    if name == "ui":
        if act == "tree":
            return call("ui.tree", **pick(a, "window", "interactive_only"))
        if act == "find":
            return call("ui.find", **pick(a, "name", "role", "window"))
        if act == "press":
            return call("ui.press", **pick(a, "name", "role", "path", "window", "index"))
        if act == "set_text":
            return call("ui.set_text", **pick(a, "text", "name", "path", "window"))
    if name == "apps":
        if act == "list":
            return call("app.list", **pick(a, "query"))
        if act == "launch":
            return call("app.launch", **pick(a, "name", "command", "workspace", "args"))
        if act == "running":
            return call("app.running")
    if name == "games":
        if act == "list":
            return call("game.list")
        if act == "launch":
            return call("game.launch", **pick(a, "game", "args"))
        if act == "stop":
            return call("game.stop", **pick(a, "game", "window"))
        if act == "mode":
            return call("totality.mode", action=a.get("state") or "toggle")
    if name == "routines":
        from . import routines as RT
        try:
            if act == "list":
                return RT.listing()
            if act == "add":
                return RT.add(a["name"], a["schedule"], a["prompt"])
            if act == "remove":
                return RT.remove(a["id"])
            if act in ("enable", "disable"):
                return RT.set_enabled(a["id"], act == "enable")
            if act == "run":
                return RT.run(a["id"])
            if act == "log":
                logs = sorted((RT.LOGS / a["id"]).glob("*.log"))
                return logs[-1].read_text()[-8000:] if logs else "no runs yet"
        except RT.RoutineError as e:
            return {"error": str(e)}
    if name == "wait":
        f = a.get("for")
        if f == "window":
            return call("wait.window", match=a.get("match"), timeout=a.get("timeout", 20))
        if f == "text":
            return call("wait.text", text=a.get("text"), target=a.get("target", "screen"), timeout=a.get("timeout", 20))
        return call("screen.wait_stable", target=a.get("target", "screen"), timeout=a.get("timeout", 10))
    if name == "clipboard":
        return call("clip.get") if act == "get" else call("clip.set", text=a.get("text", ""))
    if name == "notify":
        return call("notify.send", **pick(a, "title", "body", "urgency"))
    if name == "snapshots":
        if act == "list":
            return call("snap.list")
        if act == "create":
            return call("snap.create", label=a.get("label", "manual"))
        if act == "rollback":
            return call("snap.rollback", id=a["id"])
        if act == "delete":
            return call("snap.delete", id=a["id"])
    if name == "history":
        k = a.get("kind", "actions")
        if k == "events":
            return call("events.tail", n=a.get("n", 50))
        if k == "packages":
            return call("pkg.history", lines=a.get("n", 60))
        return call("actions.tail", n=a.get("n", 50), agent=a.get("agent"))
    if name == "machine":
        if act == "hostname":
            return call("sys.hostname", **pick(a, "name"))
        if act == "timezone":
            return call("sys.timezone", **pick(a, "tz", "ntp"))
        if act == "locale":
            return call("sys.locale", **pick(a, "lang", "keymap"))
        if act == "cmdline":
            return call("sys.cmdline", **pick(a, "add", "remove"))
        if act == "sysctl":
            return call("sys.sysctl", **pick(a, "key", "value"))
        if act == "users":
            return call("sys.users")
        if act == "user_add":
            return call("sys.user_add", **pick(a, "name", "admin"))
        if act == "user_mod":
            return call("sys.user_mod", **pick(a, "name", "add_groups"))
        if act == "power":
            return call("sys.power", action=a.get("power") or a.get("name"))
    if name == "hyprland":
        if act == "dispatch":
            return call("hypr.dispatch", expr=a["expr"])
        if act == "eval":
            return call("hypr.eval", code=a["code"])
        if act == "query":
            return call("hypr.query", what=a["what"])
        if act == "binds":
            return call("binds.list", **pick(a, "query"))
    if name == "stop":
        return call("stop")
    raise ValueError(f"unknown tool/action: {name} {act or ''}")


def tool_result(name, args):
    try:
        res = handle_tool(name, args or {})
    except C.RemoteError as e:
        return {"content": [{"type": "text", "text": f"Error: {e.message}"}], "isError": True}
    except C.Unavailable as e:
        return {"content": [{"type": "text", "text": f"Unavailable: {e}"}], "isError": True}
    except KeyError as e:
        return {"content": [{"type": "text", "text": f"Missing argument {e} for {name}"}], "isError": True}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    content = []
    if isinstance(res, dict):
        imgs = ([res.pop("_image")] if "_image" in res else []) + res.pop("_images", [])
        for p in imgs:
            content.append(image_block(p))
    text = json.dumps(res, ensure_ascii=False, default=str)
    if len(text) > 60000:
        text = text[:60000] + f"... [truncated {len(text) - 60000} chars]"
    content.insert(0, {"type": "text", "text": text})
    return {"content": content, "isError": False}


def main():
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:  # notification
            continue
        try:
            if method == "initialize":
                want = (msg.get("params") or {}).get("protocolVersion")
                result = {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[1],
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "arclight", "version": __version__},
                          "instructions": INSTRUCTIONS}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                p = msg.get("params") or {}
                result = tool_result(p.get("name"), p.get("arguments") or {})
            elif method == "ping":
                result = {}
            elif method in ("resources/list", "prompts/list"):
                result = {method.split("/")[0]: []}
            else:
                out.write(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}) + "\n")
                out.flush()
                continue
            out.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}, ensure_ascii=False) + "\n")
        except Exception as e:
            out.write(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e),
                                                                          "data": traceback.format_exc()[-1500:]}}) + "\n")
        out.flush()
    return 0
