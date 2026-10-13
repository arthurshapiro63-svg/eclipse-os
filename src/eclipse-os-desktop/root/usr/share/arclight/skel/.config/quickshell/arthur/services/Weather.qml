pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.common

// Current weather for the bar (agent A). Open-Meteo, FIXED location from settings
// (Config.bar.weatherLat/Lon/Place). No IP geolocation, no API key.
// Fetched with curl every 20 min while wanted and not GameMode.quiet (plus one first fetch).
Singleton {
    id: root

    property bool wanted: false
    readonly property bool enabled: wanted && Config.bar.showWeather
    readonly property bool running: enabled && !GameMode.quiet

    property bool ready: false
    property real temp: 0
    property int code: -1
    property bool isDay: true
    property double fetchedAt: 0          // ms epoch of the last good fetch
    readonly property string place: Config.bar.weatherPlace
    readonly property string unit: Config.bar.celsius ? "°C" : "°F"
    readonly property string tempText: ready ? Math.round(temp) + "°" : "--°"
    readonly property int refreshMs: 20 * 60 * 1000

    // Nerd Font Material weather glyphs (md-weather-*) by WMO weather code
    readonly property string icon: {
        const c = root.code, d = root.isDay;
        if (c < 0) return "\u{f0590}";                                     // no data yet: cloud (muted)
        if (c === 0) return d ? "\u{f0599}" : "\u{f0594}";                // sunny / night
        if (c <= 2) return d ? "\u{f0595}" : "\u{f0f31}";                 // partly cloudy
        if (c === 3) return "\u{f0590}";                                   // cloudy
        if (c === 45 || c === 48) return "\u{f0591}";                      // fog
        if (c >= 51 && c <= 57) return "\u{f0597}";                        // drizzle: rainy
        if (c >= 61 && c <= 67) return c >= 65 ? "\u{f0596}" : "\u{f0597}"; // rain / heavy rain
        if (c >= 80 && c <= 82) return "\u{f0596}";                        // showers: pouring
        if ((c >= 71 && c <= 77) || c === 85 || c === 86) return "\u{f0598}"; // snow
        if (c >= 95) return "\u{f067e}";                                   // thunderstorm
        return "\u{f0590}";
    }
    readonly property string description: {
        const c = root.code;
        if (c < 0) return "No data";
        if (c === 0) return "Clear";
        if (c <= 2) return "Partly cloudy";
        if (c === 3) return "Cloudy";
        if (c === 45 || c === 48) return "Fog";
        if (c >= 51 && c <= 57) return "Drizzle";
        if (c >= 61 && c <= 67) return "Rain";
        if (c >= 71 && c <= 77) return "Snow";
        if (c >= 80 && c <= 82) return "Showers";
        if (c === 85 || c === 86) return "Snow showers";
        if (c >= 95) return "Thunderstorm";
        return "Weather";
    }

    function refresh() {
        if (!root.enabled || proc.running) return;
        const url = "https://api.open-meteo.com/v1/forecast?latitude=" + Config.bar.weatherLat.toFixed(4)
            + "&longitude=" + Config.bar.weatherLon.toFixed(4)
            + "&current=temperature_2m,weather_code,is_day"
            + (Config.bar.celsius ? "" : "&temperature_unit=fahrenheit");
        proc.command = ["curl", "-sf", "--max-time", "15", url];
        proc.running = true;
    }
    function _refreshIfStale() {
        if (root.running && Date.now() - root.fetchedAt >= root.refreshMs - 1000) root.refresh();
    }

    Process {
        id: proc
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const cur = JSON.parse(text).current;
                    if (!cur || cur.temperature_2m === undefined) return;
                    root.temp = cur.temperature_2m;
                    root.code = cur.weather_code;
                    root.isDay = cur.is_day !== 0;
                    root.ready = true;
                    root.fetchedAt = Date.now();
                } catch (e) { /* offline or bad reply: keep the last value, retry next tick */ }
            }
        }
    }

    Timer {
        interval: root.refreshMs
        repeat: true
        running: root.running
        onTriggered: root.refresh()
    }
    // No data yet (offline at start): retry every 2 min until the first good fetch.
    Timer {
        interval: 120000
        repeat: true
        running: root.running && !root.ready
        onTriggered: root.refresh()
    }
    // Resume after a game / fullscreen, first use, or a location/unit change.
    onRunningChanged: _refreshIfStale()
    // One fetch at first use even during a game (a single curl, then nothing until quiet ends),
    // so the bar never sits on "--" for a whole session.
    onEnabledChanged: if (enabled && !ready) refresh()
    Connections {
        target: Config.bar
        function onWeatherLatChanged() { root.fetchedAt = 0; root._refreshIfStale(); }
        function onWeatherLonChanged() { root.fetchedAt = 0; root._refreshIfStale(); }
        function onCelsiusChanged() { root.fetchedAt = 0; root._refreshIfStale(); }
    }
}
