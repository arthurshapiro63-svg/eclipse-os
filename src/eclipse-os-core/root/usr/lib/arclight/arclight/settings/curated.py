"""Friendly settings with plain names. Each one maps onto the real mechanism the desktop
already uses (Hyprland options, theme-apply, the wallpaper script, wpctl, powerprofilesctl,
nmcli, bluetoothctl, shell-switch) so nothing behaves differently from doing it by hand."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..rpc import RPCError, Client
from ..util import run, run_full, SYSTEM_SOCK
from .registry import Setting
from . import hypr_provider

HOME = Path.home()
CFG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))


def _bt_powered():
    """bluetoothctl waits forever ("Waiting to connect to bluetoothd...") when bluetoothd is not running
    (no adapter, service off, VMs): that made `arc settings list` and the Settings app hang for 2 minutes."""
    try:
        if subprocess.run(["systemctl", "is-active", "--quiet", "bluetooth.service"], timeout=5).returncode != 0:
            return False
        return "Powered: yes" in run(["bluetoothctl", "--timeout", "3", "show"], timeout=6, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return False


def _cmd(*a, timeout=20):
    p = subprocess.run(list(a), capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RPCError(f"{a[0]}: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout.strip()


def _alias(reg, key, opt, desc, type_=None, **kw):
    """A friendly name for a Hyprland option (shares the same store entry)."""
    base = reg._settings.get("hypr." + opt)
    if not base:
        return
    t = type_ or base.type

    def getter(b=base, t=t):
        v = b.getter()
        return bool(v) if t == "bool" else v

    reg.add(Setting(key, t, desc, getter, base.setter, alias_of=base.key, **kw))


# ---------------------------------------------------------------- theme / wallpaper / shell

def _themes():
    d = CFG / "theme/tokens"
    t = sorted(p.stem for p in d.glob("*.json")) if d.exists() else []
    if shutil.which("matugen") and ((HOME / ".local/bin/wallpaper-theme").exists() or shutil.which("wallpaper-theme")):
        t.append("dynamic")  # colours follow the wallpaper (matugen, hue-clamped to blue)
    return t


def _theme_get():
    f = CFG / "theme/current"
    return f.read_text().strip() if f.exists() else None


def _theme_set(v):
    if not shutil.which("theme-apply"):
        raise RPCError("theme-apply is not installed")
    r = run_full(["theme-apply", v], timeout=120)
    if r["code"] != 0:
        raise RPCError(f"theme-apply {v}: {(r['stderr'] or r['stdout']).strip()[-500:]}")


def _wall_dir():
    return Path(os.environ.get("WALLPAPER_DIR", HOME / "Pictures/wallpapers"))


def _wallpapers():
    d = _wall_dir()
    return sorted(p.name for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif")) if d.exists() else []


def _wall_get():
    f = HOME / ".cache/current-wallpaper"
    if f.is_symlink():
        return os.readlink(f)
    if f.exists():
        return f.read_text().strip()
    try:
        out = run(["awww", "query"], check=False)
        m = re.search(r"image: (.+)$", out, re.M)
        return m.group(1).strip() if m else None
    except Exception:
        return None


def _wall_set(v):
    if shutil.which("wallpaper"):
        r = run_full(["wallpaper", v], timeout=60)
        if r["code"] != 0:
            raise RPCError((r["stderr"] or r["stdout"]).strip()[-400:])
    else:
        path = v if os.path.isabs(v) else str(_wall_dir() / v)
        _cmd("awww", "img", path, "--transition-type", "grow")


def _shell_get():
    out = run_full(["pgrep", "-a", "qs"])["stdout"]
    if "quickshell/arthur" in out or "-c arthur" in out:
        return "arthur"
    if run_full(["pgrep", "-x", "dms"])["code"] == 0:
        return "dms"
    return "none"


def _shell_set(v):
    r = run_full(["shell-switch", v], timeout=60)
    if r["code"] != 0:
        raise RPCError((r["stderr"] or r["stdout"]).strip()[-400:])


# ---------------------------------------------------------------- audio

def _wpctl_vol(target):
    out = _cmd("wpctl", "get-volume", target)
    m = re.search(r"Volume: ([\d.]+)( \[MUTED\])?", out)
    return (round(float(m.group(1)) * 100), bool(m.group(2))) if m else (None, None)


def _sinks():
    out = run(["wpctl", "status"], check=False)
    sinks, sec = [], None
    for line in out.splitlines():
        if "Sinks:" in line:
            sec = "sink"
            continue
        if sec == "sink":
            if not line.strip() or re.search(r"(Sources|Filters|Streams):", line):
                break
            m = re.search(r"(\*)?\s*(\d+)\.\s+(.+?)(\s+\[vol:.*)?$", line)
            if m:
                sinks.append({"id": int(m.group(2)), "name": m.group(3).strip(), "default": bool(m.group(1))})
    return sinks


def _out_get():
    d = next((s for s in _sinks() if s["default"]), None)
    return d["name"] if d else None


def _out_set(v):
    for s in _sinks():
        if s["name"] == v or str(s["id"]) == str(v) or v.lower() in s["name"].lower():
            _cmd("wpctl", "set-default", str(s["id"]))
            return
    raise RPCError(f"no output device {v!r}; have: {[s['name'] for s in _sinks()]}")


# ---------------------------------------------------------------- hypridle

IDLE = CFG / "hypr/hypridle.conf"


def _idle_get(kind):
    def g():
        if not IDLE.exists():
            return 0
        text = IDLE.read_text()
        cmd = "hyprlock" if kind == "lock" else "dpms"
        for m in re.finditer(r"^listener \{\s*\n\s*timeout = (\d+)\s*\n\s*on-timeout = ([^\n]*)", text, re.M):
            if cmd in m.group(2):
                return int(m.group(1))
        return 0
    return g


def _idle_set(kind):
    def s(v):
        text = IDLE.read_text() if IDLE.exists() else ""
        marker = f"# arclight:{kind}"
        text = re.sub(rf"\n{re.escape(marker)} begin.*?{re.escape(marker)} end\n", "\n", text, flags=re.S)
        if int(v) > 0:
            body = ("on-timeout = pidof hyprlock || hyprlock" if kind == "lock" else
                    "on-timeout = hyprctl dispatch 'hl.dsp.dpms({ action = \"off\" })'\n"
                    "    on-resume = hyprctl dispatch 'hl.dsp.dpms({ action = \"on\" })'")
            text = text.rstrip("\n") + f"\n\n{marker} begin\nlistener {{\n    timeout = {int(v)}\n    {body}\n}}\n{marker} end\n"
        IDLE.write_text(text)
        subprocess.run(["bash", "-c", "pkill -x hypridle; setsid -f hypridle >/dev/null 2>&1"], timeout=10)
    return s


# ---------------------------------------------------------------- system (via arclightd)

def _sys(method, **kw):
    try:
        return Client(SYSTEM_SOCK, timeout=600).call(method, **kw)
    except FileNotFoundError:
        raise RPCError("arclightd is not running (systemctl start arclightd)")


# ---------------------------------------------------------------- AI options (read by Arclight components)

AI_DEFAULTS = {"ai.agent": "claude", "ai.autofix": False, "ai.indicator": True, "ai.notify_failures": True,
               "ai.ask_model": "", "ai.voice": False, "ai.auto_game_mode": True, "ai.enabled": True}


# ---------------------------------------------------------------- displays (per monitor)

def _monitors():
    try:
        return json.loads(subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True, text=True, timeout=5).stdout or "[]")
    except Exception:
        return []


def _mon(name):
    return next((m for m in _monitors() if m["name"] == name), None)


def _mon_spec(reg, name):
    """Current persisted spec for a monitor (or one built from its live state)."""
    spec = reg.store.get(f"monitor.{name}")
    if spec:
        return dict(spec)
    m = _mon(name) or {}
    return {"output": name, "mode": f"{m.get('width', 0)}x{m.get('height', 0)}@{m.get('refreshRate', 60):.2f}",
            "position": f"{m.get('x', 0)}x{m.get('y', 0)}", "scale": str(m.get("scale", 1))}


def _mon_apply(reg, name, **change):
    from .hypr_provider import lua
    spec = _mon_spec(reg, name)
    spec.update({k: str(v) for k, v in change.items()})
    out = subprocess.run(["hyprctl", "eval", f"hl.monitor({lua(spec)})"], capture_output=True, text=True, timeout=10).stdout.strip()
    if out != "ok":
        raise RPCError(f"Hyprland rejected the monitor change: {out}")
    reg.store.put(f"monitor.{name}", spec)
    from . import hypr_provider
    hypr_provider.write_lua(reg.store)


def _mode_now(name):
    m = _mon(name)
    return f"{m['width']}x{m['height']}@{m['refreshRate']:.2f}Hz" if m else None


def register_displays(reg):
    for m in _monitors():
        name = m["name"]
        if m.get("mirrorOf") not in (None, "none", "0", 0) and m.get("mirrorOf"):
            continue
        reg.add(Setting(f"display.{name}.mode", "enum", f"{name}: resolution and refresh rate",
                        (lambda n=name: _mode_now(n)),
                        (lambda v, n=name: _mon_apply(reg, n, mode=v.replace("Hz", ""))),
                        choices_fn=(lambda n=name: (_mon(n) or {}).get("availableModes", [])), group="display"))
        reg.add(Setting(f"display.{name}.scale", "float", f"{name}: scale (1 = 100%, 1.5 = 150%)",
                        (lambda n=name: (_mon(n) or {}).get("scale")),
                        (lambda v, n=name: _mon_apply(reg, n, scale=v)), min=0.5, max=3.0, group="display"))


def register(reg):
    st = reg.store
    # hypr bool options come back from getoption as ints; normalise
    for s in list(reg._settings.values()):
        if s.key.startswith("hypr.") and s.type == "bool":
            g = s.getter
            s.getter = (lambda g=g: bool(g()))

    A = lambda *a, **k: _alias(reg, *a, **k)
    A("appearance.gaps_in", "general.gaps_in", "Gap between windows (px)", "int", min=0, max=60, unit="px")
    A("appearance.gaps_out", "general.gaps_out", "Gap around the screen edge (px)", "int", min=0, max=120, unit="px")
    A("appearance.border_size", "general.border_size", "Window border width (px)", "int", min=0, max=12, unit="px")
    A("appearance.active_border", "general.col.active_border", "Focused border colour or gradient ('rgba(..) rgba(..) 45deg')")
    A("appearance.rounding", "decoration.rounding", "Window corner radius (px)", "int", min=0, max=40, unit="px")
    A("appearance.opacity_active", "decoration.active_opacity", "Glass: focused window opacity", "float", min=0.3, max=1.0)
    A("appearance.opacity_inactive", "decoration.inactive_opacity", "Glass: unfocused window opacity", "float", min=0.3, max=1.0)
    A("appearance.blur", "decoration.blur.enabled", "Blur behind glass", "bool")
    A("appearance.blur_size", "decoration.blur.size", "Blur radius", "int", min=1, max=30)
    A("appearance.blur_passes", "decoration.blur.passes", "Blur passes (more = smoother, more GPU)", "int", min=1, max=6)
    A("appearance.blur_vibrancy", "decoration.blur.vibrancy", "Colour intensity of the glass", "float", min=0, max=1)
    A("appearance.shadow", "decoration.shadow.enabled", "Window shadows", "bool")
    A("appearance.glow", "decoration.glow.enabled", "Glow around the focused window", "bool")
    A("appearance.dim_inactive", "decoration.dim_inactive", "Dim unfocused windows", "bool")
    A("appearance.dim_strength", "decoration.dim_strength", "How much to dim unfocused windows", "float", min=0, max=1)
    A("appearance.animations", "animations.enabled", "Animations", "bool")
    A("appearance.layout", "general.layout", "Tiling layout", "enum", choices=["dwindle", "master", "scrolling"])
    A("input.keyboard_layout", "input.kb_layout", "Keyboard layout (us, gb, de, fr, ...)", "string")
    A("input.keyboard_options", "input.kb_options", "Keyboard options (e.g. caps:escape)", "string")
    A("input.mouse_speed", "input.sensitivity", "Mouse speed (-1 slow .. 1 fast)", "float", min=-1, max=1)
    A("input.mouse_accel", "input.accel_profile", "Mouse acceleration (flat / adaptive / empty = default)", "string")
    A("input.natural_scroll", "input.touchpad.natural_scroll", "Natural touchpad scrolling", "bool")
    A("input.follow_mouse", "input.follow_mouse", "Focus follows mouse (0 off, 1 always, 2 click, 3 separate)", "int", min=0, max=3)
    A("input.repeat_rate", "input.repeat_rate", "Key repeat rate (per second)", "int", min=1, max=100)
    A("input.repeat_delay", "input.repeat_delay", "Key repeat delay (ms)", "int", min=100, max=2000)
    A("display.vrr", "misc.vrr", "Adaptive sync: 0 off, 1 on, 2 fullscreen only", "int", min=0, max=3)
    A("display.tearing", "general.allow_tearing", "Allow tearing for games", "bool")
    A("cursor.hide_after", "cursor.inactive_timeout", "Hide the cursor after N idle seconds (0 = never)", "float", min=0, max=600)

    reg.add(Setting("appearance.theme", "enum", "Colour theme (rewrites every app's colours via theme-apply)",
                    _theme_get, _theme_set, choices_fn=_themes, group="appearance"))
    # the Eclipse look on/off: same features, without the eclipse styling (arclight.eclipselook)
    def _look_set(v):
        from .. import eclipselook
        return eclipselook.apply(v, {"theme_get": _theme_get, "theme_set": _theme_set,
                                     "wall_get": _wall_get, "wall_set": _wall_set})
    reg.add(Setting("appearance.eclipse_look", "bool",
                    "Eclipse look: the eclipse theme, wallpaper and boot animation (off = plain graphite, same features)",
                    lambda: st.get("appearance.eclipse_look", True) is not False, _look_set, group="appearance"))
    # the slow gold light on the focused window's edge (desktop/hypr/arclight.lua + apps/motion.py read the flag);
    # on = automatic (it still rests on battery, without a GPU and in Totality), off = always still
    _ml = Path.home() / ".local/state/arclight/moving-light"
    def _ml_set(v):
        if v:
            _ml.unlink(missing_ok=True)
        else:
            _ml.parent.mkdir(parents=True, exist_ok=True)
            _ml.write_text("off\n")
        return {"moving_light": bool(v)}
    reg.add(Setting("appearance.moving_light", "bool",
                    "Moving light: a slow gold light travels around the focused window's edge",
                    lambda: not (_ml.exists() and _ml.read_text().strip().lower() == "off"), _ml_set,
                    group="appearance"))
    reg.add(Setting("wallpaper.current", "path", "Current wallpaper (a file name in ~/Pictures/wallpapers or any path)",
                    _wall_get, _wall_set, choices_fn=_wallpapers, group="wallpaper"))
    reg.add(Setting("wallpaper.folder", "path", "Folder the wallpaper switcher cycles through", lambda: str(_wall_dir()),
                    None, group="wallpaper"))
    # living wallpaper (arclight.livingwall): the eclipse photo follows the time of day
    def _living_set(k):
        def setter(v):
            st.put(k, v)
            if shutil.which("arclight-livingwall"):   # show the change now, in the background
                subprocess.Popen(["arclight-livingwall", "now", "--fade", "2"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        return setter
    reg.add(Setting("wallpaper.living", "bool", "Living wallpaper: the eclipse photo follows the time of day",
                    lambda: st.get("wallpaper.living", True) is not False, _living_set("wallpaper.living"),
                    group="wallpaper"))
    reg.add(Setting("wallpaper.living_sunrise", "string", "Living wallpaper: sunrise time (HH:MM, default 06:30)",
                    lambda: st.get("wallpaper.living_sunrise", "06:30"), _living_set("wallpaper.living_sunrise"),
                    group="wallpaper"))
    reg.add(Setting("wallpaper.living_sunset", "string", "Living wallpaper: sunset time (HH:MM, default 19:00)",
                    lambda: st.get("wallpaper.living_sunset", "19:00"), _living_set("wallpaper.living_sunset"),
                    group="wallpaper"))
    reg.add(Setting("shell.current", "enum", "Desktop shell (bar, dock, launcher): DankMaterialShell or the Eclipse Quickshell shell",
                    _shell_get, _shell_set, choices=["dms", "arthur"], group="shell"))

    # audio
    reg.add(Setting("audio.volume", "int", "Speaker volume (%)", lambda: _wpctl_vol("@DEFAULT_AUDIO_SINK@")[0],
                    lambda v: _cmd("wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", f"{int(v)}%"),
                    min=0, max=150, unit="%"))
    reg.add(Setting("audio.muted", "bool", "Speakers muted", lambda: _wpctl_vol("@DEFAULT_AUDIO_SINK@")[1],
                    lambda v: _cmd("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if v else "0")))
    reg.add(Setting("audio.mic_volume", "int", "Microphone volume (%)", lambda: _wpctl_vol("@DEFAULT_AUDIO_SOURCE@")[0],
                    lambda v: _cmd("wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", f"{int(v)}%"), min=0, max=150, unit="%"))
    reg.add(Setting("audio.mic_muted", "bool", "Microphone muted", lambda: _wpctl_vol("@DEFAULT_AUDIO_SOURCE@")[1],
                    lambda v: _cmd("wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "1" if v else "0")))
    reg.add(Setting("audio.output", "enum", "Default output device", _out_get, _out_set,
                    choices_fn=lambda: [s["name"] for s in _sinks()]))

    # power / network / bluetooth / brightness
    reg.add(Setting("power.profile", "enum", "Power profile",
                    lambda: _cmd("powerprofilesctl", "get"), lambda v: _cmd("powerprofilesctl", "set", v),
                    choices=["power-saver", "balanced", "performance"]))
    reg.add(Setting("network.wifi", "bool", "Wi-Fi radio", lambda: _cmd("nmcli", "radio", "wifi") == "enabled",
                    lambda v: _cmd("nmcli", "radio", "wifi", "on" if v else "off")))
    reg.add(Setting("network.networking", "bool", "All networking (NetworkManager)",
                    lambda: _cmd("nmcli", "networking") == "enabled",
                    lambda v: _cmd("nmcli", "networking", "on" if v else "off")))
    reg.add(Setting("bluetooth.enabled", "bool", "Bluetooth radio",
                    _bt_powered,
                    lambda v: _cmd("bluetoothctl", "power", "on" if v else "off")))
    if shutil.which("brightnessctl") and any(Path("/sys/class/backlight").glob("*")):
        reg.add(Setting("display.brightness", "int", "Screen brightness (%)",
                        lambda: round(int(_cmd("brightnessctl", "g")) * 100 / max(1, int(_cmd("brightnessctl", "m")))),
                        lambda v: _cmd("brightnessctl", "set", f"{int(v)}%"), min=1, max=100, unit="%"))

    register_displays(reg)
    reg.add(Setting("idle.lock_after", "int", "Lock the screen after N idle seconds (0 = never)",
                    _idle_get("lock"), _idle_set("lock"), min=0, max=86400, unit="s"))
    reg.add(Setting("idle.screen_off_after", "int", "Turn screens off after N idle seconds (0 = never)",
                    _idle_get("dpms"), _idle_set("dpms"), min=0, max=86400, unit="s"))

    # system scope (arclightd: changes ask for the administrator password)
    reg.add(Setting("system.hostname", "string", "Machine name", lambda: _sys("sys.hostname")["hostname"],
                    lambda v: _sys("sys.hostname", name=v), scope="system"))
    reg.add(Setting("system.timezone", "string", "Timezone (Region/City)", lambda: _sys("sys.timezone").get("Timezone"),
                    lambda v: _sys("sys.timezone", tz=v), scope="system"))
    reg.add(Setting("system.ntp", "bool", "Automatic time sync", lambda: _sys("sys.timezone").get("NTP") == "yes",
                    lambda v: _sys("sys.timezone", ntp=bool(v)), scope="system"))
    reg.add(Setting("system.locale", "string", "System language (e.g. en_US.UTF-8)",
                    lambda: _sys("sys.locale").get("System Locale", "").replace("LANG=", ""),
                    lambda v: _sys("sys.locale", lang=v), scope="system"))
    reg.add(Setting("system.swappiness", "int", "vm.swappiness (0-200)",
                    lambda: int(_sys("sys.sysctl", key="vm.swappiness").get("vm.swappiness", 60)),
                    lambda v: _sys("sys.sysctl", key="vm.swappiness", value=str(int(v))), min=0, max=200, scope="system"))
    reg.add(Setting("system.sudo_nopasswd", "bool",
                    "Passwordless admin (unsafe): sudo, polkit and the AI's root actions stop asking for your password; "
                    "any program running as you can then change the whole system",
                    lambda: _sys("sys.nopasswd").get("enabled"),
                    lambda v: _sys("sys.nopasswd", enable=bool(v)), scope="system"))
    reg.add(Setting("system.auto_snapshot", "bool", "Snapshot the system before package changes (btrfs installs)",
                    lambda: _sys("config.get").get("auto_snapshot"),
                    lambda v: _sys("config.set", key="auto_snapshot", value=bool(v)), scope="system"))

    for key, default in AI_DEFAULTS.items():
        t = "bool" if isinstance(default, bool) else "string"
        desc = {"ai.agent": "Agent used by the Ask overlay and Fix-with-AI (claude or codex)",
                "ai.autofix": "Let the AI start fixing a failed service on its own (otherwise it asks first)",
                "ai.indicator": "Show a banner while the AI drives the mouse/keyboard",
                "ai.notify_failures": "Notify when a service fails, with a Fix-with-AI button",
                "ai.ask_model": "Model override for the Ask overlay (empty = agent default)",
                "ai.voice": "Dictation button in the Ask overlay (uses hush)",
                "ai.auto_game_mode": "Totality turns on by itself in games (Steam, Minecraft, ...)",
                "ai.enabled": "Use the AI features (Ask, Eclipse AI, Fix-with-AI, routines). Off = no AI anywhere"}[key]
        reg.add(Setting(key, "enum" if key == "ai.agent" else t, desc,
                        (lambda k=key, d=default: st.get(k, d)), (lambda v, k=key: st.put(k, v)),
                        choices=["claude", "codex"] if key == "ai.agent" else None, group="ai"))
