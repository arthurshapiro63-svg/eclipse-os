"""The operating system's name. The owner chooses it during install (required step in the advanced
install); "Eclipse OS" is only the default (Arclight is the codename and the internal name: commands,
packages and paths keep it). The name flows into os-release (so fastfetch, hostnamectl,
GNOME/KDE-style "About" pages show it), the login banner, the boot menu and the EFI boot entry.

  arclight-identity                       show the current identity
  arclight-identity --name "Voltaire OS"  rename the OS (root)
  arclight-identity --reapply             rewrite derived files from /etc/arclight/identity.json
                                          (pacman hook after the filesystem package updates)
"""
import json
import os
import re
import sys
from pathlib import Path

from . import __version__ as _VERSION

# "version" always comes from the installed eclipse-os-core (never from identity.json), so an update
# changes os-release too; the name and the rest are the user's.
DEFAULT = {"name": "Eclipse OS", "version": _VERSION, "codename": "Arclight", "id": "eclipse",
           "tagline": "AI-native Arch", "accent": "38;2;91;134;200"}


def path(root="/"):
    return Path(root) / "etc/arclight/identity.json"


def load(root="/"):
    d = dict(DEFAULT)
    try:
        d.update(json.loads(path(root).read_text()))
    except (OSError, ValueError):
        pass
    d["version"] = DEFAULT["version"]
    return d


def os_name(root="/"):
    """The name the user chose at install (identity.json, else os-release NAME), else the default."""
    try:
        n = json.loads(path(root).read_text()).get("name")
        if n:
            return n
    except (OSError, ValueError):
        pass
    try:
        m = re.search(r'^NAME="?([^"\n]+)"?$', (Path(root) / "etc/os-release").read_text(), re.M)
        # a plain Arch os-release (no identity yet) does not count
        if m and m.group(1) != "Arch Linux":
            return m.group(1)
    except OSError:
        pass
    return DEFAULT["name"]


def short_name(name=None):
    """'Eclipse OS' -> 'Eclipse' for labels like 'Ask Eclipse' / 'Eclipse Settings'."""
    n = (name or os_name()).strip()
    s = re.sub(r"\s+(OS|Linux)$", "", n, flags=re.I).strip()
    return s or n


def valid_name(name):
    name = (name or "").strip()
    if not name or len(name) > 40:
        return False
    return bool(re.fullmatch(r"[\w .+\-]+", name, re.UNICODE)) and not name.startswith(("-", "."))


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "arclight"


def os_release(d):
    pretty = f"{d['name']} {d.get('version', '')}".strip()
    return (f'NAME="{d["name"]}"\n'
            f'PRETTY_NAME="{pretty}"\n'
            f'ID={d.get("id", DEFAULT["id"])}\n'
            f'ID_LIKE=arch\n'
            f'BUILD_ID=rolling\n'
            f'VERSION_ID={d.get("version", DEFAULT["version"])}\n'
            f'VERSION_CODENAME={slug(d.get("codename", "ion"))}\n'
            f'ANSI_COLOR="{d.get("accent", DEFAULT["accent"])}"\n'
            f'HOME_URL="file:///usr/share/doc/arclight"\n'
            f'DOCUMENTATION_URL="file:///etc/arclight/AGENTS.md"\n'
            f'LOGO=arclight\n')


def issue(d):
    return (f"\\e[{d.get('accent', DEFAULT['accent'])}m  ▲ \\e[1;97m{d['name']}\\e[0m  "
            f"\\e[38;2;138;151;174m{d.get('tagline', '')} · \\n · \\l\\e[0m\n\n")


def apply(d, root="/"):
    """Write identity.json and every derived file under `root` (works on a target being installed)."""
    r = Path(root)
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2) + "\n")
    osr = r / "etc/os-release"
    if osr.is_symlink() or osr.exists():
        osr.unlink()
    osr.write_text(os_release(d))
    (r / "etc/issue").write_text(issue(d))
    rel = r / "etc/arclight/release"
    rel.write_text(f"{d['name']} {d.get('version', '')} (codename {d.get('codename', '')})\n")
    lsb = r / "etc/lsb-release"
    lsb.write_text(f'DISTRIB_ID="{d.get("id", DEFAULT["id"])}"\nDISTRIB_RELEASE="{d.get("version", "")}"\n'
                   f'DISTRIB_DESCRIPTION="{d["name"]}"\n')
    return {"identity": d, "files": ["etc/arclight/identity.json", "etc/os-release", "etc/issue", "etc/arclight/release",
                                     "etc/lsb-release"]}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="arclight-identity", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name")
    ap.add_argument("--tagline")
    ap.add_argument("--root", default="/")
    ap.add_argument("--reapply", action="store_true")
    a = ap.parse_args(argv)
    d = load(a.root)
    if not (a.name or a.tagline or a.reapply):
        print(json.dumps(d, indent=2))
        return 0
    if a.name:
        if not valid_name(a.name):
            print("arclight-identity: a name is 1-40 letters, digits, spaces, dots, dashes or pluses", file=sys.stderr)
            return 2
        d["name"] = a.name.strip()
    if a.tagline:
        d["tagline"] = a.tagline
    if os.geteuid() != 0 and a.root == "/":
        print("arclight-identity: run as root (arc root arclight-identity ...)", file=sys.stderr)
        return 1
    res = apply(d, a.root)
    print(f"OS name: {d['name']}")
    if a.root == "/" and Path("/usr/bin/arclight-bootcfg").exists() and not a.reapply:
        os.system("/usr/bin/arclight-bootcfg >/dev/null 2>&1")
    return 0
