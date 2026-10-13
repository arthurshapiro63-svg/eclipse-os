"""Hyprland IPC: queries (hyprctl -j) and dispatchers.

Arclight runs Hyprland with the Lua config, where dispatchers are Lua expressions
(`hyprctl dispatch 'hl.dsp.focus({ window = "address:0x1" })'`). A legacy hyprlang
config is detected and gets the old dispatcher syntax instead.
"""
import json
import os
import re
import subprocess

from ..rpc import RPCError

_lua = None


def hyprctl(*args, json_out=False, check=True, timeout=10):
    cmd = ["hyprctl"] + (["-j"] if json_out else []) + list(args)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = p.stdout.strip()
    if check and (p.returncode != 0 or out.startswith("error") or "Couldn't connect" in out):
        raise RPCError(f"hyprctl {' '.join(args)}: {out or p.stderr.strip()}")
    if json_out:
        try:
            return json.loads(out or "null")
        except json.JSONDecodeError:
            raise RPCError(f"hyprctl {' '.join(args)} returned non-JSON: {out[:300]}")
    return out


def is_lua():
    global _lua
    if _lua is None:
        out = subprocess.run(["hyprctl", "dispatch", "hl.dsp.no_op()"], capture_output=True, text=True).stdout.strip()
        _lua = out == "ok"
    return _lua


def lua_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def lua_val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {lua_val(x)}" if re.fullmatch(r"[A-Za-z_]\w*", str(k)) else f"[{lua_str(k)}] = {lua_val(x)}"
                               for k, x in v.items()) + " }"
    if isinstance(v, (list, tuple)):
        return "{ " + ", ".join(lua_val(x) for x in v) + " }"
    if v is None:
        return "nil"
    return lua_str(v)


def dispatch(lua_expr, legacy=None):
    """Run a dispatcher. `lua_expr` like 'hl.dsp.focus({ workspace = 3 })'; `legacy` like 'workspace 3'."""
    if is_lua():
        out = hyprctl("dispatch", lua_expr, check=False)
    else:
        if legacy is None:
            raise RPCError("this action needs the Hyprland Lua config")
        out = hyprctl("dispatch", *legacy.split(" ", 1), check=False)
    if out != "ok":
        raise RPCError(f"dispatch failed: {out}  ({lua_expr if is_lua() else legacy})")
    return True


def eval_lua(code):
    out = hyprctl("eval", code, check=False)
    if out != "ok":
        raise RPCError(f"hyprctl eval: {out}")
    return True


# ---------------------------------------------------------------- queries

def clients():
    return hyprctl("clients", json_out=True) or []


def active_window():
    w = hyprctl("activewindow", json_out=True)
    return w if w and w.get("address") else None


def monitors():
    return hyprctl("monitors", json_out=True) or []


def workspaces():
    return hyprctl("workspaces", json_out=True) or []


def active_workspace():
    return hyprctl("activeworkspace", json_out=True)


def cursor_pos():
    c = hyprctl("cursorpos", json_out=True)
    return int(c["x"]), int(c["y"])


def layers():
    return hyprctl("layers", json_out=True) or {}


def binds():
    return hyprctl("binds", json_out=True) or []


def layout_box():
    """Bounding box of all (non-mirrored) monitors in global logical coordinates."""
    xs, ys, xe, ye = [], [], [], []
    for m in monitors():
        if m.get("disabled"):
            continue
        w = m["width"] / m.get("scale", 1)
        h = m["height"] / m.get("scale", 1)
        if m.get("transform", 0) in (1, 3, 5, 7):
            w, h = h, w
        xs.append(m["x"]); ys.append(m["y"]); xe.append(m["x"] + w); ye.append(m["y"] + h)
    return (min(xs), min(ys), max(xe), max(ye)) if xs else (0, 0, 1920, 1080)


def find_window(selector):
    """Resolve a selector to one client. Accepts an address ('0x..'), 'class:REGEX', 'title:REGEX',
    'pid:N', 'active', or plain text matched against class then title (case-insensitive)."""
    cl = clients()
    if selector in (None, "", "active"):
        w = active_window()
        if not w:
            raise RPCError("no active window")
        return w
    s = str(selector)
    if re.fullmatch(r"(address:)?0x[0-9a-fA-F]+", s):
        addr = s.split(":")[-1].lower()
        for c in cl:
            if c["address"].lower() == addr:
                return c
        raise RPCError(f"no window with address {addr}")
    kind, _, pat = s.partition(":")
    if kind in ("class", "title", "initialclass", "initialtitle") and pat:
        key = {"class": "class", "title": "title", "initialclass": "initialClass", "initialtitle": "initialTitle"}[kind]
        rx = re.compile(pat, re.I)
        hits = [c for c in cl if rx.search(c.get(key) or "")]
    elif kind == "pid" and pat.isdigit():
        hits = [c for c in cl if c.get("pid") == int(pat)]
    else:
        low = s.lower()
        hits = [c for c in cl if low == (c.get("class") or "").lower()] or \
               [c for c in cl if low in (c.get("class") or "").lower()] or \
               [c for c in cl if low in (c.get("title") or "").lower()]
    if not hits:
        raise RPCError(f"no window matches {selector!r}; open windows: " +
                       "; ".join(f"{c['class']} | {c['title'][:50]}" for c in cl[:15]))
    hits.sort(key=lambda c: c.get("focusHistoryID", 99))
    return hits[0]


def summarize(c):
    return {"address": c["address"], "class": c.get("class"), "title": c.get("title"), "workspace": c["workspace"]["name"],
            "at": c.get("at"), "size": c.get("size"), "floating": c.get("floating"), "fullscreen": c.get("fullscreen"),
            "pid": c.get("pid"), "xwayland": c.get("xwayland"), "focused": c.get("focusHistoryID") == 0,
            "visible": c.get("visible", True), "stable_id": c.get("stableId"), "monitor": c.get("monitor")}


# ---------------------------------------------------------------- actions

def sel(c):
    return f"address:{c['address']}"


def focus_window(c):
    dispatch(f"hl.dsp.focus({{ window = {lua_str(sel(c))} }})", f"focuswindow {sel(c)}")


def close_window(c):
    dispatch(f"hl.dsp.window.close({{ window = {lua_str(sel(c))} }})", f"closewindow {sel(c)}")


def move_cursor(x, y):
    dispatch(f"hl.dsp.cursor.move({{ x = {int(x)}, y = {int(y)} }})", f"movecursor {int(x)} {int(y)}")


def focus_workspace(ws):
    v = int(ws) if str(ws).lstrip("-").isdigit() else str(ws)
    dispatch(f"hl.dsp.focus({{ workspace = {lua_val(v)} }})", f"workspace {ws}")


def exec_cmd(cmd, workspace=None, silent=True, float_=None):
    """Spawn through the compositor so the app gets the session environment."""
    rules = {}
    if workspace is not None:
        rules["workspace"] = f"{workspace}{' silent' if silent else ''}"
    if float_:
        rules["float"] = True
    if is_lua():
        arg = lua_str(cmd) + (f", {lua_val(rules)}" if rules else "")
        dispatch(f"hl.dsp.exec_cmd({arg})")
    else:
        prefix = f"[workspace {rules['workspace']}] " if "workspace" in rules else ""
        hyprctl("dispatch", "exec", prefix + cmd)
    return True


def notify(text, ms=4000, color="rgb(FFC94A)", icon=1):
    try:
        hyprctl("notify", str(icon), str(ms), color, text, check=False)
    except Exception:
        pass
