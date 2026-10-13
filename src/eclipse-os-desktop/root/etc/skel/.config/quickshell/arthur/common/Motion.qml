pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell

// Motion tokens. Liquid, not springy: every curve decelerates without overshoot.
// Curves (x1,y1,x2,y2): liquid = easeOutQuint-like (same family as the Hyprland
// "liquid" bezier), glide = gentle ease-in-out for things that travel, emphasized =
// Material-style decelerate for panels arriving. Presets scale every duration.
Singleton {
    id: root

    readonly property string preset: Config.motion.preset
    readonly property bool reduced: Config.motion.reduceMotion
    readonly property real scale: reduced ? 0 : (preset === "calm" ? 1.35 : preset === "snappy" ? 0.65 : 1.0)

    readonly property int fast:   Math.round(150 * scale)    // hover, press, small fades
    readonly property int normal: Math.round(240 * scale)    // popups, chips, indicators
    readonly property int slow:   Math.round(340 * scale)    // panels, dock rise
    readonly property int reveal: Math.round(420 * scale)    // wallpaper / large surfaces

    readonly property list<real> liquid:     preset === "snappy" ? [0.2, 0, 0, 1, 1, 1] : [0.22, 1, 0.36, 1, 1, 1]
    readonly property list<real> glide:      [0.4, 0, 0.2, 1, 1, 1]
    readonly property list<real> emphasized: preset === "calm" ? [0.16, 1, 0.3, 1, 1, 1] : [0.05, 0.7, 0.1, 1, 1, 1]
    readonly property list<real> exit:       [0.3, 0, 0.8, 0.15, 1, 1]
}
