"""The board's API against the fixtures' snapshot: the contract of each endpoint (DESIGN §1 and
the page's, board-contracts.md), the door's allow-list key by key, sign-in with a console code,
sessions, CSRF, and the private-address rule."""
import json
import os
import threading
import time
import unittest

from common import FIXTURES, LAN, NOW, Root

from starlette.testclient import TestClient

from bromigos_board import api, auth, door, paths, snapshot

ORIGIN = "https://myserver.local"
PAGE = {"x-bromigos-board": "1", "origin": ORIGIN}       # what the board's own page sends


def client(app, xff=LAN, **headers):
    h = {"x-forwarded-for": xff} if xff else {}
    h.update(headers)
    return TestClient(app, base_url=ORIGIN, headers=h)


class Base(Root):
    def setUp(self):
        super().setUp()
        self.app = api.make_app(tries=auth.Tries(), poll=0.05, stream_s=0.6)
        self.c = client(self.app)

    def snapshot(self, missing=""):
        os.environ["BOARD_MISSING"] = missing
        doc = snapshot.gather()
        snapshot.write(doc)
        return doc

    def sign_in(self, c=None):
        c = c or self.c
        code, _ = auth.new_code()
        r = c.post("/api/session", json={"code": code}, headers=PAGE)
        self.assertEqual(r.status_code, 200, r.text)
        return r


class DoorTests(Base):
    def test_the_door_is_built_key_by_key_from_its_allow_list(self):
        self.snapshot()
        r = self.c.get("/api/door")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(tuple(d), door.DOOR_KEYS)
        self.assertEqual(d["lab"], {"name": "myserver", "address": "https://myserver.local"})
        self.assertEqual(d["server"], {"name": "myserver"})
        self.assertEqual(d["world"], "wick")
        self.assertTrue(d["door"])
        self.assertEqual(d["signin"], {"code": True, "phone": False, "account": False})
        for t in d["tiles"]:
            self.assertEqual(tuple(t), door.TILE_KEYS)
            self.assertEqual(tuple(t["open"]), door.OPEN_KEYS)
            self.assertTrue(all(isinstance(v, str) for k, v in t.items() if k != "open"), t)
        # not installed (jellyfin), not for the household (monitoring), no page (backups) and a
        # link that isn't this network's (sneaky) stay off the door
        self.assertEqual([t["id"] for t in d["tiles"]], ["photos", "passwords", "uptime"])
        self.assertEqual(d["tiles"][0], {"id": "photos", "job": "Photos", "app": "Immich", "holo": "photos",
                                         "group": "home", "open": {"url": "https://photos-myserver.local"}})
        self.assertEqual(d["tiles"][2]["open"]["url"], "http://myserver.local:3001/dashboard")
        # nothing of the readings, versions, state, use, addresses or secrets the apps list carries
        text = r.text
        for leak in ("v3.3.5", "Running", "ram_bytes", "reading", "Last photo", "update", "should-never", "192.0.2",
                     "2283", "state", "version", "measured", "admin_token", "evil", "drives", "alerts", "activity", "port"):
            self.assertNotIn(leak, text)
        self.assertTrue(self.path(paths.WANTED).exists(), "the door asks for a reading")

    def test_every_allowed_key_is_checked(self):
        """A key added to the apps list never reaches the door by itself."""
        entry = json.loads((FIXTURES / "apps-list.json").read_text())[0]
        entry.update(secret="x", reading={"text": "y"}, extra=1, url="https://other-myserver.local")
        entry["open"] = dict(entry["open"], token="t", port=1)
        t = door.tile(entry)
        self.assertEqual(set(t), set(door.TILE_KEYS))
        self.assertEqual(t["open"], {"url": "https://photos-myserver.local"})     # open.url first, alone
        d = door.door({"host": "myserver", "apps": {"apps": [entry]}, "system": {"addresses": ["192.0.2.20"]},
                       "storage": {"drives": []}, "extra": True, "settings": {"door": True, "world": "mire", "x": 1}})
        self.assertEqual(set(d), set(door.DOOR_KEYS))
        self.assertEqual(d["world"], "mire")
        self.assertEqual(door.door({"host": "myserver", "settings": {"world": "../../etc"}})["world"], "wick")

    def test_links_that_arent_this_networks_are_left_out(self):
        for bad in ("https://user:pw@photos-myserver.local", "https://photos.example.org", "javascript:alert(1)",
                    "file:///etc/passwd", "https://photos-myserver.local/?token=abc", "https://photos-myserver.local#x",
                    "//photos-myserver.local", "https://photos-myserver.local:99999", "", None, 5,
                    "https://pho tos-myserver.local", "https://-x.local"):
            self.assertEqual(door.app_url(bad), "", bad)
        self.assertEqual(door.app_url("https://Photos-MyServer.local/"), "https://photos-myserver.local/")

    def test_the_door_can_be_turned_off_and_wear_a_world(self):
        self.path("etc/bromigos/server.toml").write_text('[board]\ndoor = false\nworld = "tidewell"\n')
        self.snapshot()
        d = self.c.get("/api/door").json()
        self.assertEqual((d["door"], d["tiles"], d["world"]), (False, [], "tidewell"))

    def test_before_the_first_reading_the_door_has_its_name_and_no_tiles(self):
        d = self.c.get("/api/door").json()
        self.assertEqual((d["server"], d["tiles"], d["door"]), ({"name": "myserver"}, [], True))

    def test_without_the_apps_list_the_door_lists_the_catalogues_web_apps_that_are_set_up(self):
        state = self.path(paths.PROVISION_STATE)
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"items": {"photos": {"state": "done"}, "passwords": {"state": "failed"},
                                               "board": {"state": "done"}, "start-page": {"state": "done"},
                                               "caddy": {"state": "done"}}}))
        doc = self.snapshot(missing="lab apps")
        self.assertIsNone(doc["apps"])
        d = self.c.get("/api/door").json()
        self.assertEqual(d["tiles"], [{"id": "photos", "job": "Photos", "app": "Immich", "holo": "photos", "group": "home",
                                       "open": {"url": "https://photos-myserver.local"}}])


class BoardContractTests(Base):
    def test_signed_in_the_board_is_the_snapshot_as_the_page_reads_it(self):
        self.snapshot()
        self.sign_in()
        r = self.c.get("/api/board")
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertEqual(set(b), {"schema", "at", "max_age_s", "age_s", "stale", "lab", "server", "status", "machines",
                                  "needs_you", "fixed", "apps", "storage", "backups", "updates", "ups",
                                  "host", "settings", "sources", "system", "activity", "alerts"})
        self.assertEqual((b["schema"], b["max_age_s"], b["stale"]), (1, 45, False))
        self.assertEqual(b["server"], {"name": "myserver", "kind": "server", "roles": ["home-services"]})
        self.assertEqual(b["status"]["state"], "needs-you")
        self.assertEqual(b["status"]["words"], "1 thing needs you.")
        # the one needs_you alert (the info one isn't), as the page reads it
        self.assertEqual(b["needs_you"], [{"id": "update.restart", "machine": "myserver", "subject": None, "severity": "warn",
                                           "words": "A restart finishes the update",
                                           "detail": "The kernel was updated. Restart when it suits you.",
                                           "since": 1794200000000, "go": "supply/updates", "job": None}])
        self.assertEqual(b["fixed"], [{"id": "20261110-0530-app.update-photos-1a2b", "machine": "myserver",
                                       "words": "Photos didn't answer after the update, so it was put back.",
                                       "at": 1794260000000}])
        m = b["machines"][0]
        self.assertEqual((m["name"], m["here"], m["state"], m["state_word"], m["apps"]), ("myserver", True, "warn", "needs you", 6))
        # the cards: the shipped commands' --json, unchanged
        self.assertEqual(b["storage"], json.loads((FIXTURES / "storage-health.json").read_text()))
        self.assertEqual(b["backups"], json.loads((FIXTURES / "backups-status.json").read_text()))
        self.assertEqual(b["apps"], snapshot.scrub(json.loads((FIXTURES / "apps-list.json").read_text())))   # as printed, less secrets
        self.assertEqual(b["updates"]["updates"]["phase"], "done")
        self.assertEqual(b["ups"], {"found": False})
        for name, src in b["sources"].items():
            self.assertEqual(set(src) - {"why"}, {"command", "at", "ok", "rc"}, name)
            self.assertTrue(src["ok"], name)
        self.assertEqual(b["sources"]["storage"]["rc"], 1)      # "found a problem" still answered
        # no secret, whatever a command printed
        self.assertNotIn("should-never-reach-the-board", r.text)
        self.assertNotIn("hunter2", r.text)
        self.assertEqual(b["system"]["backup"]["to"], "s3:https://s3.example.org/myserver")
        self.assertIs(b["system"]["ssh"]["passwords"], False)    # a yes/no stays
        self.assertNotIn("door_fallback", b)

    def test_an_old_reading_is_unknown(self):
        doc = self.snapshot()
        doc["at"] -= 120_000
        snapshot.write(doc)
        self.sign_in()
        b = self.c.get("/api/board").json()
        self.assertTrue(b["stale"])
        self.assertGreaterEqual(b["age_s"], 120)
        self.assertEqual(b["status"]["state"], "unknown")
        self.assertEqual(b["machines"][0]["state"], "unknown")

    def test_before_the_first_reading_the_board_says_it_is_reading(self):
        self.sign_in()
        r = self.c.get("/api/board")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "gathering")
        self.assertEqual(r.headers["retry-after"], "5")
        self.assertTrue(self.path(paths.WANTED).exists())

    def test_a_part_that_couldnt_be_read_is_null_and_says_why(self):
        os.environ["BOARD_MISSING"] = "lab apps storage"
        snapshot.write(snapshot.gather())
        self.sign_in()
        b = self.c.get("/api/board").json()
        self.assertIsNone(b["apps"])
        self.assertIsNone(b["storage"])
        self.assertIsNone(b["machines"][0]["apps"])
        self.assertFalse(b["sources"]["apps"]["ok"])
        self.assertTrue(b["sources"]["apps"]["why"])

    def test_every_answer_is_json_and_never_cached(self):
        for path in ("/api/door", "/api/session", "/api/board", "/api/nothing"):
            r = self.c.get(path)
            self.assertEqual(r.headers["cache-control"], "no-store", path)
            self.assertEqual(r.headers["x-content-type-options"], "nosniff", path)


class SignedOutTests(Base):
    def test_no_session_no_board_no_activity(self):
        self.snapshot()
        for path in ("/api/board", "/api/activity"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 401, path)
            self.assertEqual(r.json()["error"]["code"], "signed-out")
        for path in ("/api/session", "/api/session/0123456789abcdef"):
            r = self.c.delete(path, headers=PAGE)
            self.assertEqual(r.status_code, 401, path)
        self.assertEqual(self.c.get("/api/session").json(),
                         {"schema": 1, "signed_in": False, "role": None, "browser": None, "expires_at": None, "browsers": []})

    def test_a_made_up_or_forged_cookie_is_no_session(self):
        self.snapshot()
        value, rec = auth.new_session("curl/8")
        sid, _, token = value.partition(".")
        for bad in (f"{sid}.{token}x", f"{sid}.", f"0000000000000000.{token}", "../../etc/passwd.x", "x" * 400, ""):
            c = client(self.app)
            c.cookies.set(auth.COOKIE, bad)
            self.assertEqual(c.get("/api/board").status_code, 401, bad)
        c = client(self.app)
        c.cookies.set(auth.COOKIE, value)
        self.assertEqual(c.get("/api/board").status_code, 200)


class SignInTests(Base):
    def test_a_console_code_signs_this_browser_in_with_a_strict_cookie(self):
        r = self.sign_in()
        cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith(auth.COOKIE + "="))
        attrs = {a.strip().split("=")[0].lower(): a.strip() for a in cookie.split(";")}
        for a in ("httponly", "secure", "path", "max-age", "samesite"):
            self.assertIn(a, attrs, cookie)
        self.assertEqual(attrs["samesite"].lower(), "samesite=strict")
        self.assertEqual(attrs["path"], "Path=/")
        self.assertEqual(attrs["max-age"], f"Max-Age={30 * 24 * 3600}")
        self.assertNotIn("domain", attrs)
        d = r.json()
        self.assertEqual((d["signed_in"], d["role"], d["browser"]["name"]), (True, "owner", "A browser"))
        self.assertEqual(d["browsers"][0]["current"], True)
        self.assertEqual(set(d["browsers"][0]), {"id", "name", "signed_in_at", "last_seen_at", "expires_at", "current"})
        self.assertEqual(self.c.get("/api/session").json(), d)
        # the server keeps the token's hash, never the token
        f = self.path(f"{paths.SESSIONS}/{d['browser']['id']}.json")
        self.assertNotIn(self.c.cookies.get(auth.COOKIE).split(".", 1)[1], f.read_text())
        self.assertEqual(oct(os.stat(f).st_mode & 0o777), "0o600")

    def test_a_code_works_once(self):
        code, _ = auth.new_code()
        self.assertEqual(self.c.post("/api/session", json={"code": code}, headers=PAGE).status_code, 200)
        other = client(self.app, xff="192.168.1.21")
        r = other.post("/api/session", json={"code": code}, headers=PAGE)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "bad-code")
        self.assertEqual(other.get("/api/board").status_code, 401)

    def test_a_code_is_good_for_ten_minutes(self):
        os.environ["BROMIGOS_BOARD_NOW_MS"] = str(NOW)
        code, exp = auth.new_code()
        self.assertEqual(exp, NOW + 600_000)
        os.environ["BROMIGOS_BOARD_NOW_MS"] = str(NOW + 600_000)
        r = self.c.post("/api/session", json={"code": code}, headers=PAGE)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "expired")
        self.assertFalse(auth.use_code(code), "a late try used it up anyway")

    def test_a_code_is_read_however_it_is_typed(self):
        code, _ = auth.new_code()
        typed = " " + code.lower().replace("-", " ") + " "
        self.assertEqual(self.c.post("/api/session", json={"code": typed}, headers=PAGE).status_code, 200)

    def test_too_many_wrong_codes_wait_and_end_the_codes_waiting(self):
        for _ in range(5):
            self.assertEqual(self.c.post("/api/session", json={"code": "AAAA-AAAA"}, headers=PAGE).status_code, 401)
        code, _ = auth.new_code()
        r = self.c.post("/api/session", json={"code": code}, headers=PAGE)
        self.assertEqual(r.status_code, 429)        # even the right one, from here, for a minute
        self.assertEqual(r.json()["error"]["code"], "too-many")
        self.assertEqual(r.headers["retry-after"], "60")
        # 20 wrong in all, from anywhere: every code waiting is cancelled
        for i in range(15):
            client(self.app, xff=f"10.0.0.{i + 1}").post("/api/session", json={"code": "BBBB-BBBB"}, headers=PAGE)
        self.assertEqual(auth.codes_waiting(), [])
        self.assertFalse(auth.use_code(code))

    def test_a_session_lasts_thirty_days(self):
        os.environ["BROMIGOS_BOARD_NOW_MS"] = str(NOW)
        self.snapshot()
        self.sign_in()
        os.environ["BROMIGOS_BOARD_NOW_MS"] = str(NOW + 29 * 24 * 3600_000)
        self.assertEqual(self.c.get("/api/board").status_code, 200)
        os.environ["BROMIGOS_BOARD_NOW_MS"] = str(NOW + 30 * 24 * 3600_000)
        self.assertEqual(self.c.get("/api/board").status_code, 401)
        self.assertEqual(auth.sessions(), [])

    def test_signing_out_and_signing_another_browser_out(self):
        self.snapshot()
        self.sign_in()
        other = client(self.app, **{"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"})
        self.sign_in(other)
        d = self.c.get("/api/session").json()
        self.assertEqual(len(d["browsers"]), 2)
        self.assertNotIn("hash", json.dumps(d))
        firefox = next(b for b in d["browsers"] if b["name"] == "Firefox on Linux")
        self.assertFalse(firefox["current"])
        r = self.c.delete(f"/api/session/{firefox['id']}", headers=PAGE)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([b["id"] for b in r.json()["browsers"]], [d["browser"]["id"]])
        self.assertEqual(other.get("/api/board").status_code, 401)
        self.assertEqual(self.c.delete("/api/session/0123456789abcdef", headers=PAGE).status_code, 404)
        r = self.c.delete("/api/session", headers=PAGE)
        self.assertEqual((r.status_code, r.json()["signed_in"]), (200, False))
        self.assertEqual(self.c.get("/api/board").status_code, 401)
        self.assertEqual(auth.sessions(), [])

    def test_a_session_ended_at_the_server_is_over(self):
        self.snapshot()
        sid = self.sign_in().json()["browser"]["id"]
        self.assertTrue(auth.end_session(sid))
        self.assertEqual(self.c.get("/api/board").status_code, 401)
        self.assertFalse(auth.end_session(sid))
        self.assertFalse(auth.end_session("../codes"))


class CsrfTests(Base):
    def post_code(self, c=None, **headers):
        code, _ = auth.new_code()
        return (c or self.c).post("/api/session", json={"code": code}, headers=headers), code

    def test_sign_in_needs_the_pages_header(self):
        r, code = self.post_code(origin=ORIGIN)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "csrf"))
        self.assertTrue(auth.use_code(code), "a refused request doesn't use the code")
        for value in ("0", "true", ""):
            r, _ = self.post_code(**{"x-bromigos-board": value})
            self.assertEqual(r.status_code, 403, value)
        r, _ = self.post_code(**PAGE)
        self.assertEqual(r.status_code, 200)

    def test_another_site_cant_ask(self):
        for h in ({"origin": "https://evil.example.org"}, {"origin": "http://myserver.local"},
                  {"origin": "https://home-myserver.local"}, {"origin": "null"},
                  {"sec-fetch-site": "cross-site"}, {"sec-fetch-site": "same-site"}):
            r, code = self.post_code(**{**PAGE, **h})
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "csrf"), h)
            self.assertTrue(auth.use_code(code))

    def test_a_form_post_is_refused(self):
        code, _ = auth.new_code()
        r = self.c.post("/api/session", content=f"code={code}",
                        headers={**PAGE, "content-type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 415)
        self.assertTrue(auth.use_code(code), "a refused request doesn't use the code")

    def test_signed_in_changes_need_it_too(self):
        self.sign_in()
        other = client(self.app)
        self.sign_in(other)
        sid = other.get("/api/session").json()["browser"]["id"]
        self.assertEqual(self.c.delete(f"/api/session/{sid}").status_code, 403)
        self.assertEqual(self.c.delete("/api/session", headers={"origin": "https://evil.example.org",
                                                                "x-bromigos-board": "1"}).status_code, 403)
        self.assertEqual(len(auth.sessions()), 2)

    def test_reading_needs_nothing_more(self):
        self.snapshot()
        self.sign_in()
        self.assertEqual(self.c.get("/api/board").status_code, 200)


class SourceTests(Base):
    def test_a_public_address_gets_403_whatever_it_asks(self):
        self.snapshot()
        value, _ = auth.new_session()
        for xff in ("203.0.113.5", "8.8.8.8", "2001:db8::1", "::ffff:8.8.8.8", "100.128.0.1", "172.32.0.1",
                    "not-an-address", "192.168.1.20 , 203.0.113.5"):
            c = client(self.app, xff=xff)
            c.cookies.set(auth.COOKIE, value)
            for method, path in (("GET", "/api/door"), ("GET", "/api/session"), ("GET", "/api/board"),
                                 ("GET", "/api/activity"), ("POST", "/api/session"), ("GET", "/api/nothing")):
                r = c.request(method, path, headers=PAGE)
                self.assertEqual(r.status_code, 403, (xff, path))
                self.assertEqual(r.json()["error"]["code"], "not-local")
                self.assertEqual(r.headers["cache-control"], "no-store")

    def test_the_home_network_and_the_labs_private_network_get_in(self):
        for xff in ("192.168.1.20", "10.1.2.3", "172.16.5.4", "100.64.0.7", "169.254.1.1", "127.0.0.1", "fd7a:115c:a1e0::1",
                    "fe80::1%eth0", "::1", "::ffff:192.168.1.2", "[fd00::5]", "203.0.113.5, 192.168.1.20"):
            r = client(self.app, xff=xff).get("/api/door")
            self.assertEqual(r.status_code, 200, xff)

    def test_with_no_forwarded_address_a_named_peer_is_refused(self):
        # TestClient's own peer is the word "testclient": not an address, so refused
        self.assertEqual(client(self.app, xff=None).get("/api/door").status_code, 403)


class ActivityStreamTests(Base):
    def job(self, state="succeeded", updated=NOW, jid="20261110-1012-backup.run-a3f0"):
        rec = json.loads((FIXTURES / "activity-list.json").read_text())["jobs"][0]
        rec.update(id=jid, state=state, updated_at=updated)
        d = self.path("var/lib/bromigos/activity/jobs")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{jid}.json").write_text(json.dumps(rec))
        return rec

    def events(self, text):
        out = []
        for block in text.split("\n\n"):
            lines = dict(x.split(": ", 1) for x in block.splitlines() if x and not x.startswith(":"))
            if "event" in lines:
                out.append((lines["event"], json.loads(lines["data"])))
        return out

    def test_the_jobs_then_each_change(self):
        self.job()
        self.sign_in()

        def later():
            time.sleep(0.25)
            self.job(updated=NOW + 1000)
            self.job(jid="20261110-1013-app.update-photos-b4c1", updated=NOW + 2000)
        t = threading.Thread(target=later)
        t.start()
        with self.c.stream("GET", "/api/activity") as r:
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
            text = "".join(r.iter_text())
        t.join()
        ev = self.events(text)
        self.assertEqual(ev[0][0], "snapshot")
        self.assertEqual([j["id"] for j in ev[0][1]["jobs"]], ["20261110-1012-backup.run-a3f0"])
        changed = [(e, d["id"], d["updated_at"]) for e, d in ev[1:]]
        self.assertIn(("job", "20261110-1012-backup.run-a3f0", NOW + 1000), changed)
        self.assertIn(("job", "20261110-1013-app.update-photos-b4c1", NOW + 2000), changed)
        self.assertTrue(self.path(paths.WANTED).exists())

    def test_signed_out_no_stream(self):
        self.job()
        r = self.c.get("/api/activity")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("backup", r.text)


if __name__ == "__main__":
    unittest.main()
