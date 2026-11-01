#!/usr/bin/env bash
# Run in the booted medium (iso/test.sh boot) or the installed system (iso/test.sh
# boot-disk, with the argument `desktop` [encrypted|plain]): the live desktop must be up.
# `updated`: after the installed system's first `bromigos update` (docs/iso-encryption.md).
# PASS/FAIL per check; exits with the number of failures.
mode=${1:-live}
fails=0
channel_is() {   # channel_is stable|rc|edge: [bromigos]'s Server line is that channel's (install.sh's form)
    local sub=/$1; [[ $1 == edge ]] && sub=''
    grep -A2 '^\[bromigos\]' /etc/pacman.conf | grep -qE "^Server = https?://[^ ]+/\\\$repo$sub/\\\$arch\$"
}
check() { local name=$1; shift; if "$@" >/tmp/check.out 2>&1; then echo "PASS $name"; else echo "FAIL $name"; sed 's/^/     /' /tmp/check.out | tail -6; fails=$((fails + 1)); fi; }
# the data a rollback mustn't touch (containers, k3s, /srv, the update history), each in its
# own subvolume, so outside root's snapshots: on both editions
data_subvolumes() {
    local name path
    while read -r name path; do
        check "$path is its own subvolume ($name), outside root's snapshots" bash -c "findmnt -no SOURCE $path | grep -qF '[/$name]'"
    done <<'LIST'
@containers /var/lib/containers
@k3s /var/lib/rancher
@srv /srv
@bromigos-state /var/lib/bromigos/server
LIST
}

if [[ $mode == updated ]]; then
    # the update went to ${CHANNEL:-edge}: from the medium's channel to the other one, an older one too
    check "the update's channel: [bromigos] on ${CHANNEL:=edge}" channel_is "$CHANNEL"
    check "snap-pac's pre/post pair around the update" bash -c "sudo snapper --no-dbus -c root list --columns type | grep -q pre && sudo snapper --no-dbus -c root list --columns type | grep -q post"
    check "GRUB's menu lists the snapshots (grub-btrfs.cfg)" bash -c "for _ in \$(seq 30); do sudo grep -q 'snapshots/' /boot/grub/grub-btrfs.cfg 2>/dev/null && exit 0; sleep 2; done; exit 1"
    check "grub.cfg sources grub-btrfs.cfg" sudo grep -q 'grub-btrfs.cfg' /boot/grub/grub.cfg
    check "the update recorded for --rollback (as the user: snapper's ALLOW_GROUPS)" bash -c "bromigos rollback status | tee /dev/stderr | grep -qE '^ +pre [0-9]+ '"
    check "bromigos update --check after it" bromigos update --check
    exit $fails
fi

if [[ $mode == server ]]; then         # bromigOS Server: no desktop, the disk as the desktop's, its protection
    check "no desktop: no Hyprland, no login screen" bash -c "! pgrep -x Hyprland && ! systemctl is-enabled -q sddm 2>/dev/null"
    check "starts to the text console (multi-user.target)" bash -c "systemctl get-default | grep -qx multi-user.target"
    check "the root is btrfs" bash -c "findmnt -no FSTYPE / | grep -qx btrfs"
    data_subvolumes
    if [[ ${2:-encrypted} == encrypted ]]; then
        check "the root is on LUKS2" bash -c "sudo cryptsetup status root | grep -qE 'type: +LUKS2'"
    fi
    check "snapper's root config (bromigos rollback setup)" bash -c "sudo snapper --no-dbus list-configs | grep -q '^root '"
    check "GRUB lists the snapshots (grub-btrfs)" bash -c "pacman -Q grub-btrfs && systemctl is-enabled grub-btrfsd"
    check "no splash on the kernel line" bash -c "! grep -qw splash /proc/cmdline"
    check "SSH is on and lets the key in" test -s "$HOME/.ssh/authorized_keys"
    check "SSH: keys only (no passwords)" bash -c "sudo sshd -T | grep -qix 'passwordauthentication no'"   # OpenSSH 10 prints it capitalised
    check "the firewall is on (nftables), SSH open" bash -c "systemctl is-active -q nftables || systemctl is-active -q bromigos-server-firewall; sudo nft list ruleset | grep -q 'dport 22'"
    check "the lab console is installed" command -v bromigos-lab
    check "the install's answers kept, without the password" bash -c "test -s /var/log/bromigos/install-answers.toml && ! grep -qE '^(password|passphrase) ' /var/log/bromigos/install-answers.toml"
    exit $fails
fi

check "Hyprland is running" pgrep -x Hyprland
check "the bar (waybar)" pgrep -x waybar
check "the widgets" pgrep -f 'python3? /usr/bin/bromigos-widgets'
check "the live layer" pgrep -f 'python3? -m live.app'
# swaybg is the fallback: a working live background removes it (desktop/bin/bromigos-wallpaper)
check "the background (the live layer, or swaybg in its place)" bash -c "pgrep -x swaybg || pgrep -f 'python3? -m live.app'"
check "the login screen's service (sddm)" pgrep -x sddm
check "the theme is wick" bash -c "bromigos theme current | grep -qx wick"
check "the splash theme is bromigos" bash -c "plymouth-set-default-theme | grep -qx bromigos"
check "Hyprland config verifies" Hyprland --verify-config -c "$HOME/.config/hypr/hyprland.lua"
check "VECTOR is installed" pacman -Q bromigos-vector
if [[ $mode == desktop ]]; then       # the installed system (docs/iso-encryption.md's checks)
    check "the root is btrfs" bash -c "findmnt -no FSTYPE / | grep -qx btrfs"
    check "the subvolumes (@, @home, @.snapshots)" bash -c "sudo btrfs subvolume list / | grep -qE 'path @\$' && sudo btrfs subvolume list / | grep -q 'path @home' && findmnt -no FSTYPE /.snapshots | grep -qx btrfs"
    data_subvolumes
    # how the installer's first step left the guidance, for the welcome tour (docs/voice-guide.md)
    # (only an installer's answers carry that step: an install from archinstall's own files, as
    # the tests' first one is, has no such choice to keep)
    if [[ -e /var/log/bromigos/install-answers.toml ]]; then
        check "the guidance choices kept for the new user" bash -c "test -s \$HOME/.local/state/bromigos/voice-guide.json && test -s \$HOME/.local/state/bromigos/accessibility.json"
    else
        echo "SKIP the guidance choices kept for the new user (installed from archinstall's own files: no installer's first step)"
    fi
    if [[ ${2:-encrypted} == encrypted ]]; then
        check "the root is on LUKS (crypt under the partition)" bash -c "lsblk -no TYPE | grep -qx crypt"
        check "LUKS2 under the root (cryptsetup status root)" bash -c "sudo cryptsetup status root | grep -qE 'type: +LUKS2'"
    else
        check "no LUKS (--no-encrypt)" bash -c "! lsblk -no TYPE | grep -qx crypt"
    fi
    check "snapper's root config" bash -c "sudo snapper --no-dbus list-configs | grep -q '^root '"
    check "snapper's home config" bash -c "sudo snapper --no-dbus list-configs | grep -q '^home '"
    check "the user may list root's snapshots (wheel)" snapper -c root list
    check "snapper's root config: wheel in ALLOW_GROUPS, SYNC_ACL (bromigos rollback setup)" bash -c "snapper --csvout -c root get-config --columns key,value | grep -qE '^ALLOW_GROUPS,(.* )?wheel( |\$)' && snapper --csvout -c root get-config --columns key,value | grep -qx 'SYNC_ACL,yes'"
    check "the sync databases dated 1970 until the first -Sy" bash -c "[ \$(stat -c %Y /var/lib/pacman/sync/core.db) -lt 86400 ]"
    check "snap-pac's hooks" test -f /usr/share/libalpm/hooks/05-snap-pac-pre.hook
    check "grub-btrfs and its daemon" bash -c "pacman -Q grub-btrfs inotify-tools && systemctl is-enabled grub-btrfsd"
    check "GRUB boots it, with splash on the kernel line" bash -c "sudo grep -q 'splash' /boot/grub/grub.cfg && grep -qw splash /proc/cmdline"
    check "the initramfs has Plymouth (and the theme)" bash -c "sudo lsinitcpio /boot/initramfs-linux.img | grep -q 'usr/share/plymouth/themes/bromigos/bromigos.script'"
    check "the initramfs has grub-btrfs-overlayfs (booting a snapshot)" bash -c "grep -hE '^HOOKS=' /etc/mkinitcpio.conf /etc/mkinitcpio.conf.d/*.conf 2>/dev/null | grep -q grub-btrfs-overlayfs && sudo lsinitcpio /boot/initramfs-linux.img | grep -q overlay"
    check "the user's thin configs (bromigos install in the chroot)" test -f "$HOME/.config/hypr/hyprland.lua"
    check "bromigos rollback status" bromigos rollback status
    # archinstall's UEFI /boot (the ESP) is 0700: as the user GRUB is seen without it
    boot_seen=$(test -r /boot/grub/grub.cfg && echo "/boot readable" || echo "/boot unreadable to the user")
    check "the boot menu lists snapshots (rollback status as the user; $boot_seen)" bash -c "bromigos rollback status | grep -qE '^snapshots: .*boot menu: GRUB lists them \(grub-btrfs\)\$'"
    check "rollback status: nothing left to set up" bash -c "! bromigos rollback status | grep -q 'setup: bromigos rollback setup'"
    check "sshd let the test key in (the installer's --ssh-key)" test -s "$HOME/.ssh/authorized_keys"
    # the installers keep their answers (an unattended --config install has none to keep)
    if [[ -e /var/log/bromigos/install-answers.toml ]]; then
        check "the install's answers kept, without the password" bash -c "! grep -qE '^(password|passphrase)' /var/log/bromigos/install-answers.toml"
    fi
    check "the repository: [bromigos] on the ${CHANNEL:=stable} channel" channel_is "$CHANNEL"
    check "no offline-copy servers left (file://)" bash -c "! grep -q 'file:///var/lib/bromigos' /etc/pacman.conf /etc/pacman.d/mirrorlist"
    check "one [bromigos] section" bash -c "[ \$(grep -c '^\[bromigos\]' /etc/pacman.conf) -eq 1 ]"
fi
if [[ $mode == live ]]; then
    check "the offline repository: Arch's core and extra, bromigOS" test -f /var/lib/bromigos/repo/core/os/x86_64/core.db -a -f /var/lib/bromigos/repo/extra/os/x86_64/extra.db -a -f /var/lib/bromigos/repo/bromigos/x86_64/bromigos.db
    # a live medium has no synced databases until something syncs them (archinstall does): sync, then resolve
    check "pacman resolves bromigos from the medium (offline)" bash -c "sudo pacman -Sy >/dev/null 2>&1 && pacman -Sp bromigos 2>/dev/null | grep -q '^file:///var/lib/bromigos/repo/'"
    # pacman-init (releng's) fills the keyring once the clock is set: after time-sync.target,
    # which can take a minute or more after boot
    check "bromigOS's key is trusted" bash -c "for _ in \$(seq 90); do systemctl is-active -q pacman-init && break; sleep 2; done; pacman-key --list-keys 2>/dev/null | grep -qi bromigos"
    check "the installer is there" test -x /usr/local/bin/bromigos-iso-install
    check "archinstall is there" command -v archinstall
    check "the live user has no password and sudo" bash -c "sudo -n true"
    # nothing idles over someone trying or installing bromigOS (docs/idle.md): the live user's
    # policy has no screensaver and no lock, and the welcome card holds idle off as well
    check "the live session never starts a screensaver or locks on idle" bash -c "f=\$HOME/.local/state/bromigos/idle/hypridle.conf; test -s \$f && ! grep -qE 'on-timeout = (bromigos-live ctl screensaver open|loginctl lock-session)' \$f"
    check "the welcome card holds an idle inhibitor (Hyprland's idle_inhibit)" bash -c "bromigos session exec hyprctl -j clients | python3 -c 'import json, sys; sys.exit(not any(c.get(\"class\") == \"org.bromigos.InstallerWelcome\" and c.get(\"inhibitingIdle\") for c in json.load(sys.stdin)))'"
fi
exit $fails
