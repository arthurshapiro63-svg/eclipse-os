pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io

// CPU % and RAM for the bar (agent A). Reads /proc/stat and /proc/meminfo every 3 s,
// only while some surface wants it (`wanted`) and never while GameMode.quiet.
// Consumers set SysStats.wanted from a binding; the bar does that per visible screen.
Singleton {
    id: root

    property bool wanted: false
    readonly property bool running: wanted && !GameMode.quiet

    property real cpu: 0          // 0..100, busy share since the previous sample
    property bool cpuReady: false // false until two samples exist
    property bool memReady: false
    property real memUsedGiB: 0
    property real memTotalGiB: 0
    readonly property real memPercent: memTotalGiB > 0 ? 100 * memUsedGiB / memTotalGiB : 0

    property var _prev: null      // [idle, total]

    function _parseStat(txt) {
        const line = txt.slice(0, txt.indexOf("\n"));
        const f = line.trim().split(/\s+/).slice(1).map(Number);
        if (f.length < 5) return;
        const idle = f[3] + (f[4] || 0);
        const total = f.reduce((a, b) => a + b, 0);
        if (root._prev) {
            const dt = total - root._prev[1], di = idle - root._prev[0];
            if (dt > 0) { root.cpu = Math.max(0, Math.min(100, 100 * (dt - di) / dt)); root.cpuReady = true; }
        }
        root._prev = [idle, total];
    }
    function _parseMem(txt) {
        const tot = /MemTotal:\s+(\d+)/.exec(txt), av = /MemAvailable:\s+(\d+)/.exec(txt);
        if (!tot || !av) return;
        root.memTotalGiB = Number(tot[1]) / 1048576;
        root.memUsedGiB = (Number(tot[1]) - Number(av[1])) / 1048576;
        root.memReady = true;
    }

    function sample() { stat.reload(); mem.reload(); }

    FileView {
        id: stat
        path: root.running ? "/proc/stat" : ""   // setting the path does the first read
        printErrors: false
        onLoaded: if (path !== "") root._parseStat(text())
    }
    FileView {
        id: mem
        path: root.running ? "/proc/meminfo" : ""
        printErrors: false
        onLoaded: if (path !== "") root._parseMem(text())
    }

    Timer {
        interval: 3000
        repeat: true
        running: root.running
        onTriggered: root.sample()
    }
    // A stale CPU delta after a long pause would be an average over the pause: drop it.
    onRunningChanged: if (!running) { _prev = null; cpuReady = false; }
}
