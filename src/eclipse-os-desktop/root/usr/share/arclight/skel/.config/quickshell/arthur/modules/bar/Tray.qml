pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Widgets
import Quickshell.Services.SystemTray
import qs.common
import qs.components

// System tray. Left click = activate (or menu for menu-only items), right click = glass
// menu (TrayMenu, namespace arthur-menu), middle = secondary activate, scroll passes through.
Row {
    id: root

    required property var menu          // the screen's TrayMenu
    spacing: 2
    visible: SystemTray.items.values.length > 0

    function iconFor(item) {
        const icon = item ? item.icon : "";
        if (!icon) return "";
        if (icon.includes("?path=")) {          // "name?path=/dir" -> file:///dir/name
            const parts = icon.split("?path=");
            const name = parts[0].substring(parts[0].lastIndexOf("/") + 1);
            return "file://" + parts[1] + "/" + name;
        }
        if (icon.startsWith("/")) return "file://" + icon;
        return icon;
    }

    function buttonAt(i) { return rep.itemAt(i); }

    Repeater {
        id: rep
        model: SystemTray.items
        delegate: BarButton {
            id: btn
            required property var modelData
            padding: 5
            tip: modelData.tooltipTitle || modelData.title || modelData.id
            active: root.menu.shownFor === modelData
            onClicked: mouse => {
                if (mouse.button === Qt.MiddleButton) modelData.secondaryActivate();
                else if (mouse.button === Qt.RightButton || modelData.onlyMenu) {
                    if (modelData.hasMenu) root.menu.openFor(modelData, btn);
                } else modelData.activate();
            }
            onWheel: wheel => modelData.scroll(wheel.angleDelta.y > 0 ? 1 : -1, false)

            IconImage {
                anchors.verticalCenter: parent.verticalCenter
                implicitSize: 18
                asynchronous: true
                source: root.iconFor(btn.modelData)
                opacity: btn.modelData.status === Status.Passive ? 0.6 : 1
            }
        }
    }
}
