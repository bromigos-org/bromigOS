"""Hover menu, remote mode and on-demand playback, with sandbox state and fake players."""
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_tv_screens as S


@unittest.skipUnless(S.livetv is not None, getattr(S, "WHY", "needs PyOpenGL"))
class Controls(unittest.TestCase):
    def setUp(self):
        S.sandbox(self)
        self.tv = S.make_tv(self, {"tv": {"channel": [S.files_channel("Clips", "any")]}})
        self.tv.stop.set()
        self.tv.rects = {"big": (100,100,200,175), "wave": (450,150,124,110), "emblem": (200,400,158,143)}
        self.tv.px = dict(self.tv.rects)
        for d in self.tv.decks.values(): d.player = S.Player()
        self.submap = mock.patch.object(self.tv, "_submap"); self.submap.start(); self.addCleanup(self.submap.stop)

    def test_hover_menu_defaults_on_and_can_be_disabled(self):
        tv = self.tv
        tv.tune_to("big", 2)
        tv.pointer_motion(120, 120)
        self.assertTrue(tv.hint_visible())
        self.assertIn(tuple(round(v) for v in tv.hint_rect), tv.input_rects())
        tv.cfg["tv"]["hover_hint"] = False
        self.assertFalse(tv.hint_visible())
        self.assertEqual(tv.input_rects(), list(tv.rects.values()))
        tv.cfg["tv"]["enabled"] = False
        tv.reconfigured()
        self.assertEqual(tv.input_rects(), [])
        self.assertEqual(tv._osd("big"), (0.0, None))

    def test_old_control_positions_do_not_capture_input_or_change_tv(self):
        tv = self.tv
        before = tv.describe()["screens"]
        for x, y, w, h in tv.rects.values():
            unit = max(12, min(23, w / 8))
            for i in range(4):
                cx, cy = x + w * (.17 + i * .21), y + h + unit * .9
                tv.pointer_motion(cx, cy)
                self.assertIsNone(tv.click(cx, cy))
                self.assertIsNone(tv.scroll(cx, cy, -1))
                self.assertFalse(any(rx <= cx <= rx + rw and ry <= cy <= ry + rh
                                     for rx, ry, rw, rh in tv.input_rects()))
        self.assertEqual(tv.describe()["screens"], before)

    def test_mute_glyph_is_drawn_even_while_the_volume_bar_is_showing(self):
        from PIL import Image
        from live import glkit
        captured=[]
        def texture(surface):
            captured.append(Image.frombytes("RGBA", (surface.get_width(),surface.get_height()), bytes(surface.get_data()), "raw", "BGRA"))
            return 1
        with mock.patch.object(glkit,"texture_from_cairo", side_effect=texture), mock.patch.object(S.livetv.GL,"glDeleteTextures"):
            self.tv._draw_osd(self.tv.decks["big"], None, 65, False)
            self.tv._draw_osd(self.tv.decks["big"], None, 65, False, feedback="MUTED")
        crop=(170,145,200,175)
        self.assertIsNone(captured[0].crop(crop).getbbox())
        self.assertIsNotNone(captured[1].crop(crop).getbbox(), "the crossed-out speaker must appear on the TV")

    def test_remote_selection_digits_actions_and_timeout_share_feedback(self):
        tv = self.tv
        tv.command("select scope"); self.assertEqual(tv.selected,"wave")
        tv.remote("volume-up"); self.assertEqual(tv.screens["wave"]["volume"],65)
        tv.remote("digits"); tv.remote("channel-down") # digit 2 rather than prev
        self.assertEqual(tv.digits,"2")
        tv.digits_at -= 1.1; tv.controls_tick()
        self.assertEqual(tv.channel("wave")[0],2); self.assertIsNone(tv.digits)
        tv.remote("mute"); self.assertFalse(tv.screens["wave"]["sound"])
        self.assertEqual(tv.decks["wave"].feedback[1],"MUTED")
        tv.remote("sound"); self.assertTrue(tv.screens["wave"]["sound"])
        tv.remote("skip"); self.assertNotIn("wave",tv.overrides)
        tv.remote_at -= 15.1; tv.controls_tick(); self.assertIsNone(tv.selected)
        tv._submap.assert_called_with("reset")

    def test_direct_remote_does_not_capture_keyboard_or_tune_digit_buffer(self):
        self.tv.remote("volume-up","big")
        self.assertEqual(self.tv.screens["big"]["volume"],65)
        self.assertIsNone(self.tv.selected); self.tv._submap.assert_not_called()

    def test_skip_survives_retuning_restart_and_advances_at_item_end(self):
        tv = self.tv
        tv.tune_to("big", 2)
        ch = tv.channel("big")[1]
        before = tv.slot(ch)
        tv.skip_item("big")
        skipped = tv.slot(ch)
        self.assertEqual(skipped.item["id"], before.next["id"])
        self.assertLess(skipped.offset, 1)
        tv.tune_to("big", 1)
        tv.tune_to("big", 2)
        self.assertEqual(tv.slot(tv.channel("big")[1]).item["id"], skipped.item["id"])
        self.assertEqual(S.TV.now_next(ch).item["id"], skipped.item["id"])
        after = S.TV.now_next(ch, skipped.end + .01)
        self.assertEqual(after.item["id"], skipped.next["id"])
        tv.skip_item("big", previous=True)
        self.assertEqual(tv.slot(ch).item["id"], before.item["id"])

    def test_play_from_start_resume_eof_and_channel_change(self):
        tv = self.tv; item = dict(id="episode",title="Episode",server="jellyfin",kind="episode",duration=600,position=80)
        answer = json.loads(tv.command("play-json " + json.dumps(dict(screen="big",item=item))))
        self.assertTrue(answer["ok"]); ch = tv.channel("big")[1]
        self.assertTrue(ch["override"]); self.assertEqual(tv.slot(ch).offset,0)
        self.assertTrue(tv.describe()["screens"]["big"]["on_demand"])
        tv.override("big",item,resume=True); self.assertEqual(tv.slot(tv.channel("big")[1]).offset,80)
        ch = tv.channel("big")[1]; d = tv.decks["big"]
        d.loaded=(ch["key"],"episode"); d.player.ended=("eof",None)
        tv._check_failure(d,ch,tv.slot(ch)); self.assertNotIn("big",tv.overrides)
        tv.override("big",item); tv.tune_to("big",2); self.assertNotIn("big",tv.overrides)

    def test_shared_channels_do_not_share_an_on_demand_player(self):
        tv = self.tv
        tv.tune_to("big",2); tv.tune_to("wave",2)
        self.assertTrue(tv._sharing(["big","wave"],None))
        tv.override("big",dict(id="a",title="Movie",server="jellyfin",kind="movie"))
        self.assertFalse(tv._sharing(["big","wave"],None))

    def test_moving_sound_also_mutes_the_fullscreen_player(self):
        tv = self.tv
        tv.tune_to("big", 2); tv.tune_to("wave", 2)
        session = mock.Mock(screen="big")
        tv.full_session = session
        tv.set_sound("big", on=True)
        tv.set_sound("wave", on=True)
        session.sound.assert_called_with(tv.screens["big"]["volume"], False)
        self.assertFalse(tv.screens["big"]["sound"])
        self.assertEqual(tv.sound_screen(), "wave")
        tv.full_session = None


if __name__ == "__main__": unittest.main()
