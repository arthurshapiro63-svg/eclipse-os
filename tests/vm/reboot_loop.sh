#!/bin/bash
# Reboot a VM N times and report systemd-vconsole-setup's state after each boot.  reboot_loop.sh NAME N
H=$(dirname "$(realpath "$0")"); n=$1; N=$2; fails=0
for i in $(seq "$N"); do
  "$H/vm.sh" exec "$n" 'systemctl reboot' >/dev/null 2>&1 || true
  sleep 8; "$H/vm.sh" wait "$n" 240 >/dev/null
  for j in $(seq 20); do "$H/vm.sh" exec "$n" 'pgrep -x Hyprland' >/dev/null 2>&1 && break; sleep 2; done
  sleep 12
  s=$("$H/vm.sh" exec "$n" 'systemctl is-active systemd-vconsole-setup; journalctl -b -u systemd-vconsole-setup --no-pager -q | grep -cE "failed|Input/output" ; systemctl show systemd-vconsole-setup -p NRestarts --value' 2>/dev/null | head -3 | tr '\n' ' ')
  echo "boot $i: state/eio-lines/restarts = $s"; case "$s" in failed*) fails=$((fails+1));; esac
done
echo "failed boots: $fails of $N"
