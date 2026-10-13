"""Calls to the Arclight daemons from the Settings app.

Each worker thread gets its own socket connections (rpc.Client is not thread-safe), so a
long pkg.upgrade never blocks the rest of the UI. With ARCLIGHT_SETTINGS_FAKE=1 every call
goes to an in-memory fake (fake.py) instead: used for headless UI tests.
"""
import os
import threading

from gi.repository import GLib

from ... import client as C
from ...rpc import Client
from ...util import SYSTEM_SOCK, session_sock

RemoteError = C.RemoteError
Unavailable = C.Unavailable
_local = threading.local()


def fake_mode():
    return os.environ.get("ARCLIGHT_SETTINGS_FAKE") == "1"


def _client(which):
    path = os.environ.get("ARCLIGHT_SYSTEM_SOCK", SYSTEM_SOCK) if which == "system" else session_sock()
    cache = getattr(_local, "clients", None)
    if cache is None:
        cache = _local.clients = {}
    c = cache.get(path)
    if c is None:
        if not os.path.exists(path):
            raise Unavailable(
                "The system helper (arclightd) is not running, so system settings can't change. "
                "Run 'arc doctor' in a terminal: it says how to fix it."
                if which == "system" else
                "The desktop helper (arclight-session) is not running. It starts when you log in. "
                "Log out and back in, or run 'arc doctor' in a terminal.")
        c = cache[path] = Client(path, timeout=7200)
    return c, path


def call(method, **params):
    """Blocking call (run it off the GTK thread with run_async)."""
    if fake_mode():
        from . import fake
        return fake.call(method, **params)
    which = C.target_for(method)
    c, path = _client(which)
    try:
        return c.call(method, **params)
    except (ConnectionError, BrokenPipeError):
        _local.clients.pop(path, None)  # daemon restarted: reconnect once
        c, _ = _client(which)
        return c.call(method, **params)


def ping(which):
    """True when the daemon answers."""
    if fake_mode():
        from . import fake
        return fake.ping(which)
    try:
        c, _ = _client(which)
        c.call("api.ping")
        return True
    except Exception:
        return False


def message(err):
    """Human text for an exception from a call."""
    if isinstance(err, RemoteError):
        return err.message
    return str(err) or type(err).__name__


def run_async(fn, on_done=None, on_error=None):
    """Run fn() in a thread; deliver its result (or exception) on the GTK main loop."""
    def worker():
        try:
            res = fn()
        except Exception as e:  # delivered to the UI, never lost
            if on_error:
                GLib.idle_add(lambda err=e: (on_error(err), False)[1])
            else:
                import traceback
                traceback.print_exc()
            return
        if on_done:
            GLib.idle_add(lambda r=res: (on_done(r), False)[1])
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t
