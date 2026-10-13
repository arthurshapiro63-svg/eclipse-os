import QtQuick
import qs.common

ColorAnimation {
    duration: Motion.fast
    easing.type: Easing.BezierSpline
    easing.bezierCurve: Motion.liquid
}
