"""Bug 0.1.1-3: shared/copied folders must come from the right place on the old disk."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
from arclight_installer import disks
from arclight_installer import engine as engmod

UUID = "1111aaaa-2222-3333-4444-555566667777"
IDS = {"/dev/nvme0n1p2", f"uuid={UUID}", "label=archroot", "partuuid=abcd-02",
       f"/dev/disk/by-uuid/{UUID}"}


def resolve(fstab, sub="", fstype="btrfs", path="/home/arthur"):
    return disks.resolve_old_path(path, sub, fstab, IDS, fstype)


class Resolve(unittest.TestCase):
    def test_ordinary_ext4(self):
        fstab = f"UUID={UUID} / ext4 rw,relatime 0 1\n"
        self.assertEqual(resolve(fstab, "", "ext4"), "home/arthur")

    def test_no_fstab_at_all(self):
        self.assertEqual(resolve("", "", "xfs"), "home/arthur")

    def test_btrfs_root_subvolume_with_home_inside(self):
        fstab = f"# comment\nUUID={UUID} / btrfs rw,subvol=/@ 0 0\n"
        self.assertEqual(resolve(fstab, "@"), "@/home/arthur")

    def test_btrfs_separate_home_subvolume(self):
        for opt in ("subvol=@home", "subvol=/@home", "rw,noatime,compress=zstd,subvol=/@home,subvolid=257"):
            fstab = (f"UUID={UUID} / btrfs rw,subvol=/@ 0 0\n"
                     f"UUID={UUID} /home btrfs {opt} 0 0\n")
            self.assertEqual(resolve(fstab, "@"), "@home/arthur", opt)

    def test_home_subvolume_named_by_label_or_partuuid(self):
        for src in ("LABEL=archroot", "PARTUUID=ABCD-02", "/dev/nvme0n1p2", f'"UUID={UUID}"'):
            fstab = f"{src} / btrfs subvol=@ 0 0\n{src} /home btrfs subvol=@home 0 0\n"
            self.assertEqual(resolve(fstab, "@"), "@home/arthur", src)

    def test_per_user_subvolume(self):
        fstab = (f"UUID={UUID} / btrfs subvol=@ 0 0\nUUID={UUID} /home btrfs subvol=@home 0 0\n"
                 f"UUID={UUID} /home/arthur btrfs subvol=@arthur 0 0\n")
        self.assertEqual(resolve(fstab, "@"), "@arthur")
        self.assertEqual(resolve(fstab, "@", path="/home/arthur/Music"), "@arthur/Music")
        self.assertEqual(resolve(fstab, "@", path="/home/zoe"), "@home/zoe")

    def test_home_without_subvol_is_top_level(self):
        fstab = f"UUID={UUID} / btrfs subvol=@ 0 0\nUUID={UUID} /home btrfs subvolid=5 0 0\n"
        self.assertEqual(resolve(fstab, "@"), "arthur")

    def test_mount_points_that_only_share_a_prefix(self):
        fstab = f"UUID={UUID} / btrfs subvol=@ 0 0\nUUID=other /home2 ext4 defaults 0 0\n"
        self.assertEqual(resolve(fstab, "@"), "@/home/arthur")

    def test_refuses_home_on_other_partition(self):
        fstab = f"UUID={UUID} / ext4 rw 0 1\nUUID=9999-other /home ext4 rw 0 2\n"
        with self.assertRaisesRegex(disks.LayoutError, "different partition"):
            resolve(fstab, "", "ext4")

    def test_refuses_subvolid_only(self):
        fstab = f"UUID={UUID} / btrfs subvol=@ 0 0\nUUID={UUID} /home btrfs subvolid=258 0 0\n"
        with self.assertRaisesRegex(disks.LayoutError, "by id"):
            resolve(fstab, "@")

    def test_refuses_bind_and_network_homes(self):
        with self.assertRaises(disks.LayoutError):
            resolve(f"UUID={UUID} / ext4 rw 0 1\n/data/home /home none bind 0 0\n", "", "ext4")
        with self.assertRaises(disks.LayoutError):
            resolve(f"UUID={UUID} / ext4 rw 0 1\nnas:/export/home /home nfs defaults 0 0\n", "", "ext4")

    def test_mount_options_always_top_level_for_btrfs(self):
        self.assertEqual(disks.old_mount_opts("btrfs"), "ro,subvolid=5")
        self.assertEqual(disks.old_mount_opts("ext4"), "ro,noload")


class EngineSharePaths(unittest.TestCase):
    """migrate_home(): the copy source and the fstab line for shared folders use the translated path."""

    def run_migrate(self, layout_fstab, root_sub, home_rel):
        tmp = Path(tempfile.mkdtemp())
        top, old, target = tmp / "top", tmp / "old", tmp / "new"
        (top / root_sub / "etc").mkdir(parents=True)
        (top / root_sub / "etc/fstab").write_text(layout_fstab)
        (top / home_rel / "Games").mkdir(parents=True)
        old.symlink_to(top / root_sub if root_sub else top)
        (target / "etc").mkdir(parents=True)
        (target / "etc/fstab").write_text("")
        plan = {"source_home": "/home/arthur", "target_home": "/home/arthur", "free_bytes": 10 ** 12,
                "reserve_bytes": 0, "can_share": True,
                "items": [{"path": "Games", "bytes": 5, "action": "share", "reason": "big"}]}
        cfg = {"mode": "side-by-side", "partition": "/dev/nvme0n1p2", "old_root_subdir": root_sub,
               "user": {"name": "arthur"},
               "migrate": {"enabled": True, "old_user": {"name": "arthur"}, "from_home": "/home/arthur", "plan": plan}}
        with mock.patch.object(engmod, "LOG", tmp / "log"), mock.patch.object(engmod, "OLD", old), \
                mock.patch.object(engmod, "OLDTOP", top), mock.patch.object(engmod, "T", target), \
                mock.patch.object(engmod, "RUN", tmp), \
                mock.patch.object(engmod.disks, "device_ids", lambda p: IDS), \
                mock.patch.object(engmod.mcopy, "mirror_parents", lambda *a: 0), \
                mock.patch.object(engmod.os, "chown", lambda *a: None):
            e = engmod.Engine(cfg)
            e.fstype = "btrfs" if "btrfs" in layout_fstab else "ext4"
            e.home, e.uid, e.gid = target / "home/arthur", os.getuid(), os.getgid()
            e.chroot = lambda *a, **k: ""
            e.migrate_home()
        line = [l for l in (target / "etc/fstab").read_text().splitlines() if "/home/arthur/Games" in l][0]
        return line.split("\t")[0], e

    def test_ordinary_filesystem(self):
        src, _ = self.run_migrate(f"UUID={UUID} / ext4 rw 0 1\n", "", "home/arthur")
        self.assertEqual(src, "/run/arclight/host-rw/home/arthur/Games")

    def test_btrfs_root_subvolume(self):
        src, _ = self.run_migrate(f"UUID={UUID} / btrfs subvol=/@ 0 0\n", "@", "@/home/arthur")
        self.assertEqual(src, "/run/arclight/host-rw/@/home/arthur/Games")   # 0.1 wrote host-rw/home/arthur

    def test_btrfs_separate_home_subvolume(self):
        fstab = f"UUID={UUID} / btrfs subvol=/@ 0 0\nUUID={UUID} /home btrfs subvol=/@home 0 0\n"
        src, _ = self.run_migrate(fstab, "@", "@home/arthur")
        self.assertEqual(src, "/run/arclight/host-rw/@home/arthur/Games")

    def test_unsupported_layout_stops_with_reason(self):
        fstab = f"UUID={UUID} / ext4 rw 0 1\nUUID=elsewhere /home ext4 rw 0 2\n"
        with self.assertRaisesRegex(engmod.InstallError, "different partition.*Nothing was written"):
            self.run_migrate(fstab, "", "home/arthur")


if __name__ == "__main__":
    unittest.main()
