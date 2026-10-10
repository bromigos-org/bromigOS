"""`bromigos lab youtube add|list|remove|pause|resume|refresh|status|quality|cookies`
(pinchflat.py) against a fake Pinchflat built from recorded pages (pinchflatfake.py), and the
lab console's "Add a channel or playlist…" form. Nothing reaches a network.

    PYTHONPATH=lib:../lib python -m unittest tests.test_lab_youtube_cli
"""
import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("BROMIGOS_HOMELAB_CONFIG", "/nonexistent")

import pinchflatfake as F                                         # noqa: E402
from bromigos_homelab import config, pinchflat as P               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(os.path.dirname(HERE), "bin", "bromigos-lab")
PLAYLIST = "https://www.youtube.com/playlist?list=PLCFE9837C2F7EB8AA"
CHANNEL = "https://www.youtube.com/@NASAGoddard"
COOKIE_SECRET = "SECRETVALUE-do-not-print-0123456789"
COOKIES = ("# Netscape HTTP Cookie File\n"
           f".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\t{COOKIE_SECRET}\n"
           f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\tHSID\t{COOKIE_SECRET}x\n"
           ".google.com\tTRUE\t/\tTRUE\t1893456000\tNID\tother\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.srv = F.Server()
        self.st = self.srv.state
        self.st.names[PLAYLIST] = "Little SDO"
        self.tmp = tempfile.mkdtemp(prefix="pf-")
        self.toml = F.homelab_toml(self.tmp, self.srv.url, self.extra())
        self.patches = [mock.patch.object(config, "USER", self.toml),
                        mock.patch.dict(os.environ, {"PINCHFLAT_URL": "", "PINCHFLAT_AUTH": "",
                                                     "PINCHFLAT_COOKIES_STORE": "", "YOUTUBE_QUALITY": ""})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.srv.close()

    def extra(self):
        return ""

    def cli(self, *argv, stdin_tty=False, answer=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(sys.stdin, "isatty", lambda: stdin_tty), \
                mock.patch("builtins.input", lambda q="": (out.write(q), answer)[1] if answer is not None else "") :
            code = P.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def js(self, *argv):
        code, out, err = self.cli(*argv, "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def posts(self, path=None):
        return [p for p in self.st.posts if path is None or p[0] == path]


class AddTest(Base):
    def test_add_a_playlist(self):
        code, out, err = self.cli("add", PLAYLIST)
        self.assertEqual(code, 0, err)
        self.assertIn("Added 'Little SDO' (playlist)", out)
        self.assertIn("every video in the playlist, in its order, at 1080p (Playlists (in order))", out)
        [(path, f)] = self.posts()
        self.assertEqual(path, "/sources")
        # the form as the page has it: its defaults (Pinchflat's own), and what was asked for
        self.assertEqual(f["source[original_url]"], PLAYLIST)
        self.assertEqual(f["source[media_profile_id]"], "2")
        self.assertEqual(f["source[index_frequency_minutes]"], "1440")
        self.assertEqual(f["source[download_media]"], "true")
        self.assertEqual(f["source[fast_index]"], "false")
        self.assertEqual(f["source[cookie_behaviour]"], "disabled")
        self.assertEqual(f["source[download_cutoff_date]"], "")
        self.assertNotIn("download_cutoff_date_preset", f)

    def test_add_a_channel_with_a_date_a_name_and_4k(self):
        rec = self.js("add", "youtube.com/@NASAGoddard", "--since", "2025-01-01", "--name", "Goddard", "--quality", "2160p")
        self.assertEqual(rec["kind"], "channel")
        self.assertEqual(rec["name"], "Goddard")
        self.assertEqual(rec["since"], "2025-01-01")
        self.assertEqual(rec["quality"], "2160p")
        self.assertEqual(rec["profile"], "Channels (Media Center) · 2160p")
        self.assertTrue(rec["made_profile"])
        made = self.st.profiles[3]
        # a copy of the base profile: its template (same folders, same [id]) and every setting
        self.assertEqual(made["output_path_template"], F.CHANNEL_TEMPLATE)
        self.assertEqual(made["form"]["media_profile[preferred_resolution]"], "2160p")
        self.assertEqual(made["form"]["media_profile[download_nfo]"], "true")
        self.assertNotIn("media_profile_preset", made["form"])
        src = self.posts("/sources")[0][1]
        self.assertEqual(src["source[original_url]"], CHANNEL)
        self.assertEqual(src["source[media_profile_id]"], "3")
        self.assertEqual(src["source[custom_name]"], "Goddard")
        self.assertEqual(src["source[download_cutoff_date]"], "2025-01-01")
        # the same quality again reuses the copy
        self.js("add", "https://www.youtube.com/@NASA", "--quality", "2160p")
        self.assertEqual(len(self.st.profiles), 3)
        self.assertEqual(len(self.posts("/media_profiles")), 1)

    def test_best_is_pinchflats_highest_and_the_labs_default_applies(self):
        rec = self.js("add", PLAYLIST, "--quality", "best")
        self.assertEqual(rec["quality"], "4320p")
        self.assertEqual(rec["profile"], "Playlists (in order) · 4320p")
        with open(self.toml, "a") as f:
            f.write('\n[youtube]\nquality = "720p"\n')
        rec = self.js("add", CHANNEL)
        self.assertEqual(rec["quality"], "720p")

    def test_urls(self):
        self.assertEqual(P.normalise_url("https://www.youtube.com/watch?v=EPqhLlzZX6I&list=PLCFE9837C2F7EB8AA"),
                         (PLAYLIST, "playlist"))
        self.assertEqual(P.normalise_url("@NASA"), ("https://www.youtube.com/@NASA", "channel"))
        code, out, err = self.cli("add", "https://youtu.be/EPqhLlzZX6I")
        self.assertEqual(code, 1)
        self.assertIn("is one video", err)
        code, out, err = self.cli("add", CHANNEL, "--playlist")
        self.assertIn("a channel's URL, not a playlist's", err)
        code, out, err = self.cli("add", PLAYLIST, "--since", "last week")
        self.assertIn("YYYY-MM-DD", err)
        self.assertEqual(self.posts(), [])

    def test_pinchflat_refuses(self):
        code, out, err = self.cli("add", "https://www.youtube.com/@x", "--channel")
        self.assertEqual(code, 0, err)
        with mock.patch.object(P, "normalise_url", lambda u, k=None: ("https://www.youtube.com/watch?v=x", "channel")):
            code, out, err = self.cli("add", "anything")
        self.assertEqual(code, 1)
        self.assertIn("Pinchflat refused the channel", err)
        self.assertIn("original url must be a channel or playlist URL", err)

    def test_a_changed_form_stops_before_sending(self):
        self.st.break_form = "source[cookie_behaviour]"
        code, out, err = self.cli("add", PLAYLIST)
        self.assertEqual(code, 1)
        self.assertIn("isn't what this was built for (tested with v2025.9.26)", err)
        self.assertIn("source[cookie_behaviour]", err)
        self.assertEqual(self.posts(), [])

    def test_wrong_login(self):
        with open(os.path.join(self.tmp, "basic"), "w") as f:
            f.write("admin:wrong")
        code, out, err = self.cli("list")
        self.assertEqual(code, 1)
        self.assertIn("refused the login", err)

    def test_no_pinchflat(self):
        with mock.patch.object(config, "USER", "/nonexistent"):
            code, out, err = self.cli("list")
        self.assertIn("no Pinchflat", err)


class ManageTest(Base):
    def setUp(self):
        super().setUp()
        self.sdo = self.st.add_source(custom_name="Little SDO", collection_name="Little SDO", original_url=PLAYLIST,
                                      uuid="bb125a44-0000-4000-8000-000000000001", downloaded=4, pending=1)
        self.ch = self.st.add_source(custom_name="NASA Goddard", collection_type="channel", original_url=CHANNEL,
                                     media_profile_id=1, downloaded=120, pending=0,
                                     uuid="bb125a44-0000-4000-8000-000000000002")

    def test_list(self):
        rows = self.js("list")
        self.assertEqual([r["name"] for r in rows], ["Little SDO", "NASA Goddard"])
        sdo = rows[0]
        self.assertEqual((sdo["kind"], sdo["quality"], sdo["downloaded"], sdo["pending"]), ("playlist", "1080p", 4, 1))
        self.assertEqual(sdo["last_check"], "2026-10-10T07:42:31Z")
        self.assertEqual(sdo["newest"], "NASA | Introducing Little SDO")       # the recorded feed's newest
        self.assertEqual(rows[1]["kind"], "channel")
        code, out, err = self.cli("list")
        self.assertIn("Little SDO", out)
        self.assertIn("2026-10-10 07:42", out)
        self.assertIn("NASA | Introducing Little SDO", out)
        self.st.sources[self.ch["id"]]["marked_for_deletion_at"] = "2026-10-10T08:00:00Z"
        self.assertEqual([r["name"] for r in self.js("list")], ["Little SDO"])

    def test_pause_resume_refresh(self):
        self.assertEqual(self.cli("pause", "little sdo")[0], 0)
        self.assertEqual(self.st.sources[self.sdo["id"]]["enabled"], "false")
        self.assertIn("(paused)", self.cli("list")[1])
        self.assertEqual(self.posts()[-1][1]["_method"], "patch")
        self.assertEqual(self.cli("resume", PLAYLIST)[0], 0)
        self.assertEqual(self.st.sources[self.sdo["id"]]["enabled"], "true")
        self.assertEqual(self.js("refresh", "NASA Goddard")["refreshed"], ["NASA Goddard"])
        self.assertEqual(self.st.sources[self.ch["id"]].get("indexed"), 1)
        self.assertEqual(sorted(self.js("refresh")["refreshed"]), ["Little SDO", "NASA Goddard"])
        code, out, err = self.cli("pause", "nothing like it")
        self.assertEqual(code, 4)
        self.assertIn("no source called", err)

    def test_remove_asks_and_keeps_files(self):
        code, out, err = self.cli("remove", "Little SDO")
        self.assertEqual(code, 1)
        self.assertIn("add --yes", err)
        code, out, err = self.cli("remove", "Little SDO", stdin_tty=True, answer="n")
        self.assertIn("Its downloaded videos stay on disk", out)
        self.assertIn("Nothing removed", out)
        self.assertFalse(self.st.sources[self.sdo["id"]]["marked_for_deletion_at"])
        code, out, err = self.cli("remove", "Little SDO", stdin_tty=True, answer="y")
        self.assertEqual(code, 0, err)
        s = self.st.sources[self.sdo["id"]]
        self.assertTrue(s["marked_for_deletion_at"])
        self.assertFalse(s["delete_files"])
        self.assertEqual(self.posts()[-1][0], f"/sources/{self.sdo['id']}")
        self.assertEqual(self.posts()[-1][1]["_method"], "delete")

    def test_remove_with_files(self):
        code, out, err = self.cli("remove", CHANNEL, "--delete-files", stdin_tty=True, answer="yes")
        self.assertIn("and delete its 120 downloaded videos from disk?", out)
        self.assertTrue(self.st.sources[self.ch["id"]]["delete_files"])
        self.assertEqual(self.posts()[-1][0], f"/sources/{self.ch['id']}?delete_files=true")
        rec = self.js("remove", "Little SDO", "--yes")
        self.assertEqual(rec, {"removed": "Little SDO", "id": self.sdo["id"], "delete_files": False})

    def test_quality(self):
        code, out, err = self.cli("quality", "Little SDO", "2160p")
        self.assertEqual(code, 0, err)
        self.assertIn("new downloads only", out)
        self.assertEqual(self.st.sources[self.sdo["id"]]["media_profile_id"], 3)
        self.assertEqual(self.js("list")[0]["quality"], "2160p")
        self.cli("quality", "Little SDO", "1080p")
        self.assertEqual(self.st.sources[self.sdo["id"]]["media_profile_id"], 2)
        self.assertEqual(len(self.posts("/media_profiles")), 1)
        # a copy someone changed in Pinchflat's page is put back, not duplicated
        self.st.profiles[3]["preferred_resolution"] = "720p"
        self.js("quality", "Little SDO", "2160p")
        self.assertEqual(self.st.profiles[3]["preferred_resolution"], "2160p")
        self.assertEqual(len(self.st.profiles), 3)

    def test_status(self):
        d = self.js("status")
        self.assertEqual(d["version"], "2025.9.26")
        self.assertEqual((d["sources"], d["downloaded"], d["pending"]), (2, 124, 1))
        self.assertIsNotNone(d["queue"])
        self.assertEqual(d["failed"], 0)
        self.assertEqual(d["recent"][0]["title"], "NASA | Introducing Little SDO")
        self.st.metrics += ('pinchflat_prom_ex_oban_queue_length_count{name="Oban",queue="media_fetching",'
                            'state="discarded"} 3\n')
        code, out, err = self.cli("status")
        self.assertIn("Failed in the last 30 days: 3 jobs", out)
        self.assertIn("Recent downloads", out)

    def test_the_command_line(self):
        env = dict(os.environ, BROMIGOS_HOMELAB_CONFIG=self.toml)
        env.pop("PYTHONPATH", None)                     # the script puts its own tree first
        p = subprocess.run([sys.executable, LAB, "youtube", "list", "--json"], capture_output=True, text=True,
                           env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(json.loads(p.stdout)), 2)
        p = subprocess.run([sys.executable, LAB, "youtube", "--json"], capture_output=True, text=True, env=env, timeout=60)
        card = json.loads(p.stdout)
        cards = card.get("cards") or [card]
        yt = next(c for c in cards if c.get("id") == "youtube-downloader")
        # the card lists the sources with no route token: the Sources page's OPML link has it
        self.assertEqual(sorted(i["name"] for i in yt["items"] if i.get("kind") != "downloader"),
                         ["Little SDO", "NASA Goddard"])


class CookieTest(Base):
    def extra(self):
        return 'cookies_store = "vault:secret/lab/pinchflat#cookies"'

    def setUp(self):
        super().setUp()
        self.vault, self.store = F.fake_vault(self.tmp)
        with open(self.store, "w") as f:
            json.dump({"secret/lab/pinchflat": {"username": "admin", "password": "x"}}, f)
        self.patches.append(mock.patch.dict(os.environ, {"PATH": self.tmp + os.pathsep + os.environ.get("PATH", "")}))
        self.patches[-1].start()
        self.st.add_source(custom_name="Little SDO", original_url=PLAYLIST)
        self.cookies = os.path.join(self.tmp, "cookies.txt")
        with open(self.cookies, "w") as f:
            f.write(COOKIES)

    def kv(self):
        with open(self.store) as f:
            return json.load(f)["secret/lab/pinchflat"]

    def test_check(self):
        self.assertEqual(P.check_cookies(self.cookies)["youtube"], 2)
        for text, why in (('[{"name": "SID"}]', "is JSON"), ("hello world\n", "isn't a Netscape cookies.txt"),
                          (".google.com\tTRUE\t/\tTRUE\t0\tNID\tx\n", "no youtube.com cookies"), ("", "is empty")):
            p = os.path.join(self.tmp, "bad.txt")
            with open(p, "w") as f:
                f.write(text)
            with self.assertRaises(P.CookieError) as e:
                P.check_cookies(p)
            self.assertIn(why, str(e.exception))
            self.assertNotIn("SID", str(e.exception))

    def test_set_status_clear(self):
        d = self.js("cookies", "status")
        self.assertFalse(d["present"])
        code, out, err = self.cli("cookies", "set", self.cookies)
        self.assertEqual(code, 0, err)
        self.assertNotIn(COOKIE_SECRET, out + err)
        self.assertIn("Stored 2 youtube.com cookies", out)
        self.assertIn("Delete the exported file", out)
        kv = self.kv()
        self.assertEqual(kv["cookies"], COOKIES)
        self.assertEqual(kv["password"], "x")                    # the rest of the path is kept
        self.assertTrue(kv["cookies_set_at"])
        s = next(iter(self.st.sources.values()))
        self.assertEqual(s["cookie_behaviour"], "when_needed")
        code, out, err = self.cli("cookies", "status")
        self.assertIn("YouTube cookies are set (2 youtube.com cookies", out)
        self.assertNotIn(COOKIE_SECRET, out + err)
        self.assertNotIn("over 30 days", out)
        d = self.js("cookies", "status")
        self.assertNotIn(COOKIE_SECRET, json.dumps(d))
        self.assertEqual(d["sources_using"], 1)
        # a source added while there are cookies uses them
        rec = self.js("add", CHANNEL)
        self.assertEqual(rec["cookies"], "when_needed")
        # old ones are flagged
        with open(self.store) as f:
            kv = json.load(f)
        kv["secret/lab/pinchflat"]["cookies_set_at"] = "2026-08-01T00:00:00Z"
        with open(self.store, "w") as f:
            json.dump(kv, f)
        code, out, err = self.cli("cookies", "status")
        self.assertIn("over 30 days old", out)
        code, out, err = self.cli("cookies", "clear")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.kv()["cookies"], "")
        self.assertEqual(self.kv()["username"], "admin")
        self.assertTrue(all(s["cookie_behaviour"] == "disabled" for s in self.st.sources.values()))
        self.assertFalse(self.js("cookies", "status")["present"])

    def test_a_file_store_and_a_bad_file(self):
        target = os.path.join(self.tmp, "extras", "cookies.txt")
        st = P.CookieStore("file:" + target)
        self.assertFalse(st.status()["present"])
        st.set(self.cookies)
        self.assertEqual(oct(os.stat(target).st_mode & 0o777), "0o600")
        self.assertTrue(st.status()["present"])
        st.clear()
        self.assertFalse(st.status()["present"])
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as f:
            f.write("[]")
        code, out, err = self.cli("cookies", "set", bad)
        self.assertEqual(code, 1)
        self.assertNotIn("cookies", self.kv())                   # nothing stored
        with self.assertRaises(P.PinchflatError):
            P.CookieStore("")


try:
    import textual
    from bromigos_homelab import tui
except ImportError:
    textual = None


@unittest.skipIf(textual is None, "python-textual isn't installed")
class ConsoleTest(unittest.TestCase):
    def test_the_youtube_cards_add_form(self):
        added = []

        class Src(tui.Live):
            def status(self):
                return {"state": "ok", "generatedAt": 0, "cards": [
                    {"id": "gpus", "title": "GPUs", "state": "ok", "summary": "", "columns": ["name"], "items": []},
                    {"id": "youtube-downloader", "title": "YouTube downloads", "state": "ok", "summary": "1 source",
                     "columns": ["name"], "items": [{"name": "pinchflat", "state": "ok"}]}]}

            def jobs(self):
                return {"jobs": [], "service": "running"}

            def job_log(self, jid):
                return ""

            def youtube_quality(self):
                return "720p"

            def youtube_add(self, *a):
                added.append(a)
                return "Added 'Little SDO' (playlist) to Pinchflat."

        app = tui.LabApp(source=Src(), clock=lambda: 0, interval=3600)

        async def go():
            async with app.run_test(size=(150, 46)) as pilot:
                await pilot.pause(0.3)
                btn = app.query_one("#yt-add")
                self.assertFalse(btn.display)                       # only on the YouTube card
                app.show_card("youtube-downloader")
                await pilot.pause(0.1)
                self.assertTrue(btn.display)
                self.assertIn("bromigos lab youtube add", str(btn.tooltip))
                await pilot.click("#yt-add")
                await pilot.pause(0.3)
                screen = app.screen
                self.assertIsInstance(screen, tui.AddYouTube)
                self.assertEqual(screen.query_one("#yt-quality").value, "720p")
                for wid in ("#yt-url", "#yt-kind", "#yt-quality", "#yt-since", "#yt-name", "#yt-go", "#yt-no"):
                    self.assertTrue(screen.query_one(wid).tooltip, wid)
                screen.query_one("#yt-url").value = PLAYLIST
                screen.query_one("#yt-since").value = "2025-01-01"
                await pilot.click("#yt-go")
                for _ in range(20):
                    await pilot.pause(0.1)
                    if added:
                        break
                app.show_card("gpus")
                await pilot.pause(0.1)
                self.assertFalse(btn.display)
        asyncio.run(go())
        self.assertEqual(added, [(PLAYLIST, None, "2025-01-01", None, "720p")])


if __name__ == "__main__":
    unittest.main()
