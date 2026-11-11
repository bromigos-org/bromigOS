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
import urllib.error
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
AUTOSCAN = "srv/apps/autoscan/config/config.yml"           # /config/config.yml in its container


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

    POOL_FSTAB = ("UUID=1111  /  btrfs  rw  0 0\nUUID=2222  /srv/data  btrfs  compress=zstd,noatime,nofail  0 0\n"
                  "UUID=2222  /srv/apps  btrfs  subvol=/apps,compress=zstd,noatime,nofail  0 0\n"
                  "UUID=2222  /srv/media  btrfs  subvol=/media,compress=zstd,noatime,nofail  0 0\n"
                  "UUID=2222  /srv/backups  btrfs  subvol=/backups,compress=zstd,noatime,nofail  0 0\n")

    def test_the_passwords_vault_is_a_folder_under_the_apps_like_every_apps(self):
        # Vaultwarden is a package whose own file puts the vault in /var/lib/vaultwarden, on the
        # system disk. The engine gives it /srv/apps/passwords, and tells the service with a file
        # read after the package's own (an Environment= line would lose to that file)
        Path(self.root, "var/lib/vaultwarden").mkdir(parents=True)             # the package makes it, empty
        plan = L.build_plan(["passwords"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        vault = Path(self.root, "srv/apps/passwords")
        self.assertTrue(vault.is_dir())
        self.assertEqual(vault.stat().st_mode & 0o777, 0o700)
        self.assertEqual(Path(self.root, "etc/bromigos/lab/passwords.env").read_text().splitlines()[-1],
                         "DATA_FOLDER=/srv/apps/passwords")
        drop = Path(self.root, "etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf").read_text()
        for line in ("RequiresMountsFor=/srv/apps/passwords", "ReadWritePaths=/srv/apps/passwords",
                     "EnvironmentFile=/etc/bromigos/lab/passwords.env"):
            self.assertIn(line + "\n", drop)
        # the files are there before the service first starts: it never starts on the package's folder
        calls = [" ".join(c) for c in self.m.calls]
        self.assertLess(calls.index("systemctl daemon-reload"), calls.index("systemctl restart vaultwarden.service"))
        self.assertFalse([l for l in self.lines if l.startswith("::note passwords")])
        # set up again from nothing known (its record gone): the same files, and the vault still under /srv/apps
        (vault / "db.sqlite3").write_text("the household's passwords\n")
        Path(self.root, L.STATE).unlink()
        self.assertEqual(L.Runner(self.host(plan)).run(), 0)
        self.assertEqual((vault / "db.sqlite3").read_text(), "the household's passwords\n")
        self.assertIn("DATA_FOLDER=/srv/apps/passwords", Path(self.root, "etc/bromigos/lab/passwords.env").read_text())

    def effective_env(self, unit):
        """What a unit's process gets, as systemd puts it together: every Environment= line, then
        every EnvironmentFile= in the order they're named, each file's lines winning over what
        came before it (systemd.exec: variables from EnvironmentFile= override Environment=).
        The package's unit first, then its drop-ins by name."""
        env, files = {}, []
        drops = sorted(Path(self.root, f"etc/systemd/system/{unit}.d").glob("*.conf"))
        for text in [f"[Service]\nEnvironmentFile=/etc/vaultwarden.env\n"] + [d.read_text() for d in drops]:
            for line in text.splitlines():
                k, _, v = line.partition("=")
                if k == "Environment":
                    env.update([v.split("=", 1)])
                elif k == "EnvironmentFile":
                    files.append(v.lstrip("-"))
        for f in files:
            for line in Path(self.root, f.lstrip("/")).read_text().splitlines():
                if line.strip() and not line.lstrip().startswith("#"):
                    env.update([line.split("=", 1)])
        return env

    def test_the_web_vault_is_on_whatever_the_packages_own_file_says(self):
        # Arch's /etc/vaultwarden.env turns the web vault off and names its own folder. Settings
        # given with Environment= lose to any file, so the engine's come from a file read after it
        Path(self.root, "etc").mkdir(exist_ok=True)
        Path(self.root, "etc/vaultwarden.env").write_text("DATA_FOLDER=/var/lib/vaultwarden\nWEB_VAULT_ENABLED=false\n"
                                                          "ROCKET_ADDRESS=0.0.0.0\n")
        plan = L.build_plan(["passwords"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        env = self.effective_env("vaultwarden.service")
        self.assertEqual({k: env.get(k) for k in ("WEB_VAULT_ENABLED", "WEB_VAULT_FOLDER", "ROCKET_ADDRESS", "ROCKET_PORT",
                                                  "DOMAIN", "DATA_FOLDER")},
                         {"WEB_VAULT_ENABLED": "true", "WEB_VAULT_FOLDER": "/usr/share/webapps/vaultwarden-web",
                          "ROCKET_ADDRESS": "127.0.0.1", "ROCKET_PORT": "8222", "DOMAIN": "https://passwords-box.local",
                          "DATA_FOLDER": "/srv/apps/passwords"})
        self.assertEqual(Path(self.root, "etc/systemd/system/vaultwarden.service.d/50-bromigos.conf").read_text(),
                         "[Service]\nEnvironmentFile=/etc/bromigos/lab/vaultwarden.env\n")

    def test_litellm_is_given_its_config_file(self):
        # its config.yaml is a file the engine writes and the container mounts read-only: never a folder
        plan = L.build_plan(["litellm", "ollama"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        conf = Path(self.root, "srv/apps/litellm/config.yaml")
        self.assertTrue(conf.is_file())
        self.assertEqual(json.loads(conf.read_text())["general_settings"], {"master_key": "os.environ/LITELLM_MASTER_KEY"})
        self.assertIn("Volume=/srv/apps/litellm/config.yaml:/app/config.yaml:ro,Z\n",
                      Path(self.root, L.QUADLET_DIR, "litellm.container").read_text())
        self.assertEqual(self.states("litellm")[-1], "done")

    def autoscan(self):
        text = Path(self.root, AUTOSCAN).read_text()
        # YAML: JSON after its comment lines
        return json.loads("\n".join(l for l in text.splitlines() if not l.startswith("#")))

    def test_autoscan_has_settings_to_start_with(self):
        # upstream exits at start without /config/config.yml
        plan = L.build_plan(["autoscan", "sonarr", "radarr", "jellyfin"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        conf = Path(self.root, AUTOSCAN)
        self.assertEqual(conf.stat().st_mode & 0o777, 0o600)
        self.assertIn("Volume=/srv/apps/autoscan/config:/config:Z\n", Path(self.root, L.QUADLET_DIR, "autoscan.container").read_text())
        # Jellyfin's key isn't known yet: no target, so Autoscan starts and waits, and the note says the step
        self.assertEqual(self.autoscan(), {"port": 3030, "triggers": {"manual": {"priority": 0},
                                                                      "sonarr": [{"name": "sonarr", "priority": 2}],
                                                                      "radarr": [{"name": "radarr", "priority": 2}]}})
        (note,) = [l for l in self.lines if l.startswith("::note autoscan ")]
        self.assertIn("One step for you, then run this again: Jellyfin: finish its first-run page, make an API key "
                      "(Dashboard › API Keys) and save it with bromigos lab secrets set jellyfin/api-key.", note)
        # with the key, the next run points it at Jellyfin
        self.store.put("jellyfin/api-key", "0123456789abcdef0123456789abcdef")
        Path(self.root, L.STATE).unlink()
        self.lines.clear()
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        self.assertEqual(self.autoscan()["targets"], {"jellyfin": [{"url": "http://jellyfin:8096",
                                                                    "token": "0123456789abcdef0123456789abcdef"}]})
        self.assertFalse([l for l in self.lines if l.startswith("::note autoscan ")])
        # a file someone changed is theirs: never written over
        conf.write_text(conf.read_text().replace('"port": 3030', '"port": 3031'))
        Path(self.root, L.STATE).unlink()
        self.assertEqual(L.Runner(self.host(plan)).run(), 0)
        self.assertEqual(self.autoscan()["port"], 3031)

    def test_sonarr_and_radarr_are_connected_to_autoscan_by_the_engine(self):
        # with all three installed nobody has a hand step: where the engine adds Sonarr's and
        # Radarr's download clients (it has their API keys), it adds their connection to Autoscan
        plan = L.build_plan(["autoscan", "sonarr", "radarr", "lidarr", "jellyfin"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        host = self.host(plan)
        calls, there = [], {8989: [], 7878: [{"name": "Discord"}], 8686: []}

        def http(method, url, body=None, headers=None):
            calls.append((method, url, body, headers))
            port, what = int(url.split(":")[2].split("/")[0]), url.split("/api/")[1].split("/", 1)[1].split("?")[0]
            if method == "POST" and what == "notification":
                there[port].append(body)
            return {"downloadclient": [], "rootfolder": [{"path": p} for p in ("/media/tv", "/media/movies", "/media/music")],
                    "notification": there[port]}[what] if method == "GET" else {}

        self.assertEqual(L.wire_media(host, http=http), ["sonarr: Autoscan", "radarr: Autoscan"])
        posts = {url: (body, headers) for method, url, body, headers in calls if method == "POST"}
        self.assertEqual(sorted(posts), ["http://127.0.0.1:7878/api/v3/notification?forceSave=true",
                                         "http://127.0.0.1:8989/api/v3/notification?forceSave=true"])
        body, headers = posts["http://127.0.0.1:8989/api/v3/notification?forceSave=true"]
        self.assertEqual(headers, {"X-Api-Key": self.store.get("sonarr/api-key")})
        self.assertEqual(body, {"name": "Autoscan", "implementation": "Webhook", "configContract": "WebhookSettings",
                                "onDownload": True, "onUpgrade": True, "onRename": True, "onSeriesDelete": True,
                                "onEpisodeFileDelete": True, "onEpisodeFileDeleteForUpgrade": True, "tags": [],
                                "fields": [{"name": "url", "value": "http://autoscan:3030/triggers/sonarr"},
                                           {"name": "method", "value": 1}]})
        radarr = posts["http://127.0.0.1:7878/api/v3/notification?forceSave=true"][0]
        self.assertEqual((radarr["fields"][0]["value"], radarr["onMovieDelete"], radarr["onMovieFileDelete"], "onSeriesDelete" in radarr),
                         ("http://autoscan:3030/triggers/radarr", True, True, False))
        self.assertEqual(there[7878][0], {"name": "Discord"}, "a connection of yours is left as it is")
        # each trigger it calls is one Autoscan's own settings have, by the same name
        triggers = self.autoscan()["triggers"]
        for app in ("sonarr", "radarr"):
            self.assertEqual(triggers[app], [{"name": app, "priority": 2}])
        # again: it is there by name, and nothing is added twice. Lidarr has no trigger in Autoscan: never asked
        calls.clear()
        self.assertEqual(L.wire_media(host, http=http), [])
        self.assertEqual([c for c in calls if c[0] == "POST"], [])
        self.assertFalse([c for c in calls if ":8686/" in c[1] and "notification" in c[1]])
        # without Autoscan nobody's connections are looked at
        calls.clear()
        L.wire_media(self.host(L.build_plan(["sonarr", "radarr", "jellyfin"], hw=HW)), http=http)
        self.assertFalse([c for c in calls if "notification" in c[1]])

    def test_an_app_that_does_not_answer_yet_keeps_the_note_and_is_connected_on_the_next_run(self):
        plan = L.build_plan(["autoscan", "sonarr", "jellyfin"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        self.lines.clear()

        def down(method, url, body=None, headers=None):
            raise urllib.error.URLError("connection refused")

        self.assertEqual(L.wire_media(self.host(plan), http=down), [])
        self.assertEqual(self.lines, ["::note sonarr Sonarr (shows) didn't answer yet; its download clients and its connection "
                                      "to Autoscan are added on the next run."])

    def test_autoscan_tells_plex_once_it_is_signed_in(self):
        prefs = Path(self.root, "srv/apps/plex/config/Library/Application Support/Plex Media Server/Preferences.xml")
        prefs.parent.mkdir(parents=True)
        prefs.write_text('<?xml version="1.0" encoding="utf-8"?>\n<Preferences MachineIdentifier="x" PlexOnlineToken="plex-token-123456"/>\n')
        plan = L.build_plan(["autoscan", "sonarr", "plex"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        self.assertEqual(self.autoscan()["targets"], {"plex": [{"url": "http://host.containers.internal:32400",  # privacy: allow (Podman's name for the host)
                                                                "token": "plex-token-123456"}]})
        self.assertFalse([l for l in self.lines if l.startswith("::note autoscan ")])

    def test_folders_get_the_mode_they_are_made_with(self):
        # a repository root's alone, the SFTP jail root's and open, an app's own folder 0750, whatever the umask
        Path(self.root, "srv/apps/photos/postgres").mkdir(parents=True)
        os.chmod(Path(self.root, "srv/apps/photos/postgres"), 0o700)                # postgres's own: kept
        old = os.umask(0o077)
        try:
            plan = L.build_plan(["backups", "backup-target", "photos"], hw=HW)
            self.net["up"] = True
            self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        finally:
            os.umask(old)
        mode = {rel: Path(self.root, rel).stat().st_mode & 0o777 for rel in
                ("srv/backups/restic", "srv/backups", "srv/backups/data", "srv/apps/photos", "srv/apps/photos/postgres",
                 "srv/apps/photos/library")}
        self.assertEqual(mode, {"srv/backups/restic": 0o700, "srv/backups": 0o755, "srv/backups/data": 0o700,
                                "srv/apps/photos": 0o750, "srv/apps/photos/postgres": 0o700, "srv/apps/photos/library": 0o755})

    def hooks(self):
        import tomllib
        d = Path(self.root, "etc/bromigos/backup-databases.d")
        return {p.stem: tomllib.loads(p.read_text()) for p in sorted(d.iterdir())} if d.is_dir() else {}

    def test_the_apps_with_a_database_have_it_made_safe_before_each_backup(self):
        # a hook each (labbackup.py, copy_databases): the vault, wherever it is, and Paperless's
        # SQLite. Immich's postgres can't be copied as files: Immich dumps it itself, and its hook
        # names those dumps, which must be recent
        Path(self.root, "var/lib/vaultwarden").mkdir(parents=True)
        plan = L.build_plan(["passwords", "documents", "photos", "backups"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        self.assertEqual(self.hooks(), {
            "passwords": {"what": "passwords (Vaultwarden)",
                          "sqlite": ["/srv/apps/passwords/db.sqlite3", "/var/lib/vaultwarden/db.sqlite3"]},
            "documents": {"what": "documents (Paperless-ngx)", "sqlite": ["/srv/apps/documents/data/db.sqlite3"]},
            "photos": {"what": "photos (Immich)", "own": ["/srv/apps/photos/library/backups/*"], "own_days": 3}})
        text = Path(self.root, "etc/bromigos/backup-databases.d/photos.toml").read_text()
        self.assertIn("# Immich's database is PostgreSQL", text, "the hook's comment says why nothing is copied")
        self.assertTrue(all(len(line) <= 101 for line in text.splitlines() if line.startswith("#")), text)
        # the lab's own backup is one job, which names the apps' folder by itself: on a server with
        # data disks it is a mount of its own, which --one-file-system never crosses into
        unit = Path(self.root, "etc/systemd/system/bromigos-lab-backup.service").read_text()
        self.assertIn("ExecStart=/usr/lib/bromigos/bin/bromigos-lab backups job /etc /srv /srv/apps /var/lib/bromigos "
                      "/var/lib/vaultwarden\n", unit)
        self.assertEqual(unit.count("Exec"), 1, "nothing of bromigos-core's is run beside it")

    def test_every_catalogue_app_that_keeps_a_database_has_a_hook(self):
        # the catalogue says which items keep a database ([[item.data]] kind = "database"); each
        # one has an entry, and every path in it is inside a folder the item's recipe mounts
        cat = PC.by_id()
        keeps = {i for i, it in cat.items() if any(d["kind"] == "database" for d in it["data"])}
        self.assertEqual(keeps - set(L.DATABASES), set(), "an app with a database and no hook: add it to DATABASES")
        self.assertEqual(set(L.DATABASES) - set(cat), set())
        for i, d in L.DATABASES.items():
            folders = [r["path"] for r in L.data_paths(cat[i])] or ["/srv/apps/passwords", "/var/lib/vaultwarden"]
            paths = d.get("sqlite", []) + d.get("own", [])
            self.assertTrue(paths, i)
            for p in paths:
                self.assertTrue(any(p.startswith(f.rstrip("/") + "/") for f in folders), f"{i}: {p} isn't in {folders}")
            self.assertTrue(L.database_what(cat[i]), i)
        self.assertEqual((L.database_what(cat["sonarr"]), L.database_what(cat["jellyfin"])), ("shows (Sonarr)", "films and shows (Jellyfin)"))

    def test_a_server_set_up_before_the_hooks_gets_them_at_its_next_apply(self):
        plan = L.build_plan(["navidrome", "sonarr", "jellyfin"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        want = {"navidrome": ["/srv/apps/navidrome/data/navidrome.db"], "sonarr": ["/srv/apps/sonarr/config/*.db"],
                "jellyfin": ["/srv/apps/jellyfin/config/data/*.db"], "prowlarr": ["/srv/apps/prowlarr/config/*.db"]}
        self.assertEqual({k: v["sqlite"] for k, v in self.hooks().items()}, want)
        # as an engine from before the hooks left it: every app installed and on record, no hook
        d = Path(self.root, "etc/bromigos/backup-databases.d")
        for p in d.iterdir():
            p.unlink()
        (d / "mine.toml").write_text('what = "my own app"\nsqlite = ["/srv/mine/data.db"]\n')    # a person's own hook
        installs = len(self.m.ran("systemctl restart")) + len(self.m.ran("systemctl start"))
        self.assertEqual(L.Runner(self.host(plan)).run(), 0)
        self.assertEqual(len(self.m.ran("systemctl restart")) + len(self.m.ran("systemctl start")), installs, "nothing was set up again")
        self.assertEqual({k: v["sqlite"] for k, v in self.hooks().items()}, dict(want, mine=["/srv/mine/data.db"]))
        # an app that left (bromigos lab apps remove takes it off the record): its hook goes, a person's own stays
        state = Path(self.root, L.STATE)
        rec = json.loads(state.read_text())
        del rec["items"]["navidrome"]
        state.write_text(json.dumps(rec))
        self.assertEqual(L.Runner(self.host(L.build_plan(["sonarr", "jellyfin"], hw=HW))).run(), 0)
        self.assertEqual(sorted(self.hooks()), ["jellyfin", "mine", "prowlarr", "sonarr"])

    def test_a_container_with_an_account_of_its_own_owns_its_data_folder(self):
        # Navidrome and slskd run as the media account (User= in their units). Their data folder
        # was root's, so the app couldn't make its database in it
        plan = L.build_plan(["navidrome", "slskd", "sonarr"], hw=HW)
        self.net["up"] = True
        made = []
        mkdir = L.Host.mkdir

        def recorded(host, rel, mode=None, owner=None):
            made.append((str(rel).lstrip("/"), owner))
            return mkdir(host, rel, mode, owner)

        with mock.patch.object(L.Host, "mkdir", recorded):
            self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        owners = dict(made)
        self.assertIn("User=1000:1000\n", Path(self.root, L.QUADLET_DIR, "navidrome.container").read_text())
        self.assertEqual((owners["srv/apps/navidrome/data"], owners["srv/apps/slskd/app"]), ("1000:1000", "1000:1000"))
        self.assertIsNone(owners["srv/apps/sonarr/config"], "an image that drops to its own account itself is left as it was")

    def test_a_recipe_whose_revision_was_raised_is_set_up_again(self):
        # what the engine writes for an item changed (the lab's backup unit, the vault's settings
        # file, Autoscan's config.yml): the catalogue's `version` is in the fingerprint, so a
        # server that has the item gets the change at its next apply. An item nobody revised
        # keeps the fingerprint it had
        cat = PC.by_id()
        host = self.host(L.build_plan(["passwords", "backups", "photos"], hw=HW))
        for i in ("passwords", "backups", "autoscan", "navidrome", "slskd"):
            self.assertEqual(cat[i]["version"], 2, i)
            self.assertNotEqual(L.fingerprint(cat[i], host), L.fingerprint(dict(cat[i], version=1), host), i)
        self.assertEqual(cat["photos"]["version"], 1)
        self.assertEqual(L.fingerprint(cat["photos"], host), L.fingerprint({k: v for k, v in cat["photos"].items() if k != "version"}, host))
        # the lab's backup unit as #112 left it, on a machine the engine set up then
        self.net["up"] = True
        self.assertEqual(L.Runner(host).run(), 0, "\n".join(self.lines))
        unit = Path(self.root, "etc/systemd/system/bromigos-lab-backup.service")
        state = Path(self.root, L.STATE)
        rec = json.loads(state.read_text())
        rec["items"]["backups"]["fingerprint"] = L.fingerprint(dict(cat["backups"], version=1), host)
        state.write_text(json.dumps(rec))
        unit.write_text(unit.read_text().replace("backups job", "backups holds"))
        self.assertEqual(L.Runner(self.host(L.build_plan(["passwords", "backups", "photos"], hw=HW))).run(), 0)
        self.assertIn("bromigos-lab backups job /etc /srv /srv/apps", unit.read_text())

    def test_a_vault_already_in_the_packages_folder_stays_there_and_goes_on_working(self):
        # a server set up before the vault had a folder under /srv/apps: pointing the service at an
        # empty folder would show the household no passwords. It is left as it is, and the one
        # command that moves it safely is named on a server with data disks
        old = Path(self.root, "var/lib/vaultwarden")
        old.mkdir(parents=True)
        (old / "db.sqlite3").write_text("the household's passwords\n")
        plan = L.build_plan(["passwords"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        self.assertFalse(Path(self.root, "etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf").exists())
        self.assertFalse(Path(self.root, "etc/bromigos/lab/passwords.env").exists())
        self.assertFalse(Path(self.root, "srv/apps/passwords").exists())
        self.assertEqual((old / "db.sqlite3").read_text(), "the household's passwords\n")
        self.assertFalse([l for l in self.lines if l.startswith("::note passwords")])       # no data disks: nothing to do
        Path(self.root, "etc").mkdir(exist_ok=True)
        Path(self.root, "etc/fstab").write_text(self.POOL_FSTAB.replace("UUID=2222  /srv/apps", "# UUID=2222  /srv/apps"))
        self.lines.clear()
        Path(self.root, L.STATE).unlink()                       # done once already: it runs again only when something changed
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        (note,) = [l for l in self.lines if l.startswith("::note passwords")]
        self.assertIn("/var/lib/vaultwarden, on the system disk", note)
        self.assertIn("sudo bromigos lab app-data move", note)
        self.assertFalse(Path(self.root, "etc/bromigos/lab/passwords.env").exists())

    def test_data_disks_away_no_vault_library_or_backup_place_is_made_on_the_system_disk(self):
        # fstab mounts the data disks' subvolumes at /srv/apps, /srv/media and /srv/backups. Not
        # mounted (a stand-in root never is), each is a folder on the system disk that takes nothing
        Path(self.root, "etc").mkdir(exist_ok=True)
        Path(self.root, "etc/fstab").write_text(self.POOL_FSTAB)
        for d in ("srv/apps", "srv/media", "srv/backups"):
            Path(self.root, d).mkdir(parents=True)
        plan = L.build_plan(["passwords", "media-library", "backup-target"], hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 1)
        for item, folder in (("passwords", "/srv/apps"), ("media-library", "/srv/media"), ("backup-target", "/srv/backups")):
            self.assertEqual(self.states(item)[-1], "failed", item)
            err = next(l for l in self.lines if l.startswith(f"::error {item} "))
            self.assertIn(f"on its data disks, and they aren't mounted ({folder})", err)
        for d in ("srv/apps", "srv/media", "srv/backups"):
            self.assertEqual(list(Path(self.root, d).iterdir()), [], d)
        self.assertEqual(self.m.ran("pacman -S --needed --noconfirm vaultwarden") + self.m.ran("useradd")
                         + self.m.ran("systemctl restart vaultwarden"), [])
        self.assertFalse(Path(self.root, "etc/bromigos/lab/passwords.env").exists())

    def test_a_media_library_on_a_nas_takes_the_place_of_the_data_disks_folder(self):
        # the installer mounts the data disks' media subvolume at /srv/media. A library on a NAS
        # share is mounted there instead: the data disks' line makes way, and the share's unit stands
        Path(self.root, "etc").mkdir(exist_ok=True)
        Path(self.root, "etc/fstab").write_text(self.POOL_FSTAB)
        plan = L.build_plan(["media-library"], settings={"media-library": {"where": "nfs", "share": "nas.example:/volume1/media"}}, hw=HW)
        self.net["up"] = True
        self.assertEqual(L.Runner(self.host(plan)).run(), 0, "\n".join(self.lines))
        fstab = Path(self.root, "etc/fstab").read_text()
        self.assertNotRegex(fstab, r"(?m)^UUID=2222\s+/srv/media\s")
        self.assertRegex(fstab, r"(?m)^# .*UUID=2222  /srv/media  btrfs")          # kept as a comment: nothing is lost from view
        self.assertRegex(fstab, r"(?m)^UUID=2222\s+/srv/apps\s")
        self.assertRegex(fstab, r"(?m)^UUID=2222\s+/srv/backups\s")
        self.assertIn("What=nas.example:/volume1/media", Path(self.root, "etc/systemd/system/srv-media.mount").read_text())
        self.assertTrue(Path(self.root, "srv/media/movies").is_dir())

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
            ("monitoring", "graphs-box.local", 3005), ("start-page", "home-box.local", 3010), ("s3", "s3-box.local", 9001),
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
        self.assertIn("reverse_proxy 127.0.0.1:9001\n", caddy[caddy.index("s3-box.local {"):], "RustFS's console, not its API")
        vaultwarden = Path(self.root, "etc/bromigos/lab/vaultwarden.env").read_text()
        self.assertIn("DOMAIN=https://passwords-box.local\n", vaultwarden)
        links = json.loads(Path(self.root, "srv/apps/start-page/config/services.yaml").read_text())[0]["This server"]
        self.assertEqual({name: row["href"] for link in links for name, row in link.items()},
                         {"Monitoring": "http://box.local:3005", "S3 bucket server (RustFS)": "http://box.local:9001",
                          "Photos (Immich)": "http://box.local:2283", "Passwords (Vaultwarden)": "http://box.local:8222",
                          "File sync (Syncthing)": "http://box.local:8384"})

    def test_the_lab_board_has_its_site_and_its_names(self):
        host = self.host(["photos", "board"])
        self.assertEqual(L.Runner(host, poll=1).run(), 0)
        site = Path(self.root, "etc/caddy/conf.d/bromigos-board.caddy").read_text()
        self.assertIn("box.local, home-box.local {\n  tls internal\n  import /usr/share/bromigos-board/caddy/site.caddy\n}",
                      site)
        self.assertNotIn("home-box.local", Path(self.root, "etc/caddy/conf.d/bromigos-lab.caddy").read_text())
        self.assertEqual(Path(self.root, "etc/bromigos/lab/mdns-names").read_text().split(),
                         ["photos-box.local", "home-box.local"])
        calls = [" ".join(c) for c in self.m.calls]
        self.assertIn("pacman -S --needed --noconfirm bromigos-board", calls)
        for u in ("bromigos-board.socket", "bromigos-board-snapshot.path", "bromigos-board-act.path"):
            self.assertIn(f"systemctl enable {u}", calls)
        # the site is written once the package it imports is there, then Caddy loads it
        self.assertLess(calls.index("pacman -S --needed --noconfirm bromigos-board"),
                        calls.index("systemctl reload-or-restart caddy.service"))

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
