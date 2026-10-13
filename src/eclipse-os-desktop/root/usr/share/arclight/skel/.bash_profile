#
# ~/.bash_profile
#
[[ -f ~/.bashrc ]] && . ~/.bashrc

# Start Hyprland automatically after login on tty1
if [[ -z $WAYLAND_DISPLAY && $XDG_VTNR -eq 1 ]]; then
    ~/.local/bin/boot-hacker || true
    exec start-hyprland >/dev/null 2>&1   # its banner + debug log stay off the console (log: $XDG_RUNTIME_DIR/hypr)
fi
