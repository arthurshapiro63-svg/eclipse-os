import QtQuick
import qs.common
import qs.components

// Glyph button at the dock ends (launcher, side panel), with the same hover lift + label.
Item {
    id: root

    property string glyph: ""
    property string label: ""
    property bool checked: false
    property int iconSize: Config.dock.iconSize
    readonly property bool hovered: mouse.containsMouse

    signal clicked()

    implicitWidth: iconSize + 12
    implicitHeight: iconSize + 16

    Rectangle {
        anchors.centerIn: glyphText
        width: root.iconSize + 10
        height: root.iconSize + 10
        radius: Theme.radiusMd
        color: root.checked ? Theme.accentSoft : Theme.hoverFill
        opacity: root.checked || root.hovered ? 1 : 0
        Behavior on opacity { Anim { duration: Motion.fast } }
        Behavior on color { CAnim {} }
    }

    Icon {
        id: glyphText
        width: root.iconSize
        height: root.iconSize
        x: (root.width - width) / 2
        y: 6 - (root.hovered ? 4 : 0)
        text: root.glyph
        size: Math.round(root.iconSize * 0.62)
        color: root.checked ? Theme.accentBright : Theme.text
        Behavior on y { Anim { duration: Motion.fast } }
        Behavior on color { CAnim {} }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    DockTooltip {
        text: root.label
        shown: root.hovered
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.top
        anchors.bottomMargin: 16
    }
}
