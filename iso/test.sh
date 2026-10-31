#!/usr/bin/env bash
# The ISO's boot and install test (docs/iso.md), on any machine with KVM, headless: QEMU
# with -display none, screenshots through its monitor to DIR/shots/, never a window.
#
#   iso/test.sh boot    --iso FILE [--firmware uefi|bios] [--hosts "IP NAME"]
#                       boots the medium, waits for the live desktop, screenshots it, runs
#                       the live checks. Any medium: a test build (iso/build.sh --test-key
#                       DIR/id_ed25519.pub) has the key; a public one gets it from a cloud-init
#                       seed the harness attaches (DIR/seed.iso), so the medium is tested as built
#   iso/test.sh install [--repo URL] [--ca FILE] [--no-encrypt]
#                       the unattended install onto the VM's disk, over SSH (btrfs on
#                       LUKS2 by default; --no-encrypt: plain btrfs)
#   iso/test.sh windows [--free-gib N] [--hibernated]
#                       a stand-in Windows on the VM's disk (test/fake-windows.sh: Windows'
#                       partitions, its boot files where os-prober looks, files with their
#                       checksums), to install alongside
#   iso/test.sh tui-install --mode erase|alongside [--no-encrypt] [--edition ID] [--gib N]
#   iso/test.sh gui-install --mode erase|alongside [--no-encrypt] [--edition ID] [--gib N]
#                       the text or the graphical installer, driven like a person would (keys:
#                       test/installer/tuidrive.py; the graphical one's own script mode, with
#                       a screenshot of each step from the VM's screen) onto the VM's disk,
#                       with the real install; then as `install` after it
#   iso/test.sh data-rollback   on the installed system (after boot-disk or up): an update's rollback
#                       undoes the system, and a container volume's data written after it stays
#   iso/test.sh keep-files | verify-reinstall   a file in the installed home before `tui-install --mode
#                       reinstall`, then it, the user's ID and the old root's snapshot after
#   iso/test.sh verify-windows   in the installed system: the stand-in Windows' files and its
#                       boot files unchanged, NTFS consistent, Windows in GRUB's menu
#   iso/test.sh boot-disk [--firmware uefi|bios] [--update-channel NAME] [--update-repo URL [--ca FILE]]
#                       boots the installed system, signs in at the login screen (QMP keys),
#                       screenshots it, runs test/vm/checks.sh in it, then the first update
#                       (to NAME; default the other channel: edge from stable, else stable)
#                       and a rollback of it. --update-repo: the update reads this copy of the
#                       channels (and trusts --ca), when the system's own repository isn't
#                       reachable yet (a public medium before go-live, docs/iso.md)
#   iso/test.sh menu ENTRY  the medium's boot menu (UEFI GRUB or BIOS syslinux) saved, then one
#                       channel booted and checked: live, install (the graphical installer
#                       opens), text (the text installer on tty1, no desktop), safe
#                       (nomodeset), memtest, disk (the installed system's GRUB), speech
#   iso/test.sh param "PARAMS"  "Install bromigOS" with PARAMS added to its kernel line (GRUB's
#                       editor, syslinux's Tab): which installer opened, and the edition chosen
#   iso/test.sh grub NAME [KEYS] [--coloured]   boots the installed disk and saves its GRUB
#                       menu as shots/grub-NAME.png (KEYS first, e.g. down,down,ret: the
#                       snapshots; --coloured: it must be the theme's); the VM stays at the menu
#   iso/test.sh up      from that menu: boots the default entry, the passphrase, SSH
#   iso/test.sh mok-enroll CODE   boots the installed disk with Secure Boot on (its key asked for
#                       at this start: docs/secureboot.md) and goes through MokManager as a
#                       person does (Enroll MOK, Continue, Yes, the code, Reboot; a screen saved
#                       at each, shots/mokm-*), then the boot menu (saved as shots/grub-secureboot.png,
#                       which must be the theme's), the passphrase and SSH
#   iso/test.sh install --alongside   bromigOS into the disk's free space beside what's there
#                       (a stand-in Windows: `windows --free-gib N` first), sharing its EFI
#                       system partition
#   iso/test.sh shot NAME | ssh [cmd…] | down | destroy
#
# The VM: 6 GB, 4 CPUs, virtio-gpu (Mesa's software renderer), a 40 GB disk, user
# networking with SSH on localhost:2223. UEFI boots use edk2-ovmf's firmware (a private
# copy of its variables); BIOS boots use SeaBIOS. Everything lives in DIR (default
# ~/.cache/bromigos-isotest): the key, the disk, the console log, shots/. Beside another
# run: BROMIGOS_ISOTEST_DIR, _PORT (SSH), _VNC (display), _MEM (MiB, 6144) and _SMP (vCPUs, 4; the
# test VMs' budget is 4 vCPUs and 8 GiB together: test/vm/vm-keeper.py); BROMIGOS_ISOTEST_QEMU adds QEMU
# arguments (a faked laptop: -smbios file=… from test/vm/smbios-chassis.py; docs/hardware.md),
# BROMIGOS_ISOTEST_PASS_WAIT waits that many seconds for the passphrase prompt (25; a 2-vCPU VM needs more),
# BROMIGOS_ISOTEST_OFFLINE=1 cuts the VM off from the network (the SSH forward stays), and
# BROMIGOS_ISOTEST_OVMF_CODE another UEFI firmware (Secure Boot's: iso/ci-test.sh), BROMIGOS_ISOTEST_VGA the
# display device (default virtio-vga; e.g. virtio-vga,xres=1024,yres=768
# offers the firmware that mode, which GRUB's GFXMODE=auto takes).
# The VM stops when the session that started it ends (test/vm/vm-keeper.py):
# BROMIGOS_VM_OWNER=PID ties it to another process, BROMIGOS_VM_OWNER=none keeps it until down.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/.." && pwd)
dir=${BROMIGOS_ISOTEST_DIR:-$HOME/.cache/bromigos-isotest}
port=${BROMIGOS_ISOTEST_PORT:-2223}
ovmf_code=${BROMIGOS_ISOTEST_OVMF_CODE:-/usr/share/edk2/x64/OVMF_CODE.4m.fd}
ovmf_vars=/usr/share/edk2/x64/OVMF_VARS.4m.fd

cmd=${1:-}; shift || true
iso='' firmware='' hosts='' repo='' ca='' encrypt=1 update_channel='' update_repo='' mode=erase edition=desktop gib='' free_gib=0 hibernated=0 alongside=0
while (($#)); do
    case $1 in
        --iso) iso=$2; shift 2 ;; --firmware) firmware=$2; shift 2 ;; --hosts) hosts=$2; shift 2 ;;
        --repo) repo=$2; shift 2 ;; --ca) ca=$2; shift 2 ;; --dir) dir=$2; shift 2 ;; --no-encrypt) encrypt=0; shift ;;
        --update-channel) update_channel=$2; shift 2 ;; --update-repo) update_repo=$2; shift 2 ;;
        --mode) mode=$2; shift 2 ;; --edition) edition=$2; shift 2 ;; --gib) gib=$2; shift 2 ;;
        --free-gib) free_gib=$2; shift 2 ;; --hibernated) hibernated=1; shift ;; --alongside) alongside=1; shift ;; *) break ;;
    esac
done
mkdir -p "$dir/shots"
key=$dir/id_ed25519
[[ -f $key ]] || ssh-keygen -q -t ed25519 -N '' -f "$key"
[[ -n $firmware ]] || firmware=$(cat "$dir/firmware" 2>/dev/null || echo uefi)
[[ -n $hosts ]] || hosts=$(cat "$dir/hosts.entry" 2>/dev/null || true)
sshopts=(-i "$key" -p "$port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5)
user=$(cat "$dir/user" 2>/dev/null || echo live)
SSH=(ssh "${sshopts[@]}" "$user@127.0.0.1")
# scp names the port -P; every other option as ssh's (a substitution over the array would
# also change any path with "-p" in it)
scpopts=(); for o in "${sshopts[@]}"; do [[ $o == -p ]] && o=-P; scpopts+=("$o"); done
SCP=(scp "${scpopts[@]}")
qmp() { printf '%s\n' '{"execute":"qmp_capabilities"}' "$1" | socat - "UNIX-CONNECT:$dir/qmp.sock" >/dev/null; }

wait_ssh() {
    local n=${1:-120}
    for _ in $(seq 1 "$n"); do "${SSH[@]}" true 2>/dev/null && return 0; sleep 5; done
    echo "iso/test.sh: no SSH as $user after $((n * 5)) s (console: $dir/console.log)" >&2; return 1
}

vm_pids() { pgrep -f -- "-qmp unix:$dir/qmp.sock" || true; }

start_vm() {        # start_vm medium|disk
    local what=$1 fw=() boot=() cd=()
    [[ -z $(vm_pids) ]] || { echo "iso/test.sh: a VM of this directory is running ($0 down first)" >&2; exit 2; }
    if [[ $firmware == uefi ]]; then
        [[ -f $dir/OVMF_VARS.fd ]] || cp "$ovmf_vars" "$dir/OVMF_VARS.fd"
        fw=(-drive "if=pflash,format=raw,readonly=on,file=$ovmf_code" -drive "if=pflash,format=raw,file=$dir/OVMF_VARS.fd")
    fi
    [[ -f $dir/disk.qcow2 ]] || qemu-img create -q -f qcow2 "$dir/disk.qcow2" 40G
    if [[ $what == medium ]]; then
        # the medium first, even after an install put the disk's GRUB first in the firmware's
        # own order (bootindex: OVMF follows it; SeaBIOS too)
        cd=(-drive "file=$iso,if=none,id=medium,media=cdrom,readonly=on" -device "ide-cd,drive=medium,bootindex=0" -boot "menu=off")
        # the harness's key for `live` as a NoCloud seed (a second CD labelled CIDATA, on
        # q35's second AHCI port: one device each): the
        # medium's cloud-init (releng's, as on Arch's own medium) adds it, and releng's sshd
        # is on. A public build carries no test key; a test build already has it
        seed
        cd+=(-drive "file=$dir/seed.iso,if=none,id=seed,media=cdrom,readonly=on" -device "ide-cd,drive=seed,bus=ide.1")
    else
        boot=(-boot "order=c")
    fi
    # BROMIGOS_ISOTEST_OFFLINE=1: the VM reaches nothing but the harness's SSH (QEMU's
    # restrict=on), as a machine with no network: the offline install
    local net_restrict=''; [[ ${BROMIGOS_ISOTEST_OFFLINE:-0} == 1 ]] && net_restrict=',restrict=on'
    : > "$dir/console.log"
    # through vm-keeper.py: QEMU stops when whoever started the test is gone
    # (BROMIGOS_VM_OWNER=none keeps it until down)
    # shellcheck disable=SC2086  # BROMIGOS_ISOTEST_QEMU is words (a faked laptop: -smbios file=…)
    "$root/test/vm/vm-keeper.py" --ready "$dir/qmp.sock" --log "$dir/keeper.log" -- \
        qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -m "${BROMIGOS_ISOTEST_MEM:-6144}" -smp "${BROMIGOS_ISOTEST_SMP:-4}" "${fw[@]}" ${BROMIGOS_ISOTEST_QEMU:-} \
        -drive "file=$dir/disk.qcow2,if=virtio" "${cd[@]}" "${boot[@]}" \
        -nic "user,model=virtio-net-pci${net_restrict},hostfwd=tcp:127.0.0.1:$port-:22" \
        -device "${BROMIGOS_ISOTEST_VGA:-virtio-vga}" -device qemu-xhci -device usb-tablet -display none -vnc "127.0.0.1:${BROMIGOS_ISOTEST_VNC:-48}" \
        -qmp "unix:$dir/qmp.sock,server,nowait" -serial "file:$dir/console.log" \
        -pidfile "$dir/qemu.pid"
    printf '%s\n' "$firmware" > "$dir/firmware"
}

seed() {            # DIR/seed.iso: cloud-init's NoCloud seed, the harness's key for `live`
    local d=$dir/seed
    rm -rf "$d"; mkdir -p "$d"
    printf 'instance-id: bromigos-isotest\n' > "$d/meta-data"
    # lock_passwd false: `live` keeps its empty password, as on the medium; and its host name
    printf '#cloud-config\npreserve_hostname: true\nusers:\n  - name: live\n    lock_passwd: false\n    ssh_authorized_keys:\n      - %s\n' \
        "$(cat "$key.pub")" > "$d/user-data"
    xorriso -as mkisofs -quiet -V CIDATA -J -r -o "$dir/seed.iso" "$d/user-data" "$d/meta-data" 2>/dev/null
    rm -rf "$d"
}

shot() {
    local name=$1
    qmp "{\"execute\":\"screendump\",\"arguments\":{\"filename\":\"$dir/shots/$name.ppm\"}}"
    sleep 1
    if command -v magick >/dev/null; then magick "$dir/shots/$name.ppm" "$dir/shots/$name.png" && rm -f "$dir/shots/$name.ppm"; fi
    ls "$dir/shots/$name".*
}

press() {           # press KEY[-KEY…]: one QMP send-key of qcodes, e.g. shift-tab, ret
    qmp "{\"execute\":\"send-key\",\"arguments\":{\"keys\":[$(printf '%s' "$1" | sed -E 's/([a-z0-9_]+)/{"type":"qcode","data":"\1"}/g; s/-/,/g')]}}"
    sleep 0.3
}

click() {           # click X Y: the pointer there (the tablet's absolute axes, 0..32767 over 1280x800), a left click
    local x=$(( $1 * 32767 / 1280 )) y=$(( $2 * 32767 / 800 ))
    qmp "{\"execute\":\"input-send-event\",\"arguments\":{\"events\":[{\"type\":\"abs\",\"data\":{\"axis\":\"x\",\"value\":$x}},{\"type\":\"abs\",\"data\":{\"axis\":\"y\",\"value\":$y}}]}}"
    sleep 0.2
    qmp '{"execute":"input-send-event","arguments":{"events":[{"type":"btn","data":{"down":true,"button":"left"}}]}}'
    sleep 0.1
    qmp '{"execute":"input-send-event","arguments":{"events":[{"type":"btn","data":{"down":false,"button":"left"}}]}}'
    sleep 0.3
}

type_text() {       # type_text "text": one QMP send-key per character (no Return)
    local s=$1 c q
    for ((i = 0; i < ${#s}; i++)); do
        c=${s:i:1}
        case $c in
            [a-z0-9]) q=$c ;; [A-Z]) q="shift-${c,,}" ;; -) q="minus" ;; _) q="shift-minus" ;; .) q="dot" ;; " ") q="spc" ;;
            /) q="slash" ;; :) q="shift-semicolon" ;; \;) q="semicolon" ;; "~") q="shift-grave_accent" ;; \|) q="shift-backslash" ;; "'") q="apostrophe" ;; \$) q="shift-4" ;;
            =) q="equal" ;;
            *) echo "type_text: no key for '$c'" >&2; return 1 ;;
        esac
        press "$q"
        sleep 0.05
    done
}
type_keys() { type_text "$1"; press ret; }     # … then Return

menu_wait() {       # menu_wait NAME [KEYS] [--coloured]: a boot menu on screen, saved as shots/NAME.png
    python3 "$here/test/screen-wait.py" --qmp "$dir/qmp.sock" --out "$dir/shots/$1.png" --keys "${2:-}" --timeout 150 ${3:-}
}

blue_wait() {       # blue_wait [SECONDS]: shim's blue screens (MokManager) on screen
    python3 - "$dir/qmp.sock" "$dir/blue.ppm" "${1:-120}" <<'PY2'
import json, os, socket, sys, time
from PIL import Image
sock, ppm, timeout = sys.argv[1], sys.argv[2], float(sys.argv[3])
def dump():
    s = socket.socket(socket.AF_UNIX); s.settimeout(10)
    here = os.getcwd(); os.chdir(os.path.dirname(sock))
    try:
        s.connect(os.path.basename(sock))
    finally:
        os.chdir(here)
    f = s.makefile("rw"); f.readline()
    for c in ({"execute": "qmp_capabilities"}, {"execute": "screendump", "arguments": {"filename": ppm}}):
        f.write(json.dumps(c) + "\n"); f.flush(); f.readline()
    s.close()
end = time.time() + timeout
while time.time() < end:
    try:
        dump(); time.sleep(0.3)
        im = Image.open(ppm).convert("RGB").resize((64, 40))
        px = list(im.getdata())
        if sum(1 for r, g, b in px if b > 120 and r < 60 and g < 60) > len(px) * 0.6:
            sys.exit(0)
    except (OSError, ValueError):
        pass
    time.sleep(0.5)
sys.exit(1)
PY2
}

passphrase_then_ssh() {     # after GRUB: the disk's passphrase at the splash, then SSH
    if (( $(cat "$dir/encrypted" 2>/dev/null || echo 1) )); then
        sleep "${BROMIGOS_ISOTEST_PASS_WAIT:-25}"
        type_keys "tester"
    fi
    wait_ssh 60
}

finish_install() {   # finish_install RC: what the new system got, then a clean power-off
    local rc=$1
    # Secure Boot set up (docs/secureboot.md): the code that approves the key at the first start
    "${SSH[@]}" "sudo grep -oE -- 'setup --fresh-install --code [0-9]+' /var/log/bromigos-iso-install.log | tail -1 | awk '{print \$NF}'" \
        > "$dir/secureboot-code" 2>/dev/null || true
    # what the new system got, while it's still mounted at /mnt (install-state.out)
    : > "$dir/install-state.out"
    # beside a stand-in Windows: its C: checked where the tools are (the medium), after the resize
    "${SSH[@]}" 'c=$(lsblk -rno PATH,LABEL /dev/vda | awk "\$2 == \"Windows\" { print \$1 }"); [ -n "$c" ] && sudo ntfsresize --info --force --no-progress-bar "$c" | grep "You might resize at" | sed "s/^/ntfs-check: /"' >> "$dir/install-state.out" 2>&1 || true
    "${SSH[@]}" 'sudo bash -c "findmnt -R /mnt; lsblk -o NAME,TYPE,FSTYPE,PARTTYPENAME,MOUNTPOINTS /dev/vda; ls -la /mnt/home/*/.ssh; grep -h ^HOOKS= /mnt/etc/mkinitcpio.conf /mnt/etc/mkinitcpio.conf.d/*.conf; lsinitcpio /mnt/boot/initramfs-linux.img | grep -c plymouth; grep -E ^GRUB_CMDLINE /mnt/etc/default/grub; grep -c snapshots /mnt/boot/grub/grub.cfg; grep -E \"^menuentry\" /mnt/boot/grub/grub.cfg; grep -A2 bromigos\\] /mnt/etc/pacman.conf; arch-chroot /mnt snapper --no-dbus list-configs; arch-chroot /mnt sshd -T 2>/dev/null | grep -iE \"^(pubkeyauthentication|authorizedkeysfile|passwordauthentication)\"; [ -d /sys/firmware/efi ] && efibootmgr"' 2>&1 | tee "$dir/install-state.out.main" || true
    cat "$dir/install-state.out.main" >> "$dir/install-state.out"; rm -f "$dir/install-state.out.main"
    if (( rc != 0 )); then     # a failed install: the live system's logs, before it powers off
        "${SSH[@]}" 'sudo cat /var/log/bromigos-iso-install.log' > "$dir/failed-install.log" 2>&1 || true
        "${SSH[@]}" 'sudo cat /var/log/archinstall/install.log' > "$dir/failed-archinstall.log" 2>&1 || true
        echo "the live system's logs: $dir/failed-install.log, $dir/failed-archinstall.log"
        tail -25 "$dir/failed-install.log"
    fi
    # a clean shutdown: the new system's file systems unmounted, LUKS closed, then
    # poweroff (killing QEMU would lose what's still in the page cache)
    "${SSH[@]}" 'sudo sync; sudo umount -R /mnt; sudo cryptsetup close root 2>/dev/null; sudo systemctl poweroff' 2>/dev/null || true
    for _ in $(seq 90); do [[ -z $(vm_pids) ]] && break; sleep 1; done
    "$0" down --dir "$dir"
    return "$rc"
}

plan_json() {      # the installers' test plan: the harness's account (tester), the choices given
    python3 -c 'import json, sys; m, e, ed, g = sys.argv[1:5]; print(json.dumps({"mode": m, "encrypt": e == "1", "edition": ed,
        "gib": int(g) if g else None, "full_name": "Test Er", "user": "tester", "password": "tester",
        "hostname": "bromigos-test", "ssh": True, "disk_index": 0, "ssh_key": open(sys.argv[5]).read().strip()}))' \
        "$mode" "$encrypt" "$edition" "$gib" "$key.pub"
}

case $cmd in
    windows)
        "${SCP[@]}" "$here/test/fake-windows.sh" "live@127.0.0.1:"
        extra=(--files-mib 256 --free-gib "$free_gib"); (( hibernated )) && extra+=(--hibernated)
        "${SSH[@]}" "sudo bash fake-windows.sh $firmware /dev/vda ${extra[*]}"
        mkdir -p "$dir/windows"
        "${SSH[@]}" "sudo cat /root/fake-windows.sha256" > "$dir/windows/c.sha256"
        if [[ $firmware == uefi ]]; then "${SSH[@]}" "sudo cat /root/fake-windows-esp.sha256" > "$dir/windows/esp.sha256"; fi
        ;;
    tui-install|gui-install)
        "${SCP[@]}" "$key.pub" "live@127.0.0.1:"
        printf '%s\n' "$((encrypt ? 1 : 0))" > "$dir/encrypted"
        printf '%s\n' "$edition" > "$dir/edition"
        "${SSH[@]}" "cat /etc/bromigos-iso/channel 2>/dev/null || echo stable" > "$dir/channel"
        plan_json > "$dir/plan.json"
        "${SCP[@]}" "$dir/plan.json" "live@127.0.0.1:plan.json"
        rc=0
        if [[ $cmd == tui-install ]]; then
            "${SCP[@]}" "$here/test/installer/tuidrive.py" "live@127.0.0.1:"
            "${SSH[@]}" "sudo BROMIGOS_ISO_INSTALL_EXTRA='--ssh-key /home/live/id_ed25519.pub' python3 tuidrive.py plan.json" 2>&1 | tee "$dir/install.out" || rc=$?
        else
            # the graphical installer in the live session, as the live user, on its own script
            # (--script): each step filled in and shown, "::page NAME" when it's on screen
            : > "$dir/install.out"
            "${SSH[@]}" "export XDG_RUNTIME_DIR=/run/user/\$(id -u); export WAYLAND_DISPLAY=\$(basename \$(ls \$XDG_RUNTIME_DIR/wayland-* | grep -v lock | head -1)); BROMIGOS_ISO_INSTALL_EXTRA='--ssh-key /home/live/id_ed25519.pub' bromigos-installer --script plan.json" >> "$dir/install.out" 2>&1 &
            gui=$!
            seen=0
            while kill -0 "$gui" 2>/dev/null; do
                n=$(grep -c '^::page ' "$dir/install.out" || true)
                while (( seen < n )); do
                    seen=$((seen + 1))
                    page=$(grep '^::page ' "$dir/install.out" | sed -n "${seen}p" | awk '{print $2}')
                    shot "gui-$firmware-$mode-$page" >/dev/null
                    "${SSH[@]}" "touch /tmp/bromigos-installer-next" || true
                done
                sleep 1
            done
            wait "$gui" || rc=$?
            grep -E '^(::page|::result|  )' "$dir/install.out" | tail -25
        fi
        finish_install "$rc" || exit $?
        ;;
    keep-files)     # before a reinstall: a file in the installed system's home, to find after it
        # synced: the VM is stopped next, and btrfs would otherwise still hold it in memory
        "${SSH[@]}" 'echo "kept across the reinstall" > ~/keepme.txt && sync && sha256sum ~/keepme.txt' | tee "$dir/keepme.sha256"
        ;;
    data-rollback)      # an update's rollback undoes the system, never the data: a file in a
                        # container volume written after the update's snapshot survives it
        out=$dir/data-rollback-$firmware.out; : > "$out"
        result() { local what=$1; shift; if "$@"; then echo "PASS $what"; else echo "FAIL $what"; fi | tee -a "$out"; }
        vol=/var/lib/containers/storage/volumes/isotest/_data
        "${SSH[@]}" "sudo mkdir -p $vol && echo before | sudo tee $vol/rows >/dev/null && sudo sync"
        pre=$("${SSH[@]}" "sudo snapper -c root create -t pre -p -d 'isotest: an update'" | tr -dc 0-9)
        "${SSH[@]}" "echo an-update | sudo tee /etc/bromigos-isotest-update >/dev/null; echo after | sudo tee -a $vol/rows >/dev/null; sudo sync"
        post=$("${SSH[@]}" "sudo snapper -c root create -t post --pre-number $pre -p -d 'isotest: an update'" | tr -dc 0-9)
        echo "pre $pre, post $post" | tee -a "$out"
        "${SSH[@]}" "sudo snapper -c root undochange $pre..$post" >> "$out" 2>&1
        result "the rollback undid the system's change" "${SSH[@]}" "! test -e /etc/bromigos-isotest-update"
        result "the container volume kept what was written after the snapshot" "${SSH[@]}" "grep -qx after $vol/rows"
        result "root's snapshot doesn't hold the container data" "${SSH[@]}" "! sudo test -e /.snapshots/$pre/snapshot$vol"
        if grep -q FAIL "$out"; then exit 1; fi
        ;;
    verify-reinstall)   # after it: the file, the user's ID, the old system kept as a snapshot
        out=$dir/verify-reinstall-$firmware.out; : > "$out"
        result() { local what=$1; shift; if "$@"; then echo "PASS $what"; else echo "FAIL $what"; fi | tee -a "$out"; }
        result "the home folder's file is still there, unchanged" "${SSH[@]}" "echo '$(awk '{print $1}' "$dir/keepme.sha256")  /home/tester/keepme.txt' | sha256sum -c --quiet"
        result "the user keeps user ID 1000" "${SSH[@]}" "[ \$(id -u) -eq 1000 ]"
        result "the old system is kept as a snapshot (@old-root-…)" "${SSH[@]}" "sudo mount -o subvolid=5 \$(findmnt -no SOURCE / | sed 's/\\[.*//') /mnt && ls /mnt | grep -q '^@old-root-'; r=\$?; sudo umount /mnt; exit \$r"
        if grep -q FAIL "$out"; then exit 1; fi
        ;;
    verify-windows)
        out=$dir/verify-windows-$firmware.out; : > "$out"
        result() { local what=$1; shift; if "$@"; then echo "PASS $what"; else echo "FAIL $what"; fi | tee -a "$out"; }
        "${SCP[@]}" "$dir/windows/c.sha256" "$user@127.0.0.1:c.sha256"
        c=$("${SSH[@]}" "lsblk -rno PATH,LABEL /dev/vda | awk '\$2 == \"Windows\" { print \$1 }'")
        result "Windows' C: is still there ($c)" test -n "$c"
        result "every file on C: is as it was (sha256)" "${SSH[@]}" "sudo mkdir -p /run/win && sudo mount -t ntfs3 -o ro $c /run/win && cd /run/win && sha256sum -c --quiet ~/c.sha256; r=\$?; cd /; sudo umount /run/win; exit \$r"
        result "C:'s NTFS is consistent after the resize (ntfsresize --info, on the medium)" grep -q '^ntfs-check: You might resize at' "$dir/install-state.out"
        result "GRUB's menu has bromigOS and Windows" "${SSH[@]}" "sudo grep -q '^menuentry .bromigOS' /boot/grub/grub.cfg && sudo grep -qE '^menuentry .Windows' /boot/grub/grub.cfg"
        if [[ $firmware == uefi ]]; then
            "${SCP[@]}" "$dir/windows/esp.sha256" "$user@127.0.0.1:esp.sha256"
            result "Windows' boot files on the shared ESP are as they were" "${SSH[@]}" "sudo sh -c 'cd /boot/efi && sha256sum -c --quiet' < ~/esp.sha256"
            if "${SSH[@]}" "sudo test -d /boot/efi/EFI/bromigos-secureboot"; then
                # Secure Boot set up (docs/secureboot.md): shim, then GRUB, in their own folder
                result "shim and GRUB in their own folder on the ESP, and the firmware boots it first" "${SSH[@]}" "sudo test -f /boot/efi/EFI/bromigos-secureboot/grubx64.efi && sudo efibootmgr | grep -q '^BootOrder: '\$(sudo efibootmgr -v | awk 'tolower(\$0) ~ /bromigos-secureboot.shimx64.efi/ && \$0 !~ /Field Kit/ { sub(/^Boot/, \"\"); sub(/\\*.*/, \"\"); print; exit }')"
                result "Windows' fallback loader (EFI/Boot/bootx64.efi) isn't shim's" "${SSH[@]}" "! sudo test -f /boot/efi/EFI/Boot/grubx64.efi"
            else
                result "GRUB in its own folder on the ESP, and the firmware boots it first" "${SSH[@]}" "sudo test -f /boot/efi/EFI/GRUB/grubx64.efi && sudo efibootmgr | grep -q '^BootOrder: '\$(sudo efibootmgr | awk '/GRUB/ { sub(/^Boot/, \"\"); sub(/\\*.*/, \"\"); print; exit }')"
            fi
            result "one EFI system partition on the disk (bromigOS's /boot isn't one)" "${SSH[@]}" "[ \$(lsblk -no PARTTYPE /dev/vda | grep -ci c12a7328-f81f-11d2-ba4b-00a0c93ec93b) -eq 1 ]"
        fi
        if grep -q FAIL "$out"; then exit 1; fi
        ;;
    boot)
        [[ -n $iso ]] || iso=$(cat "$dir/iso.path" 2>/dev/null || true)
        [[ -f $iso ]] || { echo "iso/test.sh boot: --iso FILE" >&2; exit 2; }
        iso=$(realpath "$iso"); printf '%s\n' "$iso" > "$dir/iso.path"
        printf '%s\n' "$hosts" > "$dir/hosts.entry"
        echo live > "$dir/user"; user=live; SSH=(ssh "${sshopts[@]}" "live@127.0.0.1")
        start_vm medium
        wait_ssh 120
        sleep 20                                  # the desktop's own start: the bar, the widgets, the live layer
        shot "live-$firmware"
        "${SCP[@]}" "$here/test/live-checks.sh" "live@127.0.0.1:" && "${SSH[@]}" bash live-checks.sh 2>&1 | tee "$dir/live-checks-$firmware.out"
        ;;
    install)
        [[ -n $repo ]] || repo=$(cat "$dir/repo.url" 2>/dev/null || true)
        printf '%s\n' "$repo" > "$dir/repo.url"
        # the medium's own answers.py writes archinstall's files in the VM: the disk is wiped,
        # btrfs on LUKS2 (the passphrase: the password), GRUB, snapper; sshd for the checks
        "${SCP[@]}" "$key.pub" "live@127.0.0.1:"
        enc=(); (( encrypt )) || enc=(--no-encrypt)
        "${SSH[@]}" "python3 /usr/local/lib/bromigos-iso/answers.py --disk /dev/vda --firmware $firmware --user tester --password tester --hostname bromigos-test --ssh ${enc[*]} --out /home/live/answers"
        # beside another system: the installers' own answers (the backend's format), so the
        # installer does what it does for them (the other system in GRUB's menu, /boot's type)
        if (( alongside )); then
            python3 -c 'import json, sys; print(json.dumps({"schema": 1, "edition": "desktop", "answers_toml": "", "edition_file": None,
                "desktop": True, "disk": "/dev/vda", "mode": "alongside", "esp": "/dev/vda1", "shrink": None, "user": "tester",
                "full_name": "Test Er", "password": "tester", "hostname": "bromigos-test", "encrypt": sys.argv[1] == "1",
                "old_passphrase": None, "passphrase": None, "keymap": "us", "xkb_layout": "us", "xkb_variant": "", "locale": "en_US",
                "timezone": "UTC", "ssh": True, "online": False, "ssh_password": False, "ssh_keys": [open(sys.argv[2]).read().strip()],
                "firewall": False, "auto_updates": False, "auto_update_units": [], "advanced": {}, "user_commands": [],
                "default_target": "graphical.target", "other_os": True,
                # the installers first step, as they send it (common.guidance_files: all off)
                "guidance": {"voice_guide": {"enabled": False, "muted": False},
                             "accessibility": {"screen_reader": False, "large_text": False, "high_contrast": False,
                                               "reduce_motion": False, "console_font": False, "applied": False}}}))' \
                "$encrypt" "$key.pub" > "$dir/answers.json"
            "${SCP[@]}" "$dir/answers.json" "live@127.0.0.1:answers.json"
        fi
        printf '%s\n' "$((encrypt ? 1 : 0))" > "$dir/encrypted"
        # the medium's channel: the installed system follows it (the checks look for it)
        "${SSH[@]}" "cat /etc/bromigos-iso/channel 2>/dev/null || echo stable" > "$dir/channel"
        extra=(); [[ -n $repo ]] && extra+=(--repo "$repo")
        if [[ -n $ca ]]; then "${SCP[@]}" "$ca" "live@127.0.0.1:repo-ca.crt"; extra+=(--ca /home/live/repo-ca.crt); fi
        rc=0
        how=(--config /home/live/answers/config.json --creds /home/live/answers/creds.json); (( alongside )) && how=(--answers /home/live/answers.json)
        "${SSH[@]}" "sudo bromigos-iso-install ${how[*]} --ssh-key /home/live/id_ed25519.pub --no-reboot ${extra[*]}" 2>&1 | tee "$dir/install.out" || rc=$?
        # Secure Boot set up (docs/secureboot.md): the code that approves the key at the first start
        sed -n 's/^::secureboot \([0-9]*\)$/\1/p' "$dir/install.out" | tail -1 > "$dir/secureboot-code"
        # beside a stand-in Windows: its C: checked where the tools are (the medium), as finish_install does
        : > "$dir/install-state.out"
        (( alongside )) && "${SSH[@]}" 'c=$(lsblk -rno PATH,LABEL /dev/vda | awk "\$2 == \"Windows\" { print \$1 }"); [ -n "$c" ] && sudo ntfsresize --info --force --no-progress-bar "$c" | grep "You might resize at" | sed "s/^/ntfs-check: /"' >> "$dir/install-state.out" 2>&1
        # what the new system got, while it's still mounted at /mnt (install-state.out)
        "${SSH[@]}" 'sudo bash -c "findmnt -R /mnt; lsblk -o NAME,TYPE,FSTYPE,MOUNTPOINTS /dev/vda; ls -la /mnt/home/*/.ssh; grep -h ^HOOKS= /mnt/etc/mkinitcpio.conf /mnt/etc/mkinitcpio.conf.d/*.conf; lsinitcpio /mnt/boot/initramfs-linux.img | grep -c plymouth; grep -E ^GRUB_CMDLINE /mnt/etc/default/grub; grep -c snapshots /mnt/boot/grub/grub.cfg; grep -A2 bromigos\\] /mnt/etc/pacman.conf; arch-chroot /mnt snapper --no-dbus list-configs; arch-chroot /mnt sshd -T 2>/dev/null | grep -iE \"^(pubkeyauthentication|authorizedkeysfile|passwordauthentication)\""' 2>&1 | tee -a "$dir/install-state.out" || true
        # a clean shutdown: the new system's file systems unmounted, LUKS closed, then
        # poweroff (killing QEMU would lose what's still in the page cache)
        "${SSH[@]}" 'sudo sync; sudo umount -R /mnt; sudo cryptsetup close root 2>/dev/null; sudo systemctl poweroff' 2>/dev/null || true
        for _ in $(seq 90); do [[ -z $(vm_pids) ]] && break; sleep 1; done
        "$0" down --dir "$dir"
        exit "$rc"
        ;;
    boot-disk)
        echo tester > "$dir/user"; user=tester; SSH=(ssh "${sshopts[@]}" "tester@127.0.0.1")
        [[ -n $hosts ]] || hosts=$(cat "$dir/hosts.entry" 2>/dev/null || true)
        start_vm disk
        encrypted=$(cat "$dir/encrypted" 2>/dev/null || echo 1)
        if (( encrypted )); then
            sleep "${BROMIGOS_ISOTEST_PASS_WAIT:-25}"   # the splash asks for the disk's passphrase (a slow VM: longer)
            shot "passphrase-$firmware"
            type_keys "tester"
        fi
        if [[ $(cat "$dir/edition" 2>/dev/null || echo desktop) == server ]]; then
            # bromigOS Server: the text console, then its checks over SSH (no desktop, no update run)
            wait_ssh 60
            sleep 5; shot "server-console-$firmware"
            "${SSH[@]}" "echo tester | sudo -S -p '' sh -c 'echo \"tester ALL=(ALL) NOPASSWD: ALL\" > /etc/sudoers.d/99-isotest && chmod 440 /etc/sudoers.d/99-isotest'"
            "${SCP[@]}" "$here/test/live-checks.sh" "tester@127.0.0.1:"
            rc=0
            "${SSH[@]}" "bash live-checks.sh server $( (( encrypted )) && echo encrypted || echo plain)" 2>&1 | tee "$dir/checks-$firmware.out" || rc=$?
            exit "$rc"
        fi
        sleep 40                                 # the system comes up to the login screen
        shot "login-$firmware"                   # the Bromigos login screen
        click 640 501; type_text "tester"        # the account field, then the passphrase (Enter signs in)
        click 640 534; type_keys "tester"
        sleep 25                                 # the session: Hyprland, the bar, the widgets, the live layer
        shot "desktop-$firmware"
        wait_ssh 60
        # the checks use sudo without a terminal: the test user gets it without a password
        # (the harness's, not the installer's: an installed system asks)
        "${SSH[@]}" "echo tester | sudo -S -p '' sh -c 'echo \"tester ALL=(ALL) NOPASSWD: ALL\" > /etc/sudoers.d/99-isotest && chmod 440 /etc/sudoers.d/99-isotest'"
        if [[ -n $hosts ]]; then "${SSH[@]}" "grep -qxF '$hosts' /etc/hosts || echo '$hosts' | sudo tee -a /etc/hosts >/dev/null"; fi
        "${SCP[@]}" "$root/test/vm/checks.sh" "$here/test/live-checks.sh" "tester@127.0.0.1:"
        rc=0
        medium_channel=$(cat "$dir/channel" 2>/dev/null || echo stable)
        "${SSH[@]}" "CHANNEL=$medium_channel bash live-checks.sh desktop $( (( encrypted )) && echo encrypted || echo plain); r=\$?; bash checks.sh; exit \$((r + \$?))" 2>&1 | tee "$dir/checks-$firmware.out" || rc=$?
        # the theme previews' render log, when their check failed (it names what the nested desktop said)
        if grep -q "^FAIL the theme switcher" "$dir/checks-$firmware.out"; then
            "${SSH[@]}" 'tail -n 80 ~/.cache/bromigos/theme-previews/render.log 2>/dev/null; ls -la /dev/dri 2>&1' > "$dir/previews-render-$firmware.log" 2>&1 || true
        fi
        # BROMIGOS_ISOTEST_NO_UPDATE=1: the installed system's checks only (the installers' own
        # tests: the update and the rollback are the same whichever installer made the system)
        if [[ ${BROMIGOS_ISOTEST_NO_UPDATE:-0} == 1 ]]; then exit "$rc"; fi
        # the first update, from the network (Enter at each of pacman's questions: its
        # defaults), then what it left: snapshots around it, in GRUB's menu, recorded for
        # --rollback. It moves to the other channel (a transaction is what makes snapshots,
        # and the medium's channel may have nothing newer): edge from a stable medium; from
        # an edge medium to stable, a move to an older channel, after the installed channel's
        # databases are synced (a newer bromigos.db than the older channel's: what made such
        # a move fail "signature is invalid")
        if [[ -z $update_channel ]]; then
            if "${SSH[@]}" "grep -A2 '^\[bromigos\]' /etc/pacman.conf | grep -q '/stable/'"; then update_channel=edge; else update_channel=stable; fi
        fi
        # the system's repository, swapped for a reachable copy of it for the update only: its
        # [bromigos] Server's base, the channel's path kept (the installed-system checks above
        # saw the address the medium gave it)
        if [[ -n $update_repo ]]; then
            if [[ -n $ca ]]; then
                "${SCP[@]}" "$ca" "tester@127.0.0.1:update-ca.crt"
                "${SSH[@]}" "sudo install -Dm0644 update-ca.crt /etc/ca-certificates/trust-source/anchors/isotest-update-ca.crt && sudo update-ca-trust"
            fi
            "${SSH[@]}" "sudo python3 - '$update_repo'" <<'PY'
import re, sys
p = "/etc/pacman.conf"
out, sect = [], ""
for line in open(p).read().split("\n"):
    if line.startswith("["):
        sect = line.strip()
    if sect == "[bromigos]":
        line = re.sub(r"^Server = \S+?(/\$repo(?:/[a-z]+)?/\$arch)$", lambda m: "Server = " + sys.argv[1] + m.group(1), line)
    out.append(line)
open(p, "w").write("\n".join(out))
PY
            "${SSH[@]}" "grep -A2 '^\[bromigos\]' /etc/pacman.conf" | sed 's/^/update repository: /'
        fi
        "${SSH[@]}" "sudo pacman -Sy" > "$dir/sync-$firmware.out" 2>&1 || rc=$?
        before=$("${SSH[@]}" "pacman -Q bromigos-core")
        "${SSH[@]}" "yes '' | bromigos update --channel $update_channel" > "$dir/update-$firmware.out" 2>&1 || rc=$?
        tail -15 "$dir/update-$firmware.out"
        if grep -q 'signature is invalid' "$dir/update-$firmware.out"; then echo "FAIL the update: signature is invalid"; rc=1; fi
        "${SSH[@]}" "CHANNEL=$update_channel bash live-checks.sh updated" 2>&1 | tee "$dir/updated-$firmware.out" || rc=$?
        # and undone: `bromigos update --rollback` puts / back as it was before (snapper's
        # undochange over the pair), pacman's database and all
        "${SSH[@]}" "bromigos update --rollback --yes < /dev/null" > "$dir/rollback-$firmware.out" 2>&1 || rc=$?
        after=$("${SSH[@]}" "pacman -Q bromigos-core")
        if [[ $after == "$before" ]]; then echo "PASS rolled back: $after again"; else echo "FAIL rolled back: $after, not $before"; rc=1; fi | tee -a "$dir/updated-$firmware.out"
        [[ $after == "$before" ]] || rc=1
        exit "$rc"
        ;;
    menu)
        # the medium's boot menu, then one channel booted (docs/boot.md): the same six first
        # entries on UEFI's GRUB and BIOS's vesamenu
        entry=${1:-live}
        case $entry in live) n=0 ;; install) n=1 ;; text) n=2 ;; safe) n=3 ;; memtest) n=4 ;; disk) n=5 ;; speech) n=6 ;;
            *) echo "iso/test.sh menu: live, install, text, safe, memtest, disk or speech" >&2; exit 2 ;; esac
        [[ -n $iso ]] || iso=$(cat "$dir/iso.path" 2>/dev/null || true)
        [[ -f $iso ]] || { echo "iso/test.sh menu: --iso FILE (once)" >&2; exit 2; }
        iso=$(realpath "$iso"); printf '%s\n' "$iso" > "$dir/iso.path"
        echo live > "$dir/user"; user=live; SSH=(ssh "${sshopts[@]}" "live@127.0.0.1")
        out=$dir/menu-$entry-$firmware.out; : > "$out"
        result() { local what=$1; shift; if "$@"; then echo "PASS $what"; else echo "FAIL $what"; fi | tee -a "$out"; }
        on_line() { grep -qw -- "$1" <<<"$cmdline"; }
        running() { "${SSH[@]}" "pgrep -f '$1'" >/dev/null; }
        start_vm medium
        result "the medium's boot menu ($firmware)" menu_wait "menu-$firmware"
        keys=$(for _ in $(seq 1 "$n"); do printf 'down,'; done)
        menu_wait "menu-$firmware-$entry" "$keys" >/dev/null || true
        press ret
        case $entry in
            live|install|text|safe|speech)
                result "$entry boots (SSH)" wait_ssh 60
                sleep 20; shot "$entry-$firmware" >/dev/null
                cmdline=$("${SSH[@]}" cat /proc/cmdline)
                case $entry in
                    live) result "live: the desktop (Hyprland)" running '^Hyprland'
                          result "live: no installer on the kernel line" bash -c "! grep -qw bromigos.install <<<'$cmdline'" ;;
                    install) result "install: bromigos.install on the kernel line" on_line bromigos.install
                             result "install: the graphical installer, full screen" running 'bromigos_installer.gui' ;;
                    text) result "text: bromigos.install=text on the kernel line" on_line bromigos.install=text
                          result "text: no desktop (no login screen)" bash -c "! ssh ${sshopts[*]} live@127.0.0.1 pgrep -x sddm >/dev/null"
                          result "text: the text installer on tty1" running 'bromigos_installer.tui'
                          shot "text-$firmware-tty1" >/dev/null ;;
                    safe) result "safe: nomodeset on the kernel line" on_line nomodeset ;;
                    speech) result "speech: accessibility=on on the kernel line" on_line accessibility=on ;;
                esac
                ;;
            memtest) sleep 15; shot "memtest-$firmware" >/dev/null
                     result "memtest: Memtest86+ runs (no Linux comes up)" bash -c "! ssh ${sshopts[*]} live@127.0.0.1 true 2>/dev/null" ;;
            disk) sleep 8          # the medium's own menu gone: what shows now is the disk's
                  result "disk: the installed system's GRUB menu (its theme's bar)" menu_wait "disk-$firmware" "" --coloured ;;
        esac
        "$0" down --dir "$dir"
        if grep -q FAIL "$out"; then exit 1; fi
        ;;
    param)
        # the boot menu's "Install bromigOS" with more on its kernel line (GRUB's editor on UEFI,
        # syslinux's Tab on BIOS), as the direct install entries pass them: then which installer
        # opened, and with what (docs/iso.md, "Boot parameters")
        params=${1:?iso/test.sh param "PARAMETERS"}; shift || true
        [[ -n $iso ]] || iso=$(cat "$dir/iso.path" 2>/dev/null || true)
        iso=$(realpath "$iso"); printf '%s\n' "$iso" > "$dir/iso.path"
        echo live > "$dir/user"; user=live; SSH=(ssh "${sshopts[@]}" "live@127.0.0.1")
        tag=$(tr -c 'a-z0-9' '-' <<<"$params" | sed 's/-*$//')
        out=$dir/param-$tag-$firmware.out; : > "$out"
        result() { local what=$1; shift; if "$@"; then echo "PASS $what"; else echo "FAIL $what"; fi | tee -a "$out"; }
        running() { "${SSH[@]}" "pgrep -f '$1'" >/dev/null; }
        start_vm medium
        menu_wait "param-$tag-$firmware" "down" >/dev/null || true
        if [[ $firmware == uefi ]]; then
            sleep 1; press e; sleep 2; shot "param-$tag-$firmware-editor" >/dev/null
            # GRUB's editor: setparams, a blank line, set gfxpayload, then the linux line; Ctrl+E
            # is its end of line
            press down; press down; press down; press ctrl-e; type_text " $params"; sleep 1; shot "param-$tag-$firmware-edited" >/dev/null; press ctrl-x
        else
            press tab; sleep 1; type_text " $params"; press ret
        fi
        result "boots (SSH)" wait_ssh 60
        sleep 30; shot "param-$tag-$firmware" >/dev/null
        cmdline=$("${SSH[@]}" cat /proc/cmdline)
        for w in $params; do result "$w on the kernel line" grep -qw -- "$w" <<<"$cmdline"; done
        case " $params " in
            *" bromigos.edition=server "*|*" bromigos.text "*)
                result "the text installer on tty1" running 'bromigos_installer.tui'
                result "no graphical installer" bash -c "! ssh ${sshopts[*]} live@127.0.0.1 pgrep -f bromigos_installer.gui >/dev/null" ;;
            *) result "the graphical installer" running 'bromigos_installer.gui' ;;
        esac
        case " $params " in
            *" bromigos.edition=server "*) result "bromigOS Server preselected" "${SSH[@]}" "PYTHONPATH=/usr/local/lib/bromigos-iso python3 -c 'from bromigos_installer import common; import sys; sys.exit(common.defaults()[\"edition\"] != \"server\")'" ;;
        esac
        [[ ${BROMIGOS_ISOTEST_KEEP:-0} == 1 ]] || "$0" down --dir "$dir"      # _KEEP=1: it stays up (an answer file's install)
        if grep -q FAIL "$out"; then exit 1; fi
        ;;
    grub)
        # the installed system's GRUB menu (docs/boot.md), waited for and saved; the VM stays
        echo tester > "$dir/user"
        [[ -n $(vm_pids) ]] || start_vm disk
        menu_wait "grub-${1:-menu}" "${2:-down,up}" ${3:-}
        ;;
    up)
        echo tester > "$dir/user"; user=tester; SSH=(ssh "${sshopts[@]}" "tester@127.0.0.1")
        press ret
        passphrase_then_ssh
        ;;
    mok-enroll)
        # the installed system's first start with Secure Boot on (docs/secureboot.md): MokManager
        # asks to enroll its key; a person presses a key, Enroll MOK, Continue, Yes, the code, Reboot
        code=${1:?iso/test.sh mok-enroll CODE}
        echo tester > "$dir/user"; user=tester; SSH=(ssh "${sshopts[@]}" "tester@127.0.0.1")
        [[ -n $(vm_pids) ]] || start_vm disk
        rc=0
        blue_wait 120 || { echo "iso/test.sh mok-enroll: no MokManager screen"; shot mokm-none >/dev/null; exit 1; }
        shot mokm-1-press-any-key >/dev/null; press spc
        sleep 2; shot mokm-2-menu >/dev/null; press down; press ret                # Enroll MOK
        sleep 2; shot mokm-3-enroll-mok >/dev/null; press down; press ret          # Continue
        sleep 2; shot mokm-4-enroll-the-keys >/dev/null; press down; press ret     # Yes
        sleep 2; shot mokm-5-password >/dev/null; type_text "$code"; press ret     # the code
        sleep 2; shot mokm-6-reboot >/dev/null; press ret                          # Reboot
        # then the boot menu, which must be the theme's (its fonts are inside the signed GRUB)
        menu_wait grub-secureboot "" --coloured || rc=1
        press ret
        passphrase_then_ssh || rc=1
        exit "$rc"
        ;;
    shot) shot "${1:-screen}" ;;
    press) press "$1" ;;                          # a key, e.g. shift-tab, meta_l-ret
    click) click "$1" "$2" ;;                     # the pointer at X Y (of 1280x800), a left click
    type) type_keys "$1" ;;                       # text, then Return
    ssh) "${SSH[@]}" "$@" ;;
    down)       # every QEMU of this directory (by its monitor socket), not just the last pidfile's
        pids=$(vm_pids); [[ -z $pids ]] || kill $pids 2>/dev/null || true
        rm -f "$dir/qemu.pid"; sleep 1 ;;
    destroy) "$0" down --dir "$dir" || true; rm -f "$dir/disk.qcow2" "$dir/OVMF_VARS.fd" "$dir/user" "$dir/firmware" ;;
    *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
