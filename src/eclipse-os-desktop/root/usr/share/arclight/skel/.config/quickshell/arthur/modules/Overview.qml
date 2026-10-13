pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.common
import qs.components
import qs.services
import qs.modules.overview

// Workspace overview (SUPER+Tab): a glass grid of workspaces. Row 1 = the monitor of
// ShellState.activeScreen, following rows = the other monitors. Each tile lists its
// windows (app icon + title). Click a tile = go to that workspace, click a window =
// focus it. Arrows move the selection, Enter goes there, Escape closes.
// The window maps only while open; nothing is evaluated while closed.
Scope {
    id: root

    readonly property bool open: ShellState.overviewOpen
    property bool mapped: false
    property real progress: 0

    onOpenChanged: {
        if (open) {
            Hyprland.refreshWorkspaces();
            Hyprland.refreshToplevels();
            mapped = true;
            progress = 1;
            selRow = 0;
            selCol = Math.max(0, rowsModel.length > 0 ? rowsModel[0].workspaces.findIndex(w => w.active) : 0);
            focusLater.restart();
        } else {
            progress = 0;
        }
    }
    onProgressChanged: if (progress === 0 && !open) mapped = false
    Timer { id: focusLater; interval: 0; onTriggered: keys.forceActiveFocus() }
    Behavior on progress {
        Anim {
            duration: root.open ? Motion.slow : Motion.fast
            easing.bezierCurve: root.open ? Motion.emphasized : Motion.exit
        }
    }

    // [{ monitor: name, workspaces: [{ id, name, active, focused, windows: [{ address, title, appId }] }] }]
    readonly property var rowsModel: {
        if (!mapped) return [];
        const mons = Hyprland.monitors.values.map(m => m.name);
        const active = ShellState.activeScreen;
        mons.sort((a, b) => (a === active ? -1 : b === active ? 1 : a.localeCompare(b)));
        const wss = Hyprland.workspaces.values.filter(w => w.id > 0 && w.monitor);
        return mons.map(name => ({
            monitor: name,
            workspaces: wss.filter(w => w.monitor.name === name)
                .sort((a, b) => a.id - b.id)
                .map(w => ({
                    id: w.id, name: w.name, active: w.active, focused: w.focused,
                    windows: w.toplevels.values.map(t => ({
                        address: t.address,
                        title: t.title || "",
                        appId: t.wayland ? t.wayland.appId : ((t.lastIpcObject && t.lastIpcObject["class"]) || "")
                    }))
                }))
        })).filter(r => r.workspaces.length > 0);
    }

    property int selRow: 0
    property int selCol: 0

    function moveSel(dr, dc) {
        if (rowsModel.length === 0) return;
        let r = Math.max(0, Math.min(rowsModel.length - 1, selRow + dr));
        const n = rowsModel[r].workspaces.length;
        let c = dr !== 0 ? Math.min(selCol, n - 1) : (selCol + dc + n) % n;
        selRow = r;
        selCol = c;
    }
    function goWorkspace(id) {
        ShellState.close("overview");
        Hyprland.dispatch("hl.dsp.focus({ workspace = " + Number(id) + " })");
    }
    function focusWindow(address) {
        const a = String(address);
        const sel = "address:" + (a.startsWith("0x") ? a : "0x" + a);
        ShellState.close("overview");
        Hyprland.dispatch("hl.dsp.focus({ window = \"" + sel + "\" })");
    }

    PanelWindow {
        id: win
        screen: Quickshell.screens.find(s => s.name === ShellState.activeScreen) ?? null
        visible: root.mapped
        color: "transparent"
        WlrLayershell.namespace: "arthur-overview"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: root.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; bottom: true; left: true; right: true }
        // Blur follows the glass as it scales in (Region tracks geometry, not transforms).
        BackgroundEffect.blurRegion: Region {
            readonly property real s: glass.scale
            x: Math.round(glass.x + glass.width * (1 - s) / 2)
            y: Math.round(glass.y + glass.height * (1 - s) / 2)
            width: root.progress > 0.02 ? Math.round(glass.width * s) : 0
            height: root.progress > 0.02 ? Math.round(glass.height * s) : 0
            radius: Math.round(glass.radius * s)
        }

        MouseArea {
            anchors.fill: parent
            enabled: root.open
            onClicked: ShellState.close("overview")
        }

        Item {
            id: keys
            focus: true
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Escape) { ShellState.close("overview"); event.accepted = true; }
                else if (event.key === Qt.Key_Left) { root.moveSel(0, -1); event.accepted = true; }
                else if (event.key === Qt.Key_Right || event.key === Qt.Key_Tab) { root.moveSel(0, 1); event.accepted = true; }
                else if (event.key === Qt.Key_Backtab) { root.moveSel(0, -1); event.accepted = true; }
                else if (event.key === Qt.Key_Up) { root.moveSel(-1, 0); event.accepted = true; }
                else if (event.key === Qt.Key_Down) { root.moveSel(1, 0); event.accepted = true; }
                else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                    const r = root.rowsModel[root.selRow];
                    const w = r ? r.workspaces[root.selCol] : null;
                    if (w) root.goWorkspace(w.id);
                    event.accepted = true;
                }
            }
        }

        readonly property int maxCols: Math.max(1, ...root.rowsModel.map(r => r.workspaces.length))
        readonly property int tileW: Math.min(300, Math.floor((width - 2 * Theme.shadowPad - 2 * 20 - (maxCols - 1) * 12) / maxCols))
        readonly property int tileH: Math.round(tileW * 0.66)

        Glass {
            id: glass
            tone: "panel"
            width: grid.implicitWidth + 40
            height: grid.implicitHeight + 40
            anchors.centerIn: parent
            opacity: root.progress
            scale: 0.95 + 0.05 * root.progress
            MouseArea { anchors.fill: parent }

            Column {
                id: grid
                anchors.centerIn: parent
                spacing: 16

                Repeater {
                    model: root.rowsModel
                    delegate: Column {
                        id: monRow
                        required property var modelData
                        required property int index
                        spacing: 8

                        Label {
                            text: monRow.modelData.monitor
                            color: Theme.text2
                            font.pixelSize: Theme.fontSmall
                            font.family: Theme.fontMono
                            leftPadding: 4
                        }
                        Row {
                            spacing: 12
                            Repeater {
                                model: monRow.modelData.workspaces
                                delegate: WorkspaceTile {
                                    required property var modelData
                                    required property int index
                                    workspace: modelData
                                    width: win.tileW
                                    height: win.tileH
                                    selected: root.selRow === monRow.index && root.selCol === index
                                    onPicked: root.goWorkspace(modelData.id)
                                    onWindowPicked: address => root.focusWindow(address)
                                    onHovered: { root.selRow = monRow.index; root.selCol = index; }
                                }
                            }
                        }
                    }
                }

                Label {
                    anchors.right: parent.right
                    text: "←→↑↓ move   ↵ go   esc close"
                    color: Theme.muted
                    font.pixelSize: Theme.fontSmall
                }
            }
        }
    }
}
