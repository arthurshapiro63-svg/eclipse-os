#!/bin/bash
# The Rite (advanced install), unattended: `rite auto all` on a blank virtual disk with scripted answers.
#   rite_test.sh ISO NAME     -> prints each stage's result; needs network in the VM for pacstrap
set -euo pipefail
H=$(dirname "$(realpath "$0")"); iso=$1; n=$2
VMDIR=${VMDIR:-/var/tmp/eclipse-vmtest}; d=$VMDIR/$n
"$H/vm.sh" stop "$n" >/dev/null; rm -rf "$d"; mkdir -p "$d"
qemu-img create -q -f qcow2 "$d/disk.qcow2" 40G
"$H/vm.sh" start "$n" --iso "$iso" --disk "$d/disk.qcow2" >/dev/null
"$H/vm.sh" wait "$n" 300 >/dev/null
ex() { "$H/vm.sh" exec "$n" "$@"; }
ex 'test -f /etc/arclight-rite/pacman.conf && echo "pacman.conf present"; pacman --config /etc/arclight-rite/pacman.conf -Sy >/dev/null 2>&1; pacman --config /etc/arclight-rite/pacman.conf -Si eclipse-os-core | grep -E "^(Repository|Version)"'
# answers: Enter (run stage 0), disk number, disk confirmation; everything else takes the guide's defaults (stdin is not a tty)
ex 'setsid nohup bash -c "printf \"\n1\n/dev/vda\n\" | RITE_LUKS=Synthetic-Luks-01 RITE_USER=Synthetic-User-01 rite auto all > /root/rite.out 2>&1; echo DONE \$? >> /root/rite.out" >/dev/null 2>&1 &' >/dev/null
for i in $(seq 360); do ex 'tail -1 /root/rite.out' 2>/dev/null | grep -q '^DONE' && break; sleep 5; done
ex 'sed -E "s/\x1b\[[0-9;]*m//g" /root/rite.out | grep -E "Stage [0-9]+|passed|PASS|FAIL|failed|✓|✗|DONE|Ready|All stages" | tail -60; echo; rite status 2>/dev/null | sed -E "s/\x1b\[[0-9;]*m//g" | tail -20; echo; grep -q "^DONE 0" /root/rite.out && grep -q Ready /root/rite.out && ! findmnt /mnt >/dev/null && echo "RITE COMPLETE (disk unmounted and closed)"' 120
