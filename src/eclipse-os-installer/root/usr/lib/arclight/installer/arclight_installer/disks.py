"""Disk discovery for the installer. Everything here is read-only: probing an existing system mounts
its partitions READ-ONLY under /run/arclight-install/probe and unmounts them again."""
import json
import os
import re
import subprocess
from pathlib import Path

PROBE = Path("/run/arclight-install/probe")
GiB = 1024 ** 3


def sh(cmd, check=True, timeout=120):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def uefi():
    return Path("/sys/firmware/efi").exists()


def live_device():
    """The device the live medium itself runs from (never offered as a target)."""
    out = sh(["findmnt", "-no", "SOURCE", "/run/archiso/bootmnt"], check=False).strip()
    if not out:
        return None
    pk = sh(["lsblk", "-no", "PKNAME", out], check=False).strip()
    return f"/dev/{pk}" if pk else out


def lsblk():
    return json.loads(sh(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,FSVER,UUID,PARTUUID,PARTTYPE,LABEL,"
                          "PARTLABEL,MOUNTPOINTS,MODEL,RM,RO,TRAN,PTTYPE"]))["blockdevices"]


ESP_TYPES = {"c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "0xef"}


def free_regions(disk):
    """Unpartitioned regions >= 1 GiB, as (start_sector, end_sector, bytes)."""
    out = sh(["sfdisk", "--list-free", "--bytes", disk], check=False)
    regs = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+\d+\s+(\d+)", line)
        if m and int(m.group(3)) >= GiB:
            regs.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return regs


class LayoutError(RuntimeError):
    """The old system's layout is one the migration cannot handle safely (said in plain words)."""


def old_mount_opts(fstype):
    """Read-only mount options for an old system's partition. Btrfs is always mounted at its TOP level
    (subvolid=5), whatever its default subvolume is, so paths are the same everywhere: probe, plan, engine."""
    if fstype == "ext4":
        return "ro,noload"
    if fstype == "btrfs":
        return "ro,subvolid=5"
    return "ro"


def device_ids(partition):
    """Every way an fstab can name `partition`: UUID=, PARTUUID=, LABEL=, PARTLABEL=, paths (lower-case)."""
    out = sh(["blkid", "-o", "export", partition], check=False)
    ids = {partition.lower()}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        if k in ("UUID", "PARTUUID", "LABEL", "PARTLABEL") and v:
            ids.add(f"{k}={v}".lower())
            ids.add(f"/dev/disk/by-{k.lower()}/{v}".lower())
    return ids


def _fstab(text):
    rows = []
    for line in (text or "").splitlines():
        f = line.split("#", 1)[0].split()
        if len(f) >= 3:
            unesc = [x.replace("\\040", " ") for x in f]
            rows.append({"src": unesc[0].strip('"'), "mnt": unesc[1].rstrip("/") or "/", "type": unesc[2],
                         "opts": dict((o.split("=", 1) + [""])[:2] for o in (unesc[3] if len(unesc) > 3 else "").split(","))})
    return rows


def resolve_old_path(path, root_subdir, fstab_text, ids, fstype):
    """Where `path` (as the OLD system sees it, e.g. /home/arthur) lives, relative to the top level of the
    old root partition as mounted by old_mount_opts(). Follows the old fstab:

      * on the root filesystem itself        -> <root_subdir>/home/arthur   (@/home/arthur on btrfs)
      * a btrfs subvolume of the same disk   -> <subvol>/arthur             (@home/arthur)
      * anything else (another partition, bind mounts, subvolid= only, network) -> LayoutError."""
    path = "/" + path.strip("/")
    best = None
    for r in _fstab(fstab_text):
        if r["mnt"] == "/" or path == r["mnt"] or path.startswith(r["mnt"] + "/"):
            if r["type"] in ("swap",) or not r["mnt"].startswith("/"):
                continue
            if best is None or len(r["mnt"]) > len(best["mnt"]):
                best = r
    if best is None or best["mnt"] == "/":
        return "/".join(x for x in (root_subdir.strip("/"), path.strip("/")) if x)
    where = f"{best['mnt']} (from {best['src']})"
    if "bind" in best["opts"] or "rbind" in best["opts"] or best["type"] == "none":
        raise LayoutError(f"{where} is a bind mount in the old system; moving files from it is not supported")
    if best["src"].lower() not in ids:
        raise LayoutError(f"{where} is on a different partition than the old system; "
                          "copy those files yourself after the install (they are not touched)")
    if best["type"] != "btrfs" or fstype != "btrfs":
        raise LayoutError(f"{where} mounts the same {fstype} filesystem twice; this layout is not supported")
    sub = best["opts"].get("subvol")
    if sub is None:
        if "subvolid" in best["opts"] and best["opts"]["subvolid"] not in ("5", "0"):
            raise LayoutError(f"{where} is a btrfs subvolume chosen by id ({best['opts']['subvolid']}); "
                              "give it a subvol= path in the old fstab, or copy the files yourself")
        sub = ""   # no subvol option: the top level (or subvolid=5)
    rest = path[len(best["mnt"]):].strip("/")
    return "/".join(x for x in (sub.strip("/"), rest) if x)


def probe_os(dev, fstype):
    """Mount a partition read-only and look for an installed Linux system. Returns facts or None."""
    if fstype not in ("ext4", "btrfs", "xfs", "f2fs"):
        return None
    mnt = PROBE / Path(dev).name
    mnt.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["mount", "-o", old_mount_opts(fstype), dev, str(mnt)], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        roots = [mnt]
        if fstype == "btrfs":
            roots = [mnt / "@"] + [mnt]
        for root in roots:
            osr = None
            for f in ("etc/os-release", "usr/lib/os-release"):
                p = root / f
                if p.exists() or p.is_symlink():
                    try:
                        osr = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', (p if not p.is_symlink() else (root / "usr/lib/os-release")).read_text(), re.M))
                    except OSError:
                        osr = {}
                    break
            if osr is None:
                continue
            st = os.statvfs(mnt)
            homes = []
            hb = root / "home"
            if hb.is_dir():
                for h in sorted(hb.iterdir()):
                    if h.is_dir() and not h.name.startswith("."):
                        homes.append(h.name)
            users = []
            try:
                for line in (root / "etc/passwd").read_text().splitlines():
                    f = line.split(":")
                    if len(f) >= 7 and 1000 <= int(f[2]) < 60000:
                        users.append({"name": f[0], "uid": int(f[2]), "gid": int(f[3]), "gecos": f[4], "home": f[5], "shell": f[6]})
            except (OSError, ValueError):
                pass
            hostname = (root / "etc/hostname").read_text().strip() if (root / "etc/hostname").exists() else ""
            tz = os.readlink(root / "etc/localtime").split("zoneinfo/")[-1] if (root / "etc/localtime").is_symlink() else ""
            locale = ""
            if (root / "etc/locale.conf").exists():
                m = re.search(r"^LANG=(.*)$", (root / "etc/locale.conf").read_text(), re.M)
                locale = m.group(1).strip() if m else ""
            keymap = ""
            if (root / "etc/vconsole.conf").exists():
                m = re.search(r"^KEYMAP=(.*)$", (root / "etc/vconsole.conf").read_text(), re.M)
                keymap = m.group(1).strip() if m else ""
            return {"name": osr.get("PRETTY_NAME") or osr.get("NAME") or "Linux", "id": osr.get("ID", ""),
                    "root_subdir": str(root.relative_to(mnt)) if root != mnt else "",
                    "free": st.f_bavail * st.f_frsize, "size": st.f_blocks * st.f_frsize,
                    "used": (st.f_blocks - st.f_bfree) * st.f_frsize, "homes": homes, "users": users,
                    "hostname": hostname, "timezone": tz, "locale": locale, "keymap": keymap,
                    "has_arclight": (mnt / "arclight/deploy").exists()}
        return None
    finally:
        subprocess.run(["umount", str(mnt)], capture_output=True)


def scan():
    """Disks with partitions, ESPs, free space and any installed OS found on them."""
    live = live_device()
    disks = []
    for d in lsblk():
        if d["type"] != "disk" or d["path"] == live or d["path"].startswith(("/dev/loop", "/dev/zram", "/dev/sr")):
            continue
        if int(d.get("size") or 0) < 16 * GiB:
            continue
        parts = []
        for p in d.get("children") or []:
            if p["type"] != "part":
                continue
            info = {"path": p["path"], "size": int(p["size"]), "fstype": p.get("fstype"), "uuid": p.get("uuid"),
                    "partuuid": p.get("partuuid"), "parttype": (p.get("parttype") or "").lower(),
                    "label": p.get("label") or p.get("partlabel")}
            info["esp"] = info["parttype"] in ESP_TYPES and info["fstype"] == "vfat"
            if not info["esp"]:
                info["os"] = probe_os(p["path"], info["fstype"])
            parts.append(info)
        disks.append({"path": d["path"], "model": (d.get("model") or "").strip(), "size": int(d["size"]),
                      "pttype": d.get("pttype"), "removable": bool(d.get("rm")), "parts": parts,
                      "free_regions": free_regions(d["path"]) if parts else [],
                      "empty": not parts})
    return disks


def efi_entries():
    out = sh(["efibootmgr", "-v"], check=False) if uefi() else ""
    entries, order, current = {}, [], None
    for line in out.splitlines():
        m = re.match(r"BootOrder: (.*)", line)
        if m:
            order = [x.strip() for x in m.group(1).split(",") if x.strip()]
        m = re.match(r"BootCurrent: (\w+)", line)
        if m:
            current = m.group(1)
        m = re.match(r"Boot(\w{4})(\*?) (.+?)\t(.*)$", line) or re.match(r"Boot(\w{4})(\*?) (.+?)  (.*)$", line)
        if m:
            entries[m.group(1)] = {"num": m.group(1), "active": m.group(2) == "*", "label": m.group(3).strip(),
                                   "path": m.group(4)}
    return {"order": order, "entries": entries, "current": current}


def existing_loaders(esp_mount):
    """EFI binaries already on an ESP (so the Arclight boot menu can chainload the old system)."""
    out = []
    base = Path(esp_mount) / "EFI"
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        if d.name.lower() in ("arclight", "boot", "linux"):
            continue
        for f in sorted(d.glob("*.efi")) + sorted(d.glob("*.EFI")):
            out.append({"vendor": d.name, "path": "/" + str(f.relative_to(esp_mount)).replace("/", "/")})
    return out


def old_home_in(mnt, partition, fstype, root_subdir, home):
    """For planners: the old home under `mnt` (old partition mounted with old_mount_opts). LayoutError if
    the layout is not supported."""
    fstab = mnt / root_subdir / "etc/fstab"
    rel = resolve_old_path(home, root_subdir, fstab.read_text() if fstab.exists() else "", device_ids(partition), fstype)
    return mnt / rel

