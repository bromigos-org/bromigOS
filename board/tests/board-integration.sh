#!/usr/bin/env bash
# The Lab board on a real machine, under its real systemd and as real root: CI's throwaway runner
# (.github/workflows/board-tests.yml, "Board on a Server"). The unit tests run in a stand-in root
# as one user; this is where the line between root and the board's user is tried for real: who
# owns which folder once tmpfiles made them, what the board's user can't do in root's, that root
# steps down before it works in the board's, and that the units start and work inside their
# sandboxes. Then the actions: that the API can start nothing itself, that root's helper is
# started by the folder of requests, handles a burst of them each once and loses none, works
# inside its sandbox, leaves its answers in root's folder, and takes no code for a deletion that
# root didn't make.
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
# bromigos-lab's part the helper uses: the provisioning catalogue and its reader
install -Dm0644 -t /usr/lib/bromigos/lib/bromigos_homelab/ "$repo"/homelab/lib/bromigos_homelab/*.py
install -Dm0644 "$repo/homelab/share/provision-catalogue.toml" /usr/share/bromigos/lab/provision-catalogue.toml
# bromigos-core's part the board uses: the activity records
install -Dm0644 -t /usr/lib/bromigos/lib/ "$repo"/lib/bromigos_activity.py "$repo"/lib/bromigos_labjobs.py "$repo"/lib/bromigos_alerts*.py
install -Dm0755 "$repo/bin/bromigos-activity" /usr/lib/bromigos/bin/bromigos-activity
# the commands the reader runs: a stand-in that prints the tests' fixtures and notes what it was asked
install -Dm0644 -t /usr/share/bromigos-board-test/fixtures/ "$b"/tests/fixtures/*.json
install -Dm0755 "$b/tests/fixtures/bromigos" /usr/share/bromigos-board-test/fixtures/bromigos
install -d -m0755 /var/lib/bromigos-board-test
cat > /usr/bin/bromigos <<'EOF'
#!/bin/sh
echo "$(id -u) $*" >> /var/lib/bromigos-board-test/calls.log
case "$1 $2 $3" in
  "lab apps restart"|"lab apps add"|"lab apps remove") echo "::stage 100 Done"; exit 0 ;;      # what an action's job runs
esac
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
systemctl enable --now bromigos-board.socket bromigos-board-snapshot.path bromigos-board-act.path
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
# the actions' folders: requests are the board's, answers and root's note of each code are root's
[[ $(owner /run/bromigos-board/requests) == "$board:$board 750" ]] || fail "requests is $(owner /run/bromigos-board/requests)"
[[ $(owner /run/bromigos-board/results) == "root:$board 750" ]] || fail "results is $(owner /run/bromigos-board/results)"
[[ $(owner /var/lib/bromigos-board-root) == "root:root 700" && $(owner /var/lib/bromigos-board-root/codes) == "root:root 700" ]] \
    || fail "root's own folder is $(owner /var/lib/bromigos-board-root)"
! as_board touch /run/bromigos-board/results/x 2>/dev/null || fail "the board's user made a file among root's answers"
! as_board ls /var/lib/bromigos-board-root 2>/dev/null || fail "the board's user can read root's own folder"
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
in_api touch /run/bromigos-board/requests/.probe.tmp && in_api rm /run/bromigos-board/requests/.probe.tmp || fail "the API can't write its requests folder"
! nsenter -t "$pid" -m -- touch /run/bromigos-board/results/x 2>/dev/null || fail "inside the API's sandbox, root's answers folder can be written"
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

section "who is local: private addresses; the lab network's range only when it came in on the lab network's interface"
[[ $(from=203.0.113.5 api GET /api/door) == 403 ]] || fail "a public address got in"
[[ $(from=2001:db8::5 api GET /api/door) == 403 ]] || fail "a public IPv6 address got in"
if [[ ! -e /sys/class/net/tailscale0 ]]; then
    [[ $(from=100.64.0.7 api GET /api/local -H "X-Bromigos-Local: 100.100.1.1") == 403 ]] || fail "the lab network's range is local with no lab network here"
    if ip link add tailscale0 type dummy 2>/dev/null && ip link add bromigos-uplink type dummy 2>/dev/null; then
        # the lab interface's address, and an uplink inside the provider's carrier-grade NAT
        ip addr add 100.100.1.1/32 dev tailscale0 && ip addr add 100.72.9.9/32 dev bromigos-uplink
        ip link set tailscale0 up; ip link set bromigos-uplink up
        # (the API asks the kernel over rtnetlink, from inside its sandbox)
        [[ $(from=100.64.0.7 api GET /api/local -H "X-Bromigos-Local: 100.100.1.1") == 204 ]] || { journalctl -u bromigos-board.service --no-pager -n 20; fail "came in on the lab interface: its range isn't local"; }
        [[ $(from=100.64.0.7 api GET /api/local -H "X-Bromigos-Local: 100.72.9.9") == 403 ]] || fail "a neighbour in the provider's range, on the uplink, got in"
        [[ $(from=100.64.0.7 api GET /api/local) == 403 ]] || fail "the lab range got in with nobody saying where it came in"
        ip link del tailscale0; ip link del bromigos-uplink
        [[ $(from=100.64.0.7 api GET /api/local -H "X-Bromigos-Local: 100.100.1.1") == 403 ]] || fail "off the lab network again, its range stayed local"
    else
        ip link del tailscale0 2>/dev/null || true
        echo "(no dummy interface here: the lab network half isn't tried)"
    fi
fi

# ================================================================ actions
ask() {     # ask JSON: POST /api/actions as the signed-in browser, from an address with no wrong codes yet
    from=192.168.1.30 api POST /api/actions "${page[@]}" -H "$session_cookie" -d "$1"
}
calls() { grep -c "^0 lab apps $1\$" /var/lib/bromigos-board-test/calls.log || true; }
as_board_ask() {    # as_board_ask N: N requests written straight into the folder as the API writes them, at once
    as_board python3 -I -c 'import sys
sys.path.insert(0, "/usr/lib/bromigos/lib")
from bromigos_board import actions
for _ in range(int(sys.argv[1])):
    print(actions.ask("restart", "photos", {"id": "s", "browser": "the test"}))' "$1"
}
answers() { find /run/bromigos-board/results -name '*.json' | wc -l; }
field() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2" 2>/dev/null; }

section "actions: the API can start nothing; root's helper is started by the folder"
! as_board systemctl start bromigos-board-act.service 2>/dev/null || fail "the board's user may start the helper's unit"
! as_board systemd-run --unit=bromigos-board-act@0123456789abcdef.service /bin/true 2>/dev/null || fail "the board's user may start a unit of its choice"
[[ ! -e /usr/share/polkit-1/rules.d/50-bromigos-board.rules ]] || fail "a polkit rule is installed"
[[ $(ask '{"verb": "restart", "app": "photos"}') == 202 ]] || { journalctl -u bromigos-board-act.service --no-pager -n 40; fail "restart: $(cat /tmp/body)"; }
job=$(python3 -c 'import json; d = json.load(open("/tmp/body")); assert d["ok"] and d["words"] == "Restarting Photos.", d; print(d["job"])') \
    || fail "the answer: $(cat /tmp/body)"
[[ $job =~ ^[0-9]{8}-[0-9]{4}-app\.restart-photos-[0-9a-f]{4}$ ]] || fail "no job came back: $(cat /tmp/body)"
wait_for 60 bash -c "[[ \$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[\"state\"])' /var/lib/bromigos/activity/jobs/$job.json) == succeeded ]]" \
    || { cat "/var/lib/bromigos/activity/jobs/$job.json"; fail "the job didn't end well"; }
[[ $(calls 'restart photos') == 1 ]] || fail "the job's command ran $(calls 'restart photos') times: $(cat /var/lib/bromigos-board-test/calls.log)"
python3 - "$job" <<'PY' || fail "the job's record: $(cat "/var/lib/bromigos/activity/jobs/$job.json")"
import json, sys
r = json.load(open(f"/var/lib/bromigos/activity/jobs/{sys.argv[1]}.json"))
assert r["kind"] == "app.restart" and r["requested_by"]["via"] == "board" and r["subject"]["id"] == "photos", r
assert r["command"][-5:] == ["/usr/bin/bromigos", "lab", "apps", "restart", "photos"], r["command"]
PY
[[ -z $(ls /run/bromigos-board/requests) ]] || fail "the request wasn't taken out: $(ls -a /run/bromigos-board/requests)"
for f in /run/bromigos-board/results/*.json; do
    [[ $(owner "$f") == "root:$board 640" ]] || fail "an answer is $(owner "$f")"
done

section "actions: the helper inside its sandbox"
as_board_ask 1 >/dev/null
wait_for 20 bash -c '[[ $(systemctl show -P MainPID bromigos-board-act.service) != 0 ]]' || fail "the helper didn't start for a request"
hpid=$(systemctl show -P MainPID bromigos-board-act.service)
[[ $(stat -c %U "/proc/$hpid") == root ]] || fail "the helper runs as $(stat -c %U "/proc/$hpid")"
grep -q '^NoNewPrivs:[[:space:]]*1' "/proc/$hpid/status" || fail "the helper may gain privileges"
for where in /etc /usr /root /var/lib /run /run/bromigos-board /var/lib/bromigos /home; do
    ! nsenter -t "$hpid" -m -- touch "$where/x" 2>/dev/null || fail "inside the helper's sandbox, $where can be written"
done
for where in /run/bromigos-board/requests /run/bromigos-board/results /var/lib/bromigos-board-root/codes /var/lib/bromigos/activity/jobs; do
    nsenter -t "$hpid" -m -- touch "$where/.probe.tmp" && nsenter -t "$hpid" -m -- rm "$where/.probe.tmp" || fail "the helper can't write $where"
done
wait_for 40 bash -c '[[ $(systemctl show -P ActiveState bromigos-board-act.service) == inactive ]]' || fail "the helper didn't end"

section "actions: a burst of requests is each handled once, and none is lost"
before=$(calls 'restart photos')
as_board_ask 40 > /tmp/asked
for rid in $(cat /tmp/asked); do
    wait_for 120 test -s "/run/bromigos-board/results/$rid.json" || { journalctl -u bromigos-board-act.service --no-pager -n 40; fail "request $rid got no answer"; }
    [[ $(field "/run/bromigos-board/results/$rid.json" ok) == True ]] || fail "request $rid: $(cat "/run/bromigos-board/results/$rid.json")"
done
[[ -z $(ls /run/bromigos-board/requests) ]] || fail "requests were left: $(ls -a /run/bromigos-board/requests)"
jobs=$(for rid in $(cat /tmp/asked); do field "/run/bromigos-board/results/$rid.json" job; done | sort -u | wc -l)
[[ $jobs == 40 ]] || fail "40 requests started $jobs jobs"
wait_for 240 bash -c "[[ \$(grep -c '^0 lab apps restart photos\$' /var/lib/bromigos-board-test/calls.log) -ge $((before + 40)) ]]" \
    || fail "40 requests ran the command $(( $(calls 'restart photos') - before )) times"
sleep 3
[[ $(calls 'restart photos') == $((before + 40)) ]] || fail "40 requests ran the command $(( $(calls 'restart photos') - before )) times: more than once each"
# ... and requests that arrive as the helper is ending (it waits three seconds for more): each at its own moment around that
before=$(calls 'restart photos'); : > /tmp/asked
for gap in 2.6 2.8 2.9 3.0 3.1 3.2 3.4 0.1; do as_board_ask 1 >> /tmp/asked; sleep "$gap"; done
for rid in $(cat /tmp/asked); do
    wait_for 40 test -s "/run/bromigos-board/results/$rid.json" || fail "request $rid, sent as the helper ended, got no answer: $(ls -a /run/bromigos-board/requests)"
done
[[ -z $(ls /run/bromigos-board/requests) ]] || fail "a request that arrived as the helper ended was left: $(ls -a /run/bromigos-board/requests)"
wait_for 120 bash -c "[[ \$(grep -c '^0 lab apps restart photos\$' /var/lib/bromigos-board-test/calls.log) -ge $((before + 8)) ]]" || fail "those eight ran $(( $(calls 'restart photos') - before )) times"
[[ -z $(systemctl list-units --failed --no-legend 'bromigos-board*') ]] || { systemctl list-units --failed 'bromigos-board*'; fail "a unit failed under the burst"; }

section "actions: a refusal is an answer, and fails nothing"
[[ $(ask '{"verb": "restart", "app": "not-an-app"}') == 403 ]] || fail "an app that isn't in the catalogue: $(cat /tmp/body)"
grep -q '"unknown-app"' /tmp/body || fail "its refusal: $(cat /tmp/body)"
! grep -q 'not-an-app' /tmp/body || fail "the answer quotes the request: $(cat /tmp/body)"
[[ $(ask '{"verb": "logs", "app": "photos"}') == 400 ]] || fail "a verb off the list: $(cat /tmp/body)"
install -d /etc/bromigos
printf '[board]\nactions = ["restart"]\n' > /etc/bromigos/server.toml
[[ $(ask '{"verb": "remove", "app": "photos"}') == 403 ]] && grep -q '"not-allowed"' /tmp/body || fail "root's [board] actions didn't decide: $(cat /tmp/body)"
rm -f /etc/bromigos/server.toml
wait_for 30 bash -c '[[ $(systemctl show -P ActiveState bromigos-board-act.service) == inactive ]]' || fail "the helper didn't end after the refusals"
! systemctl is-failed -q bromigos-board-act.service || fail "the helper's unit failed on a refusal"
[[ -z $(systemctl list-units --failed --no-legend 'bromigos-board*') ]] || fail "a refusal left a failed unit"

section "actions: links, a FIFO and free text planted by the board's user"
echo "root's file" > /etc/bromigos-board-test-victim; chmod 600 /etc/bromigos-board-test-victim
rid=00000000000000aa
as_board python3 -I -c 'import os, sys
for pid in range(os.getpid(), os.getpid() + 300):
    os.symlink("/etc/bromigos-board-test-victim", f"/run/bromigos-board/requests/{sys.argv[1]}.result.json.{pid}.tmp")' "$rid"
as_board ln -s /etc/bromigos-board-test-victim "/run/bromigos-board/requests/$rid.result.json"
as_board mkfifo /run/bromigos-board/requests/00000000000000ff.json
as_board sh -c "printf '{\"id\": \"$rid\", \"verb\": \"x /var/lib/bromigos-board/evil.so x\", \"app\": \"photos\", \"at\": %s}' \"\$(date +%s%3N)\" > /run/bromigos-board/requests/.w.tmp && mv /run/bromigos-board/requests/.w.tmp /run/bromigos-board/requests/$rid.json"
wait_for 60 test -s "/run/bromigos-board/results/$rid.json" || { journalctl -u bromigos-board-act.service --no-pager -n 30; fail "the planted request got no answer (the helper hung?)"; }
grep -q '"unknown-verb"' "/run/bromigos-board/results/$rid.json" || fail "the planted request's answer: $(cat "/run/bromigos-board/results/$rid.json")"
! grep -q 'evil' "/run/bromigos-board/results/$rid.json" || fail "the answer quotes the request"
[[ $(cat /etc/bromigos-board-test-victim) == "root's file" && $(owner /etc/bromigos-board-test-victim) == "root:root 600" ]] || fail "root wrote through a planted link"
[[ ! -e /etc/ld.so.preload ]] || fail "/etc/ld.so.preload was made"
wait_for 60 bash -c '[[ -z $(ls -A /run/bromigos-board/requests) ]]' || fail "what was planted wasn't cleared: $(ls -A /run/bromigos-board/requests | head)"
rm -f /etc/bromigos-board-test-victim

section "actions: deleting data needs a code that root made"
forged=AAAAAAAA
as_board sh -c "printf '{\"made_at\": 0, \"expires_at\": 99999999999999}' > /var/lib/bromigos-board/codes/\$(printf %s $forged | sha256sum | cut -d' ' -f1).json"
[[ $(ask "{\"verb\": \"remove\", \"app\": \"photos\", \"delete_data\": true, \"code\": \"$forged\"}") == 403 ]] && grep -q '"needs-code"' /tmp/body \
    || fail "a code the board's user made was taken for a deletion: $(cat /tmp/body)"
[[ $(calls 'remove photos --delete-data --yes') == 0 ]] || fail "data was deleted on a forged code"
code=$(/usr/lib/bromigos/board/bromigos-board code --json | python3 -c 'import json, sys; print(json.load(sys.stdin)["code"])')
sha=$(printf %s "${code//-/}" | sha256sum | cut -d' ' -f1)
[[ $(owner "/var/lib/bromigos-board-root/codes/$sha.json") == "root:root 600" ]] || fail "root's note of the code is $(owner "/var/lib/bromigos-board-root/codes/$sha.json" 2>&1)"
[[ $(owner "/var/lib/bromigos-board/codes/$sha.json") == "$board:$board 600" ]] || fail "the board's record of the code is $(owner "/var/lib/bromigos-board/codes/$sha.json" 2>&1)"
[[ $(ask "{\"verb\": \"remove\", \"app\": \"photos\", \"delete_data\": true, \"code\": \"$code\"}") == 202 ]] || fail "root's own code wasn't taken: $(cat /tmp/body)"
wait_for 60 bash -c "[[ \$(grep -c '^0 lab apps remove photos --delete-data --yes\$' /var/lib/bromigos-board-test/calls.log) == 1 ]]" || fail "the deletion didn't run once: $(grep remove /var/lib/bromigos-board-test/calls.log)"
[[ ! -e /var/lib/bromigos-board-root/codes/$sha.json && ! -e /var/lib/bromigos-board/codes/$sha.json ]] || fail "the code's records weren't both removed"
[[ $(ask "{\"verb\": \"remove\", \"app\": \"photos\", \"delete_data\": true, \"code\": \"$code\"}") == 403 ]] || fail "the code deleted twice"
code=$(/usr/lib/bromigos/board/bromigos-board code --json | python3 -c 'import json, sys; print(json.load(sys.stdin)["code"])')
[[ $(from=192.168.1.31 api POST /api/session "${page[@]}" -d "{\"code\": \"$code\"}") == 200 ]] || fail "sign-in with a fresh code"
[[ $(ask "{\"verb\": \"remove\", \"app\": \"photos\", \"delete_data\": true, \"code\": \"$code\"}") == 403 ]] || fail "a code that signed a browser in deleted data"
sleep 2
[[ $(calls 'remove photos --delete-data --yes') == 1 ]] || fail "data was deleted more than once"

section "a job's own actions: answered, stopped and started again by root's helper, for real"
# three real jobs, started as root starts any job: one that asks, one that may be stopped, one
# that fails and was started as safe to start again
act=/usr/lib/bromigos/bin/bromigos-activity
state() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["state"])' "/var/lib/bromigos/activity/jobs/$1.json" 2>/dev/null; }
started() { python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])'; }
job_is() { [[ $(state "$1") == "$2" ]]; }
job_do() {  # job_do JOB VERB [JSON]: POST /api/activity/JOB/VERB as the signed-in browser
    local body=${3-}
    [[ -n $body ]] || body='{}'
    from=192.168.1.31 api POST "/api/activity/$1/$2" "${page[@]}" -H "$session_cookie" -d "$body"
}
asks=$("$act" run --kind test.ask --title "Asking" --detach --json -- /bin/sh -c \
    'echo "::ask ready Is it ready? [yes] It is [no] Not yet"; read -r a < "$BROMIGOS_ACTIVITY_ANSWERS"; [ "$a" = yes ]' | started)
sleeps=$("$act" run --kind test.sleep --title "Waiting" --cancel-safe --detach --json -- /bin/sleep 600 | started)
fails=$("$act" run --kind test.fail --title "Failing" --retry-safe --detach --json -- /bin/false | started)
[[ -n $asks && -n $sleeps && -n $fails ]] || fail "the jobs didn't start: '$asks' '$sleeps' '$fails'"
wait_for 30 job_is "$asks" needs-you && wait_for 30 job_is "$sleeps" running && wait_for 30 job_is "$fails" failed \
    || fail "the jobs are $(state "$asks"), $(state "$sleeps"), $(state "$fails")"
# what the job isn't asking, and what isn't a job, start nothing
[[ $(job_do "$asks" answer '{"question": "ready", "choice": "maybe"}') == 409 ]] && grep -q '"bad-choice"' /tmp/body || fail "a choice it doesn't have: $(cat /tmp/body)"
[[ $(job_do "$asks" answer '{"question": "other", "choice": "yes"}') == 409 ]] && grep -q '"not-asking"' /tmp/body || fail "another question: $(cat /tmp/body)"
[[ $(job_do "$asks" cancel) == 409 ]] && grep -q '"not-safe"' /tmp/body || fail "stopping a job that never said it is safe: $(cat /tmp/body)"
[[ $(job_do "${sleeps%-*}" cancel) == 404 ]] && grep -q '"no-job"' /tmp/body || fail "a part of an id: $(cat /tmp/body)"
[[ $(job_do "$sleeps" retry) == 409 ]] && grep -q '"cant-retry"' /tmp/body || fail "starting again a job that runs: $(cat /tmp/body)"
[[ $(state "$asks") == needs-you && $(state "$sleeps") == running ]] || fail "a refused action changed a job: $(state "$asks"), $(state "$sleeps")"
# the answer reaches the job, and the job goes on to its end
[[ $(job_do "$asks" answer '{"question": "ready", "choice": "yes"}') == 202 ]] || { journalctl -u bromigos-board-act.service --no-pager -n 30; fail "the answer: $(cat /tmp/body)"; }
grep -q '"words":"Answered."' /tmp/body || fail "the answer's words: $(cat /tmp/body)"
wait_for 30 job_is "$asks" succeeded || { cat "/var/lib/bromigos/activity/jobs/$asks.json"; fail "the answered job is $(state "$asks")"; }
grep -q 'Answered: It is' "/var/lib/bromigos/activity/jobs/$asks.json" || fail "the record doesn't say what was answered"
[[ $(job_do "$asks" answer '{"question": "ready", "choice": "yes"}') == 409 ]] && grep -q '"ended"' /tmp/body || fail "answering a job that ended: $(cat /tmp/body)"
# stopped
[[ $(job_do "$sleeps" cancel) == 202 ]] || { journalctl -u bromigos-board-act.service --no-pager -n 30; fail "the stop: $(cat /tmp/body)"; }
wait_for 40 job_is "$sleeps" cancelled || fail "the stopped job is $(state "$sleeps")"
# started again: a new job, asked for from the board
[[ $(job_do "$fails" retry) == 202 ]] || { journalctl -u bromigos-board-act.service --no-pager -n 30; fail "starting again: $(cat /tmp/body)"; }
again=$(python3 -c 'import json; print(json.load(open("/tmp/body"))["job"])')
[[ $again =~ ^[0-9]{8}-[0-9]{4}-test\.fail-[0-9a-f]{4}$ && $again != "$fails" ]] || fail "no new job came back: $(cat /tmp/body)"
wait_for 30 job_is "$again" failed || fail "the job started again is $(state "$again")"
python3 - "$again" <<'PY' || fail "the new job's record: $(cat "/var/lib/bromigos/activity/jobs/$again.json")"
import json, sys
r = json.load(open(f"/var/lib/bromigos/activity/jobs/{sys.argv[1]}.json"))
assert r["kind"] == "test.fail" and r["requested_by"]["via"] == "board" and r["command"] == ["/bin/false"], r
PY
# root's [board] actions decides each of them
printf '[board]\nactions = ["restart"]\n' > /etc/bromigos/server.toml
[[ $(job_do "$fails" retry) == 403 ]] && grep -q '"not-allowed"' /tmp/body || fail "root's [board] actions didn't decide a job's action: $(cat /tmp/body)"
rm -f /etc/bromigos/server.toml
[[ -z $(ls /run/bromigos-board/requests) ]] || fail "requests were left: $(ls -a /run/bromigos-board/requests)"

section "the activity stream: signed in, the jobs' records come through"
# (the records' folder was made here, by the helper's first run: the API's user must be able to read it)
as_board ls /var/lib/bromigos/activity/jobs >/dev/null || fail "the board's user can't read the activity records: $(stat -c '%n %U:%G %a' /var/lib/bromigos /var/lib/bromigos/activity /var/lib/bromigos/activity/jobs)"
python3 -I -c 'import sys; sys.path.insert(0, "/usr/lib/bromigos/lib"); import bromigos_activity' || fail "the activity library doesn't load as installed"
curl -sS -N --max-time 4 --unix-socket "$sock" -H "Host: $host.local" -H "X-Forwarded-For: $lan" -H "$session_cookie" http://board/api/activity > /tmp/stream 2>/dev/null || true
grep -q '^event: snapshot' /tmp/stream || fail "the activity stream: $(head -c 300 /tmp/stream)"
grep -q '"kind":"app.restart"' /tmp/stream && grep -q '"via":"board"' /tmp/stream || fail "the page's own jobs aren't in the stream: $(head -c 400 /tmp/stream)"

section "nobody looks any more: the reader stops; nothing failed"
wait_for 90 bash -c '! systemctl is-active -q bromigos-board-snapshot.service' || fail "the reader didn't stop after the board closed"
wait_for 30 bash -c '[[ $(systemctl show -P ActiveState bromigos-board-act.service) == inactive ]]' || fail "the helper didn't end"
[[ -z $(systemctl list-units --failed --no-legend 'bromigos-board*') ]] || { systemctl list-units --failed 'bromigos-board*'; fail "a unit failed"; }
systemd-analyze security --no-pager bromigos-board.service | tail -1
echo "::endgroup::"
echo "the Lab board: all of it passed"
