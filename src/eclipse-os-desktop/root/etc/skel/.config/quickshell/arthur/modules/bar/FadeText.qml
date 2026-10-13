import QtQuick
import qs.common
import qs.components

// Label whose value fades softly when it changes (numbers, clock, weather).
Label {
    id: root
    property bool fade: true
    onTextChanged: if (fade && visible && Motion.fast > 0) pulse.restart()
    SequentialAnimation {
        id: pulse
        NumberAnimation { target: root; property: "opacity"; to: 0.35; duration: Motion.fast / 2 }
        Anim { target: root; property: "opacity"; to: 1; duration: Motion.fast }
    }
}
