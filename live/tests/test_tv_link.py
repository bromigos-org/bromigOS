"""Linked channels (live/live/tvlink.py): the feed path's rules, the feed's parsing, the
party sync's correction, the commands, `tv state` without the address or the token, and
the overlay drawn for a linked screen. Sandbox state and fake players; never a window."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_tv_screens as S

from live import tvlink as L  # noqa: E402

TOKEN = "Bearer s3cr3t-viewer-token"
HLS = "http://100.64.0.7:8888/live-abcdefghij/index.m3u8"


def feed(**kw):
    f = {"version": 1, "screen": "big", "badge": "LIVE · MOVIE NIGHT", "title": "Night Shift",
         "video": {"hls": HLS, "authorization": TOKEN},
         "people": [{"name": "kestrel", "face": "f3", "speaking": True},
                    {"name": "wren", "face": "f1", "speaking": True},
                    {"name": "sable", "face": "f2"},
                    {"name": "KESTREL · LIVING ROOM TV", "face": "", "endpoint": True}],
         "voice": True, "mic": False}
    f.update(kw)
    return f


class Runtime:
    """A throwaway $XDG_RUNTIME_DIR for one test."""
    def setUp(self):
        self.run = tempfile.mkdtemp(prefix="bromigos-link-run-")
        self.addCleanup(shutil.rmtree, self.run, True)
        os.chmod(self.run, 0o700)
        p = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.run})
        p.start()
        self.addCleanup(p.stop)

    def write(self, data, name="link-big.json", mode=0o600):
        os.makedirs(os.path.join(self.run, "bromigos-live"), exist_ok=True)
        path = os.path.join(self.run, "bromigos-live", name)
        with open(path, "w") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        os.chmod(path, mode)
        return path


class FeedPath(Runtime, unittest.TestCase):
    def test_the_users_own_0600_file_under_the_runtime_folder(self):
        path = self.write(feed())
        self.assertEqual(L.check_path(path), os.path.realpath(path))
        os.chmod(path, 0o400)
        self.assertTrue(L.check_path(path))

    def test_readable_by_others_is_refused(self):
        for mode in (0o644, 0o640, 0o604, 0o660):
            path = self.write(feed(), mode=mode)
            with self.assertRaisesRegex(L.FeedError, "0600"):
                L.check_path(path)

    def test_outside_the_runtime_folder_is_refused(self):
        other = tempfile.mkdtemp(prefix="bromigos-link-elsewhere-")
        self.addCleanup(shutil.rmtree, other, True)
        path = os.path.join(other, "feed.json")
        with open(path, "w") as f:
            json.dump(feed(), f)
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(L.FeedError, "XDG_RUNTIME_DIR"):
            L.check_path(path)
        with self.assertRaisesRegex(L.FeedError, "full path"):
            L.check_path("bromigos-live/link-big.json")
        with self.assertRaisesRegex(L.FeedError, "XDG_RUNTIME_DIR"):
            L.check_path(os.path.join(self.run, "..", os.path.basename(other), "feed.json"))

    def test_a_symlink_is_refused_even_to_a_good_file(self):
        good = self.write(feed())
        link = os.path.join(self.run, "bromigos-live", "link-wave.json")
        os.symlink(good, link)
        with self.assertRaisesRegex(L.FeedError, "symlink"):
            L.check_path(link)
        with self.assertRaisesRegex(L.FeedError, "symlink"):
            L.read_feed(link)

    def test_not_a_regular_file_or_not_yours(self):
        d = os.path.join(self.run, "bromigos-live", "dir.json")
        os.makedirs(d)
        with self.assertRaisesRegex(L.FeedError, "regular"):
            L.check_path(d)
        path = self.write(feed())
        with self.assertRaisesRegex(L.FeedError, "isn't yours"):
            L.check_path(path, uid=os.getuid() + 1)
        with self.assertRaisesRegex(L.FeedError, "no such"):
            L.check_path(os.path.join(self.run, "bromigos-live", "missing.json"))

    def test_too_big_is_refused(self):
        path = self.write("x" * (L.MAX_FEED + 1))
        with self.assertRaisesRegex(L.FeedError, "too big"):
            L.check_path(path)


class Parsing(unittest.TestCase):
    def test_a_feed_is_cut_down_to_what_the_den_draws(self):
        f = L.parse_feed(json.dumps(feed()))
        self.assertEqual(f["badge"], "LIVE · MOVIE NIGHT")
        self.assertEqual(f["video"], {"hls": HLS, "authorization": TOKEN})
        self.assertEqual([p["name"] for p in f["people"]][:2], ["kestrel", "wren"])
        self.assertEqual(sum(p["speaking"] for p in f["people"]), 2)
        self.assertTrue(f["people"][3]["endpoint"])
        self.assertIsNone(f["sync"])

    def test_refusals(self):
        for bad, why in ((feed(version=2), "version"), (feed(badge=""), "badge"), ("[1]", "object"),
                         ("not json", "JSON"),
                         (feed(video={"hls": "file:///etc/passwd", "authorization": ""}), "http"),
                         (feed(video={"hls": HLS, "authorization": "x\r\nHost: evil"}), "one header")):
            with self.assertRaisesRegex(L.FeedError, why):
                L.parse_feed(bad if isinstance(bad, str) else json.dumps(bad))
        with self.assertRaisesRegex(L.FeedError, "wave"):
            L.parse_feed(json.dumps(feed(screen="wave")), screen="big")

    def test_odd_values_are_tamed(self):
        f = L.parse_feed(json.dumps(feed(
            badge="LIVE\u0007 · X" + "y" * 200,
            people=[{"name": "a" * 100}, "nope", {"name": ""}, {"name": "b", "picture": "relative.png"}]
            + [{"name": f"p{i}"} for i in range(40)],
            sync={"playing": True, "position_ms": -5, "rate": 99, "at_ms": "soon"})))
        self.assertNotIn("\u0007", f["badge"])
        self.assertLessEqual(len(f["badge"]), 48)
        self.assertEqual(len(f["people"]), L.MAX_PEOPLE - 2)        # the first 24 looked at, the two bad ones skipped
        self.assertEqual(len(f["people"][0]["name"]), 40)
        self.assertIsNone(f["people"][1]["picture"])
        self.assertEqual(f["sync"], {"playing": True, "position_ms": 0, "rate": 4.0, "at_ms": 0})

    def test_public_never_carries_the_address_or_token(self):
        f = L.parse_feed(json.dumps(feed(sync={"playing": True, "position_ms": 1, "rate": 1, "at_ms": 1})))
        pub = json.dumps(L.public(f))
        self.assertNotIn(TOKEN, pub)
        self.assertNotIn("100.64.0.7", pub)
        self.assertEqual(L.public(f)["speaking"], 2)
        self.assertTrue(L.public(f)["party"])

    def test_redact_takes_addresses_and_tokens_out_of_log_lines(self):
        line = f"Failed to open {HLS}?token=abc: Authorization: {TOKEN}"
        out = L.redact(line)
        self.assertNotIn("100.64.0.7", out)
        self.assertNotIn("s3cr3t", out)
        self.assertNotIn("token=abc", out)


class Sync(unittest.TestCase):
    def test_the_same_numbers_as_brodec(self):
        self.assertEqual(L.correct(10_000, 10_200), ("none",))
        self.assertEqual(L.correct(10_000, 9_700), ("none",))
        self.assertEqual(L.correct(10_000, 11_000), ("nudge", 0.95))
        self.assertEqual(L.correct(10_000, 9_000), ("nudge", 1.05))
        self.assertEqual(L.correct(10_000, 12_001), ("seek", 10_000))
        self.assertEqual(L.correct(10_000, 7_000, 2.0), ("seek", 10_000))
        self.assertAlmostEqual(L.correct(10_000, 11_000, 2.0)[1], 1.9)

    def test_where_the_player_should_be(self):
        s = {"playing": True, "position_ms": 60_000, "rate": 1.0, "at_ms": 1_000}
        self.assertEqual(L.expected_ms(s, 6_000), 65_000)
        self.assertEqual(L.expected_ms(dict(s, rate=2.0), 6_000), 70_000)
        self.assertEqual(L.expected_ms(dict(s, playing=False), 99_000), 60_000)
        self.assertEqual(L.expected_ms(s, 0), 60_000)                # a clock behind the host's never rewinds


class SyncPlayer(S.Player):
    def __init__(self):
        super().__init__()
        self.pos, self.speeds, self.seeks_to = 0.0, [], []

    def position(self):
        return self.pos

    def speed(self, rate):
        self.speeds.append(rate)

    def seek(self, pos):
        self.seeks_to.append(pos)


@unittest.skipUnless(S.livetv is not None, getattr(S, "WHY", "needs PyOpenGL"))
class LinkedScreen(Runtime, unittest.TestCase):
    def setUp(self):
        Runtime.setUp(self)
        S.sandbox(self)
        self.tv = S.make_tv(self, {"tv": {"channel": [S.files_channel("Clips", "any")]}})
        self.tv.stop.set()
        for d in self.tv.decks.values():
            d.player = S.Player()
        self.tv.px = {"big": (1188, 678, 200, 175), "wave": (1475, 762, 124, 110), "emblem": (1090, 920, 158, 143)}
        self.tv.rects = dict(self.tv.px)

    def cmd(self, text):
        return json.loads(self.tv.command(text))

    def test_link_plays_the_stream_with_its_header_and_unlink_goes_back(self):
        tv = self.tv
        tv.tune_to("big", 2)
        path = self.write(feed())
        out = self.cmd(f"link --screen big --feed {path} --json")
        self.assertEqual(out, {"ok": True, "screen": "big", "linked": True, "badge": "LIVE · MOVIE NIGHT",
                               "message": "big: linked to LIVE · MOVIE NIGHT"})
        n, ch = tv.channel("big")
        self.assertEqual((n, ch["kind"]), (0, "link"))
        tv.drawn_at = S.livetv._mono()
        tv.tick()
        tv._picture("big", ch, 300, 262, 1.14)
        load = tv.decks["big"].player.loads[-1]
        self.assertEqual(load["url"], HLS)
        self.assertEqual(load["headers"], {"Authorization": TOKEN})
        self.assertIs(tv.decks["big"].player.redact, L.redact)
        self.assertTrue(tv.screens["big"]["sound"], "a link with a stream joins as a listener too")
        out = self.cmd("unlink big --json")
        self.assertTrue(out["ok"])
        self.assertEqual(tv.channel("big")[1]["name"], "Clips")
        self.assertFalse(tv.screens["big"]["sound"], "the sound goes back to what it was")
        self.assertFalse(self.cmd("unlink big --json")["ok"])

    def test_state_says_linked_without_the_address_or_token(self):
        path = self.write(feed())
        self.tv.command(f"link --screen big --feed {path}")
        tv = self.tv
        tv._picture("big", tv.channel("big")[1], 300, 262, 1.14)
        state = tv.command("state --json")
        self.assertNotIn("s3cr3t", state)
        self.assertNotIn("100.64.0.7", state)
        big = json.loads(state)["screens"]["big"]
        self.assertTrue(big["linked"])
        self.assertEqual(big["badge"], "LIVE · MOVIE NIGHT")
        self.assertEqual(big["people"], 4)

    def test_commands_are_checked(self):
        bad = self.write(feed(), name="loose.json", mode=0o644)
        self.assertIn("0600", self.cmd(f"link --screen big --feed {bad} --json")["error"])
        self.assertIn("--screen", self.cmd(f"link --feed {bad} --json")["error"])
        self.assertIn("--feed", self.cmd("link --screen big --json")["error"])
        self.assertIn("no screen", self.tv.command(f"link --screen attic --feed {bad}"))
        wave = self.write(feed(screen="wave"), name="w.json")
        self.assertIn("wave", self.cmd(f"link --screen big --feed {wave} --json")["error"])
        self.tv.cfg["tv"]["enabled"] = False
        good = self.write(feed())
        self.assertIn("off", self.cmd(f"link --screen big --feed {good} --json")["error"])

    def test_the_feed_is_read_again_when_it_changes_and_its_end_unlinks(self):
        tv = self.tv
        path = self.write(feed())
        tv.command(f"link --screen big --feed {path}")
        gen = tv.links["big"]["gen"]
        time.sleep(0.01)
        self.write(feed(badge="#160.04 RAID COMMS", video={"hls": HLS, "authorization": "Bearer new"}))
        tv.links["big"]["checked"] = 0
        tv.links_tick()
        self.assertEqual(tv.links["big"]["feed"]["badge"], "#160.04 RAID COMMS")
        self.assertEqual(tv.links["big"]["gen"], gen + 1, "a new token loads the stream again")
        self.write("{broken")
        tv.links["big"]["checked"] = 0
        tv.links_tick()
        self.assertEqual(tv.links["big"]["feed"]["badge"], "#160.04 RAID COMMS", "a bad rewrite keeps the last feed")
        os.unlink(path)
        tv.links["big"]["checked"] = 0
        tv.links_tick()
        self.assertNotIn("big", tv.links)

    def test_voice_only_loads_no_stream(self):
        tv = self.tv
        path = self.write(feed(video=None, badge="#160.04 RAID COMMS"))
        tv.command(f"link --screen big --feed {path}")
        self.assertEqual(tv._picture("big", tv.channel("big")[1], 300, 262, 1.14), (None, 1.0))
        self.assertEqual(tv.decks["big"].player.loads, [])
        self.assertFalse(tv.screens["big"]["sound"])

    def test_a_party_is_kept_in_step(self):
        tv = self.tv
        now = time.time() * 1000
        path = self.write(feed(sync={"playing": True, "position_ms": 60_000, "rate": 1.0, "at_ms": now}))
        tv.command(f"link --screen big --feed {path}")
        d = tv.decks["big"]
        d.player = p = SyncPlayer()
        p.started = True
        ch = tv.channel("big")[1]
        slot = tv.slot(ch)
        self.assertAlmostEqual(slot.offset, 60.0, delta=1.0)
        d.loaded = (ch["key"], slot.item["id"])
        p.pos = 60.0 + 1.0                                     # a second ahead: slowed a little
        self.assertEqual(tv.link_check(d, ch, slot)[0], "nudge")
        self.assertAlmostEqual(p.speeds[-1], 0.95)
        tv.links["big"]["synced"] = 0
        p.pos = 10.0                                           # far off: a seek
        c = tv.link_check(d, ch, slot)
        self.assertEqual(c[0], "seek")
        self.assertAlmostEqual(p.seeks_to[-1], 60.0, delta=1.0)
        self.write(feed(sync={"playing": False, "position_ms": 61_000, "rate": 1.0, "at_ms": now}))
        tv.links["big"]["checked"] = 0
        tv.links_tick()
        self.assertTrue(tv.link_paused("big"))

    def test_skips_bumps_full_screen_and_on_demand_are_refused_while_linked(self):
        tv = self.tv
        path = self.write(feed())
        tv.command(f"link --screen big --feed {path}")
        self.assertIn("linked", tv.skip_item("big"))
        self.assertIn("linked", tv.bump_now("big"))
        self.assertIn("linked", tv.open_full("big"))
        self.assertIn("linked", json.loads(tv.play_json(json.dumps({"screen": "big", "item": {"id": "x"}})))["error"])
        tv.tune_to("big", 2)                                   # someone at the den changed channel
        self.assertNotIn("big", tv.links)

    def test_the_overlay_draws_the_people_and_the_badge(self):
        from PIL import Image
        from live import glkit
        pics = []

        def texture(surface):
            pics.append(Image.frombytes("RGBA", (surface.get_width(), surface.get_height()),
                                        bytes(surface.get_data()), "raw", "BGRA"))
            return 1
        tv = self.tv
        path = self.write(feed(video=None))
        tv.command(f"link --screen big --feed {path}")
        with mock.patch.object(glkit, "texture_from_cairo", side_effect=texture), \
                mock.patch.object(S.livetv.GL, "glDeleteTextures"):
            static, tex = tv._osd("big")
        self.assertEqual(tex, 1)
        im = pics[-1]
        self.assertEqual(im.size, (200, 175))
        # voice only: a dark glass over the whole screen, people drawn on it
        self.assertGreater(im.getpixel((100, 170))[3], 200)
        lit = sum(1 for x in range(0, 200, 2) for y in range(0, 175, 2) if sum(im.getpixel((x, y))[:3]) > 300)
        self.assertGreater(lit, 40)


class Tiles(unittest.TestCase):
    def test_a_row_over_a_stream_and_a_grid_without_one(self):
        size, row = L.tile_layout(4, 400, 300, video=True)
        self.assertEqual(len({round(y) for _, y in row}), 1)
        self.assertTrue(all(0 < x < 400 for x, _ in row))
        size2, grid = L.tile_layout(4, 400, 300, video=False)
        self.assertGreater(size2, size)
        self.assertEqual(L.tile_layout(0, 400, 300, True), (0.0, []))
        size3, many = L.tile_layout(12, 400, 300, video=False)
        self.assertTrue(all(0 < x < 400 and 0 < y < 300 for x, y in many))


if __name__ == "__main__":
    unittest.main()
