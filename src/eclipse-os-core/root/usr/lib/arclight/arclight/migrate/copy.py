"""Copy and verify: the data-moving half of migration. Never deletes or changes the source.

copy_item()   rsync -aHAX of one plan item into the staged target
verify_item() content check of source vs target (rsync --checksum dry-run: any difference fails)
fingerprint() metadata fingerprint of a whole tree (to prove a source was left untouched)
export/import bundles for whole-disk installs (tar.zst + per-file sha256 list)
"""
import hashlib
import json
import os
import stat
import subprocess
import time
from pathlib import Path


class MigrationError(RuntimeError):
    pass


def _rsync(args, timeout=None):
    return subprocess.run(["rsync"] + args, capture_output=True, text=True, timeout=timeout)


def copy_item(src_home, dst_home, rel, progress=None):
    src = Path(src_home) / rel
    dst = Path(dst_home) / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir() and not src.is_symlink():
        args = ["-aHAXS", "--numeric-ids", "--info=progress2", "--no-inc-recursive", f"{src}/", f"{dst}/"]
    else:
        args = ["-aHAXS", "--numeric-ids", str(src), str(dst)]
    p = subprocess.Popen(["rsync"] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    buf = ""
    while True:
        ch = p.stdout.read(1)
        if not ch:
            break
        if ch in "\r\n":
            if progress and buf.strip():
                progress(rel, buf.strip())
            buf = ""
        else:
            buf += ch
    err = p.stderr.read()
    if p.wait() not in (0, 24):  # 24 = files vanished during copy (only possible on a live source)
        raise MigrationError(f"copy of {rel} failed (rsync {p.returncode}): {err.strip()[-600:]}")
    return True


def mirror_parents(src_home, dst_home, rel, uid, gid):
    """Folders created on the way to a copied/shared item (e.g. ~/.local and ~/.local/share for
    ~/.local/share/Steam) are made by root: give each the owner, mode and times of the same folder in the old
    home (or the user's ownership if it did not exist there). Returns how many were fixed."""
    n = 0
    parts = Path(rel).parts
    for i in range(1, len(parts) + 1):
        d = Path(dst_home).joinpath(*parts[:i])
        s = Path(src_home).joinpath(*parts[:i])
        try:
            dst = os.lstat(d)
        except FileNotFoundError:
            break
        if not stat.S_ISDIR(dst.st_mode) or dst.st_uid != 0:
            continue
        try:
            st = os.lstat(s)
            os.lchown(d, st.st_uid, st.st_gid)
            os.chmod(d, st.st_mode & 0o7777)
            os.utime(d, ns=(st.st_atime_ns, st.st_mtime_ns))
        except FileNotFoundError:
            os.lchown(d, uid, gid)
        n += 1
    return n


def verify_item(src_home, dst_home, rel):
    """Return a list of differences ([] = identical content, metadata and links)."""
    src = Path(src_home) / rel
    dst = Path(dst_home) / rel
    if src.is_dir() and not src.is_symlink():
        args = ["-aHAX", "--numeric-ids", "--checksum", "--dry-run", "--itemize-changes", f"{src}/", f"{dst}/"]
    else:
        args = ["-aHAX", "--numeric-ids", "--checksum", "--dry-run", "--itemize-changes", str(src), str(dst)]
    r = _rsync(args)
    if r.returncode not in (0, 24):
        return [f"verify error: {r.stderr.strip()[-300:]}"]
    diffs = [l for l in r.stdout.splitlines() if l.strip() and not l.startswith(".d..t") and not l.startswith(".d....")]
    return diffs


def fingerprint(root, exclude=(), limit=None):
    """sha256 over (path, type, size, mtime_ns, mode, uid, gid, link target) of every entry under root,
    plus one hash per top-level entry (so a mismatch can say where). Content is not read.
    A directory's own mtime is left out: it only changes when a child is added or removed, and
    those children are listed themselves (this lets the installer add EFI/arclight next to EFI/GRUB
    without the existing EFI folder counting as "changed")."""
    import stat as _stat
    total = hashlib.sha256()
    parts = {}
    n = 0
    root = str(root)
    ex = [os.path.join(root, e.strip("/")) for e in exclude]
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if os.path.join(dirpath, d) not in ex)
        for name in sorted(dirnames + filenames):
            p = os.path.join(dirpath, name)
            if p in ex:
                continue
            try:
                st = os.lstat(p)
            except OSError:
                continue
            link = os.readlink(p) if os.path.islink(p) else ""
            mt = 0 if _stat.S_ISDIR(st.st_mode) else st.st_mtime_ns
            size = 0 if _stat.S_ISDIR(st.st_mode) else st.st_size
            rel = os.path.relpath(p, root)
            line = f"{rel}\0{st.st_mode}\0{size}\0{mt}\0{st.st_uid}\0{st.st_gid}\0{link}\n".encode()
            total.update(line)
            top = rel.split(os.sep, 1)[0]
            parts.setdefault(top, hashlib.sha256()).update(line)
            n += 1
            if limit and n >= limit:
                break
    return {"sha256": total.hexdigest(), "entries": n, "parts": {k: v.hexdigest() for k, v in sorted(parts.items())}}


def fingerprint_diff(a, b):
    """Top-level entries whose fingerprints differ between two fingerprint() results."""
    keys = set(a.get("parts", {})) | set(b.get("parts", {}))
    return sorted(k for k in keys if a.get("parts", {}).get(k) != b.get("parts", {}).get(k))


# ---------------------------------------------------------------- bundles (whole-disk migration)

def export_bundle(src_home, plan, dest, progress=None):
    """Write the COPY items of `plan` to `dest/` as tar.zst parts + manifest + sha256 list, then verify."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    items = [i for i in plan.items if i.action == "copy"]
    listing = dest / "files.sha256"
    with open(listing, "w") as out:
        for it in items:
            base = Path(src_home) / it.path
            paths = [base] if not base.is_dir() or base.is_symlink() else (
                Path(dp) / f for dp, _, fs in os.walk(base) for f in fs)
            for p in paths:
                if p.is_file() and not p.is_symlink():
                    out.write(f"{_sha256(p)}  {p.relative_to(src_home)}\n")
    tarlist = dest / "items.txt"
    tarlist.write_text("\n".join(i.path for i in items) + "\n")
    r = subprocess.run(["tar", "--xattrs", "--acls", "--numeric-owner", "-C", str(src_home), "-T", str(tarlist),
                        "-I", "zstd -T0 -6", "-cf", str(dest / "home.tar.zst")], capture_output=True, text=True)
    if r.returncode != 0:
        raise MigrationError(f"tar failed: {r.stderr[-600:]}")
    (dest / "plan.json").write_text(plan.to_json())
    (dest / "BUNDLE.json").write_text(json.dumps({"format": "arclight-bundle-1", "created": time.time(),
                                                 "source_home": str(src_home), "items": len(items)}))
    test = subprocess.run(["tar", "-I", "zstd", "-tf", str(dest / "home.tar.zst")], capture_output=True, text=True)
    if test.returncode != 0:
        raise MigrationError("bundle archive failed its own read-back test")
    return {"dest": str(dest), "items": len(items)}


def import_bundle(bundle, dst_home):
    bundle = Path(bundle)
    if not (bundle / "BUNDLE.json").exists():
        raise MigrationError(f"{bundle} is not an Arclight bundle")
    Path(dst_home).mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["tar", "--xattrs", "--acls", "--numeric-owner", "-I", "zstd", "-C", str(dst_home), "-xpf",
                        str(bundle / "home.tar.zst")], capture_output=True, text=True)
    if r.returncode != 0:
        raise MigrationError(f"extract failed: {r.stderr[-600:]}")
    bad = []
    for line in (bundle / "files.sha256").read_text().splitlines():
        digest, rel = line.split("  ", 1)
        p = Path(dst_home) / rel
        if not p.exists() or _sha256(p) != digest:
            bad.append(rel)
    if bad:
        raise MigrationError(f"{len(bad)} files differ after import, e.g. {bad[:5]}")
    return {"imported": True}


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
