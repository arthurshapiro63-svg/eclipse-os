# Eclipse OS (codename Arclight): guide for AI agents

You are running on **Eclipse OS** (the name Arthur picked at install may differ: see /etc/os-release),
Arthur's AI-native Arch Linux, codename **Arclight**: every command, package, service and path is
still called `arc` / `arclight-*`. The machine is built so that you
can operate all of it: every setting, service, log, package and file, and the whole desktop
(see any window, click, type, play games). Arthur chose full permissions: nothing here asks for
a password and nothing blocks you. Safety comes from undo, not from prompts, so be bold and
be careful: check results, and keep Arthur's work intact.

## How to reach the machine
- **MCP server `arclight`** (registered for Claude Code and Codex): the tools below.
- **`arc` CLI**, the same API for shell use: `arc --help`, `arc api` lists every method.
- Root without a password: the `run` tool with `root=true`, `arc root CMD`, or plain `sudo`
  (the `arclight` group has NOPASSWD sudo and full polkit rights).

## Tools (MCP) and what to use them for
| Tool | Use |
|---|---|
| `system_info` | First look: hostname, load, memory, disks, GPU, network, failed services, focused window |
| `settings` | ANY setting. `search` first (friendly keys like `appearance.gaps_out`, `audio.volume`, `power.profile`, `system.timezone`, plus every Hyprland option as `hypr.<section>.<option>`). `set` applies live AND persists. |
| `packages` | pacman + AUR (yay). install/remove/upgrade/search/info/owns/files/history |
| `services` | systemd units; `user=true` for the user's own units |
| `logs` | journal queries; `mode=errors` = everything currently wrong |
| `files` | read/write/edit any path as root; every write keeps the old version (`history`, `revert`) |
| `run` | shell commands (as the user, or `root=true`) |
| `screenshot` | `screen`, `active`, `window:<address/class/title>` (works on hidden workspaces), `monitor:NAME`, `region:X,Y,W,H`; `grid=true` overlays coordinates |
| `see` | `ocr`, `find_text` (returns click centers), `watch` (motion burst for games), `pixel`, `wait_stable` |
| `ui` | accessibility tree: `find` / `press` controls by name (exact, no pixels) and `set_text` |
| `input` | click, double/right click, drag, scroll, type, key chords, hold, down/up, `mouse_rel` (game camera) |
| `input_sequence` | timed steps for games (hold W 1200 ms, move camera, jump, screenshot) |
| `windows` | list/focus/close/float/fullscreen/move/resize windows, workspaces, monitors |
| `apps` / `games` | list and launch (returns the new window); games = Steam, Godot projects, desktop games |
| `wait` | for a window, for text on screen, for the screen to settle |
| `snapshots` | btrfs system snapshots (whole-disk installs); package changes snapshot automatically |
| `history` | every action taken through the API (who/what/result), service failures, package log |
| `machine` | hostname, timezone, locale, kernel cmdline, sysctl, users, reboot/poweroff |
| `hyprland` | raw compositor dispatch/eval/query |
| `stop` | release all keys/buttons (Arthur's panic key Super+Shift+Escape does this too) |

## Useful starting points
- `arc doctor`: health check of the whole machine, each problem with the command that fixes it.
- Displays: `settings` keys `display.<OUTPUT>.mode` (choices = the monitor's real modes, e.g.
  "1920x1080@329.92Hz") and `display.<OUTPUT>.scale`. Live + saved.
- `see find_text` is tolerant: OCR often drops tiny words, so a phrase matches when most of its words are
  found in order (check `score`). Use `exact=true` when you need every word.
- Game mode: `game.mode` (on/off/toggle/status; Super+G) turns blur/shadows/animations off and the power
  profile to performance, temporarily; turn it on before playing a game for Arthur, off afterwards.
- Undo: `file.history` + `file.revert` for files, `settings.reset` for settings (also buttons in Settings -> AI).
- `arc update` rebuilds Arclight itself from `~/Projects/arclight` (after you change its source).
- Routines (AI on a schedule): `arc routine add NAME "daily 09:00" "PROMPT"` (also "weekdays 08:30",
  "sun 10:00", "every 2h"); list/remove/run/log. When Arthur asks for something regularly ("every morning..."), make a routine.
- Super+Shift+E opens Ask with the text Arthur selected attached; Files has a right-click "Ask Eclipse about this".
- Arthur dictates with Hush; the Ask bar (Super+Shift+A, voice: Super+Shift+V) is how he usually reaches you.

## Driving the desktop well
1. Prefer, in order: `ui press` (accessibility) > `see find_text` + click its center > click
   coordinates read off a screenshot. For screenshot coordinates pass `shot=<id>` and use the
   image's own pixels; the server converts them to screen coordinates.
2. After every action that should change the screen, take a new screenshot and check.
3. Do not steal focus or switch workspaces while Arthur is actively using the machine unless the
   task needs it; window screenshots work without switching.
4. Games: `games launch`, then `screenshot target=window:<address>`, then `input_sequence`
   (hold keys with `hold`, aim with `mouse_rel`), use `see watch` to see motion. Release keys at
   the end (`stop`).

## Arthur's desktop (do not break his muscle memory)
- Hyprland 0.56 with a **Lua config**: `~/.config/hypr/hyprland.lua` is Arthur's own file.
  Arclight adds one marked block at its end (`-- arclight:begin/end`) that loads
  `/usr/share/arclight/hypr/arclight.lua`. Settings you change through `settings` land in
  `~/.config/hypr/arclight-settings.lua` (generated, loaded last). Do not hand-edit generated files.
- Lua config gotchas: `hyprctl keyword` does not work (use `hyprctl eval`), dispatchers are Lua
  (`hyprctl dispatch 'hl.dsp.focus({ workspace = 2 })'`), validate with `hyprctl configerrors`.
- Theme system: tokens in `~/.config/theme/tokens/*.json`, `theme-apply <slug>` renders every
  app's colours from templates in `~/.config/theme/templates/`. Edit templates, never outputs.
  Themes: `eclipse` (default, from the eclipse wallpaper), `arclight`, `midnight-blue`, `ember`, `graphite`,
  `daylight`, `dynamic`.
- Shell (bar/dock/launcher): DankMaterialShell, or `arthur-shell`; switch with `shell-switch`.
  Never run `dms setup` or `dms kill`; never `pkill ghostty` (Claude Code runs inside Ghostty).
- `~/.config` is a git repo: commit before and after config changes so they can be undone.
- Arthur is dyslexic: answers short, plain, one idea per sentence.

## Where things are
- `/etc/arclight/` this guide, `arclightd.json` (daemon options), `release`
- `/var/log/arclight/actions.jsonl` every API action; `events.jsonl` failures + package transactions
- `/var/lib/arclight/history/files/` previous versions of files written through the API
- `~/.config/arclight/settings.json` persisted Arclight settings
- Source of Arclight itself: `~/Projects/arclight` (if present) or `/usr/lib/arclight`
