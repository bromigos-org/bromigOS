#!/usr/bin/env bash
# The manual's installer, bromigOS Server and Field Kit pictures (manual/src/images/
# installer-*, server-*, fieldkit-{home,repair,vector}), drawn offscreen from this checkout:
# no window reaches the desktop you're on, and every reading is made up (docs/ASSETS.md,
# "Manual pictures"). Two pictures come from a VM and aren't made here: fieldkit-boot-menu
# (GRUB on the Field Kit medium) and live-welcome-card (the install stick's live desktop).
#
#   tools/screenshots/install-pictures.sh WORKDIR [--bromigos BIN] [--install]
#
# WORKDIR gets the raw renders and webp/, 1280 wide. --install copies webp/ into
# manual/src/images/. BIN (default: bromigos on PATH, else core's release build) draws
# Field Kit. Needs weston, kitty, rsvg-convert, python-textual, python-pillow and the
# MesloLGS Nerd Font Mono font (a terminal font with braille and Nerd Font icons).
# Look at every picture before it goes in: the repository is public.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
work=${1:?WORKDIR}; shift
bin=$(command -v bromigos || echo "$repo/core/target/release/bromigos") install=0
while (($#)); do case $1 in --bromigos) bin=$(realpath "$2"); shift 2 ;; --install) install=1; shift ;; *) echo "?? $1" >&2; exit 2 ;; esac; done
mkdir -p "$work"; work=$(cd "$work" && pwd)
inst=$repo/iso/test/installer
echo "== the graphical installer (desktop, then Server on its own probe)"
# as render-gui.sh draws them (the fake back end, the recorded disks; no USB is read)
"$inst/render-gui.sh" "$work/gui" >/dev/null
BROMIGOS_INSTALLER_RENDER_ONLY=server- "$inst/render-gui.sh" "$work/gui-srv" --probe "$inst/fixtures/probe-server.json" >/dev/null

# the rest in a home of its own: nothing read from, or written to, yours
export HOME=$work/home XDG_STATE_HOME=$work/home/.state XDG_CONFIG_HOME=$work/home/.config XDG_CACHE_HOME=$work/home/.cache
mkdir -p "$HOME"

echo "== the text installer, its server steps and the server's first start"
(cd "$inst" && python3 tui-shots.py "$work/tui" >/dev/null)
(cd "$inst" && BROMIGOS_INSTALLER_SHOTS=$work/srvtui python3 -m unittest -q test_server.TextSteps.test_every_step_draws_and_fits)
PYTHONPATH=$repo/lib python3 "$repo/bin/bromigos-welcome-console" --render "$work/welcome" --size 120x35

echo "== Field Kit in kitty, against term-capture.sh's stand-in engine"
fk=$work/fk; mkdir -p "$fk"
stub=$(mktemp -d); rt=$(mktemp -d); chmod 700 "$rt"
trap 'kill "${tpid:-}" "${wpid:-}" 2>/dev/null; rm -rf "$stub" "$rt"' EXIT
sed -n '/^cat > "\$stub\/fieldkit-engine" <<S$/,/^S$/p' "$repo/iso/fieldkit/term-capture.sh" | sed '1d;$d' \
    | sed 's#\$url#https://accounts.bromigos.org/device?user_code=KPGGZFVT#; s/\\\$/$/g; s/"hostname":"echo"/"hostname":"alex-pc"/' \
    >"$stub/fieldkit-engine"
chmod +x "$stub/fieldkit-engine"
XDG_RUNTIME_DIR=$rt weston --backend=headless --renderer=pixman --shell=kiosk --width=1280 --height=800 --debug \
    --socket=wl-q --no-config --idle-time=0 >"$rt/weston.log" 2>&1 &
wpid=$!
for _ in $(seq 50); do [[ -S $rt/wl-q ]] && break; sleep 0.1; done
env -u DISPLAY XDG_RUNTIME_DIR="$rt" WAYLAND_DISPLAY=wl-q HOME="$rt" kitty --config NONE -o font_size=11 \
    -o allow_remote_control=yes --listen-on "unix:$rt/kitty.sock" -o linux_display_server=wayland \
    env BROMIGOS_FIELDKIT_ENGINE="$stub/fieldkit-engine" BROMIGOS_FIELDKIT_NO_ROOT=1 BROMIGOS_REDUCED_MOTION=1 \
    COLORTERM=truecolor "$bin" fieldkit >/dev/null 2>&1 &
tpid=$!
shoot() {
    rm -f "$rt"/wayland-screenshot*.png
    (cd "$rt" && XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=wl-q weston-screenshooter >/dev/null 2>&1)
    cp "$(ls "$rt"/wayland-screenshot*.png | head -1)" "$fk/$1.png"
}
key() { HOME=$rt kitty @ --to "unix:$rt/kitty.sock" send-key "$@" >/dev/null 2>&1; }
sleep 7; shoot home
key r; sleep 3; shoot repair
key Escape; sleep 1.5; key v; sleep 4; shoot vector
kill "$tpid" "$wpid" 2>/dev/null || true

echo "== to webp"
python3 -I - "$work" <<'PY'
import os, re, subprocess, sys, tempfile
from PIL import Image
work = sys.argv[1]
PICTURES = {    # the manual's name: the render
    "installer-guidance": "gui/gui-guide.png", "installer-before-you-start": "gui/gui-checks.png",
    "installer-kind-of-computer": "gui/gui-edition.png", "installer-where-alongside-windows": "gui/gui-disk.png",
    "installer-where-erase": "gui/gui-disk-erase.png", "installer-bitlocker": "gui/gui-bitlocker.png",
    "installer-about-you": "gui/gui-user.png", "installer-encryption": "gui/gui-encryption.png",
    "installer-summary": "gui/gui-summary.png", "installer-installing": "gui/gui-install.png",
    "installer-done": "gui/gui-done-secureboot.png", "installer-failed": "gui/gui-failed.png",
    "installer-answer-file": "gui/gui-auto.png",
    "installer-text-mode-where": "tui/truecolor-desktop/tui-disk.svg",
    "installer-text-mode-about-you": "tui/truecolor-desktop/tui-user.svg",
    "installer-text-mode-summary": "tui/truecolor-desktop/tui-summary.svg",
    "installer-server-text-mode-role": "tui/truecolor-server/tui-role.svg",
    **{f"server-{n}": f"gui-srv/gui-server-{r}.png" for n, r in (
        ("role", "role"), ("keys", "keys-local"), ("network", "network"), ("access", "access"), ("reach", "reach"),
        ("storage", "storage-raid"), ("unlock", "unlock-tpm"), ("updates", "updates"), ("run", "run-home"),
        ("summary", "summary"), ("done", "done"))},
    **{f"server-welcome-{n}": f"welcome/server-welcome-{n}.svg" for n in ("network", "provision", "done")},
    **{f"fieldkit-{n}": f"fk/{n}.png" for n in ("home", "repair", "vector")},
}


def svg_png(src):
    """A Textual export: just the terminal (no window frame), in a local terminal font."""
    t = open(src).read()
    t = t.replace('font-family: "Fira Code"', 'font-family: "MesloLGS Nerd Font Mono", "Fira Code"')
    t = t.replace("font-family: Fira Code, monospace", 'font-family: "MesloLGS Nerd Font Mono", monospace')
    m = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', t)          # the screen is drawn at 9,41
    t = t.replace(m.group(0), f'viewBox="9 41 {float(m.group(1)) - 18:g} {float(m.group(2)) - 50:g}"', 1)
    t = re.sub(r'<svg([^>]*?) (width|height)="[^"]*"', r"<svg\1", t, count=1)
    t = re.sub(r'<svg([^>]*?) (width|height)="[^"]*"', r"<svg\1", t, count=1)
    fd, svg = tempfile.mkstemp(suffix=".svg"); os.write(fd, t.encode()); os.close(fd)
    png = svg[:-4] + ".png"
    subprocess.run(["rsvg-convert", "-w", "1280", svg, "-o", png], check=True)
    os.unlink(svg)
    return png


os.makedirs(os.path.join(work, "webp"), exist_ok=True)
for name, rel in PICTURES.items():
    src = os.path.join(work, rel)
    png = svg_png(src) if src.endswith(".svg") else src
    im = Image.open(png).convert("RGB")
    if im.width != 1280:
        im = im.resize((1280, round(im.height * 1280 / im.width)), Image.LANCZOS)
    im.save(os.path.join(work, "webp", name + ".webp"), "WEBP", quality=82, method=6)
    if png != src:
        os.unlink(png)
print(len(PICTURES), "pictures in", os.path.join(work, "webp"))
PY
if ((install)); then cp "$work"/webp/*.webp "$repo/manual/src/images/"; echo "copied into manual/src/images/"; fi
