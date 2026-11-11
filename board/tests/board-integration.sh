#!/usr/bin/env bash
# The Lab board on a real machine, under its real systemd and as real root: CI's throwaway runner
# (.github/workflows/board-tests.yml, "Board on a Server"). The unit tests run in a stand-in root
# as one user; this is where the line between root and the board's user is tried for real: who
# owns which folder once tmpfiles made them, what the board's user can't do in root's, that root
# steps down before it works in the board's, and that the units start and work inside their
# sandboxes.
#
# It installs the board's files where the package puts them (packaging/bromigos-board/PKGBUILD),
# with a stand-in /usr/bin/bromigos that prints the tests' fixtures.
#
# Never run this on a computer you use: it adds a user, installs units and writes under /usr,
# /etc, /run and /var/lib.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
b="$repo/board"
[[ $(id -u) == 0 ]] || { echo "run as root, on a throwaway machine" >&2; exit 2; }
[[ ${CI:-} == true ]] || { echo "this changes the machine it runs on: CI only" >&2; exit 2; }

fail() { echo "FAILED: $*" >&2; exit 1; }
section() { echo "::endgroup::"; echo "::group::$*"; }
owner() { stat -c '%U:%G %a' "$1"; }
board=bromigos-board
as_board() { runuser -u "$board" -- "$@"; }
host=$(hostname -s | tr '[:upper:]' '[:lower:]')
sock=/run/bromigos-board.sock
lan=192.168.1.20
# a request as Caddy would pass it on: over the socket, with the address it saw
api() {     # api METHOD PATH [curl options…]: prints the status, the body goes to /tmp/body
    local method=$1 path=$2; shift 2
    curl -sS -o /tmp/body -D /tmp/headers -w '%{http_code}' --unix-socket "$sock" -X "$method" -H "Host: ${as_host:-$host.local}" \
        -H "X-Forwarded-For: ${from:-$lan}" "$@" "http://board$path"
}
cookie() {  # the session cookie of the last answer, as a Cookie header (curl keeps no Secure cookie sent over a socket)
    sed -n 's/^[Ss]et-[Cc]ookie: \(__Host-bromigos-board=[^;]*\).*/Cookie: \1/p' /tmp/headers | tr -d '\r' | head -1
}
page=(-H "X-Bromigos-Board: 1" -H "Origin: https://$host.local" -H "Content-Type: application/json")
wait_for() {    # wait_for SECONDS COMMAND…
    local n=$1; shift
    for _ in $(seq $((n * 5))); do "$@" >/dev/null 2>&1 && return 0; sleep 0.2; done
    return 1
}
echo "::group::install"

# ---------------------------------------------------------------- what the package installs
install -Dm0644 -t /usr/lib/bromigos/lib/bromigos_board/ "$b"/lib/bromigos_board/*.py
install -Dm0755 "$b/bin/bromigos-board" /usr/lib/bromigos/board/bromigos-board
install -Dm0644 -t /usr/lib/systemd/system/ "$b"/systemd/*
install -Dm0644 "$b/bromigos-board.sysusers" /usr/lib/sysusers.d/bromigos-board.conf
install -Dm0644 "$b/bromigos-board.tmpfiles" /usr/lib/tmpfiles.d/bromigos-board.conf
install -Dm0644 "$b/caddy/site.caddy" /usr/share/bromigos-board/caddy/site.caddy
install -Dm0644 -t /usr/share/bromigos-board/placeholder/ "$b"/placeholder/*
# bromigos-core's part the board uses: the activity records
install -Dm0644 -t /usr/lib/bromigos/lib/ "$repo"/lib/bromigos_activity.py "$repo"/lib/bromigos_alerts*.py
install -Dm0755 "$repo/bin/bromigos-activity" /usr/lib/bromigos/bin/bromigos-activity
# the commands the reader runs: a stand-in that prints the tests' fixtures and notes what it was asked
install -Dm0644 -t /usr/share/bromigos-board-test/fixtures/ "$b"/tests/fixtures/*.json
install -Dm0755 "$b/tests/fixtures/bromigos" /usr/share/bromigos-board-test/fixtures/bromigos
install -d -m0755 /var/lib/bromigos-board-test
cat > /usr/bin/bromigos <<'EOF'
#!/bin/sh
echo "$(id -u) $*" >> /var/lib/bromigos-board-test/calls.log
BOARD_FIXTURES=/usr/share/bromigos-board-test/fixtures BOARD_MISSING="" exec /bin/sh /usr/share/bromigos-board-test/fixtures/bromigos "$@"
EOF
chmod 0755 /usr/bin/bromigos
getent group caddy >/dev/null || groupadd -r caddy            # the caddy package's: the socket's group
id caddy >/dev/null 2>&1 || useradd -r -g caddy -s /usr/sbin/nologin caddy
systemd-sysusers /usr/lib/sysusers.d/bromigos-board.conf
systemd-tmpfiles --create /usr/lib/tmpfiles.d/bromigos-board.conf
systemctl daemon-reload
systemd-analyze verify --man=no /usr/lib/systemd/system/bromigos-board*.service /usr/lib/systemd/system/bromigos-board*.path \
    /usr/lib/systemd/system/bromigos-board.socket 2>&1 | tee /tmp/verify.txt
! grep -q bromigos-board /tmp/verify.txt || fail "systemd finds fault with a unit"
systemctl enable --now bromigos-board.socket bromigos-board-snapshot.path
# as after a while of running: the two files were made long ago (a mark this fresh means "a
# browser is connected", and the reader would go on reading for it)
touch -d '10 minutes ago' /run/bromigos-board/wanted /run/bromigos-board/door

section "the folders: root's is root's, the board's is the board's"
[[ $(owner /run/bromigos-board) == "root:$board 750" ]] || fail "/run/bromigos-board is $(owner /run/bromigos-board)"
[[ $(owner /run/bromigos-board/wanted) == "root:$board 660" ]] || fail "wanted is $(owner /run/bromigos-board/wanted)"
[[ $(owner /run/bromigos-board/door) == "root:$board 660" ]] || fail "door is $(owner /run/bromigos-board/door)"
for d in /var/lib/bromigos-board /var/lib/bromigos-board/sessions /var/lib/bromigos-board/codes; do
    [[ $(owner "$d") == "$board:$board 700" ]] || fail "$d is $(owner "$d")"
done
# the board's user can read root's folder, and can put nothing in it: no file, no link, no FIFO
as_board ls /run/bromigos-board >/dev/null || fail "the board's user can't read /run/bromigos-board"
! as_board touch /run/bromigos-board/x 2>/dev/null || fail "the board's user made a file in root's folder"
! as_board ln -s /etc/shadow "/run/bromigos-board/board.json.$$.tmp" 2>/dev/null || fail "the board's user planted a link in root's folder"
! as_board mkfifo /run/bromigos-board/fifo 2>/dev/null || fail "the board's user made a FIFO in root's folder"
! as_board rm -f /run/bromigos-board/wanted 2>/dev/null || true
[[ -e /run/bromigos-board/wanted ]] || fail "the board's user removed wanted"
# ... and it can mark the two files it may mark (the door's: one reading)
as_board touch -c /run/bromigos-board/door || fail "the board's user can't mark door"
as_board test -w /run/bromigos-board/wanted || fail "the board's user can't mark wanted"
wait_for 30 test -s /run/bromigos-board/board.json || { journalctl -u bromigos-board-snapshot.service --no-pager -n 40; fail "marking door started no reading"; }
wait_for 30 bash -c '! systemctl is-active -q bromigos-board-snapshot.service' || fail "one reading was asked for, and the reader went on"
rm -f /run/bromigos-board/board.json

section "the API: on its socket, as its own user, inside its sandbox"
[[ $(api GET /api/door) == 200 ]] || { cat /tmp/body; journalctl -u bromigos-board.service --no-pager -n 40; fail "the door doesn't answer"; }
python3 - "$host" <<'PY' || fail "the door isn't the door: $(cat /tmp/body)"
import json, sys
d = json.load(open("/tmp/body"))
assert d["server"] == {"name": sys.argv[1]} and d["signin"]["code"] is True, d
PY
pid=$(systemctl show -P MainPID bromigos-board.service)
[[ $(stat -c %U "/proc/$pid") == "$board" ]] || fail "the API runs as $(stat -c %U "/proc/$pid")"
grep -q '^NoNewPrivs:[[:space:]]*1' "/proc/$pid/status" || fail "the API may gain privileges"
grep -q '^CapEff:[[:space:]]*0000000000000000' "/proc/$pid/status" || fail "the API has capabilities"
grep -q '^Seccomp:[[:space:]]*2' "/proc/$pid/status" || fail "the API has no system call filter"
# inside its own view of the files: its folder and the two files, and nothing else, can be written
in_api() { nsenter -t "$pid" -m -- runuser -u "$board" -- "$@"; }
in_api touch /var/lib/bromigos-board/sessions/.probe && in_api rm /var/lib/bromigos-board/sessions/.probe || fail "the API can't write its own folder"
in_api test -w /run/bromigos-board/wanted || fail "the API can't mark wanted"
view() {    # view PID: how that unit's sandbox sees the folders this test is about (for the log, when a check fails)
    grep -E ' (/|/run|/run/bromigos-board[^ ]*|/var/lib|/var/lib/bromigos[^ ]*|/etc|/usr) [a-z]' "/proc/$1/mountinfo" | cut -d' ' -f4-10
}
! nsenter -t "$pid" -m -- touch /run/bromigos-board/x 2>/dev/null \
    || { view "$pid"; systemctl show bromigos-board.service -p ProtectSystem -p ReadWritePaths; fail "inside the API's sandbox, even root can write /run/bromigos-board"; }
for where in /etc /usr /var/lib /run /home; do
    ! nsenter -t "$pid" -m -- touch "$where/x" 2>/dev/null || { view "$pid"; fail "inside the API's sandbox, $where can be written"; }
done
# and as itself, the board's user, it can't put anything in root's folder (that is the folder's own doing: root's, 0750)
! in_api touch /run/bromigos-board/x 2>/dev/null || fail "the API can write root's folder"
# who may open the socket: Caddy's group, and nobody else
[[ $(owner "$sock") == "$board:caddy 660" ]] || fail "the socket is $(owner "$sock")"
runuser -u caddy -- curl -sS -o /dev/null --unix-socket "$sock" -H "Host: $host.local" -H "X-Forwarded-For: $lan" http://board/api/door \
    || fail "Caddy's user can't open the socket"
! runuser -u nobody -- curl -sS -o /dev/null --unix-socket "$sock" http://board/api/door 2>/dev/null || fail "anyone can open the socket"

section "the door asks root's reader for one reading"
# (the door was asked just above, with no reading there: the API marked `door` for it)
wait_for 30 test -s /run/bromigos-board/board.json || { journalctl -u bromigos-board-snapshot.service --no-pager -n 40; fail "the reader wrote no board.json"; }
[[ $(owner /run/bromigos-board/board.json) == "root:$board 640" ]] || fail "board.json is $(owner /run/bromigos-board/board.json)"
[[ -z $(find /run/bromigos-board -name '*.tmp') ]] || fail "a temporary file was left: $(ls -a /run/bromigos-board)"
grep -q '^0 server status --json$' /var/lib/bromigos-board-test/calls.log || fail "the reader's commands didn't run as root: $(cat /var/lib/bromigos-board-test/calls.log)"
wait_for 20 bash -c '! systemctl is-active -q bromigos-board-snapshot.service' || fail "signed out, the reader went on reading"
first=$(stat -c %Y /run/bromigos-board/board.json)
for _ in 1 2 3 4 5; do api GET /api/door >/dev/null; done
sleep 3
[[ $(stat -c %Y /run/bromigos-board/board.json) == "$first" ]] || fail "the door had the reader read again within two minutes"
[[ $(api GET /api/door) == 200 ]] && python3 -c 'import json; d = json.load(open("/tmp/body")); assert [t["id"] for t in d["tiles"]] == ["photos", "passwords", "uptime"], d' \
    || fail "the door's tiles: $(cat /tmp/body)"
[[ $(api GET /api/board) == 401 ]] || fail "the board answered without a session"

section "sudo bromigos server board code: root steps down, then signs a browser in"
code=$(/usr/lib/bromigos/board/bromigos-board code --json | python3 -c 'import json, sys; print(json.load(sys.stdin)["code"])')
[[ $code =~ ^[A-Z2-9]{4}-[A-Z2-9]{4}$ ]] || fail "no code: $code"
record=$(find /var/lib/bromigos-board/codes -name '*.json')
[[ $(owner "$record") == "$board:$board 600" ]] || fail "the code's record is $(owner "$record"): root wrote it as root"
[[ $(api POST /api/session "${page[@]}" -d '{"code": "AAAA-AAAA"}') == 401 ]] || fail "a wrong code: $(cat /tmp/body)"
[[ $(api POST /api/session -H "Content-Type: application/json" -d "{\"code\": \"$code\"}") == 403 ]] || fail "sign-in without the page's header"
[[ $(as_host=evil.example.org api POST /api/session -H "X-Bromigos-Board: 1" -H "Origin: https://evil.example.org" \
        -H "Content-Type: application/json" -d "{\"code\": \"$code\"}") == 403 ]] || fail "sign-in under another name: $(cat /tmp/body)"
[[ $(api POST /api/session "${page[@]}" -d "{\"code\": \"$code\"}") == 200 ]] || fail "the code didn't sign in: $(cat /tmp/body)"
session_cookie=$(cookie)
[[ -n $session_cookie ]] || fail "no session cookie: $(cat /tmp/headers)"
grep -i '^set-cookie: __Host-bromigos-board=' /tmp/headers | grep -qi 'HttpOnly.*Secure\|Secure.*HttpOnly' || fail "the cookie isn't HttpOnly and Secure"
[[ $(api POST /api/session "${page[@]}" -d "{\"code\": \"$code\"}") == 401 ]] || fail "the code worked twice"
session=$(find /var/lib/bromigos-board/sessions -name '*.json')
[[ $(owner "$session") == "$board:$board 600" ]] || fail "the session's record is $(owner "$session")"
/usr/lib/bromigos/board/bromigos-board sessions --json | python3 -c 'import json, sys; d = json.load(sys.stdin); assert len(d["sessions"]) == 1, d' \
    || fail "sessions doesn't list the browser"
[[ -z $(find /var/lib/bromigos-board ! -user "$board") ]] || fail "root left files of its own in the board's folder: $(find /var/lib/bromigos-board ! -user "$board")"

section "a link planted where the board's folder should be: refused, and nothing is deleted"
install -d -m0755 /var/lib/bromigos-board-test/victim
touch /var/lib/bromigos-board-test/victim/{passwd,shadow,fstab}
as_board mv /var/lib/bromigos-board/codes /var/lib/bromigos-board/codes.real
as_board ln -s /var/lib/bromigos-board-test/victim /var/lib/bromigos-board/codes
rc=0; /usr/lib/bromigos/board/bromigos-board code >/tmp/out 2>&1 || rc=$?
[[ $rc == 3 ]] || fail "code, with a link planted, ended $rc: $(cat /tmp/out)"
rc=0; /usr/lib/bromigos/board/bromigos-board sessions >/tmp/out 2>&1 || rc=$?
[[ $rc == 3 ]] || fail "sessions, with a link planted, ended $rc: $(cat /tmp/out)"
[[ $(ls /var/lib/bromigos-board-test/victim | tr '\n' ' ') == "fstab passwd shadow " ]] || fail "root deleted or made files through the link: $(ls /var/lib/bromigos-board-test/victim)"
as_board rm /var/lib/bromigos-board/codes
as_board mv /var/lib/bromigos-board/codes.real /var/lib/bromigos-board/codes

section "signed in: the board, and readings every 15 seconds while it's open"
[[ $(api GET /api/board -H "$session_cookie") == 200 ]] || fail "the board: $(cat /tmp/body)"
python3 - "$host" <<'PY' || fail "the board isn't the board: $(head -c 600 /tmp/body)"
import json, sys
d = json.load(open("/tmp/body"))
assert d["server"]["name"] == sys.argv[1] and d["status"]["state"] == "needs-you" and d["storage"]["drives"], d["status"]
assert all(s["ok"] for s in d["sources"].values()), d["sources"]
assert "hunter2" not in json.dumps(d) and "should-never-reach-the-board" not in json.dumps(d)
PY
wait_for 20 systemctl is-active -q bromigos-board-snapshot.service || fail "signed in, the board didn't start the reader"
rpid=$(systemctl show -P MainPID bromigos-board-snapshot.service)
grep -q '^NoNewPrivs:[[:space:]]*1' "/proc/$rpid/status" || fail "the reader may gain privileges"
! nsenter -t "$rpid" -m -- touch /etc/x 2>/dev/null || fail "inside the reader's sandbox, /etc can be written"
! nsenter -t "$rpid" -m -- touch /usr/x 2>/dev/null || fail "inside the reader's sandbox, /usr can be written"
before=$(stat -c %Y /run/bromigos-board/board.json)
api GET /api/board -H "$session_cookie" >/dev/null
wait_for 25 bash -c "[[ \$(stat -c %Y /run/bromigos-board/board.json) -gt $before ]]" || fail "the reader didn't read again while the board was open"

section "wrong codes: this address waits, nobody else does; a big body is refused"
for i in 1 2 3 4 5; do from=10.9.9.9 api POST /api/session "${page[@]}" -d '{"code": "BBBB-BBBB"}' >/dev/null; done
[[ $(from=10.9.9.9 api POST /api/session "${page[@]}" -d '{"code": "BBBB-BBBB"}') == 429 ]] || fail "six wrong codes from one address: $(cat /tmp/body)"
for i in $(seq 30); do from=10.8.$i.1 api POST /api/session "${page[@]}" -d '{"code": "CCCC-CCCC"}' >/dev/null & done; wait
code=$(/usr/lib/bromigos/board/bromigos-board code --json | python3 -c 'import json, sys; print(json.load(sys.stdin)["code"])')
t0=$(date +%s%N)
[[ $(api POST /api/session "${page[@]}" -d "{\"code\": \"$code\"}") == 200 ]] || fail "others' wrong codes refused a right one: $(cat /tmp/body)"
(( ($(date +%s%N) - t0) / 1000000 < 900 )) || fail "others' wrong codes held a right one up"
head -c 1048576 /dev/zero | tr '\0' ' ' > /tmp/big
[[ $(api POST /api/session "${page[@]}" --data-binary @/tmp/big) == 413 ]] || fail "a 1 MB body: $(cat /tmp/body)"
[[ $(api POST /api/session "${page[@]}" -H "Transfer-Encoding: chunked" --data-binary @/tmp/big) == 413 ]] || fail "a 1 MB body with no length: $(cat /tmp/body)"
[[ $(api GET /api/door) == 200 ]] || fail "the API didn't survive the big bodies"

section "who is local: private addresses; the lab network's only while this server is on it"
[[ $(from=203.0.113.5 api GET /api/door) == 403 ]] || fail "a public address got in"
[[ $(from=2001:db8::5 api GET /api/door) == 403 ]] || fail "a public IPv6 address got in"
if [[ ! -e /sys/class/net/tailscale0 ]]; then
    [[ $(from=100.64.0.7 api GET /api/local) == 403 ]] || fail "the lab network's range is local with no lab network here"
    if ip link add tailscale0 type dummy 2>/dev/null; then
        [[ $(from=100.64.0.7 api GET /api/local) == 204 ]] || fail "on the lab network, its range isn't local"
        ip link del tailscale0
        [[ $(from=100.64.0.7 api GET /api/local) == 403 ]] || fail "off the lab network again, its range stayed local"
    else
        echo "(no dummy interface here: the lab network half isn't tried)"
    fi
fi

section "the activity stream: signed in, the jobs' records come through"
python3 -I -c 'import sys; sys.path.insert(0, "/usr/lib/bromigos/lib"); import bromigos_activity' || fail "the activity library doesn't load as installed"
curl -sS -N --max-time 4 --unix-socket "$sock" -H "Host: $host.local" -H "X-Forwarded-For: $lan" -H "$session_cookie" http://board/api/activity > /tmp/stream 2>/dev/null || true
grep -q '^event: snapshot' /tmp/stream || fail "the activity stream: $(head -c 300 /tmp/stream)"

section "nobody looks any more: the reader stops; nothing failed"
wait_for 90 bash -c '! systemctl is-active -q bromigos-board-snapshot.service' || fail "the reader didn't stop after the board closed"
[[ -z $(systemctl list-units --failed --no-legend 'bromigos-board*') ]] || { systemctl list-units --failed 'bromigos-board*'; fail "a unit failed"; }
systemd-analyze security --no-pager bromigos-board.service | tail -1
echo "::endgroup::"
echo "the Lab board: all of it passed"
