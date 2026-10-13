import QtQuick
import Quickshell
import qs.common
import qs.components
import qs.services

// Volume: icon + %. Scroll = +/- 5 %, click = mute. Hidden without a sink.
BarButton {
    id: root
    visible: Audio.available
    tip: Audio.sinkName + (Audio.muted ? " (muted)" : "")
    spacing: 4
    onClicked: Audio.toggleMute()
    onWheel: wheel => {
        if (wheel.angleDelta.y > 0) Audio.nudge(0.05);
        else if (wheel.angleDelta.y < 0) Audio.nudge(-0.05);
    }

    Icon {
        anchors.verticalCenter: parent.verticalCenter
        text: Audio.muted ? "\u{f075f}" : Audio.volume > 0.66 ? "\u{f057e}" : Audio.volume > 0.33 ? "\u{f0580}" : "\u{f057f}"  // md-volume-off/high/medium/low
        size: Theme.fontLarge
        color: Audio.muted ? Theme.muted : Theme.text
        Behavior on color { CAnim {} }
    }
    FadeText {
        anchors.verticalCenter: parent.verticalCenter
        text: Math.round(Audio.volume * 100) + "%"
        font.family: Theme.fontMono
        color: Audio.muted ? Theme.muted : Theme.text
        elide: Text.ElideNone
    }
}
