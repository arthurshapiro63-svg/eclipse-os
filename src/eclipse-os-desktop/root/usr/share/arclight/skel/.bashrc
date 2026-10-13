#
# ~/.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='ls --color=auto'
alias cp='cp -i'
alias mv='mv -i'
alias rm='rm -i'
alias grep='grep --color=auto'
PS1='[\u@\h \W]\$ '

# Midnight Blue: fastfetch on every kitty launch
if [[ -n "$KITTY_WINDOW_ID" && "$FASTFETCH_SHOWN" != "$KITTY_PID-$KITTY_WINDOW_ID" ]] && command -v fastfetch >/dev/null; then
    export FASTFETCH_SHOWN="$KITTY_PID-$KITTY_WINDOW_ID"
    fastfetch
fi
PS1='\[\e[38;2;47;124;255m\]\u@\h \[\e[38;2;200;214;240m\]\W \[\e[38;2;47;124;255m\]>\[\e[0m\] '
export PATH="$HOME/.local/bin:$PATH"

# Sketchfab API token — read from file, never hardcoded.
if [ -r "$HOME/.config/sketchfab/token" ]; then
    export SKETCHFAB_TOKEN="$(cat "$HOME/.config/sketchfab/token")"
fi

# Midnight Blue: Starship prompt (config: ~/.config/starship.toml).
# Must stay last so it wins over the PS1 lines above.
if command -v starship >/dev/null; then
    eval "$(starship init bash)"
fi

# >>> glass-terminal: bat / fzf / eza (Midnight Blue glass pass, 2026-09-21) >>>
# Colours come from ~/.config/theme/tokens via theme-apply templates:
#   bat -> ~/.config/bat/themes/rice.tmTheme (+ ~/.config/bat/config)
#   eza -> ~/.config/eza/theme.yml      fzf -> ~/.config/fzf/fzfrc (read on every run)
if command -v eza >/dev/null; then
    alias ls='eza --icons=auto --group-directories-first'
    alias ll='eza -l --icons=auto --group-directories-first --git --time-style=relative'
    alias la='eza -la --icons=auto --group-directories-first --git --time-style=relative'
    alias lt='eza --tree --level=2 --icons=auto --group-directories-first'
fi
if command -v fzf >/dev/null; then
    export FZF_DEFAULT_OPTS_FILE="$HOME/.config/fzf/fzfrc"
    command -v fd >/dev/null && export FZF_DEFAULT_COMMAND='fd --type f --hidden --follow --exclude .git'
    command -v bat >/dev/null && export FZF_CTRL_T_OPTS="--preview 'bat --color=always --style=numbers --line-range=:300 {} 2>/dev/null'"
    command -v eza >/dev/null && export FZF_ALT_C_OPTS="--preview 'eza --tree --level=2 --icons=always --color=always {} | head -200'"
    # ctrl+r fuzzy history, ctrl+t file picker, alt+c cd picker
    eval "$(fzf --bash)"
fi
if command -v bat >/dev/null; then
    # man pages through bat, so they pick up the same theme
    export MANPAGER="sh -c 'col -bx | bat -l man -p'"
    export MANROFFOPT="-c"
fi
# <<< glass-terminal <<<
fastfetch

# opencode
export PATH=@HOME@/.opencode/bin:$PATH
