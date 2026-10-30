#!/usr/bin/env bash
# A stand-in for Windows on the test VM's disk (iso/test.sh windows; docs/iso.md, "Testing
# it"), run as root in the live system: Windows' own layouts, its boot files where
# os-prober looks for them, and files with their checksums, to see that they survive an
# install alongside it.
#
#   fake-windows.sh uefi|bios DISK [--free-gib N] [--hibernated] [--files-mib M]
#
#   uefi  GPT: a 100 MiB EFI system partition with EFI/Microsoft/Boot/{bootmgfw.efi,BCD},
#         the 16 MiB Microsoft reserved partition, C: (NTFS, Windows\System32 and Users\…)
#         and a 600 MiB recovery partition at the end, as Windows Setup lays them out
#   bios  MBR: "System Reserved" (NTFS, active, bootmgr and Boot\BCD) and C:
#   --free-gib N   leave N GiB unallocated before the recovery partition (default 0: the
#                  installer has to shrink C:)
#   --hibernated   a hiberfil.sys that says "HIBR" (Fast Startup): the installer must refuse
#                  to shrink it
#   --files-mib M  how much random data under Users (default 512)
# Writes the checksums of C:'s files to /root/fake-windows.sha256 (paths relative to C:), and
# on UEFI of the EFI system partition's to /root/fake-windows-esp.sha256.
set -euo pipefail
fw=${1:?uefi|bios}; disk=${2:?DISK}; shift 2
free=0 hib=0 mib=512
while (($#)); do
    case $1 in --free-gib) free=$2; shift 2 ;; --hibernated) hib=1; shift ;; --files-mib) mib=$2; shift 2 ;; *) echo "?? $1" >&2; exit 2 ;; esac
done
[[ $EUID -eq 0 ]] || { echo "fake-windows.sh: as root" >&2; exit 2; }
p() { if [[ $disk =~ [0-9]$ ]]; then echo "${disk}p$1"; else echo "$disk$1"; fi; }

# the boot configuration's store, with the version string the way BCD holds it (UTF-16:
# os-prober greps for "W.i.n.d.o.w.s. .1.1")
bcd() { printf 'regf'; printf 'Windows Boot Manager\0Windows 11' | iconv -t UTF-16LE; head -c 4096 /dev/urandom; }

wipefs -aq "$disk"
total=$(( $(blockdev --getsize64 "$disk") / 1048576 ))          # MiB
if [[ $fw == uefi ]]; then
    re_start=$(( total - 1 - 600 ))
    c_end=$(( re_start - free * 1024 ))
    sfdisk -q "$disk" <<EOF
label: gpt
start=2048, size=$((100 * 2048)), type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name="EFI system partition"
size=$((16 * 2048)), type=E3C9E316-0B5C-4DB8-817D-F92DF00215AE, name="Microsoft reserved partition"
size=$(( (c_end - 117) * 2048 )), type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7, name="Basic data partition"
start=$(( re_start * 2048 )), size=$((600 * 2048)), type=DE94BBA4-06D1-4D40-A16A-BFD50179D6AC, name="Basic data partition"
EOF
    udevadm settle
    esp=$(p 1) c=$(p 3) re=$(p 4)
    mkfs.fat -F32 -n SYSTEM "$esp" >/dev/null
    mkntfs -Q -q -L Windows "$c"
    mkntfs -Q -q -L Recovery "$re"
    m=$(mktemp -d); mount "$esp" "$m"
    mkdir -p "$m/EFI/Microsoft/Boot" "$m/EFI/Boot"
    head -c 1200000 /dev/urandom > "$m/EFI/Microsoft/Boot/bootmgfw.efi"
    bcd > "$m/EFI/Microsoft/Boot/BCD"
    cp "$m/EFI/Microsoft/Boot/bootmgfw.efi" "$m/EFI/Boot/bootx64.efi"
    (cd "$m" && find . -type f -print0 | sort -z | xargs -0 sha256sum) > /root/fake-windows-esp.sha256
    umount "$m"; rmdir "$m"
else
    sfdisk -q "$disk" <<EOF
label: dos
start=2048, size=$((50 * 2048)), type=7, bootable
size=$(( (total - 52 - free * 1024) * 2048 )), type=7
EOF
    udevadm settle
    sr=$(p 1) c=$(p 2)
    mkntfs -Q -q -L "System Reserved" "$sr"
    mkntfs -Q -q -L Windows "$c"
    m=$(mktemp -d); mount -t ntfs3 "$sr" "$m"
    head -c 400000 /dev/urandom > "$m/bootmgr"
    mkdir -p "$m/Boot"; bcd > "$m/Boot/BCD"
    umount "$m"; rmdir "$m"
fi

m=$(mktemp -d); mount -t ntfs3 "$c" "$m"
mkdir -p "$m/Windows/System32" "$m/Users/tester/Documents" "$m/Users/tester/Pictures" "$m/Program Files"
head -c 2000000 /dev/urandom > "$m/Windows/System32/ntoskrnl.exe"
echo "Windows 11 stand-in for bromigOS's installer test" > "$m/Windows/System32/license.rtf"
for i in $(seq 1 8); do head -c $(( mib * 1048576 / 8 )) /dev/urandom > "$m/Users/tester/Documents/file-$i.bin"; done
printf 'my notes\n' > "$m/Users/tester/Documents/notes.txt"
head -c 300000 /dev/urandom > "$m/Users/tester/Pictures/holiday.jpg"
(( hib )) && { printf 'HIBR'; head -c 1048572 /dev/zero; } > "$m/hiberfil.sys"
(cd "$m" && find . -type f ! -name hiberfil.sys -print0 | sort -z | xargs -0 sha256sum) > /root/fake-windows.sha256
umount "$m"; rmdir "$m"
sync
echo "fake Windows ($fw) on $disk: C: is $c, $(wc -l < /root/fake-windows.sha256) files, $free GiB free$( ((hib)) && echo ', hibernated')"
sfdisk -l "$disk" | tail -n +2
