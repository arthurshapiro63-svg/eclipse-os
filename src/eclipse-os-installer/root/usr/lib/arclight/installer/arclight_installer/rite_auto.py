"""`rite auto` (F5 in the Rite shell): do the RECOMMENDED commands of the current stage for you.

The Rite stays the Rite: every command is shown first and runs only after Enter, and `rite check` still
proves each stage. Only real decisions are asked (which disk, passphrase, names, your account); everything
else uses the guide's recommended values. Secrets are never printed and never written to disk.
"""
import getpass
import json
import os
import re
import shlex
import subprocess
import sys

from . import rite

B, W, G, Y, R, D, N = rite.B, rite.W, rite.G, rite.Y, rite.R, rite.D, rite.N
SECRET = {}   # this process only


def ask(prompt, default=""):
    try:
        v = input(f"  {W}{prompt}{N}" + (f" [{default}]" if default else "") + ": ").strip()
    except EOFError:
        v = ""
    return v or default


def ask_secret(prompt, what):
    if what in SECRET:
        return SECRET[what]
    env = os.environ.get({"luks": "RITE_LUKS", "user": "RITE_USER"}[what])
    if env and not sys.stdin.isatty():  # scripted runs (tests); a person always types it
        SECRET[what] = env
        return env
    while True:
        a = getpass.getpass(f"  {W}{prompt}{N}: ")
        b = getpass.getpass(f"  {W}Again{N}: ")
        if a and a == b:
            SECRET[what] = a
            return a
        print(f"  {R}They don't match (or are empty). Try again.{N}")


def part(disk, n):
    return f"{disk}p{n}" if re.search(r"\d$", disk) else f"{disk}{n}"


def disks():
    out = subprocess.run(["lsblk", "-dnpo", "NAME,SIZE,MODEL,TYPE,RM"], capture_output=True, text=True).stdout
    live = subprocess.run(["findmnt", "-no", "SOURCE", "/run/archiso/bootmnt"], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 2 and f[-2] == "disk" and not (live and live.strip().startswith(f[0])):
            rows.append((f[0], line))
    return rows


def ucode():
    cpu = open("/proc/cpuinfo").read()
    return "amd-ucode" if "AuthenticAMD" in cpu else "intel-ucode"


def facts(st):
    return st.setdefault("facts", {})


def plan(n, st):
    """(commands, notes) for stage n. Commands are shell lines; $VARS come from the environment we pass."""
    f = facts(st)
    if n == 0:
        return ["loadkeys us", "timedatectl set-ntp true",
                "for i in $(seq 30); do [ \"$(timedatectl show -p NTPSynchronized --value)\" = yes ] && break; sleep 1; done"], []
    if n == 1:
        if not f.get("disk"):
            rows = disks()
            if not rows:
                raise SystemExit(f"  {R}No disk found to install on.{N}")
            print(f"\n  {W}Disks:{N}")
            for i, (name, line) in enumerate(rows, 1):
                print(f"   {i}) {line}")
            pick = ask("Which disk? (number)", "1")
            try:
                disk = rows[int(pick) - 1][0]
            except (ValueError, IndexError):
                raise SystemExit("  no such disk")
            print(f"\n  {R}Everything on {disk} will be erased.{N}")
            if ask(f"Type the disk name to confirm ({disk})") != disk:
                raise SystemExit("  not confirmed; nothing was done")
            f["disk"] = disk
            rite.save(st)
        d = f["disk"]
        return [f"sgdisk --zap-all {d}", f"sgdisk -n 1:0:+1G -t 1:ef00 -c 1:EFI {d}",
                f"sgdisk -n 2:0:0 -t 2:8309 -c 2:cryptroot {d}", f"partprobe {d}", "sleep 1",
                f"mkfs.fat -F 32 -n EFI {part(d, 1)}"], [f"erases {d}"]
    d = f.get("disk") or "/dev/DISK"
    esp, crypt = part(d, 1), part(d, 2)
    if n == 2:
        ask_secret("Disk passphrase (you type it at every start)", "luks")
        return [f'printf %s "$RITE_LUKS" | cryptsetup luksFormat --batch-mode --type luks2 --pbkdf argon2id '
                f'--cipher aes-xts-plain64 --key-size 512 {crypt} -d -',
                f'printf %s "$RITE_LUKS" | cryptsetup open {crypt} arclight -d -'], ["passphrase hidden"]
    if n == 3:
        o = "noatime,compress=zstd:1,space_cache=v2"
        return ["mkfs.btrfs -f -L arclight /dev/mapper/arclight", "mount /dev/mapper/arclight /mnt",
                "for sv in @ @home @snapshots @log @pkg; do btrfs subvolume create /mnt/$sv; done", "umount /mnt",
                f"mount -o {o},subvol=@ /dev/mapper/arclight /mnt",
                f"mount --mkdir -o {o},subvol=@home /dev/mapper/arclight /mnt/home",
                f"mount --mkdir -o {o},subvol=@snapshots /dev/mapper/arclight /mnt/.snapshots",
                f"mount --mkdir -o {o},subvol=@log /dev/mapper/arclight /mnt/var/log",
                f"mount --mkdir -o {o},subvol=@pkg /dev/mapper/arclight /mnt/var/cache/pacman/pkg",
                f"mount --mkdir {esp} /mnt/efi"], []
    if n == 4:
        return [f"pacstrap -K -C /etc/arclight-rite/pacman.conf /mnt base linux linux-firmware {ucode()} btrfs-progs "
                "cryptsetup networkmanager sbctl efibootmgr sudo vim man-db eclipse-os-core",
                "genfstab -U /mnt >> /mnt/etc/fstab"], []
    if n == 5:
        if "os_name" not in f:
            f["os_name"] = ask("Name of your operating system", "Eclipse OS")
            f["hostname"] = re.sub(r"[^a-z0-9-]", "", ask("Name of this machine", "eclipse").lower()) or "eclipse"
            tz = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"], capture_output=True,
                                text=True).stdout.strip()
            f["timezone"] = ask("Time zone", tz if tz and tz != "UTC" else "America/New_York")
            rite.save(st)
        return [f"arclight-identity --root /mnt --name {shlex.quote(f['os_name'])}",
                f"echo {shlex.quote(f['hostname'])} > /mnt/etc/hostname",
                f"arch-chroot /mnt ln -sf /usr/share/zoneinfo/{f['timezone']} /etc/localtime",
                "arch-chroot /mnt hwclock --systohc",
                "sed -i 's/^#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /mnt/etc/locale.gen",
                "arch-chroot /mnt locale-gen", "echo LANG=en_US.UTF-8 > /mnt/etc/locale.conf",
                "echo KEYMAP=us > /mnt/etc/vconsole.conf"], []
    if n == 6:
        return ["sed -i 's/^HOOKS=.*/HOOKS=(base systemd autodetect microcode modconf kms keyboard sd-vconsole "
                "block sd-encrypt filesystems fsck)/' /mnt/etc/mkinitcpio.conf",
                "mkdir -p /mnt/etc/kernel /mnt/efi/EFI/Linux",
                f'echo "rd.luks.name=$(cryptsetup luksUUID {crypt})=arclight root=/dev/mapper/arclight '
                f'rootflags=subvol=@ rw quiet loglevel=3" > /mnt/etc/kernel/cmdline',
                "printf '%s\\n' 'ALL_kver=\"/boot/vmlinuz-linux\"' \"PRESETS=('default' 'fallback')\" "
                "'default_uki=\"/efi/EFI/Linux/arclight-linux.efi\"' "
                "'fallback_uki=\"/efi/EFI/Linux/arclight-linux-fallback.efi\"' "
                "'fallback_options=\"-S autodetect\"' > /mnt/etc/mkinitcpio.d/linux.preset",
                "arch-chroot /mnt mkinitcpio -P"], []
    if n == 7:
        return ["arch-chroot /mnt sbctl create-keys",
                "arch-chroot /mnt sbctl sign -s /efi/EFI/Linux/arclight-linux.efi",
                "arch-chroot /mnt sbctl sign -s /efi/EFI/Linux/arclight-linux-fallback.efi"], []
    if n == 8:
        label = f.get("os_name") or "Eclipse OS"
        return [f"efibootmgr --create --disk {d} --part 1 --label {shlex.quote(label)} "
                "--loader '\\EFI\\Linux\\arclight-linux.efi'"], []
    if n == 9:
        if "user" not in f:
            f["user"] = re.sub(r"[^a-z0-9_-]", "", ask("Your user name", "arthur").lower()) or "arthur"
            rite.save(st)
        ask_secret(f"Password for {f['user']}", "user")
        u = f["user"]
        return [f"arch-chroot /mnt useradd -m -G wheel -s /bin/bash {u}",
                f'printf "%s:%s" {u} "$RITE_USER" | arch-chroot /mnt chpasswd',
                "arch-chroot /mnt passwd -l root",
                "echo '%wheel ALL=(ALL:ALL) ALL' > /mnt/etc/sudoers.d/10-wheel",
                "chmod 440 /mnt/etc/sudoers.d/10-wheel", "arch-chroot /mnt visudo -c"], ["password hidden"]
    u = f.get("user", "arthur")
    if n == 10:
        return ["arch-chroot /mnt systemd-sysusers", f"arch-chroot /mnt gpasswd -a {u} arclight",
                "arch-chroot /mnt systemctl enable arclightd",
                # the edition of this USB (core = no built-in AI) and its launcher entries
                "mkdir -p /mnt/etc/arclight && cp /etc/arclight/edition /mnt/etc/arclight/edition 2>/dev/null; "
                "if [ -d /usr/local/share/applications ]; then mkdir -p /mnt/usr/local/share/applications && "
                "cp -a /usr/local/share/applications/. /mnt/usr/local/share/applications/; fi; true",
                f"arch-chroot /mnt runuser -u {u} -- bash -c 'echo \"{{\\\"mcpServers\\\": {{\\\"arclight\\\": "
                f"{{\\\"type\\\": \\\"stdio\\\", \\\"command\\\": \\\"arclight-mcp\\\", \\\"args\\\": []}}}}}}\" "
                f"> ~/.claude.json'",
                f"arch-chroot /mnt runuser -u {u} -- bash -c 'mkdir -p ~/.codex && printf \"[mcp_servers.arclight]\\ncommand"
                f" = \\\"arclight-mcp\\\"\\n\" >> ~/.codex/config.toml'"], []
    if n == 11:
        return ["pacstrap -C /etc/arclight-rite/pacman.conf /mnt eclipse-os-desktop eclipse-os-installer mesa vulkan-radeon "
                "bluez bluez-utils",
                f"arch-chroot /mnt bash -c 'cp -aT /usr/share/arclight/skel /home/{u} && chown -R {u}:{u} /home/{u}'",
                f"arch-chroot /mnt runuser -u {u} -- arclight-firstrun --home /home/{u} --offline --force",
                "mkdir -p /mnt/etc/systemd/system/getty@tty1.service.d",
                "cat > /mnt/etc/systemd/system/getty@tty1.service.d/autologin.conf <<'EOF'\n[Service]\nExecStart=\n"
                f"ExecStart=-/sbin/agetty -o '-p -f -- \\\\u' --noreset --noclear --autologin {u} - ${{TERM}}\nEOF",
                "arch-chroot /mnt systemctl enable NetworkManager bluetooth",
                # the eclipse boot animation, with the glass passphrase box (kernel image rebuilt + re-signed)
                "sed -i 's/^HOOKS=(base systemd /HOOKS=(base systemd plymouth /' /mnt/etc/mkinitcpio.conf",
                "grep -q splash /mnt/etc/kernel/cmdline || sed -i 's/$/ splash/' /mnt/etc/kernel/cmdline",
                "printf '[Daemon]\\nTheme=eclipse\\nShowDelay=0\\n' > /mnt/etc/plymouth/plymouthd.conf",
                "arch-chroot /mnt mkinitcpio -P",
                "arch-chroot /mnt sbctl sign -s /efi/EFI/Linux/arclight-linux.efi",
                "arch-chroot /mnt sbctl sign -s /efi/EFI/Linux/arclight-linux-fallback.efi"], ["adds the eclipse boot animation"]
    if n == 12:
        return ["rite skip 12"], ["recommended: skip here, bring files later with arclight-migrate or the Drive backup"]
    if n == 13:
        return ["cp /run/arclight-rite/state.json /mnt/var/lib/arclight/rite.json", "umount -R /mnt",
                "cryptsetup close arclight"], ["then reboot and run `rite final`"]
    return [], []


def show(cmds):
    for c in cmds:
        print(f"    {D}#{N} {c}")


def run_stage(st, n, yes=False):
    title = rite.STAGES[n][1]
    print(f"\n{B}  Stage {n}: {title}{N}  {D}(recommended){N}")
    cmds, notes = plan(n, st)
    show(cmds)
    for x in notes:
        print(f"    {Y}{x}{N}")
    if not yes and ask("Press Enter to run them, or type n to stop", "y").lower() not in ("y", "yes"):
        print("  stopped; nothing was run")
        return 1
    env = {**os.environ, "RITE_LUKS": SECRET.get("luks", ""), "RITE_USER": SECRET.get("user", "")}
    for c in cmds:
        print(f"  {G}${N} {c}")
        r = subprocess.run(["bash", "-c", c], env=env)
        if r.returncode != 0:
            print(f"  {R}That command failed (exit {r.returncode}). Fix it by hand, then F5 again or `rite check`.{N}")
            return r.returncode
    if n == 12:  # skipped on purpose; the check is for a migration you did yourself
        return 0
    if n == 13:
        print(f"\n  {G}Ready.{N} Take out the USB, reboot, then run {W}rite final{N} in your new system.")
        return 0
    return rite.check(rite.load(), n)


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    st = rite.load()
    every = a and a[0] == "all"
    while True:
        n = rite.current(st)
        if n is None:
            print(f"\n  {G}All stages passed.{N} Reboot, then run {W}rite final{N}.")
            return 0
        rc = run_stage(st, n)
        st = rite.load()
        if rc != 0 or not every or n == 13:  # stage 13 passes only after the reboot (`rite final`)
            return rc
