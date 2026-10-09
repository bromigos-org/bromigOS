# The boot menu's entries say bromigOS (docs/boot.md). The boot theme's block in
# /etc/default/grub now sets GRUB_DISTRIBUTOR, so grub-mkconfig names the installed
# system's entries "bromigOS Linux" instead of "Arch Linux". /etc/os-release stays Arch
# Linux's. bromigos-settings' pacman hook brings an older block up to date when the package
# upgrades; this does it where the hook couldn't (grub-mkconfig failed, say). Only where the
# theme is on: `bromigos boot theme off` takes the block out, and the name with it. The root
# helper keeps a copy of /etc/default/grub and checks the new grub.cfg; sudo asks on the
# terminal, like the update's other root steps.
set -u
helper=/usr/lib/bromigos/boot/bromigos-boot-theme
[ -x "$helper" ] || exit 0          # no bromigos-settings: no boot theme here
outdated() {                        # 0: the block is an older one; 1: it's current or not there
    case $("$helper" status --json 2>/dev/null) in
        *'"block_outdated": true'*) return 0 ;;
        *'"block_outdated": false'*) return 1 ;;
        *) echo "bromigos-settings is older than this migration: the next update tries again"; exit 75 ;;
    esac
}
outdated || exit 0
if sudo "$helper" refresh; then
    outdated && echo "the boot menu's block is left as it is (above: why)"   # GRUB doesn't boot this machine, say
    exit 0
fi
echo "the boot menu is unchanged; the next update tries again (or: sudo $helper refresh)" >&2
exit 75
