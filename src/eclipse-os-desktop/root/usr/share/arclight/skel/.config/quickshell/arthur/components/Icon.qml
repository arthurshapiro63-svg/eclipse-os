import QtQuick
import qs.common

// Nerd Font glyph icon. Pass the codepoint as a string, e.g. text: "".
Text {
    property real size: 16
    color: Theme.text
    font.family: Theme.fontMono
    font.pixelSize: size
    renderType: Text.NativeRendering
    horizontalAlignment: Text.AlignHCenter
    verticalAlignment: Text.AlignVCenter
}
