import QtQuick
import qs.common
import qs.components

// Scrollable page: big title, one-line subtitle, then cards.
Flickable {
    id: root
    property string title: ""
    property string subtitle: ""
    default property alias content: col.data

    clip: true
    contentWidth: width
    contentHeight: col.implicitHeight + 32
    boundsBehavior: Flickable.StopAtBounds

    Column {
        id: col
        x: 28; y: 24
        width: root.width - 56
        spacing: 14
        Column {
            width: parent.width
            spacing: 4
            Label { text: root.title; font.pixelSize: Theme.fontLarge; font.weight: Font.Bold }
            Label { visible: root.subtitle !== ""; text: root.subtitle; color: Theme.muted; width: parent.width }
        }
    }
}
