import QtQuick
import qs.common
import qs.components

// Quick-toggle tile: big icon, short name, one-line state. Accent fill while on.
Rectangle {
    id: root

    property string icon: ""
    property string name: ""
    property string status: ""
    property bool on: false
    property bool available: true
    property bool expandable: false       // shows a chevron zone on the right that opens a list
    property bool expanded: false
    signal clicked()
    signal expandClicked()

    implicitHeight: 64
    radius: Theme.radiusMd
    opacity: available ? 1 : 0.45
    color: on ? Theme.withAlpha(Theme.accent, hover.hovered ? 0.40 : 0.30)
              : hover.hovered ? Theme.hoverFill : Theme.cardFill
    border.width: 1
    border.color: on ? Theme.withAlpha(Theme.accent, 0.55) : Theme.edge
    Behavior on color { CAnim {} }
    Behavior on border.color { CAnim {} }

    Icon {
        id: glyph
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        text: root.icon
        size: 22
        color: root.on ? Theme.accentBright : Theme.text2
        Behavior on color { CAnim {} }
    }
    Column {
        anchors.left: glyph.right
        anchors.leftMargin: 10
        anchors.right: root.expandable ? chevron.left : parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 1
        Label { width: parent.width; text: root.name; font.weight: Font.DemiBold }
        Label { width: parent.width; text: root.status; color: Theme.text2; font.pixelSize: Theme.fontSmall }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        enabled: root.available
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
    QtObject { id: hover; readonly property bool hovered: area.containsMouse }

    // chevron zone: its own tap target, drawn above the tile's
    Rectangle {
        id: chevron
        visible: root.expandable
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 6
        width: visible ? 30 : 0
        radius: Theme.radiusSm
        color: chevHover.hovered || root.expanded ? Theme.withAlpha(Theme.text, 0.10) : "transparent"
        Behavior on color { CAnim {} }
        Icon {
            anchors.centerIn: parent
            text: "\u{f0140}"
            size: 18
            color: Theme.text2
            rotation: root.expanded ? 180 : 0
            Behavior on rotation { Anim { duration: Motion.normal } }
        }
        MouseArea {
            id: chevArea
            anchors.fill: parent
            enabled: root.available
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.expandClicked()
        }
        QtObject { id: chevHover; readonly property bool hovered: chevArea.containsMouse }
    }
}
