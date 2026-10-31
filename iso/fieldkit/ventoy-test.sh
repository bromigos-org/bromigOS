#!/usr/bin/env bash
# Both ISOs through Ventoy (docs/fieldkit.md, "Ventoy"): a Ventoy stick made as Ventoy2Disk.sh
# makes one (MBR: an exFAT partition for the ISO files, Ventoy's 32 MiB EFI partition at the
# end, its boot code in the MBR and the gap), as a disk image, then each ISO booted from it in
# QEMU, in Ventoy's normal mode and its GRUB2 mode, on UEFI and BIOS. A medium passes when it
# reaches its login prompt on the serial console (a test build: iso/build.sh --test-key).
#
#   iso/fieldkit/ventoy-test.sh make OUT.img ISO…     the stick, with the ISOs on it
#   iso/fieldkit/ventoy-test.sh boot IMG uefi|bios normal|grub2 [N]
#                                                     boot the Nth ISO in Ventoy's menu (default 1)
#
# Ventoy is downloaded from its GitHub release and checked against the release's sha256.txt,
# into $BROMIGOS_VENTOY_DIR (default ~/.cache/bromigos-fieldkit-test/ventoy). The exFAT partition is
# made and filled in a privileged archlinux container (a loop device over the image file), as
# iso/build.sh builds; nothing is installed on this machine.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
version=${BROMIGOS_VENTOY_VERSION:-1.1.18}
vdir=${BROMIGOS_VENTOY_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bromigos-fieldkit-test/ventoy}
ventoy=$vdir/ventoy-$version
SECTORS=65536                       # Ventoy's EFI partition: 32 MiB

fetch() {
    [[ -d $ventoy ]] && return
    mkdir -p "$vdir"
    local base=https://github.com/ventoy/Ventoy/releases/download/v$version
    curl -fsSL -o "$vdir/ventoy-$version-linux.tar.gz" "$base/ventoy-$version-linux.tar.gz"
    curl -fsSL -o "$vdir/sha256.txt" "$base/sha256.txt"
    (cd "$vdir" && grep "ventoy-$version-linux.tar.gz" sha256.txt | sha256sum -c -)
    tar -C "$vdir" -xzf "$vdir/ventoy-$version-linux.tar.gz"
}

make_stick() {
    local img=$1; shift
    fetch
    local bytes=0 iso
    for iso in "$@"; do bytes=$((bytes + $(stat -c %s "$iso"))); done
    local size=$(( (bytes / 1048576) + 1024 ))M
    rm -f "$img"; truncate -s "$size" "$img"
    local total=$(( $(stat -c %s "$img") / 512 ))
    # as ventoy_lib.sh's format_ventoy_disk_mbr: partition 1 from sector 2048, partition 2
    # (32 MiB) after it, aligned to 8 sectors; partition 1 active
    local p1_end=$(( total - SECTORS - 1 ))
    local p2_start=$(( p1_end + 1 ))
    local mod=$(( p2_start % 8 ))
    if (( mod )); then p1_end=$(( p1_end - mod )); p2_start=$(( p1_end + 1 )); fi
    printf 'label: dos\n2048,%d,7,*\n%d,%d,ef\n' $(( p1_end - 2048 + 1 )) "$p2_start" "$SECTORS" | sfdisk -q "$img"
    # the boot code: boot.img in the MBR, core.img in the gap, Ventoy's EFI partition
    dd status=none conv=notrunc if="$ventoy/boot/boot.img" of="$img" bs=1 count=446
    xzcat "$ventoy/boot/core.img.xz" | dd status=none conv=notrunc of="$img" bs=512 count=2047 seek=1
    xzcat "$ventoy/ventoy/ventoy.disk.img.xz" | dd status=none conv=notrunc of="$img" bs=512 count=$SECTORS seek="$p2_start"
    head -c 16 /dev/urandom | dd status=none conv=notrunc of="$img" seek=384 bs=1 count=16
    head -c 4 /dev/urandom | dd status=none conv=notrunc of="$img" seek=440 bs=1 count=4
    # partition 1: Ventoy's own mkexfatfs, labelled Ventoy, filled with the ISOs. Made as a file
    # (a FUSE mount of it in a privileged container: no loop device), then written into place
    local part=$img.part1 len=$(( (p1_end - 2048 + 1) * 512 ))
    rm -f "$part"; truncate -s "$len" "$part"
    local mounts=(-v "$(realpath "$part"):/part1.img" -v "$ventoy:/ventoy:ro") i=0
    for iso in "$@"; do mounts+=(-v "$(realpath "$iso"):/iso/$i-$(basename "$iso"):ro"); i=$((i + 1)); done
    docker run --rm --privileged "${mounts[@]}" archlinux:latest bash -euc '
        xzcat /ventoy/tool/x86_64/mkexfatfs.xz > /tmp/mkexfatfs; chmod +x /tmp/mkexfatfs
        /tmp/mkexfatfs -n Ventoy -s 64 /part1.img >/dev/null
        # the container sees no loop device nodes: make them (the kernel exFAT driver mounts it)
        for n in $(seq 0 63); do [ -e /dev/loop$n ] || mknod /dev/loop$n b 7 $n; done
        dev=$(losetup -f --show /part1.img); trap "umount /mnt/v 2>/dev/null; losetup -d $dev" EXIT
        mkdir -p /mnt/v; mount -t exfat "$dev" /mnt/v
        for f in /iso/*; do cp "$f" "/mnt/v/$(basename "$f" | cut -d- -f2-)"; done
        sync; ls -l /mnt/v'
    dd status=none conv=notrunc,sparse if="$part" of="$img" bs=4M oflag=seek_bytes seek=$((2048 * 512))
    rm -f "$part"
    echo "ventoy-test: $img ($size) with $# ISO(s)"
}

boot() {
    local img=$1 fw=$2 mode=$3 n=${4:-1} name="ventoy-$2-$3"
    local t=$here/test.py
    "$t" up --name "$name" --disk "$img" --boot disk --firmware "$fw" --mem "${BROMIGOS_VENTOY_MEM:-3072}"
    sleep 12                                     # Ventoy's menu
    "$t" shot --name "$name" "ventoy-menu-$fw"
    local k=(); for ((j = 1; j < n; j++)); do k+=(down); done
    (( ${#k[@]} )) && "$t" keys --name "$name" "${k[@]}"
    "$t" keys --name "$name" ret
    sleep 3                                      # Ventoy's "Boot in normal mode / grub2 mode"
    "$t" shot --name "$name" "ventoy-mode-$fw"
    [[ $mode == grub2 ]] && "$t" keys --name "$name" down
    "$t" keys --name "$name" ret
    local rc=0
    "$t" wait-serial --name "$name" "login:" --timeout 300 || rc=1
    "$t" shot --name "$name" "ventoy-$fw-$mode-$n"
    "$t" down --name "$name"
    echo "ventoy-test: $fw $mode ISO $n: $([[ $rc == 0 ]] && echo PASS || echo FAIL)"
    return $rc
}

case ${1:-} in
    make) shift; make_stick "$@" ;;
    boot) shift; boot "$@" ;;
    *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
