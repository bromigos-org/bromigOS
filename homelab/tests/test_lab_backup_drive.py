"""The Go Bag, `bromigos lab backups go-bag` (lib/bromigos_backup_drive.py): the backup on a USB
drive you carry away. The verdict's words; what `setup` refuses; the copy as an activity job
that ends "Safe to unplug"; the status and its --json; and the restore commands reading the
drive.

No drive of this machine is read or touched. In the stand-in root (test_lab_backups.py's Rig)
lsblk, mount, umount, sync, wipefs, mkfs.ext4 and udevadm are the stand-ins below, named to the
code by BROMIGOS_BACKUPS_<TOOL>: a "drive" is a folder under the test's temporary folder, and
"mounting" it puts a link to that folder at the mount point. restic is the real one (the tests
that copy need it on PATH), and so is `bromigos activity`, run in the foreground with its
records under the stand-in root."""
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_lab_backups import DAY, HOUR, NOW, REPO, RESTIC, S3, B, Rig, rec  # noqa: E402  (it puts lib/ on the path)

import bromigos_backup_drive as D  # noqa: E402

UUID = "6f1d2c3b-aaaa-4bbb-8ccc-0123456789ab"      # the USB drive's filesystem
NEW = "0e5a7d10-1111-4222-8333-444455556666"       # what the stand-in mkfs.ext4 gives a formatted one
SYSTEM = "9c2e4f6a-dddd-4eee-8fff-ba9876543210"    # the server's own disk

TOOLS = {
    # lsblk: $FAKE/disks.json, with each filesystem's mount points from $FAKE/mounts
    "lsblk": r'''#!/usr/bin/env python3
import json, os, sys
fake = os.environ["FAKE"]
open(fake + "/log", "a").write("lsblk\n")
doc = json.load(open(fake + "/disks.json"))
mounts = {}
if os.path.exists(fake + "/mounts"):
    for line in open(fake + "/mounts"):
        u, _, m = line.rstrip("\n").partition("\t")
        mounts.setdefault(u, []).append(m)
def walk(n):
    n["mountpoints"] = (n.get("mountpoints") or []) + mounts.get(n.get("uuid") or "-", [])
    for c in n.get("children") or []:
        walk(c)
for d in doc["blockdevices"]:
    walk(d)
print(json.dumps(doc))
''',
    # mount -o OPTIONS UUID=… POINT: the mount point becomes a link to the drive's folder
    "mount": r'''#!/bin/sh
echo "mount $*" >> "$FAKE/log"
if [ -f "$FAKE/mount-fails" ]; then echo "mount: $4: wrong fs type, bad option, bad superblock" >&2; exit 32; fi
uuid=${3#UUID=}
mkdir -p "$FAKE/media/$uuid"
rmdir "$4" && ln -s "$FAKE/media/$uuid" "$4" && printf '%s\t%s\n' "$uuid" "$4" >> "$FAKE/mounts"
''',
    "umount": r'''#!/bin/sh
echo "umount $*" >> "$FAKE/log"
if [ -f "$FAKE/umount-fails" ]; then echo "umount: $1: target is busy." >&2; exit 32; fi
[ -L "$1" ] || { echo "umount: $1: not mounted." >&2; exit 32; }
rm "$1" && mkdir "$1"
grep -v "	$1\$" "$FAKE/mounts" > "$FAKE/mounts.new"; mv "$FAKE/mounts.new" "$FAKE/mounts"
''',
    "sync": '#!/bin/sh\necho "sync $*" >> "$FAKE/log"\n',
    "wipefs": '#!/bin/sh\necho "wipefs $*" >> "$FAKE/log"\n',
    "udevadm": '#!/bin/sh\necho "udevadm $*" >> "$FAKE/log"\n',
    # mkfs.ext4 … -L LABEL DEVICE: that device is an empty ext4 filesystem with a new UUID
    "mkfs.ext4": r'''#!/usr/bin/env python3
import json, os, shutil, sys
fake = os.environ["FAKE"]
open(fake + "/log", "a").write("mkfs.ext4 " + " ".join(sys.argv[1:]) + "\n")
if os.path.exists(fake + "/mkfs-fails"):
    sys.exit("mkfs.ext4: Input/output error while writing the superblock")
dev, label = sys.argv[-1], sys.argv[sys.argv.index("-L") + 1]
doc = json.load(open(fake + "/disks.json"))
def walk(n):
    if n.get("path") == dev:
        n.update(fstype="ext4", label=label, uuid=os.environ["NEW_UUID"])
    for c in n.get("children") or []:
        walk(c)
for d in doc["blockdevices"]:
    walk(d)
json.dump(doc, open(fake + "/disks.json", "w"))
shutil.rmtree(fake + "/media/" + os.environ["NEW_UUID"], ignore_errors=True)
os.makedirs(fake + "/media/" + os.environ["NEW_UUID"])
''',
    # restic: the real one; with $FAKE/backup-fails a backup fails as a full drive does, and with
    # $FAKE/check-fails what was written doesn't read back
    "restic": r'''#!/bin/sh
if [ "$1" = backup ] && [ -f "$FAKE/backup-fails" ]; then
  echo '{"message_type":"exit_error","code":1,"message":"Fatal: unable to save snapshot: no space left on device"}' >&2
  exit 1
fi
if [ "$1" = check ]; then
  echo "restic $*" >> "$FAKE/log"
  if [ -f "$FAKE/check-fails" ]; then echo "Fatal: repository contains errors" >&2; exit 1; fi
fi
exec "$REAL_RESTIC" "$@"
''',
}


def disk(name, model, size, usb=True, children=(), **more):
    return dict({"name": name, "path": f"/dev/{name}", "type": "disk", "size": size, "ro": False, "rm": False,
                 "hotplug": usb, "tran": "usb" if usb else "nvme", "fstype": None, "label": None, "uuid": None,
                 "mountpoints": [None], "model": model, "vendor": "", "children": list(children)}, **more)


def part(name, fstype, uuid, size=1_000_000_000_000, label=None, mountpoints=(None,)):
    return {"name": name, "path": f"/dev/{name}", "type": "part", "size": size, "ro": False, "rm": False, "hotplug": False,
            "tran": None, "fstype": fstype, "label": label, "uuid": uuid, "mountpoints": list(mountpoints), "model": None, "vendor": None}


def system_disk():
    return disk("nvme0n1", "Fast NVMe 500", 500_000_000_000, usb=False,
                children=[part("nvme0n1p2", "btrfs", SYSTEM, 499_000_000_000, mountpoints=["/", "/home"])])


def usb(fstype="exfat", uuid=UUID, name="sdb", label="CARRY", model="Portable SSD"):
    return disk(name, model, 1_000_204_886_016, children=[part(name + "1", fstype, uuid, 1_000_203_000_000, label)])


def drive(run_ok=None, run=None, added=None, **more):
    """backup.json's entry for the remembered drive."""
    d = {"label": "CARRY", "model": "Portable SSD", "size": 1_000_204_886_016, "fstype": "exfat",
         "added_at": "2026-09-01T10:00:00+00:00", "added_ts": NOW - (60 * DAY if added is None else added)}
    if run_ok:
        d["run_ok"] = run_ok
    if run or run_ok:
        d["run"] = run or run_ok
    return dict(d, **more)


class Words(unittest.TestCase):
    """What health() says about the Go Bag: its sentence in the one verdict, and the problems
    the alert raises."""

    def health(self, entry, to=S3, st=None, days=30, plugged=False):
        st = dict(st if st is not None else {"run": rec("ok", 6 * HOUR), "test_ok": rec("ok", 2 * DAY)}, drives={UUID: entry})
        rows = D.view(st, NOW, days, real=lambda p: os.devnull if plugged else "/nonexistent" + p)
        return B.health(to, st, NOW, {"kind": "s3", "path": "", "present": None}, None, rows)

    def test_the_go_bags_sentence_for_each_state(self):
        good = rec("ok", 3 * DAY)
        failed = rec("failed", 2 * HOUR, reason="Unable to save snapshot: no space left on device.")
        nightly = "Backed up 6 hours ago. Last test restore: 2 days ago, passed. "
        cases = [
            ("a good copy", drive(good), {}, "ok", nightly + "Go Bag: copied 3 days ago.", []),
            ("set up, never copied", drive(added=2 * DAY), {}, "ok", nightly + "Go Bag: no copy yet.", []),
            ("31 days without a copy", drive(rec("ok", 31 * DAY + HOUR)), {}, "attention",
             nightly + "Your Go Bag drive hasn't been updated in 31 days. Plug it in.", ["drive-stale"]),
            ("stale, and it is plugged in", drive(rec("ok", 40 * DAY)), dict(plugged=True), "attention",
             nightly + "Your Go Bag drive hasn't been updated in 40 days. Unplug it and plug it back in.", ["drive-stale"]),
            ("never copied since it was set up, long ago", drive(added=45 * DAY), {}, "attention",
             nightly + "Your Go Bag drive hasn't been updated in 45 days. Plug it in.", ["drive-stale"]),
            ("the last copy failed", drive(good, failed), {}, "attention",
             nightly + "The last copy to your Go Bag drive failed (2 hours ago): unable to save snapshot: no space left on device.",
             ["drive-failed"]),
            ("the Go Bag is the only backup", drive(good), dict(to="", st={}), "ok",
             "No nightly backup is set up: the Go Bag drive is this server's only backup. Go Bag: copied 3 days ago.", []),
            ("the only backup, and stale", drive(rec("ok", 33 * DAY)), dict(to="", st={}), "attention",
             "No nightly backup is set up: the Go Bag drive is this server's only backup. Your Go Bag drive hasn't "
             "been updated in 33 days. Plug it in.", ["drive-stale"]),
        ]
        for name, entry, more, state, verdict, problems in cases:
            with self.subTest(name):
                h = self.health(entry, **more)
                self.assertEqual(h["verdict"], verdict)
                self.assertEqual(h["state"], state)
                self.assertEqual([p["id"] for p in h["problems"]], problems)

    def test_the_reminder_is_worded_for_a_person(self):
        """The alert's title and the start of its detail read as one message: "Your Go Bag
        drive hasn't been updated in 31 days. Plug it in." """
        p = self.health(drive(rec("ok", 31 * DAY + HOUR)))["problems"][0]
        self.assertEqual(p["title"] + ". " + p["detail"].split(". ")[0] + ".",
                         "Your Go Bag drive hasn't been updated in 31 days. Plug it in.")
        self.assertEqual((p["severity"], p["subject"]), ("needs_you", "server-drive"))
        self.assertIn("The last good copy was on 2026-10-30T06:10:00-07:00.", p["detail"])
        self.assertIn("bromigos lab backups go-bag run", p["commands"])
        self.assertIn("drive_remind_days", p["note"])

    def test_the_thresholds(self):
        for days, age, stale in ((30, 30 * DAY - HOUR, False), (30, 30 * DAY + HOUR, True), (7, 8 * DAY, True),
                                 (0, 400 * DAY, False), (90, 60 * DAY, False)):
            with self.subTest(days=days, age=age):
                h = self.health(drive(rec("ok", age)), days=days)
                self.assertEqual([p["id"] for p in h["problems"]], ["drive-stale"] if stale else [])
        # the setting: a number of days, 0 for never; anything else is the default
        self.assertEqual([D.days(b) for b in ({}, {"drive_remind_days": 7}, {"drive_remind_days": 0}, {"drive_remind_days": "soon"},
                                              {"drive_remind_days": -1}, {"drive_remind_days": True})], [30, 7, 0, 30, 30, 30])

    def test_a_failed_copy_and_a_stale_drive_are_two_problems(self):
        """Both are in the verdict. The failed copy's alert is the copy job's own (activity.job),
        so its problem says so and the backup check leaves it out (tests/alerts has that)."""
        h = self.health(drive(rec("ok", 50 * DAY), rec("failed", DAY, reason="The Go Bag drive isn't plugged in.")))
        self.assertEqual([(p["id"], p["subject"], p.get("raised_by")) for p in h["problems"]],
                         [("drive-failed", "server-drive-copy", "activity.job"), ("drive-stale", "server-drive", None)])
        self.assertIn("The last good copy was 50 days ago.", h["problems"][0]["detail"])

    def test_a_copy_someone_stopped_is_not_a_failure(self):
        """`bromigos activity cancel` (or a stopped unit): the drive has no new copy, and nothing failed."""
        entry = drive(rec("ok", 3 * DAY), rec("stopped", HOUR, reason="It was stopped before it finished."))
        h = self.health(entry)
        self.assertEqual((h["problems"], h["state"]), ([], "ok"))
        self.assertTrue(h["verdict"].endswith(" Go Bag: copied 3 days ago."), h["verdict"])
        rows = []
        D.print_rows(D.view({"drives": {UUID: entry}}, NOW, real=lambda p: "/nonexistent" + p), NOW, lambda *r: rows.append(r))
        self.assertEqual([r[0] for r in rows], ["Go Bag", "Last copy", "", "Last good one"])
        self.assertTrue(rows[1][1].startswith("stopped before it finished, 1 hour ago ("), rows[1])
        self.assertEqual(rows[3][1].split(" (")[0], "3 days ago")

    def test_no_drive_changes_nothing(self):
        st = {"run": rec("ok", 6 * HOUR)}
        self.assertEqual(B.health(S3, st, NOW)["verdict"], "Backed up 6 hours ago. Last test restore: none yet.")
        self.assertEqual(B.health(S3, st, NOW, drives=[])["drives"], [])
        self.assertTrue(B.health("", {}, NOW, drives=[])["verdict"].startswith("Backups are off"))

    def test_what_the_status_knows_about_the_drive(self):
        st = {"drives": {UUID: drive(rec("ok", 3 * DAY, snapshot="1a2b3c4d", files=7, bytes=70_000))}}
        r = D.view(st, NOW, 30, real=lambda p: "/nonexistent" + p)[0]
        self.assertEqual({k: r[k] for k in ("name", "uuid", "label", "model", "size", "fstype", "plugged_in", "stale", "remind_days")},
                         {"name": "Go Bag", "uuid": UUID, "label": "CARRY", "model": "Portable SSD", "size": 1_000_204_886_016,
                          "fstype": "exfat", "plugged_in": False, "stale": False, "remind_days": 30})
        self.assertEqual((r["last_good_copy"]["age_s"], r["last_good_copy"]["snapshot"]), (3 * DAY, "1a2b3c4d"))
        self.assertTrue(D.view(st, NOW, 30, real=lambda p: os.devnull)[0]["plugged_in"])
        # a state file that is wrong never stops the status
        for odd in ({"drives": "x"}, {"drives": {UUID: "x"}}, {"drives": {UUID: {"run": 3, "run_ok": "y", "added_ts": "z"}}}, []):
            with self.subTest(odd=odd):
                rows = D.view(odd, NOW)
                self.assertIsInstance(B.health(S3, odd if isinstance(odd, dict) else {}, NOW, drives=rows)["verdict"], str)

    def test_a_yes_in_words(self):
        """Typed on a terminal, or --yes from a script; without a terminal and without --yes, no."""
        import argparse
        import io
        from unittest import mock
        a = argparse.Namespace(yes=False, json=False)
        with mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: False)), \
                mock.patch("builtins.input", side_effect=AssertionError("it asked with no terminal to ask on")):
            self.assertFalse(D.agreed(a, "Erase?", "erase"))
        tty = mock.Mock(isatty=lambda: True)
        with mock.patch.object(sys, "stdin", tty), mock.patch("builtins.input", return_value="erase"), \
                mock.patch.object(sys, "stdout", io.StringIO()):
            self.assertTrue(D.agreed(a, "Erase?", "erase"))
        with mock.patch.object(sys, "stdin", tty), mock.patch("builtins.input", return_value="yes"):
            self.assertFalse(D.agreed(a, "Erase?", "erase"), "yes isn't the word asked for")
        with mock.patch.object(sys, "stdin", tty), mock.patch("builtins.input", return_value="yes"):
            self.assertFalse(D.agreed(argparse.Namespace(yes=False, json=True), "Use it?"), "--json never asks")
        self.assertTrue(D.agreed(argparse.Namespace(yes=True, json=False), "Use it?"))


class DriveRig(Rig):
    """Rig's stand-in server, with a USB drive beside it: plug() and unplug() are a person's
    hands. No nightly backup is made (these tests are the drive's)."""

    backed_up = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name, text in TOOLS.items():
            (cls.bin / name).write_text(text)
            (cls.bin / name).chmod(0o755)

    def setUp(self):
        super().setUp()
        self.plug()

    @classmethod
    def environment(cls, snapper=False, **more):
        env = super().environment(snapper)
        env.update({"BROMIGOS_BACKUPS_" + name.upper().replace(".", "_"): str(cls.bin / name)
                    for name in TOOLS if name != "restic"})
        # bromigos activity: its records under the stand-in root, the job in the foreground
        env.update(BROMIGOS_ROOT=str(cls.root), BROMIGOS_ACTIVITY_RUNNER="foreground", NEW_UUID=NEW)
        env.update(more)
        return env

    # -- a person's hands
    def plug(self, *drives, system=True):
        """These drives are plugged in (default: the USB drive), beside the server's own disk."""
        drives = list(drives) if drives else [usb()]
        self.disks = ([system_disk()] if system else []) + drives
        (self.fake / "disks.json").write_text(json.dumps({"blockdevices": self.disks}))
        links = self.root / "dev/disk/by-uuid"
        shutil.rmtree(links, ignore_errors=True)
        links.mkdir(parents=True)
        for d in self.disks:
            for n in [d, *d["children"]]:
                if n.get("uuid"):
                    (links / n["uuid"]).write_text("")

    def unplug(self):
        self.plug(system_disk(), system=False)

    def media(self, uuid=UUID):
        """The drive's own files (what mounting it shows)."""
        p = self.fake / "media" / uuid
        p.mkdir(parents=True, exist_ok=True)
        return p

    # -- what happened
    def go(self, *args, rc=None, **more):
        r = self.lab("go-bag", *args, **more)
        if rc is not None:
            self.assertEqual(r.returncode, rc, r.stderr + r.stdout)
        return r

    def refused(self, *args, code, rc=3):
        d = json.loads(self.go(*args, "--json", rc=rc).stdout)
        self.assertEqual((d["ok"], d["error"]["code"]), (False, code), d)
        return d["error"]["message"]

    def touched(self):
        """The commands that would change a drive, as they were run."""
        return [line for line in self.log().splitlines() if line.split()[0] in ("mount", "umount", "wipefs", "mkfs.ext4")]

    def mounted(self):
        p = self.fake / "mounts"
        return p.read_text().strip() if p.exists() else ""

    def drives(self):
        p = self.root / "var/lib/bromigos/server/backup.json"
        return json.loads(p.read_text()).get("drives", {}) if p.exists() else {}

    def jobs(self):
        d = self.root / "var/lib/bromigos/activity/jobs"
        # oldest first (two jobs of one minute have ids that don't sort by time)
        return sorted((json.loads(p.read_text()) for p in d.glob("*.json")), key=lambda j: j["started_at"]) if d.is_dir() else []


class Setup(DriveRig):
    """`go-bag setup`: what it refuses, and that a refusal runs nothing that changes a drive."""

    def test_a_drive_inside_the_server_is_refused(self):
        inside = disk("sdc", "Desk Drive 4TB", 4_000_000_000_000, usb=False, tran="sata",
                      children=[part("sdc1", "ext4", UUID, 3_999_000_000_000)])
        self.plug(inside)
        words = self.refused("setup", "/dev/sdc", code="not-removable")
        self.assertIn("Desk Drive 4TB (4.0 TB) isn't a removable drive", words)
        self.assertIn("add --internal", words)
        # --yes alone never says it, and nothing was run or remembered
        self.refused("setup", "/dev/sdc", "--yes", code="not-removable")
        self.refused("setup", "/dev/sdc", "--erase", "--yes", code="not-removable")
        self.assertEqual((self.touched(), self.drives()), ([], {}))
        # with no drive named, a disk inside the server is never offered
        self.assertIn("No USB drive that could be the Go Bag is plugged in", self.refused("setup", code="no-drive"))

    def test_a_drive_the_server_uses_is_never_touched(self):
        for flags in ((), ("--internal", "--yes"), ("--internal", "--erase", "--yes")):
            with self.subTest(flags=flags):
                words = self.refused("setup", "/dev/nvme0n1", *flags, code="in-use")
                self.assertIn("/dev/nvme0n1p2 is mounted at /", words)
                self.assertIn("A drive this server is using is never touched", words)
        # a USB drive someone mounted is in use too: it says how to let go of it
        mine = usb()
        mine["children"][0]["mountpoints"] = ["/mnt/usb"]
        self.plug(mine)
        self.assertIn("unmount it first: sudo umount /mnt/usb", self.refused("setup", "--erase", "--yes", code="in-use"))
        ro = usb()
        ro["ro"] = True
        self.plug(ro)
        self.refused("setup", "/dev/sdb", code="read-only")
        self.assertEqual((self.touched(), self.drives()), ([], {}))

    def test_a_drive_it_cannot_write_needs_erase_and_erase_needs_a_yes(self):
        self.plug(usb("ntfs", label="My Drive"))
        words = self.refused("setup", code="needs-erase")
        self.assertIn('holds a ntfs filesystem named "My Drive"', words)
        self.assertIn("bromigos lab backups go-bag setup /dev/sdb1 --erase", words)
        self.assertEqual(self.touched(), [])
        words = self.refused("setup", "--erase", code="needs-yes")
        self.assertIn("Erasing /dev/sdb1 on Portable SSD (1.0 TB)", words)
        self.assertIn("deletes everything on it", words)
        self.assertEqual((self.touched(), self.drives()), ([], {}), "no yes: nothing was run")
        # a blank drive, and a member of someone's RAID: the same
        for d in (disk("sdb", "Blank Stick", 64_000_000_000), usb("linux_raid_member")):
            self.plug(d)
            self.refused("setup", code="needs-erase")
        self.assertEqual(self.touched(), [])

    def test_which_drive_and_which_partition(self):
        self.plug(usb(), usb(uuid=NEW, name="sdc", model="Other Stick"))
        words = self.refused("setup", code="which-drive", rc=2)
        self.assertIn("bromigos lab backups go-bag setup /dev/sdb     Portable SSD (1.0 TB)", words)
        self.assertIn("bromigos lab backups go-bag setup /dev/sdc     Other Stick (1.0 TB)", words)
        two = disk("sdb", "Two Parts", 2_000_000_000_000,
                   children=[part("sdb1", "vfat", "AB12-CD34", 500_000_000), part("sdb2", "exfat", UUID, label="DATA")])
        self.plug(two)
        words = self.refused("setup", code="which-partition", rc=2)
        self.assertIn('bromigos lab backups go-bag setup /dev/sdb2     1.0 TB, exfat, "DATA"', words)
        self.refused("setup", "--erase", "--yes", code="which-partition", rc=2)
        self.refused("setup", "/dev/sdz", code="no-such-drive", rc=2)
        self.assertEqual((self.touched(), self.drives()), ([], {}))

    def test_the_drives_it_could_be(self):
        self.plug(usb(), disk("sdc", "Desk Drive 4TB", 4_000_000_000_000, usb=False, tran="sata"))
        d = json.loads(self.go("drives", "--json", rc=0).stdout)
        self.assertEqual([(r["path"], r["usable"], r["why"]) for r in d["drives"]],
                         [("/dev/nvme0n1", False, "it is part of this server (/dev/nvme0n1p2 is mounted at /)"),
                          ("/dev/sdb", True, ""), ("/dev/sdc", False, "it isn't removable (a disk inside the server)")])
        out = self.go("drives", rc=0).stdout
        self.assertIn("/dev/sdb       Portable SSD, 1.0 TB: can be the Go Bag", out)
        self.assertIn('/dev/sdb1    1.0 TB, exfat, "CARRY"', out)
        self.assertEqual(self.touched(), [], "it only looks")

    def test_no_go_bag_yet(self):
        r = self.go(rc=0)
        self.assertTrue(r.stdout.startswith("No Go Bag drive is set up."))
        self.assertIn("bromigos lab backups go-bag setup", r.stdout)
        d = json.loads(self.go("--json", rc=0).stdout)
        self.assertEqual((d["set_up"], d["drives"], d["ok"]), (False, [], True))
        self.assertIn("No Go Bag drive is set up yet", self.refused("run", code="not-set-up"))
        self.assertIn("the only other place is the Go Bag drive, --from go-bag",
                      json.loads(self.lab("list", "--from", "the-moon", "--json").stdout)["error"]["message"])
        self.assertEqual(self.touched(), [])


@unittest.skipUnless(RESTIC, "restic isn't installed")
class SetupForReal(DriveRig):
    """`go-bag setup` on drives it may use: restic's repository on the drive, the drive
    remembered by its filesystem and never by its device name."""

    def test_files_it_does_not_know_need_a_yes_and_are_kept(self):
        (self.media() / "Holiday photos").mkdir()
        (self.media() / "Holiday photos/beach.jpg").write_text("a photo\n")
        (self.media() / "taxes.ods").write_text("numbers\n")
        (self.media() / "System Volume Information").mkdir()       # what Windows leaves isn't "files of yours"
        words = self.refused("setup", "--no-copy", code="has-files")
        self.assertIn("has files on it that aren't a Go Bag's (Holiday photos, taxes.ods)", words)
        self.assertIn("nothing is deleted", words)
        self.assertEqual((self.drives(), self.mounted()), ({}, ""), "refused: nothing remembered, the drive unmounted")
        self.assertFalse((self.media() / "bromigos-backup").exists())
        r = self.go("setup", "--no-copy", "--yes", rc=0)
        self.assertIn('Portable SSD (1.0 TB), labelled "CARRY" is now this server\'s Go Bag.', r.stdout)
        self.assertIn("The Go Bag drive is unmounted: safe to unplug.", r.stdout)
        self.assertEqual((self.media() / "Holiday photos/beach.jpg").read_text(), "a photo\n")
        self.assertEqual((self.media() / "taxes.ods").read_text(), "numbers\n")
        self.assertTrue((self.media() / "bromigos-backup/box/config").is_file(), "restic's repository, named after the server")
        self.assertIn("restic -r <this drive>/bromigos-backup/box", (self.media() / "bromigos-backup/README.txt").read_text())
        self.assertNotIn("mkfs.ext4", self.log())
        self.assertEqual(self.mounted(), "")

    def test_the_drive_is_remembered_by_its_filesystem_never_by_its_device_name(self):
        self.go("setup", "/dev/sdb", "--no-copy", rc=0)
        self.assertEqual(list(self.drives()), [UUID])
        d = self.drives()[UUID]
        self.assertEqual((d["label"], d["model"], d["fstype"], d["folder"]), ("CARRY", "Portable SSD", "exfat", "bromigos-backup/box"))
        raw = (self.root / "var/lib/bromigos/server/backup.json").read_text()
        self.assertNotIn("/dev/", raw)
        self.assertNotIn("sdb", raw)
        self.assertIn("mount -o rw,nosuid,nodev,noexec,uid=0,gid=0,umask=077 UUID=" + UUID, self.log(), "mounted by its UUID")
        # the key was made for it (this server had no backup yet), root-only, and is never printed
        key = self.root / "etc/bromigos/server/backup.key"
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        r = self.go("setup", "--no-copy", "--json", rc=0)
        self.assertNotIn(key.read_text().strip(), r.stdout + r.stderr + self.log())
        self.assertTrue(json.loads(r.stdout)["adopted"], "set up again: the backup on it is kept, with no question")

    def test_erase_formats_only_the_drive_that_was_named(self):
        self.plug(usb("ntfs", label="My Drive"))
        (self.media() / "old.doc").write_text("gone after an erase\n")
        d = json.loads(self.go("setup", "--erase", "--yes", "--no-copy", "--json", rc=0).stdout)
        self.assertEqual((d["erased"], d["adopted"], d["drive"]["uuid"], d["drive"]["fstype"], d["drive"]["label"]),
                         (True, False, NEW, "ext4", "GOBAG"))
        made = [line for line in self.log().splitlines() if line.startswith(("wipefs", "mkfs.ext4"))]
        self.assertEqual(made, ["wipefs --all /dev/sdb1", "mkfs.ext4 -q -F -m 0 -L GOBAG /dev/sdb1"])
        self.assertEqual(list(self.drives()), [NEW], "remembered as the filesystem mkfs made")
        self.assertTrue((self.media(NEW) / "bromigos-backup/box/config").is_file())
        self.assertIn(f"mount -o rw,nosuid,nodev,noexec UUID={NEW}", self.log())
        self.assertEqual(self.mounted(), "")

    def test_formatting_the_go_bag_itself_forgets_its_old_filesystem(self):
        """One drive, one entry: the filesystem `--erase` replaced is no longer remembered."""
        self.go("setup", "--no-copy", rc=0)
        self.assertEqual(list(self.drives()), [UUID])
        d = json.loads(self.go("setup", "--erase", "--yes", "--no-copy", "--json", rc=0).stdout)
        self.assertEqual((d["erased"], d["drive"]["uuid"]), (True, NEW))
        self.assertEqual(list(self.drives()), [NEW])
        self.assertEqual([r["uuid"] for r in self.doc()["drives"]], [NEW])
        self.assertFalse((self.media(NEW) / "Holiday photos").exists())
        self.assertTrue((self.media(NEW) / "bromigos-backup/box/config").is_file())

    def test_a_format_that_fails_remembers_nothing(self):
        self.plug(usb("ntfs"))
        (self.fake / "mkfs-fails").write_text("")
        self.assertIn("/dev/sdb1 couldn't be formatted: mkfs.ext4: Input/output error",
                      self.refused("setup", "--erase", "--yes", code="failed", rc=1))
        self.assertEqual((self.drives(), self.mounted()), ({}, ""))

    def test_one_drive_for_now_and_forget(self):
        self.go("setup", "--no-copy", rc=0)
        self.plug(usb(), usb(uuid=NEW, name="sdc", model="Second Stick"))
        words = self.refused("setup", "/dev/sdc", "--no-copy", code="one-drive")
        self.assertIn("One drive for now", words)
        self.assertIn("bromigos lab backups go-bag forget", words)
        self.refused("forget", code="needs-yes")
        r = self.go("forget", "--yes", rc=0)
        self.assertIn("is no longer this server's Go Bag", r.stdout)
        self.assertNotIn("drives", self.state())
        self.assertTrue((self.media() / "bromigos-backup/box/config").is_file(), "what is on the drive is left alone")
        self.go("setup", "/dev/sdc", "--no-copy", rc=0)
        self.assertEqual(list(self.drives()), [NEW])

    def test_a_backup_made_with_another_key_is_refused(self):
        self.go("setup", "--no-copy", rc=0)
        self.go("forget", "--yes", rc=0)
        (self.root / "etc/bromigos/server/backup.key").write_text("a key from another install\n")
        words = self.refused("setup", "--no-copy", code="wrong-key")
        self.assertIn("made with another key", words)
        self.assertIn("--erase", words)
        self.assertEqual((self.drives(), self.mounted()), ({}, ""))


@unittest.skipUnless(RESTIC, "restic isn't installed")
class Copy(DriveRig):
    """A Go Bag that is set up: the copy when it is plugged in, the status, and restoring from it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the drive, set up once for the class (restic's key takes half a second to open each time)
        (cls.fake / "disks.json").write_text(json.dumps({"blockdevices": [system_disk(), usb()]}))
        r = subprocess.run([sys.executable, str(REPO / "homelab/bin/bromigos-lab"), "backups", "go-bag", "setup", "--no-copy"],
                           env=cls.environment(), capture_output=True, text=True, stdin=subprocess.DEVNULL)
        assert r.returncode == 0, r.stderr + r.stdout
        shutil.rmtree(cls.pristine)
        shutil.copytree(cls.root, cls.pristine, symlinks=True)
        cls.drive = cls.fake.parent / "drive"
        shutil.copytree(cls.fake / "media", cls.drive, symlinks=True)

    def setUp(self):
        super().setUp()
        shutil.copytree(self.drive, self.fake / "media", symlinks=True)

    def plugged_in(self, uuid=UUID):
        """What the unit runs when udev sees a USB filesystem (bromigos-server-backup-drive@.service)."""
        return self.server("backup", "plugged", "--uuid", uuid)

    def test_plugged_in_the_copy_runs_as_a_job_and_ends_safe_to_unplug(self):
        r = self.plugged_in()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        (job,) = self.jobs()
        self.assertEqual((job["kind"], job["state"], job["requested_by"]["via"]), ("backup.drive", "succeeded", "timer"))
        self.assertEqual(job["title"], "Copying the backup to the Go Bag drive")
        self.assertEqual(job["subject"], {"type": "drive", "id": UUID, "name": "CARRY"})
        self.assertEqual([(s["id"], s["label"], s["state"]) for s in job["steps"]],
                         [("drive", "Finding the Go Bag drive", "done"), ("copy", "Copying what changed", "done"),
                          ("check", "Checking what was written", "done"), ("unplug", "Making it safe to unplug", "done")])
        self.assertEqual(job["steps"][0]["detail"], 'Portable SSD (1.0 TB), labelled "CARRY"')
        self.assertRegex(job["steps"][1]["detail"], r"^\d+ files, [\d.]+ KB \([\d.]+ KB added to the drive\)$")
        self.assertRegex(job["result"]["summary"], r"^Safe to unplug\. \d+ files \([\d.]+ KB\) copied to the Go Bag drive\.$")
        self.assertEqual(job["pct"], 100)
        self.assertNotIn("sdb", json.dumps(job["command"]), "the job is told the filesystem, not a device name")
        # safe to unplug is true: it was unmounted, after the copy and the check, and nothing is mounted now
        self.assertEqual(self.mounted(), "")
        self.assertEqual([line.split()[0] for line in self.touched()], ["mount", "umount"])
        d = self.drives()[UUID]
        self.assertEqual((d["run"]["phase"], d["run"]["unmounted"], d["run_ok"]["snapshot"]), ("ok", True, d["run"]["snapshot"]))
        self.assertGreater(d["run"]["files"], 5)
        # and it is a backup the existing commands read
        got = self.doc("list", "--from", "go-bag")
        self.assertEqual((got["to"], [s["short_id"] for s in got["snapshots"]], got["snapshots"][0]["nightly"]),
                         ("the Go Bag drive", [d["run"]["snapshot"]], True))
        self.assertEqual(self.mounted(), "", "reading it unmounts it again")

    def test_another_drive_plugged_in_starts_nothing(self):
        r = self.plugged_in("AB12-CD34")
        self.assertEqual((r.returncode, r.stdout, self.jobs(), self.touched()), (0, "", [], []))

    def test_the_copy_job_takes_turns_and_may_be_stopped_or_started_again(self):
        """#110's activity: the copy job holds the lock backup-drive (two copies take turns), says
        stopping is safe except while it unmounts, and may be started again by `retry`."""
        self.assertEqual(self.plugged_in().returncode, 0)
        job = self.jobs()[-1]
        self.assertEqual(job["locks"], ["backup-drive"])
        log = (self.root / "var/lib/bromigos/activity/jobs" / (job["id"] + ".log")).read_text()
        self.assertIn("::cancel unsafe The Go Bag drive is being unmounted.", log)
        self.assertLess(log.index("::cancel unsafe"), log.index("::step unplug done"))
        cmd = D.job_command(UUID)
        self.assertEqual(cmd[cmd.index("--lock") + 1], "backup-drive")
        self.assertIn("--cancel-safe", cmd)
        self.assertIn("--retry-safe", cmd)

    def test_a_failed_copy_is_one_alert_the_jobs_own(self):
        """A failed copy raises one alert, activity.job's, and the next good copy clears it."""
        import bromigos_alerts as AL
        aenv = AL.Env(dict(self.env(), BROMIGOS_ALERTS_ROOT=str(self.root)))
        (self.fake / "backup-fails").write_text("")
        self.go("run", rc=1)
        job = self.jobs()[-1]
        self.assertEqual(job["state"], "failed")
        self.assertIn("retry", job["can"])
        doc = AL.run_pass(aenv, "system", checks={"backup.restic", "activity.job"})
        got = {a["id"]: a for a in doc["alerts"]}
        self.assertEqual(sorted(got), [f"activity.job:backup.drive:drive/{UUID}"])
        self.assertEqual(got[f"activity.job:backup.drive:drive/{UUID}"]["title"], "A job failed: Copying the backup to the Go Bag drive")
        self.assertEqual([(p["id"], p.get("raised_by")) for p in self.doc(rc=1)["health"]["problems"]], [("drive-failed", "activity.job")])
        (self.fake / "backup-fails").unlink()
        self.go("run", rc=0)
        self.assertEqual(AL.run_pass(aenv, "system", checks={"backup.restic", "activity.job"})["alerts"], [])

    def test_a_copy_waits_for_a_restore_that_reads_the_drive(self):
        """A restore from the drive holds its file lock: a copy started meanwhile waits for it,
        says so, and then copies. It is never skipped."""
        import fcntl
        held = self.root / "var/lib/bromigos/server/backup-drive.lock"
        held.parent.mkdir(parents=True, exist_ok=True)
        with open(held, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            p = subprocess.Popen([sys.executable, str(REPO / "homelab/bin/bromigos-lab"), "backups", "go-bag", "run"],
                                 env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
            self.procs.append(p)
            deadline = time.time() + 60
            while not any("Waiting for the command that is using the Go Bag drive" in (j.get("stage") or "") for j in self.jobs()):
                self.assertIsNone(p.poll(), "it ended instead of waiting")
                self.assertLess(time.time(), deadline)
                time.sleep(0.1)
            self.assertEqual(self.mounted(), "", "nothing is mounted while it waits")
        out, err = p.communicate(timeout=120)
        self.assertEqual(p.returncode, 0, err)
        self.assertIn("      Waiting for the command that is using the Go Bag drive (a setup, or a restore from it)", out)
        self.assertRegex(out, r"\nSafe to unplug\. \d+ files")
        self.assertEqual(self.drives()[UUID]["run_ok"]["phase"], "ok")

    def test_the_drive_is_found_again_under_another_device_name(self):
        self.plug(usb(name="sdf"), disk("sdb", "Someone's Stick", 32_000_000_000, children=[part("sdb1", "vfat", "AB12-CD34", 31_000_000_000)]))
        r = self.go("run", rc=0)
        self.assertIn("[1/4] Finding the Go Bag drive", r.stdout)
        self.assertIn("[4/4] Making it safe to unplug", r.stdout)
        self.assertRegex(r.stdout, r"\nSafe to unplug\. \d+ files \(.*\) copied to the Go Bag drive\.\n")
        self.assertEqual(self.jobs()[0]["requested_by"]["via"], "cli")
        self.assertIn(f"UUID={UUID} ", self.log())
        self.assertNotIn("AB12-CD34", "\n".join(self.touched()), "the other stick was never touched")
        self.assertTrue((self.media() / "bromigos-backup/box/snapshots").is_dir())

    def test_not_plugged_in(self):
        self.unplug()
        r = self.go("run", rc=1)
        self.assertIn("The Go Bag drive isn't plugged in. Plug it in: the copy starts by itself.", r.stderr)
        self.assertEqual((self.jobs(), self.touched()), ([], []))
        r = self.lab("list", "--from", "go-bag")
        self.assertEqual((r.returncode, r.stderr.strip()), (1, "The Go Bag drive isn't plugged in. Plug it in, then try again."))
        d = self.doc()["drives"][0]
        self.assertEqual((d["plugged_in"], d["last_good_copy"]), (False, None))
        self.assertIn('  Go Bag        Portable SSD, 1.0 TB, labelled "CARRY": not plugged in', self.lab().stdout)

    def test_a_copy_that_fails_says_why_and_still_unmounts(self):
        self.assertEqual(self.plugged_in().returncode, 0)
        good = self.drives()[UUID]["run_ok"]
        (self.fake / "backup-fails").write_text("")
        r = self.go("run", rc=1)
        self.assertIn("Unable to save snapshot: no space left on device. The Go Bag drive is unmounted: safe to unplug.", r.stderr)
        job = self.jobs()[-1]
        self.assertEqual((job["state"], job["error"]["step"]), ("failed", "copy"))
        self.assertIn("no space left on device", job["error"]["words"])
        self.assertEqual([s["state"] for s in job["steps"]], ["done", "failed", "todo", "todo"])
        self.assertEqual(self.mounted(), "", "a failed copy leaves the drive unmounted too")
        d = self.drives()[UUID]
        self.assertEqual((d["run"]["phase"], d["run"]["unmounted"], d["run_ok"]), ("failed", True, good), "the last good copy stays on record")
        # the status, the Server's line and the alert's problem all say it
        r = self.lab()
        self.assertEqual(r.returncode, 1)
        self.assertIn("The last copy to your Go Bag drive failed (just now): unable to save snapshot: no space left on device.",
                      r.stdout.splitlines()[0])
        self.assertIn("  Last good one just now", r.stdout)
        doc = self.doc(rc=1)
        self.assertEqual([p["id"] for p in doc["health"]["problems"]], ["drive-failed"])
        self.assertIn("The last copy to your Go Bag drive failed", self.server("status").stdout)
        self.assertEqual(self.go(rc=1).stdout.splitlines()[0], r.stdout.splitlines()[0].split("tonight. ")[1])

    def test_a_copy_that_does_not_read_back_is_not_a_good_copy(self):
        """Every copy is checked on the drive before it counts: restic check, with data read back."""
        self.assertEqual(self.plugged_in().returncode, 0)
        self.assertIn("restic check --read-data-subset=2G", self.log())
        good = self.drives()[UUID]["run_ok"]
        (self.fake / "check-fails").write_text("")
        r = self.go("run", rc=1)
        self.assertIn("What was written doesn't read back: repository contains errors. The drive may be failing. "
                      "The Go Bag drive is unmounted: safe to unplug.", r.stderr)
        job = self.jobs()[-1]
        self.assertEqual((job["state"], job["error"]["step"]), ("failed", "check"))
        self.assertEqual([s["state"] for s in job["steps"]], ["done", "done", "failed", "todo"])
        d = self.drives()[UUID]
        self.assertEqual((d["run"]["phase"], d["run_ok"]), ("failed", good))
        self.assertEqual(self.mounted(), "")

    def test_a_drive_that_cannot_be_unmounted_is_never_called_safe(self):
        (self.fake / "umount-fails").write_text("")
        r = self.go("run", rc=1)
        self.assertNotIn("Safe to unplug", r.stdout + r.stderr)
        self.assertIn("The copy is good, but the Go Bag drive couldn't be unmounted (umount: ", r.stderr)
        self.assertIn(f"Don't unplug it yet: close what uses it, then `sudo umount /run/bromigos/backup-drive/{UUID}`", r.stderr)
        job = self.jobs()[-1]
        self.assertEqual((job["state"], job["error"]["step"]), ("failed", "unplug"))
        d = self.drives()[UUID]
        self.assertEqual((d["run"]["phase"], d["run"]["unmounted"], d["run_ok"]["unmounted"]), ("ok", False, False),
                         "the copy itself is good, and is kept as one")

    def test_a_drive_someone_mounted_is_used_where_it_is_and_left_there(self):
        mine = usb()
        where = self.root / "mnt/usb"
        where.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(self.media(), where)
        mine["children"][0]["mountpoints"] = [str(where)]
        self.plug(mine)
        r = self.go("run", rc=0)
        self.assertNotIn("Safe to unplug", r.stdout)
        self.assertIn("copied to the Go Bag drive. It is still mounted at /mnt/usb, where it was before: unmount it before you unplug it.",
                      r.stdout)
        self.assertEqual([line.split()[0] for line in self.touched()], [], "it was neither mounted nor unmounted here")
        self.assertIn("sync -f", self.log())
        self.assertEqual([s["state"] for s in self.jobs()[-1]["steps"]], ["done", "done", "done", "skipped"])
        self.assertIsNone(self.drives()[UUID]["run"]["unmounted"])

    def test_the_status_and_its_json(self):
        self.assertEqual(self.plugged_in().returncode, 0)
        doc = self.doc()
        self.assertEqual(doc["health"]["verdict"], "No backup yet: the first one runs tonight. Go Bag: copied just now.")
        (d,) = doc["drives"]
        self.assertEqual({k: d[k] for k in ("name", "uuid", "label", "model", "fstype", "plugged_in", "running", "stale", "remind_days")},
                         {"name": "Go Bag", "uuid": UUID, "label": "CARRY", "model": "Portable SSD", "fstype": "exfat",
                          "plugged_in": True, "running": False, "stale": False, "remind_days": 30})
        self.assertEqual((d["last_good_copy"]["phase"], d["last_good_copy"]["age_s"] < 120, d["last_copy"]["snapshot"]),
                         ("ok", True, d["last_good_copy"]["snapshot"]))
        self.assertNotIn("/dev/sd", json.dumps(doc))
        out = self.lab().stdout
        self.assertIn('  Go Bag        Portable SSD, 1.0 TB, labelled "CARRY": plugged in', out)
        self.assertRegex(out, r"  Last copy     worked, just now \(\d{4}-\d\d-\d\d \d\d:\d\d, snapshot [0-9a-f]{8}, \d+ files, [\d.]+ KB\)")
        # bromigos server: the same sentence on its Backups line, and the drive in its --json
        self.assertIn("Go Bag: copied just now. To /mnt/backup.", self.server("status").stdout)
        self.assertEqual(json.loads(self.server("status", "--json").stdout)["backup"]["drives"][0]["uuid"], UUID)
        # the Go Bag's own status; unplugged, it says so
        g = json.loads(self.go("--json", rc=0).stdout)
        self.assertEqual((g["ok"], g["set_up"], g["verdict"], g["drives"][0]["plugged_in"]), (True, True, "Go Bag: copied just now.", True))
        self.unplug()
        out = self.go(rc=0).stdout
        self.assertIn("not plugged in", out)
        self.assertIn("  Reminder      after 30 days without a good copy ([backup] drive_remind_days)", out)
        # the reminder: the setting is read, and the stale drive needs you (exit 1)
        self.put("etc/bromigos/server.toml", '[backup]\nto = "/mnt/backup"\npaths = ["/etc", "/home", "/srv"]\ndrive_remind_days = 7\n')
        st = self.state()
        st["drives"][UUID]["run_ok"]["ts"] -= 9 * DAY
        (self.root / "var/lib/bromigos/server/backup.json").write_text(json.dumps(st))
        r = self.go(rc=1)
        self.assertEqual(r.stdout.splitlines()[0], "Your Go Bag drive hasn't been updated in 9 days. Plug it in.")
        self.assertEqual([p["id"] for p in self.doc(rc=1)["health"]["problems"]], ["drive-stale"])

    def test_restore_from_the_drive_with_the_existing_commands(self):
        self.assertEqual(self.plugged_in().returncode, 0)
        snap = self.drives()[UUID]["run_ok"]["snapshot"]
        (self.root / "etc/app/app.conf").write_text("port = 9999  # a bad edit\n")
        out = self.lab("list", "--from", "go-bag")
        self.assertIn("1 backup on the Go Bag drive, newest first:", out.stdout)
        self.assertIn("bromigos lab backups restore ID [PATH…] --from go-bag", out.stdout)
        self.assertIn("The Go Bag drive is unmounted: safe to unplug.", out.stderr)
        self.assertEqual([e["name"] for e in self.doc("show", "--from", "go-bag", snap, "/etc/app")["entries"]], ["app.conf"])
        dest = Path(self.tmp.name) / "back"
        got = self.doc("restore", "--from", "go-bag", "/etc/app", "--to", str(dest))
        self.assertEqual((got["state"], got["files"], got["verified"], got["snapshot"]["short_id"]), ("done", 1, True, snap))
        self.assertEqual((dest / "etc/app/app.conf").read_text(), "port = 8080\n", "the file as it was when the drive was plugged in")
        # in place: its hints name the drive too
        look = self.lab("restore", "--from", "go-bag", "/etc/app", "--in-place")
        self.assertIn(f"To do it: bromigos lab backups restore {snap} /etc/app --in-place --apply --from go-bag", look.stdout)
        # a test restore from the drive is the drive's record, never the nightly's
        t = self.doc("test", "--from", "go-bag")
        self.assertEqual(t["state"], "passed")
        st = self.state()
        self.assertEqual(st["drives"][UUID]["test_ok"]["phase"], "ok")
        self.assertNotIn("test", st)
        self.assertNotIn("test_ok", st)
        self.assertEqual(self.doc()["drives"][0]["last_test"]["phase"], "ok")
        self.assertEqual(self.mounted(), "", "each command unmounts the drive when it is done")
        self.assertEqual(self.touched().count(f"umount {self.root}/run/bromigos/backup-drive/{UUID}"),
                         len([line for line in self.touched() if line.startswith("mount ")]))

    def test_the_go_bag_as_the_only_backup(self):
        """A server with no nightly destination: the Go Bag is its backup, and the restore
        commands read it without being told to."""
        self.put("etc/bromigos/server.toml", '[backup]\npaths = ["/etc", "/home", "/srv"]\n')
        self.assertEqual(self.plugged_in().returncode, 0)
        r = self.lab()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "No nightly backup is set up: the Go Bag drive is this server's only backup. "
                         "Go Bag: copied just now.")
        self.assertIn("  Last copy     worked, just now", r.stdout)
        self.assertEqual(len(self.doc("list")["snapshots"]), 1)
        self.assertIn("No nightly backup is set up: the Go Bag drive is this server's only backup.", self.server("status").stdout)

    def test_setup_ends_with_the_first_copy(self):
        self.go("forget", "--yes", rc=0)
        r = self.go("setup", rc=0)
        self.assertIn("is now this server's Go Bag: the backup already on it is kept.", r.stdout)
        self.assertIn("The first copy:\n[1/4] Finding the Go Bag drive", r.stdout)
        self.assertRegex(r.stdout, r"\nSafe to unplug\. \d+ files \(.*\) copied to the Go Bag drive\.\n")
        self.assertIn("From now on, plug it in and the copy starts by itself.", r.stdout)
        self.assertEqual((len(self.jobs()), self.jobs()[0]["state"], self.mounted()), (1, "succeeded", ""))
        self.assertEqual(self.drives()[UUID]["run_ok"]["phase"], "ok")


if __name__ == "__main__":
    unittest.main()
