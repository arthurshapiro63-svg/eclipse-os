# Migrating to Arclight

How your files, settings and programs come across, and why nothing can be lost on the way.

## The rules

1. **Copy, verify, then swap.** Nothing is ever moved. Data is copied, every copied file is checked
   (content checksum), and only then does the computer switch to the new system.
2. **The old system is only read.** The installer reads it through a read-only mount. Writes go only
   to new places: the new system's own folder and its own boot folder.
3. **One switch, at the very end.** The switch is one write to the firmware's boot order. Before that,
   the old system is still the one that starts.
4. **If anything fails, the new files are removed again.** The boot order is never touched, and even
   the timestamps of the folders that got new children are put back.

These were tested by crashing the install on purpose at 5 different points on a copy of your disk
layout. Every time, the old files, the EFI partition and the boot order were identical afterwards
(`tests/failinject.sh`).

## Step 1: record your current system (done)

```
arclight-migrate manifest --out manifest
```

This writes `manifest/MANIFEST.md` and `manifest/manifest.json`: hardware, disks, boot loader, every
package (with versions, AUR list separate), enabled services, changed `/etc` files, your users, home
folder sizes, projects (with git state), Steam games, toolchains, AI tool configs. Secrets are never
read; only their presence is recorded. Your copy from 2026-10-08 is in this repo under `manifest/`.

## Step 2: pick how to install

| Mode | Old system | Your files | When |
|---|---|---|---|
| **Side by side** (default when an old Linux is found) | kept, untouched, still in the boot menu | copied or shared, verified | your PC: one disk, data you care about |
| **Second disk** | untouched (other disk) | copied from it | if you add a disk |
| **Erase disk** | deleted | from a verified bundle made first (`arclight-migrate export`) | a clean start |

### Side by side, in detail

- The new system lives in `/arclight/deploy/<date>/` on your existing partition. The kernel mounts
  that folder as `/` (`rootflags=X-mount.subdir=...`). Nothing outside `/arclight` is written.
- It gets its own boot menu in `EFI/arclight/` on the EFI partition (the themed Arclight GRUB), with an
  entry that starts your old system's own boot loader. Your old GRUB is not changed.
- In the new system, your old system is visible read-only at `/host`.
- Big folders can be **shared** instead of copied: the new system mounts the old folder in place
  (nothing duplicated, nothing moved). Both systems see the same files.

## Step 3: the migration plan

The installer measures your home and makes a plan. You can change it before anything is written.

```
arclight-migrate plan --home /home/arthur --into /new/home/arthur > plan.json
```

Each top-level folder (and each folder inside `~/.local/share`, `~/.config`, `~/Projects`) is one of:

- **copy**: copied and verified.
- **share**: left where it is and mounted into the new system (side by side only).
- **skip**: not needed (caches, trash; they regenerate).

**Your real home today** (432 GiB used, about 395 GiB free on the disk):

| | Size |
|---|---|
| copy | 338 GiB |
| share | 172 GiB (`~/.local/share/Steam`) |
| skip | 24 GiB (`~/.cache`, trash) |

So it fits with 15 GiB to spare. `~/vms` (about 65 GiB: the Mint and sandbox VMs, plus the Arclight
builder VM and test replica) is copied; mark it `share` in the plan if you want more room.

## Step 4: what else comes across

- **Your user**: same name, same user and group ids (so shared files keep their owner), same
  **password** (the hash is copied from the old system), autologin on tty1 like now.
- **Machine settings**: Wi-Fi/network connections (NetworkManager), Bluetooth pairings, SSH host keys,
  timezone, language, keyboard, machine name.
- **Your packages**: every explicitly installed package from the old system. Repo packages install
  during the install when online; the rest (AUR, or if offline) are listed in
  `/var/lib/arclight/pending-packages.txt` and installed after the first boot.
- **Your desktop**: your own `~/.config` (Hyprland Lua config, DMS, arthur-shell, theme tokens,
  scripts) comes over as it is. Arclight then adds, on the copy only:
  - one marked block at the end of `hyprland.lua` (`-- arclight:begin` ... `-- arclight:end`) that loads
    the AI layer (new binds Super+Shift+A, Super+I; nothing of yours is changed),
  - the `arclight` theme tokens + one new template, then applies the Arclight theme,
  - the Arclight wallpapers next to yours,
  - the MCP server registered for Claude Code and Codex, and a short machine guide in
    `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`.
  Your Midnight Blue theme stays one `theme-apply midnight-blue` away.

## Restore from the Google Drive backup (on the new Arclight)

The backup (made 2026-10-08 with `arclight-backup`) is in Google Drive, folder **Arclight home backup**:
one archive per folder (`data/`), a file list per archive (`lists/`), checksums (`manifest.json`), the
system record (`system-manifest/`) and the tool itself. Archives keep permissions, links, owners and
timestamps, so the restore is exact. Secrets were never uploaded.

1. Sign in to Drive once (Claude can click it for you):
   `rclone config create gdrive drive scope=drive.file`
2. Restore your home (as yourself, best from a console with the desktop logged out):
   `arclight-backup restore --into $HOME`
   It downloads every archive, checks its checksum, unpacks it, then compares every file with the list
   recorded at backup time and prints the number of differences (0 = identical).
3. Bring the secrets over from the old system (side-by-side install: it is at `/host`):
   `arclight-backup secrets --source /host/home/arthur --into $HOME`
4. Put the Arclight layer back on top of your restored config: `arclight-firstrun --force`

Just one folder: `arclight-backup restore --into $HOME --only Projects/pycraft` (repeat `--only` for more).

**If rclone cannot sign in** (rclone warned in October 2026 that its shared Google login is being retired):
download the folder **Arclight home backup** from drive.google.com instead (right-click, Download; Drive
zips big folders in parts, so unzip them all into one folder that has `manifest.json`, `lists/` and
`data/`), then:
`arclight-backup restore --from ~/Downloads/Arclight\ home\ backup --into $HOME`
It checks the same checksums and file lists. No rclone needed.

Tested 2026-10-09 both ways (rclone and downloaded folder) on a real archive from your Drive
(`neon-cube`, 9,700 files): 0 differences, and the contents byte-identical to the original.
The index (checksums + file lists) is uploaded every 20 minutes during the backup, so even an
unfinished backup can be restored archive by archive.

All apps are already installed by the Arclight installer (they are built into the USB); your own
programs in your home (Unity, Blender, Godot, Claude Code, Codex, Steam games) come back with step 2.

## Going back

- **Side by side:** choose your old system in the Arclight boot menu ("Arch Linux (GRUB)"), or in the
  firmware boot menu. To make it the default again: `sudo efibootmgr -o <old>,<arclight>`.
- **Removing Arclight (side by side):** boot the old system, delete `/arclight`, remove `EFI/arclight`
  from the EFI partition and its boot entry (`efibootmgr -b XXXX -B`). Your old system was never changed.

## Commands

```
arclight-migrate manifest [--out DIR]                    record this system (read-only)
arclight-migrate plan --home H --into T [--no-share]     measure and classify (JSON)
arclight-migrate copy plan.json [--report FILE]          copy + verify every file
arclight-migrate export plan.json --to DIR               verified bundle on another disk
arclight-migrate import BUNDLE --into HOME               unpack + verify every file
arclight-migrate fingerprint DIR                         prove a tree did not change
```
