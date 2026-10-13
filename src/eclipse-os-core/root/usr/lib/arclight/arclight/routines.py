"""AI routines: requests the AI carries out on a schedule ("every morning at 9, update the system and tell me
what changed"). Each routine is a systemd user timer that runs the Ask agent without a window and then sends a
notification with the result; every run is logged. Timers are Persistent, so a run missed while the PC was off
happens at the next start.

  arclight-routine list
  arclight-routine add NAME SCHEDULE PROMPT     SCHEDULE: "daily 09:00", "weekdays 08:30", "sun 10:00",
                                                "hourly", "every 2h", or any systemd OnCalendar expression
  arclight-routine remove ID | run ID | log ID | enable ID | disable ID
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CONF = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "arclight" / "routines.json"
UNITS = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
LOGS = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "arclight" / "routines"
DAYS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}


class RoutineError(Exception):
    pass


def _load():
    try:
        return json.loads(CONF.read_text())
    except (OSError, ValueError):
        return {}


def _save(d):
    CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONF.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(CONF)


def on_calendar(schedule):
    """Friendly schedule -> systemd OnCalendar (checked with systemd-analyze)."""
    s = schedule.strip().lower()
    m = re.fullmatch(r"(daily|every day)\s+(\d{1,2}):(\d{2})", s)
    if m:
        cal = f"*-*-* {int(m[2]):02d}:{m[3]}:00"
    elif (m := re.fullmatch(r"weekdays\s+(\d{1,2}):(\d{2})", s)):
        cal = f"Mon..Fri *-*-* {int(m[1]):02d}:{m[2]}:00"
    elif (m := re.fullmatch(r"weekends?\s+(\d{1,2}):(\d{2})", s)):
        cal = f"Sat,Sun *-*-* {int(m[1]):02d}:{m[2]}:00"
    elif (m := re.fullmatch(r"(mon|tue|wed|thu|fri|sat|sun)\w*\s+(\d{1,2}):(\d{2})", s)):
        cal = f"{DAYS[m[1]]} *-*-* {int(m[2]):02d}:{m[3]}:00"
    elif s in ("hourly", "every hour"):
        cal = "hourly"
    elif (m := re.fullmatch(r"every\s+(\d{1,2})\s*h(ours?)?", s)):
        cal = f"*-*-* 00/{int(m[1])}:00:00"
    elif (m := re.fullmatch(r"every\s+(\d{1,2})\s*m(in(utes?)?)?", s)):
        cal = f"*:00/{int(m[1])}"
    else:
        cal = schedule.strip()
    r = subprocess.run(["systemd-analyze", "calendar", cal], capture_output=True, text=True)
    if r.returncode != 0:
        raise RoutineError(f"I don't understand the schedule {schedule!r} (try \"daily 09:00\", "
                           f"\"weekdays 08:30\", \"sun 10:00\", \"every 2h\")")
    nxt = next((l.split(":", 1)[1].strip() for l in r.stdout.splitlines() if "Next elapse" in l), "")
    return cal, nxt


def _systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def _write_units(rid, r):
    UNITS.mkdir(parents=True, exist_ok=True)
    exe = "/usr/bin/arclight-routine"
    if not Path(exe).exists():  # development tree
        exe = str(Path(__file__).resolve().parents[1] / "bin" / "arclight-routine")
    (UNITS / f"arclight-routine-{rid}.service").write_text(
        f"[Unit]\nDescription=AI routine: {r['name']}\n\n"
        f"[Service]\nType=oneshot\nExecStart={exe} run {rid}\nTimeoutStartSec=30min\n")
    (UNITS / f"arclight-routine-{rid}.timer").write_text(
        f"[Unit]\nDescription=AI routine timer: {r['name']}\n\n"
        f"[Timer]\nOnCalendar={r['calendar']}\nPersistent=true\nRandomizedDelaySec=30\n\n"
        f"[Install]\nWantedBy=timers.target\n")
    _systemctl("daemon-reload")


def add(name, schedule, prompt):
    cal, nxt = on_calendar(schedule)
    d = _load()
    rid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "routine"
    base, i = rid, 2
    while rid in d:
        rid, i = f"{base}-{i}", i + 1
    d[rid] = {"name": name, "schedule": schedule, "calendar": cal, "prompt": prompt, "enabled": True,
              "created": time.time()}
    _save(d)
    _write_units(rid, d[rid])
    _systemctl("enable", "--now", f"arclight-routine-{rid}.timer")
    return {"id": rid, "next": nxt, **d[rid]}


def remove(rid):
    d = _load()
    if rid not in d:
        raise RoutineError(f"no routine {rid!r}")
    _systemctl("disable", "--now", f"arclight-routine-{rid}.timer")
    for ext in ("service", "timer"):
        (UNITS / f"arclight-routine-{rid}.{ext}").unlink(missing_ok=True)
    _systemctl("daemon-reload")
    r = d.pop(rid)
    _save(d)
    return {"removed": rid, "name": r["name"]}


def set_enabled(rid, on):
    d = _load()
    if rid not in d:
        raise RoutineError(f"no routine {rid!r}")
    d[rid]["enabled"] = on
    _save(d)
    _systemctl("enable" if on else "disable", "--now", f"arclight-routine-{rid}.timer")
    return {"id": rid, "enabled": on}


def listing():
    d = _load()
    out = []
    for rid, r in d.items():
        t = _systemctl("show", f"arclight-routine-{rid}.timer", "-p", "NextElapseUSecRealtime", "--value").stdout.strip()
        logs = sorted((LOGS / rid).glob("*.log")) if (LOGS / rid).exists() else []
        out.append({"id": rid, **r, "next": t, "last_run": logs[-1].stem if logs else None})
    return out


def run(rid):
    """Run one routine now (also what the timer calls): agent without a window, log, notification."""
    d = _load()
    if rid not in d:
        raise RoutineError(f"no routine {rid!r}")
    from .aigate import ai_enabled
    if not ai_enabled():
        return {"id": rid, "skipped": "the AI features are off (Settings → AI)"}
    r = d[rid]
    LOGS.joinpath(rid).mkdir(parents=True, exist_ok=True)
    log = LOGS / rid / (time.strftime("%Y-%m-%d_%H-%M") + ".log")
    request = (f"This is the scheduled routine \"{r['name']}\" ({r['schedule']}); nobody is watching right now. "
               f"Do it, then end with a short, plain summary (2-4 sentences) of what you did or found.\n\n"
               f"{r['prompt']}")
    t0 = time.time()
    p = subprocess.run(["arclight-ask", "--cli", request], capture_output=True, text=True, timeout=1800,
                       env={**os.environ, "NO_COLOR": "1"})
    out = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)
    log.write_text(f"# {r['name']}  ({time.strftime('%Y-%m-%d %H:%M')}, {time.time() - t0:.0f}s, exit {p.returncode})\n"
                   f"# prompt: {r['prompt']}\n\n{out}")
    summary = [l for l in out.strip().splitlines() if l.strip()][-6:]
    body = " ".join(summary)[-400:] or "Done (no output)."
    subprocess.run(["notify-send", "-a", "Eclipse OS", "-i", "arclight", f"Routine: {r['name']}",
                    body + f"\n(log: {log})"], capture_output=True)
    return {"id": rid, "log": str(log), "exit": p.returncode}


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a.pop(0) if a else "list"
    try:
        if cmd == "list":
            rows = listing()
            if not rows:
                print("No routines yet. Example:\n  arclight-routine add \"Morning update\" \"daily 09:00\" "
                      "\"Update the system and tell me what changed\"")
            for r in rows:
                state = "on " if r.get("enabled", True) else "off"
                print(f"{r['id']:<22} {state} {r['schedule']:<16} next: {r['next'] or '-':<30} {r['prompt'][:60]}")
        elif cmd == "add" and len(a) >= 3:
            r = add(a[0], a[1], " ".join(a[2:]))
            print(f"Added {r['id']}: {r['schedule']} (next run: {r['next']})")
        elif cmd == "remove" and a:
            print(json.dumps(remove(a[0])))
        elif cmd in ("enable", "disable") and a:
            print(json.dumps(set_enabled(a[0], cmd == "enable")))
        elif cmd == "run" and a:
            print(json.dumps(run(a[0])))
        elif cmd == "log" and a:
            logs = sorted((LOGS / a[0]).glob("*.log"))
            print(logs[-1].read_text() if logs else "no runs yet")
        else:
            print(__doc__)
            return 2
    except RoutineError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
