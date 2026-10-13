"""Exact record of a running Arch system: packages, services, boot, /etc, home, toolchains.

Read-only and root-free. Secrets are never read: for keys and tokens only their
presence is recorded. Every probe is isolated, so one failure is recorded in
`errors` instead of stopping the export.
"""
import datetime
import glob
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import socket
import subprocess
from pathlib import Path

VERSION = 1
HOME = Path.home()


def sh(cmd, timeout=120, ok_codes=(0,)):
    """Run a command, return stdout text ('' when the tool is missing)."""
    if isinstance(cmd, str):
        cmd = ["bash", "-c", cmd]
    if not shutil.which(cmd[0]):
        return ""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode not in ok_codes:
        raise RuntimeError(f"{' '.join(cmd)} -> {p.returncode}: {p.stderr.strip()[:300]}")
    return p.stdout


def lines(text):
    return [l for l in text.splitlines() if l.strip()]


def du_bytes(path, timeout=900):
    """Disk usage in bytes (one filesystem); None when it cannot be measured."""
    try:
        out = subprocess.run(["du", "-sxB1", str(path)], capture_output=True, text=True, timeout=timeout).stdout
        return int(out.split()[0]) if out else None
    except Exception:
        return None


def count_files(path, timeout=300):
    try:
        out = subprocess.run(["bash", "-c", f"find {sh_quote(path)} -xdev -type f 2>/dev/null | wc -l"],
                             capture_output=True, text=True, timeout=timeout).stdout
        return int(out.strip())
    except Exception:
        return None


def sh_quote(p):
    return "'" + str(p).replace("'", "'\\''") + "'"


def human(n):
    if n is None:
        return "?"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


# ---------------------------------------------------------------- probes

def probe_meta():
    return {
        "manifest_version": VERSION,
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "hostname": socket.gethostname(),
        "user": pwd.getpwuid(os.getuid()).pw_name,
        "home": str(HOME),
        "kernel": platform.release(),
        "os_release": dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', Path("/etc/os-release").read_text(), re.M)),
    }


def probe_hardware():
    hw = {}
    lscpu = sh(["lscpu", "-J"])
    if lscpu:
        fields = {f["field"].rstrip(":"): f.get("data") for f in json.loads(lscpu)["lscpu"]}
        hw["cpu"] = {k: fields.get(k) for k in ("Model name", "CPU(s)", "Thread(s) per core", "Architecture")}
    mem = Path("/proc/meminfo").read_text()
    hw["memory_kib"] = int(re.search(r"MemTotal:\s+(\d+)", mem).group(1))
    hw["gpu"] = lines(sh("lspci -nn | grep -Ei 'vga|3d|display'", ok_codes=(0, 1)))
    hw["dmi"] = {}
    for k in ("sys_vendor", "product_name", "board_name", "bios_version"):
        f = Path("/sys/class/dmi/id") / k
        if f.exists():
            try:
                hw["dmi"][k] = f.read_text().strip()
            except PermissionError:
                pass
    hw["firmware"] = "uefi" if Path("/sys/firmware/efi").exists() else "bios"
    hw["secure_boot"] = sh("bootctl status 2>/dev/null | sed -n 's/^ *Secure Boot: //p'", ok_codes=(0, 1)).strip()
    hw["monitors"] = []
    mons = sh(["hyprctl", "monitors", "all", "-j"], ok_codes=(0, 1))
    if mons:
        for m in json.loads(mons):
            hw["monitors"].append({k: m.get(k) for k in ("name", "description", "make", "model", "width",
                                                          "height", "refreshRate", "scale", "mirrorOf")})
    hw["input_devices"] = []
    devs = sh(["hyprctl", "devices", "-j"], ok_codes=(0, 1))
    if devs:
        d = json.loads(devs)
        hw["input_devices"] = sorted({x["name"] for k in ("mice", "keyboards", "tablets", "touch") for x in d.get(k, [])})
    return hw


def probe_storage():
    st = {}
    st["lsblk"] = json.loads(sh(["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,FSTYPE,UUID,PARTUUID,LABEL,MOUNTPOINTS,MODEL"]))
    st["findmnt"] = json.loads(sh(["findmnt", "-J", "--real", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"]))
    st["fstab"] = Path("/etc/fstab").read_text()
    df = {}
    for target in ("/", "/boot", "/home"):
        try:
            u = shutil.disk_usage(target)
            df[target] = {"total": u.total, "used": u.used, "free": u.free}
        except OSError:
            pass
    st["usage"] = df
    st["swap"] = lines(sh(["swapon", "--show=NAME,TYPE,SIZE", "--noheadings"]))
    return st


def probe_boot():
    b = {"cmdline": Path("/proc/cmdline").read_text().strip()}
    if Path("/boot/grub/grub.cfg").exists() or Path("/etc/default/grub").exists():
        b["loader"] = "grub"
        try:
            b["etc_default_grub"] = Path("/etc/default/grub").read_text()
        except OSError:
            pass
    elif Path("/boot/loader/loader.conf").exists():
        b["loader"] = "systemd-boot"
    try:
        b["efi_entries"] = lines(sh(["efibootmgr"], ok_codes=(0, 1)))
    except Exception:
        b["efi_entries"] = []
    try:
        conf = Path("/etc/mkinitcpio.conf").read_text()
        b["mkinitcpio"] = {k: re.search(rf"^{k}=\((.*)\)", conf, re.M).group(1)
                           for k in ("MODULES", "BINARIES", "FILES", "HOOKS") if re.search(rf"^{k}=\(", conf, re.M)}
    except OSError:
        pass
    b["kernels"] = sorted(p.name for p in Path("/boot").glob("vmlinuz-*"))
    return b


def parse_pkg_lines(text):
    out = []
    for l in lines(text):
        name, ver = l.split()[:2]
        out.append({"name": name, "version": ver})
    return out


def probe_packages():
    p = {}
    p["explicit_native"] = parse_pkg_lines(sh(["pacman", "-Qen"]))
    p["explicit_foreign"] = parse_pkg_lines(sh(["pacman", "-Qem"], ok_codes=(0, 1)))
    p["all"] = parse_pkg_lines(sh(["pacman", "-Q"]))
    p["foreign_all"] = parse_pkg_lines(sh(["pacman", "-Qm"], ok_codes=(0, 1)))
    p["orphans"] = lines(sh(["pacman", "-Qtdq"], ok_codes=(0, 1)))
    conf = Path("/etc/pacman.conf").read_text()
    p["repos"] = re.findall(r"^\[(?!options\])([^\]]+)\]", conf, re.M)
    try:
        mirrors = [l for l in Path("/etc/pacman.d/mirrorlist").read_text().splitlines() if l.startswith("Server")]
        p["mirrors"] = mirrors[:10]
    except OSError:
        p["mirrors"] = []
    groups = {}
    for l in lines(sh(["pacman", "-Qg"], ok_codes=(0, 1))):
        g, n = l.split()
        groups.setdefault(g, []).append(n)
    p["groups"] = groups
    return p


def probe_services():
    s = {}

    def units(args):
        out = sh(["systemctl", *args, "list-unit-files", "--no-legend", "--no-pager"], ok_codes=(0, 1))
        res = {}
        for l in lines(out):
            parts = l.split()
            if len(parts) >= 2:
                res[parts[0]] = parts[1]
        return res

    sysu = units([])
    useru = units(["--user"])
    s["system_enabled"] = sorted(u for u, st in sysu.items() if st == "enabled")
    s["system_masked"] = sorted(u for u, st in sysu.items() if st == "masked")
    s["user_enabled"] = sorted(u for u, st in useru.items() if st == "enabled")
    s["user_masked"] = sorted(u for u, st in useru.items() if st == "masked")
    s["system_failed"] = lines(sh(["systemctl", "--failed", "--no-legend", "--plain", "--no-pager"], ok_codes=(0, 1)))
    s["user_failed"] = lines(sh(["systemctl", "--user", "--failed", "--no-legend", "--plain", "--no-pager"], ok_codes=(0, 1)))
    s["timers"] = lines(sh(["systemctl", "list-timers", "--all", "--no-legend", "--no-pager"], ok_codes=(0, 1)))
    s["user_unit_files"] = sorted(str(p.relative_to(HOME)) for p in (HOME / ".config/systemd/user").rglob("*") if p.is_file() or p.is_symlink())
    s["etc_unit_files"] = sorted(str(p) for p in Path("/etc/systemd/system").rglob("*")
                                 if (p.is_file() or p.is_symlink()) and not p.parent.name.endswith((".wants", ".requires")))
    return s


def probe_etc():
    """/etc files changed from package defaults, and /etc files no package owns."""
    modified, unreadable = [], []
    owned = set()
    for desc in glob.glob("/var/lib/pacman/local/*/files"):
        pkg = Path(desc).parent.name
        section = None
        for l in Path(desc).read_text(errors="replace").splitlines():
            if l.startswith("%"):
                section = l
                continue
            if not l:
                continue
            if section == "%FILES%":
                owned.add("/" + l.rstrip("/"))
            elif section == "%BACKUP%":
                path, md5 = l.rsplit("\t", 1)
                f = Path("/") / path
                try:
                    cur = hashlib.md5(f.read_bytes()).hexdigest()
                except FileNotFoundError:
                    modified.append({"path": str(f), "package": pkg, "state": "missing"})
                    continue
                except (PermissionError, IsADirectoryError):
                    unreadable.append(str(f))
                    continue
                if cur != md5:
                    modified.append({"path": str(f), "package": pkg, "state": "modified"})
    unowned = []
    for root, dirs, files in os.walk("/etc", onerror=lambda e: unreadable.append(e.filename)):
        for name in files:
            p = os.path.join(root, name)
            if p not in owned and not os.path.islink(p):
                unowned.append(p)
        for name in dirs:
            p = os.path.join(root, name)
            if os.path.islink(p) and p not in owned:
                unowned.append(p)
    return {"modified_backup_files": sorted(modified, key=lambda x: x["path"]),
            "unowned_files": sorted(unowned), "unreadable": sorted(set(unreadable))}


def probe_system():
    s = {}
    s["timedatectl"] = dict(l.strip().split(": ", 1) for l in lines(sh(["timedatectl"])) if ": " in l)
    s["localectl"] = dict(l.strip().split(": ", 1) for l in lines(sh(["localectl"])) if ": " in l)
    for f in ("/etc/locale.conf", "/etc/vconsole.conf", "/etc/hostname", "/etc/locale.gen"):
        try:
            text = Path(f).read_text()
            if f == "/etc/locale.gen":
                text = "\n".join(l for l in text.splitlines() if l and not l.startswith("#"))
            s[f] = text
        except OSError:
            pass
    users = []
    for pw in pwd.getpwall():
        if pw.pw_uid >= 1000 and pw.pw_uid < 60000:
            groups = sh(["id", "-nG", pw.pw_name]).split()
            users.append({"name": pw.pw_name, "uid": pw.pw_uid, "home": pw.pw_dir, "shell": pw.pw_shell, "groups": groups})
    s["users"] = users
    s["sudoers_d"] = sorted(os.listdir("/etc/sudoers.d")) if os.access("/etc/sudoers.d", os.R_OK) else "unreadable"
    s["polkit_rules"] = sorted(glob.glob("/etc/polkit-1/rules.d/*"))
    s["udev_rules"] = sorted(glob.glob("/etc/udev/rules.d/*"))
    s["modules_load"] = {f: Path(f).read_text() for f in glob.glob("/etc/modules-load.d/*.conf")}
    s["sysctl_d"] = sorted(glob.glob("/etc/sysctl.d/*"))
    nm = sh(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,AUTOCONNECT", "connection", "show"], ok_codes=(0, 1, 8, 10))
    s["network_connections"] = [dict(zip(("name", "type", "device", "autoconnect"), l.split(":"))) for l in lines(nm)]
    try:
        s["crontab"] = sh(["crontab", "-l"], ok_codes=(0, 1))
    except Exception:
        s["crontab"] = ""
    return s


def probe_desktop():
    d = {}
    v = sh(["hyprctl", "version", "-j"], ok_codes=(0, 1))
    if v:
        j = json.loads(v)
        d["hyprland"] = {k: j.get(k) for k in ("tag", "commit", "branch")}
    d["hypr_config_files"] = sorted(str(p.relative_to(HOME)) for p in (HOME / ".config/hypr").glob("*")
                                    if p.is_file() and ".bak" not in p.name)
    plugins = sh(["hyprctl", "plugin", "list", "-j"], ok_codes=(0, 1))
    try:
        d["hypr_plugins"] = [p.get("name") for p in json.loads(plugins)] if plugins.strip().startswith("[") else plugins.strip()
    except json.JSONDecodeError:
        d["hypr_plugins"] = plugins.strip()
    d["running_shell"] = "dms" if sh("pgrep -x dms", ok_codes=(0, 1)).strip() else (
        "arthur-shell" if "arthur" in sh("pgrep -a qs", ok_codes=(0, 1)) else "none")
    cur = HOME / ".config/theme/current"
    d["theme"] = cur.read_text().strip() if cur.exists() else None
    d["theme_tokens"] = sorted(p.stem for p in (HOME / ".config/theme/tokens").glob("*.json"))
    cfg = HOME / ".config"
    if (cfg / ".git").exists():
        d["config_git"] = {
            "head": sh(["git", "-C", str(cfg), "log", "-1", "--format=%H %ad %s", "--date=iso"]).strip(),
            "commits": int(sh(["git", "-C", str(cfg), "rev-list", "--count", "HEAD"]).strip() or 0),
            "dirty_files": len(lines(sh(["git", "-C", str(cfg), "status", "--porcelain"]))),
        }
    d["cursor"] = os.environ.get("XCURSOR_THEME")
    d["gtk_theme"] = os.environ.get("GTK_THEME")
    d["fonts_user"] = sorted(p.name for p in (HOME / ".local/share/fonts").rglob("*") if p.is_file()) if (HOME / ".local/share/fonts").exists() else []
    d["font_families"] = sorted(set(lines(sh("fc-list : family | cut -d, -f1", ok_codes=(0, 1)))))
    d["icon_themes_user"] = sorted({p.name for base in (HOME / ".icons", HOME / ".local/share/icons") if base.exists() for p in base.iterdir()})
    d["desktop_entries_user"] = sorted(p.name for p in (HOME / ".local/share/applications").glob("*.desktop"))
    try:
        d["wallpapers"] = sorted(p.name for p in (HOME / "Pictures/wallpapers").iterdir())
    except OSError:
        d["wallpapers"] = []
    d["mimeapps_default_browser"] = sh(["xdg-settings", "get", "default-web-browser"], ok_codes=(0, 1, 2)).strip()
    return d


def probe_home(deep_dirs=(".local/share", ".config", "Projects", ".cache", "vms")):
    """Top-level home inventory with sizes, plus one level deeper for the big containers."""
    inv = []

    def entry(p):
        st = p.lstat()
        kind = "symlink" if p.is_symlink() else ("dir" if p.is_dir() else "file")
        e = {"path": str(p.relative_to(HOME)), "kind": kind, "mtime": int(st.st_mtime)}
        if kind == "symlink":
            e["target"] = os.readlink(p)
            e["bytes"] = 0
        elif kind == "dir":
            e["bytes"] = du_bytes(p)
        else:
            e["bytes"] = st.st_size
        return e

    for p in sorted(HOME.iterdir()):
        try:
            inv.append(entry(p))
        except OSError as e:
            inv.append({"path": p.name, "error": str(e)})
    deep = {}
    for d in deep_dirs:
        base = HOME / d
        if not base.is_dir() or base.is_symlink():
            continue
        rows = []
        for p in sorted(base.iterdir()):
            try:
                rows.append(entry(p))
            except OSError as e:
                rows.append({"path": str(p.relative_to(HOME)), "error": str(e)})
        deep[d] = sorted(rows, key=lambda r: -(r.get("bytes") or 0))
    total = du_bytes(HOME, timeout=1800)
    return {"total_bytes": total, "top": inv, "deep": deep}


def probe_projects():
    out = []
    base = HOME / "Projects"
    if not base.is_dir():
        return out
    for p in sorted(base.iterdir()):
        if not p.is_dir() or p.is_symlink():
            continue
        e = {"name": p.name}
        if (p / ".git").exists():
            g = lambda *a: sh(["git", "-C", str(p), *a], ok_codes=(0, 1, 128)).strip()
            e["git"] = {
                "branch": g("rev-parse", "--abbrev-ref", "HEAD"),
                "head": g("log", "-1", "--format=%h %ad %s", "--date=short"),
                "remotes": lines(g("remote", "-v")),
                "dirty_files": len(lines(g("status", "--porcelain"))),
            }
        kinds = []
        for marker, kind in (("project.godot", "godot"), ("package.json", "node"), ("pyproject.toml", "python"),
                             ("Cargo.toml", "rust"), ("go.mod", "go"), ("Assets", "unity"), ("CMakeLists.txt", "cmake")):
            if (p / marker).exists():
                kinds.append(kind)
        e["kinds"] = kinds
        out.append(e)
    return out


def probe_toolchains():
    t = {}
    t["local_bin"] = []
    for base in (HOME / ".local/bin", HOME / "bin"):
        if base.is_dir():
            for p in sorted(base.iterdir()):
                if ".bak" in p.name or p.name == "__pycache__":
                    continue
                e = {"path": str(p.relative_to(HOME))}
                if p.is_symlink():
                    e["link"] = os.readlink(p)
                else:
                    e["bytes"] = p.stat().st_size
                t["local_bin"].append(e)
    t["local_opt"] = sorted(p.name for p in (HOME / ".local/opt").iterdir()) if (HOME / ".local/opt").is_dir() else []
    t["applications_dir"] = sorted(p.name for p in (HOME / "Applications").iterdir()) if (HOME / "Applications").is_dir() else []
    t["uv_tools"] = lines(sh(["uv", "tool", "list"], ok_codes=(0, 1, 2)))
    try:
        t["npm_global"] = lines(sh("npm ls -g --depth=0 --parseable 2>/dev/null | tail -n +2 | xargs -r -n1 basename", ok_codes=(0, 1)))
    except Exception:
        t["npm_global"] = []
    t["cargo_installed"] = lines(sh(["cargo", "install", "--list"], ok_codes=(0, 1, 101)))
    t["pip_user"] = lines(sh("python3 -m pip list --user --format=freeze 2>/dev/null", ok_codes=(0, 1)))
    t["flatpak"] = lines(sh(["flatpak", "list", "--app", "--columns=application"], ok_codes=(0, 1)))
    t["versions"] = {}
    for tool in ("python3", "node", "go", "rustc", "java", "godot", "claude", "codex", "ollama", "blender", "gcc"):
        if shutil.which(tool):
            try:
                t["versions"][tool] = sh([tool, "--version"], timeout=20, ok_codes=(0, 1, 2)).strip().splitlines()[0][:120]
            except Exception as e:
                t["versions"][tool] = f"error: {e}"[:120]
    return t


def probe_games():
    g = {"steam_libraries": [], "steam_games": []}
    steam = HOME / ".local/share/Steam"
    vdf = steam / "steamapps/libraryfolders.vdf"
    libs = []
    if vdf.exists():
        libs = re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="replace"))
    g["steam_libraries"] = libs
    for lib in libs:
        for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            text = Path(acf).read_text(errors="replace")
            get = lambda k: (re.search(rf'"{k}"\s+"([^"]*)"', text) or [None, None])[1]
            g["steam_games"].append({"appid": get("appid"), "name": get("name"), "installdir": get("installdir"),
                                     "bytes": int(get("SizeOnDisk") or 0), "library": lib})
    g["godot_projects"] = sorted(str(p.parent.relative_to(HOME)) for p in HOME.glob("Projects/*/project.godot"))
    g["minecraft"] = {k: (HOME / v).exists() for k, v in (("dotminecraft", ".minecraft"), ("prism", ".local/share/PrismLauncher"),
                                                          ("modrinth", ".local/share/ModrinthApp"))}
    return g


def probe_ai():
    a = {}
    cj = HOME / ".claude.json"
    if cj.exists():
        try:
            j = json.loads(cj.read_text())
            a["claude_mcp_user"] = {k: {"command": v.get("command"), "args": v.get("args"), "type": v.get("type", "stdio"),
                                        "env_keys": sorted((v.get("env") or {}).keys())}
                                    for k, v in (j.get("mcpServers") or {}).items()}
        except Exception as e:
            a["claude_mcp_user"] = f"error: {e}"
    cs = HOME / ".claude/settings.json"
    if cs.exists():
        try:
            j = json.loads(cs.read_text())
            a["claude_settings_keys"] = sorted(j.keys())
            a["claude_permissions_default_mode"] = (j.get("permissions") or {}).get("defaultMode")
        except Exception as e:
            a["claude_settings_keys"] = f"error: {e}"
    a["claude_md_present"] = (HOME / ".claude/CLAUDE.md").exists()
    a["claude_memory_files"] = len(list((HOME / ".claude/projects").glob("*/memory/*.md")))
    cc = HOME / ".codex/config.toml"
    if cc.exists():
        text = cc.read_text()
        a["codex_model"] = (re.search(r'^model\s*=\s*"([^"]+)"', text, re.M) or [None, None])[1]
        a["codex_mcp_servers"] = re.findall(r"^\[mcp_servers\.([^\]]+)\]", text, re.M)
    a["ollama_models"] = lines(sh(["ollama", "list"], ok_codes=(0, 1)))[1:]
    return a


def probe_secrets_presence():
    """Never reads secret contents; records only whether these exist so migration copies them."""
    names = [".ssh", ".gnupg", ".local/share/keyrings", ".config/meshy/api_key", ".codex/auth.json",
             ".claude/.credentials.json", ".config/obs-rec", ".pki", ".netrc", ".git-credentials", ".config/gh"]
    return {n: (HOME / n).exists() for n in names}


PROBES = [
    ("meta", probe_meta), ("hardware", probe_hardware), ("storage", probe_storage), ("boot", probe_boot),
    ("packages", probe_packages), ("services", probe_services), ("etc", probe_etc), ("system", probe_system),
    ("desktop", probe_desktop), ("projects", probe_projects), ("toolchains", probe_toolchains),
    ("games", probe_games), ("ai", probe_ai), ("secrets_present", probe_secrets_presence), ("home", probe_home),
]


def collect(progress=None, skip=()):
    data, errors = {}, {}
    for name, fn in PROBES:
        if name in skip:
            continue
        if progress:
            progress(name)
        try:
            data[name] = fn()
        except Exception as e:  # one broken probe must not stop the export
            errors[name] = f"{type(e).__name__}: {e}"
    data["errors"] = errors
    return data


# ---------------------------------------------------------------- writers

def write(data, outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(data, indent=1, sort_keys=False) + "\n")
    pk = data.get("packages", {})
    (out / "packages-explicit-native.txt").write_text("".join(f"{p['name']}\n" for p in pk.get("explicit_native", [])))
    (out / "packages-explicit-foreign.txt").write_text("".join(f"{p['name']}\n" for p in pk.get("explicit_foreign", [])))
    (out / "packages-all-versions.txt").write_text("".join(f"{p['name']} {p['version']}\n" for p in pk.get("all", [])))
    sv = data.get("services", {})
    (out / "services-system-enabled.txt").write_text("".join(f"{u}\n" for u in sv.get("system_enabled", [])))
    (out / "services-user-enabled.txt").write_text("".join(f"{u}\n" for u in sv.get("user_enabled", [])))
    (out / "MANIFEST.md").write_text(render_md(data))
    return out


def render_md(d):
    m, hw, st, b = d.get("meta", {}), d.get("hardware", {}), d.get("storage", {}), d.get("boot", {})
    pk, sv, de, home = d.get("packages", {}), d.get("services", {}), d.get("desktop", {}), d.get("home", {})
    o = []
    w = o.append
    w(f"# System manifest: {m.get('hostname')}\n")
    w(f"Exported {m.get('created')} by `arclight-migrate manifest` (v{m.get('manifest_version')}). "
      f"Machine-readable version: `manifest.json`.\n")
    w("## Machine\n")
    cpu = (hw.get("cpu") or {}).get("Model name")
    w(f"- {hw.get('dmi', {}).get('sys_vendor', '?')} {hw.get('dmi', {}).get('product_name', '?')}, {cpu}")
    w(f"- RAM {human((hw.get('memory_kib') or 0) * 1024)}, firmware {hw.get('firmware')}, Secure Boot {hw.get('secure_boot') or '?'}")
    for g in hw.get("gpu", []):
        w(f"- GPU: {g}")
    for mon in hw.get("monitors", []):
        w(f"- Monitor {mon['name']}: {mon['width']}x{mon['height']} @ {mon['refreshRate']:.0f} Hz, scale {mon['scale']}"
          + (f", mirrors {mon['mirrorOf']}" if mon.get("mirrorOf") not in (None, "none") else ""))
    w(f"- Kernel {m.get('kernel')}, boot loader {b.get('loader')}, cmdline `{b.get('cmdline')}`\n")
    w("## Storage\n")
    for k, u in st.get("usage", {}).items():
        w(f"- `{k}`: {human(u['used'])} used of {human(u['total'])}, {human(u['free'])} free")
    w("")
    w("## Packages\n")
    w(f"- {len(pk.get('all', []))} installed, {len(pk.get('explicit_native', []))} explicit native, "
      f"{len(pk.get('explicit_foreign', []))} explicit foreign (AUR), repos: {', '.join(pk.get('repos', []))}\n")
    w("Explicit native: " + " ".join(f"`{p['name']}`" for p in pk.get("explicit_native", [])) + "\n")
    w("Explicit foreign (AUR): " + " ".join(f"`{p['name']}`" for p in pk.get("explicit_foreign", [])) + "\n")
    w("## Services\n")
    w("System enabled: " + ", ".join(sv.get("system_enabled", [])) + "\n")
    w("User enabled: " + ", ".join(sv.get("user_enabled", [])) + "\n")
    if sv.get("system_failed") or sv.get("user_failed"):
        w("Failed now: " + "; ".join(sv.get("system_failed", []) + sv.get("user_failed", [])) + "\n")
    etc = d.get("etc", {})
    w("## /etc\n")
    w(f"{len(etc.get('modified_backup_files', []))} package config files changed from defaults, "
      f"{len(etc.get('unowned_files', []))} files owned by no package, {len(etc.get('unreadable', []))} unreadable without root.\n")
    for f in etc.get("modified_backup_files", []):
        w(f"- `{f['path']}` ({f['package']}, {f['state']})")
    w("")
    w("## Desktop\n")
    w(f"- Hyprland {(de.get('hyprland') or {}).get('tag')}, shell running: {de.get('running_shell')}, theme: {de.get('theme')}")
    w(f"- Hyprland config files: {', '.join(de.get('hypr_config_files', []))}")
    if de.get("config_git"):
        cg = de["config_git"]
        w(f"- `~/.config` git: {cg['commits']} commits, {cg['dirty_files']} uncommitted, HEAD {cg['head']}")
    w(f"- Wallpapers: {len(de.get('wallpapers', []))}, theme tokens: {', '.join(de.get('theme_tokens', []))}\n")
    w("## Home\n")
    w(f"Total {human(home.get('total_bytes'))}.\n")
    w("| Path | Kind | Size |\n|---|---|---|")
    for e in sorted(home.get("top", []), key=lambda r: -(r.get("bytes") or 0)):
        w(f"| `{e['path']}` | {e.get('kind', '?')} | {human(e.get('bytes'))} |")
    w("")
    for k, rows in home.get("deep", {}).items():
        w(f"### `~/{k}` (largest first)\n")
        w("| Path | Size |\n|---|---|")
        for e in rows[:40]:
            w(f"| `{e['path']}` | {human(e.get('bytes'))} |")
        if len(rows) > 40:
            w(f"| ... {len(rows) - 40} more | |")
        w("")
    w("## Projects\n")
    for p in d.get("projects", []):
        g = p.get("git") or {}
        w(f"- **{p['name']}** {('[' + ', '.join(p['kinds']) + ']') if p['kinds'] else ''} "
          + (f"git `{g.get('branch')}` {g.get('head')}" + (f", {g['dirty_files']} uncommitted" if g.get('dirty_files') else "") if g else "(no git)"))
    w("")
    gm = d.get("games", {})
    w("## Games\n")
    for gg in sorted(gm.get("steam_games", []), key=lambda x: x.get("name") or ""):
        w(f"- Steam {gg['appid']}: {gg['name']} ({human(gg['bytes'])})")
    for gp in gm.get("godot_projects", []):
        w(f"- Godot project: `{gp}`")
    w("")
    tc = d.get("toolchains", {})
    w("## Toolchains and user-local software\n")
    for k, v in tc.get("versions", {}).items():
        w(f"- {k}: {v}")
    w(f"- `~/.local/opt`: {', '.join(tc.get('local_opt', []))}")
    w(f"- uv tools: {len(tc.get('uv_tools', []))} lines, npm -g: {', '.join(tc.get('npm_global', []))}")
    w(f"- `~/.local/bin` + `~/bin`: {len(tc.get('local_bin', []))} entries\n")
    ai = d.get("ai", {})
    w("## AI tooling\n")
    w(f"- Claude Code MCP servers (user): {', '.join((ai.get('claude_mcp_user') or {}).keys()) if isinstance(ai.get('claude_mcp_user'), dict) else ai.get('claude_mcp_user')}")
    w(f"- Claude permissions default mode: {ai.get('claude_permissions_default_mode')}")
    w(f"- Codex model: {ai.get('codex_model')}, Codex MCP servers: {', '.join(ai.get('codex_mcp_servers', []))}")
    w(f"- Ollama models: {len(ai.get('ollama_models', []))}\n")
    w("## Secrets (presence only, contents never read)\n")
    for k, v in d.get("secrets_present", {}).items():
        w(f"- `~/{k}`: {'present' if v else 'absent'}")
    w("")
    if d.get("errors"):
        w("## Probe errors\n")
        for k, v in d["errors"].items():
            w(f"- {k}: {v}")
    return "\n".join(o) + "\n"
