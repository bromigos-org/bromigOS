#!/usr/bin/env bash
# The ISO workflow's tests of a built medium (docs/iso.md, "What CI does with it"), in an
# archlinux container with KVM, so the machine running it needs only Docker and /dev/kvm.
# Headless: QEMU never opens a window (iso/test.sh).
#
#   iso/ci-test.sh ISO --out DIR [--suite desktop|menu|hook|none] [--profile DIR]
#                  [--secureboot-cert FILE]
#
#   desktop  the desktop medium, as a release is tested: UEFI with the network, an encrypted
#            install, the installed system, its first update and rollback; then BIOS with no
#            network, a plain install and the installed system
#   menu     a medium with no installer: it boots to its menu, UEFI and BIOS, and the menus
#            are saved
#   hook     the profile's own test: PROFILE/ci-test.sh ISO DIR, run in the same container
#            (the Field Kit's, say), after the menu test
#   none     nothing but the Secure Boot test below
#
#   --secureboot-cert FILE   as well: a medium signed for Secure Boot (its certificate) boots
#            on a Windows PC's firmware with Secure Boot on (OVMF, Microsoft's keys only):
#            MokManager, the key enrolled from the medium as a person does it, then the live
#            desktop through shim
#
# DIR gets each run's directory (shots/, the checks' output, the console log). The disks
# are removed at the end. BROMIGOS_ISOTEST_MEM sets each VM's memory (MiB, default 6144);
# the VMs run one at a time.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/.." && pwd)
iso='' out='' suite=desktop profile='' sbcert=''
while (($#)); do
    case $1 in
        --out) out=$2; shift 2 ;; --suite) suite=$2; shift 2 ;; --profile) profile=$2; shift 2 ;;
        --secureboot-cert) sbcert=$2; shift 2 ;;
        -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "iso/ci-test.sh: unknown option $1" >&2; exit 2 ;;
        *) iso=$1; shift ;;
    esac
done
[[ -f $iso && -n $out ]] || { echo "iso/ci-test.sh ISO --out DIR" >&2; exit 2; }
[[ -e /dev/kvm ]] || { echo "iso/ci-test.sh: no /dev/kvm here" >&2; exit 2; }
iso=$(realpath "$iso"); mkdir -p "$out"; out=$(realpath "$out")
[[ -z $profile ]] || profile=$(realpath "$profile")
[[ -z $sbcert ]] || sbcert=$(realpath "$sbcert")

if [[ ${BROMIGOS_ISOTEST_IN_CONTAINER:-0} != 1 ]]; then
    mounts=(-v "$root:$root:ro" -v "$(dirname "$iso"):$(dirname "$iso"):ro" -v "$out:$out")
    [[ -z $profile ]] || mounts+=(-v "$profile:$profile:ro")
    [[ -z $sbcert ]] || mounts+=(-v "$sbcert:$sbcert:ro")
    # the host's network: the SSH forwards are on its 127.0.0.1
    exec docker run --rm --device /dev/kvm --network host "${mounts[@]}" \
        -e BROMIGOS_ISOTEST_IN_CONTAINER=1 -e BROMIGOS_ISOTEST_MEM -e BROMIGOS_VM_OWNER=none \
        archlinux:latest "$here/ci-test.sh" "$iso" --out "$out" --suite "$suite" \
        ${profile:+--profile "$profile"} ${sbcert:+--secureboot-cert "$sbcert"}
fi

# ── in the container ───────────────────────────────────────────────────────────────────
pacman -Syu --noconfirm --needed qemu-desktop edk2-ovmf socat openssh libisoburn python python-pillow \
    python-pip imagemagick procps-ng >/dev/null 2>&1
export BROMIGOS_VM_OWNER=none
fails=0
step() {            # step NAME CMD…: runs it, says PASS or FAIL, goes on
    local name=$1; shift
    echo "::group::$name"
    if "$@"; then echo "::endgroup::"; echo "PASS $name"; else echo "::endgroup::"; echo "FAIL $name"; fails=$((fails + 1)); return 1; fi
}
T() { "$root/iso/test.sh" "$@"; }
# a free TCP port on 127.0.0.1 at or above $1 (the host's network: other VMs may hold some)
free_port() {
    python3 - "$1" <<'PY'
import socket, sys
for p in range(int(sys.argv[1]), 65000):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", p))
        except OSError:
            continue
        print(p)
        break
PY
}
vnc_display() { echo $(( $(free_port $((5900 + $1))) - 5900 )); }

desktop_run() {     # desktop_run NAME FIRMWARE PORT VNC OFFLINE ENCRYPT
    local name=$1 fw=$2 enc=()
    (( $6 )) || enc=(--no-encrypt)
    BROMIGOS_ISOTEST_PORT=$(free_port "$3"); BROMIGOS_ISOTEST_VNC=$(vnc_display "$4")
    export BROMIGOS_ISOTEST_DIR=$out/$name BROMIGOS_ISOTEST_PORT BROMIGOS_ISOTEST_VNC BROMIGOS_ISOTEST_OFFLINE=$5
    step "$name: the live desktop" T boot --iso "$iso" --firmware "$fw" \
        && step "$name: the install" T install "${enc[@]}" \
        && { BROMIGOS_ISOTEST_OFFLINE=0 step "$name: the installed system, its first update and rollback" T boot-disk --firmware "$fw" || true; }
    T destroy >/dev/null 2>&1 || true
    rm -f "$out/$name/disk.qcow2"
}

menu_run() {        # menu_run FIRMWARE: the medium boots to its menu; the menu saved
    local fw=$1 d=$out/menu-$1 fwargs=()
    mkdir -p "$d"
    if [[ $fw == uefi ]]; then
        cp /usr/share/edk2/x64/OVMF_VARS.4m.fd "$d/vars.fd"
        fwargs=(-drive "if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd" -drive "if=pflash,format=raw,file=$d/vars.fd")
    fi
    qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -m 2048 -smp 2 "${fwargs[@]}" \
        -drive "file=$iso,if=none,id=medium,media=cdrom,readonly=on" -device "ide-cd,drive=medium,bootindex=0" \
        -device virtio-vga -display none -qmp "unix:$d/qmp.sock,server,nowait" -serial "file:$d/console.log" \
        -daemonize -pidfile "$d/qemu.pid"
    local rc=0
    python3 "$root/iso/test/screen-wait.py" --qmp "$d/qmp.sock" --out "$d/menu.png" --keys "" --timeout 150 || rc=$?
    kill "$(cat "$d/qemu.pid")" 2>/dev/null || true
    return "$rc"
}

# Secure Boot, as on a Windows PC: OVMF's Secure Boot build with Microsoft's PK, KEK and db
# (virt-firmware's --enroll-microsoft) and Secure Boot on, nothing of bromigOS's. shim can't
# verify GRUB, so MokManager starts, and the test enrolls the medium's key the way a person
# does (docs/secureboot.md), each screen saved. Then the live desktop, and the firmware
# saying Secure Boot is on
mok_keys() {        # the enrollment, keystroke by keystroke, a screenshot after each screen
    local q=$1 shots=$2 n=0
    key() { printf '%s\n' '{"execute":"qmp_capabilities"}' "{\"execute\":\"send-key\",\"arguments\":{\"keys\":[{\"type\":\"qcode\",\"data\":\"$1\"}]}}" | socat - "UNIX-CONNECT:$q" >/dev/null; sleep 0.7; }
    snap() { n=$((n + 1)); printf '%s\n' '{"execute":"qmp_capabilities"}' "{\"execute\":\"screendump\",\"arguments\":{\"filename\":\"$shots/mok-$n-$1.ppm\"}}" | socat - "UNIX-CONNECT:$q" >/dev/null; sleep 1
             magick "$shots/mok-$n-$1.ppm" "$shots/mok-$n-$1.png" 2>/dev/null && rm -f "$shots/mok-$n-$1.ppm"; }
    sleep 12; snap verification-failed; key ret                  # "Verification failed": OK
    sleep 2; snap press-any-key; key spc                          # "Press any key to perform MOK management"
    sleep 2; snap mok-menu; key down; key ret                     # Enroll key from disk
    sleep 2; snap volume; key ret                                 # the stick's volume, ARCHISO_EFI
    sleep 2; snap file; key down; key ret                         # ENROLL_THIS_KEY_IN_MOKMANAGER.cer
    sleep 2; snap enroll-mok; key down; key ret                   # Continue
    sleep 2; snap enroll-the-keys; key down; key ret              # Yes
    sleep 2; snap reboot; key ret                                 # Reboot
}
secureboot_run() {
    local d=$out/secureboot
    mkdir -p "$d/shots"
    pacman -S --noconfirm --needed virt-firmware >/dev/null 2>&1 || { echo "virt-firmware didn't install"; return 1; }
    virt-fw-vars --input /usr/share/edk2/x64/OVMF_VARS.4m.fd --output "$d/OVMF_VARS.fd" \
        --enroll-microsoft --secure-boot >/dev/null 2>&1
    BROMIGOS_ISOTEST_PORT=$(free_port 2241); BROMIGOS_ISOTEST_VNC=$(vnc_display 51)
    export BROMIGOS_ISOTEST_DIR=$d BROMIGOS_ISOTEST_PORT BROMIGOS_ISOTEST_VNC BROMIGOS_ISOTEST_OFFLINE=0
    export BROMIGOS_ISOTEST_OVMF_CODE=/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd
    # the Secure Boot firmware needs SMM, and its variables kept from the OS
    export BROMIGOS_ISOTEST_QEMU="-machine smm=on -global driver=cfi.pflash01,property=secure,value=on"
    rm -f "$d/qmp.sock"
    ( for _ in $(seq 120); do [[ -S $d/qmp.sock ]] && break; sleep 1; done; mok_keys "$d/qmp.sock" "$d/shots" ) &
    local keys=$!
    step "secure boot: MokManager enrolls the key, then the live desktop, Secure Boot on" T boot --iso "$iso" --firmware uefi || true
    wait "$keys" 2>/dev/null || true
    step "secure boot: the firmware says it's on" T ssh 'od -An -t u1 /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c | awk "{exit !(\$NF == 1)}"'
    step "secure boot: the key is in the MOK list" T ssh 'test -s /sys/firmware/efi/mok-variables/MokListRT || ls /sys/firmware/efi/efivars/ | grep -q "^MokListRT-"'
    T destroy >/dev/null 2>&1 || true
    rm -f "$d/disk.qcow2"
}

case $suite in
    desktop)
        desktop_run uefi-encrypted uefi 2231 41 0 1 || true
        desktop_run bios-offline-plain bios 2232 42 1 0 || true
        ;;
    menu|hook)
        step "the medium's menu (UEFI)" menu_run uefi || true
        step "the medium's menu (BIOS)" menu_run bios || true
        if [[ $suite == hook ]]; then
            [[ -x $profile/ci-test.sh ]] || { echo "FAIL the profile has no ci-test.sh"; fails=$((fails + 1)); }
            [[ -x $profile/ci-test.sh ]] && { step "the profile's own test" "$profile/ci-test.sh" "$iso" "$out/profile" || true; }
        fi
        ;;
    none) ;;
    *) echo "iso/ci-test.sh: --suite desktop, menu, hook or none" >&2; exit 2 ;;
esac
if [[ -n $sbcert ]]; then secureboot_run || true; fi

find "$out" -name '*.ppm' -delete 2>/dev/null || true
chmod -R a+rwX "$out" 2>/dev/null || true
echo "==> $fails failed"
(( fails == 0 ))
