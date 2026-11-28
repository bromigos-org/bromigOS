#!/bin/bash
# The Lab board's container, started and used (docs/board.md, "In a container"):
#
#   board/container/test.sh IMAGE [--checkout]
#
# It runs IMAGE with an address of the lab's own, as behind an ingress, and checks: the page and
# the post's art are served; the door says where the board lives; a code from inside the
# container signs a browser in at that address and at no other; the signed-in board, its jobs
# and the lab follower answer; the follower reads a ComfyUI named in labjobs.toml (a stand-in
# that answers /queue and /history, inside the container) and a fleet's status mirror (a stand-in
# that answers /v1/feed, inside the container too), whose tasks then show on the board; and the
# parts run as their own users.
# --checkout runs this checkout's board library over the package's, and its job follower and
# feed reader over bromigos-core's and bromigos-lab's (a change that isn't published yet). Needs
# docker and python3. Nothing is left behind.
set -euo pipefail
image=${1:?the image to test}; here=$(cd "$(dirname "$0")" && pwd); repo=$(cd "$here/../.." && pwd)
name=board-test-$$; work=$(mktemp -d); addr=board.mylab.example
fail() { echo "FAIL: $*" >&2; echo "--- the container said:" >&2; docker logs "$name" 2>&1 | tail -30 >&2; exit 1; }
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT

printf '[[comfyui]]\nname = "standin"\nurl = "http://127.0.0.1:8188"\n\n[[fleet]]\nname = "tasks"\nurl = "http://127.0.0.1:8082/v1/feed"\n' > "$work/labjobs.toml"; chmod 0644 "$work/labjobs.toml"
mounts=(-v "$work/labjobs.toml:/etc/bromigos/labjobs.toml:ro")
if [ "${2:-}" = --checkout ]; then
  mounts+=(-v "$repo/board/lib/bromigos_board:/usr/lib/bromigos/lib/bromigos_board:ro" -v "$repo/board/caddy/site.caddy:/usr/share/bromigos-board/caddy/site.caddy:ro"
           -v "$here/bromigos-board-container:/usr/local/bin/bromigos-board-container:ro" -v "$here/Caddyfile:/etc/bromigos-board-container/Caddyfile:ro"
           # the job follower (bromigos-core) and the feed's reader (bromigos-lab), which the board's API and follower use
           -v "$repo/lib/bromigos_labjobs.py:/usr/lib/bromigos/lib/bromigos_labjobs.py:ro" -v "$repo/lib/bromigos_activity.py:/usr/lib/bromigos/lib/bromigos_activity.py:ro"
           -v "$repo/bin/bromigos-activity:/usr/lib/bromigos/bin/bromigos-activity:ro"
           -v "$repo/homelab/lib/bromigos_homelab/fleet.py:/usr/lib/bromigos/lib/bromigos_homelab/fleet.py:ro")
fi
docker run -d --name "$name" -e BOARD_ADDRESS="$addr" -e PYTHONDONTWRITEBYTECODE=1 -p 127.0.0.1::8080 "${mounts[@]}" "$image" >/dev/null
port=$(docker port "$name" 8080/tcp | sed -n '1s/.*://p'); url="http://127.0.0.1:$port"
# a ComfyUI that is idle: an empty queue and no history
docker exec -d "$name" python3 -I -c '
import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"queue_running": [], "queue_pending": []} if self.path.startswith("/queue") else {}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", 8188), H).serve_forever()'
# a fleet's status mirror: one business, one task that needs a person and one being written, reported just now
docker exec -d "$name" python3 -I -c '
import http.server, json, time
def at(s): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + s))
def task(n, title, **more): return dict({"repo": "app", "issue": n, "pr": None, "title": title, "url": "https://github.com/my-org/app/issues/%d" % n, "issue_url": "https://github.com/my-org/app/issues/%d" % n}, **more)
feed = {"schema": 1, "generated_at": at(0), "stale_after": at(5400), "business": "Example", "control_repo": "my-org/agents", "timezone": "UTC", "enabled": True,
        "headline": "1 needs you \u00b7 1 working \u00b7 0 waiting \u00b7 0 merged today", "counts": {"today": {"merged": 0}, "seven_days": {"merged": 0}}, "accounts": [],
        "working": [task(57, "Add CSV export to the orders page", stage="agent", step="agent", lane="working", phrase="Writing", started_at=at(-300))],
        "needs_person": [task(41, "Checkout totals are wrong", kind="stuck", why="it did not go green", lane="needs_you", phrase="Stuck \u00b7 it did not go green", since=at(-900))],
        "waiting": [], "recent": [], "warnings": [], "omitted": {}}
body = json.dumps({"schema": 1, "feeds": [{"business": "example", "received_at": at(0), "feed": feed}]}).encode()
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path.split("?")[0] == "/v1/feed"
        self.send_response(200 if ok else 404); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body) if ok else 0)); self.end_headers(); self.wfile.write(body if ok else b"")
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", 8082), H).serve_forever()'

get() { curl -s --max-time "${wait:-10}" -o "$work/body" -w '%{http_code}' -H "Host: $addr" "${@:2}" "$url$1" || true; }
json() { python3 -I -c 'import json, sys; d = json.load(open(sys.argv[1])); print(eval(sys.argv[2], {"d": d}))' "$work/body" "$1"; }
for _ in $(seq 60); do [ "$(get /api/door)" = 200 ] && break; sleep 1; done
[ "$(get /api/door)" = 200 ] || fail "the door never answered"
[ "$(json 'd["lab"]["address"]')" = "https://$addr" ] || fail "the door doesn't say the board lives at https://$addr: $(cat "$work/body")"
{ [ "$(get /)" = 200 ] && grep -q '<html' "$work/body"; } || fail "the page isn't served"
[ "$(get /post/post.json)" = 200 ] && [ "$(json 'sorted(d)')" = "['crew', 'map', 'ship']" ] || fail "the post's drawing isn't served"
[ "$(get /post/frame.webp)" = 200 ] || fail "the post's art isn't served"
[ "$(get /api/board)" = 401 ] || fail "the board answered a browser that isn't signed in"

code=$(docker exec "$name" bromigos-board code --json | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["code"])')
docker exec "$name" bromigos-board code | grep -q "Open https://$addr " || fail "the code's own words don't name https://$addr"
page=(-H "X-Bromigos-Board: 1" -H "Content-Type: application/json" -d "{\"code\": \"$code\"}")
[ "$(curl -s --max-time 10 -o "$work/body" -w '%{http_code}' -H "Host: evil.mylab.example" -H "Origin: https://evil.mylab.example" "${page[@]}" "$url/api/session")" = 403 ] || fail "another name signed in"
[ "$(get /api/session -H "Origin: https://evil.example.org" "${page[@]}")" = 403 ] || fail "another site's page signed in"
[ "$(get /api/session -H "Origin: https://$addr" -D "$work/head" "${page[@]}")" = 200 ] || fail "the code didn't sign in at https://$addr: $(cat "$work/body")"
# (the cookie is for HTTPS only, as the ingress serves it: taken from the answer's own header here)
session=$(sed -n 's/^[Ss]et-[Cc]ookie: \(__Host-bromigos-board=[^;]*\);.*/\1/p' "$work/head")
{ [ -n "$session" ] && grep -qi '^set-cookie:.*; Secure' "$work/head"; } || fail "no session cookie for HTTPS only"
cookie=(-H "Cookie: $session")
[ "$(get /api/board "${cookie[@]}")" = 200 ] || fail "the signed-in board didn't answer: $(cat "$work/body")"
[ "$(json 'd["lab"]["address"]')" = "https://$addr" ] || fail "the board doesn't say where it lives"
[ "$(json 'd["actions"]')" = "[]" ] || fail "a board in a container offers actions: $(json 'd["actions"]')"
# (the jobs are a stream that stays open: its first lines are enough)
{ [ "$(wait=3 get /api/activity "${cookie[@]}")" = 200 ] && grep -q '^event: \|^data: \|^: ' "$work/body"; } || fail "the jobs' stream didn't answer: $(head -c 300 "$work/body")"

# the follower starts when a signed-in browser looks, and reads the stand-in
ok=
for _ in $(seq 40); do
  [ "$(get /api/lab "${cookie[@]}")" = 200 ] || fail "the lab's state didn't answer"
  if [ "$(json 'bool(d.get("following")) and [(i["name"], i["state"]) for i in d["instances"]] == [("standin", "ok")]')" = True ]; then ok=1; break; fi
  sleep 1
done
[ -n "$ok" ] || fail "the follower never read the stand-in ComfyUI: $(cat "$work/body")"

# a fleet's tasks: the follower reads the stand-in status mirror, and the board has its report,
# counts what needs you on Home and carries the tasks on the jobs' stream
ok=
for _ in $(seq 40); do
  [ "$(get /api/fleet "${cookie[@]}")" = 200 ] || fail "the fleet's document didn't answer: $(cat "$work/body")"
  if [ "$(json '[(f["business"], f["state"], f["counts"]["needs_you"], f["counts"]["working"]) for f in d["fleets"]] == [("Example", "fresh", 1, 1)] and d["state"] == "warn"')" = True ]; then ok=1; break; fi
  sleep 1
done
[ -n "$ok" ] || fail "the follower never read the stand-in status mirror: $(cat "$work/body")"
ok=
for _ in $(seq 20); do
  [ "$(get /api/board "${cookie[@]}")" = 200 ] || fail "the signed-in board stopped answering"
  if [ "$(json '[(n["job"], n["machine"]) for n in d["needs_you"] if n["job"]]')" = "[('task.example.app.41', 'Example')]" ]; then ok=1; break; fi
  sleep 1
done
[ -n "$ok" ] || fail "the task that needs you isn't on Home: $(json 'd["needs_you"]')"
wait=3 get /api/activity "${cookie[@]}" >/dev/null
{ grep -q '"task\.example\.app\.57"' "$work/body" && grep -q '"task\.example\.app\.41"' "$work/body" && grep -q '"kind":"agent\.task"' "$work/body"; } || fail "the fleet's tasks aren't on the jobs' stream: $(head -c 400 "$work/body")"

# each part as its own user, and none of them root but the reader
who=$(docker exec "$name" ps -eo user:20,args --no-headers)
grep -Eq '^bromigos-board +.*bromigos-board serve' <<<"$who" || fail "the API isn't running as bromigos-board:"$'\n'"$who"
grep -Eq '^caddy +.*caddy run' <<<"$who" || fail "Caddy isn't running as caddy:"$'\n'"$who"
grep -Eq '^bromigos-labjobs +.*bromigos-activity follow' <<<"$who" || fail "the follower isn't running as bromigos-labjobs:"$'\n'"$who"
[ "$(docker exec "$name" stat -c '%U:%G %a' /run/bromigos-board.sock)" = "bromigos-board:caddy 660" ] || fail "the API's socket isn't the board's and Caddy's alone"

# a restart keeps nothing in the way: the same container comes back up and the session still stands
docker restart -t 5 "$name" >/dev/null
port=$(docker port "$name" 8080/tcp | sed -n '1s/.*://p'); url="http://127.0.0.1:$port"
for _ in $(seq 60); do [ "$(get /api/board "${cookie[@]}")" = 200 ] && break; sleep 1; done
[ "$(get /api/board "${cookie[@]}")" = 200 ] || fail "after a restart the signed-in board didn't come back"
echo "ok: $image ($(docker exec "$name" cat /etc/bromigos-board-container.versions | tr '\n' ' '))"
