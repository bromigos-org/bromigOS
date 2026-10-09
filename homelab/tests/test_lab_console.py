"""The lab console's status cards and models, against recorded answers (labfake.py).

    PYTHONPATH=lib:../lib python -m unittest discover -s tests
"""
import unittest

import labfake
from bromigos_homelab import console, labmodels, registry
from bromigos_homelab.registry import Adapter, register


def card(doc, cid):
    return next((c for c in doc["cards"] if c["id"] == cid), None)


class StatusTest(unittest.TestCase):
    def test_cards_from_what_the_lab_has(self):
        with labfake.Lab():
            doc = console.status()
        ids = [c["id"] for c in doc["cards"]]
        for want in ("nodes", "gpus", "services", "deployments", "workloads", "storage", "alerts", "jobs", "secrets"):
            self.assertIn(want, ids)
        self.assertEqual(ids, [c["id"] for c in sorted(doc["cards"], key=lambda c: (c["order"], c["title"]))])
        for c in doc["cards"]:
            self.assertIn(c["state"], console.CARD_STATES)
            self.assertTrue(c["hint"], f"{c['id']} has no hover hint")
            for it in c["items"]:
                self.assertIn(it["state"], console.ITEM_STATES)

    def test_nodes_merged_and_generic(self):
        with labfake.Lab():
            c = card(console.status(), "nodes")
        names = [i["name"] for i in c["items"]]
        self.assertEqual(len(names), len(set(names)), "one row per host, whichever sources know it")
        self.assertIn("gpu-node", names)
        gpu = next(i for i in c["items"] if i["name"] == "gpu-node")
        self.assertIsNotNone(gpu["cpu_pct"])
        self.assertIn("root disk", gpu["hint"])

    def test_gpus_from_dcgm_and_comfyui(self):
        with labfake.Lab():
            c = card(console.status(), "gpus")
        g = next(i for i in c["items"] if "5090" in i["name"])
        self.assertTrue(g["vram"].endswith("GiB"))
        self.assertIn("comfyui", g["holds"])
        self.assertGreater(g["vram_total"], 30 * 2**30)
        sparks = [i for i in c["items"] if "GB10" in i["name"]]
        self.assertEqual(len(sparks), 3)
        self.assertEqual(sparks[0]["vram"], "unified memory")

    def test_services_and_an_unreachable_one(self):
        with labfake.Lab() as lab:
            c = card(console.status(), "services")
        by = {i["name"]: i for i in c["items"]}
        self.assertEqual(by["comfyui"]["kind"], "ComfyUI")
        self.assertEqual(by["voice"]["state"], "ok")
        self.assertIn("TTS on", by["voice"]["detail"])
        self.assertEqual(by["ollama"]["state"], "crit")            # down: a red row, never a crash
        self.assertIn("unreachable", by["ollama"]["detail"])
        self.assertIn("ollama", lab.down)

    def test_whole_source_down_is_unreachable_not_a_crash(self):
        with labfake.Lab() as lab:
            lab.down |= {"prometheus", "k3s", "comfyui", "voice", "litellm", "vault"}
            doc = console.status()
        self.assertTrue(doc["cards"])
        al = card(doc, "alerts")
        self.assertEqual(al["state"], "unreachable")
        self.assertIn("prometheus", al["errors"])

    def test_argo_problems_first(self):
        with labfake.Lab():
            c = card(console.status(), "deployments")
        states = [i["state"] for i in c["items"]]
        self.assertEqual(states, sorted(states, key=lambda s: {"crit": 0, "warn": 1, "unknown": 2, "ok": 3}[s]))
        self.assertIn("synced and healthy", c["summary"])

    def test_hide(self):
        with labfake.Lab('[console]\nhide = ["voice*", "homelab-*"]\n'):
            doc = console.status()
        dep = [i["name"] for i in card(doc, "deployments")["items"]]
        self.assertFalse([n for n in dep if n.startswith("homelab-")])
        self.assertNotIn("voice", dep)

    def test_only(self):
        with labfake.Lab():
            doc = console.status(only={"gpus"})
        self.assertEqual([c["id"] for c in doc["cards"]], ["gpus"])

    def test_nothing_configured(self):
        with labfake.Lab() as lab:
            import os
            with open(os.environ["BROMIGOS_HOMELAB_CONFIG"], "w") as f:
                f.write("")
            from bromigos_homelab import config
            config._cache.update(sig=None)
            doc = console.status()
            self.assertIsNotNone(lab)
        self.assertFalse(doc["configured"])
        self.assertEqual(doc["cards"], [])


class GenericCardTest(unittest.TestCase):
    def test_item_state(self):
        s = console.item_state
        self.assertEqual(s({"state": "failed"}), "crit")
        self.assertEqual(s({"up": False}), "crit")
        self.assertEqual(s({"sync": "out_of_sync", "health": "healthy"}), "warn")
        self.assertEqual(s({"health": "degraded", "sync": "synced"}), "crit")
        self.assertEqual(s({"state": "ok"}), "ok")
        self.assertEqual(s({"name": "x"}), "unknown")

    def test_a_new_capability_gets_a_card_and_an_adapter_its_own_cards(self):
        caps_before = registry.CAPABILITIES
        registry.CAPABILITIES = caps_before + ("kettles",)

        @register
        class Kettles(Adapter):
            type = "kettle-test"
            provides = ("kettles",)
            local = True

            def kettles(self):
                return [{"name": "office", "state": "crit", "temp_c": 99}, {"name": "lab", "up": True}]

            def cards(self):
                return [{"title": "Tea", "items": [{"name": "earl grey", "state": "ok"}], "summary": "brewing"}]

        try:
            with labfake.Lab('[[source]]\nname = "kettles"\ntype = "kettle-test"\n'):
                doc = console.status()
        finally:
            registry.CAPABILITIES = caps_before
            registry.ADAPTERS.pop("kettle-test", None)
            console.SPECS.pop("kettles", None)
        k = card(doc, "kettles")
        self.assertIsNotNone(k, "a capability nobody shaped still gets a card")
        self.assertEqual(k["state"], "crit")
        self.assertEqual({i["name"]: i["state"] for i in k["items"]}, {"office": "crit", "lab": "ok"})
        tea = next(c for c in doc["cards"] if c["title"] == "Tea")
        self.assertEqual(tea["state"], "ok")
        self.assertEqual(tea["sources"], ["kettles"])

    def test_register_card_first_wins(self):
        a = console.register_card("zz-test", title="One", build=lambda r: {"items": []}, needs=())
        b = console.register_card("zz-test", title="Two", build=lambda r: {"items": []}, needs=())
        self.assertIs(a, b)
        self.assertEqual(console.SPECS["zz-test"]["title"], "One")
        console.SPECS.pop("zz-test")


class ModelsTest(unittest.TestCase):
    def test_inventory(self):
        with labfake.Lab():
            inv = labmodels.inventory()
        kinds = {s["source"]: s for s in inv["servers"]}
        comfy = kinds["comfyui"]
        files = [m["name"] for m in comfy["models"] if m.get("folder")]
        self.assertTrue(any("qwen_image" in f for f in files))
        self.assertTrue(any(f.endswith(".gguf") for f in files))
        voice = kinds["voice"]
        self.assertTrue(all(m["loaded"] for m in voice["models"]))
        self.assertTrue(all(m["can"] == [] for m in voice["models"]), "the voice models are never unloadable here")
        self.assertIn("ollama", inv["errors"])

    def test_unload_rules(self):
        with labfake.Lab() as lab:
            with self.assertRaises(labmodels.Refused) as e:
                labmodels.unload("voice")
            self.assertIn("never", str(e.exception))
            msg = labmodels.unload("comfyui")
            self.assertIn("/free", msg)
            self.assertIn(("comfyui", "/free", {"unload_models": True, "free_memory": True}), lab.posts)
            with self.assertRaises(labmodels.Refused):
                labmodels.load("comfyui")
            with self.assertRaises(labmodels.Refused):
                labmodels.unload("no-such-model")
        self.assertFalse([p for p in lab.posts if p[0] == "voice"], "nothing is ever sent to the voice service")


if __name__ == "__main__":
    unittest.main()
