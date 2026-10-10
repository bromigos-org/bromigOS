#!/usr/bin/env bash
# Run only in a disposable Arch container. Never on the operator's desktop.
set -euo pipefail
root=${1:?checkout path}
[[ -e /.dockerenv || -n ${BROMIGOS_TEST_CONTAINER:-} ]] || { echo 'Use a disposable Arch container' >&2; exit 1; }
pacman -Syu --noconfirm --needed git gnupg sudo >/dev/null
id builder >/dev/null 2>&1 || useradd -m builder
work=$(mktemp -d)
mkdir -p "$work/keyring" "$work/mirrorlist" "$work/out"
cp "$root/packaging/aur/bromigos-keyring/"* "$work/keyring/"
cp "$root/packaging/aur/bromigos-mirrorlist/"* "$work/mirrorlist/"
chown -R builder:builder "$work"
for package in mirrorlist keyring; do
  runuser -u builder -- env PKGDEST="$work/out" bash -ec "cd '$work/$package'; makepkg --nodeps --noconfirm; makepkg --printsrcinfo > .SRCINFO"
done
pacman-key --init >/dev/null 2>&1
pacman-key --populate archlinux >/dev/null 2>&1
pacman -U --noconfirm "$work/out/"*.pkg.tar.zst
# The packages must not add a repo themselves.
if grep -qx '\[bromigos\]' /etc/pacman.conf; then
  echo 'A package edited pacman.conf' >&2
  exit 1
fi
printf '\n[bromigos]\nInclude = /etc/pacman.d/bromigos-mirrorlist\n' >> /etc/pacman.conf
pacman -Sy --noconfirm
# Downloading also verifies a signed package with the key installed above.
pacman -Sw --noconfirm --nodeps bromigos-core
pacman-key --finger 393E7D54F7DE58FE75B97214947C9D6193D3DD8B >/dev/null
printf 'AUR bootstrap: both packages installed; repository and signed core package verified.\n'
