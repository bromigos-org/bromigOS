"""`bromigos lab apps` (labapps.py): the tiles from a stand-in machine (the service manager, the
health check, cgroups, data folders), the desired state, add and remove through the engine with
the Host stand-ins, keeping or deleting data, reverse dependencies, the jobs' command lines, the
budget with what's installed, and the four `bromigos lab` stubs. Nothing here starts a real
unit or container: every command goes to provfake.FakeMachine."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from bromigos_homelab import labapps as A, localprovision as L, provcatalog as PC, secretstore as S
from provfake import FakeMachine

HERE = Path(__file__).parent
REPO = HERE.parents[1]
LAB = REPO / "homelab/bin/bromigos-lab"
FIXTURE = HERE / "fixtures/apps-integration"
HW = {"cpu": 4, "ram_gb": 16, "disk_gb": 512, "gpu": False, "gpu_vram_gb": 0, "gpu_name": ""}
NOW = 1794290000000                       # ms; the units came up at FakeMachine.since (1794200000 s)
# the tile contract (the Lab board's DESIGN, §3): exactly these keys, no more
TILE_KEYS = {"id", "job", "app", "holo", "group", "installed", "version", "recipe", "household", "state", "state_word",
             "since", "reading", "open", "update", "measured", "requires", "can", "needed_by"}
PHOTOS_UNITS = ["immich-database.service", "immich-ml.service", "immich-server.service", "immich-valkey.service"]


def setUpModule():
    global _SHARE
    _SHARE = mock.patch.object(PC, "SHARE", "/nonexistent")     # the checkout's catalogue, never an installed one
    _SHARE.start()
    PC._cache.clear()


def tearDownModule():
    _SHARE.stop()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.fm = FakeMachine(self.root)
        self.answers = {}                  # url → status the stand-in's apps answer with
        self.clock = [NOW]
        self.started = []                  # what Machine.start was handed (a job's start, journalctl)
        self.lines = []
        self.store = S.LocalStore(self.root, self.fm, "myserver")
        self.m = self.machine()

    def machine(self, **kw):
        def sleep(s):
            self.clock[0] += int(s * 1000)

        def start(argv):
            self.started.append(argv)
            return 0
        args = dict(root=self.root, run=self.fm, hostname="myserver", http=lambda url, timeout: self.answers.get(url),
                    clock=lambda: self.clock[0], sleep=sleep, euid=1000, hw=HW, start=start,
                    environ={"BROMIGOS_ACTIVITY_CMD": "/usr/lib/bromigos/bin/bromigos-activity"})
        args.update(kw)
        return A.Machine(**args)

    def host_kw(self):
        return {"store": self.store, "online": lambda: True, "sleep": lambda s: None, "tz": "UTC"}

    def write(self, rel, text):
        p = Path(self.root, rel.lstrip("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def desire(self, apps, **extra):
        d = A._blank()
        d.update(apps=apps, **extra)
        A.save_desired(self.m, d)

    def record(self, **items):
        self.write(L.STATE, json.dumps({"items": items}))

    def run_main(self, argv, m=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = A.main(argv, ["/usr/lib/bromigos/bin/bromigos-lab", "apps"], m or self.m)
        return code, out.getvalue(), err.getvalue()

    def tiles(self):
        code, out, _ = self.run_main(["list", "--json"])
        return code, {t["id"]: t for t in json.loads(out)}


class Tiles(Base):
    """The tile JSON, from the stand-in machine: what the board reads."""

    def server(self):
        """caddy, Photos and Passwords installed and running; Photos answers."""
        self.desire(["caddy", "photos", "passwords"])
        self.record(caddy={"state": "done", "recipe": 1}, passwords={"state": "done", "recipe": 1},
                    photos={"state": "done", "recipe": 1, "app_version": "v3.3.5"})
        self.fm.installed |= {"caddy", "vaultwarden", "vaultwarden-web"}
        self.fm.active |= set(PHOTOS_UNITS) | {"caddy.service", "vaultwarden.service"}
        for n, u in enumerate(PHOTOS_UNITS):
            self.write(f"sys/fs/cgroup/system.slice/{u}/memory.current", f"{(n + 1) * 100_000_000}\n")
        self.write("sys/fs/cgroup/system.slice/caddy.service/memory.current", "30000000\n")
        self.write("sys/fs/cgroup/system.slice/vaultwarden.service/memory.current", "20000000\n")
        lib = Path(self.root, "srv/apps/photos/library")
        lib.mkdir(parents=True)
        (lib / "IMG_0001.jpg").write_bytes(b"x" * 300_000)
        Path(self.root, "srv/apps/photos/postgres").mkdir()
        (Path(self.root, "srv/apps/photos/postgres") / "base").write_bytes(b"y" * 50_000)
        self.answers["http://127.0.0.1:2283/api/server/ping"] = 200

    def test_every_tile_has_exactly_the_contracts_keys(self):
        self.server()
        code, tiles = self.tiles()
        self.assertEqual(code, 0)
        self.assertEqual(len(tiles), len(PC.load()))
        for t in tiles.values():
            self.assertEqual(set(t), TILE_KEYS, t["id"])
            self.assertIsNone(t["reading"], "no adapter feeds a reading yet: never a made-up one")
            self.assertIsNone(t["update"], "there's no update path yet")
            self.assertIsNone(t["household"], "the catalogue has no household key yet")

    def test_a_running_app_that_answers(self):
        self.server()
        _, tiles = self.tiles()
        p = tiles["photos"]
        self.assertEqual((p["job"], p["app"], p["holo"], p["group"]), ("Photos", "Immich", "photos", "home"))
        self.assertEqual((p["installed"], p["state"], p["state_word"]), (True, "ok", "Running"))
        self.assertEqual(p["since"], 1794200000 * 1000)
        self.assertEqual((p["version"], p["recipe"]), ("v3.3.5", 1))
        self.assertEqual(p["open"], {"url": "https://photos-myserver.local", "port": 2283})
        self.assertEqual(p["measured"]["ram_bytes"], 1_000_000_000)           # its four units' cgroups
        self.assertGreaterEqual(p["measured"]["disk_bytes"], 350_000)           # library + postgres (+ blocks)
        self.assertLess(p["measured"]["disk_bytes"], 1_000_000)
        self.assertEqual(p["requires"], {"cpu": 2, "ram_gb": 4, "disk_gb": 20})
        self.assertEqual(p["can"], ["open", "restart", "logs", "remove"])
        self.assertEqual(p["needed_by"], [])

    def test_what_others_need_cant_be_removed_and_a_package_says_its_version(self):
        self.server()
        _, tiles = self.tiles()
        self.assertEqual(tiles["caddy"]["needed_by"], ["passwords"])
        self.assertNotIn("remove", tiles["caddy"]["can"])
        pw = tiles["passwords"]
        self.assertEqual(pw["version"], "1-1")                                  # pacman -Q vaultwarden
        self.assertEqual(pw["measured"], {"ram_bytes": 20_000_000, "disk_bytes": None})   # no [[item.data]]: not measured
        self.assertIn("remove", pw["can"])

    def test_an_app_not_installed(self):
        self.server()
        _, tiles = self.tiles()
        j = tiles["jellyfin"]
        self.assertFalse(j["installed"])
        for k in ("state", "state_word", "since", "open", "measured"):
            self.assertIsNone(j[k], k)
        self.assertEqual(j["can"], ["add"])
        self.assertEqual(j["version"], "12.4ubu2604-ls57")                      # the tag the recipe pins
        self.assertIsNone(tiles["pinchflat"]["version"], "\"latest\" is no version")

    def test_states_from_the_service_manager_and_the_check(self):
        self.server()
        self.answers.clear()                                                    # Photos stops answering
        _, tiles = self.tiles()
        self.assertEqual((tiles["photos"]["state"], tiles["photos"]["state_word"]), ("degraded", "Degraded"))
        self.clock[0] = 1794200000 * 1000 + 10_000                              # ten seconds after it came up
        _, tiles = self.tiles()
        self.assertEqual(tiles["photos"]["state"], "starting")
        self.fm.active.discard("immich-ml.service")
        self.answers["http://127.0.0.1:2283/api/server/ping"] = 200
        _, tiles = self.tiles()
        self.assertEqual(tiles["photos"]["state"], "degraded", "one of its four units is down")
        self.fm.active -= set(PHOTOS_UNITS)
        self.fm.units["immich-server.service"] = {"ActiveState": "failed", "SubState": "failed"}
        code, tiles = self.tiles()
        self.assertEqual((tiles["photos"]["state"], tiles["photos"]["state_word"]), ("down", "Down"))
        self.assertIsNone(tiles["photos"]["since"])
        self.assertEqual(code, 1, "an app that's down is a problem found")
        self.fm.units["immich-server.service"] = {"ActiveState": "activating", "SubState": "start"}
        self.fm.active |= {"immich-database.service", "immich-valkey.service"}
        _, tiles = self.tiles()
        self.assertEqual(tiles["photos"]["state"], "starting")

    def test_no_answer_from_the_service_manager_is_unknown_and_exit_4(self):
        self.server()
        self.fm.fail.add("systemctl show")
        code, tiles = self.tiles()
        self.assertEqual(code, 4)
        self.assertEqual({tiles[i]["state"] for i in ("caddy", "photos", "passwords")}, {"unknown"})
        self.assertEqual(tiles["photos"]["measured"]["ram_bytes"], None)

    def test_a_job_running_for_an_app_shows_on_its_tile(self):
        self.server()
        with mock.patch.object(A, "running_jobs", return_value={"photos": "app.install"}):
            _, tiles = self.tiles()
        self.assertEqual((tiles["photos"]["state"], tiles["photos"]["state_word"]), ("starting", "Starting"))

    def test_a_folder_that_cant_be_read_is_no_number(self):
        self.server()
        locked = Path(self.root, "srv/apps/photos/postgres")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        if os.geteuid() == 0:
            self.skipTest("root reads everything")
        self.assertIsNone(A.tree_bytes(str(Path(self.root, "srv/apps/photos"))))
        _, tiles = self.tiles()
        self.assertIsNone(tiles["photos"]["measured"]["disk_bytes"], "a part counted as the whole would be made up")

    def test_sizes_are_kept_ten_minutes_then_walked_again(self):
        self.server()
        _, tiles = self.tiles()
        before = tiles["photos"]["measured"]["disk_bytes"]
        cache = json.loads(Path(self.root, A.MEASURED).read_text())
        self.assertIn("/srv/apps/photos/library", cache)
        (Path(self.root, "srv/apps/photos/library") / "IMG_0002.jpg").write_bytes(b"x" * 400_000)
        _, tiles = self.tiles()
        self.assertEqual(tiles["photos"]["measured"]["disk_bytes"], before)
        self.clock[0] += A.MEASURE_MAX_AGE_MS
        _, tiles = self.tiles()
        self.assertGreater(tiles["photos"]["measured"]["disk_bytes"], before + 390_000)

    def test_without_caddy_a_page_is_on_its_port(self):
        self.desire(["photos"])
        _, tiles = self.tiles()
        self.assertEqual(tiles["photos"]["open"], {"url": "http://myserver.local:2283", "port": 2283})

    def test_an_item_with_no_service_is_set_up(self):
        self.desire(["media-library"])
        self.record(**{"media-library": {"state": "done"}})
        _, tiles = self.tiles()
        self.assertEqual((tiles["media-library"]["state"], tiles["media-library"]["state_word"]), ("ok", "Set up"))
        self.assertEqual(tiles["media-library"]["can"], [])

    def test_the_plain_list(self):
        self.server()
        code, out, _ = self.run_main(["list"])
        self.assertEqual(code, 0)
        self.assertIn("Apps on myserver: 3, all running", out)
        self.assertIn("Photos · Immich v3.3.5", out)
        self.assertIn("https://photos-myserver.local", out)
        self.assertIn("more can be added: bromigos lab apps list --all", out)
        code, out, _ = self.run_main(["list", "--all"])
        self.assertIn("jellyfin", out)

    def test_show(self):
        self.server()
        code, out, _ = self.run_main(["show", "photos", "--json"])
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["app"]["state"], "ok")
        self.assertEqual([u["unit"] for u in doc["units"]], PHOTOS_UNITS)
        self.assertEqual(doc["health"]["how"], "GET http://127.0.0.1:2283/api/server/ping")
        self.assertTrue(doc["health"]["ok"])
        self.assertEqual(doc["keys"], ["photos/db-password"])
        self.assertEqual([d["path"] for d in doc["data"]], ["/srv/apps/photos/library", "/srv/apps/photos/postgres",
                                                           "/srv/apps/photos/model-cache"])
        self.assertEqual(doc["data"][2]["bytes"], 0)
        self.assertIsNone(doc["snapshots"])
        code, out, _ = self.run_main(["show", "photos"])
        self.assertIn("Answers: yes", out)
        code, _, err = self.run_main(["show", "nope"])
        self.assertEqual(code, 3)
        self.assertIn("no app named 'nope'", err)


class DesiredState(Base):
    ANSWERS = """[server]
roles = ["home-services"]
lab = "none"
provision = ["passwords", "photos", "gone-from-the-catalogue"]

[server.settings.gluetun]
provider = "pia"
password = { secret = "local:gluetun/password" }
"""

    def test_seeded_once_from_the_answers_and_the_engines_record(self):
        self.write(L.ANSWERS, self.ANSWERS)
        self.record(uptime={"state": "done"}, jellyfin={"state": "failed"})
        d = A.desired(self.m)
        self.assertEqual(d["apps"], ["caddy", "photos", "passwords", "uptime"])  # caddy: Passwords needs it
        self.assertEqual(d["seeded_from"], L.ANSWERS)
        self.assertEqual(d["settings"]["gluetun"]["password"], {"secret": "local:gluetun/password"})
        self.assertFalse(Path(self.root, A.DESIRED).exists(), "reading never writes")
        A.desired(self.m, write=True)
        text = Path(self.root, A.DESIRED).read_text()
        self.assertIn('apps = ["caddy", "photos", "passwords", "uptime"]', text)
        self.assertIn('password = { secret = "local:gluetun/password" }', text)
        self.write(L.ANSWERS, self.ANSWERS.replace('"photos", ', ""))
        self.assertIn("photos", A.desired(self.m)["apps"], "seeded once: the file is what counts after")

    def test_round_trip(self):
        d = A._blank()
        d.update(apps=["uptime", "photos"], roles=["media"], models=["m1"],
                 settings={"sabnzbd": {"server": "news.example.org", "port": 563, "ssl": True, "pw": {"secret": "local:x/y"}}})
        A.save_desired(self.m, d)
        back = A.desired(self.m)
        self.assertEqual(back["apps"], ["photos", "uptime"])                    # the catalogue's order
        self.assertEqual(back["settings"], d["settings"])
        self.assertEqual(back["models"], ["m1"])

    def test_a_broken_file_is_said_not_overwritten(self):
        self.write(A.DESIRED, "apps = [\n")
        code, _, err = self.run_main(["list"])
        self.assertEqual(code, 4)
        self.assertIn("can't be read", err)
        self.assertEqual(Path(self.root, A.DESIRED).read_text(), "apps = [\n")

    def test_what_provision_applies_is_added(self):
        self.desire(["photos"])
        with mock.patch.object(L, "ROOT", self.root):
            A.note_applied(["uptime", "caddy"])
        self.assertEqual(A.desired(self.m)["apps"], ["caddy", "photos", "uptime"])


class AddAndRemove(Base):
    """Through the engine (localprovision's Runner) with the Host stand-ins."""

    def add(self, ids, **kw):
        self.lines = []
        return A.do_add(self.m, ids, kw.get("sets", []), emit=self.lines.append, host_kw=self.host_kw())

    def remove(self, i, delete=False):
        self.lines = []
        return A.do_remove(self.m, i, delete, emit=self.lines.append, host_kw=self.host_kw())

    def steps(self):
        return [ln.split()[1:3] for ln in self.lines if ln.startswith("::step ")]

    def test_add_installs_records_and_asks_it(self):
        code = self.add(["uptime"])
        self.assertEqual(code, 0, "\n".join(self.lines))
        self.assertTrue(Path(self.root, L.QUADLET_DIR, "uptime-kuma.container").exists())
        self.assertIn("uptime-kuma.service", self.fm.active)
        self.assertEqual(A.desired(self.m)["apps"], ["uptime"])
        rec = A.engine_record(self.m)["items"]["uptime"]
        self.assertEqual((rec["state"], rec["recipe"], rec["app_version"]), ("done", 1, "2.5.8"))
        self.assertEqual(self.steps(), [["plan", "running"], ["plan", "done"], ["record", "running"], ["record", "done"],
                                        ["answers", "running"], ["answers", "done"]])
        self.assertIn("::item uptime done", self.lines)

    def test_add_that_never_answers_fails_in_words(self):
        self.fm.fail.add("podman exec uptime-kuma")
        code = self.add(["uptime"])
        self.assertEqual(code, 1)
        self.assertIn(["answers", "failed"], self.steps())
        err = next(ln for ln in self.lines if ln.startswith("::error answers"))
        self.assertIn("Uptime is set up, but it doesn't answer (podman exec uptime-kuma extra/healthcheck: 1) after 480 s.", err)
        self.assertEqual(self.clock[0] - NOW, 480_000, "it asked until its time was up, and no longer")
        self.assertIn("bromigos lab apps logs uptime", err)
        self.assertEqual(A.desired(self.m)["apps"], ["uptime"], "it is installed: the board shows it, not answering")

    def test_add_pulls_in_what_it_needs(self):
        code = self.add(["passwords"])
        self.assertEqual(code, 0, "\n".join(self.lines))
        self.assertEqual(A.desired(self.m)["apps"], ["caddy", "passwords"])

    def test_a_failed_install_isnt_recorded_as_on_the_server(self):
        self.fm.fail.add("podman pull")
        code = self.add(["uptime"])
        self.assertEqual(code, 1)
        self.assertEqual(A.desired(self.m)["apps"], [])

    def test_remove_keeps_the_data_and_adding_again_finds_it(self):
        self.assertEqual(self.add(["uptime"]), 0)
        note = Path(self.root, "srv/apps/uptime/data/kuma.db")
        note.write_bytes(b"monitors" * 1000)
        code = self.remove("uptime")
        self.assertEqual(code, 0, "\n".join(self.lines))
        self.assertFalse(Path(self.root, L.QUADLET_DIR, "uptime-kuma.container").exists())
        self.assertTrue(Path(self.root, L.QUADLET_DIR, "bromigos-lab.network").exists(), "the network is every app's")
        self.assertNotIn("uptime-kuma.service", self.fm.active)
        self.assertTrue(self.fm.ran("systemctl stop uptime-kuma.service"))
        self.assertTrue(note.exists())
        self.assertNotIn("uptime", A.desired(self.m)["apps"])
        self.assertNotIn("uptime", A.engine_record(self.m)["items"])
        self.assertEqual(self.steps(), [["check", "running"], ["check", "done"], ["stop", "running"], ["stop", "done"],
                                        ["units", "running"], ["units", "done"], ["data", "skipped"],
                                        ["record", "running"], ["record", "done"]])
        self.assertTrue(any(ln.startswith("::note data Its data stays in /srv/apps/uptime (") and
                            ln.endswith("Adding Uptime again picks it up.") for ln in self.lines), self.lines)
        self.assertEqual(self.add(["uptime"]), 0)
        self.assertEqual(note.read_bytes(), b"monitors" * 1000)
        self.assertIn("uptime-kuma.service", self.fm.active)

    def test_remove_with_delete_data(self):
        self.add(["uptime"])
        Path(self.root, "srv/apps/uptime/data/kuma.db").write_bytes(b"x")
        self.assertEqual(self.remove("uptime", delete=True), 0)
        self.assertFalse(Path(self.root, "srv/apps/uptime").exists())
        self.assertIn(["data", "done"], self.steps())

    def test_removing_one_app_leaves_the_others_and_their_data(self):
        self.answers["http://127.0.0.1:2283/api/server/ping"] = 200
        self.store.put("photos/db-password", "not-a-real-one")
        self.assertEqual(self.add(["uptime", "photos"]), 0, "\n".join(self.lines))
        self.assertEqual(self.remove("uptime", delete=True), 0, "\n".join(self.lines))
        self.assertTrue(Path(self.root, L.QUADLET_DIR, "immich-server.container").exists())
        self.assertTrue(Path(self.root, "srv/apps/photos/library").is_dir())
        self.assertEqual(A.desired(self.m)["apps"], ["photos"])

    def test_remove_a_package_app(self):
        self.assertEqual(self.add(["passwords"]), 0, "\n".join(self.lines))
        self.assertEqual(self.remove("passwords"), 0, "\n".join(self.lines))
        self.assertTrue(self.fm.ran("systemctl disable vaultwarden.service"))
        self.assertTrue(self.fm.ran("pacman -R --noconfirm vaultwarden vaultwarden-web"))
        self.assertEqual(A.desired(self.m)["apps"], ["caddy"])
        # Caddy ran again for the rest: the vault's name is off the network
        self.assertNotIn("passwords-", Path(self.root, "etc/caddy/conf.d/bromigos-lab.caddy").read_text())

    def test_what_others_need_is_refused(self):
        self.desire(["media-library", "jellyfin", "seerr"])
        r = A.removal(self.m, "jellyfin")
        self.assertEqual(r["needed_by"], ["seerr"])
        self.assertEqual(r["refused"], "Jellyfin can't be removed while Requests needs it: remove it first.")
        self.assertEqual(self.remove("jellyfin"), 3)
        self.assertTrue(any("::error check Jellyfin can't be removed" in ln for ln in self.lines))
        self.desire(["media-library", "jellyfin", "plex", "seerr"])           # Plex meets "jellyfin|plex" too
        self.assertIsNone(A.removal(self.m, "jellyfin")["refused"])

    def test_steps_that_change_more_are_refused(self):
        self.desire(["caddy", "adblock"])
        self.assertIn("isn't built yet", A.removal(self.m, "adblock")["refused"])
        self.assertIsNone(A.removal(self.m, "caddy")["needed_by"] or None)
        self.assertIn("isn't built yet", A.removal(self.m, "caddy")["refused"])

    def test_what_stays_is_said_before_anything_changes(self):
        self.desire(["photos"])
        Path(self.root, "srv/apps/photos/library").mkdir(parents=True)
        Path(self.root, "srv/apps/photos/library/a.jpg").write_bytes(b"x" * 8192)
        code, out, _ = self.run_main(["remove", "photos", "--plan"])
        self.assertEqual(code, 0)
        self.assertIn("stops and leaves: immich-database.service", out)
        self.assertIn("stays: its data in /srv/apps/photos (", out)
        self.assertIn("and its keys (photos/db-password). Adding it again picks them up.", out)
        self.assertIn("/srv/apps/photos/library (", out)
        self.assertIn("never touched: the media library (/srv/media), shared folders, other apps' data.", out)
        self.assertEqual(self.started, [])
        code, out, _ = self.run_main(["remove", "photos", "--plan", "--json"])
        doc = json.loads(out)
        self.assertEqual(doc["stays"]["path"], "/srv/apps/photos")
        self.assertGreaterEqual(doc["stays"]["bytes"], 8192)
        self.assertFalse(doc["delete_data"])


class Commands(Base):
    """What the commands hand to `bromigos activity run`, and what they refuse."""

    def test_add_is_a_job_with_the_apps_lock(self):
        code, _, _ = self.run_main(["add", "photos"])
        self.assertEqual(code, 0)
        self.assertEqual(self.started, [[
            "/usr/lib/bromigos/bin/bromigos-activity", "run", "--kind", "app.install", "--title", "Adding Photos",
            "--subject", "app:photos:Photos", "--lock", "apps", "--",
            "/usr/lib/bromigos/bin/bromigos-lab", "apps", "add", "photos"]])

    def test_remove_never_deletes_without_the_flag(self):
        self.desire(["uptime"])
        self.run_main(["remove", "uptime"])
        self.assertEqual(self.started[-1][-3:], ["apps", "remove", "uptime"])
        self.assertEqual(self.started[-1][self.started[-1].index("--kind") + 1], "app.remove")
        self.assertIn("apps", self.started[-1][self.started[-1].index("--lock") + 1])
        self.started.clear()
        with mock.patch.object(sys, "stdin", io.StringIO()):
            code, _, err = self.run_main(["remove", "uptime", "--delete-data"])
        self.assertEqual(code, 3)
        self.assertIn("needs a yes", err)
        self.assertEqual(self.started, [])
        self.run_main(["remove", "uptime", "--delete-data", "--yes"])
        self.assertEqual(self.started[-1][-5:], ["apps", "remove", "uptime", "--delete-data", "--yes"])

    def test_inside_the_job_it_does_the_work(self):
        m = self.machine(environ={"BROMIGOS_ACTIVITY_JOB": "20261110-0000-app.install-photos-abcd"})
        with mock.patch.object(A, "do_add", return_value=0) as add, mock.patch.object(A, "do_remove", return_value=0) as rm:
            self.run_main(["add", "photos"], m)
            self.run_main(["remove", "photos", "--delete-data", "--yes"], m)
        add.assert_called_once_with(m, ["photos"], [])
        rm.assert_called_once_with(m, "photos", True)
        self.assertEqual(self.started, [])

    def test_refusals(self):
        self.assertEqual(self.run_main(["add", "nope"])[0], 3)
        self.assertEqual(self.run_main(["remove", "photos"])[0], 3)            # not on this server
        self.assertEqual(self.run_main(["restart", "photos"])[0], 3)
        code, _, err = self.run_main(["add", "jellyfin", "plex", "--plan"])
        self.assertEqual(code, 0)
        self.desire(["photos"])
        m = self.machine(root="/", euid=1000)
        with mock.patch.object(A, "desired", return_value=dict(A._blank(), apps=["photos"])):
            code, _, err = self.run_main(["restart", "photos"], m)
        self.assertEqual(code, 3)
        self.assertIn("needs root: sudo bromigos lab apps restart", err)
        self.assertEqual(self.started, [])

    def test_add_plan_says_what_and_the_meter(self):
        self.desire(["caddy"])
        code, out, _ = self.run_main(["add", "passwords", "photos", "--plan", "--json"])
        doc = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(doc["add"], ["passwords", "photos"])
        self.assertEqual([r["id"] for r in doc["plan"]], ["photos", "passwords"])
        self.assertEqual(doc["budget"]["installed"]["ids"], ["caddy"])
        self.assertEqual(doc["budget"]["picked"]["ids"], ["photos", "passwords"])
        code, out, _ = self.run_main(["add", "photos", "--plan"])
        self.assertIn("Adds Photos (Immich)", out)
        self.assertIn("Together with what's installed: about", out)

    def test_restart_and_logs(self):
        self.desire(["uptime"])
        code, out, _ = self.run_main(["restart", "uptime", "--json"])
        self.assertEqual(json.loads(out), {"schema": 1, "ok": True, "app": "uptime", "units": ["uptime-kuma.service"],
                                           "failed": []})
        self.assertTrue(self.fm.ran("systemctl restart uptime-kuma.service"))
        self.run_main(["logs", "uptime", "-f"])
        self.assertEqual(self.started[-1][1:], ["--no-pager", "-n", "50", "-u", "uptime-kuma.service", "-f"])
        code, out, _ = self.run_main(["logs", "uptime", "--json"])
        self.assertEqual(json.loads(out)["units"], ["uptime-kuma.service"])
        self.desire(["media-library"])
        code, _, err = self.run_main(["restart", "media-library"])
        self.assertEqual(code, 3)
        self.assertIn("has no service of its own to restart", err)

    def test_two_app_jobs_queue_on_the_apps_lock(self):
        """The real `bromigos activity run`, in the foreground under a stand-in root, with a
        stand-in for the job's command: the second app job waits for the first."""
        log = Path(self.root, "spans")
        job = Path(self.root, "fake-lab")
        job.write_text("#!/bin/sh\necho \"start $(date +%s%N)\" >> " + str(log) + "\necho '::step plan running Checking'\n"
                       "sleep 1\necho \"end $(date +%s%N)\" >> " + str(log) + "\n")
        job.chmod(0o755)
        env = dict(os.environ, BROMIGOS_ROOT=self.root, BROMIGOS_ACTIVITY_RUNNER="foreground")
        env.pop("BROMIGOS_ACTIVITY_JOB", None)
        procs = []

        def start(argv):
            procs.append(subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          start_new_session=True))
            time.sleep(0.3)
            return 0
        m = self.machine(start=start, environ={"BROMIGOS_ACTIVITY_CMD": str(REPO / "bin/bromigos-activity")})
        for _ in range(2):
            A.as_job(m, [str(job)], "app.install", "Adding Uptime", "app:uptime:Uptime", ["add", "uptime"], False)
        try:
            for p in procs:
                self.assertEqual(p.wait(timeout=30), 0)
        finally:
            for p in procs:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, 9)
        spans = [ln.split() for ln in log.read_text().splitlines()]
        self.assertEqual([s[0] for s in spans], ["start", "end", "start", "end"], "the second waited for the first")
        jobs = sorted(Path(self.root, "var/lib/bromigos/activity/jobs").glob("*.json"))
        recs = [json.loads(p.read_text()) for p in jobs]
        self.assertEqual([r["locks"] for r in recs], [["apps"], ["apps"]])
        self.assertEqual({r["subject"]["id"] for r in recs}, {"uptime"})


class Budget(Base):
    def test_installed_plus_picked(self):
        b = PC.budget(["uptime"], dict(HW, disk_gb=10), installed=["photos"])
        self.assertEqual(b["installed"]["ids"], ["photos"])
        self.assertEqual(b["picked"]["ids"], ["uptime"])
        self.assertEqual(b["ram_gb"], round(4 + PC.by_id()["uptime"]["requires"]["ram_gb"] + PC.OS_RAM_GB, 2))
        self.assertTrue(b["fits"], "Photos' 20 GB is already out of the 10 GB free: only Uptime's must fit")
        self.assertFalse(PC.budget(["uptime", "photos"], dict(HW, disk_gb=10))["fits"])
        self.assertEqual(b["cpu_max"], 2)

    def test_memory_counts_whats_installed(self):
        b = PC.budget(["photos"], dict(HW, ram_gb=6), installed=["documents"])
        self.assertFalse(b["fits"])
        self.assertIn("Together these need about", b["notes"][0])

    def test_unchanged_without_installed(self):
        old = PC.budget(["photos", "uptime"], HW)
        self.assertEqual(set(old), {"cpu", "ram_gb", "disk_gb", "gpu_vram_gb", "fits", "notes"})

    def test_the_command(self):
        self.desire(["photos"])
        self.fm.active |= set(PHOTOS_UNITS)
        self.write("sys/fs/cgroup/system.slice/immich-server.service/memory.current", "1000\n")
        code, out, _ = self.run_main(["budget", "uptime", "--json"])
        b = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(b["picked"]["ids"], ["uptime"])
        self.assertIsNone(b["measured"]["ram_bytes"], "three of Photos' four units have no reading: no total")
        for u in PHOTOS_UNITS:
            self.write(f"sys/fs/cgroup/system.slice/{u}/memory.current", "1000\n")
        b = json.loads(self.run_main(["budget", "--json"])[1])
        self.assertEqual(b["measured"]["ram_bytes"], 4000)
        code, out, _ = self.run_main(["budget"])
        self.assertIn("What the installed apps ask for (1)", out)


class Stubs(Base):
    """`bromigos lab deploy|restart|logs|update`: the apps verbs on a Server, Phase 2 elsewhere."""

    def lab(self, *args):
        env = dict(os.environ, BROMIGOS_ROOT=self.root, BROMIGOS_SHARE_DIR="/nonexistent")
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)
        return subprocess.run([sys.executable, str(LAB), *args], env=env, capture_output=True, text=True, timeout=60)

    def test_off_a_server_they_stay_phase_2(self):
        r = self.lab("deploy", "photos")
        self.assertEqual(r.returncode, 3)
        self.assertIn("Phase 2", r.stderr)
        self.assertFalse(A.is_server(self.root))

    def test_on_a_server_they_are_the_apps_verbs(self):
        self.write("etc/bromigos/server.toml", "[update]\n")
        self.assertTrue(A.is_server(self.root))
        r = self.lab("update")
        self.assertEqual(r.returncode, 3)
        self.assertIn("Updating apps is planned", r.stderr)
        r = self.lab("restart", "photos")
        self.assertEqual(r.returncode, 3)
        self.assertIn("Photos (Immich) isn't on this server", r.stderr)
        r = self.lab("logs", "nope")
        self.assertIn("no app named 'nope'", r.stderr)
        with mock.patch.object(A, "main", return_value=0) as main:
            A.stub("deploy", ["photos", "--plan"], ["lab", "apps"], self.m)
        main.assert_called_once_with(["add", "photos", "--plan"], ["lab", "apps"], self.m)

    def test_apps_list_through_the_lab_command(self):
        self.write("etc/bromigos/lab/apps.toml", 'format = 1\napps = ["uptime"]\n')
        r = self.lab("apps", "list", "--json")
        tiles = {t["id"]: t for t in json.loads(r.stdout)}
        self.assertTrue(tiles["uptime"]["installed"])


class Fixture(unittest.TestCase):
    def test_the_ci_catalogue_is_a_valid_catalogue(self):
        with mock.patch.dict(os.environ, {"BROMIGOS_QUADLET_TEMPLATES": str(FIXTURE / "quadlet")}):
            self.assertEqual(PC.validate(str(FIXTURE / "provision-catalogue.toml")), [])


if __name__ == "__main__":
    unittest.main()
