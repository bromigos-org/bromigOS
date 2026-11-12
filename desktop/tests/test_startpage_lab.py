"""The start page's LAB JOBS card (desktop/startpage/snapshot.py, lab_jobs): what the lab's
ComfyUI makes now and what it made, read through bromigos-core's lib/bromigos_labjobs.py from the
user's follower (here the real Follower, fed a real ComfyUI's recorded answers by the activity
tests' stand-in), with the pictures copied into the page folder. No ComfyUI is called, no unit
is started, and nothing outside a temporary folder is read or written."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (REPO / "lib", REPO / "tests" / "activity"):
    sys.path.insert(0, str(p))

import bromigos_activity as A  # noqa: E402
import bromigos_labjobs as L  # noqa: E402


class LabJobsCard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="startpage-lab-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        cfg = self.tmp / "labjobs.toml"
        cfg.write_text('[[comfyui]]\nname = "studio"\nurl = "http://comfy.invalid:8188"\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BROMIGOS_", "XDG_"))}
        env.update(HOME=str(self.tmp / "home"), BROMIGOS_STARTPAGE_DIR=str(self.tmp / "page"), BROMIGOS_LABJOBS_CONFIG=str(cfg),
                   BROMIGOS_STARTPAGE_NO_FOLLOW="1", XDG_RUNTIME_DIR=str(self.tmp / "run"), BROMIGOS_ROOT=str(self.tmp / "root"))
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        # (tests/alerts' `fake` may be loaded already: the activity tests' own goes in its place)
        sys.modules.pop("fake", None)
        import test_labjobs as T
        self.T = T
        spec = importlib.util.spec_from_file_location("startpage_snapshot", REPO / "desktop/startpage/snapshot.py")
        self.snap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.snap)

    def follow(self):
        f = L.Follower(L.Where(A.Env(), system=False), websocket=False, http={"studio": self.T.FakeHttp()}, log=lambda w: None)
        f.graphs[("studio", self.T.RUNNING)] = self.T.QUEUE["queue_running"][0][2]
        for fr in self.T.WS["frames"]:
            f.on_message({"name": "studio"}, json.dumps(fr["text"]) if "text" in fr else __import__("base64").b64decode(fr["binary"]))
        f.pass_once()

    def test_what_runs_now_with_its_picture_and_what_it_made(self):
        self.follow()
        card = self.snap.lab_jobs()
        self.assertEqual(len(card["running"]), 1)
        run = card["running"][0]
        self.assertTrue(run["title"].startswith("Image: Qwen-Image-2512"))
        self.assertEqual(run["stage"], "Sample · 37 of 50 steps")
        self.assertFalse(run["estimated"])
        self.assertEqual(run["where"], "ComfyUI studio")
        self.assertRegex(run["preview"], r"^lab/[0-9a-f]{16}\.(jpg|png)$")
        self.assertTrue((self.tmp / "page" / run["preview"]).is_file(), "the picture is in the page folder")
        self.assertEqual(card["queued"]["count"], 1)
        self.assertEqual(len(card["latest"]), self.snap.LAB_LATEST)
        self.assertTrue(all(m["state"] == "succeeded" for m in card["latest"]))
        self.assertTrue(card["following"])
        shown = {m["thumb"] for m in card["latest"] if m["thumb"]} | {run["preview"]}
        self.assertEqual({f"lab/{n}" for n in os.listdir(self.tmp / "page" / "lab")}, shown, "nothing else is kept")
        self.assertNotIn(str(self.tmp), json.dumps(card))

    def test_without_a_follower_it_reads_the_comfyui_and_has_no_picture_yet(self):
        with mock.patch.object(L, "reachable", return_value=True), \
                mock.patch.object(L, "Http", lambda url, timeout=L.TIMEOUT_S: self.T.FakeHttp()):
            card = self.snap.lab_jobs()
        self.assertFalse(card["following"])
        self.assertEqual(card["running"][0]["preview"], None)
        self.assertTrue(card["running"][0]["estimated"])

    def test_no_lab_no_card(self):
        os.environ["BROMIGOS_LABJOBS_CONFIG"] = str(self.tmp / "none.toml")
        os.environ["BROMIGOS_LABJOBS_NO_LOCAL"] = "1"
        self.assertIsNone(self.snap.lab_jobs())

    def test_the_page_draws_the_card(self):
        js = (REPO / "desktop/startpage/app.js").read_text()
        html = (REPO / "desktop/startpage/index.html").read_text()
        self.assertIn('id="labjobs"', html)
        self.assertIn("renderLabJobs(s, stale)", js)


if __name__ == "__main__":
    unittest.main()
