"""The lab's jobs on the board (docs/board.md, "The lab's jobs"): the lab follower's files, as
the API passes them on (the activity stream, GET /api/lab, GET /api/lab/media/NAME), stopping a
generation through root's helper, and the follower's unit. The follower is the real one
(bromigos_labjobs.Follower), fed a real ComfyUI's recorded answers (tests/activity/fixtures/
comfyui) by a stand-in: no ComfyUI is called, and the API never calls one."""
import json
import os
import sys
import time
import unittest

from common import REPO

sys.path.insert(0, str(REPO / "tests" / "activity"))

from test_api import Base, PAGE  # noqa: E402
from test_install import tmpfiles, unit, unit_lines  # noqa: E402
from test_labjobs import FakeHttp, PENDING, PNG, QUEUE, RUNNING  # noqa: E402

import bromigos_activity as A  # noqa: E402
import bromigos_labjobs as L  # noqa: E402
from bromigos_board import actions  # noqa: E402


class Lab(Base):
    def setUp(self):
        super().setUp()
        os.environ.pop("BROMIGOS_COMFYUI_URL", None)
        (self.root / "etc/bromigos/labjobs.toml").write_text('[[comfyui]]\nname = "studio"\nurl = "http://127.0.0.1:8188"\n')
        self.http = FakeHttp()
        self.where = L.Where(A.Env(), system=True)
        self.follower = L.Follower(self.where, websocket=False, http={"studio": self.http}, log=lambda w: None)
        # a pipeline run in the system's feed folder, with a thumbnail beside it
        feed = self.root / "var/lib/bromigos/activity/feed"
        feed.mkdir(parents=True)
        (feed / "ships").mkdir()
        (feed / "ships" / "cut.png").write_bytes(PNG)
        f = L.Feed("ships", "Universe assets: ships", folder=str(feed), env=A.Env())
        f.step("cutout", "Cut out ship-a")
        f.media(str(feed / "ships" / "cut.png"))
        os.chdir(self.root)

    def follow(self):
        self.follower.pass_once()
        return json.loads((self.root / "run/bromigos-labjobs/jobs.json").read_text())

    def stream(self):
        with self.c.stream("GET", "/api/activity") as r:
            self.assertEqual(r.status_code, 200)
            text = "".join(r.iter_text())
        block = next(b for b in text.split("\n\n") if b.startswith("event: snapshot"))
        return json.loads(block.split("data: ", 1)[1])["jobs"]

    def test_the_stream_carries_the_followers_jobs_and_never_a_path(self):
        doc = self.follow()
        self.sign_in()
        jobs = self.stream()
        ids = {j["id"] for j in jobs}
        self.assertIn(f"comfy-studio-{RUNNING}", ids)
        self.assertIn(f"comfy-studio-{PENDING}", ids)
        self.assertIn("feed-ships", ids)
        self.assertEqual(ids, {j["id"] for j in doc["jobs"]})
        text = json.dumps(jobs)
        self.assertNotIn(str(self.root), text, "a feed's own paths stay on the server")
        self.assertNotIn('"path"', text)
        self.assertNotIn('"file"', text)
        feed = next(j for j in jobs if j["id"] == "feed-ships")
        self.assertRegex(feed["lab"]["preview"]["media"], L.MEDIA_NAME)
        # what the follower doesn't say isn't read: a feed written since, and the ComfyUI itself
        L.Feed("later", "Later", folder=str(self.root / "var/lib/bromigos/activity/feed"), env=A.Env())
        asked = list(self.http.gets)
        self.assertNotIn("feed-later", {j["id"] for j in self.stream()})
        self.assertEqual(self.http.gets, asked)

    def test_an_old_jobs_json_shows_no_lab(self):
        self.follow()
        old = time.time() - 600
        path = self.root / "run/bromigos-labjobs/jobs.json"
        doc = json.loads(path.read_text())
        doc["at"] -= 600_000
        path.write_text(json.dumps(doc))
        os.utime(path, (old, old))
        self.sign_in()
        self.assertEqual([j for j in self.stream() if j["id"].startswith(("comfy-", "feed-"))], [])
        r = self.c.get("/api/lab")
        self.assertEqual(r.json()["following"], False)

    def test_lab_says_each_comfyui(self):
        self.assertEqual(self.c.get("/api/lab").status_code, 401)
        self.follow()
        self.sign_in()
        r = self.c.get("/api/lab")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["cache-control"], "no-store")
        doc = r.json()
        self.assertEqual(doc["following"], True)
        self.assertEqual(doc["instances"], [{"name": "studio", "state": "ok", "words": "", "live": False, "relay": False}])

    def test_media_by_the_followers_names_only(self):
        doc = self.follow()
        name = next(j for j in doc["jobs"] if j["state"] == "succeeded")["result"]["outputs"][0]["media"]
        self.assertEqual(self.c.get(f"/api/lab/media/{name}").status_code, 401)
        self.sign_in()
        r = self.c.get(f"/api/lab/media/{name}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, PNG)
        self.assertEqual(r.headers["content-type"], "image/png")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertIn("sandbox", r.headers["content-security-policy"])
        self.assertIn("immutable", r.headers["cache-control"])
        media = self.root / "var/cache/bromigos-labjobs"
        os.symlink("/etc/passwd", media / "of-00000000000000aa.png")
        (media / "notes.txt").write_text("x")
        for bad in ("of-00000000000000aa.png", "notes.txt", "..%2Fjobs.json", "of-0000000000000000.svg", "of-0000000000000000.png"):
            r = self.c.get(f"/api/lab/media/{bad}")
            self.assertEqual(r.status_code, 404, bad)
            self.assertNotIn(b"root:", r.content)

    def test_stopping_a_generation_goes_through_roots_helper(self):
        self.follow()
        ran = []

        def run(argv):
            ran.append(argv)
            import subprocess
            return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True, "refused": None, "words": "Interrupted."}), "")
        now = int(time.time() * 1000)
        doc = {"verb": "job.cancel", "job": f"comfy-studio-{RUNNING}", "at": now, "browser": "Firefox on Linux"}
        out = actions.decide_job(doc, now, run, log=lambda w: None)
        self.assertEqual(out["job"], f"comfy-studio-{RUNNING}")
        self.assertEqual(ran, [["bromigos-activity", "cancel", f"comfy-studio-{RUNNING}", "--json"]])
        # a pipeline run is the program's own to stop; a generation that ended can't be stopped
        with self.assertRaises(actions.Refused) as e:
            actions.decide_job(dict(doc, job="feed-ships"), now, run, log=lambda w: None)
        self.assertEqual(e.exception.code, "not-safe")
        done = next(j["id"] for j in json.loads((self.root / "run/bromigos-labjobs/jobs.json").read_text())["jobs"]
                    if j["state"] == "succeeded")
        with self.assertRaises(actions.Refused) as e:
            actions.decide_job(dict(doc, job=done), now, run, log=lambda w: None)
        self.assertEqual(e.exception.code, "ended")
        # a shape that is neither a server job's nor a lab job's never reaches a command
        for bad in ("comfy-studio-not-a-uuid", "feed-../../etc", "comfy-STUDIO-" + RUNNING):
            with self.assertRaises(actions.Refused):
                actions.check_job_shape("job.cancel", bad)
        self.assertEqual(len(ran), 1)

    def test_the_page_asks_through_the_api(self):
        self.follow()
        self.sign_in()
        r = self.c.post(f"/api/activity/comfy-studio-{PENDING}/cancel", json={}, headers=PAGE)
        # here nothing takes the request out (root's helper isn't running): asked, and it waits
        self.assertIn(r.status_code, (202, 503), r.text)


class FollowerUnit(unittest.TestCase):
    def test_its_own_user_out_to_private_addresses_only(self):
        svc = unit("bromigos-board-lab.service")
        self.assertEqual((svc["User"], svc["Group"]), ("bromigos-labjobs", "bromigos-labjobs"))
        self.assertTrue(svc["ExecStart"].startswith("/usr/lib/bromigos/bin/bromigos-activity follow --system"))
        self.assertEqual(svc["IPAddressDeny"], "any")
        allow = svc["IPAddressAllow"].split()
        self.assertNotIn("any", allow)
        self.assertTrue(all(a in ("localhost", "link-local") or a.startswith(("10.", "172.16.", "192.168.", "100.64.", "fc00:")) for a in allow), allow)
        self.assertEqual(svc["SocketBindDeny"], "any")
        self.assertEqual(svc["RestrictAddressFamilies"], "AF_UNIX AF_INET AF_INET6")
        self.assertEqual(set(" ".join(unit_lines("bromigos-board-lab.service", "ReadWritePaths")).split()),
                         {"/run/bromigos-labjobs", "/var/cache/bromigos-labjobs"})
        for key, want in (("ProtectSystem", "strict"), ("ProtectHome", "yes"), ("NoNewPrivileges", "yes"),
                          ("CapabilityBoundingSet", ""), ("PrivateDevices", "yes"), ("ReadOnlyPaths", "/run")):
            self.assertEqual(svc.get(key), want, key)
        self.assertEqual(unit_lines("bromigos-board-lab.path", "PathModified"), ["/run/bromigos-board/wanted"])
        # root's helper may hand it a cancel, and write nowhere else new
        self.assertIn("-/run/bromigos-labjobs-asks", unit_lines("bromigos-board-act.service", "ReadWritePaths"))

    def test_its_folders(self):
        t = tmpfiles()
        self.assertEqual(t["/run/bromigos-labjobs"], ("d", "2750", "bromigos-labjobs", "bromigos-board"))
        self.assertEqual(t["/var/cache/bromigos-labjobs"], ("d", "2750", "bromigos-labjobs", "bromigos-board"))
        self.assertEqual(t["/run/bromigos-labjobs-asks"], ("d", "2750", "root", "bromigos-labjobs"))
        self.assertEqual(L.SYSTEM_STATE, "/run/bromigos-labjobs")
        self.assertEqual(L.SYSTEM_MEDIA, "/var/cache/bromigos-labjobs")
        self.assertEqual(L.SYSTEM_ASKS, "/run/bromigos-labjobs-asks")


if __name__ == "__main__":
    unittest.main()
