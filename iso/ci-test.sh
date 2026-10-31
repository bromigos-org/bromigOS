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
#            desktop through shim. Then the installed system, Secure Boot still on
#            (docs/secureboot.md): the install sets it up, MokManager enrolls the computer's own
#            key with the installer's code, the themed boot menu, a kernel update signed again
#            and started, a Unified Kernel Image (as Field Kit's) started through shim; and
#            again beside a stand-in Windows, whose EFI files and boot entry stay as they were
#            A medium with no live desktop to sign in to (menu, hook: the Field Kit) gets the
#            MokManager steps and its themed menu, Secure Boot on
#   --secureboot-package FILE   bromigos-secureboot as built from this ref, put in the medium's
#            store for the install (a channel may not have it, or have an older one)
#   --dev-build  the medium is a pull request's (iso/ci-local-packages.sh: the channel's packages
#            and its own): the installed system's first update and rollback are skipped, as no
#            channel is sure to be newer than its packages (a move to an older channel can
#            meet packages it doesn't know). Every published medium runs them
#
# DIR gets each run's directory (shots/, the checks' output, the console log). The disks
# are removed at the end. BROMIGOS_ISOTEST_MEM sets each VM's memory (MiB, default 6144);
# the VMs run one at a time.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/.." && pwd)
iso='' out='' suite=desktop profile='' sbcert='' sbpkg='' devbuild=0
while (($#)); do
    case $1 in
        --out) out=$2; shift 2 ;; --suite) suite=$2; shift 2 ;; --profile) profile=$2; shift 2 ;;
        --secureboot-cert) sbcert=$2; shift 2 ;; --secureboot-package) sbpkg=$2; shift 2 ;; --dev-build) devbuild=1; shift ;;
        -h|--help) sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "iso/ci-test.sh: unknown option $1" >&2; exit 2 ;;
        *) iso=$1; shift ;;
    esac
done
[[ -f $iso && -n $out ]] || { echo "iso/ci-test.sh ISO --out DIR" >&2; exit 2; }
[[ -e /dev/kvm ]] || { echo "iso/ci-test.sh: no /dev/kvm here" >&2; exit 2; }
iso=$(realpath "$iso"); mkdir -p "$out"; out=$(realpath "$out")
[[ -z $profile ]] || profile=$(realpath "$profile")
[[ -z $sbcert ]] || sbcert=$(realpath "$sbcert")
[[ -z $sbpkg ]] || sbpkg=$(realpath "$sbpkg")

if [[ ${BROMIGOS_ISOTEST_IN_CONTAINER:-0} != 1 ]]; then
    mounts=(-v "$root:$root:ro" -v "$(dirname "$iso"):$(dirname "$iso"):ro" -v "$out:$out")
    [[ -z $profile ]] || mounts+=(-v "$profile:$profile:ro")
    [[ -z $sbcert ]] || mounts+=(-v "$sbcert:$sbcert:ro")
    [[ -z $sbpkg ]] || mounts+=(-v "$sbpkg:$sbpkg:ro")
    dev=(); if (( devbuild )); then dev=(--dev-build); fi
    # the host's network: the SSH forwards are on its 127.0.0.1
    exec docker run --rm --device /dev/kvm --network host "${mounts[@]}" \
        -e BROMIGOS_ISOTEST_IN_CONTAINER=1 -e BROMIGOS_ISOTEST_MEM -e BROMIGOS_VM_OWNER=none \
        archlinux:latest "$here/ci-test.sh" "$iso" --out "$out" --suite "$suite" \
        ${profile:+--profile "$profile"} ${sbcert:+--secureboot-cert "$sbcert"} ${sbpkg:+--secureboot-package "$sbpkg"} "${dev[@]}"
fi

# ── in the container (or, with BROMIGOS_ISOTEST_IN_CONTAINER=1 as a user, on a workstation
# that has the tools: vm-keeper.py then counts every test VM on it, other jobs' too) ───────
if [[ $EUID -eq 0 ]]; then
    pacman -Syu --noconfirm --needed qemu-desktop edk2-ovmf socat openssh libisoburn python python-pillow \
        python-pip imagemagick procps-ng >/dev/null 2>&1
fi
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
        && if (( devbuild )); then
            BROMIGOS_ISOTEST_OFFLINE=0 BROMIGOS_ISOTEST_NO_UPDATE=1 step "$name: the installed system" T boot-disk --firmware "$fw" || true
            echo "SKIP $name: the first update and rollback (a pull request's medium, --dev-build)"
        else
            BROMIGOS_ISOTEST_OFFLINE=0 step "$name: the installed system, its first update and rollback" T boot-disk --firmware "$fw" || true
        fi
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
    # then the medium's menu, which keeps its theme with Secure Boot on (its fonts are in GRUB's memdisk)
    python3 "$root/iso/test/screen-wait.py" --qmp "$q" --out "$shots/menu-secureboot.png" --timeout 90 --coloured >/dev/null 2>&1 \
        && : > "$shots/.menu-themed"
}
sb_vars() {         # sb_vars DIR: a Windows PC's firmware variables, Secure Boot on, in DIR/OVMF_VARS.fd
    # BROMIGOS_ISOTEST_SB_VARS: such variables made already (a workstation without virt-firmware)
    if [[ -f ${BROMIGOS_ISOTEST_SB_VARS:-} ]]; then
        cp "$BROMIGOS_ISOTEST_SB_VARS" "$1/OVMF_VARS.fd"
    else
        [[ $EUID -ne 0 ]] || pacman -S --noconfirm --needed virt-firmware >/dev/null 2>&1 || { echo "virt-firmware didn't install"; return 1; }
        virt-fw-vars --input /usr/share/edk2/x64/OVMF_VARS.4m.fd --output "$1/OVMF_VARS.fd" \
            --enroll-microsoft --secure-boot >/dev/null 2>&1 || { echo "virt-fw-vars failed"; return 1; }
    fi
}
# a medium with no live desktop to sign in to (the Field Kit's, whose own test boots its
# kernel directly): the same MokManager steps, then its menu, themed, so shim verified GRUB
# with the enrolled key and GRUB its fonts, Secure Boot on
secureboot_menu() {
    local d=$out/secureboot
    mkdir -p "$d/shots"; sb_vars "$d" || return 1
    rm -f "$d/qmp.sock"
    qemu-system-x86_64 -enable-kvm -machine q35,smm=on -global driver=cfi.pflash01,property=secure,value=on -cpu host -m 2048 -smp 2 \
        -drive "if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd" -drive "if=pflash,format=raw,file=$d/OVMF_VARS.fd" \
        -drive "file=$iso,if=none,id=medium,media=cdrom,readonly=on" -device "ide-cd,drive=medium,bootindex=0" \
        -device virtio-vga -display none -qmp "unix:$d/qmp.sock,server,nowait" -serial "file:$d/console.log" \
        -daemonize -pidfile "$d/qemu.pid"
    for _ in $(seq 30); do [[ -S $d/qmp.sock ]] && break; sleep 1; done
    mok_keys "$d/qmp.sock" "$d/shots"
    kill "$(cat "$d/qemu.pid")" 2>/dev/null || true
    step "secure boot: MokManager enrolls the medium's key, then its menu, themed" test -e "$d/shots/.menu-themed" || true
}
secureboot_run() {
    local d=$out/secureboot
    mkdir -p "$d/shots"; sb_vars "$d" || return 1
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
    step "secure boot: the medium's menu keeps its theme" test -e "$d/shots/.menu-themed" || true
    cp "$d/OVMF_VARS.fd" "$d/vars-medium.fd" 2>/dev/null || true
    step "secure boot: the firmware says it's on" T ssh 'od -An -t u1 /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c | awk "{exit !(\$NF == 1)}"'
    step "secure boot: the key is in the MOK list" T ssh 'test -s /sys/firmware/efi/mok-variables/MokListRT || ls /sys/firmware/efi/efivars/ | grep -q "^MokListRT-"'
    # the firmware's variables now: Microsoft's keys, the medium's in MOK (the dual-boot run starts here)
    T ssh 'sudo sync' >/dev/null 2>&1 || true
    secureboot_installed "$d" || true
    T destroy >/dev/null 2>&1 || true
    rm -f "$d/disk.qcow2"
    secureboot_dualboot "$d" || true
}

# Secure Boot on the installed system (docs/secureboot.md, "The installed system"), from the
# live desktop above: bromigos-secureboot in the medium's store (this ref's build, when given:
# trusted for the test, as it isn't signed with bromigOS's package key), the install, then the
# installed system's first start: MokManager enrolls its own key with the installer's code, the
# boot menu is the theme's, Secure Boot is on and everything is signed
sb_store() {        # this ref's bromigos-secureboot into the live medium's store
    [[ -n $sbpkg ]] || return 0
    local f; f=$(basename "$sbpkg")
    T ssh "cat > $f" < "$sbpkg"
    # its own build replaces the store's, so a signature of the store's goes (the same version,
    # when the channel has this ref's: not the same file)
    T ssh "sudo rm -f /var/lib/bromigos/repo/bromigos/x86_64/$f.sig && sudo install -m0644 $f /var/lib/bromigos/repo/bromigos/x86_64/ && sudo repo-add -q /var/lib/bromigos/repo/bromigos/x86_64/bromigos.db.tar.gz /var/lib/bromigos/repo/bromigos/x86_64/$f \
        && sudo sed -i '/^\[bromigos\]$/a SigLevel = Optional TrustAll' /etc/pacman.conf && sudo pacman -Sy >/dev/null"
}
sb_checks() {       # sb_checks WHAT: Secure Boot on, the key enrolled, everything signed (as tester)
    T ssh "echo tester | sudo -S -p '' sh -c 'echo \"tester ALL=(ALL) NOPASSWD: ALL\" > /etc/sudoers.d/99-isotest && chmod 440 /etc/sudoers.d/99-isotest'" >/dev/null 2>&1 || true
    T ssh 'set -e
        od -An -t u1 /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c | awk "{exit !(\$NF == 1)}"
        mokutil --sb-state | grep -q "SecureBoot enabled"
        sudo /usr/lib/bromigos/secureboot/bromigos-secureboot status | tee /dev/stderr | grep -q "^Ready: Secure Boot is on"
        sudo /usr/lib/bromigos/secureboot/bromigos-secureboot status --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d[\"mok\"] == \"enrolled\" and not d[\"problems\"] and d[\"entry\"][\"first\"], d"
        sudo sbverify --cert /var/lib/bromigos/secureboot/machine.crt /boot/vmlinuz-linux
        test "$(sudo stat -c %a /var/lib/bromigos/secureboot/keys)" = 700'
}
secureboot_installed() {
    local d=$1 code
    step "secure boot, installed: this ref's bromigos-secureboot in the medium's store" sb_store || return 1
    T ssh 'ls /var/lib/bromigos/repo/bromigos/x86_64/bromigos-secureboot-*.pkg.tar.zst >/dev/null 2>&1' \
        || { echo "SKIP secure boot, installed: the medium carries no bromigos-secureboot (--secureboot-package)"; return 0; }
    step "secure boot, installed: the installer's checks say it can stay on" T ssh 'bromigos-iso-secureboot check' || true
    step "secure boot, installed: the install sets it up" T install || return 1
    code=$(cat "$d/secureboot-code" 2>/dev/null)
    [[ $code =~ ^[0-9]{4,8}$ ]] || { echo "FAIL secure boot, installed: the installer gave no code"; fails=$((fails + 1)); return 1; }
    step "secure boot, installed: MokManager enrolls this computer's key, then the themed boot menu" T mok-enroll "$code" || return 1
    step "secure boot, installed: it starts with Secure Boot on, everything signed" sb_checks || true
    # a kernel update (the same kernel again, from the mirrors: a transaction that replaces it):
    # the hooks sign it again, and it starts
    step "secure boot, installed: a kernel update is signed again" T ssh 'sudo pacman -Sy --noconfirm linux 2>&1 | tail -6; sudo sbverify --cert /var/lib/bromigos/secureboot/machine.crt /boot/vmlinuz-linux' || true
    T ssh 'sudo systemctl reboot' >/dev/null 2>&1 || true
    sleep 5
    step "secure boot, installed: after the update, the themed menu again" T grub secureboot-after-update down,up --coloured || true
    step "secure boot, installed: and it starts, Secure Boot on" T up || true
    step "secure boot, installed: still everything signed" sb_checks || true
    # Field Kit's Unified Kernel Image in the firmware's own menu (bromigos-fieldkit-boot's
    # entry, at the end of the boot order): an image of this system made here, with a word on
    # its command line to find, then resign routes the entry through shim and signs it
    step "secure boot, installed: a Unified Kernel Image (as Field Kit's) is signed and its entry goes through shim" T ssh 'set -e
        sudo pacman -S --noconfirm --needed systemd-ukify >/dev/null
        sudo ukify build --linux "/usr/lib/modules/$(uname -r)/vmlinuz" --initrd /boot/initramfs-linux.img \
            --cmdline "$(sed "s/BOOT_IMAGE=[^ ]* //" /proc/cmdline) console=tty0 console=ttyS0,115200 bromigos.ukitest" --output /tmp/fieldkit.efi >/dev/null
        sudo install -D -m0644 /tmp/fieldkit.efi /boot/EFI/bromigos-fieldkit/fieldkit.efi
        sudo efibootmgr --quiet --create-only --disk /dev/vda --part 1 --label "bromigOS Field Kit" --loader "\\EFI\\bromigos-fieldkit\\fieldkit.efi"
        sudo /usr/lib/bromigos/secureboot/bromigos-secureboot resign
        sudo sbverify --cert /var/lib/bromigos/secureboot/machine.crt /boot/EFI/bromigos-fieldkit/fieldkit.efi
        sudo efibootmgr -v | grep "bromigOS Field Kit" | tee /dev/stderr | grep -qi "bromigos-secureboot.shimx64.efi"
        n=$(sudo efibootmgr | sed -n "s/^Boot\([0-9A-F]\{4\}\)\* bromigOS Field Kit.*/\1/p" | head -1)
        sudo efibootmgr --quiet --bootnext "$n"' || true
    T ssh 'sudo systemctl reboot' >/dev/null 2>&1 || true
    sleep 5
    step "secure boot, installed: the firmware's Field Kit entry starts its image through shim" passphrase_ssh_uki || true
}
passphrase_ssh_uki() {   # straight from the firmware (no GRUB): the passphrase, SSH, the image's word
    local i
    for i in 1 2 3; do sleep $(( ${BROMIGOS_ISOTEST_PASS_WAIT:-25} / 3 )); T shot "uki-$i" >/dev/null 2>&1 || true; done
    T type tester >/dev/null
    for _ in $(seq 60); do T ssh true 2>/dev/null && break; sleep 5; done
    T ssh 'grep -qw bromigos.ukitest /proc/cmdline && od -An -t u1 /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c | awk "{exit !(\$NF == 1)}"'
}
# beside Windows: a stand-in Windows (its ESP's files, and a firmware entry "Windows Boot
# Manager" for them), bromigOS installed beside it with Secure Boot set up; Windows' files,
# its fallback loader and its entry must be as they were, and the menu has Windows
secureboot_dualboot() {
    local d=$1 w=$out/secureboot-dualboot code
    [[ -f $d/vars-medium.fd ]] || return 0
    mkdir -p "$w/shots"; cp "$d/vars-medium.fd" "$w/OVMF_VARS.fd"
    local BROMIGOS_ISOTEST_DIR=$w
    export BROMIGOS_ISOTEST_DIR
    BROMIGOS_ISOTEST_PORT=$(free_port 2245); BROMIGOS_ISOTEST_VNC=$(vnc_display 55); export BROMIGOS_ISOTEST_PORT BROMIGOS_ISOTEST_VNC
    step "secure boot, beside Windows: the live desktop (the medium's key enrolled already)" T boot --iso "$iso" --firmware uefi || return 1
    step "secure boot, beside Windows: a stand-in Windows, and its firmware entry" T windows --free-gib 24 || return 1
    T ssh 'sudo efibootmgr --quiet --create --disk /dev/vda --part 1 --label "Windows Boot Manager" --loader "\\EFI\\Microsoft\\Boot\\bootmgfw.efi"' || true
    sb_store || true
    step "secure boot, beside Windows: the install sets it up" T install --alongside || return 1
    code=$(cat "$w/secureboot-code" 2>/dev/null)
    [[ $code =~ ^[0-9]{4,8}$ ]] || { echo "FAIL secure boot, beside Windows: the installer gave no code"; fails=$((fails + 1)); return 1; }
    step "secure boot, beside Windows: MokManager, then the themed boot menu" T mok-enroll "$code" || return 1
    step "secure boot, beside Windows: it starts with Secure Boot on, everything signed" sb_checks || true
    step "secure boot, beside Windows: Windows' files, boot files and menu entry as they were" T verify-windows || true
    step "secure boot, beside Windows: Windows' firmware entry is still there, bromigOS first" T ssh 'set -e
        sudo efibootmgr | tee /dev/stderr | grep -q "Windows Boot Manager"
        w=$(sudo efibootmgr | sed -n "s/^Boot\([0-9A-F]\{4\}\)\* Windows Boot Manager.*/\1/p"); sudo efibootmgr | grep "^BootOrder:" | grep -q "$w"
        b=$(sudo efibootmgr -v | awk "tolower(\$0) ~ /bromigos-secureboot.shimx64.efi/ && \$0 !~ /Field Kit/ { sub(/^Boot/, \"\"); sub(/\\*.*/, \"\"); print; exit }")
        sudo efibootmgr | grep -q "^BootOrder: $b"' || true
    T destroy >/dev/null 2>&1 || true
    rm -f "$w/disk.qcow2"
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
if [[ -n $sbcert ]]; then
    if [[ $suite == desktop || $suite == none ]]; then secureboot_run || true; else secureboot_menu || true; fi
fi

find "$out" -name '*.ppm' -delete 2>/dev/null || true
chmod -R a+rwX "$out" 2>/dev/null || true
echo "==> $fails failed"
(( fails == 0 ))
