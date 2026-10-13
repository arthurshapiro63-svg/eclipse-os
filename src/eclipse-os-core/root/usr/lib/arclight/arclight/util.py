"""Small shared helpers: paths, subprocess, JSON, sizes."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

SYSTEM_SOCK = os.environ.get("ARCLIGHT_SYSTEM_SOCK", "/run/arclight/arclightd.sock")
STATE_DIR = Path(os.environ.get("ARCLIGHT_STATE_DIR", "/var/lib/arclight"))
LOG_DIR = Path(os.environ.get("ARCLIGHT_LOG_DIR", "/var/log/arclight"))
ETC_DIR = Path("/etc/arclight")
SHARE_DIR = Path(os.environ.get("ARCLIGHT_SHARE", "/usr/share/arclight"))


def runtime_dir():
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "arclight"


def session_sock():
    return os.environ.get("ARCLIGHT_SESSION_SOCK", str(runtime_dir() / "session.sock"))


def user_config_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "arclight"


def user_state_dir():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "arclight"


class CmdError(RuntimeError):
    def __init__(self, cmd, code, stdout, stderr):
        self.cmd, self.code, self.stdout, self.stderr = cmd, code, stdout, stderr
        tail = (stderr or stdout or "").strip()[-800:]
        super().__init__(f"`{' '.join(map(str, cmd))}` exited {code}: {tail}")


def run(cmd, timeout=120, input=None, check=True, env=None, cwd=None, ok=(0,)):
    """Run a command; return stdout. Raise CmdError on a non-ok exit when check=True."""
    if isinstance(cmd, str):
        cmd = ["bash", "-c", cmd]
    e = None
    if env:
        e = dict(os.environ)
        e.update(env)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input, env=e, cwd=cwd)
    if check and p.returncode not in ok:
        raise CmdError(cmd, p.returncode, p.stdout, p.stderr)
    return p.stdout


def run_full(cmd, timeout=600, input=None, env=None, cwd=None):
    """Run a command; return {code, stdout, stderr, seconds} and never raise on exit status."""
    if isinstance(cmd, str):
        cmd = ["bash", "-c", cmd]
    e = None
    if env:
        e = dict(os.environ)
        e.update(env)
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input, env=e, cwd=cwd)
        return {"code": p.returncode, "stdout": p.stdout, "stderr": p.stderr,
                "seconds": round(time.monotonic() - t0, 3)}
    except subprocess.TimeoutExpired as ex:
        return {"code": -1, "stdout": (ex.stdout or b"").decode(errors="replace") if isinstance(ex.stdout, bytes) else (ex.stdout or ""),
                "stderr": f"timed out after {timeout}s", "seconds": timeout}


def which(name):
    return shutil.which(name)


def human(n):
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def clip_text(s, limit=20000):
    """Trim long tool output, keeping head and tail (the tail is usually the error)."""
    if s is None or len(s) <= limit:
        return s
    head = s[: limit // 3]
    tail = s[-(2 * limit) // 3:]
    return f"{head}\n... [{len(s) - len(head) - len(tail)} chars cut] ...\n{tail}"


def jdump(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


def atomic_write(path, data, mode=None):
    """Write via temp file + fsync + rename, so readers never see a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.arclight-tmp")
    with open(tmp, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    elif path.exists():
        st = path.stat()
        os.chmod(tmp, st.st_mode & 0o7777)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
    os.replace(tmp, path)
