pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Bluetooth
import qs.common
import qs.components

// Paired Bluetooth devices (opens under the Bluetooth tile): click to connect / disconnect,
// battery when the device reports it. Pairing a new device (PIN prompts) is handed to
// bluetoothctl in a terminal.
ColumnLayout {
    id: root

    readonly property var adapter: Bluetooth.defaultAdapter
    signal pairRequested()
    spacing: 4

    readonly property var devices: {
        if (!adapter) return [];
        return adapter.devices.values.filter(d => d.paired || d.connected)
            .sort((a, b) => (b.connected - a.connected) || (a.name || "").localeCompare(b.name || ""));
    }

    function glyph(d) {
        const i = ((d.icon || "") + " " + (d.name || "")).toLowerCase();
        if (/headset|headphone|audio|earbud|buds|airpod/.test(i)) return "\u{f02cb}";
        if (/speaker/.test(i)) return "\u{f04c3}";
        if (/mouse/.test(i)) return "\u{f037d}";
        if (/keyboard/.test(i)) return "\u{f030c}";
        if (/phone/.test(i)) return "\u{f011c}";
        if (/gamepad|joystick|controller/.test(i)) return "\u{f0297}";
        if (/watch/.test(i)) return "\u{f0589}";
        if (/display|tv/.test(i)) return "\u{f0502}";
        return "\u{f00af}";
    }

    Label {
        Layout.fillWidth: true
        Layout.topMargin: 4
        Layout.bottomMargin: 4
        visible: !root.adapter || !root.adapter.enabled || root.devices.length === 0
        horizontalAlignment: Text.AlignHCenter
        color: Theme.muted
        text: !root.adapter ? "No Bluetooth adapter" : !root.adapter.enabled ? "Bluetooth is off" : "No paired devices"
    }

    Repeater {
        model: root.adapter && root.adapter.enabled ? root.devices : []
        delegate: Rectangle {
            id: row
            required property var modelData
            readonly property bool busy: modelData.state === BluetoothDeviceState.Connecting || modelData.state === BluetoothDeviceState.Disconnecting
            Layout.fillWidth: true
            implicitHeight: 40
            radius: Theme.radiusSm
            color: rowArea.containsMouse ? Theme.hoverFill : modelData.connected ? Theme.accentSoft : "transparent"
            Behavior on color { CAnim {} }

            MouseArea {
                id: rowArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (row.busy) return;
                    if (row.modelData.connected) row.modelData.disconnect();
                    else row.modelData.connect();
                }
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 10
                spacing: 10
                Icon { text: root.glyph(row.modelData); size: 18; color: row.modelData.connected ? Theme.accentBright : Theme.text2 }
                Label { Layout.fillWidth: true; text: row.modelData.name || row.modelData.address; font.weight: row.modelData.connected ? Font.DemiBold : Font.Normal }
                Label {
                    text: row.modelData.state === BluetoothDeviceState.Connecting ? "Connecting…"
                        : row.modelData.state === BluetoothDeviceState.Disconnecting ? "Disconnecting…"
                        : row.modelData.connected ? (row.modelData.batteryAvailable ? Math.round(row.modelData.battery * 100) + "%" : "Connected")
                        : "Paired"
                    color: row.modelData.connected ? Theme.text2 : Theme.muted
                    font.pixelSize: Theme.fontSmall
                    font.family: row.modelData.batteryAvailable && row.modelData.connected ? Theme.fontMono : Theme.fontUi
                }
            }
        }
    }

    PanelButton {
        Layout.alignment: Qt.AlignHCenter
        icon: "\u{f0415}"
        label: "Pair new device…"
        onClicked: root.pairRequested()
    }
}
