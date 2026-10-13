import QtQuick
import Quickshell
import Quickshell.Widgets
import qs.common
import qs.components
import qs.services

// One app in the dock: icon, hover lift + label tooltip, running dots, active highlight.
// `appId` is the pinned desktop id or the window class; everything else is derived.
Item {
    id: root

    required property string appId
    property bool pinned: false
    property int iconSize: Config.dock.iconSize

    readonly property string key: Apps.keyFor(appId)
    readonly property var windows: Apps.windowsFor(key)
    readonly property bool running: windows.length > 0
    readonly property bool active: windows.some(t => t.activated)
    readonly property string label: Apps.entryFor(appId) ? Apps.nameFor(appId)
                                  : (windows.length > 0 && windows[0].title ? windows[0].title : appId)
    readonly property bool hovered: mouse.containsMouse

    signal menuRequested(Item item)

    implicitWidth: iconSize + 12
    implicitHeight: iconSize + 16

    // hover / active backdrop
    Rectangle {
        anchors.centerIn: iconBox
        width: root.iconSize + 10
        height: root.iconSize + 10
        radius: Theme.radiusMd
        color: root.active ? Theme.accentSoft : Theme.hoverFill
        opacity: root.active ? 1 : (root.hovered ? 1 : 0)
        Behavior on opacity { Anim { duration: Motion.fast } }
        Behavior on color { CAnim {} }
    }

    Item {
        id: iconBox
        width: root.iconSize
        height: root.iconSize
        x: (root.width - width) / 2
        y: 6 - (root.hovered ? 4 : 0)
        Behavior on y { Anim { duration: Motion.fast } }

        IconImage {
            anchors.fill: parent
            source: Apps.iconFor(root.appId)
            asynchronous: true
            mipmap: true
        }
    }

    // running dots: one per window, max three; accent when the app is focused
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 2
        spacing: 3
        Repeater {
            model: Math.min(3, root.windows.length)
            Rectangle {
                required property int index
                width: root.active && index === 0 ? 10 : 4
                height: 4
                radius: 2
                color: root.active ? Theme.accentBright : Theme.text2
                Behavior on width { Anim { duration: Motion.normal } }
                Behavior on color { CAnim {} }
            }
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        cursorShape: Qt.PointingHandCursor
        onClicked: ev => {
            if (ev.button === Qt.RightButton) root.menuRequested(root);
            else if (ev.button === Qt.MiddleButton) Apps.launch(root.appId);
            else if (!Apps.activate(root.key)) Apps.launch(root.appId);
        }
    }

    DockTooltip {
        text: root.label
        shown: root.hovered
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.top
        anchors.bottomMargin: 16
    }
}
