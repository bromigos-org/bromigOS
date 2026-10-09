"""The lab model catalog's logic (catalog.py, catalog_serving.py, catalog_upgrade.py) against a
small made-up catalog (fixtures/lab-catalog.toml), and the real catalog's data
(share/lab/models.toml) for consistency.

    PYTHONPATH=lib python -m unittest tests.test_lab_catalog
"""
import contextlib
import datetime
import io
import itertools
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("BROMIGOS_HOMELAB_CONFIG", "/nonexistent")
os.environ.setdefault("BROMIGOS_LAB_BENCH_LEDGER", "/nonexistent")
os.environ.setdefault("BROMIGOS_LAB_SETTINGS", "/nonexistent")

from bromigos_homelab import catalog as C                    # noqa: E402
from bromigos_homelab import catalog_serving as S            # noqa: E402
from bromigos_homelab import catalog_upgrade as U            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "lab-catalog.toml")
REAL = os.path.normpath(os.path.join(HERE, "..", "share", "lab", "models.toml"))


def cat():
    return C.load(FIXTURE)


def best(cap, vram=None, **kw):
    d = C.pick(cap, vram, cat=cat(), **kw)
    return d["best"]["key"] if d["best"] else None


class PickTest(unittest.TestCase):
    def test_fixture_is_consistent(self):
        self.assertEqual(C.validate(cat()), [])

    def test_the_best_that_fits_grows_with_vram(self):
        self.assertEqual(best("image", 8), "img-b/q4")
        self.assertEqual(best("image", 16), "img-b/fp8")
        self.assertEqual(best("image", 24), "img-a2/int8")
        self.assertIsNone(best("image", None))              # no CPU image model in the fixture

    def test_the_reason_names_what_more_vram_would_buy(self):
        d = C.pick("image", 12, cat=cat())
        self.assertIn("Image A", d["reason"])
        self.assertTrue(d["bigger"])
        self.assertTrue(d["alternatives"] or d["best"])

    def test_licence_filter_is_a_setting(self):
        self.assertEqual(best("image", 24, licence="commercial"), "img-b/fp8")
        self.assertEqual(best("3d", 24, licence="permissive"), "mesh-mit/fp16")
        self.assertEqual(best("3d", 24), "mesh/fp16")
        self.assertEqual(best("3d", 24, region="EU"), "mesh-mit/fp16")   # not licensed in the EU

    def test_needs_support_is_never_recommended_unless_asked(self):
        self.assertNotEqual(best("image", 24), "img-fancy/bf16")
        d = C.pick("image", 24, cat=cat())
        self.assertTrue(any("img-fancy" in x for x in d["skipped"].get("needs support", [])))
        self.assertEqual(best("image", 24, unsupported=True), "img-fancy/bf16")

    def test_goal_trades_quality_for_speed(self):
        self.assertEqual(best("video", 24, goal="quality"), "vid-14b/fp8")
        self.assertEqual(best("video", 24, goal="speed"), "vid-5b/fp16")

    def test_offloading_fits_a_bigger_model_on_a_small_card(self):
        d = C.pick("video", 12, cat=cat())
        self.assertEqual(d["best"]["key"], "vid-14b/q4-offload")
        self.assertTrue(d["best"]["offload"])
        self.assertIn("system RAM", d["reason"])
        # without the RAM for it, the offload variant is out
        self.assertNotEqual(C.pick("video", 12, cat=cat(), ram_gib=16)["best"]["key"], "vid-14b/q4-offload")

    def test_vendor_and_architecture(self):
        self.assertEqual(best("llm", 32, gpu="RTX 5090"), "moe-30b-v2/nvfp4")      # Blackwell: NVFP4
        self.assertEqual(best("llm", 24, gpu="RTX 4090"), "moe-30b/q4")            # Ada: no NVFP4
        self.assertEqual(best("llm", 24, vendor="amd"), "moe-30b/q4")              # llama.cpp runs on AMD
        k = best("llm", 64, vendor="apple")
        self.assertIn(C.load(FIXTURE).variant(k).runtime, ("llama.cpp", "mlx"))

    def test_cpu_only(self):
        self.assertEqual(best("llm", None), "small-8b/cpu")
        self.assertEqual(best("tts", None), "tts-small/cpu")
        d = C.pick("llm", None, cat=cat())
        self.assertEqual(d["best"]["vram_gib"], 0.0)
        self.assertGreater(d["best"]["ram_gib"], 0)

    def test_aliases(self):
        self.assertEqual(C.canon("image.generate"), "image")
        self.assertEqual(C.canon("video.loop"), "video")
        self.assertEqual(C.canon("voice.tts"), "tts")
        with self.assertRaises(C.CatalogError):
            C.canon("teleport")


class HardwareTest(unittest.TestCase):
    def test_parse(self):
        c = cat()
        self.assertEqual(len(C.Hardware.parse(["RTX 5090"], cat=c).gpus()), 1)
        hw = C.Hardware.parse(["2x RTX 4090"], cat=c)
        self.assertEqual([d.name for d in hw.gpus()], ["RTX 4090", "RTX 4090"])
        self.assertEqual(len({d.group for d in hw.gpus()}), 1)
        hw = C.Hardware.parse(["GB10x2"], cat=c)
        self.assertTrue(all(d.unified for d in hw.gpus()))
        self.assertAlmostEqual(hw.gpus()[0].vram_gib, 119.0 * 0.8, places=1)
        hw = C.Hardware.parse(["RTX 5090", "RTX 5070,desktop"], cat=c)
        self.assertEqual([d.desktop for d in hw.gpus()], [False, True])
        self.assertEqual(len({d.group for d in hw.gpus()}), 2)   # two machines: never split across

    def test_settings_keys_carry_no_hostname(self):
        hw = C.Hardware.parse(["RTX 5090,host=gpu-node-7", "RTX 5090,host=gpu-node-8"], cat=cat())
        self.assertEqual([d.key for d in hw.gpus()], ["RTX 5090", "RTX 5090#2"])

    def test_detect_links_a_server_split_across_hosts(self):
        inv = {"gpus": [
            {"name": "GB10", "model": "NVIDIA-GB10-SHARED", "host": "a", "vram_total": None, "holds": ["vllm/llm-head"]},
            {"name": "GB10", "model": "NVIDIA-GB10-SHARED", "host": "b", "vram_total": None, "holds": ["vllm/llm-worker"]},
            {"name": "GB10", "model": "NVIDIA-GB10-SHARED", "host": "c", "vram_total": None, "holds": ["vllm/other"]},
            {"name": "RTX 5090", "model": "NVIDIA GeForce RTX 5090", "host": "d", "vram_total": 32607 * 1024 ** 2,
             "holds": ["comfyui/comfyui"]}]}
        hw = C.detect(cat(), inv, local=False)
        g = [d for d in hw.gpus()]
        self.assertEqual(g[0].group, g[1].group)
        self.assertNotEqual(g[0].group, g[2].group)
        self.assertTrue(g[0].unified)
        self.assertAlmostEqual(g[3].vram_gib, 31.8, places=1)
        # the linked pair can carry a model neither holds alone... and tensor-parallel it
        opts = C.options(cat(), "llm", hw)
        self.assertTrue(any(set(o.devices) == {g[0].id, g[1].id} for o in opts))
        self.assertFalse(any(set(o.devices) == {g[0].id, g[2].id} for o in opts))


def configs(hw, **kw):
    return C.plan(hw, cat=cat(), **kw)["configurations"]


class PlanTest(unittest.TestCase):
    def assert_within_budgets(self, doc):
        for c in doc["configurations"]:
            for d in c["devices"]:
                self.assertLessEqual(d["peak_gib"], d["budget_gib"] + 1e-6, (c["name"], d))
                # the always-on models fit together with headroom
                self.assertLessEqual(d["resident_gib"], d["budget_gib"], (c["name"], d))

    def test_two_to_four_ranked_configurations(self):
        hw = C.Hardware.parse(["RTX 5090", "RTX 5070,desktop"], ram_gib=64, cat=cat())
        doc = C.plan(hw, cat=cat(), budgets={"RTX 5070": 6})
        cs = doc["configurations"]
        self.assertTrue(2 <= len(cs) <= 4)
        self.assertEqual(cs[0]["id"], "balanced")
        for c in cs:
            self.assertTrue(c["sacrifice"])
            for p in c["placements"]:
                self.assertTrue(p["why"])
        self.assert_within_budgets(doc)

    def test_the_priority_comes_first(self):
        hw = C.Hardware.parse(["RTX 5090"], cat=cat())
        self.assertEqual(configs(hw, priority="brain")[0]["id"], "brain")
        cs = configs(hw, priority="media")
        self.assertEqual(cs[0]["id"], "media")

    def test_brain_first_gets_the_bigger_llm(self):
        hw = C.Hardware.parse(["RTX 5090", "RTX 5070,desktop"], ram_gib=64, cat=cat())
        cs = {c["id"]: c for c in configs(hw, budgets={"RTX 5070": 6})}
        llm = {k: next(p for p in c["placements"] if p["capability"] == "llm") for k, c in cs.items()}
        self.assertGreaterEqual(llm["brain"]["quality"], max(p["quality"] for p in llm.values()))

    def test_the_llm_goes_on_the_bigger_card(self):
        hw = C.Hardware.parse(["RTX 5070", "RTX 5090"], ram_gib=64, cat=cat())
        c = configs(hw, wants=["llm", "tts", "stt"], priority="brain")[0]
        llm = next(p for p in c["placements"] if p["capability"] == "llm")
        self.assertEqual(llm["device_names"], ["RTX 5090"])

    def test_a_desktop_budget_is_never_exceeded(self):
        for b5090, b5070 in itertools.product((4, 10, 18, 31), (0, 2, 6, 11)):
            hw = C.Hardware.parse(["RTX 5090", "RTX 5070,desktop"], ram_gib=64, cat=cat())
            doc = C.plan(hw, cat=cat(), budgets={"gpu0": b5090, "gpu1": b5070})
            self.assert_within_budgets(doc)

    def test_a_tight_budget_leaves_capabilities_out_and_says_why(self):
        hw = C.Hardware.parse(["RTX 5070"], ram_gib=16, cat=cat())
        doc = C.plan(hw, cat=cat(), budgets={"gpu0": 4})
        self.assert_within_budgets(doc)
        c = doc["configurations"][0]
        self.assertTrue(c["missing"])
        for m in c["missing"]:
            self.assertTrue(m["why"])

    def test_everything_resident_has_no_swaps(self):
        hw = C.Hardware.parse(["RTX 5090"], ram_gib=64, cat=cat())
        c = next(c for c in configs(hw, priority="resident"))
        self.assertTrue(all(p["resident"] for p in c["placements"]))
        self.assertTrue(all(not d["swaps"] for d in c["devices"]))

    def test_shared_models_count_once(self):
        hw = C.Hardware.parse(["RTX 5090"], ram_gib=64, cat=cat())
        c = configs(hw, wants=["image", "image-edit"], priority="media")[0]
        edit = next(p for p in c["placements"] if p["capability"] == "image-edit")
        self.assertEqual(edit["shared_with"], "image")
        self.assertEqual(edit["vram_gib"], 0.0)

    def test_multi_gpu_tensor_parallel(self):
        hw = C.Hardware.parse(["2x RTX 4090"], ram_gib=128, cat=cat())
        c = configs(hw, wants=["llm"], priority="brain", goals={"*": "quality"})[0]
        llm = c["placements"][0]
        self.assertEqual(llm["key"], "dense-70b/awq")
        self.assertEqual(len(llm["devices"]), 2)
        self.assertLess(llm["per_gpu_gib"], 24)

    def test_tensor_parallel_wants_matching_cards(self):
        hw = C.Hardware.parse(["RTX 4090,host=x", "RTX 3060,host=x"], ram_gib=128, cat=cat())
        opts = C.options(cat(), "llm", hw)
        self.assertFalse(any(len(o.devices) > 1 and o.variant.runtime == "vllm" for o in opts))
        # llama.cpp splits layers across unlike cards
        self.assertTrue(any(len(o.devices) > 1 and o.variant.runtime == "llama.cpp" for o in opts))

    def test_goals_per_capability(self):
        hw = C.Hardware.parse(["RTX 5090"], ram_gib=64, cat=cat())
        q = configs(hw, wants=["video"], goals={"*": "quality"}, priority="media")[0]
        s = configs(hw, wants=["video"], goals={"*": "quality", "video": "speed"}, priority="media")[0]
        self.assertEqual(q["placements"][0]["key"], "vid-14b/fp8")
        self.assertEqual(s["placements"][0]["key"], "vid-5b/fp16")


class RegionTest(unittest.TestCase):
    def test_the_time_zone_sets_the_licence_region(self):
        cases = {"America/Los_Angeles": "US", "America/Indiana/Indianapolis": "US", "Europe/Berlin": "EU",
                 "Europe/London": "UK", "Asia/Seoul": "KR", "America/Toronto": None, "Asia/Tokyo": None}
        for tz, want in cases.items():
            with mock.patch.dict(os.environ, {"TZ": tz}):
                self.assertEqual(C.default_region(), want, tz)
        with mock.patch.dict(os.environ, {"TZ": "UTC", "LANG": "de_DE.UTF-8", "LC_ALL": ""}):
            self.assertEqual(C.default_region(), "EU")


class ServingTest(unittest.TestCase):
    def setUp(self):
        self.c = cat()
        self.hw = C.Hardware.parse(["RTX 5090"], ram_gib=64, cat=self.c)
        self.gpu = self.hw.gpus()[0]

    def test_kv_cache_grows_with_clients_and_context(self):
        v = self.c.variant("moe-30b-v2/nvfp4")
        one = S.serve(v.model, v, [self.gpu], S.Load(clients=1, context=32768))
        many = S.serve(v.model, v, [self.gpu], S.Load(clients=16, context=32768, prompt=8000))
        self.assertGreater(many["kv_gib"], one["kv_gib"])
        self.assertGreater(many["vram_gib"], one["vram_gib"])
        self.assertGreater(many["aggregate"], one["aggregate"])
        self.assertLess(many["per_stream"], one["per_stream"])
        a = S.max_clients(v.model, v, [self.gpu], 31, S.Load(context=8192))
        b = S.max_clients(v.model, v, [self.gpu], 31, S.Load(context=131072, prompt=60000))
        self.assertGreater(a, b)

    def test_batching_runtimes_scale_and_slots_dont(self):
        vl = self.c.variant("moe-30b-v2/nvfp4")
        lc = self.c.variant("moe-30b/q4")
        ld = S.Load(clients=16, context=16384)
        ref = C._ref(self.c, "RTX 5090")
        sv, sl = S.serve(vl.model, vl, [self.gpu], ld, ref), S.serve(lc.model, lc, [self.gpu], ld, ref)
        self.assertGreater(sv["aggregate"], 2 * sl["aggregate"])
        self.assertEqual(sv["waiting"], 0)
        self.assertGreater(sl["waiting"], 0)

    def test_moe_serves_more_agents_than_dense(self):
        hw2 = C.Hardware.parse(["2x RTX 4090"], ram_gib=128, cat=self.c)
        dense = self.c.variant("dense-70b/awq")
        moe = self.c.variant("moe-30b/fp8")
        ld = S.Load(clients=16)
        d = S.serve(dense.model, dense, hw2.gpus(), ld)
        m = S.serve(moe.model, moe, hw2.gpus(), ld)
        self.assertGreater(m["aggregate"], d["aggregate"])

    def test_published_benchmarks_anchor_the_estimate(self):
        import dataclasses
        v = self.c.variant("moe-30b-v2/nvfp4")
        bench = [{"hardware": "RTX 5090", "runtime": "vLLM", "quant": "NVFP4", "concurrency": 1,
                  "aggregate_tok_s": 100, "url": "https://example.org/c1"},
                 {"hardware": "RTX 5090", "runtime": "vLLM", "quant": "NVFP4", "concurrency": 8,
                  "aggregate_tok_s": 500, "url": "https://example.org/c8"},
                 {"hardware": "RTX 5090", "runtime": "vLLM", "quant": "FP8", "concurrency": 8,
                  "aggregate_tok_s": 9999, "url": "https://example.org/other-quant"},
                 {"hardware": "2x RTX 5090", "runtime": "vLLM", "quant": "NVFP4", "concurrency": 8,
                  "aggregate_tok_s": 9999, "url": "https://example.org/two-cards"}]
        m = dataclasses.replace(v.model, serving=bench)
        one = S.serve(m, v, [self.gpu], S.Load(clients=1))
        self.assertEqual(one["aggregate"], 100)
        mid = S.serve(m, v, [self.gpu], S.Load(clients=4))
        self.assertTrue(100 < mid["aggregate"] < 500, mid)               # between the two, never another quant's
        self.assertIn("published", mid["note"])
        more = S.serve(m, v, [self.gpu], S.Load(clients=32))
        self.assertGreater(more["aggregate"], 500)                       # the estimate's shape past the last point
        capped = S.serve(m, v, [self.gpu], S.Load(clients=32, max_seqs=8))
        self.assertEqual(capped["aggregate"], 500)                       # the server's cap: the rest wait
        self.assertEqual(capped["waiting"], 24)
        self.assertGreater(capped["ttft_s"], more["ttft_s"])

    def test_throughput_goal_prefers_a_batching_server(self):
        doc = C.pick("llm", 32, gpu="RTX 5090", cat=self.c, goal="throughput", serving=S.Load(clients=16))
        self.assertIn(doc["best"]["runtime"], ("vllm", "sglang"))
        self.assertEqual(doc["best"]["serving"]["clients"], 16)

    def test_load_parse(self):
        ld = S.Load.parse(16, "32k", "4k", 500)
        self.assertEqual((ld.clients, ld.context, ld.prompt, ld.output), (16, 32768, 4096, 500))


class UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.c = cat()
        self.hw = C.Hardware.parse(["RTX 5090,host=lab"], ram_gib=64, cat=self.c)
        self.hw.gpus()[0].holds = ("comfyui/comfyui", "voice/voice")
        self.have = [
            {"key": "img-a/int8", "name": "Image A", "quant": "INT8", "where": "comfyui", "caps": ["image", "image-edit"]},
            {"key": "vid-5b/fp16", "name": "Video 5B", "quant": "FP16", "where": "comfyui", "caps": ["video"]},
            {"key": "tts-small/bf16", "name": "TTS 0.6B", "quant": "BF16", "where": "voice", "caps": ["tts"]}]

    def ev(self, policy, **kw):
        return U.evaluate(self.c, self.hw, self.have, policy, **kw)

    def test_everything_off_by_default(self):
        self.assertEqual(self.ev({})["proposals"], [])
        s = U.settings({})
        self.assertFalse(s["enabled"])
        self.assertEqual(s["action"], "notify")

    def test_safe_takes_a_newer_version_of_the_same_family_only(self):
        ev = self.ev({"enabled": True, "policy": {"image": "safe", "video": "safe", "tts": "safe"}}, goal="quality")
        by = {p["capability"]: p for p in ev["proposals"]}
        self.assertEqual(by["image"]["to_key"], "img-a2/int8")
        self.assertEqual(by["image"]["kind"], "newer version")
        self.assertNotIn("video", by)          # vid-14b is the same family but not newer: not safe
        self.assertEqual(by["tts"]["kind"], "newer version")   # tts-big: same family, released later
        self.assertTrue(by["tts"]["voice"])
        self.assertIn("VECTOR is quiet", by["tts"]["reason"])

    def test_any_takes_any_better_pick(self):
        ev = self.ev({"enabled": True, "policy": {"video": "any"}}, goal="quality")
        (p,) = ev["proposals"]
        self.assertEqual(p["to_key"], "vid-14b/fp8")
        self.assertEqual(p["kind"], "better model")

    def test_budget_limits_upgrades(self):
        self.hw.apply_budgets({"RTX 5090": 15})
        ev = self.ev({"enabled": True, "policy": {"image": "any", "video": "any"}}, goal="quality")
        for p in ev["proposals"]:
            self.assertLessEqual(p["vram_gib"], 15)
        self.assertFalse(any(p["to_key"].startswith("img-a2") for p in ev["proposals"]))

    def test_licence_filter_limits_upgrades(self):
        ev = self.ev({"enabled": True, "policy": {"image": "any"}}, licence="commercial", goal="quality")
        self.assertFalse(any(p["to_key"].startswith("img-a") for p in ev["proposals"]))

    def test_notify_until_apply_and_quiet_hours(self):
        ev = self.ev({"enabled": True, "policy": {"image": "safe"}})
        self.assertEqual(ev["proposals"][0]["action"], "notify")
        ev = self.ev({"enabled": True, "action": "apply", "quiet_hours": "01:00-06:00", "policy": {"image": "safe"}},
                     now=datetime.datetime(2026, 10, 9, 14, 0))
        self.assertIn("quiet hours", ev["proposals"][0]["action"])
        self.assertTrue(U.in_quiet_hours("23:00-06:00", datetime.datetime(2026, 10, 9, 2, 0)))
        self.assertFalse(U.in_quiet_hours("23:00-06:00", datetime.datetime(2026, 10, 9, 12, 0)))
        ev = self.ev({"enabled": False, "policy": {"image": "safe"}})
        self.assertIn("switched off", ev["proposals"][0]["action"])

    def test_family_matching(self):
        c = self.c
        self.assertEqual(U.kind_of(c.variant("img-a/int8"), c.variant("img-a2/int8")), "newer version")
        self.assertIsNone(U.kind_of(c.variant("img-a/int8"), c.variant("img-b/fp8")))
        self.assertEqual(U.kind_of(c.variant("moe-30b/q4"), c.variant("moe-30b/fp8")), "better quantisation")
        self.assertIsNone(U.kind_of(c.variant("vid-5b/fp16"), c.variant("vid-14b/fp8")))  # same family, not newer

    def test_bad_policy_is_refused(self):
        with self.assertRaises(C.CatalogError):
            U.settings({"policy": {"image": "always"}})

    def test_nudge_tells_once(self):
        told = []
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "nudged.json")
            ev = U.evaluate(self.c, self.hw, self.have, {}, nudge=True, goal="quality")
            self.assertTrue(ev["proposals"])
            body = U.nudge(self.c, ev, f, lambda *a: told.append(a))
            self.assertIn("A better", body)
            self.assertIsNone(U.nudge(self.c, ev, f, lambda *a: told.append(a)))
        self.assertEqual(len(told), 1)


class CommandTest(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = C.main(list(argv) + ["--catalog", FIXTURE])
        return code, out.getvalue()

    def test_plan_json(self):
        code, out = self.run_main("plan", "--hw", "RTX 5090", "--hw", "RTX 5070,desktop", "--budget", "gpu1=6G",
                                  "--goal", "balanced,video=quality", "--clients", "4", "--context", "32k", "--json")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["load"]["clients"], 4)
        self.assertEqual(doc["goals"]["video"], "quality")

    def test_pick_text(self):
        code, out = self.run_main("pick", "image", "12")
        self.assertEqual(code, 0)
        self.assertIn("Image B", out)

    def test_check(self):
        code, out = self.run_main("check")
        self.assertEqual(code, 0, out)


class SharedAndBenchTest(unittest.TestCase):
    def test_a_shared_model_counts_with_its_quality_for_that_capability(self):
        hw = C.Hardware.parse(["RTX 5090"], ram_gib=64, cat=cat())
        doc = C.plan(hw, cat=cat(), wants=["llm", "vision"], always=["llm", "vision"], priority="brain")
        vis = next(p for p in doc["configurations"][0]["placements"] if p["capability"] == "vision")
        if vis.get("shared_with"):
            self.assertLess(vis["quality"], 80)              # the fixture's moe-30b sees at 75-78, not its llm 82+

    def test_bench_measurements_replace_published_figures(self):
        with tempfile.TemporaryDirectory() as d:
            led = os.path.join(d, "bench.jsonl")
            with open(led, "w") as f:
                f.write(json.dumps({"key": "img-b/fp8", "gpu": "RTX 5090", "ok": True, "seconds": 4.0,
                                    "peak_vram_gib": 10.5, "t": "2026-10-09T03:00:00"}) + "\n")
            old = os.environ.get("BROMIGOS_LAB_BENCH_LEDGER")
            os.environ["BROMIGOS_LAB_BENCH_LEDGER"] = led
            try:
                hw = C.Hardware.parse(["RTX 5090"], cat=cat())
                o = next(o for o in C.options(cat(), "image", hw) if o.key == "img-b/fp8")
                self.assertEqual(o.speed, 4.0)
                self.assertEqual(o.per_gpu, 10.5)
                self.assertIn("measured on your lab", o.notes[0])
            finally:
                os.environ["BROMIGOS_LAB_BENCH_LEDGER"] = old or "/nonexistent"

    def test_bench_is_off_by_default(self):
        from bromigos_homelab import catalog_bench
        ok, why = catalog_bench.enabled()
        self.assertFalse(ok)
        self.assertIn("Settings", why)


class SettingsFileTest(unittest.TestCase):
    def test_save_writes_through_a_link_and_keeps_other_tables(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.join(d, "dotfiles-lab.toml")
            with open(real, "w") as f:
                f.write("# mine\n[upgrade]\nenabled = true\n")
            link = os.path.join(d, "lab.toml")
            os.symlink(real, link)
            old = os.environ.get("BROMIGOS_LAB_SETTINGS")
            os.environ["BROMIGOS_LAB_SETTINGS"] = link
            try:
                C.save_settings("plan", {"budgets": {"RTX 5070": 6.0}, "always": ["llm", "tts"], "clients": 4})
                self.assertTrue(os.path.islink(link))
                s = C.read_settings()
                self.assertEqual(s["plan"]["budgets"], {"RTX 5070": 6.0})
                self.assertTrue(s["upgrade"]["enabled"])
                with open(real) as f:
                    self.assertIn("# mine", f.read())
                with self.assertRaises(C.CatalogError):
                    C.save_settings("secrets", {})
            finally:
                os.environ["BROMIGOS_LAB_SETTINGS"] = old or "/nonexistent"


@unittest.skipUnless(os.path.isfile(REAL), "no share/lab/models.toml yet")
class RealCatalogTest(unittest.TestCase):
    """The researched catalog (2026-10-09): the computed picks agree with the research's tier
    tables where it matters, so a data edit that breaks them shows up here."""

    @classmethod
    def setUpClass(cls):
        cls.c = C.load(REAL)

    def best(self, cap, vram, **kw):
        d = C.pick(cap, vram, cat=self.c, **kw)
        return d["best"]["model"] if d["best"] else None

    def test_consistent(self):
        self.assertEqual(C.validate(self.c), [])

    def test_every_capability_has_a_pick_at_24_gb(self):
        for cap in C.CAPABILITIES:
            self.assertIsNotNone(C.pick(cap, 24, cat=self.c)["best"], cap)

    def test_research_tiers_for_best_quality(self):
        q = dict(goal="quality", region="US")
        self.assertEqual(self.best("llm", 8, **q), "qwen3.6-35b-a3b")         # experts in system RAM
        self.assertEqual(self.best("llm", 24, **q), "qwen3.8-27b")
        self.assertEqual(self.best("image", 24, **q), "qwen-image-2-1")
        self.assertIn(self.best("image", 24, goal="quality", licence="commercial"),
                      ("qwen-image-2512", "ming-image-0-1-design"))   # the research's two commercial-safe picks
        self.assertEqual(self.best("video", 24, **q), "wan2.2-i2v-a14b")       # loops from a still
        self.assertEqual(self.best("3d", 32, **q), "pixal3d")
        self.assertEqual(self.best("cutout", 12, **q), "lucida")
        self.assertEqual(self.best("upscale", 32, **q), "seedvr2-7b")
        self.assertEqual(self.best("tts", 12, **q), "qwen3-tts")
        self.assertEqual(self.best("ocr", 16, **q), "paddleocr-vl-1.6")

    def test_region_and_needs_support(self):
        # MiniMax H3 isn't licensed in the US; Breeze TTS 2 isn't something the voice service runs
        self.assertNotEqual(self.best("video", 32, goal="quality", region="US"), "minimax-h3-fl2va")
        self.assertNotEqual(self.best("tts", 32, goal="quality"), "breeze-tts-2")

    def test_the_operators_kind_of_lab(self):
        inv = {"gpus": [
            {"name": "GB10", "model": "NVIDIA-GB10-SHARED", "host": "a", "vram_total": None, "holds": ["vllm/x-head"]},
            {"name": "GB10", "model": "NVIDIA-GB10-SHARED", "host": "b", "vram_total": None, "holds": ["vllm/x-worker"]},
            {"name": "RTX 5090", "model": "NVIDIA GeForce RTX 5090", "host": "c", "vram_total": 32607 * 1024 ** 2,
             "holds": ["comfyui/comfyui", "voice/voice"]}]}
        hw = C.detect(self.c, inv, local=False)
        doc = C.plan(hw, cat=self.c, region="US", goals={"*": "quality"})
        c0 = doc["configurations"][0]
        llm = next(p for p in c0["placements"] if p["capability"] == "llm")
        self.assertEqual(len(llm["devices"]), 2)              # split across the linked pair
        for d in c0["devices"]:
            self.assertLessEqual(d["peak_gib"], d["budget_gib"] + 1e-6)
        voice = [p for p in c0["placements"] if p["capability"] in ("tts", "stt")]
        self.assertTrue(all(p["device_names"] == ["RTX 5090"] for p in voice))


if __name__ == "__main__":
    unittest.main()
