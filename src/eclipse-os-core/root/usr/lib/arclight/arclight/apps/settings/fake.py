"""In-memory stand-in for the Arclight daemons (ARCLIGHT_SETTINGS_FAKE=1).

Returns realistic data for every method the Settings app uses and records every change in
SETS, so the UI can be exercised headlessly without touching a real session.
"""
import copy
import os
import threading
import time
from pathlib import Path

from ...rpc import RPCError
from ... import client as C

SETS = []          # [(key, value)] in call order
CALLS = []         # [(method, params)]
_lock = threading.Lock()
REPO = Path(__file__).resolve().parents[4]


def _wallpaper_dir():
    art = REPO / "art/wallpapers"
    if any(art.glob("*-1080.png")):
        return art
    return Path.home() / "Pictures/wallpapers"


def _wallpapers():
    d = _wallpaper_dir()
    if not d.exists():
        return []
    files = sorted(p.name for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    if d.name == "wallpapers" and (d / "contact-sheet.png").exists():
        files = [f for f in files if f.endswith("-1080.png")]
    return files


def S(key, type, description, value, group=None, scope="user", writable=True, **extra):
    d = {"key": key, "type": type, "description": description, "scope": scope,
         "group": group or key.split(".")[0], "writable": writable, "value": value}
    d.update({k: v for k, v in extra.items() if v is not None})
    return d


def _initial():
    walls = _wallpapers()
    rows = [
        S("ai.agent", "enum", "Agent used by the Ask overlay and Fix-with-AI (claude or codex)", "claude", choices=["claude", "codex"]),
        S("ai.ask_model", "string", "Model override for the Ask overlay (empty = agent default)", ""),
        S("ai.enabled", "bool", "Use the AI features (Ask, Eclipse AI, Fix-with-AI, routines)", True),
        S("ai.auto_game_mode", "bool", "Turn Totality on by itself when a game starts", True),
        S("ai.autofix", "bool", "Let the AI start fixing a failed service on its own (otherwise it asks first)", False),
        S("ai.indicator", "bool", "Show a banner while the AI drives the mouse/keyboard", True),
        S("ai.notify_failures", "bool", "Notify when a service fails, with a Fix-with-AI button", True),
        S("ai.voice", "bool", "Dictation button in the Ask overlay (uses hush)", False),
        S("appearance.active_border", "gradient", "Focused border colour or gradient ('rgba(..) rgba(..) 45deg')",
          "ee7ccbff ee2e9bff ee1260d4 45deg", alias_of="hypr.general.col.active_border"),
        S("appearance.animations", "bool", "Animations", True, alias_of="hypr.animations.enabled"),
        S("appearance.blur", "bool", "Blur behind glass", True, alias_of="hypr.decoration.blur.enabled"),
        S("appearance.blur_passes", "int", "Blur passes (more = smoother, more GPU)", 3, min=1, max=6),
        S("appearance.blur_size", "int", "Blur radius", 8, min=1, max=30),
        S("appearance.blur_vibrancy", "float", "Colour intensity of the glass", 0.24, min=0, max=1),
        S("appearance.border_size", "int", "Window border width (px)", 2, min=0, max=12, unit="px"),
        S("appearance.dim_inactive", "bool", "Dim unfocused windows", True),
        S("appearance.dim_strength", "float", "How much to dim unfocused windows", 0.1, min=0, max=1),
        S("appearance.gaps_in", "int", "Gap between windows (px)", 4, min=0, max=60, unit="px"),
        S("appearance.gaps_out", "int", "Gap around the screen edge (px)", 10, min=0, max=120, unit="px"),
        S("appearance.glow", "bool", "Glow around the focused window", True),
        S("appearance.eclipse_look", "bool", "Eclipse look: the eclipse theme, wallpaper and boot animation "
          "(off = plain graphite, same features)", True),
        S("appearance.moving_light", "bool", "Moving light: a slow gold light travels around the focused window's edge", True),
        S("appearance.layout", "enum", "Tiling layout", "dwindle", choices=["dwindle", "master", "scrolling"]),
        S("appearance.opacity_active", "float", "Glass: focused window opacity", 0.94, min=0.3, max=1.0),
        S("appearance.opacity_inactive", "float", "Glass: unfocused window opacity", 0.84, min=0.3, max=1.0),
        S("appearance.rounding", "int", "Window corner radius (px)", 10, min=0, max=40, unit="px"),
        S("appearance.shadow", "bool", "Window shadows", True),
        S("appearance.theme", "enum", "Colour theme (rewrites every app's colours via theme-apply)", "eclipse",
          choices=["eclipse", "arclight", "daylight", "ember", "graphite", "midnight-blue"]),
        S("audio.mic_muted", "bool", "Microphone muted", False),
        S("audio.mic_volume", "int", "Microphone volume (%)", 80, min=0, max=150, unit="%"),
        S("audio.muted", "bool", "Speakers muted", False),
        S("audio.output", "enum", "Default output device", "Ryzen HD Audio Controller Analog Stereo",
          choices=["Ryzen HD Audio Controller Analog Stereo", "AW2725QF HDMI Audio"]),
        S("audio.volume", "int", "Speaker volume (%)", 56, min=0, max=150, unit="%"),
        S("bluetooth.enabled", "bool", "Bluetooth radio", True),
        S("cursor.hide_after", "float", "Hide the cursor after N idle seconds (0 = never)", 0.0, min=0, max=600),
        S("display.tearing", "bool", "Allow tearing for games", False),
        S("display.vrr", "int", "Adaptive sync: 0 off, 1 on, 2 fullscreen only", 0, min=0, max=3),
        S("idle.lock_after", "int", "Lock the screen after N idle seconds (0 = never)", 0, min=0, max=86400, unit="s"),
        S("idle.screen_off_after", "int", "Turn screens off after N idle seconds (0 = never)", 0, min=0, max=86400, unit="s"),
        S("input.follow_mouse", "int", "Focus follows mouse (0 off, 1 always, 2 click, 3 separate)", 1, min=0, max=3),
        S("input.keyboard_layout", "string", "Keyboard layout (us, gb, de, fr, ...)", "us"),
        S("input.keyboard_options", "string", "Keyboard options (e.g. caps:escape)", ""),
        S("input.mouse_accel", "string", "Mouse acceleration (flat / adaptive / empty = default)", ""),
        S("input.mouse_speed", "float", "Mouse speed (-1 slow .. 1 fast)", 0.0, min=-1, max=1),
        S("input.natural_scroll", "bool", "Natural touchpad scrolling", False),
        S("input.repeat_delay", "int", "Key repeat delay (ms)", 600, min=100, max=2000),
        S("input.repeat_rate", "int", "Key repeat rate (per second)", 25, min=1, max=100),
        S("network.networking", "bool", "All networking (NetworkManager)", True),
        S("network.wifi", "bool", "Wi-Fi radio", True),
        S("power.profile", "enum", "Power profile", "performance", choices=["power-saver", "balanced", "performance"]),
        S("shell.current", "enum", "Desktop shell (bar, dock, launcher): DankMaterialShell or arthur-shell", "dms",
          choices=["dms", "arthur"]),
        S("system.auto_snapshot", "bool", "Snapshot the system before package changes (btrfs installs)", True, scope="system"),
        S("system.hostname", "string", "Machine name", "archbox", scope="system"),
        S("system.locale", "string", "System language (e.g. en_US.UTF-8)", "en_US.UTF-8", scope="system"),
        S("system.ntp", "bool", "Automatic time sync", True, scope="system"),
        S("system.swappiness", "int", "vm.swappiness (0-200)", 60, min=0, max=200, scope="system"),
        S("system.timezone", "string", "Timezone (Region/City)", "America/New_York", scope="system"),
        S("wallpaper.current", "path", "Current wallpaper (a file name in ~/Pictures/wallpapers or any path)",
          str(_wallpaper_dir() / next((w for w in walls if "eclipse" in w), walls[0])) if walls else None,
          choices=walls),
        S("wallpaper.folder", "path", "Folder the wallpaper switcher cycles through", str(_wallpaper_dir()), writable=False),
        S("hypr.decoration.blur.size", "int", "Blur radius", 8, group="hypr"),
        S("hypr.decoration.blur.noise", "float", "Hyprland option decoration.blur.noise", 0.015, group="hypr"),
        S("hypr.general.gaps_out", "gap", "Gap between windows and screen edges (px)", 10, group="hypr"),
    ]
    return {r["key"]: r for r in rows}


SETTINGS = _initial()


def _list(prefix=None, values=True, include_hypr=False):
    out = []
    for k in sorted(SETTINGS):
        if prefix and not k.startswith(prefix):
            continue
        if not prefix and not include_hypr and k.startswith("hypr."):
            continue
        out.append(copy.deepcopy(SETTINGS[k]))
    return out


def _get(key):
    if key not in SETTINGS:
        raise C.RemoteError("Error", f"unknown setting {key!r}", {})
    return copy.deepcopy(SETTINGS[key])


def _set(key, value):
    s = _get(key)
    if not s["writable"]:
        raise C.RemoteError("Error", f"{key} is read-only", {})
    if s.get("choices") and s["type"] == "enum" and str(value) not in map(str, s["choices"]):
        raise C.RemoteError("Error", f"{key}: must be one of {', '.join(map(str, s['choices']))}", {})
    if "min" in s and isinstance(value, (int, float)) and value < s["min"]:
        raise C.RemoteError("Error", f"{key}: minimum is {s['min']}", {})
    if "max" in s and isinstance(value, (int, float)) and value > s["max"]:
        raise C.RemoteError("Error", f"{key}: maximum is {s['max']}", {})
    with _lock:
        SETS.append((key, value))
        SETTINGS[key]["value"] = value
    return {"key": key, "value": value, "requested": value, "applied_live": True}


def _search(text):
    words = (text or "").lower().split()
    hits = [copy.deepcopy(s) for s in SETTINGS.values()
            if words and all(w in f"{s['key']} {s['description']}".lower() for w in words)]
    return sorted(hits, key=lambda s: (s["key"].startswith("hypr."), s["key"]))


BINDS = [
    {"combo": "SUPER + Q", "description": "", "dispatcher": "exec", "arg": "ghostty"},
    {"combo": "SUPER + Return", "description": "", "dispatcher": "exec", "arg": "ghostty"},
    {"combo": "SUPER + C", "description": "", "dispatcher": "hl.dsp.window.close", "arg": ""},
    {"combo": "SUPER + E", "description": "", "dispatcher": "exec", "arg": "thunar"},
    {"combo": "SUPER + space", "description": "", "dispatcher": "exec", "arg": "~/.local/bin/shellctl launcher"},
    {"combo": "SUPER + B", "description": "", "dispatcher": "exec", "arg": "zen-browser"},
    {"combo": "SUPER + Z", "description": "", "dispatcher": "exec", "arg": "zeditor"},
    {"combo": "SUPER + L", "description": "", "dispatcher": "exec", "arg": "pidof hyprlock || hyprlock"},
    {"combo": "SUPER + W", "description": "", "dispatcher": "exec", "arg": "~/.local/bin/shellctl wallpaper"},
    {"combo": "SUPER + Tab", "description": "", "dispatcher": "exec", "arg": "~/.local/bin/shellctl overview"},
    {"combo": "SUPER + SHIFT + A", "description": "Ask Eclipse", "dispatcher": "exec", "arg": "arclight-ask"},
    {"combo": "SUPER + I", "description": "Eclipse Settings", "dispatcher": "exec", "arg": "arclight-settings"},
    {"combo": "SUPER + SHIFT + Escape", "description": "", "dispatcher": "exec", "arg": "arclight-stop"},
    {"combo": "Print", "description": "", "dispatcher": "exec", "arg": "~/.local/bin/shot region"},
] + [{"combo": f"SUPER + {i % 10}", "description": "", "dispatcher": "hl.dsp.focus", "arg": f"workspace {i}"}
     for i in range(1, 11)]

APPS = [
    {"id": "com.mitchellh.ghostty", "name": "Ghostty", "comment": "A terminal emulator", "categories": ["System", "TerminalEmulator"], "wm_class": None},
    {"id": "zen", "name": "Zen Browser", "comment": "Experience tranquillity while browsing the web", "categories": ["Network"], "wm_class": "zen"},
    {"id": "dev.zed.Zed", "name": "Zed", "comment": "A high-performance, multiplayer code editor", "categories": ["Development"], "wm_class": None},
    {"id": "thunar", "name": "Thunar File Manager", "comment": "Browse the filesystem with the file manager", "categories": ["System"], "wm_class": None},
    {"id": "steam", "name": "Steam", "comment": "Application for managing and playing games on Steam", "categories": ["Game"], "wm_class": "steam"},
    {"id": "obs", "name": "OBS Studio", "comment": "Free and Open Source Streaming/Recording Software", "categories": ["AudioVideo"], "wm_class": None},
    {"id": "org.prismlauncher.PrismLauncher", "name": "Prism Launcher", "comment": "A custom launcher for Minecraft", "categories": ["Game"], "wm_class": None},
    {"id": "dev.arclight.Settings", "name": "Eclipse Settings", "comment": "Every setting on the machine", "categories": ["Settings"], "wm_class": None},
    {"id": "btop", "name": "btop++", "comment": "Resource monitor", "categories": ["System"], "wm_class": None},
]

MONITORS = [{"name": "DP-1", "description": "Dell Inc. AW2725QF", "width": 1920, "height": 1080, "refreshRate": 329.916,
             "x": 0, "y": 0, "scale": 1.0, "transform": 0, "focused": True, "dpmsStatus": True, "vrr": False,
             "mirrorOf": "none", "workspace": "1"},
            {"name": "HDMI-A-1", "description": "Dell Inc. AW2725QF", "width": 1920, "height": 1080, "refreshRate": 60.0,
             "x": 0, "y": 0, "scale": 1.0, "transform": 0, "focused": False, "dpmsStatus": True, "vrr": False,
             "mirrorOf": "DP-1", "workspace": "1"}]

SYSINFO = {
    "hostname": "archbox", "os": "Eclipse OS 0.1", "name": "Eclipse OS", "arclight": "Eclipse OS 0.1 (codename Arclight)", "kernel": "7.2.9-arch1-1",
    "uptime_s": 34200, "load": [0.82, 1.1, 1.3],
    "cpu": {"model": "AMD Ryzen AI 9 HX 470 w/ Radeon 890M", "threads": 24},
    "memory": {"total": 26_950_000_000, "available": 11_400_000_000, "swap_total": 0, "swap_free": 0},
    "gpu": ["c4:00.0 Display controller: Advanced Micro Devices, Inc. [AMD/ATI] Strix [Radeon 880M / 890M]"],
    "temps_c": {"k10temp/Tctl": 51.2}, "battery": [],
    "disks": [{"source": "/dev/nvme0n1p2", "fstype": "btrfs", "size": 982_000_000_000, "used": 504_000_000_000,
               "free": 478_000_000_000, "mount": "/"}],
    "root_fs": "btrfs", "network": [{"if": "wlp194s0", "state": "UP", "addrs": ["192.168.11.167/24"]}],
    "failed_units": [], "users_logged_in": ["arthur"], "firmware": "uefi", "boot": "root=UUID=... rw quiet",
}

UPDATES = [{"name": "hyprland", "version": "0.56.2-4", "new_version": "0.56.3-1"},
           {"name": "linux", "version": "7.2.9.arch1-1", "new_version": "7.2.10.arch1-1"},
           {"name": "mesa", "version": "1:26.2.3-1", "new_version": "1:26.2.4-1"}]

SNAPSHOTS = {"supported": True, "snapshots": [
    {"id": "20261008-191200-before-pkg-install-btop", "label": "before pkg install btop", "time": time.time() - 3600},
    {"id": "20261008-120000-manual", "label": "manual", "time": time.time() - 30000}]}


def _actions(n=50, agent=None, method=None):
    now = time.time()
    rows = [
        {"time": now - 40, "method": "pkg.install", "params": {"names": ["btop"]}, "uid": 1000, "agent": "claude", "ok": True, "seconds": 6.1},
        {"time": now - 300, "method": "svc.action", "params": {"unit": "bluetooth.service", "action": "restart"}, "uid": 1000, "agent": "claude", "ok": True, "seconds": 0.4},
        {"time": now - 900, "method": "file.write", "params": {"path": "/etc/sysctl.d/90-arclight.conf"}, "uid": 1000, "agent": "codex", "ok": True, "seconds": 0.02},
        {"time": now - 1500, "method": "pkg.remove", "params": {"names": ["nano"]}, "uid": 1000, "agent": "human", "ok": False, "seconds": 0.3, "error": "target not found: nano"},
        {"time": now - 4000, "method": "sys.hostname", "params": {"name": "archbox"}, "uid": 1000, "agent": "human", "ok": True, "seconds": 0.1},
    ]
    return rows[:n]


def call(method, **p):
    with _lock:
        CALLS.append((method, p))
    which = C.target_for(method)
    if method != "api.ping" and os.environ.get(f"ARCLIGHT_FAKE_DOWN_{which.upper()}") == "1":
        raise C.Unavailable("arclightd is not running (fake)" if which == "system" else
                            "arclight-session is not running (fake)")
    time.sleep(0.02)
    if method == "settings.list":
        return _list(p.get("prefix"), p.get("values", True), p.get("include_hypr", False))
    if method == "settings.get":
        return _get(p["key"])
    if method == "settings.set":
        return _set(p["key"], p["value"])
    if method == "settings.search":
        return _search(p.get("text"))
    if method == "settings.groups":
        g = {}
        for s in SETTINGS.values():
            g[s["group"]] = g.get(s["group"], 0) + 1
        return g
    if method == "binds.list":
        q = (p.get("query") or "").lower()
        return [b for b in BINDS if not q or q in str(b).lower()]
    if method == "app.list":
        q = (p.get("query") or "").lower()
        return [a for a in APPS if not q or q in a["name"].lower()]
    if method == "mon.list":
        return copy.deepcopy(MONITORS)
    if method == "sys.info":
        return copy.deepcopy(SYSINFO)
    if method == "pkg.list":
        return copy.deepcopy(UPDATES) if p.get("upgradable") else [{"name": "base", "version": "3-3"}]
    if method == "pkg.upgrade":
        time.sleep(1.2)
        UPDATES.clear()
        return {"code": 0, "output": ":: Starting full system upgrade...\n there is nothing to do"}
    if method == "actions.tail":
        return _actions(p.get("n", 50))
    if method == "snap.list":
        return copy.deepcopy(SNAPSHOTS)
    if method == "svc.list":
        return [{"unit": "arclightd.service", "load": "loaded", "active": "active", "sub": "running", "enabled": "enabled",
                 "description": "Arclight system API"}]
    if method == "session.actions":
        return [{"time": time.time() - 300, "method": "settings.set", "params": {"key": "appearance.gaps_out", "value": 40},
                 "agent": "claude", "ok": True}]
    if method == "file.history":
        return [{"id": "20261010-101500-abc123", "path": os.path.expanduser("~/.config/hypr/hyprland.lua"), "op": "edit",
                 "time": time.time() - 600, "note": "gaps", "existed": True},
                {"id": "20261010-100000-def456", "path": "/etc/hosts", "op": "write", "time": time.time() - 1200,
                 "note": None, "existed": True}][:p.get("limit", 50)]
    if method == "file.revert":
        return {"path": "/etc/hosts", "restored": "file", "saved_current_as": "x"}
    if method == "settings.reset":
        return {"key": p.get("key"), "reset": True}
    if method == "api.ping":
        return {"server": "fake", "peer": None, "time": time.time()}
    raise C.RemoteError("NoSuchMethod", f"fake backend has no {method}", {})


def ping(which):
    return os.environ.get(f"ARCLIGHT_FAKE_DOWN_{which.upper()}") != "1"


def reset():
    global SETTINGS
    SETTINGS = _initial()
    SETS.clear()
    CALLS.clear()
