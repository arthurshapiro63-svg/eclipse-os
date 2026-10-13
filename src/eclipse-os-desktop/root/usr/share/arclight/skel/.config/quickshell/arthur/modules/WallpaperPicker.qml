pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.common
import qs.components
import qs.services
import qs.modules.wallpaper

// Wallpaper switcher (SUPER+W): a centred glass card on the active screen with a large
// live preview of the focused wallpaper and a carousel of cached thumbnails under it.
//   Left/Right or wheel: browse   Enter or click the focused card: apply   Esc/click outside: close
// Browsing never changes the desktop; only apply runs ~/.local/bin/wallpaper (awww grow
// transition on every output, persistence, matugen recolour in dynamic mode).
Scope {
    id: root

    readonly property bool open: ShellState.pickerOpen
    property int focusIndex: 0
    property real shown: open ? 1 : 0
    Behavior on shown {
        Anim {
            duration: root.open ? Motion.slow : Motion.normal
            easing.bezierCurve: root.open ? Motion.emphasized : Motion.exit
        }
    }

    readonly property var focusedRow: {
        const m = Wallpapers.model;
        return (focusIndex >= 0 && focusIndex < m.count) ? m.get(focusIndex) : null;
    }

    function syncFocus() {
        const i = Wallpapers.indexOf(Wallpapers.current);
        root.focusIndex = i >= 0 ? i : 0;
    }
    function step(d) {
        const n = Wallpapers.model.count;
        if (n > 0) root.focusIndex = Math.max(0, Math.min(n - 1, root.focusIndex + d));
    }
    function applyFocused() {
        const row = root.focusedRow;
        if (row && row.path !== Wallpapers.current) Wallpapers.apply(row.path);
        ShellState.close("picker");
    }

    onOpenChanged: {
        if (open) {
            syncFocus();
            Wallpapers.refresh();
        }
    }
    Connections {
        target: Wallpapers.model
        // first scan after start: the list fills while the picker is already open
        function onCountChanged() {
            if (root.open && Wallpapers.indexOf(Wallpapers.current) === Wallpapers.model.count - 1) root.syncFocus();
        }
    }

    readonly property var targetScreen: Quickshell.screens.find(s => s.name === ShellState.activeScreen) ?? null
    readonly property bool mapped: root.open || root.shown > 0.001

    // The window only exists while open or animating out: closed costs nothing.
    LazyLoader {
        active: root.mapped && !!root.targetScreen

    PanelWindow {
        id: win
        screen: root.targetScreen
        color: "transparent"
        anchors { top: true; bottom: true; left: true; right: true }
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.namespace: "arthur-picker"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: root.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        BackgroundEffect.blurRegion: Region { item: content.item ? content.item.glassBody : null; radius: Theme.radiusLg }

        Loader {
            id: content
            anchors.fill: parent
            focus: true
            sourceComponent: FocusScope {
                id: scope
                focus: true
                readonly property Item glassBody: glass.body

                Keys.onPressed: event => {
                    if (event.key === Qt.Key_Left || event.key === Qt.Key_H) { root.step(-1); event.accepted = true; }
                    else if (event.key === Qt.Key_Right || event.key === Qt.Key_L) { root.step(1); event.accepted = true; }
                    else if (event.key === Qt.Key_Home) { root.focusIndex = 0; event.accepted = true; }
                    else if (event.key === Qt.Key_End) { root.focusIndex = Wallpapers.model.count - 1; event.accepted = true; }
                    else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { root.applyFocused(); event.accepted = true; }
                    else if (event.key === Qt.Key_Escape) { ShellState.close("picker"); event.accepted = true; }
                }

                // soft scrim; a click anywhere outside the card closes
                Rectangle {
                    anchors.fill: parent
                    color: Theme.withAlpha(Theme.bgSunken, 0.28 * root.shown)
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: ShellState.close("picker")
                }

                Glass {
                    id: glass
                    tone: "panel"
                    readonly property int inner: Math.min(1088, scope.width - 2 * (Theme.gap + Theme.shadowPad) - 2 * 16)
                    readonly property int previewH: Math.min(Math.round(inner * 9 / 16), Math.round(scope.height * 0.56))
                    width: inner + 2 * 16
                    height: col.implicitHeight + 2 * 16
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: Math.round((scope.height - height) / 2 + (1 - root.shown) * 28)
                    opacity: root.shown

                    MouseArea { anchors.fill: parent }   // swallow clicks on the card itself

                    Column {
                        id: col
                        x: 16; y: 16
                        width: glass.inner
                        spacing: 12

                        WallPreview {
                            width: parent.width
                            height: glass.previewH
                            path: root.focusedRow ? root.focusedRow.path : ""
                            thumb: root.focusedRow ? root.focusedRow.thumb : ""
                            thumbReady: root.focusedRow ? root.focusedRow.ready : false

                            // "Preview" tag so it never reads as already applied
                            Rectangle {
                                anchors { left: parent.left; top: parent.top; margins: 12 }
                                width: tagRow.implicitWidth + 20; height: 28
                                radius: 14
                                color: Theme.withAlpha(Theme.surface, Theme.menuAlpha)
                                border.width: 1
                                border.color: Theme.edge
                                Row {
                                    id: tagRow
                                    anchors.centerIn: parent
                                    spacing: 6
                                    Icon { text: "\u{f0208}"; size: 14; color: Theme.text2; anchors.verticalCenter: parent.verticalCenter }
                                    Label { text: "Preview"; color: Theme.text2; font.pixelSize: Theme.fontSmall; anchors.verticalCenter: parent.verticalCenter }
                                }
                            }
                        }

                        // name + state + key hints
                        Item {
                            width: parent.width
                            height: 30
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 10
                                Label {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: root.focusedRow ? root.focusedRow.name : (Wallpapers.scanning ? "Loading…" : "No wallpapers")
                                    font.pixelSize: Theme.fontLarge
                                    font.weight: Font.DemiBold
                                }
                                Rectangle {
                                    visible: !!root.focusedRow && root.focusedRow.path === Wallpapers.current
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: nowLabel.implicitWidth + 18; height: 22; radius: 11
                                    color: Theme.accentSoft
                                    border.width: 1
                                    border.color: Theme.accent
                                    Label { id: nowLabel; anchors.centerIn: parent; text: "On screen"; font.pixelSize: Theme.fontSmall; color: Theme.accentBright }
                                }
                                Label {
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: Wallpapers.model.count > 0
                                    text: (root.focusIndex + 1) + " / " + Wallpapers.model.count
                                    font.family: Theme.fontMono
                                    font.pixelSize: Theme.fontSmall
                                    color: Theme.muted
                                }
                            }
                            Row {
                                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                                spacing: 16
                                Repeater {
                                    model: [["\u{f0141} \u{f0142}", "Browse"], ["\u{f0311}", "Apply"], ["Esc", "Close"]]
                                    delegate: Row {
                                        id: hint
                                        required property var modelData
                                        spacing: 6
                                        Rectangle {
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: Math.max(26, keyText.implicitWidth + 12); height: 22; radius: Theme.radiusSm
                                            color: Theme.cardFill
                                            border.width: 1
                                            border.color: Theme.edge
                                            Icon { id: keyText; anchors.centerIn: parent; text: hint.modelData[0]; size: 12; color: Theme.text2 }
                                        }
                                        Label { anchors.verticalCenter: parent.verticalCenter; text: hint.modelData[1]; font.pixelSize: Theme.fontSmall; color: Theme.text2 }
                                    }
                                }
                            }
                        }

                        ListView {
                            id: carousel
                            readonly property int cellW: 224
                            width: parent.width
                            height: 140
                            orientation: ListView.Horizontal
                            model: Wallpapers.model
                            currentIndex: root.focusIndex
                            interactive: false
                            clip: true
                            cacheBuffer: cellW * 6
                            highlightRangeMode: ListView.StrictlyEnforceRange
                            preferredHighlightBegin: (width - cellW) / 2
                            preferredHighlightEnd: (width + cellW) / 2
                            highlightMoveDuration: Motion.slow
                            highlightFollowsCurrentItem: true
                            delegate: WallThumb {
                                width: carousel.cellW
                                onActivated: {
                                    if (index === root.focusIndex) root.applyFocused();
                                    else root.focusIndex = index;
                                }
                            }
                            Component.onCompleted: positionViewAtIndex(root.focusIndex, ListView.Center)

                            // wheel: one card per notch (touchpads accumulate)
                            WheelHandler {
                                property real acc: 0
                                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                                onWheel: event => {
                                    const d = Math.abs(event.angleDelta.x) > Math.abs(event.angleDelta.y) ? event.angleDelta.x : event.angleDelta.y;
                                    acc += d;
                                    while (acc >= 120) { acc -= 120; root.step(-1); }
                                    while (acc <= -120) { acc += 120; root.step(1); }
                                }
                            }

                            Label {
                                anchors.centerIn: parent
                                visible: Wallpapers.model.count === 0 && !Wallpapers.scanning
                                text: "No images in " + Config.wallpaper.dir
                                color: Theme.muted
                            }
                        }
                    }
                }
            }
            onLoaded: item.forceActiveFocus()
        }
    }
    }

    // Dev-only test hooks (no synthetic input allowed on this box): active only while
    // settings.json dev.screens is set, gone after cutover.
    IpcHandler {
        target: "wallpaperdev"
        enabled: Config.dev.screens.length > 0
        function scan(): void { Wallpapers.refresh(); }
        function next(): void { root.step(1); }
        function prev(): void { root.step(-1); }
        function select(name: string): void {
            for (let i = 0; i < Wallpapers.model.count; i++)
                if (Wallpapers.model.get(i).path.endsWith("/" + name)) { root.focusIndex = i; return; }
        }
        function apply(): void { root.applyFocused(); }
        function dryRun(mode: string): void { Wallpapers.dryRun = mode; }
        function state(): string {
            return JSON.stringify({ open: root.open, focus: root.focusIndex, focused: root.focusedRow ? root.focusedRow.path : "",
                                    current: Wallpapers.current, count: Wallpapers.model.count, scanning: Wallpapers.scanning,
                                    generated: Wallpapers.lastGenerated, scanMs: Wallpapers.lastScanMs, dryRun: Wallpapers.dryRun,
                                    applying: Wallpapers.applying, applyLog: Wallpapers.lastApplyLog });
        }
    }
}
