#!/bin/bash
# Build the Eclipse OS packages from src/ and refresh the [eclipse] repo that the ISO installs from.
# The third-party packages in the repo (yay-bin, hyprland-plugin-hyprbars, phinger-cursors) are
# upstream builds and are kept as they are; see "Third-party software" in README.md.
# Usage: tools/repack.sh [OUT_REPO_DIR]   (default: repo/)
set -euo pipefail
ROOT=$(realpath "$(dirname "$0")/..")
OUT=$(realpath -m "${1:-$ROOT/repo}")
mkdir -p "$OUT"

rm -f "$OUT"/{arclight,eclipse-os}-{core,desktop,installer}-[0-9]*.pkg.tar.zst
for d in "$ROOT"/src/eclipse-os-*/; do
    W=$(mktemp -d -p /var/tmp)
    (cd "$d" && BUILDDIR=$W PKGDEST=$OUT makepkg -f --nodeps --noconfirm >"$W/build.log" 2>&1) \
        || { tail -20 "$W/build.log"; rm -rf "$W"; exit 1; }
    rm -rf "$W"
done
rm -f "$OUT"/eclipse.{db,files}*
(cd "$OUT" && repo-add -q eclipse.db.tar.gz ./*.pkg.tar.zst)
echo "repo ready: $OUT"
