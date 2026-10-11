#!/usr/bin/env bash
# Root only inside a disposable Arch container. No desktop setup or real lab access.
set -euo pipefail
root=${1:?checkout path}
[[ -e /.dockerenv ]] || { echo 'Use a disposable Arch container' >&2; exit 1; }
pacman -Syu --noconfirm --needed python python-textual python-cairo python-gobject pango python-psutil git >/dev/null
! pacman -Qq | grep -q '^bromigos' || { echo 'Container already has bromigOS packages' >&2; exit 1; }
useradd -m builder
work=$(mktemp -d)
mkdir -p "$work/recipe" "$work/out" "$work/cache"
cp "$root/packaging/aur/bromigos-lab/PKGBUILD" "$work/recipe/"
# A local source cache is used only before the immutable release tag is pushed.
if [[ -n ${2:-} ]]; then cp "$2/"*.tar.gz "$work/cache/"; fi
chown -R builder:builder "$work"
runuser -u builder -- env PKGDEST="$work/out" SRCDEST="$work/cache" bash -ec "cd '$work/recipe'; makepkg --noconfirm; makepkg --printsrcinfo > .SRCINFO"
pacman -U --noconfirm "$work/out/"*.pkg.tar.zst
# Only the standalone package is allowed. Optional desktop dependencies stay absent.
[[ $(pacman -Qq | grep '^bromigos') == bromigos-lab ]]
! command -v bromigos
runuser -u builder -- env PYTHONPATH=/usr/lib/bromigos/lib python "$root/packaging/ci/test-installed-lab.py"
# Verify file ownership against the desktop integration package, without installing it.
source_root=$(find "$work/recipe/src" -maxdepth 1 -type d -name 'bromigOS-*' -print -quit)
mkdir "$work/desktop"
startdir="$source_root/packaging/bromigos-homelab" pkgdir="$work/desktop" bash -ec 'source "$startdir/PKGBUILD"; package'
while IFS= read -r -d '' file; do
  relative=${file#"$work/desktop"}
  [[ ! -e $relative && ! -L $relative ]] || { echo "Desktop package still owns a lab file: $relative" >&2; exit 1; }
done < <(find "$work/desktop" -type f -print0)
printf 'PASS: clean Arch install, CLI, fake doctor, headless TUI, catalog and desktop file ownership\n'
