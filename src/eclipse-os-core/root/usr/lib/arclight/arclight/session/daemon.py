"""arclight-session: the AI's eyes and hands inside the Hyprland session (runs as the user).

Socket: $XDG_RUNTIME_DIR/arclight/session.sock
Areas:  screen.* input.* win.* ws.* mon.* app.* game.* totality.* ui.* clip.* notify.* settings.*
        svc.* / log.* for --user units, wait.*, stop
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from .. import __version__
from .. import identity
from ..rpc import API, RPCError, serve
from ..util import session_sock, run, run_full
from ..settings.registry import Registry
from ..system import svc as svcmod
from . import hypr, screen, atspi, apps
from . import uinput as ui_mod

_input = None
_input_lock = threading.Lock()
_cancel = threading.Event()
_last_banner = [0.0]
_registry = None


def registry():
    global _registry
    if _registry is None:
        _registry = Registry()
    return _registry


def vin():
    global _input
    with _input_lock:
        if _input is None:
            try:
                _input = ui_mod.VirtualInput()
            except PermissionError:
                raise RPCError("no write access to /dev/uinput (Arclight grants it to the 'arclight' group; "
                               "log out and back in after being added)")
            except FileNotFoundError:
                raise RPCError("/dev/uinput is missing (modprobe uinput)")
        return _input


def banner(what):
    """Small 'AI is driving' notice, at most every 20 s (setting ai.indicator)."""
    try:
        if not registry().store.get("ai.indicator", True):
            return
    except Exception:
        pass
    now = time.monotonic()
    if now - _last_banner[0] > 20:
        _last_banner[0] = now
        hypr.notify(f"{identity.short_name()} AI is using the {what}  (Super+Shift+Esc stops it)", ms=3500)


def _xy(x, y, shot):
    if x is None or y is None:
        return None
    gx, gy = screen.to_global(x, y, shot)
    return int(round(gx)), int(round(gy))


def _move(gx, gy):
    hypr.move_cursor(gx, gy)
    v = vin()
    v.rel(1, 0)  # a real motion event so the app under the cursor sees hover/enter
    time.sleep(0.01)
    v.rel(-1, 0)
    time.sleep(0.03)


# what the session log keeps: changes and hands-on actions (not screenshots, reads or mouse moves)
LOGGED = re.compile(r"^(settings\.(set|reset)|app\.(launch|close)|win\.(?!list|get|find)|"
                    r"input\.(click|type|key|drag|hold|paste)|ui\.(press|set|type)|hypr\.dispatch|ws\.(go|move))")


def build_api():
    api = API("arclight-session")
    from pathlib import Path
    from ..system.daemon import make_logger, tail_jsonl
    actions_log = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "arclight/actions.jsonl"
    try:
        _log = make_logger(actions_log)
    except OSError:  # e.g. an unwritable ~/.local/state: keep the eyes and hands working, log to the runtime dir
        actions_log = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "arclight" / "actions.jsonl"
        _log = make_logger(actions_log)

    def on_call(method, params, peer, result, err, seconds):
        if LOGGED.match(method):
            _log(method, params, peer, result, err, seconds)
    api.on_call = on_call

    @api.method("session.actions")
    def session_actions(n=50, agent=None, method=None):
        """The most recent desktop actions (settings changes, clicks, typing, app launches): who, what, result."""
        return tail_jsonl(actions_log, int(n), agent=agent, method=method)

    # ------------------------------------------------------------ screen
    @api.method("screen.shot")
    def screen_shot(target="screen", max_width=1568, grid=False, cursor=False, format="png", mark=None):
        """Screenshot. target: screen | active | monitor:NAME | window:SELECTOR | region:X,Y,W,H.
        A window target works even when the window is on another workspace. Returns the file path and
        the shot id/scale: pass shot=<id> to input calls to click in this image's pixels."""
        return screen.shot(target, max_width=max_width, grid=grid, cursor=cursor, fmt=format, mark=mark)

    @api.method("screen.ocr")
    def screen_ocr(target="screen", min_conf=40):
        """Read all text on screen with positions (global coordinates)."""
        return screen.ocr(target, min_conf=min_conf)

    @api.method("screen.find_text")
    def screen_find_text(text, target="screen", exact=False):
        """Find text on screen; returns click-ready centers."""
        return screen.find_text(text, target, exact=exact)

    @api.method("screen.watch")
    def screen_watch(target="screen", frames=6, interval_ms=500, max_width=1568):
        """Burst of frames tiled into one image, to see motion/animation (games)."""
        return screen.watch(target, frames=frames, interval_ms=interval_ms, max_width=max_width)

    @api.method("screen.pixel")
    def screen_pixel(x, y, shot=None):
        """Colour at a point."""
        gx, gy = _xy(x, y, shot)
        return screen.pixel(gx, gy)

    @api.method("screen.wait_stable")
    def screen_wait_stable(target="screen", timeout=10):
        """Wait until the screen stops changing."""
        return screen.wait_stable(target, timeout=float(timeout))

    # ------------------------------------------------------------ input
    @api.method("input.move")
    def input_move(x, y, shot=None):
        """Move the pointer to (x, y): global coords, or image pixels of `shot`."""
        banner("mouse")
        gx, gy = _xy(x, y, shot)
        _move(gx, gy)
        return {"cursor": list(hypr.cursor_pos())}

    @api.method("input.click")
    def input_click(x=None, y=None, shot=None, button="left", count=1, mods=None, hold_ms=None):
        """Click (optionally at x,y). button: left|right|middle|back|forward. count=2 double-clicks.
        mods: 'ctrl+shift' held during the click."""
        banner("mouse")
        v = vin()
        p = _xy(x, y, shot)
        if p:
            _move(*p)
        mod_codes = ui_mod.parse_chord(mods) if mods else []
        for c in mod_codes:
            v.key(c, True)
        try:
            if hold_ms:
                v.button(button, True)
                time.sleep(float(hold_ms) / 1000)
                v.button(button, False)
            else:
                v.click(button, int(count))
        finally:
            for c in reversed(mod_codes):
                v.key(c, False)
        return {"clicked": button, "count": count, "at": list(hypr.cursor_pos())}

    @api.method("input.drag")
    def input_drag(x1, y1, x2, y2, shot=None, button="left", duration_ms=500, mods=None):
        """Press at (x1,y1), move to (x2,y2) over duration_ms, release."""
        banner("mouse")
        v = vin()
        a, b = _xy(x1, y1, shot), _xy(x2, y2, shot)
        mod_codes = ui_mod.parse_chord(mods) if mods else []
        _move(*a)
        for c in mod_codes:
            v.key(c, True)
        v.button(button, True)
        time.sleep(0.06)
        steps = max(6, int(duration_ms / 16))
        try:
            for i in range(1, steps + 1):
                if _cancel.is_set():
                    break
                x = a[0] + (b[0] - a[0]) * i / steps
                y = a[1] + (b[1] - a[1]) * i / steps
                hypr.move_cursor(x, y)
                time.sleep(duration_ms / 1000 / steps)
            v.rel(1, 0); v.rel(-1, 0)
            time.sleep(0.05)
        finally:
            v.button(button, False)
            for c in reversed(mod_codes):
                v.key(c, False)
        return {"dragged": [a, b]}

    @api.method("input.scroll")
    def input_scroll(dy=3, dx=0, x=None, y=None, shot=None):
        """Scroll by notches (dy > 0 = down, dx > 0 = right), optionally at a position first."""
        banner("mouse")
        p = _xy(x, y, shot)
        if p:
            _move(*p)
        vin().wheel(dy=int(dy), dx=int(dx))
        return {"scrolled": [dx, dy]}

    @api.method("input.type")
    def input_type(text, delay_ms=12):
        """Type text into the focused window (US keymap; other characters go through wtype)."""
        banner("keyboard")
        v = vin()
        buf = ""
        for ch in text:
            if ch in ui_mod.CHARS or ch == "\r":
                buf += ch
                continue
            if buf:
                v.type_ascii(buf, delay_ms=delay_ms)
                buf = ""
            if shutil.which("wtype"):
                subprocess.run(["wtype", ch], timeout=5)
        if buf:
            v.type_ascii(buf, delay_ms=delay_ms)
        return {"typed": len(text)}

    @api.method("input.key")
    def input_key(keys, repeat=1, hold_ms=30):
        """Press a key or chord, e.g. 'enter', 'ctrl+s', 'super+shift+q', 'alt+f4'. Also a list of chords."""
        banner("keyboard")
        v = vin()
        chords = keys if isinstance(keys, list) else [keys]
        for _ in range(int(repeat)):
            for ch in chords:
                v.tap(ui_mod.parse_chord(ch), hold_ms=int(hold_ms))
                time.sleep(0.03)
        return {"pressed": chords, "repeat": repeat}

    @api.method("input.hold")
    def input_hold(keys, ms=500):
        """Hold keys down for ms (e.g. 'w' for 1500 to walk forward in a game)."""
        banner("keyboard")
        v = vin()
        codes = ui_mod.parse_chord(keys)
        for c in codes:
            v.key(c, True)
        t0 = time.monotonic()
        try:
            while time.monotonic() - t0 < float(ms) / 1000 and not _cancel.is_set():
                time.sleep(0.01)
        finally:
            for c in reversed(codes):
                v.key(c, False)
        return {"held": keys, "ms": ms}

    @api.method("input.down")
    def input_down(key=None, button=None):
        """Press and keep holding a key or mouse button (release with input.up or input.release_all)."""
        v = vin()
        if button:
            v.button(button, True)
        for c in ui_mod.parse_chord(key) if key else []:
            v.key(c, True)
        return {"down": key or button}

    @api.method("input.up")
    def input_up(key=None, button=None):
        """Release a key or mouse button."""
        v = vin()
        if button:
            v.button(button, False)
        for c in reversed(ui_mod.parse_chord(key) if key else []):
            v.key(c, False)
        return {"up": key or button}

    @api.method("input.mouse_rel")
    def input_mouse_rel(dx, dy, duration_ms=0):
        """Relative mouse motion (game cameras / pointer-locked apps)."""
        banner("mouse")
        vin().rel_smooth(int(dx), int(dy), duration_ms=int(duration_ms))
        return {"moved": [dx, dy]}

    @api.method("input.release_all")
    def input_release_all():
        """Release every held key and button."""
        _cancel.set()
        time.sleep(0.05)
        if _input:
            _input.release_all()
        _cancel.clear()
        return {"released": True}

    @api.method("input.cursor")
    def input_cursor():
        """Current pointer position (global)."""
        return {"cursor": list(hypr.cursor_pos())}

    @api.method("input.sequence")
    def input_sequence(steps, shot_target=None):
        """Run timed steps in one go (for games). Each step is an object with one action:
        {"key": "space"} {"hold": "w", "ms": 1200} {"down": "shift"} {"up": "shift"} {"wait": 300}
        {"click": [x, y]} or {"click": true} {"button": "right"} {"mouse_rel": [dx, dy], "ms": 200}
        {"move": [x, y]} {"scroll": 3} {"type": "text"} {"shot": true} (screenshot of shot_target)."""
        banner("mouse and keyboard")
        v = vin()
        _cancel.clear()
        out = []
        for i, st in enumerate(steps):
            if _cancel.is_set():
                out.append({"step": i, "cancelled": True})
                break
            try:
                if "wait" in st:
                    time.sleep(float(st["wait"]) / 1000)
                elif "key" in st:
                    v.tap(ui_mod.parse_chord(st["key"]), hold_ms=int(st.get("ms", 30)))
                elif "hold" in st:
                    input_hold(st["hold"], st.get("ms", 500))
                elif "down" in st:
                    for c in ui_mod.parse_chord(st["down"]):
                        v.key(c, True)
                elif "up" in st:
                    for c in reversed(ui_mod.parse_chord(st["up"])):
                        v.key(c, False)
                elif "mouse_rel" in st:
                    dx, dy = st["mouse_rel"]
                    v.rel_smooth(int(dx), int(dy), duration_ms=int(st.get("ms", 0)))
                elif "move" in st:
                    _move(*_xy(st["move"][0], st["move"][1], st.get("shot_id")))
                elif "click" in st:
                    if isinstance(st["click"], list):
                        _move(*_xy(st["click"][0], st["click"][1], st.get("shot_id")))
                    v.click(st.get("button", "left"), int(st.get("count", 1)))
                elif "button_down" in st:
                    v.button(st["button_down"], True)
                elif "button_up" in st:
                    v.button(st["button_up"], False)
                elif "scroll" in st:
                    v.wheel(dy=int(st["scroll"]))
                elif "type" in st:
                    v.type_ascii(str(st["type"]))
                elif "shot" in st:
                    out.append({"step": i, "shot": screen.shot(shot_target or "screen", max_width=st.get("max_width", 1024))})
                    continue
                else:
                    raise RPCError(f"unknown step {st}")
                out.append({"step": i, "ok": True})
            except Exception as e:
                v.release_all()
                out.append({"step": i, "error": str(e)})
                break
        v.release_all()
        return out

    # ------------------------------------------------------------ windows / workspaces / monitors
    @api.method("win.list")
    def win_list(workspace=None):
        """Open windows (address, class, title, workspace, geometry, focus)."""
        ws = [hypr.summarize(c) for c in hypr.clients()]
        if workspace is not None:
            ws = [w for w in ws if str(w["workspace"]) == str(workspace)]
        return sorted(ws, key=lambda w: (str(w["workspace"]), w["class"] or ""))

    @api.method("win.active")
    def win_active():
        """The focused window."""
        c = hypr.active_window()
        return hypr.summarize(c) if c else None

    @api.method("win.focus")
    def win_focus(window):
        """Focus a window (switches to its workspace). window: address, class:RE, title:RE, or text."""
        c = hypr.find_window(window)
        hypr.focus_window(c)
        time.sleep(0.15)
        return hypr.summarize(hypr.find_window(c["address"]))

    @api.method("win.close")
    def win_close(window="active"):
        """Close a window (politely, like clicking its X)."""
        c = hypr.find_window(window)
        hypr.close_window(c)
        return {"closed": hypr.summarize(c)}

    @api.method("win.action")
    def win_action(action, window="active", x=None, y=None, w=None, h=None, workspace=None):
        """float | tile | fullscreen | maximize | pin | center | move (x,y) | resize (w,h) | to_workspace (workspace)."""
        c = hypr.find_window(window)
        sel = hypr.lua_str(hypr.sel(c))
        L = {
            "float": f"hl.dsp.window.float({{ action = 'set', window = {sel} }})",
            "tile": f"hl.dsp.window.float({{ action = 'unset', window = {sel} }})",
            "fullscreen": f"hl.dsp.window.fullscreen({{ action = 'toggle', window = {sel} }})",
            "maximize": f"hl.dsp.window.fullscreen({{ mode = 'maximized', action = 'toggle', window = {sel} }})",
            "pin": f"hl.dsp.window.pin({{ action = 'toggle', window = {sel} }})",
            "center": f"hl.dsp.window.center({{ window = {sel} }})",
        }
        if action in L:
            hypr.dispatch(L[action])
        elif action == "move":
            hypr.dispatch(f"hl.dsp.window.move({{ x = {int(x)}, y = {int(y)}, window = {sel} }})")
        elif action == "resize":
            hypr.dispatch(f"hl.dsp.window.resize({{ x = {int(w)}, y = {int(h)}, window = {sel} }})")
        elif action == "to_workspace":
            v = int(workspace) if str(workspace).isdigit() else str(workspace)
            hypr.dispatch(f"hl.dsp.window.move({{ workspace = {hypr.lua_val(v)}, follow = false, window = {sel} }})")
        else:
            raise RPCError("unknown action")
        time.sleep(0.1)
        return hypr.summarize(hypr.find_window(c["address"]))

    @api.method("ws.list")
    def ws_list():
        """Workspaces with their window counts."""
        return [{"id": w["id"], "name": w["name"], "monitor": w.get("monitor"), "windows": w.get("windows"),
                 "last": w.get("lastwindowtitle")} for w in hypr.workspaces()]

    @api.method("ws.switch")
    def ws_switch(workspace):
        """Switch to a workspace (number or name)."""
        hypr.focus_workspace(workspace)
        return hypr.active_workspace()

    @api.method("mon.list")
    def mon_list():
        """Monitors (name, mode, position, scale, active workspace)."""
        return [{k: m.get(k) for k in ("name", "description", "width", "height", "refreshRate", "x", "y", "scale",
                                        "transform", "focused", "dpmsStatus", "vrr", "mirrorOf")} |
                {"workspace": m["activeWorkspace"]["name"]} for m in hypr.monitors()]

    @api.method("hypr.dispatch")
    def hypr_dispatch(expr):
        """Raw Hyprland dispatcher (Lua expression, e.g. 'hl.dsp.focus({ workspace = 2 })')."""
        return hypr.dispatch(expr)

    @api.method("hypr.eval")
    def hypr_eval(code):
        """Run Lua in the compositor (hyprctl eval). Not persisted."""
        return hypr.eval_lua(code)

    @api.method("hypr.query")
    def hypr_query(what):
        """Raw hyprctl JSON query: clients, monitors, workspaces, layers, binds, devices, version, ..."""
        return hypr.hyprctl(what, json_out=True)

    @api.method("binds.list")
    def binds_list(query=None):
        """Keybinds currently registered in Hyprland."""
        out = []
        lua_names = None
        for b in hypr.binds():
            mods = b.get("modmask", 0)
            names = [n for bit, n in ((64, "SUPER"), (4, "CTRL"), (8, "ALT"), (1, "SHIFT")) if mods & bit]
            combo = " + ".join(names + [str(b.get("key") or b.get("keycode"))])
            desc = b.get("description")
            if not desc and b.get("dispatcher") == "__lua":  # Lua binds are anonymous functions: read the config
                if lua_names is None:
                    from . import bindnames
                    try:
                        lua_names = bindnames.names()
                    except Exception:
                        lua_names = {}
                desc = lua_names.get(bindnames.norm(combo), "")
            row = {"combo": combo, "description": desc, "dispatcher": b.get("dispatcher"),
                   "arg": b.get("arg")}
            if not query or query.lower() in str(row).lower():
                out.append(row)
        return out

    # ------------------------------------------------------------ apps / games
    api.method("app.list")(apps.app_list)
    api.method("app.launch")(apps.launch)
    api.method("app.running")(apps.running)
    api.method("game.list")(apps.games)
    api.method("game.launch")(apps.game_launch)
    api.method("game.stop")(apps.game_stop)
    from . import gamemode
    api.method("game.mode")(gamemode.mode)
    from . import totality
    api.method("totality.mode")(totality.mode)

    # ------------------------------------------------------------ accessibility
    @api.method("ui.tree")
    def ui_tree(window="active", interactive_only=True, max_nodes=300):
        """Accessibility tree of a window: buttons, fields, menus with names, states and click centers."""
        return atspi.tree(window, interactive_only=interactive_only, max_nodes=max_nodes)

    @api.method("ui.find")
    def ui_find(name=None, role=None, window="active", exact=False):
        """Find controls by name and/or role (e.g. role='push button')."""
        return atspi.find(name, role, window, exact=exact)

    @api.method("ui.press")
    def ui_press(name=None, role=None, path=None, window="active", index=0):
        """Press/activate a control by name (accessibility action; no mouse). Falls back to a real click."""
        r = atspi.press(name=name, role=role, path=path, window=window, index=index)
        if r.get("needs_mouse") and r.get("center"):
            input_click(*r["center"])
            r["clicked_with_mouse"] = r["center"]
        return r

    @api.method("ui.set_text")
    def ui_set_text(text, name=None, path=None, window="active"):
        """Set the contents of a text field by accessibility (no typing)."""
        return atspi.set_text(text, name=name, path=path, window=window)

    # ------------------------------------------------------------ clipboard / notify / media
    @api.method("clip.get")
    def clip_get():
        """Clipboard text."""
        return run(["wl-paste", "--no-newline"], check=False, timeout=5)

    @api.method("clip.set")
    def clip_set(text):
        """Put text on the clipboard."""
        subprocess.run(["wl-copy"], input=text, text=True, timeout=5)
        return {"ok": True}

    @api.method("notify.send")
    def notify_send(title, body="", urgency="normal", icon="arclight"):
        """Desktop notification to Arthur."""
        run(["notify-send", "-a", identity.os_name(), "-u", urgency, "-i", icon, title, body], check=False)
        return {"sent": title}

    @api.method("media.control")
    def media_control(action="play-pause", player=None):
        """playerctl: play | pause | play-pause | next | previous | status | metadata."""
        cmd = ["playerctl"] + (["-p", player] if player else []) + [action]
        return run_full(cmd, timeout=10)

    # ------------------------------------------------------------ settings
    @api.method("settings.list")
    def settings_list(prefix=None, values=True, include_hypr=False):
        """Every friendly setting with its value (prefix e.g. 'appearance'). 'hypr.' lists raw Hyprland options."""
        return registry().list(prefix, with_values=values, include_hypr=include_hypr)

    @api.method("settings.get")
    def settings_get(key):
        """One setting's value and description."""
        return registry().describe(key)

    @api.method("settings.set")
    def settings_set(key, value):
        """Change a setting: applies live and persists."""
        return registry().set(key, value)

    @api.method("settings.search")
    def settings_search(text):
        """Find settings by words (searches keys and descriptions, incl. every Hyprland option)."""
        return registry().search(text)

    @api.method("settings.reset")
    def settings_reset(key):
        """Remove Arclight's override so the hand-written config wins again."""
        return registry().reset(key)

    @api.method("settings.groups")
    def settings_groups():
        """Setting groups and how many settings each has."""
        return registry().groups()

    # ------------------------------------------------------------ user services / user journal
    api.method("svc.list")(lambda state=None, kind="service", query=None: svcmod.svc_list(state, kind, query, user=True))
    api.docs["svc.list"]["doc"] = "User units (systemctl --user)."
    api.method("svc.status")(lambda unit, lines=30: svcmod.svc_status(unit, lines, user=True))
    api.method("svc.action")(lambda unit, action, now=True: svcmod.svc_action(unit, action, now, user=True))
    api.method("log.query")(lambda **kw: svcmod.log_query(user=True, **kw))

    # ------------------------------------------------------------ waiting / stopping
    @api.method("wait.window")
    def wait_window(match, timeout=20):
        """Wait until a window whose class or title matches the regex exists."""
        t0 = time.monotonic()
        rx = re.compile(match, re.I)
        while time.monotonic() - t0 < float(timeout):
            for c in hypr.clients():
                if rx.search(c.get("class") or "") or rx.search(c.get("title") or ""):
                    return hypr.summarize(c)
            time.sleep(0.25)
        raise RPCError(f"no window matching {match!r} after {timeout}s")

    @api.method("wait.text")
    def wait_text(text, target="screen", timeout=20):
        """Wait until text appears on screen (OCR)."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < float(timeout):
            r = screen.find_text(text, target)
            if r["matches"]:
                return r["matches"][0]
            time.sleep(0.7)
        raise RPCError(f"{text!r} did not appear within {timeout}s")

    @api.method("stop")
    def stop():
        """Panic stop: cancel running input sequences and release every key and button."""
        return input_release_all()

    @api.method("version")
    def version():
        return {"version": __version__}

    return api


def main():
    sock = session_sock()
    os.makedirs(os.path.dirname(sock), exist_ok=True)
    os.chmod(os.path.dirname(sock), 0o700)
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        # started outside the compositor (e.g. systemd before env import): find the instance
        base = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "hypr")
        try:
            sigs = sorted(os.listdir(base), key=lambda d: os.path.getmtime(os.path.join(base, d)))
            if sigs:
                os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = sigs[-1]
        except OSError:
            pass
    api = build_api()

    def ready():
        print(f"arclight-session {__version__} listening on {sock}", flush=True)

    try:
        asyncio.run(serve(api, sock, mode=0o600, ready=ready))
    finally:
        if _input:
            _input.close()
    return 0
