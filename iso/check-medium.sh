#!/usr/bin/env bash
# What a medium for people carries (docs/iso.md, "A release's ISO"): unpacks a built ISO and
# checks it before it's published. Nothing runs as root on this machine: the squashfs is
# unpacked in an unprivileged archlinux container (Docker), as the caller's user.
#
#   iso/check-medium.sh ISO [--repo URL] [--keep DIR]
#
#   --repo URL   the repository the medium must name (default: install.sh's PUBLIC_REPO,
#                and fails if that's empty)
#   --keep DIR   unpack into DIR and leave it (default: a directory in ~/.cache, removed)
#
# Checks: the repository it names and its channel; no CA, no test key, no serial console,
# not labelled BROMIGOS_TEST; no package with a proprietary licence in the offline repository;
# the privacy guard over every file (test/medium-privacy.py); and it lists the pictures
# bromigOS puts on it, to look at (no likeness, docs/ASSETS.md). Exits 1 on a failure.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/.." && pwd)

iso='' want_repo='' keep=''
while (($#)); do
    case $1 in
        --repo) want_repo=$2; shift 2 ;; --keep) keep=$2; shift 2 ;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "iso/check-medium.sh: unknown option $1" >&2; exit 2 ;;
        *) iso=$1; shift ;;
    esac
done
[[ -f $iso ]] || { echo "iso/check-medium.sh: ISO" >&2; exit 2; }
iso=$(realpath "$iso")
if [[ -z $want_repo ]]; then
    want_repo=$(sed -n "s/^PUBLIC_REPO=\([^ ]*\).*/\1/p" "$root/install.sh" | tr -d "'\"")
    [[ -n $want_repo ]] || { echo "iso/check-medium.sh: install.sh has no PUBLIC_REPO yet: give --repo URL (the public address, docs/public.md)" >&2; exit 2; }
fi
w=${keep:-$(mktemp -d "${XDG_CACHE_HOME:-$HOME/.cache}/bromigos-iso-check.XXXXXX")}
[[ -n $keep ]] || trap 'chmod -R u+w "$w" 2>/dev/null; rm -rf "$w"' EXIT
mkdir -p "$w/iso" "$w/pkgs"

echo "==> unpacking $(basename "$iso")"
xorriso -osirrox on -indev "$iso" -extract / "$w/iso" >/dev/null 2>&1
chmod -R u+w "$w/iso"
sfs=$(ls "$w"/iso/*/x86_64/airootfs.sfs | head -1)
docker run --rm -v "$w:/w" archlinux:latest bash -c \
    "pacman -Sy --noconfirm squashfs-tools >/dev/null 2>&1 && setpriv --reuid=$(id -u) --regid=$(id -g) --clear-groups \
     unsquashfs -no-xattrs -ignore-errors -quiet -no-progress -d /w/root /w/iso/${sfs#"$w"/iso/}" >/dev/null 2>&1 || true
[[ -d $w/root/etc ]] || { echo "iso/check-medium.sh: the squashfs didn't unpack" >&2; exit 1; }
R=$w/root
offline=$R/var/lib/bromigos/repo
for f in "$offline"/bromigos/x86_64/*.pkg.tar.zst; do
    d=$w/pkgs/$(basename "$f" .pkg.tar.zst); mkdir -p "$d"; bsdtar -xf "$f" -C "$d" 2>/dev/null || true
done
chmod -R u+rwX "$w/pkgs"

fails=0
check() { local what=$1; shift; if "$@"; then echo "PASS $what"; else echo "FAIL $what"; fails=$((fails + 1)); fi; }
echo "==> the medium"
check "names the repository $want_repo" test "$(cat "$R/etc/bromigos-iso/repo.url" 2>/dev/null)" == "$want_repo"
echo "     its channel: $(cat "$R/etc/bromigos-iso/channel" 2>/dev/null || echo '(none)')"
check "no repository CA" bash -c "! ls '$R/etc/bromigos-iso/repo-ca.crt' '$R'/etc/ca-certificates/trust-source/anchors/* >/dev/null 2>&1"
check "no test key" test ! -e "$R/etc/bromigos-iso/test_authorized_keys"
check "no authorized_keys for live or root" bash -c "! ls '$R'/home/*/.ssh/authorized_keys '$R'/root/.ssh/authorized_keys >/dev/null 2>&1"
check "no serial console on the kernel line" bash -c "! grep -qs 'console=ttyS0' '$w'/iso/boot/grub/*.cfg '$w'/iso/boot/syslinux/*.cfg"
check "not a test build's label" bash -c "! grep -qrs BROMIGOS_TEST '$w'/iso/boot '$w'/iso/EFI"
prop=$(for f in "$offline"/*/os/x86_64/*.pkg.tar.zst "$offline"/bromigos/x86_64/*.pkg.tar.zst; do
           bsdtar -xOf "$f" .PKGINFO 2>/dev/null | grep -qiE '^license = .*(proprietary|custom:commercial)' && basename "$f"; true
       done | sort -u || true)
check "no proprietary licence in the offline repository" test -z "$prop"
[[ -z $prop ]] || printf '     %s\n' $prop
echo "     bromigOS's packages on it:"
for f in "$offline"/bromigos/x86_64/*.pkg.tar.zst; do echo "       $(basename "$f")"; done

echo "==> the privacy guard"
if python3 -I "$here/test/medium-privacy.py" "$R" "$w/iso" "$w/pkgs"; then echo "PASS the privacy guard"; else echo "FAIL the privacy guard (each finding above: judge it, fix it at the source)"; fails=$((fails + 1)); fi

echo "==> pictures bromigOS puts on it, to look at (no likeness: docs/ASSETS.md)"
(cd "$w" && find pkgs iso/boot -iregex '.*\.\(jpe?g\|png\|webp\|avif\)' -size +200k | sed 's|^pkgs/[^/]*/||' | sort -u | sed 's/^/  /')

echo "==> $fails failed"
(( fails == 0 ))
