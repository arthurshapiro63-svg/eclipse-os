import QtQuick
import Quickshell
import Quickshell.Hyprland
import qs.common
import qs.components

// Title of the focused window, only on the monitor that holds it.
Item {
    id: root

    required property string screenName
    property int maxWidth: 420
    readonly property var tl: Hyprland.activeToplevel
    readonly property var topMon: tl ? (tl.monitor ?? (tl.workspace ? tl.workspace.monitor : null)) : null
    readonly property bool here: !!tl && !!topMon && topMon.name === screenName
                                 && !!topMon.activeWorkspace && !!tl.workspace && tl.workspace.id === topMon.activeWorkspace.id
    readonly property string title: here ? (tl.title || "") : ""

    implicitWidth: title === "" ? 0 : Math.min(maxWidth, label.implicitWidth)
    implicitHeight: parent ? parent.height : 26
    opacity: title === "" ? 0 : 1
    visible: opacity > 0
    Behavior on opacity { Anim { duration: Motion.fast } }
    Behavior on implicitWidth { Anim { duration: Motion.normal } }

    Label {
        id: label
        anchors.verticalCenter: parent.verticalCenter
        width: root.width
        text: root.title
        color: Theme.text2
        elide: Text.ElideRight
    }
}
