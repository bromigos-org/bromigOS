#!/usr/bin/env bash
# Secure Boot for the medium (docs/secureboot.md), run by iso/build-in-container.sh inside
# the build container. mkarchiso calls it at two points (build-in-container.sh adds the calls
# to its own copy of mkarchiso):
#
#   medium.sh shim CACHE              fetches shim (Fedora's build, signed by Microsoft's UEFI
#                                     CA 2011 and 2023) once, and checks it against the pins below
#   medium.sh kernel BOOT_DIR         signs the kernels mkarchiso copies onto the medium
#   medium.sh grub ISOFS EMBED_CFG    GRUB for UEFI, built again with every module the menus
#                                     use built in (Secure Boot lets GRUB load no module from
#                                     disk: secureboot/grub-modules.txt, the installed system's
#                                     list too) and the boot theme's fonts inside it (nor any
#                                     font: grub.cfg loads them by name, from its memdisk), with
#                                     shim's verifier on, signed; shim as EFI/BOOT/BOOTx64.EFI
#                                     with its MokManager beside it; the certificate, to
#                                     enroll, at the medium's root
#
# The key and certificate are /in/sb.key and /in/sb.crt (PEM), mounted for the build only.
# Nothing of the key reaches the medium: only the certificate does.
set -euo pipefail
KEY=/in/sb.key CRT=/in/sb.crt
# shim 16.1-10, Fedora's signed build (https://kojipkgs.fedoraproject.org/packages/shim/16.1/10/)
SHIM_URL=https://kojipkgs.fedoraproject.org/packages/shim/16.1/10/x86_64/shim-x64-16.1-10.x86_64.rpm
SHIM_RPM_SHA256=50ca8ad0f0893a9b69d257b232cc38fe572d7f2c814bc9aec4df5e492800cdc7
SHIM_SHA256=351e131d3c4a636704e9cae7d1296baf8a05beca9922cfebbfa48933c9bf1ad3
MM_SHA256=eb84ac15b99ebbabf9b7dd187c6a20b05fd3aca512ccf49b08922780d6cd42d8
SHIM_DIR=/tmp/bromigos-shim
# the certificate's file name on the medium: what MokManager's file list shows
CER=ENROLL_THIS_KEY_IN_MOKMANAGER.cer

say() { printf '[secureboot] %s\n' "$*"; }
sign() { sbsign --key "$KEY" --cert "$CRT" --output "$1.signed" "$1" >/dev/null && mv -f "$1.signed" "$1"; }

case ${1:-} in
    shim)
        cache=$2; mkdir -p "$cache" "$SHIM_DIR"
        rpm=$cache/$(basename "$SHIM_URL")
        if ! echo "$SHIM_RPM_SHA256  $rpm" | sha256sum -c --quiet >/dev/null 2>&1; then
            curl -fsSL --retry 3 -o "$rpm" "$SHIM_URL"
            echo "$SHIM_RPM_SHA256  $rpm" | sha256sum -c --quiet || { echo "shim's package isn't the pinned one" >&2; exit 1; }
        fi
        # the whole tree (shimx64.efi is a hard link in it), then the two files
        x=$(mktemp -d); bsdtar -xf "$rpm" -C "$x" './usr/lib/efi/shim/*'
        install -m0644 "$x"/usr/lib/efi/shim/16.1-10/EFI/fedora/{shimx64,mmx64}.efi "$SHIM_DIR"/
        rm -rf "$x"
        printf '%s  %s\n' "$SHIM_SHA256" "$SHIM_DIR/shimx64.efi" "$MM_SHA256" "$SHIM_DIR/mmx64.efi" | sha256sum -c --quiet
        sbverify --list "$SHIM_DIR/shimx64.efi" | grep -q 'CN=Microsoft Corporation UEFI CA 2011' \
            || { echo "shim isn't signed by Microsoft's UEFI CA" >&2; exit 1; }
        say "shim 16.1 (Microsoft-signed), MokManager"
        ;;
    kernel)
        for k in "$2"/vmlinuz-*; do sign "$k"; say "signed $(basename "$k")"; done
        ;;
    grub)
        isofs=$2 embed=$3
        [[ -f $SHIM_DIR/shimx64.efi ]] || { echo "medium.sh shim first" >&2; exit 1; }
        # mkarchiso's modules, and what the medium's menus and the boot theme use, built in
        # (only those this GRUB has)
        want=(all_video at_keyboard boot btrfs cat chain configfile echo efifwsetup efinet exfat ext2 f2fs fat font
              gfxmenu gfxterm gzio halt hfsplus iso9660 jpeg keylayouts linux loadenv loopback lsefi lsefimmap
              minicmd normal ntfs ntfscomp part_apple part_gpt part_msdos png read reboot regexp search
              search_fs_file search_fs_uuid search_label serial sleep tpm udf usb usbserial_common usbserial_ftdi
              usbserial_pl2303 usbserial_usbdebug video xfs zstd
              connectefi play probe test true gfxterm_background gettext terminal tga smbios cpuid keystatus
              datetime efi_gop efi_uga video_bochs video_cirrus videoinfo sleep_test eval memdisk tar
              procfs echo help ls lsmmap)
        # and the installed system's (one list: secureboot/grub-modules.txt)
        list=$(dirname "$0")/../../secureboot/grub-modules.txt
        [[ -f $list ]] && mapfile -t -O "${#want[@]}" want < <(sed 's/#.*//' "$list" | tr -s ' \t' '\n' | grep .)
        mods=(); for m in "${want[@]}"; do [[ -f /usr/lib/grub/x86_64-efi/$m.mod ]] && mods+=("$m"); done
        mapfile -t mods < <(printf '%s\n' "${mods[@]}" | sort -u)
        # the boot theme's fonts in GRUB's memdisk, as fonts/NAME.pf2: with Secure Boot on, GRUB
        # loads no font from the disk (lockdown), but a memdisk is part of the signed image, and
        # `loadfont NAME` looks there first (grub.cfg's head)
        fonts=()
        for f in "$isofs"/boot/grub/themes/bromigos/*.pf2; do
            [[ -f $f ]] && fonts+=("fonts/$(basename "$f")=$f")
        done
        (( ${#fonts[@]} )) || { echo "no boot theme fonts in $isofs/boot/grub/themes/bromigos" >&2; exit 1; }
        tmp=$(mktemp -d)
        grub-mkstandalone -O x86_64-efi --modules="${mods[*]}" --locales="en@quot" --themes="" \
            --sbat=/usr/share/grub/sbat.csv -o "$tmp/grubx64.efi" "boot/grub/grub.cfg=$embed" "${fonts[@]}"
        sign "$tmp/grubx64.efi"
        install -m0644 "$tmp/grubx64.efi" "$isofs/EFI/BOOT/grubx64.efi"
        install -m0644 "$SHIM_DIR/shimx64.efi" "$isofs/EFI/BOOT/BOOTx64.EFI"
        install -m0644 "$SHIM_DIR/mmx64.efi" "$isofs/EFI/BOOT/mmx64.efi"
        openssl x509 -in "$CRT" -outform DER -out "$isofs/$CER"
        # the installer sets the installed system up too (bromigos-secureboot is in the store): a
        # note on the stick says so, in plain words (publish.sh reads it: secure_boot_installed)
        if [[ ${ISO_SECUREBOOT_INSTALLED:-0} == 1 ]]; then
            printf '%s\r\n' "Secure Boot can stay on." "" \
                "This stick starts with Secure Boot on, and so does the bromigOS it installs." \
                "Each asks you to approve bromigOS once, in a blue screen (MokManager), at its first start." \
                "How: https://bromigos.org/download#secure-boot" > "$isofs/SECURE_BOOT.txt"
        fi
        rm -rf "$tmp"
        say "shim -> grubx64.efi (signed, ${#mods[@]} modules built in, ${#fonts[@]} fonts inside), MokManager, $CER"
        ;;
    *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
