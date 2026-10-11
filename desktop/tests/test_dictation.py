"""Dictation lifecycle and speech requests, with synthetic PCM and no desktop or microphone."""
import ctypes
import ctypes.util
import json
import os
import socket
import stat
import tempfile
import threading
import unittest
from unittest import mock

import bromigos_dictation as D
import bromigos_type as K


class Recording:
    def __init__(self, callback):
        self.data = b"\x00\x10" * D.RATE
        self.peak, self.error, self.stopped = .03, None, False

    def snapshot(self):
        return self.data

    def stop(self):
        self.stopped = True

    def finish(self):
        self.stop()
        return self.data

    def erase(self):
        self.data = b""


class Lifecycle(unittest.TestCase):
    def session(self, backend, insert, events, observed=lambda event: None):
        def event(*value):
            events.append(value)
            observed(value)
        session = D.Session(backend, insert, event, "target",
                            recorder=Recording, interval=.01)
        session.start()
        self.addCleanup(session.cancel)
        return session

    def test_preview_release_transcribes_the_final_tail_and_inserts_once(self):
        preview = threading.Event()
        calls, inserted, events = [], [], []

        def backend(pcm):
            calls.append(pcm)
            return "First words" if len(pcm) == D.RATE * 2 else "First words, and the end."

        session = self.session(backend, lambda text, target, alive: inserted.append((text, target, alive())), events,
                               lambda event: preview.set() if event[1] == "First words" else None)
        self.assertTrue(preview.wait(2))
        session.recorder.data += b"\x00\x10" * 1000
        session.release()
        session.release()
        self.assertTrue(session.finished.wait(2))
        self.assertEqual(inserted, [("First words, and the end.", "target", True)])
        self.assertEqual(len(calls[-1]), D.RATE * 2 + 2000)
        self.assertTrue(any(state == "listening" and text == "First words" for state, text, _ in events))
        self.assertEqual(events[-1][0], "done")
        self.assertTrue(session.recorder.stopped)
        self.assertEqual(session.recorder.data, b"")
        self.assertEqual(session.text, "")

    def test_cancel_during_an_inflight_preview_never_inserts(self):
        entered, respond = threading.Event(), threading.Event()
        inserted, events = [], []

        def backend(_pcm):
            entered.set()
            respond.wait(2)
            return "Words from a cancelled recording"

        session = self.session(backend, lambda *args: inserted.append(args), events)
        self.assertTrue(entered.wait(2))
        session.cancel()
        respond.set()
        self.assertTrue(session.finished.wait(2))
        self.assertEqual(inserted, [])
        self.assertFalse(any("cancelled" in text for _, text, _ in events))
        self.assertEqual(session.recorder.data, b"")

    def test_silence_does_not_call_the_recognizer_or_insert(self):
        backend, insert = mock.Mock(), mock.Mock()
        events = []
        session = D.Session(backend, insert, lambda *e: events.append(e), "target", recorder=Recording)
        session.recorder.peak = 0
        session.start()
        session.release()
        self.assertTrue(session.finished.wait(2))
        backend.assert_not_called()
        insert.assert_not_called()
        self.assertEqual(events[-1][0], "done")

    def test_backend_failure_closes_the_microphone_without_inserting(self):
        insert, events = mock.Mock(), []
        session = self.session(mock.Mock(side_effect=D.DictationError("Speech service unavailable")), insert, events)
        self.assertTrue(session.finished.wait(2))
        insert.assert_not_called()
        self.assertTrue(session.recorder.stopped)
        self.assertEqual(events[-1][:2], ("error", "Speech service unavailable"))

    def test_focus_change_prevents_insertion(self):
        with mock.patch.object(D, "focused_window", return_value="other"), \
                mock.patch.object(K, "type_text") as insert:
            with self.assertRaisesRegex(D.DictationError, "Focus changed"):
                D.insert_text("Words", "target")
        insert.assert_not_called()


class ControllerLifecycle(unittest.TestCase):
    def test_a_finished_recording_does_not_keep_the_idle_controller_alive(self):
        import bromigos_dictation_ui as UI
        from types import SimpleNamespace
        controller = UI.Controller.__new__(UI.Controller)
        done = threading.Event(); done.set()
        controller.session = SimpleNamespace(finished=done)
        controller.last_command = 0
        controller.app = mock.Mock()
        self.assertFalse(controller._idle())
        controller.app.quit.assert_called_once()

    def test_long_preview_keeps_the_latest_words_without_using_markup(self):
        import collections
        import bromigos_dictation_ui as UI
        overlay = UI.Overlay.__new__(UI.Overlay)
        overlay.levels = collections.deque(maxlen=36)
        overlay.transcript, overlay.hint, overlay.meter = mock.Mock(), mock.Mock(), mock.Mock()
        overlay.update("listening", "Earlier words " * 30 + "latest <words> here", .3)
        shown = overlay.transcript.set_text.call_args.args[0]
        self.assertTrue(shown.startswith("… "))
        self.assertTrue(shown.endswith("latest <words> here"))
        self.assertLessEqual(len(shown), 182)



class SpeechWorker(unittest.TestCase):
    def test_existing_voice_protocol_private_snapshot_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="dictation-voice-") as root:
            path = os.path.join(root, "voice.sock")
            seen = []
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(path)
                server.listen(1)

                def reply():
                    connection, _ = server.accept()
                    with connection:
                        data = bytearray()
                        while not data.endswith(b"\n"):
                            data.extend(connection.recv(4096))
                        req = json.loads(data)
                        seen.append((req["op"], stat.S_IMODE(os.stat(req["pcm"]).st_mode)))
                        with open(req["pcm"], "rb") as sample:
                            seen.append(sample.read())
                        connection.sendall(json.dumps({"text": " Hello, café — <world>!\nNext line. "}).encode() + b"\n")

                thread = threading.Thread(target=reply)
                thread.start()
                with mock.patch.dict(os.environ, {"BROMIGOS_VOICE_SOCK": path}):
                    text = D.Backend(root)(b"\x00\x10" * 1000)
                thread.join(2)
            self.assertEqual(text, "Hello, café — <world>! Next line.")
            self.assertEqual(seen, [("stt", 0o600), b"\x00\x10" * 1000])
            self.assertFalse(any(name.endswith(".pcm") for name in os.listdir(root)))


class UnicodeKeymap(unittest.TestCase):
    def test_keymap_compiles_literal_unicode_and_punctuation_without_modifiers(self):
        raw, codes = K.keymap("Hello, café — <world>! 😀")
        self.assertEqual(len(codes), len(set("Hello, café — <world>! 😀")))
        self.assertTrue(all(2 <= code <= 51 for code in codes.values()))
        xkb = ctypes.CDLL(ctypes.util.find_library("xkbcommon"))
        xkb.xkb_context_new.restype = ctypes.c_void_p
        xkb.xkb_context_unref.argtypes = [ctypes.c_void_p]
        xkb.xkb_keymap_new_from_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        xkb.xkb_keymap_new_from_string.restype = ctypes.c_void_p
        xkb.xkb_keymap_unref.argtypes = [ctypes.c_void_p]
        context = xkb.xkb_context_new(0)
        keymap = xkb.xkb_keymap_new_from_string(context, raw, 1, 0)
        try:
            self.assertTrue(keymap, raw.decode())
        finally:
            if keymap:
                xkb.xkb_keymap_unref(keymap)
            xkb.xkb_context_unref(context)


if __name__ == "__main__":
    unittest.main()
