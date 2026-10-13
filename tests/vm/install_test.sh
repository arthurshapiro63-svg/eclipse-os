#!/bin/bash
# End-to-end install test in a disposable VM (virtual disk only).
#   install_test.sh ISO erase|free-new-esp|free-existing-esp NAME
# erase:              wipe the virtual disk, install
# free-*:             the disk first gets an EFI partition (1, with a marker file) and a data partition (3, ext4,
#                     random data) with a gap at 2; the install goes into free space. Partitions 1 and 3 are hashed
#                     before and after; free-new-esp needs them byte-identical, free-existing-esp installs to the
#                     existing ESP (partition 1 must keep its filesystem UUID and marker file; 3 byte-identical).
# Then boots the installed system from the disk and checks it.
set -euo pipefail
H=$(dirname "$(realpath "$0")"); iso=$1; mode=$2; n=$3
VMDIR=${VMDIR:-/var/tmp/eclipse-vmtest}; d=$VMDIR/$n
"$H/vm.sh" stop "$n" >/dev/null; rm -rf "$d"; mkdir -p "$d"
qemu-img create -q -f qcow2 "$d/disk.qcow2" 48G
"$H/vm.sh" start "$n" --iso "$iso" --disk "$d/disk.qcow2" >/dev/null
"$H/vm.sh" wait "$n" 300 >/dev/null
ex() { "$H/vm.sh" exec "$n" "$@"; }
for i in $(seq 60); do [ "$(ex 'systemctl is-active arclight-live-setup' 2>/dev/null | head -1)" = active ] && break; sleep 3; done
esp_json=""
if [ "$mode" != erase ]; then
  ex 'set -e
    sgdisk --zap-all /dev/vda >/dev/null
    sgdisk -n 1:2048:+512M -t 1:ef00 -c 1:OLD-EFI -n 3:3147776:+4G -t 3:8300 -c 3:DATA /dev/vda >/dev/null
    partprobe /dev/vda; udevadm settle
    mkfs.fat -F 32 -n OLDEFI /dev/vda1 >/dev/null; mkfs.ext4 -q -L DATA /dev/vda3
    mkdir -p /tmp/m && mount /dev/vda1 /tmp/m && mkdir -p /tmp/m/EFI/OldOS && echo keep > /tmp/m/EFI/OldOS/marker && umount /tmp/m
    mount /dev/vda3 /tmp/m && head -c 64M /dev/urandom > /tmp/m/data.bin && sha256sum /tmp/m/data.bin > /root/data.sum && umount /tmp/m
    sync
    sfdisk --json /dev/vda > /root/table-before.json
    sha256sum /dev/vda1 /dev/vda3 > /root/parts-before.sum
    blkid -s UUID -o value /dev/vda1 > /root/esp-uuid-before
    lsblk -o NAME,SIZE,TYPE,FSTYPE,PARTLABEL /dev/vda' 120
  [ "$mode" = free-existing-esp ] && esp_json=', "esp": "/dev/vda1"'
fi
case $mode in erase) m='"mode": "erase", "confirm_disk": "/dev/vda"';; *) m='"mode": "free"';; esac
cat > "$d/plan.json" <<PLAN
{$m, "disk": "/dev/vda"$esp_json, "fingerprint": false, "os_name": "Eclipse OS", "hostname": "eclipse-test",
 "user": {"name": "tester", "full_name": "Tester", "autologin": true, "password": "Synthetic-Pw-0001"},
 "timezone": "UTC", "locale": "en_US.UTF-8", "keymap": "us"}
PLAN
"$H/vm.sh" push "$n" "$d/plan.json" /root/plan.json >/dev/null
ex 'setsid nohup bash -c "arclight-install --config /root/plan.json --yes > /root/install.out 2>&1; echo DONE \$? >> /root/install.out" >/dev/null 2>&1 &' >/dev/null
for i in $(seq 200); do ex 'tail -1 /root/install.out' 2>/dev/null | grep -q '^DONE' && break; sleep 5; done
ex 'tail -4 /root/install.out; grep -E "new partitions|existing partitions kept|old home" /var/log/arclight-install.log'
ex 'grep -q "^DONE 0" /root/install.out' >/dev/null || { echo "INSTALL FAILED"; ex 'tail -30 /var/log/arclight-install.log'; exit 1; }
ex 'echo "install log mode: $(stat -c %a /var/log/arclight-install.log)"; grep -c "Synthetic-Pw-0001" /var/log/arclight-install.log || true'
if [ "$mode" != erase ]; then
  ex 'set -e; sync
    sfdisk --json /dev/vda > /root/table-after.json
    python3 -c "
import json
b = {p[\"node\"]: p for p in json.load(open(\"/root/table-before.json\"))[\"partitiontable\"][\"partitions\"]}
a = {p[\"node\"]: p for p in json.load(open(\"/root/table-after.json\"))[\"partitiontable\"][\"partitions\"]}
for k, v in b.items(): assert a[k] == v, (k, v, a.get(k)); print(\"unchanged table entry\", k)
print(\"new:\", sorted(set(a) - set(b)))"
    echo "partition 3:"; sha256sum /dev/vda3 | diff <(grep vda3 /root/parts-before.sum) - && echo "  byte-identical"' 300
  if [ "$mode" = free-new-esp ]; then
    ex 'echo "partition 1:"; sha256sum /dev/vda1 | diff <(grep vda1 /root/parts-before.sum) - && echo "  byte-identical"' 300
  else
    ex 'echo "partition 1 (shared ESP): UUID $(blkid -s UUID -o value /dev/vda1) (before $(cat /root/esp-uuid-before))"
        [ "$(blkid -s UUID -o value /dev/vda1)" = "$(cat /root/esp-uuid-before)" ]
        mount /dev/vda1 /tmp/m && cat /tmp/m/EFI/OldOS/marker && ls /tmp/m/EFI && umount /tmp/m' 60
  fi
fi
"$H/vm.sh" stop "$n" >/dev/null
"$H/vm.sh" start "$n" --disk "$d/disk.qcow2" >/dev/null
"$H/vm.sh" wait "$n" 300 >/dev/null
for i in $(seq 40); do ex 'pgrep -x Hyprland' >/dev/null 2>&1 && break; sleep 3; done
sleep 8
"$H/vm.sh" shot "$n" "${SHOTS:-$d}/$n-installed.png" >/dev/null
ex 'echo "booted: $(grep PRETTY /etc/os-release) on $(findmnt -no SOURCE /)"
    echo "vconsole-setup: $(systemctl is-active systemd-vconsole-setup)  $(cat /etc/vconsole.conf | tr "\n" " ")"
    systemctl --failed --no-legend
    echo "Hyprland: $(pgrep -x Hyprland >/dev/null && echo running || echo NOT running)"
    echo "repo removed: $(test -e /opt/eclipse-repo && echo NO || echo yes)"
    pacman -Q eclipse-os-core eclipse-os-desktop eclipse-os-installer terminus-font | tr "\n" " "; echo
    ls -l /var/log/arclight/ 2>/dev/null | tail -n +2'
