#!/bin/bash
# Disposable QEMU VMs for the Eclipse OS tests. Everything lives in $VMDIR (default /var/tmp/eclipse-vmtest);
# only virtual disk images are ever written.
#   vm.sh start NAME [--iso ISO] [--disk FILE]... [--bios]   boot (ISO first when given), guest agent + monitor
#   vm.sh stop NAME
#   vm.sh exec NAME 'cmd' [timeout]       run as root in the guest (needs qemu-guest-agent in the guest)
#   vm.sh push NAME LOCAL REMOTE | pull NAME REMOTE LOCAL | wait NAME [timeout]
#   vm.sh shot NAME OUT.png
set -euo pipefail
VMDIR=${VMDIR:-/var/tmp/eclipse-vmtest}
HERE=$(dirname "$(realpath "$0")")
cmd=$1; name=$2; shift 2
d="$VMDIR/$name"; mkdir -p "$d"
case "$cmd" in
start)
    iso=""; disks=(); bios=0
    while [ $# -gt 0 ]; do case "$1" in
        --iso) iso=$2; shift 2;; --disk) disks+=("$2"); shift 2;; --bios) bios=1; shift;; *) echo "bad arg $1"; exit 2;; esac; done
    [ -f "$d/vars.fd" ] || cp /usr/share/edk2/x64/OVMF_VARS.4m.fd "$d/vars.fd"
    args=(-enable-kvm -machine q35 -cpu host -smp 6 -m "${MEM:-8G}" -device virtio-vga -display none
          -nic user,model=virtio-net-pci -device virtio-serial
          -chardev "socket,path=$d/qga.sock,server=on,wait=off,id=qga0" -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0
          -monitor "unix:$d/mon.sock,server,nowait")
    [ $bios = 1 ] || args+=(-drive "if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd"
                            -drive "if=pflash,format=raw,file=$d/vars.fd")
    for f in "${disks[@]}"; do args+=(-drive "file=$f,if=virtio,format=qcow2"); done
    [ -n "$iso" ] && args+=(-cdrom "$iso" -boot order=d)
    rm -f "$d/qga.sock" "$d/mon.sock"
    nohup qemu-system-x86_64 "${args[@]}" > "$d/qemu.log" 2>&1 &
    echo $! > "$d/pid"; date +%s.%N > "$d/started"; echo "started $name (pid $(cat "$d/pid"))";;
stop)
    [ -f "$d/pid" ] && kill "$(cat "$d/pid")" 2>/dev/null || true
    for i in $(seq 30); do kill -0 "$(cat "$d/pid" 2>/dev/null)" 2>/dev/null || break; sleep 0.5; done; echo "stopped $name";;
exec) python3 "$HERE/qga.py" "$d/qga.sock" exec "$1" "${2:-300}";;
push) python3 "$HERE/qga.py" "$d/qga.sock" push "$1" "$2";;
pull) python3 "$HERE/qga.py" "$d/qga.sock" pull "$1" "$2";;
wait) python3 "$HERE/qga.py" "$d/qga.sock" wait "${1:-300}";;
shot) python3 "$HERE/shot.py" "$d/mon.sock" "$1";;
*) echo "unknown command $cmd"; exit 2;;
esac
