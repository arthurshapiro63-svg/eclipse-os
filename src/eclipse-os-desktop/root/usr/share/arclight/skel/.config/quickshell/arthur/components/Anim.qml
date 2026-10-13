import QtQuick
import qs.common

// NumberAnimation preset on the shell's motion tokens. Use in Behaviors:
//   Behavior on y { Anim {} }       Behavior on opacity { Anim { duration: Motion.fast } }
NumberAnimation {
    duration: Motion.normal
    easing.type: Easing.BezierSpline
    easing.bezierCurve: Motion.liquid
}
