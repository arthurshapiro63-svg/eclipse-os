import QtQuick
import Quickshell
import Quickshell.Io
import qs.common
import qs.components
import qs.services
import qs.modules.settings

// Arthur Settings: a real floating window (class dev.arthur.shell; hyprland.lua floats it
// at 1100x740, centred). It exists only while ShellState.settingsOpen, so every open
// re-reads the live compositor values (the Revert baseline). Closing without saving
// drops any live preview.
Scope {
    id: root

    // Section to show; the dev IPC below can set it (screenshots without clicking).
    property string section: "appearance"
    readonly property var sections: [
        { id: "appearance", name: "Appearance", icon: 0xF03D8 },
        { id: "animations", name: "Animations", icon: 0xF0068 },
        { id: "wallpaper",  name: "Wallpaper",  icon: 0xF02E9 },
        { id: "bardock",    name: "Bar & Dock", icon: 0xF10A9 },
        { id: "keybinds",   name: "Keybinds",   icon: 0xF030C },
        { id: "about",      name: "About",      icon: 0xF02FD }
    ]

    IpcHandler {
        target: "settingsapp"
        function section(name: string): string {
            if (!root.sections.some(s => s.id === name)) return "unknown section: " + name;
            root.section = name;
            return "ok";
        }
        function state(): string {
            return JSON.stringify({ open: ShellState.settingsOpen, section: root.section, ready: HyprSettings.ready,
                                    dirty: HyprSettings.dirty, values: HyprSettings.values, status: HyprSettings.status,
                                    binds: HyprSettings.binds.length, liveBinds: HyprSettings.liveBindCount });
        }
        // test hook: move a slider exactly as a drag would (never used by the UI)
        function preview(key: string, value: string): string {
            if (!ShellState.settingsOpen || !HyprSettings.ready) return "not open";
            HyprSettings.set(key, key === "shadow_enabled" ? value === "true" : Number(value));
            return JSON.stringify(HyprSettings.values);
        }
        function revert(): void { HyprSettings.revert(); }
        // test hook: press Save
        function save(): void { HyprSettings.save(); }
    }

    LazyLoader {
        active: ShellState.settingsOpen

        FloatingWindow {
            id: win
            title: "Arthur Settings"
            implicitWidth: 1100
            implicitHeight: 740
            minimumSize: Qt.size(820, 560)
            visible: true
            color: "transparent"

            Component.onCompleted: {
                HyprSettings.begin();
                HyprSettings.loadBinds();
                HyprSettings.loadSysinfo();
            }
            Component.onDestruction: HyprSettings.discard()
            // Closed by the compositor (SUPER+C, title bar): keep ShellState truthful.
            onClosed: ShellState.settingsOpen = false
            onVisibleChanged: if (!visible) ShellState.settingsOpen = false

            // Window glass: bg-base at 0.86 so the compositor blur shows through.
            Rectangle {
                anchors.fill: parent
                color: Theme.withAlpha(Theme.bgBase, 0.86)
            }

            // ---- sidebar ----
            Glass {
                id: side
                tone: "panel"
                shadowEnabled: false
                x: 12; y: 12
                width: 232
                height: parent.height - 24

                Column {
                    id: brand
                    x: 18; y: 20
                    spacing: 2
                    Label { text: "Settings"; font.pixelSize: Theme.fontLarge; font.weight: Font.Bold }
                    Label { text: "arthur-shell"; color: Theme.muted; font.pixelSize: Theme.fontSmall }
                }

                Item {
                    id: nav
                    anchors { top: brand.bottom; topMargin: 20; left: parent.left; right: parent.right; leftMargin: 10; rightMargin: 10 }
                    height: root.sections.length * 46

                    // selection pill glides between entries
                    Rectangle {
                        readonly property int idx: Math.max(0, root.sections.findIndex(s => s.id === root.section))
                        width: parent.width
                        height: 42
                        y: idx * 46
                        radius: Theme.radiusMd
                        color: Theme.accentSoft
                        Behavior on y { Anim { duration: Motion.normal; easing.bezierCurve: Motion.glide } }
                        Rectangle { x: 0; width: 3; height: 20; radius: 2; anchors.verticalCenter: parent.verticalCenter; color: Theme.accentBright }
                    }
                    Column {
                        width: parent.width
                        spacing: 4
                        Repeater {
                            model: root.sections
                            delegate: NavItem {
                                required property var modelData
                                icon: String.fromCodePoint(modelData.icon)
                                text: modelData.name
                                current: root.section === modelData.id
                                onClicked: root.section = modelData.id
                            }
                        }
                    }
                }
            }

            // ---- page ----
            Item {
                id: pageArea
                anchors { left: side.right; right: parent.right; top: parent.top; bottom: footer.top; leftMargin: 4 }
                clip: true

                Repeater {
                    model: root.sections
                    delegate: Loader {
                        id: pl
                        required property var modelData
                        readonly property bool shown: root.section === modelData.id
                        anchors.fill: parent
                        active: shown || item !== null
                        visible: opacity > 0
                        opacity: shown ? 1 : 0
                        Behavior on opacity { Anim { duration: Motion.normal } }
                        transform: Translate {
                            y: pl.shown ? 0 : 12
                            Behavior on y { Anim { duration: Motion.normal; easing.bezierCurve: Motion.emphasized } }
                        }
                        source: {
                            switch (modelData.id) {
                            case "appearance": return "settings/AppearancePage.qml";
                            case "animations": return "settings/AnimationsPage.qml";
                            case "wallpaper": return "settings/WallpaperPage.qml";
                            case "bardock": return "settings/BarDockPage.qml";
                            case "keybinds": return "settings/KeybindsPage.qml";
                            default: return "settings/AboutPage.qml";
                            }
                        }
                    }
                }
            }

            // ---- footer: status + Revert / Save (compositor settings only) ----
            Item {
                id: footer
                anchors { left: side.right; right: parent.right; bottom: parent.bottom; leftMargin: 4 }
                height: 68
                Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 28; rightMargin: 28 } height: 1; color: Theme.edge }

                Row {
                    anchors { left: parent.left; leftMargin: 28; verticalCenter: parent.verticalCenter }
                    spacing: 8
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        size: 16
                        text: String.fromCodePoint(HyprSettings.statusError ? 0xF0026 : HyprSettings.dirty ? 0xF03EB : 0xF012C)
                        color: HyprSettings.statusError ? Theme.error : HyprSettings.dirty ? Theme.warning : Theme.success
                    }
                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        width: footer.width - 380
                        text: HyprSettings.statusError ? HyprSettings.status
                            : HyprSettings.saving ? "Saving…"
                            : HyprSettings.dirty ? "Not saved yet"
                            : HyprSettings.status !== "" ? HyprSettings.status : "All saved"
                        color: HyprSettings.statusError ? Theme.error : Theme.text2
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                    }
                }
                Row {
                    anchors { right: parent.right; rightMargin: 28; verticalCenter: parent.verticalCenter }
                    spacing: 10
                    SButton {
                        icon: String.fromCodePoint(0xF054C)
                        text: "Revert"
                        enabled: HyprSettings.dirty && !HyprSettings.saving
                        onClicked: HyprSettings.revert()
                    }
                    SButton {
                        primary: true
                        icon: String.fromCodePoint(0xF0193)
                        text: "Save"
                        enabled: HyprSettings.dirty && !HyprSettings.saving
                        onClicked: HyprSettings.save()
                    }
                }
            }
        }
    }
}
