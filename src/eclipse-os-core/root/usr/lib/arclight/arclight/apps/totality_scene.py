"""Totality: the picture. Pure drawing, no windows and no clock: `draw()` renders one frame of the
eclipse for a set of parameters, `enter()` / `exit_()` / `settled()` turn a time in seconds into those
parameters. The overlay (apps/totality.py) feeds the real clock in; tools render the same frames
offscreen for contact sheets.

Everything is procedural (GSK gradients, clips and masks: GPU-drawn where a GPU exists) except the
corona, which is the corona from Arthur's own eclipse photo (the logo), deterministically scaled.
"""
import math
import os
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, Graphene, Gsk  # noqa: E402

# Phase times (seconds, real clock)
DISSOLVE = 0.9        # the desktop melts into sunlight
CONTACT = 2.3         # the moon closes the last sliver: diamond ring, then corona
TEXT_IN, TEXT_HOLD, TEXT_OUT = 2.65, 5.2, 5.9
SETTLE = 6.0          # after this only the slow breathing is left (drawn at a few frames per second)
EXIT = 1.8            # light returns
DARK = 0.90           # how dark everything except the focus window gets
CORONA_DISC = 0.2432  # radius of the dark disc in the corona image, as a fraction of its width

WARM_BLACK = (7, 7, 8)


def _find(*names):
    roots = [Path("/usr/share/arclight/eclipse"), Path(__file__).resolve().parents[3] / "desktop" / "eclipse",
             Path(__file__).resolve().parents[3] / "art" / "eclipse" / "glass",
             Path(__file__).resolve().parents[3] / "art" / "eclipse" / "logo"]
    for n in names:
        for r in roots:
            if (r / n).exists():
                return r / n
    return None


class Textures:
    def __init__(self):
        self.corona = self.noise = None
        p = _find("totality-corona.png", "eclipse-logo.png")
        if p:
            self.corona = Gdk.Texture.new_from_filename(str(p))
        p = _find("totality-grain.png")
        if p:
            self.noise = Gdk.Texture.new_from_filename(str(p))


# ------------------------------------------------------------------ small helpers

def rgba(r, g, b, a=1.0):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r / 255, g / 255, b / 255, max(0.0, min(1.0, a))
    return c


def rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def point(x, y):
    return Graphene.Point().init(x, y)


def stops(spec, mult=1.0):
    out = []
    for off, (r, g, b, a) in spec:
        s = Gsk.ColorStop()
        s.offset = max(0.0, min(1.0, off))
        s.color = rgba(r, g, b, a * mult)
        out.append(s)
    return out


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def smooth(e0, e1, x):
    t = clamp((x - e0) / (e1 - e0)) if e1 != e0 else float(x >= e1)
    return t * t * (3 - 2 * t)


def ease_io(t):
    t = clamp(t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def overlap(r1, r2, d):
    """Area of two overlapping discs (radii r1, r2, centre distance d)."""
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        return math.pi * min(r1, r2) ** 2
    a = r1 * r1 * math.acos(clamp((d * d + r1 * r1 - r2 * r2) / (2 * d * r1), -1, 1))
    b = r2 * r2 * math.acos(clamp((d * d + r2 * r2 - r1 * r1) / (2 * d * r2), -1, 1))
    c = 0.5 * math.sqrt(max(0.0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return a + b - c


# ------------------------------------------------------------------ layout

def _rect_dist(px, py, x, y, w, h):
    dx = max(x - px, 0, px - (x + w))
    dy = max(y - py, 0, py - (y + h))
    return math.hypot(dx, dy)


def layout(W, H, hole):
    """Where the eclipse sits. hole = (x, y, w, h) of the focus window (screen-local) or None.
    'beside': in the biggest free space next to the window, so the whole eclipse is seen.
    'behind': the window fills the screen: the eclipse is centred behind it and its rim and corona
    glow out around the window's edges."""
    m = min(W, H)
    if not hole:
        return {"cx": W / 2, "cy": H * 0.46, "rs": 0.12 * m, "kind": "free"}
    x, y, w, h = hole
    best = (-1, W / 2, H / 2)
    step = max(8, int(m / 60))
    for py in range(step, int(H), step):
        for px in range(step, int(W), step):
            c = min(_rect_dist(px, py, x, y, w, h), px, W - px, py, H - py)
            if c > best[0]:
                best = (c, px, py)
    c, px, py = best
    rs = min(c / 1.95, 0.13 * m)
    if rs >= 0.055 * m:
        return {"cx": px, "cy": py, "rs": rs, "kind": "beside"}
    return {"cx": x + w / 2, "cy": y + h / 2, "rs": 0.5 * math.hypot(w, h) * 0.97, "kind": "behind"}


DIR = (math.cos(math.radians(16)), math.sin(math.radians(16)))  # the moon's path: left to right, a little down


# ------------------------------------------------------------------ timelines -> parameters

def _base(L, sun_alpha=1.0):
    return {"sky": 0.0, "reveal": None, "dark": 0.0, "sun": sun_alpha, "moon_s": None, "moon_a": 0.0,
            "corona": 0.0, "corona_scale": 1.0, "bead": 0.0, "bead_side": 1, "horizon": 0.0, "rim": 0.0,
            "text": None, "text_a": 0.0, "alpha": 1.0, "L": L}


def light_of(lay, s):
    rs = lay["rs"]
    rm = rs * 1.04
    return 1.0 - overlap(rs, rm, abs(s)) / (math.pi * rs * rs)


def path_len(lay):
    return lay["rs"] * 2.04 * 1.12


def enter(t, lay, W, H, text="Totality · everything else is resting"):
    """Parameters t seconds after the start."""
    P = _base(1.0)
    # (1) the screen melts into sunlight, a wave rolling out of the sun
    far = max(math.hypot(lay["cx"] - cx, lay["cy"] - cy) for cx in (0, W) for cy in (0, H))
    k = ease_out(t / DISSOLVE)
    P["reveal"] = None if t >= DISSOLVE else (k * far * 1.35 + 1, 0.45)
    P["sun"] = ease_out(t / (DISSOLVE * 0.7))
    P["sun_scale"] = 0.82 + 0.18 * ease_out(t / DISSOLVE)
    # (2) the moon glides in and stops dead centre at CONTACT
    u = ease_io((t - DISSOLVE) / (CONTACT - DISSOLVE))
    s = -path_len(lay) * (1 - u)
    P["moon_s"] = s
    P["moon_a"] = smooth(DISSOLVE - 0.05, DISSOLVE + 0.12, t)
    L = light_of(lay, s) if t < CONTACT else 0.0
    P["L"] = L
    lit = 0.05 + 0.95 * L ** 1.6
    P["sky"] = smooth(0.0, 0.35, t) * lit
    # the desktop never shows through again once the sun has it: as the sunlight fades, the deep dark
    # takes its place (total cover stays ~DARK..1), so the light dims instead of the desktop coming back
    P["dark"] = _cover(P["sky"], DARK + 0.04) * smooth(DISSOLVE - 0.15, DISSOLVE + 0.1, t) if t < CONTACT else DARK
    # (3) the last bead of sunlight flares at the leading limb, then the corona blooms
    if t < CONTACT:
        P["bead"] = math.exp(-((t - CONTACT) / 0.085) ** 2) * 1.0
    else:
        P["bead"] = math.exp(-(t - CONTACT) / 0.20)
    P["bead_side"] = 1
    c = smooth(CONTACT - 0.04, CONTACT + 0.85, t)
    P["corona"] = c * breathe(t)
    P["corona_scale"] = (0.90 + 0.10 * ease_out((t - CONTACT + 0.04) / 0.9)) * breathe_scale(t)
    P["horizon"] = smooth(CONTACT - 0.4, CONTACT + 1.2, t)
    P["rim"] = smooth(0.2, 1.0, 1 - L) if t < CONTACT else 1.0
    # (4) a tiny word that it worked
    P["text"] = text
    P["text_a"] = smooth(TEXT_IN, TEXT_IN + 0.45, t) * (1 - smooth(TEXT_HOLD, TEXT_OUT, t))
    return P


def _cover(sky, total):
    """Alpha of the dark layer under a sky of alpha `sky` so both together cover `total`."""
    return clamp((total - sky) / max(1e-3, 1 - sky)) if sky < total else 0.0


def breathe(t):
    return 0.92 + 0.08 * math.sin(2 * math.pi * max(0.0, t - CONTACT) / 7.0)


def breathe_scale(t):
    return 1.0 + 0.012 * math.sin(2 * math.pi * max(0.0, t - CONTACT) / 7.0 - 0.6)


def settled(t, lay, W, H):
    P = enter(max(t, SETTLE), lay, W, H)
    P["text_a"] = 0.0
    return P


def exit_(e, lay, W, H, t_total, text="Totality off · full light"):
    """Parameters e seconds after leaving; t_total = time spent in Totality (for the breathing phase)."""
    P = _base(1.0)
    u = ease_io(e / 1.2)
    s = path_len(lay) * u
    P["moon_s"] = s
    L = light_of(lay, s)
    P["L"] = L
    fade = 1 - smooth(1.05, EXIT, e)
    P["moon_a"] = fade          # never a see-through moon on a bright sky: it goes with the light
    P["sky"] = (0.05 + 0.95 * L ** 1.6) * fade
    P["dark"] = _cover(0.05 + 0.95 * L ** 1.6, DARK + 0.04) * fade
    P["sun"] = fade
    P["sun_scale"] = 1.0 - 0.12 * smooth(1.05, EXIT, e)
    P["bead"] = math.exp(-((e - 0.12) / 0.10) ** 2)
    P["bead_side"] = -1
    P["corona"] = (1 - smooth(0.0, 0.4, e)) * breathe(t_total)
    P["corona_scale"] = breathe_scale(t_total) * (1 + 0.04 * smooth(0, 0.4, e))
    P["horizon"] = 1 - smooth(0.0, 0.6, e)
    P["rim"] = (1 - smooth(0.0, 0.9, e))
    P["text"] = text
    P["text_a"] = smooth(0.15, 0.45, e) * (1 - smooth(1.2, 1.65, e))
    return P


def release(e, frozen, dur=0.6):
    """Leaving before totality was reached: the half-built picture just fades out."""
    P = dict(frozen)
    P["alpha"] = 1 - smooth(0.0, dur, e)
    P["text_a"] = 0.0
    return P


# ------------------------------------------------------------------ drawing

SKY = [(0.00, (255, 248, 232, 1.00)), (0.07, (255, 236, 182, 0.995)), (0.22, (255, 205, 92, 0.98)),
       (0.48, (236, 160, 52, 0.96)), (0.78, (196, 112, 36, 0.95)), (1.00, (128, 66, 22, 0.94))]


def _sample(spec, off):
    for (o0, c0), (o1, c1) in zip(spec, spec[1:]):
        if off <= o1:
            k = 0.0 if o1 == o0 else clamp((off - o0) / (o1 - o0))
            return tuple(a + (b - a) * k for a, b in zip(c0, c1))
    return spec[-1][1]


def _circle(snap, cx, cy, r, color):
    rr = Gsk.RoundedRect()
    rr.init_from_rect(rect(cx - r, cy - r, 2 * r, 2 * r), r)
    snap.push_rounded_clip(rr)
    snap.append_color(color, rect(cx - r, cy - r, 2 * r, 2 * r))
    snap.pop()


def _radial(snap, cx, cy, rx, ry, spec, mult=1.0, bounds=None):
    if mult <= 0.002:
        return
    b = bounds or rect(cx - rx, cy - ry, 2 * rx, 2 * ry)
    snap.append_radial_gradient(b, point(cx, cy), rx, ry, 0.0, 1.0, stops(spec, mult))


def draw(snap, W, H, holes, lay, P, tex, radius=12.0, layout_text=None):
    """One frame. holes: [(x, y, w, h)] screen-local rects that stay untouched (the focus window)."""
    a = P.get("alpha", 1.0)
    if a <= 0.002:
        return
    full = rect(0, 0, W, H)
    cx, cy, rs = lay["cx"], lay["cy"], lay["rs"]
    rm = rs * 1.04
    behind = lay.get("kind") == "behind" and bool(holes)
    if a < 0.999:
        snap.push_opacity(a)

    # Everything except the focus window: an inverted-alpha mask with the window rects cut out
    # (a path fill with the window rects as holes: a plain clip for the cairo renderer, ~2x cheaper there
    # than a mask; GTK < 4.14 has no paths and uses the mask)
    masked = bool(holes)
    if masked:
        if hasattr(Gsk, "PathBuilder"):
            pb = Gsk.PathBuilder.new()
            pb.add_rect(full)
            for (x, y, w, h) in holes:
                rr = Gsk.RoundedRect()
                rr.init_from_rect(rect(x, y, w, h), radius)
                pb.add_rounded_rect(rr)
            snap.push_fill(pb.to_path(), Gsk.FillRule.EVEN_ODD)
        else:
            snap.push_mask(Gsk.MaskMode.INVERTED_ALPHA)
            for (x, y, w, h) in holes:
                rr = Gsk.RoundedRect()
                rr.init_from_rect(rect(x, y, w, h), radius)
                snap.push_rounded_clip(rr)
                snap.append_color(rgba(255, 255, 255, 1), rect(x, y, w, h))
                snap.pop()
            snap.pop()

    # deep warm dark (what's left when the light is gone)
    if P["dark"] > 0.002:
        snap.append_color(rgba(*WARM_BLACK, P["dark"]), full)
    # the last twilight on the horizon all around (real eclipses have a 360-degree sunset)
    if P["horizon"] > 0.002:
        stp = stops([(0.0, (232, 140, 48, 0.16)), (0.45, (208, 120, 50, 0.05)), (1.0, (0, 0, 0, 0))], P["horizon"])
        snap.append_linear_gradient(rect(0, H * 0.62, W, H * 0.38), point(0, H), point(0, H * 0.62), stp)

    # the sky: the whole background becomes sunlight
    if P["sky"] > 0.002:
        far = max(math.hypot(cx - x, cy - y) for x in (0, W) for y in (0, H)) * (1.5 if behind else 1.02)
        reveal = P.get("reveal")
        spec = SKY
        if reveal:   # the melting front: the sky's own stops fade out past it (no mask: cheap everywhere)
            R, soft = reveal
            edge = min(1.0, R / far)
            spec = []
            n = 24
            for i in range(n + 1):
                off = edge * i / n
                f = 1.0 - smooth(1 - soft, 1.0, i / n)
                r_, g_, b_, a_ = _sample(SKY, off)
                spec.append((off, (r_, g_, b_, a_ * f)))
            if edge < 1.0:
                spec.append((1.0, (0, 0, 0, 0)))
        _radial(snap, cx, cy, far, far, spec, P["sky"], bounds=full)
        if tex and tex.noise and P["sky"] > 0.2 and not reveal:
            snap.push_opacity(0.05 * P["sky"])
            _repeat(snap, tex.noise, full, 256)
            snap.pop()

    # the sun: white-hot disc + bloom, dimming with the light that is left
    sun = P["sun"]
    if sun > 0.002 and not behind:
        sc = P.get("sun_scale", 1.0)
        r = rs * sc
        bloom = 0.30 + 0.70 * P["L"]
        _radial(snap, cx, cy, r * 4.2, r * 4.2, [(0.0, (255, 252, 244, 1)), (0.22, (255, 246, 225, 1)),
                                                 (0.25, (255, 224, 150, 0.62)), (0.34, (255, 205, 92, 0.32)),
                                                 (0.55, (240, 168, 60, 0.13)), (1.0, (232, 155, 42, 0))], sun * bloom)
        _radial(snap, cx, cy, r * 1.02, r * 1.02, [(0.0, (255, 255, 255, 1)), (0.6, (255, 251, 242, 1)),
                                                   (0.93, (255, 242, 210, 1)), (1.0, (255, 230, 175, 0))], sun)

    # the corona (from the photo), behind the moon's edge
    if P["corona"] > 0.002 and tex and tex.corona and not behind:
        size = rm / CORONA_DISC * P["corona_scale"]
        snap.push_opacity(clamp(P["corona"]))
        snap.append_texture(tex.corona, rect(cx - size / 2, cy - size / 2, size, size))
        snap.pop()
        # a soft gold halo far out in the dark sky
        _radial(snap, cx, cy, rm * 4.5, rm * 4.5, [(0.0, (255, 214, 140, 0.0)), (0.22, (255, 201, 74, 0.20)),
                                                   (0.45, (232, 155, 42, 0.07)), (1.0, (232, 155, 42, 0))], P["corona"])

    # the moon
    s = P["moon_s"]
    if s is not None and P["moon_a"] > 0.002:
        mx, my = cx + DIR[0] * s, cy + DIR[1] * s
        rr = Gsk.RoundedRect()
        rr.init_from_rect(rect(mx - rm, my - rm, 2 * rm, 2 * rm), rm)
        snap.push_rounded_clip(rr)
        _radial(snap, mx - rm * 0.18, my - rm * 0.22, rm * 1.25, rm * 1.25,
                [(0.0, (11, 10, 12, 1)), (0.7, (5, 5, 6, 1)), (1.0, (3, 3, 4, 1))], P["moon_a"],
                bounds=rect(mx - rm, my - rm, 2 * rm, 2 * rm))
        snap.pop()
        # thin bright limb hugging the moon at totality (the inner corona)
        if P["corona"] > 0.002 and not behind:
            _radial(snap, cx, cy, rm * 1.16, rm * 1.16, [(0.0, (0, 0, 0, 0)), (0.855, (0, 0, 0, 0)),
                                                         (0.865, (255, 246, 228, 0.85)), (0.90, (255, 222, 150, 0.35)),
                                                         (1.0, (255, 201, 74, 0))], P["corona"])

    # diamond ring: one blinding bead on the limb + a four-point star
    b = P["bead"]
    if b > 0.004:
        side = P["bead_side"]
        bx, by = cx + DIR[0] * rs * side, cy + DIR[1] * rs * side
        g = rs * (0.55 + 0.75 * b)
        if behind:   # the window is the moon: the bead sits on its edge
            x, y, w, h = holes[0]
            k = min((w / 2) / max(abs(DIR[0]), 1e-6), (h / 2) / max(abs(DIR[1]), 1e-6))
            bx, by = x + w / 2 + DIR[0] * k * side, y + h / 2 + DIR[1] * k * side
            g = 0.075 * min(W, H) * (0.55 + 0.75 * b)
        _radial(snap, bx, by, g * 2.6, g * 2.6, [(0.0, (255, 250, 236, 0.85)), (0.25, (255, 214, 120, 0.35)),
                                                 (1.0, (232, 155, 42, 0))], b)
        _radial(snap, bx, by, g * 0.42, g * 0.42, [(0.0, (255, 255, 255, 1)), (0.35, (255, 252, 240, 1)),
                                                   (1.0, (255, 236, 190, 0))], b)
        for rx, ry in ((g * 3.4, g * 0.045), (g * 0.045, g * 2.2)):
            _radial(snap, bx, by, rx, ry, [(0.0, (255, 255, 255, 0.95)), (0.4, (255, 240, 205, 0.35)),
                                           (1.0, (255, 220, 150, 0))], b)
        # the whole sky flickers with it
        snap.append_color(rgba(255, 238, 200, 0.10 * b), full)

    # behind: the window itself is the eclipsed disc and the corona burns around its edges
    if behind and P["corona"] > 0.002:
        c = clamp(P["corona"]) * (0.85 + 0.15 * (P["corona_scale"] - 0.988) / 0.024)
        x, y, w, h = holes[0]
        rr = Gsk.RoundedRect()
        rr.init_from_rect(rect(x, y, w, h), radius)
        snap.append_outset_shadow(rr, rgba(232, 155, 42, 0.30 * c), 0, 0, 6, 150)
        snap.append_outset_shadow(rr, rgba(255, 201, 74, 0.55 * c), 0, 0, 2, 60)
        snap.append_outset_shadow(rr, rgba(255, 244, 222, 0.75 * c), 0, 0, 0, 12)

    # the focus window glows: gold light on its rim, strongest at totality
    if masked and P["rim"] > 0.002:
        x, y, w, h = holes[0]
        rr = Gsk.RoundedRect()
        rr.init_from_rect(rect(x, y, w, h), radius)
        snap.append_outset_shadow(rr, rgba(255, 201, 74, 0.30 * P["rim"]), 0, 0, 1, 26)
        snap.append_outset_shadow(rr, rgba(255, 236, 190, 0.22 * P["rim"]), 0, 0, 0, 5)

    if masked:
        snap.pop()

    # the word
    if P.get("text") and P["text_a"] > 0.004 and layout_text is not None:
        lw, lh, tx, ty = layout_text
        pad_x, pad_y = 16, 7
        rr = Gsk.RoundedRect()
        rr.init_from_rect(rect(tx - pad_x, ty - pad_y, lw + 2 * pad_x, lh + 2 * pad_y), (lh + 2 * pad_y) / 2)
        snap.push_rounded_clip(rr)
        snap.append_color(rgba(12, 11, 12, 0.55 * P["text_a"]), rect(tx - pad_x, ty - pad_y, lw + 2 * pad_x, lh + 2 * pad_y))
        snap.pop()
        snap.append_border(rr, [0.6] * 4, [rgba(255, 201, 74, 0.35 * P["text_a"])] * 4)
        snap.save()
        snap.translate(point(tx, ty))
        snap.append_layout(layout_text_obj(), rgba(255, 238, 208, 0.95 * P["text_a"]))
        snap.restore()

    if a < 0.999:
        snap.pop()


_LAYOUT = {"obj": None}


def layout_text_obj():
    return _LAYOUT["obj"]


def place_text(pango_layout, W, H, holes, lay):
    """Measure the status text and find a calm place for it: under the eclipse when it is beside the
    window, else in the biggest gap above/below the window, else near the bottom."""
    _LAYOUT["obj"] = pango_layout
    ink, logical = pango_layout.get_pixel_extents()
    lw, lh = logical.width, logical.height
    if lay["kind"] in ("beside", "free"):
        ty = lay["cy"] + lay["rs"] * 1.04 / CORONA_DISC * 0.5 + 6
        if ty + lh + 10 > H:
            ty = lay["cy"] - lay["rs"] * 1.04 / CORONA_DISC * 0.5 - lh - 6
        tx = clamp(lay["cx"] - lw / 2, 12, W - lw - 12)
        return lw, lh, tx, ty
    if holes:
        x, y, w, h = holes[0]
        above, below = y, H - (y + h)
        if below >= lh + 24:
            return lw, lh, x + w / 2 - lw / 2, y + h + (below - lh) / 2
        if above >= lh + 24:
            return lw, lh, x + w / 2 - lw / 2, (above - lh) / 2
    return lw, lh, W / 2 - lw / 2, H - lh - 40


def _repeat(snap, texture, bounds, tile):
    # plain tiles (a repeat node mis-renders in GTK's GL renderer: it ignores the opacity around it)
    x0, y0 = bounds.get_x(), bounds.get_y()
    w, h = bounds.get_width(), bounds.get_height()
    snap.push_clip(bounds)
    y = 0.0
    while y < h:
        x = 0.0
        while x < w:
            snap.append_texture(texture, rect(x0 + x, y0 + y, tile, tile))
            x += tile
        y += tile
    snap.pop()
