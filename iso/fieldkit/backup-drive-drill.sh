# shellcheck shell=bash
# The Go Bag drill on the installed bromigOS Server (docs/server.md, "The Go Bag"), sourced by
# iso/fieldkit/ci-test.sh after the restore drill, on the same Server (the VM "server"): a real
# USB drive as the kernel sees one, the real udev, systemd, mkfs.ext4, mount and restic, with no
# network. The drive is a disk image the harness plugs into the running VM and pulls out again
# through QEMU's control socket (iso/fieldkit/test.py plug | unplug).
#
#   1. a blank USB drive is plugged in: `go-bag drives` offers it and not the system disk; the
#      system disk is refused whatever is said; the blank drive is refused until --erase, and
#      --erase until a yes; nothing is written to it before that
#   2. `go-bag setup --erase --yes`: a real ext4 filesystem, the first copy as an activity job,
#      "Safe to unplug", and the drive really unmounted; it is remembered by its filesystem's UUID
#   3. the drive is pulled out: the status says so, and reading it says to plug it in
#   4. plugged in again, nobody runs anything: udev starts the unit, the unit starts the job,
#      the job copies, checks, unmounts and ends "Safe to unplug"
#   5. the existing restore commands read it: `list --from go-bag`, and a file restored from it
#   6. no good copy for 40 days: the health line and the alert say so, in the words for a drive
#      that is plugged in, then (pulled out) for one that isn't
#
# The restore drill before this one ends with its own backup damaged on purpose, so every check
# here reads the Go Bag's own lines, never the whole verdict.
#
# Uses ci-test.sh's step, run, T and out, and restore-drill.sh's drill (its `j` and `said`).
# About two minutes of VM time.

gobag_img=${out:?}/vm/go-bag.img

gobag_wait='# until the kernel shows the USB drive (or shows it gone)
usb() { lsblk -dnpo NAME,TRAN | awk "\$2 == \"usb\" {print \$1}"; }
appeared() { for _ in $(seq 30); do [ -n "$(usb)" ] && return 0; sleep 1; done; echo "no USB drive appeared"; return 1; }
gone() { for _ in $(seq 30); do [ -z "$(usb)" ] && return 0; sleep 1; done; echo "the USB drive is still there"; return 1; }
# the copies to the backup drive that ended, newest last: "ID STATE VIA SUMMARY"
copies() { bromigos activity list --all --json | python3 -c "
import json, sys
for x in sorted(json.load(sys.stdin)[\"jobs\"], key=lambda x: x[\"started_at\"]):
    if x[\"kind\"] == \"backup.drive\" and x[\"ended_at\"]:
        print(x[\"id\"], x[\"state\"], x[\"requested_by\"][\"via\"], (x[\"result\"] or {}).get(\"summary\", \"\"))"; }
'
gobag() { TIMEOUT=${TIMEOUT:-420} drill "$gobag_wait$1"; }

gobag_refusals() {
    rm -f "$gobag_img"; truncate -s 2G "$gobag_img" || return 1          # blank: no partitions, no filesystem
    "$T" plug --name server "$gobag_img" || return 1
    gobag "$(cat <<'VM'
appeared
dev=$(usb)
said bromigos lab backups go-bag | sed -n 1p | grep -x "No Go Bag drive is set up."
bromigos lab backups go-bag drives | tee /tmp/gobag-drives
grep -E "^  /dev/vda +.*: not offered: it is part of this server \(" /tmp/gobag-drives
grep -E "^  $dev +.*: can be the Go Bag$" /tmp/gobag-drives
# the disk the server runs from: never, whatever is said
said bromigos lab backups go-bag setup /dev/vda --internal --erase --yes | tee /tmp/gobag-refused
grep "A drive this server is using is never touched" /tmp/gobag-refused
# a blank drive: not without --erase, and --erase not without a yes (--json never asks)
said bromigos lab backups go-bag setup | grep "has no filesystem this server knows"
test "$(said bromigos lab backups go-bag setup --erase --json | j 'd["error"]["code"]')" = needs-yes
# nothing was written to it, mounted or remembered
test -z "$(sudo blkid -o value -s TYPE "$dev" || true)"
test -z "$(lsblk -no MOUNTPOINTS "$dev" | xargs)"
test "$(bromigos lab backups --json | j 'd["drives"]')" = "[]"
echo GOBAG-REFUSALS-OK
VM
)"; }

gobag_setup() { gobag "$(cat <<'VM'
dev=$(usb)
bromigos lab backups go-bag setup --erase --yes | tee /tmp/gobag-setup
grep -E "is now this server's Go Bag, formatted and empty\.$" /tmp/gobag-setup
grep -c "^\[[1-4]/4\] " /tmp/gobag-setup | grep -x 4
grep -x "\[4/4\] Making it safe to unplug" /tmp/gobag-setup
grep -Ex "Safe to unplug\. [0-9,]+ files \(.*\) copied to the Go Bag drive\." /tmp/gobag-setup
# a real ext4 filesystem with the Go Bag's label, and really unmounted
test "$(lsblk -dno FSTYPE,LABEL "$dev" | xargs)" = "ext4 GOBAG"
test -z "$(lsblk -no MOUNTPOINTS "$dev" | xargs)"
! findmnt -rno TARGET | grep /run/bromigos/backup-drive
# remembered by its filesystem's UUID, never by a device name
uuid=$(lsblk -dno UUID "$dev"); test -n "$uuid"; echo "$uuid" > /tmp/gobag-uuid
sudo python3 - "$uuid" <<'PY'
import json, sys
drives = json.load(open("/var/lib/bromigos/server/backup.json"))["drives"]
assert list(drives) == [sys.argv[1]], drives
assert "/dev/" not in json.dumps(drives), drives
PY
test "$(bromigos lab backups --json | j '[(x["name"], x["uuid"], x["label"], x["fstype"], x["plugged_in"], x["last_good_copy"]["phase"], x["stale"]) for x in d["drives"]]')" \
    = "[('Go Bag', '$uuid', 'GOBAG', 'ext4', True, 'ok', False)]"
# the copy was an activity job in a unit of its own, with its four steps
copies | tee /tmp/gobag-copies
grep -E "^[0-9]{8}-[0-9]{4}-backup\.drive-.* succeeded cli Safe to unplug\. " /tmp/gobag-copies
id=$(grep " succeeded cli Safe to unplug" /tmp/gobag-copies | tail -1 | cut -d" " -f1)
test "$(bromigos activity show "$id" --json | j '(d["job"]["unit"] == "bromigos-job-" + d["job"]["id"] + ".service", [(s["id"], s["state"]) for s in d["job"]["steps"]])')" \
    = "(True, [('drive', 'done'), ('copy', 'done'), ('check', 'done'), ('unplug', 'done')])"
# the status and the Server's own line have it
bromigos lab backups | tee /tmp/gobag-status || true
grep -E "^  Go Bag +.*labelled \"GOBAG\": plugged in$" /tmp/gobag-status
grep -E "^  Last copy +worked, $recent \(" /tmp/gobag-status
sed -n 1p /tmp/gobag-status | grep -E "Go Bag: copied $recent\."
bromigos server | grep -E "^  Backups +.*Go Bag: copied $recent\."
said bromigos lab backups go-bag | sed -n 1p | grep -Ex "Go Bag: copied $recent\."
copies | wc -l > /tmp/gobag-count
echo GOBAG-SETUP-OK
VM
)"; }

gobag_unplugged() {
    "$T" unplug --name server "$gobag_img" || return 1
    gobag "$(cat <<'VM'
gone
test "$(bromigos lab backups --json | j 'd["drives"][0]["plugged_in"]')" = False
said bromigos lab backups go-bag | grep -E "^  Go Bag +.*: not plugged in$"
said bromigos lab backups list --from go-bag | grep -x "The Go Bag drive isn't plugged in. Plug it in, then try again."
said bromigos lab backups go-bag run | grep -x "The Go Bag drive isn't plugged in. Plug it in: the copy starts by itself."
# something new on the server, for the next copy to take
printf 'packed\n' | sudo tee /etc/restore-drill/go-bag.conf >/dev/null
echo GOBAG-UNPLUGGED-OK
VM
)"; }

gobag_plugged_in() {
    "$T" plug --name server "$gobag_img" || return 1
    gobag "$(cat <<'VM'
appeared
uuid=$(cat /tmp/gobag-uuid) was=$(cat /tmp/gobag-count)
# nobody runs anything here: udev saw the drive, its unit started the job
for _ in $(seq 90); do [ "$(copies | wc -l)" -gt "$was" ] && break; sleep 2; done
copies | tee /tmp/gobag-copies
tail -1 /tmp/gobag-copies | grep -E "^[0-9]{8}-[0-9]{4}-backup\.drive-.* succeeded timer Safe to unplug\. [0-9,]+ files \(.*\) copied to the Go Bag drive\.$"
id=$(tail -1 /tmp/gobag-copies | cut -d" " -f1)
bromigos activity show "$id"
test "$(bromigos activity show "$id" --json | j '(d["job"]["unit"] == "bromigos-job-" + d["job"]["id"] + ".service", d["job"]["subject"]["type"], [(s["id"], s["label"], s["state"]) for s in d["job"]["steps"]])')" \
    = "(True, 'drive', [('drive', 'Finding the Go Bag drive', 'done'), ('copy', 'Copying what changed', 'done'), ('check', 'Checking what was written', 'done'), ('unplug', 'Making it safe to unplug', 'done')])"
# the unit udev started is the drive's own, named by its filesystem, and it ended well
unit="bromigos-server-backup-drive@$uuid.service"
sudo journalctl -u "$unit" -b --no-pager -o cat | tee /tmp/gobag-unit
grep -F "Finished bromigOS Server: a USB drive was plugged in ($uuid)." /tmp/gobag-unit
! grep -i "failed" /tmp/gobag-unit
udevadm info -q property -n "$(usb)" | grep -x "SYSTEMD_WANTS=$unit"
# safe to unplug is true: nothing of the drive is mounted
dev=$(usb)
test -z "$(lsblk -no MOUNTPOINTS "$dev" | xargs)"
! findmnt -rno TARGET | grep /run/bromigos/backup-drive
test "$(bromigos lab backups --json | j '(d["drives"][0]["plugged_in"], d["drives"][0]["last_copy"]["unmounted"], d["drives"][0]["running"])')" = "(True, True, False)"
# the job took its turn with the drive's lock, and may be started again (bromigos activity run --lock, --retry-safe)
test "$(bromigos activity show "$id" --json | j 'd["job"]["locks"]')" = "['backup-drive']"
echo GOBAG-PLUGGED-IN-OK
VM
)"; }

gobag_restore() { gobag "$(cat <<'VM'
dev=$(usb)
# the existing restore commands, reading the drive
bromigos lab backups list --from go-bag 2>&1 | tee /tmp/gobag-list
grep -Ex "[12] backups? on the Go Bag drive, newest first:" /tmp/gobag-list      # one a day is kept, as for the nightly backup
grep -x "The Go Bag drive is unmounted: safe to unplug." /tmp/gobag-list
bromigos lab backups show --from go-bag /etc/restore-drill 2>&1 | grep -E " go-bag\.conf$"
sudo rm -rf /home/tester/from-go-bag
bromigos lab backups restore --from go-bag /etc/restore-drill/go-bag.conf --to ~/from-go-bag 2>&1 | tee /tmp/gobag-restore
grep -x "Restored 1 file (7 bytes) from the backup of .*" /tmp/gobag-restore
test "$(sudo cat ~/from-go-bag/etc/restore-drill/go-bag.conf)" = packed
# a test restore from it is the drive's own record
bromigos lab backups test --from go-bag 2>&1 | grep -E "^The test restore passed: "
test "$(bromigos lab backups --json | j 'd["drives"][0]["last_test"]["phase"]')" = ok
# and each command left the drive unmounted
test -z "$(lsblk -no MOUNTPOINTS "$dev" | xargs)"
echo GOBAG-RESTORE-OK
VM
)"; }

gobag_stale() {
    gobag "$(cat <<'VM'
uuid=$(cat /tmp/gobag-uuid)
said sudo bromigos alerts check --system --only backup.restic --json | j '[a["id"] for a in d["alerts"] if "drive" in a["subject"]]' | grep -x "\[\]"
# 40 days pass with no copy (the last good one's date is moved back)
sudo python3 - "$uuid" <<'PY'
import json, sys
p = "/var/lib/bromigos/server/backup.json"
st = json.load(open(p))
for k in ("run", "run_ok"):
    st["drives"][sys.argv[1]][k]["ts"] -= 40 * 86400 + 60
json.dump(st, open(p, "w"), indent=1)
PY
# plugged in and stale: plugging it in is not the advice
said bromigos lab backups go-bag | sed -n 1p | grep -x "Your Go Bag drive hasn't been updated in 40 days. Unplug it and plug it back in."
test "$(bromigos lab backups --json | j '[p["id"] for p in d["health"]["problems"] if p["id"].startswith("drive")]')" = "['drive-stale']"
said sudo bromigos alerts check --system --only backup.restic --json | j '[a["title"] for a in d["alerts"] if a["id"] == "backup.restic:server-drive"][0]' \
    | grep -x "Your Go Bag drive hasn't been updated in 40 days"
echo GOBAG-STALE-OK
VM
)" || return 1
    "$T" unplug --name server "$gobag_img" || return 1
    gobag "$(cat <<'VM'
gone
# the reminder, as the person reads it: on the health line, on the Server's line and as an alert
said bromigos lab backups go-bag | sed -n 1p | grep -x "Your Go Bag drive hasn't been updated in 40 days. Plug it in."
said bromigos lab backups | sed -n 1p | grep -F "Your Go Bag drive hasn't been updated in 40 days. Plug it in."
bromigos server | grep -E "^  Backups +.*Your Go Bag drive hasn't been updated in 40 days\. Plug it in\."
said sudo bromigos alerts check --system --only backup.restic --json | j '[a["detail"] for a in d["alerts"] if a["id"] == "backup.restic:server-drive"][0]' \
    | grep -E "^Plug it in\. The copy starts by itself, and says when the drive is safe to unplug\."
said bromigos alerts | grep -F "Your Go Bag drive hasn't been updated in 40 days"
echo GOBAG-REMINDER-OK
VM
)"; }

if TIMEOUT=30 run server 'echo up' >/dev/null 2>&1; then
    step "go bag: the system disk and a blank USB drive are refused until the person says so in words" gobag_refusals \
        && step "go bag: setup formats the drive, makes the first copy as a job, and it is safe to unplug" gobag_setup \
        && step "go bag: pulled out, the status says so and reading it says to plug it in" gobag_unplugged \
        && step "go bag: plugged in, the copy starts by itself and ends safe to unplug, unmounted" gobag_plugged_in \
        && step "go bag: list, show, restore and the test restore read the drive" gobag_restore \
        && step "go bag: no copy for 40 days: the health line and the alert say so" gobag_stale || true
    "$T" unplug --name server "$gobag_img" >/dev/null 2>&1 || true
else
    step "go bag: the installed Server is up" false || true
fi
rm -f "$gobag_img"
