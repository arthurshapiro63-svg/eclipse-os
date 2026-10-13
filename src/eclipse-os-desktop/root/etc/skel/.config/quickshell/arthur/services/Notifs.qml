pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Notifications
import qs.common

// Notification daemon + history (owner: agent C).
//   history      newest first, plain objects, persisted to statePath("notifications.json"),
//                capped at Config.notifications.historyLimit
//   popups       ListModel of { key } the popup stack shows (Notifications.qml)
//   unreadCount  for the bar badge; markAllRead() when the side panel opens
//   dnd          Config.notifications.dnd: record, no popups (critical still pops)
// While another daemon (DMS) owns org.freedesktop.Notifications the server is simply not
// created: one log line, then a quiet re-check every 60 s until the name is free.
Singleton {
    id: root

    readonly property bool dnd: Config.notifications.dnd
    readonly property bool serving: serverLoader.active
    property string busOwner: ""                 // who owns the bus name while we cannot serve
    readonly property var history: store.items || []
    readonly property int unreadCount: history.reduce((n, e) => n + (e.read ? 0 : 1), 0)
    readonly property alias popups: popupModel
    readonly property bool sounds: true          // TODO(handoff): Config.notifications.sounds

    property bool _canServe: false
    property bool _loggedTaken: false
    property int _seq: 0
    // key -> { notif, entry } for notifications that are still alive on the bus
    property var _live: ({})

    function setDnd(on) { Config.notifications.dnd = on; }

    function entry(key) {
        const l = _live[key];
        if (l) return l.entry;
        return history.find(e => e.key === key) ?? null;
    }
    function liveNotif(key) { const l = _live[key]; return l ? l.notif : null; }

    // Entries newer than this were unread when the panel last opened (history shows a dot).
    property real newSince: 0
    function markAllRead() {
        if (unreadCount === 0) return;
        _commit(history.map(e => e.read ? e : Object.assign({}, e, { read: true })));
    }

    // The bar bell reads ShellState.notifUnread; this service is its only writer.
    Binding { target: ShellState; property: "notifUnread"; value: root.unreadCount }
    Connections {
        target: ShellState
        function onPanelOpenChanged() {
            if (!ShellState.panelOpen) return;
            const unread = root.history.filter(e => !e.read);
            root.newSince = unread.length > 0 ? Math.min.apply(null, unread.map(e => e.time)) : Date.now();
            root.markAllRead();
        }
    }

    // Click on a popup/history row: default action if there is one.
    function activate(key) {
        const n = liveNotif(key);
        if (n) {
            const def = n.actions.find(a => a.identifier === "default");
            if (def) { def.invoke(); return true; }
        }
        return false;
    }
    function invokeAction(key, identifier) {
        const n = liveNotif(key);
        if (!n) return;
        const a = n.actions.find(x => x.identifier === identifier);
        if (a) a.invoke();
    }

    // Close button on a popup: hide it, keep it in history.
    function hidePopup(key) {
        for (let i = 0; i < popupModel.count; i++)
            if (popupModel.get(i).key === key) { popupModel.remove(i); return; }
    }
    // Remove from history (and tell the app it was dismissed).
    function dismiss(key) {
        hidePopup(key);
        const n = liveNotif(key);
        _forget(key);
        if (n) n.dismiss();
        _commit(history.filter(e => e.key !== key));
    }
    function dismissApp(appName) {
        history.filter(e => e.appName === appName).forEach(e => dismiss(e.key));
    }
    function clearAll() {
        popupModel.clear();
        const keys = Object.keys(_live);
        keys.forEach(k => { const n = _live[k].notif; _forget(k); if (n) n.dismiss(); });
        _commit([]);
    }

    // Test/dev hook (IPC "notifs test"): a local entry without a bus notification behind it.
    function inject(appName, summary, body, urgency) {
        const key = Date.now() + "-" + (++_seq);
        const e = { key: key, appName: appName || "arthur-shell", appIcon: "", summary: summary || "", body: body || "",
                    image: "", urgency: urgency, time: Date.now(), read: ShellState.panelOpen };
        _commit([e].concat(history));
        if (GameMode.quiet || (dnd && urgency !== 2)) return;
        popupModel.insert(0, { key: key, stamp: _seq });
        while (popupModel.count > 5) popupModel.remove(popupModel.count - 1);
    }

    // ---- internals ----
    function _forget(key) {
        if (!_live[key]) return;
        const m = Object.assign({}, _live);
        delete m[key];
        _live = m;
    }
    function _commit(list) {
        const cap = Math.max(1, Config.notifications.historyLimit);
        if (list.length > cap) {
            list.slice(cap).forEach(e => { const n = liveNotif(e.key); _forget(e.key); if (n) n.dismiss(); });
            list = list.slice(0, cap);
        }
        store.items = list;          // JsonAdapter change -> onAdapterUpdated -> writeAdapter
    }
    function _persistableImage(img) {
        if (!img) return "";
        if (img.startsWith("/")) return "file://" + img;
        if (img.startsWith("file://")) return img;
        return "";                  // image://qsimage/... only lives while the notification does
    }
    function _entryFor(n, key, time) {
        return {
            key: key,
            appName: n.appName || "Notification",
            appIcon: n.appIcon || n.desktopEntry || "",
            summary: n.summary || "",
            body: n.body || "",
            image: _persistableImage(n.image),
            urgency: n.urgency === NotificationUrgency.Critical ? 2 : n.urgency === NotificationUrgency.Low ? 0 : 1,
            time: time,
            read: ShellState.panelOpen
        };
    }
    function _keyOf(n) {
        for (const k in _live) if (_live[k].notif === n) return k;
        return "";
    }
    function _onNotification(n) {
        n.tracked = true;
        let key = _keyOf(n);            // replaces_id: same object comes back with new content
        const fresh = key === "";
        if (fresh) key = Date.now() + "-" + (++_seq);
        const e = _entryFor(n, key, Date.now());
        const m = Object.assign({}, _live);
        m[key] = { notif: n, entry: e };
        _live = m;
        if (fresh) n.closed.connect(() => {
            root.hidePopup(key);
            root._forget(key);
        });
        const rest = history.filter(x => x.key !== key);
        _commit([e].concat(rest));

        const critical = e.urgency === 2;
        const allowed = !GameMode.quiet && (!dnd || critical);
        if (!allowed) return;
        if (fresh && sounds && e.urgency !== 0)
            Quickshell.execDetached(["pw-play", "/usr/share/sounds/freedesktop/stereo/message.oga"]);
        if (fresh) popupModel.insert(0, { key: key, stamp: _seq });
        else {
            let found = false;
            for (let i = 0; i < popupModel.count; i++)
                if (popupModel.get(i).key === key) { popupModel.setProperty(i, "stamp", ++_seq); found = true; }
            if (!found) popupModel.insert(0, { key: key, stamp: _seq });
        }
        while (popupModel.count > 5) popupModel.remove(popupModel.count - 1);
    }

    ListModel { id: popupModel }

    // ---- bus ownership check (no warning spam while DMS runs) ----
    Process {
        id: ownerCheck
        // Prints "free", "self" (our own qs process, e.g. after a hot reload) or "taken <pid> <comm>".
        command: ["sh", "-c", "o=$(busctl --user call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus GetConnectionUnixProcessID s org.freedesktop.Notifications 2>/dev/null | awk '{print $2}'); if [ -z \"$o\" ]; then echo free; elif [ \"$o\" = \"$PPID\" ] || tr '\\0' ' ' < /proc/$o/cmdline 2>/dev/null | grep -Eq -- '-c arthur|quickshell/arthur'; then echo self; else echo \"taken $o $(cat /proc/$o/comm 2>/dev/null)\"; fi"]
        stdout: StdioCollector {
            onStreamFinished: {
                const out = text.trim();
                if (out === "free" || out === "self") {
                    root.busOwner = "";
                    root._canServe = true;
                    console.info("Notifs: serving org.freedesktop.Notifications (" + out + ")");
                } else {
                    root.busOwner = out.replace(/^taken /, "");
                    if (!root._loggedTaken) {
                        root._loggedTaken = true;
                        console.info("Notifs: org.freedesktop.Notifications is owned by " + root.busOwner + "; history only, re-checking every 60 s");
                    }
                }
            }
        }
    }
    Timer {
        running: !root._canServe
        interval: 60000
        repeat: true
        onTriggered: ownerCheck.running = true
    }
    Component.onCompleted: ownerCheck.running = true

    LazyLoader {
        id: serverLoader
        active: root._canServe
        NotificationServer {
            keepOnReload: true
            persistenceSupported: true
            bodySupported: true
            bodyMarkupSupported: true
            bodyHyperlinksSupported: false
            bodyImagesSupported: false
            actionsSupported: true
            actionIconsSupported: false
            imageSupported: true
            inlineReplySupported: false
            onNotification: n => root._onNotification(n)
        }
    }

    // ---- history file ----
    FileView {
        id: file
        path: Quickshell.statePath("notifications.json")
        printErrors: false
        onAdapterUpdated: writeAdapter()
        // first run: the state dir may not exist yet -> mkdir, then write the empty history
        onLoadFailed: error => { if (error === FileViewError.FileNotFound) mkdir.running = true; }
        JsonAdapter {
            id: store
            property var items: []
        }
    }
    Process {
        id: mkdir
        command: ["mkdir", "-p", Quickshell.statePath("")]
        onExited: file.writeAdapter()
    }
}
