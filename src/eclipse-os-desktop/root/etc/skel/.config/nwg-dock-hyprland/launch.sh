#!/usr/bin/env bash
# Midnight Blue dock: pinned kitty / thunar / firefox / discord, centred at the bottom
printf '%s\n' kitty thunar firefox dev.arthur.ArchAI > "$HOME/.cache/nwg-dock-pinned"
pkill -f '^nwg-dock-hyprland'
sleep 0.3
exec nwg-dock-hyprland -p bottom -a center -i 40 -mb 10 -x -nolauncher \
    -iw special -s style.css
