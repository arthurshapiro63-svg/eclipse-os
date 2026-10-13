"""Route API calls to the right daemon: root work to arclightd, desktop work to arclight-session."""
import os

from .rpc import Client, RemoteError
from .util import SYSTEM_SOCK, session_sock

SYSTEM_NS = ("pkg.", "file.", "sys.", "snap.", "exec", "actions.", "events.", "config.")
SESSION_NS = ("screen.", "input.", "win.", "ws.", "mon.", "hypr.", "binds.", "app.", "game.", "totality.", "ui.", "clip.",
              "notify.", "media.", "settings.", "wait.", "stop", "session.")

_clients = {}


class Unavailable(Exception):
    pass


def target_for(method, user=False):
    if method.startswith(("svc.", "log.")):
        return "session" if user else "system"
    if method.startswith(SYSTEM_NS):
        return "system"
    if method.startswith(SESSION_NS):
        return "session"
    return "system"


def client(which):
    path = SYSTEM_SOCK if which == "system" else session_sock()
    c = _clients.get(path)
    if c is None:
        if not os.path.exists(path):
            raise Unavailable(
                "arclightd is not running (sudo systemctl enable --now arclightd)" if which == "system" else
                "arclight-session is not running (it starts with Hyprland: systemctl --user start arclight-session)")
        c = _clients[path] = Client(path)
    return c


def call(method, _user=False, **params):
    which = target_for(method, _user or params.get("user", False))
    if method.startswith(("svc.", "log.")):
        params.pop("user", None)  # the daemon chosen above already implies the scope
    try:
        return client(which).call(method, **params)
    except (ConnectionError, BrokenPipeError):
        _clients.pop(SYSTEM_SOCK if which == "system" else session_sock(), None)
        return client(which).call(method, **params)


__all__ = ["call", "client", "target_for", "RemoteError", "Unavailable"]
