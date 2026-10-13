import QtQuick
import qs.common
import qs.components

// Icon + text button. primary = accent fill. Hover eases (Motion.fast).
Rectangle {
    id: root
    property string icon: ""
    property string text: ""
    property bool primary: false
    property bool danger: false
    signal clicked()

    implicitHeight: 36
    implicitWidth: row.implicitWidth + 28
    radius: Theme.radiusMd
    opacity: enabled ? 1 : 0.45
    color: primary ? (area.containsMouse ? Theme.accentBright : Theme.accent)
         : (area.containsMouse ? Theme.hoverFill : Theme.cardFill)
    border.width: primary ? 0 : 1
    border.color: Theme.edge
    Behavior on color { CAnim {} }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 8
        Icon {
            visible: root.icon !== ""
            text: root.icon
            size: 16
            color: root.primary ? Theme.bgBase : (root.danger ? Theme.error : Theme.text)
            anchors.verticalCenter: parent.verticalCenter
        }
        Label {
            visible: root.text !== ""
            text: root.text
            font.weight: Font.DemiBold
            color: root.primary ? Theme.bgBase : Theme.text
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: if (root.enabled) root.clicked()
    }
}
