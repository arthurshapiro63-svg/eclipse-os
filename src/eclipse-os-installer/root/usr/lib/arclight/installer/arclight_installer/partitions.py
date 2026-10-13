"""Creating partitions without ever guessing which ones are new.

The installer must only format partitions it created in this run. Device names are not a safe way to
find them: numbers can have gaps (sgdisk reuses the lowest free number), and sorting names breaks at
p9/p10. So a new partition is identified by the partition table itself: the number we asked for, a
unique GUID (PARTUUID) that did not exist before, and a start sector inside the free region we chose.
The device node is then looked up by that PARTUUID, and checked again right before formatting.
"""
import json
import re
import subprocess
import time

ESP_GUID = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
LINUX_GUID = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"
BIOS_GUID = "21686148-6E49-6F68-744E-656564454649"
TYPE_CODES = {"ef00": ESP_GUID, "8300": LINUX_GUID, "ef02": BIOS_GUID}


class PartitionError(RuntimeError):
    pass


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise PartitionError(f"{' '.join(cmd)}: {(p.stderr or p.stdout).strip()[-400:]}")
    return p.stdout


def part_number(disk, node):
    """/dev/vda + /dev/vda10 -> 10; /dev/nvme0n1 + /dev/nvme0n1p9 -> 9."""
    if not node.startswith(disk):
        raise PartitionError(f"{node} is not on {disk}")
    m = re.fullmatch(r"p?(\d+)", node[len(disk):])
    if not m:
        raise PartitionError(f"cannot read the partition number of {node}")
    return int(m.group(1))


def read_table(disk, sfdisk_json=None):
    """The GPT as {number: {"node", "start", "size", "type", "uuid"}} (types and GUIDs upper-case)."""
    data = json.loads(sfdisk_json if sfdisk_json is not None else _run(["sfdisk", "--json", disk]))
    pt = data["partitiontable"]
    out = {}
    for p in pt.get("partitions", []):
        n = part_number(disk, p["node"])
        out[n] = {"node": p["node"], "start": int(p["start"]), "size": int(p["size"]),
                  "type": str(p.get("type", "")).upper(), "uuid": str(p.get("uuid", "")).upper()}
    return out


def free_numbers(table, count, max_parts=128):
    """The lowest `count` partition numbers not in use (what sgdisk would pick, but chosen by us)."""
    nums = [n for n in range(1, max_parts + 1) if n not in table][:count]
    if len(nums) < count:
        raise PartitionError("the partition table is full")
    return nums


def new_partitions(before, after, wanted, region):
    """Check the table after creating partitions and return {number: entry} for exactly the wanted ones.

    `wanted` is {number: type GUID}; `region` is (first_sector, last_sector) of the free space used.
    Raises if a wanted partition is missing, has the wrong type, reuses a GUID that existed before,
    starts outside the region, or if any partition that existed before changed or disappeared."""
    old_uuids = {e["uuid"] for e in before.values()}
    for n, e in before.items():
        a = after.get(n)
        if not a or (a["uuid"], a["start"], a["size"]) != (e["uuid"], e["start"], e["size"]):
            raise PartitionError(f"existing partition {e['node']} changed while partitioning; stopping")
    got = {}
    for n, typ in wanted.items():
        if n in before:
            raise PartitionError(f"partition {n} already existed; refusing to use it")
        a = after.get(n)
        if not a:
            raise PartitionError(f"partition {n} was not created")
        if a["type"] != typ.upper():
            raise PartitionError(f"partition {n} has type {a['type']}, expected {typ}")
        if not a["uuid"] or a["uuid"] in old_uuids:
            raise PartitionError(f"partition {n} has no new unique GUID")
        if not (region[0] <= a["start"] and a["start"] + a["size"] - 1 <= region[1]):
            raise PartitionError(f"partition {n} is outside the free space that was chosen")
        got[n] = a
    extra = set(after) - set(before) - set(wanted)
    if extra:
        raise PartitionError(f"unexpected new partitions {sorted(extra)}; stopping")
    return got


def lsblk_parts(disk):
    """Partition devices the kernel currently shows for `disk`: [{path, partuuid, pkname}]."""
    out = subprocess.run(["lsblk", "-J", "-p", "-o", "PATH,PARTUUID,PKNAME,TYPE", disk],
                         capture_output=True, text=True).stdout
    rows = []

    def walk(ds):
        for d in ds or []:
            if d.get("type") == "part":
                rows.append({"path": d["path"], "partuuid": (d.get("partuuid") or "").upper(),
                             "pkname": d.get("pkname")})
            walk(d.get("children"))
    try:
        walk(json.loads(out or "{}").get("blockdevices"))
    except ValueError:
        pass
    return rows


def wait_for_devices(disk, expected, probe=None, settle=None, tries=60, delay=0.5, sleep=None):
    """Wait until every expected {number: PARTUUID} shows up as a device on `disk`; return {number: path}.

    The kernel and udev can take a while (or a re-read) before new partitions appear, so this polls.
    A device only counts when its PARTUUID matches and it sits on `disk` with the expected number."""
    probe = probe or (lambda: lsblk_parts(disk))
    sleep = sleep or time.sleep
    for _ in range(tries):
        if settle:
            settle()
        found = {}
        for row in probe():
            if row.get("pkname") not in (None, disk):
                continue
            for n, uuid in expected.items():
                if row["partuuid"] == uuid.upper():
                    if part_number(disk, row["path"]) != n:
                        raise PartitionError(f"{row['path']} carries the GUID of partition {n}; stopping")
                    found[n] = row["path"]
        if len(found) == len(expected):
            return found
        sleep(delay)
    missing = sorted(set(expected) - set(found))
    raise PartitionError(f"the new partitions {missing} on {disk} did not appear")


def blkid_partuuid(dev):
    return subprocess.run(["blkid", "-p", "-o", "value", "-s", "PART_ENTRY_UUID", dev],
                          capture_output=True, text=True).stdout.strip().upper()


def assert_target(dev, uuid, protected, read_uuid=None):
    """Last check before mkfs: the device is the partition we created, never one that existed before."""
    if uuid.upper() in protected:
        raise PartitionError(f"{dev} is an existing partition; it is never formatted")
    got = (read_uuid or blkid_partuuid)(dev)
    if got != uuid.upper():
        raise PartitionError(f"{dev} is not the new partition (GUID {got or 'none'}, expected {uuid}); stopping")
