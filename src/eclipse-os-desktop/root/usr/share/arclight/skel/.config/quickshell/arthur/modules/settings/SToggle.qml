import QtQuick
import qs.common
import qs.components

// Labelled switch row.
Item {
    id: root
    property string label: ""
    property string hint: ""
    property bool checked: false
    signal toggled(bool checked)

    width: parent ? parent.width : 400
    implicitHeight: hint !== "" ? 48 : 36

    Column {
        anchors { left: parent.left; right: sw.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
        spacing: 2
        Label { text: root.label; width: parent.width }
        Label { visible: root.hint !== ""; text: root.hint; width: parent.width; color: Theme.muted; font.pixelSize: Theme.fontSmall }
    }
    Rectangle {
        id: sw
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        width: 44; height: 24; radius: 12
        color: root.checked ? Theme.accent : Theme.withAlpha(Theme.text, 0.14)
        Behavior on color { CAnim {} }
        Rectangle {
            width: 18; height: 18; radius: 9
            anchors.verticalCenter: parent.verticalCenter
            x: root.checked ? parent.width - width - 3 : 3
            color: Theme.text
            Behavior on x { Anim { duration: Motion.fast } }
        }
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
}
