pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Hyprland
import qs.common
import qs.components

// Workspaces of ONE monitor: its pinned range (always shown, even empty) plus any other
// workspace that currently lives on it. Active = gliding accent pill, occupied = dot,
// urgent = red. Click focuses, scroll walks next/prev inside this monitor's list.
Item {
    id: root

    required property string screenName
    property var pinned: []                     // workspace ids pinned to this monitor
    readonly property var monitor: Hyprland.monitors.values.find(m => m.name === root.screenName) ?? null
    readonly property int activeId: monitor && monitor.activeWorkspace ? monitor.activeWorkspace.id : -1
    readonly property var liveHere: Hyprland.workspaces.values.filter(w => w.id > 0 && w.monitor && w.monitor.name === root.screenName)
    readonly property var ids: {
        const s = new Set(root.pinned);
        for (const w of root.liveHere) s.add(w.id);
        return Array.from(s).sort((a, b) => a - b);
    }
    readonly property int activeIndex: ids.indexOf(activeId)
    readonly property int cell: 28

    function wsById(id) { return Hyprland.workspaces.values.find(w => w.id === id) ?? null; }
    function focus(id) { if (id !== root.activeId) Hyprland.dispatch("hl.dsp.focus({ workspace = " + id + " })"); }

    implicitWidth: ids.length * cell
    implicitHeight: parent ? parent.height : 26

    // gliding active indicator
    Rectangle {
        id: indicator
        visible: root.activeIndex >= 0
        x: root.activeIndex * root.cell + 2
        width: root.cell - 4
        height: parent.height
        radius: Theme.radiusMd
        color: Theme.accentSoft
        border.width: 1
        border.color: Theme.withAlpha(Theme.accent, 0.45)
        Behavior on x { Anim { duration: Motion.normal; easing.bezierCurve: Motion.liquid } }
        Behavior on width { Anim { duration: Motion.normal } }
    }

    Row {
        anchors.fill: parent
        Repeater {
            model: root.ids
            delegate: MouseArea {
                id: cellArea
                required property int modelData
                readonly property var ws: root.wsById(modelData)
                readonly property bool isActive: modelData === root.activeId
                readonly property bool occupied: !!ws && ws.toplevels.values.length > 0
                readonly property bool urgent: !!ws && ws.urgent
                width: root.cell
                height: root.height
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.focus(modelData)

                Rectangle {
                    anchors.fill: parent
                    anchors.leftMargin: 2; anchors.rightMargin: 2
                    radius: Theme.radiusMd
                    color: cellArea.containsMouse && !cellArea.isActive ? Theme.hoverFill : Theme.withAlpha(Theme.surfaceHover, 0)
                    Behavior on color { CAnim {} }
                }
                Text {
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -1
                    text: cellArea.modelData
                    font.family: Theme.fontMono
                    font.pixelSize: Theme.fontSize
                    font.weight: cellArea.isActive ? Font.Bold : Font.Medium
                    renderType: Text.NativeRendering
                    color: cellArea.urgent ? Theme.error
                         : cellArea.isActive ? Theme.accentBright
                         : cellArea.occupied ? Theme.text : Theme.withAlpha(Theme.text2, 0.75)
                    Behavior on color { CAnim {} }
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 3
                    width: cellArea.isActive ? 10 : 4
                    height: 2
                    radius: 1
                    opacity: cellArea.occupied || cellArea.urgent ? 1 : 0
                    color: cellArea.urgent ? Theme.error : cellArea.isActive ? Theme.accentBright : Theme.text2
                    Behavior on opacity { Anim { duration: Motion.fast } }
                    Behavior on width { Anim { duration: Motion.fast } }
                    Behavior on color { CAnim {} }
                }
            }
        }
    }

    // scroll = next/prev workspace of this monitor (one step per wheel notch)
    property real _acc: 0
    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: event => {
            root._acc += event.angleDelta.y;
            if (Math.abs(root._acc) < 120) return;
            const step = root._acc < 0 ? 1 : -1;
            root._acc = 0;
            const i = Math.max(0, root.activeIndex);
            const n = Math.max(0, Math.min(root.ids.length - 1, i + step));
            if (root.ids[n] !== undefined) root.focus(root.ids[n]);
        }
    }
}
