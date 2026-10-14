"""Who may do what through arclightd.

arclightd answers members of the `arclight` group. Reading the state of the machine (lists, status, logs that
the group may read anyway) is open to them. Everything that changes the system or reads what only root may read
is an administrator action: arclightd asks polkit (action dev.arclight.admin, `auth_admin`, never cached), and
polkit's authentication agent on the desktop asks the person at the computer for their password.

That password is the guarantee that a human said yes: an AI that drives the mouse and keyboard, or runs
commands as the user, can press buttons but does not know the password. With "passwordless admin" turned on
(Settings → System, system.sudo_nopasswd) a polkit rule answers YES for the arclight group instead; that is the
owner's explicit choice and Settings warns about it.

Callers that must never pop up a dialog (a background tweak) pass `_interactive: false`: polkit is asked
without interaction and the call simply fails when a password would be needed.
"""
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import time
from pathlib import Path

from ..rpc import RPCError

ACTION = "dev.arclight.admin"
# reboot / power off / sleep follow the system's own rules (logind: no password for the person at the computer),
# exactly as if the caller ran `systemctl reboot` itself
POWER_ACTIONS = {"reboot": "org.freedesktop.login1.reboot", "poweroff": "org.freedesktop.login1.power-off",
                 "suspend": "org.freedesktop.login1.suspend", "hibernate": "org.freedesktop.login1.hibernate"}

# read-only methods: open to the arclight group
OPEN = {
    "api.ping", "api.describe", "version", "sys.info", "sys.users", "sys.timezones",
    "pkg.search", "pkg.info", "pkg.list", "pkg.status", "pkg.owns", "pkg.files", "pkg.history", "pkg.orphans",
    "pkg.restart_needed",
    "svc.list", "svc.status", "log.query", "log.errors", "log.boots",
    "snap.list", "actions.tail", "events.tail", "events.add", "config.get",
}
# getters when called without the parameters that change something
GETTERS = {"sys.hostname": ("name",), "sys.timezone": ("tz", "ntp"), "sys.locale": ("lang", "keymap", "x11_layout"),
           "sys.cmdline": ("set_to", "add", "remove"), "sys.sysctl": ("value",), "sys.nopasswd": ("enable",),
           "pkg.repo": ("conf", "mirrorlist")}


# AUR builds: a root process (arclightd, or arclight-pkgsync at boot) runs yay as the user for a job that is
# already authorized; yay gets root for its `pacman` steps through arclight-asroot. Those nested calls carry a
# one-job token and may run pacman only. Tokens are files in a root-only directory, so every root process sees them.
TOKEN_DIR = Path("/run/arclight/jobtokens")


def _tfile(t):
    return TOKEN_DIR / hashlib.sha256(t.encode()).hexdigest()


def job_token(seconds=7200):
    t = secrets.token_hex(24)
    TOKEN_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(TOKEN_DIR, 0o700)
    _tfile(t).write_text(str(time.time() + seconds))
    return t


def drop_token(t):
    try:
        _tfile(t).unlink()
    except OSError:
        pass


def _token_ok(t, method, params):
    try:
        good = isinstance(t, str) and len(t) >= 32 and float(_tfile(t).read_text()) > time.time()
    except (OSError, ValueError):
        good = False
    cmd = params.get("cmd")
    return good and method == "exec" and isinstance(cmd, list) and bool(cmd) and os.path.basename(str(cmd[0])) == "pacman"


def _caller_can_read(path, peer, test="-r"):
    """Would the caller be allowed to read `path` themselves? (Then arclightd reading it changes nothing.)"""
    try:
        r = subprocess.run(["setpriv", f"--reuid={peer['uid']}", f"--regid={peer['gid']}", "--init-groups",
                            "test", test, str(path)], capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError, KeyError, TypeError):
        return False


def needs_admin(method, params, peer):
    if (peer or {}).get("uid") == 0:
        return False
    if method in OPEN:
        return False
    if method in GETTERS and all(params.get(k) in (None, "") for k in GETTERS[method]):
        return False
    # files: open when the caller could read (list: read the folder; stat: reach the path) it themselves
    if method in ("file.read", "file.list") and params.get("path") and _caller_can_read(params["path"], peer):
        return False
    if method == "file.stat" and params.get("path") and _caller_can_read(params["path"], peer, "-e"):
        return False
    return True


# ---- what the password prompt says: built only from the real request (never from a label the caller sends)

# Eclipse AI's root batches (apps/eclipse_ai/elevate.build_script): the prompt lists their commands only when the
# script is exactly that template; any other script is shown as it is.
_SAFE = r"[A-Za-z0-9_@%+=:,./~-]+"     # no spaces, quotes or shell metacharacters
_TEMPLATE = [re.compile(x) for x in (
    r"set -u", rf"exec </dev/null >>{_SAFE} 2>&1", rf"export(?: [A-Za-z_][A-Za-z0-9_]*={_SAFE})+",
    rf"cd {_SAFE} 2>/dev/null \|\| cd /",
    r"M=@@eclipse-ai:[0-9a-f]+", r"end=\$\(\(SECONDS \+ \d+\)\)",
    re.escape('run() { local left=$((end - SECONDS)); if [ "$left" -lt 1 ]; then echo "[skipped: out of time]"; '
              'return 124; fi; /usr/bin/timeout -k 5 "$left" /usr/bin/bash -c "$1"; }'),
    r'echo "\$M (begin|end|start \d+|exit \d+ \$\?)"', r"exit 0")]
_RUN = re.compile(r"run (.+)")


def _batch_commands(script):
    cmds = []
    for line in script.splitlines():
        m = _RUN.fullmatch(line)
        if m:
            try:
                parts = shlex.split(m.group(1))
            except ValueError:
                return None
            if len(parts) != 1:
                return None
            cmds.append(parts[0])
        elif not any(rx.fullmatch(line) for rx in _TEMPLATE):
            return None
    return cmds or None


def _clip(text, n=360):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def describe(method, params):
    """One line for the password prompt: exactly what this request will do."""
    from .. import redact
    p = json.loads(json.dumps(redact.redact_params(method, params), default=str))
    names = ", ".join(map(str, p.get("names") or p.get("packages") or []))
    if method == "exec":
        cmd = p.get("cmd")
        if isinstance(cmd, list) and len(cmd) == 3 and cmd[1] == "-c" and os.path.basename(str(cmd[0])) == "bash":
            batch = _batch_commands(str(cmd[2]))
            return _clip("run as root: " + (" ; ".join(batch) if batch else str(cmd[2])))
        return _clip("run as root: " + (shlex.join(map(str, cmd)) if isinstance(cmd, list) else str(cmd)))
    fixed = {
        "pkg.install": f"install software: {names}", "pkg.remove": f"remove software: {names}",
        "pkg.upgrade": "update the whole system", "pkg.refresh": "refresh the package lists",
        "sys.nopasswd": ("turn ON passwordless admin: after this, sudo, apps and AI agents can change the whole "
                         "system without asking you" if p.get("enable") else "turn off passwordless admin"),
        "sys.power": f"{p.get('action', 'change power state of')} the computer",
        "snap.rollback": "roll the whole system back to an earlier restore point",
    }
    if method in fixed:
        return _clip(fixed[method])
    if method.startswith("file."):
        return _clip(f"{method[5:]} {p.get('path') or p.get('src') or ''} {('-> ' + str(p['dst'])) if p.get('dst') else ''}"
                     " (as administrator)")
    if method == "svc.action":
        return _clip(f"{p.get('action', '')} the service {p.get('name') or p.get('unit') or ''}")
    rest = {k: v for k, v in p.items() if not k.startswith("_") and v not in (None, "")}
    return _clip(f"{method} {json.dumps(rest, ensure_ascii=False)}" if rest else method)


def _start_time(pid):
    with open(f"/proc/{pid}/stat") as f:
        raw = f.read()
    return int(raw[raw.rindex(")") + 2:].split()[19])


def authorize(method, params, peer, interactive=True):
    """Raise RPCError unless the caller may run `method` now (asking polkit when it is an admin action)."""
    token = params.pop("_job_token", None)
    if not needs_admin(method, params, peer):
        return
    if token is not None:
        if _token_ok(token, method, params):
            return
        raise RPCError("not allowed: the job token is unknown, expired, or only good for pacman")
    pid, uid = peer.get("pid"), peer.get("uid")
    if not pid or uid is None:
        raise RPCError("not allowed: the caller could not be identified")
    try:
        start = _start_time(pid)
    except (OSError, ValueError, IndexError):
        raise RPCError("not allowed: the caller is gone")
    try:
        what = describe(method, params)
    except Exception:
        what = method
    action = POWER_ACTIONS.get(params.get("action")) if method == "sys.power" else None
    cmd = ["pkcheck", "--action-id", action or ACTION, "--process", f"{pid},{start},{uid}",
           "--detail", "method", method, "--detail", "summary", what]
    if interactive:
        cmd.append("--allow-user-interaction")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise RPCError("not allowed: nobody answered the password prompt")
    if r.returncode == 0:
        return
    if r.returncode == 2 and not interactive:
        raise RPCError(f"needs the administrator password ({method}); not asked here because this is a background call")
    if r.returncode == 3:
        raise RPCError(f"not allowed: the password prompt was cancelled ({method})")
    detail = (r.stderr or r.stdout).strip()
    if "No authentication agent" in detail or "agent" in detail.lower():
        raise RPCError(f"needs the administrator password ({method}), but no password prompt is available here "
                       "(open it from the desktop session)")
    raise RPCError(f"not allowed: administrator authentication failed ({method})")
