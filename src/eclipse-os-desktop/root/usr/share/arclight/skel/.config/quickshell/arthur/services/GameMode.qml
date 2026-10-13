pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland

// "Stay out of the way" signal for every surface:
//   fullscreenOn(screenName) -> a fullscreen window is on that output (hide/stop animating there)
//   gameRunning              -> a Steam/Proton game or gamescope window exists anywhere
//   quiet                    -> pause timers/animations and never open anything that takes focus
// Source: the Wayland foreign-toplevel list (appId = window class, fullscreen, screens).
Singleton {
    id: root

    readonly property var _tops: ToplevelManager.toplevels.values
    readonly property bool gameRunning: _tops.some(t => /^(steam_app_\d+|gamescope)$/.test(t.appId))
    readonly property bool anyFullscreen: _tops.some(t => t.fullscreen)
    readonly property bool quiet: gameRunning || anyFullscreen

    function fullscreenOn(screenName) {
        return root._tops.some(t => t.fullscreen && t.screens.some(s => s && s.name === screenName));
    }
}
