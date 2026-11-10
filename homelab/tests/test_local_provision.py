"""`bromigos lab provision --local`: plans (goldens), the answer file, apply with a fake
machine (offline items first, the rest when the network comes; failures in plain words; re-runs
change nothing), rendered Quadlets that name secrets and never hold them. No network."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from bromigos_homelab import localprovision as L, provcatalog as PC, secretstore as S, provision as P
from provfake import FakeMachine

HERE = Path(__file__).parent
GOLDEN = HERE / "golden"
HW = {"cpu": 8, "ram_gb": 32, "disk_gb": 900, "gpu": False, "gpu_vram_gb": 0, "gpu_name": ""}
ANSWERS = """# what the installer writes (docs/lab-provision.md, "The answer file")
[server]
roles = ["media", "storage"]
lab = "none"
provision = ["jellyfin", "seerr", "sonarr", "radarr", "gluetun", "qbittorrent", "smb-shares", "backups"]
models = []

[server.settings.gluetun]
provider = "pia"
username = "p1234567"
password = { secret = "local:gluetun/password" }

[server.settings.media-library]
language = "English"
dual_audio = true
"""
VPN_PASSWORD = "correct-horse-battery-staple"


def setUpModule():
    """The checkout's catalogue and templates, never an installed bromigos-lab's (it comes first
    in provcatalog.paths(), and may be an older format)."""
    global _SHARE
    _SHARE = mock.patch.object(PC, "SHARE", "/nonexistent")
    _SHARE.start()
    PC._cache.clear()


def tearDownModule():
    _SHARE.stop()


def update(name, doc):
    path = GOLDEN / name
    if os.environ.get("BROMIGOS_UPDATE_GOLDEN") or not path.exists():
        path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return json.loads(path.read_text())


class PlanTests(unittest.TestCase):
    def test_from_selection_golden(self):
        plan = L.build_plan(["argocd", "photos", "passwords"], hw=HW)
        self.assertEqual(json.loads(json.dumps(plan, sort_keys=True)), update("local-plan-selection.json", plan))
        ids = [r["id"] for r in plan["items"]]
        self.assertEqual(ids[:2], ["k3s", "argocd"])
        self.assertIn("caddy", plan["auto_added"])            # Vaultwarden needs HTTPS
        row = next(r for r in plan["items"] if r["id"] == "photos")
        self.assertEqual(row["install"]["kind"], "quadlet")
        self.assertEqual(sorted(row["services"]), ["immich-database.service", "immich-ml.service",
                                                   "immich-server.service", "immich-valkey.service"])
        self.assertTrue(row["internet"])

    def test_from_answers_golden(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "install-answers.toml")
            f.write_text(ANSWERS)
            a = L.read_answers(f)
        plan = L.build_plan(a["provision"], a["roles"], a["lab"], a["lab_join"], a["models"], a["settings"], HW)
        self.assertEqual(json.loads(json.dumps(plan, sort_keys=True)), update("local-plan-answers.json", plan))
        self.assertEqual(plan["secret_refs"], {"gluetun": {"password": "local:gluetun/password"}})
        self.assertNotIn("password", plan["settings"]["gluetun"])
        self.assertIn("media-library", plan["offline"])

    def test_roles_only(self):
        plan = L.build_plan(None, ["home-services"], hw=HW)
        self.assertIn("photos", [r["id"] for r in plan["items"]])
        plan = L.build_plan(None, ["base"], hw=HW)
        self.assertEqual([r["id"] for r in plan["items"]], ["backups", "brodec-machine"])

    def test_tiers_map_onto_the_catalogue(self):
        plan = L.build_plan(None, preset="advanced", hw=HW)
        ids = [r["id"] for r in plan["items"]]
        for i in ("k3s", "argocd", "vault", "monitoring", "backups", "caddy", "start-page"):
            self.assertIn(i, ids)

    def test_secret_inline_in_answers_refused(self):
        with self.assertRaises(L.ProvisionError) as e:
            L.build_plan(["gluetun"], settings={"gluetun": {"password": "plain-text"}}, hw=HW)
        self.assertIn("never write it in the answer file", str(e.exception))
        with self.assertRaises(L.ProvisionError):
            L.build_plan(["gluetun"], settings={"gluetun": {"nonsense": 1}}, hw=HW)

    def test_problems_for_conflicts(self):
        plan = L.build_plan(["ollama", "vllm"], hw=dict(HW, gpu="nvidia", gpu_vram_gb=24))
        self.assertTrue(plan["problems"])

    def test_cli_plan_json(self):
        with tempfile.TemporaryDirectory() as d:
            hw = Path(d, "hw.json")
            hw.write_text(json.dumps(HW))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = P.main(["--local", "--select", "uptime", "--hardware", str(hw), "--plan", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual([r["id"] for r in json.loads(out.getvalue())["items"]], ["uptime"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                P.main(["--local", "--select", "uptime", "--hardware", str(hw), "--plan"])
            self.assertIn("Uptime Kuma", out.getvalue())


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.m = FakeMachine(self.root)
        self.store = S.LocalStore(self.root, self.m, "box")
        self.lines = []
        self.net = {"up": False, "after": 1, "polls": 0}

    def tearDown(self):
        self.tmp.cleanup()

    def online(self):
        return self.net["up"]

    def sleep(self, s):
        self.net["polls"] += 1
        if self.net["polls"] >= self.net["after"]:
            self.net["up"] = True

    def host(self, plan, **kw):
        return L.Host(plan, root=self.root, run_=self.m, online=self.online, sleep=self.sleep, store=self.store,
                      emit=self.lines.append, hw=HW, hostname="box", tz="America/Los_Angeles", **kw)

    def answers_plan(self):
        f = Path(self.root, "install-answers.toml")
        f.write_text(ANSWERS)
        a = L.read_answers(f)
        return L.build_plan(a["provision"], a["roles"], a["lab"], a["lab_join"], a["models"], a["settings"], HW), f

    def states(self, item):
        return [l.split()[2] for l in self.lines if l.startswith(f"::item {item} ")]

    def test_offline_then_network(self):
        self.store.put("gluetun/password", VPN_PASSWORD)
        plan, _ = self.answers_plan()
        code = L.Runner(self.host(plan), poll=1).run()
        self.assertEqual(code, 0, "\n".join(self.lines))
        self.assertEqual(self.states("media-library"), ["waiting", "installing", "done"])
        self.assertEqual(self.states("jellyfin"), ["waiting", "skipped-offline", "downloading", "installing", "done"])
        self.assertIn("::stage 0 Checking what's here", self.lines)
        self.assertTrue(any(l.startswith("::stage") and "Waiting for the internet" in l for l in self.lines))
        self.assertEqual(self.lines[-2], "::stage 100 Done")
        for l in self.lines:
            self.assertRegex(l, r"^::(stage \d+|item [a-z0-9-]+ (waiting|downloading|installing|done|failed|skipped-offline)$|note |error )")

    def test_rendered_quadlets_reference_secrets(self):
        self.store.put("gluetun/password", VPN_PASSWORD)
        plan, answers = self.answers_plan()
        L.Runner(self.host(plan), poll=1).run()
        q = Path(self.root, L.QUADLET_DIR)
        glue = (q / "gluetun.container").read_text()
        self.assertIn("Secret=bromigos-gluetun-password,type=mount,target=/run/secrets/openvpn_password", glue)
        self.assertIn("VPN_SERVICE_PROVIDER=private internet access", glue)
        self.assertIn("PublishPort=8081:8081", glue)
        qb = (q / "qbittorrent.container").read_text()
        self.assertIn("Network=gluetun.container", qb)
        self.assertNotIn("PublishPort", qb)
        sonarr = (q / "sonarr.container").read_text()
        self.assertIn("Secret=bromigos-sonarr-api-key,type=mount", sonarr)
        self.assertIn("FILE__SONARR__AUTH__APIKEY=/run/secrets/api-key", sonarr)
        self.assertNotIn("{{", sonarr)
        self.assertTrue(self.store.exists("sonarr/api-key"))
        self.assertTrue(self.store.exists("backups/restic-password"))
        self.assertTrue(self.store.exists("qbittorrent/webui-password"))
        unit = Path(self.root, "etc/systemd/system/bromigos-lab-backup.service").read_text()
        self.assertIn("LoadCredentialEncrypted=bromigos.backups.restic-password", unit)
        # nothing secret anywhere under the target, nor in the answer file
        values = {n: self.store.get(n) for n in self.store.names()}
        self.assertIn(VPN_PASSWORD, values.values())
        self.assertEqual(S.scan(self.root, values, [answers]), [])

    def test_recyclarr_and_language(self):
        plan = L.build_plan(["recyclarr", "sonarr", "radarr"], settings={"media-library": {"language": "English",
                                                                                          "dual_audio": True}}, hw=HW)
        self.net["up"] = True
        L.Runner(self.host(plan)).run()
        y = Path(self.root, L.APPS, "recyclarr/config/recyclarr.yml").read_text()
        self.assertIn("api_key: !env_var SONARR_API_KEY", y)
        self.assertIn("69aa1e159f97d860440b04cd6d590c4f", y)      # Language: Not English (Sonarr)
        self.assertIn("4b900e171accbfb172729b63323ea8ca", y)      # MULTi (Radarr)
        self.assertNotIn(self.store.get("sonarr/api-key"), y)

    def test_failure_reported_plainly_and_dependents(self):
        self.m.fail = {"podman pull ghcr.io/linuxserver/prowlarr"}
        plan = L.build_plan(["sonarr"], hw=HW)
        self.net["up"] = True
        code = L.Runner(self.host(plan)).run()
        self.assertEqual(code, 1)
        self.assertEqual(self.states("prowlarr")[-1], "failed")
        self.assertEqual(self.states("sonarr")[-1], "failed")
        err = [l for l in self.lines if l.startswith("::error prowlarr")][0]
        self.assertIn("couldn't download ghcr.io/linuxserver/prowlarr", err)
        self.assertNotIn("Traceback", "\n".join(self.lines))
        self.assertTrue(any("needs Prowlarr" in l for l in self.lines if l.startswith("::error sonarr")))

    def test_rerun_is_idempotent(self):
        self.store.put("gluetun/password", VPN_PASSWORD)
        plan, _ = self.answers_plan()
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0)
        files = {p: p.read_bytes() for p in Path(self.root).rglob("*") if p.is_file() and "provision-local" not in p.name}
        key = self.store.get("sonarr/api-key")
        self.m.calls.clear()
        self.lines.clear()
        self.assertEqual(L.Runner(self.host(plan)).run(), 0)
        self.assertEqual(self.m.ran("pacman -S"), [])
        self.assertEqual(self.m.ran("podman pull"), [])
        self.assertEqual(self.m.ran("systemctl restart"), [])
        self.assertEqual(self.store.get("sonarr/api-key"), key)
        after = {p: p.read_bytes() for p in Path(self.root).rglob("*") if p.is_file() and "provision-local" not in p.name}
        self.assertEqual(files, after)
        self.assertTrue(all(s == "done" for i in plan["items"] for s in self.states(i["id"])[1:]))

    def test_data_disks_away_nothing_is_set_up_on_the_system_disk(self):
        # a server with data disks: fstab mounts their apps subvolume at /srv/apps. Not mounted
        # (a stand-in root never is), that folder is the system disk's, and no app may start there
        Path(self.root, "etc").mkdir(exist_ok=True)
        Path(self.root, "etc/fstab").write_text(
            "# /dev/vda2\nUUID=1111  /  btrfs  rw  0 0\n"
            "UUID=2222  /srv/data  btrfs  compress=zstd,noatime,nofail  0 0\n"
            "UUID=2222  /srv/apps  btrfs  subvol=/apps,compress=zstd,noatime,nofail  0 0\n")
        Path(self.root, L.APPS).mkdir(parents=True)
        plan = L.build_plan(["uptime", "file-sync"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 1)
        for item in ("uptime", "file-sync"):
            self.assertEqual(self.states(item)[-1], "failed")
            err = next(l for l in self.lines if l.startswith(f"::error {item} "))
            self.assertIn("data disks, and they aren't mounted (/srv/apps)", err)
        self.assertEqual(list(Path(self.root, L.APPS).iterdir()), [])
        self.assertEqual(self.m.ran("podman pull") + self.m.ran("useradd") + self.m.ran("systemctl start"), [])
        self.assertFalse(Path(self.root, L.QUADLET_DIR, "uptime-kuma.container").exists())

    def test_a_folder_on_the_system_disk_when_fstab_has_no_apps_line(self):
        # no data disks: /srv/apps is the system disk's own folder, and the apps go there
        Path(self.root, "etc").mkdir(exist_ok=True)
        Path(self.root, "etc/fstab").write_text("UUID=1111  /  btrfs  rw  0 0\n# UUID=2222  /srv/apps  btrfs  subvol=/apps  0 0\n")
        plan = L.build_plan(["uptime"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        self.assertTrue(Path(self.root, L.APPS, "uptime").is_dir())

    def test_the_budget_measures_where_app_data_goes(self):
        # /srv/apps when it's there (the data disks, on a server that has them), else /srv, else /
        seen = []
        real = L.shutil.disk_usage
        L.shutil.disk_usage = lambda p: (seen.append(str(p)), real(self.root))[1]
        try:
            L.detect(self.root)
            Path(self.root, "srv").mkdir()
            L.detect(self.root)
            Path(self.root, L.APPS).mkdir()
            L.detect(self.root)
        finally:
            L.shutil.disk_usage = real
        self.assertEqual(seen, [self.root, str(Path(self.root, "srv")), str(Path(self.root, "srv/apps"))])

    def test_gives_up_waiting_with_exit_75(self):
        plan = L.build_plan(["uptime"], hw=HW)
        self.net["after"] = 999
        clock = iter(range(0, 10000, 10))
        code = L.Runner(L.Host(plan, root=self.root, run_=self.m, online=self.online, sleep=self.sleep, store=self.store,
                               emit=self.lines.append, hw=HW, hostname="box", clock=lambda: next(clock)), wait=30).run()
        self.assertEqual(code, 75)
        self.assertIn("uptime", [l for l in self.lines if l.startswith("::error network")][0])

    def test_stub_steps(self):
        calls = []
        plan = L.build_plan(["backup-target", "den-tv", "jellyfin"], hw=HW)
        self.net["up"] = True
        host = self.host(plan, steps={"backup-target": lambda h, it: calls.append(it["id"])})
        self.assertEqual(L.Runner(host).run(), 0)
        self.assertEqual(calls, ["backup-target"])
        avahi = Path(self.root, "etc/avahi/services/bromigos-media.service").read_text()
        self.assertIn("<port>8096</port>", avahi)
        self.assertIn("kind=jellyfin", avahi)

    def test_check_usenet(self):
        plan = L.build_plan(["sabnzbd"], settings={"sabnzbd": {"server": "news.example.org", "username": "me"}}, hw=HW)
        self.store.put("sabnzbd/password", "usenet-pass")
        host = self.host(plan)

        class Sock:
            def __init__(self):
                self.sent = b""
                self.answers = [b"200 welcome\r\n", b"381 more\r\n", b"281 ok\r\n"]

            def makefile(self, mode):
                outer = self

                class F:
                    def readline(self):
                        return outer.answers.pop(0)

                    def write(self, b):
                        outer.sent += b

                    def flush(self):
                        pass
                return F()

            def close(self):
                pass
        sock = Sock()
        r = L.check("sabnzbd", host, connect=lambda h, p, s: sock)
        self.assertTrue(r["ok"], r)
        self.assertIn("port 563 with SSL", r["message"])
        self.assertIn(b"AUTHINFO PASS usenet-pass", sock.sent)
        self.assertNotIn("usenet-pass", r["message"])

    def test_check_vpn(self):
        plan = L.build_plan(["gluetun"], hw=HW)
        self.assertTrue(L.check("gluetun", self.host(plan))["ok"])
        self.m.fail = {"podman healthcheck run gluetun"}
        r = L.check("gluetun", self.host(plan))
        self.assertFalse(r["ok"])
        self.assertIn("isn't connected", r["message"])

    def test_qbit_hash_format(self):
        h = L.qbit_hash("pw", salt=b"\0" * 16)
        self.assertTrue(h.startswith("@ByteArray(AAAAAAAAAAAAAAAAAAAAAA==:"))

    def test_gguf_tag(self):
        self.assertEqual(L.gguf_tag("GGUF UD-Q4_K_XL"), "UD-Q4_K_XL")
        self.assertEqual(L.gguf_tag("GGUF Q8_0"), "Q8_0")
        self.assertEqual(L.gguf_tag("FP8"), "")


class CatalogueFormatTwo(unittest.TestCase):
    """The web names, the monitoring port and the data folders are read from the catalogue
    (format 2), and a server gets exactly what the code's own tables gave it before."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.m = FakeMachine(self.root)

    def host(self, ids, hw=HW):
        plan = L.build_plan(ids, hw=hw)
        return L.Host(plan, root=self.root, run_=self.m, online=lambda: True, sleep=lambda s: None,
                      store=S.LocalStore(self.root, self.m, "box"), emit=lambda line: None, hw=hw, hostname="box",
                      tz="America/Los_Angeles")

    def test_names_ports_and_links_come_out_as_before(self):
        host = self.host(["caddy", "start-page", "monitoring", "passwords", "photos", "s3", "file-sync", "sonarr", "plex"])
        self.assertEqual(L.Runner(host, poll=1).run(), 0)
        # Sonarr and Plex have a page (web.port) and no name: Caddy and the start page leave them out, as they did
        self.assertEqual(L.web_apps(host), [
            ("monitoring", "graphs-box.local", 3005), ("start-page", "home-box.local", 3010), ("s3", "s3-box.local", 9000),
            ("photos", "photos-box.local", 2283), ("passwords", "passwords-box.local", 8222),
            ("file-sync", "sync-box.local", 8384)])
        caddy = Path(self.root, "etc/caddy/conf.d/bromigos-lab.caddy").read_text()
        self.assertIn("graphs-box.local {\n  tls internal\n  reverse_proxy 127.0.0.1:3005\n}", caddy)
        self.assertEqual(caddy.count("reverse_proxy"), 6)
        self.assertEqual(Path(self.root, "etc/bromigos/lab/mdns-names").read_text().split(),
                         ["graphs-box.local", "home-box.local", "s3-box.local", "photos-box.local", "passwords-box.local",
                          "sync-box.local"])
        grafana = Path(self.root, "etc/systemd/system/grafana.service.d/50-bromigos.conf").read_text()
        self.assertIn("Environment=GF_SERVER_HTTP_PORT=3005\n", grafana)
        vaultwarden = Path(self.root, "etc/systemd/system/vaultwarden.service.d/50-bromigos.conf").read_text()
        self.assertIn("Environment=DOMAIN=https://passwords-box.local\n", vaultwarden)
        links = json.loads(Path(self.root, "srv/apps/start-page/config/services.yaml").read_text())[0]["This server"]
        self.assertEqual({name: row["href"] for link in links for name, row in link.items()},
                         {"Monitoring": "http://box.local:3005", "S3 bucket server (RustFS)": "http://box.local:9000",
                          "Photos (Immich)": "http://box.local:2283", "Passwords (Vaultwarden)": "http://box.local:8222",
                          "File sync (Syncthing)": "http://box.local:8384"})

    def test_the_old_table_still_reads(self):
        self.assertEqual(L.WEB, PC.web_names())
        self.assertEqual(L.WEB["jellyfin"], "media")
        with self.assertRaises(AttributeError):
            L.NO_SUCH_TABLE

    def test_data_paths_are_the_folders_the_rendered_units_mount(self):
        # the catalogue's [[item.data]] against the real thing: each item's units, rendered as
        # apply renders them, mount exactly these folders of /srv/apps (where app data lives,
        # on the data disks when the server has them: docs/server.md)
        nvidia = dict(HW, gpu="nvidia", gpu_vram_gb=24)
        checked = 0
        for it in PC.load():
            if "quadlet" not in it["install"]:
                continue
            host = self.host([it["id"]], hw=nvidia)
            mounted = set()
            for f in L.template_files(it["install"]["quadlet"]):
                for line in L.render(f.read_text(), it, host).splitlines():
                    if line.startswith("Volume=/" + L.APPS + "/"):
                        mounted.add(line[len("Volume="):].split(":")[0])
            listed = {d["path"] for d in L.data_paths(it)}
            self.assertEqual(listed, mounted, it["id"])
            for path in listed:
                self.assertTrue(path.startswith(f"/srv/apps/{it['id']}/"), path)
            checked += 1
        self.assertGreater(checked, 25)
        self.assertEqual(L.data_paths(PC.by_id()["backups"]), [])
        photos = {d["path"]: d["kind"] for d in L.data_paths(PC.by_id()["photos"])}
        self.assertEqual(photos, {"/srv/apps/photos/library": "library", "/srv/apps/photos/postgres": "database",
                                  "/srv/apps/photos/model-cache": "cache"})

    def test_an_older_catalogue_is_refused_not_half_read(self):
        # format 1 has no web names: the front door would be written with no apps, and say nothing
        old = Path(self.root, "provision-catalogue.toml")
        text = Path(PC.paths()[-1]).read_text()
        self.assertIn("\nformat = 2\n", text)
        old.write_text(text.replace("\nformat = 2\n", "\nformat = 1\n"))
        with self.assertRaises(L.ProvisionError) as e:
            L.build_plan(["photos"], hw=HW, path=str(old))
        self.assertIn("format 1", str(e.exception))
        self.assertIn("Update bromigos-lab", str(e.exception))


if __name__ == "__main__":
    unittest.main()
