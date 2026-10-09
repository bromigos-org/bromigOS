#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2329  # the VM's commands expand there; the checks' functions run through check
# Hyprland during a package transaction, in the fresh-machine VM (docs/update.md,
# "Hyprland during a package transaction"): a plain `pacman -U` of a changed
# bromigos-desktop while the signed-in desktop runs with auto-reload on. After
# `test/vm/arch-vm.sh install`, a reboot and a login, with a bromigos-core that has the
# hooks installed in the VM. Prints PASS/FAIL per check; exits with the number of failures.
#
#   test/vm/hypr-hold-e2e.sh --desktop PKG [--dir DIR]   (BROMIGOS_VM_PORT etc. as arch-vm.sh)
#
# PKG is a bromigos-desktop package (packaging/dev-repo.sh builds one). Two variants of it
# are made here, A and B: each adds a function to bromigos/keys.lua that only it has
# (M.vmtest_a or _b, binding SUPER+CTRL+ALT+F12), calls it at the top of bromigos/binds.lua,
# and carries 96 MiB in bromigos/bulk.bin, which pacman extracts between those two files.
# A reload in that second reads the new binds.lua with the old keys.lua: a Lua error before
# any bind, Hyprland's emergency mode. While each transaction runs, a monitor in the VM
# records Hyprland's `configreloaded` events and polls its binds and auto-reload.
#
# 1. with the hooks: A, then B: no reload while the files change, exactly one after them,
#    the binds never drop, B's bind is live, no config errors, auto-reload back on, nothing
#    left held;
# 2. a transaction killed mid-way (SIGKILL to pacman while it writes A over B): the hold's
#    watcher releases, the half-written set isn't reloaded, B's config still runs;
# 3. the original package back;
# 4. without the hooks (moved aside: the control), last: the reloads mid-transaction, the
#    emergency mode, or Hyprland wedged (then the VM needs a reboot and a login).
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
dir=${BROMIGOS_VM_DIR:-$HOME/.cache/bromigos-vmtest}
pkg=''
while (($#)); do
  case $1 in --dir) dir=$2; shift 2 ;; --desktop) pkg=$2; shift 2 ;; *) echo "unknown: $1" >&2; exit 2 ;; esac
done
[[ -f $pkg ]] || { echo "hypr-hold-e2e: --desktop PKG (a bromigos-desktop package)" >&2; exit 2; }
work=$(mktemp -d "${TMPDIR:-/tmp}/hypr-hold-e2e.XXXX")
out=$work/check.out
trap 'rm -rf "$work"' EXIT

vm() { "$here/arch-vm.sh" ssh --dir "$dir" "$@"; }
vm_put() { scp -q -i "$dir/id_ed25519" -P "${BROMIGOS_VM_PORT:-2222}" -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "$@" tester@127.0.0.1: ; }
fails=0
check() {
  local name=$1; shift
  if "$@" >"$out" 2>&1; then echo "PASS $name"; else echo "FAIL $name"; sed 's/^/     /' "$out" | tail -8; fails=$((fails + 1)); fi
}

# ---- the variants, made on this machine from PKG (makepkg: a real package, its own .MTREE)
variant() {  # NAME: $work/NAME/bromigos-desktop-*.pkg.tar.zst
  local v=$1 d=$work/$1 base ver
  mkdir -p "$d/tree"
  bsdtar -xf "$pkg" -C "$d/tree" --exclude .PKGINFO --exclude .MTREE --exclude .BUILDINFO --exclude .INSTALL
  ver=$(bsdtar -xOf "$pkg" .PKGINFO | sed -n 's/^pkgver = //p')
  base=${ver%-*}
  local hypr=$d/tree/usr/share/bromigos/default/hypr/bromigos
  # keys.lua: the function before its last `return M`; binds.lua: called before any bind
  python3 - "$hypr/keys.lua" "$hypr/binds.lua" "$v" <<'EOF'
import sys
keys, binds, v = sys.argv[1:]
k = open(keys).read()
i = k.rstrip().rfind("return M")
k = k[:i] + f'-- test/vm/hypr-hold-e2e.sh: only variant {v} has this\nfunction M.vmtest_{v}() M.exec("SUPER + CTRL + ALT + F12", "true vmtest-{v}") end\n\n' + k[i:]
open(keys, "w").write(k)
import re
b = open(binds).read()
# the code's line, not the header comment's example of it
b, n = re.subn(r'^(local K = require\("bromigos\.keys"\)\n)', lambda m: m.group(1) + f"K.vmtest_{v}()   -- test/vm/hypr-hold-e2e.sh\n", b, count=1, flags=re.M)
assert n == 1
open(binds, "w").write(b)
EOF
  head -c $((96 * 1024 * 1024)) /dev/urandom >"$hypr/bulk.bin"
  cat >"$d/PKGBUILD" <<EOF
pkgname=bromigos-desktop
pkgver=${base//-/_}.vm$v
pkgrel=1
pkgdesc='bromigOS desktop (test/vm/hypr-hold-e2e.sh variant $v)'
arch=('any')
license=('MIT OR Apache-2.0')
options=('!debug' '!strip')
package() { cp -a "\$startdir/tree/." "\$pkgdir/"; }
EOF
  (cd "$d" && PKGDEST="$d" makepkg --nodeps --noconfirm --force >"$d/makepkg.log" 2>&1) || { cat "$d/makepkg.log" >&2; return 1; }
  ls "$d"/bromigos-desktop-*.pkg.tar.zst
}
echo "== the variants"
if ! A=$(variant a) || ! B=$(variant b); then echo "hypr-hold-e2e: couldn't build the variants" >&2; exit 2; fi
vm_put "$A" "$B" "$pkg"
A=$(basename "$A") B=$(basename "$B") ORIG=$(basename "$pkg")
echo "   $A, $B"

# ---- the monitor: Hyprland's configreloaded events, its binds and auto-reload, every 50 ms
vm 'cat > hold-monitor.py' <<'EOF'
import json, os, socket, subprocess, sys, threading, time
env = dict(os.environ)
for line in subprocess.run(["bromigos", "session"], capture_output=True, text=True).stdout.splitlines():
    k, _, v = line.partition("=")
    env[k] = v
sock = os.path.join(env["XDG_RUNTIME_DIR"], "hypr", env["HYPRLAND_INSTANCE_SIGNATURE"], ".socket2.sock")
t0, stop, events, polls = time.time(), threading.Event(), [], []
def listen():
    s = socket.socket(socket.AF_UNIX); s.connect(sock); s.settimeout(0.2)
    while not stop.is_set():
        try:
            b = s.recv(65536)
        except socket.timeout:
            continue
        for l in b.decode(errors="replace").splitlines():
            if l.startswith("configreloaded"):
                events.append(round(time.time() - t0, 3))
def ctl(*a):
    return subprocess.run(["hyprctl", *a], capture_output=True, text=True, env=env, timeout=5).stdout
threading.Thread(target=listen, daemon=True).start()
time.sleep(0.3)
open(sys.argv[1] + ".ready", "w").close()
while not os.path.exists(sys.argv[1] + ".stop"):
    try:
        binds = len(json.loads(ctl("binds", "-j") or "[]"))
        off = json.loads(ctl("getoption", "misc:disable_autoreload", "-j") or "{}").get("bool")
    except (ValueError, subprocess.SubprocessError):
        binds, off = None, None
    polls.append((round(time.time() - t0, 3), binds, off))
    time.sleep(0.05)
time.sleep(1.5)                                     # a reload right after the transaction
stop.set()
json.dump({"events": events, "polls": polls}, open(sys.argv[1], "w"))
EOF

# pacman -U PKG under the monitor; MON: the monitor's JSON, PAC: pacman's output
transaction() {  # NAME PKG
  vm "rm -f /tmp/mon-$1*; (python3 hold-monitor.py /tmp/mon-$1 &) ; for _ in \$(seq 100); do [ -f /tmp/mon-$1.ready ] && break; sleep 0.1; done
      sudo pacman -U --noconfirm $2 > /tmp/pac-$1 2>&1; echo \"pacman exit \$?\" >> /tmp/pac-$1
      touch /tmp/mon-$1.stop; for _ in \$(seq 100); do [ -s /tmp/mon-$1 ] && break; sleep 0.1; done"
}
mon() {  # NAME EXPR: a Python expression over d (the monitor's JSON) and b0 (binds before)
  vm "python3 -c 'import json,sys; d=json.load(open(\"/tmp/mon-$1\")); b0=$B0; ok=($2); print(\"events\", d[\"events\"], \"binds seen\", sorted({p[1] for p in d[\"polls\"]}), \"auto-reload off seen\", sorted({str(p[2]) for p in d[\"polls\"]})); sys.exit(0 if ok else 1)'"
}
pac_says() { vm "cat /tmp/pac-$1; grep -q \"$2\" /tmp/pac-$1"; }
live() { vm "bromigos session exec hyprctl $*"; }
binds() { live binds -j | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'; }
autoreload_on() { live getoption misc:disable_autoreload | grep -qx 'bool: false'; }
no_errors() { [[ $(live configerrors -j | tr -d '[:space:]') == '[""]' ]]; }
bind_live() { live binds | grep -q "true vmtest-$1"; }
only_b() { bind_live b && ! bind_live a; }
originals() { ! live binds | grep -q vmtest && no_errors; }
released() { vm '! sudo sh -c "ls /run/bromigos/hypr-hold/*.json" 2>/dev/null' && autoreload_on; }
still_b() { [[ $(binds) == "$B0" ]] && bind_live b; }

echo "== before"
for _ in $(seq 60); do vm 'bromigos session >/dev/null' && break; sleep 5; done
check "the signed-in desktop runs" vm 'bromigos session && pgrep -x Hyprland'
check "the hooks are installed (bromigos-core)" vm 'test -f /usr/share/libalpm/hooks/bromigos-hypr-hold.hook -a -f /usr/share/libalpm/hooks/bromigos-hypr-release.hook'
check "auto-reload is on" autoreload_on

echo "== with the hooks: A, then B"
transaction a "$A"
check "A installed, the hooks held and released" pac_says a "config ok, reloaded once; auto-reload back on"
B0=$(binds)
check "A's bind is live ($B0 binds)" bind_live a
transaction b "$B"
check "pacman -U B: the hold" pac_says b "auto-reload held off while the files change"
check "pacman -U B: one verified reload, auto-reload back on" pac_says b "config ok, reloaded once; auto-reload back on"
check "no reload while the files changed, exactly one after" mon b 'len(d["events"]) == 1'
check "the binds never dropped (no emergency mode)" mon b 'min(p[1] for p in d["polls"] if p[1] is not None) >= b0'
check "auto-reload was off during, on at the end" mon b 'any(p[2] is True for p in d["polls"]) and d["polls"][-1][2] is False'
check "B's bind is live, A's gone" only_b
check "no config errors" no_errors
check "nothing left held, no watcher left" vm '! sudo sh -c "ls /run/bromigos/hypr-hold/*.json" 2>/dev/null && ! pgrep -f "^/usr/bin/bromigos session release --after"'

echo "== a transaction killed after the hold, mid-way through the files"
# killed while pacman writes A's bulk.bin (its inode changes): A's binds.lua is in, B's
# keys.lua still: the half-written set
vm 'f=/usr/share/bromigos/default/hypr/bromigos/bulk.bin; ino=$(stat -c %i $f)
    (sudo pacman -U --noconfirm '"$A"' > /tmp/pac-kill 2>&1 &)
    for _ in $(seq 1000); do [ "$(stat -c %i $f 2>/dev/null)" != "$ino" ] && break; sleep 0.01; done
    sudo pkill -KILL -x pacman; sleep 3'
check "the transaction was killed mid-way (no post-transaction hooks)" vm 'grep -q "held off" /tmp/pac-kill && ! grep -q "post-transaction" /tmp/pac-kill'
check "the watcher released it: nothing held, auto-reload back on" released
check "the watcher said so in the journal: the half-written set isn't reloaded" vm 'sudo journalctl -t bromigos-hypr-hold --since "-2min" --no-pager | grep "without its release hook" | grep -q "doesn.t verify"'
check "Hyprland still runs B's config: all its binds, B's live (no emergency)" still_b
# pacman's own state after a SIGKILL mid-upgrade: its lock, and a half-written local entry
vm 'sudo rm -f /var/lib/pacman/db.lck
    for e in /var/lib/pacman/local/bromigos-desktop-*/; do [ -f "$e/desc" ] || sudo rm -rf "$e"; done'

echo "== the original package back"
# its files are on disk, owned by no entry now: overwritten; B's bulk.bin isn't the original's
transaction orig "--overwrite '*' $ORIG"
vm 'sudo rm -f /usr/share/bromigos/default/hypr/bromigos/bulk.bin'
live reload >/dev/null
check "pacman -U the original: one verified reload" pac_says orig "config ok, reloaded once; auto-reload back on"
check "the original's binds, no errors" originals
check "pacman -Qk clean" vm 'pacman -Qk bromigos-desktop | grep -q " 0 missing files"'
echo "== without the hooks (the control, last: it can wedge Hyprland)"
# A over the original, the hooks moved aside: Hyprland reloads the half-written set
vm 'sudo mkdir -p /root/hooks-aside && sudo mv /usr/share/libalpm/hooks/bromigos-hypr-*.hook /root/hooks-aside/'
transaction ctl "$A"
vm 'sudo sh -c "mv /root/hooks-aside/bromigos-hypr-*.hook /usr/share/libalpm/hooks/"'
check "control: Hyprland reloaded while the files changed" mon ctl 'len(d["events"]) >= 1'
if mon ctl 'any(p[1] is None for p in d["polls"])' >"$out" 2>&1; then
  echo "     control: Hyprland stopped answering mid-transaction ($(tail -1 "$out")); the VM needs a reboot and a login"
elif mon ctl 'min(p[1] for p in d["polls"]) < b0' >"$out" 2>&1; then
  echo "     control: the emergency mode, seen: its binds dropped mid-transaction ($(tail -1 "$out"))"
else
  echo "     control: no emergency caught this run ($(tail -1 "$out"))"
fi
vm "sudo pacman -U --noconfirm $ORIG >/dev/null 2>&1; sudo rm -f /usr/share/bromigos/default/hypr/bromigos/bulk.bin"
echo "$fails failed"
exit $fails
