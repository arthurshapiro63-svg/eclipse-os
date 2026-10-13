import QtQuick
import Quickshell.Widgets
import qs.common
import qs.components
import qs.services

// One carousel card: cached 480x270 thumbnail, larger when focused, accent ring when it is
// the wallpaper on screen now. Emits activated() on click.
Item {
    id: cell

    required property int index
    required property string path
    required property string name
    required property string thumb
    required property bool ready

    property int thumbW: 208
    property int thumbH: 117
    readonly property bool focused: ListView.isCurrentItem
    readonly property bool isCurrent: path === Wallpapers.current
    readonly property int distance: ListView.view ? Math.abs(index - ListView.view.currentIndex) : 0
    signal activated()

    height: ListView.view ? ListView.view.height : thumbH
    opacity: focused ? 1 : Math.max(0.45, 0.95 - distance * 0.12)
    Behavior on opacity { Anim { duration: Motion.normal } }

    Item {
        id: card
        anchors.centerIn: parent
        width: cell.thumbW
        height: cell.thumbH
        scale: cell.focused ? 1 : (hover.containsMouse ? 0.84 : 0.78)
        Behavior on scale { Anim { duration: Motion.normal } }

        // lift under the focused card
        Rectangle {
            anchors.fill: parent
            anchors.margins: -6
            radius: Theme.radiusMd + 6
            color: Theme.accentSoft
            opacity: cell.focused ? 1 : 0
            Behavior on opacity { Anim { duration: Motion.fast } }
        }

        ClippingRectangle {
            anchors.fill: parent
            radius: Theme.radiusMd
            color: Theme.surfaceRaised

            Image {
                id: img
                anchors.fill: parent
                source: cell.ready ? "file://" + cell.thumb : ""
                sourceSize: Qt.size(480, 270)
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                smooth: true
                opacity: status === Image.Ready ? 1 : 0
                Behavior on opacity { Anim { duration: Motion.normal } }
            }

            // placeholder shimmer-free glyph while the thumbnail is being made
            Icon {
                anchors.centerIn: parent
                visible: img.status !== Image.Ready
                text: "\u{f02e9}"
                size: 22
                color: Theme.muted
            }
        }

        // perimeter edge: light when focused, faint otherwise
        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusMd
            color: "transparent"
            border.width: 1
            border.color: cell.focused ? Theme.hairline : Theme.edge
        }

        // the wallpaper on screen now: accent ring + dot
        Rectangle {
            visible: cell.isCurrent
            anchors.fill: parent
            anchors.margins: -3
            radius: Theme.radiusMd + 3
            color: "transparent"
            border.width: 2
            border.color: Theme.accent
        }
        Rectangle {
            visible: cell.isCurrent
            width: 18; height: 18; radius: 9
            anchors { right: parent.right; top: parent.top; margins: 6 }
            color: Theme.accent
            Icon { anchors.centerIn: parent; text: "\u{f012c}"; size: 12; color: Theme.text }
        }

        MouseArea {
            id: hover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: cell.activated()
        }
    }
}
