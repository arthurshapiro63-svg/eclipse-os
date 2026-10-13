#!/bin/bash
# Repack the arclight packages for the public ISO:
#  - installer: drop the personal machine manifest, keep a generic services list
#  - desktop + installer: swap in the car-free images from assets/
# Usage: tools/repack.sh SRC_PKG_DIR OUT_REPO_DIR
set -euo pipefail
SRC=$(realpath "$1"); OUT=$(realpath -m "$2"); ROOT=$(realpath "$(dirname "$0")/..")
A=$ROOT/assets
mkdir -p "$OUT"

repack() {   # name, then a function that edits $W/tree
    local name=$1 edit=$2 W
    W=$(mktemp -d -p /var/tmp)
    mkdir "$W/tree"
    bsdtar -xf "$SRC/$name"-0.1.0-1-any.pkg.tar.zst -C "$W/tree"
    local pkginfo=$W/tree/.PKGINFO
    local desc deps optdeps
    desc=$(sed -n 's/^pkgdesc = //p' "$pkginfo")
    deps=$(sed -n 's/^depend = //p' "$pkginfo" | sed "s/.*/'&'/" | tr '\n' ' ')
    optdeps=$(sed -n 's/^optdepend = //p' "$pkginfo" | sed "s/.*/'&'/" | tr '\n' ' ')
    rm -f "$W"/tree/.{BUILDINFO,MTREE,PKGINFO}
    [ -f "$W/tree/.INSTALL" ] && mv "$W/tree/.INSTALL" "$W/$name.install"
    "$edit" "$W/tree"
    {
        echo "pkgname=$name"; echo "pkgver=0.1.0"; echo "pkgrel=2"
        printf 'pkgdesc=%q\n' "$desc"
        echo "arch=('any')"; echo "license=('MIT')"
        echo "depends=($deps)"; echo "optdepends=($optdeps)"
        [ -f "$W/$name.install" ] && echo "install=$name.install"
        echo "options=('!strip' '!debug')"
        echo "package() { cp -a '$W/tree/.' \"\$pkgdir/\"; }"
    } > "$W/PKGBUILD"
    (cd "$W" && PKGDEST=$OUT makepkg -f --nodeps >/dev/null)
    rm -rf "$W"
}

edit_installer() {
    local t=$1 m=$1/usr/share/arclight/manifest
    rm -f "$m"/MANIFEST.md "$m"/packages-explicit-*.txt "$m"/services-user-enabled.txt
    printf '%s\n' NetworkManager.service bluetooth.service power-profiles-daemon.service > "$m/services-system-enabled.txt"
    cp "$A/grub-background.png" "$t/usr/share/arclight/grub/theme/background.png"
}

edit_desktop() {
    local t=$1 f
    for f in usr/share/arclight/wallpapers usr/share/backgrounds/arclight \
             usr/share/arclight/skel/Pictures/wallpapers etc/skel/Pictures/wallpapers; do
        [ -d "$t/$f" ] && cp "$A/arclight-eclipse.jpg" "$t/$f/arclight-eclipse.jpg"
    done
    cp "$A/lock.jpg" "$A/hero-wide.jpg" "$t/usr/share/arclight/eclipse/"
    cp "$A/grub-background.png" "$t/usr/share/grub/themes/arclight/background.png"
    for f in "$A"/intro-*.jpg; do [ -f "$f" ] && cp "$f" "$t/usr/share/arclight/eclipse/"; done
    return 0
}

rm -f "$OUT"/arclight-{installer,desktop}-*.pkg.tar.zst
repack arclight-installer edit_installer
repack arclight-desktop edit_desktop
cp "$SRC"/{arclight-core,hyprland-plugin-hyprbars,phinger-cursors,yay-bin}-[0-9]*.pkg.tar.zst "$OUT/"
rm -f "$OUT"/eclipse.{db,files}*
(cd "$OUT" && repo-add -q eclipse.db.tar.gz ./*.pkg.tar.zst)
echo "repo ready: $OUT"
