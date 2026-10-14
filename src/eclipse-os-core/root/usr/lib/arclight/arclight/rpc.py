"""Line-delimited JSON-RPC over unix sockets, shared by arclightd and arclight-session.

Request:  {"id": 1, "method": "pkg.install", "params": {...}}
Response: {"id": 1, "result": ...}  or  {"id": 1, "error": {"message": ..., "type": ...}}

Handlers are plain functions registered with @api.method("name"); they receive the
params as keyword arguments plus `_peer` (uid, gid, pid of the caller). Blocking
handlers run in a thread pool so one slow pacman call never stalls screenshots.
"""
import asyncio
import inspect
import json
import os
import socket
import struct
import time
import traceback

from .util import jdump

MAX_LINE = 64 * 1024 * 1024


class RPCError(Exception):
    """Raised by handlers for expected failures (bad input, missing thing)."""


class API:
    def __init__(self, name):
        self.name = name
        self.methods = {}
        self.docs = {}
        self.on_call = None  # hook(method, params, peer, result|None, error|None, seconds)
        self.authorize = None  # hook(method, params, peer, interactive): raises RPCError when not allowed

    def method(self, name, doc=None):
        def deco(fn):
            self.methods[name] = fn
            self.docs[name] = {"doc": (doc or inspect.getdoc(fn) or "").strip(), "params": _params(fn)}
            return fn
        return deco

    def describe(self):
        return {k: self.docs[k] for k in sorted(self.methods)}

    async def dispatch(self, req, peer, loop):
        mid = req.get("id")
        name = req.get("method")
        params = req.get("params") or {}
        fn = self.methods.get(name)
        t0 = time.monotonic()
        if fn is None:
            return {"id": mid, "error": {"type": "NoSuchMethod", "message": f"unknown method {name!r}",
                                         "hint": "call 'api.describe' for the list"}}
        if not isinstance(params, dict):
            return {"id": mid, "error": {"type": "BadParams", "message": "params must be an object"}}
        try:
            kwargs = dict(params)
            interactive = kwargs.pop("_interactive", True) is not False
            if self.authorize:
                await loop.run_in_executor(None, lambda: self.authorize(name, kwargs, peer, interactive))
            if "_peer" in _params(fn):
                kwargs["_peer"] = peer
            if inspect.iscoroutinefunction(fn):
                result = await fn(**kwargs)
            else:
                result = await loop.run_in_executor(None, lambda: fn(**kwargs))
            resp = {"id": mid, "result": result}
            err = None
        except TypeError as e:
            err = {"type": "BadParams", "message": str(e), "params": self.docs[name]["params"]}
            resp = {"id": mid, "error": err}
            result = None
        except RPCError as e:
            err = {"type": "Error", "message": str(e)}
            resp = {"id": mid, "error": err}
            result = None
        except Exception as e:  # report, never crash the daemon
            err = {"type": type(e).__name__, "message": str(e), "trace": traceback.format_exc()[-2000:]}
            resp = {"id": mid, "error": err}
            result = None
        if self.on_call:
            try:
                self.on_call(name, params, peer, result, err, time.monotonic() - t0)
            except Exception:
                pass
        return resp


def _params(fn):
    out = {}
    for p in inspect.signature(fn).parameters.values():
        if p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            continue
        out[p.name] = None if p.default is inspect.Parameter.empty else p.default
    return out


def peer_cred(sock):
    try:
        data = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", data)
        return {"pid": pid, "uid": uid, "gid": gid}
    except OSError:
        return {"pid": None, "uid": None, "gid": None}


async def serve(api, path, mode=0o660, group=None, ready=None):
    """Serve `api` on unix socket `path` forever."""
    if os.path.exists(path):
        os.unlink(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    loop = asyncio.get_running_loop()
    loop.set_default_executor(__import__("concurrent.futures").futures.ThreadPoolExecutor(max_workers=16))

    @api.method("api.describe")
    def _describe():
        """List every method with its parameters and documentation."""
        return api.describe()

    @api.method("api.ping")
    def _ping(_peer=None):
        """Liveness check; returns the server name and the caller's credentials."""
        return {"server": api.name, "peer": _peer, "time": time.time()}

    async def handle(reader, writer):
        sock = writer.get_extra_info("socket")
        peer = peer_cred(sock)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    req = json.loads(line)
                except json.JSONDecodeError as e:
                    writer.write((jdump({"id": None, "error": {"type": "BadJSON", "message": str(e)}}) + "\n").encode())
                    await writer.drain()
                    continue
                resp = await api.dispatch(req, peer, loop)
                writer.write((jdump(resp) + "\n").encode())
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    server = await asyncio.start_unix_server(handle, path=path, limit=MAX_LINE)
    os.chmod(path, mode)
    if group is not None:
        try:
            import grp
            os.chown(path, -1, grp.getgrnam(group).gr_gid)
        except KeyError:
            pass
    if ready:
        ready()
    async with server:
        await server.serve_forever()


class Client:
    """Blocking client. `Client(path).call("pkg.info", name="btop")`."""

    def __init__(self, path, timeout=3600):
        self.path = path
        self.timeout = timeout
        self._sock = None
        self._buf = b""
        self._id = 0

    def _connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self.path)
        self._sock = s

    def call(self, method, **params):
        if self._sock is None:
            self._connect()
        self._id += 1
        msg = (jdump({"id": self._id, "method": method, "params": params}) + "\n").encode()
        try:
            self._sock.sendall(msg)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._connect()
            self._sock.sendall(msg)
        while b"\n" not in self._buf:
            chunk = self._sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError(f"{self.path} closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        resp = json.loads(line)
        if "error" in resp:
            e = resp["error"]
            raise RemoteError(e.get("type", "Error"), e.get("message", ""), e)
        return resp.get("result")

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None


class RemoteError(Exception):
    def __init__(self, kind, message, raw):
        super().__init__(f"{kind}: {message}")
        self.kind, self.message, self.raw = kind, message, raw
