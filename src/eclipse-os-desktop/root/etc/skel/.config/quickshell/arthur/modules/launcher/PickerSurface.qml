pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import qs.common
import qs.components
import qs.services

// Keyboard-first glass picker shared by the launcher and the clipboard history:
// a search field over a list of rows. It maps only while open (or animating closed),
// and holds keyboard focus (Exclusive) only while open.
//
// Rows are plain objects: { title, subtitle, icon (image url or ""), glyph (Nerd Font
// fallback), image (thumbnail url or ""), badge (short tag) }.
PanelWindow {
    id: win

    required property string surface          // "launcher" | "clipboard": namespace + ShellState key
    property bool open: false
    property string placeholder: "Search"
    property string searchGlyph: "\u{f002}"
    property string hint: "↵ open   esc close"
    property string emptyText: "Nothing found"
    property var rows: []
    property int currentIndex: 0
    property int rowHeight: 52
    property int maxRows: 8
    property int panelWidth: 640
    property bool deleteEnabled: false
    property alias query: input.text

    signal activated(int index)
    signal removeRequested(int index)

    property bool mapped: false
    property real progress: 0                  // 0 closed .. 1 open (drives scale + fade)

    screen: Quickshell.screens.find(s => s.name === ShellState.activeScreen) ?? null
    visible: mapped
    color: "transparent"
    WlrLayershell.namespace: "arthur-" + surface
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    // Blur follows the glass as it scales in (Region tracks geometry, not transforms).
    BackgroundEffect.blurRegion: Region {
        readonly property real s: glass.scale
        x: Math.round(glass.x + glass.width * (1 - s) / 2)
        y: glass.y
        width: win.progress > 0.02 ? Math.round(glass.width * s) : 0
        height: win.progress > 0.02 ? Math.round(glass.height * s) : 0
        radius: Math.round(glass.radius * s)
    }

    onOpenChanged: {
        if (open) {
            mapped = true;
            progress = 1;
            currentIndex = 0;
            input.forceActiveFocus();
            input.selectAll();
        } else {
            progress = 0;
        }
    }
    onProgressChanged: if (progress === 0 && !open) mapped = false
    Behavior on progress {
        Anim {
            duration: win.open ? Motion.normal : Motion.fast
            easing.bezierCurve: win.open ? Motion.emphasized : Motion.exit
        }
    }

    property bool _keepIndex: false
    function keepIndexOnce() { _keepIndex = true; }   // next rows change keeps the selection (after a delete)
    onRowsChanged: {
        if (_keepIndex) {
            _keepIndex = false;
            currentIndex = Math.max(0, Math.min(currentIndex, rows.length - 1));
            return;
        }
        currentIndex = 0;
        list.positionViewAtBeginning();
        if (open) fade.restart();
    }

    function move(delta) {
        if (rows.length === 0) return;
        currentIndex = (currentIndex + delta + rows.length) % rows.length;
        list.positionViewAtIndex(currentIndex, ListView.Contain);
    }
    function close() { ShellState.close(surface); }
    function selectQuery() { input.selectAll(); }

    // Click outside the glass closes.
    MouseArea {
        anchors.fill: parent
        enabled: win.open
        onClicked: win.close()
    }

    Glass {
        id: glass
        tone: "panel"
        width: Math.min(win.panelWidth, win.width - 2 * Theme.shadowPad)
        height: column.implicitHeight + 2 * Theme.pad
        x: Math.round((win.width - width) / 2)
        y: Math.round(win.height * 0.2)
        opacity: win.progress
        scale: 0.96 + 0.04 * win.progress
        transformOrigin: Item.Top
        Behavior on height { Anim { duration: Motion.fast } }

        // swallow clicks on the glass itself
        MouseArea { anchors.fill: parent }

        Column {
            id: column
            x: Theme.pad
            y: Theme.pad
            width: parent.width - 2 * Theme.pad
            spacing: 8

            // ---- search field ----
            Item {
                width: parent.width
                height: 44

                Icon {
                    id: searchIcon
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: win.searchGlyph
                    size: 20
                    color: Theme.accentBright
                }
                TextInput {
                    id: input
                    anchors.left: searchIcon.right
                    anchors.leftMargin: 12
                    anchors.right: countLabel.left
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.text
                    font.family: Theme.fontUi
                    font.pixelSize: Theme.fontLarge + 2
                    selectionColor: Theme.accentSoft
                    selectedTextColor: Theme.text
                    selectByMouse: true
                    clip: true
                    focus: true

                    Keys.onPressed: event => {
                        const ctrl = (event.modifiers & Qt.ControlModifier) !== 0;
                        if (event.key === Qt.Key_Escape) { win.close(); event.accepted = true; }
                        else if (event.key === Qt.Key_Down || event.key === Qt.Key_Tab || (ctrl && event.key === Qt.Key_J)) { win.move(1); event.accepted = true; }
                        else if (event.key === Qt.Key_Up || event.key === Qt.Key_Backtab || (ctrl && event.key === Qt.Key_K)) { win.move(-1); event.accepted = true; }
                        else if (event.key === Qt.Key_PageDown) { win.move(Math.min(win.maxRows, win.rows.length - 1 - win.currentIndex) || 0); event.accepted = true; }
                        else if (event.key === Qt.Key_PageUp) { win.move(-Math.min(win.maxRows, win.currentIndex)); event.accepted = true; }
                        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            if (win.rows.length > 0) win.activated(win.currentIndex);
                            event.accepted = true;
                        }
                        else if (win.deleteEnabled && event.key === Qt.Key_Delete) {
                            if (win.rows.length > 0) win.removeRequested(win.currentIndex);
                            event.accepted = true;
                        }
                    }

                    Label {
                        anchors.fill: parent
                        visible: input.text.length === 0
                        text: win.placeholder
                        color: Theme.muted
                        font.pixelSize: input.font.pixelSize
                    }
                }
                Label {
                    id: countLabel
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: win.rows.length > 0 ? String(win.rows.length) : ""
                    color: Theme.muted
                    font.family: Theme.fontMono
                    font.pixelSize: Theme.fontSmall
                }
            }

            Rectangle {
                width: parent.width
                height: 1
                color: Theme.hairline
                visible: list.count > 0 || empty.visible
            }

            // ---- results ----
            ListView {
                id: list
                width: parent.width
                height: Math.min(list.count, win.maxRows) * win.rowHeight
                visible: list.count > 0
                clip: true
                model: win.rows
                currentIndex: win.currentIndex
                boundsBehavior: Flickable.StopAtBounds
                highlightFollowsCurrentItem: false
                highlight: Rectangle {
                    width: list.width
                    height: win.rowHeight
                    y: list.currentItem ? list.currentItem.y : 0
                    radius: Theme.radiusMd
                    color: Theme.accentSoft
                    Behavior on y { Anim { duration: Motion.normal } }
                    Rectangle {
                        x: 0; width: 3; radius: 2
                        height: parent.height - 20
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.accentBright
                    }
                }

                // results cross-fade: a short dip-and-rise on every new result set
                NumberAnimation on opacity {
                    id: fade
                    running: false
                    from: 0.55
                    to: 1
                    duration: Motion.fast
                    easing.type: Easing.BezierSpline
                    easing.bezierCurve: Motion.liquid
                }

                delegate: Item {
                    id: row
                    required property var modelData
                    required property int index
                    width: list.width
                    height: win.rowHeight

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusMd
                        color: rowMouse.containsMouse && row.index !== win.currentIndex ? Theme.hoverFill : "transparent"
                        Behavior on color { CAnim {} }
                    }

                    // icon / thumbnail / glyph
                    Item {
                        id: iconBox
                        x: 10
                        width: 32; height: 32
                        anchors.verticalCenter: parent.verticalCenter
                        IconImage {
                            id: appIcon
                            anchors.fill: parent
                            visible: !!row.modelData.icon && status === Image.Ready
                            source: row.modelData.icon || ""
                            asynchronous: true
                            mipmap: true
                        }
                        Rectangle {
                            anchors.fill: parent
                            visible: !!row.modelData.image
                            radius: Theme.radiusSm
                            color: Theme.cardFill
                            clip: true
                            Image {
                                anchors.fill: parent
                                source: row.modelData.image || ""
                                sourceSize.width: 64
                                sourceSize.height: 64
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                            }
                        }
                        Icon {
                            anchors.centerIn: parent
                            visible: !row.modelData.image && (!row.modelData.icon || appIcon.status !== Image.Ready)
                            text: row.modelData.glyph || "\u{f08c6}"
                            size: 20
                            color: Theme.text2
                        }
                    }

                    Column {
                        anchors.left: iconBox.right
                        anchors.leftMargin: 12
                        anchors.right: badge.left
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Label {
                            width: parent.width
                            text: row.modelData.title || ""
                            font.pixelSize: Theme.fontSize + 1
                            font.weight: row.index === win.currentIndex ? Font.DemiBold : Font.Normal
                            maximumLineCount: 1
                        }
                        Label {
                            width: parent.width
                            visible: text.length > 0
                            text: row.modelData.subtitle || ""
                            color: Theme.text2
                            font.pixelSize: Theme.fontSmall
                            maximumLineCount: 1
                        }
                    }

                    Label {
                        id: badge
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.modelData.badge || ""
                        color: Theme.muted
                        font.pixelSize: Theme.fontSmall
                        font.family: Theme.fontMono
                    }

                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { win.currentIndex = row.index; win.activated(row.index); }
                    }
                }
            }

            Label {
                id: empty
                width: parent.width
                height: 40
                visible: list.count === 0 && input.text.length > 0
                horizontalAlignment: Text.AlignHCenter
                text: win.emptyText
                color: Theme.muted
            }

            Label {
                width: parent.width
                height: 18
                horizontalAlignment: Text.AlignRight
                rightPadding: 8
                text: win.hint
                color: Theme.muted
                font.pixelSize: Theme.fontSmall
            }
        }
    }
}
