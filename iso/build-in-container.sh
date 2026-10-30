#!/usr/bin/env bash
# The ISO build proper, run by iso/build.sh inside a privileged archlinux container:
# /src is the bromigOS checkout (read-only), /out the output and cache volume,
# $ISO_PROFILE the profile (a directory of iso/), $ISO_REPO the package repository, $ISO_MEDIUM_REPO the one the medium names (default
# $ISO_REPO), $ISO_VERSION the medium's version, /in/repo-ca.crt the CA of $ISO_REPO,
# /in/test_key.pub a test key, /in/sb.key and /in/sb.crt the Secure Boot key and certificate, $ISO_OWNER (uid:gid) the owner of what it makes.
set -euo pipefail
repo=${ISO_REPO:?}
medium_repo=${ISO_MEDIUM_REPO:-$repo}
# the CA goes on the medium only for the repository it names: a public build downloads from
# a repository with its own CA and names the public mirror, which needs none
medium_ca=0; [[ -f /in/repo-ca.crt && $medium_repo == "$repo" ]] && medium_ca=1
channel=${ISO_CHANNEL:-stable}
case $channel in edge) sub='' ;; *) sub="/$channel" ;; esac        # as install.sh lays the channels out
profile_src=/src/iso/${ISO_PROFILE:-profile}
secureboot=0; [[ -f /in/sb.key && -f /in/sb.crt ]] && secureboot=1
# the desktop medium (iso/profile), or Field Kit, bromigOS without the desktop (iso/fieldkit,
# docs/fieldkit.md), which shares the full medium's offline store and installer
case ${ISO_PROFILE:-profile} in fieldkit) edition=fieldkit ;; *) edition=desktop ;; esac
work=/out/work
cache=/out/cache
mkdir -p "$work" "$cache/pkg"

say() { printf '\n==> %s\n' "$*"; }

# ── 1. the build container: archiso, and bromigOS's repository trusted ───────────────
say "the build tools"
# python-pillow and grub (grub-mkfont): the boot menus' theme (docs/boot.md)
pacman -Syu --noconfirm --needed archiso arch-install-scripts git python python-pillow grub >/dev/null
(( secureboot )) && pacman -S --noconfirm --needed sbsigntools openssl libarchive >/dev/null
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
# a dev build (iso/build.sh --local-repo): this checkout's own packages, unsigned, ahead of
# [bromigos]'s; never a medium for people (check-medium.sh refuses it)
dev=0
if compgen -G '/in/local-repo/*.pkg.tar.zst' >/dev/null; then
    dev=1
    rm -rf "$work/localrepo"; mkdir -p "$work/localrepo"
    cp /in/local-repo/*.pkg.tar.zst "$work/localrepo/"
    repo-add -q "$work/localrepo/bromigos-dev.db.tar.gz" "$work"/localrepo/*.pkg.tar.zst >/dev/null
    if ! grep -q '^\[bromigos-dev\]' /etc/pacman.conf; then
        sed -i "0,/^\[bromigos\]/s||[bromigos-dev]\nSigLevel = Optional TrustAll\nServer = file://$work/localrepo\n\n[bromigos]|" /etc/pacman.conf
    fi
fi
pacman -Sy >/dev/null
pacman -S --noconfirm --needed ttf-geist-mono >/dev/null          # the boot menus' font, bromigOS's build of it

# ── 2. the profile: archiso's releng, bromigOS's overlay on top ───────────────────────
say "the profile"
profile=$work/profile
rm -rf "$profile"
cp -r /usr/share/archiso/configs/releng "$profile"
rm -f "$profile/airootfs/root/.automated_script.sh" "$profile/airootfs/root/.zlogin"
rm -f "$profile/airootfs/usr/local/bin/Installation_guide"
if [[ $edition == fieldkit ]]; then
    # the full medium's shared pieces: the offline store's pacman.conf, the clock's wait, the
    # installer (bromigos-iso-install and its library are the installer's own files)
    a=$profile/airootfs
    mkdir -p "$a/usr/local/bin" "$a/usr/local/lib" "$a/usr/local/share" "$a/etc/systemd/system"
    cp /src/iso/profile/airootfs/etc/pacman.conf "$a/etc/pacman.conf"
    cp -r /src/iso/profile/airootfs/etc/systemd/system/systemd-time-wait-sync.service.d "$a/etc/systemd/system/"
    cp /src/iso/profile/airootfs/usr/local/bin/{bromigos-iso-install,bromigos-iso-text-console} "$a/usr/local/bin/"
    # the text installer on the console for the menu's "Install bromigOS Server" (on tty1 Field
    # Kit's own console runs it: iso/fieldkit/airootfs/root/.zlogin)
    mkdir -p "$a/etc/systemd/system/multi-user.target.wants"
    cp /src/iso/profile/airootfs/etc/systemd/system/bromigos-iso-text-{check,install@}.service "$a/etc/systemd/system/"
    ln -sf ../bromigos-iso-text-check.service "$a/etc/systemd/system/multi-user.target.wants/bromigos-iso-text-check.service"
    cp -r /src/iso/profile/airootfs/usr/local/lib/bromigos-iso "$a/usr/local/lib/"
    cp -r /src/iso/profile/airootfs/usr/local/share/bromigos-iso "$a/usr/local/share/"
    rm -f "$a/usr/local/share/bromigos-iso/live-answers.toml"
    cp -r "$profile_src"/{profiledef.sh,grub,syslinux,airootfs} "$profile"/
    # the medium's packages: iso/fieldkit/packages.toml (docs/fieldkit-packages.md)
    { echo "# made by iso/fieldkit/manifest.py from iso/fieldkit/packages.toml"; python3 /src/iso/fieldkit/manifest.py live; } > "$profile/packages.x86_64"
    # if_available: on the medium once a repository has it (brodec-machine before its first
    # publish, say); its store-only ones join the offline store below
    fk_optional=()
    while read -r name where; do
        if pacman -Si "$name" >/dev/null 2>&1; then
            [[ $where == live ]] && echo "$name" >> "$profile/packages.x86_64"
            fk_optional+=("$name"); echo "   $name: in the repositories, on the medium"
        else
            echo "   $name: not in the repositories yet, left out"
        fi
    done < <(python3 /src/iso/fieldkit/manifest.py optional)
    # releng's services Field Kit leaves off: one network stack (NetworkManager, not iwd and
    # networkd), no cloud-init, no virtual machine guest tools, no smartcards, SSH off until
    # remote help or a test build turns it on (docs/fieldkit.md)
    ( cd "$a/etc/systemd/system"
      rm -rf cloud-init.target.wants systemd-networkd-wait-online.service.d dbus-org.freedesktop.network1.service \
          multi-user.target.wants/{iwd,systemd-networkd,hv_fcopy_daemon,hv_kvp_daemon,hv_vss_daemon,vboxservice,vmtoolsd,vmware-vmblock-fuse,sshd}.service \
          network-online.target.wants/systemd-networkd-wait-online.service sockets.target.wants/{pcscd,systemd-networkd}.socket
      ln -sf /usr/lib/systemd/system/NetworkManager.service multi-user.target.wants/NetworkManager.service
      mkdir -p network-online.target.wants
      ln -sf /usr/lib/systemd/system/NetworkManager-wait-online.service network-online.target.wants/NetworkManager-wait-online.service )
    rm -rf "$a/etc/systemd/network" "$a/etc/systemd/networkd.conf.d"
    heading="BROMIGOS // FIELD KIT"
else
    cp -r "$profile_src"/. "$profile"/
    # SDDM has tty1: releng's root autologin goes; the Field Kit entry's (bromigos-fieldkit.conf) stays
    rm -f "$profile/airootfs/etc/systemd/system/getty@tty1.service.d/autologin.conf"
    heading=''
fi
# the boot menus (docs/boot.md): GRUB on UEFI with bromigOS's boot theme, the medium's
# title card ("BROMIGOS // RELAY MEDIUM", the Wick's den at night); syslinux's vesamenu on
# BIOS, drawn to match (its picture and Geist Mono as a console font). releng's systemd-boot
# entries go: uefi.grub replaces them. releng's PXE entries say what this is
rm -rf "$profile/efiboot"
python3 /src/settings/grub/build-grub-theme.py --theme-dir /src/themes/wick --medium ${heading:+--heading "$heading"} \
    --font-dir /usr/share/fonts/TTF --out "$profile/grub/themes/bromigos"
python3 /src/iso/syslinux-theme.py --font-dir /usr/share/fonts/TTF ${heading:+--heading "$heading"} --out "$profile/syslinux"
mv "$profile/syslinux/bromigos.psf" "$profile/grub/bromigos.psf"     # mkarchiso copies grub/ whole, syslinux/ only its .cfg and splash.png
sed -i "s/@DOT@/$(printf '\xfa')/g" "$profile"/syslinux/*.cfg       # CP437's middle dot
for f in "$profile"/syslinux/*.cfg "$profile"/grub/*.cfg; do
    [[ -f $f ]] || continue
    sed -i -e 's/Arch Linux install medium/bromigOS live medium/g' -e 's/Arch Linux/bromigOS/g' "$f"
done
# a dev build's medium says so, and trusts this checkout's unsigned packages
if (( dev )); then
    install -d "$profile/airootfs/etc/bromigos-iso"
    echo "a dev build (iso/build.sh --local-repo): not for people" > "$profile/airootfs/etc/bromigos-iso/dev-build"
    sed -i '/^\[bromigos\]/a SigLevel = Optional TrustAll' "$profile/airootfs/etc/pacman.conf"
fi
# a release's version in the file name (bromigos-0.1.2-x86_64.iso), else the build's date
if [[ -n ${ISO_VERSION:-} ]]; then
    sed -i "s/^iso_version=.*/iso_version=\"$ISO_VERSION\"/" "$profile/profiledef.sh"
fi
# what the medium remembers for the installed system: the repository and its CA
install -d "$profile/airootfs/etc/bromigos-iso"
printf '%s\n' "$medium_repo" > "$profile/airootfs/etc/bromigos-iso/repo.url"
printf '%s\n' "$channel" > "$profile/airootfs/etc/bromigos-iso/channel"
(( medium_ca )) && install -m0644 /in/repo-ca.crt "$profile/airootfs/etc/bromigos-iso/repo-ca.crt"
# a test build: the live user takes this key over SSH, and the console is on the serial port too
if [[ -f /in/test_key.pub ]]; then
    install -m0644 /in/test_key.pub "$profile/airootfs/etc/bromigos-iso/test_authorized_keys"
    sed -i 's/^kernel_params_x86_64="\(.*\)"/kernel_params_x86_64="\1 console=tty0 console=ttyS0,115200"/' "$profile/profiledef.sh"
    sed -i 's/^iso_label=.*/iso_label="BROMIGOS_TEST"/' "$profile/profiledef.sh"
fi
# the CA, trusted on the live medium itself (its pacman reaches the repository once online)
if (( medium_ca )); then
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
if [[ $edition == fieldkit ]]; then
    # bromigOS Server's packages and the installer's hardware extras (iso/fieldkit/packages.toml),
    # and what archinstall straps by itself (base, sudo, linux-firmware, mkinitcpio, the
    # microcode, zram swap, the mirrorlist): installing from Field Kit needs no network
    mapfile -t -O "${#want[@]}" want < <(python3 /src/iso/fieldkit/manifest.py store)
    want+=("${fk_optional[@]}")
    want+=(base sudo linux-firmware mkinitcpio linux amd-ucode intel-ucode zram-generator pacman-mirrorlist
           grub efibootmgr btrfs-progs cryptsetup snapper snap-pac grub-btrfs inotify-tools networkmanager openssh)
    # and what the installer adds to every install, whatever the edition (answers.py's REQUIRED)
    mapfile -t -O "${#want[@]}" want < <(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import answers; print("\n".join(answers.REQUIRED))' \
        /src/iso/profile/airootfs/usr/local/lib/bromigos-iso)
else
# what an install adds that the live list may not have: archinstall's configuration's
# packages, the boot loaders archinstall may pick, the kernel's headers, pacman's mirrorlist
mapfile -t -O "${#want[@]}" want < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["packages"]))' "$profile/airootfs/usr/local/share/bromigos-iso/archinstall.json")
# ... and what archinstall straps on its own for the configuration's choices: zram swap,
# PipeWire for the audio, snapper, cryptsetup, Limine, the mirrorlist
want+=(base-devel linux-headers grub efibootmgr os-prober systemd-ukify pacman-mirrorlist
       grub-btrfs inotify-tools snapper snap-pac cryptsetup btrfs-progs zram-generator
       pipewire pipewire-alsa pipewire-pulse pipewire-jack wireplumber gst-plugin-pipewire
       networkmanager dhcpcd iwd xdg-user-dirs)
# Secure Boot on the installed system (docs/secureboot.md): bromigos-secureboot and what it
# runs, so the installer sets it up with no network (the package only where the channel has it)
want+=(sbsigntools mokutil)
# (the medium's Secure Boot step then also puts SECURE_BOOT.txt on it, which publish.sh reads)
if pacman -Si bromigos-secureboot >/dev/null 2>&1; then want+=(bromigos-secureboot); export ISO_SECUREBOOT_INSTALLED=1; fi
# bromigos hw: what `bromigos hw setup` may install for this machine's GPU and kind (hw.rs's
# ALL_PACKAGES, a test keeps the two in step; not -lts/-dkms: the medium installs the stock
# kernel), so the installer can hand this machine's to archinstall from the medium
want+=(nvidia-open nvidia-utils libva-nvidia-driver nvidia-prime mesa vulkan-radeon vulkan-intel
       vulkan-nouveau intel-media-driver libva-intel-driver linux-firmware-nvidia
       linux-firmware-amdgpu linux-firmware-radeon linux-firmware-intel brightnessctl
       power-profiles-daemon vulkan-mesa-implicit-layers)
fi
# resolved against an empty root: what's installed in this container is no reason to
# leave a package out (pacman -Sp lists only what it would add), so every dependency
# down to glibc is a target there
empty=$work/emptyroot
rm -rf "$empty"; mkdir -p "$empty/var/lib/pacman"
pacman -r "$empty" -Sy >/dev/null
mapfile -t closure < <(pacman -r "$empty" -Sp --print-format '%r %n %f' "${want[@]}" 2>/dev/null | grep -E '^(core|extra|bromigos|bromigos-dev) ' | sort -u)
(( ${#closure[@]} )) || { pacman -r "$empty" -Sp "${want[@]}" >&2 || true; echo "the package list didn't resolve" >&2; exit 1; }
mapfile -t names < <(printf '%s\n' "${closure[@]}" | awk '{print $2}')
echo "${#closure[@]} packages"
# bromigOS's own packages are downloaded afresh every build: a channel's build of a
# version can differ byte for byte from another's under the same file name (edge and
# stable both build r73), and pacman would find the cached one "corrupted" and give up
printf '%s\n' "${closure[@]}" | awk '$1 == "bromigos" { print $3 }' | while read -r f; do rm -f "$cache/pkg/$f" "$cache/pkg/$f.sig"; done
# a dev build's own packages: from the local repository as they are, unsigned
printf '%s\n' "${closure[@]}" | awk '$1 == "bromigos-dev" { print $3 }' | while read -r f; do
    cp "$work/localrepo/$f" "$cache/pkg/$f"; rm -f "$cache/pkg/$f.sig"; done
# three tries: a reset connection on one of ~1000 downloads shouldn't fail a release's build
# (what's already downloaded stays in the cache)
ok=0
for try in 1 2 3; do
    if pacman -r "$empty" -Sw --noconfirm --noprogressbar --cachedir "$cache/pkg" "${names[@]}" > "$work/download.log" 2>&1; then ok=1; break; fi
    echo "the download failed (try $try of 3): $(grep -m1 '^error:' "$work/download.log")" >&2
    sleep $((try * 15))
done
if (( ! ok )); then
    grep -vE '^(:: |  |$)' "$work/download.log" | tail -30 >&2
    echo "the download failed (the whole of it: $work/download.log in the work dir)" >&2; exit 1
fi
printf '%s\n' "${closure[@]}" | while read -r r n f; do
    [[ -f $cache/pkg/$f ]] || { echo "missing from the cache: $f" >&2; exit 1; }
    case $r in
        core|extra) d=$offline/$r/os/x86_64 ;;
        bromigos|bromigos-dev) d=$offline/bromigos/x86_64 ;;
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
if (( dev )); then sed -i '/^\[bromigos\]/a SigLevel = Optional TrustAll' "$profile/pacman.conf"; fi
# the sizes behind docs/fieldkit-packages.md (iso/fieldkit/manifest.py docs)
if [[ $edition == fieldkit ]]; then
    pacman -r "$empty" -Si "${names[@]}" 2>/dev/null | awk -F' *: ' '
        /^Name/ { n = $2 }
        /^Installed Size/ { split($2, a, " "); m = (a[2] == "KiB") ? 1024 : (a[2] == "MiB") ? 1048576 : (a[2] == "GiB") ? 1073741824 : 1; printf "%s\t%d\n", n, a[1] * m }' > /out/fieldkit-sizes.tsv
    mapfile -t live_want < <(grep -vE "^\s*(#|$)" "$profile/packages.x86_64")
    mapfile -t live_names < <(pacman -r "$empty" -Sp --print-format "%n" "${live_want[@]}" 2>/dev/null | sort -u)
    awk -F'\t' 'NR == FNR { keep[$1] = 1; next } $1 in keep' <(printf '%s\n' "${live_names[@]}") /out/fieldkit-sizes.tsv > /out/fieldkit-live.tsv
    find "$offline" -name '*.pkg.tar.zst' -printf '%f\t%s\n' > /out/fieldkit-store.tsv
fi

# the medium's EFI partition, as the firmware's boot list shows it ("UEFI: BROMIGOS FK" or
# "UEFI: BROMIGOS"): mkarchiso names it ARCHISO_EFI; nothing looks it up by that name
if [[ $edition == fieldkit ]]; then efi_label=BROMIGOS_FK; else efi_label=BROMIGOS; fi
sed -i "s/-n ARCHISO_EFI/-n $efi_label/" /usr/bin/mkarchiso

# ── 5. mkarchiso ───────────────────────────────────────────────────────────────────────
mkarchiso=mkarchiso
if (( secureboot )); then
    # Secure Boot (docs/secureboot.md): mkarchiso has no step for it, so a copy of it calls
    # iso/secureboot/medium.sh where it needs to: once the kernels are out of the image (they
    # are signed before they are copied onto the medium), and once GRUB's EFI binary is made
    # (shim goes in front of it, before the EFI system partition is written). Each anchor
    # must be there exactly once, or the build stops: a new archiso needs a look first.
    say "Secure Boot"
    /src/iso/secureboot/medium.sh shim "$cache/shim"
    mkarchiso=$work/mkarchiso-secureboot
    python3 - /usr/bin/mkarchiso "$mkarchiso" <<'PY'
import sys
src, dst = sys.argv[1:3]
s = open(src).read()
hook = "/src/iso/secureboot/medium.sh"
for anchor, add in (
    ("    _run_once _copy_boot_out_of_pacstrap_dir\n",
     f'    _run_once _copy_boot_out_of_pacstrap_dir\n    "{hook}" kernel "${{boot_dir}}" || _msg_error "Secure Boot: signing the kernel failed" 1\n'),
    ('    efiboot_files=("${isofs_dir}/EFI")\n',
     f'    "{hook}" grub "${{isofs_dir}}" "${{work_dir}}/grub-embed.cfg" || _msg_error "Secure Boot: shim and GRUB failed" 1\n'
     '    efiboot_files=("${isofs_dir}/EFI" "${isofs_dir}/ENROLL_THIS_KEY_IN_MOKMANAGER.cer")\n'),
):
    n = s.count(anchor)
    if n != 1:
        sys.exit(f"mkarchiso: the Secure Boot anchor {anchor.strip()!r} is there {n} times, not once")
    s = s.replace(anchor, add)
open(dst, "w").write(s)
PY
    chmod +x "$mkarchiso"
fi
say "mkarchiso"
iso_work=$work/mkarchiso
rm -rf "$iso_work"                 # mkarchiso skips every stage a kept work dir has stamped
mkdir -p "$iso_work" /out/iso
rm -f /out/iso/*.iso
"$mkarchiso" -v -w "$iso_work" -o /out/iso "$profile" 2>&1 | grep -vE '^\[mkarchiso\] INFO: (Adding|Creating|Installing)' | tail -40
iso=$(ls /out/iso/*.iso | tail -1)
(cd /out/iso && sha256sum "$(basename "$iso")" > "$(basename "$iso").sha256")
mv -f "$iso" "$iso.sha256" /out/
rmdir /out/iso 2>/dev/null || true
iso=/out/$(basename "$iso")
# Field Kit for /boot (package bromigos-fieldkit, docs/fieldkit.md "In the boot menu"): the same
# kernel, initramfs and system without the offline store (installing is the stick's job), and
# a Unified Kernel Image of them for the firmware's own boot menu, as <iso>-boot.tar:
#   fieldkit/boot/x86_64/{vmlinuz-linux,initramfs-linux.img}   what GRUB starts
#   fieldkit/x86_64/airootfs.sfs                               the system
#   fieldkit/boot-<id>.id                                      how the initramfs finds it
#   EFI/bromigos-fieldkit/fieldkit.efi                         the UKI (kernel, initramfs, command line)
# The initramfs finds the system by that file (archisosearchfilename), so the command line is
# the same on every machine and the UKI can be made, and signed, here.
if [[ $edition == fieldkit ]]; then
    say "Field Kit for /boot"
    pacman -S --noconfirm --needed systemd-ukify >/dev/null
    bt=$work/bootcopy
    rm -rf "$bt"; mkdir -p "$bt/fieldkit/boot/x86_64" "$bt/fieldkit/x86_64" "$bt/EFI/bromigos-fieldkit"
    cp "$iso_work"/iso/fieldkit/boot/x86_64/{vmlinuz-linux,initramfs-linux.img} "$bt/fieldkit/boot/x86_64/"
    mksquashfs "$iso_work/x86_64/airootfs" "$bt/fieldkit/x86_64/airootfs.sfs" -noappend -no-progress -quiet \
        -comp zstd -Xcompression-level 19 -b 1M -e var/lib/bromigos/repo >/dev/null
    id=$(printf '%s' "$(basename "$iso" .iso)" | tr -c 'A-Za-z0-9._-' _)-$(date -u +%Y%m%d%H%M%S)
    printf 'bromigOS Field Kit for /boot: %s\n' "$id" > "$bt/fieldkit/boot-$id.id"
    # the medium's own kernel parameters (profiledef.sh: nouveau off, DRIFTGLASS's colours) and how to find it
    params=$(sed -n 's/^kernel_params_x86_64="\(.*\)"/\1/p' "$profile/profiledef.sh" | sed 's/ console=[^ ]*//g')
    # copytoram: the system is read into memory (about 1 GiB), so /boot isn't held mounted
    # read-only while Field Kit repairs it
    printf '%s\n' "archisobasedir=fieldkit archisosearchfilename=/fieldkit/boot-$id.id $params copytoram=y bromigos.fieldkit=disk" > "$bt/fieldkit/cmdline"
    # a test build's console on the serial port too, as on its medium (iso/fieldkit/test.py)
    [[ -f /in/test_key.pub ]] && sed -i 's/$/ console=tty0 console=ttyS0,115200/' "$bt/fieldkit/cmdline"
    printf 'NAME="bromigOS Field Kit"\nPRETTY_NAME="bromigOS Field Kit"\nID=bromigos-fieldkit\nID_LIKE=arch\nVERSION_ID="%s"\nHOME_URL="https://bromigos.org"\n' \
        "${ISO_VERSION:-$(date +%Y.%m.%d)}" > "$work/fieldkit-os-release"
    ukify build --linux "$bt/fieldkit/boot/x86_64/vmlinuz-linux" --initrd "$bt/fieldkit/boot/x86_64/initramfs-linux.img" \
        --cmdline "@$bt/fieldkit/cmdline" --os-release "@$work/fieldkit-os-release" \
        --output "$bt/EFI/bromigos-fieldkit/fieldkit.efi" >/dev/null
    tar -C "$bt" -cf "${iso%.iso}-boot.tar" fieldkit EFI
    rm -rf "$bt"
    du -h "${iso%.iso}-boot.tar" | awk '{print "Field Kit for /boot: " $1}'
fi
[[ ${ISO_KEEP_WORK:-0} == 1 ]] || rm -rf "$iso_work" "$profile" "$empty" "$work/download.log"
# what the build made belongs to whoever ran iso/build.sh, not to the container's root
if [[ -n ${ISO_OWNER:-} ]]; then
    chown -R "$ISO_OWNER" "$iso" "$iso.sha256" "$cache" "$work" /out/*-boot.tar /out/fieldkit-*.tsv 2>/dev/null || true
fi
say "done: $iso ($(du -h "$iso" | cut -f1))"
