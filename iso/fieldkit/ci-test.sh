#!/usr/bin/env bash
# Field Kit's own test in the ISO workflow (iso/ci-test.sh --suite hook, after the menu test):
#
#   iso/fieldkit/ci-test.sh ISO DIR
#
# The medium as built (no test key): QEMU starts its kernel with the kernel line of its menu's
# entry and the console on the serial port too (iso/fieldkit/test.py up --direct), with no
# network. UEFI, headless.
#
#   1. Field Kit starts: its console on the first screen, Home drawn, the engine and the
#      scripted CLI answer, the offline store carries bromigOS Server
#   2. "Install bromigOS Server": the installer's own backend (bromigos-iso-install --answers,
#      the answers the text installer would hand it) installs Server offline onto the VM's disk
#   3. the installed Server boots to its console and passes its checks
#
# DIR gets shots/, each VM's folder (serial logs) and the output; the disk is removed at the
# end. Runs in iso/ci-test.sh's container (QEMU, OVMF, xorriso, ImageMagick), or anywhere
# with those and KVM.
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
iso=$(realpath "${1:?ISO}"); out=${2:?DIR}
mkdir -p "$out"; out=$(realpath "$out")
export BROMIGOS_FIELDKIT_TEST_DIR=$out/vm BROMIGOS_FIELDKIT_SHOTS=$out/shots BROMIGOS_FIELDKIT_HOST_RULES=0
export BROMIGOS_VM_OWNER=${BROMIGOS_VM_OWNER:-none}
T=$here/test.py
fails=0
step() {            # step NAME CMD…: runs it, says PASS or FAIL, goes on
    local name=$1; shift
    echo "::group::$name"
    if "$@"; then echo "::endgroup::"; echo "PASS $name"; else echo "::endgroup::"; echo "FAIL $name"; fails=$((fails + 1)); return 1; fi
}
run() { local n=$1; shift; "$T" run --name "$n" --timeout "${TIMEOUT:-300}" -- "$@"; }

# ── 1. Field Kit starts ─────────────────────────────────────────────────────────────────
live() {
    "$T" up --name live --iso "$iso" --firmware uefi --direct --mem 3072 --vga "virtio-vga,xres=1280,yres=800" || return 1
    "$T" wait-serial --name live "login:" --timeout 300 || return 1
    sleep 15
    "$T" shot --name live fieldkit-home
    "$T" login --name live --timeout 60 >/dev/null || return 1
    run live 'set -e
        test -e /etc/bromigos-fieldkit/medium
        systemctl is-active kmsconvt@tty1.service || systemctl is-active getty@tty1.service
        pgrep -fa "bromigos fieldkit" | head -2
        grep -qw bromigos.edition=server /proc/cmdline
        ls /var/lib/bromigos/repo/bromigos/x86_64/ | grep -E "^bromigos-(server|fieldkit-tools|boot)-[0-9]"
        fieldkit overview --json | python3 -c "import json,sys; d = json.load(sys.stdin); print(sorted(d)[:8])"
        fieldkit repair black-screen --dry-run --json | python3 -c "import json,sys; json.load(sys.stdin); print(\"black-screen: ok\")"
        fieldkit disks --json | python3 -c "import json,sys; json.load(sys.stdin); print(\"disks: ok\")"
        test "$(systemctl is-system-running || true)" != maintenance
        echo LIVE-OK'
}

# ── 2. bromigOS Server, installed offline ───────────────────────────────────────────────
disk=$out/vm/server.qcow2
install() {
    rm -f "$disk"
    "$T" up --name install --iso "$iso" --firmware uefi --direct --mem 3584 --disk "$disk" --disk-size 24G || return 1
    "$T" wait-serial --name install "login:" --timeout 300 || return 1
    "$T" login --name install --timeout 60 >/dev/null || return 1
    # the answers the text installer hands the backend for: Server (preselected on this
    # stick), the whole disk, encrypted, a user tester (password tester)
    TIMEOUT=60 run install "PYTHONPATH=/usr/local/lib/bromigos-iso python3 - <<'PY'
import json
from bromigos_installer import common
a = common.defaults()
assert a['edition'] == 'server', a['edition']
a.update(disk='/dev/vda', mode='erase', user='tester', full_name='Test Er', password='tester',
         hostname='fkserver', encrypt=False, ssh=False)
b = common.backend_answers(a, None)
assert not b['online'], 'bromigOS Server should install with no network from this stick'
json.dump(b, open('/root/answers.json', 'w'))
print('answers:', b['edition'], b['default_target'], b['auto_update_units'])
PY" || return 1
    # the installer runs on its own (setsid), so a console that hangs up can't stop it; this
    # looks in every 30 s, signing in again if it must, for an hour at most
    run install 'setsid nohup bash -c "bromigos-iso-install --answers /root/answers.json --no-reboot > /root/install.log 2>&1; echo \$? > /root/install.rc" >/dev/null 2>&1 < /dev/null & echo started' || return 1
    local rc='' out
    for _ in $(seq 120); do
        sleep 30
        out=$(TIMEOUT=40 run install 'echo "S:$(grep -E "^::(stage|error)" /root/install.log | tail -1)"; echo "R:$(cat /root/install.rc 2>/dev/null)"' 2>&1) \
            || { "$T" login --name install --timeout 60 >/dev/null 2>&1; continue; }
        echo "  $(sed -n 's/^S://p' <<<"$out")"
        rc=$(sed -n 's/^R://p' <<<"$out" | tr -dc 0-9)
        [[ -n $rc ]] && break
    done
    echo "installer: ${rc:-no answer after an hour}"
    [[ $rc == 0 ]] || { run install 'tail -60 /root/install.log; tail -40 /var/log/bromigos-iso-install.log' || true; return 1; }
    # what the harness needs from the installed system: the console on the serial port too
    run install 'set -e
        t=/mnt; findmnt $t >/dev/null
        arch-chroot $t pacman -Q bromigos-server bromigos-boot bromigos-fieldkit-tools kmscon
        arch-chroot $t systemctl get-default
        arch-chroot $t systemctl is-enabled bromigos-server-update.timer
        # the welcome tour waits for the first sign-in (its screens are checked by its own
        # --render); the harness signs in on the serial console, so it goes now
        ls $t/home/tester/.local/state/bromigos/welcome-pending
        rm -f $t/home/tester/.local/state/bromigos/welcome-pending
        sed -i -E "s/^GRUB_CMDLINE_LINUX_DEFAULT=\"([^\"]*)\"/GRUB_CMDLINE_LINUX_DEFAULT=\"\1 console=tty0 console=ttyS0,115200\"/" $t/etc/default/grub
        arch-chroot $t grub-mkconfig -o /boot/grub/grub.cfg >/dev/null 2>&1
        sync; umount -R $t; echo INSTALLED' || return 1
    "$T" down --name install >/dev/null
    sleep 3
}

# ── 3. the installed Server ─────────────────────────────────────────────────────────────
server() {
    "$T" up --name server --firmware uefi --mem 3072 --disk "$disk" --boot disk --vga "virtio-vga,xres=1280,yres=800" || return 1
    sleep 12; "$T" shot --name server server-grub
    "$T" wait-serial --name server "login:" --timeout 300 || return 1
    sleep 10; "$T" shot --name server server-console
    "$T" login --name server --user tester --password tester --timeout 60 >/dev/null || return 1
    run server 'set -e
        systemctl get-default | grep -qx multi-user.target
        ! systemctl is-active -q display-manager.service
        systemctl is-active kmsconvt@tty1.service || systemctl is-active getty@tty1.service
        systemctl is-active bromigos-server-firewall.service
        systemctl is-enabled bromigos-server-update.timer
        ls /etc/snapper/configs/root
        grep -q "More ways to start" /boot/grub/grub.cfg
        test "$(systemctl is-system-running || true)" != maintenance
        echo SERVER-OK'
}

step "Field Kit starts (offline): console, Home, engine, offline store" live || true
"$T" down --name live >/dev/null 2>&1 || true
if step "bromigOS Server installs from the stick with no network" install; then
    step "the installed bromigOS Server boots to its console" server || true
fi
"$T" down --name install >/dev/null 2>&1 || true
"$T" down --name server >/dev/null 2>&1 || true
rm -f "$disk" "$out"/vm/*/OVMF_VARS.fd "$out"/vm/*/vmlinuz "$out"/vm/*/initramfs.img
echo "==> Field Kit: $fails failed"
((fails == 0))
