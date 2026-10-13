"""Files anywhere on the machine, with automatic history so every write can be reverted.

Before a file is overwritten, deleted or moved, its previous content goes into
<state>/history/files/<id>/ with a JSON record. `file.history` lists records,
`file.revert` puts a recorded version back (recording the current one first).
"""
import base64
import grp
import json
import os
import pwd
import shutil
import stat
import time
import uuid
from pathlib import Path

from ..rpc import RPCError
from ..util import STATE_DIR, atomic_write

TEXT_LIMIT = 4 * 1024 * 1024


def hist_dir():
    d = Path(os.environ.get("ARCLIGHT_HISTORY_DIR", STATE_DIR / "history/files"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _record(path, op, note=None):
    """Save the current state of `path` (if it exists) before an operation. Returns record id."""
    p = Path(path)
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    d = hist_dir() / rid
    d.mkdir(parents=True)
    rec = {"id": rid, "path": str(p), "op": op, "time": time.time(), "note": note, "existed": p.exists() or p.is_symlink()}
    if p.is_symlink():
        rec["symlink"] = os.readlink(p)
    elif p.is_file():
        shutil.copy2(p, d / "content")
        st = p.stat()
        rec.update(mode=st.st_mode & 0o7777, uid=st.st_uid, gid=st.st_gid, size=st.st_size)
    elif p.is_dir():
        if op in ("delete", "move"):
            shutil.copytree(p, d / "content", symlinks=True)
            rec["dir"] = True
    (d / "record.json").write_text(json.dumps(rec))
    return rid


def _stat(p):
    st = p.lstat()
    kind = "symlink" if stat.S_ISLNK(st.st_mode) else "dir" if stat.S_ISDIR(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else "other"
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = st.st_uid
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = st.st_gid
    d = {"path": str(p), "name": p.name, "kind": kind, "size": st.st_size, "mode": oct(st.st_mode & 0o7777),
         "owner": owner, "group": group, "mtime": int(st.st_mtime)}
    if kind == "symlink":
        d["target"] = os.readlink(p)
    return d


def read(path, offset=0, max_bytes=TEXT_LIMIT, binary=False):
    """Read a file as text (or base64 when binary=true or the file is not UTF-8)."""
    p = Path(path)
    if not p.exists():
        raise RPCError(f"no such file: {path}")
    if p.is_dir():
        raise RPCError(f"{path} is a directory; use file.list")
    size = p.stat().st_size
    with open(p, "rb") as f:
        f.seek(int(offset))
        data = f.read(int(max_bytes))
    res = {"path": str(p), "size": size, "offset": offset, "truncated": offset + len(data) < size}
    if not binary:
        try:
            res["text"] = data.decode("utf-8")
            return res
        except UnicodeDecodeError:
            pass
    res["base64"] = base64.b64encode(data).decode()
    return res


def write(path, content=None, base64_content=None, mode=None, owner=None, group=None, append=False, mkdirs=True,
          note=None):
    """Write a file atomically (any path). The old version is kept in history."""
    p = Path(path)
    if p.is_dir():
        raise RPCError(f"{path} is a directory")
    if mkdirs:
        p.parent.mkdir(parents=True, exist_ok=True)
    rid = _record(p, "write", note)
    if base64_content is not None:
        data = base64.b64decode(base64_content)
    elif content is not None:
        data = content.encode()
    else:
        raise RPCError("give content or base64_content")
    if append and p.exists():
        data = p.read_bytes() + data
    atomic_write(p, data, mode=int(mode, 8) if isinstance(mode, str) else mode)
    if owner or group:
        shutil.chown(p, user=owner, group=group)
    return {"path": str(p), "bytes": len(data), "history_id": rid}


def edit(path, old, new, count=1, note=None):
    """Replace exact text `old` with `new` in a file (count=0 replaces all). Fails if `old` is absent."""
    p = Path(path)
    text = p.read_text()
    n = text.count(old)
    if n == 0:
        raise RPCError("the text to replace was not found")
    if count == 1 and n > 1:
        raise RPCError(f"the text to replace occurs {n} times; give more context or count=0")
    text = text.replace(old, new) if count == 0 else text.replace(old, new, count)
    return write(str(p), content=text, note=note)


def listing(path, hidden=True, limit=500):
    """Directory listing with type, size, mode, owner and mtime."""
    p = Path(path)
    if not p.is_dir():
        raise RPCError(f"not a directory: {path}")
    rows = []
    for c in sorted(p.iterdir(), key=lambda c: c.name):
        if not hidden and c.name.startswith("."):
            continue
        try:
            rows.append(_stat(c))
        except OSError as e:
            rows.append({"path": str(c), "error": str(e)})
        if len(rows) >= limit:
            break
    return rows


def stat_(path):
    """Metadata for one path."""
    p = Path(path)
    if not (p.exists() or p.is_symlink()):
        raise RPCError(f"no such path: {path}")
    return _stat(p)


def delete(path, recursive=False, note=None):
    """Delete a file or directory. The content is kept in history, so file.revert brings it back."""
    p = Path(path)
    if not (p.exists() or p.is_symlink()):
        raise RPCError(f"no such path: {path}")
    if p.is_dir() and not p.is_symlink() and not recursive:
        raise RPCError(f"{path} is a directory; pass recursive=true")
    rid = _record(p, "delete", note)
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()
    return {"deleted": str(p), "history_id": rid}


def mkdir(path, mode="755", owner=None, group=None):
    """Create a directory (and parents)."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True, mode=int(mode, 8))
    if owner or group:
        shutil.chown(p, user=owner, group=group)
    return _stat(p)


def copy(src, dst, note=None):
    """Copy a file or directory tree (preserving metadata)."""
    s, d = Path(src), Path(dst)
    rid = _record(d, "write", note) if d.exists() else None
    if s.is_dir():
        shutil.copytree(s, d, symlinks=True, dirs_exist_ok=True)
    else:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
    return {"copied": str(s), "to": str(d), "history_id": rid}


def move(src, dst, note=None):
    """Move/rename a path."""
    s, d = Path(src), Path(dst)
    rid = _record(d, "write", note) if d.exists() else None
    shutil.move(str(s), str(d))
    return {"moved": str(s), "to": str(d), "history_id": rid}


def chmod(path, mode, owner=None, group=None):
    """Change mode (octal string like '644') and optionally owner/group."""
    p = Path(path)
    os.chmod(p, int(mode, 8) if isinstance(mode, str) else mode)
    if owner or group:
        shutil.chown(p, user=owner, group=group)
    return _stat(p)


def history(path=None, limit=50):
    """Saved versions (newest first), optionally only for one path."""
    recs = []
    for d in sorted(hist_dir().iterdir(), reverse=True):
        f = d / "record.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        if path and r["path"] != str(Path(path)):
            continue
        recs.append(r)
        if len(recs) >= limit:
            break
    return recs


def revert(history_id):
    """Restore the version saved in a history record (the current state is saved first)."""
    d = hist_dir() / history_id
    f = d / "record.json"
    if not f.exists():
        raise RPCError(f"no history record {history_id}")
    r = json.loads(f.read_text())
    p = Path(r["path"])
    now_id = _record(p, "revert", f"before reverting to {history_id}")
    if not r.get("existed"):
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        elif p.exists() or p.is_symlink():
            p.unlink()
        return {"path": str(p), "restored": "absent", "saved_current_as": now_id}
    if "symlink" in r:
        if p.exists() or p.is_symlink():
            p.unlink()
        os.symlink(r["symlink"], p)
    elif r.get("dir"):
        if p.exists():
            shutil.rmtree(p)
        shutil.copytree(d / "content", p, symlinks=True)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(p, (d / "content").read_bytes(), mode=r.get("mode"))
        try:
            os.chown(p, r.get("uid", -1), r.get("gid", -1))
        except PermissionError:
            pass
    return {"path": str(p), "restored": history_id, "saved_current_as": now_id}


def register(api):
    api.method("file.read")(read)
    api.method("file.write")(write)
    api.method("file.edit")(edit)
    api.method("file.list")(listing)
    api.method("file.stat")(stat_)
    api.method("file.delete")(delete)
    api.method("file.mkdir")(mkdir)
    api.method("file.copy")(copy)
    api.method("file.move")(move)
    api.method("file.chmod")(chmod)
    api.method("file.history")(history)
    api.method("file.revert")(revert)
