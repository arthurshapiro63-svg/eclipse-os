pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.common
import qs.components
import qs.services
import qs.modules.notifications

// Notification popups (owner: agent C). Glass cards stacked top-right of the active screen,
// under the bar. New cards slide in from the right and fade; they leave the same way.
// Never takes keyboard focus. The window is unmapped while there is nothing to show.
Scope {
    id: root

    readonly property var screenObj: Quickshell.screens.find(s => s.name === ShellState.activeScreen) ?? null

    readonly property int cardWidth: 380
    readonly property int maxCards: 5
    property var cardBodies: []          // glass bodies of the live cards -> blur region

    function registerBody(b) { if (cardBodies.indexOf(b) < 0) cardBodies = cardBodies.concat([b]); }
    function unregisterBody(b) { const i = cardBodies.indexOf(b); if (i >= 0) { const a = cardBodies.slice(); a.splice(i, 1); cardBodies = a; } }

    PanelWindow {
        id: win

        screen: root.screenObj
        visible: !!root.screenObj && (Notifs.popups.count > 0 || list.leaving > 0) && !ShellState.panelOpen && !GameMode.fullscreenOn(ShellState.activeScreen)

        WlrLayershell.namespace: "arthur-notifs"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Normal
        exclusiveZone: 0
        anchors { top: true; right: true }
        margins { top: 0; right: 0 }
        implicitWidth: root.cardWidth + Theme.gap + Theme.shadowPad
        implicitHeight: Math.max(1, Math.min(list.contentHeight + Theme.gap + Theme.shadowPad, (root.screenObj ? root.screenObj.height : 1080) - 120))
        color: "transparent"

        // clicks outside the cards fall through to the windows below
        mask: Region { item: list.contentItem }

        BackgroundEffect.blurRegion: Region {
            Region { item: root.cardBodies[0] ?? null; radius: Theme.radiusLg }
            Region { item: root.cardBodies[1] ?? null; radius: Theme.radiusLg }
            Region { item: root.cardBodies[2] ?? null; radius: Theme.radiusLg }
            Region { item: root.cardBodies[3] ?? null; radius: Theme.radiusLg }
            Region { item: root.cardBodies[4] ?? null; radius: Theme.radiusLg }
            Region { item: root.cardBodies[5] ?? null; radius: Theme.radiusLg }
        }

        ListView {
            id: list
            property int leaving: 0
            x: Theme.shadowPad
            y: Theme.gap
            width: root.cardWidth
            height: parent.height - y
            interactive: false
            spacing: 8
            model: Notifs.popups

            add: Transition {
                ParallelAnimation {
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.slow; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.emphasized }
                    NumberAnimation { property: "x"; from: root.cardWidth * 0.6; to: 0; duration: Motion.slow; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.emphasized }
                }
            }
            remove: Transition {
                SequentialAnimation {
                    ScriptAction { script: list.leaving++ }
                    ParallelAnimation {
                        NumberAnimation { property: "opacity"; to: 0; duration: Motion.normal; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.exit }
                        NumberAnimation { property: "x"; to: root.cardWidth * 0.6; duration: Motion.normal; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.exit }
                    }
                    ScriptAction { script: list.leaving = Math.max(0, list.leaving - 1) }
                }
            }
            displaced: Transition {
                NumberAnimation { properties: "y"; duration: Motion.normal; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.liquid }
            }

            delegate: NotifCard {
                id: card
                width: root.cardWidth
                onExpired: Notifs.hidePopup(card.key)
                Component.onCompleted: root.registerBody(card)
                Component.onDestruction: root.unregisterBody(card)
            }
        }
    }

    // qs -c arthur ipc call notifs <fn>
    IpcHandler {
        target: "notifs"
        function test(): void { Notifs.inject("arthur-shell", "Test notification", "This is how a popup looks. Hover to keep it.", 1); }
        function testCritical(): void { Notifs.inject("arthur-shell", "Critical test", "Critical popups stay until closed.", 2); }
        function toggleDnd(): void { Notifs.setDnd(!Notifs.dnd); }
        function clear(): void { Notifs.clearAll(); }
        function status(): string {
            return JSON.stringify({ serving: Notifs.serving, owner: Notifs.busOwner, dnd: Notifs.dnd,
                                    history: Notifs.history.length, unread: Notifs.unreadCount, popups: Notifs.popups.count });
        }
    }
}
