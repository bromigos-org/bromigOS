"""The provisioning catalogue (share/provision-catalogue.toml) and provcatalog's API. No network."""
import glob
import os
import unittest

from bromigos_homelab import provcatalog as PC

NO_GPU = {"cpu": 4, "ram_gb": 16, "disk_gb": 500, "gpu": False, "gpu_vram_gb": 0}
NVIDIA_12 = {"cpu": 8, "ram_gb": 32, "disk_gb": 900, "gpu": "nvidia", "gpu_vram_gb": 12, "gpu_name": "RTX 4070"}
NVIDIA_24 = dict(NVIDIA_12, gpu_vram_gb=24, ram_gb=64)
SMALL = {"cpu": 2, "ram_gb": 2, "disk_gb": 30, "gpu": False, "gpu_vram_gb": 0}


class CatalogueTests(unittest.TestCase):
    def test_loads_and_validates(self):
        self.assertEqual(PC.validate(), [])
        items = PC.load()
        self.assertGreater(len(items), 40)
        self.assertEqual([g["id"] for g in PC.groups()], list(PC.GROUPS))

    def test_every_needs_and_conflicts_id_exists(self):
        ids = {it["id"] for it in PC.load()}
        for it in PC.load():
            for need in it["needs"]:
                for alt in PC.alternatives(need):
                    self.assertIn(alt, ids, it["id"])
            for c in it["conflicts"]:
                self.assertIn(c, ids, it["id"])

    def test_no_cycles(self):
        self.assertIsNone(PC._cycle(PC.load()))
        looped = [{"id": "a", "needs": ["b"]}, {"id": "b", "needs": ["c|a"]}, {"id": "c", "needs": []}]
        self.assertEqual(PC._cycle(looped)[-1], "a")

    def test_every_group_has_items_and_icons(self):
        items = PC.load()
        for g in PC.groups():
            self.assertTrue(any(it["group"] == g["id"] for it in items), g["id"])
            self.assertTrue(g["icon"].endswith("-symbolic"))
            self.assertIn(g["glyph"], PC.GLYPHS)
        for it in items:
            self.assertTrue(it["icon"].endswith("-symbolic"), it["id"])
            self.assertIn(it["glyph"], PC.GLYPHS, it["id"])

    def test_icons_are_adwaita_names_where_adwaita_is_installed(self):
        have = {os.path.basename(p)[:-4] for p in glob.glob("/usr/share/icons/Adwaita/symbolic/*/*.svg")}
        if not have:
            self.skipTest("no Adwaita icon theme here")
        for x in PC.groups() + PC.load():
            self.assertIn(x["icon"], have, x["id"])

    def test_glyphs_match_bromigos_textual_when_it_has_icons(self):
        try:
            import bromigos_textual as T
        except Exception:                          # noqa: BLE001
            self.skipTest("no bromigos_textual")
        if not hasattr(T, "ICONS"):
            self.skipTest("this bromigos_textual has no ICONS table yet")
        for g in PC.GLYPHS:
            self.assertIn(g, T.ICONS)

    def test_images_pinned_by_digest(self):
        for it in PC.load():
            for name, ref in it["images"].items():
                self.assertRegex(ref, r"@sha256:[0-9a-f]{64}$", f"{it['id']} {name}")

    def test_never_pterodactyl_and_neutral_media(self):
        from pathlib import Path
        text = Path(PC.paths()[-1]).read_text().lower()
        self.assertNotIn("pterodactyl", text)
        self.assertNotIn("netdata", text)
        cat = PC.by_id()
        for i in ("qbittorrent", "sabnzbd", "slskd", "gluetun"):
            self.assertFalse(cat[i]["default"], i)
        self.assertIn("indexers you have access to", cat["prowlarr"]["setup"]["intro"])
        # no indexer or tracker is named anywhere
        for word in ("nzbgeek", "drunkenslug", "rarbg", "1337x", "thepiratebay", "torrentleech"):
            self.assertNotIn(word, text)

    def test_unknown_id_refused(self):
        with self.assertRaises(PC.CatalogueError):
            PC.resolve(["no-such-thing"])


class ResolveTests(unittest.TestCase):
    def test_argocd_adds_k3s_first(self):
        ids, added = PC.resolve(["argocd"])
        self.assertEqual(ids, ["k3s", "argocd"])
        self.assertEqual(added, ["k3s"])

    def test_either_need_met_by_choice(self):
        ids, added = PC.resolve(["litellm", "vllm"])
        self.assertNotIn("ollama", ids)
        self.assertEqual(added, [])
        ids, added = PC.resolve(["litellm"])
        self.assertIn("ollama", added)
        self.assertLess(ids.index("ollama"), ids.index("litellm"))

    def test_chain_and_order(self):
        ids, added = PC.resolve(["autoscan"])
        for need in ("media-library", "jellyfin", "sonarr", "prowlarr"):
            self.assertIn(need, added)
        self.assertLess(ids.index("media-library"), ids.index("jellyfin"))
        self.assertLess(ids.index("prowlarr"), ids.index("sonarr"))
        self.assertLess(ids.index("sonarr"), ids.index("autoscan"))

    def test_conflicts_in_words(self):
        self.assertTrue(PC.conflicts(["ollama", "vllm"]))
        self.assertEqual(PC.conflicts(["ollama", "litellm"]), [])


class BudgetTests(unittest.TestCase):
    def test_sums(self):
        b = PC.budget(["photos", "passwords"], NO_GPU)
        self.assertEqual(b["ram_gb"], 4 + 0.25 + PC.OS_RAM_GB)
        self.assertEqual(b["disk_gb"], 21)
        self.assertEqual(b["cpu"], 3)
        self.assertTrue(b["fits"])

    def test_small_ram_doesnt_fit(self):
        b = PC.budget(["photos"], SMALL)
        self.assertFalse(b["fits"])
        self.assertTrue(any("memory" in n for n in b["notes"]))
        self.assertTrue(all(n.endswith(".") for n in b["notes"]))

    def test_gpu_needed(self):
        b = PC.budget(["ollama"], NO_GPU)
        self.assertFalse(b["fits"])
        self.assertIn("graphics card", " ".join(b["notes"]))
        self.assertTrue(PC.budget(["ollama"], NVIDIA_12)["fits"])

    def test_vram_and_vendor(self):
        self.assertFalse(PC.budget(["vllm"], NVIDIA_12)["fits"])
        self.assertTrue(PC.budget(["vllm"], NVIDIA_24)["fits"])
        self.assertFalse(PC.budget(["vllm"], dict(NVIDIA_24, gpu="amd"))["fits"])
        b = PC.budget(["ollama"], NVIDIA_12, models=[{"vram_gb": 20}])
        self.assertFalse(b["fits"])

    def test_disk(self):
        self.assertFalse(PC.budget(["vllm"], dict(NVIDIA_24, disk_gb=50))["fits"])

    def test_conflict_doesnt_fit(self):
        self.assertFalse(PC.budget(["ollama", "vllm"], NVIDIA_24)["fits"])


class RecommendTests(unittest.TestCase):
    def test_each_role(self):
        self.assertIn("smb-shares", PC.recommend(["storage"], NO_GPU))
        self.assertIn("s3", PC.recommend(["storage"], NO_GPU))
        home = PC.recommend(["home-services"], NO_GPU)
        for i in ("photos", "passwords", "caddy", "start-page", "uptime"):
            self.assertIn(i, home)
        self.assertNotIn("documents", home)               # default = false
        media = PC.recommend(["media"], NO_GPU)
        for i in ("jellyfin", "seerr", "sonarr", "radarr", "lidarr", "prowlarr", "recyclarr", "den-tv"):
            self.assertIn(i, media)
        for i in ("qbittorrent", "sabnzbd", "gluetun", "slskd", "plex"):
            self.assertNotIn(i, media)
        self.assertEqual(PC.recommend(["base"], NO_GPU), ["backups", "brodec-machine"])
        self.assertEqual(PC.recommend(["just-a-server"], NO_GPU), ["backups", "brodec-machine"])

    def test_game_server_by_lab(self):
        self.assertIn("minecraft", PC.recommend(["game-server"], NO_GPU, lab="none"))
        joined = PC.recommend(["game-server"], NO_GPU, lab="join")
        self.assertIn("wings", joined)
        self.assertNotIn("pelican-panel", joined)
        self.assertNotIn("minecraft", joined)
        new = PC.recommend(["game-server"], NO_GPU, lab="new")
        self.assertIn("pelican-panel", new)

    def test_lab_node_and_gpu(self):
        plain = PC.recommend(["lab-node"], NO_GPU, lab="new")
        self.assertIn("k3s", plain)
        self.assertIn("vault", plain)
        self.assertNotIn("ollama", plain)
        gpu = PC.recommend(["lab-node"], NVIDIA_12, lab="new")
        self.assertIn("ollama", gpu)
        self.assertIn("litellm", gpu)
        self.assertNotIn("vllm", gpu)
        joined = PC.recommend(["lab-node"], NO_GPU, lab="join")
        self.assertIn("lab-network", joined)
        self.assertNotIn("vault", joined)

    def test_union_of_roles(self):
        a = set(PC.recommend(["storage"], NO_GPU))
        b = set(PC.recommend(["media"], NO_GPU))
        both = PC.recommend(["storage", "media"], NO_GPU)
        self.assertEqual(set(both), a | b)
        self.assertEqual(len(both), len(set(both)))

    def test_unknown_role(self):
        with self.assertRaises(PC.CatalogueError):
            PC.recommend(["spaceship"], NO_GPU)


class ModelTests(unittest.TestCase):
    def test_sized_to_vram(self):
        for hw in (NVIDIA_12, NVIDIA_24):
            ms = PC.suggest_models(hw)
            self.assertTrue(ms)
            for m in ms:
                self.assertLessEqual(m["vram_gb"], hw["gpu_vram_gb"], m["id"])
                self.assertIn(m["serve_with"], ("ollama", "vllm"))
            self.assertEqual(sum(1 for m in ms if m["default"] and m["capability"] == "llm"), 1)

    def test_bigger_card_bigger_model(self):
        small = next(m for m in PC.suggest_models(NVIDIA_12) if m["default"] and m["capability"] == "llm")
        big = next(m for m in PC.suggest_models(NVIDIA_24) if m["default"] and m["capability"] == "llm")
        self.assertGreaterEqual(big["vram_gb"], small["vram_gb"])

    def test_cpu_only(self):
        for m in PC.suggest_models(NO_GPU):
            self.assertEqual(m["vram_gb"], 0)


if __name__ == "__main__":
    unittest.main()
