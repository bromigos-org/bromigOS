#!/usr/bin/env bash
# bromigos-fieldkit, the package that puts Field Kit in every install's boot menu, made from a
# built Field Kit medium (docs/fieldkit.md, "In the boot menu"):
#
#   iso/fieldkit/package.sh BOOT_TAR OUTDIR  -> OUTDIR/bromigos-fieldkit-<version>-1-x86_64.pkg.tar.zst
#
# BOOT_TAR is what iso/build.sh --edition fieldkit leaves beside the ISO:
# bromigos-fieldkit-<version>-x86_64-boot.tar. The version is the ISO's, with - turned into _.
# Unsigned: the pipeline signs it when it publishes (packaging/ci/publish.sh, PKGS_PREBUILT).
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
tar=$(realpath "${1:?BOOT_TAR}"); out=$(realpath -m "${2:?OUTDIR}")
name=$(basename "$tar")
[[ $name =~ ^bromigos-fieldkit-(.+)-x86_64-boot\.tar$ ]] || { echo "package.sh: $name isn't bromigos-fieldkit-<version>-x86_64-boot.tar" >&2; exit 2; }
version=${BASH_REMATCH[1]//-/_}
mkdir -p "$out"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
cp "$root/packaging/prebuilt/bromigos-fieldkit/PKGBUILD" "$work/"
ln -s "$root/LICENSE-MIT" "$root/LICENSE-APACHE" "$work/"
cd "$work"
# startdir must look like <root>/packaging/… for the licences: give it the repository's
FIELDKIT_BOOT=$tar FIELDKIT_VERSION=$version PKGDEST=$out SRCDEST=$work BUILDDIR=$work/build \
    makepkg --nodeps --force --noconfirm --skipinteg -p PKGBUILD >/dev/null
ls "$out"/bromigos-fieldkit-"$version"-*.pkg.tar.zst
