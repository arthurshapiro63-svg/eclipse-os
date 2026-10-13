pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.common
import qs.services
import qs.modules.launcher

// Clipboard history (SUPER+X): a glass picker over `cliphist list`.
// Enter copies (cliphist decode ID | wl-copy), Delete removes (cliphist delete).
// Images show a small thumbnail (decoded once into Quickshell.cachePath("clipboard/")).
// Needs a `wl-paste --watch cliphist store` watcher (see handoff/D.md). Nothing runs while closed.
Scope {
    id: root

    property var entries: []          // [{ id, text, isImage, kind, size, dims, lower }]
    readonly property string thumbDir: Quickshell.cachePath("clipboard")
    property var thumbReady: ({})     // ids whose thumbnail file has been written
    property string status: ""        // "" | "loading" | "missing" (no cliphist history yet)

    // "[[ binary data 12 KiB png 800x600 ]]"
    readonly property var imageRe: /^\[\[ binary data (.+?) (png|jpe?g|webp|gif|bmp|svg\+xml|[a-z]+) (\d+x\d+)? ?\]\]$/

    function parse(text) {
        const out = [];
        const lines = text.split("\n");
        for (let i = 0; i < lines.length && out.length < 500; i++) {
            const line = lines[i];
            const tab = line.indexOf("\t");
            if (tab <= 0) continue;
            const id = line.slice(0, tab);
            const body = line.slice(tab + 1);
            const m = body.match(root.imageRe);
            out.push({
                id: id, text: body, isImage: !!m,
                kind: m ? m[2] : "", size: m ? m[1] : "", dims: m ? (m[3] || "") : "",
                lower: body.toLowerCase()
            });
        }
        return out;
    }

    function filtered(query) {
        const words = query.toLowerCase().split(/\s+/).filter(w => w.length > 0);
        if (words.length === 0) return root.entries;
        return root.entries.filter(e => words.every(w => e.lower.indexOf(w) >= 0 || (w === "image" && e.isImage)));
    }

    function refresh() {
        root.status = "loading";
        lister.running = true;
    }

    Process {
        id: lister
        command: ["cliphist", "list"]
        stdout: StdioCollector {
            onStreamFinished: {
                root.entries = root.parse(text);
                root.status = root.entries.length === 0 ? "missing" : "";
                const imgs = root.entries.filter(e => e.isImage).slice(0, 40).map(e => e.id);
                thumbs.pending = imgs;
                if (imgs.length > 0) {
                    thumbs.command = ["sh", "-c",
                        'd="$1"; shift; mkdir -p "$d"; for id in "$@"; do [ -s "$d/$id.img" ] || cliphist decode "$id" > "$d/$id.img" 2>/dev/null; done',
                        "sh", root.thumbDir].concat(imgs);
                    thumbs.running = true;
                }
            }
        }
        onExited: code => { if (code !== 0) { root.entries = []; root.status = "missing"; } }
    }
    Process {
        id: thumbs
        property var pending: []
        onExited: {
            const r = Object.assign({}, root.thumbReady);
            pending.forEach(id => r[id] = true);
            root.thumbReady = r;
        }
    }
    Process { id: runner }

    function copy(e) {
        runner.command = ["sh", "-c", 'cliphist decode "$1" | wl-copy', "sh", e.id];
        runner.running = true;
    }
    function remove(e) {
        // cliphist delete reads list lines ("ID<tab>preview") from stdin; the ID is what counts.
        runner.command = ["sh", "-c", 'printf "%s\\t%s\\n" "$1" "$2" | cliphist delete', "sh", e.id, e.text];
        runner.running = true;
        root.entries = root.entries.filter(x => x.id !== e.id);
        Quickshell.execDetached(["rm", "-f", root.thumbDir + "/" + e.id + ".img"]);
    }

    PickerSurface {
        id: picker
        surface: "clipboard"
        open: ShellState.clipboardOpen
        placeholder: "Search clipboard"
        searchGlyph: "\u{f014c}"
        hint: "↵ copy   del remove   esc close"
        emptyText: root.status === "missing" ? "No clipboard history yet" : "Nothing found"
        deleteEnabled: true
        maxRows: 8
        rowHeight: 48

        readonly property var shown: open ? root.filtered(query).slice(0, 200) : []
        rows: shown.map(e => ({
            title: e.isImage ? "Image" : e.text.replace(/\s+/g, " ").trim(),
            subtitle: e.isImage ? [e.kind.toUpperCase(), e.dims, e.size].filter(s => s).join("  ·  ") : "",
            image: e.isImage && root.thumbReady[e.id] ? "file://" + root.thumbDir + "/" + e.id + ".img" : "",
            glyph: e.isImage ? "\u{f02e9}" : "\u{f0219}",
            badge: ""
        }))

        onOpenChanged: {
            if (!open) return;
            query = "";
            root.refresh();
        }
        onActivated: index => {
            const e = shown[index];
            ShellState.close("clipboard");
            if (e) root.copy(e);
        }
        onRemoveRequested: index => {
            const e = shown[index];
            if (e) { picker.keepIndexOnce(); root.remove(e); }
        }
    }
}
