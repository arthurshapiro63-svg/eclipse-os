# Eclipse OS 0.1.2

A safety and honesty release. If you downloaded 0.1.1, please use this one instead. Install it fresh from the ISO.

Flash the ISO to a USB stick (4 GB or more), boot it, and click "Install it" on the welcome screen. The live system logs in by itself as `eclipse` with no password.

Check the download with `sha256sum -c eclipse-os-0.1.2-x86_64.iso.sha256`.

## Changed

- **Root needs your password again.** In 0.1 and 0.1.1, everyone in the `arclight` group (that is, every user the installer made) could become root with no password: sudo, every polkit action, and Eclipse's root service all said yes on their own. So any program running as you, AI agents included, could change the whole system silently. Now, on an installed system:
  - `sudo` asks for your password.
  - polkit asks for your password.
  - Eclipse's root service (arclightd) asks for your administrator password, through the normal system prompt, for every change: installing or removing apps, services, files outside your home, settings for the whole system, and the AI's root commands. Reading things (lists, status, logs) still works without a prompt.
  - The password prompt says exactly what you're approving, like "run as root: pacman -S htop" or "install software: htop". It's built from the real request, not from a label the app sends.
  - The live USB stays passwordless, because it has no password to ask for.
  - If you really want the old behaviour, turn on **Settings → System → Passwordless admin** (`system.sudo_nopasswd`). It warns you first. Turning it on is itself a change, so it asks for your password.
- **An AI can't approve its own root action.** Eclipse AI still shows the exact command and you click yes. The real check is the password prompt that comes after: the AI can click and type, but it doesn't know your password. The yes card is also harder to fake: "yes" is no longer pre-selected, and a yes that comes right after the AI used the mouse or keyboard is refused.
- **A password prompt that always shows up.** The prompt is now polkit-gnome, in the Eclipse colours. The Hyprland one (hyprpolkitagent) crashed every time it tried to draw without GPU acceleration, which would have left no way to approve anything.
- **The cloud model is named for what it is.** Eclipse AI used to show OpenAI's Codex as "Eclipse Totality" and hid where it came from. It's now called **Codex (cloud)**. The picker and the chat say that your messages leave your computer. It only shows up when Codex is installed and signed in. The chat also says plainly that Codex runs its own commands in its own sandbox (your home folder, never root) without the yes/no cards. You still see each command as it runs. Root commands still go through the card and your password. "Totality" is only the Super+G feature now.
- **Eclipse AI's command log works again.** A broken import in 0.1.1 made logging a command fail, which also broke the AI's root commands. A VM test of the new password flow caught it.
- **No more personal leftovers.** The guide for AI agents (`/etc/arclight/AGENTS.md`), the AI prompts and the installer were written around my own machine. They're now generic for anyone, and they match the new password rules. The installer no longer fills in a user name for you.
- **The README describes the AI correctly.** It covers the local model through Ollama, the yes/no cards, the password prompt, file backups and revert, snapshots on whole-drive installs, the optional Codex (cloud) model, and other agents through the MCP server.

## Good to know

- Totality's extra CPU priority for the window you're using needs root, so it only happens with passwordless admin on. Pausing the other apps works either way.
- After 3 wrong passwords in a row, Arch locks the account for 10 minutes (`faillock`). That includes wrong guesses typed into the prompt by anything other than you.
- Codex (cloud) also works on a PC without the local AI engine.

## Updating from 0.1 or 0.1.1

Updating `eclipse-os-core` switches sudo and the root service back to asking for your password, and tells you so. Updating `eclipse-os-desktop` brings the new password prompt.

---

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
- **The console font failed on every boot after installing.** `terminus-font` is now installed, and the installer never names a font that isn't there. Console setup also retries when it races the graphics takeover early in boot.
- **The Rite (the advanced install) was missing its package config.** `/etc/arclight-rite/pacman.conf` now ships with the installer, and the ISO carries the Eclipse packages at `/opt/eclipse-repo`, as the install guide says. The Rite's last stage can now unmount the new system: a key helper left running by `pacman-key` used to keep it busy.

## Also

- `/etc/os-release` now always shows the installed Eclipse version.
- `tools/build-iso.sh` cleans up after a failed build, so it can't reuse stale packages.
- There is a test suite: `python3 -m unittest discover -s tests`.

---

# Eclipse OS 0.1

First public build of Eclipse OS.
