"""The connector catalogue (share/lab/connectors.toml), connectors.py's API, `bromigos lab
connectors`, and the script that makes the file (tools/lab/connectors-import.py). The liveness
check is asked of a server on this machine: nothing reaches a network.

    PYTHONPATH=lib python -m unittest tests.test_lab_connectors
"""
import contextlib
import copy
import http.server
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from bromigos_homelab import connectors as C

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "homelab/bin/bromigos-lab"
SHIPPED = ROOT / "homelab/share/lab/connectors.toml"
TOOL = ROOT / "tools/lab/connectors-import.py"
SOURCE = ROOT / "tools/lab/connectors/starnet.json"
CHECKED = ROOT / "tools/lab/connectors/checked.json"
# the rows that work only through a sign-in or code of our own: listed, never on offer
LISTED_ONLY = {"github", "gmail", "gmail-app-password", "gmail-send", "google-calendar", "google-docs",
               "google-drive", "google-files", "google-sheets"}
# the rows marked as able to spend money or contact people (tools/lab/connectors-import.py: ACTS)
ACTS = {("one-click", "adspirer"), ("one-click", "composio"), ("one-click", "markifact"), ("one-click", "zapier"),
        ("key", "bland"), ("key", "lob"), ("key", "vapi")}

GOOD = """
format = 1
checked = "2026-11-17"
connector_categories = ["Docs", "Local"]
platform_categories = ["Shops"]

[[connector]]
id = "docs"
name = "Docs"
category = "Docs"
auth = "none"
url = "https://mcp.example.org/mcp"
official = true
homepage = "https://example.org"
summary = "Reads the docs."
answered = true
answer = "405"

[[connector]]
id = "editor"
name = "Editor"
category = "Local"
auth = "none"
url = "http://127.0.0.1:8000/mcp"
local = true
official = true
homepage = "https://example.org/editor"
summary = "Drives an editor on this machine."

[[platform]]
id = "shop"
name = "Shop"
category = "Shops"
env = "SHOP_API_KEY"
docs = "https://example.org/docs"
api_base = "https://api.example.org/v1"
auth_header = "Authorization: Bearer ${SHOP_API_KEY}"
summary = "Sells things."
"""


def setUpModule():
    """The checkout's catalogue, never an installed bromigos-lab's (it comes first in
    connectors.paths(), and may be an older one)."""
    global _SHARE
    _SHARE = mock.patch.object(C, "SHARE", "/nonexistent")
    _SHARE.start()


def tearDownModule():
    _SHARE.stop()


def tool():
    spec = importlib.util.spec_from_file_location("connectors_import", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def changed(old, new, count=1):
    """GOOD with one thing changed, as a parsed file."""
    assert GOOD.count(old) >= count, old
    return tomllib.loads(GOOD.replace(old, new, count))


class ShippedTest(unittest.TestCase):
    def setUp(self):
        self.cat = C.load()

    def test_the_shipped_file_loads_and_validates(self):
        self.assertEqual(C.where(), str(SHIPPED))
        self.assertEqual(C.validate(), [])
        self.assertEqual(self.cat["checked"], "2026-11-17")

    def test_counts(self):
        self.assertEqual(len(C.rows(self.cat, kind="one-click", every=True)), 74)
        self.assertEqual(len(C.rows(self.cat, kind="key", every=True)), 38)
        self.assertEqual(len(self.cat["categories"]["one-click"]), 12)
        self.assertEqual(len(self.cat["categories"]["key"]), 8)

    def test_rows_that_need_our_own_sign_in_are_listed_and_never_on_offer(self):
        listed = {r["id"] for r in self.cat["rows"] if C.state(r) == "listed only"}
        self.assertEqual(listed, LISTED_ONLY)
        on_offer = {r["id"] for r in C.rows(self.cat, kind="one-click")}
        self.assertFalse(on_offer & LISTED_ONLY)
        for r in self.cat["rows"]:
            if r["id"] in LISTED_ONLY and r["kind"] == "one-click":
                self.assertTrue(C.needs(r).startswith("Listed only. "), r["id"])
                self.assertTrue(r["listed_only"].endswith("."), r["id"])

    def test_every_row_stands_somewhere_and_every_key_platform_is_on_offer(self):
        states = [C.state(r) for r in self.cat["rows"]]
        self.assertEqual(set(states), {"offered", "listed only", "no address", "no answer"})
        self.assertEqual(len(C.rows(self.cat, kind="key")), 38)
        self.assertEqual(len(C.rows(self.cat)), len([s for s in states if s == "offered"]))

    def test_the_liveness_check_is_recorded_for_every_address_that_can_be_asked(self):
        for r in C.rows(self.cat, kind="one-click", every=True):
            asked = bool(r.get("url")) and not r.get("local")
            self.assertEqual("answered" in r, asked, r["id"])
        local = C.find(self.cat, "unreal-engine")[0]
        self.assertTrue(local["local"])
        self.assertEqual(C.state(local), "offered")
        self.assertEqual(C.state(C.find(self.cat, "atlassian")[0]), "no address")
        self.assertEqual(C.find(self.cat, "atlassian")[0]["via"], "zapier")

    def test_every_address_is_https_but_the_local_one(self):
        for r in self.cat["rows"]:
            for key in ("url", "homepage", "docs", "api_base"):
                if key in r and not r.get("local"):
                    self.assertTrue(r[key].startswith("https://"), (r["id"], key))
        self.assertEqual([r["id"] for r in self.cat["rows"] if r.get("local")], ["unreal-engine"])

    def test_rows_that_spend_money_or_contact_people_say_what_they_can_do(self):
        self.assertEqual({(r["kind"], r["id"]) for r in self.cat["rows"] if "acts" in r}, ACTS)
        for r in self.cat["rows"]:
            if "acts" in r:
                self.assertRegex(r["acts"], r"^It .*\.$", r["id"])
        self.assertIn("spend real ad budget", C.find(self.cat, "adspirer")[0]["acts"])
        self.assertIn("calls to real phones", C.find(self.cat, "bland", "key")[0]["acts"])
        self.assertNotIn("acts", C.find(self.cat, "tavily")[0])
        self.assertEqual(C.describe(C.find(self.cat, "zapier")[0])["acts"], C.find(self.cat, "zapier")[0]["acts"])

    def test_api_notes_are_kept(self):
        notes = C.find(self.cat, "printify", "key")[0]["api_notes"]
        self.assertIn("EVERY variant of the product must be in the request", notes)

    def test_the_source_is_credited_and_never_named_in_a_row(self):
        text = SHIPPED.read_text(encoding="utf-8")
        head = text[:text.index("\nformat = 1")]
        self.assertIn("derived from StarNet's catalogue", head)
        self.assertIn("Copyright (c) 2026 Andrew Sims", head)
        self.assertIn("StarNet\n# doesn't endorse it", head)
        self.assertNotIn("starnet", text[len(head):].lower())
        notice = (SHIPPED.parent / "LICENSE-starnet").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2026 Andrew Sims", notice)
        self.assertIn("Permission is hereby granted, free of charge", notice)
        self.assertEqual(notice, (SOURCE.parent / "LICENSE-starnet").read_text(encoding="utf-8"))

    def test_the_package_installs_the_catalogue_its_notice_and_its_page(self):
        script = (ROOT / "packaging/install-lab.sh").read_text(encoding="utf-8")
        self.assertIn('"$root"/homelab/share/lab/*.toml', script)                 # connectors.toml with the rest
        self.assertIn('"$root"/homelab/lib/bromigos_homelab/*.py', script)        # connectors.py with the rest
        self.assertIn('licenses/bromigos-lab/" "$root/homelab/share/lab/LICENSE-starnet"', script)
        self.assertIn("lab-connectors,", script)


class ValidateTest(unittest.TestCase):
    def test_a_good_file_has_no_problems(self):
        self.assertEqual(C.problems(tomllib.loads(GOOD)), [])

    def bad(self, old, new, says, count=1):
        found = C.problems(changed(old, new, count))
        self.assertTrue(any(says in p for p in found), found)

    def test_ids_are_unique_in_each_table(self):
        self.bad('id = "editor"', 'id = "docs"', "connector docs: the id is used 2 times")

    def test_an_address_is_https_unless_the_row_is_local(self):
        self.bad("https://mcp.example.org/mcp", "http://mcp.example.org/mcp",
                 "connector docs: url 'http://mcp.example.org/mcp' isn't an https address")
        self.bad("http://127.0.0.1:8000/mcp", "http://192.0.2.7:8000/mcp", "a local row's url is on this machine")
        self.bad("https://mcp.example.org/mcp", "https://user:pw@mcp.example.org/mcp", "isn't an https address")
        self.bad("https://api.example.org/v1", "ftp://api.example.org/v1", "platform shop: api_base")

    def test_auth_is_a_known_kind(self):
        self.bad('auth = "none"', 'auth = "magic"', "connector docs: auth 'magic' isn't one of none, key, sign-in")

    def test_an_env_name_is_capitals(self):
        for name in ("shop_api_key", "1SHOP", "SHOP-KEY", "SHOP KEY"):
            self.bad('env = "SHOP_API_KEY"', f'env = "{name}"', f"platform shop: env '{name}' isn't shaped like")

    def test_the_header_names_the_rows_own_variable(self):
        self.bad("${SHOP_API_KEY}", "${OTHER_KEY}", "auth_header")

    def test_an_unknown_key_a_missing_one_and_a_wrong_shape(self):
        self.bad('summary = "Sells things."', 'summary = "Sells things."\ncommand = "rm -rf /"',
                 "platform shop: 'command' isn't a key a row has")
        self.bad('summary = "Reads the docs."\n', "", "connector docs: no summary")
        self.bad("official = true", 'official = "yes"', "connector docs: official is true or false")

    def test_text_with_a_control_character_is_refused(self):
        self.bad('name = "Docs"', 'name = "Do\\u001b[31mcs"', "connector docs: name is empty")

    def test_a_category_is_one_the_file_lists(self):
        self.bad('category = "Shops"', 'category = "Elsewhere"', "category 'Elsewhere' isn't in platform_categories")

    def test_a_row_with_no_address_names_the_connector_that_reaches_it(self):
        self.bad('url = "https://mcp.example.org/mcp"\n', "", "no url, and no via")

    def test_acts_is_a_sentence_on_either_kind_of_row(self):
        for old in ('summary = "Reads the docs."', 'summary = "Sells things."'):
            self.assertEqual(C.problems(changed(old, old + '\nacts = "It can send post."')), [])
            self.assertTrue(any("acts is words" in p for p in C.problems(changed(old, old + "\nacts = true"))))
            self.assertTrue(any("acts is empty" in p for p in C.problems(changed(old, old + '\nacts = ""'))))

    def test_another_format_is_refused_whole(self):
        self.assertEqual(C.problems(changed("format = 1", "format = 2")),
                         ["format 2 isn't the one this bromigOS reads (1): update bromigos-lab"])

    def test_load_refuses_a_bad_file_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "connectors.toml")
            Path(path).write_text(GOOD.replace('env = "SHOP_API_KEY"', 'env = "shop key"'), encoding="utf-8")
            with self.assertRaises(C.CatalogueError) as e:
                C.load(path)
            self.assertIn(path, str(e.exception))
            self.assertIn("platform shop: env 'shop key' isn't shaped like PRINTIFY_API_KEY", str(e.exception))
            Path(path).write_text("format = [", encoding="utf-8")
            with self.assertRaises(C.CatalogueError) as e:
                C.load(path)
            self.assertIn("can't be read", str(e.exception))
            self.assertEqual(len(C.validate(path)), 1)
        with self.assertRaises(C.CatalogueError) as e:
            C.load("/nonexistent/connectors.toml")
        self.assertIn("no connectors.toml", str(e.exception))


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.cat = C.load()

    def ids(self, words, kind=None):
        return [(r["kind"], r["id"]) for r in C.search(self.cat, words, kind)]

    def test_a_name_finds_both_kinds(self):
        self.assertEqual(self.ids("stripe"), [("one-click", "stripe"), ("key", "stripe")])
        self.assertEqual(self.ids("STRIPE", "key"), [("key", "stripe")])
        self.assertEqual(self.ids(["Hugging", "Face"]), [("one-click", "huggingface")])

    def test_an_alias_finds_it(self):
        self.assertEqual(self.ids("jira"), [("one-click", "atlassian")])
        self.assertEqual(self.ids("gcal"), [("one-click", "google-calendar")])
        pod = self.ids("print on demand")
        self.assertIn(("key", "printify"), pod)
        self.assertIn(("key", "printful"), pod)
        self.assertTrue(all(kind == "key" for kind, _ in pod))

    def test_the_whole_name_comes_before_an_alias_and_a_part(self):
        found = self.ids("google drive")
        self.assertEqual(found[0], ("one-click", "google-drive"))        # its name
        self.assertIn(("one-click", "zapier"), found)                    # an alias of the bridge that reaches it
        self.assertLess(found.index(("one-click", "google-drive")), found.index(("one-click", "zapier")))
        self.assertEqual(self.ids("notion")[:2], [("one-click", "notion"), ("key", "notion")])

    def test_nothing_found_is_an_empty_list(self):
        self.assertEqual(self.ids("no such service anywhere"), [])
        self.assertEqual(self.ids("   "), [])

    def test_a_category_by_a_part_of_its_name(self):
        self.assertEqual(C.category_named(self.cat, None, "design"), "Design")
        self.assertEqual(C.category_named(self.cat, "key", "pay"), "Payments")
        self.assertIsNone(C.category_named(self.cat, None, "pay"))        # Payments, and Payments & Finance
        self.assertIsNone(C.category_named(self.cat, None, "nope"))
        self.assertEqual({r["id"] for r in C.rows(self.cat, category="Design")},
                         {"canva", "higgsfield", "webflow", "wix"})


class NeedsTest(unittest.TestCase):
    def setUp(self):
        self.cat = C.load()

    def needs(self, rid, kind="one-click"):
        return C.needs(C.find(self.cat, rid, kind)[0])

    def test_what_each_kind_of_row_needs_in_plain_words(self):
        self.assertEqual(self.needs("deepwiki"), "Nothing: no account and no key.")
        self.assertEqual(self.needs("tavily"), "An API key from Tavily, sent as a Bearer token.")
        self.assertEqual(self.needs("composio"), "An API key from Composio, sent in the x-consumer-api-key header.")
        self.assertEqual(self.needs("notion"), "A sign-in to Notion in your browser (OAuth).")
        self.assertEqual(self.needs("unreal-engine"),
                         "Nothing to sign in to. The server runs on your own machine, so start it first.")
        self.assertEqual(self.needs("atlassian"), "No address of its own: it's reached through the zapier connector.")
        self.assertIn("a Google sign-in that bromigOS registers", self.needs("gmail"))
        self.assertEqual(self.needs("printify", "key"), "An API key from Printify, in PRINTIFY_API_KEY.")
        self.assertEqual(self.needs("etsy", "key"), "An API key from Etsy, in ETSY_API_KEY. Its note and its docs "
                                                    "say how the key is sent. A key alone can't run it unattended.")


class CliTest(unittest.TestCase):
    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = C.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def js(self, *argv):
        code, out, err = self.cli(*argv, "--json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_list_shows_what_is_on_offer_by_category(self):
        code, out, err = self.cli("list")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("ONE-CLICK CONNECTORS: remote MCP servers (", out)
        self.assertIn("KEY PLATFORMS: REST APIs, reached with a key (38 of 38)", out)
        self.assertLess(out.index("\nDocs & Knowledge\n"), out.index("\nSearch & Research\n"))
        self.assertRegex(out, r"\n  deepwiki +DeepWiki +no sign-in +Ask natural-language questions")
        self.assertRegex(out, r"\n  printify +Printify +PRINTIFY_API_KEY +Print-on-demand")
        self.assertNotRegex(out, r"\n  gmail ")
        self.assertIn("more aren't on offer (--all lists them): 9 listed only, 1 no address of its own", out)
        self.assertIn("connecting one to an agent isn't built yet", out)
        self.assertEqual(self.cli()[1], out)                            # no verb: list

    def test_list_all_adds_the_rest_and_says_why(self):
        code, out, _ = self.cli("list", "--all", "--kind", "one-click")
        self.assertEqual(code, 0)
        self.assertIn("(74 of 74)", out)
        self.assertNotIn("KEY PLATFORMS", out)
        self.assertRegex(out, r"\n  gmail +Gmail +a sign-in +\(listed only: it needs a sign-in or code of our own\)")
        self.assertRegex(out, r"\n  atlassian +Jira & Confluence +a sign-in +\(no address of its own\)")
        self.assertNotIn("more aren't on offer", out)

    def test_list_by_kind_and_category(self):
        rows = self.js("list", "--kind", "key", "--category", "physical")["rows"]
        self.assertEqual([r["id"] for r in rows], ["duffel", "lob", "lulu"])
        self.assertEqual({r["category"] for r in rows}, {"Physical World"})
        code, out, err = self.cli("list", "--category", "nowhere")
        self.assertEqual((code, out), (3, ""))
        self.assertIn("no one category matches 'nowhere'", err)
        code, _, err = self.cli("list", "stripe")
        self.assertEqual(code, 2)
        self.assertIn("bromigos lab connectors search stripe", err)

    def test_list_json(self):
        doc = self.js("list")
        self.assertEqual(doc["checked"], "2026-11-17")
        self.assertTrue(all(r["state"] == "offered" for r in doc["rows"]))
        self.assertEqual(len([r for r in doc["rows"] if r["kind"] == "key"]), 38)
        every = self.js("list", "--all")["rows"]
        self.assertEqual(len(every), 112)
        gmail = next(r for r in every if r["id"] == "gmail")
        self.assertEqual(gmail["state"], "listed only")
        self.assertTrue(gmail["needs"].startswith("Listed only. "))

    def test_search(self):
        code, out, _ = self.cli("search", "google", "drive")
        self.assertEqual(code, 0)
        self.assertRegex(out.splitlines()[0],
                         r"^one-click connector +google-drive +Google Drive +a sign-in +\(listed only")
        self.assertEqual([(r["kind"], r["id"]) for r in self.js("search", "stripe")["rows"]],
                         [("one-click", "stripe"), ("key", "stripe")])
        code, out, _ = self.cli("search", "no", "such", "thing")
        self.assertEqual((code, out), (0, "Nothing in the catalogue is called 'no such thing'.\n"))
        self.assertEqual(self.js("search", "no such thing")["rows"], [])
        self.assertEqual(self.cli("search")[0], 2)

    def test_show_a_key_platform(self):
        code, out, _ = self.cli("show", "printify")
        self.assertEqual(code, 0)
        self.assertIn("Printify (key platform) · Commerce & Print-on-Demand", out)
        self.assertRegex(out, r"Key goes in +PRINTIFY_API_KEY\n")
        self.assertRegex(out, r"Sent as +Authorization: Bearer \$\{PRINTIFY_API_KEY\}\n")
        self.assertRegex(out, r"Docs +https://developers\.printify\.com/\n")
        self.assertRegex(out, r"API base +https://api\.printify\.com/v1\n")
        self.assertRegex(out, r"Note +Create a personal access token")
        self.assertRegex(out, r"API notes +Mockups are read-only")
        self.assertNotIn("Can act", out)
        self.assertRegex(self.cli("show", "lob")[1], r"Can act +It can send real postcards, letters and cheques")
        self.assertIn("connecting one to an agent isn't built yet", out)
        self.assertRegex(self.cli("show", "supliful")[1], r"API base +https://\{your-store\}\.myshopify\.com/admin/api "
                                                          r"\(through the Shopify Admin API\)")

    def test_show_a_one_click_connector(self):
        code, out, _ = self.cli("show", "tavily")
        self.assertEqual(code, 0)
        self.assertIn("Tavily (one-click connector) · Search & Research", out)
        self.assertRegex(out, r"Address +https://mcp\.tavily\.com/mcp\n")
        self.assertRegex(out, r"Sign-in +an API key\n")
        self.assertRegex(out, r"Last check +2026-11-17: answered \(\d+\)\n")
        self.assertNotIn("Can act", out)
        self.assertRegex(self.cli("show", "zapier")[1], r"Can act +It acts in the apps you connect to it")
        out = self.cli("show", "replaid")[1]
        self.assertRegex(out, r"Last check +2026-11-17: didn't answer \(")
        out = self.cli("show", "unreal-engine")[1]
        self.assertRegex(out, r"Address +http://127\.0\.0\.1:8000/mcp\n")
        self.assertRegex(out, r"Last check +never asked: it runs on your own machine\n")
        out = self.cli("show", "gmail")[1]
        self.assertRegex(out, r"Needs +Listed only\. The address is Google's own API")

    def test_show_an_id_both_kinds_have(self):
        code, out, _ = self.cli("show", "stripe")
        self.assertEqual(code, 0)
        self.assertLess(out.index("Stripe (one-click connector)"), out.index("Stripe (key platform)"))
        self.assertNotIn("(one-click connector)", self.cli("show", "stripe", "--kind", "key")[1])
        rows = self.js("show", "stripe")["rows"]
        self.assertEqual([r["kind"] for r in rows], ["one-click", "key"])
        self.assertEqual(rows[0]["url"], "https://mcp.stripe.com/")
        self.assertEqual(rows[0]["auth"], "key")
        self.assertIs(rows[0]["answered"], True)
        self.assertEqual(rows[1]["env"], "STRIPE_API_KEY")
        self.assertEqual(rows[1]["needs"], "An API key from Stripe, in STRIPE_API_KEY.")

    def test_show_an_id_nothing_has(self):
        code, out, err = self.cli("show", "strip")
        self.assertEqual((code, out), (3, ""))
        self.assertIn("nothing has the id 'strip'. Close: stripe", err)
        self.assertEqual(self.cli("show")[0], 2)
        self.assertEqual(self.cli("show", "a", "b")[0], 2)

    def test_a_bad_catalogue_is_refused_in_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "connectors.toml")
            Path(path).write_text(GOOD.replace('auth = "none"', 'auth = "magic"', 1), encoding="utf-8")
            with mock.patch.dict(os.environ, {"BROMIGOS_LAB_CONNECTORS": path}):
                code, out, err = self.cli("list")
                self.assertEqual((code, out), (4, ""))
                self.assertIn("isn't a connector catalogue this bromigOS can use", err)
                self.assertIn("connector docs: auth 'magic' isn't one of none, key, sign-in", err)
                code, out, _ = self.cli("show", "docs", "--json")
                self.assertEqual(code, 4)
                self.assertIn("auth 'magic'", json.loads(out)["error"])

    def test_nothing_asks_for_or_reads_a_key(self):
        with mock.patch.dict(os.environ, {"STRIPE_API_KEY": "not-a-real-key-do-not-print"}), \
                mock.patch("builtins.input", side_effect=AssertionError("asked a question")):
            for argv in (["list", "--all"], ["show", "stripe"], ["show", "stripe", "--json"], ["search", "stripe"]):
                code, out, err = self.cli(*argv)
                self.assertEqual(code, 0)
                self.assertNotIn("do-not-print", out + err)

    def test_through_bromigos_lab(self):
        env = dict(os.environ, BROMIGOS_SHARE_DIR="/nonexistent", BROMIGOS_HOMELAB_CONFIG="/nonexistent")
        env.pop("BROMIGOS_LAB_CONNECTORS", None)
        run = subprocess.run([sys.executable, str(LAB), "connectors", "show", "printify", "--json"],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        [row] = json.loads(run.stdout)["rows"]
        self.assertEqual((row["kind"], row["env"]), ("key", "PRINTIFY_API_KEY"))
        text = LAB.read_text(encoding="utf-8")
        args = next(line for line in text.splitlines() if line.startswith("# bromigos:args="))
        self.assertIn("connectors [list [--kind one-click|key] [--category NAME] [--all] | search WORDS | show ID] "
                      "[--json]", args)
        self.assertIn("bromigos lab connectors search WORDS | show ID", text)


class _Statuses(http.server.BaseHTTPRequestHandler):
    """Answers /<status> with that status, and keeps what each request sent."""
    seen = []

    def do_GET(self):
        type(self).seen.append((self.path, dict(self.headers.items())))
        self.send_response(int(self.path.strip("/")))
        if self.path == "/302":
            self.send_header("Location", "/200")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class ImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = tool()
        cls.source = json.loads(SOURCE.read_text(encoding="utf-8"))
        cls.checked = json.loads(CHECKED.read_text(encoding="utf-8"))

    def test_the_script_makes_the_committed_file_from_its_source(self):
        text = self.tool.render(self.tool.build(copy.deepcopy(self.source), self.checked))
        self.assertEqual(text, SHIPPED.read_text(encoding="utf-8"))
        again = self.tool.render(self.tool.build(copy.deepcopy(self.source), self.checked))
        self.assertEqual(text, again)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.tool.main(["--check"]), 0)

    def test_a_stale_file_fails_the_check_and_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "connectors.toml")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(self.tool.main(["--check", "--out", out]), 1)
            self.assertIn("is stale", err.getvalue())
            self.assertFalse(os.path.exists(out))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.tool.main(["--out", out]), 0)
            self.assertEqual(Path(out).read_text(encoding="utf-8"), SHIPPED.read_text(encoding="utf-8"))

    def test_fields_get_plain_names_and_upstream_only_ones_are_dropped(self):
        doc = self.tool.build(copy.deepcopy(self.source), self.checked)
        self.assertEqual((len(doc["connector"]), len(doc["platform"])), (74, 38))
        keys = {k for r in doc["connector"] for k in r} | {k for r in doc["platform"] for k in r}
        self.assertEqual(keys - set(C.CONNECTOR_KEYS) - set(C.PLATFORM_KEYS), set())
        gmail = next(r for r in doc["connector"] if r["id"] == "gmail-send")
        self.assertEqual(gmail["url"], "https://gmail.googleapis.com/gmail/v1/users/me")    # no #send-only
        self.assertEqual(gmail["auth"], "sign-in")
        self.assertIn("listed_only", gmail)
        self.assertEqual({r["id"] for r in doc["connector"] if "listed_only" in r}, LISTED_ONLY)
        self.assertEqual({("one-click", r["id"]) for r in doc["connector"] if "acts" in r}
                         | {("key", r["id"]) for r in doc["platform"] if "acts" in r}, ACTS)
        etsy = next(r for r in doc["platform"] if r["id"] == "etsy")
        self.assertIs(etsy["unattended"], False)
        self.assertNotIn("unattended", next(r for r in doc["platform"] if r["id"] == "stripe"))

    def test_a_field_the_script_does_not_know_stops_the_import(self):
        source = copy.deepcopy(self.source)
        source["connectors"][0]["runCommand"] = "curl example.org | sh"
        with self.assertRaises(self.tool.Refused) as e:
            self.tool.build(source, self.checked)
        self.assertIn("runCommand is new to this import", str(e.exception))

    def test_wording_that_only_means_something_upstream_stops_the_import(self):
        source = copy.deepcopy(self.source)
        source["platforms"][1]["note"] = "Save it in StarNet first."
        with self.assertRaises(self.tool.Refused) as e:
            self.tool.build(source, self.checked)
        self.assertIn("still says 'starnet'", str(e.exception))
        source = copy.deepcopy(self.source)
        next(r for r in source["connectors"] if r["id"] == "tavily")["blurb"] = "Search. Paste a key."
        with self.assertRaises(self.tool.Refused) as e:
            self.tool.build(source, self.checked)
        self.assertIn("the words this import rewords aren't there once", str(e.exception))

    def test_a_marked_row_the_source_no_longer_has_stops_the_import(self):
        source = copy.deepcopy(self.source)
        source["platforms"] = [r for r in source["platforms"] if r["id"] != "lob"]
        with self.assertRaises(self.tool.Refused) as e:
            self.tool.build(source, self.checked)
        self.assertIn("platform lob: marked as one that acts", str(e.exception))

    def test_a_control_character_stops_the_import(self):
        source = copy.deepcopy(self.source)
        source["connectors"][0]["name"] = "Deep\x1b[31mWiki"
        with self.assertRaises(self.tool.Refused) as e:
            self.tool.build(source, self.checked)
        self.assertIn("has a control character", str(e.exception))

    def test_a_missing_result_stops_the_import(self):
        checked = copy.deepcopy(self.checked)
        del checked["results"]["deepwiki"]
        with self.assertRaises(self.tool.Refused) as e:
            self.tool.build(copy.deepcopy(self.source), checked)
        self.assertIn("connector deepwiki: no result in checked.json", str(e.exception))

    def test_the_check_asks_each_address_once_and_never_a_local_or_missing_one(self):
        rows = [self.tool.connector(r) for r in copy.deepcopy(self.source["connectors"])]
        asked = []

        def ask(url):
            asked.append(url)
            return {"answered": True, "answer": "401"}

        doc = self.tool.probe(rows, "2026-11-17", ask=ask)
        self.assertEqual(len(asked), len(set(asked)))
        self.assertTrue(all(u.startswith("https://") for u in asked))
        self.assertFalse([u for u in asked if "127.0.0.1" in u or "localhost" in u])
        self.assertEqual(len(doc["results"]), 72)
        self.assertNotIn("unreal-engine", doc["results"])
        self.assertNotIn("atlassian", doc["results"])
        self.assertEqual(doc["results"]["gmail"], doc["results"]["gmail-send"])      # one address, asked once
        self.assertEqual(sorted(doc["results"]), sorted(self.checked["results"]))
        with self.assertRaises(self.tool.Refused):
            self.tool.probe([{"id": "x", "url": "http://example.org/mcp"}], "2026-11-17", ask=ask)

    def test_what_counts_as_an_answer(self):
        _Statuses.seen = []
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Statuses)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            got = {s: self.tool.probe_one(f"{base}/{s}", timeout=5)
                   for s in (200, 302, 400, 401, 403, 405, 404, 410, 500)}
        finally:
            server.shutdown()
            server.server_close()
        for status in (200, 302, 400, 401, 403, 405):
            self.assertEqual(got[status], {"answered": True, "answer": str(status)})
        for status in (404, 410, 500):
            self.assertEqual(got[status], {"answered": False, "answer": str(status)})
        self.assertEqual([path for path, _ in _Statuses.seen].count("/200"), 1)       # the redirect isn't followed
        for _, headers in _Statuses.seen:
            sent = {k.lower(): v for k, v in headers.items()}
            self.assertEqual(sent["user-agent"], "liveness-check/1.0")
            self.assertEqual(set(sent) - {"host", "user-agent", "accept", "accept-encoding", "connection"}, set())
        closed = self.tool.probe_one(f"http://127.0.0.1:{server.server_address[1]}/200", timeout=5)
        self.assertEqual(closed, {"answered": False, "answer": "connection refused"})
        with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror(-2, "Name or service not known")):
            self.assertEqual(self.tool.probe_one("https://mcp.example.org/mcp", timeout=5),
                             {"answered": False, "answer": "host not found"})


if __name__ == "__main__":
    unittest.main()
