pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.common

// Compositor settings for the settings app (agent F).
//
// This Hyprland runs a LUA config, so there is no `hyprctl keyword`:
//   read    hyprctl getoption <opt> -j
//   preview hyprctl eval 'hl.config({ decoration = { blur = { passes = 2 } } })'  (live, until reload)
//   save    ~/.local/bin/arthur-settings-apply  (renders ~/.config/hypr/arthur-generated.lua,
//           luac -p, backup, install, hyprctl reload, configerrors + readback, auto-revert on error)
//
// begin()   re-reads the live values; they become the "opened" baseline for revert().
// set(k,v)  clamps, stores and previews (debounced 80 ms, one hyprctl eval for all values).
// revert()  restores the opened values live.  save() persists appearance + animation preset.
Singleton {
    id: root

    // key -> [hyprctl option, lua path, min, max, isFloat]
    readonly property var spec: ({
        blur_size:        ["decoration:blur:size",        "decoration.blur.size",        1, 12, false],
        blur_passes:      ["decoration:blur:passes",      "decoration.blur.passes",      1, 4, false],
        active_opacity:   ["decoration:active_opacity",   "decoration.active_opacity",   0.5, 1.0, true],
        inactive_opacity: ["decoration:inactive_opacity", "decoration.inactive_opacity", 0.5, 1.0, true],
        border_size:      ["general:border_size",         "general.border_size",         0, 4, false],
        gaps_in:          ["general:gaps_in",             "general.gaps_in",             0, 30, false],
        gaps_out:         ["general:gaps_out",            "general.gaps_out",            0, 30, false],
        rounding:         ["decoration:rounding",         "decoration.rounding",         0, 24, false],
        shadow_range:     ["decoration:shadow:range",     "decoration.shadow.range",     0, 40, false],
        shadow_enabled:   ["decoration:shadow:enabled",   "decoration.shadow.enabled",   0, 1, false]
    })
    readonly property var keys: Object.keys(spec)

    property var opened: ({})          // values when the app opened (or after the last save)
    property var values: ({})          // what is live now (previewed)
    property bool ready: false
    property string openedPreset: Config.motion.preset
    property bool openedReduce: Config.motion.reduceMotion
    property string preset: Config.motion.preset
    property bool reduceMotion: Config.motion.reduceMotion

    readonly property bool saving: saver.running
    property string status: ""          // last save/preview message
    property bool statusError: false

    readonly property bool dirty: {
        if (!ready) return false;
        for (const k of keys) if (values[k] !== opened[k]) return true;
        return preset !== openedPreset || reduceMotion !== openedReduce;
    }

    function clamp(k, v) {
        const s = spec[k];
        if (k === "shadow_enabled") return !!v;
        v = Math.min(s[3], Math.max(s[2], Number(v)));
        return s[4] ? Math.round(v * 100) / 100 : Math.round(v);
    }

    function begin() {
        ready = false;
        status = "";
        statusError = false;
        preset = Config.motion.preset;
        reduceMotion = Config.motion.reduceMotion;
        openedPreset = preset;
        openedReduce = reduceMotion;
        reader.running = true;
    }

    function set(k, v) {
        if (!ready) return;
        const c = clamp(k, v);
        if (values[k] === c) return;
        const n = Object.assign({}, values);
        n[k] = c;
        values = n;
        previewTimer.restart();
    }

    function revert() {
        if (!ready) return;
        values = Object.assign({}, opened);
        preset = openedPreset;
        reduceMotion = openedReduce;
        previewTimer.stop();
        _preview();
        status = "Reverted";
        statusError = false;
    }

    // Close without saving: drop any live preview so the desktop matches the saved state.
    function discard() {
        if (ready && dirty) revert();
    }

    function luaFor(vals) {
        const lv = v => typeof v === "boolean" ? (v ? "true" : "false") : String(v);
        return "hl.config({ general = { gaps_in = " + lv(vals.gaps_in) + ", gaps_out = " + lv(vals.gaps_out)
            + ", border_size = " + lv(vals.border_size) + " }, decoration = { rounding = " + lv(vals.rounding)
            + ", active_opacity = " + lv(vals.active_opacity) + ", inactive_opacity = " + lv(vals.inactive_opacity)
            + ", shadow = { enabled = " + lv(vals.shadow_enabled) + ", range = " + lv(vals.shadow_range)
            + " }, blur = { size = " + lv(vals.blur_size) + ", passes = " + lv(vals.blur_passes) + " } } })";
    }

    function _preview() {
        if (previewer.running) { _previewAgain = true; return; }
        previewer.command = ["hyprctl", "eval", luaFor(values)];
        previewer.running = true;
    }
    property bool _previewAgain: false

    function save() {
        if (!ready || saver.running) return;
        const payload = JSON.stringify({
            appearance: values,
            animations: { preset: preset, reduce_motion: reduceMotion }
        });
        status = "Saving…";
        statusError = false;
        saver.command = ["sh", "-c", "printf '%s' \"$1\" | \"$HOME/.local/bin/arthur-settings-apply\" -", "arthur-settings", payload];
        saver.running = true;
    }

    Timer {
        id: previewTimer
        interval: 80
        onTriggered: root._preview()
    }

    // ---- read the live values ----
    Process {
        id: reader
        command: ["sh", "-c", "for o in \"$@\"; do hyprctl getoption \"$o\" -j | tr -d '\\n'; echo; done", "getoptions"]
            .concat(root.keys.map(k => root.spec[k][0]))
        stdout: StdioCollector {
            onStreamFinished: {
                const byOpt = {};
                for (const line of text.split("\n")) {
                    if (!line.trim()) continue;
                    try { const o = JSON.parse(line); byOpt[o.option] = o; } catch (e) {}
                }
                const v = {};
                for (const k of root.keys) {
                    const o = byOpt[root.spec[k][0]];
                    if (!o) continue;
                    if (o.css !== undefined) v[k] = parseInt(o.css.split(" ")[0]);
                    else if (o.bool !== undefined) v[k] = o.bool;
                    else if (o.float !== undefined) v[k] = Math.round(o.float * 100) / 100;
                    else if (o.int !== undefined) v[k] = o.int;
                }
                if (Object.keys(v).length !== root.keys.length) {
                    root.status = "Could not read compositor settings";
                    root.statusError = true;
                    return;
                }
                root.opened = v;
                root.values = Object.assign({}, v);
                root.ready = true;
            }
        }
    }

    Process {
        id: previewer
        stdout: StdioCollector {
            onStreamFinished: {
                const t = text.trim();
                if (t !== "ok" && t !== "") { root.status = t; root.statusError = true; }
            }
        }
        onExited: {
            if (root._previewAgain) { root._previewAgain = false; root._preview(); }
        }
    }

    Process {
        id: saver
        stdout: StdioCollector { id: saveOut }
        stderr: StdioCollector { id: saveErr }
        onExited: (code, status) => {
            if (code === 0) {
                root.opened = Object.assign({}, root.values);
                root.openedPreset = root.preset;
                root.openedReduce = root.reduceMotion;
                Config.motion.preset = root.preset;
                Config.motion.reduceMotion = root.reduceMotion;
                root.status = "Saved";
                root.statusError = false;
            } else {
                const err = (saveErr.text || saveOut.text || ("exit " + code)).trim();
                root.status = err.replace(/^arthur-settings-apply:\s*/, "");
                root.statusError = true;
                // The script restored the previous file and reloaded: show what is live now.
                root.begin();
                root.status = err.replace(/^arthur-settings-apply:\s*/, "");
                root.statusError = true;
            }
        }
    }

    // ---- keybinds: parsed from hyprland.lua (live binds are Lua closures) ----
    property var binds: []
    property int liveBindCount: -1
    property string bindsError: ""
    function loadBinds() {
        bindReader.running = true;
        liveCounter.running = true;
    }
    Process {
        id: bindReader
        command: ["lua", Quickshell.shellPath("modules/settings/keybinds.lua")]
        stdout: StdioCollector {
            onStreamFinished: {
                const out = [];
                for (const line of text.split("\n")) {
                    if (!line.trim()) continue;
                    try { out.push(JSON.parse(line)); } catch (e) {}
                }
                root.binds = out;
            }
        }
        stderr: StdioCollector { onStreamFinished: root.bindsError = text.trim() }
    }
    Process {
        id: liveCounter
        command: ["hyprctl", "binds", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.liveBindCount = JSON.parse(text).length; } catch (e) { root.liveBindCount = -1; }
            }
        }
    }

    // ---- about / system ----
    property var sysinfo: ({})
    function loadSysinfo() { sysReader.running = true; }
    Process {
        id: sysReader
        command: ["sh", "-c", [
            "echo \"commit\t$(git -C \"$HOME/.config\" log -1 --format='%h %cs' -- quickshell/arthur 2>/dev/null)\"",
            "echo \"quickshell\t$(qs --version 2>/dev/null | head -1 | cut -d' ' -f2)\"",
            "echo \"hyprland\t$(hyprctl version -j 2>/dev/null | sed -n 's/.*\"tag\": *\"\\([^\"]*\\)\".*/\\1/p' | head -1)\"",
            "echo \"uptime\t$(cut -d. -f1 /proc/uptime)\"",
            "echo \"cpu\t$(sed -n 's/^model name[^:]*: //p' /proc/cpuinfo | head -1)\"",
            "echo \"cores\t$(nproc)\"",
            "echo \"gpu\t$(lspci 2>/dev/null | sed -n 's/.*\\(VGA\\|Display\\)[^:]*: //p' | head -1)\"",
            "echo \"ram\t$(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{printf \"%.1f/%.1f\", (t-a)/1048576, t/1048576}' /proc/meminfo)\"",
            "echo \"dms\t$(pgrep -x dms >/dev/null && echo running || echo stopped)\"",
            "echo \"kernel\t$(uname -r)\""
        ].join("; ")]
        stdout: StdioCollector {
            onStreamFinished: {
                const o = {};
                for (const line of text.split("\n")) {
                    const i = line.indexOf("\t");
                    if (i > 0) o[line.slice(0, i)] = line.slice(i + 1).trim();
                }
                root.sysinfo = o;
            }
        }
    }
}
