# The boot menu (docs/boot.md): bromigOS's GRUB theme, in the theme's colours, on machines
# installed before it existed, the way `bromigos install` and `bromigos setup` turn it on
# now. Only where GRUB boots the machine (systemd-boot and limine keep their own menus), and
# never where `bromigos boot theme off` turned it off. The root helper copies the theme into
# /boot/grub/themes/bromigos, adds bromigOS's block to /etc/default/grub (a copy of the
# file before is kept as /etc/default/grub.bromigos-bak) and makes grub.cfg again, checked;
# it asks sudo on the terminal, like the update's other root steps.
set -u
if [ ! -x /usr/lib/bromigos/boot/bromigos-boot-theme ]; then
    echo "bromigos-settings has no boot theme yet: the next update tries again"
    exit 75
fi
out=$(bromigos boot theme on --auto 2>&1)
rc=$?
printf '%s\n' "$out"
if [ $rc -eq 0 ]; then
    exit 0
fi
echo "the boot menu is unchanged; the next update tries again (or: bromigos boot theme on)" >&2
exit 75
