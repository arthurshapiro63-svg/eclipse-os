pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell.Networking as QsNet
import qs.common
import qs.components
import qs.services

// Wi-Fi network list (opens under the Wi-Fi tile). Scans only while shown.
// Click a network: connected -> Disconnect button; saved or open -> connect;
// secured and new -> a password field (Enter connects with the key).
ColumnLayout {
    id: root

    readonly property var dev: Network.wifi ?? null
    property string askFor: ""            // network name waiting for a password
    property string failed: ""            // network name whose last attempt failed
    spacing: 4

    readonly property var networks: {
        if (!dev) return [];
        const list = dev.networks.values.filter(n => n.name !== "");
        return list.sort((a, b) => (b.connected - a.connected) || (b.known - a.known) || (b.signalStrength - a.signalStrength)).slice(0, 12);
    }

    // scan only while the list is on screen
    Binding {
        target: root.dev ?? null
        property: "scannerEnabled"
        value: true
        when: root.visible && !!root.dev && Network.wifiEnabled
        restoreMode: Binding.RestoreValue
    }

    function glyph(n) {
        const s = n.signalStrength, lock = n.security !== QsNet.WifiSecurityType.Open;
        if (s > 0.75) return lock ? "\u{f092a}" : "\u{f0928}";
        if (s > 0.5) return lock ? "\u{f0927}" : "\u{f0925}";
        if (s > 0.25) return lock ? "\u{f0924}" : "\u{f0922}";
        return lock ? "\u{f0921}" : "\u{f091f}";
    }

    Label {
        Layout.fillWidth: true
        Layout.topMargin: 4
        Layout.bottomMargin: 4
        visible: !root.dev || !Network.wifiEnabled || root.networks.length === 0
        horizontalAlignment: Text.AlignHCenter
        color: Theme.muted
        text: !root.dev ? "No Wi-Fi device" : !Network.wifiEnabled ? "Wi-Fi is off" : "Searching…"
    }

    Repeater {
        model: root.networks
        delegate: Rectangle {
            id: row
            required property var modelData
            readonly property bool asking: root.askFor === modelData.name
            readonly property bool secured: modelData.security !== QsNet.WifiSecurityType.Open
            Layout.fillWidth: true
            implicitHeight: col.implicitHeight + 12
            radius: Theme.radiusSm
            color: rowArea.containsMouse ? Theme.hoverFill : modelData.connected ? Theme.accentSoft : "transparent"
            Behavior on color { CAnim {} }

            Connections {
                target: row.modelData
                function onConnectionFailed(reason) {
                    root.failed = row.modelData.name;
                    if (row.secured) root.askFor = row.modelData.name;
                }
                function onConnectedChanged() { if (row.modelData.connected && root.failed === row.modelData.name) root.failed = ""; }
            }

            MouseArea {
                id: rowArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    const n = row.modelData;
                    if (n.connected || n.stateChanging) return;
                    root.failed = "";
                    if (n.known || !row.secured) { root.askFor = ""; n.connect(); }
                    else root.askFor = row.asking ? "" : n.name;
                }
            }

            ColumnLayout {
                id: col
                x: 8; y: 6
                width: parent.width - 16
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Icon { text: root.glyph(row.modelData); size: 18; color: row.modelData.connected ? Theme.accentBright : Theme.text2 }
                    Label { Layout.fillWidth: true; text: row.modelData.name; font.weight: row.modelData.connected ? Font.DemiBold : Font.Normal }
                    Label {
                        text: row.modelData.stateChanging ? "Connecting…"
                            : root.failed === row.modelData.name ? "Failed"
                            : row.modelData.connected ? "" : row.modelData.known ? "Saved" : ""
                        color: root.failed === row.modelData.name ? Theme.error : Theme.muted
                        font.pixelSize: Theme.fontSmall
                        visible: text !== ""
                    }
                    PanelButton {
                        visible: row.modelData.connected
                        implicitHeight: 26
                        label: "Disconnect"
                        onClicked: row.modelData.disconnect()
                    }
                }

                // password for a new secured network
                Rectangle {
                    visible: row.asking
                    Layout.fillWidth: true
                    Layout.preferredHeight: 34
                    radius: Theme.radiusSm
                    color: Theme.withAlpha(Theme.bgSunken, 0.55)
                    border.width: 1
                    border.color: pass.activeFocus ? Theme.accent : Theme.edge
                    Icon { id: keyIcon; x: 10; anchors.verticalCenter: parent.verticalCenter; text: "\u{f0306}"; size: 14; color: Theme.muted }
                    TextInput {
                        id: pass
                        anchors.left: keyIcon.right
                        anchors.leftMargin: 8
                        anchors.right: go.left
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        echoMode: TextInput.Password
                        color: Theme.text
                        selectionColor: Theme.accent
                        font.family: Theme.fontUi
                        font.pixelSize: Theme.fontSize
                        clip: true
                        onVisibleChanged: if (visible) { text = ""; forceActiveFocus(); }
                        onAccepted: if (text.length > 0) { row.modelData.connectWithPsk(text); root.askFor = ""; text = ""; }
                        Keys.onEscapePressed: event => { root.askFor = ""; event.accepted = true; }
                        Label {
                            anchors.fill: parent
                            visible: pass.text === ""
                            text: "Password"
                            color: Theme.muted
                        }
                    }
                    PanelButton {
                        id: go
                        anchors.right: parent.right
                        anchors.rightMargin: 3
                        anchors.verticalCenter: parent.verticalCenter
                        implicitHeight: 28
                        label: "Join"
                        onClicked: pass.accepted()
                    }
                }
            }
        }
    }
}
