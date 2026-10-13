"""In-memory Eclipse Store backend for `arclight-store --demo` and the headless test.

No root, no network, nothing installed: searches answer from a small catalogue, installs print realistic
pacman / yay output with short pauses and then mark the app installed. Every action is recorded in CALLS.
ARCLIGHT_STORE_DEMO_SPEED speeds the fake jobs up (default 1; the test uses 8). ARCLIGHT_STORE_DEMO_FAIL=name
makes the job for that package fail.
"""
import os
import threading
import time

from . import catalog

CALLS = []
_lock = threading.Lock()
HAS_FLATPAK = True

INSTALLED = {}
_UPDATES = []
_FAILED_ONCE = []


def reset():
    global INSTALLED, _UPDATES
    CALLS.clear()
    INSTALLED = {"firefox": "143.0.1-1", "steam": "1.0.0.83-2", "zed": "0.205.6-1", "btop": "1.4.5-1",
                 "obs-studio": "32.0.1-1", "prismlauncher": "9.4-1", "zen-browser-bin": "1.16.2b-1",
                 "ghostty": "1.2.0-1", "thunar": "4.20.4-1", "org.gimp.GIMP": "3.0.4", "eclipse-os-core": "0.1.0-1"}
    _UPDATES = [
        {"name": "firefox", "version": "143.0.1-1", "new_version": "143.0.4-1"},
        {"name": "mesa", "version": "1:25.2.3-1", "new_version": "1:25.2.4-1"},
        {"name": "linux", "version": "6.17.1.arch1-1", "new_version": "6.17.2.arch1-1"},
        {"name": "steam", "version": "1.0.0.83-2", "new_version": "1.0.0.84-1"},
        {"name": "zed", "version": "0.205.6-1", "new_version": "0.206.1-1"},
        {"name": "python", "version": "3.13.7-1", "new_version": "3.13.8-1"},
        {"name": "zen-browser-bin", "version": "1.16.2b-1", "new_version": "1.16.3b-1", "source": "aur"},
    ]


reset()

# a small world of packages the demo can find
EXTRA = [
    {"name": "krita", "source": "repo", "repo": "extra", "version": "5.2.11-2", "size": 207_500_000,
     "description": "Edit and paint images"},
    {"name": "krita-plugin-gmic", "source": "repo", "repo": "extra", "version": "3.5.5.1-3", "size": 11_200_000,
     "description": "GMic plugin for Krita"},
    {"name": "blender", "source": "repo", "repo": "extra", "version": "17:4.5.3-2", "size": 412_000_000,
     "description": "A fully integrated 3D graphics creation suite"},
    {"name": "cowsay", "source": "repo", "repo": "extra", "version": "3.8.4-2", "size": 38_600,
     "description": "Configurable talking cow (and a few other creatures)"},
    {"name": "ponysay", "source": "repo", "repo": "extra", "version": "3.0.3-6", "size": 7_400_000,
     "description": "cowsay reimplemention for ponies"},
    {"name": "godot", "source": "repo", "repo": "extra", "version": "4.5-1", "size": 128_000_000,
     "description": "Advanced cross-platform 2D and 3D game engine"},
    {"name": "obs-studio", "source": "repo", "repo": "extra", "version": "32.0.1-1", "size": 26_400_000,
     "description": "Free, open source software for live streaming and recording"},
    {"name": "steam", "source": "repo", "repo": "multilib", "version": "1.0.0.83-2", "size": 5_100_000,
     "description": "Valve's digital software delivery system"},
    {"name": "lutris", "source": "repo", "repo": "extra", "version": "0.5.19-2", "size": 9_800_000,
     "description": "Open Gaming Platform"},
    {"name": "prismlauncher", "source": "repo", "repo": "extra", "version": "9.4-1", "size": 18_900_000,
     "description": "Minecraft launcher with ability to manage multiple instances."},
    {"name": "ollama", "source": "repo", "repo": "extra", "version": "0.12.3-1", "size": 64_000_000,
     "description": "Create, run and share large language models (LLMs)"},
    {"name": "zed", "source": "repo", "repo": "extra", "version": "0.205.6-1", "size": 330_000_000,
     "description": "A high-performance, multiplayer code editor from the creators of Atom and Tree-sitter"},
    {"name": "firefox", "source": "repo", "repo": "extra", "version": "143.0.1-1", "size": 262_000_000,
     "description": "Fast, Private & Safe Web Browser"},
    {"name": "python-krita-tools", "source": "repo", "repo": "extra", "version": "1.0-1", "size": 120_000,
     "description": "Python bindings used by some Krita scripts"},
    {"name": "heroic-games-launcher-bin", "source": "aur", "version": "2.18.1-1", "votes": 296,
     "description": "An Open Source Launcher for GOG, Epic Games and Amazon Games"},
    {"name": "krita-appimage", "source": "aur", "version": "5.2.11-1", "votes": 6,
     "description": "Krita painting program (AppImage)"},
    {"name": "krita-git", "source": "aur", "version": "5.3.0.r1234-1", "votes": 21,
     "description": "Edit and paint images (git version)"},
    {"name": "davinci-resolve", "source": "aur", "version": "20.2-1", "votes": 191,
     "description": "Professional A/V post-production software suite from Blackmagic Design"},
    {"name": "cowsay-bin", "source": "aur", "version": "1.0-1", "votes": 1, "out_of_date": True,
     "description": "cowsay rewritten in Go"},
    {"name": "visual-studio-code-bin", "source": "aur", "version": "1.104.3-1", "votes": 1710,
     "description": "Visual Studio Code (vscode): Editor for building and debugging modern web and cloud applications"},
    {"name": "zen-browser-bin", "source": "aur", "version": "1.16.2b-1", "votes": 341,
     "description": "Official package for Zen, a privacy-focused, feature packed browser"},
    {"name": "org.kde.krita", "title": "Krita", "source": "flatpak", "version": "5.2.11", "remote": "flathub",
     "size": 270_000_000, "description": "Digital Painting, Creative Freedom"},
    {"name": "org.blender.Blender", "title": "Blender", "source": "flatpak", "version": "4.5.3", "remote": "flathub",
     "size": 980_000_000, "description": "Free and open source 3D creation suite"},
    {"name": "org.gimp.GIMP", "title": "GIMP", "source": "flatpak", "version": "3.0.4", "remote": "flathub",
     "size": 410_000_000, "description": "Create images and edit photographs"},
]


def _rec(method, **params):
    with _lock:
        CALLS.append((method, params))


def _speed():
    try:
        return max(0.1, float(os.environ.get("ARCLIGHT_STORE_DEMO_SPEED", "1")))
    except ValueError:
        return 1.0


def _world():
    """EXTRA + every curated app, so any curated tile has data."""
    by = {(e["source"], e["name"]): dict(e) for e in EXTRA}
    for c in catalog.curated():
        for a in c["apps"]:
            k = (a["source"], a["name"])
            if k not in by:
                by[k] = {"name": a["name"], "source": a["source"], "repo": "extra" if a["source"] == "repo" else None,
                         "version": "1.0-1", "size": 42_000_000 if a["source"] == "repo" else None,
                         "votes": 120 if a["source"] == "aur" else None, "description": a.get("blurb", "")}
    return by


def _match(q, src):
    q = q.lower().strip()
    out = []
    for (s, n), e in _world().items():
        if s != src:
            continue
        hay = (n + " " + e.get("title", "") + " " + e.get("description", "")).lower()
        if all(w in hay for w in q.split()):
            r = {k: v for k, v in e.items() if k != "size"}
            r["installed"] = n in INSTALLED
            out.append(r)
    return out


def call(method, **params):
    _rec(method, **params)
    if os.environ.get("ARCLIGHT_FAKE_DOWN_SYSTEM") == "1":
        from ..settings.backend import Unavailable
        raise Unavailable("arclightd is not running.")
    if method == "pkg.list" and params.get("upgradable"):
        return [u for u in _UPDATES if params.get("aur") or u.get("source") != "aur"]
    if method == "pkg.search":
        return _match(params.get("query", ""), "repo")
    raise RuntimeError(f"fake: no {method}")


def search_repo(q):
    time.sleep(0.15 / _speed())
    return call("pkg.search", query=q, aur=False)


def search_aur(q):
    _rec("aur.search", query=q)
    time.sleep(0.4 / _speed())
    if os.environ.get("ARCLIGHT_STORE_DEMO_OFFLINE") == "1":
        raise OSError("urlopen error [Errno -3] Temporary failure in name resolution")
    return _match(q, "aur")


def search_flatpak(q):
    _rec("flatpak.search", query=q)
    time.sleep(0.25 / _speed())
    return _match(q, "flatpak")


def sizes(names):
    w = _world()
    return {n: w.get(("repo", n), {}).get("size") for n in names}


def details(item):
    _rec("details", name=item["name"])
    time.sleep(0.1 / _speed())
    e = _world().get((item.get("source", "repo"), item["name"]), {})
    d = {"version": INSTALLED.get(item["name"]) or e.get("version") or "1.0-1", "size": e.get("size"),
         "download_size": int(e["size"] * 0.35) if e.get("size") else None,
         "url": f"https://example.org/{item['name']}", "license": "GPL-3.0-or-later",
         "description": e.get("description"), "needs": 12}
    if item.get("source") == "aur":
        d.update(votes=e.get("votes"), maintainer="someone", out_of_date=e.get("out_of_date", False), size=None)
    return d


_DESKTOP = {"firefox": ("Firefox", "firefox"), "steam": ("Steam", "steam"), "zed": ("Zed", "zed"),
            "btop": ("btop++", "btop"), "obs-studio": ("OBS Studio", "com.obsproject.Studio"),
            "prismlauncher": ("Prism Launcher", "org.prismlauncher.PrismLauncher"),
            "zen-browser-bin": ("Zen Browser", "zen-browser"), "ghostty": ("Ghostty", "com.mitchellh.ghostty"),
            "thunar": ("Thunar File Manager", "org.xfce.thunar"), "org.gimp.GIMP": ("GIMP", "gimp"),
            "krita": ("Krita", "krita"), "eclipse-os-core": ("Ask Eclipse", "arclight"), "blender": ("Blender", "blender"), "cowsay": None}


def desktop_entry(item):
    n = item["name"]
    if n not in INSTALLED:
        return None
    t = _DESKTOP.get(n, (catalog.nice_title(n), n))
    if t is None:
        return None
    return {"file": f"/usr/share/applications/{n}.desktop", "id": f"{n}.desktop", "name": t[0], "icon": t[1],
            "comment": "", "hidden": False, "terminal": n == "btop"}


def installed_apps():
    _rec("installed_apps")
    time.sleep(0.1 / _speed())
    out = []
    w = _world()
    for n, v in INSTALLED.items():
        e = desktop_entry({"name": n})
        if not e:
            continue
        src = "flatpak" if "." in n and n.count(".") >= 2 else ("aur" if n.endswith("-bin") else "repo")
        if catalog.is_system_part(n):
            src = "eclipse"
        out.append({"name": n, "source": src, "version": v, "installed": True, "title": e["name"],
                    "description": (w.get((src, n)) or {}).get("description") or "", "icon": e["icon"],
                    "desktop": e["file"]})
    return out


def updates():
    time.sleep(0.2 / _speed())
    return call("pkg.list", upgradable=True, aur=True)


_INSTALL_LINES = """resolving dependencies...
looking for conflicting packages...

Packages ({n}) {pkgs}

Total Download Size:   {dl:.2f} MiB
Total Installed Size:  {inst:.2f} MiB

:: Proceed with installation? [Y/n]
:: Retrieving packages...
{downloads}
checking keyring...
checking package integrity...
loading package files...
checking for file conflicts...
checking available disk space...
:: Processing package changes...
{installs}
:: Running post-transaction hooks...
(1/3) Arming ConditionNeedsUpdate...
(2/3) Updating icon theme caches...
(3/3) Updating the desktop file MIME type cache..."""

_AUR_BUILD = """:: (1/1) Downloaded PKGBUILD: {name}
==> Making package: {name} {ver} (Fri Oct 10 15:02:11 2026)
==> Checking runtime dependencies...
==> Retrieving sources...
  -> Downloading {name}-{ver}.tar.gz...
==> Validating source files with sha256sums...
==> Extracting sources...
==> Starting build()...
==> Entering fakeroot environment...
==> Starting package()...
==> Creating package "{name}"...
==> Finished making: {name} {ver} (Fri Oct 10 15:02:58 2026)
loading packages...
resolving dependencies...
looking for conflicting packages...

Packages (1) {name}-{ver}

:: Proceed with installation? [Y/n]
checking keyring...
checking package integrity...
loading package files...
checking for file conflicts...
:: Processing package changes...
installing {name}...
:: Running post-transaction hooks..."""


def _emit(text, on_line, pause):
    for line in text.splitlines():
        if on_line and line.strip():
            on_line(line)
        time.sleep(pause)


def run_job(action, item, on_line):
    name = item["name"] if item else None
    _rec("job." + action, name=name)
    sp = _speed()
    fail = os.environ.get("ARCLIGHT_STORE_DEMO_FAIL")
    if os.environ.get("ARCLIGHT_FAKE_DOWN_SYSTEM") == "1":
        from .backend import JobError
        raise JobError("arclightd is not running.")
    snapshot = {"id": "20261010-150211-before-pkg-" + action, "label": f"before pkg {action} {name or ''}".strip()}
    if action == "update":
        names = [u["name"] for u in _UPDATES]
        text = _INSTALL_LINES.format(n=len(names), pkgs="  ".join(f"{u['name']}-{u['new_version']}" for u in _UPDATES),
                                     dl=212.4, inst=18.0,
                                     downloads="\n".join(f" {n} downloading..." for n in names),
                                     installs="\n".join(f"upgrading {n}..." for n in names))
        _emit(":: Synchronizing package databases...\n core downloading...\n extra downloading...\n:: Starting full system upgrade...",
              on_line, 0.15 / sp)
        _emit(text, on_line, 0.12 / sp)
        if fail == "update":
            from .backend import JobError
            on_line and on_line("error: failed to commit transaction (conflicting files)")
            raise JobError("pacman -Syu failed: error: failed to commit transaction (conflicting files)")
        if fail == "update-aur" and not _FAILED_ONCE:   # repo part works, AUR build fails: a partial result
            _FAILED_ONCE.append(True)                     # (once: Retry then succeeds)
            aur = [u for u in _UPDATES if u.get("source") == "aur"]
            repo = [u for u in _UPDATES if u.get("source") != "aur"]
            for u in repo:
                if u["name"] in INSTALLED:
                    INSTALLED[u["name"]] = u["new_version"]
            diag = (f"==> Making package: {aur[0]['name']} {aur[0]['new_version']}\n==> ERROR: Failure while downloading "
                    f"https://example.invalid/{aur[0]['name']}.tar.bz2\n -> error making: {aur[0]['name']}-exit status 4")
            _emit(diag, on_line, 0.1 / sp)
            _UPDATES[:] = aur
            return {"snapshot": snapshot, "result": {
                "status": "partial", "ok": False, "updated": [u["name"] for u in repo],
                "failed": [u["name"] for u in aur], "diagnostics": diag,
                "retry": {"method": "pkg.upgrade", "params": {"aur": True}}}}
        for u in _UPDATES:
            if u["name"] in INSTALLED:
                INSTALLED[u["name"]] = u["new_version"]
        _UPDATES.clear()
        return {"snapshot": snapshot, "result": {"status": "ok", "ok": True, "code": 0}}
    if action == "remove":
        _emit(f"checking dependencies...\n\nPackages (1) {name}-1.0-1\n\nTotal Removed Size:  40.00 MiB\n\n"
              f":: Do you want to remove these packages? [Y/n]\n:: Processing package changes...\nremoving {name}...\n"
              f":: Running post-transaction hooks...\n(1/1) Arming ConditionNeedsUpdate...", on_line, 0.15 / sp)
        INSTALLED.pop(name, None)
        return {"snapshot": snapshot, "result": {"removed": [name]}}
    # install
    if item.get("source") == "flatpak":
        for i in range(1, 4):
            _emit(f"Installing {i}/3… {['org.freedesktop.Platform', 'org.freedesktop.Platform.GL.default', name][i - 1]}",
                  on_line, 0.5 / sp)
        INSTALLED[name] = item.get("version") or "1.0"
        return {"snapshot": None, "result": {"output": "ok"}}
    deps = ["qt6-multimedia", "kseexpr", "quazip-qt6"] if name == "krita" else []
    pkgs = deps + [name]
    if item.get("source") == "aur":
        _emit(f":: Resolving dependencies...\n:: Checking for conflicts...\n:: Checking for inner conflicts...",
              on_line, 0.2 / sp)
        if name == fail:
            from .backend import JobError
            _emit("==> Making package: {0} 1.0-1\n==> Starting build()...\n==> ERROR: A failure occurred in build().".format(name),
                  on_line, 0.3 / sp)
            raise JobError(f"AUR build failed (1): ==> ERROR: A failure occurred in build(). Aborting...")
        _emit(_AUR_BUILD.format(name=name, ver=item.get("version") or "1.0-1"), on_line, 0.35 / sp)
    else:
        text = _INSTALL_LINES.format(n=len(pkgs), pkgs="  ".join(f"{p}-1.0-1" for p in pkgs), dl=63.2, inst=207.5,
                                     downloads="\n".join(f" {p}-1.0-1-x86_64 downloading..." for p in pkgs),
                                     installs="\n".join(f"installing {p}..." for p in pkgs))
        if name == fail:
            from .backend import JobError
            _emit(text.split(":: Processing")[0], on_line, 0.1 / sp)
            on_line and on_line(f"error: failed retrieving file '{name}-1.0-1-x86_64.pkg.tar.zst' from mirror : Could not resolve host")
            raise JobError(f"pacman failed (1): error: failed retrieving file '{name}-1.0-1-x86_64.pkg.tar.zst'")
        _emit(text, on_line, 0.18 / sp)
    INSTALLED[name] = item.get("version") or "1.0-1"
    return {"snapshot": snapshot, "result": {"installed": {name: f"{name} 1.0-1"}}}


def open_app(item):
    _rec("open", name=item["name"])
    return True


def ask(prefill):
    _rec("ask", prefill=prefill)
    return True
