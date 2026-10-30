#!/usr/bin/env bash
# Run in the test VM after install.sh (test/vm/arch-vm.sh check): what a fresh install must
# have. Prints PASS/FAIL per check; exits with the number of failures.
fails=0
check() { local name=$1; shift; if "$@" >/tmp/check.out 2>&1; then echo "PASS $name"; else echo "FAIL $name"; sed 's/^/     /' /tmp/check.out | tail -8; fails=$((fails + 1)); fi; }

check "packages installed" pacman -Q bromigos bromigos-core bromigos-desktop bromigos-settings bromigos-live bromigos-widgets bromigos-vector ttf-geist-mono
check "pacman -Qk clean (bromigOS packages)" bash -c "! pacman -Qk bromigos bromigos-core bromigos-desktop bromigos-settings bromigos-live bromigos-widgets bromigos-vector ttf-geist-mono 2>&1 | grep -v ' 0 missing files'"
check "every dependency satisfied (pacman -Dk)" pacman -Dk
check "fonts: Geist Mono" bash -c "fc-list | grep -q 'Geist Mono'"
check "fonts: MesloLGM Nerd Font Propo" bash -c "fc-list | grep -q 'MesloLGM Nerd Font Propo'"
# SDDM's effective theme: its config files in its own reading order, the last Current= wins
# shellcheck disable=SC2329  # called through check
sddm_theme() {
  local f v cur=''
  for f in /usr/lib/sddm/sddm.conf.d/* /etc/sddm.conf.d/* /etc/sddm.conf; do
    [ -f "$f" ] || continue
    v=$(grep -h '^Current=' "$f" | tail -1)
    [ -n "$v" ] && cur=$v
  done
  [ "$cur" = Current=bromigos ]
}
check "the desktop menu's tree (bromigos-menu --dump)" bash -c "bromigos-menu --dump | grep -q '^STYLE'"
# The previews draw the real desktop nested on the GPU. A VM whose display has no 3D (QEMU's
# virtio-vga, as the ISO's tests and CI give it) can't start that desktop, and the previews
# say so (GpuLost) and try again later: on a virtual machine that's a SKIP, not a failure;
# anywhere else it fails.
previews=$(bromigos theme previews wick --force --json 2>&1)
if grep -q '"pieces"' <<<"$previews"; then
  echo "PASS the theme switcher's preview of the Wick is drawn offscreen"
elif grep -q 'GpuLost' <<<"$previews" && systemd-detect-virt -q --vm; then
  echo "SKIP the theme switcher's preview of the Wick is drawn offscreen (a VM with no 3D: the nested desktop can't start)"
else
  echo "FAIL the theme switcher's preview of the Wick is drawn offscreen"
  tail -4 <<<"$previews" | sed 's/^/     /'
  fails=$((fails + 1))
fi
check "web apps: the catalog" bash -c "bromigos-webapp catalog | grep -q chatgpt"
check "the on-screen display is installed" command -v swayosd-server
check "the OSD's style is rendered by theme set" test -f "$HOME/.local/state/bromigos/theme/current/swayosd.css"
check "SDDM enabled" systemctl is-enabled sddm
check "SDDM's effective theme is Bromigos" sddm_theme
check "NetworkManager or another network manager enabled" bash -c "systemctl is-enabled NetworkManager || systemctl is-enabled systemd-networkd"
check "the thin configs seeded" test -f "$HOME/.config/hypr/hyprland.lua" -a -f "$HOME/.config/waybar/config"
check "Hyprland config verifies" Hyprland --verify-config -c "$HOME/.config/hypr/hyprland.lua"
# the shortcut picker (bromigos keys; docs/desktop.md, "Shortcuts you set by pressing the
# keys"): it reads the config as installed, the capture's submap ships in the defaults, a bind
# and a reset leave the file as it was
check "bromigos keys reads the config (SUPER + SPACE is the menu)" bash -c "bromigos keys check 'SUPER + SPACE' | grep -q 'Desktop menu (a bromigOS default)'"
check "the capture submap is in the defaults" grep -q 'define_submap("bromigos-capture"' /usr/share/bromigos/default/hypr/bromigos/binds.lua
# (the keys are written in bromigos keys' own order, SUPER ALT CTRL SHIFT, whatever order they
# were typed in; the reset runs even when a step before it fails, so a rerun starts clean)
# shellcheck disable=SC2016  # the inner bash expands them
check "bromigos keys: a bind, then reset, the file back byte for byte" bash -c 'f=$HOME/.config/hypr/hyprland.lua; cp "$f" /tmp/hl.before || exit 1; bromigos keys bind "SUPER + CTRL + ALT + J" --exec true && bromigos keys check "SUPER + CTRL + ALT + J" | grep -qx "SUPER + ALT + CTRL + J: true (your shortcut)" && grep -qF "K.exec(\"SUPER + ALT + CTRL + J\", \"true\")" "$f"; ok=$?; bromigos keys reset --yes && cmp "$f" /tmp/hl.before && exit $ok'
check "a theme is set (wick)" bash -c "bromigos theme current | grep -qx wick"
check "the emblem link" test -d "$HOME/.local/state/bromigos/emblem/lock"
check "the wallpaper link (the packaged den)" bash -c "readlink -f ~/.local/state/bromigos/wallpaper/den.jpg | grep -q /usr/share/bromigos/wallpaper/"
check "the wall link swaybg shows (the Wick: the den itself)" bash -c "[ \"\$(readlink -f ~/.local/state/bromigos/wallpaper/wall.jpg)\" = \"\$(readlink -f ~/.local/state/bromigos/wallpaper/den.jpg)\" ]"
check "setup monitors: the block in hyprland.lua" grep -q 'bromigos.monitors = {' "$HOME/.config/hypr/hyprland.lua"
check "setup monitors: the primary" grep -q '^primary = ' "$HOME/.config/bromigos/monitors.toml"
check "Hyprland config verifies with the block" Hyprland --verify-config -c "$HOME/.config/hypr/hyprland.lua"
check "setup create: create.toml, format 1, all off" bash -c "grep -qx 'format = 1' ~/.config/bromigos/create.toml && ! grep -q comfyui ~/.config/bromigos/create.toml"
check "VECTOR's voice off" test -f "$HOME/.local/state/bromigos/vector-voice-muted"
check "theme set mire" bromigos theme set mire --no-reload
check "back to wick" bromigos theme set wick --no-reload
# extensions (docs/extensions.md): one data (a theme: no question) and one that runs code (a
# widget: refused without a person at a terminal, approved by an answers file), from starters
# shellcheck disable=SC2329  # called through check (declare -f)
ext_repo() {  # KIND NAME: a starter, committed in its own repository under /tmp/vm-ext
  local d=/tmp/vm-ext/$2
  rm -rf "$d" && bromigos ext new "$1" "$2" --dir "$d" >/dev/null &&
    git -C "$d" init -q -b main && git -C "$d" add -A &&
    git -C "$d" -c user.name=vm -c user.email=vm@localhost commit -qm "$2 0.1.0"
}
check "ext: a theme installs without a question" bash -c "$(declare -f ext_repo); ext_repo theme vm-teal && bromigos ext install /tmp/vm-ext/vm-teal </dev/null"
check "ext: the theme is listed and sets" bash -c "bromigos theme list | grep -q 'vm-teal.*ext' && bromigos theme set vm-teal --no-reload && bromigos theme set wick --no-reload"
check "ext: code is refused without a yes" bash -c "$(declare -f ext_repo); ext_repo widget vm-panel && ! bromigos ext install /tmp/vm-ext/vm-panel </dev/null && ! bromigos ext list | grep -q vm-panel"
check "ext: an answers file approves it, recorded" bash -c "printf '[extensions]\ninstall = [\"/tmp/vm-ext/vm-panel\"]\napprove = true\n' > /tmp/vm-ext/answers.toml && bromigos setup extensions --answers /tmp/vm-ext/answers.toml && grep -q '\"how\": \"answers\"' ~/.local/state/bromigos/ext/ledger.json"
check "ext: the widget renders from its link" bash -c "test -L ~/.local/share/bromigos/ext/active/widgets/vm_panel.py && bromigos-widgets render vm_panel /tmp/vm-ext/panel.png"
check "ext: list --verify is clean" bash -c "bromigos ext list --verify | grep vm-panel | grep -q ' ok '"
check "ext: remove unlinks" bash -c "bromigos ext remove vm-panel && bromigos ext remove vm-teal && ! test -e ~/.local/share/bromigos/ext/active/widgets/vm_panel.py && ! test -e ~/.local/share/bromigos/ext/src/vm-teal"
check "bromigos update --check" bromigos update --check
# rolling back (docs/update.md), where / is btrfs: bromigos install's rollback step set it up
if [ "$(findmnt -no FSTYPE /)" = btrfs ]; then
  check "rollback: snapper's root configuration" bash -c "snapper list-configs | grep -q '^root '"
  check "rollback: the user may list root's snapshots (updates are recorded)" snapper -c root list
  check "rollback: snap-pac's hooks" test -f /usr/share/libalpm/hooks/05-snap-pac-pre.hook
  # the overlay hook goes in a busybox (udev) initramfs; a systemd one (Arch's cloud image) runs
  # no such hook, and setup says so instead
  check "rollback: grub-btrfs-overlayfs in HOOKS and the initramfs (or, systemd's, setup's note)" bash -c "if grep -hE '^HOOKS=' /etc/mkinitcpio.conf /etc/mkinitcpio.conf.d/*.conf 2>/dev/null | tail -1 | grep -qw udev; then grep -hE '^HOOKS=' /etc/mkinitcpio.conf /etc/mkinitcpio.conf.d/*.conf 2>/dev/null | grep -q grub-btrfs-overlayfs && sudo lsinitcpio /boot/initramfs-linux.img | grep -q overlay; else bromigos rollback setup --dry-run | grep -q \"initramfs is systemd's\"; fi"
  check "rollback: status as the user, GRUB's menu lists them" bash -c "bromigos rollback status | grep -qE '^snapshots: .*boot menu: GRUB lists them \(grub-btrfs\)'"
  check "rollback: nothing left to set up" bash -c "! bromigos rollback status | grep -q 'setup: bromigos rollback setup'"
fi
check "install again is a no-op" bash -c "bromigos install --yes --no-setup 2>&1 | tee /dev/stderr | grep -E '^(ok|done|would)' >/dev/null"
# the app bundle, when the install asked for it (BROMIGOS_VM_WITH=bromigos-apps)
if pacman -Q bromigos-apps >/dev/null 2>&1; then
  check "bromigos-apps: defaults installed" test -f /usr/share/bromigos/default/apps/nvim/init.lua -a -f /usr/share/bromigos/default/apps/tmux/tmux.conf
  check "bromigos-apps: the user's thin files seeded (migration)" bash -c "grep -q default/apps ~/.config/nvim/init.lua && grep -q default/apps ~/.config/tmux/tmux.conf && test -f ~/.config/lazygit/config.yml"
  check "bromigos-apps: setup is idempotent" bash -c "bromigos apps setup | grep -q kept && ! bromigos apps setup | grep -q seeded"
  check "bromigos-apps: the theme renders the apps' files" test -f ~/.local/state/bromigos/theme/current/btop.theme -a -f ~/.local/state/bromigos/theme/current/nvim.lua -a -f ~/.local/state/bromigos/theme/current/tmux.conf
  check "bromigos-apps: tmux loads the defaults and the theme" bash -c "tmux -L vmcheck -f ~/.config/tmux/tmux.conf start-server \; kill-server"
  check "bromigos-apps: the neovim colorscheme applies" bash -c "nvim --headless -u NONE -c 'lua local m = dofile(os.getenv(\"HOME\") .. \"/.local/state/bromigos/theme/current/nvim.lua\"); assert(vim.g.colors_name == \"bromigos\")' -c q"
fi
exit $fails
