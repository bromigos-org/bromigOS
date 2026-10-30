#!/usr/bin/env bash
# shellcheck disable=SC2034
# bromigOS Field Kit: bromigOS without the desktop, the small medium for repairs, the lab and
# installing bromigOS Server (docs/fieldkit.md). archiso's releng profile, overlaid with this
# directory by iso/build-in-container.sh (iso/build.sh --edition fieldkit).

iso_name="bromigos-fieldkit"
iso_label="BROMIGOS_FIELD_KIT"
iso_publisher="bromigOS <https://github.com/bromigos-org/bromigOS>"
iso_application="bromigOS Field Kit: repair, lab and server"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="fieldkit"
bootmodes=('bios.syslinux'
           'uefi.grub')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
# zstd at its high levels: the offline store is most of the image and is zstd already; the
# rest packs about as well as xz, and unpacks faster on old machines
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '19' '-b' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
# no splash: the console from the first line, in DRIFTGLASS's 16 colours from the kernel's first
# message (vt.default_*: the Wick's terminal colours, as bromigos-boot's palette.vtrgb).
# nouveau stays off (the firmware's display, or kmscon on it, instead of a driver that needs
# NVIDIA's large firmware)
kernel_params_x86_64="module_blacklist=nouveau vt.default_red=0,255,57,212,90,201,63,180,78,255,156,240,140,227,138,230 vt.default_grn=5,118,255,175,169,123,224,200,107,157,255,211,202,168,245,245 vt.default_blu=0,111,20,55,230,219,197,180,78,151,138,106,245,239,226,230"
kernel_params_aarch64="clk_ignore_unused pd_ignore_unused arm64.nopauth"
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/customize_airootfs.sh"]="0:0:755"
  ["/usr/local/bin/bromigos-iso-install"]="0:0:755"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
  ["/usr/local/bin/livecd-sound"]="0:0:755"
)
