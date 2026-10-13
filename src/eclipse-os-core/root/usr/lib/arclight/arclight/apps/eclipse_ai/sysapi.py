"""Eclipse AI's line to the Eclipse daemons: arclightd (root: exec, packages) and the session daemon
(settings). One short-lived connection per call, so worker threads never share a socket.
Tests replace `call` with a fake (nothing here ever needs a password)."""
import os

from arclight.client import target_for
from arclight.rpc import Client, RemoteError
from arclight.util import SYSTEM_SOCK, session_sock


class Unavailable(Exception):
    pass


def _sock(which: str) -> str:
    return SYSTEM_SOCK if which == "system" else session_sock()


def available(which: str = "system") -> bool:
    return os.path.exists(_sock(which))


def _real_call(method: str, _wait: float = 7300, **params):
    which = target_for(method)
    path = _sock(which)
    if not os.path.exists(path):
        raise Unavailable("arclightd (the root service) is not running" if which == "system" else
                          "the Eclipse session service is not running")
    c = Client(path, timeout=_wait)
    try:
        return c.call(method, **params)
    finally:
        c.close()


call = _real_call

__all__ = ["call", "available", "Unavailable", "RemoteError"]
