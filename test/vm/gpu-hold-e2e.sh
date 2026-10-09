#!/usr/bin/env bash
# The driver-update hold, end to end, inside the fresh-machine VM (docs/update.md, "When the
# kernel or the graphics driver changes"). Run it signed in to the VM's desktop:
#
#   test/vm/arch-vm.sh ssh 'bash -s' < test/vm/gpu-hold-e2e.sh            # or, with another build:
#   scp core/target/debug/bromigos …:/tmp/bromigos-new; … 'BROMIGOS=/tmp/bromigos-new bash -s' < …
#
# The VM has no NVIDIA GPU, so the mismatch is faked with BROMIGOS_GPU_ROOT: a module file
# saying 615.71.09 and a library named for 615.78.08, as on 2026-10-09. The live layer
# and the panels are made stale by reinstalling their packages. Then:
#   1. the update with the mismatch holds the live layer back (its PID stays), restarts the
#      panels, ends with the restart line, and sends one notification;
#   2. the same update with the driver in step restarts the live layer.
# Prints PASS/FAIL per check; exits with the number of failures.
set -uo pipefail
bro=${BROMIGOS:-bromigos}
fails=0
pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; fails=$((fails + 1)); }
pid_of() { pgrep -f -- "$1" | head -1; }
stale() {       # reinstall the packages from pacman's cache: installed after their processes started
    local p f
    for p in "$@"; do
        f=$(ls -t /var/cache/pacman/pkg/"$p"-[0-9]*.pkg.tar.zst | head -1)
        sudo pacman -U --noconfirm "$f" >/dev/null 2>&1 || echo "could not reinstall $p"
    done
}

$bro session >/dev/null 2>&1 || { echo "no desktop session: sign in first"; exit 1; }
gpu=$(mktemp -d)
mkdir -p "$gpu/sys/module/nvidia" "$gpu/usr/lib"
echo 615.71.09 > "$gpu/sys/module/nvidia/version"
touch "$gpu/usr/lib/libEGL_nvidia.so.615.78.08"
dunstctl history-clear 2>/dev/null

echo "== 1. the driver waits for a restart"
live=$(pid_of 'python3 -m live.app'); widgets=$(pid_of 'bromigos-widgets')
[[ -n $live && -n $widgets ]] || { echo "the live layer and the panels must run (live $live, widgets $widgets)"; exit 1; }
stale bromigos-live bromigos-widgets
$bro restart --check | grep -E '^  (live|widgets) ' | sed 's/^/  before: /'
out=$(BROMIGOS_GPU_ROOT=$gpu BROMIGOS_NO_PREVIEWS= $bro update --no-packages 2>&1)
echo "$out" | sed -n '/== restarts:/,$p'
grep -q '^  live      held back: restart the computer to run it' <<<"$out" && pass "the live layer held back" || fail "the live layer wasn't held back"
grep -q '^  widgets   restarted' <<<"$out" && pass "the panels restarted" || fail "the panels weren't restarted"
grep -q '^  driver    reboot to run it' <<<"$out" && pass "the driver's line" || fail "no driver line"
last=$(tail -1 <<<"$out")
[[ $last == "The graphics driver was updated: restart the computer to use it. Until then, the animated background keeps running as it is." ]] \
    && pass "the last line: $last" || fail "the last line: $last"
sleep 1
[[ $(pid_of 'python3 -m live.app') == "$live" ]] && pass "the live layer's process is the same (PID $live)" || fail "the live layer was restarted"
[[ $(pid_of 'bromigos-widgets') != "$widgets" ]] && pass "the panels' process is new" || fail "the panels' process is the same"
# shown now, or already in dunst's history: one
n=$(( $(dunstctl count displayed 2>/dev/null || echo 0) + $(dunstctl count history 2>/dev/null || echo 0) ))
[[ $n == 1 ]] && pass "one notification" || fail "notifications: $n"
json=$(BROMIGOS_GPU_ROOT=$gpu $bro update --no-packages --json 2>/dev/null)
python3 -c 'import json,sys; r=json.loads(sys.argv[1])["report"]["reboot"]; assert r["driver"]["running"]=="615.71.09" and r["driver"]["installed"]=="615.78.08" and "live" in r["held"], r' "$json" \
    && pass "--json: report.reboot names the driver and what was held" || fail "--json: $json"

echo "== 2. the driver in step: the live layer restarts"
echo 615.78.08 > "$gpu/sys/module/nvidia/version"
out=$(BROMIGOS_GPU_ROOT=$gpu $bro update --no-packages 2>&1)
echo "$out" | sed -n '/== restarts:/,$p'
grep -q '^  live      restarted' <<<"$out" && pass "the live layer restarted" || fail "the live layer wasn't restarted"
grep -q 'restart the computer' <<<"$out" && fail "a restart line without a mismatch" || pass "no restart line"
sleep 3
new=$(pid_of 'python3 -m live.app')
[[ -n $new && $new != "$live" ]] && pass "a new live layer process (PID $new)" || fail "no new live layer ($new)"

rm -rf "$gpu"
echo "$fails failed"
exit "$fails"
