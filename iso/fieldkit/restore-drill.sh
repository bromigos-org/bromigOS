# shellcheck shell=bash
# The restore drill on the installed bromigOS Server (docs/server.md, "Backups"), sourced by
# iso/fieldkit/ci-test.sh once that Server is up and signed in as tester (the VM "server"):
# the real restic, the real snapper on btrfs, sudo and systemd, with no network.
#
#   1. a backup to a folder (as a USB disk's would be), and a healthy health line
#   2. `backups list` and `show` find the files
#   3. a restore to a new folder: identical files, nothing else changed
#   4. `restore --in-place`: the dry run names the one changed file; --apply takes a real
#      snapper snapshot of that subvolume first; then there is nothing to do. /home gets its
#      own snapshot; where none can be taken (/srv has no snapper configuration) it says so
#      and stops
#   5. the test restore: by hand, and under systemd as its timer runs it
#   6. as a user in wheel, with sudo's password forgotten: the command asks sudo itself
#   7. a damaged repository: the test restore fails, the health line and the alert say so
#
# Every `bromigos lab backups` here is run as tester, with no sudo in front: the command runs
# itself again through sudo, on the serial console's terminal. sudo's password is given once
# per step, the scripted way (sudo -S -v, which sudo remembers for that terminal), since the
# harness can't type at a prompt in the middle of a command.
#
# Uses ci-test.sh's step and run. About two minutes of VM time.

# what every step's script starts with: stop at the first failure, sudo's password for this
# terminal, j EXPR: a value out of the JSON on stdin (d is the document), and said CMD…: what a
# command that is meant to fail says (its exit status isn't the pipeline's)
drill_start='set -e -o pipefail
echo tester | sudo -S -p "" -v
j() { python3 -c "import json, sys; d = json.load(sys.stdin); print(eval(sys.argv[1]))" "$1"; }
said() { "$@" 2>&1 || true; }
recent="(just now|a minute ago|[0-9] minutes ago)"
'
drill() { run server "$drill_start$1"; }

drill_backup() { drill "$(cat <<'VM'
# files where the backup looks: on / (snapper's root), on /home (snapper's home) and on /srv (no snapshots)
sudo mkdir -p /etc/restore-drill /srv/restore-drill /mnt/restore-drill
mkdir -p ~/restore-drill
printf 'port = 8080\n' | sudo tee /etc/restore-drill/app.conf >/dev/null
printf 'one\n' | sudo tee /etc/restore-drill/one.conf >/dev/null
head -c 300000 /dev/urandom | sudo tee /srv/restore-drill/data.bin >/dev/null
printf 'remember the milk\n' > ~/restore-drill/note.txt
ln -sfn note.txt ~/restore-drill/latest
sudo sh -c 'sha256sum /etc/restore-drill/* /srv/restore-drill/* /home/tester/restore-drill/note.txt > /root/restore-drill.sums'
# before a destination is set: off, in plain words, and nothing raised
bromigos lab backups | sed -n 1p | grep -x "Backups are off: nothing on this server is backed up. .*"
# the destination: a folder on this disk, set the way a USB disk's is ([backup] to)
sudo python3 - <<'PY'
import re, tomllib
p = "/etc/bromigos/server.toml"
s = open(p).read()
if "backup" in tomllib.loads(s):
    s = re.sub(r"(?m)^to *=.*\n", "", s) if 'to' in tomllib.loads(s)["backup"] else s
    s = re.sub(r"(?m)^\[backup\]\n", '[backup]\nto = "/mnt/restore-drill"\n', s)
else:
    s += '\n[backup]\nto = "/mnt/restore-drill"\n'
open(p, "w").write(s)
assert tomllib.loads(s)["backup"]["to"] == "/mnt/restore-drill"
PY
bromigos lab backups | sed -n 1p | grep -x "No backup yet: the first one runs tonight."
bromigos lab backups run                     # = bromigos server backup run, which asks sudo itself
test -f /mnt/restore-drill/config            # restic's repository is there
bromigos lab backups | tee /tmp/drill-status
sed -n 1p /tmp/drill-status | grep -Ex "Backed up $recent\. Last test restore: none yet\."
grep -E "^  Backups kept +1 backup, from " /tmp/drill-status
test "$(bromigos lab backups --json | j '(d["ok"], d["health"]["state"], d["snapshots"]["count"], d["health"]["problems"])')" = "(True, 'ok', 1, [])"
# whether the folder is there: root sees restic's repository in it; you can't look into it, and that is said as unknown, not as gone
test "$(sudo bromigos lab backups --json | j 'd["destination"]')" = "{'kind': 'folder', 'path': '/mnt/restore-drill', 'present': True}"
test "$(bromigos lab backups --json | j 'd["destination"]["present"]')" != False
bromigos server | grep -E "^  Backups +Backed up $recent\. Last test restore: none yet\. To /mnt/restore-drill\.$"
echo DRILL-BACKUP-OK
VM
)"; }

drill_look() { drill "$(cat <<'VM'
bromigos lab backups list | tee /tmp/drill-list
grep -E "^1 backup at /mnt/restore-drill, newest first:$" /tmp/drill-list
id=$(bromigos lab backups list --json | j 'd["snapshots"][-1]["short_id"]')
test "$(bromigos lab backups list --json | j 'all(p in d["snapshots"][-1]["paths"] for p in ("/etc", "/srv", "/home"))')" = True
bromigos lab backups show "$id" /etc/restore-drill | tee /tmp/drill-show
grep -E "^  file +12 bytes .* app\.conf$" /tmp/drill-show
grep -E "^  file +4 bytes .* one\.conf$" /tmp/drill-show
test "$(bromigos lab backups show /home/tester/restore-drill --json | j 'sorted((e["name"], e["type"], e["size"]) for e in d["entries"])')" \
    = "[('latest', 'symlink', None), ('note.txt', 'file', 18)]"
test "$(bromigos lab backups show "$id" /srv/restore-drill --json | j 'd["entries"][0]["size"]')" = 300000
said bromigos lab backups show "$id" /etc/nothing-here | grep "isn't in the backup"
echo DRILL-LOOK-OK
VM
)"; }

drill_restore() { drill "$(cat <<'VM'
# what the server's own files are now: a restore to a new folder must leave every one alone
state() { sudo sh -c 'find /etc /home/tester/restore-drill /srv/restore-drill -xdev \( -type f -o -type l \) -printf "%p %s %T@ %l\n" | sort | sha256sum'; }
before=$(state)
bromigos lab backups restore /etc/restore-drill /srv/restore-drill /home/tester/restore-drill | tee /tmp/drill-restore
grep -c "^\[[1-5]/5\] " /tmp/drill-restore | grep -x 5
dest=$(sed -n 's/^  into //p' /tmp/drill-restore)
case $dest in /srv/restore/backup-*) ;; *) echo "restored into: $dest"; exit 1 ;; esac
grep -x "Restored 5 files (300 KB) from the backup of .*" /tmp/drill-restore
grep -x "  Skipped: nothing." /tmp/drill-restore
# identical: the same checksums, read from inside the new folder
sudo sh -c "cd '$dest' && sed 's|  /|  ./|' /root/restore-drill.sums | sha256sum -c --quiet"
sudo test "$(sudo readlink "$dest/home/tester/restore-drill/latest")" = note.txt
sudo test ! -e "$dest/.bromigos-restore-incomplete"
test "$(sudo stat -c %a "$dest")" = 700
test "$(state)" = "$before"
sudo sha256sum -c --quiet /root/restore-drill.sums
# and never into a folder with files in it
said bromigos lab backups restore /etc/restore-drill --to /etc | grep "Restore never writes into a folder with files in it"
test "$(state)" = "$before"
echo DRILL-RESTORE-OK
VM
)"; }

drill_in_place() { drill "$(cat <<'VM'
id=$(bromigos lab backups list --json | j 'd["snapshots"][-1]["short_id"]')
printf 'port = 9999  # a bad edit\n' | sudo tee /etc/restore-drill/app.conf >/dev/null
# the look: exactly that file, a snapshot of / promised, nothing changed
bromigos lab backups restore "$id" /etc/restore-drill --in-place | tee /tmp/drill-look
grep -x "  replace 1 file that changed since the backup:" /tmp/drill-look
grep -E "^    /etc/restore-drill/app\.conf   \(now $(stat -c %s /etc/restore-drill/app.conf) bytes, .*; the backup's is 12 bytes\)$" /tmp/drill-look
grep -x '  First, a snapshot of / is taken (snapper'"'"'s "root"), so this can be undone.' /tmp/drill-look
plan=$(bromigos lab backups restore "$id" /etc/restore-drill --in-place --json)
test "$(echo "$plan" | j '([r["path"] for r in d["replace"]], d["add"], d["unchanged"], [(s["subvolume"], s["config"]) for s in d["safety"]])')" \
    = "(['/etc/restore-drill/app.conf'], [], 1, [('/', 'root')])"
grep -q 9999 /etc/restore-drill/app.conf
newest() { sudo snapper --csvout -c root list --columns number | tail -1; }
was=$(newest)
# without a yes it stops; with one: a real snapshot of / first, then the file is back
said bromigos lab backups restore "$id" /etc/restore-drill --in-place --apply --json | j 'd["error"]["code"]' | grep -x needs-yes
test "$(newest)" = "$was"
applied=$(bromigos lab backups restore "$id" /etc/restore-drill --in-place --apply --yes --plan "$(echo "$plan" | j 'd["digest"]')" --json)
test "$(echo "$applied" | j '(d["state"], d["replaced"], d["added"], d["skipped"], d["verified"], len(d["snapshots_taken"]))')" = "('done', 1, 0, [], True, 1)"
number=$(echo "$applied" | j 'd["snapshots_taken"][0]["number"]')
test "$number" -gt "$was"
# snapper itself has it, and it's the newest
sudo snapper --csvout -c root list --columns number,description | grep -x "$number,before restoring from backup $id (bromigos lab backups)"
test "$(newest)" = "$number"
# the snapshot holds the file as it was before the restore: the bad edit is in it, to go back to
sudo grep -q 9999 "/.snapshots/$number/snapshot/etc/restore-drill/app.conf"
test "$(cat /etc/restore-drill/app.conf)" = "port = 8080"
sudo sha256sum -c --quiet /root/restore-drill.sums
# again: nothing to do, and no second snapshot
bromigos lab backups restore "$id" /etc/restore-drill --in-place --apply --yes | grep "there is nothing to do: every file already matches the backup"
test "$(newest)" = "$number"
echo DRILL-IN-PLACE-OK
VM
)"; }

drill_subvolumes() { drill "$(cat <<'VM'
id=$(bromigos lab backups list --json | j 'd["snapshots"][-1]["short_id"]')
# /home has snapper's "home": its own snapshot
printf 'forgotten\n' > ~/restore-drill/note.txt
test "$(bromigos lab backups restore "$id" /home/tester/restore-drill --in-place --json | j '[(s["subvolume"], s["config"]) for s in d["safety"]]')" = "[('/home', 'home')]"
bromigos lab backups restore "$id" /home/tester/restore-drill --in-place --apply --yes | grep -E "Before it, snapshot [0-9]+ of /home was taken"
test "$(cat ~/restore-drill/note.txt)" = "remember the milk"
# /srv has no snapshots: it says so plainly, and stops until it is told to go on without one
echo spoiled | sudo tee /srv/restore-drill/data.bin >/dev/null
bromigos lab backups restore "$id" /srv/restore-drill --in-place | grep -x "  No snapshot can be taken of /srv: snapshots aren't set up for it. What this replaces there can't be brought back afterwards."
said bromigos lab backups restore "$id" /srv/restore-drill --in-place --apply --yes | grep "No snapshot can be taken of /srv first"
test "$(cat /srv/restore-drill/data.bin)" = spoiled
bromigos lab backups restore "$id" /srv/restore-drill --in-place --apply --yes --without-snapshot | grep -x "  No snapshot was taken first: the files that were replaced can't be brought back."
sudo sha256sum -c --quiet /root/restore-drill.sums
test "$(bromigos lab backups --json | j '(d["health"]["state"], d["restore"]["state"], d["restore"]["mode"])')" = "('ok', 'done', 'in-place')"
echo DRILL-SUBVOLUMES-OK
VM
)"; }

drill_test() { drill "$(cat <<'VM'
bromigos lab backups test | tee /tmp/drill-test
grep -c "^\[[1-6]/6\] " /tmp/drill-test | grep -x 6
grep -E "^The test restore passed: [0-9,]+ files \(.*\) came back from the backup of .* and match it\." /tmp/drill-test
sudo test -z "$(sudo ls /var/lib/bromigos/server/restore-test)"
first=$(bromigos lab backups --json | j 'd["last_test"]["ts"]')
# under systemd, as the monthly timer runs it
systemctl is-enabled bromigos-server-backup-test.timer | grep -x enabled
systemctl list-timers --all --no-pager | grep bromigos-server-backup-test.timer
systemctl show -P TriggeredBy bromigos-server-backup-test.service | grep -x bromigos-server-backup-test.timer
sudo systemctl start bromigos-server-backup-test.service
test "$(systemctl show -P Result bromigos-server-backup-test.service)" = success
sudo journalctl -u bromigos-server-backup-test.service -b --no-pager -o cat | grep "The test restore passed"
test "$(bromigos lab backups --json | j "d['last_test']['ts'] > $first and d['last_test']['phase'] == 'ok' and d['last_test_passed']['ts'] == d['last_test']['ts']")" = True
# the health line has it, with its date
bromigos lab backups | tee /tmp/drill-status
sed -n 1p /tmp/drill-status | grep -Ex "Backed up $recent\. Last test restore: $recent, passed\."
grep -E "^  Test restore +passed $recent \($(date +%F) [0-9:]{5}\): [0-9,]+ files restored and read back, a sample$" /tmp/drill-status
grep -E "^  Schedule +backup nightly \(active\), check weekly \(active\), test restore monthly \(active\)$" /tmp/drill-status
# the weekly check too, with the real restic
sudo bromigos server backup check --data | grep "the backup checks out"
echo DRILL-TEST-OK
VM
)"; }

drill_damage() { drill "$(cat <<'VM'
said sudo bromigos alerts check --system --only backup.restic --json | j '[a["id"] for a in d["alerts"] if a["check"] == "backup.restic"]' | grep -x "\[\]"
# bit rot: the biggest pack file at the destination cut in half
pack=$(sudo sh -c 'ls -S /mnt/restore-drill/data/*/* | head -1')
sudo chmod u+w "$pack"; sudo truncate -s "$(( $(sudo stat -c %s "$pack") / 2 ))" "$pack"
# the status still reads fine: nothing looks at the data until a restore does
bromigos lab backups | sed -n 1p | grep -E "Last test restore: $recent, passed\."
# every file restored, from the destination alone: it fails, in plain words
if bromigos lab backups test --all > /tmp/drill-damage 2>&1; then cat /tmp/drill-damage; echo "the test restore passed on a damaged repository"; exit 1; fi
cat /tmp/drill-damage
grep "^The test restore failed: " /tmp/drill-damage
grep "^Until one passes, don't count on this backup to give your files back\." /tmp/drill-damage
sudo test -z "$(sudo ls /var/lib/bromigos/server/restore-test)"
# the health line, `bromigos server` and the alert say so
bromigos lab backups > /tmp/drill-status && { echo "the status still exits 0"; exit 1; }
cat /tmp/drill-status
sed -n 1p /tmp/drill-status | grep -E "The last test restore failed \($recent\): "
grep -E "^  Test restore +failed $recent " /tmp/drill-status
test "$(bromigos lab backups --json | j '(d["ok"], d["health"]["state"], [p["id"] for p in d["health"]["problems"]], d["last_test_passed"] is not None)')" \
    = "(False, 'attention', ['test-failed'], True)"
bromigos server | grep -E "^  Backups +.*The last test restore failed"
said sudo bromigos alerts check --system --only backup.restic --json | j '[(a["id"], a["severity"], a["title"]) for a in d["alerts"] if a["check"] == "backup.restic"]' \
    | grep -x "\[('backup.restic:server-test', 'needs_you', 'The last test restore failed')\]"
said bromigos alerts | grep "The last test restore failed"
# under systemd it fails the unit too, and is in the journal
sudo systemctl start bromigos-server-backup-test.service && { echo "the unit passed"; exit 1; }
test "$(systemctl show -P Result bromigos-server-backup-test.service)" = exit-code
sudo systemctl reset-failed bromigos-server-backup-test.service
echo DRILL-DAMAGE-OK
VM
)"; }

drill_user() { run server "$(cat <<'VM'
set -e -o pipefail
# tester is in wheel and not root; nothing here is run with sudo by hand
test "$(id -u)" != 0; id -nG | grep -qw wheel
sudo -k                                      # forget sudo's password: the command has to ask
# with no terminal to ask on, it says so plainly, as JSON too, and stops
{ bromigos lab backups list --json < /dev/null || true; } | python3 -c 'import json, sys; e = json.load(sys.stdin)["error"]; print(e["message"]); assert e["code"] == "needs-root"'
# the status needs no rights at all
bromigos lab backups < /dev/null | sed -n 1p | grep -E "^Backed up .*Last test restore: .*, passed\.$"
# on a terminal the command runs itself again through sudo, which asks for the password. The
# harness can't type at that prompt, so the password is given to sudo beforehand (it keeps it
# for this terminal); the command's own sudo then goes through without one
echo tester | sudo -S -p "" -v
test -t 0
bromigos lab backups list | grep -E "^1 backup at /mnt/restore-drill, newest first:$"
bromigos lab backups show /etc/restore-drill | grep -E " app\.conf$"
rm -rf ~/restored
bromigos lab backups restore /home/tester/restore-drill --to ~/restored 2>&1 | tail -6
sudo test "$(sudo cat ~/restored/home/tester/restore-drill/note.txt)" = "remember the milk"
echo DRILL-USER-OK
VM
)"; }

if TIMEOUT=30 run server 'echo up' >/dev/null 2>&1; then
    step "restore drill: a backup to a folder, and a healthy health line" drill_backup \
        && step "restore drill: list and show find the files" drill_look \
        && step "restore drill: a restore to a new folder is identical, and changes nothing else" drill_restore \
        && step "restore drill: in place: the dry run names the file, a real snapper snapshot first, then nothing to do" drill_in_place \
        && step "restore drill: in place on /home (its own snapshot) and on /srv (none: said plainly, and stopped)" drill_subvolumes \
        && step "restore drill: the test restore passes, by hand and under systemd; its timer is on" drill_test \
        && step "restore drill: as a user in wheel, the command asks sudo itself" drill_user \
        && step "restore drill: a damaged repository fails the test restore; the health line and the alert say so" drill_damage || true
else
    echo "SKIP restore drill: the installed Server isn't up"
fi
