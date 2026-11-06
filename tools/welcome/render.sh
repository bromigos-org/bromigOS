#!/usr/bin/env bash
# Offscreen renders of the welcome tour (bromigos welcome --render; manual/src/welcome-tour.md):
#
#   tools/welcome/render.sh OUTDIR [--size WxH] [--only STEP…] [THEME]
#
# (THEME: the theme in force, default wick; --size: the screen, default 1280x800, the tour's
# window size; --only: just these pictures, by name: lab draws welcome-lab*.png)
#
# Each step drawn with its sample data to OUTDIR/welcome-STEP.png, and the Your lab step's
# states too (its three tiles, the link code for a hosted lab and for this computer, approved,
# paired, failed, Find my lab, Ask VECTOR). A headless weston (kiosk shell, pixman) in a
# runtime directory of its own and a throwaway home where this checkout's `bromigos`
# (core/target/debug, or $BROMIGOS; build it first) sets the theme with --no-reload, so
# nothing reaches the desktop you're on: no window, no screenshot of your screen, no reload.
# No password window opens and nothing is linked: the renders feed the tour recorded events.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
out=${1:?OUTDIR}; shift
size=1280x800 theme=wick only=()
while (($#)); do
  case $1 in
    --size) size=$2; shift 2 ;;
    --only) only+=("$2"); shift 2 ;;
    *) theme=$1; shift ;;
  esac
done
bin=${BROMIGOS:-$root/core/target/debug/bromigos}
[[ -x $bin ]] || { echo "render: no $bin (cargo build -p bromigos in core/)" >&2; exit 2; }
mkdir -p "$out"
out=$(cd "$out" && pwd)
# a short runtime path: a Wayland socket's path must fit in 108 bytes
rt=$(mktemp -d /tmp/bwr.XXXX)
work=$(mktemp -d "${TMPDIR:-/tmp}/bromigos-welcome-render.XXXX")
chmod 700 "$rt"
# shellcheck disable=SC2329  # run by the trap
cleanup() {
  [[ -n ${wpid:-} ]] && kill "$wpid" 2>/dev/null
  rm -rf "$rt" "$work"
}
trap cleanup EXIT
w=${size%x*} h=${size#*x}
env -i HOME="$work/home" XDG_RUNTIME_DIR="$rt" PATH=/usr/bin \
  weston --backend=headless --renderer=pixman --shell=kiosk --width="$w" --height="$h" \
         --socket=wl-render --no-config --idle-time=0 >"$work/weston.log" 2>&1 &
wpid=$!
for _ in $(seq 50); do [[ -S $rt/wl-render ]] && break; sleep 0.1; done
[[ -S $rt/wl-render ]] || { echo "render: weston didn't start:" >&2; tail -5 "$work/weston.log" >&2; exit 1; }
mkdir -p "$work/bin" "$work/home"
# `bromigos` for everything here, except `bromigos session`: nothing in a render may find
# the desktop's live session (a launch, a reload)
# shellcheck disable=SC2016  # $1 and $@ are the stand-in's own
printf '#!/bin/sh\n[ "$1" = session ] && exit 0\nexec "%s" "$@"\n' "$bin" >"$work/bin/bromigos"
chmod +x "$work/bin/bromigos"
share=$work/share
mkdir -p "$share"
for d in themes theme live; do ln -s "$root/$d" "$share/$d"; done
run() {
  env -i HOME="$work/home" XDG_RUNTIME_DIR="$rt" WAYLAND_DISPLAY=wl-render GDK_BACKEND=wayland \
    PATH="$work/bin:$root/desktop/bin:/usr/bin" LANG=C.UTF-8 BROMIGOS_SHARE_DIR="$share" \
    PYTHONPATH="$root/desktop/lib:$root/lib:$root/desktop/settings" \
    DBUS_SESSION_BUS_ADDRESS=disabled: DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
    BROMIGOS_WELCOME_ONLY="${only[*]}" GSK_RENDERER="${GSK_RENDERER:-cairo}" "$@"
}
run "$bin" theme set "$theme" --no-reload >/dev/null
if ! run python3 "$root/desktop/bin/bromigos-welcome" --render "$out" 2>"$work/app.log"; then
  echo "render: the tour failed:" >&2; tail -20 "$work/app.log" >&2; exit 1
fi
grep -v '^rendered' "$work/app.log" | grep -E 'Traceback|Error' >&2 && exit 1
exit 0
