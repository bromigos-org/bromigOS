"""Den TV's bumps (lib/bromigos_bumps.py, live/live/tvbumps.py): a fixture pack, stand-in
players, sandboxed state; no GPU, no desktop, no network.

    cd live && python -m unittest tests.test_tv_bumps

- the packs: found by name, the first of a name wins, a clip outside its pack or missing left out;
- the night block across midnight, its first bump (open) and the sign-off (close) once a night;
- the caps: off, `bromigos mascot off`, night only, the spacing, the night's maximum, never the
  same bump twice in a row, tune bumps short;
- on a den screen: between items the channel waits for the bump (nothing missed), screens on the
  same channel share it, no sound of its own, no "BACK TO CHANNEL" at its end, skip
  ends it, a caption over it; a channel change gets one once it settles, never while flicking
  through; nothing when the screen can't be seen (covered, locked, VECTOR speaking, reduced motion);
- full screen: a bump between two items, the channel held for it;
- `bromigos-live tv bumps` and `tv bump`.
"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_tv_screens as S  # noqa: E402  (the sandboxed paths come first)

import bromigos_bumps as B  # noqa: E402
import bromigos_tv as TV  # noqa: E402


def make_pack(root, name="static", bumps=None):
    folder = os.path.join(root, name)
    os.makedirs(os.path.join(folder, "clips"), exist_ok=True)
    bumps = bumps if bumps is not None else [
        {"id": "still-lit", "file": "clips/still-lit.mp4", "seconds": 7.0, "roles": ["open"], "caption": "STILL LIT"},
        {"id": "right-back", "file": "clips/right-back.mp4", "seconds": 6.0, "roles": ["between"],
         "caption": "BACK IN A MOMENT"},
        {"id": "crew", "file": "clips/crew.mp4", "seconds": 9.0, "roles": ["between"]},
        {"id": "signal-in", "file": "clips/signal-in.mp4", "seconds": 5.0, "roles": ["tune", "between"]},
        {"id": "sign-off", "file": "clips/sign-off.mp4", "seconds": 8.0, "roles": ["close"]},
    ]
    for b in bumps:
        if ".." not in b["file"]:
            with open(os.path.join(folder, b["file"]), "wb") as f:
                f.write(b"\0")
    with open(os.path.join(folder, "bumps.json"), "w") as f:
        json.dump({"schema": 1, "pack": name, "title": "Test pack", "bumps": bumps}, f)
    return folder


class Zone:
    """The tests' clock in one time zone, so the night block's hours are known."""
    def __init__(self, t, tz="UTC"):
        self.tz = tz

    def __enter__(self):
        self.old = os.environ.get("TZ")
        os.environ["TZ"] = self.tz
        time.tzset()

    def __exit__(self, *a):
        if self.old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.old
        time.tzset()


def at(hh, mm=0, day=1):
    """2026-11-<day> hh:mm UTC."""
    return 1793491200.0 + (day - 1) * 86400 + hh * 3600 + mm * 60      # 2026-11-01T00:00:00Z


class Packs(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="bromigos-bumps-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.env = {"HOME": self.root, "XDG_DATA_HOME": os.path.join(self.root, "data"),
                    "XDG_CONFIG_HOME": os.path.join(self.root, "config")}

    def test_found_by_name_and_bad_entries_left_out(self):
        mine = make_pack(os.path.join(self.root, "data", "bromigos", "bumps"), "static")
        make_pack(os.path.join(self.root, "other"), "static", [{"id": "x", "file": "clips/x.mp4", "seconds": 5}])
        bad = [{"id": "escape", "file": "../../etc/passwd", "seconds": 5},
               {"id": "missing", "file": "clips/none.mp4", "seconds": 5},
               {"id": "long", "file": "clips/long.mp4", "seconds": 600},
               {"id": "ok", "file": "clips/ok.mp4", "seconds": 5}]
        make_pack(os.path.join(self.root, "data", "bromigos", "bumps"), "extra", bad)
        os.remove(os.path.join(self.root, "data", "bromigos", "bumps", "extra", "clips", "none.mp4"))
        env = dict(self.env, BROMIGOS_BUMPS=os.path.join(self.root, "other", "static"))
        ps = {p.name: p for p in B.packs(env)}
        self.assertEqual(ps["static"].folder, os.path.join(self.root, "other", "static"), "BROMIGOS_BUMPS first")
        self.assertEqual([b.id for b in ps["extra"].bumps], ["extra/ok"])
        self.assertTrue(os.path.isdir(mine))

    def test_settings_checked(self):
        s = B.settings({"tv": {"bumps": {"mode": "loud", "night": "25:00-01:00", "every": -1, "max": "x",
                                         "packs": ["static"]}}})
        self.assertEqual((s["mode"], s["night"], s["every"], s["max"], s["packs"]),
                         ("night", "22:00-04:00", 20, 10, ["static"]))
        self.assertEqual(B.settings({"tv": {"bumps": {"enabled": False}}})["mode"], "off")

    def test_mascot_off_turns_them_off(self):
        os.makedirs(os.path.join(self.root, "config", "bromigos"))
        with open(os.path.join(self.root, "config", "bromigos", "mascot.toml"), "w") as f:
            f.write('mode = "off"\n')
        self.assertTrue(B.mascot_off(self.env))
        self.assertFalse(B.mascot_off(dict(self.env, BROMIGOS_MASCOT="quiet")))


class Night(unittest.TestCase):
    def setUp(self):
        root = tempfile.mkdtemp(prefix="bromigos-bumps-")
        self.addCleanup(shutil.rmtree, root, True)
        self.bumps = B.packs({"BROMIGOS_BUMPS": make_pack(root), "HOME": root})[0].bumps
        self.env = {"HOME": root, "BROMIGOS_MASCOT": "on"}
        self.rng = random.Random(7)

    def choose(self, kind, t, cfg, st):
        return B.choose(kind, t, cfg, st, self.bumps, self.rng, self.env)

    def test_the_night_block_runs_past_midnight(self):
        with Zone(0):
            self.assertEqual(B.night(at(23, 30), "22:00-04:00"), "2026-11-01")
            self.assertEqual(B.night(at(3, 59, day=2), "22:00-04:00"), "2026-11-01")
            self.assertIsNone(B.night(at(4, 0, day=2), "22:00-04:00"))
            self.assertIsNone(B.night(at(12), "22:00-04:00"))
            self.assertEqual(B.night(at(1), "00:30-02:00"), "2026-11-01")
            self.assertEqual(B.just_ended(at(4, 30, day=2), "22:00-04:00"), "2026-11-01")
            self.assertIsNone(B.just_ended(at(9, day=2), "22:00-04:00"))

    def test_open_first_then_spaced_then_capped(self):
        cfg = {"tv": {"bumps": {"every_night": 10, "max": 3}}}
        with Zone(0):
            self.assertIsNone(self.choose("between", at(20), cfg, {}), "night only, by default")
            b, role = self.choose("between", at(22, 5), cfg, {})
            self.assertEqual((b.id, role), ("static/still-lit", "open"))
            st = B.record({}, b, role, at(22, 5), cfg)
            self.assertIsNone(self.choose("between", at(22, 6), cfg, st), "never two within two minutes")
            self.assertIsNone(self.choose("between", at(22, 12), cfg, st), "every_night: 10 minutes apart")
            b, role = self.choose("between", at(22, 16), cfg, st)
            self.assertEqual(role, "between")
            st = B.record(st, b, role, at(22, 16), cfg)
            b2, _ = self.choose("between", at(22, 27), cfg, st)
            self.assertNotEqual(b2.id, b.id, "never the same bump twice in a row")
            st = B.record(st, b2, "between", at(22, 27), cfg)
            self.assertIsNone(self.choose("between", at(23, 50), cfg, st), "max: three a night")
            self.assertEqual(B.count_key(at(1, day=2), cfg), "2026-11-01", "after midnight is still tonight")

    def test_the_sign_off_once_after_the_block(self):
        cfg = {"tv": {"bumps": {}}}
        with Zone(0):
            st = {"opened": "2026-11-01", "last": at(3, 50, day=2), "last_between": at(3, 50, day=2)}
            b, role = self.choose("between", at(4, 10, day=2), cfg, st)
            self.assertEqual((b.id, role), ("static/sign-off", "close"))
            st = B.record(st, b, role, at(4, 10, day=2), cfg)
            self.assertEqual(st["closed"], "2026-11-01")
            self.assertIsNone(self.choose("between", at(4, 40, day=2), cfg, st), "once; then nothing by day")

    def test_always_off_and_tune(self):
        with Zone(0):
            always = {"tv": {"bumps": {"mode": "always", "every": 20, "tune_every": 30}}}
            b, role = self.choose("between", at(12), always, {"opened": "x"})
            self.assertEqual(role, "between")
            self.assertIsNone(self.choose("between", at(12), {"tv": {"bumps": {"mode": "off"}}}, {}))
            b, role = self.choose("tune", at(12), always, {})
            self.assertEqual((b.id, role), ("static/signal-in", "tune"), "only short ones cover a tune")
            st = B.record({}, b, role, at(12), always)
            self.assertIsNone(self.choose("tune", at(12, 20), always, st), "tune_every: 30 minutes")
            self.assertIsNone(B.choose("between", at(23), always, {}, self.bumps, self.rng, {"BROMIGOS_MASCOT": "off"}))


@unittest.skipUnless(S.livetv is not None, getattr(S, "WHY", "needs PyOpenGL"))
class Den(unittest.TestCase):
    def setUp(self):
        S.sandbox(self)
        root = tempfile.mkdtemp(prefix="bromigos-bumps-den-")
        self.addCleanup(shutil.rmtree, root, True)
        for k, v in (("STATE", os.path.join(root, "tv-bumps.json")),):
            p = mock.patch.object(B, k, v)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"BROMIGOS_BUMPS": make_pack(root), "BROMIGOS_MASCOT": "on"})
        p.start()
        self.addCleanup(p.stop)
        cfg = {"tv": {"channel": [S.files_channel("Clips", "any")],
                      "bumps": {"mode": "always", "every": 0, "tune_every": 0}}}
        self.tv = S.make_tv(self, cfg)
        self.tv.stop.set()
        self.tv.bump_rng = random.Random(3)
        self.tv.rects = {"big": (100, 100, 200, 175), "wave": (450, 150, 124, 110), "emblem": (200, 400, 158, 143)}
        self.tv.px = dict(self.tv.rects)
        for d in self.tv.decks.values():
            d.player = S.Player()
        sub = mock.patch.object(self.tv, "_submap")
        sub.start()
        self.addCleanup(sub.stop)

    def boundary(self, screen="big"):
        """The screen on channel 2, its first item loaded, the clock just past the second's start."""
        tv = self.tv
        tv.tune_to(screen, 2)
        tv._tune_pending.clear()
        n, ch = tv.channel(screen)
        d = tv.decks[screen]
        d.allowed, d.tune = True, None
        slot = tv.slot(ch)
        d.loaded = (ch["key"], "previous-item")
        return d, ch, TV.Slot(slot, offset=0.5)

    def test_between_items_the_channel_waits_for_the_bump(self):
        tv = self.tv
        d, ch, slot = self.boundary()
        before = TV.channel_offset(ch)
        tv._ensure_loaded(d, ch, slot)
        o = tv.bumping("big")
        self.assertIsNotNone(o, "a bump between items")
        self.assertAlmostEqual(TV.channel_offset(ch), before - o["bump"].seconds - 0.5, places=3)
        self.assertIsNone(d.tune, "no tuning static under a bump")
        self.assertEqual(tv.describe()["screens"]["big"]["bump"], o["item"]["id"])
        self.assertFalse(tv.describe()["screens"]["big"]["on_demand"])
        n, bch = tv.channel("big")
        tv.screens["big"]["sound"] = True
        tv._ensure_loaded(d, bch, tv.slot(bch))
        load = d.player.loads[-1]
        self.assertEqual(load["url"], o["bump"].path)
        self.assertIsNone(load.get("audio"), "a bump has no sound of its own")
        self.assertEqual(load.get("start"), 0.0)
        d.player.ended = ("eof", None)
        tv._check_failure(d, bch, tv.slot(bch))
        self.assertIsNone(tv.bumping("big"))
        self.assertIsNone(d.feedback, "a bump's end is just the channel again")

    def test_nothing_where_nobody_can_see_it(self):
        tv = self.tv
        for setup in (lambda d: setattr(d, "allowed", False), lambda d: setattr(tv, "quiet", True),
                      lambda d: setattr(tv, "ducked", True), lambda d: setattr(tv, "motion", "reduced"),
                      lambda d: setattr(d, "capped", True)):
            tv.quiet = tv.ducked = False
            tv.motion = "full"
            d, ch, slot = self.boundary()
            d.capped = False
            setup(d)
            tv._ensure_loaded(d, ch, slot)
            self.assertIsNone(tv.bumping("big"))
        tv.quiet, tv.motion = False, "full"
        d, ch, slot = self.boundary()
        tv._ensure_loaded(d, ch, TV.Slot(slot, offset=40.0))
        self.assertIsNone(tv.bumping("big"), "mid-item is not between items")

    def test_screens_on_the_channel_share_it(self):
        tv = self.tv
        tv.tune_to("wave", 2)
        d, ch, slot = self.boundary("big")
        tv._ensure_loaded(d, ch, slot)
        self.assertIsNotNone(tv.bumping("wave"))
        self.assertEqual(tv.channel("big")[1]["key"], tv.channel("wave")[1]["key"], "one player for both")

    def test_skip_and_tune_end_it(self):
        tv = self.tv
        d, ch, slot = self.boundary()
        tv._ensure_loaded(d, ch, slot)
        self.assertIn("skipped", tv.skip_item("big"))
        self.assertIsNone(tv.bumping("big"))
        tv.bump_now("big", "crew")
        self.assertIsNotNone(tv.bumping("big"))
        tv.tune_to("big", step=1)
        self.assertIsNone(tv.bumping("big"))

    def test_a_tune_gets_one_once_it_settles(self):
        tv = self.tv
        tv.decks["big"].allowed = True
        tv.tune_to("big", 2)
        tv.bumps_tick()
        self.assertIsNone(tv.bumping("big"), "not at once")
        tv.tune_to("big", 1)                                   # flicking: channel 1 is the screen's own
        tv.tune_to("big", 2)
        when, key = tv._tune_pending["big"]
        tv._tune_pending["big"] = (when - 2, key)
        tv.bumps_tick()
        o = tv.bumping("big")
        self.assertEqual((o["role"], o["bump"].id), ("tune", "static/signal-in"))
        self.assertEqual(TV.channel_offset(o["channel"]), 0.0, "a tune holds nothing: it's live")

    def test_caption(self):
        tv = self.tv
        tv.tune_to("big", 2)
        tv.bump_now("big", "right-back")
        o = tv.bumping("big")
        self.assertIsNone(tv.bump_caption("big"), "not in the first moment")
        o["at"] -= 2.0
        cap = tv.bump_caption("big")
        self.assertEqual(cap[:3], ("bump", "BACK IN A MOMENT", "Clips"))
        o["at"] -= 10.0
        self.assertIsNone(tv.bump_caption("big"), "gone before the end")

    def test_full_screen_holds_the_channel(self):
        tv = self.tv
        tv.tune_to("big", 2)
        n, ch = tv.channel("big")
        before = TV.channel_offset(ch)
        b = tv.full_bump("big")
        self.assertIsNotNone(b)
        self.assertAlmostEqual(TV.channel_offset(ch), before - b.seconds, places=3)
        self.assertTrue(os.path.isfile(B.STATE), "the cap is remembered")

    def test_commands(self):
        tv = self.tv
        doc = json.loads(tv.command("bumps"))
        self.assertEqual(doc["mode"], "always")
        self.assertEqual(doc["packs"][0]["bumps"], 5)
        self.assertIn("tune a channel first", tv.command("bump --screen big"))
        tv.tune_to("big", 2)
        self.assertIn("static/crew", tv.command("bump crew --screen big"))
        self.assertIn("No bump called", tv.command("bump nope --screen big"))


if __name__ == "__main__":
    unittest.main()
