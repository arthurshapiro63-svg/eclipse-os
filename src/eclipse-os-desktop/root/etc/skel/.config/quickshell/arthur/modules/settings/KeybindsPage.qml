import QtQuick
import qs.common
import qs.components
import qs.services

// Every keybind in hyprland.lua, searchable, read-only. Parsed by keybinds.lua (the live
// binds are Lua closures, so hyprctl cannot say what they do). Count is checked
// against `hyprctl binds -j`.
Item {
    id: page
    property alias query: search.text

    readonly property var shown: {
        const q = query.trim().toLowerCase();
        const all = HyprSettings.binds;
        if (q === "") return all;
        const words = q.split(/\s+/);
        return all.filter(b => {
            const hay = (b.key + " " + b.action + " " + b.group + " " + b.note).toLowerCase();
            return words.every(w => hay.indexOf(w) >= 0);
        });
    }

    Column {
        id: head
        x: 28; y: 24
        width: page.width - 56
        spacing: 14
        Column {
            width: parent.width
            spacing: 4
            Label { text: "Keybinds"; font.pixelSize: Theme.fontLarge; font.weight: Font.Bold }
            Label {
                width: parent.width
                color: HyprSettings.liveBindCount >= 0 && HyprSettings.liveBindCount !== HyprSettings.binds.length ? Theme.warning : Theme.muted
                text: HyprSettings.bindsError !== "" ? HyprSettings.bindsError
                    : HyprSettings.binds.length + " binds from hyprland.lua"
                      + (HyprSettings.liveBindCount >= 0 ? "  ·  " + HyprSettings.liveBindCount + " live" : "")
                      + (page.query.trim() !== "" ? "  ·  " + page.shown.length + " match" : "")
            }
        }
        Rectangle {
            width: parent.width
            height: 40
            radius: Theme.radiusMd
            color: Theme.withAlpha(Theme.bgSunken, 0.5)
            border.width: 1
            border.color: search.activeFocus ? Theme.accent : Theme.edge
            Behavior on border.color { CAnim {} }
            Icon { id: mag; text: String.fromCodePoint(0xF0349); size: 16; color: Theme.muted; x: 12; anchors.verticalCenter: parent.verticalCenter }
            TextInput {
                id: search
                anchors { left: mag.right; leftMargin: 10; right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                color: Theme.text
                font.family: Theme.fontUi
                font.pixelSize: Theme.fontSize
                clip: true
                Label { visible: search.text === ""; text: "Search keys or actions"; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
            }
        }
    }

    ListView {
        id: list
        anchors { top: head.bottom; topMargin: 12; left: parent.left; leftMargin: 28; right: parent.right; rightMargin: 28; bottom: parent.bottom; bottomMargin: 16 }
        clip: true
        spacing: 2
        boundsBehavior: Flickable.StopAtBounds
        model: page.shown
        delegate: Rectangle {
            id: row
            required property var modelData
            width: list.width
            height: 38
            radius: Theme.radiusSm
            color: rh.containsMouse ? Theme.hoverFill : "transparent"
            Behavior on color { CAnim {} }
            MouseArea { id: rh; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            Row {
                id: keys
                x: 8
                width: 250
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4
                Repeater {
                    model: row.modelData.key.split(" + ")
                    delegate: Rectangle {
                        required property string modelData
                        height: 24
                        width: Math.max(24, kl.implicitWidth + 14)
                        radius: Theme.radiusSm
                        color: Theme.cardFill
                        border.width: 1
                        border.color: Theme.edge
                        Label { id: kl; anchors.centerIn: parent; text: parent.modelData; font.family: Theme.fontMono; font.pixelSize: Theme.fontSmall; color: Theme.text }
                    }
                }
            }
            Label {
                anchors { left: parent.left; leftMargin: 270; right: grp.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                text: row.modelData.action + (row.modelData.note !== "" ? "   ·  " + row.modelData.note : "")
                textFormat: Text.PlainText
            }
            Label {
                id: grp
                width: 100
                anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                horizontalAlignment: Text.AlignRight
                text: row.modelData.group
                color: Theme.muted
                font.pixelSize: Theme.fontSmall
            }
        }
    }
}
