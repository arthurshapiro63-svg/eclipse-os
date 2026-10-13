import QtQuick
import Quickshell
import qs.common
import qs.components
import qs.services

// Current weather (Open-Meteo, fixed place from settings). Click = refresh now.
BarButton {
    id: root
    visible: Config.bar.showWeather
    tip: Weather.ready ? (Weather.place + ": " + Weather.description + ", " + Math.round(Weather.temp) + Weather.unit) : (Weather.place + ": loading")
    spacing: 6
    onClicked: Weather.refresh()

    FadeText {
        anchors.verticalCenter: parent.verticalCenter
        text: Weather.icon
        font.family: Theme.fontMono
        font.pixelSize: Theme.fontLarge
        color: Weather.ready ? Theme.accentBright : Theme.muted
        elide: Text.ElideNone
    }
    FadeText {
        anchors.verticalCenter: parent.verticalCenter
        text: Weather.tempText
        font.features: { "tnum": 1 }
        color: Theme.text
        elide: Text.ElideNone
    }
}
