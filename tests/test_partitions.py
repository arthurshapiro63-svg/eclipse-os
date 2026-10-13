"""Bug 0.1.1-1: free-space installs must only ever format the partitions they created."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from arclight_installer import partitions as parts
from arclight_installer import engine as engmod

GIB = 1 << 30
SEC = 512
ESP, LIN, BIOS = parts.ESP_GUID, parts.LINUX_GUID, parts.BIOS_GUID


class FakeDisk:
    """A GPT disk: understands the sgdisk/sfdisk/lsblk/blkid calls the engine makes."""

    def __init__(self, path, size_gib, existing=(), appear_after=0):
        self.path, self.last = path, size_gib * GIB // SEC - 34
        self.table = {}
        self.n_uuid = 0
        for n, start, size, typ in existing:
            self.table[n] = {"start": start, "size": size, "type": typ, "uuid": self._uuid()}
        self.visible = set(self.table)          # what the kernel shows as devices
        self.appear_after, self.settles = appear_after, 0
        self.formatted = []

    def _uuid(self):
        self.n_uuid += 1
        return f"00000000-0000-4000-8000-{self.n_uuid:012d}"

    def node(self, n):
        return f"{self.path}p{n}" if self.path[-1].isdigit() else f"{self.path}{n}"

    def free_regions(self, _disk):
        used = sorted((e["start"], e["start"] + e["size"] - 1) for e in self.table.values())
        regs, cur = [], 2048
        for s, e in used + [(self.last + 1, self.last + 1)]:
            if s - cur >= GIB // SEC:
                regs.append((cur, s - 1, (s - cur) * SEC))
            cur = max(cur, e + 1)
        return regs

    def sfdisk_json(self):
        ps = [{"node": self.node(n), "start": e["start"], "size": e["size"], "type": e["type"], "uuid": e["uuid"]}
              for n, e in sorted(self.table.items())]
        return json.dumps({"partitiontable": {"label": "gpt", "device": self.path, "partitions": ps}})

    def sgdisk(self, args):
        it = iter(args[1:-1])
        for flag in it:
            if flag == "--zap-all":
                self.table.clear()
                self.visible.clear()
                continue
            val = next(it)
            n, rest = val.split(":", 1)
            n = int(n)
            if flag == "-n":
                start, end = rest.split(":")
                start = int(start) or max([e["start"] + e["size"] for e in self.table.values()] + [2048])
                start = (start + 2047) // 2048 * 2048
                size = (int(end[1:-1]) * GIB // SEC if end.startswith("+") and end.endswith("G") else
                        int(end[1:-1]) * (1 << 20) // SEC if end.startswith("+") else
                        (self.last if end == "0" else int(end)) - start + 1)
                assert n not in self.table, f"sgdisk would fail: {n} exists"
                self.table[n] = {"start": start, "size": size, "type": LIN, "uuid": self._uuid()}
            elif flag == "-t":
                self.table[n]["type"] = {"ef00": ESP, "8300": LIN, "ef02": BIOS}[rest]

    def settle(self):
        self.settles += 1
        if self.settles > self.appear_after:
            self.visible = set(self.table)

    def lsblk(self):
        return [{"path": self.node(n), "partuuid": self.table[n]["uuid"], "pkname": self.path}
                for n in sorted(self.visible) if n in self.table]

    def blkid_uuid(self, dev):
        n = parts.part_number(self.path, dev)
        return self.table[n]["uuid"] if n in self.table else ""

    def sh(self, cmd, check=True, **kw):
        cmd = [str(c) for c in cmd]
        if cmd[0] == "sgdisk":
            self.sgdisk(cmd)
        elif cmd[0] in ("partprobe", "udevadm"):
            if cmd[0] == "udevadm":
                self.settle()
        elif cmd[0].startswith("mkfs"):
            self.formatted.append(cmd[-1])
        elif cmd[:2] == ["blkid", "-o"]:
            return "vfat\n" if cmd[-2] == "TYPE" else f"uuid-of-{cmd[-1]}\n"
        return ""


def run_partition(disk, cfg):
    tmp = tempfile.mkdtemp()
    with mock.patch.object(engmod, "LOG", Path(tmp) / "install.log"), \
            mock.patch.object(engmod.disks, "free_regions", disk.free_regions), \
            mock.patch.object(parts, "_run", lambda cmd: disk.sfdisk_json()), \
            mock.patch.object(parts, "lsblk_parts", lambda d: disk.lsblk()), \
            mock.patch.object(parts, "blkid_partuuid", disk.blkid_uuid), \
            mock.patch.object(parts.time, "sleep", lambda s: None):
        e = engmod.Engine({"disk": disk.path, "os_name": "Eclipse OS", **cfg})
        e.sh = disk.sh
        e.partition()
        return e


class EngineFreeSpace(unittest.TestCase):
    def test_gap_in_numbering_new_esp(self):
        # existing 1 (EFI of another OS) and 3 (data); 2 is a gap. Sorting names would pick 3 as "new".
        d = FakeDisk("/dev/vda", 64, existing=[(1, 2048, 1048576, ESP), (3, 3 * 1048576, 20 * 2097152, LIN)])
        keep = {n: dict(e) for n, e in d.table.items()}
        e = run_partition(d, {"mode": "free"})
        self.assertEqual((e.esp_dev, e.root_dev), ("/dev/vda2", "/dev/vda4"))
        self.assertEqual(d.formatted, ["/dev/vda2", "/dev/vda4"])
        for n, old in keep.items():
            self.assertEqual(d.table[n], old)

    def test_ten_plus_partitions_nvme(self):
        ex = [(n, 2048 + (n - 1) * 2097152, 2097152, LIN) for n in range(1, 10)]   # p1..p9, 1 GiB each
        d = FakeDisk("/dev/nvme0n1", 64, existing=ex)
        e = run_partition(d, {"mode": "free"})
        self.assertEqual((e.esp_dev, e.root_dev), ("/dev/nvme0n1p10", "/dev/nvme0n1p11"))
        self.assertNotIn("/dev/nvme0n1p9", d.formatted)
        self.assertEqual(d.formatted, ["/dev/nvme0n1p10", "/dev/nvme0n1p11"])

    def test_existing_esp_is_never_formatted(self):
        ex = [(n, 2048 + (n - 1) * 2097152, 2097152, ESP if n == 1 else LIN) for n in range(1, 11)]
        del ex[4]                                                                  # gap at 5
        d = FakeDisk("/dev/nvme0n1", 64, existing=ex)
        e = run_partition(d, {"mode": "free", "esp": "/dev/nvme0n1p1"})
        self.assertEqual(e.esp_dev, "/dev/nvme0n1p1")
        self.assertEqual(e.root_dev, "/dev/nvme0n1p5")       # the gap, found by GUID, not by name order
        self.assertEqual(d.formatted, ["/dev/nvme0n1p5"])

    def test_delayed_device_discovery(self):
        d = FakeDisk("/dev/sda", 64, existing=[(1, 2048, 1048576, ESP)], appear_after=5)
        e = run_partition(d, {"mode": "free"})
        self.assertGreater(d.settles, 5)
        self.assertEqual(d.formatted, ["/dev/sda2", "/dev/sda3"])
        self.assertEqual(e.root_dev, "/dev/sda3")

    def test_devices_never_appear(self):
        d = FakeDisk("/dev/sda", 64, existing=[(1, 2048, 1048576, ESP)], appear_after=10 ** 6)
        with self.assertRaises(engmod.InstallError):
            run_partition(d, {"mode": "free"})
        self.assertEqual(d.formatted, [])

    def test_erase_mode(self):
        d = FakeDisk("/dev/vda", 64, existing=[(7, 2048, 2097152, LIN)])
        e = run_partition(d, {"mode": "erase", "confirm_disk": "/dev/vda"})
        self.assertEqual((e.esp_dev, e.root_dev), ("/dev/vda2", "/dev/vda3"))
        self.assertEqual(d.formatted, ["/dev/vda2", "/dev/vda3"])


class Identification(unittest.TestCase):
    def table(self, *rows):
        return {n: {"node": f"/dev/vda{n}", "start": s, "size": z, "type": t, "uuid": u} for n, s, z, t, u in rows}

    def test_part_number(self):
        self.assertEqual(parts.part_number("/dev/vda", "/dev/vda10"), 10)
        self.assertEqual(parts.part_number("/dev/nvme0n1", "/dev/nvme0n1p9"), 9)
        self.assertEqual(parts.part_number("/dev/mmcblk0", "/dev/mmcblk0p12"), 12)
        with self.assertRaises(parts.PartitionError):
            parts.part_number("/dev/vda", "/dev/vdb1")

    def test_free_numbers_fill_gaps(self):
        self.assertEqual(parts.free_numbers({1: {}, 3: {}, 4: {}}, 2), [2, 5])

    def test_reused_guid_is_rejected(self):
        before = self.table((1, 2048, 100, LIN, "A"))
        after = self.table((1, 2048, 100, LIN, "A"), (2, 5000, 100, LIN, "A"))
        with self.assertRaises(parts.PartitionError):
            parts.new_partitions(before, after, {2: LIN}, (4096, 10 ** 6))

    def test_outside_region_is_rejected(self):
        after = self.table((2, 100, 100, LIN, "B"))
        with self.assertRaises(parts.PartitionError):
            parts.new_partitions({}, after, {2: LIN}, (4096, 10 ** 6))

    def test_changed_existing_partition_stops(self):
        before = self.table((1, 2048, 100, LIN, "A"))
        after = self.table((1, 2048, 50, LIN, "A"), (2, 5000, 100, LIN, "B"))
        with self.assertRaises(parts.PartitionError):
            parts.new_partitions(before, after, {2: LIN}, (4096, 10 ** 6))

    def test_wrong_number_for_guid_stops(self):
        probe = lambda: [{"path": "/dev/vda9", "partuuid": "B", "pkname": "/dev/vda"}]
        with self.assertRaises(parts.PartitionError):
            parts.wait_for_devices("/dev/vda", {10: "B"}, probe=probe, sleep=lambda s: None)

    def test_assert_target_protects_existing(self):
        with self.assertRaises(parts.PartitionError):
            parts.assert_target("/dev/vda1", "A", {"A"}, read_uuid=lambda d: "A")
        with self.assertRaises(parts.PartitionError):
            parts.assert_target("/dev/vda2", "B", {"A"}, read_uuid=lambda d: "A")
        parts.assert_target("/dev/vda2", "B", {"A"}, read_uuid=lambda d: "B")


if __name__ == "__main__":
    unittest.main()
