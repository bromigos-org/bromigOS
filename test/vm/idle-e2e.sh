#!/usr/bin/env bash
# shellcheck disable=SC2329,SC2016  # the checks' functions run through check; the VM's commands expand there
# Idle and lock end to end in the fresh-machine VM (docs/idle.md, "Runs"): after
# `test/vm/arch-vm.sh install` (a channel carrying `bromigos idle`) and a reboot into the
# desktop. Everything happens in the VM's own session: commands over SSH, its screen,
# mouse and keyboard through QEMU's monitor. Prints PASS/FAIL per check; exits with the
# number of failures; screenshots in DIR/shots/idle-*.png. About ten minutes.
#
#   test/vm/idle-e2e.sh [--dir DIR]       (BROMIGOS_VM_PORT etc. as arch-vm.sh)
#
# 1. the install: hypridle.conf sources the rendered policy, hypridle runs in the
#    graphical session, the defaults;
# 2. Screensaver only (the screensaver at 1 min, the lock's timer at 2, switched off): the
#    config rendered, hypridle restarted inside the graphical session (its logind scope),
#    the screensaver up after a minute, nothing locked at 2.5 min, a mouse movement ends it;
# 3. stay awake: logind's inhibitor held, no screensaver while it is, gone after `off`;
# 4. the migration: an old hypridle.conf (the packaged source and a listener of the user's)
#    moved by `bromigos idle hook`, `bromigos restart` restarting the stale hypridle, the
#    user's listener still firing;
# 5. the lock through the restarted hypridle: locked at 2 min, unlocked by typing the
#    password; 6. the Settings window on the VM's screen.
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
dir=${BROMIGOS_VM_DIR:-$HOME/.cache/bromigos-vmtest}
[[ ${1:-} == --dir ]] && dir=$2
out=$(mktemp "${TMPDIR:-/tmp}/idle-e2e.XXXX")
trap 'rm -f "$out"' EXIT

vm() { "$here/arch-vm.sh" ssh --dir "$dir" "$@"; }
shot() { "$here/arch-vm.sh" shot --dir "$dir" "idle-$1" >/dev/null && echo "     shot: $dir/shots/idle-$1.png"; }
qmp() { printf '%s\n' '{"execute":"qmp_capabilities"}' "$@" | socat - "UNIX-CONNECT:$dir/qmp.sock" >/dev/null; }
point() { qmp "{\"execute\":\"input-send-event\",\"arguments\":{\"events\":[{\"type\":\"abs\",\"data\":{\"axis\":\"x\",\"value\":$1}},{\"type\":\"abs\",\"data\":{\"axis\":\"y\",\"value\":$2}}]}}"; }
mouse() { point 9000 9000; sleep 0.3; point 12000 11000; sleep 0.3; point 15000 13000; }   # a real movement, in steps
key() { qmp "{\"execute\":\"send-key\",\"arguments\":{\"keys\":[{\"type\":\"qcode\",\"data\":\"$1\"}]}}"; sleep 0.15; }
type_text() { local c; while IFS= read -r -n1 c; do [[ -n $c ]] && key "$c"; done <<<"$1"; }
fails=0
check() {
  local name=$1; shift
  if "$@" >"$out" 2>&1; then echo "PASS $name"; else echo "FAIL $name"; sed 's/^/     /' "$out" | tail -6; fails=$((fails + 1)); fi
}

# what the checks ask
field() { vm "bromigos idle --json" | python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
hook_is() { [[ $(field 'd["hook"]') == "$1" ]]; }
change() {  # bromigos idle ARGS: applied, and this session's hypridle restarted
  vm "bromigos idle $* --json" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=(d.get("applied") or {}).get("restarts") or []; print(r); sys.exit(0 if r and all(x["ok"] for x in r) else 1)'
}
saver() { vm "bromigos session exec hyprctl layers" | grep -q "namespace: bromigos-live-screensaver"; }
no_saver() { ! saver; }
locked() { vm 'pgrep -x gtklock || pgrep -x hyprlock'; }
unlocked() { ! locked; }
session_unlocked() { vm 'loginctl show-session "$(loginctl list-sessions --no-legend | awk "\$4==\"seat0\"{print \$1; exit}")" -p LockedHint' | grep -qx 'LockedHint=no'; }
hypridle_pid() { vm 'pgrep -xo hypridle'; }
in_session() {  # hypridle's cgroup is the compositor's: the graphical logind session, not an SSH one
  local h; h=$(vm 'pgrep -xo Hyprland || pgrep -xo hyprland')
  [[ -n $1 && -n $h ]] && [[ $(vm "cat /proc/$1/cgroup") == "$(vm "cat /proc/$h/cgroup")" ]]
}
restarted() { [[ -n $2 && $1 != "$2" ]] && in_session "$2"; }
wait_until() { local t0=$1 s=$2 now; now=$(date +%s); ((now - t0 < s)) && sleep $((s - (now - t0))); }

echo "== the install"
for _ in $(seq 60); do vm 'bromigos session >/dev/null && pgrep -x hypridle >/dev/null' && break; sleep 5; done
check "the session and hypridle are up" vm 'bromigos session && pgrep -x hypridle'
check "hypridle.conf sources the rendered policy" hook_is rendered
check "the defaults are in force" vm "bromigos idle | head -1 | grep -qx 'Screensaver at 8 min, then the lock at 10 min, then displays off at 15 min. Never suspends.'"
a=$(hypridle_pid)
check "hypridle runs in the graphical session" in_session "$a"
shot defaults

echo "== screensaver only"
check "preset screensaver-only" change preset screensaver-only
check "the screensaver at 1 min, the lock's timer at 2 (it stays off)" change set screensaver 1 lock.minutes 2
t0=$(date +%s)
check "rendered: the screensaver at 60 s, no idle lock, SUPER+L's lock_cmd kept" \
  vm 'f=~/.local/state/bromigos/idle/hypridle.conf; grep -q "timeout = 60" $f && grep -q "ctl screensaver open" $f && ! grep -q "on-timeout = loginctl lock-session" $f && grep -q "lock_cmd = bromigos lock-run" $f'
b=$(hypridle_pid)
check "hypridle restarted in the graphical session ($a -> $b)" restarted "$a" "$b"
check "the bar says NO LOCK" vm '/usr/lib/bromigos/desktop/waybar/idle.py | grep -q "NO LOCK"'
wait_until "$t0" 75
check "the screensaver is up after a minute idle" saver
shot screensaver
wait_until "$t0" 155
check "nothing locked at 2.5 minutes" unlocked
check "logind's session isn't locked" session_unlocked
mouse; sleep 3
check "a mouse movement ends the screensaver" no_saver
shot after-input

echo "== stay awake"
check "stay-awake 1h holds logind's idle inhibitor" vm 'bromigos idle stay-awake 1h >/dev/null && systemd-inhibit --list --no-legend | grep -q "bromigOS.*idle"'
check "the bar shows the cup" vm '/usr/lib/bromigos/desktop/waybar/idle.py | grep -q "AWAKE"'
sleep 2; shot awake
sleep 75
check "no screensaver while staying awake" no_saver
check "off lets it go" vm 'bromigos idle off >/dev/null && ! systemd-inhibit --list --no-legend | grep -q bromigOS'

echo "== the migration"
vm 'cat > ~/.config/hypr/hypridle.conf <<EOF
# Your idle policy: bromigOS'"'"'s (lock at 10 min, displays off at 15), then any listeners of yours.
source = /usr/share/bromigos/default/hypr/hypridle.conf
listener {
    timeout = 30
    on-timeout = touch /tmp/mine-fired
}
EOF
rm -f /tmp/mine-fired'
check "an old hypridle.conf reads as the packaged policy" hook_is packaged
check "restart --check sees hypridle's config changed" vm 'bromigos restart --check | grep -q idle'
check "idle hook moves it, keeping the user's listener" vm 'bromigos idle hook | grep -q "^moved" && grep -q "^source = ~/.local/state/bromigos/idle/hypridle.conf" ~/.config/hypr/hypridle.conf && grep -q mine-fired ~/.config/hypr/hypridle.conf && test -f ~/.local/state/bromigos/idle/hypridle.conf.before-policy'
c=$(hypridle_pid)
check "bromigos restart restarts the stale hypridle" vm 'bromigos restart | grep -q idle'
d=$(hypridle_pid)
check "a new hypridle in the graphical session ($c -> $d)" restarted "$c" "$d"
sleep 40
check "the user's own listener fired" vm 'test -f /tmp/mine-fired'

echo "== the lock, through the restarted hypridle"
check "default preset" change preset default
check "the lock at 2 min" change set screensaver 1 lock 2
t1=$(date +%s)
wait_until "$t1" 135
check "locked at 2 minutes" locked
shot locked
mouse; sleep 1; type_text tester; key ret; sleep 4
check "the password unlocks it" unlocked

echo "== Settings on the VM's screen"
vm 'bromigos idle preset default >/dev/null; bromigos idle set screensaver 8 lock 10 >/dev/null'
vm "bromigos session exec /usr/lib/bromigos/bin/bromigos-dispatch 'hl.dsp.exec_cmd(\"bromigos settings idle\")' exec bromigos settings idle" >/dev/null
sleep 6
check "the Settings window opened" vm 'bromigos session exec hyprctl clients | grep -q "org.bromigos.Settings"'
shot settings
check "the defaults again" vm "bromigos idle | head -1 | grep -q '^Screensaver at 8 min, then the lock at 10 min'"
echo "$fails failed"
exit $fails
