# Eclipse OS: the Rite (advanced install guide)

This is the hard way to install Eclipse OS (codename Arclight). You build every layer yourself:
partitions, encryption, filesystems, a signed kernel image, the boot entry,
your account, the AI layer and the desktop. It is harder than a normal Arch
install on purpose.

The `rite` tool checks your work. Each stage ends with `rite check`. You only
move on when the check passes.

**Quick install instead?** Run `arclight-install` and pick **Quick**.

---

## How to use this guide

- Do the stages in order: 0, 1, 2 ... 13.
- Type every command exactly. Lines starting with `#` are comments.
- Words in CAPITALS like `DISK` are **variables**. You set them once, in stage 1.
- If a check fails, run `rite hint`. It tells you the first thing that is wrong.
- To read one stage on screen: `rite guide 5` (stage 5). To see where you are: `rite`.
- Keep a second console open for this guide: press **Alt+F2**, log in as `root`
  (password `arclight`), and run `rite guide`. Switch back with **Alt+F1**.

> **Warning.** Stage 1 erases the disk you choose. Back up first. If you want to
> keep your old system, use the Quick install's side-by-side mode instead.

### Contents

| Stage | What you do |
|---|---|
| 0 | Preparation: UEFI, network, clock, keyboard |
| 1 | Partitions (GPT, EFI + LUKS) |
| 2 | Encryption (LUKS2, argon2id) |
| 3 | Filesystems (btrfs, five subvolumes, zstd) |
| 4 | Base system (pick every package) |
| 5 | **Identity: name your operating system and your machine** |
| 6 | Kernel image (systemd initramfs + unified kernel image) |
| 7 | Secure Boot keys (your own, sign the kernel) |
| 8 | Boot entry (firmware boots your signed image) |
| 9 | Users and power |
| 10 | The AI layer |
| 11 | Desktop |
| 12 | Migration (optional) |
| 13 | First boot and the final trial |

---

## Stage 0: Preparation

**Goal:** you are booted in UEFI mode, online, with the right time and keyboard.

1. Start the Rite from the installer menu (**Advanced**), or type:

   ```
   rite begin
   ```

2. Check the boot mode. It must print `64`:

   ```
   cat /sys/firmware/efi/fw_platform_size
   ```

   If the file does not exist, you booted in BIOS mode. Reboot and pick the
   **UEFI** entry for the USB in your firmware boot menu.

3. Set the keyboard layout (`us` shown; others: `uk`, `de-latin1`, `fr`):

   ```
   loadkeys us
   ```

4. Connect to the internet.
   - Cable: it just works.
   - Wi-Fi:

     ```
     nmcli device wifi list
     nmcli device wifi connect "NETWORK NAME" password "WIFI PASSWORD"
     ```

   Test it:

   ```
   ping -c 3 archlinux.org
   ```

5. Turn on time sync:

   ```
   timedatectl set-ntp true
   timedatectl
   ```

   Wait until it says `System clock synchronized: yes`.

6. Check:

   ```
   rite check
   ```

---

## Stage 1: Partitions

**Goal:** a GPT disk with two partitions: a 1 GiB EFI system partition and one
big partition for encryption (type 8309, "Linux LUKS").

1. Find your disk:

   ```
   lsblk -o NAME,SIZE,MODEL,TYPE
   ```

   NVMe disks look like `nvme0n1`. SATA/USB disks look like `sda`. In a VM: `vda`.
   The USB stick you booted from is NOT the target.

2. Set the variables. Change `nvme0n1` to your disk:

   ```
   DISK=/dev/nvme0n1
   ```

   Partition names: NVMe disks add `p1`, `p2`. Other disks just add `1`, `2`.

   ```
   # NVMe:
   ESP=${DISK}p1 ; CRYPT=${DISK}p2
   # SATA, USB or VM (sda, vda):
   ESP=${DISK}1 ; CRYPT=${DISK}2
   ```

   Run only the line that matches your disk. Check with `echo $DISK $ESP $CRYPT`.

3. **Erase** the disk and make a new GPT table:

   ```
   sgdisk --zap-all $DISK
   ```

4. Make the EFI system partition (1 GiB, type `ef00`):

   ```
   sgdisk -n 1:0:+1G -t 1:ef00 -c 1:EFI $DISK
   ```

5. Make the encrypted partition (the rest of the disk, type `8309`):

   ```
   sgdisk -n 2:0:0 -t 2:8309 -c 2:cryptroot $DISK
   partprobe $DISK
   ```

6. Format the EFI partition as FAT32:

   ```
   mkfs.fat -F 32 -n EFI $ESP
   ```

7. Check:

   ```
   rite check
   ```

> The variables are lost if you log out. If a later stage says `DISK` is empty,
> set them again (step 2).

---

## Stage 2: Encryption

**Goal:** the big partition is a LUKS2 container with the argon2id key function,
opened as `/dev/mapper/arclight`.

1. Encrypt it. Type `YES` (capitals) when asked, then your passphrase twice.
   **Do not forget this passphrase.** Without it the data is gone.

   ```
   cryptsetup luksFormat --type luks2 --pbkdf argon2id --cipher aes-xts-plain64 --key-size 512 $CRYPT
   ```

2. Open it:

   ```
   cryptsetup open $CRYPT arclight
   ```

3. Check:

   ```
   rite check
   ```

---

## Stage 3: Filesystems

**Goal:** btrfs inside the container, five subvolumes, all mounted under `/mnt`
with zstd compression, and the EFI partition at `/mnt/efi`.

| Subvolume | Mounted at | Why |
|---|---|---|
| `@` | `/` | the system (snapshots roll this back) |
| `@home` | `/home` | your files survive a rollback |
| `@snapshots` | `/.snapshots` | where snapshots live |
| `@log` | `/var/log` | logs survive a rollback |
| `@pkg` | `/var/cache/pacman/pkg` | the package cache is not snapshotted |

1. Make the filesystem:

   ```
   mkfs.btrfs -L arclight /dev/mapper/arclight
   ```

2. Make the subvolumes:

   ```
   mount /dev/mapper/arclight /mnt
   for sv in @ @home @snapshots @log @pkg; do btrfs subvolume create /mnt/$sv; done
   umount /mnt
   ```

3. Mount them with compression:

   ```
   O=noatime,compress=zstd:1,space_cache=v2
   mount -o $O,subvol=@ /dev/mapper/arclight /mnt
   mount --mkdir -o $O,subvol=@home /dev/mapper/arclight /mnt/home
   mount --mkdir -o $O,subvol=@snapshots /dev/mapper/arclight /mnt/.snapshots
   mount --mkdir -o $O,subvol=@log /dev/mapper/arclight /mnt/var/log
   mount --mkdir -o $O,subvol=@pkg /dev/mapper/arclight /mnt/var/cache/pacman/pkg
   mount --mkdir $ESP /mnt/efi
   ```

4. Look at what you built:

   ```
   lsblk $DISK
   findmnt -R /mnt
   ```

5. Check:

   ```
   rite check
   ```

---

## Stage 4: Base system

**Goal:** a minimal system in `/mnt` with packages **you** picked.

The Eclipse OS packages (named `eclipse-os-*`) come from the USB stick (`/opt/eclipse-repo`). Normal Arch
packages come from the internet. Both are set up in `/etc/arclight-rite/pacman.conf`.

1. Pick your parts:

   | Part | Choose one |
   |---|---|
   | Kernel | `linux` (default), `linux-lts` (calm), `linux-zen` (snappy desktop) |
   | Microcode | `amd-ucode` (AMD CPU) or `intel-ucode` (Intel CPU) |
   | Editor | `vim`, `nano`, or both |

2. Install. This example uses `linux` and AMD. Change them to your picks:

   ```
   pacstrap -K -C /etc/arclight-rite/pacman.conf /mnt \
       base linux linux-firmware amd-ucode \
       btrfs-progs cryptsetup networkmanager sbctl efibootmgr \
       sudo vim man-db \
       eclipse-os-core
   ```

   `eclipse-os-core` is the AI interface (the daemons, `arc`, the MCP server).

3. Write the filesystem table:

   ```
   genfstab -U /mnt >> /mnt/etc/fstab
   cat /mnt/etc/fstab
   ```

   You should see `/`, `/home`, `/.snapshots`, `/var/log`, `/var/cache/pacman/pkg`
   (all btrfs, with `subvol=/@...`) and `/efi` (vfat).

4. Check:

   ```
   rite check
   ```

---

## Stage 5: Identity

**Goal:** give your operating system its name, name the machine, and set time,
language and keyboard.

### 5.1 Name your operating system

This is the name of **your** operating system. "Eclipse OS" is only the default.
It appears in the boot menu, on the login screen, in `fastfetch`, in
`hostnamectl` and in every app's "About" page.

```
arclight-identity --root /mnt --name "Eclipse OS"
```

Put your own name between the quotes, for example `--name "Voltcore OS"`.
Letters, digits, spaces, dots and dashes; up to 40 characters.
You can rename it later with `sudo arclight-identity --name "New Name"`.

Look at the result:

```
cat /mnt/etc/os-release
```

### 5.2 Name your machine

This is the computer's network name (the hostname). Letters, digits and dashes:

```
echo archbox > /mnt/etc/hostname
```

### 5.3 Time zone

```
arch-chroot /mnt ln -sf /usr/share/zoneinfo/America/New_York /etc/localtime
arch-chroot /mnt hwclock --systohc
```

List zones with `ls /usr/share/zoneinfo/` if you need a different one.

### 5.4 Language

```
sed -i 's/^#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /mnt/etc/locale.gen
arch-chroot /mnt locale-gen
echo LANG=en_US.UTF-8 > /mnt/etc/locale.conf
```

### 5.5 Console keyboard

```
echo KEYMAP=us > /mnt/etc/vconsole.conf
```

Check:

```
rite check
```

---

## Stage 6: Kernel image

**Goal:** the kernel, the initramfs (with the unlocker for your encrypted disk)
and the kernel command line, built into **one signed-able file**: a unified
kernel image (UKI) on the EFI partition.

1. Use the systemd-based initramfs with `sd-encrypt`. The order matters:
   `sd-encrypt` must come before `filesystems`.

   ```
   sed -i 's/^HOOKS=.*/HOOKS=(base systemd autodetect microcode modconf kms keyboard sd-vconsole block sd-encrypt filesystems fsck)/' /mnt/etc/mkinitcpio.conf
   grep ^HOOKS /mnt/etc/mkinitcpio.conf
   ```

2. Write the kernel command line. It tells the initramfs which partition to
   unlock and where the root is:

   ```
   UUID=$(cryptsetup luksUUID $CRYPT)
   mkdir -p /mnt/etc/kernel
   echo "rd.luks.name=$UUID=arclight root=/dev/mapper/arclight rootflags=subvol=@ rw quiet loglevel=3" > /mnt/etc/kernel/cmdline
   cat /mnt/etc/kernel/cmdline
   ```

3. Tell mkinitcpio to build UKIs. For the `linux` kernel (for `linux-zen`, change
   every `linux` below to `linux-zen`, also in the file name):

   ```
   cat > /mnt/etc/mkinitcpio.d/linux.preset <<'EOF'
   ALL_kver="/boot/vmlinuz-linux"
   PRESETS=('default' 'fallback')
   default_uki="/efi/EFI/Linux/arclight-linux.efi"
   fallback_uki="/efi/EFI/Linux/arclight-linux-fallback.efi"
   fallback_options="-S autodetect"
   EOF
   ```

4. Build it:

   ```
   mkdir -p /mnt/efi/EFI/Linux
   arch-chroot /mnt mkinitcpio -P
   ls -la /mnt/efi/EFI/Linux/
   ```

   You should see `arclight-linux.efi` and `arclight-linux-fallback.efi`.

5. Check:

   ```
   rite check
   ```

---

## Stage 7: Secure Boot keys

**Goal:** your own Secure Boot keys, and your kernel images signed with them.
After this, only images **you** signed can boot (once the keys are enrolled).

1. Make your keys:

   ```
   arch-chroot /mnt sbctl create-keys
   ```

2. Sign both kernel images. `-s` saves them in sbctl's list, so every kernel
   update is signed again automatically:

   ```
   arch-chroot /mnt sbctl sign -s /efi/EFI/Linux/arclight-linux.efi
   arch-chroot /mnt sbctl sign -s /efi/EFI/Linux/arclight-linux-fallback.efi
   ```

3. Check:

   ```
   rite check
   ```

4. **Optional, later: enforce it.** The keys only take effect when the firmware
   knows them. After the first successful boot:
   1. Reboot into the firmware settings, set Secure Boot to **Setup Mode**
      (sometimes called "clear keys" / "reset to setup mode"), save, boot Eclipse OS.
   2. Run `sudo sbctl enroll-keys -m` (`-m` keeps Microsoft's keys too, which
      graphics cards and some firmware need).
   3. Reboot into the firmware, turn Secure Boot **on**.

   If the PC then refuses to boot: turn Secure Boot off in the firmware again.
   Nothing is lost.

---

## Stage 8: Boot entry

**Goal:** the firmware loads your signed kernel image directly, with no boot
loader in between, and it is first in the boot order.

1. Create the entry. Change the label to your OS name from stage 5:

   ```
   efibootmgr --create --disk $DISK --part 1 --label "Eclipse OS" --loader '\EFI\Linux\arclight-linux.efi'
   ```

   `efibootmgr` puts the new entry first in the boot order.

2. Look at it:

   ```
   efibootmgr
   ```

   You can also add the fallback image as a second entry (optional):

   ```
   efibootmgr --create --disk $DISK --part 1 --label "Eclipse OS (fallback)" --loader '\EFI\Linux\arclight-linux-fallback.efi'
   efibootmgr -o $(efibootmgr | awk '/ Eclipse OS$/{print substr($1,5,4)}'),$(efibootmgr | sed -n 's/^BootOrder: //p')
   ```

   (The second line moves the main entry back to the front.)

3. Check:

   ```
   rite check
   ```

---

## Stage 9: Users and power

**Goal:** your account with a password, root locked (or with its own password),
and a sudo rule you wrote yourself.

1. Make your user (change `arthur` if you like):

   ```
   arch-chroot /mnt useradd -m -G wheel -s /bin/bash arthur
   arch-chroot /mnt passwd arthur
   ```

2. Lock root (you will use sudo instead):

   ```
   arch-chroot /mnt passwd -l root
   ```

3. Write the sudo rule. Pick one:

   ```
   # sudo asks for your password:
   echo '%wheel ALL=(ALL:ALL) ALL' > /mnt/etc/sudoers.d/10-wheel
   # or never asks (the default here, full power for you and your AI):
   echo '%wheel ALL=(ALL:ALL) NOPASSWD: ALL' > /mnt/etc/sudoers.d/10-wheel
   ```

   Then:

   ```
   chmod 440 /mnt/etc/sudoers.d/10-wheel
   arch-chroot /mnt visudo -c
   ```

   `visudo -c` must say `parsed OK` for every file.

4. Check:

   ```
   rite check
   ```

---

## Stage 10: The AI layer

**Goal:** assemble the AI interface (the `arclight` daemons) by hand and understand each part.

| Part | What it does |
|---|---|
| group `arclight` | members talk to the root daemon with no password |
| `arclightd` | the root half of the API: packages, services, logs, files, settings |
| `arclight-session` | the desktop half: screen, mouse, keyboard, windows (starts with Hyprland) |
| uinput rule | lets the AI's virtual keyboard and mouse exist |
| polkit rule | no password popups for the `arclight` group |
| MCP server | how Claude Code and Codex reach all of it |

1. Create the `arclight` group and add yourself:

   ```
   arch-chroot /mnt systemd-sysusers
   arch-chroot /mnt gpasswd -a arthur arclight
   ```

2. Start the root daemon at every boot:

   ```
   arch-chroot /mnt systemctl enable arclightd
   ```

   Keep this USB's edition (`core` = Eclipse OS without built-in AI, `ai` = Eclipse OS AI):

   ```
   mkdir -p /mnt/etc/arclight && cp /etc/arclight/edition /mnt/etc/arclight/edition
   cp -a /usr/local/share/applications /mnt/usr/local/share/ 2>/dev/null
   ```

3. Look at the uinput and polkit rules (they came with `eclipse-os-core`):

   ```
   cat /mnt/usr/lib/udev/rules.d/70-arclight-uinput.rules
   cat /mnt/usr/lib/modules-load.d/arclight.conf
   cat /mnt/usr/share/polkit-1/rules.d/49-arclight.rules
   ```

4. Register the MCP server for Claude Code and Codex, by hand:

   ```
   arch-chroot /mnt runuser -u arthur -- bash -c '
     echo "{\"mcpServers\": {\"arclight\": {\"type\": \"stdio\", \"command\": \"arclight-mcp\", \"args\": []}}}" > ~/.claude.json
     mkdir -p ~/.codex
     printf "[mcp_servers.arclight]\ncommand = \"arclight-mcp\"\n" >> ~/.codex/config.toml'
   ```

   (The quick way that does the same and more: `arch-chroot /mnt runuser -u arthur --
   arclight-firstrun --home /home/arthur --offline --force`.)

5. Check:

   ```
   rite check
   ```

---

## Stage 11: Desktop

**Goal:** Arthur's Hyprland desktop with the Eclipse look, starting when you log in.

1. Install the desktop, the browser, the editor, graphics drivers and the rite
   tool itself (for stage 13). Pick the Vulkan driver for your GPU: `vulkan-radeon`
   (AMD) or `vulkan-intel` (Intel):

   ```
   pacstrap -C /etc/arclight-rite/pacman.conf /mnt \
       eclipse-os-desktop eclipse-os-installer zen-browser-bin zed \
       mesa vulkan-radeon bluez bluez-utils
   ```

2. Put Arthur's desktop config into your home (the files from the Eclipse OS
   default home), then fill in your home path:

   ```
   arch-chroot /mnt bash -c 'cp -aT /usr/share/arclight/skel /home/arthur && chown -R arthur:arthur /home/arthur'
   arch-chroot /mnt runuser -u arthur -- arclight-firstrun --home /home/arthur --offline --force
   ```

3. Log in automatically on the first console (like Arthur's PC). The login
   starts Hyprland through `~/.bash_profile`:

   ```
   mkdir -p /mnt/etc/systemd/system/getty@tty1.service.d
   cat > /mnt/etc/systemd/system/getty@tty1.service.d/autologin.conf <<'EOF'
   [Service]
   ExecStart=
   ExecStart=-/sbin/agetty -o '-p -f -- \\u' --noreset --noclear --autologin arthur - ${TERM}
   EOF
   ```

   (Skip this to get a normal login prompt instead.)

4. Networking and Bluetooth at boot:

   ```
   arch-chroot /mnt systemctl enable NetworkManager bluetooth
   ```

5. Check:

   ```
   rite check
   ```

---

## Stage 12: Migration (optional)

**Goal:** bring your files from an old system, with a plan you wrote, copied and
then verified file by file. Skip it with `rite skip 12`.

1. Mount the old system **read-only** (it is never changed). Example: the old
   root was `/dev/sda2`:

   ```
   mount --mkdir -o ro /dev/sda2 /old
   ```

2. Make a plan. It measures every folder and marks each one `copy`, `share` or
   `skip`:

   ```
   arclight-migrate plan --home /old/home/arthur --into /mnt/home/arthur --no-share > /root/plan.json
   ```

3. Read it and change it if you want (`"action": "copy"` / `"skip"`):

   ```
   vim /root/plan.json
   ```

4. Copy and verify:

   ```
   arclight-migrate copy /root/plan.json --report /mnt/var/lib/arclight/migration-report.json
   ```

   It ends with `verified: every copied file is identical`.

5. Check:

   ```
   rite check
   ```

---

## Stage 13: First boot and the final trial

1. Close everything and reboot. The first line stops the key helper that `pacman-key` left running in
   the new system (otherwise `umount` says the target is busy):

   ```
   gpgconf --homedir /mnt/etc/pacman.d/gnupg --kill all
   umount -R /mnt
   cryptsetup close arclight
   systemctl reboot
   ```

   Pull the USB stick out when the screen goes black.

2. The firmware starts your kernel image. Type your **disk passphrase** (stage 2).
3. You are logged in automatically and Hyprland starts with the Eclipse look.
4. Open a terminal (**Super+Q**) and run the final trial:

   ```
   rite final
   ```

   When every line is ✓ you get your certificate. The Rite is complete.

---

## Troubleshooting

**The PC boots the old system or the USB instead.** Open the firmware boot menu
and pick your entry (the name from stage 8), or put it first in the firmware's
boot order.

**"Secure Boot violation" / it will not boot.** You enabled Secure Boot before
enrolling your keys. Turn Secure Boot off in the firmware, boot, and do stage 7
step 4 in order.

**It asks for the passphrase and then stops / "root device not found".**
The UUID in `/etc/kernel/cmdline` is wrong. Boot the USB, then:

```
cryptsetup open /dev/YOURDISK2 arclight
mount -o subvol=@ /dev/mapper/arclight /mnt
mount /dev/YOURDISK1 /mnt/efi
# fix /mnt/etc/kernel/cmdline (cryptsetup luksUUID /dev/YOURDISK2 shows the right UUID)
arch-chroot /mnt mkinitcpio -P
arch-chroot /mnt sbctl sign -s /efi/EFI/Linux/arclight-linux.efi
```

**Black screen after login.** Hyprland needs working graphics. Log in on
**Ctrl+Alt+F2** and check `journalctl -b -p err`. Install the right Vulkan driver
(stage 11) and reboot.

**`rite check` says a stage before this one is not done.** The Rite goes in
order. Run `rite` to see which stage is open.

**I logged out of the live system and lost my variables.** Set `DISK`, `ESP` and
`CRYPT` again (stage 1, step 2). If the container is closed: `cryptsetup open
$CRYPT arclight`, then mount again (stage 3, step 3).

**Starting over.** `umount -R /mnt; cryptsetup close arclight`, then go back to
stage 1. To reset the Rite's progress: `rm /run/arclight-rite/state.json`.
