#!/bin/bash
# Build the Eclipse OS ISO into out/. Needs archiso and root.
set -euo pipefail
ROOT=$(realpath "$(dirname "$0")/..")
W=$(mktemp -d -p /var/tmp eclipse-profile.XXXX)
cp -r "$ROOT/profile/." "$W/"
sed -i "s|@REPO@|$ROOT/repo|" "$W/pacman.conf"
sudo rm -rf /var/tmp/eclipse-iso-work   # a work dir left by a failed build makes mkarchiso skip steps and reuse old packages
sudo mkarchiso -v -r -w /var/tmp/eclipse-iso-work -o "$ROOT/out" "$W"
rm -rf "$W"
sudo chown -R "$(id -u):$(id -g)" "$ROOT/out"
cd "$ROOT/out" && sha256sum eclipse-os-*.iso > "$(ls eclipse-os-*.iso | tail -1).sha256"
