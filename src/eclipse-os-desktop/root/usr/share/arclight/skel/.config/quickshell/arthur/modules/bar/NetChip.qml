import QtQuick
import Quickshell
import qs.common
import qs.components
import qs.services

// Network icon; the name (SSID / Wired / Offline) is in the tooltip. Click opens the panel.
BarButton {
    id: root
    tip: Network.label + (Network.wifiUp ? "  " + Math.round(Network.strength * 100) + " %" : "") + (Network.limited ? "  (limited)" : "")
    onClicked: ShellState.toggle("panel")

    Icon {
        anchors.verticalCenter: parent.verticalCenter
        text: Network.icon
        size: Theme.fontLarge
        color: !Network.connected ? Theme.muted : Network.limited ? Theme.warning : Theme.text
        Behavior on color { CAnim {} }
    }
}
