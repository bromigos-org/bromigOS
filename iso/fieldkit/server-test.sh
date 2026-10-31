#!/usr/bin/env bash
# bromigOS Server installed from Field Kit with no network, then everything that needs an
# install (docs/fieldkit.md, "Testing it"), in QEMU through iso/fieldkit/test.py:
#
#   iso/fieldkit/server-test.sh install ISO     Field Kit (no network) installs bromigOS Server
#                                               onto the VM's disk, encrypted, from its offline
#                                               store: archinstall with edition.json's packages
#                                               and services, as the installer's --edition server
#                                               would; /boot 2 GiB, as the installer is asked to
#   iso/fieldkit/server-test.sh image PKG       adds the bromigos-fieldkit package (iso/fieldkit/package.sh's)
#                                               to the installed system, from a second disk
#   iso/fieldkit/server-test.sh boot            boots the installed system and checks it
#
# The VM's folder is $BROMIGOS_FIELDKIT_TEST_DIR/server; its disk server.qcow2. The test user is
# tester (password tester), the disk's passphrase tester. A test medium (iso/build.sh
# --test-key) has its console on the serial port; the installed system gets it too.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
T=$here/test.py
base=${BROMIGOS_FIELDKIT_TEST_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bromigos-fieldkit-test/vm}
disk=$base/server/server.qcow2
name=server

run() { "$T" run --name "$name" --timeout "${TIMEOUT:-1800}" -- "$@"; }

install() {
    local iso=$1
    rm -f "$disk"
    "$T" up --name "$name" --iso "$iso" --firmware uefi --disk "$disk" --disk-size 24G --mem 3584
    "$T" wait-serial --name "$name" "login:" --timeout 300
    "$T" login --name "$name"
    steps
    "$T" down --name "$name"
}

steps() {           # the install itself, in a Field Kit VM that's up and signed in
    run 'systemctl start pacman-init.service; python3 /usr/local/lib/bromigos-iso/answers.py --disk /dev/vda --user tester --password tester --hostname fkserver --firmware uefi --out /tmp/a >/dev/null && ls /tmp/a'
    # the edition: edition.json's packages and services in place of the desktop's; /boot 2 GiB
    run "python3 - <<'PY'
import json
c = json.load(open('/tmp/a/config.json'))
e = json.load(open('/usr/share/bromigos/fieldkit/edition.json'))
c['packages'] = e['packages']
c['services'] = [s for s in e['services']]
c['audio_config'] = None
for mod in c['disk_config']['device_modifications']:
    parts = mod['partitions']
    for p in parts:
        if p.get('mountpoint') == '/boot':
            p['size']['value'] = 2
    for p in parts:
        if p.get('mountpoint') != '/boot':
            p['start']['value'] = p['start']['value'] + 1024
            if p['size']['unit'] == 'GiB':
                p['size']['value'] -= 1
json.dump(c, open('/tmp/a/config.json', 'w'), indent=1)
print(len(c['packages']), 'packages;', c['services'])
PY"
    TIMEOUT=3600 run 'archinstall --config /tmp/a/config.json --creds /tmp/a/creds.json --offline --skip-ntp --skip-wkd --skip-version-check --skip-wifi-check --silent >/tmp/archinstall.log 2>&1; echo archinstall: $?; tail -3 /tmp/archinstall.log; ls /mnt/etc/pacman.d >/dev/null && echo installed'
    # what bromigos-iso-install does after archinstall, for bromigOS Server (edition.json):
    # snapper for /home, rollback setup, the user's terminal apps, text mode; and for the harness:
    # the serial console and root's password
    run 'set -e
        t=/mnt
        printf "tester ALL=(ALL) NOPASSWD: ALL\n" > $t/etc/sudoers.d/90-bromigos-iso-install; chmod 440 $t/etc/sudoers.d/90-bromigos-iso-install
        arch-chroot $t snapper --no-dbus -c home create-config /home
        arch-chroot $t snapper --no-dbus -c home set-config ALLOW_GROUPS=wheel SYNC_ACL=yes
        arch-chroot $t sudo -u tester -H bromigos rollback setup --yes
        arch-chroot $t sudo -u tester -H /usr/lib/bromigos/bin/bromigos-apps-setup || true
        arch-chroot $t systemctl set-default multi-user.target
        arch-chroot $t /usr/lib/bromigos/boot/bromigos-boot-theme on --theme wick --auto
        sed -i -E "s/^GRUB_CMDLINE_LINUX_DEFAULT=\"([^\"]*)\"/GRUB_CMDLINE_LINUX_DEFAULT=\"\1 console=tty0 console=ttyS0,115200\"/" $t/etc/default/grub
        arch-chroot $t grub-mkconfig -o /boot/grub/grub.cfg >/dev/null 2>&1
        echo root:root | arch-chroot $t chpasswd
        arch-chroot $t pacman -Q bromigos-server bromigos-boot bromigos-fieldkit-tools kmscon
        grep -c "Advanced boot options" $t/boot/grub/grub.cfg
        sync; umount -R $t; cryptsetup close root 2>/dev/null || true; echo done'
}

image() {
    local pkg=$1 img=$base/server/fieldkit-pkg.img
    local d; d=$(mktemp -d "$base/server/pkg.XXXXXX")
    rm -f "$img"; cp "$pkg" "$d/"
    # an ext4 disk made from a folder (mke2fs -d): no mounting, no root
    truncate -s $(( $(stat -c %s "$pkg") + 268435456 )) "$img"
    mkfs.ext4 -q -L FKPKG -d "$d" "$img"
    rm -rf "$d"
    echo "$img"
}

case ${1:-} in
    install) shift; install "$@" ;;
    steps) steps ;;
    image) shift; image "$@" ;;
    *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
