#!/usr/bin/env bash
# The graphical installer's steps drawn offscreen (gui.py --render, the fake back end on the
# recorded disks in fixtures/), in a headless weston of its own: no window reaches the
# desktop you're on. docs/iso.md, "Testing it".
#
#   iso/test/installer/render-gui.sh OUTDIR [--size 1280x800] [--scale 1|2] [--probe FIXTURE.json]
#   (the window's size in logical pixels; --scale 2: a HiDPI screen, the pictures twice the size)
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
lib=$here/../../profile/airootfs/usr/local/lib/bromigos-iso
out=${1:?OUTDIR}; shift
size=1280x800 scale=1 probe=$here/fixtures/probe-windows-uefi.json
while (($#)); do case $1 in --size) size=$2; shift 2 ;; --scale) scale=$2; shift 2 ;; --probe) probe=$2; shift 2 ;; *) echo "?? $1" >&2; exit 2 ;; esac; done
mkdir -p "$out"; out=$(cd "$out" && pwd)
rt=$(mktemp -d /tmp/bir.XXXX); chmod 700 "$rt"
# the medium's offline repository as both editions find it (a stand-in: the names only)
store=$rt/store; mkdir -p "$store/bromigos/x86_64"
for p in bromigos-1-1-x86_64 bromigos-desktop-1-1-x86_64 bromigos-core-1-1-x86_64 bromigos-lab-1-1-any; do
    : > "$store/bromigos/x86_64/$p.pkg.tar.zst"
done
trap 'kill $wpid 2>/dev/null || true; rm -rf "$rt"' EXIT
XDG_RUNTIME_DIR=$rt weston --backend=headless --renderer=pixman --shell=kiosk --width="$(( ${size%x*} * scale ))" --height="$(( ${size#*x} * scale ))" --scale="$scale" \
    --socket=wl-render --no-config --idle-time=0 >"$rt/weston.log" 2>&1 &
wpid=$!
for _ in $(seq 50); do [[ -S $rt/wl-render ]] && break; sleep 0.1; done
[[ -S $rt/wl-render ]] || { echo "render-gui: weston didn't start" >&2; cat "$rt/weston.log" >&2; exit 1; }
env -u DISPLAY XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=wl-render GDK_BACKEND=wayland GSK_RENDERER=cairo \
    BROMIGOS_INSTALLER_PROBE="$probe" BROMIGOS_EDITION_DIRS="$lib/../../share/bromigos-iso/editions" \
    BROMIGOS_REDUCED_MOTION=1 BROMIGOS_ISO_REPO_DIR="$store" BROMIGOS_NO_USB=1 PYTHONPATH="$lib" timeout 120 python3 -m bromigos_installer.gui --render "$out" --size "$size"
