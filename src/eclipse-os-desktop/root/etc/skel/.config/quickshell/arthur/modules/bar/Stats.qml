import QtQuick
import Quickshell
import qs.common
import qs.components
import qs.services

// CPU % and RAM used (GiB). Values from services/SysStats.
BarButton {
    id: root
    tip: !SysStats.running ? "Paused while a game or fullscreen app runs" : "CPU " + Math.round(SysStats.cpu) + " %   RAM " + SysStats.memUsedGiB.toFixed(1) + " / " + SysStats.memTotalGiB.toFixed(1) + " GiB"
    spacing: 10
    cursorShape: Qt.ArrowCursor

    Row {
        spacing: 4
        anchors.verticalCenter: parent.verticalCenter
        Icon { anchors.verticalCenter: parent.verticalCenter; text: "\u{f0ee0}"; size: Theme.fontLarge; color: SysStats.cpu > 85 ? Theme.warning : Theme.text2 }  // md-cpu-64-bit
        FadeText {
            anchors.verticalCenter: parent.verticalCenter
            text: SysStats.cpuReady ? Math.round(SysStats.cpu) + "%" : "--%"
            font.family: Theme.fontMono
            color: Theme.text
            elide: Text.ElideNone
        }
    }
    Row {
        spacing: 4
        anchors.verticalCenter: parent.verticalCenter
        Icon { anchors.verticalCenter: parent.verticalCenter; text: "\u{f035b}"; size: Theme.fontLarge; color: SysStats.memPercent > 85 ? Theme.warning : Theme.text2 }  // md-memory
        FadeText {
            anchors.verticalCenter: parent.verticalCenter
            text: SysStats.memReady ? SysStats.memUsedGiB.toFixed(1) + "G" : "--G"
            font.family: Theme.fontMono
            color: Theme.text
            elide: Text.ElideNone
        }
    }
}
