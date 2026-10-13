pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Hyprland
import qs.common

// Which transient surface is open, and on which screen. IPC (shell.qml -> Ipc.qml),
// keybinds, bar and dock buttons all go through these functions; modules only READ
// the state. Opening one input surface closes the others, so at most one surface
// ever holds keyboard focus.
Singleton {
    id: root

    property bool launcherOpen: false
    property bool panelOpen: false
    property bool pickerOpen: false        // wallpaper switcher
    property bool settingsOpen: false      // settings app window
    property bool powerOpen: false
    property bool overviewOpen: false
    property bool clipboardOpen: false
    property string launcherQuery: ""      // pre-filled query for launcher.openQuery
    // Unread notification count. Written ONLY by the notification service (services/Notifs.qml):
    // +1 per new notification not yet seen, reset to 0 when the side panel opens. Read by the bar bell.
    property int notifUnread: 0

    // The screen transient surfaces open on: the monitor with keyboard focus.
    // While developing next to DMS (settings.json dev.screens set) it is pinned to the
    // first dev screen, so tests never pop up on the screen the user is working on.
    readonly property string activeScreen: (Config.dev.screens && Config.dev.screens.length > 0) ? Config.dev.screens[0]
        : (Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : "")

    function closeAll(except) {
        if (except !== "launcher") launcherOpen = false;
        if (except !== "panel") panelOpen = false;
        if (except !== "picker") pickerOpen = false;
        if (except !== "power") powerOpen = false;
        if (except !== "overview") overviewOpen = false;
        if (except !== "clipboard") clipboardOpen = false;
    }
    function toggle(name) {
        const key = name + "Open";
        const next = !root[key];
        closeAll(name);
        root[key] = next;
        return next;
    }
    function open(name) { closeAll(name); root[name + "Open"] = true; }
    function close(name) { root[name + "Open"] = false; }
}
