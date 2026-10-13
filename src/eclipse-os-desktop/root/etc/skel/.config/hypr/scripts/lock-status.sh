#!/bin/sh
# Status row for hyprlock: battery (only if one exists) + wifi. Pango-escaped.
esc() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }
out=""
for b in /sys/class/power_supply/BAT*; do
    [ -r "$b/capacity" ] || continue
    cap=$(cat "$b/capacity"); st=$(cat "$b/status" 2>/dev/null)
    icon="󰁹"; [ "$st" = "Charging" ] && icon="󰂄"
    out="$icon $cap%     "
    break
done
# 'connection show --active' is instant; 'dev wifi' can take ~4s (scan cache)
active=$(nmcli -t -f TYPE,NAME connection show --active 2>/dev/null | grep -v '^loopback:')
ssid=$(printf '%s\n' "$active" | awk -F: '$1=="802-11-wireless"{sub(/^[^:]*:/,""); print; exit}')
if [ -n "$ssid" ]; then
    out="${out}󰖩  $(esc "$ssid")"
elif printf '%s' "$active" | grep -q '^802-3-ethernet:'; then
    out="${out}󰈀  wired"
else
    out="${out}󰖪  offline"
fi
printf '%s\n' "$out"
