"""Physical knobs, remote mode and on-demand playback, with sandbox state and fake players."""
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

    def test_hint_off_keeps_analog_regions_and_tv_off_has_none(self):
        tv = self.tv
        tv.tune_to("big",2); tv.pointer_motion(120,120)
        self.assertTrue(tv.hint_visible())
        tv.cfg["tv"]["hover_hint"] = False
        self.assertFalse(tv.hint_visible())
        self.assertEqual(len(tv.analog_regions()),12)
        s,a,r = tv.analog_regions()[0]
        tv.scroll(r[0]+r[2]/2,r[1]+r[3]/2,-1)
        self.assertEqual(tv.screens[s]["volume"],65)
        self.assertIsNotNone(tv.decks[s].vol_osd)
        tv.cfg["tv"]["enabled"] = False; tv.reconfigured()
        self.assertEqual(tv.analog_regions(),[]); self.assertEqual(tv.input_rects(),[])
        self.assertEqual(tv._osd("big"),(0.0,None))

    def test_knob_readout_clears_when_the_pointer_leaves_the_layer(self):
        tv = self.tv
        _,_,rect = tv.analog_regions()[0]
        tv.pointer_motion(rect[0]+rect[2]/2, rect[1]+rect[3]/2)
        self.assertEqual(tv.analog_hover, ("big","volume"))
        tv.pointer_leave()
        self.assertIsNone(tv.analog_hover)

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
        tv.remote("skip"); self.assertIn("wave",tv.overrides)
        tv.remote_at -= 15.1; tv.controls_tick(); self.assertIsNone(tv.selected)
        tv._submap.assert_called_with("reset")

    def test_direct_remote_does_not_capture_keyboard_or_tune_digit_buffer(self):
        self.tv.remote("volume-up","big")
        self.assertEqual(self.tv.screens["big"]["volume"],65)
        self.assertIsNone(self.tv.selected); self.tv._submap.assert_not_called()

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

    def test_channel_knob_mute_and_skip_are_real_actions(self):
        tv = self.tv
        for action in ("channel","mute","skip"):
            s,_,r = next(v for v in tv.analog_regions() if v[:2]==("big",action))
            tv.click(r[0]+r[2]/2,r[1]+r[3]/2)
        self.assertEqual(tv.channel("big")[0],2)
        self.assertTrue(tv.screens["big"]["sound"])
        self.assertIn("big",tv.overrides)
        tv.release(); self.assertIsNone(tv.analog_press)


if __name__ == "__main__": unittest.main()
