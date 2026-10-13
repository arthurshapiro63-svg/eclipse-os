import QtQuick
import Quickshell
import qs.common
import qs.components

// A hoverable chip in the bar: soft hover fill that eases in, optional glass tooltip
// after a short hover. Put Icon/Label children inside; they are laid out in a row.
MouseArea {
    id: root

    property bool active: false            // e.g. the panel is open
    property string tip: ""
    property bool forceTip: false          // dev/IPC check: show the tooltip without hovering
    onForceTipChanged: tipLoader.active = forceTip && tip !== ""
    property int padding: 8
    default property alias content: row.data
    property alias spacing: row.spacing

    implicitWidth: row.implicitWidth + 2 * padding
    implicitHeight: parent ? parent.height : 26
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusMd
        color: root.pressed ? Theme.withAlpha(Theme.surfaceHover, 0.8)
             : root.containsMouse ? Theme.hoverFill
             : root.active ? Theme.accentSoft
             : Theme.withAlpha(Theme.surfaceHover, 0)
        Behavior on color { CAnim {} }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
    }

    // tooltip: only exists while shown
    Timer {
        id: tipDelay
        interval: 550
        onTriggered: tipLoader.active = root.tip !== "" && root.containsMouse
    }
    onContainsMouseChanged: {
        if (containsMouse) tipDelay.restart();
        else { tipDelay.stop(); tipLoader.active = root.forceTip; }
    }
    onPressed: { tipDelay.stop(); tipLoader.active = false; }
    LazyLoader {
        id: tipLoader
        active: false
        BarTooltip { target: root; text: root.tip }
    }
}
