pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Services.Mpris

// The MPRIS player the shell shows: the one playing, else the last one that was
// playing, else the first. `player` is null when nothing exposes MPRIS.
Singleton {
    id: root

    readonly property var players: Mpris.players.values
    property var _last: null
    readonly property var player: players.find(p => p.isPlaying) ?? (players.indexOf(_last) >= 0 ? _last : (players[0] ?? null))
    readonly property bool active: !!player
    readonly property bool playing: !!player && player.isPlaying
    readonly property string title: player ? (player.trackTitle || player.identity || "") : ""
    readonly property string artist: player ? (player.trackArtist || "") : ""
    readonly property string artUrl: player ? (player.trackArtUrl || "") : ""

    onPlayerChanged: if (player && player.isPlaying) _last = player
    function toggle() { if (player && player.canTogglePlaying) player.togglePlaying(); }
    function next() { if (player && player.canGoNext) player.next(); }
    function previous() { if (player && player.canGoPrevious) player.previous(); }
}
