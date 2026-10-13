import QtQuick
import qs.common
import qs.components
import qs.services

// Motion preset for the shell (Config.motion) AND the compositor (hl.animation lines in
// arthur-generated.lua). Both apply together on Save.
SPage {
    id: page
    title: "Animations"
    subtitle: "Pick a feel. Save applies it to windows and the shell."

    readonly property var presets: [
        { id: "calm",   name: "Calm",   icon: 0xF032A, text: "Slower, soft landing" },
        { id: "liquid", name: "Liquid", icon: 0xF058C, text: "The default glide" },
        { id: "snappy", name: "Snappy", icon: 0xF140B, text: "Quick and sharp" }
    ]

    Row {
        width: parent.width
        spacing: 12
        Repeater {
            model: page.presets
            delegate: Glass {
                id: tile
                required property var modelData
                readonly property bool current: HyprSettings.preset === modelData.id
                tone: "card"
                width: (page.width - 56 - 24) / 3
                height: 124
                fill: current ? Theme.accentSoft : (hov.containsMouse ? Theme.hoverFill : Theme.cardFill)
                opacity: HyprSettings.reduceMotion ? 0.5 : 1
                Rectangle {
                    anchors.fill: parent
                    radius: tile.radius
                    color: "transparent"
                    border.width: 2
                    border.color: Theme.accent
                    opacity: tile.current ? 1 : 0
                    Behavior on opacity { Anim { duration: Motion.fast } }
                }
                Column {
                    anchors.centerIn: parent
                    spacing: 6
                    Icon { text: String.fromCodePoint(tile.modelData.icon); size: 26; color: tile.current ? Theme.accentBright : Theme.text2; anchors.horizontalCenter: parent.horizontalCenter }
                    Label { text: tile.modelData.name; font.pixelSize: Theme.fontLarge; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
                    Label { text: tile.modelData.text; color: Theme.muted; font.pixelSize: Theme.fontSmall; anchors.horizontalCenter: parent.horizontalCenter }
                }
                MouseArea {
                    id: hov
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: HyprSettings.preset = tile.modelData.id
                }
            }
        }
    }

    SCard {
        title: "Comfort"
        icon: String.fromCodePoint(0xF0208)
        SToggle {
            label: "Reduce motion"
            hint: "Turns off window and shell animations."
            checked: HyprSettings.reduceMotion
            onToggled: c => HyprSettings.reduceMotion = c
        }
    }

    SCard {
        title: "Now"
        icon: String.fromCodePoint(0xF02FD)
        Label { text: "Saved: " + Config.motion.preset + (Config.motion.reduceMotion ? ", reduced" : "") + "   ·   shell panels " + Motion.slow + " ms"; color: Theme.text2 }
    }
}
