import QtQuick
import qs.common
import qs.components

// Sidebar entry: glyph + short label. The selection pill itself glides in the sidebar.
Item {
    id: root
    property string icon: ""
    property string text: ""
    property bool current: false
    signal clicked()

    width: parent ? parent.width : 200
    height: 42

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusMd
        color: area.containsMouse && !root.current ? Theme.hoverFill : "transparent"
        Behavior on color { CAnim {} }
    }
    Row {
        anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
        spacing: 12
        Icon { text: root.icon; size: 18; width: 22; color: root.current ? Theme.accentBright : Theme.text2; anchors.verticalCenter: parent.verticalCenter
               Behavior on color { CAnim {} } }
        Label { text: root.text; font.weight: root.current ? Font.DemiBold : Font.Normal; color: root.current ? Theme.text : Theme.text2
                anchors.verticalCenter: parent.verticalCenter; Behavior on color { CAnim {} } }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
