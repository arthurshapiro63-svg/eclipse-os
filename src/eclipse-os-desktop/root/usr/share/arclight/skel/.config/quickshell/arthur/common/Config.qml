pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io

// Every user-tunable shell setting, backed by ~/.config/quickshell/arthur/settings.json.
// The file is watched: hand edits (or the settings app) apply live. Writing a property
// from QML persists it (onAdapterUpdated -> writeAdapter).
// Reach it as Config.<group>.<key>, e.g. Config.dock.autoHide.
Singleton {
    id: root

    property alias bar: adapter.bar
    property alias dock: adapter.dock
    property alias glass: adapter.glass
    property alias motion: adapter.motion
    property alias notifications: adapter.notifications
    property alias launcher: adapter.launcher
    property alias wallpaper: adapter.wallpaper
    property alias panel: adapter.panel
    property alias dev: adapter.dev
    readonly property bool loaded: file.loaded

    // Screens this shell draws on. Empty dev.screens = every screen.
    function wantsScreen(screen) {
        const only = root.dev.screens;
        return !only || only.length === 0 || only.indexOf(screen.name) >= 0;
    }

    FileView {
        id: file
        path: Quickshell.shellPath("settings.json")
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onAdapterUpdated: writeAdapter()
        onLoadFailed: error => {
            // First run: write the defaults out so the file exists and is discoverable.
            if (error === FileViewError.FileNotFound) writeAdapter();
        }

        JsonAdapter {
            id: adapter

            property JsonObject bar: JsonObject {
                property int height: 34
                property bool clock24h: false
                property bool showSeconds: false
                property bool showMedia: true
                // Weather: Open-Meteo with a FIXED location (no IP geolocation). DMS had resolved New York.
                property bool showWeather: true
                property string weatherPlace: "New York"
                property real weatherLat: 40.71
                property real weatherLon: -74.01
                property bool celsius: true
            }
            property JsonObject dock: JsonObject {
                property bool autoHide: true
                property int iconSize: 42
                property int revealDelayMs: 90
                property int hideDelayMs: 500
                // desktop-entry ids (or window classes) of pinned apps, left to right
                property list<string> pinned: ["com.mitchellh.ghostty", "thunar", "zen", "dev.arthur.ArchAI"]
            }
            property JsonObject glass: JsonObject {
                // -1 = follow the theme tokens (alpha.shell-*); 0..1 = override
                property real bar: -1
                property real panel: -1
                property real card: -1
                property real hairline: -1
            }
            property JsonObject motion: JsonObject {
                property string preset: "liquid"     // calm | liquid | snappy
                property bool reduceMotion: false
            }
            property JsonObject notifications: JsonObject {
                property int timeoutMs: 6000
                property bool dnd: false
                property int historyLimit: 100
            }
            property JsonObject launcher: JsonObject {
                property int maxResults: 8
            }
            property JsonObject wallpaper: JsonObject {
                property string dir: "~/Pictures/wallpapers"
            }
            property JsonObject panel: JsonObject {
                property int width: 420
            }
            property JsonObject dev: JsonObject {
                // Restrict every surface to these outputs (used while developing next to DMS).
                property list<string> screens: []
            }
        }
    }
}
