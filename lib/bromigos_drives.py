"""Drive health with history (docs/storage.md, "Drive health"): what each drive says about
itself, kept over time, and a verdict in plain words decided from the trend.

  check(ctx)            the `disk.smart` check of `bromigos alerts`: read every drive, add the
                        reading to its history, judge it, write the history, return the alerts
  report(env)           what `bromigos storage health` shows: every drive with its verdict
  find(doc, word)       one drive of a report, by device name, model or key

A drive is known by its model and serial number, never by its device name: nvme0 and nvme1
swap between boots. The history is one file, written by the system pass (root, 0644):

  /var/lib/bromigos/drives/history.json

The verdicts, worst first. Every number is a constant below, with why:

  replace    replace soon: the drive says so itself (SMART's failing flag, an NVMe critical
             warning, spare under the drive's own threshold, an attribute past the drive's own
             limit, a failed self-test, its rated life used up), or a count kept rising
  worse      getting worse: an error count rose in the last QUIET_DAYS days
  checking   has errors, still checking: errors that were there when the history began, so
             nothing says yet whether they are old
  watch      old errors that haven't grown for QUIET_DAYS days. No alarm, one quiet line
  healthy    nothing to report
  unknown    cannot tell: the drive doesn't report (a USB adapter, a virtual disk)

Everything goes through an Env (bromigos_alerts), so a test gives stand-in commands, a
stand-in root and a fixed clock.
"""

import hashlib
import json
import math
import re
import time

from bromigos_alerts import Failed, Skip, alert, evidence, read_json, write_json

HISTORY = "/var/lib/bromigos/drives/history.json"
SCHEMA = 1
DAY = 86400_000

# An error count that hasn't risen for this long is old news: the alarm goes quiet. A month,
# because on bromigOS Server the drive's whole surface is read four times in it (a long
# self-test every Saturday) and btrfs scrubs once, so a defect that is still spreading has had
# the chance to show. Other systems that check before they alarm watch for a month too.
QUIET_DAYS = 30
# A count that rose on this many separate days inside QUIET_DAYS is no longer one event (a
# knock, a power cut, one bad write): it keeps happening, so the drive should be replaced.
SUSTAINED_DAYS = 3
# An SSD's "percentage used" is the maker's own estimate of its rated life. 100 is the
# maker's line: the rated writes are used up. From 90 it shows as a quiet line, so the end
# isn't a surprise.
WORN_PERCENT = 90
SPENT_PERCENT = 100
# How long the quiet line says "the alarm is off" after an alarm ends: a day, so it is said
# once and seen whenever the person next looks.
NOTE_HOURS = 24
# The history's bounds. One reading a day plus one at each change: 400 is over a year.
MAX_SAMPLES = 400
MAX_DRIVES = 64
MAX_RISES = 64
MAX_EVENTS = 40

WORDS = {"healthy": "healthy", "watch": "watch", "checking": "has errors, still checking",
         "worse": "getting worse", "replace": "replace soon", "unknown": "cannot tell"}
RANK = {"healthy": 0, "unknown": 0, "watch": 1, "checking": 2, "worse": 3, "replace": 4}
ALARMS = ("checking", "worse", "replace")

# The error counts judged by their trend: (one, many).
COUNTERS = {
    "reallocated": ("reallocated sector", "reallocated sectors"),
    "pending": ("sector it can't read", "sectors it can't read"),
    "uncorrectable": ("uncorrectable sector", "uncorrectable sectors"),
    "reported_uncorrectable": ("uncorrectable error", "uncorrectable errors"),
    "media_errors": ("media error", "media errors"),
    "grown_defects": ("grown defect", "grown defects"),
}
# SATA attributes, by number (their names differ between makers) and by smartctl's usual name.
ATA_IDS = {5: "reallocated", 187: "reported_uncorrectable", 197: "pending", 198: "uncorrectable", 199: "crc_errors"}
ATA_NAMES = {"Reallocated_Sector_Ct": "reallocated", "Reported_Uncorrect": "reported_uncorrectable",
             "Current_Pending_Sector": "pending", "Offline_Uncorrectable": "uncorrectable",
             "UDMA_CRC_Error_Count": "crc_errors"}
# A SATA self-test's status, high four bits: 0 passed; 3 to 8 failed (unknown, electrical,
# servo, read, handling damage); 1, 2 and 15 are aborted, interrupted and still running.
ATA_TEST_FAILED = {3, 4, 5, 6, 7, 8}
# An NVMe self-test's result: 0 passed; 5, 6 and 7 failed; the rest were aborted.
NVME_TEST_FAILED = {5, 6, 7}
# NVMe's critical warning bits (NVMe base specification, SMART / Health Information log).
NVME_HOT = 0x02
NVME_WARNINGS = (
    (0x01, "its spare space fell under the drive's own threshold"),
    (0x04, "it says its reliability is degraded"),
    (0x08, "it has gone read-only"),
    (0x10, "its power-loss protection failed"),
    (0x20, "its persistent memory region is read-only"),
)
NVME_KNOWN = 0x3f
# What a reading is compared by: a new sample is kept when any of these changed.
STEADY = ("temperature", "power_on_hours")
SKIP_DEV = ("/dev/loop", "/dev/zram", "/dev/sr", "/dev/ram", "/dev/fd", "/dev/nbd", "/dev/dm-", "/dev/md")


# ------------------------------------------------------------------ small helpers

def _int(v):
    """A count as a whole number, or None for anything that isn't one (a count is never negative)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int) or (isinstance(v, float) and v == v and abs(v) < 1e18):
        return int(v) if v >= 0 else None
    if isinstance(v, str) and re.fullmatch(r"\s*\d{1,18}\s*", v):
        return int(v)
    return None


def _dict(v):
    return v if isinstance(v, dict) else {}


def _rows(v):
    """A table's rows: the dicts of a list. Anything else a tool printed there is passed over."""
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _clean(text, n=60):
    """A drive's own text (model, firmware), safe to print: one line, no control characters."""
    if isinstance(text, bool) or not isinstance(text, (str, int)):
        return ""
    s = "".join(ch for ch in " ".join(str(text).split()) if ch.isprintable())
    return s[:n].strip()


def _slug(text, n=40):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n].strip("-")


def drive_key(model, serial, name):
    """(key, stable): the drive's name in the history and in its alert's id. Stable when the
    drive gives a serial number; otherwise it is only as good as its device name."""
    if serial:
        digest = hashlib.sha256(f"{model}\n{serial}".encode()).hexdigest()[:8]
        return f"{_slug(model) or 'drive'}-{digest}", True
    return f"{_slug(model) or 'drive'}-{_slug(name) or 'unnamed'}", False


def day(ms):
    """9 Nov 2026, in this computer's time zone."""
    t = time.localtime(ms / 1000)
    return f"{t.tm_mday} {time.strftime('%b %Y', t)}"


def stamp(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000))


def _n(count, words):
    return f"{count:,} {words[0] if count == 1 else words[1]}"


def _span(ms):
    days = max(1, math.ceil(ms / DAY))
    return "the last day" if days == 1 else f"the last {days} days"


# ------------------------------------------------------------------ reading a drive

def _ata_self_test(doc):
    """The newest SATA self-test that finished: smartctl lists them newest first."""
    for row in _rows(_dict(_dict(doc.get("ata_smart_self_test_log")).get("standard")).get("table")):
        st = _dict(row.get("status"))
        code = _int(st.get("value"))
        if code is not None:
            top = code >> 4
            if top == 0:
                passed = True
            elif top in ATA_TEST_FAILED:
                passed = False
            else:
                continue
        elif isinstance(st.get("passed"), bool):
            passed = st["passed"]
        else:
            continue
        return {"type": _clean(_dict(row.get("type")).get("string") or "Self-test", 40), "passed": passed,
                "status": _clean(st.get("string"), 80), "hours": _int(row.get("lifetime_hours"))}
    return None


def _nvme_self_test(doc):
    """The newest NVMe self-test that finished (newest first, as smartctl lists them)."""
    for row in _rows(_dict(doc.get("nvme_self_test_log")).get("table")):
        res = _dict(row.get("self_test_result"))
        code = _int(res.get("value"))
        if code == 0:
            passed = True
        elif code in NVME_TEST_FAILED:
            passed = False
        else:
            continue
        return {"type": _clean(_dict(row.get("self_test_code")).get("string") or "Self-test", 40), "passed": passed,
                "status": _clean(res.get("string"), 80), "hours": _int(row.get("power_on_hours"))}
    return None


def _put(values, key, v):
    if v is not None:
        values[key] = v


def reading_from_smartctl(doc, rc, dev):
    """One drive's reading from `smartctl -j -H -A -i -l selftest DEV`: its document and its
    exit status. `reports` is False when the drive gave nothing to judge."""
    doc = _dict(doc)
    name = dev.rsplit("/", 1)[-1]
    device = _dict(doc.get("device"))
    values = {}
    passed = _dict(doc.get("smart_status")).get("passed")
    if rc & 0b1000:               # smartctl's exit bit 3: "SMART status check returned DISK FAILING"
        passed = False
    if isinstance(passed, bool):
        values["passed"] = passed
    nvme = _dict(doc.get("nvme_smart_health_information_log"))
    table = _rows(_dict(doc.get("ata_smart_attributes")).get("table"))
    kind = "nvme" if nvme else "ata" if table or device.get("protocol") == "ATA" else \
        "scsi" if device.get("protocol") == "SCSI" else _clean(device.get("type"), 12).lower()
    if nvme:
        values["critical_warning"] = _int(nvme.get("critical_warning")) or 0
        _put(values, "media_errors", _int(nvme.get("media_errors")))
        _put(values, "spare", _int(nvme.get("available_spare")))
        _put(values, "spare_threshold", _int(nvme.get("available_spare_threshold")))
        _put(values, "percent_used", _int(nvme.get("percentage_used")))
        _put(values, "unsafe_shutdowns", _int(nvme.get("unsafe_shutdowns")))
        _put(values, "temperature", _int(nvme.get("temperature")))
        _put(values, "power_on_hours", _int(nvme.get("power_on_hours")))
        _put(values, "self_test", _nvme_self_test(doc))
    prefail, oldage, before = [], [], []
    for row in table:
        label = _clean(row.get("name"), 40) or f"attribute {_int(row.get('id'))}"
        key = ATA_IDS.get(_int(row.get("id"))) or ATA_NAMES.get(label)
        if key:
            _put(values, key, _int(_dict(row.get("raw")).get("value")))
        if row.get("when_failed") == "now":
            (prefail if _dict(row.get("flags")).get("prefailure") else oldage).append(label)
        elif row.get("when_failed") == "past":
            before.append(label)
    if prefail:
        values["prefail_now"] = prefail
    if oldage:
        values["oldage_now"] = oldage
    if before:
        values["failed_before"] = before
    if table:
        _put(values, "self_test", _ata_self_test(doc))
    _put(values, "grown_defects", _int(doc.get("scsi_grown_defect_list")))
    values.setdefault("temperature", _int(_dict(doc.get("temperature")).get("current")))
    values.setdefault("power_on_hours", _int(_dict(doc.get("power_on_time")).get("hours")))
    values = {k: v for k, v in values.items() if v is not None}
    supported = _dict(doc.get("smart_support")).get("available")
    # exit bits 0 and 1: the command line didn't parse, or the device couldn't be opened
    reports = not (rc & 0b11) and supported is not False and bool(
        nvme or table or "passed" in values or "grown_defects" in values)
    messages = [m.get("string") for m in _rows(_dict(doc.get("smartctl")).get("messages"))]
    return {"device": dev, "name": name, "model": _clean(doc.get("model_name") or doc.get("scsi_model_name")
                                                         or doc.get("model_family")),
            "serial": _clean(doc.get("serial_number"), 80), "firmware": _clean(doc.get("firmware_version"), 40),
            "kind": kind, "reports": reports, "values": values if reports else {},
            "said": _clean(messages[0], 160) if messages and not reports else ""}


def values_from_nvme_cli(doc):
    """An NVMe drive's values from `nvme smart-log DEV -o json` (nvme-cli), for when smartctl
    isn't there or can't read the drive. It gives the temperature in kelvin."""
    doc = _dict(doc)
    cw = doc.get("critical_warning")
    if isinstance(cw, dict):      # nvme-cli's verbose output spells the bits out
        cw = cw.get("value")
    temp = _int(doc.get("temperature"))
    if temp is not None and temp > 200:
        temp -= 273
    values = {"critical_warning": _int(cw) or 0}
    for key, theirs in (("media_errors", "media_errors"), ("spare", "avail_spare"), ("spare_threshold", "spare_thresh"),
                        ("percent_used", "percent_used"), ("unsafe_shutdowns", "unsafe_shutdowns"),
                        ("power_on_hours", "power_on_hours")):
        _put(values, key, _int(doc.get(theirs)))
    _put(values, "temperature", temp)
    return values


def _lsblk(env):
    """{name: row} of the whole disks lsblk lists, or {} without lsblk."""
    rc, out, _ = env.run(["lsblk", "-J", "-d", "-o", "NAME,TYPE,MODEL,SERIAL,TRAN"], timeout=15)
    if rc != 0:
        return {}
    try:
        rows = _rows(_dict(json.loads(out)).get("blockdevices"))
    except ValueError:
        return {}
    return {r["name"]: r for r in rows if r.get("type") == "disk" and isinstance(r.get("name"), str) and r["name"]
            and not f"/dev/{r['name']}".startswith(SKIP_DEV)}


def _block_of(name, blocks):
    """lsblk's row for a drive smartctl names: nvme0 is nvme0n1 there."""
    if name in blocks:
        return name
    for b in sorted(blocks):
        if re.fullmatch(re.escape(name) + r"n\d+", b):
            return b
    return None


def _why_not(name, row, said, model=""):
    """Why a drive can't be judged, in plain words. Never a guess at its health."""
    row = row or {}
    tran, model = _clean(row.get("tran"), 20).lower(), f"{model} {_clean(row.get('model'))}"
    if tran == "usb":
        return "it's connected through a USB adapter that doesn't pass the drive's health records on"
    if name.startswith(("vd", "xvd")) or tran == "virtio" or re.search(r"qemu|vbox|vmware|virtual", model, re.I):
        return "it's a virtual disk: the real drive's health is on the machine that hosts it"
    if name.startswith("mmcblk"):
        return "memory cards and eMMC storage keep no health records bromigOS reads"
    return "it didn't answer when asked for its health records" + (f" ({said})" if said else "")


def scan(env):
    """Every drive's reading now. Skip without the tools, Failed when smartctl gave no answer."""
    rc, out, err = env.run(["smartctl", "--scan", "-j"], timeout=30)
    devices = []
    if rc != 127:
        try:
            devices = _rows(json.loads(out).get("devices"))
        except (ValueError, AttributeError):
            raise Failed("smartctl --scan gave no answer: " + (err.strip() or "?")[:200])
    elif not env.find("nvme"):
        raise Skip("smartmontools isn't installed")
    readings = []
    for d in devices:
        dev = d.get("name")
        if not isinstance(dev, str) or not dev or dev.startswith(SKIP_DEV):
            continue
        # A plain scan calls every sdX "scsi". Told that type, smartctl stops looking for the SATA
        # drive behind it and its attributes never show; left to itself it detects SATA, SAS and
        # the USB adapters it knows. Every other type (nvme, a RAID card's) is passed on.
        kind = d.get("type") if isinstance(d.get("type"), str) else ""
        argv = ["smartctl", "-j", "-H", "-A", "-i", "-l", "selftest", *(["-d", kind] if kind not in ("", "scsi") else []), dev]
        rc, out, _ = env.run(argv, timeout=60)
        try:
            doc = json.loads(out)
        except ValueError:
            doc = {}
        readings.append(reading_from_smartctl(doc, rc, dev))
    by_name = {r["name"]: r for r in readings}
    # NVMe drives smartctl didn't read (or all of them, without smartctl): nvme-cli's health log
    if env.find("nvme"):
        for ctrl in env.listdir("/sys/class/nvme"):
            if not re.fullmatch(r"nvme\d+", ctrl) or (by_name.get(ctrl) or {}).get("reports"):
                continue
            rc, out, _ = env.run(["nvme", "smart-log", f"/dev/{ctrl}", "-o", "json"], timeout=30)
            try:
                values = values_from_nvme_cli(json.loads(out)) if rc == 0 else None
            except ValueError:
                values = None
            if values is None:
                continue

            def sys_text(leaf, n=60):
                return _clean(env.read(f"/sys/class/nvme/{ctrl}/{leaf}") or "", n)
            r = {"device": f"/dev/{ctrl}", "name": ctrl, "model": sys_text("model"), "serial": sys_text("serial", 80),
                 "firmware": sys_text("firmware_rev", 40), "kind": "nvme", "reports": True, "values": values, "said": ""}
            if ctrl in by_name:
                readings[readings.index(by_name[ctrl])] = r
            else:
                readings.append(r)
            by_name[ctrl] = r
    # what lsblk knows fills in the rest: a drive that didn't answer gets its model and why,
    # and a disk smartctl never listed (a virtual one) is still named
    blocks = _lsblk(env)
    claimed = set()
    for r in readings:
        b = _block_of(r["name"], blocks)
        row = blocks.get(b) if b else None
        if b:
            claimed.add(b)
        if not r["reports"]:
            r["model"] = r["model"] or _clean((row or {}).get("model"))
            r["serial"] = r["serial"] or _clean((row or {}).get("serial"), 80)
            r["why"] = _why_not(r["name"], row, r["said"], r["model"])
    for b, row in sorted(blocks.items()):
        if b in claimed:
            continue
        readings.append({"device": f"/dev/{b}", "name": b, "model": _clean(row.get("model")),
                         "serial": _clean(row.get("serial"), 80), "firmware": "", "kind": "", "reports": False,
                         "values": {}, "said": "", "why": _why_not(b, row, "")})
    for r in readings:
        r["model"] = r["model"] or "A drive"
        r.setdefault("why", "")
    return readings


# ------------------------------------------------------------------ the history

def load(env):
    """The history, or an empty one when the file isn't there or can't be read. A record that
    isn't shaped as one is left out, so that drive starts again."""
    doc = read_json(env.path(HISTORY))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("drives"), dict):
        return {"schema": SCHEMA, "drives": {}}
    doc["drives"] = {k: d for k, d in doc["drives"].items()
                     if isinstance(d, dict) and d.get("key") == k and isinstance(d.get("trend"), dict)
                     and isinstance(d.get("samples"), list) and isinstance(d.get("events"), list)}
    return doc


def save(env, history):
    write_json(env.path(HISTORY), history, 0o644, 0o755)


def _event(d, now, kind, **more):
    d.setdefault("events", []).append(dict(t=now, kind=kind, **more))
    del d["events"][:-MAX_EVENTS]


def _track(d, values, now):
    """Follow each error count: when it was first seen above zero, and each rise."""
    trend = d.setdefault("trend", {})
    for c in COUNTERS:
        v = values.get(c)
        if v is None:
            continue
        st = trend.get(c)
        if st is None:
            # the first reading of this count. Above zero already: nothing says how old it is
            st = trend[c] = {"value": v, "rises": []}
            if v > 0:
                st.update(since=now, baseline=True)
        elif v > st["value"]:
            if st["value"] == 0:
                st.update(since=now, baseline=False)
            today = now // DAY
            rises = st.setdefault("rises", [])
            if rises and rises[-1]["day"] == today:
                rises[-1].update(t=now, to=v)
            else:
                # `t0`: when the lower count was last seen, so a rise found after an absence
                # says "in the last 40 days", not "in the last day"
                rises.append({"day": today, "t0": st.get("seen", now), "t": now, "from": st["value"], "to": v})
                del rises[:-MAX_RISES]
            st["value"] = v
        elif v < st["value"]:
            _event(d, now, "fell" if v else "cleared", counter=c, **{"from": st["value"], "to": v})
            st["value"] = v
            if v == 0:
                trend[c] = st = {"value": 0, "rises": []}
        st["seen"] = now


def _signature(values):
    return json.dumps({k: v for k, v in values.items() if k not in STEADY}, sort_keys=True)


def _sample(d, values, now):
    """Keep this reading when something changed, and once a day otherwise."""
    samples = d.setdefault("samples", [])
    last = samples[-1] if samples else None
    if last is not None and last["t"] // DAY == now // DAY and \
            _signature({k: v for k, v in last.items() if k != "t"}) == _signature(values):
        return
    samples.append(dict(values, t=now))
    del samples[:-MAX_SAMPLES]


def observe(history, r, now):
    """Add one reading to its drive's record (made on first sight), and return the record."""
    key, stable = drive_key(r["model"], r["serial"], r["name"])
    drives = history["drives"]
    if r.get("key"):
        # a drive that no longer says who it is, matched to its record by same_drive()
        d = drives[r["key"]]
        d.update(device=r["name"], last_seen=now, why=r["why"])
    else:
        d = drives.get(key)
        if d is None:
            d = drives[key] = {"key": key, "first_seen": now, "trend": {}, "events": [], "samples": []}
            _event(d, now, "first_seen")
        if r["firmware"] and d.get("firmware") and r["firmware"] != d["firmware"]:
            _event(d, now, "firmware", **{"from": d["firmware"], "to": r["firmware"]})
        d.update(model=r["model"], serial_tail=r["serial"][-4:], kind=r["kind"] or d.get("kind") or "",
                 device=r["name"], stable_identity=stable, last_seen=now, why=r["why"])
    if r["firmware"]:
        d["firmware"] = r["firmware"]
    if r["reports"]:
        d["reports"] = True
        d.pop("silent_since", None)
        _track(d, r["values"], now)
        _sample(d, r["values"], now)
        d["readings"] = r["values"]
    elif d.get("readings"):
        # it answered before and doesn't now: its last verdict stands (a drive that is dying
        # may stop answering, and that must not clear its alarm)
        if "silent_since" not in d:
            d["silent_since"] = now
            _event(d, now, "silent")
    else:
        d["reports"] = False
    return d


def same_drive(history, r):
    """The key a reading belongs to. A drive that stops answering often can't say its model
    or serial number either, so its reading would look like a new, unknown drive and its
    alarm would clear. It is the drive that answered at this device name at the last check,
    unless what is known of its serial number says otherwise."""
    key = drive_key(r["model"], r["serial"], r["name"])[0]
    drives = history["drives"]
    if r["reports"] or (drives.get(key) or {}).get("readings"):
        return key
    was = [d for d in drives.values() if d.get("present") and d.get("device") == r["name"] and d.get("readings")
           and (not r["serial"] or r["serial"][-4:] == d.get("serial_tail"))]
    if len(was) == 1:
        r["key"] = was[0]["key"]
        return r["key"]
    return key


def _trim(history):
    """Forget the drives gone longest when there are more than MAX_DRIVES."""
    drives = history["drives"]
    gone = sorted((k for k, d in drives.items() if not d.get("present")), key=lambda k: drives[k].get("last_seen", 0))
    while len(drives) > MAX_DRIVES and gone:
        del drives[gone.pop(0)]


# ------------------------------------------------------------------ the verdict

def judge(d, now):
    """The verdict on one drive's record, from its newest reading and its trend:
    {verdict, words, severity, summary, reasons, hot, quiet_on}. `severity` is the alert's
    (None: no alert). `reasons` is [{level, text, …}], worst first. `quiet_on` is when a
    "checking" or "worse" alarm goes quiet if nothing rises until then."""
    if not d.get("reports"):
        why = d.get("why") or "it didn't answer when asked for its health records"
        return {"verdict": "unknown", "words": WORDS["unknown"], "severity": None, "summary": why,
                "reasons": [{"level": "unknown", "text": why}], "hot": False, "quiet_on": None}
    v = d.get("readings") or {}
    reasons = []

    def add(level, text, **more):
        reasons.append(dict(level=level, text=text, **more))

    # what the drive says about itself
    if v.get("passed") is False:
        add("failing", "its own health check says FAILED")
    spare, limit = v.get("spare"), v.get("spare_threshold")
    low_spare = spare is not None and limit is not None and spare < limit
    if low_spare:
        add("failing", f"its spare space is down to {spare}%, under the drive's own threshold of {limit}%")
    cw = v.get("critical_warning") or 0
    for bit, text in NVME_WARNINGS:
        if cw & bit and not (bit == 0x01 and low_spare):
            add("failing", text)
    if cw & ~NVME_KNOWN:
        add("failing", f"it raised a critical warning (0x{cw:02x})")
    for name in v.get("prefail_now") or []:
        add("failing", f"{name} is past the drive's own failure threshold")
    for name in v.get("oldage_now") or []:
        add("replace", f"{name} is past the drive's own wear threshold")
    test = v.get("self_test")
    if test and test.get("passed") is False:
        add("replace", f"its last self-test failed ({test.get('status') or test.get('type')})")
    used = v.get("percent_used")
    if used is not None and used >= SPENT_PERCENT:
        add("replace", f"{used}% of its rated life is used")
    elif used is not None and used >= WORN_PERCENT:
        add("watch", f"{used}% of its rated life is used")
    for name in v.get("failed_before") or []:
        add("watch", f"{name} was past its threshold at some point (it isn't now)")
    # what the history says
    quiet_on = None
    window = now - QUIET_DAYS * DAY
    for c, words in COUNTERS.items():
        value = v.get(c)
        st = (d.get("trend") or {}).get(c)
        if not value or not st:
            continue
        recent = [r for r in st.get("rises") or [] if r["t"] > window]
        if recent:
            first = recent[0]
            span = _span(now - min(first.get("t0", first["t"]), first["t"]))
            text = (f"{_n(value, words)} appeared in {span}" if first["from"] == 0 else
                    f"{words[1]} rose from {first['from']:,} to {value:,} in {span}")
            if len(recent) >= SUSTAINED_DAYS:
                add("replace", f"{text}, on {len(recent)} separate days", counter=c, value=value,
                    rise=value - first["from"], days=len(recent))
            else:
                add("worse", text, counter=c, value=value, rise=value - first["from"], days=len(recent))
            quiet_on = max(quiet_on or 0, recent[-1]["t"] + QUIET_DAYS * DAY)
            continue
        rises = st.get("rises") or []
        since = max(st.get("since") or 0, rises[-1]["t"] if rises else 0) or d.get("first_seen") or now
        if st.get("baseline") and not rises and now - since < QUIET_DAYS * DAY:
            add("checking", f"{_n(value, words)}, first seen {day(since)} when this drive's history began",
                counter=c, value=value, since=since)
            quiet_on = max(quiet_on or 0, since + QUIET_DAYS * DAY)
        else:
            at_least = " at least" if st.get("baseline") and not rises else ""
            add("watch", f"{_n(value, words)}, unchanged since{at_least} {day(since)}", counter=c, value=value,
                since=since)
    hot = bool(cw & NVME_HOT)
    if hot:
        temp = v.get("temperature")
        add("hot", "it says it's over its temperature limit" + (f" ({temp} °C)" if temp is not None else ""))
    levels = {r["level"] for r in reasons}
    if levels & {"failing", "replace"}:
        verdict, severity = "replace", "critical" if "failing" in levels else "needs_you"
    elif "worse" in levels:
        verdict, severity = "worse", "needs_you"
    elif "checking" in levels:
        verdict, severity = "checking", "needs_you"
    elif "watch" in levels:
        verdict, severity = "watch", "info"
    else:
        verdict, severity = "healthy", None
    if hot and severity in (None, "info"):
        severity = "needs_you"
    order = {"failing": 0, "replace": 1, "worse": 2, "checking": 3, "hot": 4, "watch": 5}
    reasons.sort(key=lambda r: order[r["level"]])
    top = {"replace": ("failing", "replace"), "worse": ("worse",), "checking": ("checking",),
           "watch": ("watch",)}.get(verdict, ())
    said = [r["text"] for r in reasons if r["level"] in top]
    if verdict == "healthy":
        said = ["no errors"] + [x for x in (
            f"{v['power_on_hours']:,} hours on" if v.get("power_on_hours") is not None else "",
            f"{v['temperature']} °C" if v.get("temperature") is not None else "") if x]
        summary = ", ".join(said)
    else:
        summary = "; ".join(said)
    if hot:
        summary += "; too hot" if verdict != "healthy" else ", but too hot"
    return {"verdict": verdict, "words": WORDS[verdict], "severity": severity, "summary": summary,
            "reasons": reasons, "hot": hot, "quiet_on": quiet_on if verdict in ("checking", "worse") else None}


def settle(d, verdict, now):
    """Keep the verdict on the record, with when it changed. An alarm that ends in "watch" is
    marked, so the quiet line can say once that the alarm is off."""
    old = d.get("verdict") or {}
    if old.get("verdict") != verdict["verdict"]:
        verdict["since"] = now
        if old.get("verdict"):
            _event(d, now, "verdict", **{"from": old["verdict"], "to": verdict["verdict"]}, why=verdict["summary"][:200])
        if verdict["verdict"] == "watch" and old.get("verdict") in ALARMS:
            d["quiet_at"] = now
    else:
        verdict["since"] = old.get("since") or now
    if verdict["verdict"] != "watch":
        d.pop("quiet_at", None)
    d["verdict"] = verdict
    return verdict


# ------------------------------------------------------------------ the alert

def _advice(d, verdict):
    """What to do, in one or two sentences."""
    v = verdict["verdict"]
    name = d.get("device") or "DRIVE"
    if v == "replace" and verdict["severity"] == "critical":
        return "Copy your files off it now, then replace it."
    if v == "replace":
        return "It still works, but this doesn't get better: back up what's on it and replace it soon."
    if v == "worse":
        hint = ""
        if any(r.get("counter") == "media_errors" for r in verdict["reasons"]):
            hint = " A firmware fault can count errors like this too: look for an update for this model."
        return (f"Back up what's on it now and plan to replace it.{hint} If the count stops rising for "
                f"{QUIET_DAYS} days, this alarm goes quiet.")
    if v == "checking":
        return ("bromigOS can't tell yet whether the count is still rising. Make sure what's on it is backed up. "
                f"If nothing changes until {day(verdict['quiet_on'])}, this alarm goes quiet.")
    if v == "watch":
        return (f"Nothing to do while it stays that way. The alarm comes back if a count rises. "
                f"bromigos storage health {name} shows its history.")
    if v == "unknown":
        return "Connect it directly (SATA or NVMe) to have its health read."
    return "Nothing to do."


HOT_ADVICE = "Check that air reaches it and its fans turn: heat shortens a drive's life."


def _evidence_lines(d, r):
    v = d.get("readings") or {}
    ev = [f"Drive: {d['model']}, {r['device']}", f"Verdict: {d['verdict']['words']}"]
    if "passed" in v:
        ev.append(f"SMART overall-health self-assessment test result: {'PASSED' if v['passed'] else 'FAILED'}")
    if "critical_warning" in v:
        ev += [f"Critical Warning: 0x{v['critical_warning']:02x}",
               f"Available Spare: {v.get('spare', '?')}% (threshold {v.get('spare_threshold', '?')}%)",
               f"Percentage Used: {v.get('percent_used', '?')}%",
               f"Media and Data Integrity Errors: {v.get('media_errors', '?')}",
               f"Unsafe Shutdowns: {v.get('unsafe_shutdowns', '?')}"]
    for key, label in (("reallocated", "Reallocated_Sector_Ct"), ("pending", "Current_Pending_Sector"),
                       ("uncorrectable", "Offline_Uncorrectable"), ("reported_uncorrectable", "Reported_Uncorrect"),
                       ("crc_errors", "UDMA_CRC_Error_Count"), ("grown_defects", "Grown defect list")):
        if key in v:
            ev.append(f"{label}: {v[key]}")
    if "temperature" in v:
        ev.append(f"Temperature: {v['temperature']} Celsius")
    if "power_on_hours" in v:
        ev.append(f"Power On Hours: {v['power_on_hours']}")
    test = v.get("self_test")
    if test:
        ev.append(f"Last self-test: {test['type']}, {'passed' if test['passed'] else 'FAILED'} ({test['status']})")
    ev += [f"History: {x['text']}" for x in d["verdict"]["reasons"]]
    for e in (d.get("events") or [])[-6:]:
        ev.append(f"{stamp(e['t'])}  {event_words(e)}")
    return ev


def alert_for(d, r, verdict, now):
    """The alert a verdict raises, or None. Its id follows the drive, not its device name."""
    sev = verdict["severity"]
    if not sev:
        return None
    what = f"{d['model']} ({r['name']})"
    lead = what[0].upper() + what[1:]
    v = verdict["verdict"]
    hot_only = verdict["hot"] and v in ("healthy", "watch")
    said = "; ".join(x["text"] for x in verdict["reasons"]
                     if x["level"] != "watch" or v == "watch") or verdict["summary"]
    if hot_only:
        title = f"A drive is too hot: {what}"
        detail = f"{lead}: {said}. {HOT_ADVICE}"
    else:
        title = {"replace": f"A drive is failing: {what}" if sev == "critical" else f"Replace this drive soon: {what}",
                 "worse": f"A drive is getting worse: {what}", "checking": f"A drive has errors: {what}",
                 "watch": f"A drive to keep an eye on: {what}"}[v]
        note = ""
        if v == "watch" and d.get("quiet_at") is not None and now - d["quiet_at"] < NOTE_HOURS * 3600_000:
            note = "The alarm for this drive is off. "
        detail = f"{note}{lead}: {said}. {_advice(d, verdict)}" + (f" {HOT_ADVICE}" if verdict["hot"] else "")
    if d.get("silent_since"):
        detail += f" It hasn't answered since {day(d['silent_since'])}: this is its last reading."
    quiet = sev == "info"
    fix = None if quiet else {
        "commands": [f"bromigos storage health {r['name']}", f"sudo smartctl -a {r['device']}",
                     f"sudo smartctl -t short {r['device']}"],
        "touches": ["nothing (it reads the drive's records and runs its own 2-minute self-test)"],
        "from": "bromigos", "root": True,
        "note": "Back up first: Field Kit's Back up my files copies every home folder to a USB drive."}
    a = alert("disk.smart", r["name"], sev, title, detail, "SMART",
              actions=[{"kind": "open"}] if quiet else None,
              evidence=evidence(_evidence_lines(d, r), model=d["model"], device=r["device"],
                                serial_tail=d.get("serial_tail") or "", firmware=d.get("firmware") or "",
                                verdict=v, drive=d["key"]),
              fix=fix)
    a["id"] = f"disk.smart:{d['key']}"
    return a


def check(ctx):
    """`bromigos alerts`' disk.smart: read the drives, keep the history, alert by verdict."""
    env = ctx.env
    now = env.now_ms()
    readings = scan(env)
    history = load(env)
    found, present = [], set()
    for r in readings:
        key = same_drive(history, r)
        if key in present:        # one drive listed twice (two paths to it)
            continue
        present.add(key)
        d = observe(history, r, now)
        # a drive that stopped answering keeps the verdict of its last reading
        verdict = d["verdict"] if d.get("silent_since") and d.get("verdict") else settle(d, judge(d, now), now)
        a = alert_for(d, r, verdict, now)
        if a:
            found.append(a)
    for key, d in history["drives"].items():
        d["present"] = key in present
    _trim(history)
    history["checked_at"] = now
    try:
        save(env, history)
    except OSError as e:
        raise Failed(f"can't write the drives' history ({env.path(HISTORY)}): {e}")
    return found


# ------------------------------------------------------------------ reading it back

RULES = {"quiet_days": QUIET_DAYS, "sustained_days": SUSTAINED_DAYS, "worn_percent": WORN_PERCENT,
         "spent_percent": SPENT_PERCENT, "max_samples": MAX_SAMPLES, "max_drives": MAX_DRIVES}


def event_words(e):
    kind = e.get("kind")
    if kind == "first_seen":
        return "its history begins"
    if kind == "firmware":
        return f"firmware changed from {e.get('from')} to {e.get('to')}"
    if kind == "verdict":
        words = f"{WORDS.get(e.get('from'), e.get('from'))} became {WORDS.get(e.get('to'), e.get('to'))}"
        if e.get("to") == "watch" and e.get("from") in ALARMS:
            words += " (the alarm went quiet)"
        return words + (f": {e['why']}" if e.get("why") else "")
    if kind == "silent":
        return "it stopped answering; its last verdict stands"
    if kind in ("fell", "cleared"):
        words = COUNTERS.get(e.get("counter"), ("", e.get("counter") or "a count"))[1]
        return f"{words} went from {e.get('from'):,} down to {e.get('to'):,}"
    return str(kind)


def report(env, samples=False):
    """Every drive the history knows, connected ones first and worst first: the document
    `bromigos storage health --json` prints. The verdicts are the last check's."""
    history = load(env)
    drives = []
    for d in history["drives"].values():
        verdict = d.get("verdict") or {"verdict": "unknown", "words": WORDS["unknown"], "severity": None,
                                       "summary": "", "reasons": []}
        row = {"key": d["key"], "device": d.get("device") or "", "model": d.get("model") or "A drive",
               "serial_tail": d.get("serial_tail") or "", "firmware": d.get("firmware") or "",
               "kind": d.get("kind") or "", "present": bool(d.get("present")), "reports": bool(d.get("reports")),
               "stable_identity": bool(d.get("stable_identity")), "first_seen": d.get("first_seen"),
               "last_seen": d.get("last_seen"), "silent_since": d.get("silent_since"),
               "verdict": verdict["verdict"], "words": verdict["words"],
               "alert": verdict.get("severity"), "since": verdict.get("since"), "summary": verdict.get("summary") or "",
               "reasons": verdict.get("reasons") or [], "advice": _advice(d, verdict) if verdict.get("verdict") else "",
               "quiet_on": verdict.get("quiet_on"), "readings": d.get("readings") or {}, "trend": d.get("trend") or {},
               "events": d.get("events") or []}
        if verdict.get("hot"):
            row["advice"] = (row["advice"] + " " + HOT_ADVICE).strip()
        if samples:
            row["samples"] = d.get("samples") or []
        drives.append(row)
    drives.sort(key=lambda r: (not r["present"], -RANK.get(r["verdict"], 0), r["device"], r["key"]))
    return {"schema": SCHEMA, "checked_at": history.get("checked_at"), "history": env.path(HISTORY),
            "rules": RULES, "drives": drives}


class NoSuchDrive(Exception):
    pass


def find(doc, word):
    """The one drive `word` names: its device name (nvme0, /dev/nvme0), its key, or part of
    its model or key. Connected drives win over ones that are gone."""
    w = word.strip().lower()
    w = w[5:] if w.startswith("/dev/") else w
    drives = doc["drives"]
    for exact in (lambda d: d["present"] and d["device"].lower() == w, lambda d: d["key"] == w,
                  lambda d: d["device"].lower() == w):
        hit = [d for d in drives if exact(d)]
        if len(hit) == 1:
            return hit[0]
    hit = [d for d in drives if w and (w in d["model"].lower() or w in d["key"])]
    if len(hit) > 1 and len([d for d in hit if d["present"]]) == 1:
        hit = [d for d in hit if d["present"]]
    if len(hit) == 1:
        return hit[0]
    if not hit:
        raise NoSuchDrive(f"No drive matches {word!r}. bromigos storage health lists them.")
    raise NoSuchDrive(f"{word!r} matches {len(hit)} drives: " + ", ".join(d["device"] or d["key"] for d in hit)
                      + ". Use a device name or a key.")


def _ago(ms):
    s = max(0, int(ms // 1000))
    for n, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if s >= n:
            return f"{s // n} {unit} ago"
    return "just now"


NOT_YET = ("No drive health has been recorded yet. The system checks read the drives every 15 minutes "
           "(bromigos-alerts.timer); `sudo bromigos alerts check --system --only disk.smart` reads them now.")


def _label(d):
    return f"{d['model']} ({d['device']})" if d["device"] else d["model"]


def plain(doc, now):
    """One line per drive."""
    if doc.get("checked_at") is None or not doc["drives"]:
        return NOT_YET
    here = [d for d in doc["drives"] if d["present"]]
    gone = [d for d in doc["drives"] if not d["present"]]
    width = max([len(_label(d)) for d in here] + [10])
    words = max([len(d["words"]) for d in here] + [7])
    lines = [f"Drive health, read {_ago(now - doc['checked_at'])}", ""]
    for d in here:
        silent = f"; it hasn't answered since {day(d['silent_since'])}" if d.get("silent_since") else ""
        lines.append(f"  {_label(d):<{width}}  {d['words']:<{words}}  {d['summary']}{silent}".rstrip())
    if not here:
        lines.append("  No drive answered the last check.")
    if gone:
        lines += ["", "Not connected now:"]
        lines += [f"  {_label(d)}, last seen {day(d['last_seen'])}, then: {d['words']}" for d in gone]
    lines += ["", "bromigos storage health DRIVE shows one drive's readings over time (DRIVE: "
                  + (here or gone)[0]["device"] + ", or part of a model)."]
    return "\n".join(lines)


# the detail view's rows and the table's columns: (key, row label, column label)
FIELDS = (("media_errors", "Media errors", "Media"), ("reallocated", "Reallocated sectors", "Realloc"),
          ("pending", "Sectors it can't read", "Pending"), ("uncorrectable", "Uncorrectable sectors", "Uncorr"),
          ("reported_uncorrectable", "Uncorrectable errors", "Reported"), ("grown_defects", "Grown defects", "Defects"),
          ("crc_errors", "Cable (CRC) errors", "CRC"), ("spare", "Spare space", "Spare"),
          ("percent_used", "Rated life used", "Used"), ("critical_warning", "Critical warning", "Warning"),
          ("unsafe_shutdowns", "Unsafe shutdowns", "Unsafe"), ("temperature", "Temperature", "Temp"),
          ("power_on_hours", "Power-on hours", "Hours"), ("self_test", "Last self-test", "Self-test"))


def _cell(key, v, values=None, short=False):
    if v is None:
        return "-"
    if key == "spare":
        limit = (values or {}).get("spare_threshold")
        return f"{v}%" if short or limit is None else f"{v}% (the drive's own threshold: {limit}%)"
    if key == "percent_used":
        return f"{v}%"
    if key == "critical_warning":
        return "none" if not v else f"0x{v:02x}"
    if key == "temperature":
        return f"{v} °C"
    if key == "self_test":
        if short:
            return "passed" if v.get("passed") else "FAILED"
        at = f", at {v['hours']:,} h" if v.get("hours") is not None else ""
        return f"{v.get('type')}, {'passed' if v.get('passed') else 'FAILED: ' + (v.get('status') or '?')}{at}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def detail(d, now, every=False):
    """One drive: its verdict, what to do, the newest reading, what happened, and the readings
    over time as a table."""
    head = _label(d) + (f", serial ends {d['serial_tail']}" if d["serial_tail"] else "") \
        + (f", firmware {d['firmware']}" if d["firmware"] else "")
    lines = [head, f"{d['words']}: {d['summary']}" if d["summary"] else d["words"]]
    if d["advice"]:
        lines.append(f"What to do: {d['advice']}")
    if not d["present"]:
        lines.append(f"Not connected now. Last seen {day(d['last_seen'])}; this is how it stood then.")
    if d.get("silent_since"):
        lines.append(f"It hasn't answered since {day(d['silent_since'])}: this is its last reading.")
    if not d["stable_identity"]:
        lines.append("It gives no serial number, so its history follows its device name.")
    v = d["readings"]
    if v:
        lines += ["", "Now" if d["present"] else "Last reading"]
        if "passed" in v:
            lines.append(f"  {'Its own health check':<24}{'passed' if v['passed'] else 'FAILED'}")
        for key, label, _ in FIELDS:
            if key in v:
                lines.append(f"  {label:<24}{_cell(key, v[key], v)}")
        for key in ("prefail_now", "oldage_now", "failed_before"):
            if v.get(key):
                lines.append(f"  {'Past its threshold' + (' before' if key == 'failed_before' else ' now'):<24}"
                             f"{', '.join(v[key])}")
    if d["events"]:
        lines += ["", "What happened"]
        lines += [f"  {stamp(e['t'])}  {event_words(e)}" for e in d["events"]]
    samples = d.get("samples") or []
    if samples:
        cols = [(k, short) for k, _, short in FIELDS if any(k in s for s in samples)]
        shown = samples if every else samples[-30:]
        rows = [["When"] + [short for _, short in cols]]
        rows += [[stamp(s["t"])] + [_cell(k, s.get(k), s, short=True) for k, _ in cols] for s in shown]
        widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
        lines += ["", f"Readings over time (one a day, and one at each change; {len(samples)} kept, "
                      f"{MAX_SAMPLES} at most)"]
        if len(shown) < len(samples):
            lines.append(f"  the newest {len(shown)}; --all shows every one")
        for r in rows:
            lines.append("  " + "  ".join(c.ljust(w) if i == 0 else c.rjust(w)
                                          for i, (c, w) in enumerate(zip(r, widths))).rstrip())
    return "\n".join(lines)
