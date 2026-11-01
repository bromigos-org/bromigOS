#!/usr/bin/env bash
# Field Kit's screens in REAL terminals, captured (the cells are checked by the Rust tests;
# this checks what a terminal actually draws), as iso/test/qr-capture.sh does for the console
# tour: the pairing screen's QR, decoded, and Home with a disk's map, to look at (the map is
# background-coloured cells only, so it keeps one thickness in every font). Each terminal runs in a headless weston of its own (never on the
# desktop you're on), weston's screenshooter takes the picture, and the QR is decoded at 100%,
# 50% and 33% (about what a phone camera sees) with zbarimg, and ZXingReader when it's there.
# At 120x35 the QR must decode; at 80x24 there's no room for one a phone can read, and the
# code is shown big instead (no QR may be found).
#
#   iso/fieldkit/term-capture.sh OUTDIR [--bromigos BIN] [kitty|alacritty …]
#
# BIN (default: bromigos on PATH) runs `bromigos fieldkit pair` and `bromigos fieldkit` against
# a stand-in engine (a code, no pairing; one computer's overview). OUTDIR gets
# fieldkit-pair-TERM-SIZE.png and fieldkit-home-TERM-SIZE.png. The bare VT and kmscon are
# checked in QEMU (iso/fieldkit/ci-test.sh).
set -u
out=${1:?OUTDIR}; shift; mkdir -p "$out"; out=$(cd "$out" && pwd)
bin=$(command -v bromigos || true)
if [[ ${1:-} == --bromigos ]]; then bin=$(realpath "$2"); shift 2; fi
[[ -x $bin ]] || { echo "iso/fieldkit/term-capture.sh: no bromigos to run (--bromigos BIN)" >&2; exit 2; }
terms=("$@"); ((${#terms[@]})) || terms=(kitty alacritty)
url='https://accounts.bromigos.org/device?user_code=KPGGZFVT#machine=k1.3f2a9c0d&n=fieldkit'
stub=$(mktemp -d); trap 'rm -rf "$stub"' EXIT
cat > "$stub/fieldkit-engine" <<S
#!/bin/sh
case " \$* " in
  *" overview "*) echo '{"ok":true,"version":"2026.10.30","network":{"kind":"wired","state":"lan","name":"enp1s0"},"ssh":{"on":false},"stick":"stick settings: 1 SSH key(s)","remote":{"on":false},"computer":{"board":"QEMU Standard PC (Q35 + ICH9, 2009)","cpu":"AMD Ryzen 9 7950X 16-Core Processor (4 threads)","ram":"4.0 GB","gpus":["Red Hat Virtio 1.0 GPU (virtio_gpu)"],"temps":[{"label":"CPU","celsius":41.0},{"label":"GPU","celsius":55.0}]},"load":{"cpu_pct":31.0,"mem_pct":62.5},"disks":[{"name":"vda","path":"/dev/vda","size":256060514304,"model":"","tran":"","health":"ok","parts":[{"name":"vda1","path":"/dev/vda1","size":1073741824,"fstype":"vfat","label":"","parttypename":"EFI System"},{"name":"vda2","path":"/dev/vda2","size":137438953472,"fstype":"crypto_LUKS","label":"","parttypename":"Linux filesystem"},{"name":"vda3","path":"/dev/vda3","size":16777216,"fstype":"","label":"","parttypename":"Microsoft reserved"},{"name":"vda4","path":"/dev/vda4","size":85899345920,"fstype":"BitLocker","label":"","parttypename":"Microsoft basic data"}]}],"found":[{"kind":"bromigos","title":"bromigOS","device":"vda2","state":"encrypted, locked","detail":"","health":"ok"},{"kind":"windows","title":"Windows 11","device":"vda4","state":"BitLocker on","detail":"","health":"ok"},{"kind":"fieldkit","title":"Field Kit stick","device":"sr0","state":"","detail":"this medium"}],"suggestions":[]}' ;;
  *" status "*) echo '{"ok":true,"live":true,"network":"none","remote":{"on":false},"remote_words":"","stick":"stick settings: 1 SSH key(s)","target":{"root":"/mnt/bromigos","hostname":"echo","mounted_by_fieldkit":true,"users":["tester"]}}' ;;
  *" controls "*) echo '{"ok": true, "controls": [{"id": "reboot", "title": "Restart", "available": true, "why": ""}]}' ;;
  *" pair "*) echo '{"ok": true, "installed": true, "state": "waiting", "code": {"user_code": "KPGGZFVT", "verification_uri": "https://accounts.bromigos.org/device", "qr": "$url", "fingerprint": "3f2a9c0d", "lab_name": "fieldkit", "expires_at_ms": 4102444800000}, "message": "In BRODEC: LAB › MACHINES › ADD MACHINE, then scan this code."}' ;;
  *) echo '{"ok": true}' ;;
esac
S
chmod +x "$stub/fieldkit-engine"
decode() {          # decode PNG: the first QR's text, from zbarimg, else ZXingReader
    local r
    r=$(zbarimg -q --raw "$1" 2>/dev/null | head -1)
    if [[ -z $r ]] && command -v ZXingReader >/dev/null; then
        r=$(ZXingReader -format QRCode -fast "$1" 2>/dev/null | sed -n 's/^Text: *"\(.*\)"$/\1/p' | head -1)
    fi
    printf '%s' "$r"
}
fail=0
for term in "${terms[@]}"; do
  for screen in pair home; do
    for geo in "1320 910 120x35" "880 624 80x24"; do
        set -- $geo
        rt=$(mktemp -d); chmod 700 "$rt"
        XDG_RUNTIME_DIR=$rt weston --backend=headless --renderer=pixman --shell=kiosk --width="$1" --height="$2" --debug \
            --socket=wl-q --no-config --idle-time=0 >"$rt/weston.log" 2>&1 &
        wpid=$!
        for _ in $(seq 50); do [[ -S $rt/wl-q ]] && break; sleep 0.1; done
        cmd=(env BROMIGOS_FIELDKIT_ENGINE="$stub/fieldkit-engine" BROMIGOS_FIELDKIT_NO_ROOT=1 BROMIGOS_REDUCED_MOTION=1
             COLORTERM=truecolor "$bin" fieldkit)
        [[ $screen == pair ]] && cmd+=(pair)
        case $term in
            kitty) env -u DISPLAY XDG_RUNTIME_DIR="$rt" WAYLAND_DISPLAY=wl-q HOME="$rt" kitty --config NONE -o font_size=14 \
                       -o linux_display_server=wayland "${cmd[@]}" >/dev/null 2>&1 & ;;
            alacritty) env -u DISPLAY XDG_RUNTIME_DIR="$rt" WAYLAND_DISPLAY=wl-q HOME="$rt" alacritty -o font.size=14 \
                       -e "${cmd[@]}" >/dev/null 2>&1 & ;;
            *) echo "iso/fieldkit/qr-capture.sh: kitty or alacritty, not $term" >&2; exit 2 ;;
        esac
        tpid=$!
        sleep 7
        (cd "$rt" && XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=wl-q weston-screenshooter >/dev/null 2>&1)
        shot=$out/fieldkit-$screen-$term-$3.png
        cp "$(ls "$rt"/wayland-screenshot*.png 2>/dev/null | head -1)" "$shot" 2>/dev/null
        kill "$tpid" "$wpid" 2>/dev/null; wait "$wpid" 2>/dev/null; rm -rf "$rt"
        [[ -s $shot ]] || { echo "FAIL $screen $term $3: no screenshot"; fail=1; continue; }
        [[ $screen == home ]] && { echo "SHOT $screen $term $3: $shot"; continue; }
        for s in 100 50 33; do
            g=$(mktemp --suffix=.png); magick "$shot" -resize "${s}%" "$g" 2>/dev/null
            r=$(decode "$g"); rm -f "$g"
            if [[ $3 == 80x24 ]]; then
                if [[ -z $r ]]; then echo "PASS $term $3 ${s}%: no QR (the code, big)"; else echo "FAIL $term $3 ${s}%: a QR where none fits"; fail=1; fi
            elif [[ $r == "$url" ]]; then
                echo "PASS $term $3 ${s}%: decoded"
            else
                echo "FAIL $term $3 ${s}%: ${r:-no decode}"; fail=1
            fi
        done
    done
  done
done
exit $fail
