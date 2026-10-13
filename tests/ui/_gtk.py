"""Helpers for driving real GTK windows in tests (run under a headless broadway display)."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _paths  # noqa: F401,E402

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402


def texts(w):
    """Every visible label and button text under a widget."""
    out = []

    def walk(x):
        if not x.get_visible():
            return
        if isinstance(x, Gtk.Label) and x.get_label():
            out.append(x.get_label())
        elif isinstance(x, Gtk.Button) and x.get_label():
            out.append(x.get_label())
        c = x.get_first_child()
        while c is not None:
            walk(c)
            c = c.get_next_sibling()
    walk(w)
    return out


def find_button(w, label):
    if isinstance(w, Gtk.Button) and w.get_label() == label and w.get_visible():
        return w
    c = w.get_first_child()
    while c is not None:
        b = find_button(c, label)
        if b:
            return b
        c = c.get_next_sibling()
    return None


def wait(cond, timeout=30.0):
    """Run the main loop until cond() is true."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {cond.__doc__ or cond}")


def settle(seconds=0.6):
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)


def shot(win, name):
    """Render the window to a PNG in $SHOTS (if set)."""
    d = os.environ.get("SHOTS")
    if not d:
        return None
    node = None
    for _ in range(20):            # until the window has drawn a frame
        settle(0.3)
        w, h = win.get_width(), win.get_height()
        snap = Gtk.Snapshot()
        Gtk.WidgetPaintable.new(win).snapshot(snap, w, h)
        node = snap.to_node()
        if node is not None and w > 0:
            break
    if node is None:
        raise AssertionError(f"window never drew a frame (size {win.get_width()}x{win.get_height()})")
    path = os.path.join(d, name)
    win.get_renderer().render_texture(node, None).save_to_png(path)
    return path
