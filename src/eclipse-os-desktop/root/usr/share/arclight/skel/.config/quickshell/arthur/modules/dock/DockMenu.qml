import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.common
import qs.components
import qs.services

// Right-click menu for one dock app: New window / Pin or Unpin / Close.
// A small glass layer surface (namespace arthur-menu) placed just above the dock.
// Closes on a pick, on an outside click (Hyprland focus grab) or when `open` goes false.
PanelWindow {
    id: win

    property bool open: false
    property string appId: ""
    property real centerX: 0          // x of the clicked icon's centre, in screen coordinates
    property int bottomOffset: 0      // distance from the screen bottom to the dock glass top
    property var grabWindows: []
    property bool grab: true

    signal closeRequested()

    readonly property string key: Apps.keyFor(appId)
    readonly property var windows: Apps.windowsFor(key)
    readonly property bool pinned: Apps.isPinned(appId)
    readonly property bool canLaunch: !!Apps.entryFor(appId)

    WlrLayershell.namespace: "arthur-menu"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusiveZone: 0
    color: "transparent"
    anchors { bottom: true; left: true }
    margins.bottom: Math.max(0, bottomOffset + 8 - Theme.shadowPad)
    margins.left: Math.max(0, Math.round(centerX - implicitWidth / 2))
    implicitWidth: glass.width + 2 * Theme.shadowPad
    implicitHeight: glass.height + 2 * Theme.shadowPad
    visible: open || glass.opacity > 0
    BackgroundEffect.blurRegion: Region { item: glass.body; radius: glass.radius }

    HyprlandFocusGrab {
        active: win.grab && win.open && win.visible
        windows: [win].concat(win.grabWindows)
        onCleared: win.closeRequested()
    }

    Glass {
        id: glass
        tone: "menu"
        radius: Theme.radiusMd
        x: Theme.shadowPad
        y: Theme.shadowPad + (win.open ? 0 : 6)
        width: Math.max(180, column.implicitWidth + 2 * 6)
        height: column.implicitHeight + 2 * 6
        opacity: win.open ? 1 : 0
        Behavior on opacity { Anim { duration: Motion.normal } }
        Behavior on y { Anim { duration: Motion.normal } }

        Column {
            id: column
            x: 6; y: 6
            width: glass.width - 12

            Label {
                width: parent.width
                height: 30
                leftPadding: 10
                rightPadding: 10
                text: Apps.nameFor(win.appId)
                color: Theme.text2
                font.pixelSize: Theme.fontSmall
                font.weight: Font.DemiBold
            }
            MenuRow {
                visible: win.canLaunch
                glyph: "\u{f0415}"
                text: win.windows.length > 0 ? "New window" : "Open"
                onPicked: Apps.launch(win.appId)
            }
            MenuRow {
                glyph: win.pinned ? "\u{f0931}" : "\u{f0403}"
                text: win.pinned ? "Unpin" : "Pin"
                onPicked: win.pinned ? Apps.unpin(win.appId) : Apps.pin(win.appId)
            }
            MenuRow {
                visible: win.windows.length > 0
                glyph: "\u{f0156}"
                text: win.windows.length > 1 ? "Close all (" + win.windows.length + ")" : "Close"
                danger: true
                onPicked: Apps.closeAll(win.key)
            }
        }
    }

    component MenuRow: Item {
        id: row
        property string glyph
        property string text
        property bool danger: false
        signal picked()
        width: column.width
        height: visible ? 34 : 0

        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusSm
            color: Theme.hoverFill
            opacity: rowMouse.containsMouse ? 1 : 0
            Behavior on opacity { Anim { duration: Motion.fast } }
        }
        Icon {
            x: 10
            width: 18
            anchors.verticalCenter: parent.verticalCenter
            text: row.glyph
            size: 16
            color: row.danger ? Theme.error : Theme.text2
        }
        Label {
            x: 38
            width: parent.width - 48
            anchors.verticalCenter: parent.verticalCenter
            text: row.text
            color: row.danger ? Theme.error : Theme.text
        }
        MouseArea {
            id: rowMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: { row.picked(); win.closeRequested(); }
        }
    }
}
