import QtQuick
import qs.common
import qs.components

// Small label that fades + glides in above a hovered dock item. Liquid, no bounce.
Item {
    id: root

    property alias text: label.text
    property bool shown: false

    width: label.implicitWidth + 2 * Theme.pad
    height: 26
    opacity: shown ? 1 : 0
    visible: opacity > 0
    transform: Translate { y: root.shown ? 0 : 4; Behavior on y { Anim { duration: Motion.fast } } }
    Behavior on opacity { Anim { duration: Motion.fast } }

    Glass {
        anchors.fill: parent
        tone: "menu"
        radius: Theme.radiusSm
        shadowEnabled: false
    }
    Label {
        id: label
        anchors.centerIn: parent
        font.pixelSize: Theme.fontSmall + 1
        font.weight: Font.Medium
    }
}
