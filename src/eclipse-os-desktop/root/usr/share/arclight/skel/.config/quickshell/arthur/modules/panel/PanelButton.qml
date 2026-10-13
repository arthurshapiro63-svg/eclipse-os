import QtQuick
import qs.common
import qs.components

// Round-cornered icon (+ optional label) button used across the side panel.
Rectangle {
    id: root

    property string icon: ""
    property string label: ""
    property real iconSize: 18
    property bool active: false
    property color iconColor: active ? Theme.accentBright : Theme.text
    signal clicked()

    implicitWidth: label === "" ? 34 : Math.max(34, row.implicitWidth + 20)
    implicitHeight: 34
    radius: Theme.radiusMd
    color: active ? Theme.accentSoft : hover.hovered ? Theme.hoverFill : "transparent"
    Behavior on color { CAnim {} }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        Icon { text: root.icon; size: root.iconSize; color: root.iconColor; anchors.verticalCenter: parent.verticalCenter }
        Label { visible: root.label !== ""; text: root.label; anchors.verticalCenter: parent.verticalCenter }
    }

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: root.clicked() }
}
