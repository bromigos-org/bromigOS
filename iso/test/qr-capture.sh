#!/usr/bin/env bash
# The console tour's pairing QR in a REAL terminal, captured and decoded (iso/test/installer/test_qr.py
# checks the cells; this checks what a terminal actually draws). Each terminal runs in a headless
# weston of its own (never on the desktop you're on), weston's screenshooter takes the picture,
# zbarimg decodes it at 100%, 50% and 33% (about what a phone camera sees).
#
#   iso/test/qr-capture.sh OUTDIR [kitty|alacritty …]      default: kitty alacritty
#
# A stand-in brodec-machine (pair --json: a code, no pairing) is put first on PATH. The bare
# VT is checked in QEMU: docs/iso.md, "Testing it".
set -u
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); root=$here/../..
out=${1:?OUTDIR}; shift; mkdir -p "$out"; out=$(cd "$out" && pwd)
terms=("$@"); ((${#terms[@]})) || terms=(kitty alacritty)
stub=$(mktemp -d); trap 'rm -rf "$stub"' EXIT
cat > "$stub/brodec-machine" <<'S'
#!/bin/sh
[ "$1" = pair ] || exit 2
echo '{"event":"code","kind":"machine","name":"desk","user_code":"KPGGZFVT","user_code_display":"KPGG-ZFVT","qr":"https://accounts.bromigos.org/device#machine=k1.example&n=desk"}'
sleep 600
S
chmod +x "$stub/brodec-machine"; : > "$stub/machine.toml"
fail=0
for term in "${terms[@]}"; do
  for geo in "1320 910 120x35" "880 624 80x24"; do
    set -- $geo
    rt=$(mktemp -d); chmod 700 "$rt"
    XDG_RUNTIME_DIR=$rt weston --backend=headless --renderer=pixman --shell=kiosk --width=$1 --height=$2 --debug \
      --socket=wl-q --no-config --idle-time=0 >"$rt/weston.log" 2>&1 &
    wpid=$!
    for _ in $(seq 50); do [[ -S $rt/wl-q ]] && break; sleep 0.1; done
    cmd=(env PATH="$stub:$PATH" BRODEC_MACHINE_TOML="$stub/machine.toml" PYTHONPATH="$root/lib" BROMIGOS_REDUCED_MOTION=1
         python3 "$root/bin/bromigos-welcome-console" --step phone)
    case $term in
      kitty) env -u DISPLAY XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=wl-q HOME=$rt kitty --config NONE -o font_size=14 \
               -o linux_display_server=wayland "${cmd[@]}" >/dev/null 2>&1 & ;;
      alacritty) env -u DISPLAY XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=wl-q HOME=$rt alacritty -o font.size=14 \
               -e "${cmd[@]}" >/dev/null 2>&1 & ;;
    esac
    tpid=$!
    sleep 7
    (cd "$rt" && XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=wl-q weston-screenshooter >/dev/null 2>&1)
    shot=$out/$term-$3.png
    cp "$(ls "$rt"/wayland-screenshot*.png | head -1)" "$shot" 2>/dev/null
    kill $tpid $wpid 2>/dev/null; wait $wpid 2>/dev/null; rm -rf "$rt"
    for s in 100 50 33; do
      g=$(mktemp --suffix=.png); magick "$shot" -resize ${s}% "$g" 2>/dev/null
      r=$(zbarimg -q --raw "$g" 2>/dev/null | head -1); rm -f "$g"
      if [[ $3 == 80x24 ]]; then          # too small for a readable QR: the code is shown big instead
        [[ -z $r ]] && echo "PASS $term $3 ${s}%: no QR (the code, big)" || { echo "FAIL $term $3 ${s}%: a QR where none fits"; fail=1; }
      else
        [[ $r == https://accounts.bromigos.org/device* ]] && echo "PASS $term $3 ${s}%: decoded" || { echo "FAIL $term $3 ${s}%: ${r:-no decode}"; fail=1; }
      fi
    done
  done
done
exit $fail
