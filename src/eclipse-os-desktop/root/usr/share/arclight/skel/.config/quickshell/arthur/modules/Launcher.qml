pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.common
import qs.services
import qs.modules.launcher
import "../services/Fuzzy.js" as Fuzzy

// App launcher (SUPER+space -> shellctl -> ipc launcher toggle). Fuzzy search over
// name, keywords, generic name, exec and comment (services/Fuzzy.js), with a frecency
// boost from launch counts kept in Quickshell.statePath("launcher-usage.json").
Scope {
    id: root

    property var usage: ({})                 // { desktopId: { count, last } }
    property var items: []                   // plain JS objects, built from DesktopEntries
    property bool itemsDirty: true

    readonly property var entries: DesktopEntries.applications.values
    onEntriesChanged: { itemsDirty = true; if (ShellState.launcherOpen) rebuild(); }

    function rebuild() {
        const out = [];
        const list = root.entries;
        for (let i = 0; i < list.length; i++) {
            const e = list[i];
            if (!e || e.noDisplay) continue;
            out.push({
                id: e.id, name: e.name || e.id, genericName: e.genericName || "",
                keywords: Array.from(e.keywords || []), comment: e.comment || "",
                exec: e.execString || "", icon: e.icon || "", entry: e
            });
        }
        items = out;
        itemsDirty = false;
    }

    function launch(item) {
        if (!item) return;
        const e = item.entry;
        if (e.runInTerminal)
            Quickshell.execDetached(["ghostty", "-e"].concat(Array.from(e.command)));
        else
            e.execute();
        const u = Object.assign({}, root.usage);
        const prev = u[item.id] || { count: 0, last: 0 };
        u[item.id] = { count: prev.count + 1, last: Date.now() };
        root.usage = u;
        usageFile.setText(JSON.stringify(u));
    }

    FileView {
        id: usageFile
        path: Quickshell.statePath("launcher-usage.json")
        printErrors: false
        onLoaded: {
            try { root.usage = JSON.parse(text()) || {}; }
            catch (e) { root.usage = {}; }
        }
    }

    PickerSurface {
        id: picker
        surface: "launcher"
        open: ShellState.launcherOpen
        placeholder: "Search apps"
        searchGlyph: "\u{f0349}"
        hint: "↵ open   ↑↓ move   esc close"
        emptyText: "No app found"
        maxRows: Config.launcher.maxResults

        // Drop weak tail matches (below 35% of the best score) so the list stays short and clear.
        readonly property var ranked: {
            if (!open) return [];
            const r = Fuzzy.rank(query, root.items, root.usage, Config.launcher.maxResults);
            if (query.trim().length === 0 || r.length === 0) return r;
            const cut = r[0].score * 0.35;
            return r.filter(x => x.score >= cut);
        }
        rows: ranked.map(r => ({
            title: r.entry.name,
            subtitle: r.entry.genericName || r.entry.comment,
            icon: r.entry.icon ? Quickshell.iconPath(r.entry.icon, true) : "",
            glyph: "\u{f08c6}"
        }))

        onOpenChanged: {
            if (!open) return;
            if (root.itemsDirty) root.rebuild();
            query = ShellState.launcherQuery;
            selectAllLater.restart();
        }
        onActivated: index => {
            const r = ranked[index];
            ShellState.close("launcher");
            if (r) root.launch(r.entry);
        }

        // the pre-filled query is selected, so typing replaces it
        Timer { id: selectAllLater; interval: 0; onTriggered: picker.selectQuery() }
    }
}
