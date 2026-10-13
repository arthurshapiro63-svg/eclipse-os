pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.common

// Apps: desktop-entry lookup + running-app grouping (owner: dock; launcher may read it).
//
// Every app is identified by a KEY: the lowercase desktop-entry id when one can be resolved,
// else the lowercase window class. A pinned id ("zen") and a window class ("zen",
// "com.mitchellh.ghostty", "Thunar") land on the same key, so "is this pinned app open"
// is plain key equality.
//   entryFor(id)    DesktopEntry or null (byId, then heuristicLookup)
//   keyFor(id)      grouping key
//   running         [{ key, appId, windows: [Toplevel] }] in first-seen order
//   windowsFor(key) Toplevels of that app
//   iconFor(id) / nameFor(id)
//   activate(key)   focus the app; cycles windows when one of them is already active
//   launch(id)      DesktopEntry.execute()
//   closeAll(key)   Toplevel.close() on every window
//   isPinned(id) / pin(id) / unpin(id)   edit Config.dock.pinned (persists to settings.json)
Singleton {
    id: root

    readonly property var toplevels: ToplevelManager.toplevels.values
    readonly property var activeToplevel: ToplevelManager.activeToplevel
    // Read so every lookup re-evaluates once desktop entries finish (re)scanning.
    readonly property var _apps: DesktopEntries.applications.values

    function entryFor(id) {
        if (!id) return null;
        // Steam games: window class steam_app_<n>, desktop file runs steam://rungameid/<n>
        const game = /^steam_app_(\d+)$/.exec(id);
        if (game) {
            const needle = "rungameid/" + game[1];
            return root._apps.find(e => (e.execString || "").indexOf(needle) >= 0) ?? null;
        }
        void root._apps;
        return DesktopEntries.byId(id) ?? DesktopEntries.heuristicLookup(id) ?? null;
    }

    function keyFor(id) {
        if (!id) return "";
        const e = entryFor(id);
        return ((e && e.id) ? e.id : id).toLowerCase();
    }

    readonly property var running: {
        const groups = [];
        const index = {};
        for (const t of root.toplevels) {
            if (!t || !t.appId) continue;
            const key = root.keyFor(t.appId);
            if (index[key] === undefined) {
                index[key] = groups.length;
                groups.push({ key: key, appId: t.appId, windows: [] });
            }
            groups[index[key]].windows.push(t);
        }
        return groups;
    }

    function windowsFor(key) {
        const g = root.running.find(g => g.key === key);
        return g ? g.windows : [];
    }

    function nameFor(id) {
        const e = entryFor(id);
        return (e && e.name) ? e.name : (id || "");
    }

    function iconFor(id) {
        if (!id) return "";
        const e = entryFor(id);
        const tries = [];
        if (e && e.icon) tries.push(e.icon);
        tries.push(id, id.toLowerCase());
        const last = id.split(".").pop();
        if (last && last !== id) tries.push(last, last.toLowerCase());
        for (const name of tries) {
            if (name.startsWith("/")) return "file://" + name;
            const p = Quickshell.iconPath(name, true);
            if (p) return p;
        }
        return Quickshell.iconPath("application-x-executable", true) || "";
    }

    function activate(key) {
        const wins = windowsFor(key);
        if (wins.length === 0) return false;
        const cur = wins.findIndex(t => t.activated);
        const next = wins[cur < 0 ? 0 : (cur + 1) % wins.length];
        next.activate();
        return true;
    }

    function launch(id) {
        const e = entryFor(id);
        if (!e) return false;
        e.execute();
        return true;
    }

    function closeAll(key) {
        for (const t of windowsFor(key).slice()) t.close();
    }

    function pinnedIds() { return Array.from(Config.dock.pinned || []); }
    function isPinned(id) {
        const k = keyFor(id);
        return pinnedIds().some(p => keyFor(p) === k);
    }
    function pin(id) {
        if (!id || isPinned(id)) return;
        const e = entryFor(id);
        Config.dock.pinned = pinnedIds().concat([(e && e.id) ? e.id : id]);
    }
    function unpin(id) {
        const k = keyFor(id);
        Config.dock.pinned = pinnedIds().filter(p => keyFor(p) !== k);
    }
}
