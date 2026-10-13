import QtQuick
import qs.common
import qs.components

// A glass card (tone "card") with an optional title, content stacked in a column.
Glass {
    id: root
    tone: "card"
    property string title: ""
    property string icon: ""
    default property alias rows: col.data
    width: parent ? parent.width : 400
    implicitHeight: col.implicitHeight + 2 * 16

    Column {
        id: col
        x: 18; y: 16
        width: root.width - 36
        spacing: 10
        Row {
            visible: root.title !== ""
            spacing: 8
            height: 24
            Icon { visible: root.icon !== ""; text: root.icon; size: 16; color: Theme.accentBright; anchors.verticalCenter: parent.verticalCenter }
            Label { text: root.title; font.pixelSize: Theme.fontSize; font.weight: Font.DemiBold; color: Theme.text2; anchors.verticalCenter: parent.verticalCenter }
        }
    }
}
