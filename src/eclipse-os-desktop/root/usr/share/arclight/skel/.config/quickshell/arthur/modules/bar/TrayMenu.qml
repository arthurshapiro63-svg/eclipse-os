pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import qs.common
import qs.components
import qs.services

// Glass context menu for a tray item (namespace arthur-menu). One per bar/screen.
// Full-screen transparent layer: a click anywhere outside the menu closes it.
// Never takes keyboard focus. Submenus open in place with a Back row.
PanelWindow {
    id: root

    required property var barWindow           // the bar PanelWindow (for anchor coordinates)
    property var shownFor: null                // SystemTrayItem whose menu is open
    property var stack: []                     // submenu entries, innermost last
    property real anchorX: 0                   // centre x of the tray button, screen coords
    property real anchorY: 0                   // bottom of the bar glass
    readonly property bool open: shownFor !== null
    readonly property var entryTexts: open ? opener.children.values.map(e => e.isSeparator ? "---" : e.text) : []
    readonly property var current: stack.length > 0 ? stack[stack.length - 1] : (shownFor ? shownFor.menu : null)

    function openFor(item, button) {
        if (shownFor === item) { close(); return; }
        const p = button.mapToItem(null, button.width / 2, button.height);
        anchorX = p.x;
        anchorY = p.y + 6;
        stack = [];
        shownFor = item;
    }
    function close() { shownFor = null; stack = []; }
    function enter(entry) {
        if (typeof entry.updateLayout === "function") entry.updateLayout();
        stack = stack.concat([entry]);
    }
    function back() { stack = stack.slice(0, -1); }

    visible: open
    WlrLayershell.namespace: "arthur-menu"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    BackgroundEffect.blurRegion: Region { item: glass.body; radius: glass.radius }

    // close if the item goes away or a game/fullscreen starts
    Connections {
        target: GameMode
        function onQuietChanged() { if (GameMode.quiet) root.close(); }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onPressed: root.close()
    }

    FontMetrics { id: fm; font.family: Theme.fontUi; font.pixelSize: Theme.fontSize }

    QsMenuOpener {
        id: opener
        menu: root.current
    }

    Glass {
        id: glass
        tone: "menu"
        radius: Theme.radiusMd
        width: Math.min(380, Math.max(200, root.entryTexts.reduce((m, t) => Math.max(m, fm.advanceWidth(t)), 0) + 76))
        height: Math.min(col.implicitHeight + 12, root.height - root.anchorY - Theme.gap)
        x: Math.max(Theme.gap, Math.min(root.width - width - Theme.gap, root.anchorX - width / 2))
        y: root.anchorY
        opacity: root.open ? 1 : 0
        Behavior on opacity { Anim { duration: Motion.fast } }

        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }   // clicks inside do not close

        Flickable {
            anchors.fill: parent
            anchors.margins: 6
            contentHeight: col.implicitHeight
            interactive: contentHeight > height
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: col
                width: parent.width

                MenuRow {
                    visible: root.stack.length > 0
                    glyph: "\u{f004d}"                 // md-arrow-left
                    text: "Back"
                    onActivated: root.back()
                }
                Rectangle {
                    visible: root.stack.length > 0
                    width: col.width; height: 1
                    color: Theme.hairline
                }
                Repeater {
                    model: opener.children
                    delegate: Loader {
                        id: row
                        required property var modelData
                        width: col.width
                        sourceComponent: modelData.isSeparator ? sep : entryRow
                        Component {
                            id: sep
                            Item {
                                height: 9
                                Rectangle { anchors.verticalCenter: parent.verticalCenter; x: 8; width: col.width - 16; height: 1; color: Theme.hairline }
                            }
                        }
                        Component {
                            id: entryRow
                            MenuRow {
                                entry: row.modelData
                                text: (row.modelData.text || "").replace(/_([^_])/g, "$1")
                                iconSource: row.modelData.icon || ""
                                enabled: row.modelData.enabled
                                checkType: row.modelData.buttonType
                                checked: row.modelData.checkState === Qt.Checked
                                hasChildren: row.modelData.hasChildren
                                onActivated: {
                                    if (row.modelData.hasChildren) { root.enter(row.modelData); return; }
                                    row.modelData.triggered();
                                    root.close();
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    component MenuRow: MouseArea {
        id: mr
        property var entry: null
        property string text: ""
        property string glyph: ""
        property string iconSource: ""
        property int checkType: 0          // QsMenuButtonType: 0 none, 1 checkbox, 2 radio
        property bool checked: false
        property bool hasChildren: false
        signal activated()
        width: parent ? parent.width : 0
        height: 32
        hoverEnabled: true
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: if (enabled) activated()

        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusSm
            color: mr.containsMouse && mr.enabled ? Theme.hoverFill : Theme.withAlpha(Theme.surfaceHover, 0)
            Behavior on color { CAnim {} }
        }
        Row {
            anchors.left: parent.left; anchors.leftMargin: 10
            anchors.right: parent.right; anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            opacity: mr.enabled ? 1 : 0.45

            Icon {
                visible: mr.checkType !== 0 || mr.glyph !== ""
                anchors.verticalCenter: parent.verticalCenter
                width: 16
                size: 15
                color: mr.checked ? Theme.accentBright : Theme.text2
                text: mr.glyph !== "" ? mr.glyph
                    : mr.checkType === 2 ? (mr.checked ? "\u{f0133}" : "\u{f0130}")      // md-radiobox-marked / blank
                    : (mr.checked ? "\u{f0132}" : "\u{f0131}")                          // md-checkbox-marked / blank
            }
            IconImage {
                visible: mr.iconSource !== "" && mr.checkType === 0
                anchors.verticalCenter: parent.verticalCenter
                implicitSize: 16
                source: mr.iconSource
            }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 40
                text: mr.text
                color: Theme.text
            }
        }
        Icon {
            visible: mr.hasChildren
            anchors.right: parent.right; anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: "\u{f0142}"                     // md-chevron-right
            size: 14
            color: Theme.text2
        }
    }
}
