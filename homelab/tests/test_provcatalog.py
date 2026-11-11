"""The provisioning catalogue (share/provision-catalogue.toml) and provcatalog's API. No network."""
import copy
import glob
import os
import re
import unittest
from unittest import mock

from bromigos_homelab import provcatalog as PC

NO_GPU = {"cpu": 4, "ram_gb": 16, "disk_gb": 500, "gpu": False, "gpu_vram_gb": 0}
NVIDIA_12 = {"cpu": 8, "ram_gb": 32, "disk_gb": 900, "gpu": "nvidia", "gpu_vram_gb": 12, "gpu_name": "RTX 4070"}
NVIDIA_24 = dict(NVIDIA_12, gpu_vram_gb=24, ram_gb=64)
SMALL = {"cpu": 2, "ram_gb": 2, "disk_gb": 30, "gpu": False, "gpu_vram_gb": 0}


def setUpModule():
    """The checkout's catalogue and templates, never an installed bromigos-lab's (it comes first
    in provcatalog.paths(), and may be an older format)."""
    global _SHARE
    _SHARE = mock.patch.object(PC, "SHARE", "/nonexistent")
    _SHARE.start()
    PC._cache.clear()


def tearDownModule():
    _SHARE.stop()


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

    def test_no_catalogue_app_is_marked_to_update_by_itself(self):
        # The docs say plainly that the catalogue's container apps don't update by themselves (docs/server.md,
        # "Containers and services"; docs/lab-provision.md, "Updates"). An AutoUpdate= here would
        # update around the pinned digest with no snapshot and no check: when apps do update, it's
        # through the planned path, and those pages change with it
        from bromigos_homelab import localprovision as L
        units = [f for it in PC.load() if "quadlet" in it["install"] for f in L.template_files(it["install"]["quadlet"])]
        self.assertGreater(len(units), 30)
        self.assertEqual([f"{u.parent.name}/{u.name}" for u in units if "AutoUpdate" in u.read_text()], [])

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

    def test_the_lab_board_replaces_the_start_page(self):
        cat = PC.by_id()
        board = cat["board"]
        self.assertEqual((board["job"], board["app"], board["holo"]), ("Lab board", "bromigOS", "board"))
        self.assertEqual(board["install"], {"step": "board"})
        self.assertEqual(sorted(board["roles"]), ["game-server", "home-services", "media", "storage"])
        self.assertEqual(board["conflicts"], ["start-page"])
        self.assertFalse(cat["start-page"]["default"])
        ids, added = PC.resolve(["board"])
        self.assertEqual((ids, added), (["caddy", "board"], ["caddy"]))
        self.assertIsNone(board["web"])                 # Caddy serves it at <server>.local, not a port of its own

    def test_unknown_id_refused(self):
        with self.assertRaises(PC.CatalogueError):
            PC.resolve(["no-such-thing"])


# what localprovision.WEB held before the names moved into the catalogue (format 2), and the one
# port that wasn't the item's first: a server that's already set up keeps every name and address
WEB_NAMES = {"start-page": "home", "photos": "photos", "passwords": "passwords", "documents": "documents",
             "home-automation": "automation", "uptime": "uptime", "jellyfin": "media", "seerr": "requests",
             "monitoring": "graphs", "navidrome": "music", "audiobookshelf": "books", "file-sync": "sync", "s3": "s3",
             "pelican-panel": "games"}
# container apps nobody can ask "do you answer?": they listen on no port (the catalogue says why)
NO_HEALTH = {"recyclarr", "unpackerr"}
# container apps that keep nothing of their own under /srv/apps/<id>
NO_DATA = {"gluetun", "unpackerr"}


def quadlet_items():
    return [it for it in PC.load() if "quadlet" in it["install"]]


class FormatTwoTests(unittest.TestCase):
    """What format 2 added for the app manager: the job and the app apart, our icon, the web
    address, the data folders and the health check (docs/lab-provision.md, "The catalogue")."""

    def test_format(self):
        self.assertEqual(PC.file_format(), PC.FORMAT)
        self.assertEqual(PC.FORMAT, 2)

    def test_every_item_says_its_job_and_its_icon(self):
        for it in PC.load():
            self.assertTrue(it["job"], it["id"])
            self.assertIn(it["holo"], PC.HOLO, it["id"])
            self.assertEqual(it["version"], 1, it["id"])
            # the name the installer shows is still there, and still says both
            self.assertTrue(it["name"], it["id"])
        cat = PC.by_id()
        self.assertEqual((cat["photos"]["job"], cat["photos"]["app"]), ("Photos", "Immich"))
        self.assertEqual((cat["jellyfin"]["job"], cat["plex"]["job"]), ("Films and shows", "Films and shows"))
        self.assertEqual(cat["media-library"]["app"], "")           # a folder tree, not a program
        pairs = [(it["job"], it["app"]) for it in PC.load()]
        self.assertEqual(len(pairs), len(set(pairs)), "two tiles would read the same")

    def test_every_icon_has_an_item(self):
        self.assertEqual({it["holo"] for it in PC.load()}, set(PC.HOLO))

    def test_web_names_and_ports_are_what_the_code_built(self):
        self.assertEqual(PC.web_names(), WEB_NAMES)
        cat = PC.by_id()
        for i in WEB_NAMES:
            # Grafana's port; RustFS's console (its first port, 9000, is the S3 API, no page)
            want = {"monitoring": 3005, "s3": 9001}.get(i, cat[i]["ports"][0])
            self.assertEqual(cat[i]["web"]["port"], want, i)
        for it in PC.load():
            if it["web"]:
                self.assertIn(it["web"]["port"], it["ports"], it["id"])

    def test_every_container_app_lists_its_data_as_its_template_mounts_it(self):
        for it in quadlet_items():
            kept = PC.template_data(it["install"]["quadlet"])
            self.assertEqual(sorted(d["path"] for d in it["data"]), kept, it["id"])
            self.assertEqual(not kept, it["id"] in NO_DATA, it["id"])
            for d in it["data"]:
                self.assertIn(d["kind"], PC.DATA_KINDS, it["id"])
                self.assertTrue(d["what"].endswith("."), it["id"])

    def test_every_container_app_has_a_health_check_or_a_reason(self):
        self.assertEqual({it["id"] for it in quadlet_items() if not it["health"]}, NO_HEALTH)
        for it in quadlet_items():
            h = it["health"]
            if not h:
                continue
            units = PC.template_units(it["install"]["quadlet"])
            text = "\n".join(units.values())
            if "http" in h:
                published = {int(p) for p in re.findall(r"^(?:#[a-z]+:\S+ )?PublishPort=(\d+):", text, re.M)}
                on_host = re.search(r"^Network=host$", text, re.M)
                self.assertTrue(on_host or h["port"] in published, f"{it['id']}: nothing answers on port {h['port']}")
            else:
                self.assertEqual(h["cmd"][:2], ["podman", "exec"], it["id"])
                self.assertIn(f"ContainerName={h['cmd'][2]}\n", text, it["id"])

    def test_a_downloader_behind_the_vpn_is_checked_on_the_port_the_vpn_publishes(self):
        # with the kill switch on, the downloaders' pages are published by Gluetun's container
        gluetun = "\n".join(PC.template_units("gluetun").values())
        cat = PC.by_id()
        for i in ("sabnzbd", "slskd"):
            self.assertIn(f"#if:{i} PublishPort={cat[i]['health']['port']}:", gluetun)

    # -- validate() says so when a key is wrong
    def problems(self, change):
        doc = copy.deepcopy(PC._doc())
        change(doc, lambda i: next(x for x in doc["item"] if x["id"] == i))
        with mock.patch.object(PC, "_doc", lambda path=None: doc):
            return PC.validate()

    def assertProblem(self, words, change):
        got = self.problems(change)
        self.assertTrue(any(words in p for p in got), f"nothing said {words!r}: {got}")

    def test_validate_names_the_format_and_unknown_keys(self):
        self.assertProblem("format is 1", lambda doc, item: doc.update(format=1))
        self.assertProblem("photos: 'heatlh' isn't a key an item has", lambda doc, item: item("photos").update(heatlh={}))

    def test_validate_job_app_and_icon(self):
        self.assertProblem("photos: no job", lambda doc, item: item("photos").pop("job"))
        self.assertProblem("photos: job 'photos.'", lambda doc, item: item("photos").update(job="photos."))
        self.assertProblem("photos: holo 'camera'", lambda doc, item: item("photos").update(holo="camera"))
        self.assertProblem("job and app 'Films and shows · Jellyfin': used by jellyfin, plex",
                           lambda doc, item: item("plex").update(app="Jellyfin"))

    def test_validate_web(self):
        self.assertProblem("photos: web.port 2284 isn't one of its ports", lambda doc, item: item("photos")["web"].update(port=2284))
        self.assertProblem("photos: web.name 'my.photos'", lambda doc, item: item("photos")["web"].update(name="my.photos"))
        self.assertProblem("web name 'media': used by jellyfin, plex", lambda doc, item: item("plex")["web"].update(name="media"))
        self.assertProblem("plex: web.path 'web'", lambda doc, item: item("plex")["web"].update(path="web"))
        self.assertProblem("photos: web has no key 'url'", lambda doc, item: item("photos")["web"].update(url="x"))

    def test_validate_data(self):
        self.assertProblem("photos: its template keeps {{data}}/postgres, which no [[item.data]] names",
                           lambda doc, item: item("photos")["data"].pop(1))
        self.assertProblem("photos: data path thumbs isn't a volume under {{data}} in its template",
                           lambda doc, item: item("photos")["data"].append({"path": "thumbs", "kind": "cache", "what": "Thumbnails."}))
        self.assertProblem("photos: data path '../media'", lambda doc, item: item("photos")["data"][0].update(path="../media"))
        self.assertProblem("photos: data path '/srv/apps/photos/library'",
                           lambda doc, item: item("photos")["data"][0].update(path="/srv/apps/photos/library"))
        self.assertProblem("photos: data library: kind 'photos'", lambda doc, item: item("photos")["data"][0].update(kind="photos"))
        self.assertProblem("photos: data library: what says what is in it", lambda doc, item: item("photos")["data"][0].update(what="Photos"))
        self.assertProblem("photos: data path library is listed twice",
                           lambda doc, item: item("photos")["data"].append(dict(item("photos")["data"][0])))

    def test_validate_health(self):
        self.assertProblem("photos: health checks one way", lambda doc, item: item("photos")["health"].update(cmd=["podman", "exec", "immich-server", "true"]))
        self.assertProblem("photos: health checks one way", lambda doc, item: item("photos").update(health={"within_s": 5}))
        self.assertProblem("photos: health.port 2284 isn't one of its ports", lambda doc, item: item("photos")["health"].update(port=2284))
        self.assertProblem("photos: health.http 'api/server/ping'", lambda doc, item: item("photos")["health"].update(http="api/server/ping"))
        self.assertProblem("photos: health.expect 500", lambda doc, item: item("photos")["health"].update(expect=500))
        self.assertEqual(self.problems(lambda doc, item: item("photos")["health"].update(expect=[200, 302])), [])
        self.assertProblem("photos: health.within_s 0", lambda doc, item: item("photos")["health"].update(within_s=0))
        self.assertProblem("minecraft: health.cmd runs in 'paperless', which isn't a container of its template (minecraft)",
                           lambda doc, item: item("minecraft")["health"].update(cmd=["podman", "exec", "paperless", "mc-health"]))
        self.assertProblem("minecraft: health.cmd is [\"podman\", \"exec\", CONTAINER, COMMAND, …]",
                           lambda doc, item: item("minecraft")["health"].update(cmd=["sh", "-c", "mc-health"]))
        self.assertProblem("passwords: health.cmd is for an item that runs containers",
                           lambda doc, item: item("passwords").update(health={"cmd": ["podman", "exec", "x", "true"]}))

    def test_validate_the_keys_no_item_fills_yet(self):
        self.assertEqual(self.problems(lambda doc, item: item("photos").update(
            homepage="https://example.org", licence="AGPL-3.0", remove_note="Its phone app keeps its own copies.",
            version=2, app_version="v3.3.5", changed="2026-11-10", track="v3", status="testing",
            status_note="Its 3.x releases change the database often.", download_mb=2500,
            update={"manual": True, "note": "Read the release notes first.", "stop_first": True, "pre": ["true"]},
            tile={"reading": "last-backup", "source": "adapter:immich", "max_age_s": 900})), [])
        for words, change in (
                ("photos: homepage is an https:// address", {"homepage": "immich.app"}),
                ("photos: version is the recipe's revision", {"version": 0}),
                ("photos: changed is a date", {"changed": "yesterday"}),
                ("photos: status 'beta'", {"status": "beta"}),
                ("photos: status held needs a status_note", {"status": "held"}),
                ("photos: status_note is a sentence, beside a status", {"status_note": "Why."}),
                ("photos: download_mb is a number of megabytes", {"download_mb": "2.5 GB"}),
                ("photos: remove_note is a sentence", {"remove_note": "no"}),
                ("photos: update is auto or manual, not both", {"update": {"auto": True, "manual": True}}),
                ("photos: update has no key 'when'", {"update": {"when": "night"}}),
                ("photos: update.manual is true or false", {"update": {"manual": "yes"}}),
                ("photos: tile.max_age_s is a number above 0", {"tile": {"max_age_s": 0}})):
            self.assertProblem(words, lambda doc, item, change=change: item("photos").update(change))


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

    def test_memory_sentence_counts_the_system_when_the_item_alone_would_fit(self):
        argo = PC.by_id()["argocd"]                          # 1 GB, beside the system's 1 GB
        self.assertEqual(PC.fits_item(argo, {"ram_gb": 1.9}),
                         "Argo CD needs 1 GB of memory beside the 1 GB the system uses; this server has 1.9 GB.")
        self.assertEqual(PC.fits_item(argo, {"ram_gb": 0.5}), "Argo CD needs 1 GB of memory; this server has 0.5 GB.")
        self.assertIsNone(PC.fits_item(argo, {"ram_gb": 2}))


class RecommendTests(unittest.TestCase):
    def test_each_role(self):
        self.assertIn("smb-shares", PC.recommend(["storage"], NO_GPU))
        self.assertIn("s3", PC.recommend(["storage"], NO_GPU))
        home = PC.recommend(["home-services"], NO_GPU)
        for i in ("photos", "passwords", "caddy", "board", "uptime"):
            self.assertIn(i, home)
        self.assertNotIn("documents", home)               # default = false
        self.assertNotIn("start-page", home)              # the Lab board replaced it
        for role in ("storage", "game-server", "media"):
            self.assertIn("board", PC.recommend([role], NO_GPU), role)
        self.assertNotIn("board", PC.recommend(["lab-node"], NO_GPU))
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
