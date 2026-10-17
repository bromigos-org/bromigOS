"""Game mode suppresses live notifications as well as the compositor's popups."""
import os
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from test_theme_refresh import method
from live import sound


class GameModeTest(unittest.TestCase):
    def test_mode_watcher_refreshes_without_needing_window_events(self):
        exists=Mock(return_value=True)
        check=method('App','_watch_game_mode',os=NS(path=NS(exists=exists,join=os.path.join)),RUNTIME='/sandbox')
        app=NS(_game_mode=False,refresh_state=Mock())
        self.assertTrue(check(app))
        app.refresh_state.assert_called_once()
        self.assertTrue(app._game_mode)
        check(app)
        app.refresh_state.assert_called_once()
        exists.return_value=False
        check(app)
        self.assertFalse(app._game_mode)
        self.assertEqual(app.refresh_state.call_count,2)

    def test_critical_notifications_are_logged_but_neither_drawn_nor_voiced(self):
        notify=method('App','on_notify',os=NS(path=NS(exists=lambda _:True,join=os.path.join)),RUNTIME='/sandbox')
        app=NS(cfg={'sounds':{}},history=Mock(),sound=Mock(),overlay=Mock(),codec=Mock())
        self.assertFalse(notify(app,'notify','Test app','Priority notification',2))
        app.history.event.assert_called_once()
        app.sound.play.assert_not_called()
        app.overlay.assert_not_called()
        app.codec.offer.assert_not_called()

    def test_pending_codec_offer_stays_quiet_during_game_mode(self):
        from live.codec import Desk
        app=NS(cfg={'codec':{}},_game_mode=True)
        self.assertEqual(Desk(app).offer('LAB','Test alert',force=True),'held: game mode')

    def test_sound_playback_is_suppressed_without_changing_saved_mute(self):
        player=sound.Sound({'sounds':{'enabled':True}})
        player.player='pw-play'
        with patch.object(sound,'game_quiet',return_value=True), patch.object(sound,'muted',return_value=False), \
             patch.object(sound.subprocess,'Popen') as start:
            player.play('notify')
            player.play_file('/sandbox/call.wav')
            start.assert_not_called()


if __name__=='__main__':
    unittest.main()
