pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import qs.common
import qs.components
import qs.services

// Power menu (owner: agent C). Centred glass modal on the active screen; the compositor dims
// what is behind it (layer rule dim-arthur-modals). Keyboard: arrows, Enter, Escape, and the
// letters L/O/S/R/P. Log out, Reboot and Shut down need a second press within 4 s.
// Commands are data (`commands`); ARTHUR_POWER_DRYRUN=1 in the shell's environment logs them
// instead of running them, so tests can drive the menu without firing anything.
Scope {
    id: root

    readonly property var screenObj: Quickshell.screens.find(s => s.name === ShellState.activeScreen) ?? null

    readonly property bool open: ShellState.powerOpen
    property var commands: ({
        lock: "pidof hyprlock || hyprlock",
        logout: "hyprctl dispatch 'hl.dsp.exit()'",
        suspend: "systemctl suspend",
        reboot: "systemctl reboot",
        poweroff: "systemctl poweroff"
    })
    property bool dryRun: Quickshell.env("ARTHUR_POWER_DRYRUN") === "1"
    // runner(id, command): replace to intercept; default runs the command detached via sh.
    property var runner: (id, cmd) => {
        if (root.dryRun) { console.info("PowerMenu: dry run", id, "->", cmd); return; }
        Quickshell.execDetached(["sh", "-c", cmd]);
    }

    readonly property var items: [
        { id: "lock",     label: "Lock",      key: "L", icon: "\u{f033e}", confirm: false, verb: "lock" },
        { id: "logout",   label: "Log out",   key: "O", icon: "\u{f0343}", confirm: true,  verb: "log out" },
        { id: "suspend",  label: "Suspend",   key: "S", icon: "\u{f04b2}", confirm: false, verb: "suspend" },
        { id: "reboot",   label: "Reboot",    key: "R", icon: "\u{f0709}", confirm: true,  verb: "reboot" },
        { id: "poweroff", label: "Shut down", key: "P", icon: "\u{f0425}", confirm: true,  verb: "shut down" }
    ]
    property int current: 0
    readonly property int tileWidth: 104
    property string armed: ""            // id waiting for its second press

    function trigger(index) {
        const it = items[index];
        if (!it) return;
        current = index;
        if (it.confirm && armed !== it.id) {
            armed = it.id;
            disarm.restart();
            return;
        }
        armed = "";
        ShellState.close("power");
        root.runner(it.id, root.commands[it.id]);
    }

    onOpenChanged: { armed = ""; if (open) current = 0; }

    Timer { id: disarm; interval: 4000; onTriggered: root.armed = "" }

    PanelWindow {
        id: win

        property real shown: root.open ? 1 : 0
        Behavior on shown { Anim { duration: Motion.slow; easing.bezierCurve: root.open ? Motion.emphasized : Motion.exit } }

        screen: root.screenObj
        visible: !!root.screenObj && (root.open || shown > 0.001)

        WlrLayershell.namespace: "arthur-power"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: root.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"

        BackgroundEffect.blurRegion: Region { item: glass; radius: glass.radius }

        // click outside the card closes
        MouseArea {
            anchors.fill: parent
            onClicked: ShellState.close("power")
        }

        Glass {
            id: glass
            tone: "panel"
            anchors.centerIn: parent
            anchors.verticalCenterOffset: (1 - win.shown) * 24
            width: row.implicitWidth + 2 * 20
            height: col.implicitHeight + 2 * 20
            opacity: win.shown
            scale: 0.96 + 0.04 * win.shown

            // swallow clicks on the card itself
            MouseArea { anchors.fill: parent }

            Item {
                id: keys
                focus: true
                Keys.onPressed: event => {
                    const k = event.key;
                    if (k === Qt.Key_Escape) { ShellState.close("power"); }
                    else if (k === Qt.Key_Left || k === Qt.Key_Up || k === Qt.Key_Backtab) { root.current = (root.current + root.items.length - 1) % root.items.length; root.armed = ""; }
                    else if (k === Qt.Key_Right || k === Qt.Key_Down || k === Qt.Key_Tab) { root.current = (root.current + 1) % root.items.length; root.armed = ""; }
                    else if (k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) { root.trigger(root.current); }
                    else {
                        const i = root.items.findIndex(it => it.key === event.text.toUpperCase());
                        if (i < 0) return;
                        root.trigger(i);
                    }
                    event.accepted = true;
                }
            }
            Connections {
                target: root
                function onOpenChanged() { if (root.open) keys.forceActiveFocus(); }
            }

            ColumnLayout {
                id: col
                anchors.centerIn: parent
                spacing: 14

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: root.armed !== "" ? "Press again to " + root.items.find(i => i.id === root.armed).verb : "Power"
                    color: root.armed !== "" ? Theme.warning : Theme.text
                    font.pixelSize: Theme.fontLarge + 2
                    font.weight: Font.DemiBold
                    Behavior on color { CAnim {} }
                }

                Item {
                    Layout.preferredWidth: row.implicitWidth
                    Layout.preferredHeight: row.implicitHeight

                    // gliding selection
                    Rectangle {
                        x: root.current * (root.tileWidth + row.spacing)
                        width: root.tileWidth
                        height: row.implicitHeight
                        radius: Theme.radiusMd
                        color: root.armed !== "" ? Theme.withAlpha(Theme.warning, 0.20) : Theme.accentSoft
                        border.width: 1
                        border.color: root.armed !== "" ? Theme.withAlpha(Theme.warning, 0.55) : Theme.withAlpha(Theme.accent, 0.55)
                        Behavior on x { Anim { duration: Motion.normal } }
                        Behavior on color { CAnim {} }
                    }

                    Row {
                        id: row
                        spacing: 8
                        Repeater {
                            id: rep
                            model: root.items
                            delegate: Item {
                                id: tile
                                required property var modelData
                                required property int index
                                readonly property bool isArmed: root.armed === modelData.id
                                width: root.tileWidth
                                height: 112

                                Rectangle {
                                    anchors.fill: parent
                                    radius: Theme.radiusMd
                                    color: tileHover.hovered && root.current !== tile.index ? Theme.hoverFill : "transparent"
                                    Behavior on color { CAnim {} }
                                }
                                Column {
                                    anchors.centerIn: parent
                                    spacing: 6
                                    Icon {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: tile.modelData.icon
                                        size: 30
                                        color: tile.isArmed ? Theme.warning : root.current === tile.index ? Theme.accentBright : Theme.text
                                        Behavior on color { CAnim {} }
                                    }
                                    Label {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        text: tile.isArmed ? "Again" : tile.modelData.label
                                        font.pixelSize: Theme.fontSize + 1
                                        font.weight: Font.Medium
                                    }
                                    Rectangle {
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        width: 22; height: 20
                                        radius: Theme.radiusSm
                                        color: Theme.cardFill
                                        border.width: 1
                                        border.color: Theme.edge
                                        Label {
                                            anchors.centerIn: parent
                                            text: tile.modelData.key
                                            font.family: Theme.fontMono
                                            font.pixelSize: Theme.fontSmall
                                            color: Theme.text2
                                        }
                                    }
                                }
                                HoverHandler { id: tileHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: root.trigger(tile.index) }
                            }
                        }
                    }
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Arrows + Enter   ·   Esc to close"
                    color: Theme.muted
                    font.pixelSize: Theme.fontSmall
                }
            }
        }
    }
}
