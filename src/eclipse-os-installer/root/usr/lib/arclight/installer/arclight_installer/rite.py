"""rite: the advanced Eclipse OS (codename Arclight) install, done by hand and checked by machine.

  rite              where am I? (status of every stage)
  rite begin        start (or restart) the Rite
  rite guide [N]    read the guide for stage N (default: the current stage)
  rite check [N]    check stage N (default: the current stage); passing it unlocks the next
  rite hint         a hint for the first thing that is not right yet
  rite skip N       skip an optional stage (only 12, migration)
  rite auto       do the recommended commands of the current stage for you (F5 in the Rite shell)
  rite final        run inside the NEW system after the first boot: the last trial + your certificate

The guide is /usr/share/doc/arclight/INSTALL-GUIDE.md. Every stage ends with `rite check`.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

GUIDE = Path(os.environ.get("ARCLIGHT_GUIDE", "/usr/share/doc/arclight/INSTALL-GUIDE.md"))
STATE = Path(os.environ.get("RITE_STATE", "/run/arclight-rite/state.json"))
MNT = Path(os.environ.get("RITE_MNT", "/mnt"))
B, G, R, Y, W, D, N = ("\033[38;2;91;134;200m", "\033[38;2;63;214;154m", "\033[38;2;212;43;43m",
                       "\033[38;2;224;176;64m", "\033[1;38;2;242;245;255m", "\033[38;2;138;151;174m", "\033[0m")

STAGES = [
    (0, "Preparation", "UEFI mode, network, clock, keyboard"),
    (1, "Partitions", "GPT: an EFI system partition and a LUKS partition, made by hand"),
    (2, "Encryption", "LUKS2 with argon2id, opened as /dev/mapper/arclight"),
    (3, "Filesystems", "btrfs with five subvolumes, mounted with zstd compression"),
    (4, "Base system", "hand-picked packages, the OS core (eclipse-os-core) from the local repo"),
    (5, "Identity", "name the operating system and the machine; time, language, keyboard"),
    (6, "Kernel image", "systemd initramfs with sd-encrypt, built into a unified kernel image"),
    (7, "Secure Boot keys", "your own keys; the kernel image signed with them"),
    (8, "Boot entry", "a firmware boot entry for your signed image, first in the boot order"),
    (9, "Users and power", "your account, root, sudo, written and validated by hand"),
    (10, "The AI layer", "arclight group, daemon, uinput, polkit, MCP for Claude and Codex"),
    (11, "Desktop", "Hyprland, the Eclipse config and theme, login"),
    (12, "Migration", "bring your files over with a plan you wrote (optional)"),
    (13, "First boot", "reboot into it; `rite final` proves it works"),
]


def sh(cmd, check=False, timeout=60):
    try:
        p = subprocess.run(cmd if isinstance(cmd, list) else ["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def chroot(cmd):
    return sh(["arch-chroot", str(MNT), "bash", "-c", cmd], timeout=120)


def load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"done": [], "skipped": [], "started": None, "facts": {}}


def save(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2))
    # keep a copy inside the new system once it exists, so `rite final` can read it after reboot
    if (MNT / "etc").is_dir() and (MNT / "var/lib").is_dir():
        d = MNT / "var/lib/arclight"
        d.mkdir(parents=True, exist_ok=True)
        (d / "rite.json").write_text(json.dumps(st, indent=2))


def current(st):
    for n, _, _ in STAGES:
        if n not in st["done"] and n not in st["skipped"]:
            return n
    return None


# ---------------------------------------------------------------- checks
# each returns a list of (ok: bool, what: str, hint: str)

def c0(st):
    out = []
    plat = Path("/sys/firmware/efi/fw_platform_size")
    out.append((plat.exists() and plat.read_text().strip() == "64", "booted in 64-bit UEFI mode",
                "Reboot the USB in UEFI mode (firmware menu). The Rite needs UEFI."))
    rc, _ = sh("ping -c1 -W3 archlinux.org")
    out.append((rc == 0, "network reaches archlinux.org", "Connect with `nmtui` (Wi-Fi) or plug in a cable."))
    rc, t = sh("timedatectl show -p NTPSynchronized --value")
    out.append((t == "yes", "clock synchronised (NTP)", "Run `timedatectl set-ntp true` and wait a few seconds."))
    rc, k = sh("localectl status")
    out.append(("VC Keymap" in k, "keyboard layout set for the console", "Run `loadkeys us` (or your layout)."))
    return out


def _target_disk(st):
    return st["facts"].get("disk")


def c1(st):
    out = []
    # lsblk reads udev's database: right after sgdisk/mkfs (e.g. `rite auto` stage 1) it can still show the
    # old (empty) FSTYPE/PARTTYPE, and the check failed although the disk was right
    sh("udevadm settle --timeout=10")
    rc, lsblk = sh("lsblk -J -b -o PATH,TYPE,SIZE,PARTTYPE,FSTYPE,PKNAME")
    devs = json.loads(lsblk)["blockdevices"] if rc == 0 else []

    def walk(ds):
        for d in ds:
            yield d
            yield from walk(d.get("children") or [])
    allp = list(walk(devs))
    esp = [p for p in allp if p["type"] == "part" and (p.get("parttype") or "").lower() == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
           and p.get("fstype") == "vfat" and int(p["size"]) >= 512 * 1024 ** 2 and "arclight-live" not in (p.get("path") or "")]
    luks = [p for p in allp if p["type"] == "part" and (p.get("parttype") or "").lower() == "ca7d7ccb-63ed-4c53-861c-1742536059cc"]
    same = [(e, l) for e in esp for l in luks if e.get("pkname") == l.get("pkname")]
    out.append((bool(esp), "an EFI system partition (type EF00), FAT32, at least 512 MiB",
                "sgdisk -n 1:0:+1G -t 1:ef00 /dev/DISK, then mkfs.fat -F 32 /dev/DISK1"))
    out.append((bool(luks), "a partition with type 8309 (Linux LUKS)", "sgdisk -n 2:0:0 -t 2:8309 /dev/DISK"))
    out.append((bool(same), "both on the same GPT disk", "Put the ESP and the LUKS partition on the disk you install to."))
    if same:
        st["facts"].update(disk="/dev/" + same[0][0]["pkname"], esp=same[0][0]["path"], luks=same[0][1]["path"])
    return out


def c2(st):
    out = []
    dev = st["facts"].get("luks")
    rc, dump = sh(["cryptsetup", "luksDump", dev or "/dev/null"])
    out.append((rc == 0 and re.search(r"^Version:\s+2\s*$", dump, re.M) is not None,
                "LUKS version 2 on the 8309 partition", f"cryptsetup luksFormat --type luks2 --pbkdf argon2id {dev or '/dev/DISK2'}"))
    out.append(("argon2id" in dump, "key slot uses argon2id", "Re-run luksFormat with --pbkdf argon2id"))
    out.append((Path("/dev/mapper/arclight").exists(), "opened as /dev/mapper/arclight",
                f"cryptsetup open {dev or '/dev/DISK2'} arclight"))
    if rc == 0:
        m = re.search(r"UUID:\s+(\S+)", dump)
        if m:
            st["facts"]["luks_uuid"] = m.group(1)
    return out


def c3(st):
    out = []
    rc, fs = sh("blkid -o value -s TYPE /dev/mapper/arclight")
    out.append((fs == "btrfs", "btrfs on /dev/mapper/arclight", "mkfs.btrfs -L arclight /dev/mapper/arclight"))
    rc, subs = sh(f"btrfs subvolume list {MNT}")
    have = set(re.findall(r"path (\S+)", subs))
    for sv in ("@", "@home", "@snapshots", "@log", "@pkg"):
        out.append((sv in have, f"subvolume {sv}", f"btrfs subvolume create /mnt/{sv}  (with the top level mounted at /mnt)"))
    rc, fm = sh("findmnt -J -o TARGET,SOURCE,FSTYPE,OPTIONS")
    mounts = {m["target"]: m for m in json.loads(fm).get("filesystems", [])} if rc == 0 else {}
    flat = {}

    def walk(ms):
        for m in ms:
            flat[m["target"]] = m
            walk(m.get("children") or [])
    walk(json.loads(fm).get("filesystems", []) if rc == 0 else [])
    for target, sv in ((str(MNT), "@"), (f"{MNT}/home", "@home"), (f"{MNT}/.snapshots", "@snapshots"),
                       (f"{MNT}/var/log", "@log"), (f"{MNT}/var/cache/pacman/pkg", "@pkg")):
        m = flat.get(target)
        ok = bool(m) and f"subvol=/{sv}" in m["options"] and "compress=zstd" in m["options"]
        out.append((ok, f"{target} = {sv} with compress=zstd",
                    f"mount -o noatime,compress=zstd,subvol={sv} /dev/mapper/arclight {target}"))
    m = flat.get(f"{MNT}/efi")
    out.append((bool(m) and m["fstype"] == "vfat", f"{MNT}/efi = the EFI partition", f"mount --mkdir {st['facts'].get('esp', '/dev/DISK1')} /mnt/efi"))
    return out


def c4(st):
    out = []
    rc, q = chroot("pacman -Qq")
    pk = set(q.split()) if rc == 0 else set()
    out.append(("base" in pk, "base installed in /mnt", "pacstrap -K -C /etc/arclight-rite/pacman.conf /mnt base ..."))
    kernels = [k for k in ("linux", "linux-lts", "linux-zen", "linux-hardened") if k in pk]
    out.append((bool(kernels), "a kernel you picked (linux, linux-lts, linux-zen, ...)", "add one kernel to your pacstrap line"))
    out.append(("linux-firmware" in pk, "linux-firmware", "add linux-firmware"))
    out.append((bool({"amd-ucode", "intel-ucode"} & pk), "CPU microcode", "add amd-ucode (AMD) or intel-ucode (Intel)"))
    for p in ("btrfs-progs", "cryptsetup", "networkmanager", "sbctl", "eclipse-os-core"):
        out.append((p in pk, p, f"add {p}"))
    out.append((Path(MNT / "etc/fstab").exists() and "subvol=/@" in (MNT / "etc/fstab").read_text() if (MNT / "etc/fstab").exists() else False,
                "fstab generated (with the subvolumes)", "genfstab -U /mnt >> /mnt/etc/fstab"))
    if kernels:
        st["facts"]["kernel"] = kernels[0]
    return out


def c5(st):
    out = []
    idf = MNT / "etc/arclight/identity.json"
    name = None
    if idf.exists():
        try:
            name = json.loads(idf.read_text()).get("name")
        except ValueError:
            pass
    out.append((bool(name), "you named the operating system", 'arclight-identity --root /mnt --name "Your OS Name"'))
    osr = (MNT / "etc/os-release").read_text() if (MNT / "etc/os-release").exists() and not (MNT / "etc/os-release").is_symlink() else ""
    out.append((bool(name) and f'NAME="{name}"' in osr, "os-release carries that name", "re-run arclight-identity --root /mnt --name ..."))
    hn = (MNT / "etc/hostname").read_text().strip() if (MNT / "etc/hostname").exists() else ""
    out.append((bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", hn)), f"machine name set ({hn or 'none'})",
                "echo yourmachine > /mnt/etc/hostname"))
    lt = MNT / "etc/localtime"
    out.append((lt.is_symlink() and "zoneinfo" in os.readlink(lt), "timezone symlink", "arch-chroot /mnt ln -sf /usr/share/zoneinfo/Region/City /etc/localtime"))
    lc = (MNT / "etc/locale.conf").read_text() if (MNT / "etc/locale.conf").exists() else ""
    m = re.search(r"LANG=(\S+)", lc)
    gen_ok = False
    if m:
        rc, locs = chroot("locale -a")
        gen_ok = m.group(1).lower().replace("utf-8", "utf8") in locs.lower()
    out.append((bool(m) and gen_ok, "language set and generated (locale.conf + locale-gen)",
                "uncomment it in /mnt/etc/locale.gen, arch-chroot /mnt locale-gen, write LANG=... to /mnt/etc/locale.conf"))
    out.append(((MNT / "etc/vconsole.conf").exists() and "KEYMAP=" in (MNT / "etc/vconsole.conf").read_text(),
                "console keyboard (vconsole.conf)", "echo KEYMAP=us > /mnt/etc/vconsole.conf"))
    st["facts"].update(os_name=name, hostname=hn)
    return out


def c6(st):
    out = []
    conf = ""
    for f in [MNT / "etc/mkinitcpio.conf"] + sorted((MNT / "etc/mkinitcpio.conf.d").glob("*.conf")):
        if f.exists():
            conf += f.read_text() + "\n"
    hooks = re.findall(r"^HOOKS=\((.*)\)", conf, re.M)
    h = hooks[-1].split() if hooks else []
    for need in ("systemd", "sd-encrypt", "sd-vconsole", "block", "filesystems"):
        out.append((need in h, f"HOOKS has {need}", "edit HOOKS in /mnt/etc/mkinitcpio.conf (systemd-based, with sd-encrypt before filesystems)"))
    out.append(("sd-encrypt" in h and "filesystems" in h and h.index("sd-encrypt") < h.index("filesystems"),
                "sd-encrypt comes before filesystems", "order matters: ... block sd-encrypt filesystems fsck"))
    cl = (MNT / "etc/kernel/cmdline").read_text() if (MNT / "etc/kernel/cmdline").exists() else ""
    uuid = st["facts"].get("luks_uuid", "")
    out.append((f"rd.luks.name={uuid}=arclight" in cl, "kernel cmdline unlocks your LUKS partition (rd.luks.name=UUID=arclight)",
                f"echo 'rd.luks.name={uuid or 'UUID'}=arclight root=/dev/mapper/arclight rootflags=subvol=@ rw quiet' > /mnt/etc/kernel/cmdline"))
    out.append(("root=/dev/mapper/arclight" in cl and "subvol=@" in cl, "cmdline root= and rootflags=subvol=@", "see above"))
    uki = sorted((MNT / "efi/EFI/Linux").glob("*.efi"), key=lambda f: ("fallback" in f.name, f.name))
    out.append((bool(uki), "a unified kernel image in /efi/EFI/Linux/", "set default_uki in /mnt/etc/mkinitcpio.d/<kernel>.preset, then arch-chroot /mnt mkinitcpio -P"))
    if uki:
        st["facts"]["uki"] = "/" + str(uki[0].relative_to(MNT))
    return out


def c7(st):
    out = []
    keys = MNT / "var/lib/sbctl/keys/db/db.key"
    out.append((keys.exists(), "your own Secure Boot keys (sbctl create-keys)", "arch-chroot /mnt sbctl create-keys"))
    uki = st["facts"].get("uki")
    signed = False
    if uki:
        rc, v = chroot(f"sbctl verify {uki} 2>&1")
        signed = rc == 0 and "is signed" in v
    out.append((signed, "the kernel image is signed with them", f"arch-chroot /mnt sbctl sign -s {uki or '/efi/EFI/Linux/arclight-linux.efi'}"))
    rc, enrolled = chroot("sbctl status 2>&1")
    st["facts"]["sb_enrolled"] = "Secure Boot:\t✓ Enabled" in enrolled or "Installed:\t✓" in enrolled
    return out


def c8(st):
    out = []
    rc, eb = sh("efibootmgr -v")
    uki = (st["facts"].get("uki") or "").replace("/efi", "").replace("/", "\\")
    entries = re.findall(r"^Boot(\w{4})\*? (.+?)\t(.*)$", eb, re.M) or re.findall(r"^Boot(\w{4})\*? (.+?)\s{2,}(.*)$", eb, re.M)
    mine = [e for e in entries if uki and uki.lower() in e[2].lower().replace("/", "\\")] if uki else []
    out.append((bool(mine), "a firmware boot entry that loads your kernel image directly",
                f"efibootmgr --create --disk {st['facts'].get('disk', '/dev/DISK')} --part 1 --label \"{st['facts'].get('os_name') or 'Eclipse OS'}\" --loader '{uki or '\\\\EFI\\\\Linux\\\\arclight-linux.efi'}' --unicode"))
    m = re.search(r"BootOrder: (\S+)", eb)
    first = m.group(1).split(",")[0] if m else ""
    out.append((bool(mine) and first == mine[0][0], "it is first in the boot order", "efibootmgr -o XXXX,... (your entry first)"))
    return out


def c9(st):
    out = []
    rc, pw = chroot("awk -F: '$3>=1000 && $3<60000 {print $1}' /etc/passwd")
    users = pw.split()
    out.append((bool(users), "a regular user account", "arch-chroot /mnt useradd -m -G wheel NAME"))
    has_pw = False
    if users:
        rc, sp = chroot(f"getent shadow {users[0]}")
        has_pw = rc == 0 and len(sp.split(":")[1]) > 10
    out.append((has_pw, "the user has a password", f"arch-chroot /mnt passwd {users[0] if users else 'NAME'}"))
    rc, rs = chroot("getent shadow root")
    root_field = rs.split(":")[1] if ":" in rs else ""
    out.append((root_field.startswith(("!", "*")) or len(root_field) > 10, "root is either locked or has a password",
                "arch-chroot /mnt passwd -l root   (or set one with passwd)"))
    sud = list((MNT / "etc/sudoers.d").glob("*")) if (MNT / "etc/sudoers.d").exists() else []
    rc, vis = chroot("visudo -c")
    out.append((rc == 0 and bool(sud), "a sudo rule you wrote, and visudo -c says it is valid",
                "write /mnt/etc/sudoers.d/10-wheel by hand, then arch-chroot /mnt visudo -c"))
    if users:
        st["facts"]["user"] = users[0]
    return out


def c10(st):
    out = []
    u = st["facts"].get("user", "")
    rc, g = chroot("getent group arclight")
    out.append((rc == 0 and bool(g), "group arclight exists (systemd-sysusers)", "arch-chroot /mnt systemd-sysusers"))
    out.append((bool(u) and u in g.split(":")[-1].split(","), f"{u or 'your user'} is in group arclight", f"arch-chroot /mnt gpasswd -a {u or 'NAME'} arclight"))
    rc, en = chroot("systemctl is-enabled arclightd.service")
    out.append((en.strip() == "enabled", "arclightd enabled", "arch-chroot /mnt systemctl enable arclightd"))
    out.append(((MNT / "usr/lib/udev/rules.d/70-arclight-uinput.rules").exists() and (MNT / "usr/lib/modules-load.d/arclight.conf").exists(),
                "uinput access for the AI's virtual keyboard and mouse", "reinstall eclipse-os-core"))
    out.append(((MNT / "usr/share/polkit-1/actions/dev.arclight.admin.policy").exists(),
                "polkit action: the root daemon asks for your password", "reinstall eclipse-os-core"))
    home = MNT / "home" / u if u else None
    cj = {}
    try:
        cj = json.loads((home / ".claude.json").read_text()) if home else {}
    except (OSError, ValueError):
        pass
    out.append(("arclight" in (cj.get("mcpServers") or {}), "Claude Code knows the arclight MCP server (~/.claude.json)",
                f"arch-chroot /mnt runuser -u {u or 'NAME'} -- arclight-firstrun --home /home/{u or 'NAME'} --offline --force"))
    cc = (home / ".codex/config.toml").read_text() if home and (home / ".codex/config.toml").exists() else ""
    out.append(("[mcp_servers.arclight]" in cc, "Codex knows it too (~/.codex/config.toml)", "same command as above"))
    return out


def c11(st):
    out = []
    u = st["facts"].get("user", "")
    home = MNT / "home" / u if u else MNT / "nonexistent"
    rc, q = chroot("pacman -Qq")
    pk = set(q.split())
    out.append(("eclipse-os-desktop" in pk and "hyprland" in pk, "eclipse-os-desktop + hyprland installed", "arch-chroot /mnt pacman -S eclipse-os-desktop"))
    hl = home / ".config/hypr/hyprland.lua"
    out.append((hl.exists() and "arclight:begin" in hl.read_text() if hl.exists() else False,
                "the Hyprland config with the arclight block", "copy /usr/share/arclight/skel into the home (useradd -k does it)"))
    cur = home / ".config/theme/current"
    out.append((cur.exists() and cur.read_text().strip() != "", "a theme applied (~/.config/theme/current)",
                f"arch-chroot /mnt runuser -u {u} -- theme-apply eclipse"))
    bp = home / ".bash_profile"
    al = MNT / "etc/systemd/system/getty@tty1.service.d"
    out.append((bp.exists() and "start-hyprland" in bp.read_text(), "logging in on tty1 starts Hyprland (~/.bash_profile)",
                "the skel .bash_profile does this"))
    out.append((al.exists() or (MNT / "etc/systemd/system/display-manager.service").exists(), "a login path: tty1 autologin or a display manager",
                "write /mnt/etc/systemd/system/getty@tty1.service.d/autologin.conf (see the guide)"))
    rc, nm = chroot("systemctl is-enabled NetworkManager")
    out.append((nm.strip() == "enabled", "NetworkManager enabled", "arch-chroot /mnt systemctl enable NetworkManager"))
    return out


def c12(st):
    rep = MNT / "var/lib/arclight/migration-report.json"
    ok = False
    if rep.exists():
        try:
            ok = json.loads(rep.read_text()).get("verified") is True
        except ValueError:
            pass
    return [(ok, "migration copied AND verified (arclight-migrate copy ... --verify)", "or `rite skip 12` if you start fresh")]


def c13(st):
    return [(False, "reboot into the new system, log in, and run `rite final` there", "systemctl reboot")]


CHECKS = {0: c0, 1: c1, 2: c2, 3: c3, 4: c4, 5: c5, 6: c6, 7: c7, 8: c8, 9: c9, 10: c10, 11: c11, 12: c12, 13: c13}


# ---------------------------------------------------------------- final trial (inside the new system)

def final():
    st = load() if STATE.exists() else json.loads(Path("/var/lib/arclight/rite.json").read_text()) if Path("/var/lib/arclight/rite.json").exists() else {"facts": {}, "done": []}
    res = []
    rc, cmd = sh("cat /proc/cmdline")
    res.append(("rd.luks.name" in cmd or Path("/dev/mapper/arclight").exists(), "the root filesystem is encrypted (LUKS)"))
    rc, fm = sh("findmnt -no FSTYPE,OPTIONS /")
    res.append(("btrfs" in fm and "subvol=/@" in fm, "root is the btrfs subvolume @"))
    res.append((Path("/sys/firmware/efi").exists(), "booted through UEFI from your own boot entry"))
    rc, sb = sh("sbctl status 2>&1")
    print(f"  {D}Secure Boot: {'enabled with your keys' if 'Enabled' in sb else 'keys made and kernel signed; enrol them in the firmware to enforce'}{N}")
    rc, s = sh(["arc", "--json", "info"])
    res.append((rc == 0, "arc talks to arclightd (root API)"))
    rc, s2 = sh("arc --json settings get appearance.theme")
    res.append((rc == 0, "arc talks to arclight-session (the desktop API)"))
    rc, w = sh("arc --json win list")
    res.append((rc == 0 and w.strip().startswith("["), "the AI can see the windows of your Hyprland session"))
    rc, osr = sh(". /etc/os-release; echo $NAME")
    name = osr.strip()
    res.append((bool(name), f"your operating system is called {name}"))
    allok = all(ok for ok, _ in res)
    for ok, what in res:
        print(f"  {G + '✓' if ok else R + '✗'}{N} {what}")
    if not allok:
        print(f"\n{Y}Not yet. Fix the ✗ lines (the guide's Troubleshooting section helps) and run rite final again.{N}")
        return 1
    started = st.get("started")
    took = f"{(time.time() - started) / 3600:.1f} hours" if started else "an unknown time"
    host = Path("/etc/hostname").read_text().strip()
    print(f"""
{B}  ╔══════════════════════════════════════════════════════════════╗
  ║{N}{W}                     THE RITE IS COMPLETE                     {B}║
  ╠══════════════════════════════════════════════════════════════╣{N}
{B}  ║{N}   Operating system : {W}{name:<40}{N}{B}║
  ║{N}   Machine          : {W}{host:<40}{N}{B}║
  ║{N}   Built by hand in : {W}{took:<40}{N}{B}║
  ║{N}   Encrypted, signed, AI-wired. Every layer placed by you.     {B}║
  ╚══════════════════════════════════════════════════════════════╝{N}
""")
    cert = f"{name} on {host}, Rite completed {time.ctime()}, took {took}\n"
    for d in (Path.home() / ".local/share/arclight", Path("/var/lib/arclight")):
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / "rite-certificate.txt").write_text(cert)
        except OSError:
            pass
    return 0


# ---------------------------------------------------------------- CLI

def show_status(st):
    cur = current(st)
    print(f"\n{B}  ● the Rite{N}  {D}(advanced Eclipse OS install){N}\n")
    for n, title, desc in STAGES:
        mark = f"{G}✓{N}" if n in st["done"] else f"{D}–{N}" if n in st["skipped"] else f"{B}▶{N}" if n == cur else f"{D}·{N}"
        col = W if n == cur else (N if n in st["done"] else D)
        print(f"  {mark} {col}{n:>2}  {title:<18}{N} {D}{desc}{N}")
    if cur is not None:
        print(f"\n  Now: stage {cur}. Read it with {W}rite guide{N}, do it, then {W}rite check{N}.\n")
    else:
        print(f"\n  {G}All stages done.{N}\n")


def guide(n):
    if not GUIDE.exists():
        print(f"guide not found at {GUIDE}")
        return 1
    text = GUIDE.read_text()
    m = re.search(rf"^## Stage {n}\b.*?(?=^## Stage \d|^## Troubleshooting|\Z)", text, re.M | re.S)
    part = m.group(0) if m else text
    if shutil.which("glow") and sys.stdout.isatty():
        p = subprocess.run(["glow", "-s", "dark", "-w", "100", "-"], input=part, text=True)
        return p.returncode
    pager = shutil.which("less")
    if pager and sys.stdout.isatty():
        subprocess.run([pager, "-R"], input=part, text=True)
    else:
        print(part)
    return 0


def check(st, n):
    if n is None:
        print("all stages are done")
        return 0
    if n > 0 and any(k not in st["done"] and k not in st["skipped"] for k in range(n)):
        first = next(k for k in range(n) if k not in st["done"] and k not in st["skipped"])
        print(f"{Y}Stage {first} is not done yet. The Rite goes in order.{N}")
        return 1
    title = STAGES[n][1]
    print(f"\n{B}  Stage {n}: {title}{N}")
    results = CHECKS[n](st)
    for ok, what, hint in results:
        print(f"  {G + '✓' if ok else R + '✗'}{N} {what}")
    if all(ok for ok, _, _ in results):
        if n not in st["done"]:
            st["done"].append(n)
        save(st)
        nxt = current(st)
        print(f"\n  {G}Stage {n} passed.{N}" + (f" Next: stage {nxt}, {STAGES[nxt][1]}. {W}rite guide{N}" if nxt is not None else ""))
        return 0
    save(st)
    first = next((h for ok, _, h in results if not ok), "")
    print(f"\n  {Y}Not yet.{N} Hint: {first}")
    return 1


def begin():
    st = load()
    if not st.get("started"):
        st["started"] = time.time()
    save(st)
    print(f"""
{B}  ▲ the Rite{N}

  {W}This is the hard way.{N} You build the whole system yourself: partitions, encryption,
  filesystems, a signed kernel image, the boot entry, your account, the AI layer and the desktop.
  Nothing is done for you. Every stage is checked by `rite check` before you can go on.

  Open the guide in a second console (Alt+F2, log in as root / arclight) with {W}rite guide{N},
  or read it on another screen: /usr/share/doc/arclight/INSTALL-GUIDE.md

  Your disks are not touched by the Rite itself. Only the commands you type change anything.
""")
    print(f"  {W}Want a hand?{N} Press {W}F5{N} (or type {W}rite auto{N}) at any stage: the recommended commands are\n"
          f"  shown and run for you after Enter, then checked. You only answer the real choices.\n")
    show_status(st)
    if sys.stdin.isatty():
        rc = Path("/run/arclight-rite/bashrc")
        rc.parent.mkdir(parents=True, exist_ok=True)
        rc.write_text('PS1="rite \\w # "\n'
                      "# F5: do the recommended commands of the current stage (shown first, Enter to run)\n"
                      "bind -x '\"\\e[15~\": rite auto'\n"
                      "alias auto='rite auto'\n")
        os.execvp("bash", ["bash", "--rcfile", str(rc), "-i"])
    return 0


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    st = load()
    cmd = a[0] if a else "status"
    try:
        if cmd == "status":
            show_status(st)
        elif cmd == "begin":
            return begin()
        elif cmd == "guide":
            return guide(int(a[1]) if len(a) > 1 else (current(st) or 0))
        elif cmd == "check":
            return check(st, int(a[1]) if len(a) > 1 else current(st))
        elif cmd == "hint":
            n = current(st)
            res = CHECKS[n](st) if n is not None else []
            h = next((f"{what}: {hint}" for ok, what, hint in res if not ok), "nothing to fix in this stage; run rite check")
            print(h)
        elif cmd == "skip":
            n = int(a[1])
            if n != 12:
                print("only stage 12 (migration) is optional")
                return 1
            st["skipped"].append(n)
            save(st)
            show_status(st)
        elif cmd == "final":
            return final()
        elif cmd == "auto":
            from . import rite_auto
            return rite_auto.main(a[1:])
        else:
            print(__doc__)
    except KeyboardInterrupt:
        return 130
    return 0
