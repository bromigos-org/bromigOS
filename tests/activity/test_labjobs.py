"""Lab jobs (lib/bromigos_labjobs.py, docs/activity.md "Lab jobs"): ComfyUI's recorded answers
(fixtures/comfyui: a live ComfyUI 0.45.2's /queue and /history, names scrubbed; the websocket
and two ends made from its source's shapes) as activity records, the follower's state and media,
stopping a prompt, job feeds and their writer, `bromigos activity` list/show/watch/emit/cancel,
and the relay node. No ComfyUI is called: a stand-in answers every request."""
import asyncio
import base64
import importlib.util
import io
import json
import os
import struct
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake import FakeMachine, FIXTURES, REPO  # noqa: E402

import bromigos_activity as A  # noqa: E402
import bromigos_labjobs as L  # noqa: E402

COMFY = FIXTURES / "comfyui"
QUEUE = json.loads((COMFY / "queue.json").read_text())
HISTORY = json.loads((COMFY / "history.json").read_text())
ENDS = json.loads((COMFY / "history-ends.json").read_text())["history"]
WS = json.loads((COMFY / "ws.json").read_text())
STATUS = json.loads((COMFY / "status.json").read_text())
RUNNING = QUEUE["queue_running"][0][1]
PENDING = QUEUE["queue_pending"][0][1]
INST = {"name": "studio", "url": "http://comfy.invalid:8188"}
# a tiny PNG: what /view answers in these tests
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def ended_at(h):
    return max(m[1]["timestamp"] for m in h["status"]["messages"])


LAST_END = max(ended_at(h) for h in HISTORY.values())
NOW = LAST_END + 30_000        # 30 s after the last prompt ended
# without the websocket, the running prompt began when the one before it ended, or when it was
# queued if that was later
RAN = max(LAST_END, QUEUE["queue_running"][0][3]["create_time"])


class FakeHttp:
    """One ComfyUI: answers /queue, /history and /view from the fixtures, notes every POST."""

    def __init__(self, queue=None, history=None):
        self.queue = json.loads(json.dumps(QUEUE if queue is None else queue))
        self.history = json.loads(json.dumps(HISTORY if history is None else history))
        self.posts, self.gets = [], []

    def get(self, path):
        self.gets.append(path)
        if path == "/queue":
            return self.queue
        if path.startswith("/history"):
            return self.history
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, body):
        self.posts.append((path, body))
        return {}

    def fetch(self, path, cap=L.MEDIA_MAX):
        self.gets.append(path)
        return PNG


def wfs():
    return L.workflows(L.Where(A.Env({"HOME": "/nonexistent", "XDG_CONFIG_HOME": "/nonexistent"})))


def records(now=NOW, live=None, queue=None, history=None):
    return L.comfy_records(INST, QUEUE if queue is None else queue, HISTORY if history is None else history, now, wfs(), live)


class Mapping(unittest.TestCase):
    """A recorded queue and history, as records."""

    def setUp(self):
        self.recs = records()
        self.by = {r["lab"]["prompt_id"]: r for r in self.recs}

    def test_every_prompt_once_running_then_queue_then_ended(self):
        self.assertEqual(len(self.recs), 1 + len(QUEUE["queue_pending"]) + len(HISTORY))
        self.assertEqual([r["state"] for r in self.recs[:2]], ["running", "queued"])
        self.assertTrue(all(r["state"] == "succeeded" for r in self.recs[2:]))
        starts = [r["lab"]["ran_at"] for r in self.recs[2:]]
        self.assertEqual(starts, sorted(starts, reverse=True), "the ended come newest first")
        for r in self.recs:
            self.assertRegex(r["id"], L.COMFY_ID)
            self.assertTrue(L.is_lab_id(r["id"]))
            self.assertEqual(r["subject"], {"type": "comfyui", "id": "studio", "name": "studio"})

    def test_the_activity_record_keys_are_all_there(self):
        from test_activity import RECORD_KEYS, STEP_KEYS
        for r in self.recs:
            self.assertEqual(set(r) - {"lab"}, RECORD_KEYS)
            for s in r["steps"]:
                self.assertEqual(set(s), STEP_KEYS)

    def test_workflows_are_named_from_the_shipped_ones(self):
        titles = {r["title"].split(" · ")[0] for r in self.recs}
        self.assertIn("Image: Qwen-Image-2512", titles)
        self.assertIn("Cut-out: Lucida", titles)
        self.assertIn("3D: Pixal3D", titles)
        self.assertIn("Edit: Qwen-Image-Edit-2511", titles)
        self.assertIn("Image: Qwen-Image-2512 Lightning", titles, "the Lightning LoRA tells the two apart")
        kinds = {r["kind"] for r in self.recs}
        self.assertTrue({"lab.image", "lab.cutout", "lab.model3d", "lab.edit"} <= kinds)

    def test_the_title_carries_the_positive_prompt_or_the_input(self):
        run = self.by[RUNNING]
        self.assertTrue(run["title"].startswith("Image: Qwen-Image-2512 · A clean reference sheet"), run["title"])
        self.assertNotIn("低分辨率", run["title"], "never the negative prompt")
        pix = next(r for r in self.recs if r["kind"] == "lab.model3d")
        self.assertTrue(pix["title"].endswith(".png"), "a 3D job is named by its input picture")

    def test_stages_follow_the_graph(self):
        run = self.by[RUNNING]
        self.assertEqual([s["id"] for s in run["steps"]], ["load", "prompt", "sample", "decode", "save"])
        cut = self.by[PENDING]
        self.assertEqual([s["id"] for s in cut["steps"]], ["load", "inputs", "save"])
        self.assertTrue(all(s["state"] == "todo" for s in cut["steps"]))
        done = next(r for r in self.recs if r["state"] == "succeeded")
        self.assertTrue(all(s["state"] == "done" for s in done["steps"]))

    def test_the_queue_says_its_place(self):
        q = self.by[PENDING]
        self.assertEqual((q["lab"]["position"], q["lab"]["ahead"]), (1, 1))
        self.assertEqual(q["stage"], "In the queue: 1 ahead")
        self.assertEqual(q["can"], ["cancel"])
        self.assertTrue(q["cancel_safe"])
        self.assertEqual(q["lab"]["client"], "my-pipeline", "the client's own id loses its random end")

    def test_a_running_prompt_without_the_websocket_is_estimated(self):
        run = self.by[RUNNING]
        lab = run["lab"]
        self.assertTrue(lab["estimated"])
        self.assertFalse(lab["live"])
        self.assertEqual(lab["ran_at"], RAN)
        self.assertEqual(lab["elapsed_ms"], NOW - RAN)
        self.assertGreater(lab["estimate_ms"], NOW - RAN, "from the same workflow's runs here")
        self.assertEqual(run["pct"], (NOW - RAN) * 100 // lab["estimate_ms"])
        self.assertIsNone(run["step"])
        self.assertTrue(lab["interrupt"])
        later = records(now=NOW + 3600_000)
        self.assertEqual(next(r for r in later if r["lab"]["prompt_id"] == RUNNING)["pct"], 95, "an estimate never says done")

    def test_outputs_and_the_summary(self):
        done = [r for r in self.recs if r["state"] == "succeeded"]
        for r in done:
            outs = r["result"]["outputs"]
            self.assertTrue(outs, r["title"])
            self.assertTrue(r["result"]["ok"])
        glb = next(r for r in done if r["kind"] == "lab.model3d")
        self.assertEqual(glb["result"]["outputs"][0]["kind"], "model3d")
        self.assertEqual(glb["result"]["summary"], "1 3D model made")
        img = next(r for r in done if r["kind"] == "lab.image")
        self.assertEqual(img["result"]["summary"], "1 image made")
        self.assertEqual(img["result"]["outputs"][0]["subfolder"], "my-pipeline")
        self.assertEqual(img["can"], [])

    def test_an_error_and_an_interrupt(self):
        recs = records(history=ENDS)
        by = {r["lab"]["prompt_id"]: r for r in recs}
        bad = by["0e5a4f6c-0000-4000-8000-00000000e001"]
        self.assertEqual(bad["state"], "failed")
        self.assertIn("out of memory", bad["error"]["words"])
        self.assertEqual(bad["error"]["step"], "sample")
        self.assertEqual(bad["error"]["fix"], "It failed in KSampler.")
        self.assertFalse(bad["result"]["ok"])
        stopped = by["0e5a4f6c-0000-4000-8000-00000000e002"]
        self.assertEqual(stopped["state"], "cancelled")
        self.assertEqual(stopped["result"]["summary"], "Interrupted before it finished.")

    def test_an_unknown_graph_still_reads(self):
        graph = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "my_model_v3.safetensors"}},
                 "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a lighthouse", "clip": ["1", 1]}},
                 "3": {"class_type": "KSampler", "inputs": {"positive": ["2", 0], "model": ["1", 0]}},
                 "4": {"class_type": "SaveAnimatedWEBP", "inputs": {"images": ["3", 0]}}}
        kind, label, name, words, wf = L.describe_with(graph, wfs())
        self.assertEqual((kind, label, name, words, wf), ("lab.video", "Video", "my_model_v3", "a lighthouse", None))

    def test_a_shape_that_isnt_comfyuis_is_no_crash(self):
        self.assertEqual(L.comfy_records(INST, {"queue_running": [["x"]], "queue_pending": "no"}, {"a": 1}, NOW, []), [])
        got, why = L.poll(INST, FakeHttp(queue=[], history={}), NOW)
        self.assertEqual((got, why), ([], "its answer wasn't ComfyUI's"))

        class Down(FakeHttp):
            def get(self, path):
                raise OSError("connection refused to http://comfy.invalid:8188")
        got, why = L.poll(INST, Down(), NOW)
        self.assertEqual(why, "it isn't answering")
        self.assertNotIn("invalid", why, "the address is never in the words")


class Live(unittest.TestCase):
    """The websocket's frames, through the follower."""

    def setUp(self):
        self.m = FakeMachine()
        cfg = self.m.tmp / "labjobs.toml"
        cfg.write_text('[[comfyui]]\nname = "studio"\nurl = "http://comfy.invalid:8188"\n')
        self.m.environ["BROMIGOS_LABJOBS_CONFIG"] = str(cfg)
        self.where = L.Where(self.m.env(), system=False)
        self.http = FakeHttp()
        self.f = L.Follower(self.where, websocket=False, http={"studio": self.http}, log=lambda w: None)
        self.f.graphs[("studio", RUNNING)] = QUEUE["queue_running"][0][2]
        L.PREVIEW_EVERY_S, self.every = 0.0, L.PREVIEW_EVERY_S

    def tearDown(self):
        L.PREVIEW_EVERY_S = self.every
        self.m.close()

    def feed(self, frames):
        for fr in frames:
            self.f.on_message(INST, json.dumps(fr["text"]) if "text" in fr else base64.b64decode(fr["binary"]))

    def test_progress_and_previews_make_a_live_record(self):
        self.feed(WS["frames"])
        live = self.f.live["studio"][RUNNING]
        self.assertEqual(live["progress"], {"value": 37, "max": 50, "node": "8"})
        self.assertEqual(live["stage_max"], L.STAGE_INDEX["sample"])
        self.assertRegex(live["preview"]["media"], L.MEDIA_NAME)
        self.assertTrue(live["preview"]["media"].endswith(".jpg"), "the last frame: JPEG, matched to the prompt that runs")
        rec = next(r for r in records(live=json.loads(json.dumps(self.f.live["studio"]))) if r["lab"]["prompt_id"] == RUNNING)
        self.assertEqual([s["state"] for s in rec["steps"]], ["done", "done", "running", "todo", "todo"])
        self.assertEqual(rec["steps"][2]["progress"], {"done": 37.0, "total": 50.0, "unit": "steps"})
        self.assertEqual(rec["stage"], "Sample · 37 of 50 steps")
        self.assertEqual(rec["step"], 2)
        self.assertFalse(rec["lab"]["estimated"])
        self.assertTrue(rec["lab"]["live"])
        # load 10 + prompt 5 done, sample 70 at 37/50, of 98
        self.assertEqual(rec["pct"], int((15 + 70 * 37 / 50) * 100 / 98))
        self.assertEqual(rec["lab"]["ran_at"], 1794513000000, "execution_start says when it began")

    def test_a_preview_with_metadata_names_its_prompt(self):
        frame = next(f for f in WS["frames"] if f.get("binary") and "METADATA" in f.get("about", ""))
        self.f.on_message(INST, base64.b64decode(frame["binary"]))
        self.assertTrue(self.f.live["studio"][RUNNING]["preview"]["media"].endswith(".png"))
        path = L.media_path(self.where.media_dir(), self.f.live["studio"][RUNNING]["preview"]["media"])
        self.assertTrue(path and Path(path).read_bytes().startswith(b"\x89PNG"))

    def test_a_strangers_socket_has_nothing_to_show(self):
        self.feed(STATUS["frames"])
        self.assertEqual(self.f.live.get("studio") or {}, {})

    def test_junk_frames_are_dropped(self):
        for junk in (b"", b"\x00\x00\x00\x04\xff\xff\xff\xff", b"\x00\x00\x00\x01\x00\x00\x00\x01", "not json",
                     json.dumps({"type": "progress", "data": {"prompt_id": "../../etc"}}), json.dumps([1, 2])):
            self.f.on_message(INST, junk)
        self.assertEqual(self.f.live.get("studio") or {}, {})

    def test_a_pass_writes_jobs_json_and_keeps_outputs(self):
        self.feed(WS["frames"])
        got = self.f.pass_once()
        doc = json.loads(Path(self.where.state_dir(), "jobs.json").read_text())
        self.assertEqual(doc["schema"], 1)
        self.assertEqual(doc["instances"], [{"name": "studio", "state": "ok", "words": "", "live": False, "relay": True}])
        self.assertEqual(len(doc["jobs"]), len(got))
        done = [j for j in doc["jobs"] if j["state"] == "succeeded"]
        for j in done[:L.OUTPUTS_CACHED]:
            o = j["result"]["outputs"][0]
            self.assertRegex(o["media"], L.MEDIA_NAME)
            self.assertTrue(L.media_path(self.where.media_dir(), o["media"]))
        views = [g for g in self.http.gets if g.startswith("/view?")]
        self.assertEqual(len(views), min(len(done), L.OUTPUTS_CACHED))
        self.f.pass_once()
        self.assertEqual(len([g for g in self.http.gets if g.startswith("/view?")]), len(views), "each output fetched once")
        run = next(j for j in doc["jobs"] if j["state"] == "running")
        self.assertRegex(run["lab"]["preview"]["media"], L.MEDIA_NAME)
        # readers take the follower's records, without asking ComfyUI themselves
        doc = json.loads(Path(self.where.state_dir(), "jobs.json").read_text())
        env = self.m.env(BROMIGOS_ACTIVITY_NOW_MS=doc["at"])
        listed = L.jobs(env, L.Where(env), live=False)
        self.assertEqual({j["id"] for j in listed}, {j["id"] for j in doc["jobs"]})

    def test_an_old_state_file_isnt_used(self):
        self.f.pass_once()
        doc = json.loads(Path(self.where.state_dir(), "jobs.json").read_text())
        env = self.m.env(BROMIGOS_ACTIVITY_NOW_MS=doc["at"] + L.STATE_FRESH_MS + 1)
        self.assertEqual(L.jobs(env, L.Where(env), live=False), [])


class Stopping(unittest.TestCase):

    def test_a_queued_prompt_leaves_the_queue(self):
        http = FakeHttp()
        self.assertEqual(L.stop_prompt(http, PENDING), (None, "Taken out of the queue."))
        self.assertEqual(http.posts, [("/queue", {"delete": [PENDING]})])

    def test_a_running_prompt_is_interrupted_by_its_id(self):
        http = FakeHttp()
        self.assertEqual(L.stop_prompt(http, RUNNING), (None, "Interrupted."))
        self.assertEqual(http.posts, [("/interrupt", {"prompt_id": RUNNING})])

    def test_an_ended_prompt_is_left_alone(self):
        http = FakeHttp()
        self.assertEqual(L.stop_prompt(http, next(iter(HISTORY))), ("ended", "It has already ended."))
        self.assertEqual(http.posts, [])

    def test_cancel_through_bromigos_activity(self):
        m = FakeMachine()
        self.addCleanup(m.close)
        cfg = m.tmp / "labjobs.toml"
        cfg.write_text('[[comfyui]]\nname = "studio"\nurl = "http://comfy.invalid:8188"\n')
        env = m.env(BROMIGOS_LABJOBS_CONFIG=cfg, BROMIGOS_ACTIVITY_NOW_MS=NOW)
        where = L.Where(env, system=False)
        http = FakeHttp()
        f = L.Follower(where, websocket=False, http={"studio": http}, log=lambda w: None)
        f.pass_once()
        out = L.cancel(env, f"comfy-studio-{PENDING}", where, http={"studio": http})
        self.assertTrue(out["ok"], out)
        self.assertIn(("/queue", {"delete": [PENDING]}), http.posts)
        out = L.cancel(env, next(r["id"] for r in L.jobs(env, where, live=False) if r["state"] == "succeeded"), where)
        self.assertEqual(out["refused"], "ended")

    def test_without_the_network_the_follower_does_it(self):
        """Root's board helper has no network: it asks the follower through root's folder."""
        m = FakeMachine()
        self.addCleanup(m.close)
        cfg = m.tmp / "labjobs.toml"
        cfg.write_text('[[comfyui]]\nname = "studio"\nurl = "http://comfy.invalid:8188"\n')
        asks = m.tmp / "asks"
        asks.mkdir()
        env = m.env(BROMIGOS_LABJOBS_CONFIG=cfg, BROMIGOS_LABJOBS_ASKS=asks, BROMIGOS_LABJOBS_STATE=m.tmp / "state",
                    BROMIGOS_LABJOBS_MEDIA=m.tmp / "media")
        where = L.Where(env, system=True)
        http = FakeHttp()
        f = L.Follower(where, websocket=False, http={"studio": http}, log=lambda w: None)
        f.pass_once()
        stop = threading.Event()

        def follow():
            while not stop.is_set():
                f.handle_asks()
                time.sleep(0.02)
        t = threading.Thread(target=follow, daemon=True)
        t.start()
        try:
            out = L.cancel(env, f"comfy-studio-{RUNNING}", where, wait=5)
        finally:
            stop.set()
            t.join()
        self.assertEqual((out["ok"], out["words"]), (True, "Interrupted."))
        self.assertEqual(http.posts, [("/interrupt", {"prompt_id": RUNNING})])
        self.assertEqual(list(asks.iterdir()), [], "the asker takes its request back")
        # an ask that isn't a lab job's, or is old, does nothing
        A.write_json(str(asks / "00000000000000aa.json"), {"id": "00000000000000aa", "verb": "cancel", "job": "rm -rf /",
                                                           "at": env.now_ms()}, 0o640)
        A.write_json(str(asks / "00000000000000bb.json"), {"id": "00000000000000bb", "verb": "cancel",
                                                           "job": f"comfy-studio-{PENDING}", "at": env.now_ms() - 120_000}, 0o640)
        f.handle_asks()
        self.assertEqual(len(http.posts), 1)


class Feeds(unittest.TestCase):

    def setUp(self):
        self.m = FakeMachine()
        self.env = self.m.env()
        self.where = L.Where(self.env, system=False)

    def tearDown(self):
        self.m.close()

    def test_a_run_reads_as_a_job(self):
        pic = self.m.tmp / "cut.png"
        pic.write_bytes(PNG)
        with L.Feed("ships-20261112", "Universe assets: ships", env=self.env) as feed:
            feed.step("cutout", "Cut out ship-a")
            feed.media(pic)
            feed.step("shape", "Shape ship-a")
            feed.stage(50, "Half way")
            feed.output(pic)
        rec = L.find(self.env, "feed-ships-20261112", self.where)
        self.assertEqual(rec["state"], "succeeded")
        self.assertEqual(rec["title"], "Universe assets: ships")
        self.assertEqual(rec["kind"], "lab.pipeline")
        self.assertEqual([(s["id"], s["label"], s["state"]) for s in rec["steps"]],
                         [("cutout", "Cut out ship-a", "done"), ("shape", "Shape ship-a", "done")])
        self.assertEqual(rec["lab"]["preview"]["step"], "cutout")
        self.assertEqual(rec["lab"]["preview"]["path"], str(pic))
        self.assertEqual([o["role"] for o in rec["result"]["outputs"]], ["output"])
        self.assertEqual(rec["result"]["summary"], "Half way")
        self.assertEqual(rec["can"], [])

    def test_an_exception_ends_it_failed_with_its_words(self):
        with self.assertRaises(RuntimeError):
            with L.Feed("ships", "Ships", env=self.env) as feed:
                feed.step("bake", "Bake")
                raise RuntimeError("Blender ran out of memory")
        rec = L.find(self.env, "feed-ships", self.where)
        self.assertEqual(rec["state"], "failed")
        self.assertEqual(rec["error"]["words"], "Blender ran out of memory")
        self.assertEqual(rec["error"]["step"], "bake")

    def test_a_writer_gone_or_quiet_is_interrupted(self):
        L.Feed("gone", "Gone", env=self.env, pid=1).step("x", "X")
        path = Path(self.where.write_feed(), "gone.jsonl")
        lines = path.read_text().splitlines()
        first = json.loads(lines[0])
        first["start"]["boot_id"] = "another-boot"
        path.write_text("\n".join([json.dumps(first)] + lines[1:]) + "\n")
        self.assertEqual(L.find(self.env, "feed-gone", self.where)["state"], "interrupted")
        L.Feed("quiet", "Quiet", env=self.env, pid=None).step("x", "X")
        later = self.m.env(BROMIGOS_ACTIVITY_NOW_MS=int(time.time() * 1000) + L.FEED_QUIET_MS + 60_000)
        rec = L.find(later, "feed-quiet", L.Where(later, system=False))
        self.assertEqual(rec["state"], "interrupted")
        self.assertIn("hasn't said anything", rec["error"]["words"])
        self.assertEqual(L.find(self.env, "feed-quiet", self.where)["state"], "running")

    def test_lines_that_arent_the_format_are_skipped(self):
        folder = Path(self.where.write_feed())
        folder.mkdir(parents=True)
        t = self.env.now_ms()
        (folder / "odd.jsonl").write_text("\n".join([
            json.dumps({"v": 1, "at": t, "start": {"title": "Odd", "kind": "not a kind!"}}),
            "not json", json.dumps([1]), json.dumps({"at": t + 1, "line": "plain output"}),
            json.dumps({"at": t + 2, "line": "::step a running A token=sk-abcdefabcdefabcdefabcdef"}),
            json.dumps({"at": t + 3, "line": "::step a running " + "x" * 5000}),
            json.dumps({"at": t + 4, "media": {"path": "rel/pic.png"}}),
        ]) + "\n")
        (folder / "Bad Name.jsonl").write_text(json.dumps({"start": {"title": "x"}}) + "\n")
        rec = L.find(self.env, "feed-odd", self.where)
        self.assertEqual(rec["kind"], "lab.pipeline")
        self.assertEqual([s["id"] for s in rec["steps"]], ["a"])
        self.assertNotIn("sk-abcdef", json.dumps(rec), "a feed's words are redacted like a job's")
        self.assertEqual(rec["lab"]["media"][0]["path"], str(folder / "rel" / "pic.png"), "relative to the feed's folder")
        self.assertEqual([j["id"] for j in L.jobs(self.env, self.where, comfy=False)], ["feed-odd"])

    def test_the_writer_refuses_what_isnt_the_format(self):
        with self.assertRaises(A.ActivityError):
            L.Feed("Not A Run", "x", env=self.env)
        with self.assertRaises(A.ActivityError):
            L.Feed("ok", "x", kind="backup.run", env=self.env)
        with self.assertRaises(A.ActivityError):
            L.Feed("ok", "x", env=self.env).line("not a progress line")


class Cli(unittest.TestCase):

    def setUp(self):
        self.m = FakeMachine()

    def tearDown(self):
        self.m.close()

    def test_emit_then_list_show_watch_and_cancel(self):
        pic = self.m.tmp / "cut.png"
        pic.write_bytes(PNG)
        for args in (("start", "--title", "Universe assets: ships"), ("::step", "cutout", "running", "Cutting", "out", "ship-a"),
                     ("media", str(pic), "--step", "cutout"), ("::stage", "40", "Cutting out")):
            code, out, err = self.m.cli("emit", "ships", *args)
            self.assertEqual(code, 0, err)
        jobs = self.m.listed("--lab")
        self.assertEqual([j["id"] for j in jobs], ["feed-ships"])
        self.assertEqual(jobs[0]["steps"][0]["label"], "Cutting out ship-a")
        self.assertEqual(self.m.listed("--server"), [])
        code, out, err = self.m.cli("show", "feed-ships")
        self.assertEqual(code, 0, err)
        self.assertIn("Universe assets: ships", out)
        self.assertIn("Feed     ", out)
        code, out, err = self.m.cli("watch", "--once")
        self.assertEqual(code, 0, err)
        self.assertIn("▸ Universe assets: ships  (running)", out)
        self.assertIn("40 %", out)
        self.assertNotIn("\x1b", out, "no escape codes when it isn't a terminal")
        code, out, err = self.m.cli("cancel", "feed-ships")
        self.assertEqual(code, 3)
        self.assertIn("stopped by the program that runs it", err)
        self.assertEqual(self.m.calls(), [], "no sudo for a lab job")
        code, out, err = self.m.cli("emit", "ships", "end", "succeeded", "1", "ship", "made")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.m.listed("--lab")[0]["result"]["summary"], "1 ship made")

    def test_wrong_words_are_a_usage_error(self):
        for args in (("emit",), ("emit", "ships", "start"), ("emit", "ships", "dance"), ("list", "--lab", "--server"),
                     ("watch", "a", "b")):
            self.assertEqual(self.m.cli(*args)[0], 2, args)
        code, out, err = self.m.cli("emit", "ships", "media", str(self.m.tmp / "missing.png"))
        self.assertEqual(code, 1)

    def test_help_names_the_lab_verbs(self):
        code, out, err = self.m.cli("--help")
        for words in ("bromigos activity watch", "bromigos activity emit RUN", "bromigos activity follow", "--lab"):
            self.assertIn(words, out)


class Config(unittest.TestCase):

    def setUp(self):
        self.m = FakeMachine()
        self.cfg = self.m.home / ".config" / "bromigos"
        self.cfg.mkdir(parents=True)

    def tearDown(self):
        self.m.close()

    def test_the_creation_settings_name_the_comfyuis(self):
        (self.cfg / "create.toml").write_text('[comfyui.studio]\nendpoint = "@env:MY_COMFY"\n[comfyui.broken]\nendpoint = "@vault:kv/x#y"\n')
        (self.cfg / "art.toml").write_text('comfyui_url = "http://10.0.0.9:8188"\n')
        env = self.m.env(MY_COMFY="http://studio.invalid:8188/", BROMIGOS_COMFYUI_URL="http://studio.invalid:8188")
        got = L.instances(L.Where(env, system=False))
        self.assertEqual([(i["name"], i["url"]) for i in got],
                         [("studio", "http://studio.invalid:8188"), ("homelab", "http://10.0.0.9:8188")])

    def test_labjobs_toml_and_what_isnt_an_address(self):
        (self.cfg / "labjobs.toml").write_text(
            '[[comfyui]]\nname = "Big GPU!"\nurl = "http://gpu.invalid:8188"\n'
            '[[comfyui]]\nname = "creds"\nurl = "http://user:pass@gpu2.invalid:8188"\n'
            '[[comfyui]]\nname = "file"\nurl = "file:///etc/passwd"\n'
            '[feed]\ndirs = ["~/feeds"]\n')
        where = L.Where(self.m.env(), system=False)
        self.assertEqual([(i["name"], i["url"]) for i in L.instances(where)], [("biggpu", "http://gpu.invalid:8188")])
        self.assertIn(str(self.m.home / "feeds"), where.feed_dirs())

    def test_the_system_reads_only_its_own(self):
        (self.cfg / "labjobs.toml").write_text('[[comfyui]]\nname = "mine"\nurl = "http://mine.invalid:8188"\n')
        sysconf = self.m.root / "etc/bromigos"
        sysconf.mkdir(parents=True)
        (sysconf / "labjobs.toml").write_text('[[comfyui]]\nname = "studio"\nurl = "http://127.0.0.1:8188"\n')
        env = self.m.env(BROMIGOS_COMFYUI_URL="http://lab.invalid:8188")
        self.assertEqual([i["name"] for i in L.instances(L.Where(env, system=True))], ["studio"])
        self.assertEqual([i["name"] for i in L.instances(L.Where(env, system=False))], ["studio", "mine", "homelab"])

    def test_with_nothing_set_this_machines_own_port(self):
        env = A.Env({k: v for k, v in self.m.environ.items() if k != "BROMIGOS_LABJOBS_NO_LOCAL"})
        got = L.instances(L.Where(env, system=False))
        self.assertEqual([(i["name"], i["url"], i.get("quiet")) for i in got], [("local", L.LOCAL_URL, True)])


class MediaFiles(unittest.TestCase):

    def test_types_by_their_bytes(self):
        self.assertEqual(L.sniff(PNG), "png")
        self.assertEqual(L.sniff(b"\xff\xd8\xff\xe0rest"), "jpg")
        self.assertEqual(L.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "webp")
        self.assertEqual(L.sniff(b"\x00\x00\x00\x18ftypmp42"), "mp4")
        self.assertEqual(L.sniff(b"glTF\x02\x00\x00\x00"), "glb")
        self.assertIsNone(L.sniff(b"<svg onload=alert(1)>"))
        self.assertIsNone(L.sniff(b"<html>"))

    def test_names_only_the_follower_makes(self):
        m = FakeMachine()
        self.addCleanup(m.close)
        media = L.Media(str(m.tmp / "media"))
        name = media.put(PNG, "of")
        self.assertRegex(name, L.MEDIA_NAME)
        self.assertEqual(media.put(PNG, "of"), name, "the same bytes, the same name")
        self.assertIsNone(media.put(b"<svg/>"))
        self.assertTrue(L.media_path(media.folder, name))
        for bad in ("../jobs.json", "of-0000000000000000.svg", "of-00000000000000000.png", "/etc/passwd", None):
            self.assertIsNone(L.media_path(media.folder, bad))
        small = L.Media(str(m.tmp / "media"), total=len(PNG))
        other = small.put(PNG + b"\x00", "of")
        small.prune(keep={other})
        self.assertTrue(L.media_path(small.folder, other))
        self.assertIsNone(L.media_path(small.folder, name), "the oldest go first")

    def test_kitty_gets_the_picture_in_chunks(self):
        big = PNG + b"\x00" * 9000
        out = L.kitty_image(big)
        self.assertTrue(out.startswith("\x1b_Ga=d,d=I,i=7311,q=2\x1b\\"))
        self.assertIn("a=T,f=100,i=7311", out)
        self.assertEqual(out.count("m=1"), 2)
        self.assertEqual(out.count("m=0"), 1)
        self.assertTrue(L.is_kitty({"KITTY_WINDOW_ID": "1"}))
        self.assertFalse(L.is_kitty({"TERM": "xterm-256color"}))


class Relay(unittest.TestCase):
    """The ComfyUI node, against a stand-in PromptServer."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("bromigos_relay", REPO / "core/crates/bromigos-art/comfyui-relay/__init__.py")
        self.relay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.relay)

        class Server:
            def __init__(s):
                s.sockets = {"client-a": object(), "bromigos-watch-1": object(), "other": object()}
                s.sent = []

            async def send_json(s, event, data, sid=None):
                s.sent.append(("json", event, sid))

            async def send_bytes(s, event, data, sid=None):
                s.sent.append(("bytes", event, sid))
        self.server = Server()

    def test_progress_and_previews_reach_the_watchers(self):
        self.assertTrue(self.relay.install(self.server))
        self.assertFalse(self.relay.install(self.server), "once")
        s = self.server

        async def go():
            await s.send_json("progress", {"value": 1}, "client-a")
            await s.send_json("status", {}, "client-a")
            await s.send_json("executing", {}, None)
            await s.send_bytes(4, b"img", "client-a")
            await s.send_bytes(3, b"text", "client-a")
            await s.send_json("progress", {}, "bromigos-watch-1")
        asyncio.run(go())
        self.assertEqual(s.sent, [
            ("json", "progress", "client-a"), ("json", "progress", "bromigos-watch-1"),
            ("json", "status", "client-a"),
            ("json", "executing", None),
            ("bytes", 4, "client-a"), ("bytes", 4, "bromigos-watch-1"),
            ("bytes", 3, "client-a"),
            ("json", "progress", "bromigos-watch-1"),
        ])
        self.assertEqual(self.relay.NODE_CLASS_MAPPINGS, {})


class ActivityHooks(unittest.TestCase):
    """bromigos_activity reads the lab's jobs where asked, and only then."""

    def test_list_find_and_cancel(self):
        m = FakeMachine()
        self.addCleanup(m.close)
        env = m.env()
        L.Feed("ships", "Ships", env=env).step("a", "A")
        self.assertEqual(A.list_jobs(env), [], "the board's own readers ask for lab jobs by name")
        self.assertEqual([j["id"] for j in A.list_jobs(env, lab={})], ["feed-ships"])
        self.assertEqual(A.find(env, "feed-ships")["title"], "Ships")
        self.assertEqual(A.find(env, "ships")["id"], "feed-ships", "a part no server job has")
        out = A.cancel(env, "feed-ships")
        self.assertEqual(out["refused"], "unsafe")
        self.assertIn("A pipeline run", A.plain_show(A.find(env, "feed-ships"), [], env.now_ms()))


if __name__ == "__main__":
    unittest.main()
