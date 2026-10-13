pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.UPower
import qs.common
import qs.components
import qs.services

// OSD (owner: agent C). Signal-driven, no IPC, no polling: sink volume / mute, mic mute,
// power profile, keep-awake, and the MPRIS player's own volume each show a glass pill
// bottom-centre above the dock area, which fades out 1.5 s after the last change.
// Never focusable, never clickable. Not shown on startup: changes only count once the
// source has been ready for 2 s. A volume change plays the freedesktop "volume change"
// sound once it settles (300 ms), unless the shell is quiet (game / fullscreen).
Scope {
    id: root

    readonly property var screenObj: Quickshell.screens.find(s => s.name === ShellState.activeScreen) ?? null

    property string kind: "volume"      // volume | mic | profile | awake | media
    property bool showing: false
    property bool armed: false            // audio: ready for 2 s
    property bool started: false          // everything else: shell up for 2 s
    Timer { interval: 2000; running: true; onTriggered: root.started = true }
    readonly property bool sounds: true   // TODO(handoff): Config.notifications.sounds
    readonly property var profileNames: ["Power saver", "Balanced", "Performance"]

    function poke(k) {
        const audioKind = k === "volume" || k === "mic";
        if (!(audioKind ? armed : started) || GameMode.fullscreenOn(ShellState.activeScreen)) return;
        kind = k;
        showing = true;
        hideTimer.restart();
        if (k === "volume") soundTimer.restart();
    }

    // volume-change sound after the change settles
    Timer {
        id: soundTimer
        interval: 300
        onTriggered: if (root.sounds && !GameMode.quiet && !Audio.muted)
            Quickshell.execDetached(["pw-play", "/usr/share/sounds/freedesktop/stereo/audio-volume-change.oga"])
    }

    Connections {
        target: PowerProfiles
        function onProfileChanged() { root.poke("profile"); }
    }
    Connections {
        target: PanelAwake
        function onOnChanged() { root.poke("awake"); }
    }
    // MPRIS player volume: only real steps on the same player (players report on attach)
    property var _mediaPlayer: null
    property real _mediaVol: -1
    Connections {
        target: Media.player
        ignoreUnknownSignals: true
        function onVolumeChanged() {
            const p = Media.player;
            if (!p || !p.volumeSupported) return;
            const v = p.volume;
            const step = p === root._mediaPlayer && root._mediaVol >= 0 && Math.abs(v - root._mediaVol) >= 0.01;
            root._mediaPlayer = p;
            root._mediaVol = v;
            if (step) root.poke("media");
        }
    }

    Connections {
        target: Audio
        function onVolumeChanged() { root.poke("volume"); }
        function onMutedChanged() { root.poke("volume"); }
        function onMicMutedChanged() { root.poke("mic"); }
        // a new default device fills in asynchronously: re-arm instead of flashing
        function onSinkChanged() { root.armed = false; armTimer.restart(); }
        function onSourceChanged() { root.armed = false; armTimer.restart(); }
        function onAvailableChanged() { root.armed = false; armTimer.restart(); }
    }
    Timer { id: armTimer; interval: 2000; running: true; onTriggered: root.armed = Audio.available }
    Timer { id: hideTimer; interval: 1500; onTriggered: root.showing = false }

    PanelWindow {
        id: win

        property real shown: root.showing ? 1 : 0
        Behavior on shown { Anim { duration: root.showing ? Motion.fast : Motion.normal } }

        screen: root.screenObj
        visible: !!root.screenObj && (root.showing || shown > 0.001)

        WlrLayershell.namespace: "arthur-osd"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        anchors { bottom: true }
        // above the dock: dock icon + its padding + gaps
        margins { bottom: Config.dock.iconSize + 2 * Theme.pad + 3 * Theme.gap }
        implicitWidth: 300 + 2 * Theme.shadowPad
        implicitHeight: 52 + 2 * Theme.shadowPad
        color: "transparent"
        mask: Region {}                          // fully click-through
        BackgroundEffect.blurRegion: Region { item: pill; radius: pill.radius }   // the moving item itself: a Region only follows its own item's geometry

        Glass {
            id: pill
            tone: "panel"
            x: Theme.shadowPad
            y: Theme.shadowPad + (1 - win.shown) * 10
            width: 300
            height: 52
            radius: 26
            opacity: win.shown

            readonly property bool mic: root.kind === "mic"
            readonly property bool media: root.kind === "media"
            readonly property bool hasBar: root.kind === "volume" || media
            readonly property real mediaVol: media && Media.player ? Media.player.volume : 0
            readonly property bool off: mic ? Audio.micMuted
                : root.kind === "awake" ? !PanelAwake.on
                : root.kind === "profile" ? false
                : media ? mediaVol <= 0.001
                : (Audio.muted || Audio.volume <= 0.001)
            readonly property real level: media ? mediaVol : (Audio.muted ? 0 : Audio.volume)
            readonly property string text: mic ? (Audio.micMuted ? "Microphone muted" : "Microphone on")
                : root.kind === "awake" ? (PanelAwake.on ? "Keep awake on" : "Keep awake off")
                : root.kind === "profile" ? (root.profileNames[PowerProfiles.profile] ?? "Balanced")
                : ""

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                spacing: 12

                Icon {
                    Layout.preferredWidth: 24
                    size: 22
                    color: pill.off ? Theme.muted : Theme.accentBright
                    text: pill.mic ? (pill.off ? "\u{f036d}" : "\u{f036c}")
                        : root.kind === "awake" ? (pill.off ? "\u{f0faa}" : "\u{f0176}")
                        : root.kind === "profile" ? (PowerProfiles.profile === PowerProfile.PowerSaver ? "\u{f032a}" : PowerProfiles.profile === PowerProfile.Performance ? "\u{f14de}" : "\u{f05d1}")
                        : pill.media ? "\u{f0387}"
                        : pill.off ? "\u{f0581}"
                        : Audio.volume < 0.34 ? "\u{f057f}" : Audio.volume < 0.67 ? "\u{f0580}" : "\u{f057e}"
                }

                // bar (volume kinds only; the others are a short text)
                Rectangle {
                    visible: pill.hasBar
                    Layout.fillWidth: true
                    Layout.preferredHeight: 6
                    radius: 3
                    color: Theme.withAlpha(Theme.text, 0.14)
                    Rectangle {
                        width: parent.width * Math.max(0, Math.min(1, pill.level))
                        height: parent.height
                        radius: 3
                        color: pill.off ? Theme.muted : Theme.accent
                        Behavior on width { Anim { duration: Motion.fast } }
                    }
                }
                Label {
                    visible: !pill.hasBar
                    Layout.fillWidth: true
                    text: pill.text
                    font.pixelSize: Theme.fontSize + 1
                }

                Label {
                    visible: pill.hasBar
                    Layout.preferredWidth: 38
                    horizontalAlignment: Text.AlignRight
                    text: pill.media ? Math.round(pill.mediaVol * 100) + "%" : Audio.muted ? "Mute" : Math.round(Audio.volume * 100) + "%"
                    font.family: Theme.fontMono
                    font.pixelSize: Theme.fontSize
                    color: Theme.text2
                }
            }
        }
    }
}
