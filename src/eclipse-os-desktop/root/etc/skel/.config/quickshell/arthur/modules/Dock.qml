pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.common
import qs.components
import qs.services
import qs.modules.dock

// Bottom dock, one per screen (arthur-dock, layer Top, floats over windows: exclusiveZone 0).
//   [launcher] | pinned apps | running apps not pinned | [side panel]
// Auto-hide: hidden until the pointer touches a 3 px strip at the bottom edge (under the dock),
// rises with Motion.slow/emphasized, falls with Motion.exit. Stays up while a menu is open or the
// monitor's workspace is empty. Unmapped while a fullscreen window is on that screen.
// Input mask: when hidden only the trigger strip takes input, so windows never lose clicks.
Scope {
    id: root

    // IPC test override: "" = automatic, "show" = force up, "hide" = force down.
    property string forced: ""
    // One menu at a time across all docks.
    property string menuScreen: ""
    property string menuAppId: ""
    property real menuX: 0
    property bool menuGrab: true      // false only for the IPC preview (no focus grab while testing)

    function closeMenu() { root.menuScreen = ""; root.menuGrab = true; }

    IpcHandler {
        target: "dock"
        function reveal(): void { root.forced = "show"; }
        function hide(): void { root.forced = "hide"; root.closeMenu(); }
        function auto(): void { root.forced = ""; }
        function pin(id: string): void { Apps.pin(id); }
        function unpin(id: string): void { Apps.unpin(id); }
        function menu(id: string): void {
            // test hook: show the context menu for `id` on the active screen, centred, WITHOUT the
            // focus grab (so it can never catch the user's clicks); close it with closeMenu()
            root.menuAppId = id; root.menuX = -1; root.menuGrab = false; root.menuScreen = ShellState.activeScreen;
        }
        function closeMenu(): void { root.closeMenu(); }
        function state(): string {
            return JSON.stringify({ forced: root.forced, menu: root.menuScreen ? root.menuAppId : "",
                                    pinned: Apps.pinnedIds(), running: Apps.running.map(g => g.key + "x" + g.windows.length),
                                    docks: docks.instances.map(d => ({ screen: d.modelData.name, shown: d.shown, mapped: d.visible,
                                                                       emptyWorkspace: d.emptyWorkspace, hoverUp: d.hoverUp })),
                                    fullscreen: Quickshell.screens.map(s => s.name + ":" + GameMode.fullscreenOn(s.name)) });
        }
    }

    Variants {
        id: docks
        model: Quickshell.screens.filter(s => Config.wantsScreen(s))

        delegate: PanelWindow {
            id: dock
            required property var modelData
            screen: modelData

            readonly property int itemH: Config.dock.iconSize + 16
            readonly property int glassH: itemH + 8
            readonly property int topRoom: 48                  // tooltip + shadow headroom above the glass
            readonly property int strip: 3                     // trigger strip height
            readonly property bool fullscreenHere: GameMode.fullscreenOn(modelData.name)
            readonly property var hyprMon: Hyprland.monitorFor(modelData)
            readonly property bool emptyWorkspace: !!hyprMon && !!hyprMon.activeWorkspace
                                                   && hyprMon.activeWorkspace.toplevels.values.length === 0
            readonly property bool menuHere: root.menuScreen === modelData.name
            property bool hoverUp: false

            readonly property bool shown: root.forced === "show" ? true
                                        : root.forced === "hide" ? false
                                        : (!Config.dock.autoHide || hoverUp || menuHere || emptyWorkspace)

            WlrLayershell.namespace: "arthur-dock"
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            exclusiveZone: 0
            color: "transparent"
            anchors { bottom: true; left: true; right: true }
            implicitHeight: topRoom + glassH + Theme.gap
            visible: !fullscreenHere

            // blur follows the moving glass (explicit numbers so it tracks the rise/fall)
            BackgroundEffect.blurRegion: Region {
                x: glass.x; y: Math.round(glass.y); width: glass.width
                height: Math.max(0, Math.min(glass.height, dock.height - Math.round(glass.y)))
                radius: glass.radius
            }
            // input: glass + gap below it when shown; only the strip under the dock when hidden
            mask: Region {
                x: glass.x - (dock.shown ? 0 : 24)
                y: dock.shown ? dock.topRoom : dock.height - dock.strip
                width: glass.width + (dock.shown ? 0 : 48)
                height: dock.shown ? dock.height - dock.topRoom : dock.strip
            }

            Timer {
                id: revealTimer
                interval: Config.dock.revealDelayMs
                onTriggered: dock.hoverUp = true
            }
            Timer {
                id: hideTimer
                interval: Config.dock.hideDelayMs
                onTriggered: if (!dock.menuHere) dock.hoverUp = false
            }

            onMenuHereChanged: if (!menuHere && !hover.hovered && hoverUp) hideTimer.restart()
            onVisibleChanged: if (!visible) { revealTimer.stop(); hideTimer.stop(); hoverUp = false; }

            // hover zone = the whole surface; the input mask limits where the pointer can reach it
            Item {
                id: zone
                anchors.fill: parent

                HoverHandler {
                    id: hover
                    onHoveredChanged: {
                        if (hovered) { hideTimer.stop(); if (!dock.hoverUp) revealTimer.restart(); }
                        else { revealTimer.stop(); if (dock.hoverUp) hideTimer.restart(); }
                    }
                }

                Glass {
                    id: glass
                    tone: "panel"
                    width: row.implicitWidth + 16
                    height: dock.glassH
                    x: Math.round((dock.width - width) / 2)
                    y: dock.topRoom
                    opacity: 1

                    Behavior on width { Anim { duration: Motion.normal } }

                    states: State {
                        name: "hidden"
                        when: !dock.shown
                        PropertyChanges { glass.y: dock.height + Theme.shadowPad; glass.opacity: 0 }
                    }
                    transitions: [
                        Transition {
                            to: "hidden"
                            Anim { properties: "y"; duration: Motion.normal; easing.bezierCurve: Motion.exit }
                            Anim { properties: "opacity"; duration: Motion.normal; easing.bezierCurve: Motion.exit }
                        },
                        Transition {
                            to: ""
                            Anim { properties: "y"; duration: Motion.slow; easing.bezierCurve: Motion.emphasized }
                            Anim { properties: "opacity"; duration: Motion.fast; easing.bezierCurve: Motion.liquid }
                        }
                    ]

                    Row {
                        id: row
                        x: 8
                        y: 4
                        spacing: 0

                        DockButton {
                            glyph: "\u{f003b}"
                            label: "Apps"
                            checked: ShellState.launcherOpen
                            onClicked: ShellState.toggle("launcher")
                        }
                        Divider {}

                        Repeater {
                            model: ScriptModel { values: Apps.pinnedIds() }
                            DockItem {
                                required property string modelData
                                appId: modelData
                                pinned: true
                                onMenuRequested: item => dock.openMenu(item, modelData)
                            }
                        }

                        Divider { visible: extras.count > 0 }
                        Repeater {
                            id: extras
                            model: ScriptModel {
                                values: {
                                    const pinnedKeys = Apps.pinnedIds().map(p => Apps.keyFor(p));
                                    return Apps.running.filter(g => pinnedKeys.indexOf(g.key) < 0).map(g => g.appId);
                                }
                            }
                            DockItem {
                                required property string modelData
                                appId: modelData
                                onMenuRequested: item => dock.openMenu(item, modelData)
                            }
                        }

                        Divider {}
                        DockButton {
                            glyph: "\u{f062e}"
                            label: "Panel"
                            checked: ShellState.panelOpen
                            onClicked: ShellState.toggle("panel")
                        }
                    }
                }
            }

            function openMenu(item, appId) {
                const p = item.mapToItem(dock.contentItem, item.width / 2, 0);
                root.menuAppId = appId;
                root.menuX = p.x;
                root.menuGrab = true;
                root.menuScreen = dock.modelData.name;
            }

            DockMenu {
                screen: dock.modelData
                open: dock.menuHere && dock.visible
                appId: root.menuAppId
                centerX: root.menuX < 0 ? dock.width / 2 : root.menuX
                bottomOffset: Theme.gap + dock.glassH
                grab: root.menuGrab
                grabWindows: [dock]
                onCloseRequested: root.closeMenu()
            }
        }
    }

    component Divider: Item {
        implicitWidth: 13
        implicitHeight: Config.dock.iconSize + 16
        Rectangle {
            anchors.centerIn: parent
            width: 1
            height: Config.dock.iconSize * 0.6
            color: Theme.hairline
        }
    }
}
