import QtQuick
import Quickshell
import qs.common
import qs.components

// Small glass tooltip under a bar chip. Created only while shown (see BarButton).
PopupWindow {
    id: root

    required property Item target
    property string text: ""

    anchor.item: target
    anchor.edges: Edges.Bottom
    anchor.gravity: Edges.Bottom
    anchor.adjustment: PopupAdjustment.Slide
    implicitWidth: glass.width
    implicitHeight: glass.height + 8
    color: "transparent"
    visible: true

    Glass {
        id: glass
        tone: "menu"
        radius: Theme.radiusMd
        shadowEnabled: false
        y: 8
        width: label.implicitWidth + 2 * Theme.pad
        height: label.implicitHeight + 2 * 8
        opacity: 0
        Component.onCompleted: opacity = 1
        Behavior on opacity { Anim { duration: Motion.fast } }

        Label {
            id: label
            anchors.centerIn: parent
            text: root.text
            color: Theme.text
            font.pixelSize: Theme.fontSmall + 1
            elide: Text.ElideNone
        }
    }
}
