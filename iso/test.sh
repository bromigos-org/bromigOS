#!/usr/bin/env bash
# The ISO's boot and install test (docs/iso.md), on any machine with KVM, headless: QEMU
# with -display none, screenshots through its monitor to DIR/shots/, never a window.
#
#   iso/test.sh boot    --iso FILE [--firmware uefi|bios] [--hosts "IP NAME"]
#                       boots the medium (a test build: iso/build.sh --test-key DIR/id_ed25519.pub),
#                       waits for the live desktop, screenshots it, runs the live checks
#   iso/test.sh install [--repo URL] [--ca FILE] [--no-encrypt]
#                       the unattended install onto the VM's disk, over SSH (btrfs on
#                       LUKS2 by default; --no-encrypt: plain btrfs)
#   iso/test.sh boot-disk [--firmware uefi|bios] [--update-channel NAME]
#                       boots the installed system, signs in at the login screen (QMP keys),
#                       screenshots it, runs test/vm/checks.sh in it, then the first update
#                       (to NAME; default the other channel: edge from stable, else stable)
#                       and a rollback of it
#   iso/test.sh menu ENTRY  the medium's boot menu (UEFI GRUB or BIOS syslinux) saved, then one
#                       channel booted and checked: live, install (the installer opens),
#                       safe (nomodeset), memtest, disk (the installed system's GRUB), speech
#   iso/test.sh grub NAME [KEYS]   boots the installed disk and saves its GRUB menu as
#                       shots/grub-NAME.png (KEYS first, e.g. down,down,ret: the snapshots);
#                       the VM stays at the menu
#   iso/test.sh up      from that menu: boots the default entry, the passphrase, SSH
#   iso/test.sh shot NAME | ssh [cmd…] | down | destroy
#
# The VM: 6 GB, 4 CPUs, virtio-gpu (Mesa's software renderer), a 40 GB disk, user
# networking with SSH on localhost:2223. UEFI boots use edk2-ovmf's firmware (a private
# copy of its variables); BIOS boots use SeaBIOS. Everything lives in DIR (default
# ~/.cache/bromigos-isotest): the key, the disk, the console log, shots/. Beside another
# run: BROMIGOS_ISOTEST_DIR, _PORT (SSH), _VNC (display) and _MEM (MiB, 6144); BROMIGOS_ISOTEST_QEMU adds QEMU
# arguments (a faked laptop: -smbios file=… from test/vm/smbios-chassis.py; docs/hardware.md),
# BROMIGOS_ISOTEST_VGA the display device (default virtio-vga; e.g. virtio-vga,xres=1024,yres=768
# offers the firmware that mode, which GRUB's GFXMODE=auto takes).
# The VM stops when the session that started it ends (test/vm/vm-keeper.py):
# BROMIGOS_VM_OWNER=PID ties it to another process, BROMIGOS_VM_OWNER=none keeps it until down.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/.." && pwd)
dir=${BROMIGOS_ISOTEST_DIR:-$HOME/.cache/bromigos-isotest}
port=${BROMIGOS_ISOTEST_PORT:-2223}
ovmf_code=/usr/share/edk2/x64/OVMF_CODE.4m.fd
ovmf_vars=/usr/share/edk2/x64/OVMF_VARS.4m.fd

cmd=${1:-}; shift || true
iso='' firmware='' hosts='' repo='' ca='' encrypt=1 update_channel='' 
while (($#)); do
    case $1 in
        --iso) iso=$2; shift 2 ;; --firmware) firmware=$2; shift 2 ;; --hosts) hosts=$2; shift 2 ;;
        --repo) repo=$2; shift 2 ;; --ca) ca=$2; shift 2 ;; --dir) dir=$2; shift 2 ;; --no-encrypt) encrypt=0; shift ;;
        --update-channel) update_channel=$2; shift 2 ;; *) break ;;
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
SCP=(scp "${sshopts[@]/-p/-P}")
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
    else
        boot=(-boot "order=c")
    fi
    : > "$dir/console.log"
    # through vm-keeper.py: QEMU stops when whoever started the test is gone
    # (BROMIGOS_VM_OWNER=none keeps it until down)
    # shellcheck disable=SC2086  # BROMIGOS_ISOTEST_QEMU is words (a faked laptop: -smbios file=…)
    "$root/test/vm/vm-keeper.py" --ready "$dir/qmp.sock" --log "$dir/keeper.log" -- \
        qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -m "${BROMIGOS_ISOTEST_MEM:-6144}" -smp 4 "${fw[@]}" ${BROMIGOS_ISOTEST_QEMU:-} \
        -drive "file=$dir/disk.qcow2,if=virtio" "${cd[@]}" "${boot[@]}" \
        -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:$port-:22" \
        -device "${BROMIGOS_ISOTEST_VGA:-virtio-vga}" -device qemu-xhci -device usb-tablet -display none -vnc "127.0.0.1:${BROMIGOS_ISOTEST_VNC:-48}" \
        -qmp "unix:$dir/qmp.sock,server,nowait" -serial "file:$dir/console.log" \
        -pidfile "$dir/qemu.pid"
    printf '%s\n' "$firmware" > "$dir/firmware"
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

passphrase_then_ssh() {     # after GRUB: the disk's passphrase at the splash, then SSH
    if (( $(cat "$dir/encrypted" 2>/dev/null || echo 1) )); then
        sleep 25
        type_keys "tester"
    fi
    wait_ssh 60
}

case $cmd in
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
        printf '%s\n' "$((encrypt ? 1 : 0))" > "$dir/encrypted"
        # the medium's channel: the installed system follows it (the checks look for it)
        "${SSH[@]}" "cat /etc/bromigos-iso/channel 2>/dev/null || echo stable" > "$dir/channel"
        extra=(); [[ -n $repo ]] && extra+=(--repo "$repo")
        if [[ -n $ca ]]; then "${SCP[@]}" "$ca" "live@127.0.0.1:repo-ca.crt"; extra+=(--ca /home/live/repo-ca.crt); fi
        rc=0
        "${SSH[@]}" "sudo bromigos-iso-install --config /home/live/answers/config.json --creds /home/live/answers/creds.json --ssh-key /home/live/id_ed25519.pub --no-reboot ${extra[*]}" 2>&1 | tee "$dir/install.out" || rc=$?
        # what the new system got, while it's still mounted at /mnt (install-state.out)
        "${SSH[@]}" 'sudo bash -c "findmnt -R /mnt; lsblk -o NAME,TYPE,FSTYPE,MOUNTPOINTS /dev/vda; ls -la /mnt/home/*/.ssh; grep -h ^HOOKS= /mnt/etc/mkinitcpio.conf /mnt/etc/mkinitcpio.conf.d/*.conf; lsinitcpio /mnt/boot/initramfs-linux.img | grep -c plymouth; grep -E ^GRUB_CMDLINE /mnt/etc/default/grub; grep -c snapshots /mnt/boot/grub/grub.cfg; grep -A2 bromigos\\] /mnt/etc/pacman.conf; arch-chroot /mnt snapper --no-dbus list-configs; arch-chroot /mnt sshd -T 2>/dev/null | grep -iE \"^(pubkeyauthentication|authorizedkeysfile|passwordauthentication)\""' 2>&1 | tee "$dir/install-state.out" || true
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
            sleep 25                             # the splash asks for the disk's passphrase
            shot "passphrase-$firmware"
            type_keys "tester"
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
        case $entry in live) n=0 ;; install) n=1 ;; safe) n=2 ;; memtest) n=3 ;; disk) n=4 ;; speech) n=5 ;;
            *) echo "iso/test.sh menu: live, install, safe, memtest, disk or speech" >&2; exit 2 ;; esac
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
            live|install|safe|speech)
                result "$entry boots (SSH)" wait_ssh 60
                sleep 20; shot "$entry-$firmware" >/dev/null
                cmdline=$("${SSH[@]}" cat /proc/cmdline)
                case $entry in
                    live) result "live: the desktop (Hyprland)" running '^Hyprland'
                          result "live: no installer on the kernel line" bash -c "! grep -qw bromigos.install <<<'$cmdline'" ;;
                    install) result "install: bromigos.install on the kernel line" on_line bromigos.install
                             result "install: the installer's terminal" running 'kitty --class bromigos-iso-install'
                             result "install: the installer, asking" running '^bash /usr/local/bin/bromigos-iso-install' ;;
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
    grub)
        # the installed system's GRUB menu (docs/boot.md), waited for and saved; the VM stays
        echo tester > "$dir/user"
        [[ -n $(vm_pids) ]] || start_vm disk
        menu_wait "grub-${1:-menu}" "${2:-down,up}"
        ;;
    up)
        echo tester > "$dir/user"; user=tester; SSH=(ssh "${sshopts[@]}" "tester@127.0.0.1")
        press ret
        passphrase_then_ssh
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
