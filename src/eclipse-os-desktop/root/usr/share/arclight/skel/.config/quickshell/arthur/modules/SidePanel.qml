pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Bluetooth
import Quickshell.Services.UPower
import qs.common
import qs.components
import qs.services
import qs.modules.panel

// Side panel / control centre (owner: agent C). Slides in from the right on the active screen,
// full height below the bar. Escape or a click outside closes it (HyprlandFocusGrab); it holds
// keyboard focus only while open. Sections: header, quick toggles, volume, media, shortcuts,
// calendar, notification history.
Scope {
    id: root

    readonly property bool open: ShellState.panelOpen
    property string expanded: ""          // "" | "wifi" | "bt": the list under the toggles
    readonly property var screenObj: Quickshell.screens.find(s => s.name === ShellState.activeScreen) ?? null

    property string uptime: ""
    Process {
        id: uptimeProc
        command: ["cat", "/proc/uptime"]
        stdout: StdioCollector {
            onStreamFinished: {
                const s = Math.floor(parseFloat(text.split(" ")[0]) || 0);
                const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
                root.uptime = "up " + (d > 0 ? d + " d " : "") + (d > 0 || h > 0 ? h + " h " : "") + m + " min";
            }
        }
    }
    Timer {
        interval: 60000
        repeat: true
        running: root.open && !GameMode.quiet
        onTriggered: uptimeProc.running = true
    }
    onOpenChanged: {
        if (open) { uptimeProc.running = true; clock.now = new Date(); }
        else expanded = "";
    }

    SystemClock {
        id: sysClock
        enabled: root.open
        precision: SystemClock.Minutes
    }
    QtObject {
        id: clock
        property date now: new Date()
    }
    Connections {
        target: sysClock
        function onDateChanged() { clock.now = sysClock.date; }
    }

    function runDetached(cmd) {
        ShellState.close("panel");
        Quickshell.execDetached(["sh", "-c", cmd]);
    }

    readonly property var profileNames: ["Power saver", "Balanced", "Performance"]
    function cycleProfile() {
        const order = [PowerProfile.PowerSaver, PowerProfile.Balanced].concat(PowerProfiles.hasPerformanceProfile ? [PowerProfile.Performance] : []);
        const i = order.indexOf(PowerProfiles.profile);
        PowerProfiles.profile = order[(i + 1) % order.length];
    }

    // ---- the panel ----
    PanelWindow {
        id: win

        property real shown: root.open ? 1 : 0
        Behavior on shown { Anim { duration: Motion.slow; easing.bezierCurve: root.open ? Motion.emphasized : Motion.exit } }

        screen: root.screenObj
        visible: !!root.screenObj && (root.open || shown > 0.001)

        WlrLayershell.namespace: "arthur-panel"
        WlrLayershell.layer: WlrLayer.Top
        WlrLayershell.keyboardFocus: root.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Normal
        exclusiveZone: 0
        anchors { top: true; bottom: true; right: true }
        implicitWidth: Config.panel.width + Theme.gap + Theme.shadowPad
        color: "transparent"

        mask: Region { item: glass }
        BackgroundEffect.blurRegion: Region { item: glass; radius: glass.radius }

        HyprlandFocusGrab {
            windows: [win]
            active: root.open && win.visible
            onCleared: ShellState.close("panel")
        }

        Glass {
            id: glass
            tone: "panel"
            y: Theme.gap
            width: Config.panel.width
            height: win.height - 2 * Theme.gap
            x: Theme.shadowPad + (1 - win.shown) * (Config.panel.width + Theme.gap)
            opacity: Math.min(1, win.shown * 1.6)

            Item {
                id: keys
                anchors.fill: parent
                focus: true
                Keys.onEscapePressed: ShellState.close("panel")
            }
            Connections {
                target: root
                function onOpenChanged() { if (root.open) keys.forceActiveFocus(); }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 14

                // header: user + uptime, power
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Rectangle {
                        Layout.preferredWidth: 42
                        Layout.preferredHeight: 42
                        radius: 21
                        color: Theme.accentSoft
                        border.width: 1
                        border.color: Theme.withAlpha(Theme.accent, 0.55)
                        Label {
                            anchors.centerIn: parent
                            text: (Quickshell.env("USER") || "?").charAt(0).toUpperCase()
                            font.pixelSize: Theme.fontLarge + 2
                            font.weight: Font.Bold
                            color: Theme.accentBright
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Label {
                            Layout.fillWidth: true
                            text: { const u = Quickshell.env("USER") || "user"; return u.charAt(0).toUpperCase() + u.slice(1); }
                            font.pixelSize: Theme.fontLarge
                            font.weight: Font.DemiBold
                        }
                        Label {
                            Layout.fillWidth: true
                            text: root.uptime
                            color: Theme.text2
                            font.pixelSize: Theme.fontSmall + 1
                        }
                    }
                    PanelButton {
                        icon: "\u{f0425}"
                        iconSize: 20
                        onClicked: ShellState.open("power")
                    }
                }

                // quick toggles
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    rowSpacing: 8
                    columnSpacing: 8

                    PanelToggle {
                        Layout.fillWidth: true
                        icon: Network.wifiEnabled ? "\u{f05a9}" : "\u{f05aa}"
                        name: "Wi-Fi"
                        on: Network.wifiEnabled
                        status: !Network.wifiEnabled ? "Off" : Network.wifiUp ? Network.wifiNetwork.name : "Not connected"
                        onClicked: Network.setWifiEnabled(!Network.wifiEnabled)
                        expandable: true
                        expanded: root.expanded === "wifi"
                        onExpandClicked: root.expanded = root.expanded === "wifi" ? "" : "wifi"
                    }
                    PanelToggle {
                        readonly property var adapter: Bluetooth.defaultAdapter
                        Layout.fillWidth: true
                        available: !!adapter
                        icon: adapter && adapter.enabled ? "\u{f00af}" : "\u{f00b2}"
                        name: "Bluetooth"
                        on: !!adapter && adapter.enabled
                        readonly property int connectedCount: adapter ? adapter.devices.values.filter(d => d.connected).length : 0
                        status: !adapter ? "No adapter" : !adapter.enabled ? "Off" : connectedCount > 0 ? connectedCount + " connected" : "On"
                        onClicked: if (adapter) adapter.enabled = !adapter.enabled
                        expandable: true
                        expanded: root.expanded === "bt"
                        onExpandClicked: root.expanded = root.expanded === "bt" ? "" : "bt"
                    }
                    PanelToggle {
                        Layout.fillWidth: true
                        icon: Notifs.dnd ? "\u{f009b}" : "\u{f009a}"
                        name: "Do not disturb"
                        on: Notifs.dnd
                        status: Notifs.dnd ? "On" : "Off"
                        onClicked: Notifs.setDnd(!Notifs.dnd)
                    }
                    PanelToggle {
                        Layout.fillWidth: true
                        icon: PanelAwake.on ? "\u{f0176}" : "\u{f0faa}"
                        name: "Keep awake"
                        on: PanelAwake.on
                        status: PanelAwake.on ? "Screen stays on" : "Off"
                        onClicked: PanelAwake.toggle()
                    }
                    PanelToggle {
                        Layout.fillWidth: true
                        icon: PowerProfiles.profile === PowerProfile.PowerSaver ? "\u{f032a}"
                            : PowerProfiles.profile === PowerProfile.Performance ? "\u{f14de}" : "\u{f05d1}"
                        name: "Power"
                        on: PowerProfiles.profile !== PowerProfile.Balanced
                        status: root.profileNames[PowerProfiles.profile] ?? "Balanced"
                        onClicked: root.cycleProfile()
                    }
                    PanelToggle {
                        Layout.fillWidth: true
                        available: Audio.micAvailable
                        icon: Audio.micMuted ? "\u{f036d}" : "\u{f036c}"
                        name: "Microphone"
                        on: Audio.micAvailable && !Audio.micMuted
                        status: !Audio.micAvailable ? "None" : Audio.micMuted ? "Muted" : "On"
                        onClicked: Audio.toggleMicMute()
                    }
                }

                // Wi-Fi / Bluetooth list, opened from a tile's chevron
                Rectangle {
                    id: listBox
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.expanded === "" ? 0 : Math.min(260, flick.contentHeight + 16)
                    Behavior on Layout.preferredHeight { Anim { duration: Motion.normal } }
                    visible: Layout.preferredHeight > 0.5
                    radius: Theme.radiusMd
                    color: Theme.cardFill
                    border.width: 1
                    border.color: Theme.edge
                    clip: true
                    Flickable {
                        id: flick
                        x: 8; y: 8
                        width: parent.width - 16
                        height: parent.height - 16
                        contentHeight: listLoader.item ? listLoader.item.implicitHeight : 0
                        boundsBehavior: Flickable.StopAtBounds
                        Loader {
                            id: listLoader
                            width: flick.width
                            active: root.expanded !== ""
                            sourceComponent: root.expanded === "bt" ? btComp : wifiComp
                        }
                    }
                    Component { id: wifiComp; WifiList {} }
                    Component {
                        id: btComp
                        BtList { onPairRequested: root.runDetached("ghostty -e bluetoothctl") }
                    }
                }

                VolumeSlider { Layout.fillWidth: true }

                MediaCard { Layout.fillWidth: true }

                // shortcuts
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: [
                            { icon: "\u{f02f9}", label: "Walls",    act: "picker" },
                            { icon: "\u{f0493}", label: "Settings", act: "settings" },
                            { icon: "\u{f0e51}", label: "Capture",  act: "shot" },
                            { icon: "\u{f020a}", label: "Colour",   act: "color" },
                            { icon: "\u{f0425}", label: "Power",    act: "power" }
                        ]
                        delegate: Rectangle {
                            id: sc
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 60
                            radius: Theme.radiusMd
                            color: scHover.hovered ? Theme.hoverFill : Theme.cardFill
                            border.width: 1
                            border.color: Theme.edge
                            Behavior on color { CAnim {} }
                            Column {
                                anchors.centerIn: parent
                                spacing: 4
                                Icon { anchors.horizontalCenter: parent.horizontalCenter; text: sc.modelData.icon; size: 20; color: Theme.accentBright }
                                Label { anchors.horizontalCenter: parent.horizontalCenter; text: sc.modelData.label; font.pixelSize: Theme.fontSmall + 1 }
                            }
                            HoverHandler { id: scHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler {
                                onTapped: {
                                    const a = sc.modelData.act;
                                    if (a === "picker") ShellState.open("picker");
                                    else if (a === "settings") { ShellState.close("panel"); ShellState.settingsOpen = true; }
                                    else if (a === "shot") root.runDetached("sleep 0.35; ~/.local/bin/shot menu");
                                    else if (a === "color") root.runDetached("sleep 0.35; ~/.local/bin/colorpick");
                                    else if (a === "power") ShellState.open("power");
                                }
                            }
                        }
                    }
                }

                Calendar {
                    Layout.fillWidth: true
                    today: clock.now
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: Theme.hairline
                }

                NotifHistory {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 120
                    now: clock.now
                }
            }
        }
    }

    // qs -c arthur ipc call sidepanel expand wifi|bt|none   (opens the list under a tile)
    IpcHandler {
        target: "sidepanel"
        function expand(which: string): void { root.expanded = (which === "wifi" || which === "bt") ? which : ""; }
    }
}
