"""Totality overlay: a full-screen, click-through layer over everything except the window you use.

Runs as the transient user unit `arclight-totality` (started by session/totality.py). The picture is
apps/totality_scene.py; this file is the window, the real clock and the link to Hyprland:

  enter   0.0-0.9 s  the desktop melts into sunlight
          0.9-2.3 s  the moon glides over the sun, the light goes
          2.3 s      diamond ring -> the rest of the desktop is put to rest (session/totality.apply)
          ...        golden corona, calm dark; status words fade in and out; then a few frames a second
  exit    (SIGUSR1)  everything is woken first, then the sun breaks free and the light floods back (1.8 s)
  SIGTERM            restore at once and quit (the unit's ExecStopPost restores too)

The hole follows the focus window (Hyprland's event socket), with a soft gold rim.
"""
import ctypes
import json
import math
import os
import signal
import socket
import sys
import threading
import time

from ..session import totality as T

FRAME_IDLE_MS = 200   # after settling: 5 frames a second for the slow corona breathing


def _hypr_sock(name):
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(rt, "hypr", sig, name)


def hypr(cmd):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(_hypr_sock(".socket.sock"))
        s.sendall(f"j/{cmd}".encode())
        buf = b""
        while True:
            d = s.recv(65536)
            if not d:
                break
            buf += d
        s.close()
        return json.loads(buf.decode() or "null")
    except (OSError, ValueError):
        return None


def hypr_opt(name, default):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(_hypr_sock(".socket.sock"))
        s.sendall(f"j/getoption {name}".encode())
        buf = b""
        while True:
            d = s.recv(65536)
            if not d:
                break
            buf += d
        s.close()
        j = json.loads(buf.decode())
        for k in ("int", "float"):
            if k in j:
                return j[k]
    except (OSError, ValueError, AttributeError):
        pass
    return default


def run(argv):
    try:
        ctypes.CDLL("libgtk4-layer-shell.so")
    except OSError:
        pass
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, GLib, Gtk, Pango
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LS
    except (ValueError, ImportError):
        LS = None
    from . import totality_scene as S

    T.log("overlay start")
    Gtk.init()
    _pick_renderer(Gdk)
    if not (LS and LS.is_supported()):
        T.log("no layer shell: Totality without the animation")
        T.apply()
        return _hold_without_overlay(GLib)

    act = hypr("activewindow") or {}
    mons = hypr("monitors") or []
    mon = next((m for m in mons if m.get("id") == act.get("monitor")), None) or \
        next((m for m in mons if m.get("focused")), None) or (mons[0] if mons else None)
    border = hypr_opt("general:border_size", 2)
    rounding = hypr_opt("decoration:rounding", 12)

    class Overlay(Gtk.Widget):
        def __init__(self):
            super().__init__()
            self.tex = S.Textures()
            self.mode = "enter"
            self.t0 = None
            self.exit_t0 = None
            self.frozen = None
            self.applied = False
            self.restore_at = None
            self.wake_at = None
            self.frames = 0
            self.phase_logged = set()
            self.target = None       # (x, y, w, h) of the focus window, local coords
            self.extra = []          # other windows of the same app on screen
            self.cur = None
            self.lay_target = None
            self.lay = None
            self.vis = 1.0
            self.vis_target = 1.0
            self.focus_pid = act.get("pid")
            self.last = None
            self.idle_src = None
            self.tick_id = None
            self.text_layout = self.create_pango_layout("")
            self.text_layout.set_font_description(Pango.FontDescription.from_string("Inter Medium 11"))
            self.refresh(initial=True)
            self.start_ticking()

        # ---------------- Hyprland
        def refresh(self, initial=False):
            before = (self.target, tuple(self.extra), self.vis_target)
            a = hypr("activewindow") or {}
            W, H = self.size()
            ox, oy = (mon or {}).get("x", 0), (mon or {}).get("y", 0)
            if a.get("address") and not a.get("hidden"):
                b = border
                x, y = a["at"][0] - ox - b, a["at"][1] - oy - b
                self.target = (x, y, a["size"][0] + 2 * b, a["size"][1] + 2 * b)
                fs = a.get("fullscreen", 0)
                self.vis_target = 0.0 if (fs == 2 or (fs and a["size"][0] >= W - 4 and a["size"][1] >= H - 4)) else 1.0
                self.extra = []
                ws = (a.get("workspace") or {}).get("id")
                for c in hypr("clients") or []:
                    if c.get("pid") == a.get("pid") and c.get("address") != a["address"] and \
                            (c.get("workspace") or {}).get("id") == ws and not c.get("hidden"):
                        self.extra.append((c["at"][0] - ox - b, c["at"][1] - oy - b,
                                           c["size"][0] + 2 * b, c["size"][1] + 2 * b))
                pid = a.get("pid")
                if pid and pid != self.focus_pid:
                    self.focus_pid = pid
                    threading.Thread(target=T.adopt, args=(pid,), daemon=True).start()
            else:
                self.target, self.extra = None, []
                self.vis_target = 1.0
            if W > 0:
                self.lay_target = S.layout(W, H, self.target)
                if self.lay is None or initial:
                    self.lay = dict(self.lay_target)
            if self.cur is None or initial:
                self.cur = self.target
            if initial or before != (self.target, tuple(self.extra), self.vis_target):
                self.start_ticking()

        def size(self):
            W, H = self.get_width(), self.get_height()
            if W <= 0 and mon:
                sc = mon.get("scale", 1) or 1
                W, H = mon["width"] / sc, mon["height"] / sc
                if mon.get("transform", 0) % 2:
                    W, H = H, W
            return W, H

        # ---------------- clock
        def start_ticking(self):
            if self.tick_id is None:
                self.tick_id = self.add_tick_callback(self.on_tick)
            if self.idle_src:
                GLib.source_remove(self.idle_src)
                self.idle_src = None

        def on_tick(self, widget, clock):
            now = clock.get_frame_time() / 1e6
            dt = 0.016 if self.last is None else min(0.1, max(0.0, now - self.last))
            self.last = now
            if self.t0 is None:
                self.t0 = now
                T.log("animation start (first frame)")
            moving = self.smooth(dt)
            self.queue_draw()
            t = now - self.t0
            if self.mode == "enter":
                if not self.applied and t >= S.CONTACT:
                    self.applied = True
                    T.log(f"diamond ring at t={t:.3f}s (frames so far {self.frames}) -> rest")
                    threading.Thread(target=T.apply, args=(self.focus_pid,), daemon=True).start()
                if t >= S.SETTLE and not moving:
                    self.mode = "settled"
                    T.log(f"settled at t={t:.3f}s, {self.frames} frames ({self.frames / max(t, 0.001):.1f} fps)")
            elif self.mode in ("exit", "release"):
                e = now - self.exit_t0
                if self.wake_at is not None and (e >= self.wake_at or self.mode == "release"):
                    self.wake_at = None
                    threading.Thread(target=T.wake, daemon=True).start()
                if self.restore_at is not None and (e >= self.restore_at or self.mode == "release"):
                    self.restore_at = None
                    threading.Thread(target=T.restore, daemon=True).start()
                if e >= (S.EXIT if self.mode == "exit" else 0.6):
                    T.log(f"{self.mode} done at e={e:.3f}s, {self.frames - self.exit_frames} frames")
                    app.quit()
                    return GLib.SOURCE_REMOVE
            if self.mode == "settled" and not moving:
                self.tick_id = None
                self.idle_src = GLib.timeout_add(FRAME_IDLE_MS, self.on_idle)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        def on_idle(self):
            self.queue_draw()
            return GLib.SOURCE_CONTINUE

        def smooth(self, dt):
            moving = False
            k = 1 - math.exp(-dt / 0.085)
            if self.target and self.cur:
                nxt = tuple(c + (t - c) * k for c, t in zip(self.cur, self.target))
                moving = any(abs(a - b) > 0.4 for a, b in zip(nxt, self.target))
                self.cur = nxt if moving else self.target
            else:
                self.cur = self.target
            if self.lay_target and self.lay:
                k2 = 1 - math.exp(-dt / 0.22)
                for key in ("cx", "cy", "rs"):
                    self.lay[key] += (self.lay_target[key] - self.lay[key]) * k2
                    if abs(self.lay[key] - self.lay_target[key]) > 0.4:
                        moving = True
                self.lay["kind"] = self.lay_target["kind"]
            kv = 1 - math.exp(-dt / 0.15)
            self.vis += (self.vis_target - self.vis) * kv
            if abs(self.vis - self.vis_target) > 0.01:
                moving = True
            else:
                self.vis = self.vis_target
            return moving

        # ---------------- leaving
        def leave(self, hard=False):
            if self.mode in ("exit", "release"):
                return
            T.log("leave requested" + (" (hard)" if hard else ""))
            self.wake_at = 0.35          # apps run again just after the bead flash, as the light returns
            self.restore_at = 1.0        # effects back while the sky still covers everything
            now = GLib.get_monotonic_time() / 1e6
            t = (now - self.t0) if self.t0 is not None else 0.0
            self.exit_frames = self.frames
            self.exit_t0 = now
            if self.mode == "enter" and t < S.CONTACT:
                self.frozen = self.params(now)
                self.mode = "release"
            else:
                self.t_total = t
                self.mode = "exit"
            self.start_ticking()

        # ---------------- drawing
        def params(self, now):
            W, H = self.size()
            lay = self.lay or S.layout(W, H, self.cur)
            t = 0.0 if self.t0 is None else now - self.t0
            if self.mode == "enter":
                P = S.enter(t, lay, W, H)
            elif self.mode == "settled":
                P = S.settled(t, lay, W, H)
            elif self.mode == "exit":
                P = S.exit_(now - self.exit_t0, lay, W, H, self.t_total)
            else:
                P = S.release(now - self.exit_t0, self.frozen or S.enter(0, lay, W, H))
            if self.vis < 0.999 and self.mode != "exit":
                P = dict(P)
                P["alpha"] = P.get("alpha", 1.0) * self.vis
            return P

        def do_snapshot(self, snap):
            self.frames += 1
            now = GLib.get_monotonic_time() / 1e6
            W, H = self.size()
            P = self.params(now)
            holes = [self.cur] + self.extra if self.cur else []
            lt = None
            if P.get("text") and P.get("text_a", 0) > 0.004:
                self.text_layout.set_text(P["text"], -1)
                lt = S.place_text(self.text_layout, W, H, holes, self.lay)
            S.draw(snap, W, H, holes, self.lay, P, self.tex, radius=rounding + border, layout_text=lt)

    css = Gtk.CssProvider()
    css.load_from_string("window.totality, window.totality > * { background: none; background-color: transparent; box-shadow: none; backdrop-filter: none; border: none; }")
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                              Gtk.STYLE_PROVIDER_PRIORITY_USER + 10)  # beats ~/.config/gtk-4.0 glass

    app = Gtk.Application(application_id=None)
    state = {}

    def activate(app):
        win = Gtk.ApplicationWindow(application=app, title="Totality")
        win.add_css_class("totality")
        win.set_decorated(False)
        LS.init_for_window(win)
        LS.set_namespace(win, "arclight-totality")
        LS.set_layer(win, LS.Layer.TOP)   # under notifications, launcher and Ask; fullscreen games hide it
        for edge in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(win, edge, True)
        LS.set_exclusive_zone(win, -1)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        if mon:
            dm = Gdk.Display.get_default().get_monitors()
            for i in range(dm.get_n_items()):
                m = dm.get_item(i)
                if m.get_connector() == mon.get("name"):
                    LS.set_monitor(win, m)
        ov = Overlay()
        state["ov"] = ov
        win.set_child(ov)

        def realized(w):
            import cairo
            w.get_surface().set_input_region(cairo.Region())   # every click goes through
        win.connect("realize", realized)
        win.present()
        _watch_events(GLib, ov)

        def on_usr1():
            ov.leave()
            return GLib.SOURCE_CONTINUE

        def on_term():
            T.log("SIGTERM: restore now")
            T.restore()
            app.quit()
            return GLib.SOURCE_REMOVE
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, on_usr1)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, on_term)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, on_term)
        app.hold()

    app.connect("activate", activate)
    try:
        app.run([sys.argv[0]])
    finally:
        T.restore()          # whatever happened, nothing stays paused
        T.log("overlay end")
    return 0


def _watch_events(GLib, ov):
    """Hyprland's event socket: follow the focus window as it moves, resizes, changes or goes fullscreen."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(_hypr_sock(".socket2.sock"))
        s.setblocking(False)
    except OSError:
        s = None
    pending = {"src": None}
    WANT = (b"activewindow", b"movewindow", b"openwindow", b"closewindow", b"fullscreen", b"changefloatingmode",
            b"workspace", b"resizewindow", b"windowtitle", b"focusedmon", b"minimized")

    def kick():
        pending["src"] = None
        ov.refresh()
        return GLib.SOURCE_REMOVE

    def schedule():
        if pending["src"] is None:
            pending["src"] = GLib.timeout_add(25, kick)

    if s:
        buf = {"b": b""}

        def readable(fd, cond):
            try:
                d = s.recv(65536)
            except BlockingIOError:
                return GLib.SOURCE_CONTINUE
            except OSError:
                return GLib.SOURCE_REMOVE
            if not d:
                return GLib.SOURCE_REMOVE
            buf["b"] += d
            *lines, buf["b"] = buf["b"].split(b"\n")
            if any(line.split(b">>")[0] in WANT or line.startswith(WANT) for line in lines):
                schedule()
            return GLib.SOURCE_CONTINUE
        GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, s.fileno(), GLib.IOCondition.IN, readable)
        ov._sock = s
    # drags/resizes by mouse don't always send events: a cheap poll catches them
    GLib.timeout_add(500, lambda: (ov.refresh() if ov.mode in ("enter", "settled") else None) or True)


def _pick_renderer(Gdk):
    """On software GL (llvmpipe: VMs, broken drivers) GTK's GL renderer is ~10x slower than its cairo one
    for this full-screen picture, so use cairo there. Real GPUs keep GTK's default (GL/Vulkan)."""
    if os.environ.get("GSK_RENDERER"):
        return
    name = b""
    try:
        ctx = Gdk.Display.get_default().create_gl_context()
        ctx.realize()
        ctx.make_current()
        gl = ctypes.CDLL("libOpenGL.so.0")
        gl.glGetString.restype = ctypes.c_char_p
        name = gl.glGetString(0x1F01) or b""
        Gdk.GLContext.clear_current()
    except Exception:
        pass
    soft = not name or any(k in name.lower() for k in (b"llvmpipe", b"softpipe", b"swrast", b"lavapipe"))
    if soft:
        os.environ["GSK_RENDERER"] = "cairo"
        threading.Thread(target=T.effects_off_early, daemon=True).start()
    T.log(f"GL: {name.decode(errors='replace') or 'none'} -> renderer {os.environ.get('GSK_RENDERER', 'default')}")


def _hold_without_overlay(GLib):
    loop = GLib.MainLoop()

    def stop():
        T.restore()
        loop.quit()
        return GLib.SOURCE_REMOVE
    for sig in (signal.SIGUSR1, signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, stop)
    loop.run()
    return 0
