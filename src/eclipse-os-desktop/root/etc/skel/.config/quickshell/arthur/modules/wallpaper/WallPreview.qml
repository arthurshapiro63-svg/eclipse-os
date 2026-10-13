import QtQuick
import Quickshell.Widgets
import qs.common
import qs.components

// Large preview of the focused wallpaper (not applied). The cached thumbnail shows at once;
// the full image is decoded off-thread at preview size after a short settle delay (so fast
// scrolling never decodes every 4K file) and fades in over it.
ClippingRectangle {
    id: root

    property string path: ""
    property string thumb: ""
    property bool thumbReady: false

    radius: Theme.radiusMd
    color: Theme.bgSunken

    Image {
        id: low
        anchors.fill: parent
        source: root.thumbReady ? "file://" + root.thumb : ""
        sourceSize: Qt.size(480, 270)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        smooth: true
    }

    Image {
        id: high
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        smooth: true
        sourceSize: Qt.size(Math.max(1, Math.round(root.width)), Math.max(1, Math.round(root.height)))
        readonly property bool matches: source.toString() === (root.path ? "file://" + root.path : "")
        opacity: status === Image.Ready && matches ? 1 : 0
        Behavior on opacity { Anim { duration: Motion.normal } }
    }

    Timer {
        id: settle
        interval: 140
        onTriggered: high.source = root.path ? "file://" + root.path : ""
    }
    onPathChanged: settle.restart()
    Component.onCompleted: settle.restart()

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: "transparent"
        border.width: 1
        border.color: Theme.edge
    }
}
