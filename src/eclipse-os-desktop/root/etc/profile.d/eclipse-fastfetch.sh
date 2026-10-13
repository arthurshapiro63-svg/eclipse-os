# Eclipse OS: the fastfetch logo is an image (Ghostty/kitty graphics). A text console cannot show images,
# so there it runs without a logo instead of falling back to ASCII art.
if [ "$TERM" = "linux" ]; then
    fastfetch() { command fastfetch --logo-type none "$@"; }
fi
