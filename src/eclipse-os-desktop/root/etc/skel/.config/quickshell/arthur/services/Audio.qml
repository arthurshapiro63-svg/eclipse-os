pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Services.Pipewire

// Default PipeWire sink/source. This box has one real sink (Ryzen analog stereo), so a
// volume UI is justified; `available` is false if no sink exists and every volume UI
// must hide itself then.
Singleton {
    id: root

    readonly property var sink: Pipewire.defaultAudioSink
    readonly property var source: Pipewire.defaultAudioSource
    readonly property bool available: !!sink && sink.ready && !!sink.audio
    readonly property real volume: available ? sink.audio.volume : 0
    readonly property bool muted: available ? sink.audio.muted : false
    readonly property bool micAvailable: !!source && source.ready && !!source.audio
    readonly property bool micMuted: micAvailable ? source.audio.muted : false
    readonly property string sinkName: available ? (sink.nickname || sink.description || sink.name) : ""

    function setVolume(v) { if (available) { sink.audio.muted = false; sink.audio.volume = Math.max(0, Math.min(1.0, v)); } }
    function nudge(delta) { setVolume(volume + delta); }
    function toggleMute() { if (available) sink.audio.muted = !sink.audio.muted; }
    function toggleMicMute() { if (micAvailable) source.audio.muted = !source.audio.muted; }

    // Binding the nodes keeps their audio properties live.
    PwObjectTracker { objects: [root.sink, root.source].filter(n => !!n) }
}
