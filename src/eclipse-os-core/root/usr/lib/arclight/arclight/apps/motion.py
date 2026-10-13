"""Eclipse motion for our GTK4 apps (Settings, Store, Welcome, Ask, installer).

Everything here runs on the real clock: CSS animations/transitions (GTK times them on the frame clock)
or tick callbacks that read Gdk.FrameClock.get_frame_time() and compute the position from elapsed
microseconds. A slow machine draws fewer in-between frames but every move takes the same wall time.
Nothing is counted in frames.

  rise(widgets)            fade + rise in, one after another (cards, rows, groups)
  stagger(root)            rise() the first real list of children under `root` (a page)
  Tween(widget, ms, cb)    ease any number on the frame clock (cb gets the value each frame)
  EasedProgress(bar)       a Gtk.ProgressBar whose fraction glides to each new value
  SidebarGlide(listbox)    the selection highlight slides from the old row to the new one
  SunGlow()                the sun's light drifting slowly over a hero photo (still on software rendering)

GTK honours gtk-enable-animations (and prefers-reduced-motion in the CSS): with animations off the
CSS rules stop animating and the tweens jump straight to their end value.
"""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

from .glass import EASE_BLOOM, EASE_OUT, MAX_STAGGER, STEP_MS  # noqa: E402  (the CSS half lives in glass.MOTION)

_TRACE = bool(os.environ.get("ARCLIGHT_MOTION_TRACE"))


# ------------------------------------------------------------------ entrances
def rise(widgets, first=0):
    """Fade + rise `widgets` in, each STEP_MS after the one before (CSS keyframes on the frame clock).
    Everything happens in this call, before the next frame: new widgets get the class right away (so they
    are never drawn finished first), and a replay flips between two animation names, which restarts it."""
    for i, w in enumerate(x for x in widgets if x is not None):
        for k in range(1, MAX_STAGGER + 1):
            w.remove_css_class(f"arc-d{k}")
        d = min(first + i, MAX_STAGGER)
        if d:
            w.add_css_class(f"arc-d{d}")
        if w.has_css_class("arc-rise"):
            if w.has_css_class("arc-again"):
                w.remove_css_class("arc-again")
            else:
                w.add_css_class("arc-again")
        else:
            w.add_css_class("arc-rise")


def children(w):
    out, c = [], w.get_first_child()
    while c is not None:
        out.append(c)
        c = c.get_next_sibling()
    return out


def stagger(root, limit=12):
    """Rise the first list of real children below `root` (follows single-child wrappers such as
    scrolled windows, viewports and clamps), so a page's groups come in one after another."""
    w = root
    for _ in range(12):
        kids = [c for c in children(w) if c.get_visible() and not isinstance(c, (Gtk.Scrollbar,))]
        if len(kids) >= 2:
            rise(kids[:limit])
            return kids[:limit]
        if not kids:
            break
        w = kids[0]
    rise([root])
    return [root]


# ------------------------------------------------------------------ tweens on the frame clock
def _cubic_bezier(p1x, p1y, p2x, p2y):
    """CSS cubic-bezier easing as a function of t in [0, 1]."""
    def sample(a, b, t):
        return ((1 - 3 * b + 3 * a) * t + (3 * b - 6 * a)) * t * t + 3 * a * t

    def solve_x(x):
        t = x
        for _ in range(8):
            err = sample(p1x, p2x, t) - x
            d = (3 * (1 - 3 * p2x + 3 * p1x) * t + 2 * (3 * p2x - 6 * p1x)) * t + 3 * p1x
            if abs(err) < 1e-5 or abs(d) < 1e-6:
                break
            t -= err / d
        return min(max(t, 0.0), 1.0)
    return lambda x: sample(p1y, p2y, solve_x(x)) if 0 < x < 1 else float(x >= 1)


ease_out = _cubic_bezier(*EASE_OUT)
ease_bloom = _cubic_bezier(*EASE_BLOOM)


def animations_on(widget):
    s = widget.get_settings()
    return bool(s.get_property("gtk-enable-animations")) if s else True


class Tween:
    """Ease a number from its current value to a target over `ms` of wall-clock time.
    `on_value(v)` is called once per frame; position = ease(elapsed / duration), never a frame count."""

    def __init__(self, widget, ms, on_value, ease=ease_out, value=0.0):
        self.widget, self.ms, self.on_value, self.ease = widget, ms, on_value, ease
        self.value = value
        self._tick = 0

    def to(self, target, ms=None):
        dur = (ms if ms is not None else self.ms) * 1000.0
        if self._tick:
            self.widget.remove_tick_callback(self._tick)
            self._tick = 0
        if dur <= 0 or not animations_on(self.widget) or not self.widget.get_mapped():
            self.value = target
            self.on_value(target)
            return
        start, t0, frames = self.value, None, 0

        def tick(_w, clock):
            nonlocal t0, frames
            now = clock.get_frame_time()
            if t0 is None:
                t0 = now
            frames += 1
            k = min((now - t0) / dur, 1.0)
            self.value = start + (target - start) * self.ease(k)
            self.on_value(self.value)
            if k >= 1.0:
                self._tick = 0
                if _TRACE:   # ARCLIGHT_MOTION_TRACE=1: proof that the length is wall time, not frames
                    print(f"motion: {type(self.widget).__name__} {dur / 1000:.0f} ms planned, "
                          f"{(now - t0) / 1000:.0f} ms taken, {frames} frames drawn", file=sys.stderr, flush=True)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        self._tick = self.widget.add_tick_callback(tick)

    def jump(self, v):
        if self._tick:
            self.widget.remove_tick_callback(self._tick)
            self._tick = 0
        self.value = v
        self.on_value(v)


class EasedProgress:
    """Wrap a Gtk.ProgressBar: set(f) glides the bar to f (600 ms, ease-out) instead of jumping.
    pulse() and set_text() pass straight through."""

    def __init__(self, bar, ms=600):
        self.bar = bar
        self._t = Tween(bar, ms, bar.set_fraction, value=bar.get_fraction())

    def set(self, f):
        f = min(max(float(f), 0.0), 1.0)
        if f < self._t.value - 1e-6:     # going back (a new job): no rewind animation
            self._t.jump(f)
        else:
            self._t.to(f)

    def jump(self, f):
        self._t.jump(f)

    def __getattr__(self, name):
        return getattr(self.bar, name)


class SidebarGlide:
    """The selected row's highlight slides (eased, 300 ms) to the newly selected row instead of
    blinking from one to the other. Build it, then put .widget where the listbox would go."""

    def __init__(self, listbox, ms=300):
        self.listbox = listbox
        self.track = Gtk.Fixed()
        self.pill = Gtk.Box(can_target=False, can_focus=False)
        self.pill.add_css_class("arc-glide-pill")
        self.pill.set_visible(False)
        self.track.put(self.pill, 0, 0)
        self.widget = Gtk.Overlay(child=self.track)
        self.widget.add_overlay(listbox)
        self.widget.set_measure_overlay(listbox, True)
        listbox.add_css_class("arc-glide")
        self._geo = None              # (x, y, w, h) shown now
        self._from = None
        self._target = None
        self._t = Tween(self.pill, ms, self._step, ease=ease_bloom)
        listbox.connect("row-selected", lambda _lb, row: self.follow(row))
        self._fix_src = 0
        self._sync_src = 0
        # every time the overlay lays the list out (window resized, sidebar narrower), re-fit the pill
        self.widget.connect("get-child-position", self._on_layout)

    def _on_layout(self, _ov, _child, *_alloc):
        if not self._sync_src:
            self._sync_src = GLib.idle_add(self._resync)
        return False      # GTK places the list itself; this is only the "laid out" notice

    def _resync(self):
        self._sync_src = 0
        row = self.listbox.get_selected_row()
        if row is not None and not self._t._tick:
            g = self._bounds(row)
            if g is not None and g != self._geo:
                self.pill.set_visible(True)
                self._place(g)
        return GLib.SOURCE_REMOVE

    def _bounds(self, row):
        ok, r = row.compute_bounds(self.listbox)
        if not ok or r.get_width() < 20 or r.get_height() < 12:   # not laid out yet
            return None
        return (r.get_x(), r.get_y(), r.get_width(), r.get_height())

    def _place(self, g):
        x, y, w, h = g
        self._geo = g
        self.pill.set_size_request(int(round(w)), int(round(h)))
        self.track.move(self.pill, x, y)

    def _step(self, k):
        if self._from is None or self._target is None:
            return
        a, b = self._from, self._target
        self._place(tuple(a[i] + (b[i] - a[i]) * k for i in range(4)))

    def follow(self, row):
        if row is None:
            self.pill.set_visible(False)
            return
        g = self._bounds(row)
        if g is None:                 # not laid out yet (first show): place it once it is
            if not self._fix_src:
                self._fix_src = GLib.timeout_add(30, self._retry, row)
            return
        self.pill.set_visible(True)
        if self._geo is None:
            self._place(g)
            return
        self._from, self._target = self._geo, g
        self._t.value = 0.0
        self._t.to(1.0)

    def _retry(self, row):
        self._fix_src = 0
        if self.listbox.get_selected_row() is row:
            self.follow(row)
        return GLib.SOURCE_REMOVE


_MOVING_LIGHT = None


def moving_light():
    """Should the sunlight drift? The same rule as the Hyprland sun timer (desktop/hypr/arclight.lua):
    ~/.local/state/arclight/moving-light says "on"/"off"; otherwise off under software rendering
    (Hyprland's log names llvmpipe/softpipe: every redraw would run on the CPU), on everywhere else."""
    global _MOVING_LIGHT
    if _MOVING_LIGHT is None:
        import os
        from pathlib import Path
        try:
            flag = (Path.home() / ".local/state/arclight/moving-light").read_text().strip().lower()
        except OSError:
            flag = ""
        if flag in ("on", "off"):
            _MOVING_LIGHT = flag == "on"
        else:
            log = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())) / "hypr" / \
                os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "-") / "hyprland.log"
            try:
                with open(log, errors="replace") as f:
                    head = f.read(200000)
            except OSError:
                head = ""
            _MOVING_LIGHT = not ("Renderer: llvmpipe" in head or "Renderer: softpipe" in head)
    return _MOVING_LIGHT


class SunGlow(Gtk.Widget):
    """The sun's light drifting slowly across a glass hero (a soft golden radial glow).

    Position comes from the wall clock (one slow figure-of-eight every `period` seconds), so it is the
    same on every machine. It is redrawn 12 times a second, not every frame: the light moves a couple
    of pixels per redraw, which reads as smooth drift at a fraction of the cost of a CSS animation.
    Stops while unmapped (another page, window hidden) and when animations are off."""

    def __init__(self, period=36.0, strength=0.17, **kw):
        super().__init__(can_target=False, can_focus=False, **kw)
        self.period, self.strength = period, strength
        self._src = 0
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def _on_map(self, *_a):
        if not self._src and animations_on(self) and moving_light():
            self._src = GLib.timeout_add(83, self._tick)

    def _on_unmap(self, *_a):
        if self._src:
            GLib.source_remove(self._src)
            self._src = 0

    def _tick(self):
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def phase(self):
        import math
        t = GLib.get_monotonic_time() / 1e6 if (animations_on(self) and moving_light()) else 0.0
        a = 2 * math.pi * t / self.period
        return 0.30 + 0.32 * math.sin(a), 0.38 + 0.16 * math.sin(2 * a + 0.8)

    def do_snapshot(self, snap):
        from gi.repository import Gdk, Graphene, Gsk
        w, h = self.get_width(), self.get_height()
        if w <= 0 or h <= 0:
            return
        fx, fy = self.phase()
        gold = Gdk.RGBA()
        gold.parse("#FFC94A")
        stops = []
        for off, alpha in ((0.0, self.strength), (0.35, self.strength * 0.30), (1.0, 0.0)):
            c = gold.copy()
            c.alpha = alpha
            cs = Gsk.ColorStop()
            cs.offset, cs.color = off, c
            stops.append(cs)
        rect = Graphene.Rect().init(0, 0, w, h)
        center = Graphene.Point().init(fx * w, fy * h)
        r = max(w, h) * 0.55
        snap.append_radial_gradient(rect, center, r, r * 0.75, 0.0, 1.0, stops)
