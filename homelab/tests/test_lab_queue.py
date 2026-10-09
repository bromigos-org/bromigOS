"""The lab job queue: VRAM gating, ordering, the voice service's reserve, cancel, retry,
recovery, measured peaks and notifications. The GPU is a stand-in view; the kinds are test
kinds whose run() waits for the test to let it finish.

    PYTHONPATH=lib:../lib python -m unittest discover -s tests
"""
import os
import threading
import time
import unittest
from unittest import mock

import labfake
from bromigos_homelab import jobqueue as Q
from bromigos_homelab import jobs as J

GIB = 1024


class Gate:
    """Test kinds: run() blocks until release(id) (or the job is cancelled)."""

    def __init__(self):
        self.go = {}
        self.ran = []

    def run(self, job, ctx):
        self.ran.append(job["id"])
        ev = self.go.setdefault(job["id"], threading.Event())
        while not ev.wait(0.02):
            if ctx.cancelled():
                return []
        if job.get("prompt") == "fail":
            raise J.JobError("the model said no")
        out = ctx.out()
        with open(out, "w") as f:
            f.write("ok")
        return [out]

    def release(self, jid):
        self.go.setdefault(jid, threading.Event()).set()


G = Gate()
for k in (J.Kind("t-heavy", "Heavy", "a heavy test job", G.run, (), vram_mib=7270, heavy=True, ext=".png"),
          J.Kind("t-big", "Big", "needs more than any GPU", G.run, (), vram_mib=40 * GIB, heavy=True),
          J.Kind("t-voice", "Voice", "a voice line", G.run, (), gpu="voice", ext=".wav"),
          J.Kind("t-llm", "LLM", "a batch", G.run, (), gpu="llm", ext=".jsonl"),
          J.Kind("t-off", "Off", "no backend", None, ())):
    J.register_kind(k)
J.register_preset(J.Preset("t-later", "t-heavy", "Later", "not yet", disabled="needs video on the lab"))


def view(free=20 * GIB, total=32 * GIB, holds=0, running=0, pending=0):
    return {"source": "comfyui", "free": free, "total": total, "holds": holds, "running": running, "pending": pending}


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.lab = labfake.Lab()
        self.lab.__enter__()
        self.view = view()
        self.notes = []
        self.patches = [mock.patch.object(Q, "gpu_view", lambda pool="media": self.view if pool == "media" else None),
                        mock.patch.object(Q, "notify", lambda t, b, urgency="normal", icon=None: self.notes.append((t, b, urgency)))]
        for p in self.patches:
            p.start()
        self.svc = Q.Service()

    def tearDown(self):
        for jid in list(G.go):
            G.release(jid)
        for t, ev, _ in list(self.svc.workers.values()):
            ev.set()
            t.join(2)
        for p in self.patches:
            p.stop()
        self.lab.__exit__(None, None, None)

    def state(self, j):
        return Q.get(j["id"])["state"]

    def settle(self, j, states=Q.DONE, timeout=5):
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.svc.step()
            if self.state(j) in states:
                return Q.get(j["id"])
            time.sleep(0.03)
        self.fail(f"{j['id']} stayed {self.state(j)}")

    def wait_notes(self, n=1, timeout=3):
        """The notification follows the job's last state by a moment (another thread)."""
        t0 = time.time()
        while len(self.notes) < n and time.time() - t0 < timeout:
            time.sleep(0.02)
        return self.notes

    def submit(self, kind, **kw):
        j = Q.submit(kind, **kw)
        time.sleep(0.002)                         # distinct creation times: the order is theirs
        return j

    # ------------------------------------------------------------------ the gate
    def test_gate(self):
        with mock.patch.object(Q, "voice_reserve_mib", lambda: 2048):
            ok, why = Q.gate("t-heavy", view(free=10 * GIB), reserve=2048)
            self.assertTrue(ok)
            ok, why = Q.gate("t-heavy", view(free=9 * GIB), reserve=2048)        # 9 - 7.1 < 2
            self.assertFalse(ok)
            self.assertIn("stays free for the voice service", why)
            ok, why = Q.gate("t-heavy", view(free=4 * GIB, holds=6 * GIB), reserve=2048)   # an idle ComfyUI gives back
            self.assertTrue(ok)
            ok, why = Q.gate("t-heavy", view(free=30 * GIB, running=1), reserve=2048)
            self.assertFalse(ok)
            self.assertIn("busy with other work", why)
            ok, why = Q.gate("t-big", view(), reserve=2048)
            self.assertIsNone(ok)
            self.assertIn("more than the GPU has", why)
            ok, why = Q.gate("t-heavy", {"error": "unreachable: refused", "source": "comfyui"}, reserve=2048)
            self.assertFalse(ok)

    # ------------------------------------------------------------------ ordering
    def test_heavy_jobs_one_at_a_time_in_order(self):
        a, b, c = (self.submit("t-heavy", prompt=str(i)) for i in range(3))
        self.svc.step()
        self.assertEqual([self.state(x) for x in (a, b, c)], ["running", "waiting", "waiting"])
        self.assertIn("one heavy job at a time", Q.get(b["id"])["why"])
        G.release(a["id"])
        self.settle(a)
        self.svc.step()
        self.assertEqual([self.state(x) for x in (b, c)], ["running", "waiting"])
        G.release(b["id"])
        G.release(c["id"])
        self.settle(c)
        self.assertEqual([G.ran.index(x["id"]) for x in (a, b, c)], sorted(G.ran.index(x["id"]) for x in (a, b, c)))

    def test_waits_for_vram_and_keeps_the_voice_reserve(self):
        self.view = view(free=8 * GIB)                              # 8 - 7.1 leaves under 2 GiB for the voice
        a = self.submit("t-heavy")
        later = self.submit("t-heavy")
        v = self.submit("t-voice", text="hello")
        self.svc.step()
        self.assertEqual(self.state(a), "waiting")
        self.assertIn("waiting for VRAM", Q.get(a["id"])["why"])
        self.assertEqual(self.state(later), "waiting", "no overtaking: heavy jobs keep their order")
        self.assertEqual(self.state(v), "running", "a light job doesn't wait behind a heavy one")
        self.view = view(free=12 * GIB)
        self.svc.view_at = 0
        self.svc.step()
        self.assertEqual(self.state(a), "running")
        self.assertEqual(self.state(later), "waiting")

    def test_an_idle_comfyui_is_asked_to_unload_for_a_waiting_job(self):
        free = ("comfyui", "/free", {"unload_models": True, "free_memory": True})
        self.view = view(free=8 * GIB)          # what ComfyUI keeps from the last job isn't in `holds`
        a = self.submit("t-heavy")
        self.svc.step()
        self.assertEqual(self.state(a), "waiting")
        self.assertEqual(self.lab.posts.count(free), 1)
        self.assertEqual(self.svc.view_at, 0.0, "the GPU is looked at again on the next step")
        self.svc.step()
        self.assertEqual(self.lab.posts.count(free), 1, "asked once, not on every step")
        self.view = view(free=17 * GIB)         # it gave the room back
        self.svc.view_at = 0
        self.svc.step()
        self.assertEqual(self.state(a), "running")

    def test_a_busy_comfyui_is_never_asked_to_unload(self):
        self.view = view(free=8 * GIB, running=1)
        a = self.submit("t-heavy")
        self.svc.step()
        self.assertIn("busy with other work", Q.get(a["id"])["why"])
        self.assertFalse([p for p in self.lab.posts if p[1] == "/free"])

    def test_never_fits_fails_at_once(self):
        j = self.submit("t-big")
        self.svc.step()
        j = Q.get(j["id"])
        self.assertEqual(j["state"], "failed")
        self.assertIn("more than the GPU has", j["why"])
        self.assertEqual(self.wait_notes()[-1][2], "critical")

    def test_one_voice_job_at_a_time(self):
        a, b = self.submit("t-voice", text="one"), self.submit("t-voice", text="two")
        llm = self.submit("t-llm", prompt="x")
        self.svc.step()
        self.assertEqual([self.state(a), self.state(b), self.state(llm)], ["running", "waiting", "running"])
        self.assertIn("1 voice job at a time", Q.get(b["id"])["why"])

    # ------------------------------------------------------------------ results, cancel, retry
    def test_success_lands_in_pictures_and_notifies(self):
        j = self.submit("t-heavy", prompt="a lighthouse")
        self.svc.step()
        G.release(j["id"])
        j = self.settle(j)
        self.assertEqual(j["state"], "succeeded")
        (out,) = j["outputs"]
        self.assertEqual(os.path.dirname(out), os.path.join(os.environ["BROMIGOS_LAB_OUT"], "t-heavy"))
        self.assertTrue(out.endswith(".png") and os.path.exists(out))
        self.assertTrue(any("done" in t for t, _, _ in self.wait_notes()))
        self.assertIn("started", Q.read_log(j["id"]))

    def test_failure_says_why(self):
        j = self.submit("t-heavy", prompt="fail")
        self.svc.step()
        G.release(j["id"])
        j = self.settle(j)
        self.assertEqual(j["state"], "failed")
        self.assertEqual(j["why"], "the model said no")
        self.assertEqual(self.wait_notes()[-1], ("Lab: t-heavy failed", "the model said no", "critical"))

    def test_cancel_queued_and_running(self):
        a, b = self.submit("t-heavy"), self.submit("t-heavy")
        self.svc.step()
        self.assertEqual(Q.cancel(b["id"])["state"], "cancelled")
        Q.cancel(a["id"])
        j = self.settle(a)
        self.assertEqual(j["state"], "cancelled")

    def test_retry(self):
        j = self.submit("t-heavy", prompt="fail")
        self.svc.step()
        G.release(j["id"])
        self.settle(j)
        n = Q.retry(j["id"])
        self.assertEqual(n["retry_of"], j["id"])
        self.assertEqual(n["attempt"], 2)
        self.assertEqual(n["prompt"], "fail")
        with self.assertRaises(ValueError):
            Q.retry(n["id"])                              # still queued

    def test_a_dead_service_leaves_no_job_running(self):
        j = self.submit("t-heavy")
        Q.update(j["id"], state="running", started=time.time())
        Q.Service().recover()
        j = Q.get(j["id"])
        self.assertEqual(j["state"], "failed")
        self.assertIn("retry", j["why"])

    def test_measured_peak_raises_the_need(self):
        self.assertEqual(Q.need_mib("t-heavy"), 7270)
        Q._observe("t-heavy", 9000)
        self.assertEqual(Q.need_mib("t-heavy"), 9000)
        Q._observe("t-heavy", 100)
        self.assertEqual(Q.need_mib("t-heavy"), 9000)

    # ------------------------------------------------------------------ submitting
    def test_submit_refuses_what_cannot_run(self):
        with self.assertRaises(ValueError) as e:
            Q.submit("t-off")
        self.assertIn("no backend yet", str(e.exception))
        with self.assertRaises(ValueError) as e:
            Q.submit(None, preset="t-later")
        self.assertIn("needs video", str(e.exception))
        with self.assertRaises(ValueError):
            Q.submit("no-such-kind")
        with self.assertRaises(ValueError):
            Q.submit("t-heavy", inputs=["/nonexistent/x.png"])

    def test_cloud_is_off_unless_asked(self):
        self.assertFalse(Q.submit("t-heavy")["cloud"])
        self.assertTrue(Q.submit("t-heavy", cloud=True)["cloud"])

    def test_real_kinds_say_why_not(self):
        with mock.patch.object(J.caps, "available", lambda c: c != "media"):
            ok, why = J.KINDS["image"].status()
        self.assertFalse(ok)
        self.assertIn("media", why)
        # share/lab/jobs.toml's measurements (the 5090) set the gates
        self.assertEqual(J.KINDS["3d"].vram_mib, 12800, "Pixal3D shape: up to 12.5 GiB")
        self.assertIn("Pixal3D", J.KINDS["3d"].vram_note)
        self.assertEqual(J.KINDS["cutout"].vram_mib, 1100)
        self.assertEqual(J.KINDS["upscale"].vram_mib, 8900)
        with mock.patch.object(J.caps, "available", lambda c: True):
            self.assertTrue(J.KINDS["upscale"].status()[0])

    def test_video_runs_a_loop_on_the_lab(self):
        # share/lab/jobs.toml's measurement (Wan 2.2 on the 5090) sets the gate
        self.assertEqual(J.KINDS["video"].vram_mib, 17800)
        self.assertIn("Wan 2.2", J.KINDS["video"].vram_note)
        with mock.patch.object(J.caps, "available", lambda c: True):
            self.assertTrue(J.KINDS["video"].status()[0])
            self.assertTrue(J.PRESETS["creature-loop"].describe()["available"])
        seen = {}

        class Ctx:
            cloud = False

            def out(self, stem="out", ext=".png"):
                return os.path.join(self.dir, stem + ext)

            def log(self, *_):
                pass

            def note(self, **_):
                pass

            def run(self, argv, timeout=None):
                seen["argv"] = argv
                open(argv[argv.index("--out") + 1], "w").close()
                return mock.Mock(returncode=0, stdout='{"provider": "comfyui:homelab"}', stderr="")

        import tempfile
        with tempfile.TemporaryDirectory() as d:
            still = os.path.join(d, "jelly.png")
            open(still, "w").close()
            ctx = Ctx()
            ctx.dir = d
            job = {"prompt": "its bell pulses", "inputs": [still],
                   "options": dict(J.PRESETS["creature-loop"].options, seed=7)}
            outs = J.run_video(job, ctx)
        a = seen["argv"]
        self.assertEqual(a[2:4], ["make", "video.loop"])
        self.assertEqual(a[a.index("--duration") + 1], "5")
        self.assertEqual(a[a.index("--alpha") + 1], "luma")
        self.assertIn("seed=7", a)
        self.assertIn("moving the whole time", a[a.index("--prompt") + 1])
        self.assertEqual(a[a.index("--provider") + 1], "comfyui:homelab")
        self.assertEqual(a[a.index("--max-credits") + 1], "0")
        self.assertTrue(outs[0].endswith("jelly-loop.mp4"))

    def test_upscale_sends_an_image_and_a_clip_to_their_capabilities(self):
        seen = []

        class Ctx:
            cloud = False

            def out(self, stem="out", ext=".png"):
                return os.path.join(self.dir, stem + ext)

            def log(self, *_):
                pass

            def note(self, **_):
                pass

            def run(self, argv, timeout=None):
                seen.append(argv)
                open(argv[argv.index("--out") + 1], "w").close()
                return mock.Mock(returncode=0, stdout='{"provider": "comfyui:homelab"}', stderr="")

        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ctx = Ctx()
            ctx.dir = d
            pic, clip = os.path.join(d, "pic.png"), os.path.join(d, "loop.mp4")
            for f in (pic, clip):
                open(f, "w").close()
            a = J.run_upscale({"inputs": [pic]}, ctx)
            b = J.run_upscale({"inputs": [clip], "options": {"scale": 2}}, ctx)
        self.assertEqual(seen[0][2:4], ["make", "image.upscale"])
        self.assertTrue(a[0].endswith("pic-up.png"))
        self.assertNotIn("--extra", seen[0])
        self.assertEqual(seen[1][2:4], ["make", "video.upscale"])
        self.assertTrue(b[0].endswith("loop-up.mp4"))
        self.assertEqual(seen[1][seen[1].index("--extra") + 1], "scale=2")
        self.assertEqual(seen[1][seen[1].index("--provider") + 1], "comfyui:homelab")

    def test_ctx_run_is_killed_on_cancel(self):
        ev = threading.Event()
        ctx = Q.Ctx({"id": "x", "kind": "t-heavy", "cloud": False}, ev)
        threading.Timer(0.3, ev.set).start()
        t0 = time.time()
        p = ctx.run(["sleep", "30"], timeout=60)
        self.assertLess(time.time() - t0, 5)
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
