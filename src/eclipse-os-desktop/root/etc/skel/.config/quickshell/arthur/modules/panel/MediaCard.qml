import QtQuick
import QtQuick.Layouts
import Quickshell.Widgets
import qs.common
import qs.components
import qs.services

// Now playing: art, title, artist, previous / play-pause / next. Hidden with no MPRIS player.
Rectangle {
    id: root
    visible: Media.active
    implicitHeight: 76
    radius: Theme.radiusMd
    color: Theme.cardFill
    border.width: 1
    border.color: Theme.edge

    RowLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 12

        ClippingRectangle {
            Layout.preferredWidth: 56
            Layout.preferredHeight: 56
            radius: Theme.radiusSm
            color: Theme.surfaceRaised
            Icon { anchors.centerIn: parent; text: "\u{f0387}"; size: 24; color: Theme.muted; visible: art.status !== Image.Ready }
            Image {
                id: art
                anchors.fill: parent
                source: Media.artUrl
                fillMode: Image.PreserveAspectCrop
                sourceSize: Qt.size(112, 112)
                asynchronous: true
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Label { Layout.fillWidth: true; text: Media.title || "Nothing playing"; font.weight: Font.DemiBold }
            Label { Layout.fillWidth: true; text: Media.artist; color: Theme.text2; font.pixelSize: Theme.fontSmall + 1; visible: text !== "" }
        }
        Row {
            spacing: 2
            PanelButton { icon: "\u{f04ae}"; onClicked: Media.previous() }
            PanelButton { icon: Media.playing ? "\u{f03e4}" : "\u{f040a}"; active: true; onClicked: Media.toggle() }
            PanelButton { icon: "\u{f04ad}"; onClicked: Media.next() }
        }
    }
}
