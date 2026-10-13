import QtQuick
import Quickshell
import Quickshell.Io
import qs.services

// Every action a keybind needs, as IPC. CLI:  qs -c arthur ipc call <target> <function> [args]
// Keybinds go through ~/.local/bin/shellctl, which routes to whichever shell is running.
Scope {
    IpcHandler {
        target: "launcher"
        function toggle(): void { ShellState.launcherQuery = ""; ShellState.toggle("launcher"); }
        function open(): void { ShellState.launcherQuery = ""; ShellState.open("launcher"); }
        function openQuery(query: string): void { ShellState.launcherQuery = query; ShellState.open("launcher"); }
        function close(): void { ShellState.close("launcher"); }
    }
    IpcHandler {
        target: "panel"
        function toggle(): void { ShellState.toggle("panel"); }
        function open(): void { ShellState.open("panel"); }
        function close(): void { ShellState.close("panel"); }
    }
    IpcHandler {
        target: "wallpaper"
        function toggle(): void { ShellState.toggle("picker"); }
        function open(): void { ShellState.open("picker"); }
        function close(): void { ShellState.close("picker"); }
    }
    IpcHandler {
        target: "settings"
        function toggle(): void { ShellState.settingsOpen = !ShellState.settingsOpen; }
        function open(): void { ShellState.settingsOpen = true; }
        function close(): void { ShellState.settingsOpen = false; }
    }
    IpcHandler {
        target: "power"
        function toggle(): void { ShellState.toggle("power"); }
        function open(): void { ShellState.open("power"); }
        function close(): void { ShellState.close("power"); }
    }
    IpcHandler {
        target: "overview"
        function toggle(): void { ShellState.toggle("overview"); }
        function open(): void { ShellState.open("overview"); }
        function close(): void { ShellState.close("overview"); }
    }
    IpcHandler {
        target: "clipboard"
        function toggle(): void { ShellState.toggle("clipboard"); }
        function open(): void { ShellState.open("clipboard"); }
        function close(): void { ShellState.close("clipboard"); }
    }
    IpcHandler {
        target: "shell"
        function ping(): string { return "arthur-shell ok"; }
        function state(): string {
            return JSON.stringify({ launcher: ShellState.launcherOpen, panel: ShellState.panelOpen, picker: ShellState.pickerOpen,
                                    settings: ShellState.settingsOpen, power: ShellState.powerOpen, overview: ShellState.overviewOpen,
                                    clipboard: ShellState.clipboardOpen, screen: ShellState.activeScreen });
        }
        function closeAll(): void { ShellState.closeAll(""); ShellState.settingsOpen = false; }
    }
}
