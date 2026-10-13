import QtQuick
import QtQuick.Layouts
import qs.common
import qs.components
import qs.services

// Output volume: mute button, draggable bar, percent. Hidden when there is no sink.
RowLayout {
    id: root
    visible: Audio.available
    spacing: 10

    PanelButton {
        icon: Audio.muted || Audio.volume <= 0.001 ? "\u{f0581}" : Audio.volume < 0.34 ? "\u{f057f}" : Audio.volume < 0.67 ? "\u{f0580}" : "\u{f057e}"
        iconColor: Audio.muted ? Theme.muted : Theme.text
        onClicked: Audio.toggleMute()
    }

    Item {
        id: track
        Layout.fillWidth: true
        Layout.preferredHeight: 28
        readonly property real value: drag.pressed ? drag.live : (Audio.muted ? 0 : Audio.volume)

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width; height: 6; radius: 3
            color: Theme.withAlpha(Theme.text, 0.14)
            Rectangle {
                width: parent.width * Math.max(0, Math.min(1, track.value))
                height: parent.height; radius: 3
                color: Audio.muted ? Theme.muted : Theme.accent
                Behavior on width { enabled: !drag.pressed; Anim { duration: Motion.fast } }
            }
        }
        Rectangle {
            x: Math.max(0, Math.min(track.width - width, track.width * track.value - width / 2))
            anchors.verticalCenter: parent.verticalCenter
            width: 16; height: 16; radius: 8
            color: Theme.text
            border.width: 2
            border.color: Audio.muted ? Theme.muted : Theme.accent
            scale: drag.pressed || drag.containsMouse ? 1.15 : 1
            Behavior on scale { Anim { duration: Motion.fast } }
        }
        MouseArea {
            id: drag
            property real live: 0
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            function apply(mx) { live = Math.max(0, Math.min(1, mx / width)); Audio.setVolume(live); }
            onPressed: mouse => apply(mouse.x)
            onPositionChanged: mouse => { if (pressed) apply(mouse.x); }
            onWheel: wheel => Audio.nudge(wheel.angleDelta.y > 0 ? 0.02 : -0.02)
        }
    }

    Label {
        Layout.preferredWidth: 40
        horizontalAlignment: Text.AlignRight
        text: Audio.muted ? "Mute" : Math.round(Audio.volume * 100) + "%"
        font.family: Theme.fontMono
        color: Theme.text2
    }
}
