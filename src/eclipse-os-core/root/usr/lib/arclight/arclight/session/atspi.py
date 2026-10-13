"""Accessibility tree (AT-SPI): find controls by name/role and press them without guessing pixels.

Works for GTK3/GTK4 apps out of the box, Qt apps with QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1,
Electron/Chromium with ACCESSIBILITY_ENABLED=1 (Arclight sets all of these in the
session). Coordinates come from the toolkit relative to the window and are turned
into global coordinates with the Hyprland window position.
"""
import threading

from ..rpc import RPCError
from . import hypr

_lock = threading.RLock()
_atspi = None

INTERACTIVE = {"push button", "toggle button", "check box", "radio button", "menu item", "check menu item",
               "radio menu item", "combo box", "text", "entry", "password text", "spin button", "slider", "link",
               "page tab", "list item", "tree item", "table cell", "menu", "button", "switch", "toggle switch",
               "icon", "tool bar item", "split button", "editbar"}


def A():
    global _atspi
    if _atspi is None:
        try:
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi
            Atspi.init()
            try:
                Atspi.set_timeout(1500, 4000)  # one hung app must not freeze every lookup (default is 25 s)
            except Exception:
                pass
            _atspi = Atspi
        except Exception as e:
            raise RPCError(f"AT-SPI unavailable: {e}")
    return _atspi


def _states(acc):
    Atspi = A()
    ss = acc.get_state_set()
    names = []
    for st in ("FOCUSED", "ENABLED", "SENSITIVE", "VISIBLE", "SHOWING", "CHECKED", "SELECTED", "EXPANDED",
               "EDITABLE", "PRESSED", "ACTIVE"):
        if ss.contains(getattr(Atspi.StateType, st)):
            names.append(st.lower())
    return names


def _bounds(acc, origin):
    Atspi = A()
    try:
        comp = acc.get_component_iface()
        if not comp:
            return None
        e = comp.get_extents(Atspi.CoordType.WINDOW)
        if e.width <= 0 or e.height <= 0:
            return None
        x, y = origin[0] + e.x, origin[1] + e.y
        return [round(x), round(y), e.width, e.height]
    except Exception:
        return None


def _actions(acc):
    try:
        act = acc.get_action_iface()
        if not act:
            return []
        return [act.get_action_name(i) for i in range(act.get_n_actions())]
    except Exception:
        return []


def _text(acc):
    try:
        t = acc.get_text_iface()
        if t:
            n = t.get_character_count()
            return t.get_text(0, min(n, 500))
    except Exception:
        pass
    return None


def _value(acc):
    try:
        v = acc.get_value_iface()
        if v:
            return v.get_current_value()
    except Exception:
        pass
    return None


def _app_frames(window):
    """(frame accessible, hypr client) pairs for a window selector (or all windows if None)."""
    Atspi = A()
    desktop = Atspi.get_desktop(0)
    clients = hypr.clients()
    targets = [hypr.find_window(window)] if window else clients
    out = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app is None:
            continue
        try:
            pid = app.get_process_id()
        except Exception:
            continue
        if pid not in {c.get("pid") for c in targets}:
            continue
        try:
            nchild = app.get_child_count()
        except Exception:
            continue
        for j in range(nchild):
            fr = app.get_child_at_index(j)
            if fr is None:
                continue
            title = fr.get_name() or ""
            for c in targets:
                if c.get("pid") == pid and (not title or title == c.get("title") or title in (c.get("title") or "")
                                            or len([x for x in targets if x.get("pid") == pid]) == 1):
                    out.append((fr, c))
                    break
    return out


def _origin(client, frame=None):
    """Global position of the app's surface. Measured when possible: the window box minus the app's own
    frame size is whatever the compositor draws inside the box (a hyprbars title bar, or nothing when a
    rule turned the bar off) — rules do not show up in the client JSON, so guessing was off by a bar."""
    x, y = client["at"]
    if frame is not None:
        try:
            Atspi = A()
            e = frame.get_component_iface().get_extents(Atspi.CoordType.WINDOW)
            dw, dh = client["size"][0] - e.width, client["size"][1] - e.height
            if e.width > 0 and e.height > 0 and 0 <= dh <= 64 and abs(dw) <= 4:
                return x, y + dh
        except Exception:
            pass
    return x + _content_offset(client)[0], y + _content_offset(client)[1]


_bar_h = None


def _content_offset(client):
    """hyprbars draws its title bar inside the window box; the app's surface starts below it."""
    global _bar_h
    if client.get("fullscreen") or "hyprbars:no_bar" in str(client.get("tags")):
        return (0, 0)
    if _bar_h is None:
        try:
            plugins = hypr.hyprctl("plugin", "list", check=False)
            if "hyprbars" in plugins:
                o = hypr.hyprctl("getoption", "plugin:hyprbars:bar_height", json_out=True)
                _bar_h = int(o.get("int", 0))
            else:
                _bar_h = 0
        except Exception:
            _bar_h = 0
    if client.get("class", "").startswith("steam_app_") or client.get("class") in ("claude-orange", "gamescope"):
        return (0, 0)
    return (0, _bar_h)


def _walk(acc, origin, depth, max_depth, path, out, interactive_only, max_nodes):
    """Depth-first walk. Containers are always descended (GTK4 does not mark every container SHOWING);
    only nodes that are visible on screen are reported."""
    if len(out) >= max_nodes or depth > max_depth or acc is None:
        return
    try:
        role = acc.get_role_name()
        name = acc.get_name() or ""
        states = _states(acc)
    except Exception:
        return
    shown = depth == 0 or "showing" in states or "visible" in states
    if shown and (not interactive_only or role in INTERACTIVE or (role == "label" and name)):
        node = {"path": path, "role": role, "name": name, "states": states}
        b = _bounds(acc, origin)
        if b:
            node["box"] = b
            node["center"] = [b[0] + b[2] // 2, b[1] + b[3] // 2]
        acts = _actions(acc)
        if acts:
            node["actions"] = acts
        txt = _text(acc) if role in ("text", "entry", "password text", "paragraph", "terminal") else None
        if txt:
            node["text"] = txt
        val = _value(acc)
        if val is not None:
            node["value"] = val
        if b or depth == 0:
            out.append(node)
    if "visible" not in states and depth > 0 and role not in ("filler", "panel", "scroll pane", "list", "list box",
                                                              "viewport", "section", "page tab list", "split pane"):
        return  # an invisible subtree (a hidden page): skip it
    try:
        n = min(acc.get_child_count(), 400)
    except Exception:
        n = 0
    for i in range(n):
        try:
            ch = acc.get_child_at_index(i)
        except Exception:
            continue
        _walk(ch, origin, depth + 1, max_depth, f"{path}.{i}", out, interactive_only, max_nodes)


def tree(window="active", depth=40, interactive_only=True, max_nodes=400):
    """Controls of a window (flat list with role, name, state, box, center, actions, text)."""
    with _lock:
        frames = _app_frames(window)
        if not frames:
            raise RPCError("this window exposes no accessibility tree (canvas apps, games and terminals usually "
                           "don't); use screen OCR / find_text instead")
        out = []
        for fr, c in frames:
            _walk(fr, _origin(c, fr), 0, depth, "0", out, interactive_only, max_nodes)
        return {"window": hypr.summarize(frames[0][1]), "nodes": out, "count": len(out)}


def _resolve(window, path):
    frames = _app_frames(window)
    if not frames:
        raise RPCError("no accessibility tree for that window")
    fr, c = frames[0]
    acc = fr
    for idx in path.split(".")[1:]:
        acc = acc.get_child_at_index(int(idx))
        if acc is None:
            raise RPCError(f"path {path} no longer exists (the UI changed); call ui tree again")
    return acc, c


def find(name=None, role=None, window="active", exact=False, limit=20):
    """Find controls by (partial) name and/or role."""
    nodes = tree(window, interactive_only=False, max_nodes=2500)["nodes"]
    q = (name or "").lower()
    hits = []
    for n in nodes:
        nm = (n.get("name") or n.get("text") or "").lower()
        if role and n["role"] != role.lower():
            continue
        if name and not ((nm == q) if exact else (q in nm)):
            continue
        hits.append(n)
    hits.sort(key=lambda n: (-((n.get("name") or "").lower() == q), "showing" not in n["states"],
                             "actions" not in n, n["role"] not in INTERACTIVE))
    return hits[:limit]


def _pressy(action_name):
    n = (action_name or "").lower()
    return n in ("click", "press", "activate", "toggle", "jump", "open", "default", "select", "expand or contract")


def press(name=None, role=None, path=None, window="active", index=0, action=None):
    """Activate a control through its accessibility action (no mouse needed). Falls back to the
    caller doing a mouse click at the returned center when the control has no action."""
    with _lock:
        if path is None:
            hits = find(name, role, window)
            if not hits:
                raise RPCError(f"no control named {name!r}" + (f" with role {role}" if role else ""))
            if index >= len(hits):
                raise RPCError(f"only {len(hits)} matches")
            node = hits[index]
            path = node["path"]
        acc, c = _resolve(window, path)
        act = None
        probe = acc
        for _ in range(4):  # a matched label usually sits inside the actionable row/button
            try:
                a = probe.get_action_iface()
                if a and any(_pressy(a.get_action_name(i)) for i in range(a.get_n_actions())):
                    acc, act = probe, a
                    break
                probe = probe.get_parent()
                if probe is None:
                    break
            except Exception:
                break
        if act and act.get_n_actions() > 0:
            names = [act.get_action_name(i) for i in range(act.get_n_actions())]
            pick = names.index(action) if action in names else next((i for i, n in enumerate(names) if _pressy(n)), 0)
            ok = act.do_action(pick)
            return {"pressed": path, "action": names[pick], "ok": bool(ok), "role": acc.get_role_name(),
                    "name": acc.get_name()}
        fr0 = next((f for f, cc in _app_frames(window) if cc.get("address") == c.get("address")), None)
        b = _bounds(acc, _origin(c, fr0))
        return {"pressed": None, "needs_mouse": True, "center": [b[0] + b[2] // 2, b[1] + b[3] // 2] if b else None,
                "role": acc.get_role_name(), "name": acc.get_name()}


def set_text(text, name=None, path=None, role=None, window="active"):
    """Replace the text of an editable field."""
    with _lock:
        if path is None:
            hits = [h for h in find(name, role, window) if "editable" in h["states"]]
            if not hits:
                raise RPCError(f"no editable field named {name!r}")
            path = hits[0]["path"]
        acc, _ = _resolve(window, path)
        et = acc.get_editable_text_iface()
        if not et:
            raise RPCError("that control is not editable")
        ok = et.set_text_contents(text)
        return {"path": path, "ok": bool(ok)}
