#!/usr/bin/env bash
# `bromigos lab apps` on a real machine, with Podman, Quadlet and systemd: CI's throwaway runner
# (.github/workflows/homelab-tests.yml, "Apps on a Server"), as root. It adds a tiny app (BusyBox's
# web server, tests/fixtures/apps-integration), lists it, removes it keeping its data, adds it
# again and finds the data, then removes it with its data.
#
# Never run this on a computer you use: it installs its own catalogue in /usr/share/bromigos/lab
# and writes /etc/bromigos, /etc/containers/systemd and /srv/apps.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
fix="$repo/homelab/tests/fixtures/apps-integration"
lab="$repo/homelab/bin/bromigos-lab"
activity="$repo/bin/bromigos-activity"
[[ $(id -u) == 0 ]] || { echo "run as root, on a throwaway machine" >&2; exit 2; }
[[ ${CI:-} == true ]] || { echo "this changes the machine it runs on: CI only" >&2; exit 2; }

install -Dm0644 "$fix/provision-catalogue.toml" /usr/share/bromigos/lab/provision-catalogue.toml
for t in hello _common; do
    install -Dm0644 -t "/usr/share/bromigos/lab/quadlet/$t/" "$fix/quadlet/$t/"*
done
# a bromigOS Server: `bromigos lab deploy` is `bromigos lab apps add` there
install -d /etc/bromigos
printf '# the app manager'"'"'s CI test: a Server, for bromigos lab deploy\n' > /etc/bromigos/server.toml

fail() { echo "FAILED: $*" >&2; exit 1; }
hello() {   # the hello tile from `apps list --json`, or one of its fields
    "$lab" apps list --json | python3 -c 'import json, sys
t = {x["id"]: x for x in json.load(sys.stdin)}["hello"]
print(json.dumps(t) if len(sys.argv) < 2 else json.dumps(t[sys.argv[1]]))' "$@"
}
section() { echo "::endgroup::"; echo "::group::$*"; }
echo "::group::start"

section "add: a job of its own, with the lock apps"
"$lab" apps add hello
[[ $(hello installed) == true ]] || fail "hello isn't installed after add"
[[ $(hello state) == '"ok"' ]] || fail "hello isn't running and answering: $(hello)"
[[ $(curl -fsS http://127.0.0.1:18080/) == hello ]] || fail "hello's page doesn't answer"

section "list"
"$lab" apps list
hello
[[ $(hello since) =~ ^[0-9]{13}$ ]] || fail "no start time from the service manager"
python3 - "$(hello)" <<'EOF' || fail "the tile isn't the contract"
import json, sys
t = json.loads(sys.argv[1])
keys = {"id", "job", "app", "holo", "group", "installed", "version", "recipe", "household", "state", "state_word",
        "since", "reading", "open", "update", "measured", "requires", "can", "needed_by"}
assert set(t) == keys, set(t) ^ keys
assert t["state_word"] == "Running" and t["version"] == "1.37.0" and t["recipe"] == 1, t
assert t["open"] == {"url": "http://" + __import__("socket").gethostname().split(".")[0] + ".local:18080", "port": 18080}, t["open"]
assert t["measured"]["ram_bytes"] and t["measured"]["ram_bytes"] > 0, t["measured"]   # the units' cgroups
assert t["measured"]["disk_bytes"] is not None, t["measured"]
assert t["reading"] is None and t["update"] is None, t
assert t["can"] == ["open", "restart", "logs", "remove"], t["can"]
EOF

section "the app keeps a note in its data folder"
note="note $(date +%s%N)"
echo "$note" > /srv/apps/hello/notes/note.txt
[[ $(podman exec hello cat /data/note.txt) == "$note" ]] || fail "the container doesn't see its data folder"

section "remove, keeping the data"
"$lab" apps remove hello --plan
"$lab" apps remove hello
[[ $(hello installed) == false ]] || fail "hello is still listed as installed"
! systemctl is-active --quiet hello.service || fail "hello.service still runs"
[[ ! -e /etc/containers/systemd/hello.container ]] || fail "its unit is still there"
[[ -e /etc/containers/systemd/bromigos-lab.network ]] || fail "the apps' shared network went with it"
[[ $(cat /srv/apps/hello/notes/note.txt) == "$note" ]] || fail "remove deleted the data without --delete-data"
grep -qx 'apps = \[\]' /etc/bromigos/lab/apps.toml || fail "apps.toml still has hello: $(cat /etc/bromigos/lab/apps.toml)"

section "add again (as bromigos lab deploy, on a Server): it finds its data"
"$lab" deploy hello
[[ $(hello state) == '"ok"' ]] || fail "hello isn't running after it was added again: $(hello)"
[[ $(podman exec hello cat /data/note.txt) == "$note" ]] || fail "adding it again didn't find the data"

section "restart and logs"
"$lab" apps restart hello
"$lab" apps logs hello -n 5
"$lab" apps logs hello --json | python3 -c 'import json, sys; d = json.load(sys.stdin); assert d["ok"] and d["units"] == ["hello.service"], d'

section "remove, deleting the data"
"$lab" apps remove hello --delete-data --yes
[[ ! -e /srv/apps/hello ]] || fail "--delete-data left /srv/apps/hello"

section "the jobs' records"
python3 "$activity" list --all
python3 "$activity" list --all --json | python3 -c '
import json, sys
jobs = json.load(sys.stdin)["jobs"]
kinds = sorted(j["kind"] for j in jobs)
assert kinds == ["app.install", "app.install", "app.remove", "app.remove"], kinds
assert all(j["locks"] == ["apps"] and j["state"] == "succeeded" and j["subject"]["id"] == "hello" for j in jobs), jobs
first = min((j for j in jobs if j["kind"] == "app.remove"), key=lambda j: j["started_at"])
steps = [(s["id"], s["state"]) for s in first["steps"]]
assert steps == [("check", "done"), ("stop", "done"), ("units", "done"), ("data", "skipped"), ("record", "done")], steps
'
echo "::endgroup::"
echo "bromigos lab apps: add, list, remove keeping data, add again finding it, remove deleting it: all as they should be"
