#!/usr/bin/env bash
# Offscreen renders of the Settings window (docs/settings.md, "Tests"), one per theme:
#
#   tools/settings/render.sh OUTDIR [--page PAGE]… [--size WxH] [--idle "ARGS"] [--name SUFFIX] [--interact]
#                            [--path DIR] [--previews DIR] [--fixtures] [--audit] [--search WORDS] [--advanced]
#                            [THEME…]
#
# (no theme: every one; --idle: `bromigos idle ARGS` first, e.g. "preset screensaver-only";
# --interact: then drive the Idle & lock page's controls, interact.py, in the last theme;
# --path: a folder of stand-in commands put first on PATH, e.g. a `bromigos-lab` answering
# from recorded JSON, so a page that reads a service renders without one; --previews: the
# theme previews the Theme page shows, an earlier tools/theme-switcher/render.sh's; --fixtures: the
# stand-ins in desktop/tests/fixtures/bin (pactl, nmcli, bluetoothctl, hyprctl … answering
# as one made-up machine, a laptop: its sysfs, apps and pacman log too; each theme with its
# own copy of its state); --audit: each page's
# controls without a hover hint, its search entries without a row and rows wider than the
# window, to OUTDIR/audit.jsonl; --search: the sidebar's results for WORDS; --advanced:
# every row's Advanced line open)
#
# A headless weston (kiosk shell, pixman) in a runtime directory of its own, so nothing
# reaches the desktop you're on: no window, no screenshot of your screen. A throwaway home
# where this checkout's `bromigos` (core/target/debug, or $BROMIGOS; build it first) renders
# each theme and the idle policy; the window drawn with GTK's own renderer to
# OUTDIR/<theme>-<page>.png. Prints one line per image; exits non-zero if any failed.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
out=${1:?OUTDIR}; shift
pages=() size=1120x780 themes=() idle_args='' suffix='' interact= extra_path= previews= extra=()
while (($#)); do
  case $1 in
    --page) pages+=("$2"); shift 2 ;;
    --previews) previews=$(cd "$2" && pwd); shift 2 ;;
    --size) size=$2; shift 2 ;;
    --idle) idle_args=$2; shift 2 ;;
    --name) suffix=-$2; shift 2 ;;
    --interact) interact=1; shift ;;
    --path) extra_path=$(cd "$2" && pwd):$extra_path; shift 2 ;;
    --fixtures) extra_path=$root/desktop/tests/fixtures/bin:$extra_path; fixtures=1; shift ;;
    --audit) extra+=(--audit); audit=1; shift ;;
    --search) extra+=(--search "$2"); shift 2 ;;
    --advanced) extra+=(--advanced); shift ;;
    *) themes+=("$1"); shift ;;
  esac
done
((${#pages[@]})) || pages=(idle)
bin=${BROMIGOS:-$root/core/target/debug/bromigos}
[[ -x $bin ]] || { echo "render: no $bin (cargo build -p bromigos in core/)" >&2; exit 2; }
if ((${#themes[@]} == 0)); then
  for d in "$root"/themes/*/; do themes+=("$(basename "$d")"); done
fi
mkdir -p "$out"
out=$(cd "$out" && pwd)
# a short runtime path: a Wayland socket's path must fit in 108 bytes
rt=$(mktemp -d /tmp/bsr.XXXX)
work=$(mktemp -d "${TMPDIR:-/tmp}/bromigos-settings-render.XXXX")
chmod 700 "$rt"
# shellcheck disable=SC2329  # run by the trap
cleanup() { [[ -n ${wpid:-} ]] && kill "$wpid" 2>/dev/null; rm -rf "$rt" "$work"; }
trap cleanup EXIT
w=${size%x*} h=${size#*x}
env -i HOME="$work/home" XDG_RUNTIME_DIR="$rt" PATH=/usr/bin \
  weston --backend=headless --renderer=pixman --shell=kiosk --width="$w" --height="$h" \
         --socket=wl-render --no-config --idle-time=0 >"$work/weston.log" 2>&1 &
wpid=$!
for _ in $(seq 50); do [[ -S $rt/wl-render ]] && break; sleep 0.1; done
[[ -S $rt/wl-render ]] || { echo "render: weston didn't start:" >&2; tail -5 "$work/weston.log" >&2; exit 1; }
mkdir -p "$work/bin"
# `bromigos` for everything here, except `bromigos session`: nothing in a render may find
# the desktop's live session (a launch, a reload)
printf '#!/bin/sh\n[ "$1" = session ] && exit 0\nexec "%s" "$@"\n' "$bin" >"$work/bin/bromigos"
chmod +x "$work/bin/bromigos"
# /usr/share/bromigos as the packages lay it out, from this checkout (the defaults the
# Shortcuts page reads, the idle and live defaults, the themes)
share=$work/share
mkdir -p "$share/default" "$share/idle" "$share/widgets"
for d in themes theme live migrations peripherals; do ln -s "$root/$d" "$share/$d"; done
ln -s "$root/desktop/hooks" "$share/hooks"
for d in hypr waybar rofi dunst gtklock zsh user; do ln -s "$root/desktop/$d" "$share/default/$d"; done
ln -s "$root/core/crates/bromigos-core/idle/idle.toml" "$share/default/idle.toml"
ln -s "$root/core/crates/bromigos-core/idle/hypridle.conf.tpl" "$share/idle/hypridle.conf.tpl"
ln -s "$root/core/crates/bromigos-art/targets.default.toml" "$share/default/targets.toml"
ln -s "$root/core/crates/bromigos-art/create.default.toml" "$share/default/create.toml"
ln -s "$root/homelab/share/homelab.toml" "$share/default/homelab.toml"
ln -s "$root/widgets/layout.json" "$share/widgets/layout.json"
fails=0
for t in "${themes[@]}"; do
  home=$work/home-$t
  mkdir -p "$home"
  run() {
    env -i HOME="$home" XDG_RUNTIME_DIR="$rt" WAYLAND_DISPLAY=wl-render GDK_BACKEND=wayland \
      PATH="$extra_path$work/bin:$root/desktop/bin:$root/desktop/settings:/usr/bin" LANG=C.UTF-8 TZ="${TZ:-America/Los_Angeles}" BROMIGOS_SHARE_DIR="$share" \
      PYTHONPATH="$root/desktop/lib:$root/lib" BROMIGOS_FIXTURE_STATE="${fixtures:+$work/fixtures-$t}" \
      BROMIGOS_REAL="$work/bin/bromigos" \
      ${fixtures:+XDG_DATA_DIRS=$root/desktop/tests/fixtures/share:/usr/share} \
      ${fixtures:+BROMIGOS_SYSFS=$root/desktop/tests/fixtures/sysfs/sys BROMIGOS_PROC=$root/desktop/tests/fixtures/sysfs/proc} \
      ${fixtures:+BROMIGOS_PACMAN_LOG=$root/desktop/tests/fixtures/pacman.log} \
      DBUS_SESSION_BUS_ADDRESS=disabled: DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \
      BROMIGOS_SETTINGS_PAGES="${BROMIGOS_SETTINGS_PAGES:-}" GSK_RENDERER="${GSK_RENDERER:-cairo}" "$@"
  }
  # the thin hyprland.lua a new user starts from (the Shortcuts page reads it)
  mkdir -p "$home/.config/hypr" && cp "$root/desktop/user/hypr/hyprland.lua" "$home/.config/hypr/hyprland.lua"
  # the theme previews the Theme page shows: an earlier tools/theme-switcher/render.sh's
  if [[ -n $previews ]]; then
    mkdir -p "$home/.cache/bromigos" && ln -sfn "$previews" "$home/.cache/bromigos/theme-previews"
  fi
  run "$bin" theme set "$t" --no-reload >/dev/null
  run "$bin" idle hook >/dev/null
  # shellcheck disable=SC2086  # the words of --idle
  [[ -z $idle_args ]] || run "$bin" idle $idle_args --no-restart >/dev/null
  for p in "${pages[@]}"; do
    if [[ -n ${audit:-} ]]; then
      if ! run python3 "$root/desktop/settings/bromigos-settings" --render "$out/$t-$p$suffix.png" --page "$p" \
           --size "$size" "${extra[@]}" 2>>"${BROMIGOS_RENDER_LOG:-$work/app.log}" >>"$out/audit.jsonl"; then
        echo "FAILED $t $p"; tail -5 "$work/app.log"; fails=$((fails + 1))
      else
        echo "rendered $out/$t-$p$suffix.png (audit in $out/audit.jsonl)"
      fi
    elif ! run python3 "$root/desktop/settings/bromigos-settings" --render "$out/$t-$p$suffix.png" --page "$p" \
         --size "$size" "${extra[@]}" 2>>"${BROMIGOS_RENDER_LOG:-$work/app.log}"; then
      echo "FAILED $t $p"; tail -5 "$work/app.log"; fails=$((fails + 1))
    fi
  done
done
if [[ -n $interact ]]; then
  run "$bin" idle preset default --no-restart >/dev/null
  run python3 "$here/interact.py" "$root/desktop/settings" 2>>"$work/app.log" | grep -E '^(PASS|FAIL|[0-9]+ steps)' ||
    fails=$((fails + 1))
fi
exit $fails
