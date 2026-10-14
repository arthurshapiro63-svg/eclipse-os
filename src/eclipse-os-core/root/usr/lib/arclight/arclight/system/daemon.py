"""arclightd: the root half of Arclight's AI interface.

Serves packages, services, logs, files, machine settings, snapshots and arbitrary root
commands on /run/arclight/arclightd.sock to members of the `arclight` group. Reading is open
to them; every change asks for the administrator password through polkit (system/authz.py),
unless the owner turned on passwordless admin. Every call is appended to /var/log/arclight/actions.jsonl together
with the process chain that made it (so the log shows whether Claude, Codex or a
human ran it). Secrets are masked before writing and the log is 0600 (arclight.redact).
"""
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

from .. import __version__
from ..rpc import API, serve
from ..util import SYSTEM_SOCK, LOG_DIR, ETC_DIR, jdump
from .. import redact
from . import authz, pkg, svc, files, sysconf, snap

CONFIG = ETC_DIR / "arclightd.json"
DEFAULTS = {"auto_snapshot": True, "snapshot_keep": 30, "socket_group": "arclight"}
AGENTS = ("claude", "codex", "arclight-ask", "arch-ai", "eclipse-ai", "opencode", "ollama")
_lock = threading.Lock()


def load_config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG.read_text()))
    except (OSError, ValueError):
        pass
    return cfg


def proc_chain(pid, depth=12):
    chain = []
    while pid and pid > 1 and len(chain) < depth:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            comm = stat[stat.index("(") + 1: stat.rindex(")")]
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
            chain.append(comm)
            pid = ppid
        except (OSError, ValueError):
            break
    return chain


def _trim(v, limit=400):
    if isinstance(v, str) and len(v) > limit:
        return v[:limit] + f"... [{len(v)} chars]"
    if isinstance(v, dict):
        return {k: _trim(x, limit) for k, x in v.items()}
    if isinstance(v, list):
        return [_trim(x, limit) for x in v[:50]]
    return v


QUIET = {"api.ping", "api.describe", "sys.info", "actions.tail", "events.tail"}


def make_logger(path):
    path.parent.mkdir(parents=True, exist_ok=True)

    def on_call(method, params, peer, result, err, seconds):
        if method in QUIET or method.endswith((".list", ".status", ".info", ".query", ".read", ".stat", ".history")):
            if not err:
                return
        chain = proc_chain(peer.get("pid"))
        agent = next((a for c in chain for a in AGENTS if c.startswith(a)), "human")
        # secrets never reach the file: secret parameters masked, typed text / file contents / stdin reduced
        # to their length, secret-looking values in commands and errors masked (arclight.redact)
        rec = {"time": time.time(), "method": method, "params": _trim(redact.redact_params(method, params or {})),
               "uid": peer.get("uid"), "agent": agent, "chain": chain[:6], "ok": err is None, "seconds": round(seconds, 3)}
        if err:
            rec["error"] = err.get("message", "")[:500]
        rec = redact.redact_record(rec, params)
        with _lock:
            redact.append_private(path, jdump(rec) + "\n")
    return on_call


def tail_jsonl(path, n=50, **filters):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(errors="replace").splitlines()[-max(n * 20, 2000):]:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if all(r.get(k) == v for k, v in filters.items() if v is not None):
            rows.append(r)
    return rows[-n:]


def build_api():
    cfg = load_config()
    api = API("arclightd")
    actions = LOG_DIR / "actions.jsonl"
    events = LOG_DIR / "events.jsonl"
    api.on_call = make_logger(actions)
    api.authorize = authz.authorize      # admin actions need the owner's password (polkit), see authz.py

    def pre_pkg(label, kw):
        if load_config().get("auto_snapshot") and snap.supported():
            try:
                names = kw.get("names") or []
                return snap.create(label=f"before pkg {label} {' '.join(names) if isinstance(names, list) else names}"[:60],
                                   keep=load_config().get("snapshot_keep"))
            except Exception as e:
                print(f"auto snapshot failed: {e}", file=sys.stderr)
        return None

    pkg.register(api, {"pre_pkg": pre_pkg})
    svc.register(api)
    files.register(api)
    sysconf.register(api)
    snap.register(api)

    @api.method("actions.tail")
    def actions_tail(n=50, agent=None, method=None):
        """The most recent actions taken through arclightd (who, what, result)."""
        return tail_jsonl(actions, int(n), agent=agent, method=method)

    @api.method("events.add")
    def events_add(kind, message, unit=None, data=None, _peer=None):
        """Record a system event (unit failure, package transaction, ...)."""
        rec = redact.redact_record({"time": time.time(), "kind": kind, "message": message, "unit": unit, "data": data})
        with _lock:
            redact.append_private(events, jdump(rec) + "\n")
        return rec

    @api.method("events.tail")
    def events_tail(n=50, kind=None):
        """Recent system events (unit failures, package transactions)."""
        return tail_jsonl(events, int(n), kind=kind)

    @api.method("config.get")
    def config_get():
        """arclightd's own configuration."""
        return load_config()

    @api.method("config.set")
    def config_set(key, value):
        """Change one arclightd option (auto_snapshot, snapshot_keep, ...)."""
        c = load_config()
        c[key] = value
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(c, indent=2) + "\n")
        return c

    @api.method("version")
    def version():
        """arclightd version."""
        return {"version": __version__}

    return api, cfg


def main():
    if os.geteuid() != 0 and not os.environ.get("ARCLIGHT_ALLOW_NONROOT"):
        print("arclightd must run as root", file=sys.stderr)
        return 1
    api, cfg = build_api()
    sock = os.environ.get("ARCLIGHT_SYSTEM_SOCK", SYSTEM_SOCK)

    def ready():
        print(f"arclightd {__version__} listening on {sock}", flush=True)
        try:
            import socket as s
            n = os.environ.get("NOTIFY_SOCKET")
            if n:
                c = s.socket(s.AF_UNIX, s.SOCK_DGRAM)
                c.connect(n if not n.startswith("@") else "\0" + n[1:])
                c.send(b"READY=1")
        except OSError:
            pass

    asyncio.run(serve(api, sock, mode=0o660, group=cfg.get("socket_group", "arclight"), ready=ready))
    return 0
