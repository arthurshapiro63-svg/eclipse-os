"""The Eclipse look, on or off. Off keeps every Eclipse OS feature (the AI, Totality, the Store, Settings...)
but drops the eclipse styling: a neutral graphite theme, a plain dark wallpaper (made here with ImageMagick, no
photo), the system's plain boot splash, the Arch logo in the terminal, no living wallpaper. On puts back exactly
what was there before (theme and wallpaper are remembered when the look is turned off)."""
import os
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
PLAIN_THEME = "graphite"
PLAIN_WALL = HOME / "Pictures/wallpapers/plain-graphite.jpg"
ECLIPSE_THEME = "eclipse"
ECLIPSE_WALL = "arclight-eclipse.jpg"


def _store():
    from .settings.registry import Store
    return Store()


def _plain_wallpaper():
    """A quiet dark graphite gradient with a soft vignette (procedural, deterministic)."""
    if PLAIN_WALL.exists():
        return PLAIN_WALL
    PLAIN_WALL.parent.mkdir(parents=True, exist_ok=True)
    size = "3840x2160"
    subprocess.run(["magick", "-size", size, "radial-gradient:#26272B-#0E0E10", "-gravity", "center",
                    # the vignette mask is blurred at quarter size and scaled up: same soft look, ~40x less CPU
                    # (a 0x320 blur at 4K took 3+ CPU-minutes, so the plain look landed ~1 min after the first login)
                    "(", "-size", "960x540", "xc:black", "-fill", "white", "-draw", "ellipse 480,270 575,375 0,360",
                    "-blur", "0x80", "-resize", f"{size}!", ")", "-compose", "multiply", "-composite",
                    "-attenuate", "0.25", "+noise", "Gaussian", "-quality", "92", str(PLAIN_WALL)],
                   capture_output=True, timeout=120)
    if not PLAIN_WALL.exists():  # minimal fallback
        subprocess.run(["magick", "-size", size, "gradient:#1E1F23-#0B0B0D", str(PLAIN_WALL)], capture_output=True)
    return PLAIN_WALL


def _splash(theme):
    """System boot splash (root, initramfs rebuild): done in the background, it takes a while."""
    asroot = shutil.which("arclight-asroot")
    if not asroot or not Path("/usr/share/plymouth/themes", theme).is_dir():
        return False
    subprocess.Popen([asroot, "plymouth-set-default-theme", "-R", theme], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _fastfetch(on):
    """On: the eclipse logo image (desktop.fastfetch_logo). Off: the user's original fastfetch template/config
    (kept as *.arclight-orig when the eclipse logo was swapped in)."""
    if on:
        from .desktop import fastfetch_logo
        return fastfetch_logo(HOME)
    n = 0
    for f in (HOME / ".config/theme/templates/fastfetch-static.tmpl", HOME / ".config/fastfetch/config.jsonc"):
        orig = f.with_name(f.name + ".arclight-orig")
        if orig.exists():
            shutil.copy2(orig, f)
            n += 1
    return f"{n} fastfetch files back to the original logo"


def apply(on, settings=None):
    """Switch the look. `settings` = the curated setters (theme / wallpaper / living) to reuse their logic."""
    st = _store()
    on = bool(on)
    report = {}
    if not on:
        if st.get("look.saved_theme") is None:
            st.put("look.saved_theme", settings["theme_get"]() if settings else ECLIPSE_THEME)
            st.put("look.saved_wallpaper", settings["wall_get"]() if settings else ECLIPSE_WALL)
            st.put("look.saved_living", st.get("wallpaper.living", True))
        st.put("wallpaper.living", False)
        if settings:
            report["theme"] = settings["theme_set"](PLAIN_THEME)
            report["wallpaper"] = settings["wall_set"](str(_plain_wallpaper()))
        report["fastfetch"] = _fastfetch(False)
        report["splash"] = _splash("bgrt") or _splash("spinner")
    else:
        theme = st.get("look.saved_theme") or ECLIPSE_THEME
        wall = st.get("look.saved_wallpaper") or ECLIPSE_WALL
        if theme == PLAIN_THEME:
            theme = ECLIPSE_THEME
        if "plain-graphite" in str(wall):
            wall = ECLIPSE_WALL
        st.put("wallpaper.living", st.get("look.saved_living", True))
        if settings:
            report["theme"] = settings["theme_set"](theme)
            report["wallpaper"] = settings["wall_set"](wall)
        report["fastfetch"] = _fastfetch(True)
        report["splash"] = _splash("eclipse")
        for k in ("look.saved_theme", "look.saved_wallpaper", "look.saved_living"):
            st.put(k, None)
    st.put("appearance.eclipse_look", on)
    return {"eclipse_look": on, **{k: v for k, v in report.items() if v is not None}}


def is_on():
    return bool(_store().get("appearance.eclipse_look", True))
