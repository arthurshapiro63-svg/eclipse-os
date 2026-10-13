import QtQuick
import Quickshell
import Quickshell.Io
import qs.common
import qs.components
import qs.services

// Current wallpaper + a button that opens the wallpaper switcher.
SPage {
    id: page
    title: "Wallpaper"
    subtitle: "The picture behind the glass."

    readonly property string current: curFile.text().trim()

    FileView {
        id: curFile
        path: (Quickshell.env("HOME") || "@HOME@") + "/.cache/current-wallpaper"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
    }

    SCard {
        title: "Now showing"
        icon: String.fromCodePoint(0xF02E9)
        Rectangle {
            width: parent.width
            height: Math.round(width * 9 / 16)
            radius: Theme.radiusMd
            color: Theme.bgSunken
            clip: true
            Image {
                anchors.fill: parent
                source: page.current !== "" ? "file://" + page.current : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                sourceSize.width: 1280
                opacity: status === Image.Ready ? 1 : 0
                Behavior on opacity { Anim { duration: Motion.slow } }
            }
        }
        Label {
            text: page.current !== "" ? page.current.split("/").pop() : "No wallpaper found"
            font.pixelSize: Theme.fontLarge
            width: parent.width
        }
    }
    SButton {
        primary: true
        icon: String.fromCodePoint(0xF02E9)
        text: "Choose wallpaper"
        onClicked: ShellState.open("picker")
    }
}
