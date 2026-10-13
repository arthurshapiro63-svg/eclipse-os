"""btrfs snapshots of / (Arclight whole-disk layout: subvolumes @, @home, @snapshots, @log, @pkg).

Snapshots live in /.snapshots/<id> (read-only) with a JSON sidecar. Rollback swaps the
@ subvolume for a writable copy of a snapshot; the old @ is kept as @rollback-<time>.
On a side-by-side (ext4 deployment directory) install snapshots are not available.
"""
import json
import os
import re
import time
from pathlib import Path

from ..rpc import RPCError
from ..util import run, run_full

SNAPDIR = Path("/.snapshots")
TOP = Path("/run/arclight/btrfs-top")


def supported():
    fs = run(["findmnt", "-no", "FSTYPE", "/"], check=False).strip()
    return fs == "btrfs" and SNAPDIR.is_dir()


def _require():
    if not supported():
        raise RPCError("snapshots need a btrfs root with /.snapshots (whole-disk Arclight install)")


def snap_list():
    """All snapshots, newest first."""
    if not supported():
        return {"supported": False, "snapshots": []}
    out = []
    for d in sorted(SNAPDIR.iterdir(), reverse=True):
        if d.is_dir() and re.fullmatch(r"\d{8}-\d{6}(-[a-z0-9-]+)?", d.name):
            meta = SNAPDIR / f"{d.name}.json"
            m = json.loads(meta.read_text()) if meta.exists() else {}
            out.append({"id": d.name, **m})
    return {"supported": True, "snapshots": out}


def create(label="manual", keep=None):
    """Read-only snapshot of / right now."""
    _require()
    slug = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")[:40] or "manual"
    sid = time.strftime("%Y%m%d-%H%M%S") + "-" + slug
    run(["btrfs", "subvolume", "snapshot", "-r", "/", str(SNAPDIR / sid)], timeout=120)
    (SNAPDIR / f"{sid}.json").write_text(json.dumps({"label": label, "time": time.time()}))
    if keep:
        prune(int(keep))
    return {"id": sid, "label": label}


def prune(keep=20):
    """Delete the oldest automatic snapshots beyond `keep`."""
    _require()
    snaps = [s for s in snap_list()["snapshots"] if not s.get("pinned")]
    removed = []
    for s in snaps[keep:]:
        delete(s["id"])
        removed.append(s["id"])
    return {"removed": removed}


def delete(id):
    """Delete one snapshot."""
    _require()
    p = SNAPDIR / id
    if not p.is_dir() or "/" in id:
        raise RPCError(f"no snapshot {id}")
    run(["btrfs", "subvolume", "delete", str(p)], timeout=300)
    (SNAPDIR / f"{id}.json").unlink(missing_ok=True)
    return {"deleted": id}


def _mount_top():
    TOP.mkdir(parents=True, exist_ok=True)
    if not os.path.ismount(TOP):
        dev = run(["findmnt", "-no", "SOURCE", "/"]).strip().split("[")[0]
        run(["mount", "-o", "subvolid=5", dev, str(TOP)])
    return TOP


def rollback(id):
    """Make snapshot `id` the root filesystem at the next boot. The current root is kept."""
    _require()
    if not (SNAPDIR / id).is_dir():
        raise RPCError(f"no snapshot {id}")
    top = _mount_top()
    try:
        if not (top / "@").is_dir():
            raise RPCError("root subvolume is not named @; cannot roll back automatically")
        backup = f"@rollback-{time.strftime('%Y%m%d-%H%M%S')}"
        os.rename(top / "@", top / backup)
        r = run_full(["btrfs", "subvolume", "snapshot", str(top / "@snapshots" / id), str(top / "@")])
        if r["code"] != 0:
            os.rename(top / backup, top / "@")
            raise RPCError(f"snapshot failed, nothing changed: {r['stderr']}")
    finally:
        run(["umount", str(top)], check=False)
    return {"rolled_back_to": id, "previous_root_kept_as": backup, "note": "reboot to use it"}


def register(api):
    api.method("snap.list")(snap_list)
    api.method("snap.create")(create)
    api.method("snap.delete")(delete)
    api.method("snap.prune")(prune)
    api.method("snap.rollback")(rollback)
