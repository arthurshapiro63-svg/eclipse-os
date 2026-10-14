"""Totality: Eclipse OS's focus / performance mode (it replaces game mode; `arc game mode` still works).

Super+G (or a game opening, or `arc totality on`): everything except the window you use melts into
sunlight, the moon covers the sun, and at the diamond-ring moment the rest of the desktop goes to sleep:

  * compositor eye candy off (blur, shadows, glow, animations, dimming)    -> restored exactly
  * other apps' processes paused (SIGSTOP), never: the focus app and its family, the compositor,
    the shell/bar/notifications, audio (anything playing sound), network, portals, ssh, systemd,
    terminals (builds keep running), Steam, our own daemons                 -> SIGCONT on exit
  * power profile -> performance                                            -> restored
  * the focus app's threads get a higher priority (nice -5, best I/O)       -> restored
  * $XDG_RUNTIME_DIR/arclight/totality.json exists while it is on (other parts, e.g. the living
    wallpaper, pause themselves while it is there)

Everything changed is written to that state file BEFORE it is changed, so `restore()` (exit, `arc
totality off`, the overlay's ExecStopPost, a crash, a logout) can always put every bit back, even
when the state is partial. The animation runs in a transient user unit `arclight-totality`
(arclight-totality run), whose ExecStopPost is `arclight-totality restore`: if the overlay dies,
nothing stays frozen.
"""
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from ..rpc import RPCError

UNIT = "arclight-totality"

# (option, value while in Totality): the GPU-heavy compositor effects, plus the "not responding"
# dialog (paused apps can't answer the compositor's pings)
OPTIONS = [("decoration:blur:enabled", False), ("decoration:shadow:enabled", False),
           ("decoration:glow:enabled", False), ("animations:enabled", False),
           ("decoration:dim_inactive", False), ("misc:enable_anr_dialog", False)]

# Never paused (process names, /proc/PID/comm, max 15 chars)
KEEP = {
    # compositor, shell, desktop plumbing
    "Hyprland", "Xwayland", "hyprpaper", "hypridle", "hyprlock", "hyprpolkitagen", "hyprpolkitagent",
    "dms", "qs", "quickshell", "waybar", "mako", "swaync", "dunst", "awww", "awww-daemon", "swww-daemon",
    "wl-paste", "cliphist", "xdg-desktop-por", "xdg-document-po", "xdg-permission-",
    "polkit-gnome-au", "polkit-kde-auth", "gnome-keyring-d", "kwalletd6", "at-spi-bus-laun", "at-spi2-registr",
    # audio, network, system
    "pipewire", "pipewire-pulse", "wireplumber", "pulseaudio", "NetworkManager", "nm-applet",
    "blueman-applet", "bluetoothd", "iwd", "wpa_supplicant", "ssh", "sshd", "ssh-agent", "gpg-agent",
    "systemd", "dbus-daemon", "dbus-broker", "dbus-broker-lau",
    # terminals: builds and downloads in them keep going
    "kitty", "foot", "footclient", "ghostty", "alacritty", "wezterm-gui", "konsole", "gnome-terminal-",
    "xterm", "ptyxis", "kgx", "tilix", "terminator", "zellij", "tmux: server",
    # things people expect to keep working while they play
    "steam", "steamwebhelper", "obs", "claude", "claude-desktop", "Claude", "discord", "Discord",
}
KEEP_CMD = ("arclight", "/usr/lib/arclight/", "dms", "quickshell")


def runtime():
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "arclight"


def state_file():
    return runtime() / "totality.json"


def log_file():
    return runtime() / "totality.log"


def log(msg):
    try:
        runtime().mkdir(parents=True, exist_ok=True)
        with open(log_file(), "a") as f:
            f.write(f"{time.monotonic():.3f} {time.strftime('%H:%M:%S')} [{os.getpid()}] {msg}\n")
    except OSError:
        pass


@contextmanager
def locked():
    runtime().mkdir(parents=True, exist_ok=True)
    with open(runtime() / "totality.lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def load():
    try:
        return json.loads(state_file().read_text())
    except (OSError, ValueError):
        return None


def save(s):
    f = state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(s))
    os.replace(tmp, f)


# ------------------------------------------------------------------ helpers

def _get(opt):
    from ..settings.hypr_provider import getoption
    return getoption(opt)


def _set(opt, value):
    from ..settings.hypr_provider import apply_live
    apply_live(opt.replace(":", "."), "bool", value)


def _hypr_sock_req(req):
    import socket
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sk.settimeout(3)
    try:
        sk.connect(os.path.join(rt, "hypr", sig, ".socket.sock"))
        sk.sendall(req.encode())
        buf = b""
        while True:
            d = sk.recv(65536)
            if not d:
                break
            buf += d
        return buf.decode(errors="replace")
    finally:
        sk.close()


def _get_options(names):
    """{option: bool} straight from Hyprland's socket (no process per option: cheap under load)."""
    out = {}
    for n in names:
        try:
            j = json.loads(_hypr_sock_req(f"j/getoption {n}"))
        except (OSError, ValueError):
            try:
                v = _get(n)
            except (RPCError, OSError, ValueError, subprocess.SubprocessError):
                continue
            if isinstance(v, bool):
                out[n] = v
            continue
        if isinstance(j, dict):
            v = j.get("bool", j.get("int"))
            if isinstance(v, bool):
                out[n] = v
            elif isinstance(v, int) and v in (0, 1):
                out[n] = bool(v)
    return out


def _set_options(values):
    """Set several bool options in ONE hl.config() eval (each eval re-applies the config: slow under load)."""
    if not values:
        return
    tree = {}
    for opt, val in values.items():
        node = tree
        parts = opt.replace(":", ".").split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = bool(val)

    def lua(v):
        if isinstance(v, dict):
            return "{ " + ", ".join(f"{k} = {lua(x)}" for k, x in v.items()) + " }"
        return "true" if v else "false"
    try:
        r = subprocess.run(["hyprctl", "eval", f"hl.config({lua(tree)})"], capture_output=True, text=True,
                           timeout=30)
        if r.stdout.strip() == "ok":
            return
        log(f"batched option set refused ({r.stdout.strip()[:120]}): one by one")
    except (OSError, subprocess.SubprocessError):
        pass
    for opt, val in values.items():
        try:
            _set(opt, val)
        except (RPCError, OSError, subprocess.SubprocessError):
            pass


def _power(profile=None):
    if not shutil.which("powerprofilesctl"):
        return None
    try:
        if profile is None:
            r = subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True, timeout=5)
            return r.stdout.strip() or None
        subprocess.run(["powerprofilesctl", "set", profile], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return profile


def _hypr(what):
    try:
        return json.loads(_hypr_sock_req(f"j/{what}") or "null")
    except (OSError, ValueError):
        pass
    try:
        out = subprocess.run(["hyprctl", "-j", what], capture_output=True, text=True, timeout=5).stdout
        return json.loads(out or "null")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _stat(pid):
    """(ppid, starttime, state, uid) or None."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        rest = raw[raw.rindex(")") + 2:].split()
        uid = os.stat(f"/proc/{pid}").st_uid
        return int(rest[1]), int(rest[19]), rest[0], uid
    except (OSError, ValueError, IndexError):
        return None


def _comm(pid):
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def _cmd(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def _children_map():
    kids = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            st = _stat(int(d))
            if st:
                kids.setdefault(st[0], []).append(int(d))
    return kids


def _tree(pid, kids):
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        todo.extend(kids.get(p, []))
    return out


def _ancestors(pid):
    out = []
    while pid and pid > 1 and len(out) < 64:
        out.append(pid)
        st = _stat(pid)
        if not st:
            break
        pid = st[0]
    return out


def _audio_pids():
    """PIDs of everything playing or recording sound right now."""
    pids = set()
    if shutil.which("pactl"):
        for what in ("sink-inputs", "source-outputs"):
            try:
                out = subprocess.run(["pactl", "-f", "json", "list", what], capture_output=True, text=True,
                                     timeout=5).stdout
                for s in json.loads(out or "[]"):
                    p = (s.get("properties") or {}).get("application.process.id")
                    if p and str(p).isdigit():
                        pids.add(int(p))
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
    return pids


def _keep(pid):
    c = _comm(pid)
    if c in KEEP or c.startswith(("pipewire", "xdg-desktop", "systemd", "dbus", "Hyprland", "gvfs")):
        return True
    cmd = _cmd(pid)
    return any(k in cmd for k in KEEP_CMD)


def _exec_root(cmd):
    try:
        from .. import client as C
        r = C.call("exec", cmd=cmd, timeout=20, _interactive=False)   # never a password popup during Totality
        return r.get("code") == 0
    except Exception:
        return False


# ------------------------------------------------------------------ the switch

def status():
    s = load()
    if not s:
        return {"on": False, "overlay": _overlay_alive()}
    return {"on": True, "since": s.get("time"), "auto": s.get("auto", False), "phase": s.get("phase"),
            "applied": s.get("applied", False), "paused": len(s.get("stopped", [])),
            "overlay": _overlay_alive()}


def _overlay_pid():
    s = load() or {}
    pid = s.get("overlay_pid")
    if not pid:
        try:
            out = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", UNIT],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            pid = int(out or 0)
        except (OSError, ValueError, subprocess.SubprocessError):
            pid = 0
    if pid and "arclight-totality" in _cmd(pid) and " run" in _cmd(pid):
        return pid
    return 0


def _overlay_alive():
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", "--quiet", UNIT], timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _launcher():
    here = Path(__file__).resolve().parents[2] / "bin" / "arclight-totality"
    return shutil.which("arclight-totality") or (str(here) if here.exists() else None)


def on(auto=False, window=None):
    if load():
        return status()
    if window and window.startswith("0x"):   # a game just opened: it is the window that stays lit
        subprocess.run(["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{window}" }})'],
                       capture_output=True, timeout=5)
    for _ in range(30):              # a previous Totality still fading out: let it finish
        if not _overlay_alive():
            break
        time.sleep(0.1)
    with locked():
        save({"on": True, "time": time.time(), "auto": bool(auto), "phase": "starting", "applied": False,
              "saved": {"options": {}, "power": None}, "stopped": [], "niced": {}})
    log(f"on (auto={auto})")
    exe = _launcher()
    started = False
    if exe and shutil.which("systemd-run"):
        subprocess.run(["systemctl", "--user", "reset-failed", UNIT], capture_output=True, timeout=5)
        env = []
        for k in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "XDG_RUNTIME_DIR", "DISPLAY",
                  "XDG_CURRENT_DESKTOP", "DBUS_SESSION_BUS_ADDRESS", "PATH", "GSK_RENDERER"):
            if os.environ.get(k):
                env += ["-E", f"{k}={os.environ[k]}"]
        cmd = ["systemd-run", "--user", "--quiet", "--collect", f"--unit={UNIT}",
               "-p", f"ExecStopPost={exe} restore", "-p", "TimeoutStopSec=5", "-p", "CPUWeight=1000", *env, exe, "run"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        started = r.returncode == 0
        if not started:
            log(f"systemd-run failed: {r.stderr.strip()}")
        else:   # the show must not stutter behind a busy game: first in line for the CPU (needs root)
            pid = _overlay_pid()
            if pid:
                _exec_root(["renice", "-n", "-10", "-p", str(pid)])
    if not started:              # no overlay possible: just do the work, without the show
        apply()
    return status()


def off():
    s = load()
    pid = _overlay_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGUSR1)     # the overlay plays the light coming back and restores
            log(f"off -> overlay {pid}")
        except OSError:
            pid = 0
    if not pid:
        r = restore()
        return {"on": False, **r}

    def guard():                             # if the overlay hangs, stop it (its ExecStopPost restores)
        time.sleep(5)
        if _overlay_alive():
            subprocess.run(["systemctl", "--user", "stop", UNIT], capture_output=True, timeout=10)
        restore()
    threading.Thread(target=guard, daemon=True).start()
    return {"on": False, "leaving": True, "was": bool(s)}


def mode(action="toggle", auto=False, window=None):
    """Totality: action = on | off | toggle | status (window: address of the window that stays lit)."""
    if action == "status":
        return status()
    if action == "on" or (action == "toggle" and not load()):
        return on(auto=auto, window=window)
    return off()


# ------------------------------------------------------------------ the work (at the diamond ring)

def apply(focus_pid=None):
    """Turn the rest of the desktop down. Every change is recorded before it is made."""
    with locked():
        s = load()
        if not s or s.get("applied") or s.get("phase") == "leaving":
            return s
        t0 = time.monotonic()
        saved = s.setdefault("saved", {"options": {}, "power": None})
        # 1) compositor effects
        if not s.get("effects_off"):
            saved["options"].update(_get_options([o for o, _ in OPTIONS]))
        saved["power"] = _power()
        save(s)
        # 2) pause the other apps (effects off right after)
        if focus_pid is None:
            focus_pid = (_hypr("activewindow") or {}).get("pid")
        me = os.getuid()
        kids = _children_map()
        protected = set(_ancestors(os.getpid()))
        if focus_pid:
            protected |= set(_ancestors(focus_pid)) | set(_tree(focus_pid, kids))
        audio = _audio_pids()
        for a in audio:
            protected |= set(_ancestors(a))
        clients = _hypr("clients") or []
        done = set()
        for c in clients:
            pid = c.get("pid") or 0
            if pid <= 1 or pid in done or pid in protected:
                continue
            done.add(pid)
            tree = _tree(pid, kids)
            if set(tree) & audio or _keep(pid):
                continue
            for p in tree:
                st = _stat(p)
                if not st or st[3] != me or p in protected or _keep(p) or st[2] in ("T", "t", "Z"):
                    continue
                s["stopped"].append([p, st[1], _comm(p)])
                save(s)
                try:
                    os.kill(p, signal.SIGSTOP)
                except OSError:
                    s["stopped"].pop()
        # (paused first: frees the CPU, so the compositor changes below are quick even under load)
        if not s.get("effects_off"):
            _set_options({o: v for o, v in OPTIONS if o in saved["options"] and saved["options"][o] != v})
        if saved["power"] and saved["power"] != "performance":
            _power("performance")
            s["power_now"] = _power()     # machines without a performance profile stay where they were
        # 3) the focus app first in line for the CPU and the disk
        if focus_pid:
            tids = []
            for p in _tree(focus_pid, kids):
                try:
                    tids += [int(t) for t in os.listdir(f"/proc/{p}/task")]
                except OSError:
                    pass
            tids = tids[:4000]
            for t in tids:
                try:
                    s["niced"][str(t)] = os.getpriority(os.PRIO_PROCESS, t)
                except OSError:
                    pass
            save(s)
            want = [str(t) for t, n in s["niced"].items() if n > -5]
            if want and not _exec_root(["renice", "-n", "-5", "-p", *want]):
                s["niced"] = {}      # not allowed: nothing to undo
            if shutil.which("ionice"):
                subprocess.run(["ionice", "-c", "2", "-n", "0", "-p", *[str(t) for t in tids][:2000]],
                               capture_output=True, timeout=10)
        s["applied"] = True
        s["phase"] = "total"
        s["focus_pid"] = focus_pid
        save(s)
        log(f"applied: paused {len(s['stopped'])} processes "
            f"({', '.join(sorted({x[2] for x in s['stopped']}))}), niced {len(s['niced'])} threads, "
            f"power {saved['power']}->{s.get('power_now', saved['power'])}, took {time.monotonic() - t0:.2f}s")
        return s


def effects_off_early():
    """Slow (software-rendered) screens only: the compositor effects go off as the show starts instead of
    at the diamond ring. The sunlight covers everything within a moment anyway, and blur on a CPU-drawn
    screen would leave the animation only a couple of frames."""
    with locked():
        s = load()
        if not s or s.get("effects_off") or s.get("phase") == "leaving":
            return
        saved = s.setdefault("saved", {"options": {}, "power": None})
        saved["options"].update(_get_options([o for o, _ in OPTIONS]))
        s["effects_off"] = True
        save(s)
        _set_options({o: v for o, v in OPTIONS if o in saved["options"] and saved["options"][o] != v})
        log("effects off early (software rendering)")


def adopt(pid):
    """The user focused another window during Totality: wake it (and its family) if it was paused."""
    if not pid:
        return
    with locked():
        s = load()
        if not s or not s.get("stopped"):
            return
        fam = set(_ancestors(pid)) | set(_tree(pid, _children_map()))
        keep, woke = [], []
        for item in s["stopped"]:
            if item[0] in fam:
                try:
                    os.kill(item[0], signal.SIGCONT)
                except OSError:
                    pass
                woke.append(item[2])
            else:
                keep.append(item)
        if woke:
            s["stopped"] = keep
            save(s)
            log(f"focus moved: woke {', '.join(sorted(set(woke)))}")


def wake():
    """First half of leaving (as the light comes back): every paused app runs again. The compositor
    effects come back with restore() a moment later, under the still-bright sky."""
    with locked():
        s = load()
        if not s:
            return 0
        s["phase"] = "leaving"
        woke = _cont(s)
        s["stopped"] = []
        save(s)
        log(f"woke {woke}")
        return woke


def _cont(s):
    woke = 0
    for item in s.get("stopped", []):
        pid, start = item[0], item[1]
        st = _stat(pid)
        if st and st[1] == start:    # same process (not a recycled pid)
            try:
                os.kill(pid, signal.SIGCONT)
                woke += 1
            except OSError:
                pass
    return woke


def restore():
    """Put everything back. Safe to call any number of times, with any partial state."""
    with locked():
        s = load()
        if not s:
            return {"restored": False}
        errors = []
        woke = _cont(s)
        saved = s.get("saved") or {}
        want = dict(OPTIONS)
        _set_options({o: v for o, v in (saved.get("options") or {}).items()
                      if isinstance(v, bool) and want.get(o, not v) != v})
        if saved.get("power") and saved["power"] != "performance":
            _power(saved["power"])
        niced = s.get("niced") or {}
        if niced:
            by = {}
            for t, n in niced.items():
                by.setdefault(n, []).append(t)
            for n, ts in by.items():
                live = [t for t in ts if os.path.exists(f"/proc/{t}")]
                if not live:
                    continue
                for t in live:
                    try:
                        os.setpriority(os.PRIO_PROCESS, int(t), n)
                    except OSError:
                        pass
                if any(_nice(t) != n for t in live):
                    _exec_root(["renice", "-n", str(n), "-p", *live])
            if shutil.which("ionice"):
                subprocess.run(["ionice", "-c", "0", "-p", *list(niced)[:2000]], capture_output=True, timeout=10)
        try:
            state_file().unlink()
        except OSError:
            pass
        log(f"restored: woke {woke}, options {len(saved.get('options') or {})}, power {saved.get('power')}, "
            f"nice {len(niced)}" + (f", errors {errors}" if errors else ""))
        return {"restored": True, "woke": woke, "errors": errors}


def _nice(t):
    try:
        return os.getpriority(os.PRIO_PROCESS, int(t))
    except OSError:
        return None


def main(argv=None):
    """arclight-totality run | restore | on | off | toggle | status"""
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd == "run":
        from ..apps.totality import run
        return run(argv[1:])
    if cmd == "restore":
        r = restore()
        print(json.dumps(r))
        return 0
    if cmd in ("on", "off", "toggle", "status"):
        print(json.dumps(mode(cmd)))
        return 0
    print(main.__doc__, file=sys.stderr)
    return 2
