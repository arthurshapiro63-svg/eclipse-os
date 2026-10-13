"""Every Hyprland option as a setting, generated from the Lua API stubs Hyprland ships.

Live:    hyprctl eval 'hl.config({ decoration = { blur = { size = 10 } } })'
Persist: ~/.config/hypr/arclight-settings.lua, regenerated from the settings store and
         loaded at the END of hyprland.lua (pcall), so these overrides win but a broken
         or missing file can never stop Hyprland starting.
"""
import os
import re
import subprocess
from pathlib import Path

from ..rpc import RPCError
from ..util import atomic_write
from .registry import Setting

STUBS = Path("/usr/share/hypr/stubs/hl.meta.lua")
LUA_OUT = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hypr" / "arclight-settings.lua"

# Short descriptions for the options people actually change; the rest get a generic one.
DOCS = {
    "general.gaps_in": "Gap between windows (px)", "general.gaps_out": "Gap between windows and screen edges (px)",
    "general.border_size": "Window border width (px)", "general.layout": "Tiling layout",
    "general.col.active_border": "Focused window border colour/gradient",
    "general.col.inactive_border": "Unfocused window border colour",
    "general.allow_tearing": "Allow tearing (lower latency in games)",
    "general.resize_on_border": "Resize windows by dragging their borders",
    "decoration.rounding": "Window corner radius (px)", "decoration.rounding_power": "Corner shape (2 = squircle)",
    "decoration.active_opacity": "Focused window opacity (glass)", "decoration.inactive_opacity": "Unfocused window opacity",
    "decoration.fullscreen_opacity": "Fullscreen window opacity", "decoration.dim_inactive": "Dim unfocused windows",
    "decoration.dim_strength": "How much to dim unfocused windows", "decoration.blur.enabled": "Blur behind glass",
    "decoration.blur.size": "Blur radius", "decoration.blur.passes": "Blur passes (quality vs GPU cost)",
    "decoration.blur.noise": "Blur grain", "decoration.blur.vibrancy": "Colour saturation of blurred glass",
    "decoration.blur.xray": "Blur only the wallpaper (flat) instead of windows behind",
    "decoration.shadow.enabled": "Window shadows", "decoration.shadow.range": "Shadow size",
    "decoration.glow.enabled": "Accent glow around the focused window",
    "animations.enabled": "Animations on/off", "input.kb_layout": "Keyboard layout (e.g. us, gb, de)",
    "input.kb_options": "XKB options (e.g. caps:escape)", "input.sensitivity": "Mouse speed (-1..1)",
    "input.accel_profile": "Mouse acceleration profile (flat/adaptive)", "input.follow_mouse": "Focus follows mouse mode",
    "input.touchpad.natural_scroll": "Natural (reversed) touchpad scrolling", "input.repeat_rate": "Key repeat rate",
    "input.repeat_delay": "Key repeat delay (ms)", "misc.vfr": "Variable frame rate (saves power)",
    "misc.vrr": "Adaptive sync (0 off, 1 on, 2 fullscreen only)", "cursor.no_hardware_cursors": "Software cursors",
    "cursor.inactive_timeout": "Hide the cursor after N seconds idle",
}

TYPEMAP = [("Gradient", "gradient"), ("CssGap", "gap"), ("Vec2", "raw")]


def parse_stubs():
    if not STUBS.exists():
        return {}
    opts = {}
    for m in re.finditer(r"^---@field \['([a-z0-9_.]+)'\] (.+)$", STUBS.read_text(), re.M):
        key, t = m.group(1), m.group(2).strip()
        kind = "raw"
        for needle, k in TYPEMAP:
            if needle in t:
                kind = k
                break
        else:
            if t == "boolean":
                kind = "bool"
            elif t.startswith("integer"):
                kind = "int"
            elif t.startswith("number"):
                kind = "float"
            elif t.startswith("string"):
                kind = "string"
        opts[key] = kind
    return opts


def getoption(opt):
    p = subprocess.run(["hyprctl", "-j", "getoption", opt], capture_output=True, text=True, timeout=5)
    out = p.stdout.strip()
    if not out.startswith("{"):
        raise RPCError(f"hyprctl getoption {opt}: {out}")
    import json
    j = json.loads(out)
    for k in ("bool", "int", "float", "str", "gradient", "vec2", "custom", "css"):
        if k in j:
            v = j[k]
            if k == "css":
                parts = v.split()
                v = int(parts[0]) if len(set(parts)) == 1 and parts[0].lstrip("-").isdigit() else v
            if k == "str" and v.startswith("[[EMPTY]]"):
                v = ""
            return v
    return None


def nest(path, value):
    d = value
    for part in reversed(path.split(".")):
        d = {part: d}
    return d


def lua(v):
    from ..session.hypr import lua_val
    return lua_val(v)


def to_lua_value(kind, v):
    if kind == "bool":
        return bool(v) if not isinstance(v, int) else bool(v)
    if kind in ("int", "float"):
        return v
    if kind == "gap" and isinstance(v, str) and re.fullmatch(r"\d+", v.strip()):
        return int(v)
    if kind == "gradient":
        s = str(v).strip()
        parts = s.split()
        if len(parts) > 1:  # "rgba(..) rgba(..) 45deg" -> { colors = {...}, angle = 45 }
            angle = None
            if parts[-1].endswith("deg"):
                angle = float(parts[-1][:-3])
                parts = parts[:-1]
            g = {"colors": [_color(p) for p in parts]}
            if angle is not None:
                g["angle"] = angle
            return g
        return _color(s)
    return v


def _color(s):
    s = s.strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", s):
        return f"rgb({s.lstrip('#')})"
    if re.fullmatch(r"#?[0-9a-fA-F]{8}", s):
        return f"rgba({s.lstrip('#')})"
    if re.fullmatch(r"[0-9a-fA-F]{8}", s):
        return f"rgba({s})"
    return s


def apply_live(opt, kind, value):
    from ..session import hypr
    expr = "hl.config(" + lua(nest(opt, to_lua_value(kind, value))) + ")"
    out = hypr.hyprctl("eval", expr, check=False)
    if out != "ok":
        raise RPCError(f"Hyprland rejected {opt} = {value!r}: {out}")


def write_lua(store):
    """Regenerate arclight-settings.lua from every persisted hypr.* value."""
    data = store.load()
    kinds = parse_stubs()
    lines = ["-- Generated by Arclight settings (arc set / Arclight Settings). Do not edit by hand:",
             "-- change values with `arc set hypr.<option> <value>`, or remove one with `arc settings reset KEY`.",
             "-- hyprland.lua loads this file last (pcall), so these values override the hand-written ones.", ""]
    for key in sorted(k for k in data if k.startswith("hypr.")):
        opt = key[5:]
        kind = kinds.get(opt, "raw")
        lines.append(f"hl.config({lua(nest(opt, to_lua_value(kind, data[key])))})")
    for key in sorted(k for k in data if k.startswith("monitor.")):
        lines.append(f"hl.monitor({lua(data[key])})")
    atomic_write(LUA_OUT, "\n".join(lines) + "\n")
    return LUA_OUT


def register(reg):
    kinds = parse_stubs()
    for opt, kind in kinds.items():
        key = "hypr." + opt

        def getter(o=opt):
            return getoption(o)

        def setter(v, o=opt, k=kind, key=key):
            apply_live(o, k, v)
            reg.store.put(key, v)
            write_lua(reg.store)

        reg.add(Setting(key, kind if kind in ("bool", "int", "float", "string", "gradient", "gap") else "raw",
                        DOCS.get(opt, f"Hyprland option {opt}"), getter, setter, group="hypr"))
