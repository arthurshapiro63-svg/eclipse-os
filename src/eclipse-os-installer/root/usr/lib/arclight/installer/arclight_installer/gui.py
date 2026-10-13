"""arclight-installer-gui: the graphical Quick installer for Eclipse OS (codename Arclight).

It asks the same questions as the text Quick install (main.quick) and runs the same engine the same way:
it writes the same config and starts `arclight-install --config FILE` as root, then shows its stage lines
as a golden progress bar. Nothing is written to any disk before the Install button.

  arclight-installer-gui            the installer (live USB)
  arclight-installer-gui --demo     fake disks, fake plan and a fake engine (no root, nothing touched)

Internal (run as root by the GUI through `sudo -n`, the live session's passwordless rule):
  --probe scan                      disks.scan() + main.targets() as JSON (read-only)
  --probe plan --partition P ...    the migration plan, measured exactly like main.quick (read-only mount)
  --probe shadow --partition P ...  whether the old password can be kept (prints yes/no, never the hash)
  --fake-engine CFG                 demo: print realistic engine output for CFG
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import disks

GiB = 1024 ** 3
MiB = 1024 ** 2
APP_ID = "dev.arclight.Installer"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LOG_PATH = "/var/log/arclight-install.log"
RUN = Path("/run/arclight-install")


def gib(n):
    if n < 0.05 * GiB:
        return "0 GiB"        # not "0.0 GiB"
    return f"{n / GiB:.0f} GiB" if n >= 10 * GiB else f"{n / GiB:.1f} GiB"


def launcher():
    """This program's own launcher (the GUI re-runs it as root for the probes)."""
    a = os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if os.path.basename(a) == "arclight-installer-gui":
        return a
    for c in (REPO / "src/bin/arclight-installer-gui", Path("/usr/bin/arclight-installer-gui")):
        if c.exists():
            return str(c)
    return shutil.which("arclight-installer-gui") or "arclight-installer-gui"


def install_cmd():
    for c in (shutil.which("arclight-install"), REPO / "installer/bin/arclight-install"):
        if c and Path(c).exists():
            return str(c)
    return "/usr/bin/arclight-install"


def as_root(args):
    return ([] if os.geteuid() == 0 else ["sudo", "-n"]) + args


# =============================================================== root-side probes (no GTK)

def probe_main(argv):
    ap = argparse.ArgumentParser(prog="arclight-installer-gui --probe")
    ap.add_argument("what", choices=["scan", "plan", "shadow"])
    ap.add_argument("--partition")
    ap.add_argument("--fstype", default="ext4")
    ap.add_argument("--subdir", default="")
    ap.add_argument("--home")
    ap.add_argument("--user")
    ap.add_argument("--free", type=int, default=0)
    a = ap.parse_args(argv)
    from . import main as M
    if a.what == "scan":
        scan = disks.scan()
        opts = M.targets(scan)
        print(json.dumps({"uefi": disks.uefi(), "disks": scan,
                          "targets": [{"kind": k, "t": t, "label": l} for k, t, l in opts]}))
        return 0
    if a.what == "shadow":
        h = M.old_shadow_hash(a.partition, a.user, a.subdir)
        print(json.dumps({"found": bool(h)}))
        return 0
    # plan: exactly what main.quick does (read-only mount, minus the live system's size, can_share=True)
    from arclight.migrate import plan as mplan
    mnt = M.RUN / "plan-probe"
    mnt.mkdir(parents=True, exist_ok=True)
    subprocess.run(["mount", "-o", "ro,noload" if a.fstype == "ext4" else "ro", a.partition, str(mnt)], check=True)
    try:
        src = mnt / a.subdir / a.home.lstrip("/")
        sysb = int(subprocess.run(["du", "-sxB1", "/run/archiso/airootfs"], capture_output=True, text=True).stdout.split()[0] or 0)
        plan = mplan.build(src, f"/home/{a.user}", max(0, a.free - sysb), can_share=True,
                           progress=lambda rel: print(rel, file=sys.stderr, flush=True))
    finally:
        subprocess.run(["umount", str(mnt)])
    print(json.dumps({"plan": json.loads(plan.to_json()), "system_bytes": sysb}))
    return 0


# =============================================================== demo data + fake engine

def demo_scan():
    arch = {"name": "Arch Linux", "id": "arch", "root_subdir": "", "free": 395 * GiB, "size": 930 * GiB, "used": 432 * GiB,
            "homes": ["arthur"], "users": [{"name": "arthur", "uid": 1000, "gid": 1000, "gecos": "Arthur",
                                            "home": "/home/arthur", "shell": "/bin/bash"}],
            "hostname": "archbox", "timezone": "America/New_York", "locale": "en_US.UTF-8", "keymap": "us",
            "has_arclight": False}
    return [
        {"path": "/dev/nvme0n1", "model": "Samsung SSD 990 PRO 1TB", "size": 931 * GiB, "pttype": "gpt", "removable": False,
         "parts": [{"path": "/dev/nvme0n1p1", "size": 1 * GiB, "fstype": "vfat", "esp": True,
                    "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"},
                   {"path": "/dev/nvme0n1p2", "size": 930 * GiB, "fstype": "ext4", "esp": False, "os": arch,
                    "parttype": "0fc63daf-8483-4772-8e79-3d69d8477de4"}],
         "free_regions": [], "empty": False},
        {"path": "/dev/sda", "model": "WD Blue 2TB", "size": 1863 * GiB, "pttype": "gpt", "removable": False,
         "parts": [{"path": "/dev/sda1", "size": 1500 * GiB, "fstype": "ntfs", "esp": False, "os": None,
                    "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"}],
         "free_regions": [(3145728000, 3907029134, 363 * GiB)], "empty": False},
    ]


DEMO_HOME = [  # (path, GiB) shaped like Arthur's real home (docs/MIGRATION.md)
    (".local/share/Steam", 172), ("vms", 65), ("Projects/apex-learners", 41), ("Unity", 29), (".cache", 22),
    ("Projects/primal-rpg", 19), (".local/share/arch-ai", 18), ("Projects/arclight", 16), (".ollama", 14),
    ("Projects/apex-velocity", 12), ("blender", 11), (".local/share/PrismLauncher", 9.5), ("Videos", 8.4),
    ("Projects/hearthfall", 7.2), ("Projects/pulsebound", 6.1), ("Downloads", 5.8), (".config", 4.6),
    ("Projects/wonderwake", 4.1), ("Projects/broadside", 3.3), (".local/share/Trash", 2.1), ("Pictures", 1.9),
    (".rustup", 1.7), ("Projects/skyhook", 1.2), (".var", 0.9), ("Documents", 0.4), (".local/share/fonts", 0.2),
    ("Music", 0.08), (".ssh", 0.0001), (".bashrc", 0.00001), (".gitconfig", 0.00001)]


def demo_plan(free, uname):
    from arclight.migrate import plan as mplan
    items = []
    for p, g in DEMO_HOME:
        it = mplan.Item(p, int(g * GiB))
        if p in mplan.SKIP:
            it.action, it.reason = "skip", "Cache or trash. It comes back by itself"
        items.append(it)
    sysb = int(24.6 * GiB)
    plan = mplan.Plan("/home/arthur", f"/home/{uname}", items, max(0, free - sysb), 15 * GiB, True)
    mplan.balance(plan)
    return {"plan": json.loads(plan.to_json()), "system_bytes": sysb}


def expected_stages(cfg):
    """The stage names Engine.run() will print for this config, in order (mirrors engine.py)."""
    mode = cfg["mode"]
    s = ["preflight"]
    if mode == "side-by-side":
        s += ["mount existing system (old system read-only)", "fingerprint old system",
              "check space (before writing anything)", "create deployment directory"]
    else:
        s += ["partition and format", "mount new filesystems"]
        if cfg.get("migrate", {}).get("source_partition"):
            s.append("mount old system read-only")
    s += ["copy the Arclight system", "prepare chroot", "turn the live image into an installed system",
          "identity: OS name, machine name, time, language", "filesystems and boot image", "services and permissions",
          "user account"]
    s += (["migrate home (copy + verify)", "migrate system settings"] if cfg.get("migrate", {}).get("enabled")
          else ["prepare desktop"])
    s += ["packages", "boot loader (staged, not active yet)", "verify new system"]
    if mode == "side-by-side":
        s.append("verify old system untouched")
    s.append("COMMIT: make the new system the default")
    return s


def fake_engine(cfg_path):
    """Demo: print what `arclight-install --config` prints (ui.Progress + main.run), at a quick pace."""
    cfg = json.loads(Path(cfg_path).read_text())
    speed = float(os.environ.get("ARCLIGHT_INSTALLER_DEMO_SPEED", "1"))
    fail = os.environ.get("ARCLIGHT_INSTALLER_DEMO_FAIL")

    def p(s, t=0.0):
        print(s, flush=True)
        time.sleep(t / speed)

    for st in expected_stages(cfg):
        p(f"▸ {st}", 0.25)
        if st == "preflight":
            p(f"firmware uefi, mode {cfg['mode']}, OS name '{cfg.get('os_name')}', host '{cfg['hostname']}'", 0.3)
        elif st.startswith("mount existing"):
            p(f"existing system found at {cfg.get('partition')}", 0.3)
        elif st == "fingerprint old system":
            p("old system: 1482113 entries recorded; ESP: 41", 1.2)
        elif st.startswith("check space"):
            p("fits: system 24.6 GiB + " + cfg.get("migrate", {}).get("_summary", "fresh desktop"), 0.3)
        elif st == "copy the Arclight system":
            for pc in range(10, 101, 10):
                p(f"  system copy {pc}%", 0.35)
        elif st.startswith("migrate home"):
            items = [i for i in cfg.get("migrate", {}).get("plan", {}).get("items", []) if i["action"] == "copy"]
            items = sorted(items, key=lambda i: -i["bytes"])
            for n, it in enumerate(items, 1):
                p(f"  copy [{n}/{len(items)}] {it['path']} ({it['bytes'] / GiB:.2f} GiB)", 0.12)
            p("verifying every copied file (content checksums)", 1.0)
            p(f"verified {len(items)} items: identical", 0.2)
        elif st == "packages":
            p("212 packages from the old system are not on the install medium", 0.6)
            p("installed 187 packages; 25 left for first boot (AUR)", 0.4)
        elif st.startswith("boot loader"):
            p(f"EFI entry Boot0003 '{cfg.get('os_name')}' created (not active yet)", 0.3)
        elif st.startswith("verify old"):
            p("old system verified unchanged (1482113 entries, ESP 41)", 0.8)
        else:
            time.sleep(0.5 / speed)
        if fail and fail == st:
            p(f"✗ FAILED: not enough space: the new system needs 25 GiB and the migration plan does not fit "
              f"(copy 391.0 GiB · free 370.0 GiB). Share or skip more. Nothing was written.")
            p("rolling back: removing only what this install created", 0.3)
            p("  removed /run/arclight-install/host/arclight/deploy/20261010-120000", 0.2)
            p("\n== Install stopped ==")
            p("not enough space: the new system needs 25 GiB and the migration plan does not fit. Nothing was written.")
            p("Nothing changed on your existing system: the boot order is as it was, and the files this run")
            p("created were removed. Log: /var/log/arclight-install.log")
            return 2
        p(f"✓ {st} ({0.4 * 7:.1f}s)", 0.1)
    p(f"\n== {cfg['os_name']} is installed ==")
    p("It is now the default. Your previous system is still in the boot menu.")
    if cfg["mode"] == "side-by-side":
        p("  Old system verified unchanged (1482113 files checked).")
    return 0


# =============================================================== backends

class RealBackend:
    demo = False

    def _probe(self, args, progress=None):
        cmd = as_root([sys.executable, "-u", launcher(), "--probe"] + args)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
        err = []

        def pump():
            for line in p.stderr:
                err.append(line)
                if progress:
                    progress(line.strip())
        th = threading.Thread(target=pump, daemon=True)
        th.start()
        out = p.stdout.read()
        p.wait()
        th.join(2)
        if p.returncode != 0:
            msg = "".join(err).strip().splitlines()
            if any("password is required" in l or "a terminal is required" in l for l in msg):
                raise RuntimeError("The installer could not get admin rights (sudo asked for a password).")
            raise RuntimeError((msg[-1] if msg else f"exit {p.returncode}")[:300])
        return json.loads(out)

    def scan(self):
        return self._probe(["scan"])

    def plan(self, t, home, uname, progress=None):
        old = t["os"]
        return self._probe(["plan", "--partition", t["partition"], "--fstype", t.get("fstype", "ext4"),
                            "--subdir", old.get("root_subdir", ""), "--home", home, "--user", uname,
                            "--free", str(old["free"])], progress)

    def shadow_ok(self, partition, user, subdir):
        try:
            return self._probe(["shadow", "--partition", partition, "--user", user, "--subdir", subdir]).get("found")
        except Exception:
            return False

    def online(self):
        try:
            return subprocess.run(["bash", "-c", "getent hosts archlinux.org >/dev/null 2>&1"], timeout=10).returncode == 0
        except Exception:
            return False

    def hash_password(self, pw):
        from .main import hash_password
        return hash_password(pw)

    def install(self, cfg_path):
        return subprocess.Popen(as_root([sys.executable, "-u", install_cmd(), "--config", cfg_path]),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, bufsize=1)

    def report(self, since):
        f = RUN / "report.json"
        try:
            if f.stat().st_mtime >= since - 1:
                return json.loads(f.read_text())
        except (OSError, ValueError):
            pass
        return None

    def reboot(self):
        if subprocess.run(["systemctl", "reboot"], capture_output=True).returncode != 0:
            subprocess.run(as_root(["systemctl", "reboot"]))


class DemoBackend(RealBackend):
    demo = True

    def __init__(self):
        disks.uefi = lambda: True

    def scan(self):
        from . import main as M
        time.sleep(0.8)
        scan = demo_scan()
        return {"uefi": True, "disks": scan, "targets": [{"kind": k, "t": t, "label": l} for k, t, l in M.targets(scan)]}

    def plan(self, t, home, uname, progress=None):
        for p, _ in DEMO_HOME:
            if progress:
                progress(p)
            time.sleep(0.04)
        return demo_plan(t["os"]["free"], uname)

    def shadow_ok(self, partition, user, subdir):
        time.sleep(0.3)
        return os.environ.get("ARCLIGHT_INSTALLER_DEMO_NOSHADOW") != "1"

    def online(self):
        return True

    def hash_password(self, pw):
        return "$6$demo$" + "x" * 20

    def install(self, cfg_path):
        return subprocess.Popen([sys.executable, "-u", launcher(), "--fake-engine", cfg_path], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, bufsize=1, env=dict(os.environ))

    def report(self, since):
        return None

    def reboot(self):
        print("demo: would restart now", flush=True)


# =============================================================== plain words

STAGE_TEXT = {
    "preflight": "Checking everything first",
    "mount existing system (old system read-only)": "Opening {old} (read-only)",
    "fingerprint old system": "Taking a fingerprint of {old}",
    "check space (before writing anything)": "Checking there is enough space",
    "create deployment directory": "Making a folder for {name}",
    "partition and format": "Preparing the disk",
    "mount new filesystems": "Opening the new disk",
    "mount old system read-only": "Opening {old} (read-only)",
    "copy the Arclight system": "Copying {name}",
    "prepare chroot": "Getting ready to set it up",
    "turn the live image into an installed system": "Turning the USB system into a real one",
    "identity: OS name, machine name, time, language": "Setting the name, time and language",
    "filesystems and boot image": "Building the start-up image",
    "services and permissions": "Turning on services",
    "user account": "Making your account",
    "migrate home (copy + verify)": "Copying your files and checking each one",
    "migrate system settings": "Bringing over Wi-Fi, Bluetooth and keys",
    "prepare desktop": "Setting up your desktop",
    "packages": "Installing your apps",
    "boot loader (staged, not active yet)": "Adding the boot menu (not active yet)",
    "verify new system": "Checking the new system",
    "verify old system untouched": "Checking {old} is unchanged",
    "COMMIT: make the new system the default": "Making {name} the default",
}
STAGE_WEIGHT = {"copy the Arclight system": 18, "migrate home (copy + verify)": 30, "packages": 12,
                "filesystems and boot image": 8, "turn the live image into an installed system": 5,
                "identity: OS name, machine name, time, language": 4, "fingerprint old system": 3,
                "verify old system untouched": 3, "services and permissions": 3, "prepare desktop": 3,
                "boot loader (staged, not active yet)": 3, "verify new system": 2}

ERRORS = [
    ("not enough space", "There is not enough free space on the disk."),
    ("does not fit", "Your files do not fit in the free space."),
    ("could not read the old password", "Your old password could not be read."),
    ("admin rights", "The installer could not get admin rights."),
    ("is in use", "Another install seems to be running."),
    ("live system image not found", "This only works when started from the USB stick."),
    ("does not exist", "The disk you picked cannot be found any more."),
    ("old system's files changed", "Your old system changed during the install, so it stopped to stay safe."),
    ("verification failed", "A check at the end failed, so it stopped to stay safe."),
    ("copying the system failed", "Copying the system failed."),
    ("efi boot entry", "The boot entry could not be made."),
    ("already exists", "An earlier Eclipse OS install is in the way."),
    ("needs uefi", "This PC started the USB in old BIOS mode. Side by side needs UEFI."),
]


def plain_error(err):
    e = (err or "").strip()
    low = e.lower()
    for k, v in ERRORS:
        if k in low:
            return v
    first = re.split(r"(?<=[.:])\s", e, maxsplit=1)[0].rstrip(":.")
    return (first[:1].upper() + first[1:] + ".") if first else "Something went wrong."


# =============================================================== the window

CSS = """
window.installer, window.installer.background { background-color: $base; color: $text;
  font-family: "Inter", "Noto Sans", sans-serif; font-size: 17px; }
.scrim { background-image: linear-gradient(to bottom, rgba($base_rgb, 0.30), rgba($base_rgb, 0.10) 30%, rgba($base_rgb, 0.55) 100%); }
.scrim.deep { background-image: linear-gradient(to bottom, rgba($base_rgb, 0.45), rgba($base_rgb, 0.62)); }

/* top strip */
.topbar { padding: 12px 18px 10px 22px; }
.brand { font-size: 17px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.3px; }
.brand-sub { font-size: 15px; color: $gold_soft; font-weight: 600; }
.step { font-size: 13px; font-weight: 700; color: rgba($text_rgb, 0.66); padding: 4px 11px; border-radius: 99px; }
.step.done { color: rgba($gold_soft_rgb, 0.85); }
.step.now { color: #1A1205; background-image: linear-gradient(to bottom, $gold_soft, $gold); box-shadow: 0 0 12px rgba($gold_rgb, 0.45); }
.stepdot { color: rgba($text_rgb, 0.25); font-size: 11px; }
button.winclose { min-width: 34px; min-height: 34px; padding: 0; border-radius: 99px; color: $text;
  background-color: rgba($text_rgb, 0.08); box-shadow: inset 0 1px rgba(255,255,255,0.14); border: none; }
button.winclose:hover { background-color: rgba($red_rgb, 0.80); color: white; }

/* liquid glass card */
.glass {
  background-color: rgba($surface_rgb, 0.55);
  background-image: MATERIAL;
  border-radius: 26px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.24), inset 0 0 0 1px rgba($text_rgb, 0.08),
              inset 0 -1px 0 rgba($shadow_rgb, 0.35), 0 18px 48px rgba($shadow_rgb, 0.55);
}
.glass.deep { background-color: rgba($base_rgb, 0.72); }
.kicker { font-size: 13px; font-weight: 800; letter-spacing: 3px; color: $gold; }
.title { font-size: 34px; font-weight: 800; color: #FFFFFF; }
.title.huge { font-size: 46px; }
.sub { font-size: 18px; color: rgba($text_rgb, 0.82); }
.body { font-size: 17px; color: $text; }
.dim { font-size: 15px; color: $text_dim; }
.small { font-size: 14px; color: $text_dim; }
.gold { color: $gold; }
.goldsoft { color: $gold_soft; }
.ok { color: $success; }
.bad { color: #FF6B6B; }
.mono { font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; font-size: 13px; }
.corona-line { min-height: 2px; background-image: linear-gradient(to right, rgba($gold_rgb, 0.0), rgba($gold_rgb, 0.95) 25%, rgba($gold_soft_rgb, 0.0)); }
.point { font-size: 17px; color: $text; }
.point-mark { color: $gold; font-size: 17px; font-weight: 800; }

/* buttons */
button.primary {
  background-image: linear-gradient(to bottom, $gold_soft, $gold 55%, $gold_deep);
  color: #1A1205; font-weight: 800; font-size: 18px; border: none; border-radius: 16px;
  padding: 12px 30px; min-height: 30px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.65), 0 0 18px rgba($gold_rgb, 0.35), 0 6px 16px rgba($shadow_rgb, 0.45);
}
button.primary:hover { box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 0 26px rgba($gold_rgb, 0.60), 0 6px 16px rgba($shadow_rgb, 0.45); }
button.primary:disabled { background-image: none; background-color: rgba($text_rgb, 0.10); color: rgba($text_rgb, 0.35); box-shadow: none; }
button.primary.danger { background-image: linear-gradient(to bottom, #E85050, $red 60%, #A61E1E); color: #FFFFFF;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 0 18px rgba($red_rgb, 0.45), 0 6px 16px rgba($shadow_rgb, 0.45); }
button.primary.danger:disabled { background-image: none; background-color: rgba($red_rgb, 0.18); color: rgba(255,255,255,0.4); box-shadow: none; }
button.ghost { background-color: rgba($text_rgb, 0.07); color: $text; font-size: 17px; font-weight: 600; border: none;
  border-radius: 16px; padding: 12px 24px; box-shadow: inset 0 1px rgba(255,255,255,0.12), inset 0 0 0 1px rgba($text_rgb, 0.08); }
button.ghost:hover { background-color: rgba($text_rgb, 0.13); }
button.link { background: none; border: none; box-shadow: none; color: $text_dim; font-size: 15px; padding: 6px 10px; border-radius: 10px; }
button.link:hover { color: $gold_soft; background-color: rgba($text_rgb, 0.06); }
button:focus-visible { outline: 3px solid rgba($gold_rgb, 0.85); outline-offset: 2px; }

/* choice cards (Where, password) */
button.option {
  background-color: rgba($raised_rgb, 0.42);
  background-image: linear-gradient(to bottom, rgba($text_rgb, 0.05), rgba($text_rgb, 0) 60px);
  border: none; border-radius: 20px; padding: 12px 20px; color: $text;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.16), inset 0 0 0 1px rgba($text_rgb, 0.07);
}
button.option:hover { background-color: rgba($hover_rgb, 0.60); }
button.option:checked {
  background-color: rgba($accent_dim_rgb, 0.70);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.22), transparent 65%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.26), inset 0 0 0 2px rgba($gold_rgb, 0.85), 0 0 22px rgba($gold_rgb, 0.22);
}
button.option.danger:checked {
  background-color: rgba(70, 12, 16, 0.70);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($red_rgb, 0.30), transparent 65%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.20), inset 0 0 0 2px rgba($red_rgb, 0.95), 0 0 22px rgba($red_rgb, 0.30);
}
.opt-title { font-size: 20px; font-weight: 800; color: #FFFFFF; }
.opt-sub { font-size: 15px; color: rgba($text_rgb, 0.78); }
.opt-icon { color: $gold_soft; }
button.option.danger .opt-icon, button.option.danger .opt-title { color: #FF8080; }
.radio { min-width: 22px; min-height: 22px; border-radius: 99px; box-shadow: inset 0 0 0 2px rgba($text_rgb, 0.35); }
button.option:checked .radio { box-shadow: inset 0 0 0 7px $gold; }
button.option.danger:checked .radio { box-shadow: inset 0 0 0 7px $red; }
.badge { font-size: 12px; font-weight: 800; letter-spacing: 1px; color: #1A1205; background-color: $gold; border-radius: 99px; padding: 2px 10px; }
.badge.red { background-color: $red; color: white; }

/* notes */
.note { background-color: rgba($text_rgb, 0.05); border-radius: 16px; padding: 14px 18px;
  box-shadow: inset 0 0 0 1px rgba($text_rgb, 0.07); }
.note.gold { background-color: rgba($gold_rgb, 0.08); box-shadow: inset 0 0 0 1px rgba($gold_rgb, 0.30); }
.note.red { background-color: rgba($red_rgb, 0.16); box-shadow: inset 0 0 0 1px rgba($red_rgb, 0.70); }
.note.red label.body { color: #FFD9D9; }

/* entries */
.field-label { font-size: 16px; font-weight: 700; color: $gold_soft; }
entry, passwordentry { font-size: 20px; min-height: 48px; padding: 0 16px; border-radius: 14px; color: #FFFFFF;
  background-color: rgba($sunken_rgb, 0.55); border: none; caret-color: $gold;
  box-shadow: inset 0 0 0 1px rgba($text_rgb, 0.14), inset 0 2px 6px rgba(0,0,0,0.35); }
entry:focus-within, passwordentry:focus-within { box-shadow: inset 0 0 0 2px rgba($gold_rgb, 0.85), 0 0 14px rgba($gold_rgb, 0.22); outline: none; }
entry.error, passwordentry.error { box-shadow: inset 0 0 0 2px rgba($red_rgb, 0.9); }
entry.erase:focus-within { box-shadow: inset 0 0 0 2px rgba($red_rgb, 0.95), 0 0 14px rgba($red_rgb, 0.30); }
.hint { font-size: 14px; color: $text_dim; }
.err { font-size: 15px; color: #FF7A7A; font-weight: 600; }

/* switch row */
switch { background-color: rgba($text_rgb, 0.18); border-radius: 99px; }
switch:checked { background-color: $gold; }
switch slider { background-color: #FFFFFF; border-radius: 99px; min-width: 26px; min-height: 26px; }

/* plan */
.tile { background-color: rgba($text_rgb, 0.05); border-radius: 18px; padding: 12px 16px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.10), inset 0 0 0 1px rgba($text_rgb, 0.06); }
.tile-num { font-size: 26px; font-weight: 800; color: #FFFFFF; }
.tile-copy .tile-num { color: $gold; }
.tile-share .tile-num { color: $accent_bright; }
.tile-label { font-size: 14px; color: $text_dim; font-weight: 600; }
.fits { font-size: 17px; font-weight: 700; color: $success; }
.fits.no { color: #FF7A7A; }
.plan-list { background: transparent; }
.plan-row { padding: 6px 4px; border-bottom: 1px solid rgba($text_rgb, 0.06); }
.plan-size { font-size: 16px; font-weight: 700; color: $gold_soft; font-family: "JetBrainsMono Nerd Font", monospace; }
.plan-path { font-size: 16px; color: #FFFFFF; }
.plan-why { font-size: 13px; color: $text_dim; }
.seg button { font-size: 14px; font-weight: 700; padding: 5px 12px; min-height: 26px; color: $text_dim;
  background-color: rgba($text_rgb, 0.06); border: none; box-shadow: inset 0 0 0 1px rgba($text_rgb, 0.08); }
.seg button:first-child { border-radius: 10px 0 0 10px; }
.seg button:last-child { border-radius: 0 10px 10px 0; }
.seg button:checked { color: #1A1205; background-color: $gold; box-shadow: none; }
.seg button.share:checked { background-color: $accent_bright; }
.seg button.skip:checked { background-color: rgba($text_rgb, 0.55); }
scrolledwindow.plain, scrolledwindow.plain > viewport { background: transparent; }
/* a list that goes on below the fold fades out softly (and says so) instead of cutting a row in half */
scrolledwindow.plain undershoot.bottom {
  background-image: linear-gradient(to top, rgba($base_rgb, 0.85), rgba($base_rgb, 0.0));
  min-height: 36px; border-radius: 0 0 20px 20px;
}
scrolledwindow.plain undershoot.top { background-image: linear-gradient(to bottom, rgba($base_rgb, 0.6), rgba($base_rgb, 0.0)); min-height: 18px; }
/* Where: compact choices so four fit in the window */
.where-list button.option { padding: 9px 18px; }
.where-list .opt-title { font-size: 18px; }
.where-list .opt-sub { font-size: 14px; }

/* summary */
.sum-key { font-size: 15px; font-weight: 700; color: $text_dim; }
.sum-val { font-size: 18px; color: #FFFFFF; }
.nothing { font-size: 20px; font-weight: 700; color: $gold_soft; }

/* progress */
.stage-now { font-size: 26px; font-weight: 800; color: #FFFFFF; }
.stage-detail { font-size: 15px; color: $text_dim; font-family: "JetBrainsMono Nerd Font", monospace; }
progressbar.big trough { min-height: 14px; border-radius: 99px; background-color: rgba($text_rgb, 0.10); }
progressbar.big progress { min-height: 14px; border-radius: 99px; }
.pct { font-size: 22px; font-weight: 800; color: $gold; }
.st-row { font-size: 15px; color: rgba($text_rgb, 0.60); }  /* steps still to come: dim but readable */
.st-row.done { color: rgba($text_rgb, 0.85); }
.st-row.now { color: $gold_soft; font-weight: 700; }
.st-row.fail { color: #FF7A7A; font-weight: 700; }
.st-mark { font-size: 15px; min-width: 20px; }
.st-row.done .st-mark { color: $success; }
.logview, .logview text { background-color: rgba($sunken_rgb, 0.65); color: rgba($text_rgb, 0.85); }
.logbox { border-radius: 14px; box-shadow: inset 0 0 0 1px rgba($text_rgb, 0.08); }
expander title { color: $text_dim; font-size: 15px; }
expander title:hover { color: $gold_soft; }
spinner { color: $gold; }
.big-mark { color: #1A1205; font-size: 34px; font-weight: 900; min-width: 58px; min-height: 58px; border-radius: 99px;
  background-image: radial-gradient(circle, $gold_soft, $gold 60%, $gold_deep); box-shadow: 0 0 24px rgba($gold_rgb, 0.55); }
.big-mark.bad { color: #FFFFFF; background-image: radial-gradient(circle, #F06060, $red 65%, #8E1A1A);
  box-shadow: 0 0 24px rgba($red_rgb, 0.55); }
"""


class _GlassFallback:
    ECLIPSE = {"base": "#0B0B0D", "sunken": "#070708", "surface": "#17181B", "raised": "#222327", "hover": "#2B2C31",
               "border": "#34353A", "border_strong": "#4A4A50", "accent": "#D08A4E", "accent_bright": "#EDB98A",
               "accent_dim": "#6E4F36", "gold": "#FFC94A", "gold_soft": "#FFE6B8", "gold_deep": "#E89B2A",
               "core": "#FFF6E4", "red": "#D42B2B", "text": "#ECEAE6", "text_dim": "#9A958E", "muted": "#6A665F",
               "success": "#3FD69A", "warning": "#E0B040", "shadow": "#000000"}
    MATERIAL = ('radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.13), transparent 46%), '
                'linear-gradient(to bottom, rgba($text_rgb, 0.06), rgba($text_rgb, 0.0) 38%)')
    COMMON = """
progressbar progress { background-image: linear-gradient(to right, $gold_deep, $gold, $gold_soft); border: none;
  box-shadow: 0 0 8px rgba($gold_rgb, 0.45); }
progressbar trough { background-color: rgba($text_rgb, 0.10); border: none; }
selection, text selection, label selection { background-color: rgba($gold_rgb, 0.32); color: $core; }
tooltip, tooltip.background { background-color: rgba($surface_rgb, 0.92); color: $text; border-radius: 10px; }
scrollbar slider { background-color: rgba($text_rgb, 0.22); border-radius: 99px; min-width: 6px; }
"""

    @staticmethod
    def asset_uri(name):
        for d in (Path("/usr/share/arclight/eclipse"), REPO / "desktop/eclipse", REPO / "art/eclipse/glass"):
            if (d / name).exists():
                return (d / name).as_uri()
        return ""


def main_gui(demo=False):
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: F401

    from . import main as M
    try:
        from arclight.apps import glass
    except ImportError:   # an older eclipse-os-core without the shared glass module: same values, inline
        glass = _GlassFallback
    try:
        from arclight.apps import motion   # eased progress + entrances on the real clock
    except ImportError:   # older eclipse-os-core: no motion, everything still works
        motion = None

    backend = DemoBackend() if demo else RealBackend()

    def lab(text, cls=None, xalign=0.0, wrap=True, **kw):
        w = Gtk.Label(label=text, xalign=xalign, wrap=wrap, **kw)
        if wrap:
            w.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD) if hasattr(w, "set_natural_wrap_mode") else None
        for c in (cls or "").split():
            w.add_css_class(c)
        return w

    def box(vertical=True, spacing=0, cls=None, **kw):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing, **kw)
        for c in (cls or "").split():
            b.add_css_class(c)
        return b

    def button(text, cls="ghost", cb=None):
        b = Gtk.Button(label=text)
        for c in cls.split():
            b.add_css_class(c)
        if cb:
            b.connect("clicked", lambda _b: cb())
        return b

    def a11y(w, text):
        try:
            w.update_property([Gtk.AccessibleProperty.LABEL], [text])
        except Exception:
            pass

    def background_file():
        """The photo, lightly blurred and dimmed once (cached), so text on glass stays readable."""
        src = None
        for c in (Path("/usr/share/arclight/wallpapers/arclight-eclipse.jpg"), REPO / "desktop/wallpapers/arclight-eclipse.jpg",
                  Path("/usr/share/backgrounds/arclight/arclight-eclipse.jpg")):
            if c.exists():
                src = c
                break
        if not src:
            return None
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "arclight"
        out = cache / "installer-bg-v3.jpg"
        try:
            if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
                return out
            from PIL import Image, ImageEnhance, ImageFilter
            im = Image.open(src).convert("RGB")
            im.thumbnail((1920, 1080))
            im = im.filter(ImageFilter.GaussianBlur(4.5))
            im = ImageEnhance.Brightness(im).enhance(0.72)
            im = ImageEnhance.Color(im).enhance(1.08)
            cache.mkdir(parents=True, exist_ok=True)
            im.save(out, quality=90)
            return out
        except Exception:
            return src

    def logo_file():
        for c in (Path("/usr/share/arclight/logo/eclipse-mark.svg"), REPO / "art/eclipse/logo/eclipse-mark.svg",
                  Path("/usr/share/icons/hicolor/scalable/apps/arclight.svg")):
            if c.exists():
                return str(c)
        return None

    def logo(size):
        f = logo_file()
        img = Gtk.Image.new_from_file(f) if f else Gtk.Image.new_from_icon_name("arclight")
        img.set_pixel_size(size)
        return img

    def in_thread(fn, done, *args):
        def run():
            try:
                r = fn(*args)
                GLib.idle_add(lambda: (done(r, None), False)[1])
            except Exception as e:  # noqa: BLE001
                err = e
                GLib.idle_add(lambda: (done(None, err), False)[1])
        threading.Thread(target=run, daemon=True).start()

    STEPS = [("where", "Where"), ("name", "Name"), ("files", "Files"), ("user", "You"), ("summary", "Check"),
             ("install", "Install")]

    class Win(Adw.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title=f"Install {M.ui.os_name()}", default_width=1100, default_height=720)
            self.add_css_class("installer")
            self.set_icon_name("arclight")
            self.default_name = M.ui.os_name()
            self.s = {"scan": None, "scan_err": None, "target": None, "os_name": self.default_name, "hostname": None,
                      "migrate_on": True, "old_user": None, "plan": None, "plan_key": None, "sysb": 0, "uname": None,
                      "keep_pw": True, "shadow": None, "online": None, "result": None}
            self.running = None
            self.history = []
            self.pages = {}
            root = Gtk.Overlay()
            bg = background_file()
            if bg:
                pic = Gtk.Picture.new_for_filename(str(bg))
                pic.set_content_fit(Gtk.ContentFit.COVER)
                pic.set_can_shrink(True)
                root.set_child(pic)
            else:
                root.set_child(Gtk.Box())
            self.scrim = box(cls="scrim")
            self.scrim.set_can_target(False)
            root.add_overlay(self.scrim)
            main = box()
            root.add_overlay(main)
            main.append(self._topbar())
            # pages cross-fade while the new page's content rises in (motion.rise in go())
            self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=260, vexpand=True)
            main.append(self.stack)
            self.set_content(root)
            for pid, build in (("welcome", self.p_welcome), ("where", self.p_where), ("name", self.p_name),
                               ("files", self.p_files), ("user", self.p_user), ("summary", self.p_summary),
                               ("install", self.p_install), ("done", self.p_done)):
                w = build()
                self.pages[pid] = w
                self.stack.add_named(w, pid)
            kc = Gtk.EventControllerKey()
            kc.connect("key-pressed", self._key)
            self.add_controller(kc)
            self.connect("close-request", self._close_request)
            self.go("welcome", push=False)
            in_thread(backend.scan, self._scanned)

        # ------------------------------------------------ chrome
        def _topbar(self):
            h = Gtk.WindowHandle()
            bar = box(False, 10, cls="topbar")
            bar.append(logo(30))
            bar.append(lab(self.default_name, "brand", wrap=False))
            bar.append(lab("Installer" + ("  ·  demo" if backend.demo else ""), "brand-sub", wrap=False))
            spacer = Gtk.Box(hexpand=True)
            bar.append(spacer)
            self.steps = box(False, 4, valign=Gtk.Align.CENTER)
            self.step_labels = {}
            self.step_dots = {}
            for i, (pid, name) in enumerate(STEPS):
                if i:
                    dot = lab("•", "stepdot", wrap=False, accessible_role=Gtk.AccessibleRole.PRESENTATION)
                    self.step_dots[pid] = dot
                    self.steps.append(dot)
                l = lab(name, "step", wrap=False)
                self.step_labels[pid] = l
                self.steps.append(l)
            bar.append(self.steps)
            sp2 = Gtk.Box(width_request=14)
            bar.append(sp2)
            self.closeb = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Close")
            self.closeb.add_css_class("winclose")
            a11y(self.closeb, "Close")
            self.closeb.connect("clicked", lambda _b: self.close())
            bar.append(self.closeb)
            h.set_child(bar)
            return h

        def _set_steps(self, pid):
            order = [p for p, _ in STEPS]
            cur = {"done": "install"}.get(pid, pid)
            self.steps.set_visible(pid != "welcome")
            idx = order.index(cur) if cur in order else -1
            for i, p in enumerate(order):
                l = self.step_labels[p]
                for c in ("now", "done"):
                    l.remove_css_class(c)
                if i < idx or (pid == "done" and i == idx):
                    l.add_css_class("done")
                elif i == idx:
                    l.add_css_class("now")
            files_needed = self._target_kind() in (None, "side")
            self.step_labels["files"].set_visible(files_needed)
            self.step_dots["files"].set_visible(files_needed)

        def _card(self, kicker, title, sub=None, deep=False):
            """A page: a glass card with a kicker, a big title, a subtitle, a content box and a nav row."""
            outer = box(margin_start=40, margin_end=40, margin_top=6, margin_bottom=30)
            card = box(spacing=0, cls="glass deep" if deep else "glass", vexpand=True)
            inner = box(spacing=8, margin_start=40, margin_end=40, margin_top=26, margin_bottom=24, vexpand=True)
            card.append(inner)
            outer.append(card)
            inner.append(lab(kicker.upper(), "kicker"))
            t = lab(title, "title")
            inner.append(t)
            line = Gtk.Box(width_request=260, halign=Gtk.Align.START, margin_top=2, margin_bottom=2)
            line.add_css_class("corona-line")
            inner.append(line)
            s = lab(sub or "", "sub")
            s.set_visible(bool(sub))
            inner.append(s)
            content = box(spacing=12, vexpand=True, margin_top=8)
            inner.append(content)
            nav = box(False, 12, margin_top=14)
            inner.append(nav)
            outer.title_label, outer.sub_label, outer.content, outer.nav = t, s, content, nav
            outer.inner = inner
            return outer

        def _nav(self, page, next_text="Next", next_cb=None, back=True, extra=None):
            if back:
                b = button("Back", "ghost", self.back)
                page.nav.append(b)
                page.back_btn = b
            for w in extra or []:
                page.nav.append(w)
            page.nav.append(Gtk.Box(hexpand=True))
            n = button(next_text, "primary", next_cb or self.next)
            page.nav.append(n)
            page.next_btn = n
            return n

        def _key(self, _c, kv, _code, state):
            alt = state & Gdk.ModifierType.ALT_MASK
            cur = self.stack.get_visible_child_name()
            if kv == Gdk.KEY_Escape or (alt and kv == Gdk.KEY_Left):
                if cur not in ("welcome", "install", "done"):
                    self.back()
                    return True
            if alt and kv == Gdk.KEY_Right:
                nb = getattr(self.pages[cur], "next_btn", None)
                if nb and nb.get_sensitive():
                    nb.emit("clicked")
                return True
            return False

        def _close_request(self, _w):
            if self.running:
                self.install_note.set_label("The install is running. Please wait until it finishes; closing now would stop it halfway.")
                self.install_note.set_visible(True)
                return True
            return False

        # ------------------------------------------------ navigation
        def flow(self):
            f = ["welcome", "where", "name"]
            if self._target_kind() == "side" and self._old_users():
                f.append("files")
            f += ["user", "summary", "install", "done"]
            return f

        def go(self, pid, push=True):
            cur = self.stack.get_visible_child_name()
            if push and cur and cur != pid:
                self.history.append(cur)
            enter = getattr(self, "enter_" + pid, None)
            if enter:
                enter()
            self.stack.set_visible_child_name(pid)
            self._set_steps(pid)
            page = self.pages[pid]
            if motion and getattr(page, "inner", None) is not None and cur != pid:
                motion.rise(motion.children(page.inner))   # kicker, title, content, buttons come in in turn
            self.scrim.remove_css_class("deep")
            if pid != "welcome":
                self.scrim.add_css_class("deep")
            nb = getattr(page, "next_btn", None)
            self.set_default_widget(nb)
            GLib.idle_add(lambda: (self._focus(pid), False)[1])

        def _focus(self, pid):
            page = self.pages[pid]
            f = getattr(page, "first_focus", None)
            w = f() if callable(f) else f
            if w is None:
                w = getattr(page, "next_btn", None)
            if w is not None and w.get_visible() and w.get_sensitive():
                w.grab_focus()

        def next(self):
            f = self.flow()
            cur = self.stack.get_visible_child_name()
            leave = getattr(self, "leave_" + cur, None)
            if leave and leave() is False:
                return
            i = f.index(cur)
            self.go(f[i + 1])

        def back(self):
            if self.running:
                return
            while self.history:
                p = self.history.pop()
                if p in self.flow() and p not in ("install", "done"):
                    self.go(p, push=False)
                    return
            self.go("welcome", push=False)

        # ------------------------------------------------ state helpers
        def _target(self):
            return self.s["target"]

        def _target_kind(self):
            t = self._target()
            return t["kind"] if t else None

        def _old(self):
            t = self._target()
            return (t["t"].get("os") if t else None) or None

        def _old_users(self):
            return (self._old() or {}).get("users", [])

        def _migrating(self):
            return "files" in self.flow() and self.s["migrate_on"]

        # ================================================= pages
        def p_welcome(self):
            outer = box(margin_start=44, margin_end=44, margin_bottom=40, margin_top=10)
            outer.append(Gtk.Box(vexpand=True))
            card = box(spacing=0, cls="glass", halign=Gtk.Align.START, width_request=600)
            inner = box(spacing=12, margin_start=38, margin_end=38, margin_top=32, margin_bottom=28)
            card.append(inner)
            row = box(False, 18)
            row.append(logo(84))
            tb = box(spacing=4, valign=Gtk.Align.CENTER)
            from arclight.edition import has_ai
            tb.append(lab("AI-NATIVE ARCH  ·  INSTALLER" if has_ai() else "ARCH LINUX  ·  INSTALLER", "kicker"))
            tb.append(lab(f"Install {self.default_name}", "title huge"))
            row.append(tb)
            inner.append(row)
            line = Gtk.Box(width_request=320, halign=Gtk.Align.START)
            line.add_css_class("corona-line")
            inner.append(line)
            inner.append(lab("Your desktop, your apps, your files. A few questions, then it builds itself.", "sub"))
            pts = box(spacing=8, margin_top=8)
            for t in ("Nothing is written until you press Install.", "Your old system stays safe.",
                      "It takes about 15 minutes."):
                r = box(False, 12)
                r.append(lab("●", "point-mark", wrap=False, accessible_role=Gtk.AccessibleRole.PRESENTATION))
                r.append(lab(t, "point"))
                pts.append(r)
            inner.append(pts)
            nav = box(False, 12, margin_top=18)
            start = button("Start", "primary", self.next)
            start.set_size_request(170, -1)
            nav.append(start)
            nav.append(Gtk.Box(hexpand=True))
            rite = button("Advanced install", "link", self.open_rite)
            rite.set_tooltip_text("The Rite: build every part by hand, in a terminal. For experts.")
            shell = button("Terminal", "link", self.open_shell)
            shell.set_tooltip_text("Open a terminal")
            nav.append(rite)
            nav.append(shell)
            inner.append(nav)
            outer.append(card)
            outer.next_btn = start
            return outer

        def _terminal(self, title, cmd):
            term = shutil.which("ghostty") or shutil.which("kitty")
            if not term:
                return
            if term.endswith("ghostty"):
                args = [term, "--class=dev.arclight.InstallerText", f"--title={title}", "--font-size=14"]
                args += (["-e"] + cmd) if cmd else []
            else:
                args = [term, "--class", "dev.arclight.InstallerText", "--title", title] + cmd
            subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def open_rite(self):
            # what main.py's "Advanced" choice does: the Rite as root (sudo is passwordless on the live USB)
            self._terminal("The Rite", (["sudo"] if os.geteuid() else []) + ["rite", "begin"])

        def open_shell(self):
            self._terminal(f"{self.default_name} shell", [])

        # ------------------------------------------------ where
        def p_where(self):
            p = self._card("Step 1 · Where", f"Where should {self.default_name} go?",
                           "Pick a place. Nothing is changed yet.")
            self.where_stack = Gtk.Stack(vexpand=True)
            loading = box(spacing=14, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
            sp = Gtk.Spinner(spinning=True, width_request=48, height_request=48)
            loading.append(sp)
            loading.append(lab("Looking at your disks (read-only)…", "sub", xalign=0.5))
            self.where_stack.add_named(loading, "loading")
            err = box(spacing=14, valign=Gtk.Align.CENTER)
            self.where_err = lab("", "body")
            err.append(self.where_err)
            err.append(button("Try again", "ghost", self.rescan))
            self.where_stack.add_named(err, "error")
            sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, propagate_natural_height=True)
            sw.add_css_class("plain")
            self.where_list = box(spacing=10, cls="where-list")
            sw.set_child(self.where_list)
            self.where_stack.add_named(sw, "list")
            p.content.append(self.where_stack)
            self.where_note = box(cls="note")
            self.where_note_text = lab("", "body")
            self.where_note.append(self.where_note_text)
            p.content.append(self.where_note)
            self._nav(p)
            p.first_focus = lambda: next((b for b in getattr(self, "where_buttons", []) if b.get_active()), None)
            return p

        def rescan(self):
            self.where_stack.set_visible_child_name("loading")
            in_thread(backend.scan, self._scanned)

        def _scanned(self, res, err):
            if err:
                self.s["scan_err"] = str(err)
                self.where_err.set_label(f"Could not look at the disks.\n{err}")
                self.where_stack.set_visible_child_name("error")
                self._where_changed()
                return
            self.s["scan"] = res
            child = self.where_list.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                self.where_list.remove(child)
                child = nxt
            self.where_buttons = []
            targets = res["targets"]
            if not targets:
                self.where_err.set_label("No disk found that can hold it (it needs 16 GiB or more).")
                self.where_stack.set_visible_child_name("error")
                return
            first = None
            dmodel = {d["path"]: d for d in res.get("disks", [])}
            # recommended first: side-by-side, then free space, then erase (same options as main.targets)
            order = {"side": 0, "free": 1, "erase": 2}
            for o in sorted(targets, key=lambda o: order.get(o["kind"], 3)):
                t, k = o["t"], o["kind"]
                d = dmodel.get(t.get("disk"), {})
                dlabel = f"{d.get('model') or 'disk'} · {gib(d.get('size', 0))}" if d else t.get("disk")
                if k == "side":
                    title = f"Next to {t['os']['name']}"
                    sub = f"Keeps it untouched. {t['partition']} · {gib(t['os']['free'])} free"
                    icon, badge = "drive-harddisk-symbolic", "RECOMMENDED"
                elif k == "free":
                    big = max((r[2] for r in d.get("free_regions", [])), default=0)
                    title = f"Free space on {t['disk']}"
                    sub = f"{gib(big)} not used yet on {d.get('model') or t['disk']}. The rest of the disk stays as it is."
                    icon, badge = "list-add-symbolic", None
                else:
                    osn = ", ".join(sorted({p['os']['name'] for p in d.get('parts', []) if p.get('os')}))
                    title = f"Erase {t['disk']}"
                    sub = f"{dlabel} · " + (f"deletes {osn} and everything else on it" if osn else
                                            ("it is empty" if d.get("empty") else "deletes everything on it"))
                    icon, badge = "user-trash-symbolic", None
                b = Gtk.ToggleButton()
                b.add_css_class("option")
                if k == "erase":
                    b.add_css_class("danger")
                inner = box(False, 16)
                radio = Gtk.Box(valign=Gtk.Align.CENTER)
                radio.add_css_class("radio")
                inner.append(radio)
                ic = Gtk.Image.new_from_icon_name(icon)
                ic.set_pixel_size(30)
                ic.add_css_class("opt-icon")
                inner.append(ic)
                tb = box(spacing=3, hexpand=True)
                tr = box(False, 10)
                tr.append(lab(title, "opt-title", wrap=False))
                if badge:
                    bl = lab(badge, "badge", wrap=False, valign=Gtk.Align.CENTER)
                    tr.append(bl)
                tb.append(tr)
                tb.append(lab(sub, "opt-sub"))
                inner.append(tb)
                b.set_child(inner)
                b.set_tooltip_text(o["label"])
                a11y(b, title)
                if first is None:
                    first = b
                else:
                    b.set_group(first)
                b.target = o
                b.connect("toggled", lambda bb: bb.get_active() and self._pick(bb.target))
                self.where_list.append(b)
                self.where_buttons.append(b)
            self.where_stack.set_visible_child_name("list")
            prev = self.s["target"]
            sel = next((b for b in self.where_buttons if prev and b.target == prev), first)
            sel.set_active(True)
            self._pick(sel.target)
            if self.stack.get_visible_child_name() == "where":
                sel.grab_focus()

        def _pick(self, o):
            if self.s["target"] != o:
                self.s["plan"] = None
                self.s["shadow"] = None
            self.s["target"] = o
            self._where_changed()
            self._set_steps(self.stack.get_visible_child_name() or "welcome")

        def _where_changed(self):
            o = self.s["target"]
            p = self.pages.get("where")
            if not p:
                return
            p.next_btn.set_sensitive(bool(o and self.s["scan"]))
            n = self.where_note
            for c in ("red", "gold"):
                n.remove_css_class(c)
            if not o:
                n.set_visible(False)
                return
            n.set_visible(True)
            t = o["t"]
            if o["kind"] == "side":
                n.add_css_class("gold")
                self.where_note_text.set_label(
                    f"{t['os']['name']} stays exactly as it is. {self.default_name} gets its own folder on that disk and "
                    "its own boot entry. The switch happens at the very end, after everything is checked.")
            elif o["kind"] == "free":
                self.where_note_text.set_label(f"{self.default_name} goes into the empty space. Your other partitions are not touched.")
            else:
                n.add_css_class("red")
                self.where_note_text.set_label(f"This deletes everything on {t['disk']}. "
                                               f"Before anything happens, you will type {t['disk']} to confirm.")

        def enter_where(self):
            self._where_changed()

        # ------------------------------------------------ name
        def p_name(self):
            p = self._card("Step 2 · Name", "Name your system", "You can keep the suggested names. Press Enter to go on.")
            g = box(spacing=6)
            g.append(lab("Name of the operating system", "field-label"))
            self.e_os = Gtk.Entry(text=self.default_name, activates_default=True)
            a11y(self.e_os, "Name of the operating system")
            g.append(self.e_os)
            self.e_os_hint = lab("Shown in the boot menu, the login screen and system info.", "hint")
            g.append(self.e_os_hint)
            p.content.append(g)
            g2 = box(spacing=6, margin_top=14)
            g2.append(lab("Computer name", "field-label"))     # same words as Settings → System
            self.e_host = Gtk.Entry(activates_default=True)
            a11y(self.e_host, "Computer name")
            g2.append(self.e_host)
            self.e_host_hint = lab("How this PC is called on your network. Letters, digits and dashes.", "hint")
            g2.append(self.e_host_hint)
            p.content.append(g2)
            # two choices (both can be changed later in Settings)
            # (the core edition has no built-in AI, so it only asks about the look)
            from arclight.edition import has_ai
            choices = ((("sw_ai", "Use the AI features", "Ask, Eclipse AI and Fix with AI. Off: no AI anywhere."),)
                       if has_ai() else ())
            for attr, title, sub in choices + (("sw_look", "Eclipse look", "The eclipse theme, wallpaper and boot animation. "
                                                                           "Off: plain graphite, same features."),):
                row = box(vertical=False, spacing=12, margin_top=14)
                col = box(spacing=2)
                col.set_hexpand(True)
                col.append(lab(title, "field-label"))
                col.append(lab(sub, "hint"))
                sw = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
                a11y(sw, title)
                setattr(self, attr, sw)
                row.append(col)
                row.append(sw)
                p.content.append(row)
            self.e_os.connect("changed", lambda _e: self._validate_name())
            self.e_host.connect("changed", lambda _e: self._validate_name())
            self._nav(p)
            p.first_focus = self.e_os
            return p

        def enter_name(self):
            if self.s["hostname"] is None:
                self.e_host.set_text((self._old() or {}).get("hostname") or "arclight")
            self._validate_name()

        def _validate_name(self):
            errs = []
            for e, hint, v, ok_text in ((self.e_os, self.e_os_hint, M.v_osname,
                                         "Shown in the boot menu, the login screen and system info."),
                                        (self.e_host, self.e_host_hint, M.v_hostname,
                                         "How this PC is called on your network. Letters, digits and dashes.")):
                err = v(e.get_text().strip())
                if err:
                    e.add_css_class("error")
                    hint.set_label("Use " + err + ".")
                    hint.remove_css_class("hint")
                    hint.add_css_class("err")
                    errs.append(err)
                else:
                    e.remove_css_class("error")
                    hint.set_label(ok_text)
                    hint.remove_css_class("err")
                    hint.add_css_class("hint")
            self.pages["name"].next_btn.set_sensitive(not errs)
            return not errs

        def leave_name(self):
            if not self._validate_name():
                return False
            self.s["os_name"] = self.e_os.get_text().strip()
            self.s["hostname"] = self.e_host.get_text().strip()

        # ------------------------------------------------ files
        def p_files(self):
            p = self._card("Step 3 · Your files", "Bring your files?")
            top = box(False, 16)
            tb = box(spacing=2, hexpand=True)
            self.f_title = lab("Bring over your home folder", "opt-title")
            tb.append(self.f_title)
            tb.append(lab("Settings, projects, games: everything. Nothing is moved: it is copied and checked, or shared.", "opt-sub"))
            top.append(tb)
            self.f_users = Gtk.DropDown.new_from_strings([""])
            self.f_users.set_valign(Gtk.Align.CENTER)
            self.f_users.connect("notify::selected", self._user_picked)
            top.append(self.f_users)
            self.f_switch = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
            a11y(self.f_switch, "Bring over my files")
            self.f_switch.connect("notify::active", lambda *_: self._files_toggled())
            top.append(self.f_switch)
            p.content.append(top)
            self.f_stack = Gtk.Stack(vexpand=True)
            off = box(valign=Gtk.Align.CENTER, cls="note")
            off.append(lab("You get a fresh desktop. Your old files stay on the old system.", "body"))
            self.f_stack.add_named(off, "off")
            meas = box(spacing=12, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
            meas.append(Gtk.Spinner(spinning=True, width_request=44, height_request=44))
            meas.append(lab("Measuring your files…", "sub", xalign=0.5))
            meas.append(lab("Big homes can take a few minutes. Nothing is changed.", "dim", xalign=0.5))
            self.f_meas = lab("", "stage-detail", xalign=0.5, wrap=False, ellipsize=Pango.EllipsizeMode.END)
            meas.append(self.f_meas)
            self.f_stack.add_named(meas, "measuring")
            ferr = box(spacing=12, valign=Gtk.Align.CENTER)
            self.f_err = lab("", "body")
            ferr.append(self.f_err)
            ferr.append(button("Try again", "ghost", self._measure))
            self.f_stack.add_named(ferr, "error")
            planbox = box(spacing=8)
            tiles = box(False, 10, homogeneous=True)
            self.tiles = {}
            for k, name in (("copy", "Copy"), ("share", "Share"), ("skip", "Skip"), ("free", "Free space")):
                t = box(spacing=0, cls=f"tile tile-{k}")
                n = lab("–", "tile-num")
                t.append(n)
                t.append(lab(name, "tile-label"))
                tiles.append(t)
                self.tiles[k] = n
            planbox.append(tiles)
            self.f_fits = lab("", "fits")
            planbox.append(self.f_fits)
            planbox.append(lab("Copy: copied and checked.   Share: stays where it is, both systems use it.   "
                               "Skip: caches, they come back by themselves.", "small"))
            sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            sw.add_css_class("plain")
            self.f_list = box(spacing=0, cls="plan-list")
            sw.set_child(self.f_list)
            planbox.append(sw)
            self.f_stack.add_named(planbox, "plan")
            p.content.append(self.f_stack)
            self._nav(p)
            p.first_focus = self.f_switch
            return p

        def enter_files(self):
            users = self._old_users()
            if self.s["old_user"] not in users:
                self.s["old_user"] = users[0]
            names = [f"{u['name']} ({u['home']})" for u in users]
            self.f_users.set_model(Gtk.StringList.new(names))
            self.f_users.set_selected(users.index(self.s["old_user"]))
            self.f_users.set_visible(len(users) > 1)
            self._files_toggled()

        def _user_picked(self, *_):
            users = self._old_users()
            i = self.f_users.get_selected()
            if 0 <= i < len(users) and users[i] != self.s["old_user"]:
                self.s["old_user"] = users[i]
                self.s["plan"] = None
                self.s["shadow"] = None
                self._files_toggled()

        def _files_toggled(self):
            on = self.f_switch.get_active()
            self.s["migrate_on"] = on
            ou = self.s["old_user"] or {}
            self.f_title.set_label(f"Bring over {ou.get('home', 'your home folder')}")
            nb = self.pages["files"].next_btn
            if not on:
                self.f_stack.set_visible_child_name("off")
                nb.set_sensitive(True)
                return
            key = (self._target()["t"].get("partition"), ou.get("home"))
            if self.s["plan"] is not None and self.s["plan_key"] == key:
                self._show_plan()
            else:
                self._measure()

        def _measure(self):
            ou = self.s["old_user"]
            t = self._target()["t"]
            key = (t.get("partition"), ou["home"])
            self.f_stack.set_visible_child_name("measuring")
            self.pages["files"].next_btn.set_sensitive(False)
            uname = self.s["uname"] or ou["name"]

            def progress(rel):
                GLib.idle_add(lambda: (self.f_meas.set_label("~/" + rel), False)[1])

            def done(res, err):
                if self.s["old_user"] != ou or self._target()["t"] is not t:
                    return
                if err:
                    self.f_err.set_label(f"Could not measure your files. {err}")
                    self.f_stack.set_visible_child_name("error")
                    return
                from arclight.migrate import plan as mplan
                self.s["plan"] = mplan.Plan.from_json(json.dumps(res["plan"]))
                self.s["plan_key"] = key
                self.s["sysb"] = res.get("system_bytes", 0)
                if self.f_switch.get_active():
                    self._show_plan()
            in_thread(backend.plan, done, t, ou["home"], uname, progress)

        def _show_plan(self):
            plan = self.s["plan"]
            child = self.f_list.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                self.f_list.remove(child)
                child = nxt
            items = sorted(plan.items, key=lambda i: -i.bytes)
            big = [i for i in items if i.bytes > 50 * MiB][:40]   # the same items main.py lets you choose
            rest = [i for i in items if i not in big]
            self.f_rows = {}
            for it in big:
                r = box(False, 12, cls="plan-row")
                sz = lab(gib(it.bytes), "plan-size", xalign=1.0, wrap=False, width_chars=8)
                r.append(sz)
                tb = box(spacing=0, hexpand=True, valign=Gtk.Align.CENTER)
                tb.append(lab("~/" + it.path, "plan-path", wrap=False, ellipsize=Pango.EllipsizeMode.END))
                why = lab(it.reason or "", "plan-why", wrap=False, ellipsize=Pango.EllipsizeMode.END)
                why.set_visible(bool(it.reason))
                tb.append(why)
                r.append(tb)
                seg = box(False, 0, cls="seg", valign=Gtk.Align.CENTER)
                grp = None
                btns = {}
                for act, name in (("copy", "Copy"), ("share", "Share"), ("skip", "Skip")):
                    b = Gtk.ToggleButton(child=Gtk.Label(label=name))   # own child: no labelled-by, so the name below wins
                    b.add_css_class(act)
                    a11y(b, f"{name} ~/{it.path}")
                    if grp:
                        b.set_group(grp)
                    else:
                        grp = b
                    b.set_active(it.action == act)
                    btns[act] = b
                    seg.append(b)
                for act, b in btns.items():
                    b.connect("toggled", self._seg_toggled, it, act, why)
                self.f_rows[it.path] = btns
                r.append(seg)
                self.f_list.append(r)
            if rest:
                tot = sum(i.bytes for i in rest if i.action == "copy")
                ex = Gtk.Expander(label=f"{len(rest)} small items, {gib(tot)} copied", margin_top=8)
                eb = box(spacing=2, margin_top=6)
                for it in rest:
                    eb.append(lab(f"{it.action:<5}  {gib(it.bytes):>9}   ~/{it.path}", "mono small", wrap=False))
                ex.set_child(eb)
                self.f_list.append(ex)
            self.f_stack.set_visible_child_name("plan")
            self._plan_totals()

        def _seg_toggled(self, b, it, act, why):
            if not b.get_active():
                return
            it.action, it.reason = act, "your choice"
            why.set_label("your choice")
            why.set_visible(True)
            self._plan_totals()

        def _plan_totals(self):
            plan = self.s["plan"]
            for k in ("copy", "share", "skip"):
                self.tiles[k].set_label(gib(plan.total(k)))
            self.tiles["free"].set_label(gib(plan.free_bytes))
            fits = plan.fits()
            if fits:
                spare = plan.free_bytes - plan.total("copy")
                self.f_fits.set_label(f"✓  It fits. {gib(spare)} stays free after the copy.")
                self.f_fits.set_tooltip_text(f"The new system's own {gib(self.s['sysb'])} is already counted.")
                self.f_fits.remove_css_class("no")
            else:
                self.f_fits.set_label("✗  It does not fit yet. Share or skip more.")
                self.f_fits.add_css_class("no")
            self.pages["files"].next_btn.set_sensitive(fits)

        def leave_files(self):
            if self.s["migrate_on"] and not (self.s["plan"] and self.s["plan"].fits()):
                return False

        # ------------------------------------------------ user
        def p_user(self):
            p = self._card("Step 4 · You", "Your account", "You log in automatically on this PC, like now.")
            g = box(spacing=6)
            g.append(lab("User name", "field-label"))
            self.e_user = Gtk.Entry(activates_default=True)
            a11y(self.e_user, "User name")
            self.e_user.connect("changed", lambda _e: self._validate_user())
            g.append(self.e_user)
            self.e_user_hint = lab("", "hint")
            g.append(self.e_user_hint)
            p.content.append(g)
            self.pw_choice = box(False, 12, homogeneous=True, margin_top=8)
            self.pw_keep = Gtk.ToggleButton()
            self.pw_new = Gtk.ToggleButton(group=self.pw_keep)
            for b, title, sub in ((self.pw_keep, "Keep my old password", "The one you use now. Nothing new to remember."),
                                  (self.pw_new, "Choose a new password", "Type it twice.")):
                b.add_css_class("option")
                ib = box(False, 14)
                r = Gtk.Box(valign=Gtk.Align.CENTER)
                r.add_css_class("radio")
                ib.append(r)
                tb = box(spacing=2)
                tb.append(lab(title, "opt-title"))
                tb.append(lab(sub, "opt-sub"))
                ib.append(tb)
                b.set_child(ib)
                a11y(b, title)
                self.pw_choice.append(b)
            self.pw_keep.connect("toggled", lambda _b: self._pw_mode())
            self.pw_new.connect("toggled", lambda _b: self._pw_mode())
            p.content.append(self.pw_choice)
            self.pw_note = lab("", "dim")
            p.content.append(self.pw_note)
            self.pw_fields = box(spacing=6, margin_top=4)
            pr = box(False, 12, homogeneous=True)
            c1 = box(spacing=6)
            c1.append(lab("Password", "field-label"))
            self.e_pw1 = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True)
            a11y(self.e_pw1, "Password")
            c1.append(self.e_pw1)
            c2 = box(spacing=6)
            c2.append(lab("Password again", "field-label"))
            self.e_pw2 = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True)
            a11y(self.e_pw2, "Password again")
            c2.append(self.e_pw2)
            pr.append(c1)
            pr.append(c2)
            self.pw_fields.append(pr)
            self.pw_err = lab("", "err")
            self.pw_fields.append(self.pw_err)
            p.content.append(self.pw_fields)
            for e in (self.e_pw1, self.e_pw2):
                e.connect("changed", lambda _e: self._validate_user())
            self._nav(p)
            p.first_focus = self.e_user
            return p

        def enter_user(self):
            ou = self.s["old_user"] if self._migrating() else None
            if self.s["uname"] is None or (ou and self.s.get("uname_from") != ou["name"]):
                self.e_user.set_text((ou or {}).get("name") or "arthur")
                self.s["uname_from"] = (ou or {}).get("name")
            can_keep = bool(self._migrating())
            self.pw_choice.set_visible(can_keep)
            if not can_keep:
                self.pw_new.set_active(True)
            elif not self.pw_new.get_active() and not self.pw_keep.get_active():
                self.pw_keep.set_active(True)
            self._pw_mode()

        def _pw_mode(self):
            keep = self.pw_keep.get_active() and self.pw_choice.get_visible()
            self.pw_fields.set_visible(not keep)
            self.pw_note.set_visible(keep)
            if keep:
                ou = self.s["old_user"]
                t = self._target()["t"]
                if self.s["shadow"] is None:
                    self.pw_note.set_label("Checking that your old password can be read…")
                    self.s["shadow"] = "checking"

                    def done(ok, _err):
                        self.s["shadow"] = bool(ok)
                        self._pw_mode()
                    in_thread(backend.shadow_ok, done, t["partition"], ou["name"], t["os"].get("root_subdir", ""))
                elif self.s["shadow"] is False:
                    self.pw_note.set_label("Your old password could not be read. Please choose a new one.")
                    self.pw_new.set_active(True)
                    return
                elif self.s["shadow"] is True:
                    self.pw_note.set_label(f"✓  Your password for {ou['name']} on {t['os']['name']} will work here too.")
            self._validate_user()

        def _validate_user(self):
            ok = True
            err = M.v_user(self.e_user.get_text().strip())
            if err:
                self.e_user.add_css_class("error")
                self.e_user_hint.set_label("Use " + err + ".")
                self.e_user_hint.add_css_class("err")
                ok = False
            else:
                self.e_user.remove_css_class("error")
                self.e_user_hint.remove_css_class("err")
                self.e_user_hint.set_label("Small letters and digits, like arthur.")
            if self.pw_fields.get_visible():
                p1, p2 = self.e_pw1.get_text(), self.e_pw2.get_text()
                if not p1:
                    self.pw_err.set_label("")
                    ok = False
                elif p2 and p1 != p2:
                    self.pw_err.set_label("The two passwords are not the same.")
                    self.pw_err.add_css_class("err")
                    self.pw_err.remove_css_class("ok")
                    ok = False
                elif not p2:
                    self.pw_err.set_label("")
                    ok = False
                else:
                    self.pw_err.set_label("✓  The passwords match.")
                    self.pw_err.add_css_class("ok")
                    self.pw_err.remove_css_class("err")
            elif self.s["shadow"] != True:  # noqa: E712  (still checking)
                ok = False
            self.pages["user"].next_btn.set_sensitive(ok)
            return ok

        def leave_user(self):
            if not self._validate_user():
                return False
            self.s["uname"] = self.e_user.get_text().strip()

        # ------------------------------------------------ summary
        def p_summary(self):
            p = self._card("Step 5 · Check", "Ready to install", None)
            p.content.set_spacing(10)
            nothing = box(False, 12)
            ic = Gtk.Image.new_from_icon_name("security-high-symbolic")
            ic.set_pixel_size(26)
            ic.add_css_class("gold")
            nothing.append(ic)
            nothing.append(lab("Nothing has been written yet.", "nothing"))
            p.content.append(nothing)
            self.sum_grid = Gtk.Grid(column_spacing=24, row_spacing=7, margin_top=4)
            ssw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, propagate_natural_height=True)
            ssw.add_css_class("plain")
            ssw.set_child(self.sum_grid)
            p.content.append(ssw)
            self.erase_box = box(spacing=8, cls="note red", margin_top=6)
            self.erase_text = lab("", "body")
            self.erase_box.append(self.erase_text)
            self.e_confirm = Gtk.Entry(activates_default=True)
            self.e_confirm.add_css_class("erase")
            a11y(self.e_confirm, "Type the disk name to confirm")
            self.e_confirm.connect("changed", lambda _e: self._sum_ready())
            self.erase_box.append(self.e_confirm)
            p.content.append(self.erase_box)
            self._nav(p, "Install now", self.start_install)
            p.first_focus = lambda: self.e_confirm if self.erase_box.get_visible() else p.next_btn
            return p

        def build_cfg(self, password=None):
            """The config main.quick() would build for the same answers (same keys, same values)."""
            o = self._target()
            t = dict(o["t"])
            cfg = {"mode": t["mode"], "disk": t.get("disk"), "fingerprint": True}
            old = t.get("os")
            if t["mode"] == "side-by-side":
                cfg.update(partition=t["partition"], esp=t["esp"], old_os_name=old["name"],
                           old_root_subdir=old.get("root_subdir", ""))
            elif t["mode"] == "free":
                cfg["esp"] = t.get("esp")
            cfg["os_name"] = self.s["os_name"]
            cfg["hostname"] = self.s["hostname"]
            from arclight.edition import has_ai
            cfg["ai"] = has_ai() and bool(getattr(self, "sw_ai", None) is None or self.sw_ai.get_active())
            cfg["eclipse_look"] = bool(getattr(self, "sw_look", None) is None or self.sw_look.get_active())
            migrate = {"enabled": False}
            if self._migrating():
                ou = self.s["old_user"]
                migrate = {"enabled": True, "old_user": ou, "from_home": ou["home"]}
            uname = self.s["uname"]
            user = {"name": uname, "autologin": True,
                    "full_name": (migrate.get("old_user", {}).get("gecos") or uname.title()).split(",")[0]}
            if migrate["enabled"] and self.pw_keep.get_active() and self.s["shadow"] is True:
                user["keep_old_password"] = True    # main.py --config reads the old hash (read-only), like quick()
            elif password is not None:
                user["password_hash"] = backend.hash_password(password)
            cfg["user"] = user
            cfg["timezone"] = (old or {}).get("timezone") or "America/New_York"
            cfg["locale"] = (old or {}).get("locale") or "en_US.UTF-8"
            cfg["keymap"] = (old or {}).get("keymap") or "us"
            online = bool(self.s["online"])
            if migrate["enabled"]:
                plan = json.loads(self.s["plan"].to_json())
                plan["target_home"] = f"/home/{uname}"
                migrate["plan"] = plan
                cfg["packages"] = {"from_old_system": True, "online": online}
            else:
                cfg["packages"] = {"from_old_system": False, "online": online}
            cfg["migrate"] = migrate
            if t["mode"] == "erase":
                cfg["confirm_disk"] = self.e_confirm.get_text().strip()
            return cfg

        def enter_summary(self):
            if self.s["online"] is None:
                def done(ok, _e):
                    self.s["online"] = bool(ok)
                    if self.stack.get_visible_child_name() == "summary":
                        self.enter_summary()
                in_thread(backend.online, done)
            g = self.sum_grid
            child = g.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                g.remove(child)
                child = nxt
            o = self._target()
            t = o["t"]
            old = t.get("os")
            if o["kind"] == "side":
                where = f"Next to {old['name']} on {t['partition']}. It stays untouched."
            elif o["kind"] == "free":
                where = f"Free space on {t['disk']}."
            else:
                where = f"Erase {t['disk']} and use all of it."
            mig = self._migrating()
            plan = self.s["plan"]
            files = (f"Yes, {self.s['old_user']['home']}: copy {gib(plan.total('copy'))}, share {gib(plan.total('share'))}, "
                     f"skip {gib(plan.total('skip'))}" if mig and plan else "No. A fresh desktop.")
            pw = ("Your old password" if (mig and self.pw_keep.get_active() and self.s["shadow"] is True)
                  else "The new one you typed")
            tz = (old or {}).get("timezone") or "America/New_York"
            loc = (old or {}).get("locale") or "en_US.UTF-8"
            km = (old or {}).get("keymap") or "us"
            onl = {None: "checking the internet…", True: "online", False: "offline"}[self.s["online"]]
            pk = "From this USB" + (f", plus your full app list from the old system ({onl})" if mig else "")
            rows = [("Where", where), ("System name", self.s["os_name"]), ("Computer name", self.s["hostname"]),
                    ("You", f"{self.s['uname']}, logs in automatically"), ("Password", pw),
                    ("Time and keyboard", f"{tz} · {loc} · keyboard {km}"), ("Your files", files), ("Apps", pk)]
            for i, (k, v) in enumerate(rows):
                g.attach(lab(k, "sum-key", valign=Gtk.Align.START), 0, i, 1, 1)
                vl = lab(v, "sum-val", hexpand=True)
                if k == "Where" and o["kind"] == "erase":
                    vl.add_css_class("bad")
                g.attach(vl, 1, i, 1, 1)
            p = self.pages["summary"]
            erase = o["kind"] == "erase"
            self.erase_box.set_visible(erase)
            nb = p.next_btn
            if erase:
                d = next((d for d in self.s["scan"].get("disks", []) if d["path"] == t["disk"]), {})
                self.erase_text.set_label(f"This ERASES {t['disk']} ({d.get('model') or 'disk'}, {gib(d.get('size', 0))}). "
                                          f"Everything on it is deleted. Type {t['disk']} below to confirm.")
                self.e_confirm.set_placeholder_text(t["disk"])
                nb.set_label(f"Erase {t['disk']} and install")
                nb.add_css_class("danger")
            else:
                self.e_confirm.set_text("")
                nb.set_label("Install now")
                nb.remove_css_class("danger")
            p.sub_label.set_visible(False)
            self._sum_ready()

        def _sum_ready(self):
            t = self._target()["t"]
            ok = self.s["online"] is not None
            if t["mode"] == "erase":
                ok = ok and self.e_confirm.get_text().strip() == t["disk"]
            self.pages["summary"].next_btn.set_sensitive(ok)

        # ------------------------------------------------ install
        def p_install(self):
            p = self._card("Step 6 · Install", f"Installing {self.default_name}",
                           "This takes a while. You can watch, or get a coffee.", deep=True)
            top = box(False, 16)
            self.i_spin = Gtk.Spinner(spinning=True, width_request=30, height_request=30, valign=Gtk.Align.CENTER)
            top.append(self.i_spin)
            tb = box(spacing=2, hexpand=True)
            self.i_stage = lab("Starting…", "stage-now")
            tb.append(self.i_stage)
            self.i_detail = lab("", "stage-detail", wrap=False, ellipsize=Pango.EllipsizeMode.END)
            tb.append(self.i_detail)
            top.append(tb)
            self.i_pct = lab("0%", "pct", wrap=False, valign=Gtk.Align.CENTER)
            top.append(self.i_pct)
            p.content.append(top)
            self.i_bar = Gtk.ProgressBar()
            self.i_bar.add_css_class("big")
            # the bar glides to each new value (eased on the real clock) instead of jumping
            self.i_ease = motion.EasedProgress(self.i_bar) if motion else None
            p.content.append(self.i_bar)
            self.install_note = lab("", "err")
            self.install_note.set_visible(False)
            p.content.append(self.install_note)
            self.i_steps = Gtk.Grid(column_spacing=28, row_spacing=3, column_homogeneous=True, margin_top=6)
            p.content.append(self.i_steps)
            self.i_exp = Gtk.Expander(label="Show the full log")
            self.i_exp.connect("notify::expanded", lambda e, _p: self.i_steps.set_visible(not e.get_expanded()))
            sw = Gtk.ScrolledWindow(min_content_height=150, vexpand=True)
            sw.add_css_class("logbox")
            self.i_log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                      left_margin=10, right_margin=10, top_margin=8, bottom_margin=8)
            self.i_log.add_css_class("logview")
            self.i_log.add_css_class("mono")
            sw.set_child(self.i_log)
            self.i_log_sw = sw
            self.i_exp.set_child(sw)
            p.content.append(self.i_exp)
            p.nav.set_visible(False)
            return p

        def _stage_text(self, st):
            old = (self._old() or {}).get("name") or "your old system"
            return STAGE_TEXT.get(st, st[:1].upper() + st[1:]).format(name=self.s["os_name"], old=old)

        def start_install(self):
            t = self._target()["t"]
            if t["mode"] == "erase" and self.e_confirm.get_text().strip() != t["disk"]:
                return
            pw = self.e_pw1.get_text() if self.pw_fields.get_visible() else None
            try:
                cfg = self.build_cfg(pw)
            except Exception as e:  # noqa: BLE001
                self._finish(False, f"could not prepare the install: {e}", [])
                return
            if backend.demo and cfg["migrate"].get("enabled"):
                cfg["migrate"]["_summary"] = self.s["plan"].summary()
            self.cfg = cfg
            self.stages = expected_stages(cfg)
            self.stage_state = {s: "todo" for s in self.stages}
            self.stage_rows = {}
            child = self.i_steps.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                self.i_steps.remove(child)
                child = nxt
            half = (len(self.stages) + 1) // 2
            for n, st in enumerate(self.stages):
                r = box(False, 8, cls="st-row")
                m = lab("○", "st-mark", wrap=False)
                r.append(m)
                r.append(lab(self._stage_text(st), None, wrap=False, ellipsize=Pango.EllipsizeMode.END, hexpand=True))
                r.mark = m
                self.i_steps.attach(r, n // half, n % half, 1, 1)
                self.stage_rows[st] = r
            self.i_log.get_buffer().set_text("")
            self.i_ease.jump(0) if self.i_ease else self.i_bar.set_fraction(0)
            self.i_pct.set_label("0%")
            self.i_stage.set_label("Starting…")
            self.i_detail.set_label("")
            self.i_spin.set_spinning(True)
            self.install_note.set_visible(False)
            self.cur_stage = None
            self.sub_frac = 0.0
            self.lines = []
            self.failed_msg = None
            self.not_changed_line = False
            rd = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
            fd, path = tempfile.mkstemp(prefix="arclight-install-", suffix=".json", dir=rd)
            with os.fdopen(fd, "w") as f:
                json.dump(cfg, f, indent=2)
            os.chmod(path, 0o600)
            self.cfg_path = path
            self.t0 = time.time()
            self.go("install")
            self.closeb.set_sensitive(False)
            try:
                proc = backend.install(path)
            except Exception as e:  # noqa: BLE001
                self._finish(False, str(e), [])
                return
            self.running = proc

            def reader():
                for line in proc.stdout:
                    GLib.idle_add(self._line, line.rstrip("\n"))
                rc = proc.wait()
                GLib.idle_add(self._ended, rc)
            threading.Thread(target=reader, daemon=True).start()

        def _progress(self):
            w = {s: STAGE_WEIGHT.get(s, 1) for s in self.stages}
            tot = sum(w.values())
            done = sum(w[s] for s in self.stages if self.stage_state[s] == "done")
            if self.cur_stage in w and self.stage_state.get(self.cur_stage) == "now":
                done += w[self.cur_stage] * min(self.sub_frac, 0.98)
            f = done / tot
            self.i_ease.set(f) if self.i_ease else self.i_bar.set_fraction(f)
            self.i_pct.set_label(f"{int(f * 100)}%")

        def _mark(self, st, state):
            self.stage_state[st] = state
            r = self.stage_rows.get(st)
            if not r:
                return
            for c in ("now", "done", "fail"):
                r.remove_css_class(c)
            if state != "todo":
                r.add_css_class(state)
            r.mark.set_label({"todo": "○", "now": "●", "done": "✓", "fail": "✗"}[state])

        def _line(self, line):
            self.lines.append(line)
            buf = self.i_log.get_buffer()
            buf.insert(buf.get_end_iter(), line + "\n")
            adj = self.i_log_sw.get_vadjustment()
            GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), False)[1])
            s = line.strip()
            if s.startswith("▸ "):
                st = s[2:].strip()
                if st not in self.stage_state:          # an unexpected stage: track it (not drawn in the list)
                    self.stages.append(st)
                    self.stage_state[st] = "todo"
                self.cur_stage = st
                self.sub_frac = 0.0
                self._mark(st, "now")
                self.i_stage.set_label(self._stage_text(st))
                self.i_detail.set_label("")
            elif s.startswith("✓ "):
                st = re.sub(r"\s*\([\d.]+s\)$", "", s[2:].strip())
                if st in self.stage_state:
                    self._mark(st, "done")
            elif s.startswith("✗"):
                self.failed_msg = re.sub(r"^✗\s*(FAILED:\s*)?", "", s)
                if self.cur_stage:
                    self._mark(self.cur_stage, "fail")
            elif s.startswith("Nothing changed on your existing system"):
                self.not_changed_line = True
            elif s and not s.startswith("=="):
                m = re.search(r"system copy (\d+)%", s)
                if m:
                    self.sub_frac = int(m.group(1)) / 100
                m = re.search(r"copy \[(\d+)/(\d+)\]", s)
                if m:
                    self.sub_frac = 0.85 * int(m.group(1)) / max(1, int(m.group(2)))
                if s.startswith("verifying every copied"):
                    self.sub_frac = 0.9
                self.i_detail.set_label(s)
            self._progress()
            return False

        def _ended(self, rc):
            self.running = None
            try:
                os.unlink(self.cfg_path)
            except OSError:
                pass
            rep = backend.report(self.t0)
            ok = rc == 0 and not self.failed_msg
            if ok:
                for st in self.stages:
                    if self.stage_state[st] != "done":
                        self._mark(st, "done")
                self.sub_frac = 1
                self.i_ease.set(1) if self.i_ease else self.i_bar.set_fraction(1)
                self.i_pct.set_label("100%")
                self._finish(True, None, self.lines, rep)
            else:
                err = self.failed_msg or (rep or {}).get("error")
                if not err:  # failed before the engine started (sudo, password hash, bad config)
                    tail = [l for l in self.lines if l.strip()]
                    err = tail[-1].strip() if tail else f"the installer stopped (exit {rc})"
                self._finish(False, err, self.lines, rep)
            return False

        def _finish(self, ok, err, lines, rep=None):
            self.running = None
            self.closeb.set_sensitive(True)
            self.i_spin.set_spinning(False)
            self.s["result"] = {"ok": ok, "error": err, "report": rep}
            d = self.pages["done"]
            mode = self.cfg["mode"] if hasattr(self, "cfg") else None
            started = [s for s, v in getattr(self, "stage_state", {}).items() if v != "todo"]
            any_stage = bool(started)
            for c in ("bad",):
                d.mark.remove_css_class(c)
            d.points_clear()
            if ok:
                d.kicker.set_label("DONE")
                d.title_label.set_label(f"{self.s['os_name']} is installed")
                d.sub_label.set_label("It is now the default. Your old system is still in the boot menu."
                                      if mode == "side-by-side" else "It is now the default when this PC starts.")
                d.mark.set_label("✓")
                text = "\n".join(lines)
                m = re.search(r"Old system verified unchanged \((\d+) files checked\)", text)
                if m or (rep or {}).get("old_system_untouched"):
                    n = int(m.group(1)) if m else rep.get("old_system_entries", 0)
                    d.point(f"Your old system was checked: unchanged ({n:,} files).", "ok")
                if self._migrating() and self.s["plan"]:
                    d.point(f"Your files came over: {gib(self.s['plan'].total('copy'))} copied and checked.", None)
                d.point("Take out the USB stick after the restart.", None)
                for w in (rep or {}).get("warnings", []):
                    d.point(f"Note: {w}", "dim")
                d.restart.set_visible(True)
                d.retry.set_visible(False)
                d.restart.grab_focus()
            else:
                d.kicker.set_label("STOPPED")
                d.mark.set_label("!")
                d.mark.add_css_class("bad")
                d.title_label.set_label("The install stopped")
                d.sub_label.set_label(plain_error(err))
                if mode == "erase" and "partition and format" in started:
                    d.point(f"The disk {self.cfg['disk']} was already erased. Nothing else was changed.", "bad")
                elif self.not_changed_line or not any_stage or mode != "erase":
                    d.point("Your old system was not changed.", "ok")
                d.point(f"Details: {err}", "dim")
                d.point(f"Full log: {LOG_PATH}", "dim")
                d.restart.set_visible(False)
                d.retry.set_visible(True)
                d.retry.grab_focus()
            d.log_buf.set_text("\n".join(lines))
            self.go("done")

        # ------------------------------------------------ done
        def p_done(self):
            p = self._card("Done", "", "")
            p.kicker = p.content.get_parent().get_first_child()
            row = box(False, 18)
            # a drawn glyph, not a theme icon: the live USB's icon theme does not have every symbolic icon
            p.mark = lab("✓", "big-mark", xalign=0.5, wrap=False, accessible_role=Gtk.AccessibleRole.PRESENTATION)
            p.mark.set_valign(Gtk.Align.START)
            # move the title + sub into a row next to the big mark
            t, s = p.title_label, p.sub_label
            inner = p.content.get_parent()
            inner.remove(t)
            inner.remove(s)
            tb = box(spacing=6, hexpand=True)
            tb.append(t)
            tb.append(s)
            row.append(p.mark)
            row.append(tb)
            inner.insert_child_after(row, p.kicker)
            s.set_visible(True)
            pts = box(spacing=8, margin_top=6)
            p.content.append(pts)

            def point(text, cls):
                r = box(False, 12)
                r.append(lab("●", "point-mark", wrap=False, accessible_role=Gtk.AccessibleRole.PRESENTATION))
                r.append(lab(text, ("body " + cls) if cls else "body"))
                pts.append(r)

            def clear():
                c = pts.get_first_child()
                while c:
                    n = c.get_next_sibling()
                    pts.remove(c)
                    c = n
            p.point, p.points_clear = point, clear
            ex = Gtk.Expander(label="Show the full log", vexpand=True)
            sw = Gtk.ScrolledWindow(min_content_height=120, vexpand=True)
            sw.add_css_class("logbox")
            tv = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                              left_margin=10, right_margin=10, top_margin=8, bottom_margin=8)
            tv.add_css_class("logview")
            tv.add_css_class("mono")
            sw.set_child(tv)
            ex.set_child(sw)
            p.log_buf = tv.get_buffer()
            p.content.append(ex)
            close = button("Close", "ghost", self.close)
            p.nav.append(close)
            p.nav.append(Gtk.Box(hexpand=True))
            p.retry = button("Try again", "primary", lambda: self.go("summary"))
            p.restart = button("Restart now", "primary", backend.reboot)
            p.nav.append(p.retry)
            p.nav.append(p.restart)
            p.first_focus = lambda: p.restart if p.restart.get_visible() else p.retry
            return p

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id=APP_ID)
            self.win = None

        def do_activate(self):
            if self.win:
                self.win.present()
                return
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            # always the Eclipse palette (the live USB has no user theme yet; a host theme must not recolour it)
            from string import Template
            pal = dict(glass.ECLIPSE)
            for k in list(pal):
                h = pal[k].lstrip("#")
                pal[k + "_rgb"] = ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))
            pal["noise"] = glass.asset_uri("glass-noise.png")
            data = Template(glass.COMMON + CSS.replace("MATERIAL", glass.MATERIAL)).safe_substitute(pal)
            if not pal["noise"]:
                data = data.replace('url(""), ', "")
            prov = Gtk.CssProvider()
            if hasattr(prov, "load_from_string"):
                prov.load_from_string(data)
            else:
                prov.load_from_data(data.encode())
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
            self.win = Win(self)
            self.win.present()

    app = App()
    main_gui.app = app
    return app


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--probe"]:
        return probe_main(argv[1:])
    if argv[:1] == ["--fake-engine"]:
        return fake_engine(argv[1])
    ap = argparse.ArgumentParser(prog="arclight-installer-gui", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="fake disks, plan and engine: nothing is touched, no root needed")
    a = ap.parse_args(argv)
    app = main_gui(demo=a.demo or os.environ.get("ARCLIGHT_INSTALLER_DEMO") == "1")
    return app.run([])
