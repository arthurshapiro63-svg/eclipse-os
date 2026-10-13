import QtQuick
import qs.common

// The one glass surface every module uses (GLASS-REPORT language):
//   translucent fill over real compositor blur + 1px light highlight on the top edge
//   + a faint perimeter edge + a soft, dropped near-black outer shadow.
// Put it inside a layer surface that reserves Theme.shadowPad of transparent margin
// around it, and point the window's BackgroundEffect.blurRegion at it (see GlassWindow).
Item {
    id: root

    property string tone: "panel"          // bar | panel | card | menu
    property real radius: tone === "card" ? Theme.radiusMd : Theme.radiusLg
    property bool shadowEnabled: tone !== "card"
    property bool highlight: true
    property color fill: tone === "bar" ? Theme.barFill
                       : tone === "card" ? Theme.cardFill
                       : tone === "menu" ? Theme.withAlpha(Theme.surface, Theme.menuAlpha)
                       : Theme.panelFill
    default property alias content: contentItem.data
    readonly property alias body: body

    // Soft outer shadow that exists ONLY outside the glass shape (a shadow under the
    // translucent fill would darken it: measured 0.55 -> ~0.75 over white). It is a
    // 9-slice of a pre-rendered blurred panel shadow with the body cut out
    // (assets/shadow-r<radius>.png: 28px margin, 5px drop, #050810 @ 0.55, blur sigma 9).
    readonly property int _sp: 28
    readonly property int _sr: radius <= 8 ? 6 : radius <= 13 ? 10 : radius <= 19 ? 16 : 22
    BorderImage {
        visible: root.shadowEnabled
        x: -root._sp; y: -root._sp
        width: root.width + 2 * root._sp; height: root.height + 2 * root._sp
        source: Qt.resolvedUrl("../assets/shadow-r" + root._sr + ".png")
        border { left: root._sp + root._sr + 1; right: root._sp + root._sr + 1; top: root._sp + root._sr + 1; bottom: root._sp + root._sr + 1 }
        horizontalTileMode: BorderImage.Stretch
        verticalTileMode: BorderImage.Stretch
        smooth: true
    }

    Rectangle {
        id: body
        anchors.fill: parent
        radius: root.radius
        color: root.fill
        border.width: 1
        border.color: Theme.edge
        Behavior on color { ColorAnimation { duration: Motion.normal; easing.type: Easing.OutCubic } }

        // one-pixel top highlight: light catching the glass edge
        Rectangle {
            visible: root.highlight
            x: root.radius * 0.6
            y: 0
            width: parent.width - root.radius * 1.2
            height: 1
            color: Theme.hairline
        }
    }

    Item {
        id: contentItem
        anchors.fill: parent
    }
}
