# Eclipse OS 0.1.1

A bug-fix release. Install it fresh from the ISO (0.1 has no in-place update path yet; that comes in 0.2).

Flash the ISO to a USB stick (4 GB or more), boot it, and click "Install it" on the welcome screen. The live system logs in by itself as `eclipse` with no password.

Check the download with `sha256sum -c eclipse-os-0.1.1-x86_64.iso.sha256`.

Heads up: the AI features need an agent like Claude Code, which you install after.

## Fixed

- **Installer could format the wrong partition (free-space mode).** New partitions were picked by sorting device names, which goes wrong with numbering gaps or ten or more partitions (`p9`/`p10`). The installer now uses explicit partition numbers inside the free space it chose. It identifies each new partition by a fresh partition GUID, waits for exactly those devices, and checks the GUID again right before formatting. Existing partitions are never formatted.
- **Passwords could end up in logs.** Calls like `sys.user_add` and `sys.user_mod` were logged with their parameters as-is. Secrets are now masked before anything is written: password and token parameters, command input, typed text, clipboard, file contents, `chpasswd` pipes, bearer tokens, URL credentials and password hashes. This applies to the system and desktop action logs, the event log, the installer log and Eclipse AI's command log. Log files are now `0600`, and updating from 0.1 scrubs old logs.
- **Moving files from an old Btrfs system used the wrong path.** Folders shared with the old system pointed outside the old root subvolume (`@`), and a separate `@home` subvolume was not followed. Paths now go through the old system's own fstab. Layouts that can't be handled safely, like a home on another partition, stop the install with a clear reason before anything is written.
- **Failed AUR updates looked like success.** An update whose AUR part failed came back as a normal result, and the Store then said "Everything is up to date". The Store now shows which packages were updated, which were not and why, with a Retry button. `arc pkg upgrade`, Settings and Eclipse AI also report these updates as unfinished.
- **The live USB sat for 2 minutes on "A start job is running for Eclipse OS live user".** The live setup opened a login session that waited for a unit that was waiting for it. It no longer does.
- **The console font failed on every boot after installing.** `terminus-font` is now installed, and the installer never names a font that isn't there.
- **The Rite (the advanced install) was missing its package config.** `/etc/arclight-rite/pacman.conf` now ships with the installer, and the ISO carries the Eclipse packages at `/opt/eclipse-repo`, as the install guide says.

## Also

- `/etc/os-release` now always shows the installed Eclipse version.
- `tools/build-iso.sh` cleans up after a failed build, so it can't reuse stale packages.
- There is a test suite: `python3 -m unittest discover -s tests`.

---

# Eclipse OS 0.1

First public build of Eclipse OS.
