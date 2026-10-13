pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Widgets
import qs.common
import qs.components

// One workspace in the overview: number + window list (app icon + title).
Item {
    id: tile

    property var workspace: ({ id: 0, name: "", active: false, focused: false, windows: [] })
    property bool selected: false
    readonly property int maxShown: Math.max(1, Math.floor((height - 48) / 30))
    signal picked()
    signal windowPicked(string address)
    signal hovered()

    function iconFor(appId) {
        if (!appId) return "";
        const e = DesktopEntries.heuristicLookup(appId);
        return (e && e.icon ? Quickshell.iconPath(e.icon, true) : "") || Quickshell.iconPath(appId, true) || Quickshell.iconPath(appId.toLowerCase(), true);
    }

    Glass {
        id: card
        anchors.fill: parent
        tone: "card"
        fill: tile.selected ? Theme.accentSoft : tileMouse.containsMouse ? Theme.hoverFill : Theme.cardFill
        Behavior on fill { CAnim {} }

        // selection / active ring
        Rectangle {
            anchors.fill: parent
            radius: card.radius
            color: "transparent"
            border.width: tile.selected ? 2 : 1
            border.color: tile.selected ? Theme.accentBright : tile.workspace.active ? Theme.borderStrong : "transparent"
            Behavior on border.color { CAnim {} }
        }

        MouseArea {
            id: tileMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: tile.picked()
            onEntered: tile.hovered()
        }

        Row {
            x: 12; y: 10
            spacing: 8
            Label {
                text: tile.workspace.name || String(tile.workspace.id)
                font.family: Theme.fontMono
                font.pixelSize: Theme.fontLarge
                font.weight: Font.DemiBold
                color: tile.workspace.active ? Theme.accentBright : Theme.text
            }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: tile.workspace.windows.length === 0 ? "empty"
                    : tile.workspace.windows.length === 1 ? "1 window" : tile.workspace.windows.length + " windows"
                color: Theme.muted
                font.pixelSize: Theme.fontSmall
            }
        }

        Column {
            id: winList
            x: 8; y: 40
            width: parent.width - 16
            spacing: 2

            Repeater {
                model: tile.workspace.windows.slice(0, tile.maxShown)
                delegate: Item {
                    id: winRow
                    required property var modelData
                    width: winList.width
                    height: 28

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusSm
                        color: winMouse.containsMouse ? Theme.hoverFill : "transparent"
                        Behavior on color { CAnim {} }
                    }
                    IconImage {
                        id: appIcon
                        x: 6
                        anchors.verticalCenter: parent.verticalCenter
                        width: 20; height: 20
                        source: tile.iconFor(winRow.modelData.appId)
                        asynchronous: true
                        mipmap: true
                        visible: status === Image.Ready
                    }
                    Icon {
                        anchors.centerIn: appIcon
                        visible: appIcon.status !== Image.Ready
                        text: "\u{f08c6}"
                        size: 16
                        color: Theme.text2
                    }
                    Label {
                        anchors.left: appIcon.right
                        anchors.leftMargin: 8
                        anchors.right: parent.right
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        text: winRow.modelData.title || winRow.modelData.appId
                        font.pixelSize: Theme.fontSmall + 1
                        color: Theme.text
                    }
                    MouseArea {
                        id: winMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: tile.windowPicked(winRow.modelData.address)
                        onEntered: tile.hovered()
                    }
                }
            }
            Label {
                visible: tile.workspace.windows.length > tile.maxShown
                leftPadding: 8
                text: "+" + (tile.workspace.windows.length - tile.maxShown) + " more"
                color: Theme.muted
                font.pixelSize: Theme.fontSmall
            }
        }
    }
}
