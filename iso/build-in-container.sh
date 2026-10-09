#!/usr/bin/env bash
# The ISO build proper, run by iso/build.sh inside a privileged archlinux container:
# /src is the bromigOS checkout (read-only), /out the output and cache volume,
# $ISO_REPO the package repository, /in/repo-ca.crt its CA, /in/test_key.pub a test key.
set -euo pipefail
repo=${ISO_REPO:?}
channel=${ISO_CHANNEL:-stable}
case $channel in edge) sub='' ;; *) sub="/$channel" ;; esac        # as install.sh lays the channels out
profile_src=/src/iso/profile
work=/out/work
cache=/out/cache
mkdir -p "$work" "$cache/pkg"

say() { printf '\n==> %s\n' "$*"; }

# ── 1. the build container: archiso, and bromigOS's repository trusted ───────────────
say "the build tools"
# python-pillow and grub (grub-mkfont): the boot menus' theme (docs/boot.md)
pacman -Syu --noconfirm --needed archiso arch-install-scripts git python python-pillow grub >/dev/null
if [[ -f /in/repo-ca.crt ]]; then
    install -Dm0644 /in/repo-ca.crt /etc/ca-certificates/trust-source/anchors/bromigos-repo-ca.crt
    update-ca-trust
fi
if ! grep -q '^\[bromigos\]' /etc/pacman.conf; then
    printf '\n[bromigos]\nSigLevel = Required DatabaseOptional\nServer = %s/$repo%s/$arch\n' "$repo" "$sub" >> /etc/pacman.conf
fi
curl -fsSL -o /tmp/bromigos.asc "$repo/bromigos/bromigos.asc"
want=$(gpg --batch --with-colons --import-options show-only --import /src/packaging/keys/bromigos.asc 2>/dev/null | awk -F: '/^fpr:/ { print $10; exit }')
have=$(gpg --batch --with-colons --import-options show-only --import /tmp/bromigos.asc 2>/dev/null | awk -F: '/^fpr:/ { print $10; exit }')
[[ -n $want && $have == "$want" ]] || { echo "the repository's key isn't packaging/keys/bromigos.asc ($have vs $want)" >&2; exit 1; }
pacman-key --init >/dev/null 2>&1
pacman-key --add /tmp/bromigos.asc >/dev/null 2>&1
pacman-key --lsign-key "$want" >/dev/null 2>&1
pacman -Sy >/dev/null
pacman -S --noconfirm --needed ttf-geist-mono >/dev/null          # the boot menus' font, bromigOS's build of it

# ── 2. the profile: archiso's releng, bromigOS's overlay on top ───────────────────────
say "the profile"
profile=$work/profile
rm -rf "$profile"
cp -r /usr/share/archiso/configs/releng "$profile"
cp -r "$profile_src"/. "$profile"/
rm -rf "$profile/airootfs/etc/systemd/system/getty@tty1.service.d"     # SDDM has tty1, not root's autologin
rm -f "$profile/airootfs/root/.automated_script.sh" "$profile/airootfs/root/.zlogin"
rm -f "$profile/airootfs/usr/local/bin/Installation_guide"
# the boot menus (docs/boot.md): GRUB on UEFI with bromigOS's boot theme, the medium's
# title card ("BROMIGOS // RELAY MEDIUM", the Wick's den at night); syslinux's vesamenu on
# BIOS, drawn to match (its picture and Geist Mono as a console font). releng's systemd-boot
# entries go: uefi.grub replaces them. releng's PXE entries say what this is
rm -rf "$profile/efiboot"
python3 /src/settings/grub/build-grub-theme.py --theme-dir /src/themes/wick --medium \
    --font-dir /usr/share/fonts/TTF --out "$profile/grub/themes/bromigos"
python3 /src/iso/syslinux-theme.py --font-dir /usr/share/fonts/TTF --out "$profile/syslinux"
mv "$profile/syslinux/bromigos.psf" "$profile/grub/bromigos.psf"     # mkarchiso copies grub/ whole, syslinux/ only its .cfg and splash.png
sed -i "s/@DOT@/$(printf '\xfa')/g" "$profile/syslinux/archiso_head.cfg"       # CP437's middle dot
for f in "$profile"/syslinux/*.cfg "$profile"/grub/*.cfg; do
    [[ -f $f ]] || continue
    sed -i -e 's/Arch Linux install medium/bromigOS live medium/g' -e 's/Arch Linux/bromigOS/g' "$f"
done
# what the medium remembers for the installed system: the repository and its CA
install -d "$profile/airootfs/etc/bromigos-iso"
printf '%s\n' "$repo" > "$profile/airootfs/etc/bromigos-iso/repo.url"
printf '%s\n' "$channel" > "$profile/airootfs/etc/bromigos-iso/channel"
[[ -f /in/repo-ca.crt ]] && install -m0644 /in/repo-ca.crt "$profile/airootfs/etc/bromigos-iso/repo-ca.crt"
# a test build: the live user takes this key over SSH, and the console is on the serial port too
if [[ -f /in/test_key.pub ]]; then
    install -m0644 /in/test_key.pub "$profile/airootfs/etc/bromigos-iso/test_authorized_keys"
    sed -i 's/^kernel_params_x86_64="\(.*\)"/kernel_params_x86_64="\1 console=tty0 console=ttyS0,115200"/' "$profile/profiledef.sh"
    sed -i 's/^iso_label=.*/iso_label="BROMIGOS_TEST"/' "$profile/profiledef.sh"
fi
# the CA, trusted on the live medium itself (its pacman reaches the repository once online)
if [[ -f /in/repo-ca.crt ]]; then
    install -Dm0644 /in/repo-ca.crt "$profile/airootfs/etc/ca-certificates/trust-source/anchors/bromigos-repo-ca.crt"
fi

# ── 3. the offline repository: every package on the medium's list, the closure of
#      bromigos, and what an install adds, from Arch's mirrors and bromigOS's, verified
#      (SigLevel Required): core and extra by origin, in pacman's own layout ──────────
say "the offline repository"
offline=$profile/airootfs/var/lib/bromigos/repo
rm -rf "$offline"
mkdir -p "$offline/core/os/x86_64" "$offline/extra/os/x86_64" "$offline/bromigos/x86_64"
mapfile -t want < <(grep -vE '^\s*(#|$)' "$profile/packages.x86_64")
# what an install adds that the live list may not have: archinstall's configuration's
# packages, the boot loaders archinstall may pick, the kernel's headers, pacman's mirrorlist
mapfile -t -O "${#want[@]}" want < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["packages"]))' "$profile/airootfs/usr/local/share/bromigos-iso/archinstall.json")
# ... and what archinstall straps on its own for the configuration's choices: zram swap,
# PipeWire for the audio, snapper, cryptsetup, Limine, the mirrorlist
want+=(base-devel linux-headers grub efibootmgr os-prober systemd-ukify pacman-mirrorlist
       grub-btrfs inotify-tools snapper snap-pac cryptsetup btrfs-progs zram-generator
       pipewire pipewire-alsa pipewire-pulse pipewire-jack wireplumber gst-plugin-pipewire
       networkmanager dhcpcd iwd xdg-user-dirs)
# bromigos hw: what `bromigos hw setup` may install for this machine's GPU and kind (hw.rs's
# ALL_PACKAGES, a test keeps the two in step; not -lts/-dkms: the medium installs the stock
# kernel), so the installer can hand this machine's to archinstall from the medium
want+=(nvidia-open nvidia-utils libva-nvidia-driver nvidia-prime mesa vulkan-radeon vulkan-intel
       vulkan-nouveau intel-media-driver libva-intel-driver linux-firmware-nvidia
       linux-firmware-amdgpu linux-firmware-radeon linux-firmware-intel brightnessctl
       power-profiles-daemon)
# resolved against an empty root: what's installed in this container is no reason to
# leave a package out (pacman -Sp lists only what it would add), so every dependency
# down to glibc is a target there
empty=$work/emptyroot
rm -rf "$empty"; mkdir -p "$empty/var/lib/pacman"
pacman -r "$empty" -Sy >/dev/null
mapfile -t closure < <(pacman -r "$empty" -Sp --print-format '%r %n %f' "${want[@]}" 2>/dev/null | grep -E '^(core|extra|bromigos) ' | sort -u)
mapfile -t names < <(printf '%s\n' "${closure[@]}" | awk '{print $2}')
echo "${#closure[@]} packages"
# bromigOS's own packages are downloaded afresh every build: a channel's build of a
# version can differ byte for byte from another's under the same file name (edge and
# stable both build r73), and pacman would find the cached one "corrupted" and give up
printf '%s\n' "${closure[@]}" | awk '$1 == "bromigos" { print $3 }' | while read -r f; do rm -f "$cache/pkg/$f" "$cache/pkg/$f.sig"; done
if ! pacman -r "$empty" -Sw --noconfirm --noprogressbar --cachedir "$cache/pkg" "${names[@]}" > "$work/download.log" 2>&1; then
    grep -vE '^(:: |  |$)' "$work/download.log" | tail -30 >&2
    echo "the download failed (the whole of it: $work/download.log in the work dir)" >&2; exit 1
fi
printf '%s\n' "${closure[@]}" | while read -r r n f; do
    [[ -f $cache/pkg/$f ]] || { echo "missing from the cache: $f" >&2; exit 1; }
    case $r in
        core|extra) d=$offline/$r/os/x86_64 ;;
        bromigos) d=$offline/bromigos/x86_64 ;;
        *) echo "unexpected repository $r for $n" >&2; exit 1 ;;
    esac
    ln -f "$cache/pkg/$f" "$d/$f" 2>/dev/null || cp "$cache/pkg/$f" "$d/$f"
    [[ -f $cache/pkg/$f.sig ]] && { ln -f "$cache/pkg/$f.sig" "$d/$f.sig" 2>/dev/null || cp "$cache/pkg/$f.sig" "$d/$f.sig"; }
done
for r in core extra; do (cd "$offline/$r/os/x86_64" && repo-add -q "$r.db.tar.gz" ./*.pkg.tar.zst >/dev/null); done
# Memtest86+ on UEFI: memtest86+-efi 8 names it memtest86x64.efi, which mkarchiso 91 doesn't copy
# (it looks for memtest.efi); the boot menu finds it in grub/ (docs/boot.md)
if m=$(ls "$offline"/extra/os/x86_64/memtest86+-efi-*.pkg.tar.zst 2>/dev/null | head -1) && [[ -n $m ]]; then
    bsdtar -xOf "$m" boot/memtest86+/memtest86x64.efi > "$profile/grub/memtest86x64.efi" 2>/dev/null \
        || rm -f "$profile/grub/memtest86x64.efi"
fi
(cd "$offline/bromigos/x86_64" && repo-add -q bromigos.db.tar.gz ./*.pkg.tar.zst >/dev/null)
du -sh "$offline" | awk '{print "offline repository: " $1}'

# ── 4. the build's pacman.conf: the offline repository first (what the image's packages
#      come from: the same files the medium carries), the mirrors after it ──────────────
cat > "$profile/pacman.conf" <<EOF
[options]
HoldPkg     = pacman glibc
Architecture = auto
ParallelDownloads = 5
SigLevel    = Required DatabaseOptional
LocalFileSigLevel = Optional

[core]
Server = file://$offline/\$repo/os/\$arch
[extra]
Server = file://$offline/\$repo/os/\$arch
[bromigos]
Server = file://$offline/\$repo/\$arch
EOF

# ── 5. mkarchiso ───────────────────────────────────────────────────────────────────────
say "mkarchiso"
iso_work=$work/mkarchiso
rm -rf "$iso_work"                 # mkarchiso skips every stage a kept work dir has stamped
mkdir -p "$iso_work" /out/iso
rm -f /out/iso/bromigos-*.iso
mkarchiso -v -w "$iso_work" -o /out/iso "$profile" 2>&1 | grep -vE '^\[mkarchiso\] INFO: (Adding|Creating|Installing)' | tail -40
iso=$(ls /out/iso/bromigos-*.iso | tail -1)
(cd /out/iso && sha256sum "$(basename "$iso")" > "$(basename "$iso").sha256")
cp "$iso" "$iso.sha256" /out/
[[ ${ISO_KEEP_WORK:-0} == 1 ]] || rm -rf "$iso_work" "$profile"
say "done: /out/$(basename "$iso") ($(du -h "$iso" | cut -f1))"
