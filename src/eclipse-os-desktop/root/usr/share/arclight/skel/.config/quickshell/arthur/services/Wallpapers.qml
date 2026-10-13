pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.common

// Wallpaper list + thumbnail cache + apply, for the wallpaper switcher.
//   model    ListModel of { path, name, thumb, ready } in the same order `wallpaper` uses
//   current  absolute path of the wallpaper on screen (~/.cache/current-wallpaper, watched)
//   refresh() runs ~/.local/bin/wallpaper-thumbs once (never blocks: it streams lines)
//   apply(p)  runs ~/.local/bin/wallpaper <p> (awww transition on every output, persists,
//             recolours in dynamic mode). dryRun "log" only records the call, "hdmi" paints
//             HDMI-A-1 with awww directly and persists nothing (dev testing).
Singleton {
    id: root

    readonly property string home: Quickshell.env("HOME") || "@HOME@"
    readonly property string dir: {
        const d = Config.wallpaper.dir || "~/Pictures/wallpapers";
        return d.startsWith("~/") ? home + d.slice(1) : d;
    }
    readonly property alias model: list
    readonly property string current: _currentText.trim()
    readonly property bool scanning: scan.running
    readonly property bool applying: applier.running
    property string dryRun: ""          // "" | "log" | "hdmi"
    property string lastApplyLog: ""
    // stats of the last scan: thumbnails generated and wall time in ms (from the D line)
    property int lastGenerated: -1
    property int lastScanMs: -1

    property string _currentText: ""
    property int _seen: 0

    function nameOf(path) {
        const base = path.substring(path.lastIndexOf("/") + 1).replace(/\.[^.]+$/, "");
        const words = base.replace(/[-_]+/g, " ").trim();
        return words.length ? words.charAt(0).toUpperCase() + words.slice(1) : base;
    }
    function indexOf(path) {
        for (let i = 0; i < list.count; i++)
            if (list.get(i).path === path) return i;
        return -1;
    }

    function refresh() {
        if (scan.running) return;
        root._seen = 0;
        scan.command = [root.home + "/.local/bin/wallpaper-thumbs", root.dir];
        scan.running = true;
    }

    function apply(path) {
        if (!path || applier.running) return;
        if (root.dryRun === "log") {
            applier.command = ["sh", "-c", "printf 'dry-run: wallpaper %s\\n' \"$1\"", "sh", path];
        } else if (root.dryRun === "hdmi") {
            applier.command = ["awww", "img", path, "--outputs", "HDMI-A-1", "--resize", "crop",
                               "--transition-type", "grow", "--transition-duration", "1.5",
                               "--transition-fps", "120", "--transition-pos", "center"];
        } else {
            applier.command = [root.home + "/.local/bin/wallpaper", path];
        }
        root.lastApplyLog = "";
        applier.running = true;
    }

    function _line(line) {
        const f = line.split("\t");
        if (f[0] === "I" && f.length >= 4) {
            const row = { path: f[1], name: root.nameOf(f[1]), thumb: f[2], ready: f[3] === "1" };
            const k = root._seen++;
            if (k < list.count) {
                const old = list.get(k);
                if (old.path === row.path && old.thumb === row.thumb) {
                    if (old.ready !== row.ready) list.setProperty(k, "ready", row.ready);
                } else {
                    list.set(k, row);
                }
            } else {
                list.append(row);
            }
        } else if (f[0] === "T" && f.length >= 2) {
            for (let i = 0; i < list.count; i++)
                if (list.get(i).thumb === f[1]) { list.setProperty(i, "ready", true); break; }
        } else if (f[0] === "D" && f.length >= 3) {
            if (list.count > root._seen) list.remove(root._seen, list.count - root._seen);
            root.lastGenerated = parseInt(f[1]);
            root.lastScanMs = parseInt(f[2]);
        } else if (f[0] === "E") {
            console.info("Wallpapers: thumbnail failed:", f.slice(1).join(" "));
        }
    }

    ListModel { id: list }

    Process {
        id: scan
        stdout: SplitParser { onRead: data => root._line(data) }
        onExited: (code, status) => {
            if (code !== 0) console.info("Wallpapers: wallpaper-thumbs exited", code);
        }
    }

    Process {
        id: applier
        stdout: StdioCollector { onStreamFinished: root.lastApplyLog = text.trim() }
        onExited: (code, status) => {
            if (code !== 0) console.info("Wallpapers: apply exited", code);
        }
    }

    FileView {
        path: root.home + "/.cache/current-wallpaper"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: root._currentText = text()
    }
}
