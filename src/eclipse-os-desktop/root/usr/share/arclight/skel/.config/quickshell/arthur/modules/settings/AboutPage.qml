import QtQuick
import Quickshell
import qs.common
import qs.components
import qs.services

// Versions, hardware, which shell runs, where the settings live.
SPage {
    id: page
    title: "About"
    subtitle: "arthur-shell on " + (HyprSettings.sysinfo.kernel ? "Linux " + HyprSettings.sysinfo.kernel : "Arch Linux")
    readonly property var s: HyprSettings.sysinfo

    function uptime(sec) {
        sec = parseInt(sec);
        if (isNaN(sec)) return "…";
        const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
        return (d > 0 ? d + " d " : "") + h + " h " + m + " min";
    }

    component InfoRow: Item {
        property string label
        property string value
        width: parent ? parent.width : 400
        height: 30
        Label { id: l; text: parent.label; width: 170; color: Theme.text2; anchors.verticalCenter: parent.verticalCenter }
        Label { anchors { left: l.right; leftMargin: 8; right: parent.right; verticalCenter: parent.verticalCenter }
                text: parent.value || "…"; font.family: Theme.fontMono; font.pixelSize: Theme.fontSize }
    }

    SCard {
        title: "Shell"
        icon: String.fromCodePoint(0xF08C7)
        InfoRow { label: "Version"; value: page.s.commit ? "arthur-shell " + page.s.commit : "arthur-shell (not committed)" }
        InfoRow { label: "Running"; value: "arthur-shell" + (page.s.dms === "running" ? "  +  DankMaterialShell (dev mode)" : "") }
        InfoRow { label: "Quickshell"; value: page.s.quickshell || "" }
        InfoRow { label: "Hyprland"; value: page.s.hyprland || "" }
        InfoRow { label: "Settings file"; value: Quickshell.shellPath("settings.json") }
        InfoRow { label: "Compositor file"; value: "~/.config/hypr/arthur-generated.lua" }
    }
    SCard {
        title: "System"
        icon: String.fromCodePoint(0xF0EE0)
        InfoRow { label: "Uptime"; value: page.uptime(page.s.uptime) }
        InfoRow { label: "CPU"; value: page.s.cpu ? page.s.cpu + "  (" + page.s.cores + " threads)" : "" }
        InfoRow { label: "GPU"; value: page.s.gpu || "" }
        InfoRow { label: "Memory"; value: page.s.ram ? page.s.ram + " GiB used" : "" }
    }
}
