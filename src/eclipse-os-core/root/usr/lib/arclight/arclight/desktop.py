"""Eclipse OS (codename Arclight): the per-user desktop layer, applied on top of the user's own config.

Used in three places, always the same code:
  * building the distro's default home (/etc/skel) from the author's synced config
  * migrating the user's real home into a new install (on the STAGED copy, never the original)
  * `arclight-firstrun` at first login (one-time steps that need the live session)

Every step is idempotent. Edits to files the user owns are confined to marked blocks
(`-- arclight:begin` ... `-- arclight:end`), so his own later changes are never overwritten.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, identity

SHARE = Path(os.environ.get("ARCLIGHT_SHARE", "/usr/share/arclight"))
BEGIN, END = "-- arclight:begin", "-- arclight:end"
HYPR_BLOCK = f"""
{BEGIN}  (added by Arclight; delete this block to go back to plain Hyprland)
-- The AI-native layer: new binds (Super+Shift+A ask, Super+I settings), autostart of the
-- session daemon, accessibility env, the window glow. Source: /usr/share/arclight/hypr/arclight.lua
-- (copy it to ~/.config/hypr/arclight.lua to customise).
package.path = package.path .. ";{SHARE}/hypr/?.lua"
-- `hyprctl reload` re-runs this file in the same Lua state: drop cached modules so they run again
for _, m in ipairs({{ "arclight", "arclight-colors", "arclight-settings" }}) do package.loaded[m] = nil end
local okArc, arcErr = pcall(require, "arclight")
if not okArc then
    hl.notification.create({{ text = "Arclight layer failed to load: " .. tostring(arcErr), timeout = 10000 }})
end
-- Values set with `arc set` / Arclight Settings. Loaded last so they win.
pcall(require, "arclight-settings")
{END}
"""
STOP_RX = re.compile(r'hl\.dsp\.exec_cmd\("\$HOME/\.local/bin/claude-orange --stop"\)')


def log(msg):
    print(f"arclight: {msg}", file=sys.stderr, flush=True)


def src_path(*parts):
    """Find a shipped asset: installed share dir first, then the source tree (development)."""
    p = SHARE.joinpath(*parts)
    if p.exists():
        return p
    repo = Path(__file__).resolve().parents[2]
    for base in (repo / "desktop", repo):
        q = base.joinpath(*parts)
        if q.exists():
            return q
    return p


# ---------------------------------------------------------------- steps

def fill_home(home):
    """Replace the @HOME@ placeholder (skel) with the real home path."""
    n = 0
    for base in (home / ".config", home / ".local/bin", home / ".bashrc", home / ".bash_profile",
                 home / ".cache/current-wallpaper"):
        files = [base] if base.is_file() else (p for p in base.rglob("*") if p.is_file() and not p.is_symlink()) if base.is_dir() else []
        for f in files:
            try:
                t = f.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            if "@HOME@" in t:
                f.write_text(t.replace("@HOME@", str(home)))
                n += 1
    return n


def patch_hyprland(home, fresh=False):
    """Add (or refresh) the marked Arclight block at the end of hyprland.lua."""
    f = home / ".config/hypr/hyprland.lua"
    if not f.exists():
        return "no hyprland.lua"
    text = f.read_text()
    text = re.sub(rf"\n?{re.escape(BEGIN)}.*?{re.escape(END)}\n?", "\n", text, flags=re.S).rstrip("\n") + "\n"
    # the panic key also stops Arclight's virtual input (claude-orange is still stopped when present)
    text = STOP_RX.sub('hl.dsp.exec_cmd("arclight-stop")', text)
    if fresh:
        text = _neutralize_monitor_rules(text)
        # a fresh machine has no ~/Projects/arch-ai: Super+A / Ctrl+Alt+A open Eclipse AI (the Eclipse edition
        # of Arch AI). A migrated home keeps its own bind (Arch AI) untouched.
        text = re.sub(r'hl\.dsp\.exec_cmd\("[^"]*arch-ai/bin/arch-ai-toggle"\)',
                      'hl.dsp.exec_cmd("eclipse-ai-toggle")',
                      text)
        text = text.replace('hl.dsp.exec_cmd("sh -c \'command -v arch-ai-toggle >/dev/null && exec arch-ai-toggle || '
                            'exec arclight-ask\'")', 'hl.dsp.exec_cmd("eclipse-ai-toggle")')   # older fresh installs
    text += HYPR_BLOCK
    f.write_text(text)
    return "patched"


def _neutralize_monitor_rules(text):
    """Comment out workspace rules and mirrors that name the author's outputs (DP-1 / HDMI-A-1).
    On other screens they would pin workspaces 1-10 to a monitor that does not exist."""
    out, block, depth = [], [], 0
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        starts = ln.lstrip().startswith(("hl.workspace_rule(", "hl.monitor(")) or \
            (ln.lstrip().startswith("for i =") and i + 1 < len(lines) and "hl.workspace_rule" in lines[i + 1])
        if starts:
            j, chunk, bal = i, [], 0
            while j < len(lines):
                chunk.append(lines[j])
                bal += lines[j].count("(") - lines[j].count(")")
                if lines[j].lstrip().startswith("for i ="):
                    bal += 1
                if lines[j].strip() == "end" or (bal <= 0 and ")" in lines[j] and not lines[i].lstrip().startswith("for")):
                    break
                j += 1
            blob = "\n".join(chunk)
            if re.search(r'"(DP-1|HDMI-A-1)"', blob) and 'output   = ""' not in blob:
                out.append("-- arclight: machine-specific (the author's dual-monitor DP-1 + HDMI-A-1 setup), off on this machine:")
                out += ["-- " + c for c in chunk]
                i = j + 1
                continue
        out.append(ln)
        i += 1
    return "\n".join(out)


DEFAULT_THEME = "eclipse"            # the Eclipse OS look (from the arclight-eclipse wallpaper)
SHIPPED_THEMES = ("eclipse", "arclight")
DEFAULT_WALLPAPER = "arclight-eclipse.jpg"


def install_theme(home):
    tok = home / ".config/theme/tokens"
    tpl = home / ".config/theme/templates"
    if not tok.parent.exists():
        return "no theme system"
    tok.mkdir(parents=True, exist_ok=True)
    tpl.mkdir(parents=True, exist_ok=True)
    done = []
    for slug in SHIPPED_THEMES:
        f = src_path(f"theme/{slug}.json")
        if not f.exists():
            f = src_path(f"overlay/.config/theme/tokens/{slug}.json")
        if f.exists():
            shutil.copy(f, tok / f"{slug}.json")
            done.append(slug)
    shutil.copy(src_path("hypr/arclight-colors.tmpl"), tpl / "arclight-colors.tmpl")
    backfilled = backfill_sun(tok)
    return f"tokens ({', '.join(done)}) + template installed" + (f", sun added to {backfilled}" if backfilled else "")


def backfill_sun(tok_dir):
    """Eclipse OS templates use a `sun` token group (focus rings, selection, progress, glows).
    Older theme files (e.g. hand-made ones) don't have it: add one built from the theme's own accent,
    so those themes look exactly as before and theme-apply never fails on an unknown token."""
    n = 0
    for f in sorted(Path(tok_dir).glob("*.json")):
        try:
            d = json.loads(f.read_text())
            if "sun" in d or "color" not in d:
                continue
            c, g = d["color"], d.get("glow", {})
            d["sun"] = {"gold": c["accent"], "gold-soft": c.get("accent-bright", c["accent"]),
                        "gold-deep": c.get("accent-dim", c["accent"]), "core": g.get("peak", c["accent"]),
                        "on": "#FFFFFF"}
        except (OSError, ValueError, KeyError):
            continue
        f.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        n += 1
    return n


FF_IMAGE_LOGO = ('    "type": "kitty-direct",\n    "source": "~/.config/fastfetch/eclipse-logo.png",\n'
                 '    "width": 44,')


def fastfetch_logo(home):
    """fastfetch shows the Eclipse OS logo image instead of the Arch mark (also on a migrated home: its
    fastfetch template and config are patched, originals kept as *.arclight-orig)."""
    d = home / ".config/fastfetch"
    d.mkdir(parents=True, exist_ok=True)
    src = next((p for p in (Path("/usr/share/arclight/logo/eclipse-logo-512.png"),
                            Path(src_path("..", "art", "eclipse", "logo", "icons", "eclipse-logo-512.png")))
                if p.exists()), None)
    if src:
        shutil.copy(src, d / "eclipse-logo.png")
    pat = re.compile(r'    "type": "file",\n    "source": "~/\.config/fastfetch/logo-[^"]*\.txt",')
    n = 0
    for f in (home / ".config/theme/templates/fastfetch-static.tmpl", d / "config.jsonc"):
        if not f.exists():
            continue
        t = f.read_text()
        t2 = pat.sub(FF_IMAGE_LOGO, t).replace("\U000F08C7", "\U000F0599")  # Arch glyph -> sun on the os line
        if t2 != t:
            orig = f.with_name(f.name + ".arclight-orig")
            if not orig.exists():
                orig.write_text(t)
            f.write_text(t2)
            n += 1
    return f"logo image {'copied' if src else 'missing'}, {n} files switched to it"


THUNAR_ACTION = """<action>
	<icon>arclight</icon>
	<name>Ask Eclipse about this</name>
	<submenu></submenu>
	<unique-id>eclipse-ask-about-this</unique-id>
	<command>arclight-ask --prefill "About %F: "</command>
	<description>Ask the AI about the selected files or folders</description>
	<range></range>
	<patterns>*</patterns>
	<directories/>
	<audio-files/>
	<image-files/>
	<other-files/>
	<text-files/>
	<video-files/>
</action>
"""


def thunar_action(home):
    """Right-click any file or folder in Files: "Ask Eclipse about this" (added next to existing actions)."""
    f = home / ".config/Thunar/uca.xml"
    f.parent.mkdir(parents=True, exist_ok=True)
    t = f.read_text() if f.exists() else '<?xml version="1.0" encoding="UTF-8"?>\n<actions>\n</actions>\n'
    if "eclipse-ask-about-this" in t:
        return "already there"
    if "</actions>" not in t:
        return "uca.xml not understood; left alone"
    f.write_text(t.replace("</actions>", THUNAR_ACTION + "</actions>", 1))
    return "added"


def install_wallpapers(home):
    dst = home / "Pictures/wallpapers"
    dst.mkdir(parents=True, exist_ok=True)
    src = Path("/usr/share/backgrounds/arclight")
    if not src.exists():
        src = src_path("wallpapers")
    n = 0
    for p in sorted(src.glob("arclight-*")):
        if not (dst / p.name).exists():
            shutil.copy(p, dst / p.name)
            n += 1
    return f"{n} wallpapers added"


def set_wallpaper(home, name=DEFAULT_WALLPAPER, placeholder=False):
    """Point the wallpaper script state at an Arclight wallpaper.
    ~/.cache/current-wallpaper is a text file holding the path; current-wallpaper-lock is a symlink."""
    wp = home / "Pictures/wallpapers" / name
    if not wp.exists():
        return "wallpaper missing"
    cache = home / ".cache"
    cache.mkdir(exist_ok=True)
    shown = f"@HOME@/Pictures/wallpapers/{name}" if placeholder else str(wp)
    (cache / "current-wallpaper").write_text(shown + "\n")
    lock = cache / "current-wallpaper-lock"
    if lock.exists() or lock.is_symlink():
        lock.unlink()
    lock_img = lock_image(home, name)
    if not placeholder:
        lock.symlink_to(lock_img if lock_img.exists() else wp)
    return f"wallpaper -> {name}"


def lock_image(home, wallpaper=DEFAULT_WALLPAPER):
    """The lock-screen picture: the crescent crop of Arthur's eclipse photo (a real photo; the old
    generated lock image is gone), else the wallpaper itself."""
    p = src_path("eclipse/lock.jpg")
    if p.exists():
        return p
    return home / "Pictures/wallpapers" / wallpaper


def fix_lock_link(home):
    lock = home / ".cache/current-wallpaper-lock"
    if not lock.exists():
        img = lock_image(home)
        if img.exists():
            if lock.is_symlink():
                lock.unlink()
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.symlink_to(img)
            return "lock wallpaper linked"
    return "ok"


def apply_theme(home, slug=DEFAULT_THEME, sandbox=False):
    """Render every theme template for `home`. sandbox=True (building a skel or a staged home) puts
    stubs for hyprctl/dms/pgrep/pkill first in PATH, so nothing reaches a running desktop."""
    import tempfile
    ta = home / ".local/bin/theme-apply"
    exe = str(ta) if ta.exists() else shutil.which("theme-apply")
    if not exe:
        return "theme-apply missing"
    env = dict(os.environ, HOME=str(home))
    tmp = None
    if sandbox:
        tmp = tempfile.mkdtemp(prefix="arclight-themebox-")
        for tool in ("hyprctl", "dms", "pgrep", "pkill", "qs", "killall", "notify-send", "makoctl", "systemctl"):
            stub = Path(tmp) / tool
            stub.write_text("#!/bin/sh\nexit 1\n")
            stub.chmod(0o755)
        env["PATH"] = tmp + ":" + env.get("PATH", "")
        for k in ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"):
            env.pop(k, None)
    try:
        r = subprocess.run([sys.executable, exe, slug], env=env, capture_output=True, text=True, timeout=180)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return f"theme-apply {slug}: rc={r.returncode} {(r.stdout.strip().splitlines() or [''])[0][:80]}" + \
        (f" ERR {r.stderr.strip()[-200:]}" if r.returncode else "")


# Eclipse motion for the shell (DankMaterialShell: bar popouts, launcher, notifications, modals). DMS times
# these in milliseconds (Qt animations on the real clock). Custom 360 ms base instead of the stock 250 ms
# "Short"; the Depth effect (popouts grow out of 88% with a small travel) and Material's expressive spring
# curves; notifications 380 ms. The values a home had before are kept in ~/.local/state/arclight/
# dms-motion-prev.json (once), so the "Eclipse look off" switch can put them back.
DMS_MOTION = {"animationSpeed": 4, "customAnimationDuration": 360, "syncComponentAnimationSpeeds": True,
              "animationVariant": 0, "motionEffect": 2, "reduceMotion": False,
              "notificationAnimationSpeed": 4, "notificationCustomAnimationDuration": 380}


def dms_motion(home):
    f = home / ".config/DankMaterialShell/settings.json"
    if not f.exists():
        return "no DMS settings"
    try:
        s = json.loads(f.read_text())
    except ValueError:
        return "DMS settings unreadable: left alone"
    prev = home / ".local/state/arclight/dms-motion-prev.json"
    if not prev.exists():
        prev.parent.mkdir(parents=True, exist_ok=True)
        prev.write_text(json.dumps({k: s.get(k) for k in DMS_MOTION}, indent=2))
    live = (shutil.which("dms") and os.environ.get("HOME") == str(home)
            and subprocess.run(["pgrep", "-x", "dms"], capture_output=True).returncode == 0)
    if live:   # a running DMS rewrites settings.json on exit: tell it instead
        for k, v in DMS_MOTION.items():
            subprocess.run(["dms", "ipc", "call", "settings", "set", k, json.dumps(v) if isinstance(v, bool) else str(v)],
                           capture_output=True, timeout=10)
        return "set live (dms ipc)"
    s.update(DMS_MOTION)
    tmp = f.with_suffix(".json.arclight-tmp")
    tmp.write_text(json.dumps(s, indent=2) + "\n")
    os.replace(tmp, f)
    return "written"


GUIDE_MARK_B = "<!-- arclight:begin -->"
GUIDE_MARK_E = "<!-- arclight:end -->"
GUIDE = f"""{GUIDE_MARK_B}
## This machine runs Eclipse OS (AI-native Arch, codename Arclight)

You can operate this computer through the `arclight` MCP tools (or the `arc` CLI). Read
`/etc/arclight/AGENTS.md` once per session for the details. Short version:
- Reading is open. Root work (`packages`, `services`, system `files`, `machine`, `run root=true`, `arc root CMD`)
  asks the person at the computer for their administrator password. Never type or ask for it yourself.
- Every setting: `settings search` / `settings set` (applies live + persists). Prefer it to editing configs.
- Eyes and hands on the whole desktop: `screenshot` (any window, any workspace), `see`, `ui press`,
  `input`, `input_sequence`, `apps`, `games`. Verify every UI action with a new screenshot.
- Everything you do is logged (`history`); file writes and deletes can be reverted (`files revert`).
{GUIDE_MARK_E}
"""


def agent_guides(home):
    done = []
    for f in (home / ".claude/CLAUDE.md", home / ".codex/AGENTS.md"):
        f.parent.mkdir(parents=True, exist_ok=True)
        text = f.read_text() if f.exists() else ""
        text = re.sub(rf"\n?{re.escape(GUIDE_MARK_B)}.*?{re.escape(GUIDE_MARK_E)}\n?", "\n", text, flags=re.S).rstrip("\n")
        f.write_text((text + "\n\n" if text else "") + GUIDE)
        done.append(str(f.relative_to(home)))
    return ", ".join(done)


def register_mcp(home):
    """Claude Code: user-scope MCP server `arclight`. Codex: [mcp_servers.arclight] in config.toml."""
    res = []
    cj = home / ".claude.json"
    try:
        data = json.loads(cj.read_text()) if cj.exists() else {}
    except ValueError:
        data = None
    if data is not None:
        data.setdefault("mcpServers", {})["arclight"] = {"type": "stdio", "command": "arclight-mcp", "args": [], "env": {}}
        tmp = cj.with_suffix(".json.arclight-tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, cj)
        res.append("claude")
    cs = home / ".claude/settings.json"
    cs.parent.mkdir(parents=True, exist_ok=True)
    try:
        s = json.loads(cs.read_text()) if cs.exists() else {}
    except ValueError:
        s = None
    if s is not None:
        perms = s.setdefault("permissions", {})
        perms.setdefault("defaultMode", "bypassPermissions")
        allow = perms.setdefault("allow", [])
        if "mcp__arclight" not in allow:
            allow.append("mcp__arclight")
        s.setdefault("skipDangerousModePermissionPrompt", True)
        cs.write_text(json.dumps(s, indent=2) + "\n")
        res.append("claude-permissions")
    cc = home / ".codex/config.toml"
    cc.parent.mkdir(parents=True, exist_ok=True)
    text = cc.read_text() if cc.exists() else ""
    if "[mcp_servers.arclight]" not in text:
        text = text.rstrip("\n") + ("\n\n" if text else "") + '[mcp_servers.arclight]\ncommand = "arclight-mcp"\nstartup_timeout_sec = 20\ntool_timeout_sec = 3600\n'
    if not re.search(r"^approval_policy\s*=", text, re.M):
        text = 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n' + text
    cc.write_text(text)
    res.append("codex")
    return ", ".join(res)


def ensure_agents(home, allow_network=True):
    """Install Claude Code / Codex for this user if missing (official installers)."""
    out = []
    env = dict(os.environ, HOME=str(home))
    if not (home / ".local/bin/claude").exists() and not shutil.which("claude"):
        if allow_network:
            r = subprocess.run(["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"], env=env,
                               capture_output=True, text=True, timeout=900)
            out.append(f"claude install rc={r.returncode}")
        else:
            out.append("claude missing (offline)")
    if not shutil.which("codex") and not (home / ".local/bin/codex").exists():
        if allow_network and shutil.which("npm"):
            r = subprocess.run(["npm", "install", "-g", "--prefix", str(home / ".local"), "@openai/codex"], env=env,
                               capture_output=True, text=True, timeout=900)
            out.append(f"codex install rc={r.returncode}")
        else:
            out.append("codex missing")
    return ", ".join(out) or "agents present"


# ---------------------------------------------------------------- orchestration

STEPS_BUILD = ["theme", "hyprland", "wallpapers", "wallpaper", "fastfetch", "thunar", "apply_theme"]
STEPS_FIRSTRUN = ["fill", "locklink", "theme", "hyprland", "wallpapers", "fastfetch", "thunar", "dms_motion", "guides", "mcp", "agents"]


def run_steps(home, steps, fresh=False, network=True, placeholder=False, sandbox=False):
    home = Path(home)
    report = {}
    for st in steps:
        try:
            if st == "fill":
                report[st] = f"{fill_home(home)} files"
            elif st == "theme":
                report[st] = install_theme(home)
            elif st == "hyprland":
                report[st] = patch_hyprland(home, fresh=fresh)
            elif st == "wallpapers":
                report[st] = install_wallpapers(home)
            elif st == "wallpaper":
                report[st] = set_wallpaper(home, placeholder=placeholder)
            elif st == "fastfetch":
                report[st] = fastfetch_logo(home)
            elif st == "thunar":
                report[st] = thunar_action(home)
            elif st == "locklink":
                report[st] = fix_lock_link(home)
            elif st == "apply_theme":
                report[st] = apply_theme(home, sandbox=placeholder or sandbox)
            elif st == "dms_motion":
                report[st] = dms_motion(home)
            elif st == "guides":
                report[st] = agent_guides(home)
            elif st == "mcp":
                report[st] = register_mcp(home)
            elif st == "agents":
                report[st] = ensure_agents(home, allow_network=network)
        except Exception as e:
            report[st] = f"FAILED: {type(e).__name__}: {e}"
        log(f"{st}: {report[st]}")
    return report


def _pending_look():
    """The plain look chosen in the installer is applied once, at the first login (it needs the session)."""
    try:
        from .settings.registry import Store
        st = Store()
        if not st.get("look.apply_at_login"):
            return
        st.put("look.apply_at_login", None)
        from . import eclipselook
        from .settings import curated as C
        eclipselook.apply(False, {"theme_get": C._theme_get, "theme_set": C._theme_set,
                                  "wall_get": C._wall_get, "wall_set": C._wall_set})
    except Exception as e:
        log(f"plain look at login: {e}")


def firstrun_main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="arclight-firstrun", description="one-time per-user Arclight setup")
    p.add_argument("--home", default=str(Path.home()))
    p.add_argument("--session", action="store_true", help="called from Hyprland autostart: exit fast when done before")
    p.add_argument("--force", action="store_true")
    p.add_argument("--skel", action="store_true", help="build-time: prepare a skeleton home (no network, fresh machine)")
    p.add_argument("--migrated", action="store_true", help="prepare a migrated (staged) home")
    p.add_argument("--offline", action="store_true")
    a = p.parse_args(argv)
    home = Path(a.home)
    state = home / ".local/state/arclight/firstrun.json"
    # first login of a new install: the intro, then Welcome. Started BEFORE the pending plain look: making the
    # plain wallpaper + theme takes ~30 s, which used to leave the first login blank-ish until the intro jumped
    # in. The look is applied underneath the full-screen intro instead.
    intro = a.session and _intro_once(home)
    if a.session:
        _pending_look()
    if a.skel:
        rep = run_steps(home, ["theme", "hyprland", "wallpapers", "wallpaper", "fastfetch", "thunar", "apply_theme", "dms_motion"], fresh=True, network=False,
                        placeholder=True)
        # theme-apply and its hooks write absolute paths of the build home: turn them back into @HOME@
        for f in home.rglob("*"):
            if f.is_file() and not f.is_symlink():
                try:
                    t = f.read_text()
                except (UnicodeDecodeError, OSError):
                    continue
                if str(home) in t:
                    f.write_text(t.replace(str(home), "@HOME@"))
        print(json.dumps(rep, indent=2))
        return 0
    if a.migrated:
        rep = run_steps(home, ["theme", "hyprland", "wallpapers", "wallpaper", "fastfetch", "thunar", "apply_theme", "dms_motion", "guides", "mcp"],
                        fresh=False, network=False, sandbox=True)
        print(json.dumps(rep, indent=2))
        return 0
    if state.exists() and not a.force:
        try:
            if json.loads(state.read_text()).get("version") == __version__:
                if a.session and not intro:
                    _welcome_once(home)
                return 0
        except ValueError:
            pass
    rep = run_steps(home, STEPS_FIRSTRUN, fresh=not (home / "Projects/arch-ai").exists(), network=not a.offline)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"version": __version__, "time": time.time(), "report": rep}, indent=2))
    if a.session and not intro and not _welcome_once(home):
        subprocess.run(["notify-send", "-a", identity.os_name(), "-i", "arclight", f"{identity.os_name()} is ready",
                        "Super+Shift+A: ask the AI anything.  Super+I: settings."], timeout=5)
    return 0


def _intro_once(home):
    """The genuine first boot of an installed system (the installer left intro-pending in the home): play the
    cinematic intro (apps/intro.py), then the Welcome window. Never on the live USB, never twice: the marker
    is swapped for intro-done BEFORE the intro starts, so a crash can neither replay it nor block the desktop
    (Welcome opens whatever the intro's exit status). True when it was started."""
    st = home / ".local/state/arclight"
    if Path("/run/archiso").exists() or not (st / "intro-pending").exists() or not shutil.which("arclight-intro"):
        return False
    try:
        (st / "intro-pending").unlink()
        (st / "intro-done").write_text(time.strftime("%Y-%m-%d %H:%M:%S first boot\n"))
    except OSError as e:
        log(f"intro: marker not cleared ({e}); skipping the intro")
        return False
    subprocess.Popen(["sh", "-c", "arclight-intro --first-boot; exec arclight-welcome --once"], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _welcome_once(home):
    """First login of a new install (or the live USB): the welcome window, once. True when it was opened."""
    if shutil.which("arclight-welcome") and not (home / ".local/state/arclight/welcome-shown").exists():
        subprocess.Popen(["arclight-welcome", "--once"], start_new_session=True)
        return True
    return False


def stop_main(argv=None):
    """arclight-stop: panic stop for every AI driving the desktop."""
    from . import client as C
    try:
        C.call("stop")
    except Exception as e:
        log(f"session stop: {e}")
    co = Path.home() / ".local/bin/claude-orange"
    if co.exists():
        subprocess.run([str(co), "--stop"], timeout=10)
    subprocess.run(["pkill", "-INT", "-f", "arclight-ask-agent"], timeout=5)
    subprocess.run(["hyprctl", "notify", "1", "2500", "rgb(e0303c)", "AI input stopped"], timeout=5)
    return 0
