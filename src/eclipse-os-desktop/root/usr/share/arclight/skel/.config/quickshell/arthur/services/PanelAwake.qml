pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.common

// "Keep awake" (owner: agent C): the side-panel toggle and the OSD both read it.
// A Wayland idle inhibitor needs a mapped surface, so while it is on a 1 px, click-through,
// fully transparent keeper surface sits on the background layer. The state survives hot
// reloads (PersistentProperties) but not a shell restart.
Singleton {
    id: root

    readonly property bool on: persist.keepAwake
    function toggle() { persist.keepAwake = !persist.keepAwake; }
    function set(v) { persist.keepAwake = v; }

    PersistentProperties {
        id: persist
        reloadableId: "arthurPanelAwake"
        property bool keepAwake: false
    }

    readonly property var _screen: Quickshell.screens.find(s => s.name === ShellState.activeScreen) ?? Quickshell.screens[0] ?? null

    PanelWindow {
        id: keeper
        screen: root._screen
        visible: persist.keepAwake && !!root._screen
        WlrLayershell.namespace: "arthur-panel"
        WlrLayershell.layer: WlrLayer.Background
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; left: true }
        implicitWidth: 1
        implicitHeight: 1
        color: "transparent"
        mask: Region {}
    }
    IdleInhibitor {
        window: keeper
        enabled: persist.keepAwake
    }
}
