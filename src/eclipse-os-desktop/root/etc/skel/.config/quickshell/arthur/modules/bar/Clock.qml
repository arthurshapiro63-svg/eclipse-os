import QtQuick
import Quickshell
import qs.common
import qs.components
import qs.services

// Time + date. Click opens the side panel (calendar lives there).
BarButton {
    id: root
    property bool running: true
    tip: Qt.formatDate(clock.date, "dddd d MMMM yyyy")
    active: ShellState.panelOpen
    spacing: 8
    onClicked: ShellState.toggle("panel")

    SystemClock {
        id: clock
        enabled: root.running
        precision: Config.bar.showSeconds ? SystemClock.Seconds : SystemClock.Minutes
    }

    FadeText {
        anchors.verticalCenter: parent.verticalCenter
        fade: !Config.bar.showSeconds
        text: Qt.formatTime(clock.date, Config.bar.clock24h ? (Config.bar.showSeconds ? "HH:mm:ss" : "HH:mm")
                                                            : (Config.bar.showSeconds ? "h:mm:ss AP" : "h:mm AP"))
        font.family: Theme.fontUi
        font.pixelSize: Theme.fontSize + 1
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
        color: Theme.text
        elide: Text.ElideNone
    }
    FadeText {
        anchors.verticalCenter: parent.verticalCenter
        text: Qt.formatDate(clock.date, "ddd d MMM")
        color: Theme.text2
        elide: Text.ElideNone
    }
}
