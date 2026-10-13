pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io

// Single source of colour, glass and geometry for every surface.
// Colours come from colors.json, which theme-apply (static themes) or the hue-clamped
// matugen pipeline (dynamic mode) writes. The file is watched: a wallpaper/theme change
// recolours the whole shell live. Built-in Midnight Blue values are the fallback, so the
// shell still renders correctly if colors.json is missing or half-written.
Singleton {
    id: root

    // ---- palette (Midnight Blue fallbacks = tokens/midnight-blue.json) ----
    readonly property var _c: colorsFile.loaded ? (root._parsed.color || {}) : {}
    readonly property var _a: colorsFile.loaded ? (root._parsed.alpha || {}) : {}
    property var _parsed: ({})

    readonly property color bgSunken:      _c["bg-sunken"]      || "#060A14"
    readonly property color bgBase:        _c["bg-base"]        || "#0A0F1E"
    readonly property color surface:       _c["surface"]        || "#121B32"
    readonly property color surfaceRaised: _c["surface-raised"] || "#1D2A4A"
    readonly property color surfaceHover:  _c["surface-hover"]  || "#26355A"
    readonly property color border:        _c["border-subtle"]  || "#2A3A5E"
    readonly property color borderStrong:  _c["border-strong"]  || "#3A4E7A"
    readonly property color text:          _c["text-primary"]   || "#E6ECFA"
    readonly property color text2:         _c["text-secondary"] || "#A8B6D4"
    readonly property color muted:         _c["text-muted"]     || "#6B7A9B"
    readonly property color accent:        _c["accent"]         || "#2F7CFF"
    readonly property color accentBright:  _c["accent-bright"]  || "#5A9BFF"
    readonly property color accentDim:     _c["accent-dim"]     || "#1E5BCC"
    readonly property color success:       _c["success"]        || "#3FD68C"
    readonly property color warning:       _c["warning"]        || "#FFC857"
    readonly property color error:         _c["error"]          || "#FF5C6E"
    readonly property color shadow:        _c["shadow"]         || "#050810"

    // ---- glass (GLASS-REPORT baseline; settings.json "glass" overrides tokens) ----
    // settings.json "glass" values of -1 mean "use the theme token".
    function _pick(cfg, tok, def) { return cfg >= 0 ? cfg : (tok !== undefined ? tok : def); }
    readonly property real barAlpha:      _pick(Config.glass.bar,      _a["shell-bar"],   0.55)
    readonly property real panelAlpha:    _pick(Config.glass.panel,    _a["shell-panel"], 0.62)
    readonly property real cardAlpha:     _pick(Config.glass.card,     _a["shell-card"],  0.32)
    readonly property real hairlineAlpha: _pick(Config.glass.hairline, undefined,         0.16)
    readonly property real menuAlpha:     0.94           // small menus must stay readable
    readonly property real shadowAlpha:   0.55

    // glass fills
    readonly property color barFill:   withAlpha(surface, barAlpha)
    readonly property color panelFill: withAlpha(surface, panelAlpha)
    readonly property color cardFill:  withAlpha(surfaceRaised, cardAlpha)
    readonly property color hoverFill: withAlpha(surfaceHover, 0.55)
    readonly property color hairline:  withAlpha(text, hairlineAlpha)
    readonly property color edge:      withAlpha(border, 0.55)
    readonly property color shadowColor: withAlpha(shadow, shadowAlpha)
    readonly property color accentSoft: withAlpha(accent, 0.22)

    // ---- geometry / type ----
    readonly property int radiusSm: 6
    readonly property int radiusMd: 10
    readonly property int radiusLg: 16
    readonly property int gap: 10          // compositor gaps_out, so shell and windows line up
    readonly property int pad: 12
    readonly property int shadowPad: 28    // transparent margin reserved inside a layer surface for the shadow
    readonly property string fontUi: "Inter"
    readonly property string fontMono: "JetBrainsMono Nerd Font"
    readonly property int fontSize: 13
    readonly property int fontSmall: 11
    readonly property int fontLarge: 16

    function withAlpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a); }
    function mix(a, b, t) { return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, a.a + (b.a - a.a) * t); }

    FileView {
        id: colorsFile
        path: Quickshell.shellPath("colors.json")
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try { root._parsed = JSON.parse(text()); }
            catch (e) { console.warn("Theme: colors.json unreadable, keeping previous palette:", e); }
        }
    }
}
