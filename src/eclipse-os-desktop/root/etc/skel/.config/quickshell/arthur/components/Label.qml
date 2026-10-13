import QtQuick
import qs.common

// Text with the shell's type defaults.
Text {
    color: Theme.text
    font.family: Theme.fontUi
    font.pixelSize: Theme.fontSize
    renderType: Text.NativeRendering
    verticalAlignment: Text.AlignVCenter
    elide: Text.ElideRight
}
