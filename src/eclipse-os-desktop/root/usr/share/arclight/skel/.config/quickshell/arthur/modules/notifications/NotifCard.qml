pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Widgets
import qs.common
import qs.components
import qs.services

// One popup card: glass, app icon/image, summary, body, action buttons, close button.
// Click the card = default action. Hover pauses the timeout. Never takes focus.
Item {
    id: root

    required property string key
    required property int stamp                 // bumps when the app replaces the notification
    property int timeoutMs: Config.notifications.timeoutMs
    signal expired()

    readonly property var entry: { root.stamp; return Notifs.entry(root.key); }
    readonly property var notif: { root.stamp; return Notifs.liveNotif(root.key); }
    readonly property bool critical: !!entry && entry.urgency === 2
    readonly property var actions: notif ? notif.actions.filter(a => a.identifier !== "default" && a.text !== "") : []
    readonly property string imageSrc: {
        if (!entry) return "";
        if (notif && notif.image) return notif.image;
        return entry.image || "";
    }
    readonly property string iconSrc: {
        const i = entry ? entry.appIcon : "";
        if (!i) return "";
        if (i.startsWith("/")) return "file://" + i;
        if (i.startsWith("file://") || i.startsWith("image://")) return i;
        return Quickshell.iconPath(i, true);
    }
    readonly property bool hovered: hover.hovered
    readonly property alias body: glass.body

    implicitHeight: glass.height

    Glass {
        id: glass
        tone: "panel"
        width: root.width
        height: content.implicitHeight + 2 * Theme.pad
        radius: Theme.radiusLg

        // critical: thin accent-error rail on the left edge
        Rectangle {
            visible: root.critical
            x: 0; y: Theme.radiusLg
            width: 3; height: parent.height - 2 * Theme.radiusLg
            radius: 2
            color: Theme.error
        }

        HoverHandler { id: hover }
        TapHandler {
            onTapped: { Notifs.activate(root.key); Notifs.hidePopup(root.key); }
        }

        ColumnLayout {
            id: content
            x: Theme.pad; y: Theme.pad
            width: parent.width - 2 * Theme.pad
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                // image (sender avatar / album art) > app icon > bell glyph
                Item {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 40
                    Layout.alignment: Qt.AlignTop
                    ClippingRectangle {
                        anchors.fill: parent
                        radius: Theme.radiusMd
                        color: Theme.cardFill
                        visible: root.imageSrc !== ""
                        Image {
                            anchors.fill: parent
                            source: root.imageSrc
                            fillMode: Image.PreserveAspectCrop
                            sourceSize: Qt.size(80, 80)
                            asynchronous: true
                        }
                    }
                    IconImage {
                        anchors.fill: parent
                        anchors.margins: 4
                        visible: root.imageSrc === "" && root.iconSrc !== ""
                        source: root.iconSrc
                        asynchronous: true
                    }
                    Icon {
                        anchors.centerIn: parent
                        visible: root.imageSrc === "" && root.iconSrc === ""
                        text: "\u{f009a}"
                        size: 22
                        color: root.critical ? Theme.error : Theme.accentBright
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            text: root.entry ? root.entry.appName : ""
                            color: Theme.muted
                            font.pixelSize: Theme.fontSmall
                        }
                        // close
                        Rectangle {
                            Layout.preferredWidth: 22
                            Layout.preferredHeight: 22
                            radius: 11
                            color: closeHover.hovered ? Theme.hoverFill : "transparent"
                            Behavior on color { CAnim {} }
                            Icon { anchors.centerIn: parent; text: "\u{f0156}"; size: 14; color: Theme.text2 }
                            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: Notifs.hidePopup(root.key) }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.entry ? root.entry.summary : ""
                        font.pixelSize: Theme.fontSize + 1
                        font.weight: Font.DemiBold
                        maximumLineCount: 2
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: root.entry ? root.entry.body : ""
                        textFormat: Text.StyledText
                        color: Theme.text2
                        maximumLineCount: 4
                        wrapMode: Text.Wrap
                    }
                }
            }

            // action buttons
            RowLayout {
                Layout.fillWidth: true
                visible: root.actions.length > 0
                spacing: 6
                Repeater {
                    model: root.actions
                    delegate: Rectangle {
                        id: btn
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: 30
                        radius: Theme.radiusSm
                        color: btnHover.hovered ? Theme.accentSoft : Theme.cardFill
                        border.width: 1
                        border.color: Theme.edge
                        Behavior on color { CAnim {} }
                        Label {
                            anchors.centerIn: parent
                            width: parent.width - 12
                            horizontalAlignment: Text.AlignHCenter
                            text: btn.modelData.text
                            font.pixelSize: Theme.fontSmall + 1
                        }
                        HoverHandler { id: btnHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            onTapped: { Notifs.invokeAction(root.key, btn.modelData.identifier); Notifs.hidePopup(root.key); }
                        }
                    }
                }
            }
        }
    }

    // timeout, paused (restarted) while hovered; critical stays until closed
    Timer {
        id: timeout
        interval: Math.max(1500, root.timeoutMs)
        running: !root.critical && !root.hovered
        onTriggered: root.expired()
    }
    onStampChanged: timeout.restart()
}
