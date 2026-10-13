import QtQuick
import Quickshell
import qs.common
import qs.components

// Bar clock + weather and dock behaviour + pinned apps. Shell settings apply instantly
// (Config writes settings.json).
SPage {
    id: page
    title: "Bar & Dock"
    subtitle: "These change instantly."

    SCard {
        title: "Clock"
        icon: String.fromCodePoint(0xF0954)
        SToggle { label: "24-hour clock"; checked: Config.bar.clock24h; onToggled: c => Config.bar.clock24h = c }
        SToggle { label: "Show seconds"; checked: Config.bar.showSeconds; onToggled: c => Config.bar.showSeconds = c }
    }

    SCard {
        title: "Weather"
        icon: String.fromCodePoint(0xF0599)
        SToggle { label: "Show weather"; checked: Config.bar.showWeather; onToggled: c => Config.bar.showWeather = c }
        SToggle { label: "Celsius"; checked: Config.bar.celsius; onToggled: c => Config.bar.celsius = c }
        Item {
            width: parent.width
            height: 36
            Label { id: pl; text: "Place"; width: 170; anchors.verticalCenter: parent.verticalCenter }
            Rectangle {
                anchors { left: pl.right; leftMargin: 8; right: parent.right; verticalCenter: parent.verticalCenter }
                height: 34
                radius: Theme.radiusSm
                color: Theme.withAlpha(Theme.bgSunken, 0.5)
                border.width: 1
                border.color: place.activeFocus ? Theme.accent : Theme.edge
                TextInput {
                    id: place
                    anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.text
                    font.family: Theme.fontUi
                    font.pixelSize: Theme.fontSize
                    text: Config.bar.weatherPlace
                    onEditingFinished: if (text.trim() !== "") Config.bar.weatherPlace = text.trim()
                }
            }
        }
        Label {
            text: "Location  " + Config.bar.weatherLat.toFixed(2) + ", " + Config.bar.weatherLon.toFixed(2) + "  (settings.json bar.weatherLat / weatherLon)"
            color: Theme.muted
            font.pixelSize: Theme.fontSmall
            width: parent.width
        }
    }

    SCard {
        title: "Dock"
        icon: String.fromCodePoint(0xF10A9)
        SToggle { label: "Hide the dock"; hint: "It slides up when the pointer reaches the bottom."; checked: Config.dock.autoHide; onToggled: c => Config.dock.autoHide = c }
    }

    SCard {
        title: "Pinned apps"
        icon: String.fromCodePoint(0xF0403)
        Label { visible: Config.dock.pinned.length === 0; text: "Nothing pinned"; color: Theme.muted }
        Repeater {
            model: Config.dock.pinned
            delegate: Item {
                id: pin
                required property string modelData
                required property int index
                readonly property var entry: DesktopEntries.heuristicLookup(modelData)
                width: parent.width
                height: 44
                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusSm
                    color: pinHover.containsMouse ? Theme.hoverFill : "transparent"
                    Behavior on color { CAnim {} }
                    MouseArea { id: pinHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                }
                Image {
                    id: appIcon
                    x: 8
                    width: 28; height: 28
                    anchors.verticalCenter: parent.verticalCenter
                    source: pin.entry && pin.entry.icon ? Quickshell.iconPath(pin.entry.icon, true) : ""
                    sourceSize: Qt.size(56, 56)
                }
                Column {
                    anchors { left: appIcon.right; leftMargin: 12; right: btns.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    Label { text: pin.entry ? pin.entry.name : pin.modelData; width: parent.width }
                    Label { text: pin.modelData; color: Theme.muted; font.pixelSize: Theme.fontSmall; width: parent.width }
                }
                Row {
                    id: btns
                    anchors { right: parent.right; rightMargin: 4; verticalCenter: parent.verticalCenter }
                    spacing: 6
                    SButton { icon: String.fromCodePoint(0xF0143); implicitWidth: 36; enabled: pin.index > 0; onClicked: page.move(pin.index, -1) }
                    SButton { icon: String.fromCodePoint(0xF0140); implicitWidth: 36; enabled: pin.index < Config.dock.pinned.length - 1; onClicked: page.move(pin.index, 1) }
                    SButton { icon: String.fromCodePoint(0xF01B4); danger: true; implicitWidth: 36; onClicked: page.remove(pin.index) }
                }
            }
        }
    }

    function move(i, d) {
        const a = Array.from(Config.dock.pinned);
        const j = i + d;
        if (j < 0 || j >= a.length) return;
        const t = a[i]; a[i] = a[j]; a[j] = t;
        Config.dock.pinned = a;
    }
    function remove(i) {
        const a = Array.from(Config.dock.pinned);
        a.splice(i, 1);
        Config.dock.pinned = a;
    }
}
