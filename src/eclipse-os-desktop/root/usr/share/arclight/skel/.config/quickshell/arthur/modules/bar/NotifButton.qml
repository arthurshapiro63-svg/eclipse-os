import QtQuick
import Quickshell
import qs.common
import qs.components
import qs.services

// Notification bell with an unread count; click opens the side panel (notification centre).
// `count` and `dnd` are fed by agent C's notification service through ShellState
// (see handoff/A.md). Until those properties exist they read as 0 / Config DND.
BarButton {
    id: root
    readonly property int count: typeof ShellState.notifUnread === "number" ? ShellState.notifUnread : 0
    readonly property bool dnd: Config.notifications.dnd
    tip: root.dnd ? "Do not disturb" : root.count > 0 ? root.count + " new" : "No new notifications"
    onClicked: ShellState.toggle("panel")

    Icon {
        anchors.verticalCenter: parent.verticalCenter
        text: root.dnd ? "\u{f009b}" : root.count > 0 ? "\u{f116b}" : "\u{f009a}"   // md-bell-off / bell-badge / bell
        size: Theme.fontLarge
        color: root.dnd ? Theme.muted : root.count > 0 ? Theme.accentBright : Theme.text
        Behavior on color { CAnim {} }
    }
    FadeText {
        anchors.verticalCenter: parent.verticalCenter
        visible: root.count > 0 && !root.dnd
        text: root.count > 99 ? "99+" : root.count
        font.family: Theme.fontMono
        font.pixelSize: Theme.fontSmall + 1
        color: Theme.accentBright
        elide: Text.ElideNone
    }
}
