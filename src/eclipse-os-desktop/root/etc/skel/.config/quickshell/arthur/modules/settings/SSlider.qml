import QtQuick
import qs.common
import qs.components

// Labelled slider row: [label ........ track ........ value]. Emits moved(value) while
// dragging (the caller previews live). Keyboard: none (mouse + wheel), the window is
// opened by the user and never typed into by tests.
Item {
    id: root
    property string label: ""
    property real from: 0
    property real to: 1
    property real step: 1
    property real value: 0
    property int decimals: 0
    property string suffix: ""
    signal moved(real value)

    width: parent ? parent.width : 400
    implicitHeight: 36

    function _snap(v) {
        v = Math.min(to, Math.max(from, v));
        v = from + Math.round((v - from) / step) * step;
        return Number(v.toFixed(decimals));
    }
    readonly property real _frac: to > from ? (value - from) / (to - from) : 0

    Label {
        id: lbl
        text: root.label
        width: 170
        anchors.verticalCenter: parent.verticalCenter
    }
    Item {
        id: track
        anchors { left: lbl.right; leftMargin: 8; right: val.left; rightMargin: 16; verticalCenter: parent.verticalCenter }
        height: 24
        Rectangle {
            id: groove
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width; height: 6; radius: 3
            color: Theme.withAlpha(Theme.text, 0.12)
            Rectangle {
                width: Math.max(groove.height, root._frac * groove.width)
                height: parent.height; radius: parent.radius
                color: Theme.accent
                Behavior on width { enabled: !drag.pressed; Anim { duration: Motion.fast } }
            }
        }
        Rectangle {
            id: knob
            width: 18; height: 18; radius: 9
            anchors.verticalCenter: parent.verticalCenter
            x: root._frac * (track.width - width)
            color: drag.pressed || drag.containsMouse ? Theme.accentBright : Theme.text
            border.width: 2
            border.color: Theme.accent
            Behavior on x { enabled: !drag.pressed; Anim { duration: Motion.fast } }
            Behavior on color { CAnim {} }
        }
        MouseArea {
            id: drag
            anchors.fill: parent
            anchors.margins: -6
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            function _at(mx) { return root._snap(root.from + (mx - 6 - knob.width / 2) / (track.width - knob.width) * (root.to - root.from)); }
            onPressed: mouse => root.moved(_at(mouse.x))
            onPositionChanged: mouse => { if (pressed) root.moved(_at(mouse.x)); }
            onWheel: wheel => root.moved(root._snap(root.value + (wheel.angleDelta.y > 0 ? root.step : -root.step)))
        }
    }
    Label {
        id: val
        width: 56
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        horizontalAlignment: Text.AlignRight
        font.family: Theme.fontMono
        color: Theme.accentBright
        text: root.value.toFixed(root.decimals) + root.suffix
    }
}
