#!/usr/bin/env bash
# Offscreen pictures of Zettlr in bromigOS themes (docs/theming.md, "Zettlr"):
#
#   tools/zettlr/render.sh OUTDIR [--theme NAME]… [--size WxH]
#
# (no --theme: wick and tidewell; --size: 1600x1000) Writes OUTDIR/zettlr-NAME.png.
#
# Everything happens in a throwaway home: this checkout's `bromigos` (core/target/debug,
# or $BROMIGOS; build it first) renders the theme with --no-reload, the `zettlr` theme-set
# hook merges it into that home's ~/.config/Zettlr/custom.css next to a rule of "the
# user's", and Zettlr starts in a headless weston of its own (kiosk shell, pixman). Node
# drives it over the DevTools protocol (shot.mjs) and saves the window. Nothing reaches the
# desktop you're on: no window, no screenshot of your screen, no reload. Needs zettlr,
# weston and node.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
out=${1:?OUTDIR}; shift
themes=() size=1600x1000
while (($#)); do
  case $1 in
    --theme) themes+=("$2"); shift 2 ;;
    --size) size=$2; shift 2 ;;
    *) echo "render: unknown argument $1" >&2; exit 2 ;;
  esac
done
((${#themes[@]})) || themes=(wick tidewell)
bin=${BROMIGOS:-$root/core/target/debug/bromigos}
[[ -x $bin ]] || { echo "render: no $bin (cargo build -p bromigos in core/)" >&2; exit 2; }
for tool in zettlr weston node; do
  command -v "$tool" >/dev/null || { echo "render: needs $tool" >&2; exit 2; }
done
mkdir -p "$out"
out=$(cd "$out" && pwd)
# short: a Wayland socket's path must fit in 108 bytes
work=$(mktemp -d "${TMPDIR:-/tmp}/bzr.XXXX")
wpid='' zpid=''
# shellcheck disable=SC2329  # run by the trap
cleanup() {
  [[ -n $zpid ]] && kill "$zpid" 2>/dev/null && wait "$zpid" 2>/dev/null
  [[ -n $wpid ]] && kill "$wpid" 2>/dev/null && wait "$wpid" 2>/dev/null
  rm -rf "$work"
}
trap cleanup EXIT
home=$work/home
mkdir -p "$home/notes" "$home/.config/Zettlr" "$work/run"
chmod 700 "$work/run"

# a note with every part the theme colours
cat >"$home/notes/Field notes.md" <<'EOF'
---
title: Field notes
tags: [den, signal]
---

# Field notes

The **signal** came in at 03:14. See [the log](https://example.org/log) and [[Second note]].

## Checklist

- [x] Tune the receiver
- [ ] Trace the carrier #signal

> A quote from the notebook, with `inline code` inside it.

```python
def tune(freq: float) -> str:
    """Lock on to a carrier."""
    return f"locked {freq:.2f} MHz"  # comment
```

### Table

| Band | Strength |
|------|----------|
| VHF  | 0.82     |

Some ==highlighted== text and a footnote.[^1]

[^1]: The footnote.
EOF
printf '# Second note\n\nAnother note.\n' >"$home/notes/Second note.md"
# the user's own custom CSS, which the hook must keep
printf '/* Enter your custom CSS here */\n\n/* mine: a little more room between lines */\n.cm-editor { --zettlr-editor-line-height: 1.6 !important; }\n' \
  >"$home/.config/Zettlr/custom.css"
# Zettlr's settings as after its first start (so no welcome window), with the workspace open
version=$(pacman -Q zettlr 2>/dev/null | awk '{print $2}' | cut -d- -f1)
cat >"$home/.config/Zettlr/config.json" <<EOF
{"version": "${version:-4.8.0}", "darkMode": false, "autoDarkMode": "off",
 "app": {"openWorkspaces": ["$home/notes"], "openFiles": ["$home/notes/Field notes.md"],
         "fileManagerVisible": true, "sidebarVisible": true, "currentSidebarTab": "toc"}}
EOF

XDG_RUNTIME_DIR=$work/run weston --backend=headless --renderer=pixman --shell=kiosk \
  --width="${size%x*}" --height="${size#*x}" --socket=wl-zr --no-config --idle-time=0 \
  >"$work/weston.log" 2>&1 &
wpid=$!
for _ in $(seq 50); do [[ -S $work/run/wl-zr ]] && break; sleep 0.1; done
[[ -S $work/run/wl-zr ]] || { echo "render: weston didn't start:" >&2; tail -5 "$work/weston.log" >&2; exit 1; }

port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
fails=0
for theme in "${themes[@]}"; do
  env -i HOME="$home" PATH=/usr/bin BROMIGOS_SHARE_DIR="$root" "$bin" theme set "$theme" --no-reload >/dev/null
  env -i HOME="$home" PATH=/usr/bin BROMIGOS_ZETTLR_RUNNING=0 \
    BROMIGOS_THEME_DIR="$home/.local/state/bromigos/theme/current" "$root/desktop/hooks/theme-set.d/zettlr"
  # Zettlr reads custom.css when it starts: a fresh start per theme
  env -i HOME="$home" PATH=/usr/bin XDG_RUNTIME_DIR="$work/run" WAYLAND_DISPLAY=wl-zr LANG=en_US.UTF-8 \
    zettlr --ozone-platform=wayland --remote-debugging-port="$port" >"$work/zettlr-$theme.log" 2>&1 &
  zpid=$!
  if node "$here/shot.mjs" "$port" "Field notes" "$out/zettlr-$theme.png"; then
    echo "$out/zettlr-$theme.png"
  else
    fails=$((fails + 1))
    tail -5 "$work/zettlr-$theme.log" >&2
  fi
  kill "$zpid" 2>/dev/null && wait "$zpid" 2>/dev/null || true
  zpid=''
done
exit "$fails"
