"""systemd services and the journal (system scope; the session daemon handles --user)."""
import json
import re

from ..rpc import RPCError
from ..util import run, run_full, clip_text

ENV = {"LANG": "C", "LC_ALL": "C", "SYSTEMD_COLORS": "0"}
PROPS = ("Id,Description,LoadState,ActiveState,SubState,UnitFileState,MainPID,Result,NRestarts,"
         "ExecMainStartTimestamp,ActiveEnterTimestamp,MemoryCurrent,CPUUsageNSec,FragmentPath,DropInPaths,"
         "Triggers,TriggeredBy,After,Wants")
ACTIONS = ("start", "stop", "restart", "reload", "try-restart", "enable", "disable", "reenable", "mask", "unmask",
           "kill", "reset-failed")


def _unit(u):
    if not u or not re.fullmatch(r"[A-Za-z0-9@:._\\\-]+", u):
        raise RPCError(f"not a unit name: {u!r}")
    return u


def sctl(user):
    return ["systemctl", "--user"] if user else ["systemctl"]


def jctl(user):
    return ["journalctl", "--user"] if user else ["journalctl"]


def svc_list(state=None, kind="service", query=None, user=False):
    """Units with their load/active/sub state. kind: service|timer|socket|mount|target|all."""
    cmd = sctl(user) + ["list-units", "--all", "--output=json", "--no-pager"]
    if kind and kind != "all":
        cmd += ["--type", kind]
    if state:
        cmd += ["--state", state]
    units = json.loads(run(cmd, env=ENV) or "[]")
    files = {}
    try:
        for f in json.loads(run(sctl(user) + ["list-unit-files", "--output=json", "--no-pager"] +
                                (["--type", kind] if kind and kind != "all" else []), env=ENV) or "[]"):
            files[f["unit_file"]] = f["state"]
    except Exception:
        pass
    out = []
    seen = set()
    for u in units:
        name = u.get("unit")
        seen.add(name)
        out.append({"unit": name, "load": u.get("load"), "active": u.get("active"), "sub": u.get("sub"),
                    "enabled": files.get(name), "description": u.get("description")})
    if not state:
        for name, st in files.items():
            if name not in seen and "@" not in name:
                out.append({"unit": name, "load": "not-loaded", "active": "inactive", "sub": "dead", "enabled": st})
    if query:
        q = query.lower()
        out = [u for u in out if q in u["unit"].lower() or q in (u.get("description") or "").lower()]
    return sorted(out, key=lambda u: u["unit"])


def svc_status(unit, lines=30, user=False):
    """Detailed state of one unit plus its most recent log lines."""
    unit = _unit(unit)
    props = {}
    for line in run(sctl(user) + ["show", unit, "-p", PROPS], env=ENV).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    logs = run(jctl(user) + ["-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"], env=ENV, check=False)
    return {"properties": props, "recent_log": logs.splitlines()}


def svc_action(unit, action, now=True, user=False):
    """start|stop|restart|reload|enable|disable|mask|unmask|... a unit. enable/disable use --now by default."""
    unit = _unit(unit)
    if action not in ACTIONS:
        raise RPCError(f"action must be one of {', '.join(ACTIONS)}")
    cmd = sctl(user) + [action]
    if now and action in ("enable", "disable", "mask"):
        cmd.append("--now")
    cmd.append(unit)
    r = run_full(cmd, env=ENV, timeout=300)
    st = run_full(sctl(user) + ["show", unit, "-p", "ActiveState,SubState,UnitFileState,Result"], env=ENV)["stdout"]
    state = dict(l.split("=", 1) for l in st.splitlines() if "=" in l)
    if r["code"] != 0:
        tail = run(jctl(user) + ["-u", unit, "-n", "20", "--no-pager"], env=ENV, check=False)
        raise RPCError(f"systemctl {action} {unit} failed: {(r['stderr'] or r['stdout']).strip()}\nstate: {state}\n"
                       f"recent log:\n{tail}")
    return {"unit": unit, "action": action, "state": state, "output": (r["stdout"] + r["stderr"]).strip()}


def daemon_reload(user=False):
    """systemctl daemon-reload."""
    run(sctl(user) + ["daemon-reload"], env=ENV)
    return {"ok": True}


def _journal(args, lines, user=False):
    out = run(jctl(user) + args + ["-o", "json", "-n", str(lines), "--no-pager"], env=ENV, check=False, timeout=120)
    rows = []
    for l in out.splitlines():
        try:
            j = json.loads(l)
        except json.JSONDecodeError:
            continue
        msg = j.get("MESSAGE")
        if isinstance(msg, list):  # binary message
            msg = bytes(x for x in msg if isinstance(x, int)).decode(errors="replace")
        rows.append({
            "time": int(j.get("__REALTIME_TIMESTAMP", 0)) // 1000000,
            "unit": j.get("_SYSTEMD_UNIT") or j.get("_SYSTEMD_USER_UNIT") or j.get("UNIT"),
            "ident": j.get("SYSLOG_IDENTIFIER") or j.get("_COMM"),
            "prio": int(j.get("PRIORITY", 6)),
            "pid": j.get("_PID"),
            "msg": clip_text(msg, 2000),
        })
    return rows


def log_query(unit=None, user_unit=None, since=None, until=None, priority=None, grep=None, boot=None,
              kernel=False, identifier=None, lines=200, user=False):
    """Query the journal. since/until accept journalctl syntax ('1h ago', 'today', '2026-10-08 10:00').
    priority: 0-7 or emerg..debug (shows that level and worse). boot: 0 = this boot, -1 = previous."""
    args = []
    if unit:
        args += ["-u", _unit(unit)]
    if user_unit:
        args += ["--user-unit", _unit(user_unit)]
    if since:
        args += ["-S", str(since)]
    if until:
        args += ["-U", str(until)]
    if priority is not None:
        args += ["-p", str(priority)]
    if grep:
        args += ["-g", str(grep)]
    if boot is not None:
        args += ["-b", str(boot)]
    if kernel:
        args += ["-k"]
    if identifier:
        args += ["-t", str(identifier)]
    return _journal(args, int(lines), user=user)


def log_errors(since="-0h", boot=0, user=False):
    """Everything wrong right now: failed units, error-level messages grouped by source, coredumps."""
    args = ["-p", "3", "-b", str(boot)]
    if since and since != "-0h":
        args += ["-S", since]
    rows = _journal(args, 2000, user=user)
    groups = {}
    for r in rows:
        key = r["unit"] or r["ident"] or "?"
        g = groups.setdefault(key, {"source": key, "count": 0, "last": None, "samples": []})
        g["count"] += 1
        g["last"] = r["time"]
        if r["msg"] not in g["samples"]:
            g["samples"] = (g["samples"] + [r["msg"]])[-3:]
    failed = [l.split()[0] for l in run(sctl(user) + ["--failed", "--no-legend", "--plain", "--no-pager"],
                                         env=ENV, check=False).splitlines() if l.strip()]
    cores = []
    cd = run_full(["coredumpctl", "list", "--json=short", "--no-pager", "-S", "-7d"], env=ENV)
    if cd["code"] == 0 and cd["stdout"].strip():
        try:
            cores = [{"time": c.get("time"), "exe": c.get("exe"), "pid": c.get("pid"), "sig": c.get("sig")}
                     for c in json.loads(cd["stdout"])][-20:]
        except json.JSONDecodeError:
            pass
    return {"failed_units": failed, "error_sources": sorted(groups.values(), key=lambda g: -g["count"]),
            "coredumps_7d": cores}


def boots():
    """List boots known to the journal."""
    return json.loads(run(["journalctl", "--list-boots", "-o", "json", "--no-pager"], env=ENV, check=False) or "[]")


def register(api):
    api.method("svc.list")(svc_list)
    api.method("svc.status")(svc_status)
    api.method("svc.action")(svc_action)
    api.method("svc.daemon_reload")(daemon_reload)
    api.method("log.query")(log_query)
    api.method("log.errors")(log_errors)
    api.method("log.boots")(boots)
