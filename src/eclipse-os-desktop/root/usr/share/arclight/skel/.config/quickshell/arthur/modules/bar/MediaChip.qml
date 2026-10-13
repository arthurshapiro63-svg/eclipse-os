import QtQuick
import Quickshell
import qs.common
import qs.components
import qs.services

// Now playing: "title - artist". Click = play/pause, right click = next,
// scroll down = next, scroll up = previous. Hidden when no MPRIS player exists.
BarButton {
    id: root
    readonly property string line: Media.artist !== "" ? Media.title + " - " + Media.artist : Media.title
    visible: Config.bar.showMedia && Media.active && line !== ""
    tip: (Media.playing ? "Playing" : "Paused") + ": " + line
    spacing: 6
    onClicked: mouse => { if (mouse.button === Qt.RightButton) Media.next(); else Media.toggle(); }
    onWheel: wheel => {
        if (wheel.angleDelta.y < 0) Media.next();
        else if (wheel.angleDelta.y > 0) Media.previous();
    }

    Icon {
        anchors.verticalCenter: parent.verticalCenter
        text: Media.playing ? "\u{f03e4}" : "\u{f040a}"      // md-pause / md-play
        size: Theme.fontLarge
        color: Media.playing ? Theme.accentBright : Theme.text2
        Behavior on color { CAnim {} }
    }
    FadeText {
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, 260)
        text: root.line
        color: Theme.text
    }
}
