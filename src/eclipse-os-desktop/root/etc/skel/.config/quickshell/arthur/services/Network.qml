pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Networking

// NetworkManager state via Quickshell.Networking. This box: wifi (wlp194s0) in use,
// wired port (eno1) present but unplugged.
Singleton {
    id: root

    readonly property var devices: Networking.devices.values
    readonly property var wifi: devices.find(d => d.type === DeviceType.Wifi) ?? null
    readonly property var wired: devices.find(d => d.type === DeviceType.Wired) ?? null
    readonly property bool wiredUp: !!wired && wired.connected
    readonly property var wifiNetwork: wifi ? (wifi.networks.values.find(n => n.connected) ?? null) : null
    readonly property bool wifiUp: !!wifiNetwork
    readonly property bool connected: wiredUp || wifiUp
    readonly property string label: wiredUp ? "Wired" : wifiUp ? wifiNetwork.name : "Offline"
    readonly property real strength: wifiUp ? wifiNetwork.signalStrength : (wiredUp ? 1 : 0)   // 0..1
    readonly property bool wifiEnabled: Networking.wifiEnabled
    readonly property bool limited: Networking.connectivity === NetworkConnectivity.Limited || Networking.connectivity === NetworkConnectivity.Portal

    // Nerd Font glyphs (md-wifi strength ramp / ethernet / off)
    readonly property string icon: wiredUp ? "\u{f0200}"
        : !wifiUp ? "\u{f092e}"
        : strength > 0.75 ? "\u{f0928}" : strength > 0.5 ? "\u{f0925}" : strength > 0.25 ? "\u{f0922}" : "\u{f091f}"

    function setWifiEnabled(on) { Networking.wifiEnabled = on; }
}
