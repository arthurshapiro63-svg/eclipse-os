import QtQuick
import qs.common
import qs.components
import qs.services

// Window look: blur, opacity, border, gaps, rounding, shadow. Every change previews live
// (hyprctl eval); Save writes arthur-generated.lua, Revert restores the opened values.
SPage {
    id: page
    title: "Appearance"
    subtitle: "Changes show right away. Save keeps them."
    readonly property var v: HyprSettings.values

    Label {
        visible: !HyprSettings.ready
        text: "Reading compositor settings…"
        color: Theme.muted
    }

    SCard {
        visible: HyprSettings.ready
        title: "Glass"
        icon: String.fromCodePoint(0xF03D8)
        SSlider { label: "Blur size"; from: 1; to: 12; value: page.v.blur_size ?? 0; onMoved: x => HyprSettings.set("blur_size", x) }
        SSlider { label: "Blur passes"; from: 1; to: 4; value: page.v.blur_passes ?? 0; onMoved: x => HyprSettings.set("blur_passes", x) }
        SSlider { label: "Focused opacity"; from: 0.5; to: 1; step: 0.01; decimals: 2; value: page.v.active_opacity ?? 0; onMoved: x => HyprSettings.set("active_opacity", x) }
        SSlider { label: "Other windows"; from: 0.5; to: 1; step: 0.01; decimals: 2; value: page.v.inactive_opacity ?? 0; onMoved: x => HyprSettings.set("inactive_opacity", x) }
    }
    SCard {
        visible: HyprSettings.ready
        title: "Shape"
        icon: String.fromCodePoint(0xF0E09)
        SSlider { label: "Border"; from: 0; to: 4; suffix: " px"; value: page.v.border_size ?? 0; onMoved: x => HyprSettings.set("border_size", x) }
        SSlider { label: "Gaps inside"; from: 0; to: 30; suffix: " px"; value: page.v.gaps_in ?? 0; onMoved: x => HyprSettings.set("gaps_in", x) }
        SSlider { label: "Gaps outside"; from: 0; to: 30; suffix: " px"; value: page.v.gaps_out ?? 0; onMoved: x => HyprSettings.set("gaps_out", x) }
        SSlider { label: "Rounding"; from: 0; to: 24; suffix: " px"; value: page.v.rounding ?? 0; onMoved: x => HyprSettings.set("rounding", x) }
    }
    SCard {
        visible: HyprSettings.ready
        title: "Shadow"
        icon: String.fromCodePoint(0xF0637)
        SToggle { label: "Window shadow"; checked: !!page.v.shadow_enabled; onToggled: c => HyprSettings.set("shadow_enabled", c) }
        SSlider { label: "Shadow size"; from: 0; to: 40; suffix: " px"; value: page.v.shadow_range ?? 0; opacity: page.v.shadow_enabled ? 1 : 0.45
                  onMoved: x => HyprSettings.set("shadow_range", x) }
    }
}
