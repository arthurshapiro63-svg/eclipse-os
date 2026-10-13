# Eclipse OS

My own spin on Arch Linux. It's built around Hyprland, a dark gold theme, and an AI that can actually control the computer: change settings, install stuff, fix things, open apps.

![Welcome screen](screenshots/welcome.jpg)

## What's in it

The thing I like most is Totality. Press Super+G and everything except the window you're using fades out, the moon covers the sun, and the other apps get paused so games and big jobs get the whole PC. Press it again and it all comes back.

![Totality](screenshots/totality.jpg)

You can ask the AI for stuff in plain words, like "make the dock icons bigger" (Super+Shift+A).

![Ask](screenshots/ask.jpg)

There's also an app store for games and apps, and a settings app with six themes.

![Store](screenshots/store.jpg)
![Settings](screenshots/settings.jpg)
![Terminal](screenshots/terminal.jpg)

## Installing

1. Grab the ISO from [Releases](../../releases).
2. Flash it to a USB stick (4 GB or more). I use [Ventoy](https://www.ventoy.net) but [balenaEtcher](https://etcher.balena.io) works too.
3. Boot from the USB. It goes straight to the desktop.
4. Click "Install it". It can go next to your current system or on its own drive.

The AI part needs an AI agent like Claude Code. It isn't on the ISO, so you install it yourself after.

## Keys

| Key | What it does |
|---|---|
| Super+G | Totality on/off |
| Super+Space | App launcher |
| Super+Shift+A | Ask the AI |
| Super+I | Settings |

## Building the ISO yourself

You need Arch with `archiso` installed.

```
tools/build-iso.sh
```

The ISO ends up in `out/`. The packages it uses are in `repo/`, and the archiso setup is in `profile/`. `tools/repack.sh` is how I made the packages in `repo/` from my own builds.
