"""The Creation studio's models (studio.py): what it picks for a card from the real catalog and
the shipped workflows, the catalog's pinned files, and applying a plan with stand-ins: a fake
downloader (no real download), a stand-in root, a fake machine for the node packs. Upgrades,
the previous copies, rollback, the disk gate and create.toml.

    PYTHONPATH=lib python -m unittest tests.test_studio
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from unittest import mock

os.environ.setdefault("BROMIGOS_HOMELAB_CONFIG", "/nonexistent")
os.environ.setdefault("BROMIGOS_LAB_BENCH_LEDGER", "/nonexistent")
os.environ.setdefault("BROMIGOS_LAB_SETTINGS", "/nonexistent")

from bromigos_homelab import catalog as C                    # noqa: E402
from bromigos_homelab import catalog_upgrade as U            # noqa: E402
from bromigos_homelab import localprovision as L             # noqa: E402
from bromigos_homelab import studio as S                     # noqa: E402
from provfake import FakeMachine                             # noqa: E402

HERE = Path(__file__).parent
REAL = HERE.parent / "share" / "lab" / "models.toml"
WORKFLOWS = HERE.parent.parent / "core" / "crates" / "bromigos-art" / "workflows"
CAT = C.load(str(REAL))
WFS = S.load_workflows([str(WORKFLOWS)])
NV24 = {"gpu": "nvidia", "gpu_vram_gb": 24, "gpu_name": "", "ram_gb": 64}
NV8 = dict(NV24, gpu_vram_gb=8)
CORE_CLASSES = None


def content(dest):
    """A small stand-in for a model file: a few bytes made from its name."""
    return (dest.encode() + b"\n") * 3


def fake_manifest(cat):
    """The real manifest (every dest, repo and commit) with stand-in sizes and checksums."""
    out = {}
    for d, f in C.files(cat).items():
        c = content(d)
        out[d] = dict(f, bytes=len(c), sha256=hashlib.sha256(c).hexdigest())
    return out


FAKE = fake_manifest(CAT)
BY_URL = {S.url_of(f): f["dest"] for f in FAKE.values()}


class Fetcher:
    """download()'s shape: writes the stand-in bytes; `corrupt` dests get the wrong ones."""

    def __init__(self, corrupt=()):
        self.got = []
        self.corrupt = set(corrupt)

    def __call__(self, url, part, size, token=None):
        dest = BY_URL[url]
        self.got.append(dest)
        Path(part).write_bytes(content(dest)[::-1] if dest in self.corrupt else content(dest))


def plan(hw=NV24, **kw):
    kw.setdefault("licence", "commercial")
    kw.setdefault("region", "US")
    return S.plan(CAT, hw, wfs=WFS, **kw)


class CatalogFilesTest(unittest.TestCase):
    def test_the_pinned_files_are_whole(self):
        self.assertEqual(C.validate_files(CAT), [])
        man = C.files(CAT)
        for d, f in man.items():
            self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$", d)
            self.assertRegex(f["rev"], r"^[0-9a-f]{40}$", d)
            self.assertTrue(S.url_of(f).startswith(f"https://huggingface.co/{f['repo']}/resolve/{f['rev']}/"))

    def test_every_shipped_workflow_names_a_catalog_variant_and_has_every_file_pinned(self):
        self.assertGreater(len(WFS), 10)
        man = C.files(CAT)
        for name, w in WFS.items():
            v = S.variant_of(CAT, w)
            self.assertIsNotNone(v, f"{name}: _meta.catalog {w['catalog']!r} isn't a catalog variant")
            self.assertEqual(v.runtime, "comfyui", name)
            for d in w["requires"]:
                self.assertIn(d, man, f"{name} needs {d}, and no variant pins it")

    def test_a_node_class_comfyui_lacks_comes_from_a_pinned_pack(self):
        self.assertEqual(S.packs_for(CAT, WFS["birefnet"]["classes"]), ["comfyui-rmbg"])
        self.assertEqual(S.packs_for(CAT, WFS["pixal3d"]["classes"]), [])
        pack = CAT.node_packs["comfyui-rmbg"]
        self.assertEqual(pack["licence"], "GPL-3.0")

    def test_the_validator_names_a_bad_row(self):
        doc = tomllib.loads(REAL.read_text())
        v = next(v for m in doc["model"] if m["id"] == "lucida" for v in m["variant"] if v["id"] == "native-fp16")
        v["file"][0]["sha256"] = "abc"
        v["file"][0]["dest"] = "../escape.safetensors"
        bad = C.validate_files(C.Catalog(doc))
        self.assertTrue(any("sha256 is 64 hex digits" in b for b in bad), bad)
        self.assertTrue(any("dest is <folder>/<file>" in b for b in bad), bad)


class PlanTest(unittest.TestCase):
    def test_a_24_gb_card_makes_everything_with_licences_that_allow_selling(self):
        d = plan()
        got = {r["capability"]: r["workflow"] for r in d["capabilities"]}
        self.assertEqual(got, {"image.generate": "qwen-image-2512", "image.edit": "qwen-image-edit-2511",
                               "image.cutout": "lucida", "image.upscale": "seedvr2-7b",
                               "video.loop": "wan2.2-i2v-a14b", "video.upscale": "seedvr2-7b-video",
                               "model3d.generate": "pixal3d"})
        rows = {r["capability"]: r for r in d["capabilities"]}
        self.assertEqual(rows["image.generate"]["also"], ["qwen-image-2512-lightning"])
        self.assertIn("copy of the DINOv3 License", rows["model3d.generate"]["notices"][0])
        self.assertEqual(rows["model3d.generate"]["effective_tier"], "conditional")
        dests = [f["dest"] for f in d["files"]]
        self.assertEqual(len(dests), len(set(dests)), "a file two workflows share is fetched once")
        self.assertIn("text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", dests)
        self.assertEqual(d["bytes"], sum(f["bytes"] for f in d["files"]))
        self.assertEqual(d["node_packs"], [])

    def test_an_8_gb_card_gets_what_fits_and_says_why_not_the_rest(self):
        d = plan(NV8)
        got = {r["capability"]: r["workflow"] for r in d["capabilities"]}
        self.assertEqual(got["image.cutout"], "lucida")
        self.assertEqual(got["video.loop"], "wan2.2-ti2v-5b")
        self.assertIsNone(got["image.generate"])
        why = next(r for r in d["capabilities"] if r["capability"] == "image.generate")["why"]
        self.assertIn("needs 22 GiB", why)
        self.assertIn("no workflow for yet", why)

    def test_the_licence_filter_and_the_region_count(self):
        research = {r["capability"]: r["workflow"] for r in plan(licence="any")["capabilities"]}
        self.assertEqual(research["image.generate"], "qwen-image-2.1")
        amd = {r["capability"]: r["workflow"] for r in plan(dict(NV24, gpu="amd", gpu_vram_gb=12))["capabilities"]}
        self.assertEqual(amd["model3d.generate"], "hunyuan3d-2.1")
        eu = {r["capability"]: r["workflow"] for r in plan(dict(NV24, gpu_vram_gb=12), region="EU")["capabilities"]}
        self.assertIsNone(eu["model3d.generate"], "Tencent's licence excludes the EU")

    def test_no_card_no_models(self):
        d = plan({"gpu": False, "gpu_vram_gb": 0})
        self.assertEqual(d["files"], [])
        self.assertTrue(all("no graphics card" in r["why"] for r in d["capabilities"]))

    def test_a_desktop_card_keeps_room_for_its_screen(self):
        self.assertLess(plan(desktop=True)["gives_gib"], plan()["gives_gib"])


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.m = FakeMachine(self.root)
        self.clock = [1_800_000_000]
        self.fetch = Fetcher()
        self.free = [10 ** 15]
        p = mock.patch.object(C, "files", lambda cat: FAKE)
        p.start()
        self.addCleanup(p.stop)
        q = Path(self.root, S.QUADLET)
        q.parent.mkdir(parents=True)
        q.write_text("[Container]\nExec=bash /bromigos/launch.sh\n")
        self.manager = [404]
        self.home = Path(self.root, "home/me")
        self.home.mkdir(parents=True)

    def studio(self):
        return S.Studio(root=self.root, run=self.m, fetch=self.fetch, now=lambda: self.clock[0],
                        free=lambda p: self.free[0], http=lambda url: {"system": {"comfyui_version": "0.38.0"}},
                        status_of=lambda url: self.manager[0])

    def user(self):
        return (str(self.home), os.getuid(), os.getgid())

    def model(self, dest):
        return Path(self.root, S.MODELS, dest)

    def test_fetch_check_place_then_nothing_the_second_time(self):
        s = self.studio()
        d = plan()
        r = s.apply(d, CAT, WFS, user=self.user())
        self.assertTrue(r["ok"])
        self.assertEqual(sorted(r["fetched"]), sorted(f["dest"] for f in d["files"]))
        for f in d["files"]:
            self.assertEqual(self.model(f["dest"]).read_bytes(), content(f["dest"]))
            self.assertFalse(self.model(f["dest"] + ".part").exists())
        st = json.loads(Path(self.root, S.STATE).read_text())
        self.assertEqual(st["capabilities"]["video.loop"], "wan2.2-i2v-a14b")
        wf = Path(self.root, S.WORKFLOWS_OUT)
        self.assertEqual(sorted(p.stem for p in wf.glob("*.json")), sorted(d["workflows"]))
        self.fetch.got.clear()
        r = s.apply(d, CAT, WFS, user=self.user())
        self.assertEqual((r["fetched"], self.fetch.got), ([], []))
        status = s.status(CAT, WFS)
        self.assertTrue(status["answers"])
        self.assertTrue(all(c["ready"] for c in status["capabilities"]))
        self.assertEqual(status["missing"], [])

    def test_a_file_that_does_not_match_its_checksum_is_thrown_away(self):
        self.fetch.corrupt = {"vae/wan_2.1_vae.safetensors"}
        r = self.studio().apply(plan(), CAT, WFS)
        self.assertFalse(r["ok"])
        self.assertEqual([x["dest"] for x in r["failed"]], ["vae/wan_2.1_vae.safetensors"])
        self.assertIn("published checksum", r["failed"][0]["why"])
        self.assertFalse(self.model("vae/wan_2.1_vae.safetensors").exists())
        self.assertFalse(self.model("vae/wan_2.1_vae.safetensors.part").exists())
        self.assertNotIn("video.loop", r["capabilities"], "a kind of art with a bad file isn't wired up")
        self.assertIn("image.generate", r["capabilities"])
        st = self.studio().status(CAT, WFS)
        self.assertEqual(next(c for c in st["capabilities"] if c["capability"] == "video.loop")["workflow"], None)

    def test_a_file_put_there_by_hand_is_checked_once_and_kept(self):
        d = plan()
        f = next(x for x in d["files"] if x["dest"].startswith("background_removal/"))
        self.model(f["dest"]).parent.mkdir(parents=True)
        self.model(f["dest"]).write_bytes(content(f["dest"]))
        self.studio().apply(d, CAT, WFS)
        self.assertNotIn(f["dest"], self.fetch.got)

    def test_the_disk_gate_leaves_out_the_last_kinds_of_art(self):
        d = plan()
        sizes = sum(f["bytes"] for f in d["files"])
        self.free[0] = S.RESERVE_GIB * 1024 ** 3 + sizes - 1
        r = self.studio().apply(d, CAT, WFS)
        self.assertEqual([x["capability"] for x in r["left_out"]], ["model3d.generate"])
        self.assertIn("not enough disk", r["left_out"][0]["why"])
        self.assertNotIn("model3d.generate", r["capabilities"])

    def test_node_packs_are_installed_pinned_inside_the_container_once(self):
        d = plan(only=["birefnet"])
        self.assertEqual([p["name"] for p in d["node_packs"]], ["ComfyUI-RMBG"])
        s = self.studio()
        r = s.apply(d, CAT, WFS)
        self.assertEqual(r["node_packs"], ["comfyui-rmbg"])
        calls = [" ".join(c) for c in self.m.calls]
        commit = CAT.node_packs["comfyui-rmbg"]["commit"]
        self.assertIn("podman exec comfyui git clone --filter=blob:none https://github.com/1038lab/ComfyUI-RMBG "
                      "/root/ComfyUI/custom_nodes/ComfyUI-RMBG", calls)
        self.assertIn(f"podman exec comfyui git -C /root/ComfyUI/custom_nodes/ComfyUI-RMBG checkout --quiet {commit}", calls)
        self.assertIn("systemctl restart comfyui.service", calls)
        Path(self.root, S.NODES, "ComfyUI-RMBG").mkdir(parents=True)
        self.m.calls.clear()
        s.apply(d, CAT, WFS)
        self.assertFalse(self.m.ran("podman exec"))

    def test_an_upgrade_keeps_the_earlier_model_and_rollback_puts_it_back(self):
        s = self.studio()
        small = plan(NV8)
        s.apply(small, CAT, WFS)
        ti2v = WFS["wan2.2-ti2v-5b"]["requires"]
        # the card grew: the policy (video: any) moves loops to the A14B
        ev = S.upgrade(CAT, NV24, s, {"enabled": True, "policy": {"video": "any"}}, "commercial", "US", wfs=WFS)
        moves = {c["capability"]: (c["from"], c["to"]) for c in ev["changes"]}
        self.assertEqual(moves["video.loop"], ("wan2.2-ti2v-5b", "wan2.2-i2v-a14b"))
        self.assertIn("image.generate", moves, "a kind of art nothing made yet is simply added")
        held = {c["capability"]: c["held"] for c in ev["held"]}
        self.assertNotIn("video.loop", held)
        caps = {c["capability"] for c in ev["changes"]}
        doc = dict(ev["plan"], capabilities=[r for r in ev["plan"]["capabilities"] if r["capability"] in caps])
        r = s.apply(doc, CAT, WFS, user=self.user())
        self.assertEqual(r["capabilities"]["video.loop"], "wan2.2-i2v-a14b")
        self.assertIn("wan2.2-ti2v-5b", r["workflows"], "the previous model stays installed")
        for dest in ti2v:
            self.assertTrue(self.model(dest).exists(), dest)
        toml = tomllib.loads((self.home / ".config/bromigos/create.toml").read_text())
        self.assertEqual(toml["video"]["loop"]["comfyui"][:2], ["wan2.2-i2v-a14b", "wan2.2-ti2v-5b"])
        rb = s.rollback("video.loop", wfs=WFS)
        self.assertEqual(rb["rolled_back"], [{"capability": "video.loop", "from": "wan2.2-i2v-a14b", "to": "wan2.2-ti2v-5b"}])
        self.assertEqual(s.state()["capabilities"]["video.loop"], "wan2.2-ti2v-5b")
        self.assertEqual(s.state()["previous"]["video.loop"]["workflow"], "wan2.2-i2v-a14b")
        # after KEEP_DAYS the one not in use goes, with the files only it needed
        self.clock[0] += S.KEEP_DAYS * 86400
        r = s.apply(dict(plan(NV8), capabilities=[]), CAT, WFS)
        self.assertNotIn("wan2.2-i2v-a14b", r["workflows"])
        self.assertIn("diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", r["retired"])
        self.assertFalse(self.model("diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors").exists())
        self.assertTrue(self.model("text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors").exists(),
                        "a file the kept model shares stays")

    def test_the_policy_holds_what_it_does_not_allow(self):
        s = self.studio()
        s.apply(plan(NV8), CAT, WFS)
        off = S.upgrade(CAT, NV24, s, {"enabled": False, "policy": {"video": "any"}}, "commercial", "US", wfs=WFS)
        self.assertIn("switched off", {c["capability"]: c["held"] for c in off["held"]}["video.loop"])
        safe = S.upgrade(CAT, NV24, s, {"enabled": True, "policy": {"video": "safe"}}, "commercial", "US", wfs=WFS)
        held = {c["capability"]: c["held"] for c in safe["held"]}
        self.assertIn("video.loop", {c["capability"] for c in safe["changes"]} | set(held))

    def test_a_file_replaced_at_the_same_path_is_kept_and_rolled_back(self):
        s = self.studio()
        d = plan(only=["lucida"])
        s.apply(d, CAT, WFS)
        dest = "background_removal/lucida_v7.safetensors"
        newer = b"lucida v8\n" * 4
        man = dict(FAKE, **{dest: dict(FAKE[dest], bytes=len(newer), sha256=hashlib.sha256(newer).hexdigest())})
        st = s.state()
        f = man[dest]
        self.fetch = lambda url, part, size, token=None: Path(part).write_bytes(newer)
        s.fetch = self.fetch
        s.get(f, st)
        s.save(st)
        self.assertEqual(self.model(dest).read_bytes(), newer)
        self.assertEqual(Path(self.root, S.PREVIOUS, dest).read_bytes(), content(dest))
        st = s.state()
        st["previous"]["image.cutout"] = {"workflow": "lucida", "at": self.clock[0]}
        s.save(st)
        s.rollback("image.cutout", wfs=WFS)
        self.assertEqual(self.model(dest).read_bytes(), content(dest))
        self.assertEqual(Path(self.root, S.PREVIOUS, dest).read_bytes(), newer)

    def test_every_apply_locks_the_page_again(self):
        s = self.studio()
        s.apply(plan(NV8), CAT, WFS)
        base = Path(self.root, S.DATA)
        self.assertNotIn("--enable-manager", (base / "launch.sh").read_text())
        for rel in ("user/__manager/config.ini", "user/default/ComfyUI-Manager/config.ini"):
            cfg = (base / rel).read_text()
            self.assertIn("security_level = strong\n", cfg)
            self.assertIn("network_mode = private\n", cfg)
            self.assertIn("allow_pip_install = false\n", cfg)
        self.assertTrue(s.status(CAT, WFS)["locked"])
        # an image update, or a hand, reopened it: status says so, and the next apply locks it again
        (base / "user/__manager/config.ini").write_text("[default]\nsecurity_level = weak\n")
        st = s.status(CAT, WFS)
        self.assertFalse(st["locked"])
        self.assertIn("the Manager's settings (user/__manager/config.ini) aren't locked", st["lock_problems"])
        self.m.calls.clear()
        r = s.apply(plan(NV8), CAT, WFS)
        self.assertTrue(r["relocked"])
        self.assertEqual(r["lock_problems"], [])
        self.assertIn(["systemctl", "restart", "comfyui.service"], self.m.calls, "ComfyUI starts again to take it")
        self.assertIn("security_level = strong", (base / "user/__manager/config.ini").read_text())
        self.m.calls.clear()
        self.assertFalse(s.apply(plan(NV8), CAT, WFS)["relocked"])
        self.assertNotIn(["systemctl", "restart", "comfyui.service"], self.m.calls)

    def test_apply_puts_the_relay_and_its_token_back(self):
        """bromigos lab studio apply re-asserts the relay node, its token and labjobs.toml's reference."""
        s = self.studio()
        s.apply(plan(NV8), CAT, WFS)
        relay = Path(self.root, "srv/apps/comfyui/custom_nodes/bromigos-relay")
        token = (relay / "token").read_text()
        (relay / "__init__.py").unlink()
        Path(self.root, "etc/bromigos/labjobs.toml").write_text('[[comfyui]]\nname = "studio"\nurl = "http://127.0.0.1:8188"\n')
        self.m.calls.clear()
        self.assertTrue(s.apply(plan(NV8), CAT, WFS)["relocked"])
        self.assertIn(["systemctl", "restart", "comfyui.service"], self.m.calls, "ComfyUI starts again to load the node")
        self.assertTrue((relay / "__init__.py").is_file())
        self.assertEqual((relay / "token").read_text(), token, "the same token")
        self.assertIn('relay_token = "@file:/srv/apps/comfyui/custom_nodes/bromigos-relay/token"',
                      Path(self.root, "etc/bromigos/labjobs.toml").read_text())

    def test_a_manager_that_answers_or_the_image_s_own_start_is_a_problem(self):
        s = self.studio()
        s.apply(plan(NV8), CAT, WFS)
        self.manager[0] = 200
        self.assertIn("ComfyUI-Manager answers on the page, so it could install node packs",
                      s.status(CAT, WFS)["lock_problems"])
        self.manager[0] = 404
        Path(self.root, S.QUADLET).write_text("[Container]\n")
        self.assertTrue(any("the image's own way" in p for p in s.status(CAT, WFS)["lock_problems"]))

    def test_nothing_set_up_nothing_applied(self):
        Path(self.root, S.QUADLET).unlink()
        with self.assertRaises(S.StudioError):
            self.studio().apply(plan(), CAT, WFS)
        self.assertFalse(self.studio().status(CAT, WFS)["installed"])


class DownloadTest(unittest.TestCase):
    def test_a_stopped_download_carries_on_with_a_range(self):
        body = b"0123456789" * 10
        seen = []

        class Resp(io.BytesIO):
            status = 206

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout=None):
            seen.append(req.get_header("Range"))
            start = int(req.get_header("Range").split("=")[1].rstrip("-"))
            return Resp(body[start:])

        with tempfile.TemporaryDirectory() as d:
            part = os.path.join(d, "x.part")
            Path(part).write_bytes(body[:37])
            S.download("https://huggingface.co/a/b/resolve/c/x", part, len(body), opener=opener)
            self.assertEqual(Path(part).read_bytes(), body)
            self.assertEqual(seen, ["bytes=37-"])

    def test_a_network_error_keeps_what_came(self):
        def opener(req, timeout=None):
            raise OSError("reset")

        with tempfile.TemporaryDirectory() as d:
            part = os.path.join(d, "x.part")
            Path(part).write_bytes(b"abc")
            with self.assertRaises(S.FetchError):
                S.download("https://example.invalid/x", part, 10, opener=opener)
            self.assertEqual(Path(part).read_bytes(), b"abc")


class CreateTomlTest(unittest.TestCase):
    ST = {"capabilities": {"image.generate": "qwen-image-2512", "video.loop": "wan2.2-ti2v-5b"},
          "previous": {}}
    SHIPPED = {"image": {"generate": {"comfyui": "qwen-image-2512"}},
               "video": {"loop": {"comfyui": ["wan2.2-i2v-a14b", "wan2.2-ti2v-5b"]}}}

    def test_a_new_file(self):
        text = S.create_toml_text("", self.ST, WFS, self.SHIPPED)
        doc = tomllib.loads(text)
        self.assertEqual(doc["comfyui"]["local"]["endpoint"], "http://127.0.0.1:8188")
        self.assertEqual(doc["video"]["loop"]["comfyui"], ["wan2.2-ti2v-5b", "wan2.2-i2v-a14b"])
        self.assertEqual(doc["image"]["generate"]["comfyui"], ["qwen-image-2512"])

    def test_yours_is_kept_and_only_the_lists_change(self):
        mine = ('format = 1\n# my notes\n[comfyui.local]\nendpoint = "http://10.0.0.9:8188"\n\n'
                '[video.loop]\nproviders = ["comfyui:local", "nolgia"]   # mine\ncomfyui = "wan2.2-i2v-a14b"\nnolgia = "seedance-2.5"\n')
        text = S.create_toml_text(mine, self.ST, WFS, self.SHIPPED)
        self.assertIn("# my notes", text)
        self.assertIn('providers = ["comfyui:local", "nolgia"]   # mine', text)
        doc = tomllib.loads(text)
        self.assertEqual(doc["comfyui"]["local"]["endpoint"], "http://10.0.0.9:8188", "your endpoint stays")
        self.assertEqual(doc["video"]["loop"]["comfyui"][0], "wan2.2-ti2v-5b")
        self.assertEqual(doc["video"]["loop"]["nolgia"], "seedance-2.5")
        self.assertEqual(text.count("[comfyui.local]"), 1)
        self.assertEqual(S.create_toml_text(text, self.ST, WFS, self.SHIPPED), text, "running it again changes nothing")

    def test_the_shipped_default_file_is_read(self):
        shipped = S.shipped_create(path="/nonexistent")
        self.assertIn("generate", shipped.get("image", {}))


class WiringTest(unittest.TestCase):
    def test_the_provisioning_step_applies_and_says_what_it_made(self):
        lines = []

        class Host:
            root = "/nonexistent-root"
            hw = NV24
            run = None

            def setting(self, item, field):
                return "commercial"

            def emit(self, line):
                lines.append(line)

        class Fake:
            def __init__(self, failed=()):
                self.failed = list(failed)
                self.docs = []

            def apply(self, doc, user=None):
                self.docs.append(doc)
                return {"left_out": [], "failed": self.failed, "capabilities": {"image.cutout": "lucida"}}

        f = Fake()
        with mock.patch.object(S, "load_workflows", lambda dirs=None: WFS), mock.patch.object(S, "user_home", lambda *a, **k: None):
            S.provision_step(Host(), {"id": "comfyui"}, studio=f)
            self.assertEqual(f.docs[0]["licence"], "commercial")
            self.assertTrue(any("makes cutouts" in l for l in lines), lines)
            with self.assertRaises(L.ProvisionError):
                S.provision_step(Host(), {"id": "comfyui"}, studio=Fake([{"dest": "x", "why": "it stopped"}]))

    def test_upgrades_apply_goes_to_the_studio_on_this_machine(self):
        with mock.patch.object(S.Studio, "installed", lambda self: True), \
                mock.patch.object(S, "main", return_value=0) as main:
            self.assertEqual(U.main(["--apply"]), 0)
        self.assertEqual(main.call_args[0][0], ["upgrade", "--apply"])

    def test_changing_the_studio_needs_root_and_says_so(self):
        err = io.StringIO()
        with mock.patch.object(S.Studio, "installed", lambda self: True), \
                mock.patch("bromigos_homelab.labapps.Machine.may_change", lambda self: False), \
                mock.patch("bromigos_homelab.labapps.Machine.hw", lambda self: NV24), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(S.main(["apply"]), S.EXIT_REFUSED)
        self.assertIn("needs root", err.getvalue())

    def test_plan_json_for_a_card_you_name(self):
        out = io.StringIO()
        with mock.patch.object(S, "load_workflows", lambda dirs=None: WFS), contextlib.redirect_stdout(out):
            self.assertEqual(S.main(["plan", "--vram", "24", "--licence", "commercial", "--region", "US", "--json"]), 0)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["licence"], "commercial")
        self.assertTrue(re.match(r"https://huggingface.co/", doc["files"][0]["url"]))


if __name__ == "__main__":
    unittest.main()
