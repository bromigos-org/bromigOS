#!/usr/bin/env bash
# Offscreen renders of the theme switcher (docs/theming.md, "The theme switcher"), one per
# monitor size:
#
#   tools/theme-switcher/render.sh OUTDIR [--size WxH]… [--theme NAME] [--previews DIR] [--select NAME]
#                                  [--filter TEXT] [--catalog FILE] [--name SUFFIX] [--backdrop IMAGE]
#                                  [--tab themes|widgets] [--save-layout]
#
# (no --size: 1366x768, 1920x1080, 2560x1440 and 3440x1440; --theme: the theme in force,
# default wick; --previews: a cache of previews to reuse instead of drawing them, the
# OUTDIR/previews of an earlier run; --catalog: a JSON file of catalog themes to show;
# --backdrop: the desktop behind it, instead of the theme in force's preview, e.g. a full-size
# `bromigos theme previews NAME --size WxH --out` picture; --tab: the Customize window's tab,
# the widgets with demo readings)
#
# A throwaway home where this checkout's `bromigos` (core/target/debug, or $BROMIGOS;
# build it first) sets the theme and `bromigos theme previews` draws every preview into
# OUTDIR/previews (offscreen: the live layer on EGL, kitty and the bar in a headless
# compositor of its own). Then, per size, a headless weston (kiosk shell, pixman) of that
# size in a runtime directory of its own, the switcher in it drawn with GTK's own renderer
# to OUTDIR/switcher-WxH.png, over the preview of the theme in force as the desktop behind
# it. Nothing reaches the desktop you're on: no window, no screenshot of your screen.
# Then (when it drew the previews) check.py: a preview for every theme, each different,
# the switcher at every size. Exit status: the number of failures.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
out=${1:?OUTDIR}; shift
sizes=() theme=wick previews='' select='' filter='' catalog='' suffix='' backdrop_in='' tab=themes save_layout=false
while (($#)); do
  case $1 in
    --size) sizes+=("$2"); shift 2 ;;
    --theme) theme=$2; shift 2 ;;
    --previews) previews=$2; shift 2 ;;
    --select) select=$2; shift 2 ;;
    --filter) filter=$2; shift 2 ;;
    --catalog) catalog=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); shift 2 ;;
    --name) suffix=-$2; shift 2 ;;
    --backdrop) backdrop_in=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); shift 2 ;;
    --tab) tab=$2; shift 2 ;;
    --save-layout) save_layout=true; tab=widgets; shift ;;
    *) echo "render: unknown argument $1" >&2; exit 2 ;;
  esac
done
((${#sizes[@]})) || sizes=(1366x768 1920x1080 2560x1440 3440x1440)
bin=${BROMIGOS:-$root/core/target/debug/bromigos}
[[ -x $bin ]] || { echo "render: no $bin (cargo build -p bromigos in core/)" >&2; exit 2; }
mkdir -p "$out"
out=$(cd "$out" && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/bromigos-switcher-render.XXXX")
rt=''
wpid=''
# shellcheck disable=SC2329  # run by the trap
cleanup() {
  [[ -n $wpid ]] && kill "$wpid" 2>/dev/null && wait "$wpid" 2>/dev/null
  [[ -n $rt ]] && rm -rf "$rt"
  rm -rf "$work"
}
trap cleanup EXIT
mkdir -p "$work/bin" "$work/home" "$work/config" "$work/state" "$work/data" "$work/run"
chmod 700 "$work/run"
# `bromigos` for everything here, except `bromigos session`: nothing in this run may find
# the desktop's live session (a window or a reload could reach it)
cat >"$work/bin/bromigos" <<EOF
#!/bin/sh
[ "\$1" = session ] && exit 0
# this checkout's commands (bromigos panels, …), and the widgets' demo readings
export BROMIGOS_LIB_BIN="$root/desktop/bin" BROMIGOS_WIDGETS_DEMO=1
exec "$bin" "\$@"
EOF
chmod +x "$work/bin/bromigos"
if [[ -n $previews ]]; then
  mkdir -p "$work/cache/bromigos"
  ln -s "$(cd "$previews" && pwd)" "$work/cache/bromigos/theme-previews"
else
  mkdir -p "$out/previews" "$work/cache/bromigos"
  ln -s "$out/previews" "$work/cache/bromigos/theme-previews"
fi
run() {
  env -i HOME="$work/home" XDG_CONFIG_HOME="$work/config" XDG_STATE_HOME="$work/state" \
    XDG_CACHE_HOME="$work/cache" XDG_DATA_HOME="$work/data" XDG_RUNTIME_DIR="${RUNDIR:-$work/run}" \
    PATH="$work/bin:$root/desktop/bin:/usr/bin:/bin" LANG=C.UTF-8 TZ=UTC BROMIGOS="$work/bin/bromigos" \
    BROMIGOS_THEME_CATALOG="$catalog" NO_AT_BRIDGE=1 GSK_RENDERER=cairo BROMIGOS_PREVIEWS_HOLD="${BROMIGOS_PREVIEWS_HOLD:-}" \
    ${__EGL_VENDOR_LIBRARY_FILENAMES:+__EGL_VENDOR_LIBRARY_FILENAMES="$__EGL_VENDOR_LIBRARY_FILENAMES"} \
    "$@"
}
run bromigos theme set "$theme" --no-reload >/dev/null
if [[ -z $previews ]]; then
  echo "drawing the previews (bromigos theme previews) into $out/previews"
  run python3 "$root/desktop/bin/bromigos-theme-previews" || { echo "render: some previews failed" >&2; }
fi
hex12='[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'
# NAME-STAMP.jpg only: wick's preview, never wick-mire's
# shellcheck disable=SC2086
backdrop=${backdrop_in:-$(ls -t "$work/cache/bromigos/theme-previews/$theme"-$hex12.jpg 2>/dev/null | head -1 || true)}
fails=0
for s in "${sizes[@]}"; do
  w=${s%x*} h=${s#*x}
  # a short runtime path: a Wayland socket's path must fit in 108 bytes
  rt=$(mktemp -d /tmp/bts.XXXX)
  chmod 700 "$rt"
  env -i HOME="$work/home" XDG_RUNTIME_DIR="$rt" PATH=/usr/bin \
    weston --backend=headless --renderer=pixman --shell=kiosk --width="$w" --height="$h" \
           --socket=wl-render --no-config --idle-time=0 >"$work/weston-$s.log" 2>&1 &
  wpid=$!
  for _ in $(seq 50); do [[ -S $rt/wl-render ]] && break; sleep 0.1; done
  [[ -S $rt/wl-render ]] || { echo "render: weston didn't start:" >&2; tail -5 "$work/weston-$s.log" >&2; exit 1; }
  args=(--screenshot "$out/switcher-$s$suffix.png" --size "$s" --tab "$tab")
  [[ $save_layout == true ]] && args+=(--save-layout)
  [[ -n $backdrop ]] && args+=(--backdrop "$backdrop")
  [[ -n $select ]] && args+=(--select "$select")
  [[ -n $filter ]] && args+=(--filter "$filter")
  [[ -n $catalog ]] && args+=(--catalog)
  if ! RUNDIR=$rt run env WAYLAND_DISPLAY=wl-render GDK_BACKEND=wayland \
       python3 "$root/desktop/bin/bromigos-theme-switcher" "${args[@]}" 2>>"$work/app.log"; then
    echo "FAILED $s"; tail -5 "$work/app.log"; fails=$((fails + 1))
  fi
  kill "$wpid" 2>/dev/null; wait "$wpid" 2>/dev/null || true
  wpid=''
  rm -rf "$rt"; rt=''
done
# drawn here: every theme has a preview, each its own, the switcher at every size
if [[ -z $previews && -z $suffix ]]; then
  python3 "$here/check.py" "$out" "${sizes[@]}" || fails=$((fails + 1))
fi
exit $fails
