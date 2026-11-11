"""The lab model catalog's review queue (catalog_review.py): the recommendation rules, the
eight-week archive, `review accept|ignore`, and the rolling "Lab catalog review" issue, against
the small made-up catalog (fixtures/lab-catalog.toml) with made-up pending entries. No network:
the issue's gh calls are a dry run against a recorded issue list (fixtures/lab-catalog-issues.json).

    PYTHONPATH=lib python -m unittest tests.test_lab_catalog_review
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("BROMIGOS_HOMELAB_CONFIG", "/nonexistent")
os.environ.setdefault("BROMIGOS_LAB_BENCH_LEDGER", "/nonexistent")
os.environ.setdefault("BROMIGOS_LAB_SETTINGS", "/nonexistent")

from bromigos_homelab import catalog as C                    # noqa: E402
from bromigos_homelab import catalog_review as R             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "lab-catalog.toml")
ISSUES = os.path.join(HERE, "fixtures", "lab-catalog-issues.json")
REAL = os.path.normpath(os.path.join(HERE, "..", "share", "lab", "models.toml"))
TODAY = "2026-11-10"

try:
    import tomlkit  # noqa: F401
    HAVE_TOMLKIT = True
except ImportError:                                           # CI installs python-tomlkit
    HAVE_TOMLKIT = False

PENDING = '''
[[pending]]
id = "hf:org/Ready-Big-35B-A3B"
kind = "new model"
capability = "llm"
repo = "org/Ready-Big-35B-A3B"
why = "new in the last 60 days (5 days old), 900 likes, 50000 downloads"
stack = "ready (vllm, sglang)"
licence = "apache-2.0"
found = "2026-11-02"
state = "pending review"

[[pending]]
id = "hf:org/Unsupported-9B"
kind = "new model"
capability = "llm"
repo = "org/Unsupported-9B"
why = "new in the last 60 days (9 days old), 40 likes, 300 downloads"
stack = "needs support: no vLLM, llama.cpp, Ollama or MLX support on the Hub yet"
licence = "apache-2.0"
found = "2026-11-02"
state = "pending review"

[[pending]]
id = "hf:org/Popular-Unsupported-9B"
kind = "new model"
capability = "llm"
repo = "org/Popular-Unsupported-9B"
why = "new in the last 60 days (9 days old), 2000 likes, 90000 downloads"
stack = "needs support: no vLLM, llama.cpp, Ollama or MLX support on the Hub yet"
licence = "apache-2.0"
found = "2026-11-02"
state = "pending review"

[[pending]]
id = "hf:org/Mystery-30B"
kind = "new model"
capability = "llm"
repo = "org/Mystery-30B"
why = "new in the last 60 days (3 days old), 1500 likes, 40000 downloads"
stack = "ready (vllm)"
licence = "other"
found = "2026-11-09"
state = "pending review"

[[pending]]
id = "hf:org/Huge-9000B"
kind = "new model"
capability = "llm"
repo = "org/Huge-9000B"
why = "1000 likes, 9000 downloads"
stack = "ready (vllm)"
licence = "apache-2.0"
found = "2026-11-09"
state = "pending review"

[[pending]]
id = "hf:org/Tiny-150M"
kind = "new model"
capability = "llm"
repo = "org/Tiny-150M"
why = "1000 likes, 90000 downloads"
stack = "ready (vllm)"
licence = "apache-2.0"
found = "2026-11-09"
state = "pending review"

[[pending]]
id = "hf:org/Chat-7B-Base"
kind = "new model"
capability = "llm"
repo = "org/Chat-7B-Base"
why = "1000 likes, 90000 downloads"
stack = "ready (vllm)"
licence = "apache-2.0"
found = "2026-11-09"
state = "pending review"

[[pending]]
id = "hf:org/img-a3"
kind = "newer in family"
capability = "image"
repo = "org/img-a3"
why = "org published it 4 days ago (20 likes)"
stack = "ready (ComfyUI: Comfy-Org/img-a3)"
licence = "apache-2.0"
model = "img-a2"
found = "2026-11-09"
state = "pending review"

[[pending]]
id = "hf:org/Research-Only"
kind = "new model"
capability = "image"
repo = "org/Research-Only"
why = "500 likes, 9000 downloads"
stack = "needs support: no ComfyUI-native repackage (Comfy-Org) yet"
licence = "research"
found = "2026-11-02"
state = "pending review"

[[pending]]
id = "licence:mesh-mit:research"
kind = "licence changed"
capability = "3d"
repo = "org/mesh-mit"
why = "the Hub says research"
licence = "research"
model = "mesh-mit"
found = "2026-11-02"
state = "pending review"

[[pending]]
id = "hf:org/Old-Forgotten"
kind = "new model"
capability = "image"
repo = "org/Old-Forgotten"
why = "50 likes, 400 downloads"
stack = "ready (ComfyUI: Comfy-Org/Old-Forgotten)"
licence = "apache-2.0"
found = "2026-08-01"
state = "pending review"

[[pending]]
id = "hf:org/Now-Added"
kind = "new model"
capability = "image"
repo = "org/Now-Added"
why = "500 likes, 4000 downloads"
stack = "ready (ComfyUI: Comfy-Org/Now-Added)"
licence = "apache-2.0"
found = "2026-11-02"
state = "accepted"
accepted = "2026-11-03"

[[pending]]
id = "hf:org/Already-Dismissed"
kind = "new model"
capability = "image"
repo = "org/Already-Dismissed"
why = "500 likes"
found = "2026-08-01"
state = "dismissed"
dismissed = "a robot policy"

[[model]]
id = "now-added"
name = "Now Added"
repo = "org/Now-Added"
capabilities = ["image"]
licence = "apache-2"
quality = 60
cite = ["fixture"]
  [[model.variant]]
  id = "fp16"
  runtime = "comfyui"
  quant = "FP16"
  vram_gib = 10
  speed = 20
  speed_ref = "RTX 4090"
'''


class Fixture:
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lab-review-")
        self.path = os.path.join(self.tmp, "models.toml")
        with open(FIXTURE) as f:
            text = f.read()
        with open(self.path, "w") as f:
            f.write(text + PENDING)
        self.cat = C.load(self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def rec(self, ident):
        p = next(p for p in self.cat.pending if p["id"] == ident)
        return R.recommend(self.cat, p, TODAY)


class RecommendTest(Fixture, unittest.TestCase):
    def test_ready_clean_popular_and_fitting_is_adopt(self):
        r = self.rec("hf:org/Ready-Big-35B-A3B")
        self.assertEqual(r["action"], "adopt", r)
        self.assertEqual(r["signals"]["params_b"], 35)
        self.assertEqual(r["signals"]["active_b"], 3)
        self.assertIn("Apache 2.0 (clean)", r["reason"])
        self.assertIn("24 GB card at 4-bit", r["reason"])

    def test_unsupported_and_little_used_is_ignore_and_popular_is_watch(self):
        self.assertEqual(self.rec("hf:org/Unsupported-9B")["action"], "ignore")
        r = self.rec("hf:org/Popular-Unsupported-9B")
        self.assertEqual(r["action"], "watch")
        self.assertIn("waiting for support", r["reason"])

    def test_an_unnamed_licence_waits_for_the_card(self):
        r = self.rec("hf:org/Mystery-30B")
        self.assertEqual(r["action"], "watch")
        self.assertEqual(r["signals"]["licence_tier"], "unknown")
        self.assertIn("read the card", r["reason"])

    def test_size_rules(self):
        self.assertEqual(self.rec("hf:org/Huge-9000B")["action"], "ignore")       # no setup holds it
        tiny = self.rec("hf:org/Tiny-150M")
        self.assertEqual(tiny["action"], "ignore")
        self.assertIn("smaller than the smallest llm", tiny["reason"])
        self.assertEqual(self.rec("hf:org/Chat-7B-Base")["action"], "ignore")    # a base model

    def test_a_newer_member_of_a_top_family_is_adopt_despite_few_likes(self):
        r = self.rec("hf:org/img-a3")
        self.assertEqual(r["action"], "adopt", r)
        self.assertIn("near the top", r["reason"])

    def test_non_commercial_and_unsupported_is_ignore(self):
        r = self.rec("hf:org/Research-Only")
        self.assertEqual(r["action"], "ignore")
        self.assertIn("non-commercial", r["reason"])

    def test_a_licence_change_is_adopt_with_what_to_do(self):
        r = self.rec("licence:mesh-mit:research")
        self.assertEqual(r["action"], "adopt")
        self.assertIn("set the model's licence", r["reason"])

    def test_params_from_the_name(self):
        self.assertEqual(R.params_of({"repo": "a/Qwen3.6-35B-A3B"}), (35, 3))
        self.assertEqual(R.params_of({"repo": "a/GPT-X3-150M"}), (0.15, 0.15))
        self.assertEqual(R.params_of({"repo": "a/Kimi-K3.1-Pro"}), (None, None))
        self.assertEqual(R.params_of({"repo": "a/x", "params_b": 12.5}), (12.5, 12.5))

    def test_the_licence_tier(self):
        self.assertEqual(self.cat.licences["apache-2"].tier, "clean")
        self.assertEqual(self.cat.licences["research"].tier, "non-commercial")
        self.assertEqual(self.cat.licences["regional"].tier, "conditional")
        self.assertIsNone(self.cat.hub_licence("other"))
        self.assertEqual(self.cat.hub_licence("apache-2.0").id, "apache-2")


class QueueTest(Fixture, unittest.TestCase):
    def test_queue_counts_and_order(self):
        rows = R.queue(self.cat, TODAY)
        ids = [r["id"] for r in rows]
        self.assertNotIn("hf:org/Already-Dismissed", ids)
        c = R.counts(rows)
        self.assertEqual(c["accepted"], 1)
        self.assertEqual(c["to_review"], 11)
        self.assertEqual(c["adopt"] + c["watch"] + c["ignore"], c["to_review"])
        # adopt first, accepted last
        self.assertEqual(rows[0]["action"], "adopt")
        self.assertEqual(rows[-1]["state"], "accepted")
        self.assertTrue(rows[-1]["added"])

    def test_review_command_text_and_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = C.main(["review", "--catalog", self.path, "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertIn("nobody has decided on yet", out.getvalue())
        self.assertIn("Adopt (research it", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = C.main(["review", "--json", "--catalog", self.path, "--today", TODAY])
        doc = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(doc["counts"]["to_review"], 11)
        self.assertTrue(all(e["action"] in R.ACTIONS and e["reason"] for e in doc["entries"]))

    def test_a_bad_verb_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(R.main(["frobnicate", "--catalog", self.path]), 2)


@unittest.skipUnless(HAVE_TOMLKIT, "needs python-tomlkit")
class EditTest(Fixture, unittest.TestCase):
    def test_accept_and_ignore(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(R.main(["accept", "org/ready-big-35b-a3b", "--catalog", self.path]), 0)
            self.assertEqual(R.main(["ignore", "hf:org/Unsupported-9B", "--reason", "a duplicate",
                                     "--catalog", self.path]), 0)
        cat = C.load(self.path)
        st = {p["id"]: p for p in cat.pending}
        self.assertEqual(st["hf:org/Ready-Big-35B-A3B"]["state"], "accepted")
        self.assertEqual(st["hf:org/Unsupported-9B"]["state"], "dismissed")
        self.assertEqual(st["hf:org/Unsupported-9B"]["dismissed"], "a duplicate")
        self.assertEqual(C.validate(cat), [])
        with open(self.path) as f:
            self.assertIn("# A small, made-up lab model catalog", f.read())     # the layout is kept

    def test_an_unknown_id_is_a_problem(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(R.main(["accept", "org/nope", "--catalog", self.path]), 2)

    def test_archive_after_eight_weeks_and_once_added(self):
        import tomlkit
        with open(self.path) as f:
            doc = tomlkit.parse(f.read())
        moved = R.archive(doc, self.cat, TODAY)
        self.assertEqual(sorted(moved), ["hf:org/Now-Added", "hf:org/Old-Forgotten"])
        arch = {a["id"]: a for a in doc["archived"]}
        self.assertIn("no decision in 14 weeks", arch["hf:org/Old-Forgotten"]["reason"])
        self.assertIn("added to the catalog as now-added", arch["hf:org/Now-Added"]["reason"])
        self.assertNotIn("hf:org/Old-Forgotten", [p["id"] for p in doc["pending"]])
        self.assertIn("hf:org/Already-Dismissed", [p["id"] for p in doc["pending"]])   # a decision stays
        with open(self.path, "w") as f:
            f.write(tomlkit.dumps(doc))
        cat = C.load(self.path)
        self.assertEqual(len(cat.archived), 2)
        # nothing more to move a week on
        self.assertEqual(R.archive(doc, cat, TODAY), [])

    def test_propose_archives_and_bumps_the_version(self):
        from bromigos_homelab import catalog_refresh as F
        text, counts = F.propose(self.path, [], today=TODAY, cat=self.cat)
        self.assertEqual(counts["archived"], 2)
        self.assertIn("[[archived]]", text)
        self.assertIn("version = 2", text)


class IssueTest(Fixture, unittest.TestCase):
    def issues(self):
        with open(ISSUES) as f:
            return json.load(f)

    def test_the_plan_creates_one_issue_and_closes_the_weekly_ones(self):
        plan = R.issue_plan(self.issues())
        self.assertTrue(plan["create"])
        self.assertIsNone(plan["update"])
        self.assertEqual(plan["close"], [1, 3, 5, 7, 82, 96])        # #4 is closed already

    def test_the_plan_updates_the_rolling_issue(self):
        issues = self.issues() + [{"number": 120, "title": "Lab catalog review", "state": "OPEN", "url": "u/120"},
                                  {"number": 130, "title": "Lab catalog review", "state": "OPEN", "url": "u/130"}]
        plan = R.issue_plan(issues)
        self.assertFalse(plan["create"])
        self.assertEqual(plan["update"], 120)                          # the oldest one rolls
        self.assertIn(130, plan["close"])                              # a duplicate goes
        self.assertNotIn(120, plan["close"])

    def test_a_closed_rolling_issue_reopens_and_an_empty_queue_closes_it(self):
        closed = [{"number": 120, "title": "Lab catalog review", "state": "CLOSED", "url": "u/120"}]
        self.assertTrue(R.issue_plan(closed)["reopen"])
        opened = [{"number": 120, "title": "Lab catalog review", "state": "OPEN", "url": "u/120"}]
        self.assertTrue(R.issue_plan(opened, nonempty=False)["close_rolling"])
        self.assertFalse(R.issue_plan([], nonempty=False)["create"])

    def test_issue_sync_dry_run_runs_no_gh(self):
        def boom(args):
            raise AssertionError(f"ran gh {args}")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            r = R.issue_sync(self.cat, "example/repo", "the report", self.issues(), dry_run=True, today=TODAY, run=boom)
        cmds = [" ".join(c) for c in r["commands"]]
        self.assertTrue(cmds[0].startswith("gh issue create -R example/repo --title Lab catalog review"))
        self.assertEqual(sum(1 for c in cmds if c.startswith("gh issue close")), 6)
        self.assertIn("keeps one issue up to date", cmds[-1])
        self.assertIn("gh issue create", out.getvalue())

    def test_issue_sync_updates_through_gh(self):
        calls = []
        issues = self.issues() + [{"number": 120, "title": "Lab catalog review", "state": "OPEN",
                                   "url": "https://example/issues/120"}]

        def run(args):
            calls.append(args)
            return ""
        R.issue_sync(self.cat, "example/repo", "", issues, today=TODAY, run=run)
        self.assertEqual(calls[0][:3], ["issue", "edit", "120"])
        self.assertIn("pending-review", calls[0])
        closes = [c for c in calls if c[:2] == ["issue", "close"]]
        self.assertEqual(len(closes), 6)
        self.assertIn("https://example/issues/120", closes[0][-1])

    def test_the_body(self):
        body = R.issue_body(self.cat, "weekly report text", TODAY)
        self.assertTrue(body.startswith(R.ISSUE_MARK))
        self.assertIn("**11 to review:**", body)
        self.assertIn("### Adopt", body)
        self.assertIn("weekly report text", body)
        self.assertIn("Accepted, waiting to be added (1)", body)

    def test_the_cli_dry_run(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = R.main(["issue-sync", "--catalog", self.path, "--repo", "example/repo", "--issues", ISSUES,
                           "--dry-run", "--today", TODAY])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(err.getvalue())["plan"]["close"], [1, 3, 5, 7, 82, 96])


SURVEY = '''
format = 1
surveyed = "2026-11-10"

[[model]]
id = "img-b"
name = "Image B again"
capability = "image"
licence = "apache-2"
tier = "clean"

[[model]]
id = "parts-3d"
name = "Parts 3D"
hf_id = "org/Parts-3D"
capability = "mesh-parts"
licence = "apache-2"
licence_name = "Apache-2.0"
tier = "clean"
tier_reason = "Apache-2.0, on DINOv2"
built_on = [{ name = "DINOv2", licence = "apache-2", licence_url = "https://example/dinov2" }]
comfyui = "yes (native)"
memory_gb = 9
quality_notes = "makes separate parts"
cite = ["https://example/parts"]

[[model]]
id = "nc-thing"
name = "NC Thing"
hf_id = "org/NC-Thing"
capability = "timeseries"
licence = "timesfm-nc"
licence_name = "TimesFM Non-Commercial License"
tier = "no"
tier_reason = "non-commercial since 2026"
comfyui = "n/a"

[[model]]
id = "needs-node"
name = "Needs Node"
hf_id = "org/Needs-Node"
capability = "texture"
licence = "mit"
tier = "conditional"
tier_reason = "MIT, but its painter is on an OpenRAIL model"
comfyui = "community"
'''


@unittest.skipUnless(HAVE_TOMLKIT, "needs python-tomlkit")
class SurveyImportTest(Fixture, unittest.TestCase):
    def test_import_and_recommend(self):
        sv = os.path.join(self.tmp, "candidates.toml")
        with open(sv, "w") as f:
            f.write(SURVEY)
        r = R.import_survey(self.path, sv, TODAY)
        self.assertEqual(r["added"], ["survey:parts-3d", "survey:nc-thing", "survey:needs-node"])
        self.assertEqual(r["skipped"], {"in the catalog": ["img-b"]})
        self.assertEqual(R.import_survey(self.path, sv, TODAY)["added"], [])          # twice changes nothing
        cat = C.load(self.path)
        self.assertEqual(C.validate(cat), [])
        rows = {e["id"]: e for e in R.queue(cat, TODAY)}
        p = rows["survey:parts-3d"]
        self.assertEqual((p["capability"], p["action"]), ("mesh", "adopt"))
        self.assertTrue(next(x for x in cat.pending if x["id"] == "survey:parts-3d")["parts"])
        self.assertIn("about 9 GB", p["reason"])
        self.assertEqual(rows["survey:nc-thing"]["action"], "ignore")                  # the survey's "no"
        self.assertIn("non-commercial since 2026", rows["survey:nc-thing"]["reason"])
        n = rows["survey:needs-node"]
        self.assertEqual(n["action"], "watch")
        self.assertEqual(n["signals"]["licence_tier"], "conditional")                  # worse than MIT alone
        self.assertIn("needs a way to run it", n["reason"])


class PublicTest(unittest.TestCase):
    def test_a_survey_loses_local_paths(self):
        self.assertEqual(R._public("made in ~/Pictures/x/y (scripts) and /mnt/Dev/build/z, kept"),
                         "made in a local folder (scripts) and a local folder, kept")


class RealQueueTest(unittest.TestCase):
    def test_every_pending_entry_gets_a_recommendation(self):
        cat = C.load(REAL)
        rows = R.queue(cat, TODAY)
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["action"], R.ACTIONS)
            self.assertTrue(r["reason"])


if __name__ == "__main__":
    unittest.main()
