#!/bin/bash
# Boot an ISO and report how long the "Eclipse OS live user" unit took, and when Hyprland started.
#   live_setup_timing.sh ISO NAME
set -euo pipefail
H=$(dirname "$(realpath "$0")"); iso=$1; n=$2
"$H/vm.sh" stop "$n" >/dev/null; rm -rf "${VMDIR:-/var/tmp/eclipse-vmtest}/$n"
"$H/vm.sh" start "$n" --iso "$iso" >/dev/null
"$H/vm.sh" wait "$n" 300 >/dev/null
for i in $(seq 120); do
    s=$("$H/vm.sh" exec "$n" 'systemctl is-active arclight-live-setup' 2>/dev/null | head -1 || true)
    [ "$s" = active ] && break; sleep 3
done
"$H/vm.sh" exec "$n" '
a=$(systemctl show arclight-live-setup -p ExecMainStartTimestampMonotonic --value)
b=$(systemctl show arclight-live-setup -p ActiveEnterTimestampMonotonic --value)
echo "live-setup took $(( (b - a) / 1000 )) ms"
journalctl -b -u arclight-live-setup -o short-monotonic --no-pager | grep -E "Starting|pam_systemd|Finished"
for i in $(seq 60); do pgrep -x Hyprland >/dev/null && break; sleep 1; done
echo "Hyprland started at $(ps -o etimes= -p 1 | tr -d " ")s - $(ps -o etimes= -p $(pgrep -x Hyprland) | tr -d " ")s after boot = $(( $(ps -o etimes= -p 1) - $(ps -o etimes= -p $(pgrep -x Hyprland)) ))s"
' 120
