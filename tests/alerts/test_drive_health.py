"""Drive health with history (lib/bromigos_drives.py, docs/storage.md "Drive health"), on a
stand-in machine (fake.py) with a clock the tests move: each verdict, the alert that follows
it, a drive known by its model and serial whatever its device name, drives that go away, come
back or are replaced, the history's bounds, and `bromigos storage health`.

The drives are files in tests/alerts/drives/, shaped as `smartctl --json` and
`nvme smart-log -o json` print them, with made-up serial numbers. No real smartctl, nvme or
lsblk runs, and nothing on this machine is read or changed."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["TZ"] = "UTC"        # the dates in the texts, the same everywhere
time.tzset()

import fake  # noqa: E402
from fake import FakeMachine, NOW  # noqa: E402

import bromigos_alerts as A  # noqa: E402
import bromigos_drives as D  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "drives"
STORAGE = fake.REPO / "bin/bromigos-storage"
DAY = D.DAY
HOUR = 3600_000

STUBS = {
    "lsblk": '#!/bin/sh\n[ -f "$FAKE/lsblk.json" ] || exit 1\ncat "$FAKE/lsblk.json"\n',
    "nvme": '#!/bin/sh\necho "nvme $*" >> "$FAKE/log"\n[ "$1" = "smart-log" ] || exit 1\n'
            'f="$FAKE/nvme/$(basename "$2").json"\n[ -f "$f" ] || exit 1\ncat "$f"\n',
}


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def nvme(serial="FAKE0NVME000001", firmware=None, passed=True, tests=None, **log):
    """An NVMe drive as smartctl prints it; `log` changes its health log's fields."""
    doc = fixture("smartctl-nvme.json")
    doc["serial_number"] = serial
    if firmware:
        doc["firmware_version"] = firmware
    doc["smart_status"]["passed"] = passed
    assert not set(log) - set(doc["nvme_smart_health_information_log"]), log
    doc["nvme_smart_health_information_log"].update(log)
    if tests is not None:
        doc["nvme_self_test_log"]["table"] = [
            {"self_test_code": {"value": 1, "string": "Short"}, "self_test_result": {"value": code, "string": words},
             "power_on_hours": 9100 - i} for i, (code, words) in enumerate(tests)]
    return doc


def sata(serial="FAKE0SATA000002", passed=True, failing=None, tests=None, **raw):
    """A SATA drive as smartctl prints it; `raw` sets attributes' raw values by name."""
    doc = fixture("smartctl-sata.json")
    doc["serial_number"] = serial
    doc["smart_status"]["passed"] = passed
    rows = {r["name"]: r for r in doc["ata_smart_attributes"]["table"]}
    for name, value in raw.items():
        rows[name]["raw"] = {"value": value, "string": str(value)}
    for name, when in (failing or {}).items():
        rows[name]["when_failed"] = when
    if tests is not None:
        doc["ata_smart_self_test_log"]["standard"]["table"] = [
            {"type": {"value": 1, "string": "Short offline"}, "status": dict({"value": code, "string": words},
                                                                              **({"passed": code == 0} if code >> 4 != 15 else {})),
             "lifetime_hours": 21490 - i} for i, (code, words) in enumerate(tests)]
    return doc


def key(doc):
    return D.drive_key(doc.get("model_name") or "A drive", doc.get("serial_number") or "", "x")[0]


def aid(doc):
    return "disk.smart:" + key(doc)


class Drives(unittest.TestCase):
    def setUp(self):
        self.m = FakeMachine()
        for name, text in STUBS.items():
            p = self.m.bin / name
            p.write_text(text)
            p.chmod(0o755)
        for p in (self.m.fake / "smart").iterdir():
            p.unlink()
        self.devices = {}
        self._scan()

    def tearDown(self):
        self.m.close()

    def _scan(self):
        # as a plain `smartctl --scan -j` lists them: every sdX is "scsi"
        self.m.write("smart/scan.json", {"devices": [
            {"name": f"/dev/{n}", "info_name": f"/dev/{n}", "type": "nvme" if n.startswith("nvme") else "scsi",
             "protocol": "NVMe" if n.startswith("nvme") else "SCSI"} for n in sorted(self.devices)]})

    def plug(self, name, doc, rc=0):
        """A drive at a device name (or the same drive with new numbers)."""
        self.devices[name] = doc
        self.m.write(f"smart/{name}.json", doc)
        self.m.write(f"smart/{name}.json.rc", str(rc))
        self._scan()

    def unplug(self, name):
        del self.devices[name]
        (self.m.fake / f"smart/{name}.json").unlink()
        self._scan()

    def check(self, days=0, hours=0):
        """Move the clock, run the drive check as the system pass does, and give its alerts by id."""
        self.m.now += days * DAY + hours * HOUR
        doc = A.run_pass(self.m.env(), "system", checks={"disk.smart"})
        row = [c for c in doc["checks"] if c["check"] == "disk.smart"][0]
        self.assertEqual((row["state"], row["error"]), ("ran", None))
        return {a["id"]: a for a in doc["alerts"] if a["check"] == "disk.smart"}

    def daily(self, n):
        """n days, one check a day; the last day's alerts."""
        got = {}
        for _ in range(n):
            got = self.check(days=1)
        return got

    def health(self):
        return D.report(self.m.env(), samples=True)

    def drive(self, word):
        return D.find(self.health(), word)

    def cli(self, *args):
        e = dict(self.m.env().environ, TZ="UTC")
        return subprocess.run([sys.executable, str(STORAGE), "health", *args], env=e, capture_output=True, text=True)


class Verdicts(Drives):
    def test_healthy_drives_raise_nothing(self):
        self.plug("nvme0", nvme())
        self.plug("sda", sata())
        self.assertEqual(self.check(), {})
        a, b = self.drive("nvme0"), self.drive("sda")
        self.assertEqual((a["verdict"], a["words"], a["alert"]), ("healthy", "healthy", None))
        self.assertEqual(a["summary"], "no errors, 9,120 hours on, 41 °C")
        self.assertEqual(b["summary"], "no errors, 21,503 hours on, 34 °C")
        # every value the docs name is read
        self.assertEqual(a["readings"], {
            "passed": True, "critical_warning": 0, "media_errors": 0, "spare": 100, "spare_threshold": 10,
            "percent_used": 3, "unsafe_shutdowns": 112, "temperature": 41, "power_on_hours": 9120,
            "self_test": {"type": "Short", "passed": True, "status": "Completed without error", "hours": 9100}})
        self.assertEqual(b["readings"], {
            "passed": True, "reallocated": 0, "pending": 0, "uncorrectable": 0, "crc_errors": 0, "temperature": 34,
            "power_on_hours": 21503,
            "self_test": {"type": "Short offline", "passed": True, "status": "Completed without error", "hours": 21490}})
        # smartctl finds the SATA drive itself: the scan's "scsi" isn't passed on, "nvme" is
        log = (self.m.fake / "log").read_text()
        self.assertIn("smartctl -j -H -A -i -l selftest /dev/sda\n", log)
        self.assertIn("smartctl -j -H -A -i -l selftest -d nvme /dev/nvme0\n", log)

    def test_old_errors_alarm_until_the_history_proves_them_stable_then_go_quiet_once(self):
        """An install that already had a count above zero: it keeps its alarm while nothing
        says the count is old, and after QUIET_DAYS without growth it is one quiet line."""
        drive = sata(Reallocated_Sector_Ct=12)
        self.plug("sda", drive)
        first = self.check()[aid(drive)]
        self.assertEqual(first["severity"], "needs_you")
        self.assertEqual(first["title"], "A drive has errors: WDC WD40EFRX-68N32N0 (sda)")
        self.assertIn(f"12 reallocated sectors, first seen {D.day(NOW)} when this drive's history began", first["detail"])
        self.assertIn(f"If nothing changes until {D.day(NOW + 30 * DAY)}, this alarm goes quiet", first["detail"])
        self.assertEqual(first["fix"]["commands"][0], "bromigos storage health sda")
        d = self.drive("sda")
        self.assertEqual((d["verdict"], d["words"], d["quiet_on"]), ("checking", "has errors, still checking", NOW + 30 * DAY))
        # 29 days on: still not proven
        self.assertEqual(self.daily(29)[aid(drive)]["severity"], "needs_you")
        # the 30th day: quiet, and it says so
        quiet = self.check(days=1)[aid(drive)]
        self.assertEqual(quiet["severity"], "info")
        self.assertEqual(quiet["title"], "A drive to keep an eye on: WDC WD40EFRX-68N32N0 (sda)")
        self.assertTrue(quiet["detail"].startswith("The alarm for this drive is off. "), quiet["detail"])
        self.assertIn(f"12 reallocated sectors, unchanged since at least {D.day(NOW)}", quiet["detail"])
        self.assertIsNone(quiet["fix"])
        self.assertEqual(quiet["since"], first["since"])
        d = self.drive("sda")
        self.assertEqual((d["verdict"], d["alert"]), ("watch", "info"))
        self.assertEqual(d["events"][-1]["kind"], "verdict")
        self.assertEqual((d["events"][-1]["from"], d["events"][-1]["to"]), ("checking", "watch"))
        # an info line never counts as something that needs you
        self.assertEqual([a["severity"] for a in A.read_merged(self.m.env())["alerts"]], ["info"])
        # said once: a day later the line no longer announces it
        later = self.check(days=1, hours=1)[aid(drive)]
        self.assertEqual(later["severity"], "info")
        self.assertFalse(later["detail"].startswith("The alarm"), later["detail"])
        # and it stays quiet
        self.assertEqual(self.daily(60)[aid(drive)]["severity"], "info")

    def test_a_count_that_rises_is_getting_worse_and_says_how_fast(self):
        self.plug("sda", sata())
        self.assertEqual(self.check(), {})
        self.daily(5)
        drive = sata(Reallocated_Sector_Ct=5)
        self.plug("sda", drive)
        a = self.check(days=1)[aid(drive)]
        self.assertEqual(a["severity"], "needs_you")
        self.assertEqual(a["title"], "A drive is getting worse: WDC WD40EFRX-68N32N0 (sda)")
        self.assertIn("5 reallocated sectors appeared in the last day", a["detail"])
        self.assertIn("If the count stops rising for 30 days, this alarm goes quiet", a["detail"])
        self.plug("sda", sata(Reallocated_Sector_Ct=8, Current_Pending_Sector=2))
        a = self.check(days=1)[aid(drive)]
        self.assertIn("8 reallocated sectors appeared in the last 2 days", a["detail"])
        self.assertIn("2 sectors it can't read appeared in the last day", a["detail"])
        d = self.drive("sda")
        self.assertEqual((d["verdict"], d["words"]), ("worse", "getting worse"))
        rise = [r for r in d["reasons"] if r.get("counter") == "reallocated"][0]
        self.assertEqual((rise["value"], rise["rise"], rise["days"]), (8, 8, 2))

    def test_the_alarm_goes_quiet_and_comes_back(self):
        drive = sata(Reallocated_Sector_Ct=12)
        self.plug("sda", drive)
        self.check()
        self.assertEqual(self.daily(30)[aid(drive)]["severity"], "info")
        self.daily(40)
        # it rises again: the alarm is back, and says from what to what
        self.plug("sda", sata(Reallocated_Sector_Ct=20))
        back = self.check(days=1)[aid(drive)]
        self.assertEqual(back["severity"], "needs_you")
        self.assertEqual(back["title"], "A drive is getting worse: WDC WD40EFRX-68N32N0 (sda)")
        self.assertIn("reallocated sectors rose from 12 to 20 in the last day", back["detail"])
        self.assertEqual(self.daily(29)[aid(drive)]["severity"], "needs_you")
        # and quiet again once it has held for 30 days, counted from the rise
        again = self.check(days=1)[aid(drive)]
        self.assertEqual(again["severity"], "info")
        self.assertTrue(again["detail"].startswith("The alarm for this drive is off. "))
        self.assertIn(f"20 reallocated sectors, unchanged since {D.day(NOW + 71 * DAY)}", again["detail"])
        kinds = [(e.get("from"), e.get("to")) for e in self.drive("sda")["events"] if e["kind"] == "verdict"]
        self.assertEqual(kinds, [("checking", "watch"), ("watch", "worse"), ("worse", "watch")])

    def test_a_count_that_keeps_rising_means_replace_soon(self):
        self.plug("sda", sata())
        self.check()
        drive = sata()
        for n, count in enumerate((3, 9, 21), 1):
            self.plug("sda", sata(Offline_Uncorrectable=count))
            a = self.check(days=2)[aid(drive)]
            self.assertEqual(a["severity"], "needs_you")
            self.assertEqual(self.drive("sda")["verdict"], "worse" if n < D.SUSTAINED_DAYS else "replace", n)
        self.assertEqual(a["title"], "Replace this drive soon: WDC WD40EFRX-68N32N0 (sda)")
        self.assertIn("21 uncorrectable sectors appeared in the last 6 days, on 3 separate days", a["detail"])
        self.assertIn("back up what's on it and replace it soon", a["detail"])
        # many rises on one day are one day
        self.plug("sdb", sata(serial="FAKE0SATA000009"))
        self.check()
        for count in (1, 2, 3, 4, 5):
            self.plug("sdb", sata(serial="FAKE0SATA000009", Current_Pending_Sector=count))
            self.check(hours=1)
        self.assertEqual(self.drive("sdb")["verdict"], "worse")

    def test_what_the_drive_says_itself_means_replace_soon(self):
        cases = [
            # (drive, exit status, severity, title starts, the detail says)
            (nvme(available_spare=8), 0, "critical", "A drive is failing",
             "its spare space is down to 8%, under the drive's own threshold of 10%"),
            (nvme(available_spare=8, critical_warning=0x01), 0, "critical", "A drive is failing",
             "its spare space is down to 8%, under the drive's own threshold of 10%"),
            (nvme(critical_warning=0x01), 0, "critical", "A drive is failing",
             "its spare space fell under the drive's own threshold"),
            (nvme(critical_warning=0x04), 0, "critical", "A drive is failing", "it says its reliability is degraded"),
            (nvme(critical_warning=0x08), 0, "critical", "A drive is failing", "it has gone read-only"),
            (nvme(passed=False), 0, "critical", "A drive is failing", "its own health check says FAILED"),
            (sata(), 8, "critical", "A drive is failing", "its own health check says FAILED"),
            (sata(failing={"Reallocated_Sector_Ct": "now"}), 16, "critical", "A drive is failing",
             "Reallocated_Sector_Ct is past the drive's own failure threshold"),
            (sata(failing={"Power_On_Hours": "now"}), 0, "needs_you", "Replace this drive soon",
             "Power_On_Hours is past the drive's own wear threshold"),
            (sata(tests=[(0x71, "Completed: read failure"), (0, "Completed without error")]), 128, "needs_you",
             "Replace this drive soon", "its last self-test failed (Completed: read failure)"),
            (nvme(tests=[(7, "Completed: failed segments")]), 0, "needs_you", "Replace this drive soon",
             "its last self-test failed (Completed: failed segments)"),
            (nvme(percentage_used=104), 0, "needs_you", "Replace this drive soon", "104% of its rated life is used"),
        ]
        for i, (doc, rc, severity, title, says) in enumerate(cases):
            doc["serial_number"] = f"FAKE0CASE{i:06d}"
            name = "nvme0" if "nvme_smart_health_information_log" in doc else "sda"
            self.plug(name, doc, rc)
            a = self.check()[aid(doc)]
            self.assertEqual(a["severity"], severity, says)
            self.assertTrue(a["title"].startswith(title + ": "), a["title"])
            self.assertIn(says, a["detail"])
            d = self.drive(name)
            self.assertEqual((d["verdict"], d["words"]), ("replace", "replace soon"), says)
            self.assertIn("Copy your files off it now" if severity == "critical" else "replace it soon", a["detail"])
            self.assertEqual(a["detail"].count("spare space"), 1 if "spare" in says else 0, a["detail"])   # said once
            self.unplug(name)

    def test_the_newest_finished_self_test_counts(self):
        # an old failure, then a pass: the pass counts. One still running, or aborted, is no result
        doc = sata(tests=[(0xf9, "Self-test routine in progress"), (0x10, "Aborted by host"),
                          (0, "Completed without error"), (0x71, "Completed: read failure")])
        self.plug("sda", doc)
        self.assertEqual(self.check(), {})
        self.assertEqual(self.drive("sda")["readings"]["self_test"]["hours"], 21488)
        doc = nvme(tests=[(1, "Aborted: Self-test command"), (0, "Completed without error"), (6, "Completed: failed")])
        self.plug("nvme0", doc)
        self.assertEqual(self.check(), {})

    def test_wear_is_a_quiet_line_until_the_makers_own_limit(self):
        drive = nvme(percentage_used=93)
        self.plug("nvme0", drive)
        a = self.check()[aid(drive)]
        self.assertEqual((a["severity"], self.drive("nvme0")["verdict"]), ("info", "watch"))
        self.assertIn("93% of its rated life is used", a["detail"])
        # an attribute that was past its threshold once and isn't now: quiet too
        drive = sata(failing={"Temperature_Celsius": "past"})
        self.plug("sda", drive, rc=32)
        a = self.check()[aid(drive)]
        self.assertEqual(a["severity"], "info")
        self.assertIn("Temperature_Celsius was past its threshold at some point (it isn't now)", a["detail"])
        # spare that has dropped but isn't under the drive's own threshold is not judged
        for spare in (61, 10):
            self.plug("nvme1", nvme(serial="FAKE0NVME000008", available_spare=spare))
            self.check()
            self.assertEqual(self.drive("nvme1")["verdict"], "healthy", spare)

    def test_a_drive_that_is_too_hot(self):
        drive = nvme(critical_warning=0x02, temperature=86)
        self.plug("nvme0", drive)
        a = self.check()[aid(drive)]
        self.assertEqual((a["severity"], a["title"]), ("needs_you", "A drive is too hot: Samsung SSD 980 PRO 2TB (nvme0)"))
        self.assertIn("it says it's over its temperature limit (86 °C)", a["detail"])
        d = self.drive("nvme0")
        self.assertEqual((d["verdict"], d["summary"]), ("healthy", "no errors, 9,120 hours on, 86 °C, but too hot"))
        self.plug("nvme0", nvme())
        self.assertEqual(self.check(hours=1), {})

    def test_a_drive_that_does_not_report_cannot_be_told(self):
        self.m.write("lsblk.json", fixture("lsblk.json"))
        self.plug("nvme0", nvme())
        self.plug("sda", sata())
        self.plug("sdb", fixture("smartctl-virtual.json"), rc=4)       # a VM's disk, says it has no SMART
        self.plug("sdc", fixture("smartctl-usb-bridge.json"), rc=1)    # behind a USB adapter
        self.assertEqual(self.check(), {})                             # never an alert, never a guess
        got = {d["device"]: d for d in self.health()["drives"]}
        # lsblk's nvme0n1 is smartctl's nvme0; zram and the DVD drive aren't drives
        self.assertEqual(sorted(got), ["nvme0", "sda", "sdb", "sdc", "vda"])
        self.assertEqual((got["nvme0"]["verdict"], got["sda"]["verdict"]), ("healthy", "healthy"))
        for name, why in (("sdb", "it's a virtual disk: the real drive's health is on the machine that hosts it"),
                          ("sdc", "it's connected through a USB adapter that doesn't pass the drive's health records on"),
                          ("vda", "it's a virtual disk: the real drive's health is on the machine that hosts it")):
            d = got[name]
            self.assertEqual((d["verdict"], d["words"], d["alert"], d["reports"]), ("unknown", "cannot tell", None, False))
            self.assertEqual(d["summary"], why)
            self.assertEqual(d["readings"], {})
        self.assertEqual(got["sdc"]["model"], "Extreme 55AE")           # named from lsblk
        self.assertEqual(got["sdb"]["model"], "QEMU QEMU HARDDISK")
        # without lsblk, one that doesn't answer still isn't guessed at
        (self.m.bin / "lsblk").unlink()
        self.unplug("sdb")
        self.plug("sdd", fixture("smartctl-usb-bridge.json"), rc=1)
        self.assertEqual(self.check(hours=1), {})
        d = self.drive("sdd")
        self.assertEqual(d["verdict"], "unknown")
        self.assertIn("it didn't answer when asked for its health records (/dev/sdc: Unknown USB bridge", d["summary"])

    def test_nonsense_from_a_tool_never_breaks_the_check(self):
        odd = nvme()
        odd["nvme_smart_health_information_log"].update(media_errors="many", available_spare=[], temperature=None,
                                                        critical_warning={"value": 4}, unsafe_shutdowns=-3)
        odd["nvme_self_test_log"] = {"table": [7, None, {"self_test_result": "failed"}]}
        odd["smart_status"] = ["passed"]
        odd["power_on_time"] = "long"
        self.plug("nvme0", odd)
        worse = sata()
        worse["ata_smart_attributes"]["table"] = [None, 5, {"id": "five", "name": ["x"], "raw": 3},
                                                  {"id": 5, "name": "Reallocated_Sector_Ct", "raw": {"value": "2"}}]
        worse["ata_smart_self_test_log"] = {"standard": {"table": "none"}}
        self.plug("sda", worse)
        self.plug("sdb", ["not", "a", "document"])
        got = self.check()                         # check() asserts the check ran, not "the check broke"
        self.assertEqual(got[aid(worse)]["severity"], "needs_you")
        self.assertEqual(self.drive("sda")["readings"]["reallocated"], 2)
        self.assertEqual(self.drive("nvme0")["readings"], {"critical_warning": 0, "percent_used": 3, "power_on_hours": 9120,
                                                           "spare_threshold": 10, "temperature": 41})
        self.assertEqual(self.drive("sdb")["verdict"], "unknown")
        # a history record that isn't one is dropped, and that drive starts again
        path = self.m.root / "var/lib/bromigos/drives/history.json"
        doc = json.loads(path.read_text())
        doc["drives"][key(worse)] = "gone wrong"
        path.write_text(json.dumps(doc))
        self.assertEqual(self.check(days=1)[aid(worse)]["severity"], "needs_you")
        self.assertEqual(self.drive("sda")["first_seen"], NOW + DAY)
        self.assertEqual(self.drive("nvme0")["first_seen"], NOW)

    def test_a_drive_that_stops_answering_keeps_its_alarm(self):
        drive = nvme(critical_warning=0x04)
        self.plug("nvme0", drive)
        self.assertEqual(self.check()[aid(drive)]["severity"], "critical")
        # dying drives stop answering: smartctl can't open it, so it can't even say who it is
        silent = {"smartctl": {"exit_status": 2, "messages": [
            {"string": "Smartctl open device: /dev/nvme0 failed: No such device", "severity": "error"}]}}
        self.plug("nvme0", silent, rc=2)
        a = self.check(days=2)[aid(drive)]
        self.assertEqual((a["severity"], a["title"]), ("critical", "A drive is failing: Samsung SSD 980 PRO 2TB (nvme0)"))
        self.assertIn(f"It hasn't answered since {D.day(NOW + 2 * DAY)}: this is its last reading.", a["detail"])
        d = self.drive("nvme0")
        self.assertEqual((d["verdict"], d["silent_since"], d["present"]), ("replace", NOW + 2 * DAY, True))
        self.assertEqual(len(self.health()["drives"]), 1)             # not a second, unknown drive
        self.assertIn("it hasn't answered since", D.plain(self.health(), self.m.now))
        # still silent the next day, and lsblk still naming it: the same
        self.m.write("lsblk.json", fixture("lsblk.json"))
        self.assertEqual(self.check(days=1)[aid(drive)]["severity"], "critical")
        self.assertEqual(self.drive("nvme0")["silent_since"], NOW + 2 * DAY)
        # it answers again, and well: the alarm ends
        self.plug("nvme0", nvme())
        self.assertEqual(self.check(days=1), {})
        self.assertIsNone(self.drive("nvme0")["silent_since"])

    def test_silence_proves_nothing(self):
        """A drive with errors that stops answering isn't "stable" after 30 days of saying nothing."""
        drive = sata(Reallocated_Sector_Ct=3)
        self.plug("sda", drive)
        self.check()
        self.daily(5)
        self.plug("sda", {"smartctl": {"exit_status": 2}}, rc=2)
        a = self.daily(40)[aid(drive)]
        self.assertEqual((a["severity"], a["title"]), ("needs_you", "A drive has errors: WDC WD40EFRX-68N32N0 (sda)"))
        self.assertEqual(self.drive("sda")["verdict"], "checking")
        # it answers again with the same count: now the history does prove it
        self.plug("sda", drive)
        self.assertEqual(self.check(days=1)[aid(drive)]["severity"], "info")

    def test_another_drive_that_does_not_answer_is_not_the_one_that_was_there(self):
        old = sata(Reallocated_Sector_Ct=3)
        self.plug("sda", old)
        self.assertEqual(self.check()[aid(old)]["severity"], "needs_you")
        # the slot now holds a drive in a USB case: lsblk gives another serial number
        self.m.write("lsblk.json", {"blockdevices": [
            {"name": "sda", "type": "disk", "model": "Extreme 55AE", "serial": "FAKE0USB0000003", "tran": "usb"}]})
        self.plug("sda", fixture("smartctl-usb-bridge.json"), rc=1)
        self.assertEqual(self.check(days=1), {})
        got = {d["key"]: d for d in self.health()["drives"]}
        self.assertEqual((got[key(old)]["present"], got[key(old)]["silent_since"]), (False, None))
        new = [d for d in got.values() if d["present"]][0]
        self.assertEqual((new["model"], new["verdict"]), ("Extreme 55AE", "unknown"))


class FirmwareBug(Drives):
    """The real case: an NVMe drive whose media error count jumped to tens of thousands because
    of a firmware bug, then stopped once the firmware was updated, its spare still over the
    drive's own threshold. After the quiet period that is "watch", not a drive wearing out."""

    def test_the_count_jumps_then_stops_after_a_firmware_update(self):
        self.plug("nvme0", nvme(firmware="3B2QGXA7"))
        self.assertEqual(self.check(), {})
        self.daily(10)
        drive = nvme()
        # the bug: tens of thousands of media errors over two days, and some spare used
        self.plug("nvme0", nvme(firmware="3B2QGXA7", media_errors=23110, available_spare=97))
        a = self.check(days=1)[aid(drive)]
        self.assertEqual((a["severity"], a["title"]), ("needs_you", "A drive is getting worse: Samsung SSD 980 PRO 2TB (nvme0)"))
        self.assertIn("23,110 media errors appeared in the last day", a["detail"])
        self.assertIn("A firmware fault can count errors like this too: look for an update for this model.", a["detail"])
        self.plug("nvme0", nvme(firmware="3B2QGXA7", media_errors=41870, available_spare=94))
        a = self.check(days=1)[aid(drive)]
        self.assertIn("41,870 media errors appeared in the last 2 days", a["detail"])
        self.assertEqual(self.drive("nvme0")["verdict"], "worse")
        # the firmware is updated: the count stops, the spare stays over the threshold of 10
        self.plug("nvme0", nvme(firmware="5B2QGXA7", media_errors=41870, available_spare=94))
        self.assertEqual(self.daily(29)[aid(drive)]["severity"], "needs_you")
        quiet = self.check(days=1)[aid(drive)]
        self.assertEqual((quiet["severity"], quiet["title"]), ("info", "A drive to keep an eye on: Samsung SSD 980 PRO 2TB (nvme0)"))
        self.assertTrue(quiet["detail"].startswith("The alarm for this drive is off. "))
        self.assertIn(f"41,870 media errors, unchanged since {D.day(NOW + 12 * DAY)}", quiet["detail"])
        d = self.drive("nvme0")
        self.assertEqual((d["verdict"], d["words"], d["firmware"]), ("watch", "watch", "5B2QGXA7"))
        self.assertIn({"t": NOW + 13 * DAY, "kind": "firmware", "from": "3B2QGXA7", "to": "5B2QGXA7"}, d["events"])
        self.assertNotIn("wearing out", json.dumps(self.health()))
        # and it stays that way
        self.assertEqual(self.daily(90)[aid(drive)]["severity"], "info")

    def test_an_install_that_already_had_the_big_count(self):
        """The same drive on an install whose history starts after the bug: the count is there
        from the first reading."""
        drive = nvme(media_errors=41870, available_spare=94)
        self.plug("nvme0", drive)
        a = self.check()[aid(drive)]
        self.assertEqual((a["severity"], a["title"]), ("needs_you", "A drive has errors: Samsung SSD 980 PRO 2TB (nvme0)"))
        quiet = self.daily(30)[aid(drive)]
        self.assertEqual(quiet["severity"], "info")
        self.assertIn(f"41,870 media errors, unchanged since at least {D.day(NOW)}", quiet["detail"])

    def test_a_count_that_climbed_for_days_is_replace_soon_until_it_holds(self):
        self.plug("nvme0", nvme(firmware="3B2QGXA7"))
        self.check()
        drive = nvme()
        for count in (900, 5200, 19800, 41870):
            self.plug("nvme0", nvme(firmware="3B2QGXA7", media_errors=count))
            a = self.check(days=1)[aid(drive)]
        self.assertEqual((a["severity"], self.drive("nvme0")["verdict"]), ("needs_you", "replace"))
        self.plug("nvme0", nvme(firmware="5B2QGXA7", media_errors=41870))
        self.assertEqual(self.daily(29)[aid(drive)]["severity"], "needs_you")
        self.assertEqual(self.check(days=1)[aid(drive)]["severity"], "info")
        self.assertEqual(self.drive("nvme0")["verdict"], "watch")


class Identity(Drives):
    def test_a_drive_is_itself_whatever_its_device_name(self):
        """nvme0 and nvme1 swap between boots: the alert, its first-seen time and the history
        follow the drive."""
        bad, good = nvme(serial="FAKE0NVME00000A", media_errors=17), nvme(serial="FAKE0NVME00000B")
        self.plug("nvme0", bad)
        self.plug("nvme1", good)
        first = self.check()
        self.assertEqual(list(first), [aid(bad)])
        self.assertEqual(first[aid(bad)]["title"], "A drive has errors: Samsung SSD 980 PRO 2TB (nvme0)")
        self.daily(20)
        self.plug("nvme0", good)        # the next boot names them the other way round
        self.plug("nvme1", bad)
        second = self.check(days=1)
        self.assertEqual(list(second), [aid(bad)])
        a = second[aid(bad)]
        self.assertEqual(a["title"], "A drive has errors: Samsung SSD 980 PRO 2TB (nvme1)")
        self.assertEqual(a["since"], NOW)
        self.assertEqual(a["fix"]["commands"][:2], ["bromigos storage health nvme1", "sudo smartctl -a /dev/nvme1"])
        self.assertEqual((a["subject"], a["evidence"]["facts"]["serial_tail"]), ("nvme1", "000A"))
        # the 30 days run on across the swap: quiet on the day they would have been
        self.assertEqual(self.daily(8)[aid(bad)]["severity"], "needs_you")
        self.assertEqual(self.check(days=1)[aid(bad)]["severity"], "info")
        got = {d["key"]: d for d in self.health()["drives"]}
        self.assertEqual(len(got), 2)
        self.assertEqual((got[key(bad)]["device"], got[key(bad)]["verdict"]), ("nvme1", "watch"))
        self.assertEqual((got[key(good)]["device"], got[key(good)]["verdict"]), ("nvme0", "healthy"))
        self.assertEqual(got[key(bad)]["first_seen"], NOW)
        self.assertTrue(all(s["media_errors"] == 17 for s in got[key(bad)]["samples"]))
        self.assertTrue(all(s["media_errors"] == 0 for s in got[key(good)]["samples"]))
        # the full serial number is not kept, only its last four characters
        text = (self.m.root / "var/lib/bromigos/drives/history.json").read_text()
        self.assertNotIn("FAKE0NVME00000A", text)
        self.assertIn('"serial_tail": "000A"', text)

    def test_a_drive_that_goes_away_and_comes_back(self):
        drive = sata(Reallocated_Sector_Ct=4)
        self.plug("sda", drive)
        self.plug("nvme0", nvme())
        self.check()
        self.daily(5)
        self.unplug("sda")
        self.assertEqual(self.check(days=1), {})         # not there: no alert about it
        d = self.drive(key(drive))
        self.assertEqual((d["present"], d["verdict"], d["last_seen"]), (False, "checking", NOW + 5 * DAY))
        self.assertIn("Not connected now:", D.plain(self.health(), self.m.now))
        self.daily(40)
        # back with the same count, under another name: nothing grew, so the wait is over
        self.plug("sdb", drive)
        back = self.check(days=1)[aid(drive)]
        self.assertEqual(back["severity"], "info")
        self.assertIn(f"4 reallocated sectors, unchanged since at least {D.day(NOW)}", back["detail"])
        d = self.drive("sdb")
        self.assertEqual((d["present"], d["first_seen"], len(d["samples"])), (True, NOW, 7))
        # away again, and back with more: it rose while away, over that whole time
        self.unplug("sdb")
        self.daily(12)
        self.plug("sda", sata(Reallocated_Sector_Ct=9))
        worse = self.check(days=1)[aid(drive)]
        self.assertEqual(worse["severity"], "needs_you")
        self.assertIn("reallocated sectors rose from 4 to 9 in the last 13 days", worse["detail"])

    def test_a_drive_replaced_by_another_in_the_same_slot(self):
        old = sata(serial="FAKE0SATA00000A", Reallocated_Sector_Ct=40, Current_Pending_Sector=6)
        self.plug("sda", old)
        self.assertEqual(self.check()[aid(old)]["severity"], "needs_you")
        self.daily(3)
        new = sata(serial="FAKE0SATA00000B")
        self.plug("sda", new)            # the new drive takes the old one's name
        self.assertEqual(self.check(days=1), {})
        got = {d["key"]: d for d in self.health()["drives"]}
        self.assertEqual((got[key(new)]["verdict"], got[key(new)]["present"], got[key(new)]["first_seen"]),
                         ("healthy", True, NOW + 4 * DAY))
        self.assertEqual(got[key(new)]["trend"]["reallocated"]["value"], 0)
        self.assertEqual(len(got[key(new)]["samples"]), 1)
        self.assertEqual((got[key(old)]["verdict"], got[key(old)]["present"], got[key(old)]["device"]),
                         ("checking", False, "sda"))
        self.assertEqual(self.drive("sda")["key"], key(new))     # the name means the drive that is there
        # two drives of one model are told apart by their serial numbers
        self.assertNotEqual(key(old), key(new))
        self.assertTrue(key(old).startswith("wdc-wd40efrx-68n32n0-"))

    def test_a_drive_without_a_serial_number_follows_its_device_name(self):
        doc = sata(serial="", Reallocated_Sector_Ct=2)
        self.plug("sda", doc)
        a = self.check()["disk.smart:wdc-wd40efrx-68n32n0-sda"]
        self.assertEqual(a["severity"], "needs_you")
        d = self.drive("sda")
        self.assertFalse(d["stable_identity"])
        self.assertIn("It gives no serial number", D.detail(d, self.m.now))


class History(Drives):
    def test_one_reading_a_day_and_one_at_each_change(self):
        self.plug("nvme0", nvme())
        for _ in range(96):                        # a day of checks, every 15 minutes
            self.m.now += 15 * 60_000
            self.check()
        self.assertEqual(len(self.drive("nvme0")["samples"]), 2)     # two calendar days touched
        # the temperature and the hours move all the time: no new reading for them
        self.plug("nvme0", nvme(temperature=55, power_on_hours=9200))
        self.check()
        self.assertEqual(len(self.drive("nvme0")["samples"]), 2)
        # a count changes: a reading at once
        self.plug("nvme0", nvme(unsafe_shutdowns=113))
        self.check()
        samples = self.drive("nvme0")["samples"]
        self.assertEqual([s["unsafe_shutdowns"] for s in samples], [112, 112, 113])
        self.assertEqual(samples[0]["t"], NOW + 15 * 60_000)

    def test_the_history_is_bounded(self):
        history = {"schema": 1, "drives": {}}
        r = D.reading_from_smartctl(nvme(), 0, "/dev/nvme0")
        r["why"] = ""
        for i in range(D.MAX_SAMPLES + 150):
            d = D.observe(history, r, NOW + i * DAY)
        self.assertEqual(len(d["samples"]), D.MAX_SAMPLES)
        self.assertEqual(d["samples"][0]["t"], NOW + 150 * DAY)     # the oldest went
        self.assertEqual(d["first_seen"], NOW)
        # rises are kept a day at a time, and bounded
        for i in range(D.MAX_RISES + 20):
            r["values"]["media_errors"] = i + 1
            D.observe(history, r, NOW + (600 + i) * DAY)
        self.assertEqual(len(d["trend"]["media_errors"]["rises"]), D.MAX_RISES)
        for i in range(D.MAX_EVENTS + 20):
            r["firmware"] = f"FW{i}"
            D.observe(history, r, NOW + 700 * DAY)
        self.assertEqual(len(d["events"]), D.MAX_EVENTS)
        # more drives than MAX_DRIVES: the ones gone longest are forgotten, connected ones never
        d["present"] = True
        for i in range(D.MAX_DRIVES + 10):
            r2 = D.reading_from_smartctl(nvme(serial=f"FAKE0GONE{i:06d}"), 0, "/dev/nvme1")
            r2["why"] = ""
            D.observe(history, r2, NOW + i * DAY)["present"] = False
        D._trim(history)
        self.assertEqual(len(history["drives"]), D.MAX_DRIVES)
        self.assertIn(d["key"], history["drives"])
        self.assertNotIn(key(nvme(serial="FAKE0GONE000000")), history["drives"])
        self.assertIn(key(nvme(serial=f"FAKE0GONE{D.MAX_DRIVES + 9:06d}")), history["drives"])

    def test_the_file(self):
        self.plug("nvme0", nvme(media_errors=3))
        self.check()
        path = self.m.root / "var/lib/bromigos/drives/history.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        doc = json.loads(path.read_text())
        self.assertEqual((doc["schema"], doc["checked_at"], list(doc["drives"])), (1, NOW, [key(nvme())]))
        # a file that can't be read is started again, and the drive is judged as new
        path.write_text("{not json")
        a = self.check(days=1)[aid(nvme())]
        self.assertEqual(a["severity"], "needs_you")
        self.assertEqual(json.loads(path.read_text())["drives"][key(nvme())]["first_seen"], NOW + DAY)
        # nothing else was written: no home, no real state
        self.assertFalse((self.m.home / ".local/state/bromigos/drives").exists())

    def test_a_count_that_falls_or_clears(self):
        drive = sata(Current_Pending_Sector=8)
        self.plug("sda", drive)
        self.check()
        self.plug("sda", sata(Current_Pending_Sector=3))        # some were read again and let go
        self.assertEqual(self.check(days=1)[aid(drive)]["severity"], "needs_you")
        self.plug("sda", sata())                                # all of them
        self.assertEqual(self.check(days=1), {})
        d = self.drive("sda")
        self.assertEqual(d["verdict"], "healthy")
        self.assertEqual([(e["kind"], e["from"], e["to"]) for e in d["events"] if e["kind"] in ("fell", "cleared")],
                         [("fell", 8, 3), ("cleared", 3, 0)])
        # new ones later are new: a rise from zero, not old errors
        self.plug("sda", sata(Current_Pending_Sector=1))
        a = self.check(days=1)[aid(drive)]
        self.assertIn("1 sector it can't read appeared in the last day", a["detail"])


class NvmeCli(Drives):
    def sysfs(self, ctrl, model, serial, firmware):
        for leaf, text in (("model", model), ("serial", serial), ("firmware_rev", firmware)):
            self.m.rootfile(f"/sys/class/nvme/{ctrl}/{leaf}", text + "   \n")

    def test_nvme_cli_reads_the_drive_without_smartctl(self):
        (self.m.bin / "smartctl").unlink()
        self.sysfs("nvme0", "Samsung SSD 980 PRO 2TB", "FAKE0NVME000001", "5B2QGXA7")
        log = fixture("nvme-smart-log.json")
        self.m.write("nvme/nvme0.json", log)
        self.assertEqual(self.check(), {})
        d = self.drive("nvme0")
        self.assertEqual(d["key"], key(nvme()))                  # the same drive as smartctl would name
        self.assertEqual(d["readings"], {"critical_warning": 0, "media_errors": 0, "spare": 100, "spare_threshold": 10,
                                         "percent_used": 3, "unsafe_shutdowns": 112, "power_on_hours": 9120,
                                         "temperature": 41})    # 314 K
        self.assertEqual((d["verdict"], d["firmware"]), ("healthy", "5B2QGXA7"))
        self.assertIn("nvme smart-log /dev/nvme0 -o json", (self.m.fake / "log").read_text())
        # its verbose form spells the warning out as an object
        self.m.write("nvme/nvme0.json", dict(log, critical_warning={"value": 1, "available_spare": 1}, avail_spare=4))
        a = self.check(hours=1)[aid(nvme())]
        self.assertEqual(a["severity"], "critical")
        self.assertIn("its spare space is down to 4%, under the drive's own threshold of 10%", a["detail"])

    def test_nvme_cli_fills_in_for_a_drive_smartctl_cannot_read(self):
        self.sysfs("nvme0", "Samsung SSD 980 PRO 2TB", "FAKE0NVME000001", "5B2QGXA7")
        self.plug("nvme0", {"smartctl": {"exit_status": 2}}, rc=2)
        self.plug("sda", sata())
        self.m.write("nvme/nvme0.json", dict(fixture("nvme-smart-log.json"), media_errors=7))
        a = self.check()[aid(nvme())]
        self.assertEqual(a["title"], "A drive has errors: Samsung SSD 980 PRO 2TB (nvme0)")
        self.assertEqual({d["device"]: d["verdict"] for d in self.health()["drives"]}, {"nvme0": "checking", "sda": "healthy"})

    def test_neither_tool_is_a_skip(self):
        (self.m.bin / "smartctl").unlink()
        (self.m.bin / "nvme").unlink()
        doc = A.run_pass(self.m.env(), "system", checks={"disk.smart"})
        row = [c for c in doc["checks"] if c["check"] == "disk.smart"][0]
        self.assertEqual((row["state"], row["error"]), ("skipped", "smartmontools isn't installed"))


class Command(Drives):
    def test_before_any_check(self):
        r = self.cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("No drive health has been recorded yet.", r.stdout)
        self.assertIn("sudo bromigos alerts check --system --only disk.smart", r.stdout)
        self.assertEqual(json.loads(self.cli("--json").stdout)["drives"], [])

    def test_one_line_per_drive(self):
        self.m.write("lsblk.json", fixture("lsblk.json"))
        self.plug("nvme0", nvme(media_errors=41870, available_spare=94))
        self.plug("sda", sata())
        self.plug("sdc", fixture("smartctl-usb-bridge.json"), rc=1)
        self.check()
        self.daily(30)
        self.m.now += 12 * 60_000
        r = self.cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"""Drive health, read 12 min ago

  Samsung SSD 980 PRO 2TB (nvme0)  watch        41,870 media errors, unchanged since at least {D.day(NOW)}
  WDC WD40EFRX-68N32N0 (sda)       healthy      no errors, 21,503 hours on, 34 °C
  Extreme 55AE (sdc)               cannot tell  it's connected through a USB adapter that doesn't pass the drive's health records on
  A drive (vda)                    cannot tell  it's a virtual disk: the real drive's health is on the machine that hosts it

bromigos storage health DRIVE shows one drive's readings over time (DRIVE: nvme0, or part of a model).
""")
        doc = json.loads(self.cli("--json").stdout)
        self.assertEqual((doc["schema"], doc["checked_at"], doc["history"]),
                         (1, NOW + 30 * DAY, str(self.m.root / "var/lib/bromigos/drives/history.json")))
        self.assertEqual(doc["rules"], {"quiet_days": 30, "sustained_days": 3, "worn_percent": 90, "spent_percent": 100,
                                        "max_samples": 400, "max_drives": 64})
        self.assertEqual([(d["device"], d["verdict"], d["alert"]) for d in doc["drives"]],
                         [("nvme0", "watch", "info"), ("sda", "healthy", None), ("sdc", "unknown", None),
                          ("vda", "unknown", None)])
        self.assertNotIn("samples", doc["drives"][0])
        for d in doc["drives"]:
            self.assertEqual(set(d) >= {"key", "device", "model", "serial_tail", "firmware", "present", "verdict", "words",
                                        "alert", "summary", "reasons", "advice", "readings", "events"}, True)

    def test_one_drive_with_its_readings_over_time(self):
        self.plug("nvme0", nvme(firmware="3B2QGXA7"))
        self.check()
        self.plug("nvme0", nvme(firmware="3B2QGXA7", media_errors=41870, available_spare=94))
        self.check(days=1)
        self.plug("nvme0", nvme(firmware="5B2QGXA7", media_errors=41870, available_spare=94))
        self.daily(30)
        r = self.cli("nvme0")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertTrue(out.startswith("Samsung SSD 980 PRO 2TB (nvme0), serial ends 0001, firmware 5B2QGXA7\n"
                                       f"watch: 41,870 media errors, unchanged since {D.day(NOW + DAY)}\n"
                                       "What to do: Nothing to do while it stays that way."), out)
        for line in ("  Media errors            41,870", "  Spare space             94% (the drive's own threshold: 10%)",
                     "  Rated life used         3%", "  Critical warning        none", "  Unsafe shutdowns        112",
                     "  Temperature             41 °C", "  Power-on hours          9,120",
                     "  Last self-test          Short, passed, at 9,100 h", "  Its own health check    passed",
                     f"  {D.stamp(NOW)}  its history begins",
                     f"  {D.stamp(NOW + 2 * DAY)}  firmware changed from 3B2QGXA7 to 5B2QGXA7",
                     f"  {D.stamp(NOW + 31 * DAY)}  getting worse became watch (the alarm went quiet): 41,870 media errors, "
                     f"unchanged since {D.day(NOW + DAY)}",
                     "Readings over time (one a day, and one at each change; 32 kept, 400 at most)",
                     "  the newest 30; --all shows every one",
                     "  When               Media  Spare  Used  Warning  Unsafe   Temp  Hours  Self-test",
                     f"  {D.stamp(NOW + 31 * DAY)}  41,870    94%    3%     none     112  41 °C  9,120     passed"):
            self.assertIn(line + "\n", out + "\n", line)
        self.assertNotIn(f"  {D.stamp(NOW)}       0", out)
        self.assertIn(f"  {D.stamp(NOW)}       0   100%", self.cli("nvme0", "--all").stdout)
        # --json: the one drive, every kept reading
        doc = json.loads(self.cli("nvme0", "--json").stdout)
        self.assertEqual(len(doc["drives"]), 1)
        d = doc["drives"][0]
        self.assertEqual((d["verdict"], len(d["samples"]), d["samples"][0]["media_errors"], d["samples"][-1]["media_errors"]),
                         ("watch", 32, 0, 41870))
        # by /dev name, by part of the model, by key
        for word in ("/dev/nvme0", "980 pro", d["key"]):
            self.assertEqual(json.loads(self.cli(word, "--json").stdout)["drives"][0]["key"], d["key"], word)
        r = self.cli("sdz")
        self.assertEqual(r.returncode, 1)
        self.assertIn("No drive matches 'sdz'", r.stderr)
        self.plug("nvme1", nvme(serial="FAKE0NVME000002"))
        self.check()
        r = self.cli("samsung")
        self.assertEqual(r.returncode, 1)
        self.assertIn("matches 2 drives: nvme0, nvme1", r.stderr)

    def test_a_drives_own_text_is_printed_safely(self):
        doc = nvme()
        doc["model_name"] = "Evil\x1b[31m Drive\n\twith   spaces " + "x" * 200
        self.plug("nvme0", doc)
        self.check()
        d = self.drive("nvme0")
        self.assertEqual(d["model"], ("Evil[31m Drive with spaces " + "x" * 200)[:60].strip())
        self.assertNotIn("\x1b", self.cli().stdout)


if __name__ == "__main__":
    unittest.main()
