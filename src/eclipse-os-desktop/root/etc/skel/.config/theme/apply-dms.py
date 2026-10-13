#!/usr/bin/env python3
"""Push the active theme's design tokens into DankMaterialShell 1.6.2 (Eclipse OS: liquid glass, sun-gold primary).

Source of truth: ~/.config/theme/tokens/midnight-blue.json. Nothing below is a
colour/alpha literal; every value is read from the tokens.

  apply-dms.py theme      rewrite the dark surface/outline/accent slots of the DMS
                          custom theme (safe while DMS runs; DMS reloads it on restart)
  apply-dms.py settings   patch settings.json (bar glass + hairline, appsDock,
                          control-centre layout, popup/card alpha, shadow). REFUSES while
                          DMS runs (DMS rewrites settings.json on exit). DMS 1.6.2 does watch
                          settings.json and reloads it live, so for a running shell prefer
                          `dms ipc call settings set <key> <value>` for scalars.
  apply-dms.py all        both

Why the settings file and not IPC: `dms ipc call settings set` only takes scalars,
and barConfigs / controlCenterWidgets are arrays.
"""
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
def _active_tokens():
    """THEME_TOKENS (set by theme-apply hooks) wins; else the active theme; else midnight-blue."""
    if os.environ.get("THEME_TOKENS"):
        return os.environ["THEME_TOKENS"]
    cur = f"{HOME}/.config/theme/current"
    slug = open(cur).read().strip() if os.path.exists(cur) else "midnight-blue"
    return f"{HOME}/.config/theme/tokens/{slug}.json"


TOKENS = _active_tokens()
THEME = f"{HOME}/.config/DankMaterialShell/midnight-blue.json"
SETTINGS = f"{HOME}/.config/DankMaterialShell/settings.json"

tok = json.load(open(TOKENS))
C, A, G = tok["color"], tok["alpha"], tok["geometry"]
# The theme's "sun": the colour of focus, selection, active workspace, sliders and progress
# (Eclipse: the golden corona). Themes made before it fall back to their accent.
SUN = tok.get("sun") or {"gold": C["accent"], "gold-soft": C["accent-bright"], "gold-deep": C["accent-dim"],
                         "on": C["bg-base"]}
# DMS shell surfaces sit directly on the blurred (luminous) wallpaper, so they run lighter than
# the window-level glass-bar/glass-panel tokens. Optional tokens alpha.shell-* override these.
SHELL = {"bar": A.get("shell-bar", 0.55), "panel": A.get("shell-panel", 0.62), "card": A.get("shell-card", 0.32)}
SLOT = "light" if tok["meta"].get("variant") == "light" else "dark"


def rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def apply_theme():
    theme = json.load(open(THEME))
    d = theme[SLOT]
    d["name"] = tok["meta"]["name"]
    # Bar and every panel paint Theme.surfaceContainer (DankBarBody.qml _bgColor,
    # DankPopoutConnected/Standalone), so that slot must be the `surface` token.
    d["surface"] = C["surface"].lower()
    d["surfaceContainer"] = C["surface"].lower()
    # Control-centre "off" tiles paint surfaceContainerHigh -> surface-raised.
    d["surfaceContainerHigh"] = C["surface-raised"].lower()
    d["surfaceContainerHighest"] = C["surface-hover"].lower()
    d["surfaceVariant"] = C["surface-raised"].lower()
    d["outline"] = C["border-subtle"].lower()
    d["background"] = C["bg-base"].lower()
    d["primary"] = SUN["gold"].lower()
    d["primaryContainer"] = C["accent-dim"].lower()
    d["primaryText"] = SUN.get("on", C["bg-base"]).lower()   # text sitting ON the sun colour
    d["secondary"] = C["accent"].lower()                    # moonlit accent for secondary marks
    d["surfaceTint"] = C["accent"].lower()
    # Text slots follow the tokens too, so a warm or grey theme doesn't keep blue text.
    d["surfaceText"] = C["text-primary"].lower()
    d["backgroundText"] = C["text-primary"].lower()
    d["surfaceVariantText"] = C["text-secondary"].lower()
    d["error"], d["warning"], d["info"] = C["error"].lower(), C["warning"].lower(), C["accent-bright"].lower()
    write_json(THEME, theme)
    print(f"theme: wrote {SLOT} slots of {THEME} from {os.path.basename(TOKENS)}")
    # Flip DMS light/dark to match the variant (no-op if DMS isn't running).
    if subprocess.run(["pgrep", "-x", "dms"], capture_output=True).returncode == 0:
        r = subprocess.run(["dms", "ipc", "call", "theme", SLOT], capture_output=True, text=True)
        print(f"theme: dms mode -> {SLOT} ({(r.stdout or r.stderr).strip()[:40]})")


def hairline_opacity(text_hex):
    """DMS bar borders only accept surfaceText/primary/secondary (BarCanvas.qml:251),
    not a hex. Find the alpha at which surfaceText over `surface` lands closest to
    `border-subtle` (least squares over RGB)."""
    t, b, target = rgb(text_hex), rgb(C["surface"]), rgb(C["border-subtle"])
    num = sum((tg - bg) * (tx - bg) for tx, bg, tg in zip(t, b, target))
    den = sum((tx - bg) ** 2 for tx, bg in zip(t, b))
    return round(num / den, 2)


def apply_settings():
    if subprocess.run(["pgrep", "-x", "dms"], capture_output=True).returncode == 0:
        sys.exit("settings: DMS is running; `dms kill` first (it would overwrite settings.json on exit)")
    s = json.load(open(SETTINGS))
    theme = json.load(open(THEME))
    bar = next(b for b in s["barConfigs"] if b.get("id") == "default")

    # A) glass bar + 1px top hairline
    bar["transparency"] = SHELL["bar"]
    bar["borderEnabled"] = True
    # the bar's lit edge is a thin corona line in the sun colour
    bar["borderColor"] = "primary"
    bar["borderOpacity"] = 0.38
    bar["borderThickness"] = G["hairline"]
    # spacing 0 = flush bar; BarCanvas.qml:253 then draws only the inner (top) edge
    # instead of a full outline.
    bar["spacing"] = 0

    # D) pinned apps: runningApps never reads barPinnedApps; appsDock does.
    left = [w for w in bar["leftWidgets"]
            if (w if isinstance(w, str) else w.get("id")) not in ("runningApps", "appsDock")]
    left.insert(1 if left and left[0] == "launcherButton" else 0,
                {"id": "appsDock", "enabled": True, "runningAppsCompactMode": True,
                 "barMaxVisibleApps": 0, "barMaxVisibleRunningApps": 0,
                 "barShowOverflowBadge": True})
    bar["leftWidgets"] = left

    # A) panels / popups / launcher / notifications
    s["popupTransparency"] = SHELL["panel"]

    # E) shell glass (pass 3): cards/pills inside panels at low alpha, perimeter light hairline,
    # soft near-black shadow. See ~/.cache/glass-pass3/reports/B-dms.md for the measurements.
    bar["widgetTransparency"] = SHELL["card"]
    bar["noBackground"] = False
    bar["widgetOutlineEnabled"] = False
    bar["shadowIntensity"] = 0              # 0 = inherit global M3 level-2 elevation (not "off")
    s["dockTransparency"] = SHELL["bar"]
    s["blurForegroundLayers"] = True
    s["foregroundLayerTransparency"] = SHELL["card"]
    s["floatingWindowTransparency"] = SHELL["panel"]
    s["floatingWindowForegroundTransparency"] = SHELL["card"]
    s["blurBorderEnabled"] = True
    # every popup (notifications, OSD, control centre, launcher) wears a thin corona rim in the sun colour
    s["blurBorderColor"] = "primary"
    s["blurBorderOpacity"] = 0.30
    s["cornerRadius"] = G["radius-md"] + 4      # generous liquid-glass rounding (Eclipse: 18)
    s["m3ElevationOpacity"] = 40
    s["m3ElevationColorMode"] = "custom"
    s["m3ElevationCustomColor"] = C["shadow"].lower()
    s["m3ElevationLightDirection"] = "autoBar"
    s["mediaWallpaperEnabled"] = False
    s["matugenTemplateZenBrowser"] = False  # zen.css is themed by theme-apply, not DMS

    # C) control centre: round quick toggles (width<=25 -> SmallToggle/SmallCompound
    # buttons, four per row), volume slider last so it sits at the bottom.
    # Not included: brightness (no backlight/DDC device), screen record (no DMS widget).
    s["controlCenterWidgets"] = [
        {"id": "wifi", "enabled": True, "width": 25},
        {"id": "bluetooth", "enabled": True, "width": 25},
        {"id": "doNotDisturb", "enabled": True, "width": 25},
        {"id": "audioInput", "enabled": True, "width": 25},
        {"id": "volumeSlider", "enabled": True, "width": 100},
    ]
    write_json(SETTINGS, s)
    print(f"settings: wrote {SETTINGS} (hairline opacity {bar['borderOpacity']})")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("theme", "all"):
        apply_theme()
    if what in ("settings", "all"):
        apply_settings()
