"""arclight-intro: the cinematic intro on the very first start of an installed Eclipse OS.

Black -> Arthur's crescent photo (the diamond ring flares) -> his eclipse photo with a slow push-in and a
golden bloom on the corona -> the OS name (the one chosen at install) -> "Welcome, <name>". Then five
short scenes (desktop, Ask the AI, the Store, Settings, Totality): a real screenshot of the OS floating on
glass with depth, a short headline, one plain line and the keys as glass keycaps. Finale: "You're all set."
and Start. The session (desktop.py) then opens the Welcome window.

Everything is drawn by one widget from the frame clock's timestamps (eased, never per frame), so a slow
machine shows the same film at a lower frame rate. When frames come slowly (software rendering) it drops
the blur and blend layers by itself ("lite"). Esc or Skip ends it at any time; Space / Right = next,
Left = back.

  arclight-intro               play it when this install's first-boot marker is there (consumes it)
  arclight-intro --replay      play it again (Settings -> About -> "Play the intro again")
  arclight-intro --first-boot  what the session runs on the first login (markers already handled)
  arclight-intro --render-shots DIR   developer: render stills of every scene to DIR (needs a display)
"""
import math
import os
import pwd
import sys
import time
from pathlib import Path

HOME = Path.home()
STATE = HOME / ".local/state/arclight"
PENDING = STATE / "intro-pending"
DONE = STATE / "intro-done"
REPO = Path(__file__).resolve().parents[3]

OPENING_LEN = 10.4      # seconds before the opening hands over to the first scene (unless the user goes first)
SCENE_LEN = 6.6         # autoplay time per scene
TRANS = 1.05            # page transition
BASE_W, BASE_H = 1920.0, 1080.0

SUN = (0.741, 0.129)        # corona centre in the eclipse photo (fraction of width / height)
DIAMOND = (0.865, 0.435)    # the diamond-ring flare in the crescent photo
SUN_R = 0.0878              # radius of the photo's bright ring (fraction of the photo's height)
MOON_C = (0.633, 0.455, 0.381)   # the crescent photo's ring: centre x, y (fractions) and radius (of height)

SCENES = [
    dict(id="desktop", img="intro-desktop.jpg", kicker="YOUR DESKTOP", title="Your desktop, your keys",
         line="Hold Super, the key with the logo, and press one more key.",
         keys=[(["Super", "Space"], "Open apps"), (["Super", "Enter"], "Terminal"), (["Super", "C"], "Close a window")]),
    dict(id="ask", ai=True, img="intro-ask.jpg", kicker="ASK THE AI", title="Just ask",
         line="Say what you want in plain words. The AI does it on your PC.",
         keys=[(["Super", "Shift", "A"], "Type it"), (["Super", "Shift", "V"], "Say it"),
               (["Super", "Shift", "E"], "Explain the text you selected")]),
    dict(id="store", img="intro-store.jpg", kicker="THE STORE", title="One click.\nA restore point first.",
         line="Games, art, code and AI apps. Undo is always one step away.",
         keys=[(["Super", "Space"], "then type Store")]),
    dict(id="settings", img="intro-settings.jpg", kicker="SETTINGS", title="Everything in one place",
         line="Look, screens, sound and the AI. Plain words, no files to edit.",
         line_no_ai="Look, screens, sound and more. Plain words, no files to edit.",
         keys=[(["Super", "I"], "Open Settings")]),
    dict(id="totality", img="intro-totality.jpg", kicker="TOTALITY", title="Everything else rests.\nYour game shines.",
         line="Effects pause and the PC gives the game full power. It turns on by itself in games.",
         keys=[(["Super", "G"], "Totality on or off")]),
]


# ------------------------------------------------------------------ easing (all time based)
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def seg(t, a, b):
    return clamp((t - a) / (b - a)) if b > a else float(t >= a)


def ease_out(x):          # cubic
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):       # cubic
    x = clamp(x)
    return 4 * x * x * x if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_out_expo(x):
    x = clamp(x)
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def bump(t, a, peak, b):
    """0 before a, eases up to 1 at peak, eases back to 0 at b."""
    if t <= a or t >= b:
        return 0.0
    return smooth(seg(t, a, peak)) if t < peak else 1 - smooth(seg(t, peak, b))


def lerp(a, b, x):
    return a + (b - a) * x


# ------------------------------------------------------------------ data
def os_name():
    try:
        from arclight import identity
        return identity.os_name()
    except Exception:
        return "Eclipse OS"


def first_name():
    try:
        pw = pwd.getpwuid(os.getuid())
        full = (pw.pw_gecos or "").split(",")[0].strip()
        if full:
            return full.split()[0]
        return pw.pw_name.title()
    except Exception:
        return os.environ.get("USER", "").title()


def ai_enabled():
    """Settings key ai.enabled (install-time choice); default on. Always off in the core edition."""
    try:
        from arclight.edition import has_ai
        if not has_ai():
            return False
    except ImportError:
        pass
    try:
        from arclight.settings.registry import Store
        v = Store().get("ai.enabled", True)
        return not (v is False or str(v).lower() in ("0", "false", "off", "no"))
    except Exception:
        return True


def scenes():
    ai = ai_enabled()
    # with the AI off (or no built-in AI) a scene's line may not mention it
    return [s if ai or "line_no_ai" not in s else dict(s, line=s["line_no_ai"]) for s in SCENES if ai or not s.get("ai")]


def find(name):
    """Intro asset: installed, else the source tree."""
    for d in (Path("/usr/share/arclight/eclipse"), REPO / "desktop/eclipse",
              Path("/usr/share/arclight/wallpapers"), REPO / "desktop/wallpapers",
              Path("/usr/share/arclight/logo"), REPO / "art/eclipse/logo/icons"):
        if (d / name).exists():
            return d / name
    return None


def palette():
    try:
        from arclight.apps import glass
        p = glass.palette()
    except Exception:
        p = {"gold": "#FFC94A", "gold_soft": "#FFE6B8", "gold_deep": "#E89B2A", "text": "#ECEAE6",
             "accent": "#D08A4E", "base": "#0B0B0D"}
    return p


def nudge_pointer():
    """Hyprland only tells a new window about the pointer once the pointer moves, so until then the arrow
    stays in the middle of the film. A 1px move there and back hands the pointer to us (it then hides)."""
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return
    import json
    import subprocess
    try:
        pos = json.loads(subprocess.run(["hyprctl", "-j", "cursorpos"], capture_output=True, text=True, timeout=2).stdout)
        x, y = int(pos["x"]), int(pos["y"])
        for dx in (1, 0):
            subprocess.run(["hyprctl", "dispatch", f"hl.dsp.cursor.move({{x={x + dx},y={y}}})"],
                           capture_output=True, timeout=2)
    except Exception:
        pass


CSS = """
window.intro { background-color: #000000; }
window.intro button { font-family: "Inter", sans-serif; }
button.intro-skip {
  background: none; border: none; box-shadow: none; padding: 6px 14px; border-radius: 999px;
  color: rgba(236, 234, 230, 0.62); font-size: 15px; font-weight: 500; letter-spacing: 0.5px;
}
button.intro-skip:hover { color: #FFFFFF; background-color: rgba(255, 255, 255, 0.08); }
button.intro-nav {
  min-width: 112px; min-height: 44px; padding: 0 22px; border-radius: 999px; border: none;
  font-size: 16px; font-weight: 600; color: #ECEAE6;
  background-color: rgba(255, 255, 255, 0.07);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.20), inset 0 0 0 1px rgba(255, 255, 255, 0.08);
}
button.intro-nav:hover { background-color: rgba(255, 255, 255, 0.13);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.24), inset 0 0 0 1px rgba($gold_rgb, 0.45); }
button.intro-nav.next { color: #1A1206; background-image: linear-gradient(to bottom, $gold_soft, $gold 55%, $gold_deep);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55), 0 0 22px rgba($gold_rgb, 0.28); }
button.intro-nav.next:hover { box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65), 0 0 30px rgba($gold_rgb, 0.45); }
button.intro-start {
  min-width: 220px; min-height: 58px; border-radius: 999px; border: none; padding: 0 40px;
  font-size: 20px; font-weight: 700; letter-spacing: 0.5px; color: #1A1206;
  background-image: linear-gradient(to bottom, $gold_soft, $gold 55%, $gold_deep);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 0 34px rgba($gold_rgb, 0.40), 0 10px 30px rgba(0, 0, 0, 0.5);
}
button.intro-start:hover { box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7), 0 0 46px rgba($gold_rgb, 0.6), 0 10px 30px rgba(0, 0, 0, 0.5); }
button:focus-visible { outline: 2px solid rgba($gold_rgb, 0.8); outline-offset: 2px; }
"""


def build(app, mode, render_dir=None, force_lite=False):
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gsk", "4.0")
    gi.require_version("Graphene", "1.0")
    gi.require_version("Pango", "1.0")
    from gi.repository import Gdk, GLib, GObject, Graphene, Gsk, Gtk, Pango

    pal = palette()

    def hexrgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    GOLD, GOLD_SOFT, GOLD_DEEP = hexrgb(pal["gold"]), hexrgb(pal["gold_soft"]), hexrgb(pal["gold_deep"])
    TEXT = hexrgb(pal.get("text", "#ECEAE6"))

    def C(rgb, a=1.0):
        return Gdk.RGBA(red=rgb[0], green=rgb[1], blue=rgb[2], alpha=clamp(a))

    BLACK = (0.0, 0.0, 0.0)
    WHITE = (1.0, 1.0, 1.0)

    def R(x, y, w, h):
        return Graphene.Rect().init(x, y, w, h)

    def P(x, y):
        return Graphene.Point().init(x, y)

    def RR(x, y, w, h, r):
        rr = Gsk.RoundedRect()
        rr.init_from_rect(R(x, y, w, h), r)
        return rr

    def stops(*pairs):
        out = []
        for off, col in pairs:
            s = Gsk.ColorStop()
            s.offset = off
            s.color = col
            out.append(s)
        return out

    def tex(name):
        f = find(name)
        if not f:
            return None
        try:
            return Gdk.Texture.new_from_filename(str(f))
        except Exception:
            return None

    SC = scenes()
    PAGES = ["opening"] + [s["id"] for s in SC] + ["finale"]
    T = {"photo": tex("arclight-eclipse.jpg"), "crescent": tex("intro-crescent.jpg") or tex("arclight-eclipse-crescent.jpg"),
         "backdrop": tex("intro-backdrop.jpg"), "bloom": tex("intro-bloom.jpg"),
         "bloom_c": tex("intro-bloom-crescent.jpg"), "logo": tex("eclipse-logo-512.png") or tex("eclipse-logo.png")}
    for s in SC:
        T[s["id"]] = tex(s["img"])
    NAME = os_name()
    WHO = first_name()

    class Stage(Gtk.Widget):
        __gtype_name__ = "ArclightIntroStage"

        def __init__(self):
            super().__init__()
            self.set_hexpand(True)
            self.set_vexpand(True)
            self.page, self.prev, self.dir = 0, None, 1
            self.prev_start = 0.0
            self.closing = None
            self.t0 = None              # start of the film (s)
            self.page_start = 0.0
            self.switch = -100.0        # time of the last page change
            self.autoplay = True
            self.fake = None            # render mode: fixed clock
            self.lite = force_lite
            self.frames = []            # recent frame times, for the lite decision
            self.mouse = [0.0, 0.0]     # pointer, -1..1
            self.par = [0.0, 0.0]       # smoothed parallax
            self.last = None
            self.nframes, self.lite_at, self.moved, self.nudged = 0, None, -100.0, False
            self.layouts = {}
            self.on_page = None
            self.add_tick_callback(self.tick)
            mc = Gtk.EventControllerMotion()
            mc.connect("motion", self.motion)
            self.add_controller(mc)

        # ---------------------------------------------------------- clock
        def now(self):
            if self.fake is not None:
                return self.fake
            clock = self.get_frame_clock()
            if clock:
                return clock.get_frame_time() / 1e6
            return GLib.get_monotonic_time() / 1e6

        def tick(self, _w, clock):
            now = clock.get_frame_time() / 1e6
            if self.fake is not None:
                return GLib.SOURCE_CONTINUE
            if self.t0 is None:
                self.t0 = now
                self.page_start = now
            if self.last is not None:
                dt = max(0.0, min(0.25, now - self.last))
                k = 1 - math.exp(-dt / 0.45)
                self.par[0] += (self.mouse[0] - self.par[0]) * k
                self.par[1] += (self.mouse[1] - self.par[1]) * k
                if not self.lite and now - self.t0 > 0.8:
                    self.frames.append(dt)
                    if len(self.frames) >= 45:
                        med = sorted(self.frames)[len(self.frames) // 2]
                        if med > 0.034:      # under ~30 fps: drop blur/blend layers, keep the timing
                            self.lite = True
                            self.lite_at = now - self.t0
                        self.frames = self.frames[-30:]
            self.last = now
            self.nframes += 1
            # a film has no pointer: it hides until the mouse moves
            want = "default" if now - self.moved < 1.8 else "none"
            if want != getattr(self, "_cursor", None):
                self._cursor = want
                self.set_cursor_from_name(want)
            if not self.nudged and now - self.t0 > 0.3:
                self.nudged = True
                nudge_pointer()
            # autoplay
            lt = now - self.page_start
            name = PAGES[self.page]
            if self.autoplay and name != "finale":
                if (name == "opening" and lt > OPENING_LEN) or (name != "opening" and lt > SCENE_LEN):
                    self.go(1, manual=False)
            if self.on_page:
                self.on_page(now)
            self.queue_draw()
            return GLib.SOURCE_CONTINUE

        def motion(self, _c, x, y):
            w, h = max(1, self.get_width()), max(1, self.get_height())
            m = [clamp(x / w * 2 - 1, -1, 1), clamp(y / h * 2 - 1, -1, 1)]
            if abs(m[0] - self.mouse[0]) + abs(m[1] - self.mouse[1]) > 0.004:
                self.moved = self.now()
            self.mouse = m

        def go(self, d, manual=True):
            n = self.page + d
            if n < 0 or n >= len(PAGES):
                return False
            now = self.now()
            if manual:
                self.autoplay = False
                # a press during a transition finishes it first, so pages never pile up
                if now - self.switch < TRANS * 0.35:
                    return False
            self.prev, self.page, self.dir = self.page, n, (1 if d > 0 else -1)
            self.prev_start = self.page_start     # the leaving page keeps its own clock
            self.switch = now
            self.page_start = now + TRANS * 0.28     # the new page's own clock starts when it arrives
            return True

        # ---------------------------------------------------------- text
        def layout(self, key, text, family, weight, px, width=None, spacing=0.0, align=None):
            k = (key, text, round(px, 2), width and round(width), round(spacing, 2))
            lay = self.layouts.get(k)
            if lay is None:
                if len(self.layouts) > 400:
                    self.layouts.clear()
                lay = self.create_pango_layout(text)
                fd = Pango.FontDescription.from_string(family)
                fd.set_weight(weight)
                fd.set_absolute_size(px * Pango.SCALE)
                lay.set_font_description(fd)
                if width:
                    lay.set_width(int(width * Pango.SCALE))
                    lay.set_wrap(Pango.WrapMode.WORD)
                if align is not None:
                    lay.set_alignment(align)
                attrs = Pango.AttrList()
                if spacing:
                    attrs.insert(Pango.attr_letter_spacing_new(int(spacing * Pango.SCALE)))
                attrs.insert(Pango.attr_font_features_new("ss01 1, cv11 1"))
                lay.set_attributes(attrs)
                self.layouts[k] = lay
            return lay

        def text(self, s, lay, x, y, rgb, a, blur=0.0, rise=0.0):
            if a <= 0.003:
                return
            s.save()
            s.translate(P(x, y + rise))
            if blur > 0.4 and not self.lite:
                s.push_blur(blur)
                s.append_layout(lay, C(rgb, a))
                s.pop()
            else:
                s.append_layout(lay, C(rgb, a))
            s.restore()

        # ---------------------------------------------------------- pictures
        @staticmethod
        def place(texture, w, h, scale, focus, drift=(0.0, 0.0)):
            """Rect (x, y, w, h) where `texture` covers w x h, zoomed by `scale` about image point `focus`."""
            iw, ih = texture.get_width(), texture.get_height()
            base = max(w / iw, h / ih)
            dw1, dh1 = iw * base, ih * base
            x1, y1 = (w - dw1) / 2, (h - dh1) / 2
            fx, fy = x1 + focus[0] * dw1, y1 + focus[1] * dh1
            dw, dh = dw1 * scale, dh1 * scale
            return (clamp(fx - focus[0] * dw + drift[0], w - dw, 0), clamp(fy - focus[1] * dh + drift[1], h - dh, 0), dw, dh)

        def paint(self, s, texture, rect, alpha=1.0, bloom=None, bloom_a=0.0):
            """Draw `texture` in rect; optional bloom layer screen-blended on top (skipped in lite mode)."""
            if texture is None or alpha <= 0.003:
                return
            r = R(*rect)
            if alpha < 0.997:
                s.push_opacity(alpha)
            if bloom is not None and bloom_a > 0.01 and not self.lite:
                s.push_blend(Gsk.BlendMode.SCREEN)
                s.append_scaled_texture(texture, Gsk.ScalingFilter.LINEAR, r)
                s.pop()
                s.push_opacity(clamp(bloom_a))
                s.append_scaled_texture(bloom, Gsk.ScalingFilter.LINEAR, r)
                s.pop()
                s.pop()
            else:
                s.append_scaled_texture(texture, Gsk.ScalingFilter.LINEAR, r)
            if alpha < 0.997:
                s.pop()

        def cover(self, s, texture, w, h, scale, focus, alpha=1.0, drift=(0.0, 0.0), bloom=None, bloom_a=0.0):
            if texture is not None:
                self.paint(s, texture, self.place(texture, w, h, scale, focus, drift), alpha, bloom, bloom_a)

        def shade(self, s, w, h, a):
            if a > 0.003:
                s.append_color(C(BLACK, a), R(0, 0, w, h))

        def vignette(self, s, w, h, a):
            if a <= 0.003:
                return
            s.append_radial_gradient(R(0, 0, w, h), P(w / 2, h * 0.46), w * 0.78, h * 0.86, 0.0, 1.0,
                                     stops((0.0, C(BLACK, 0)), (0.55, C(BLACK, 0.18 * a)), (1.0, C(BLACK, 0.82 * a))))

        # ---------------------------------------------------------- glass pieces
        def keycap(self, s, u, x, y, label, a, lit=False):
            lay = self.layout("key", label, "Inter", Pango.Weight.SEMIBOLD, 17 * u)
            tw, th = lay.get_pixel_size()
            kh = 46 * u
            kw = max(kh, tw + 30 * u)
            rr = RR(x, y, kw, kh, 11 * u)
            s.push_opacity(a)
            if not self.lite:
                s.append_outset_shadow(rr, C(BLACK, 0.45), 0, 5 * u, 0, 12 * u)
            s.push_rounded_clip(rr)
            s.append_linear_gradient(R(x, y, kw, kh), P(x, y), P(x, y + kh),
                                     stops((0.0, C(WHITE, 0.17)), (0.5, C(WHITE, 0.08)), (1.0, C(WHITE, 0.05))))
            if lit:
                s.append_radial_gradient(R(x, y, kw, kh), P(x + kw / 2, y + kh), kw * 0.7, kh * 0.9, 0, 1,
                                         stops((0.0, C(GOLD, 0.30)), (1.0, C(GOLD, 0.0))))
            s.pop()
            rim = C(GOLD, 0.55) if lit else C(WHITE, 0.13)
            s.append_border(rr, [1, 1, 1, 1], [C(WHITE, 0.32), rim, C(BLACK, 0.4), rim])
            s.save()
            s.translate(P(x + (kw - tw) / 2, y + (kh - th) / 2 - 1 * u))
            s.append_layout(lay, C(GOLD_SOFT if lit else WHITE, 0.96))
            s.restore()
            s.pop()
            return kw

        def combo(self, s, u, x, y, keys, label, a):
            cx = x
            for i, k in enumerate(keys):
                cx += self.keycap(s, u, cx, y, k, a, lit=(i == len(keys) - 1))
                if i < len(keys) - 1:
                    plus = self.layout("plus", "+", "Inter", Pango.Weight.LIGHT, 18 * u)
                    pw, ph = plus.get_pixel_size()
                    self.text(s, plus, cx + 8 * u, y + (46 * u - ph) / 2, WHITE, 0.45 * a)
                    cx += pw + 16 * u
            lab = self.layout("klabel", label, "Inter", Pango.Weight.MEDIUM, 19 * u)
            lw, lh = lab.get_pixel_size()
            self.text(s, lab, cx + 20 * u, y + (46 * u - lh) / 2, TEXT, 0.80 * a)

        def card(self, s, u, w, h, texture, lt, presence, glow=0.0):
            """A real screenshot floating on glass: perspective tilt, depth layers, a sheen that sweeps once."""
            if texture is None:
                return
            ap = abs(presence)
            vis = 1 - ease_in_out(ap)
            if vis <= 0.003:
                return
            iw, ih = texture.get_width(), texture.get_height()
            cw = 940 * u
            ch = cw * ih / iw
            if ch > 640 * u:
                ch = 640 * u
                cw = ch * iw / ih
            cx, cy = w - 110 * u - cw / 2, h * 0.5 - 10 * u
            enter = ease_out_expo(seg(lt, 0.0, 1.5)) if presence >= 0 else 1.0
            px, py = self.par
            ang_y = -10 + 1.6 * math.sin(lt * 0.42) + 3.2 * px - 16 * presence
            ang_x = 3.5 - 1.0 * math.sin(lt * 0.33 + 1) - 2.2 * py
            dx = (220 if presence > 0 else 110) * u * presence + (1 - enter) * 120 * u - 10 * u * px
            dy = 7 * u * math.sin(lt * 0.6) + (1 - enter) * 26 * u - 8 * u * py
            sc = 1 - 0.07 * ap + 0.035 * (1 - enter) * -1
            s.push_opacity(vis)
            # back glass plate (deeper layer: moves less)
            s.save()
            s.translate(P(cx + dx * 0.55, cy + dy * 0.5))
            s.perspective(2200 * u)
            s.rotate_3d(ang_y * 0.75, Graphene.vec3_y_axis())
            s.rotate_3d(ang_x * 0.75, Graphene.vec3_x_axis())
            s.scale(sc, sc)
            pw, ph = cw + 64 * u, ch + 64 * u
            plate = RR(-pw / 2, -ph / 2, pw, ph, 32 * u)
            if not self.lite:
                s.append_outset_shadow(plate, C(BLACK, 0.55), 0, 30 * u, 0, 60 * u)
            s.push_rounded_clip(plate)
            s.append_linear_gradient(R(-pw / 2, -ph / 2, pw, ph), P(-pw / 2, -ph / 2), P(pw / 2, ph / 2),
                                     stops((0.0, C(WHITE, 0.11)), (0.45, C(WHITE, 0.04)), (1.0, C(WHITE, 0.07))))
            s.append_radial_gradient(R(-pw / 2, -ph / 2, pw, ph), P(-pw / 2, -ph / 2), pw * 0.6, ph * 0.6, 0, 1,
                                     stops((0.0, C(GOLD, 0.14)), (1.0, C(GOLD, 0.0))))
            s.pop()
            s.append_border(plate, [1, 1, 1, 1], [C(WHITE, 0.26), C(WHITE, 0.08), C(WHITE, 0.05), C(WHITE, 0.10)])
            s.restore()
            # the screenshot
            s.save()
            s.translate(P(cx + dx, cy + dy))
            s.perspective(2200 * u)
            s.rotate_3d(ang_y, Graphene.vec3_y_axis())
            s.rotate_3d(ang_x, Graphene.vec3_x_axis())
            s.scale(sc, sc)
            rr = RR(-cw / 2, -ch / 2, cw, ch, 18 * u)
            if not self.lite:
                s.append_outset_shadow(rr, C(BLACK, 0.6), 0, 18 * u, 0, 40 * u)
                if glow > 0.01:
                    s.append_outset_shadow(rr, C(GOLD, 0.30 * glow), 0, 0, 2 * u, 70 * u)
            elif glow > 0.01:
                s.append_outset_shadow(rr, C(GOLD, 0.22 * glow), 0, 0, 6 * u, 0)
            s.push_rounded_clip(rr)
            s.append_scaled_texture(texture, Gsk.ScalingFilter.TRILINEAR, R(-cw / 2, -ch / 2, cw, ch))
            # one slow sheen across the glass as it lands
            sw = seg(lt, 0.35, 2.4)
            if 0 < sw < 1:
                sx = -cw / 2 - cw * 0.5 + sw * cw * 2.0
                a = 0.16 * math.sin(math.pi * sw)
                s.append_linear_gradient(R(-cw / 2, -ch / 2, cw, ch), P(sx - cw * 0.25, -ch / 2), P(sx + cw * 0.25, ch / 2),
                                         stops((0.0, C(WHITE, 0)), (0.5, C(WHITE, a)), (1.0, C(WHITE, 0))))
            s.append_linear_gradient(R(-cw / 2, -ch / 2, cw, ch), P(0, -ch / 2), P(0, ch / 2),
                                     stops((0.0, C(WHITE, 0.07)), (0.25, C(WHITE, 0.0)), (1.0, C(BLACK, 0.12))))
            s.pop()
            s.append_border(rr, [1, 1, 1, 1], [C(WHITE, 0.34), C(WHITE, 0.12), C(BLACK, 0.5), C(WHITE, 0.12)])
            s.restore()
            s.pop()

        # ---------------------------------------------------------- pages
        def bg(self, s, name, w, h, lt, alpha):
            """Background layer of a page (drawn under the foregrounds; the incoming one fades over the old)."""
            if name == "opening":
                self.opening_bg(s, w, h, lt, alpha)
            elif name == "finale":
                s.push_opacity(alpha)
                s.append_color(C(BLACK), R(0, 0, w, h))
                kb = 1.10 + 0.05 * ease_in_out(seg(lt, 0, 16))
                breath = 0.5 + 0.5 * math.sin(lt * 1.1)
                self.cover(s, T["photo"], w, h, kb, (0.62, 0.30), 1.0, bloom=T["bloom"], bloom_a=0.45 + 0.25 * breath)
                self.shade(s, w, h, 0.42)
                self.vignette(s, w, h, 1.0)
                s.pop()
            else:
                s.push_opacity(alpha)
                s.append_color(C(BLACK), R(0, 0, w, h))
                tt = self.now() - (self.t0 or 0)
                drift = (-30 * math.sin(tt * 0.05), -14 * math.sin(tt * 0.07 + 1))
                self.cover(s, T["backdrop"], w, h, 1.12, (0.5, 0.45), 1.0, drift=drift)
                # text side darker, so the words always read
                s.append_linear_gradient(R(0, 0, w, h), P(0, 0), P(w, 0),
                                         stops((0.0, C(BLACK, 0.55)), (0.42, C(BLACK, 0.25)), (1.0, C(BLACK, 0.05))))
                if name == "totality":
                    # the moon slides over: everything else dims as the scene plays
                    self.shade(s, w, h, 0.55 * ease_in_out(seg(lt, 0.6, 3.2)))
                self.vignette(s, w, h, 0.9)
                s.pop()

        def opening_bg(self, s, w, h, lt, alpha):
            s.push_opacity(alpha)
            # the eclipse photo: dissolves in under the crescent, slow push-in, the corona blooms
            pa = ease_in_out(seg(lt, 3.7, 6.0))
            kb = 1.03 + 0.09 * ease_in_out(seg(lt, 3.5, 17.0))
            corona = 0.25 + 0.55 * ease_out(seg(lt, 4.6, 7.2)) + 0.12 * math.sin(lt * 1.3) * seg(lt, 6, 8)
            photo = T["photo"]
            prect = self.place(photo, w, h, kb, (0.60, 0.26)) if photo is not None else (0, 0, w, h)
            # the crescent: emerges from black, the diamond ring flares, then it shrinks onto the photo's sun
            # (a match cut: its moon lands exactly on the photo's moon) and melts into the corona
            cres = T["crescent"]
            ca = ease_in_out(seg(lt, 0.6, 3.0)) * (1 - ease_in_out(seg(lt, 5.0, 6.6)))
            flare = bump(lt, 1.4, 2.9, 4.6)
            crect = None
            if cres is not None and ca > 0.003:
                cz = 1.14 - 0.08 * ease_out(seg(lt, 0.0, 6.0))
                x0, y0, dw, dh = self.place(cres, w, h, cz, DIAMOND)
                mx, my, mr = x0 + MOON_C[0] * dw, y0 + MOON_C[1] * dh, MOON_C[2] * dh
                sx, sy, sr = prect[0] + SUN[0] * prect[2], prect[1] + SUN[1] * prect[3], SUN_R * prect[3]
                k = ease_in_out(seg(lt, 3.2, 5.9))
                r = math.exp(lerp(math.log(mr), math.log(sr), k))
                m = r / mr
                cx, cy = lerp(mx, sx, k), lerp(my, sy, k)
                crect = (cx - (mx - x0) * m, cy - (my - y0) * m, dw * m, dh * m)
            if crect is not None and not self.lite:
                s.push_blend(Gsk.BlendMode.SCREEN)       # bottom: black + photo
            s.append_color(C(BLACK), R(0, 0, w, h))
            self.paint(s, photo, prect, pa, bloom=T["bloom"], bloom_a=corona)
            # the sky on the left dims for the title
            da = ease_in_out(seg(lt, 5.2, 6.8))
            if da > 0:
                s.append_linear_gradient(R(0, 0, w, h), P(0, 0), P(w * 0.75, h * 0.25),
                                         stops((0.0, C(BLACK, 0.72 * da)), (0.55, C(BLACK, 0.30 * da)), (1.0, C(BLACK, 0))))
                s.append_linear_gradient(R(0, 0, w, h), P(0, h * 0.55), P(0, h),
                                         stops((0.0, C(BLACK, 0)), (1.0, C(BLACK, 0.45 * da))))
            self.vignette(s, w, h, 0.85 * pa)
            if crect is not None:
                if not self.lite:
                    s.pop()                                  # top: the crescent, light only (screen)
                    self.paint(s, cres, crect, ca, bloom=T["bloom_c"], bloom_a=0.25 + 0.95 * flare)
                    s.pop()
                else:                                        # lite: a plain cross-fade
                    self.paint(s, cres, crect, ca * (1 - pa))
            s.pop()

        def opening_fg(self, s, w, h, u, lt, presence):
            vis = 1 - ease_in_out(abs(presence))
            if vis <= 0.003:
                return
            x0 = 150 * u - 90 * u * max(0.0, -presence)
            s.push_opacity(vis)
            # logo
            la = ease_out(seg(lt, 5.5, 7.0))
            if T["logo"] is not None and la > 0:
                ls = 168 * u * (0.86 + 0.14 * ease_out_expo(seg(lt, 5.5, 7.4)))
                lx, ly = x0 - 22 * u - (ls - 168 * u) / 2, 128 * u - (ls - 168 * u) / 2
                # a warm halo first, then the photo logo itself
                s.append_radial_gradient(R(lx - ls, ly - ls, ls * 3, ls * 3), P(lx + ls / 2, ly + ls / 2), ls * 1.2, ls * 1.2,
                                         0, 1, stops((0.0, C(GOLD, 0.22 * la)), (1.0, C(GOLD, 0.0))))
                s.push_opacity(la)
                s.append_scaled_texture(T["logo"], Gsk.ScalingFilter.TRILINEAR, R(lx, ly, ls, ls))
                s.pop()
            # the name, letters gathering in
            ta = ease_out(seg(lt, 5.9, 7.6))
            spacing = lerp(34, 1.5, ease_out_expo(seg(lt, 5.9, 8.4))) * u
            size = 112 * u
            lay = self.layout("title", NAME, "Inter Display", Pango.Weight.SEMIBOLD, size, spacing=spacing)
            tw, th = lay.get_pixel_size()
            if tw > w * 0.62:     # a long name chosen at install still fits
                size *= w * 0.62 / tw
                lay = self.layout("title", NAME, "Inter Display", Pango.Weight.SEMIBOLD, size, spacing=spacing)
                tw, th = lay.get_pixel_size()
            self.text(s, lay, x0 - 4 * u, 310 * u, WHITE, ta, blur=10 * u * (1 - ta), rise=10 * u * (1 - ta))
            # corona line
            lw = 440 * u * ease_out_expo(seg(lt, 6.6, 8.2))
            if lw > 1:
                ly = 310 * u + th + 16 * u
                s.append_linear_gradient(R(x0, ly, lw, 2 * u), P(x0, ly), P(x0 + lw, ly),
                                         stops((0.0, C(GOLD, 0.0)), (0.25, C(GOLD, 0.95)), (1.0, C(GOLD_SOFT, 0.0))))
            # welcome
            wa = ease_out(seg(lt, 7.3, 8.8))
            wl = self.layout("welcome", f"Welcome, {WHO}" if WHO else "Welcome", "Inter Display", Pango.Weight.MEDIUM, 40 * u)
            self.text(s, wl, x0, 310 * u + th + 44 * u, GOLD_SOFT, wa, blur=6 * u * (1 - wa), rise=14 * u * (1 - wa))
            s.pop()

        def scene_fg(self, s, sc, w, h, u, lt, presence):
            vis = 1 - ease_in_out(abs(presence))
            if vis <= 0.003:
                return
            glow = ease_in_out(seg(lt, 1.2, 3.4)) if sc["id"] == "totality" else 0.25
            self.card(s, u, w, h, T.get(sc["id"]), lt, presence, glow=glow)
            # words: staggered rise + unblur
            x0 = 150 * u - 140 * u * presence
            colw = min(700 * u, w * 0.37)
            kick = self.layout("kick", sc["kicker"], "Inter", Pango.Weight.BOLD, 15 * u, spacing=4 * u)
            title = self.layout("stitle", sc["title"], "Inter Display", Pango.Weight.SEMIBOLD, 58 * u, width=colw)
            line = self.layout("sline", sc["line"], "Inter", Pango.Weight.NORMAL, 23 * u, width=colw)
            _, kh = kick.get_pixel_size()
            _, th = title.get_pixel_size()
            _, lh = line.get_pixel_size()
            keys_h = len(sc["keys"]) * 62 * u
            total = kh + 18 * u + th + 22 * u + lh + 44 * u + keys_h
            y = h * 0.5 - total / 2 - 6 * u

            def stag(d):
                a = ease_out(seg(lt, d, d + 0.8)) if presence >= 0 else 1.0
                return a * vis, (1 - a)

            a, r = stag(0.15)
            self.text(s, kick, x0, y, GOLD, a, blur=6 * u * r, rise=16 * u * r)
            # thin gold tick before the kicker
            y += kh + 18 * u
            a, r = stag(0.28)
            self.text(s, title, x0, y, WHITE, a, blur=10 * u * r, rise=22 * u * r)
            y += th + 22 * u
            a, r = stag(0.44)
            self.text(s, line, x0, y, TEXT, 0.78 * a, blur=6 * u * r, rise=18 * u * r)
            y += lh + 44 * u
            for i, (keys, label) in enumerate(sc["keys"]):
                a, r = stag(0.62 + i * 0.12)
                if a > 0.003:
                    s.save()
                    s.translate(P(0, 16 * u * r))
                    self.combo(s, u, x0, y, keys, label, a)
                    s.restore()
                y += 62 * u

        def finale_fg(self, s, w, h, u, lt, presence):
            vis = 1 - ease_in_out(abs(presence))
            if vis <= 0.003:
                return
            s.push_opacity(vis)
            a = ease_out(seg(lt, 0.35, 1.6))
            title = self.layout("ftitle", "You’re all set.", "Inter Display", Pango.Weight.SEMIBOLD, 104 * u,
                                spacing=lerp(14, 0, ease_out_expo(seg(lt, 0.35, 2.2))) * u)
            tw, th = title.get_pixel_size()
            ty = h * 0.5 - 150 * u
            self.text(s, title, (w - tw) / 2, ty, WHITE, a, blur=10 * u * (1 - a), rise=16 * u * (1 - a))
            lw = 360 * u * ease_out_expo(seg(lt, 0.9, 2.3))
            if lw > 1:
                ly = ty + th + 18 * u
                s.append_linear_gradient(R((w - lw) / 2, ly, lw, 2 * u), P((w - lw) / 2, ly), P((w + lw) / 2, ly),
                                         stops((0.0, C(GOLD, 0.0)), (0.5, C(GOLD, 0.95)), (1.0, C(GOLD, 0.0))))
            b = ease_out(seg(lt, 1.0, 2.2))
            line = self.layout("fline", "Next: a few first steps, like bringing your files back.", "Inter",
                               Pango.Weight.NORMAL, 25 * u)
            lw2, _ = line.get_pixel_size()
            self.text(s, line, (w - lw2) / 2, ty + th + 44 * u, TEXT, 0.80 * b, blur=6 * u * (1 - b), rise=12 * u * (1 - b))
            s.pop()

        def dots(self, s, w, h, u, now):
            n = len(SC)
            # how "scene-like" the screen is, and where the active pill is (both eased through transitions)
            def pos(i):
                return i - 1 if 1 <= i <= n else None

            tp = ease_in_out(seg(now, self.switch, self.switch + TRANS))
            cur, prv = pos(self.page), pos(self.prev) if self.prev is not None else None
            vis_c = 1.0 if cur is not None else 0.0
            vis_p = 1.0 if prv is not None else 0.0
            vis = lerp(vis_p, vis_c, tp) if self.prev is not None else vis_c
            if vis <= 0.003:
                return
            act = lerp(prv if prv is not None else cur if cur is not None else 0,
                       cur if cur is not None else prv if prv is not None else 0, tp)
            gap, dot, pill = 18 * u, 8 * u, 30 * u
            total = (n - 1) * gap + dot * (n - 1) + pill
            x = (w - total) / 2
            y = h - 66 * u - dot / 2
            s.push_opacity(vis)
            lt = now - self.page_start
            for i in range(n):
                k = clamp(1 - abs(i - act))
                dw = lerp(dot, pill, smooth(k))
                rr = RR(x, y, dw, dot, dot / 2)
                s.push_rounded_clip(rr)
                s.append_color(C(WHITE, lerp(0.28, 0.0, k)), R(x, y, dw, dot))
                if k > 0:
                    s.append_color(C(GOLD, 0.35 * k), R(x, y, dw, dot))
                    if self.autoplay and cur is not None and i == cur:
                        s.append_color(C(GOLD, 0.95 * k), R(x, y, dw * clamp(lt / SCENE_LEN), dot))
                    elif not self.autoplay:
                        s.append_color(C(GOLD, 0.95 * k), R(x, y, dw, dot))
                s.pop()
                x += dw + gap
            s.pop()

        def page_draw(self, s, idx, w, h, u, lt, presence, layer):
            name = PAGES[idx]
            if layer == "bg":
                return
            if name == "opening":
                self.opening_fg(s, w, h, u, lt, presence)
            elif name == "finale":
                self.finale_fg(s, w, h, u, lt, presence)
            else:
                self.scene_fg(s, SC[idx - 1], w, h, u, lt, presence)

        def do_snapshot(self, s):
            w, h = float(self.get_width()), float(self.get_height())
            if w < 2 or h < 2:
                return
            u = min(w / BASE_W, h / BASE_H)
            now = self.now()
            if self.t0 is None:
                s.append_color(C(BLACK), R(0, 0, w, h))
                return
            lt = now - self.page_start
            tp = seg(now, self.switch, self.switch + TRANS)
            if self.prev is not None and tp < 1:
                plt = now - self.prev_start
                # backgrounds cross-fade over the whole transition; the old page leaves first, the new one
                # arrives after it (overlapping a little), so two pages never sit on top of each other
                self.bg(s, PAGES[self.prev], w, h, plt, 1.0)
                self.bg(s, PAGES[self.page], w, h, lt, ease_in_out(tp))
                self.page_draw(s, self.prev, w, h, u, plt, -self.dir * ease_in_out(seg(tp, 0.0, 0.5)), "fg")
                self.page_draw(s, self.page, w, h, u, lt, self.dir * (1 - ease_in_out(seg(tp, 0.28, 1.0))), "fg")
            else:
                self.bg(s, PAGES[self.page], w, h, lt, 1.0)
                self.page_draw(s, self.page, w, h, u, lt, 0.0, "fg")
            self.dots(s, w, h, u, now)
            # the film begins and ends in black
            if PAGES[self.page] == "opening":
                self.shade(s, w, h, 1 - ease_in_out(seg(lt, 0.0, 0.6)) if lt < 0.6 else 0)
            if self.closing is not None:
                self.shade(s, w, h, ease_in_out(seg(now, self.closing, self.closing + 0.45)))

    # ---------------------------------------------------------------- window
    from arclight.apps import glass
    glass.install(CSS)
    win = Gtk.ApplicationWindow(application=app, title=f"{NAME} intro")
    win.add_css_class("intro")
    win.set_decorated(False)
    stage = Stage()
    ov = Gtk.Overlay()
    ov.set_child(stage)

    skip = Gtk.Button(label="Skip", halign=Gtk.Align.END, valign=Gtk.Align.START, margin_top=26, margin_end=30)
    skip.add_css_class("intro-skip")
    skip.set_tooltip_text("Skip the intro (Esc)")
    ov.add_overlay(skip)

    nav = Gtk.Box(spacing=0, halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=44)
    back = Gtk.Button(label="Back")
    back.add_css_class("intro-nav")
    nxt = Gtk.Button(label="Next")
    nxt.add_css_class("intro-nav")
    nxt.add_css_class("next")
    gapbox = Gtk.Box(width_request=330)
    nav.append(back)
    nav.append(gapbox)
    nav.append(nxt)
    ov.add_overlay(nav)

    start = Gtk.Button(label="Start", halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
    start.add_css_class("intro-start")
    ov.add_overlay(start)
    for wdg in (skip, nav, start):
        ov.set_measure_overlay(wdg, False)
    win.set_child(ov)

    def finish(*_a):
        if stage.closing is None and stage.t0 is not None:
            el = stage.now() - stage.t0
            print(f"arclight-intro: {stage.nframes} frames in {el:.1f} s ({stage.nframes / max(el, 0.01):.0f} fps), "
                  f"lite={'yes (from %.1f s)' % stage.lite_at if stage.lite_at is not None else stage.lite}", file=sys.stderr)
        if stage.closing is None:
            stage.closing = stage.now()
            GLib.timeout_add(480, lambda: (app.quit(), False)[1])

    skip.connect("clicked", finish)
    start.connect("clicked", finish)
    back.connect("clicked", lambda _b: stage.go(-1))
    nxt.connect("clicked", lambda _b: stage.go(1))

    def controls(now):
        """Fade the real buttons with the film (they stay clickable only while visible)."""
        if stage.t0 is None:
            return
        name = PAGES[stage.page]
        lt = now - stage.page_start
        tp = ease_in_out(seg(now, stage.switch, stage.switch + TRANS))
        sk = ease_out(seg(now - stage.t0, 1.2, 2.4)) * (0.0 if name == "finale" else 1.0)
        def scene_like(i):
            return 0.0 if PAGES[i] in ("opening", "finale") else 1.0
        nv = lerp(scene_like(stage.prev), scene_like(stage.page), tp) if stage.prev is not None else scene_like(stage.page)
        st = ease_out(seg(lt, 1.6, 2.6)) if name == "finale" else 0.0
        for wdg, a in ((skip, sk), (nav, nv), (start, st)):
            wdg.set_opacity(a)
            wdg.set_can_target(a > 0.5)
            wdg.set_visible(a > 0.003)
        back.set_sensitive(stage.page > 1)
        nxt.set_label("Finish" if stage.page == len(PAGES) - 2 else "Next")
        hgt = stage.get_height()
        u = min(stage.get_width() / BASE_W, hgt / BASE_H) if hgt else 1
        mt = int(hgt * 0.5 + 60 * u)
        if start.get_margin_top() != mt:
            start.set_margin_top(mt)
        gw = int(330 * u)
        if gapbox.get_size_request()[0] != gw:
            gapbox.set_size_request(gw, -1)

    stage.on_page = controls

    kc = Gtk.EventControllerKey()

    def key(_c, kv, _code, _state):
        if kv == Gdk.KEY_Escape:
            finish()
        elif kv in (Gdk.KEY_space, Gdk.KEY_Right, Gdk.KEY_Page_Down):
            if PAGES[stage.page] == "finale":
                finish()
            else:
                stage.go(1)
        elif kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if PAGES[stage.page] == "finale":
                finish()
            else:
                return False   # Enter activates the focused button
        elif kv in (Gdk.KEY_Left, Gdk.KEY_Page_Up, Gdk.KEY_BackSpace):
            if stage.page > 1:
                stage.go(-1)
        else:
            return False
        return True

    kc.connect("key-pressed", key)
    kc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    win.add_controller(kc)

    if render_dir:
        return render(win, stage, controls, PAGES, render_dir, Gtk, Gsk, Graphene, GLib, app)
    win.fullscreen()
    win.present()
    return win


def render(win, stage, controls, PAGES, out, Gtk, Gsk, Graphene, GLib, app):
    """Developer stills: every page at a few moments, plus mid-transition frames (fixed clock)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    win.set_default_size(1920, 1080)
    win.present()
    n = len(PAGES)
    plan = [(f"opening-{x:04.1f}s", 0, x, None, 0) for x in (0.4, 1.6, 2.6, 3.6, 4.4, 5.2, 6.0, 6.8, 7.6, 9.5)]
    plan += [(f"trans-opening-{x:.2f}", 1, x * TRANS, 0, 10.0) for x in (0.25, 0.5, 0.75)]
    for i in range(1, n - 1):
        name = PAGES[i]
        plan += [(f"scene{i}-{name}-{x:.1f}s", i, x, None, 0) for x in (0.4, 1.0, 4.0)]
        plan += [(f"trans{i}-{name}-{x:.2f}", i + 1, x * TRANS, i, 6.0) for x in (0.25, 0.5, 0.75)]
    plan += [(f"zfinale-{x:.1f}s", n - 1, x, None, 0) for x in (1.0, 3.0)]
    plan = [(f"{k:02d}-{p[0]}",) + p[1:] for k, p in enumerate(plan)]
    base = 1000.0

    def shoot():
        try:
            shoot_all()
        finally:
            app.quit()
        return False

    def shoot_all():
        for fname, page, lt, prev, prev_lt in plan:
            now = base + 100
            stage.fake = now
            stage.t0 = base
            stage.page = page
            stage.page_start = now - lt
            stage.autoplay = True
            if prev is not None:      # lt = time since the switch
                stage.prev = prev
                stage.dir = 1
                stage.switch = now - lt
                stage.page_start = stage.switch + TRANS * 0.28
                stage.prev_start = stage.switch - prev_lt
            else:
                stage.prev = None
                stage.switch = -100.0
            controls(now)
            # let GTK lay out the buttons for this state
            ctx = GLib.MainContext.default()
            for _ in range(20):
                ctx.iteration(False)
            stage.queue_draw()
            for _ in range(5):
                ctx.iteration(False)
            ov = win.get_child()
            w, h = ov.get_width(), ov.get_height()
            snap = Gtk.Snapshot()
            stage.do_snapshot(snap)
            c = ov.get_first_child()
            while c is not None:          # the real buttons on top (skip, nav, start)
                if c is not stage and c.get_visible():
                    ov.snapshot_child(c, snap)
                c = c.get_next_sibling()
            node = snap.to_node()
            if node is None:
                print(f"render: nothing drawn for {fname} ({w}x{h})", flush=True)
                continue
            texture = win.get_renderer().render_texture(node, Graphene.Rect().init(0, 0, w, h))
            texture.save_to_png(str(out / f"{fname}.png"))
            print(out / f"{fname}.png", flush=True)

    GLib.timeout_add(1500, shoot)
    return win


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="arclight-intro", description="the cinematic first-boot intro")
    p.add_argument("--replay", action="store_true", help="play it again")
    p.add_argument("--first-boot", action="store_true", help="run by the session on the first login")
    p.add_argument("--lite", action="store_true", help="no blur or bloom layers (slow graphics)")
    p.add_argument("--render-shots", metavar="DIR", help="developer: render stills of every scene")
    a = p.parse_args(argv)
    if not (a.replay or a.first_boot or a.render_shots):
        # bare call: only the genuine first boot of an installed system plays it, and only once
        if Path("/run/archiso").exists() or not PENDING.exists():
            print("arclight-intro: already played on this install (arclight-intro --replay plays it again)")
            return 0
        PENDING.unlink(missing_ok=True)
        try:
            DONE.write_text(time.strftime("%Y-%m-%d %H:%M:%S\n"))
        except OSError:
            pass
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio, Gtk
    app = Gtk.Application(application_id="dev.arclight.Intro",
                          flags=Gio.ApplicationFlags.NON_UNIQUE if a.render_shots else Gio.ApplicationFlags.DEFAULT_FLAGS)
    def activate(ap):
        if ap.get_windows():          # already playing: bring it forward instead of a second film
            ap.get_windows()[0].present()
            return
        build(ap, "replay", a.render_shots, a.lite or os.environ.get("ARCLIGHT_INTRO_LITE") == "1")
    app.connect("activate", activate)
    return app.run([])


if __name__ == "__main__":
    sys.exit(main())
