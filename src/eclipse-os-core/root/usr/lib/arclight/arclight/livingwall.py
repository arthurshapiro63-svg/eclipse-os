"""Living wallpaper: Arthur's eclipse photo follows the real time of day.

Deep night (cool, dark, the corona the brightest thing) -> dawn (gold lift on the horizon) ->
bright midday (lighter, more neutral) -> dusk (the photo exactly as shot) -> night again.

Everything is deterministic grading of the one real photo (tone curves, white balance,
saturation, a vignette and soft position masks so the sky and the ground can be graded
differently). Nothing is painted in.

Cheap by design:
  * the five looks are rendered ONCE per screen size and cached in ~/.cache/arclight/livingwall/
  * a frame is a single ImageMagick blend of two cached looks, made only when the blend has
    actually moved (every few minutes at most), at nice 19 / idle I/O
  * paused while Totality or game mode is on, frozen on battery, idle when the setting is off
    or another wallpaper is picked (it never fights the wallpaper switcher)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .util import runtime_dir, user_config_dir

VERSION = 1                      # bump when the looks change: old caches are ignored
EVERY = int(os.environ.get("ARCLIGHT_LIVINGWALL_EVERY", "180"))   # seconds between checks (the blend moves ~1-3 % per step)
FADE = 4                         # crossfade seconds (awww fade)
STEPS = 60                       # blend weight resolution: 1/60 per frame at most
SETTING = "wallpaper.living"
ECLIPSE_NAMES = ("arclight-eclipse.jpg", "arclight-eclipse.png", "arclight-eclipse-1080.png")
SHARE_SRC = Path(os.environ.get("ARCLIGHT_SHARE", "/usr/share/arclight")) / "wallpapers/arclight-eclipse.jpg"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "arclight/livingwall"
HOME = Path.home()

# ------------------------------------------------------------------ the looks
# Each look is a list of ImageMagick operations on the photo. Masks are made from the frame
# size only (vertical gradients / a radial vignette), so they fit the photo at any resolution.
#   SKY  = 1 above ~30 % of the height, fading to 0 at ~55 % (ridge line ~40-45 %)
#   GLOW = a soft band on the horizon (where the photo's own orange glow already is)
LOOKS = ("night", "dawn", "midday", "dusk")
LABELS = {"night": "Night", "dawn": "Dawn", "midday": "Midday", "dusk": "Dusk"}


def _wb(r, g, b):
    return ["-channel", "R", "-evaluate", "multiply", str(r), "-channel", "G", "-evaluate", "multiply", str(g),
            "-channel", "B", "-evaluate", "multiply", str(b), "+channel", "-clamp"]


def _sky(w, h):
    return ["(", "-size", f"{w}x{h}", "gradient:white-black", "-level", "45%,70%", ")"]


def _glow(w, h):
    # product of two ramps: rises from 30 % height, falls after 46 %
    return ["(", "-size", f"{w}x{h}", "gradient:white-black", "-level", "40%,62%", "-negate",
            "(", "-size", f"{w}x{h}", "gradient:white-black", "-level", "46%,58%", ")",
            "-compose", "multiply", "-composite", "-blur", "0x" + str(max(2, h // 60)), ")"]


def _vignette(w, h, edge):
    # 1.0 in the middle, `edge` in the far corners
    return ["(", "-size", f"{w * 3 // 2}x{w * 3 // 2}", "radial-gradient:white-black", "-gravity", "center",
            "-crop", f"{w}x{h}+0+0", "+repage", "+level", f"{edge * 100:.0f}%,100%", ")",
            "-compose", "multiply", "-composite"]


def look_ops(name, w, h):
    """ImageMagick ops turning the (already sized) photo into one look. Input is the current image."""
    if name == "dusk":                       # the photo as shot: it IS dusk
        return []
    if name == "night":
        return (["-level", "0,100%,0.72", "-clamp"] + _wb(0.88, 0.96, 1.07) + ["-modulate", "100,72,100"]
                # sky: the orange glow fades out, the sky goes deep blue-grey
                + ["(", "+clone", "-modulate", "92,45,100", ")"] + _sky(w, h) + ["-compose", "over", "-composite"]
                + ["(", "+clone", "-modulate", "100,40,100", ")"] + _glow(w, h) + ["-compose", "over", "-composite"]
                + _vignette(w, h, 0.55))
    if name == "dawn":
        return (["-level", "0,100%,1.10", "-clamp"] + _wb(1.03, 1.0, 0.96)
                # cool, slightly rosy upper sky ...
                + ["(", "+clone"] + _wb(0.98, 0.99, 1.05) + ["-modulate", "106,90,100", ")"] + _sky(w, h)
                + ["-compose", "over", "-composite"]
                # ... above a gold lift on the horizon: gold inside the glow band, black elsewhere, screened
                + ["(", "(", "-size", f"{w}x{h}", "xc:black", ")",
                   "(", "-size", f"{w}x{h}", "xc:#FFB462", ")"] + _glow(w, h)
                + ["-compose", "over", "-composite", ")"]
                + ["-define", "compose:args=55", "-compose", "screen", "-composite"]
                + _vignette(w, h, 0.85))
    if name == "midday":
        return (["-level", "0,100%,1.42", "-clamp"] + _wb(0.97, 1.0, 1.03) + ["-modulate", "104,86,100"]
                # neutral, hazier, brighter sky (the orange cast mostly gone)
                + ["(", "+clone", "-modulate", "108,55,100", "-fill", "#9FB4CC", "-colorize", "16", ")"] + _sky(w, h)
                + ["-compose", "over", "-composite"]
                + ["(", "+clone", "-modulate", "104,60,100", ")"] + _glow(w, h) + ["-compose", "over", "-composite"])
    raise ValueError(name)


# ------------------------------------------------------------------ the day

def _hm(s):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(s or ""))
    if not m or int(m.group(1)) > 24 or int(m.group(2)) > 59:
        raise ValueError(f"not a time (HH:MM): {s!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


def _settings():
    try:
        return json.loads((user_config_dir() / "settings.json").read_text())
    except (OSError, ValueError):
        return {}


def schedule(sunrise=None, sunset=None):
    """(minute of day, look) keyframes. Defaults: sunrise 06:30, sunset 19:00 (settings can move them)."""
    s = _settings()
    try:
        rise = _hm(sunrise or s.get("wallpaper.living_sunrise") or "06:30")
    except ValueError:
        rise = 390
    try:
        sset = _hm(sunset or s.get("wallpaper.living_sunset") or "19:00")
    except ValueError:
        sset = 1140
    if not 180 <= rise < sset - 360 <= 1380:
        rise, sset = 390, 1140
    day = [(rise - 120, "night"), (rise, "dawn"),            # night lifts into dawn gold over 2 h
           (rise + 180, "midday"), (sset - 240, "midday"),   # bright from mid-morning to late afternoon
           (sset - 30, "dusk"), (sset + 30, "dusk"),         # the photo as shot, around sunset
           (sset + 150, "night")]                            # deep night 2 h after
    return day


def blend_at(minute, sched=None):
    """-> (look_a, look_b, weight of b in 0..1) for a minute of the day (smoothstep eased)."""
    sched = sched or schedule()
    pts = sched + [(sched[0][0] + 1440, sched[0][1])]
    pts = [(sched[-1][0] - 1440, sched[-1][1])] + pts
    m = minute
    if m < pts[0][0]:
        m += 1440
    for (t0, a), (t1, b) in zip(pts, pts[1:]):
        if t0 <= m <= t1:
            if a == b or t1 == t0:
                return a, a, 0.0
            x = (m - t0) / (t1 - t0)
            return a, b, x * x * (3 - 2 * x)
    return sched[0][1], sched[0][1], 0.0


def now_minute(at=None):
    at = at or os.environ.get("ARCLIGHT_LIVINGWALL_TIME")
    if at:
        return _hm(at)
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def describe(a, b, w):
    if a == b or w < 0.05:
        return LABELS[a]
    if w > 0.95:
        return LABELS[b]
    return f"{LABELS[a]} turning to {LABELS[b].lower()} ({round(w * 100)} %)"


# ------------------------------------------------------------------ state of the desktop

def enabled():
    v = _settings().get(SETTING, True)
    return v is not False and str(v).lower() not in ("false", "0", "off", "no")


def current_wallpaper():
    f = HOME / ".cache/current-wallpaper"
    try:
        return (os.readlink(f) if f.is_symlink() else f.read_text().strip()) or None
    except OSError:
        return None


def is_eclipse(path):
    return bool(path) and os.path.basename(str(path)) in ECLIPSE_NAMES


def source_photo():
    cur = current_wallpaper()
    if is_eclipse(cur) and os.path.isfile(cur):
        return Path(cur)
    for p in (HOME / "Pictures/wallpapers/arclight-eclipse.jpg", SHARE_SRC):
        if p.is_file():
            return p
    raise FileNotFoundError("the eclipse photo is missing")


def paused():
    """Totality (another feature) or game mode on -> a reason string, else None."""
    rd = runtime_dir()
    for name, why in (("totality.json", "Totality is on"), ("gamemode.json", "game mode is on")):
        f = rd / name
        if f.exists():
            try:
                d = json.loads(f.read_text() or "{}")
                if isinstance(d, dict) and (d.get("on") is False or d.get("active") is False):
                    continue
            except (OSError, ValueError, AttributeError):
                pass
            return why
    return None


def on_battery():
    base = Path(os.environ.get("ARCLIGHT_POWER_SUPPLY_DIR", "/sys/class/power_supply"))
    ac_seen = ac_online = discharging = False
    try:
        supplies = list(base.iterdir())
    except OSError:
        return False
    for d in supplies:
        def rd(n, d=d):
            try:
                return (d / n).read_text().strip()
            except OSError:
                return ""
        typ = rd("type")
        if typ in ("Mains", "USB", "USB_C", "USB_PD") or d.name.startswith(("AC", "ADP", "ACAD")):
            if rd("online") != "":
                ac_seen = True
                ac_online |= rd("online") == "1"
        elif typ == "Battery" or d.name.startswith("BAT"):
            if rd("scope") == "Device":       # mouse / headset batteries do not count
                continue
            discharging |= rd("status") == "Discharging"
    # a battery that is emptying is the signal; AC online overrides odd firmware reports
    return discharging and not ac_online


def screen_size():
    """Largest monitor (pixels, rotation-aware), default 1920x1080."""
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=5).stdout
        best = None
        for m in json.loads(out or "[]"):
            w, h = int(m["width"]), int(m["height"])
            if int(m.get("transform", 0)) % 2:
                w, h = h, w
            if not best or w * h > best[0] * best[1]:
                best = (w, h)
        if best:
            return best
    except Exception:
        pass
    return (1920, 1080)


# ------------------------------------------------------------------ rendering

def _magick(args, timeout=300):
    cmd = ["magick"] + [str(a) for a in args]
    pre = []
    if shutil.which("ionice"):
        pre += ["ionice", "-c", "3"]
    pre += ["nice", "-n", "19"]
    env = dict(os.environ, MAGICK_THREAD_LIMIT=os.environ.get("MAGICK_THREAD_LIMIT", "2"))
    p = subprocess.run(pre + cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if p.returncode != 0:
        raise RuntimeError(f"magick failed: {p.stderr.strip()[-400:]}")


def keyframe(name, w, h, src=None):
    """The cached look at this size (16-bit PNG, made once)."""
    src = Path(src or source_photo())
    st = src.stat()
    tag = f"v{VERSION}-{w}x{h}-{st.st_size}"
    out = CACHE / f"look-{name}-{tag}.png"
    if out.exists():
        return out
    CACHE.mkdir(parents=True, exist_ok=True)
    for old in CACHE.glob("look-*.png"):                   # looks from an older version
        if f"-v{VERSION}-" not in old.name:
            old.unlink(missing_ok=True)
    tmp = out.with_name(out.name + ".tmp.png")
    _magick([src, "-colorspace", "sRGB", "-depth", "16", "-resize", f"{w}x{h}^", "-gravity", "center",
             "-extent", f"{w}x{h}", "+repage", "-gravity", "northwest"] + look_ops(name, w, h)
            + ["-depth", "16", "-define", "png:compression-level=1", tmp])
    os.replace(tmp, out)
    return out


def render(minute, w, h, out, src=None, quality=92):
    """Write the frame for a minute of the day to `out` (JPEG). Returns (a, b, weight)."""
    a, b, wt = blend_at(minute)
    wt = round(wt * STEPS) / STEPS
    ka = keyframe(a, w, h, src)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(".tmp-" + out.name)
    if a == b or wt <= 0:
        args = [ka]
    elif wt >= 1:
        args = [keyframe(b, w, h, src)]
    else:
        # blend: B over A at weight wt (one pass, 16-bit in, 8-bit out once)
        args = [ka, keyframe(b, w, h, src), "-define", f"compose:args={wt * 100:.2f}", "-compose", "blend",
                "-composite"]
    _magick(args + ["-depth", "8", "-quality", str(quality), "-sampling-factor", "4:4:4", tmp])
    os.replace(tmp, out)
    return a, b, wt


# ------------------------------------------------------------------ showing it

STATE = CACHE / "state.json"


def _state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(**kw):
    CACHE.mkdir(parents=True, exist_ok=True)
    d = _state()
    d.update(kw)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    os.replace(tmp, STATE)


def shown_image():
    """What awww is painting right now (first output), or None."""
    try:
        out = subprocess.run(["awww", "query"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    m = re.search(r"image: (.+)$", out, re.M)
    return m.group(1).strip() if m else None


def _ours(path):
    return bool(path) and str(path).startswith(str(CACHE))


def show(path, fade=FADE):
    subprocess.run(["awww", "img", str(path), "--resize", "crop", "--transition-type", "fade",
                    "--transition-duration", str(fade), "--transition-fps", "30"],
                   capture_output=True, timeout=30)


def tick(at=None, force=False, fade=FADE, anyway=False):
    """One check. Returns a short plain status string."""
    if not enabled():
        st = _state()
        if _ours(shown_image()):                 # switched off: put the plain photo back
            cur = current_wallpaper()
            if cur and os.path.isfile(cur):
                show(cur, fade)
        if st.get("frame"):
            _save_state(frame=None, key=None)
        return "off"
    cur = current_wallpaper()
    if not is_eclipse(cur):
        return "another wallpaper is picked"
    shown = shown_image()
    if shown and not _ours(shown) and not is_eclipse(shown):
        return "another wallpaper is on screen"
    why = paused()
    if why and not anyway:
        return f"paused ({why})"
    if on_battery() and not anyway:
        return "on battery: kept still"
    minute = now_minute(at)
    w, h = screen_size()
    a, b, wt = blend_at(minute)
    key = f"{a}:{b}:{round(wt * STEPS)}:{w}x{h}:v{VERSION}"
    st = _state()
    if not force and st.get("key") == key and _ours(shown) and st.get("frame") == shown:
        return f"up to date: {describe(a, b, wt)}"
    # alternate between two file names so awww always sees a new image
    nxt = CACHE / ("frame-b.jpg" if (st.get("frame") or "").endswith("frame-a.jpg") else "frame-a.jpg")
    t0 = time.monotonic()
    render(minute, w, h, nxt)
    show(nxt, fade)
    _save_state(key=key, frame=str(nxt), minute=minute, at=time.time(), render_s=round(time.monotonic() - t0, 2))
    return f"now: {describe(a, b, wt)}"


def run_loop():
    """The service: check now, then every EVERY seconds (aligned to the clock)."""
    print("living wallpaper: started", flush=True)
    time.sleep(float(os.environ.get("ARCLIGHT_LIVINGWALL_DELAY", "10")))   # let `wallpaper --restore` go first
    last = None
    while True:
        try:
            msg = tick()
        except Exception as e:                        # never die: log and try again later
            msg = f"error: {e}"
        if msg != last:
            print(f"living wallpaper: {msg}", flush=True)
            last = msg
        time.sleep(EVERY - (time.time() % EVERY) + 1)


def thumbs(size=(320, 180)):
    """[(label, path)] for Night, Dawn, Midday, Dusk and Now (small, cached)."""
    w, h = size
    res = []
    for name in LOOKS:
        res.append((LABELS[name], str(keyframe(name, w, h))))
    out = CACHE / f"thumb-now-{w}x{h}.jpg"
    render(now_minute(), w, h, out, quality=88)
    res.append(("Now", str(out)))
    return res


# ------------------------------------------------------------------ CLI

USAGE = """arclight-livingwall: the eclipse photo follows the time of day

  arclight-livingwall now [--time HH:MM] [--anyway]   update the wallpaper now (fades in;
                                              --anyway also on battery / in game mode)
  arclight-livingwall status [--time HH:MM]   what it is doing and why
  arclight-livingwall preview HH:MM [-o FILE] [--size WxH]   render one time to a file
  arclight-livingwall render [--size WxH]     make the cached looks for this screen
  arclight-livingwall run                     the background loop (systemd user service)

  ARCLIGHT_LIVINGWALL_TIME=HH:MM pretends it is that time (testing)."""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    opt = {}
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--time", "-o", "--out", "--size", "--fade") and i + 1 < len(argv):
            opt[a.lstrip("-")] = argv[i + 1]
            i += 2
            continue
        rest.append(a)
        i += 1
    cmd = rest[0] if rest else "status"
    at = opt.get("time")
    if at:
        os.environ["ARCLIGHT_LIVINGWALL_TIME"] = at
    size = None
    if opt.get("size"):
        m = re.fullmatch(r"(\d+)x(\d+)", opt["size"])
        if not m:
            print("size must look like 1920x1080", file=sys.stderr)
            return 2
        size = (int(m.group(1)), int(m.group(2)))
    try:
        if cmd in ("-h", "--help", "help"):
            print(USAGE)
        elif cmd == "now":
            print(tick(at, force=True, fade=float(opt.get("fade", FADE)), anyway="--anyway" in rest))
        elif cmd == "status":
            minute = now_minute(at)
            a, b, wt = blend_at(minute)
            sched = schedule()
            print(json.dumps({
                "on": enabled(), "wallpaper_is_eclipse": is_eclipse(current_wallpaper()),
                "paused": paused(), "on_battery": on_battery(),
                "time": f"{minute // 60:02d}:{minute % 60:02d}", "look": describe(a, b, wt),
                "schedule": [f"{(t % 1440) // 60:02d}:{t % 60:02d} {n}" for t, n in sched],
                "shown": shown_image(), "last": _state()}, indent=1))
        elif cmd == "preview":
            t = rest[1] if len(rest) > 1 else at
            minute = now_minute(t)
            w, h = size or screen_size()
            out = opt.get("o") or opt.get("out") or f"livingwall-{minute // 60:02d}{minute % 60:02d}.jpg"
            a, b, wt = render(minute, w, h, out)
            print(f"{out}: {describe(a, b, wt)}")
        elif cmd == "render":
            w, h = size or screen_size()
            t0 = time.monotonic()
            for n in LOOKS:
                print(keyframe(n, w, h))
            print(f"{w}x{h} looks ready in {time.monotonic() - t0:.1f} s")
        elif cmd == "run":
            run_loop()
        else:
            print(USAGE, file=sys.stderr)
            return 2
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"arclight-livingwall: {e}", file=sys.stderr)
        return 1
    return 0
