"""Eclipse Store logic without GTK: the curated home page, plain-English text, ranking of search results
from the repos + AUR + Flathub, sizes, desktop entries of installed apps, and the progress parser that turns
pacman / yay / flatpak output into a progress bar and one plain sentence.

Everything here is pure (or read-only on the local system) so it can be unit-tested and reused by the fake
backend.
"""
import configparser
import json
import math
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
CURATED_FILE = HERE / "curated.json"
ENV = {**os.environ, "LANG": "C", "LC_ALL": "C"}

SOURCES = {
    "repo": {"badge": "Arch", "long": "Arch Linux (official)", "note": "Official Arch package. Checked and signed."},
    "aur": {"badge": "AUR", "long": "AUR (community)", "note": "Made by the community. It is built on your PC, so it can take a while."},
    "flatpak": {"badge": "Flatpak", "long": "Flathub", "note": "Runs in its own sandbox, apart from the rest of the system."},
    "eclipse": {"badge": "Eclipse", "long": "Part of Eclipse OS", "note": "Comes with the system. It cannot be removed here."},
}


def is_system_part(name):
    """Eclipse OS's own packages (eclipse-os-core, -desktop, -installer, ...): never offered for removal."""
    return (name or "").startswith(("eclipse-os-", "arclight"))

# packages that are building blocks, not apps: shown last in search results
_NOISE = re.compile(r"^(lib|python-|python2-|perl-|ruby-|haskell-|node-|nodejs-|r-|rust-|go-|ocaml-|lua-|lua5|"
                    r"php-|java-|jdk|texlive-|ttf-|otf-|noto-|xorg-|xf86-|qt5-|qt6-|kf5|kf6|gst-|mingw-|lib32-)"
                    r"|(-docs?|-debug|-headers|-devel|-dev|-data|-common|-git|-nightly|-dbg|-l10n.*|-i18n.*)$")


# ------------------------------------------------------------------ curated home page
def curated(path=None):
    try:
        data = json.loads(Path(path or CURATED_FILE).read_text())
    except (OSError, ValueError):
        return []
    out = []
    for c in data.get("categories", []):
        apps = [dict(a, source=a.get("source", "repo")) for a in c.get("apps", []) if a.get("name")]
        out.append({"id": c.get("id"), "title": c.get("title", ""), "sub": c.get("sub", ""), "apps": apps})
    return out


def curated_index(cats=None):
    """name -> curated entry (title, blurb, icon, category)."""
    idx = {}
    for c in cats if cats is not None else curated():
        for a in c["apps"]:
            idx.setdefault(a["name"], dict(a, category=c["title"]))
    return idx


# ------------------------------------------------------------------ plain words
def nice_title(name):
    """'heroic-games-launcher-bin' -> 'Heroic Games Launcher'."""
    n = re.sub(r"-(bin|git|appimage|desktop|nightly|beta|stable)$", "", name)
    if "." in n and n.count(".") >= 2:            # flatpak id: org.gimp.GIMP -> GIMP
        n = n.split(".")[-1]
    words = re.split(r"[-_]+", n)
    if len(words) == 1 and words[0].islower() and len(words[0]) <= 3:
        return words[0].upper() if len(words[0]) <= 2 else words[0]
    return " ".join(w[:1].upper() + w[1:] for w in words if w)


def plain(desc, limit=110):
    """A package description as one short plain sentence."""
    d = re.sub(r"\s+", " ", (desc or "").strip())
    if not d:
        return "No description yet."
    d = re.sub(r"\s*\((?:[^()]*)\)", "", d)        # drop "(git version)" style asides
    d = re.sub(r"^(An?|The)\s+", "", d)
    d = d[:1].upper() + d[1:]
    m = re.match(r"^(.{20,}?[.!?])\s", d + " ")
    if m:
        d = m.group(1)
    if len(d) > limit:
        cut = d[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
        d = cut + "…"
    if d[-1] not in ".!?…":
        d += "."
    return d


def human_size(n):
    if n is None:
        return None
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") or n >= 100 else f"{n:.1f} {unit}"
        n /= 1000


_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4,
          "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "kB": 1000}


def parse_size(text):
    """'12.40 MiB' -> bytes."""
    m = re.match(r"^\s*([\d.,]+)\s*([KMGT]?i?B|kB)\s*$", text or "")
    if not m:
        return None
    return int(float(m.group(1).replace(",", ".")) * _UNITS.get(m.group(2), 1))


# ------------------------------------------------------------------ search ranking
def rank(results, query, cur=None):
    """Sort and tidy results from every source: exact name first, then apps people know (curated,
    installed, popular), official before Flathub before AUR, building blocks last."""
    q = (query or "").strip().lower()
    cur = cur if cur is not None else curated_index()
    words = q.split()
    seen = set()
    out = []
    for r in results:
        key = (r.get("source"), r.get("name"))
        if not r.get("name") or key in seen:
            continue
        seen.add(key)
        n = r["name"].lower()
        title = (r.get("title") or "").lower()
        s = 0.0
        if n == q or title == q:
            s += 100
        elif n.startswith(q) or title.startswith(q):
            s += 45
        elif q and (q in n or q in title):
            s += 25
        elif words and all(w in (n + " " + title + " " + (r.get("description") or "").lower()) for w in words):
            s += 8
        if r["name"] in cur:
            s += 30
        if r.get("installed"):
            s += 6
        s += {"repo": 12, "flatpak": 8, "aur": 0}.get(r.get("source"), 0)
        if r.get("source") == "aur":
            s += min(14, 3 * math.log10(1 + (r.get("votes") or 0)))
            if r.get("out_of_date"):
                s -= 6
        if _NOISE.search(n):
            s -= 40
        out.append((s, r))
    out.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [r for _, r in out]


def decorate(r, cur=None):
    """Add title/blurb/icon to a raw search result (curated text wins)."""
    cur = cur if cur is not None else curated_index()
    c = cur.get(r["name"]) if r.get("source") != "flatpak" else None
    r.setdefault("title", (c or {}).get("title") or nice_title(r["name"]))
    r["blurb"] = (c or {}).get("blurb") or plain(r.get("description"))
    if c and c.get("icon"):
        r.setdefault("icon", c["icon"])
    return r


# ------------------------------------------------------------------ local, read-only package facts
def _run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=ENV)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def installed_versions():
    """{name: version} of every installed package (pacman -Q)."""
    _, out = _run(["pacman", "-Q"])
    return dict(l.split()[:2] for l in out.splitlines() if len(l.split()) >= 2)


def parse_si(text):
    """`pacman -Si/-Qi a b c` -> {name: {field: value}}."""
    out, cur, key = {}, None, None
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z][A-Za-z ]+?)\s*: (.*)$", line)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            if key == "repository":
                cur = {"repository": m.group(2).strip()}
                continue
            if key == "name":
                if cur is None:
                    cur = {}
                cur["name"] = m.group(2).strip()
                out[cur["name"]] = cur
                continue
            if cur is not None:
                cur[key] = m.group(2).strip()
        elif not line.strip():
            cur = None if cur is not None and "name" in cur else cur
        elif cur is not None and key and line.startswith(" "):
            cur[key] = cur.get(key, "") + " " + line.strip()
    return out


def repo_sizes(names):
    """{name: installed size in bytes} for repo packages (one read-only pacman -Si call)."""
    names = [n for n in names if re.fullmatch(r"[A-Za-z0-9@._+\-]+", n or "")]
    if not names:
        return {}
    _, out = _run(["pacman", "-Si"] + names, timeout=60)
    return {n: parse_size(d.get("installed_size")) for n, d in parse_si(out).items()}


APP_DIRS = [Path("/usr/share/applications"), Path("/var/lib/flatpak/exports/share/applications"),
            Path.home() / ".local/share/flatpak/exports/share/applications"]


def read_desktop(path):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    try:
        cp.read(path, encoding="utf-8")
        e = cp["Desktop Entry"]
    except (KeyError, configparser.Error, OSError, UnicodeDecodeError):
        return None
    if e.get("Type", "Application") != "Application":
        return None
    return {"file": str(path), "id": Path(path).name, "name": e.get("Name", Path(path).stem), "icon": e.get("Icon"),
            "comment": e.get("Comment") or e.get("GenericName") or "",
            "hidden": e.get("NoDisplay", "").lower() == "true" or e.get("Hidden", "").lower() == "true",
            "terminal": e.get("Terminal", "").lower() == "true"}


def desktop_files_of(pkg):
    """Desktop entries a package installs (pacman -Ql, read-only), visible ones first."""
    code, out = _run(["pacman", "-Qlq", pkg])
    if code:
        return []
    ents = [read_desktop(f) for f in out.split() if re.match(r"^/usr/share/applications/[^/]+\.desktop$", f)]
    ents = [e for e in ents if e]
    ents.sort(key=lambda e: (e["hidden"], e["terminal"], len(e["id"])))
    return ents


def installed_apps():
    """Apps you chose to install (pacman -Qe) that have a menu entry, with that entry."""
    _, ex = _run(["pacman", "-Qe"])
    explicit = dict(l.split()[:2] for l in ex.splitlines() if len(l.split()) >= 2)
    ents = {}
    d = Path("/usr/share/applications")
    files = sorted(str(p) for p in d.glob("*.desktop")) if d.is_dir() else []
    if not files:
        return []
    _, own = _run(["pacman", "-Qo"] + files, timeout=60)
    for line in own.splitlines():
        m = re.match(r"^(\S+) is owned by (\S+) (\S+)$", line)
        if not m or m.group(2) not in explicit:
            continue
        e = read_desktop(m.group(1))
        if not e or e["hidden"]:
            continue
        cur = ents.get(m.group(2))
        if cur is None or (cur["terminal"] and not e["terminal"]) or len(e["id"]) < len(cur["id"]):
            ents[m.group(2)] = e
    _, fo = _run(["pacman", "-Qqm"])
    foreign = set(fo.split())
    out = []
    for pkg, e in ents.items():
        out.append({"name": pkg, "source": "eclipse" if is_system_part(pkg) else ("aur" if pkg in foreign else "repo"), "version": explicit[pkg], "installed": True, "title": e["name"],
                    "description": e["comment"], "desktop": e["file"], "icon": e["icon"]})
    return out


def appstream_icon(name, flatpak=False):
    """An icon file from AppStream metadata, when installed (archlinux-appstream-data / Flathub)."""
    roots = []
    if flatpak:
        for base in (Path("/var/lib/flatpak/appstream"), Path.home() / ".local/share/flatpak/appstream"):
            roots += sorted(base.glob("*/*/active/icons/128x128")) + sorted(base.glob("*/*/active/icons/64x64"))
        for r in roots:
            f = r / f"{name}.png"
            if f.exists():
                return str(f)
        return None
    for base in (Path("/usr/share/swcatalog/icons"), Path("/usr/share/app-info/icons")):
        for size in ("128x128", "64x64"):
            for d in sorted(base.glob(f"*/{size}")):
                hits = sorted(d.glob(f"{name}_*.png"))
                if hits:
                    return str(hits[0])
    return None


# ------------------------------------------------------------------ progress
class Progress:
    """Turns pacman / yay / flatpak output lines into (fraction, one plain sentence).

    fraction is None while the work has no measurable length (building from source): show a pulsing bar.
    It never goes backwards."""

    def __init__(self, action="install", title=""):
        self.action = action          # install | remove | update
        self.title = title
        self.total = None
        self.dl = 0
        self.done = 0
        self.fraction = 0.02
        self.building = False
        self.text = {"remove": "Getting ready to remove it", "update": "Checking for updates"}.get(action, "Getting ready")
        self.error = None

    def _set(self, frac, text=None):
        if frac is not None:
            self.fraction = max(self.fraction or 0, min(frac, 0.99))
        if text:
            self.text = text

    def _of(self):
        return f" ({self.done} of {self.total})" if self.total and self.total > 1 else ""

    def feed(self, line):
        """Read one output line. True when the bar or the sentence changed."""
        before = (self.fraction, self.text, self.building)
        s = line.strip()
        low = s.lower()
        m = re.match(r"^Packages \((\d+)\)", s)
        if m:
            self.total = int(m.group(1))
        if low.startswith(":: synchronizing package databases"):
            self._set(0.03, "Checking for updates")
        elif low.startswith("resolving dependencies") or low.startswith("looking for conflicting"):
            self._set(0.04, "Getting ready" if (self.fraction or 0) <= 0.04 else None)
        elif low.startswith(":: retrieving packages"):
            self.building = False
            self._set(0.08, "Downloading")
        elif re.search(r"\S+ downloading\.\.\.$", s) and self.total:
            self.dl += 1
            self._set(0.08 + 0.42 * min(self.dl, self.total) / self.total,
                      f"Downloading ({min(self.dl, self.total)} of {self.total})" if self.total > 1 else "Downloading")
        elif low.startswith(("checking keyring", "checking keys in keyring", "checking package integrity")):
            self._set(0.52, "Checking the download")
        elif low.startswith(("loading package files", "checking for file conflicts", "checking available disk space")):
            self._set(0.58, "Checking there is room")
        elif low.startswith(":: processing package changes"):
            self._set(0.60, {"remove": "Removing", "update": "Updating"}.get(self.action, "Installing"))
        elif re.match(r"^(installing|upgrading|reinstalling|downgrading|removing) (\S+)\.\.\.$", s):
            m = re.match(r"^(\S+) (\S+)\.\.\.$", s)
            self.building = False
            self.done += 1
            verb = {"installing": "Installing", "upgrading": "Updating", "reinstalling": "Installing",
                    "downgrading": "Changing", "removing": "Removing"}[m.group(1)]
            base = 0.60 if self.action != "remove" else 0.10
            span = 0.32 if self.action != "remove" else 0.80
            tot = self.total or self.done
            self._set(base + span * min(self.done, tot) / max(tot, 1), f"{verb} {m.group(2)}{self._of()}")
        elif low.startswith(":: running post-transaction hooks"):
            self._set(0.93, "Finishing up")
        elif re.match(r"^\(\d+/\d+\) ", s) and self.fraction and self.fraction >= 0.93:
            self._set(min(0.99, self.fraction + 0.01))
        elif low.startswith("==> making package:") or (low.startswith(":: (") and "pkgbuild" in low):
            m = re.match(r"^==> Making package: (\S+)", s)
            self.building = True
            self._set(None, f"Building {self.title or (m.group(1) if m else 'it')} on your PC. This can take a while.")
        elif low.startswith("==> starting build()") or low.startswith("==> starting package()"):
            self.building = True
            self._set(None, "Building it on your PC. This can take a while.")
        elif low.startswith("==> finished making"):
            self.building = False
            self._set(0.60, "Built. Installing it now")
        elif low.startswith("there is nothing to do") or " is up to date -- skipping" in low:
            self._set(0.99, "Already up to date")
        elif low.startswith("error:") or low.startswith("==> error:"):
            self.error = s.split(":", 1)[1].strip() if ":" in s else s
        else:
            # flatpak: "Installing 2/3…", percentages
            m = re.search(r"(Installing|Updating|Uninstalling) (\d+)/(\d+)", s)
            if m:
                self.total = int(m.group(3))
                self.done = int(m.group(2))
                verb = {"Uninstalling": "Removing"}.get(m.group(1), m.group(1))
                self._set(0.05 + 0.9 * (self.done - 1) / self.total, f"{verb}{self._of()}")
        return before != (self.fraction, self.text, self.building)

    @property
    def pulsing(self):
        return self.building


def plain_error(msg):
    """A pacman / yay / RPC error as one plain sentence (plus the raw text for the details box)."""
    m = (msg or "").lower()
    if "busy" in m or "db.lck" in m or "unable to lock database" in m:
        return "Another install or update is running. Try again when it is done."
    if "target not found" in m or "no package named" in m:
        return "That app was not found. It may have a new name."
    if "failed retrieving" in m or "could not resolve" in m or "network" in m or "timed out" in m or "urlopen" in m:
        return "The download failed. Check the internet and try again."
    if "not enough free disk space" in m or "no space left" in m:
        return "There is not enough free space on the disk."
    if "conflict" in m:
        return "It clashes with something already installed. Ask the AI to sort it out."
    if "breaks dependency" in m or "required by" in m:
        return "Other apps need this, so it cannot be removed on its own."
    if "aur build failed" in m or "makepkg" in m or "build failed" in m:
        return "Building it from the AUR failed. Ask the AI to look at it."
    if "not running" in m:
        return "The system helper is not running, so nothing can be installed. Run arc doctor in a terminal to fix it."
    if "not installed" in m and "yay" in m:
        return "AUR apps need yay, and yay is not installed."
    return "Something went wrong. The details are below."
