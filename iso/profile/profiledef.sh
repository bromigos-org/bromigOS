#!/usr/bin/env bash
# shellcheck disable=SC2034
# The bromigOS live and install medium: archiso's releng profile (copied by iso/build.sh,
# which overlays this directory on it) with bromigOS on top. docs/iso.md, docs/boot.md.

iso_name="bromigos"
iso_label="BROMIGOS_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="bromigOS <https://github.com/bromigos-org/bromigOS>"
iso_application="bromigOS live and install medium"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="bromigos"
# BIOS: syslinux's vesamenu; UEFI: GRUB, with bromigOS's boot theme (docs/boot.md). Both
# menus are bromigOS's (profile grub/ and syslinux/; the theme is rendered at build)
bootmodes=('bios.syslinux'
           'uefi.grub')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
# zstd, not releng's xz: the offline repository is most of the image and is zstd already
# (incompressible); zstd keeps the build to minutes and the live system's reads quick
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '6' '-b' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
# Plymouth's splash on the live boot; `quiet` keeps the kernel's lines off it (the journal
# has them; the tty gets them again if the splash fails)
kernel_params_x86_64="splash quiet"
kernel_params_aarch64="clk_ignore_unused pd_ignore_unused arm64.nopauth"
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/customize_airootfs.sh"]="0:0:755"
  ["/usr/local/bin/bromigos-iso-install"]="0:0:755"
  ["/usr/local/bin/bromigos-iso-autostart"]="0:0:755"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
  ["/usr/local/bin/livecd-sound"]="0:0:755"
)
