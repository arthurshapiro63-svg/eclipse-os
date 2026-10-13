//@ pragma UseQApplication
//@ pragma AppId dev.arthur.shell
//@ pragma Env QT_QUICK_CONTROLS_STYLE=Basic
//@ pragma Env QSG_RENDER_LOOP=threaded
//@ pragma Env QT_WAYLAND_DISABLE_WINDOWDECORATION=1

import QtQuick
import Quickshell
import qs.common
import qs.components
import qs.services
import qs.modules.bar
import qs.modules.dock
import qs.modules.panel
import qs.modules.launcher
import qs.modules.wallpaper
import qs.modules.settings
import qs.modules.notifications
import qs.modules.osd
import qs.modules.power
import qs.modules.overview
import qs.modules.clipboard
// NOTE: Quickshell only registers qs.* modules that shell.qml imports. Any new folder must be imported here.

// arthur-shell: Arthur's own Quickshell desktop shell (replaces DankMaterialShell).
// Every module is its own file under modules/ and is loaded in isolation: a QML error in
// one module is logged and that module is skipped, the rest of the shell keeps running.
// Layer namespaces are all "arthur-<surface>".
ShellRoot {
    id: root

    Ipc {}


    component Module: LazyLoader {
        property string name
        property bool enabled: true
        active: enabled
        source: Quickshell.shellPath("modules/" + name + ".qml")
    }

    Module { name: "Bar" }
    Module { name: "Dock" }
    Module { name: "SidePanel" }
    Module { name: "Launcher" }
    Module { name: "WallpaperPicker" }
    Module { name: "SettingsApp" }
    Module { name: "Notifications" }
    Module { name: "Osd" }
    Module { name: "PowerMenu" }
    Module { name: "Overview" }
    Module { name: "Clipboard" }
}
