#!/usr/bin/env bash
# Runs once, inside the live image's chroot, at the end of mkarchiso's package step
# (iso/build.sh). Makes the live desktop's user and seeds its configs, sets the splash,
# and leaves the test hooks only on a test build (iso/build.sh --test-key).
set -euo pipefail

# ── the live user: `live`, no password, sudo without one (a live medium; the installed
#    system's user is the installer's, with a password and the login screen)
if ! id live >/dev/null 2>&1; then
    useradd -m -u 1000 -G wheel,video,audio,input,render -s /usr/bin/zsh -c "bromigOS live" live
fi
passwd -d live >/dev/null
printf 'live ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/live
chmod 440 /etc/sudoers.d/live

# ── bromigOS for that user: the thin configs, the desktop settings and the theme, the way
#    `bromigos install` does them on a fresh machine (docs/install.md); the packages are
#    installed already (packages.x86_64), so pacman has nothing to add. Then the first-run
#    answers a live medium can give (live-answers.toml). No services: the live image's
#    units are the profile's (sddm.conf.d/live.conf signs the user in).
pacman -Sy --noconfirm >/dev/null                      # the offline repository's databases
# (a chroot has no session bus: the desktop-settings step's gsettings may report a failure
# there; the configs and the theme are what matter here, and they're checked below)
sudo -u live -H bromigos install --yes --no-services --no-setup --theme wick \
    || echo "customize_airootfs: bromigos install reported a failure (the chroot: see /home/live/.local/state/bromigos/install.log)"
sudo -u live -H bromigos setup --answers /usr/local/share/bromigos-iso/live-answers.toml
test -f /home/live/.config/hypr/hyprland.lua -a -f /home/live/.config/waybar/config \
    || { echo "customize_airootfs: the live user's configs weren't seeded" >&2; exit 1; }
sudo -u live -H bromigos theme current | grep -qx wick \
    || { echo "customize_airootfs: the theme isn't set" >&2; exit 1; }
# nothing idles over someone trying or installing bromigOS (docs/idle.md): no screensaver
# and no lock on the live session (the live user has no password to unlock with). The
# displays still go dark after a while, and any input wakes them. The welcome card, the
# installer and full-screen windows hold idle off too (hyprland.lua's idle_inhibit rules).
sudo -u live -H bromigos idle set screensaver off lock off --no-restart >/dev/null
grep -qzE '\[screensaver\]\s*enabled = false.*\[lock\]\s*enabled = false' /home/live/.config/bromigos/idle.toml \
    || { echo "customize_airootfs: the live user's idle policy isn't set" >&2; exit 1; }
# `bromigos update` would nudge the live user after the install step's pacman: no need
rm -f /home/live/.local/state/bromigos/restart-* 2>/dev/null || true
# the boot menu's "Install bromigOS" (bromigos.install): the live session opens the installer
# (bromigos-iso-autostart, from the live user's Hyprland autostart; any other boot, nothing)
sed -i 's|^\( *\)-- autostart = { },|\1autostart = { "/usr/local/bin/bromigos-iso-autostart" },|' /home/live/.config/hypr/hyprland.lua
grep -q '^ *autostart = { "/usr/local/bin/bromigos-iso-autostart" },' /home/live/.config/hypr/hyprland.lua \
    || { echo "customize_airootfs: the installer's autostart isn't in the live user's hyprland.lua" >&2; exit 1; }

# the installer's ways in on the live desktop: its Install icon (a panel of the live user's:
# a click opens the installer) and the app launcher's entry (/usr/local/share/applications)
install -Dm0644 -o live -g live /usr/local/share/bromigos-iso/install-panel.py \
    /home/live/.config/bromigos/plugins/widgets/install.py
chown -R live:live /home/live/.config/bromigos

# ── the splash: bromigos-settings' Plymouth theme on the live boot (the hook is in
#    /etc/mkinitcpio.conf.d/archiso.conf; mkarchiso builds the initramfs after this script)
if command -v plymouth-set-default-theme >/dev/null; then
    plymouth-set-default-theme bromigos
fi

# ── the live keyring: bromigOS's key is trusted at boot by pacman-init.service
#    (releng), which populates every keyring under /usr/share/pacman/keyrings

# ── a test build only (iso/build.sh --test-key): the harness signs in over SSH as `live`
if [[ -s /etc/bromigos-iso/test_authorized_keys ]]; then
    install -d -m 700 -o live -g live /home/live/.ssh
    install -m 600 -o live -g live /etc/bromigos-iso/test_authorized_keys /home/live/.ssh/authorized_keys
    rm -f /etc/bromigos-iso/test_authorized_keys
    systemctl enable sshd.service >/dev/null 2>&1 || true
fi

echo "customize_airootfs: the live user and its desktop are ready"
