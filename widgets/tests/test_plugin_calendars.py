"""plugins/calendars.py: ICS parsing (time zones, UTC, floating times, all-day events),
repeating events (RRULE, EXDATE, RDATE, a moved instance), the calendars setting, the
sources (a file, a folder), and the empty states. Parsing needs python-icalendar; those
tests are skipped without it."""
import datetime as dt
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import plugintest as PT  # noqa: E402  (before the plugin: a throwaway config home)

_spec = importlib.util.spec_from_file_location("calendars", os.path.join(HERE, "plugins", "calendars.py"))
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

from dateutil import tz as dtz  # noqa: E402

HAVE_ICAL = C.icalendar_module() is not None
NEEDS_ICAL = unittest.skipUnless(HAVE_ICAL, "python-icalendar isn't installed: the ICS parsing tests are skipped")
NY = dtz.gettz("America/New_York")
UTC = dt.timezone.utc


def ics(*events, tzdef=True):
    vtz = ("BEGIN:VTIMEZONE\r\nTZID:America/New_York\r\nBEGIN:STANDARD\r\nDTSTART:19701101T020000\r\n"
           "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU\r\nTZOFFSETFROM:-0400\r\nTZOFFSETTO:-0500\r\nEND:STANDARD\r\n"
           "BEGIN:DAYLIGHT\r\nDTSTART:19700308T020000\r\nRRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU\r\n"
           "TZOFFSETFROM:-0500\r\nTZOFFSETTO:-0400\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n") if tzdef else ""
    body = "".join("BEGIN:VEVENT\r\n" + "\r\n".join(e) + "\r\nEND:VEVENT\r\n" for e in events)
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n" + vtz + body + "END:VCALENDAR\r\n").encode()


def ts(*a, tzinfo=UTC):
    return dt.datetime(*a, tzinfo=tzinfo).timestamp()


LO, HI = ts(2026, 10, 1), ts(2026, 11, 30)


@NEEDS_ICAL
class Parse(unittest.TestCase):
    def test_tzid_utc_and_floating(self):
        data = ics(["UID:a", "SUMMARY:NY call", "DTSTART;TZID=America/New_York:20261012T090000",
                    "DTEND;TZID=America/New_York:20261012T100000", "LOCATION:https://meet.example.org/x"],
                   ["UID:b", "SUMMARY:UTC", "DTSTART:20261012T150000Z", "DTEND:20261012T153000Z"],
                   ["UID:c", "SUMMARY:Floating", "DTSTART:20261012T080000", "DTEND:20261012T083000"])
        evs = {e["uid"]: e for e in C.parse(data, lo=LO, hi=HI, tz=NY)}
        self.assertEqual(evs["a"]["start"], ts(2026, 10, 12, 13))              # 09:00 EDT = 13:00 UTC
        self.assertEqual(evs["a"]["end"] - evs["a"]["start"], 3600)
        self.assertEqual(evs["b"]["start"], ts(2026, 10, 12, 15))
        self.assertEqual(evs["c"]["start"], ts(2026, 10, 12, 8, tzinfo=NY))    # floating: local time
        self.assertEqual(C.link_of(evs["a"]), "https://meet.example.org/x")
        self.assertIsNone(C.link_of(evs["b"]))

    def test_all_day(self):
        data = ics(["UID:d", "SUMMARY:Trip", "DTSTART;VALUE=DATE:20261020", "DTEND;VALUE=DATE:20261023"],
                   ["UID:e", "SUMMARY:Holiday", "DTSTART;VALUE=DATE:20261026"])
        evs = {e["uid"]: e for e in C.parse(data, lo=LO, hi=HI, tz=NY)}
        self.assertTrue(evs["d"]["all_day"])
        self.assertEqual(evs["d"]["start"], ts(2026, 10, 20, tzinfo=NY))
        self.assertEqual(C.when(evs["d"]), "all day, 3 days")
        self.assertEqual(evs["e"]["end"] - evs["e"]["start"], 86400)          # no DTEND: one day

    def test_weekly_rule_with_exdate_rdate_and_a_moved_instance(self):
        data = ics(["UID:w", "SUMMARY:Stand-up", "DTSTART;TZID=America/New_York:20261005T093000",
                    "DURATION:PT15M", "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=6",
                    "EXDATE;TZID=America/New_York:20261019T093000",
                    "RDATE;TZID=America/New_York:20261021T093000"],
                   ["UID:w", "SUMMARY:Stand-up (moved)", "RECURRENCE-ID;TZID=America/New_York:20261026T093000",
                    "DTSTART;TZID=America/New_York:20261027T110000", "DTEND;TZID=America/New_York:20261027T111500"])
        evs = [e for e in C.parse(data, lo=LO, hi=HI, tz=NY) if e["uid"] == "w"]
        days = [dt.datetime.fromtimestamp(e["start"], NY).strftime("%m-%d %H:%M") for e in evs]
        self.assertEqual(days, ["10-05 09:30", "10-12 09:30", "10-21 09:30", "10-27 11:00", "11-02 09:30",
                                "11-09 09:30"])                          # 19th out, 21st in, 26th moved
        self.assertEqual(evs[-1]["start"], ts(2026, 11, 9, 14, 30))           # after DST ends: 09:30 EST
        self.assertEqual(evs[0]["end"] - evs[0]["start"], 900)

    def test_until_in_the_wrong_form_both_ways(self):
        data = ics(["UID:u1", "SUMMARY:Aware, UNTIL a date", "DTSTART;TZID=America/New_York:20261001T100000",
                    "DTEND;TZID=America/New_York:20261001T103000", "RRULE:FREQ=DAILY;UNTIL=20261003"],
                   ["UID:u2", "SUMMARY:All day, UNTIL in UTC", "DTSTART;VALUE=DATE:20261010",
                    "RRULE:FREQ=DAILY;UNTIL=20261012T000000Z"])
        evs = C.parse(data, lo=LO, hi=HI, tz=NY)
        self.assertEqual(len([e for e in evs if e["uid"] == "u1"]), 3)
        self.assertEqual(len([e for e in evs if e["uid"] == "u2"]), 2)          # 10th, 11th (midnight UTC = 11th, 20:00)

    def test_cancelled_and_out_of_window(self):
        data = ics(["UID:x", "SUMMARY:Off", "STATUS:CANCELLED", "DTSTART:20261012T150000Z"],
                   ["UID:y", "SUMMARY:Long ago", "DTSTART:20200101T150000Z", "DTEND:20200101T160000Z"])
        self.assertEqual(C.parse(data, lo=LO, hi=HI, tz=NY), [])

    def test_folder_of_files(self):
        d = tempfile.mkdtemp()
        for i in range(3):
            with open(os.path.join(d, f"{i}.ics"), "wb") as f:
                f.write(ics([f"UID:f{i}", f"SUMMARY:Event {i}",
                             "DTSTART:%sT150000Z" % (dt.date.today() + dt.timedelta(days=i + 1)).strftime("%Y%m%d")],
                            tzdef=False))
        with open(os.path.join(d, "notes.txt"), "w") as f:
            f.write("not a calendar")
        s = C.Sources()
        got = s.refresh(C.calendars_of([{"source": d, "name": "Home", "colour": "#58a6ff"}]))
        self.assertEqual([e["title"] for e in got["events"]], ["Event 0", "Event 1", "Event 2"])
        self.assertEqual({e["colour"] for e in got["events"]}, {"#58a6ff"})
        self.assertEqual(got["errors"], {})
        again = s.refresh(C.calendars_of([d]))
        self.assertEqual(len(again["events"]), 3)


class Setting(unittest.TestCase):
    def test_calendars_of(self):
        cals = C.calendars_of(["webcal://cal.example.org/team/basic.ics", "~/calendars/home",
                               {"url": "https://x.example.org/c.ics", "name": "Work", "color": "#ff0000"}, {}, 7])
        self.assertEqual([c["name"] for c in cals], ["basic", "home", "Work"])
        self.assertEqual(cals[2]["colour"], "#ff0000")
        self.assertEqual(C.https_url(cals[0]["source"]), "https://cal.example.org/team/basic.ics")
        self.assertEqual(C.calendars_of("~/one.ics")[0]["source"], "~/one.ics")

    def test_missing_file_is_an_error_not_a_crash(self):
        if not HAVE_ICAL:
            self.skipTest("python-icalendar isn't installed")
        got = C.Sources().refresh(C.calendars_of(["/nonexistent/cal.ics"]))
        self.assertIn("no file", next(iter(got["errors"].values())))

    def test_countdown(self):
        e = {"start": 1000.0, "end": 4600.0, "all_day": False}
        self.assertEqual(C.countdown(e, now=400), "in 10m")
        self.assertEqual(C.countdown(e, now=1600), "now · ends in 50m")


class Panel(unittest.TestCase):
    def test_empty_state_says_where_to_add_calendars(self):
        p = PT.make(C.CalendarPanel)
        tips = PT.draw(p, 440, 300)
        self.assertTrue(any("calendars.toml" in t for t in tips), tips)

    def test_missing_icalendar_says_so(self):
        p = PT.make(C.CalendarPanel)
        p.cals = lambda: [{"source": "x.ics", "name": "x", "colour": "phosphor"}]
        real = C.icalendar_module
        C.icalendar_module = lambda: None
        try:
            p.poll.run_once()
        finally:
            C.icalendar_module = real
        tips = PT.draw(p, 440, 300)
        self.assertTrue(any("python-icalendar" in t for t in tips), tips)

    def test_every_size_class_draws_with_hints(self):
        PT.every_class(self, PT.make(C.CalendarPanel, demo=True))


if __name__ == "__main__":
    unittest.main()
