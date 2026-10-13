pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import qs.common
import qs.components
import qs.services

// Notification history grouped by app (newest group first). Click a row = its default action
// (while the app still listens); x dismisses one, the group x dismisses the app, "Clear" all.
ColumnLayout {
    id: root

    property date now: new Date()
    spacing: 8

    readonly property var groups: {
        const order = [], map = {};
        for (const e of Notifs.history) {
            if (!map[e.appName]) { map[e.appName] = []; order.push(e.appName); }
            map[e.appName].push(e);
        }
        return order.map(a => ({ app: a, items: map[a] }));
    }

    function ago(t) {
        const s = Math.max(0, Math.floor((root.now.getTime() - t) / 1000));
        if (s < 60) return "now";
        if (s < 3600) return Math.floor(s / 60) + " min";
        if (s < 86400) return Math.floor(s / 3600) + " h";
        return Math.floor(s / 86400) + " d";
    }

    RowLayout {
        Layout.fillWidth: true
        Label {
            Layout.fillWidth: true
            text: Notifs.history.length > 0 ? "Notifications  ·  " + Notifs.history.length : "Notifications"
            font.pixelSize: Theme.fontLarge
            font.weight: Font.DemiBold
        }
        PanelButton {
            visible: Notifs.history.length > 0
            icon: "\u{f05e9}"
            label: "Clear"
            onClicked: Notifs.clearAll()
        }
    }

    // empty state
    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: Notifs.history.length === 0
        Column {
            anchors.centerIn: parent
            spacing: 6
            Icon { anchors.horizontalCenter: parent.horizontalCenter; text: Notifs.dnd ? "\u{f009b}" : "\u{f009a}"; size: 28; color: Theme.muted }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: Notifs.dnd ? "Do not disturb is on" : "No notifications"; color: Theme.muted }
        }
    }

    ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: Notifs.history.length > 0
        clip: true
        spacing: 10
        boundsBehavior: Flickable.StopAtBounds
        model: root.groups

        delegate: ColumnLayout {
            id: group
            required property var modelData
            width: list.width
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                Label {
                    Layout.fillWidth: true
                    text: group.modelData.app + (group.modelData.items.length > 1 ? "  (" + group.modelData.items.length + ")" : "")
                    color: Theme.text2
                    font.pixelSize: Theme.fontSmall + 1
                    font.weight: Font.DemiBold
                }
                PanelButton {
                    implicitWidth: 26; implicitHeight: 26
                    icon: "\u{f0156}"; iconSize: 14; iconColor: Theme.muted
                    onClicked: Notifs.dismissApp(group.modelData.app)
                }
            }

            Repeater {
                model: group.modelData.items
                delegate: Rectangle {
                    id: row
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: body.implicitHeight + 16
                    radius: Theme.radiusMd
                    color: rowHover.hovered ? Theme.hoverFill : Theme.cardFill
                    border.width: 1
                    border.color: row.modelData.urgency === 2 ? Theme.withAlpha(Theme.error, 0.6) : Theme.edge
                    Behavior on color { CAnim {} }

                    // new since the panel was last opened
                    Rectangle {
                        visible: Notifs.newSince > 0 && row.modelData.time >= Notifs.newSince
                        x: 6; y: 14
                        width: 6; height: 6; radius: 3
                        color: Theme.accentBright
                    }

                    ColumnLayout {
                        id: body
                        x: 16; y: 8
                        width: parent.width - 16 - 36
                        spacing: 2
                        RowLayout {
                            Layout.fillWidth: true
                            Label { Layout.fillWidth: true; text: row.modelData.summary; font.weight: Font.DemiBold }
                            Label { text: root.ago(row.modelData.time); color: Theme.muted; font.pixelSize: Theme.fontSmall }
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: row.modelData.body
                            textFormat: Text.StyledText
                            color: Theme.text2
                            wrapMode: Text.Wrap
                            maximumLineCount: 3
                            font.pixelSize: Theme.fontSmall + 1
                        }
                    }
                    HoverHandler { id: rowHover }
                    TapHandler { onTapped: Notifs.activate(row.modelData.key) }
                    PanelButton {
                        anchors.right: parent.right
                        anchors.rightMargin: 6
                        anchors.top: parent.top
                        anchors.topMargin: 6
                        implicitWidth: 26; implicitHeight: 26
                        icon: "\u{f0156}"; iconSize: 14; iconColor: Theme.muted
                        onClicked: Notifs.dismiss(row.modelData.key)
                    }
                }
            }
        }
    }
}
