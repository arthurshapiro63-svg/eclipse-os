pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Services.SystemTray
import qs.common
import qs.components
import qs.services
import qs.modules.bar

// arthur-bar: floating glass top bar on every shell screen (agent A).
//   left   workspaces of THIS monitor + focused window title
//   centre clock/date (opens side panel) + weather
//   right  privacy (mic/camera/screen), media, tray, CPU/RAM, network, volume, notifications, clipboard, side panel
// Hides (unmaps, so its exclusive zone goes too) while a fullscreen window is on its screen.
Scope {
    id: scope

    // Workspace ranges pinned to each monitor, read once from the compositor's workspace
    // rules. Fallback = this box's layout (hyprland.lua): DP-1 1-4, HDMI-A-1 5-10.
    property var pinnedByMonitor: ({ "DP-1": [1, 2, 3, 4], "HDMI-A-1": [5, 6, 7, 8, 9, 10] })
    Process {
        running: true
        command: ["hyprctl", "workspacerules", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const map = {};
                    for (const r of JSON.parse(text)) {
                        const id = parseInt(r.workspaceString);
                        if (!r.monitor || !(id > 0) || String(id) !== String(r.workspaceString).trim()) continue;
                        (map[r.monitor] = map[r.monitor] || []).push(id);
                    }
                    if (Object.keys(map).length > 0) scope.pinnedByMonitor = map;
                } catch (e) { /* keep fallback */ }
            }
        }
    }

    // Dev checks without clicking (qs -c arthur ipc call bar <fn>): state, tip, tray.
    IpcHandler {
        target: "bar"
        function state(): string {
            return JSON.stringify(variants.instances.map(w => w.report()));
        }
        function tip(on: bool): void { for (const w of variants.instances) w.clockChip.forceTip = on; }
        function tray(index: int): void { for (const w of variants.instances) w.openTray(index); }
        // pretend a fullscreen window is on every bar's screen (tests hide + zone release without a real one)
        function simulateFullscreen(on: bool): void { scope.simFullscreen = on; }
        function closeMenus(): void { for (const w of variants.instances) w.trayMenu.close(); }
    }

    property bool simFullscreen: false

    // Stats and weather run only while at least one bar is mapped.
    property int shownBars: 0
    Binding { target: SysStats; property: "wanted"; value: scope.shownBars > 0 }
    Binding { target: Weather; property: "wanted"; value: scope.shownBars > 0 }

    Variants {
        id: variants
        model: Quickshell.screens.filter(s => Config.wantsScreen(s))
        delegate: PanelWindow {
            id: win
            required property var modelData
            readonly property string screenName: modelData.name
            readonly property bool hidden: GameMode.fullscreenOn(screenName) || scope.simFullscreen

            screen: modelData
            visible: !hidden
            onVisibleChanged: scope.shownBars += visible ? 1 : -1
            Component.onCompleted: if (visible) scope.shownBars += 1
            Component.onDestruction: if (visible) scope.shownBars -= 1

            WlrLayershell.namespace: "arthur-bar"
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            anchors { top: true; left: true; right: true }
            implicitHeight: Theme.gap + Config.bar.height + Theme.shadowPad
            exclusiveZone: Theme.gap + Config.bar.height
            color: "transparent"
            // input only on the glass itself: the shadow margin stays click-through
            mask: Region { item: glass }
            BackgroundEffect.blurRegion: Region { item: glass.body; radius: glass.radius }

            readonly property alias trayMenu: trayMenu
            readonly property alias clockChip: clockChip
            function openTray(i) {
                const b = tray.buttonAt(i);
                if (b && SystemTray.items.values[i]) trayMenu.openFor(SystemTray.items.values[i], b);
            }
            function report() {
                return { screen: screenName, mapped: visible, fullscreenHere: GameMode.fullscreenOn(screenName), fullscreenOnDP1: GameMode.fullscreenOn("DP-1"), workspaces: ws.ids, active: ws.activeId,
                         occupied: ws.ids.filter(id => { const w = ws.wsById(id); return !!w && w.toplevels.values.length > 0; }),
                         title: title.title, clock: clockChip.tip, weather: Weather.ready ? Weather.tempText + " " + Weather.description : "none",
                         cpu: SysStats.cpuReady ? Math.round(SysStats.cpu) : null, ramGiB: SysStats.memReady ? +SysStats.memUsedGiB.toFixed(1) : null,
                         statsRunning: SysStats.running, weatherRunning: Weather.running,
                         media: Media.active ? Media.title : null, volume: Audio.available ? Math.round(Audio.volume * 100) : null,
                         net: Network.label, tray: SystemTray.items.values.map(t => t.id), menuOpen: trayMenu.open, privacy: { mic: privacy.micOn, micApps: privacy.micApps, video: privacy.videoOn, screen: privacy.screencast, videoApps: privacy.videoApps }, menu: trayMenu.entryTexts };
            }

            TrayMenu { id: trayMenu; screen: win.modelData; barWindow: win }

            Glass {
                id: glass
                tone: "bar"
                x: Theme.gap; y: Theme.gap
                width: win.width - 2 * Theme.gap
                height: Config.bar.height

                // ---- left ----
                Row {
                    id: left
                    anchors.left: parent.left; anchors.leftMargin: 6
                    anchors.verticalCenter: parent.verticalCenter
                    height: parent.height - 8
                    spacing: 10

                    Workspaces {
                        id: ws
                        screenName: win.screenName
                        pinned: scope.pinnedByMonitor[win.screenName] || []
                    }
                    WindowTitle {
                        id: title
                        screenName: win.screenName
                        maxWidth: Math.max(0, centre.x - left.x - 16 - x)
                    }
                }

                // ---- centre ----
                Row {
                    id: centre
                    anchors.centerIn: parent
                    height: parent.height - 8
                    spacing: 2
                    Clock { id: clockChip; running: win.visible }
                    WeatherChip {}
                }

                // ---- right ----
                Row {
                    id: right
                    anchors.right: parent.right; anchors.rightMargin: 6
                    anchors.verticalCenter: parent.verticalCenter
                    height: parent.height - 8
                    spacing: 2

                    Privacy { id: privacy; height: parent.height }
                    MediaChip { id: media }
                    Tray { id: tray; menu: trayMenu; height: parent.height }
                    Divider { visible: privacy.visible || media.visible || tray.visible }
                    Stats {}
                    NetChip {}
                    VolumeChip {}
                    Divider {}
                    NotifButton {}
                    BarButton {
                        tip: "Clipboard"
                        active: ShellState.clipboardOpen
                        onClicked: ShellState.toggle("clipboard")
                        Icon { anchors.verticalCenter: parent.verticalCenter; text: "\u{f014c}"; size: Theme.fontLarge }   // md-clipboard-text-outline
                    }
                    BarButton {
                        tip: "Side panel"
                        active: ShellState.panelOpen
                        onClicked: ShellState.toggle("panel")
                        Icon { anchors.verticalCenter: parent.verticalCenter; text: "\u{f035c}"; size: Theme.fontLarge }   // md-menu
                    }
                }
            }
        }
    }

    component Divider: Item {
        width: 9
        height: parent ? parent.height : 0
        Rectangle {
            anchors.centerIn: parent
            width: 1; height: parent.height - 10
            color: Theme.hairline
        }
    }
}
