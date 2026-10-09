#!/usr/bin/env bash
# vm-keeper.py's checks: a test VM's QEMU stops when whoever started it is gone. Runs a
# QEMU with no machine at all (-machine none: no guest, a few MB), never a window.
#
#   test/vm/keeper-test.sh        PASS/FAIL per check; exits 1 on a failure
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
keeper=$here/vm-keeper.py
base=${TMPDIR:-/tmp}; (( ${#base} < 60 )) || base=/tmp     # a socket's path has 108 bytes at most
dir=$(mktemp -d "$base/bromigos-keeper.XXXXXX")
trap 'pkill -f -- "-qmp unix:$dir/" 2>/dev/null; rm -rf "$dir"' EXIT
fails=0
pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; fails=$((fails + 1)); }

qemu_args() {   # qemu_args NAME: a QEMU with nothing in it, its QMP socket in DIR (one word each)
    qemu=(qemu-system-x86_64 -machine none -nodefaults -display none -m 16
       -qmp "unix:$dir/$1.sock,server,nowait" -pidfile "$dir/$1.pid" -daemonize)
}
gone_within() { # gone_within SECONDS PID
    for _ in $(seq $(($1 * 10))); do kill -0 "$2" 2>/dev/null || return 0; sleep 0.1; done
    return 1
}

# 1. an owner that dies: QEMU goes with it (the usage-limit kill of 2026-10-09)
sleep 600 & owner=$!
qemu_args a
if BROMIGOS_VM_OWNER=$owner "$keeper" --ready "$dir/a.sock" --log "$dir/a.log" -- "${qemu[@]}"; then
    q=$(cat "$dir/a.pid")
    kill -0 "$q" && pass "QEMU is up when the command returns (PID $q), detached"
    if [[ $(ps -o args= -p "$q") != *-daemonize* ]]; then pass "QEMU runs without -daemonize"; else fail "-daemonize left in"; fi
    kill -9 "$owner"; wait "$owner" 2>/dev/null
    if gone_within 5 "$q"; then pass "the owner killed: QEMU stopped"; else fail "QEMU outlived its owner"; fi
    grep -q "its owner (PID $owner) is gone" "$dir/a.log" && pass "the keeper logged why"
else
    fail "the keeper didn't start QEMU"; cat "$dir/a.log"
fi

# 2. the keeper killed outright (SIGKILL): the kernel stops QEMU (PR_SET_PDEATHSIG)
qemu_args b
BROMIGOS_VM_OWNER=none "$keeper" --ready "$dir/b.sock" --log "$dir/b.log" -- "${qemu[@]}"
q=$(cat "$dir/b.pid"); k=$(ps -o ppid= -p "$q" | tr -d ' ')
[[ $(ps -o args= -p "$k") == *vm-keeper.py* ]] && pass "QEMU's parent is the keeper"
kill -9 "$k"
if gone_within 5 "$q"; then pass "the keeper SIGKILLed: QEMU stopped"; else fail "QEMU outlived the keeper"; fi

# 3. no owner given: the nearest ancestor that isn't a passing shell or wrapper. Here a
# python process runs `bash -c 'timeout 60 bash -c "keeper …"'`, as a harness would be run
qemu_args c
python3 - "$keeper" "$dir" "${qemu[*]}" <<'EOF' &
import subprocess, sys, time
keeper, d, qemu = sys.argv[1:]
subprocess.run(["bash", "-c", f'timeout 60 bash -c "{keeper} --ready {d}/c.sock --log {d}/c.log -- {qemu}"'])
time.sleep(600)
EOF
py=$!
for _ in $(seq 100); do [[ -s $dir/c.pid ]] && break; sleep 0.1; done
q=$(cat "$dir/c.pid" 2>/dev/null)
if grep -q "owner PID $py (.*python3" "$dir/c.log"; then
    pass "the owner found: the python process, past bash, timeout and bash"
else
    fail "the owner: $(grep owner "$dir/c.log")"
fi
kill -0 "$q" 2>/dev/null && pass "QEMU outlives the commands that started it"
kill -9 "$py"; wait "$py" 2>/dev/null
if gone_within 5 "$q"; then pass "the owner killed: QEMU stopped"; else fail "QEMU outlived its owner"; fi

# 4. QEMU stopped by itself (down, a guest's poweroff): the keeper goes too
qemu_args d
BROMIGOS_VM_OWNER=none "$keeper" --ready "$dir/d.sock" --log "$dir/d.log" -- "${qemu[@]}"
q=$(cat "$dir/d.pid"); k=$(ps -o ppid= -p "$q" | tr -d ' ')
kill "$q"
if gone_within 5 "$k"; then pass "QEMU stopped: the keeper exited"; else fail "the keeper stayed"; fi

# 5. QEMU that can't start: the command fails and says why
if "$keeper" --ready "$dir/e.sock" --log "$dir/e.log" -- qemu-system-x86_64 -machine bogus 2>"$dir/e.err"; then
    fail "a QEMU that didn't start reported up"
else
    grep -q "before it was up" "$dir/e.err" && pass "a QEMU that can't start: exit 1, with its error"
fi

echo "$((fails)) failed"
exit $((fails > 0))
