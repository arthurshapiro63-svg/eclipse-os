"""The quick-install engine. Runs the stages of an install plan with these rules:

  * The old system is only ever READ, through a read-only mount (`OLD`). Nothing under it is
    written, moved or deleted. (Side-by-side: the partition is also mounted read-write at `HOST`,
    but the only writes are inside the new deployment directory and the new EFI/arclight folder.)
  * Everything new is staged first. The single commit is the last step: one EFI BootOrder write
    (side-by-side / second disk), or the boot sector (whole disk, BIOS).
  * Before the commit the result is verified: the new system's files, the migrated home (content
    checksums) and, for side-by-side, a metadata fingerprint of the old filesystem taken before and
    after the install, which must be identical.
  * If anything fails before the commit, the staged files are removed again (only paths this run
    created, guarded by a marker file) and the boot order is untouched.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/usr/lib/arclight")
from arclight.migrate import plan as mplan, copy as mcopy   # noqa: E402
from arclight import identity, bootcfg                       # noqa: E402

from . import disks

RUN = Path("/run/arclight-install")
HOST = RUN / "host"        # side-by-side: the existing root partition, read-write (writes only to arclight/)
OLD = RUN / "old"          # the old system, READ-ONLY view (all migration reads come from here)
ESP = RUN / "esp"
T = Path("/mnt/arclight")  # the new system being built
AIROOTFS = Path(os.environ.get("ARCLIGHT_AIROOTFS", "/run/archiso/airootfs"))
LOG = Path("/var/log/arclight-install.log")
MARKER = ".arclight-incomplete"
GiB = 1024 ** 3
DEFAULT_GROUPS = ["wheel", "arclight", "video", "audio", "input", "storage", "uucp", "network"]


class InstallError(RuntimeError):
    pass


class Engine:
    def __init__(self, cfg, ui=None):
        self.c = cfg
        self.ui = ui
        self.created = []        # things to undo on failure: ("dir", path) / ("efi", bootnum) / ("mount", path)
        self.mounts = []
        self.committed = False
        self.report = {"stages": [], "warnings": []}
        self.efi_new = None
        self.saved_times = {}    # existing folders we add a child to: their timestamps are restored on rollback
        LOG.parent.mkdir(parents=True, exist_ok=True)
        self.logf = open(LOG, "a")

    # ------------------------------------------------------------ plumbing
    def log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.logf.write(line + "\n")
        self.logf.flush()
        if self.ui:
            self.ui.progress(msg)
        else:
            print(line, flush=True)

    def sh(self, cmd, check=True, input=None, timeout=None, env=None):
        if isinstance(cmd, str):
            cmd = ["bash", "-c", cmd]
        self.logf.write(f"$ {' '.join(shlex.quote(str(c)) for c in cmd)}\n")
        e = None
        if env:
            e = dict(os.environ)
            e.update(env)
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, input=input, timeout=timeout, env=e)
        if p.stdout:
            self.logf.write(p.stdout[-20000:])
        if p.stderr:
            self.logf.write(p.stderr[-20000:])
        self.logf.flush()
        if check and p.returncode != 0:
            raise InstallError(f"{cmd[0] if cmd[0] != 'bash' else cmd[2][:60]} failed ({p.returncode}): "
                               f"{(p.stderr or p.stdout).strip()[-800:]}")
        return p.stdout

    def chroot(self, cmd, check=True, input=None, timeout=None):
        if isinstance(cmd, str):
            cmd = ["bash", "-c", cmd]
        return self.sh(["arch-chroot", str(T)] + cmd, check=check, input=input, timeout=timeout)

    def mount(self, src, dst, opts=None, fstype=None, bind=False):
        Path(dst).mkdir(parents=True, exist_ok=True)
        cmd = ["mount"]
        if bind:
            cmd.append("--bind")
        if fstype:
            cmd += ["-t", fstype]
        if opts:
            cmd += ["-o", opts]
        self.sh(cmd + [str(src), str(dst)])
        self.mounts.append(str(dst))

    def umount_all(self):
        for m in reversed(self.mounts):
            subprocess.run(["umount", "-R", m], capture_output=True)
            if subprocess.run(["mountpoint", "-q", m]).returncode == 0:
                subprocess.run(["umount", "-l", m], capture_output=True)
        self.mounts = []

    def stage(self, name, fn):
        t0 = time.monotonic()
        self.log(f"▸ {name}")
        fn()
        dt = round(time.monotonic() - t0, 1)
        self.report["stages"].append({"stage": name, "seconds": dt})
        self.log(f"✓ {name} ({dt}s)")
        fail_at = os.environ.get("ARCLIGHT_TEST_FAIL_AT")  # failure injection for the safety tests
        if fail_at and fail_at == name:
            raise InstallError(f"injected failure after stage '{name}' (ARCLIGHT_TEST_FAIL_AT)")

    # ------------------------------------------------------------ run
    def run(self):
        mode = self.c["mode"]
        try:
            self.stage("preflight", self.preflight)
            if mode == "side-by-side":
                self.stage("mount existing system (old system read-only)", self.mount_side_by_side)
                self.stage("fingerprint old system", self.fingerprint_before)
                self.stage("check space (before writing anything)", self.check_space)
                self.stage("create deployment directory", self.create_deploy)
            elif mode in ("erase", "free"):
                self.stage("partition and format", self.partition)
                self.stage("mount new filesystems", self.mount_whole)
                if self.c.get("migrate", {}).get("source_partition"):
                    self.stage("mount old system read-only", self.mount_old_readonly)
            else:
                raise InstallError(f"unknown mode {mode}")
            self.stage("copy the Arclight system", self.unpack)
            self.stage("prepare chroot", self.prepare_chroot)
            self.stage("turn the live image into an installed system", self.unlive)
            self.stage("identity: OS name, machine name, time, language", self.configure_identity)
            self.stage("filesystems and boot image", self.configure_boot_files)
            self.stage("services and permissions", self.configure_services)
            self.stage("user account", self.create_user)
            if self.c.get("migrate", {}).get("enabled"):
                self.stage("migrate home (copy + verify)", self.migrate_home)
                self.stage("migrate system settings", self.migrate_etc)
            else:
                self.stage("prepare desktop", self.fresh_home)
            self.stage("your choices: the AI and the look", self.user_choices)
            self.stage("packages", self.packages)
            self.stage("boot loader (staged, not active yet)", self.bootloader)
            self.stage("verify new system", self.verify)
            if mode == "side-by-side":
                self.stage("verify old system untouched", self.fingerprint_after)
            self.stage("COMMIT: make the new system the default", self.commit)
            self.report["ok"] = True
        except Exception as e:
            self.report["ok"] = False
            self.report["error"] = str(e)
            self.log(f"✗ FAILED: {e}")
            self.logf.write(traceback.format_exc())
            if not self.committed:
                self.rollback()
            raise
        finally:
            self.umount_all()
            self.report["log"] = str(LOG)
            (RUN / "report.json").write_text(json.dumps(self.report, indent=2, default=str))
        return self.report

    # ------------------------------------------------------------ stages
    def preflight(self):
        c = self.c
        if os.geteuid() != 0:
            raise InstallError("the installer must run as root")
        if not AIROOTFS.is_dir() or not (AIROOTFS / "usr/bin/arclightd").exists():
            raise InstallError(f"live system image not found at {AIROOTFS}")
        if not identity.valid_name(c.get("os_name", identity.DEFAULT["name"])):
            raise InstallError("invalid OS name")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", c.get("hostname", "")):
            raise InstallError("invalid machine name (letters, digits, dashes)")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", c["user"]["name"]):
            raise InstallError("invalid user name")
        self.uefi = disks.uefi()
        c["firmware"] = "uefi" if self.uefi else "bios"
        if c["mode"] == "side-by-side":
            if not self.uefi:
                raise InstallError("side-by-side install needs UEFI (it adds its own boot entry instead of touching the old boot loader)")
            for k in ("partition", "esp"):
                if not Path(c[k]).exists():
                    raise InstallError(f"{k} {c[k]} does not exist")
            fs = self.sh(["blkid", "-o", "value", "-s", "TYPE", c["partition"]]).strip()
            if fs not in ("ext4", "btrfs", "xfs"):
                raise InstallError(f"side-by-side needs ext4, btrfs or xfs (found {fs})")
            self.fstype = fs
        else:
            if not Path(c["disk"]).exists():
                raise InstallError(f"disk {c['disk']} does not exist")
            if c["disk"] == disks.live_device():
                raise InstallError("that is the disk the installer is running from")
            if c["mode"] == "erase" and c.get("confirm_disk") != c["disk"]:
                raise InstallError("erasing a disk needs confirm_disk set to the disk's path")
            bundle = c.get("migrate", {}).get("bundle")
            if bundle and not (Path(bundle) / "BUNDLE.json").exists():
                raise InstallError(f"migration bundle {bundle} not found or not a bundle (checked BEFORE touching the disk)")
        need = ["rsync", "arch-chroot", "grub-install", "efibootmgr" if self.uefi else "true", "mkfs.btrfs", "sgdisk"]
        missing = [t for t in need if not shutil.which(t)]
        if missing:
            raise InstallError(f"missing tools: {missing}")
        if T.exists() and os.listdir(T):
            if subprocess.run(["mountpoint", "-q", str(T)]).returncode == 0:
                raise InstallError(f"{T} is in use; is another install running?")
        RUN.mkdir(parents=True, exist_ok=True)
        self.log(f"firmware {c['firmware']}, mode {c['mode']}, OS name '{c.get('os_name')}', host '{c['hostname']}'")

    # -- side-by-side
    def mount_side_by_side(self):
        c = self.c
        opts = "rw,noatime" if self.fstype != "btrfs" else "rw,noatime,subvolid=5"
        self.mount(c["partition"], HOST, opts=opts)
        sub = c.get("old_root_subdir", "")
        old_src = HOST / sub if sub else HOST
        # the read-only view: a bind mount remounted ro (all reads of the old system go through here)
        self.mount(old_src, OLD, bind=True)
        self.sh(["mount", "-o", "remount,bind,ro,noatime", str(OLD)])
        if (OLD / "etc/os-release").exists() or (OLD / "usr/lib/os-release").exists():
            self.log(f"existing system found at {c['partition']}{'/' + sub if sub else ''}")
        st = os.statvfs(HOST)
        self.host_free = st.f_bavail * st.f_frsize
        self.mount(c["esp"], ESP, opts="rw,noatime")
        self.esp_uuid = self.sh(["blkid", "-o", "value", "-s", "UUID", c["esp"]]).strip()
        self.root_uuid = self.sh(["blkid", "-o", "value", "-s", "UUID", c["partition"]]).strip()

    def fingerprint_before(self):
        if not self.c.get("fingerprint", True):
            self.log("fingerprint skipped (fingerprint=false)")
            return
        self.fp_before = mcopy.fingerprint(OLD, exclude=["arclight", "proc", "sys", "dev", "run", "tmp"])
        self.fp_esp_before = mcopy.fingerprint(ESP, exclude=["EFI/arclight"])
        (RUN / "fingerprint-before.json").write_text(json.dumps({"old": self.fp_before, "esp": self.fp_esp_before}))
        self.log(f"old system: {self.fp_before['entries']} entries recorded; ESP: {self.fp_esp_before['entries']}")

    def check_space(self):
        """Refuse BEFORE the first write if the new system + the migration cannot fit."""
        out = subprocess.run(["du", "-sxB1", str(AIROOTFS)], capture_output=True, text=True).stdout
        sysb = int(out.split()[0]) if out else 25 * GiB
        m = self.c.get("migrate", {})
        if m.get("enabled") and not m.get("bundle") and not isinstance(m.get("plan"), dict):
            src = OLD / m.get("from_home", f"home/{m['old_user']['name']}").lstrip("/")
            plan = mplan.build(src, f"/home/{self.c['user']['name']}", max(0, self.host_free - sysb), can_share=True,
                               progress=lambda r: None)
            for it in plan.items:
                if it.path in m.get("share", []):
                    it.action, it.reason = "share", "chosen"
                elif it.path in m.get("skip", []):
                    it.action, it.reason = "skip", "chosen"
            if not plan.fits():
                raise InstallError(f"not enough space: the new system needs {sysb / GiB:.0f} GiB and the migration plan "
                                   f"does not fit ({plan.summary()}). Share or skip more. Nothing was written.")
            m["plan"] = json.loads(plan.to_json())
            self.log(f"fits: system {sysb / GiB:.1f} GiB + {plan.summary()}")
        elif self.host_free < sysb + 5 * GiB:
            raise InstallError(f"not enough space: need {(sysb + 5 * GiB) / GiB:.0f} GiB, have {self.host_free / GiB:.0f} GiB. "
                               "Nothing was written.")

    def create_deploy(self):
        did = self.c.get("deploy_id") or time.strftime("%Y%m%d-%H%M%S")
        base = HOST / "arclight/deploy"
        d = base / did
        if d.exists():
            raise InstallError(f"deployment {d} already exists")
        need = 12 * GiB
        if self.host_free < need:
            raise InstallError(f"only {self.host_free // GiB} GiB free on {self.c['partition']}; need at least {need // GiB}")
        self._save_times(HOST)
        if not (HOST / "arclight").exists():
            (HOST / "arclight").mkdir()
            self.created.append(("dir", HOST / "arclight"))
        base.mkdir(parents=True, exist_ok=True)
        d.mkdir()
        (d / MARKER).write_text("this Arclight deployment is not finished; the installer removes it on failure\n")
        self.created.append(("dir", d))
        self.deploy_rel = f"/arclight/deploy/{did}"
        self.deploy = d
        self.mount(d, T, bind=True)

    # -- whole disk
    def partition(self):
        c = self.c
        disk = c["disk"]
        if c["mode"] == "erase":
            self.log(f"ERASING {disk}")
            self.sh(["wipefs", "-af", disk])
            self.sh(["sgdisk", "--zap-all", disk])
            self.sh(["sgdisk", "-n", "1:0:+1M", "-t", "1:ef02", "-c", "1:bios", "-n", "2:0:+1G", "-t", "2:ef00", "-c",
                     "2:EFI", "-n", "3:0:0", "-t", "3:8300", "-c", f"3:{identity.slug(c.get('os_name', 'arclight'))}", disk])
            nums = (2, 3)
        else:  # free space: append ESP (if none) + root into the largest free region
            regs = disks.free_regions(disk)
            if not regs:
                raise InstallError(f"no free space on {disk}")
            existing_esp = c.get("esp")
            if existing_esp:
                self.sh(["sgdisk", "-n", "0:0:0", "-t", "0:8300", disk])
                nums = (None, None)
            else:
                self.sh(["sgdisk", "-n", "0:0:+1G", "-t", "0:ef00", "-n", "0:0:0", "-t", "0:8300", disk])
            nums = (None, None)
        want = 3 if c["mode"] == "erase" else 1
        parts = []
        for _ in range(40):  # the kernel and udev need a moment before the new partitions appear
            self.sh(["partprobe", disk], check=False)
            self.sh(["udevadm", "settle"], check=False)
            devs = json.loads(self.sh(["lsblk", "-J", "-o", "NAME,PATH,TYPE", disk]))["blockdevices"]
            flat = []
            for d in devs:  # lsblk nests partitions under the disk, or lists them flat, depending on columns
                flat.append(d)
                flat += d.get("children") or []
            parts = sorted({p["path"] for p in flat if p.get("type") == "part"})
            if len(parts) >= want and all(Path(p).exists() for p in parts):
                break
            time.sleep(0.5)
        else:
            raise InstallError(f"the new partitions on {disk} did not appear")
        if c["mode"] == "erase":
            self.esp_dev, self.root_dev = parts[1], parts[2]
            self.sh(["mkfs.fat", "-F", "32", "-n", "EFI", self.esp_dev])
        else:
            self.root_dev = parts[-1]
            self.esp_dev = c.get("esp") or parts[-2]
            if not c.get("esp"):
                self.sh(["mkfs.fat", "-F", "32", "-n", "EFI", self.esp_dev])
        self.sh(["mkfs.btrfs", "-f", "-L", identity.slug(c.get("os_name", "arclight"))[:16], self.root_dev])
        self.root_uuid = self.sh(["blkid", "-o", "value", "-s", "UUID", self.root_dev]).strip()
        self.esp_uuid = self.sh(["blkid", "-o", "value", "-s", "UUID", self.esp_dev]).strip()

    def mount_whole(self):
        top = RUN / "btrfs-top"
        self.mount(self.root_dev, top)
        for sv in ("@", "@home", "@snapshots", "@log", "@pkg"):
            self.sh(["btrfs", "subvolume", "create", str(top / sv)])
        self.sh(["umount", str(top)])
        self.mounts.remove(str(top))
        o = "noatime,compress=zstd:1,space_cache=v2"
        self.mount(self.root_dev, T, opts=f"{o},subvol=@")
        for sv, mp in (("@home", "home"), ("@snapshots", ".snapshots"), ("@log", "var/log"), ("@pkg", "var/cache/pacman/pkg")):
            self.mount(self.root_dev, T / mp, opts=f"{o},subvol={sv}")
        self.mount(self.esp_dev, T / "efi", opts="umask=0077")
        self.host_free = os.statvfs(T).f_bavail * os.statvfs(T).f_frsize

    def mount_old_readonly(self):
        m = self.c["migrate"]
        self.mount(m["source_partition"], OLD, opts="ro,noload" if m.get("source_fstype", "ext4") == "ext4" else "ro")

    # -- common
    def unpack(self):
        excl = ["--exclude=/home/*", "--exclude=/proc/*", "--exclude=/sys/*", "--exclude=/dev/*", "--exclude=/run/*",
                "--exclude=/tmp/*", "--exclude=/mnt/*", "--exclude=/var/tmp/*"]
        if self.c["mode"] in ("erase", "free"):
            excl += ["--exclude=/var/log/*", "--exclude=/var/cache/pacman/pkg/*"]
        p = subprocess.Popen(["rsync", "-aHAX", "--numeric-ids", "--info=progress2", "--no-inc-recursive"] + excl +
                             [f"{AIROOTFS}/", f"{T}/"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        last = 0
        buf = ""
        while True:
            ch = p.stdout.read(1)
            if not ch:
                break
            if ch in "\r\n":
                m = re.search(r"(\d+)%", buf)
                if m and int(m.group(1)) >= last + 10:
                    last = int(m.group(1))
                    self.log(f"  system copy {last}%")
                buf = ""
            else:
                buf += ch
        err = p.stderr.read()
        if p.wait() != 0:
            raise InstallError(f"copying the system failed: {err[-600:]}")
        kern = T / "boot/vmlinuz-linux"
        if not kern.exists():
            base = re.search(r"\barchisobasedir=(\S+)", Path("/proc/cmdline").read_text())
            src = Path("/run/archiso/bootmnt") / (base.group(1) if base else "eclipse") / "boot/x86_64/vmlinuz-linux"
            if not src.exists():
                raise InstallError("kernel image not found")
            shutil.copy2(src, kern)

    def prepare_chroot(self):
        (T / "efi").mkdir(exist_ok=True)
        if self.c["mode"] == "side-by-side":
            self.mount(ESP, T / "efi", bind=True)
            (T / "host").mkdir(exist_ok=True)
            self.mount(OLD, T / "host", bind=True)
            self.sh(["mount", "-o", "remount,bind,ro", str(T / "host")])

    def unlive(self):
        rm = ["etc/mkinitcpio.conf.d/archiso.conf", "etc/systemd/system/getty@tty1.service.d/autologin.conf",
              "etc/systemd/journald.conf.d/volatile-storage.conf", "etc/systemd/logind.conf.d/do-not-suspend.conf",
              "etc/ssh/sshd_config.d/10-archiso.conf", "etc/systemd/system/arclight-live-setup.service",
              "etc/systemd/system/multi-user.target.wants/arclight-live-setup.service",
              "etc/systemd/system/etc-pacman.d-gnupg.mount", "etc/systemd/system/pacman-init.service",
              "etc/systemd/system/multi-user.target.wants/pacman-init.service",
              "usr/local/bin/arclight-live-setup", "usr/local/bin/arclight-live-session", "etc/machine-id"]
        for r in rm:
            p = T / r
            if p.exists() or p.is_symlink():
                p.unlink()
        for k in (T / "etc/ssh").glob("ssh_host_*"):
            k.unlink()
        self.chroot("systemd-machine-id-setup")
        self.chroot("pacman-key --init && pacman-key --populate archlinux", timeout=600)
        # live mirrorlist may be all-commented; keep the uncommented https mirrors
        ml = T / "etc/pacman.d/mirrorlist"
        if ml.exists() and not re.search(r"^Server", ml.read_text(), re.M):
            ml.write_text(re.sub(r"^#(Server = https:)", r"\1", ml.read_text(), flags=re.M))
        self.chroot("passwd -l root", check=False)

    def configure_identity(self):
        c = self.c
        idt = identity.load(str(T))
        idt["name"] = c.get("os_name") or identity.DEFAULT["name"]
        identity.apply(idt, str(T))
        (T / "etc/hostname").write_text(c["hostname"] + "\n")
        (T / "etc/hosts").write_text(f"127.0.0.1\tlocalhost\n::1\tlocalhost\n127.0.1.1\t{c['hostname']}.localdomain\t{c['hostname']}\n")
        tz = c.get("timezone") or "UTC"
        if not (T / "usr/share/zoneinfo" / tz).exists():
            self.report["warnings"].append(f"unknown timezone {tz}, using UTC")
            tz = "UTC"
        lt = T / "etc/localtime"
        if lt.exists() or lt.is_symlink():
            lt.unlink()
        lt.symlink_to(f"/usr/share/zoneinfo/{tz}")
        loc = c.get("locale") or "en_US.UTF-8"
        gen = T / "etc/locale.gen"
        text = gen.read_text() if gen.exists() else ""
        entry = f"{loc} UTF-8" if loc.endswith("UTF-8") else loc
        if not re.search(rf"^{re.escape(entry)}", text, re.M):
            text = re.sub(rf"^#\s*{re.escape(entry)}", entry, text, flags=re.M)
            if not re.search(rf"^{re.escape(entry)}", text, re.M):
                text += f"\n{entry}\n"
        if "en_US.UTF-8 UTF-8" not in text.split("\n"):
            text += "en_US.UTF-8 UTF-8\n"
        gen.write_text(text)
        self.chroot("locale-gen", timeout=600)
        (T / "etc/locale.conf").write_text(f"LANG={loc}\n")
        (T / "etc/vconsole.conf").write_text(f"KEYMAP={c.get('keymap') or 'us'}\nFONT=ter-v20b\n")

    def configure_boot_files(self):
        c = self.c
        fstab = ["# /etc/fstab: generated by the Arclight installer"]
        if c["mode"] == "side-by-side":
            fs = self.fstype
            # "/" is mounted by the initramfs from root= + rootflags=X-mount.subdir (no fstab line on purpose)
            extra = ",subvolid=5" if fs == "btrfs" else ""
            # The same filesystem is already mounted read-write as "/" (a subdirectory of it), and Linux
            # cannot mount it again read-only. So: mount it once, hidden, and show it at /host through a
            # read-only bind. nofail: the old system can never block this one from booting.
            fstab.append(f"UUID={self.root_uuid}\t/run/arclight/host-rw\t{fs}\tnoatime,nofail{extra}\t0 0")
            fstab.append("/run/arclight/host-rw\t/host\tnone\tbind,ro,nofail,x-systemd.requires-mounts-for=/run/arclight/host-rw\t0 0")
            fstab.append(f"UUID={self.esp_uuid}\t/efi\tvfat\tumask=0077,noatime\t0 2")
        else:
            o = "noatime,compress=zstd:1,space_cache=v2"
            fstab.append(f"UUID={self.root_uuid}\t/\tbtrfs\t{o},subvol=@\t0 0")
            for sv, mp in (("@home", "/home"), ("@snapshots", "/.snapshots"), ("@log", "/var/log"), ("@pkg", "/var/cache/pacman/pkg")):
                fstab.append(f"UUID={self.root_uuid}\t{mp}\tbtrfs\t{o},subvol={sv}\t0 0")
            fstab.append(f"UUID={self.esp_uuid}\t/efi\tvfat\tumask=0077,noatime\t0 2")
        self.fstab = fstab
        (T / "etc/fstab").write_text("\n".join(fstab) + "\n")
        (T / "etc/mkinitcpio.conf.d").mkdir(parents=True, exist_ok=True)
        (T / "etc/mkinitcpio.conf.d/arclight.conf").write_text(
            "# Arclight: systemd-based initramfs (needed for X-mount.subdir roots of side-by-side installs)\n"
            "HOOKS=(base systemd plymouth autodetect microcode modconf kms keyboard sd-vconsole block filesystems fsck)\n"
            "COMPRESSION=\"zstd\"\n")
        # boot splash: the Arclight theme (art/boot/plymouth); shown with the "splash" kernel parameter
        (T / "etc/plymouth").mkdir(parents=True, exist_ok=True)
        (T / "etc/plymouth/plymouthd.conf").write_text("[Daemon]\nTheme=eclipse\nShowDelay=0\nDeviceTimeout=8\n")
        self.chroot("mkinitcpio -P", timeout=1200)
        for f in ("boot/vmlinuz-linux", "boot/initramfs-linux.img"):
            if not (T / f).exists():
                raise InstallError(f"{f} missing after mkinitcpio")

    def configure_services(self):
        enable = ["NetworkManager", "bluetooth", "arclightd", "arclight-pkgsync", "arclight-pacman-sync", "power-profiles-daemon", "systemd-timesyncd", "fstrim.timer",
                  "sshd" if self.c.get("sshd", True) else None]
        for s in filter(None, enable):
            self.chroot(f"systemctl enable {s}", check=False)
        self.chroot("systemctl --global enable arclight-watch.service", check=False)
        # the services Arthur has on (from the old system if it is here, else from the record on the USB)
        wanted = set()
        for wants in OLD.glob("etc/systemd/system/*.target.wants/*") if OLD.is_dir() else []:
            wanted.add(wants.name)
        rec = Path("/usr/share/arclight/manifest/services-system-enabled.txt")
        if not wanted and rec.exists():
            wanted = set(rec.read_text().split())
        skip = {"getty@.service", "remote-fs.target", "systemd-userdbd.socket"}
        on = []
        for unit in sorted(wanted - skip):
            if self.chroot(f"systemctl cat {shlex.quote(unit)} >/dev/null 2>&1 && systemctl enable {shlex.quote(unit)} >/dev/null 2>&1 && echo y",
                           check=False).strip() == "y":
                on.append(unit)
        self.report["services_enabled_from_old_setup"] = on
        if on:
            self.log(f"turned on {len(on)} of your services: {', '.join(on)}")
        # a locked root must not lock Arthur out of the rescue shell
        for unit in ("emergency", "rescue"):
            d = T / f"etc/systemd/system/{unit}.service.d"
            d.mkdir(parents=True, exist_ok=True)
            (d / "arclight.conf").write_text("[Service]\nEnvironment=SYSTEMD_SULOGIN_FORCE=1\n")
        self.chroot("systemd-sysusers", check=False)
        if not self.c.get("sudo_nopasswd", True):
            p = T / "etc/sudoers.d/10-arclight"
            if p.exists():
                p.write_text("# NOPASSWD disabled at install time\n%arclight ALL=(ALL:ALL) ALL\n")
        else:
            (T / "etc/sudoers.d").mkdir(exist_ok=True)
            w = T / "etc/sudoers.d/00-wheel"
            w.write_text("%wheel ALL=(ALL:ALL) ALL\n")
            w.chmod(0o440)

    def create_user(self):
        u = self.c["user"]
        old = self.c.get("migrate", {}).get("old_user") or {}
        uid = old.get("uid") or 1000
        gid = old.get("gid") or uid
        self.chroot(f"userdel -r {shlex.quote(u['name'])} 2>/dev/null; groupadd -g {gid} {shlex.quote(u['name'])} 2>/dev/null || true", check=False)
        groups = [g for g in DEFAULT_GROUPS if self.chroot(f"getent group {g}", check=False).strip()]
        self.chroot(["useradd", "-M", "-u", str(uid), "-g", str(gid), "-G", ",".join(groups), "-s", "/bin/bash",
                     "-c", u.get("full_name") or u["name"].title(), u["name"]])
        if u.get("password_hash"):
            self.chroot(["usermod", "-p", u["password_hash"], u["name"]])
        elif u.get("password"):
            self.chroot(["chpasswd"], input=f"{u['name']}:{u['password']}\n")
        else:
            raise InstallError("no password or password hash for the user")
        home = T / "home" / u["name"]
        self.home = home
        self.uid, self.gid = uid, gid
        if u.get("autologin", True):
            d = T / "etc/systemd/system/getty@tty1.service.d"
            d.mkdir(parents=True, exist_ok=True)
            (d / "autologin.conf").write_text(
                "[Service]\nExecStart=\nExecStart=-/sbin/agetty -o '-p -f -- \\\\u' --noreset --noclear "
                f"--autologin {u['name']} - ${{TERM}}\n")

    def fresh_home(self):
        home = self.home
        if home.exists():
            shutil.rmtree(home)
        skel = T / "usr/share/arclight/skel"
        shutil.copytree(skel if skel.is_dir() else T / "etc/skel", home, symlinks=True)
        self.sh(["chown", "-R", f"{self.uid}:{self.gid}", str(home)])
        self.chroot(["runuser", "-u", self.c["user"]["name"], "--", "arclight-firstrun", "--home", f"/home/{self.c['user']['name']}",
                     "--offline", "--force"], check=False)

    def user_choices(self):
        """The two choices from the installer: use the AI features (ai.enabled) and the Eclipse look
        (appearance.eclipse_look; off = plain graphite, applied at the first login). Merged into the user's
        own settings file; folders made here belong to the user."""
        ai = bool(self.c.get("ai", True))
        look = bool(self.c.get("eclipse_look", True))
        cfg = self.home / ".config/arclight"
        for d in (self.home / ".config", cfg):
            if not d.exists():
                d.mkdir(parents=True)
                os.chown(d, self.uid, self.gid)
        f = cfg / "settings.json"
        try:
            data = json.loads(f.read_text()) if f.exists() else {}
        except (OSError, ValueError):
            data = {}
        data["ai.enabled"] = ai
        data["appearance.eclipse_look"] = look
        if not look:
            data["look.apply_at_login"] = True
        f.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.chown(f, self.uid, self.gid)
        self.log(f"AI features: {'on' if ai else 'off'} · Eclipse look: {'on' if look else 'off (plain)'}")

    def migrate_home(self):
        m = self.c["migrate"]
        src = OLD / m.get("from_home", f"home/{m['old_user']['name']}").lstrip("/")
        if m.get("bundle"):
            self.home.mkdir(parents=True, exist_ok=True)
            mcopy.import_bundle(m["bundle"], self.home)
            self.log("bundle imported and every file checksum verified")
        else:
            if not src.is_dir():
                raise InstallError(f"old home {src} not found")
            plan = mplan.Plan.from_json(json.dumps(m["plan"])) if isinstance(m.get("plan"), dict) else None
            if plan is None:
                # measured NOW: the new system is already unpacked, so its ~25 GB are accounted for
                fsroot = HOST if self.c["mode"] == "side-by-side" else T
                free = os.statvfs(fsroot).f_bavail * os.statvfs(fsroot).f_frsize
                plan = mplan.build(src, self.home, free, can_share=self.c["mode"] == "side-by-side",
                                   progress=lambda r: None)
            for it in plan.items:  # explicit choices from the config win over the automatic plan
                if it.path in m.get("share", []) and self.c["mode"] == "side-by-side":
                    it.action, it.reason = "share", "chosen"
                elif it.path in m.get("skip", []):
                    it.action, it.reason = "skip", "chosen"
            if not plan.fits():
                raise InstallError(f"the migration plan does not fit: {plan.summary()}")
            self.log(f"plan: {plan.summary()}")
            (RUN / "migration-plan.json").write_text(plan.to_json())
            self.home.mkdir(parents=True, exist_ok=True)
            st = src.stat()
            os.chown(self.home, self.uid, self.gid)
            os.chmod(self.home, st.st_mode & 0o7777)
            copies = [i for i in plan.items if i.action == "copy"]
            for n, it in enumerate(copies, 1):
                self.log(f"  copy [{n}/{len(copies)}] {it.path} ({it.bytes / GiB:.2f} GiB)")
                mcopy.copy_item(src, self.home, it.path)
            self.log("verifying every copied file (content checksums)")
            bad = {}
            for it in copies:
                d = mcopy.verify_item(src, self.home, it.path)
                if d:
                    bad[it.path] = d[:5]
            if bad:
                raise InstallError(f"migration verification failed for {len(bad)} items: {json.dumps(bad)[:800]}")
            self.log(f"verified {len(copies)} items: identical")
            shares = [i for i in plan.items if i.action == "share"]
            if shares:
                old_home_rel = str(src.relative_to(OLD))
                lines = ["", "# Shared with the previous system (not copied, nothing moved): Arclight migration"]
                for it in shares:
                    target = Path("/home") / self.c["user"]["name"] / it.path
                    (T / str(target).lstrip("/")).mkdir(parents=True, exist_ok=True)
                    # /host is read-only for safety; shared data needs its own read-write bind of the old path
                    lines.append(f"/run/arclight/host-rw/{old_home_rel}/{it.path}\t{target}\tnone\tbind,nofail,"
                                 f"x-systemd.requires-mounts-for=/run/arclight/host-rw\t0 0")
                with open(T / "etc/fstab", "a") as f:
                    f.write("\n".join(lines) + "\n")
                self.log(f"{len(shares)} items shared in place: {', '.join(i.path for i in shares)}")
            # folders the installer created on the way (~/.local for ~/.local/share/Steam, ...) belong to the user
            fixed = sum(mcopy.mirror_parents(src, self.home, it.path, self.uid, self.gid)
                        for it in plan.items if it.action in ("copy", "share"))
            if fixed:
                self.log(f"{fixed} parent folders given back to their owner")
            self.report["migration"] = {"summary": plan.summary(), "copied": len(copies), "shared": [i.path for i in shares],
                                        "skipped": [i.path for i in plan.items if i.action == "skip"]}
        # Arclight layer on the migrated (staged) copy: marked blocks only, theme rendered in a sandbox
        self.chroot(["runuser", "-u", self.c["user"]["name"], "--", "arclight-firstrun", "--migrated", "--home",
                     f"/home/{self.c['user']['name']}"], check=False)

    def migrate_etc(self):
        """Carry machine settings over from the old system (read-only source)."""
        moved = []
        for rel in ("etc/NetworkManager/system-connections", "var/lib/bluetooth"):
            s = OLD / rel
            if s.is_dir():
                d = T / rel
                d.mkdir(parents=True, exist_ok=True)
                self.sh(["rsync", "-aHAX", "--numeric-ids", f"{s}/", f"{d}/"])
                moved.append(rel)
        keys = list((OLD / "etc/ssh").glob("ssh_host_*"))
        for k in keys:
            shutil.copy2(k, T / "etc/ssh" / k.name)
        if keys:
            moved.append("ssh host keys")
        self.report["migrated_etc"] = moved
        self.log(f"carried over: {', '.join(moved) or 'nothing'}")

    def packages(self):
        """Arthur's explicit package list from the old system (repo packages online now; AUR + offline later)."""
        want = list(self.c.get("packages", {}).get("extra", []))
        if self.c.get("packages", {}).get("from_old_system") and (OLD / "var/lib/pacman/local").is_dir():
            out = self.sh(["pacman", "--root", str(OLD), "--dbpath", str(OLD / "var/lib/pacman"), "-Qqe"], check=False)
            want += out.split()
        if not want:
            return
        have = set(self.chroot("pacman -Qq", check=False).split())
        missing = sorted(set(want) - have - {"yay-bin-debug"})
        pending = T / "var/lib/arclight/pending-packages.txt"
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text("\n".join(missing) + "\n")
        self.log(f"{len(missing)} packages from the old system are not on the install medium")
        online = subprocess.run(["bash", "-c", "getent hosts archlinux.org >/dev/null && curl -fsI https://geo.mirror.pkgbuild.com >/dev/null"],
                                capture_output=True).returncode == 0
        if not missing or not online or not self.c.get("packages", {}).get("online", True):
            if missing:
                self.log("offline: they will be installed at first boot (arclight-pkgsync)")
            return
        repo = [p for p in missing if self.chroot(f"pacman -Si {shlex.quote(p)} >/dev/null 2>&1 && echo y", check=False).strip() == "y"]
        if repo:
            self.chroot("pacman -Sy --noconfirm", check=False, timeout=600)
            r = subprocess.run(["arch-chroot", str(T), "pacman", "-S", "--noconfirm", "--needed"] + repo,
                               capture_output=True, text=True, timeout=7200)
            self.logf.write(r.stdout[-20000:] + r.stderr[-20000:])
            if r.returncode != 0:
                self.report["warnings"].append("some repo packages failed to install; first boot retries them")
        left = sorted(set(missing) - set(self.chroot("pacman -Qq", check=False).split()))
        pending.write_text("\n".join(left) + ("\n" if left else ""))
        self.log(f"installed {len(missing) - len(left)} packages; {len(left)} left for first boot (AUR)")

    def bootloader(self):
        c = self.c
        theme_src = Path("/usr/share/arclight/grub/theme")
        vt = Path("/usr/share/arclight/console/vt-colors.conf")
        params = "quiet loglevel=3 splash rd.udev.log_level=3 vt.global_cursor_default=0 " + \
            (" ".join(vt.read_text().split()) if vt.exists() else "")
        if self.uefi:
            efi_dir = "/efi"
            boot_dir = "/efi/EFI/arclight"
            if (ESP / "EFI/arclight").exists() and c["mode"] == "side-by-side":
                raise InstallError("an EFI/arclight folder already exists on the ESP (another Arclight install?)")
            if c["mode"] == "side-by-side":
                self._save_times(ESP / "EFI")
                self._save_times(ESP)
            self.chroot(["grub-install", "--target=x86_64-efi", f"--efi-directory={efi_dir}", "--bootloader-id=arclight",
                         f"--boot-directory={boot_dir}", "--no-nvram"])
            if c["mode"] == "side-by-side":
                self.created.append(("dir", ESP / "EFI/arclight"))
            else:
                # whole disk: also the removable-media path so the disk boots even with empty NVRAM
                self.chroot(["grub-install", "--target=x86_64-efi", f"--efi-directory={efi_dir}", "--bootloader-id=arclight",
                             f"--boot-directory={boot_dir}", "--no-nvram", "--removable"])
            grub_dir = f"{boot_dir}/grub"
        else:
            grub_dir = "/boot/grub"
        if theme_src.exists():
            td = T / grub_dir.lstrip("/") / "themes/arclight"
            if td.exists():
                shutil.rmtree(td)
            shutil.copytree(theme_src, td)
        chain = []
        if c["mode"] == "side-by-side":
            for ld in disks.existing_loaders(ESP):
                label = c.get("old_os_name") or "Previous system"
                chain.append({"label": f"{label} ({ld['vendor']})", "esp_uuid": self.esp_uuid, "path": ld["path"]})
        conf = {"mode": "deploy" if c["mode"] == "side-by-side" else "btrfs", "root_uuid": self.root_uuid,
                "fstype": getattr(self, "fstype", "btrfs"),
                "deploy": getattr(self, "deploy_rel", None), "subvol": "@", "esp_uuid": self.esp_uuid,
                "grub_cfg": f"{grub_dir}/grub.cfg", "kernel_params": params.strip(), "firmware": c["firmware"],
                "chain": chain, "timeout": 4}
        (T / "etc/arclight").mkdir(parents=True, exist_ok=True)
        (T / "etc/arclight/boot.json").write_text(json.dumps(conf, indent=2))
        self.intro_marker()
        bootcfg.write(conf, str(T))
        if not self.uefi:
            self.bios_disk = c["disk"]
        if self.uefi:
            dev = c["esp"] if c["mode"] == "side-by-side" else self.esp_dev
            pk = self.sh(["lsblk", "-no", "PKNAME", dev]).strip()
            partn = self.sh(["lsblk", "-no", "PARTN", dev]).strip()
            before = set(disks.efi_entries()["entries"])
            label = c.get("os_name") or identity.DEFAULT["name"]
            # create-only (-C): the entry exists but is NOT in BootOrder yet. Nothing changes until commit.
            self.sh(["efibootmgr", "-C", "-d", f"/dev/{pk}", "-p", partn, "-L", label, "-l", "\\EFI\\arclight\\grubx64.efi"])
            new = sorted(set(disks.efi_entries()["entries"]) - before)
            if not new:
                raise InstallError("could not create the EFI boot entry")
            self.efi_new = new[0]
            self.created.append(("efi", self.efi_new))
            self.log(f"EFI entry Boot{self.efi_new} '{label}' created (not active yet)")

    def intro_marker(self):
        """First login of this install plays the Eclipse intro once (desktop.py _intro_once consumes the marker).
        Best effort: a failure here changes nothing else about the install."""
        try:
            d = self.home / ".local/state/arclight"
            for p in (d.parent.parent, d.parent, d):      # ~/.local, ~/.local/state, ~/.local/state/arclight
                if not p.exists():
                    p.mkdir()
                    os.chown(p, self.uid, self.gid)
            m = d / "intro-pending"
            m.write_text("installed " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            os.chown(m, self.uid, self.gid)
            (d / "intro-done").unlink(missing_ok=True)
        except (OSError, AttributeError) as e:
            self.log(f"intro marker not written ({e}); the intro just won't play by itself")

    def verify(self):
        problems = []
        for f in ("etc/os-release", "etc/hostname", "etc/fstab", "boot/vmlinuz-linux", "boot/initramfs-linux.img",
                  "usr/bin/arclightd", "etc/arclight/boot.json"):
            if not (T / f).exists():
                problems.append(f"missing {f}")
        u = self.c["user"]["name"]
        if not self.chroot(f"id -u {shlex.quote(u)}", check=False).strip():
            problems.append("user missing")
        if not (self.home / ".config/hypr/hyprland.lua").exists():
            problems.append("home has no Hyprland config")
        if self.chroot("systemctl is-enabled arclightd", check=False).strip() != "enabled":
            problems.append("arclightd not enabled")
        # verify fstab from INSIDE the new system (its mount points and devices), not from the live USB
        r = subprocess.run(["arch-chroot", str(T), "findmnt", "--verify", "--tab-file", "/etc/fstab"], capture_output=True, text=True)
        # "unreachable target" only means the folder does not exist yet; systemd creates mount points
        errs = [l for l in (r.stdout + r.stderr).splitlines() if "[E]" in l and "unreachable on boot required target" not in l]
        if errs:
            problems.append("fstab: " + "; ".join(errs)[:400])
        conf = json.loads((T / "etc/arclight/boot.json").read_text())
        cfg = T / conf["grub_cfg"].lstrip("/") if not conf["grub_cfg"].startswith("/efi") else T / conf["grub_cfg"].lstrip("/")
        if not cfg.exists():
            problems.append("grub.cfg missing")
        if self.uefi and not (T / "efi/EFI/arclight/grubx64.efi").exists():
            problems.append("grubx64.efi missing")
        if problems:
            raise InstallError("verification failed: " + "; ".join(problems))
        self.chroot("pacman -Dk >/dev/null", check=False)

    def fingerprint_after(self):
        if not hasattr(self, "fp_before"):
            return
        after = mcopy.fingerprint(OLD, exclude=["arclight", "proc", "sys", "dev", "run", "tmp"])
        esp_after = mcopy.fingerprint(ESP, exclude=["EFI/arclight"])
        ok = after["sha256"] == self.fp_before["sha256"] and esp_after["sha256"] == self.fp_esp_before["sha256"]
        self.report["old_system_untouched"] = ok
        self.report["old_system_entries"] = after["entries"]
        if not ok:
            where = mcopy.fingerprint_diff(self.fp_before, after) + ["ESP:" + d for d in mcopy.fingerprint_diff(self.fp_esp_before, esp_after)]
            raise InstallError(f"the old system's files changed during the install (in: {', '.join(where) or '?'}); refusing to commit")
        self.log(f"old system verified unchanged ({after['entries']} entries, ESP {esp_after['entries']})")

    def commit(self):
        """The one atomic step: boot order (UEFI) or nothing extra (BIOS GRUB is written here, last)."""
        if self.uefi:
            order = disks.efi_entries()["order"]
            new_order = [self.efi_new] + [o for o in order if o != self.efi_new]
            self.sh(["efibootmgr", "-o", ",".join(new_order)])
            self.committed = True
            self.log(f"BootOrder is now {','.join(new_order)} (was {','.join(order)})")
            self.report["boot_order_before"] = order
            self.report["boot_order_after"] = new_order
        else:
            self.chroot(["grub-install", "--target=i386-pc", "--boot-directory=/boot", self.bios_disk])
            self.committed = True
        if self.c["mode"] == "side-by-side":
            (self.deploy / MARKER).unlink(missing_ok=True)   # finished deployment: never auto-removed again
        self.report["boot_entry"] = self.efi_new

    # ------------------------------------------------------------ undo
    def rollback(self):
        self.log("rolling back: removing only what this install created")
        self.umount_all()
        for kind, what in reversed(self.created):
            try:
                if kind == "efi":
                    subprocess.run(["efibootmgr", "-b", what, "-B"], capture_output=True)
                    self.log(f"  removed EFI entry Boot{what}")
                elif kind == "dir":
                    p = Path(what)
                    # re-mount what we need to delete: these paths live on HOST/ESP
                    self._remount_for_cleanup(p)
                    target = self._cleanup_path(p)
                    if target and target.name == "arclight" and target.parent == HOST:
                        dep = target / "deploy"
                        if dep.is_dir() and not any(dep.iterdir()):
                            dep.rmdir()
                    if target and target.exists():
                        safe = (target.name == "arclight" and target.parent == HOST and not any(target.iterdir())) or \
                               (target.parent.name == "deploy" and (target / MARKER).exists()) or \
                               (target.name == "arclight" and target.parent.name == "EFI")
                        if safe:
                            shutil.rmtree(target) if target.is_dir() else target.unlink()
                            self.log(f"  removed {target}")
                        else:
                            self.log(f"  left {target} in place (not provably ours)")
            except Exception as e:
                self.log(f"  cleanup of {what} failed: {e}")
        self._restore_times()
        self.umount_all()

    def _save_times(self, path):
        try:
            st = os.stat(path)
            self.saved_times.setdefault(str(path), (st.st_atime_ns, st.st_mtime_ns))
        except OSError:
            pass

    def _restore_times(self):
        for path, (at, mt) in self.saved_times.items():
            try:
                self._remount_for_cleanup(Path(path))
                os.utime(path, ns=(at, mt))
                self.log(f"  restored the timestamps of {path}")
            except OSError as e:
                self.log(f"  could not restore timestamps of {path}: {e}")

    def _remount_for_cleanup(self, p):
        try:
            if str(p).startswith(str(HOST)) and subprocess.run(["mountpoint", "-q", str(HOST)]).returncode != 0:
                self.mount(self.c["partition"], HOST, opts="rw,noatime" if getattr(self, "fstype", "ext4") != "btrfs" else "rw,subvolid=5")
            if str(p).startswith(str(ESP)) and subprocess.run(["mountpoint", "-q", str(ESP)]).returncode != 0:
                self.mount(self.c["esp"], ESP, opts="rw,noatime")
        except Exception:
            pass

    def _cleanup_path(self, p):
        return Path(p)
