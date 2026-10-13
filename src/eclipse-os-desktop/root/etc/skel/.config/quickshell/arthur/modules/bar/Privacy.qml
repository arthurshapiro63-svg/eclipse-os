pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Services.Pipewire
import qs.common
import qs.components

// Privacy indicators (DMS parity): mic in use (warning), camera or screen capture (error).
// Bound to the PipeWire node list, no polling. Nothing shows while idle.
//   mic    = an audio INPUT stream (Stream/Input/Audio) that is not a desktop/monitor capture
//   video  = a video input stream (Stream/Input/Video); it is "screen" when a portal
//            screencast node (xdg-desktop-portal-hyprland, "xdph-*") exists, else "camera".
Row {
    id: root
    spacing: 2

    function _p(n, k) { return (n && n.properties && n.properties[k]) ? String(n.properties[k]) : ""; }
    function _app(n) { return _p(n, "application.name") || _p(n, "node.name") || (n ? n.name : "") || "app"; }
    function _uniq(list) { return list.filter((v, i) => list.indexOf(v) === i); }

    // Node properties (media.class, application.name) are only filled for TRACKED nodes, so the
    // input streams are picked by type flags first and then tracked (PwObjectTracker below).
    readonly property int _videoIn: PwNodeType.Video | PwNodeType.Stream | PwNodeType.Source
    readonly property var nodes: Pipewire.nodes.values
    readonly property var inStreams: nodes.filter(n => n && n.isStream
        && ((n.type & PwNodeType.AudioInStream) === PwNodeType.AudioInStream || (n.type & _videoIn) === _videoIn))
    readonly property var micStreams: inStreams.filter(n => (n.type & PwNodeType.AudioInStream) === PwNodeType.AudioInStream
        && _p(n, "stream.capture.sink") !== "true"
        && !/cava|monitor|peak|loopback/i.test(_app(n) + " " + _p(n, "media.name") + " " + (n.name || "")))
    readonly property var videoStreams: inStreams.filter(n => (n.type & _videoIn) === _videoIn)
    readonly property bool screencast: nodes.some(n => n && (n.type & PwNodeType.Video) && /xdg-desktop-portal|xdph|screencast|screen-cast/i.test(n.name || ""))
    readonly property bool micOn: micStreams.length > 0
    readonly property bool videoOn: videoStreams.length > 0
    readonly property string micApps: _uniq(micStreams.map(n => _app(n))).join(", ")
    readonly property string videoApps: _uniq(videoStreams.map(n => _app(n))).join(", ")

    visible: micOn || videoOn

    PwObjectTracker { objects: root.inStreams }

    BarButton {
        visible: root.micOn
        padding: 6
        tip: "Microphone in use: " + root.micApps
        cursorShape: Qt.ArrowCursor
        Icon { anchors.verticalCenter: parent.verticalCenter; text: "\u{f036c}"; size: Theme.fontLarge; color: Theme.warning }   // md-microphone
    }
    BarButton {
        visible: root.videoOn
        padding: 6
        tip: (root.screencast ? "Screen shared with: " : "Camera in use: ") + root.videoApps
        cursorShape: Qt.ArrowCursor
        Icon {
            anchors.verticalCenter: parent.verticalCenter
            text: root.screencast ? "\u{f1483}" : "\u{f0567}"      // md-monitor-share / md-video
            size: Theme.fontLarge
            color: Theme.error
        }
    }
}
