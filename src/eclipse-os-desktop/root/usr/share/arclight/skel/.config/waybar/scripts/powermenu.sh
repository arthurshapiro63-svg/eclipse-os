#!/usr/bin/env bash
# Midnight Blue power menu (wofi)
pkill -x wofi && exit 0

choice=$(printf '%s\n' "  Lock" "󰍃  Logout" "󰜉  Reboot" "⏻  Shutdown" |
  wofi --dmenu --prompt "power" --cache-file /dev/null \
       --width 220 --height 168 --location top_right --xoffset -26 --yoffset 8 \
       --style ~/.config/wofi/power.css)

case "$choice" in
  *Lock)     pidof hyprlock || hyprlock ;;
  *Logout)   hyprctl dispatch 'hl.dsp.exit()' ;;
  *Reboot)   systemctl reboot ;;
  *Shutdown) systemctl poweroff ;;
esac
