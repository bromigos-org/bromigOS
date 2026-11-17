#!/usr/bin/env python3
"""The lab's connector catalogue, made from its source rows so the import can be repeated:
homelab/share/lab/connectors.toml (docs/lab-connectors.md).

  tools/lab/connectors-import.py            rewrite the catalogue
  tools/lab/connectors-import.py --check    rewrite nothing; exit 1 when it's stale
  tools/lab/connectors-import.py --probe    ask each connector's address once, write checked.json

  --source FILE    the source rows (default tools/lab/connectors/starnet.json)
  --checked FILE   the liveness results (default tools/lab/connectors/checked.json)
  --out FILE       where the catalogue goes (default homelab/share/lab/connectors.toml; - prints it)
  --date DATE      --probe: the day to record (default today)

Where the rows come from. tools/lab/connectors/starnet.json is the data of two modules of
StarNet (https://github.com/androoAGI/starnet, commit e316231d, 2026-11-07; MIT, Copyright (c)
2026 Andrew Sims: LICENSE-starnet beside it), printed as JSON and indented with
`python -m json.tool --indent 1 --no-ensure-ascii`:

  connectors, order          sidecar/mcp/catalog.js: CATALOG and CATEGORY_ORDER
  platforms, platformOrder   sidecar/servicekeys-catalog.js: PLATFORMS and CATEGORY_ORDER

To import again, print those four from a newer StarNet into starnet.json and run this. The file
is data from somewhere else: it's read as JSON and nothing in it is run. A field this script
doesn't know stops the import, so a new one is kept or dropped on purpose (KEPT, DROPPED below).

What the import changes. Fields get plain names. What only StarNet's interface or its own code
uses is dropped. A row that works only through StarNet's own code, or through a sign-in client
StarNet registered, is kept and marked `listed_only` with the reason (LISTED_ONLY). Wording that
names StarNet's own screens and tools is reworded (REWORDED): each old text must still be there,
so an upstream edit stops the import instead of slipping past.

--probe is the only part that uses the network: one GET per address, a generic User-Agent, no
credentials, redirects not followed, nothing read but the status. A row on your own machine
(`local`) and a row with no address are never asked. It writes checked.json; the catalogue is
made from that file, so making it again never touches the network.
"""

import argparse
import concurrent.futures
import datetime
import http.client
import json
import re
import socket
import ssl
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent / "connectors"
SOURCE = HERE / "starnet.json"
CHECKED = HERE / "checked.json"
OUT = REPO / "homelab/share/lab/connectors.toml"

AUTH = {"none": "none", "apikey": "key", "oauth": "sign-in"}
# source field -> ours, in the order a row is written
CONNECTOR_KEPT = {"id": "id", "name": "name", "category": "category", "authType": "auth", "url": "url", "via": "via",
                  "local": "local", "official": "official", "homepage": "homepage", "keyHeader": "key_header",
                  "aliases": "aliases", "blurb": "summary"}
# transport: always "http" (checked). presets: buttons in StarNet's window. keyAuthRetired: moves a
# key saved in StarNet over to sign-in. staticOauth, googleApi, appPassword, deviceFlow: how
# StarNet's own code signs in; they decide listed_only and aren't copied.
CONNECTOR_DROPPED = ("transport", "presets", "keyAuthRetired", "staticOauth", "googleApi", "appPassword", "deviceFlow")
PLATFORM_KEPT = {"id": "id", "name": "name", "category": "category", "envVar": "env", "docsUrl": "docs",
                 "apiBase": "api_base", "apiVia": "api_via", "authHint": "auth_header",
                 "unattendedSupported": "unattended", "aliases": "aliases", "blurb": "summary", "note": "note",
                 "apiNotes": "api_notes"}
# retiredDocsUrls: mends a docs link saved in StarNet. unattendedReason: says what StarNet lacks;
# the row's note says what the service needs instead.
PLATFORM_DROPPED = ("retiredDocsUrls", "unattendedReason")
# our own fields, written after the source's
CONNECTOR_ORDER = list(CONNECTOR_KEPT.values()) + ["listed_only", "answered", "answer"]
PLATFORM_ORDER = list(PLATFORM_KEPT.values())

GOOGLE = ("The address is Google's own API, not a remote MCP server. It needs a Google sign-in that bromigOS "
          "registers and tools of our own on top. Neither is built.")
LISTED_ONLY = (
    (lambda r: r.get("googleApi") or r.get("staticOauth"), GOOGLE),
    (lambda r: r.get("appPassword"),
     "Not a remote MCP server. It needs mail tools of our own that speak IMAP and SMTP with a Google app "
     "password. They aren't built."),
    (lambda r: r.get("deviceFlow"),
     "GitHub's server doesn't register a sign-in by itself, so it needs a GitHub sign-in that bromigOS "
     "registers. It isn't set up."),
)

# (table, id, field, the source's words, ours)
REWORDED = (
    ("connector", "tavily", "summary", "Paste your Tavily API key.", "Needs a Tavily API key."),
    ("connector", "prisma", "summary", "Paste your Prisma API key.", "Needs a Prisma API key."),
    ("connector", "airtable", "summary", "Paste an Airtable personal access token.",
     "Needs an Airtable personal access token."),
    ("connector", "google-files", "summary", "files you grant to StarNet", "the files you pick"),
    ("connector", "github", "summary", " Sign in with GitHub using a short code — no API key needed.", ""),
    ("connector", "gmail", "summary", " Sign in with Google to connect your account.", ""),
    ("connector", "gmail-send", "summary", " Sign in with Google to connect your account.", ""),
    ("connector", "google-drive", "summary", " Sign in with Google to connect your account.", ""),
    ("connector", "google-calendar", "summary", " Sign in with Google to connect your account.", ""),
    ("connector", "google-docs", "summary", " Sign in with Google to connect your account.", ""),
    ("connector", "google-sheets", "summary", " Sign in with Google to connect your account.", ""),
    ("connector", "atlassian", "summary",
     "A newer direct OAuth endpoint is under verification; use the proven Zapier route until StarNet completes "
     "an authenticated tool call.",
     "Atlassian's own server isn't listed yet: reach both through Zapier."),
    ("platform", "etsy", "summary", "Public/manual API work only — persistent shop automation is not connected.",
     "Public listing data with an API key. Shop automation needs Etsy's OAuth."),
    ("platform", "etsy", "note",
     "MANUAL OAUTH ONLY: Etsy private/write endpoints need OAuth 2.0; access tokens expire after one hour. StarNet "
     "does not refresh them yet, so this key cannot be enabled for scheduled, messaged, or Night Shift runs.",
     "Etsy's private and write endpoints need OAuth 2.0, and its access tokens expire after one hour. A key alone "
     "reaches the public endpoints only, so nothing here can run unattended."),
    ("platform", "stripe", "note",
     "Stripe also has a one-click MCP connector in APPS — use that if you want tools instead of raw REST.",
     "Stripe is also a one-click connector: use that for tools instead of raw REST."),
    ("platform", "notion", "note",
     "Notion also has a one-click OAuth connector in APPS — that is usually the easier route.",
     "Notion is also a one-click connector with a sign-in, usually the easier route."),
    ("platform", "github", "note", "GitHub also has a one-click MCP connector in APPS.",
     "GitHub is also listed as a one-click connector."),
    ("platform", "jina", "summary", "Cleaner page-text extraction for web_fetch — pages",
     "Cleaner page-text extraction: pages"),
    ("platform", "jina", "note",
     "Optional. StarNet uses this automatically for web_fetch when connected; without it pages still load, just "
     "with cruder text extraction. Jina's keyless tier no longer works.",
     "Jina's keyless tier no longer works: every request needs a key."),
    ("platform", "porkbun", "note",
     "save the secret as a second KEYS entry named \"Porkbun Secret\" and enable API access per-domain in the "
     "Porkbun dashboard.",
     "so it needs a second secret beside PORKBUN_API_KEY. Enable API access per domain in the Porkbun dashboard."),
    ("platform", "printify", "api_notes", "{\"file_name\":\"art.png\",\"contents\":\"${file:path/art.png}\"}",
     "{\"file_name\":\"art.png\",\"contents\":\"<the file, base64>\"}"),
    ("platform", "printify", "api_notes",
     "Product documents are large: pass web_request select, e.g. [\"id\",\"variants[].id\",\"variants[].is_enabled\","
     "\"variants[].price\",\"print_areas\",\"images[].src\"].",
     "Product documents are large: read only the fields you need, such as id, variants[].id, "
     "variants[].is_enabled, variants[].price, print_areas and images[].src."),
)
# words that name StarNet's own screens and tools: none may reach the catalogue
UPSTREAM_ONLY = ("starnet", "night shift", "web_request", "web_fetch", "${file:", " in apps", "keys entry", "commander")

UA = "liveness-check/1.0"
TIMEOUT = 8
WIDTH = 110

HEADER = """\
# The lab's connector catalogue (docs/lab-connectors.md): services an agent in your lab could
# reach. A [[connector]] is a remote MCP server ("one-click": an address, and at most a sign-in
# or a key). A [[platform]] has no such server: an agent reaches its REST API with a key ("paste
# a key"). `bromigos lab connectors` lists, searches and shows them (bromigos_homelab.connectors).
# It's a catalogue only: nothing here connects, signs in or keeps a key yet.
#
# Made by tools/lab/connectors-import.py from tools/lab/connectors/: change those, never this
# file. The rows are derived from StarNet's catalogue (https://github.com/androoAGI/starnet),
# MIT, Copyright (c) 2026 Andrew Sims. The notice is LICENSE-starnet beside this file, installed
# as /usr/share/licenses/bromigos-lab/LICENSE-starnet. bromigOS isn't part of StarNet and StarNet
# doesn't endorse it; the marks and some of the wording here are ours.
#
# Installed as /usr/share/bromigos/homelab/lab/connectors.toml (bromigos-lab).
#
# checked                  the day each connector's address was asked, once, with no credentials
# connector_categories     the order the one-click connectors' categories are listed in
# platform_categories      the same, for the key platforms
#
# [[connector]]            a remote MCP server (Streamable HTTP)
#   id, name, category     its id (unique among connectors), its name, one of connector_categories
#   auth                   none | key | sign-in (OAuth in a browser)
#   url                    its address: https, or http on this machine for a `local` row
#   via                    for a row with no address of its own: the connector that reaches it
#   local                  true: the server runs on your own machine, and you start it
#   official               true: the service's own maker runs the server
#   homepage               the service's site
#   key_header             the header a key goes in, when it isn't Authorization: Bearer
#   aliases                other words people type for it (search matches them)
#   summary                one or two sentences on what it does
#   listed_only            why bromigOS can't offer it yet: it needs a sign-in or code of our own
#   answered               whether the address answered on `checked` (absent: never asked)
#   answer                 the HTTP status it gave, or why there was none
#
# [[platform]]             a service with a REST API and no MCP server
#   id, name, category     its id (unique among platforms), its name, one of platform_categories
#   env                    the environment variable its key goes in
#   docs, api_base         its API's documentation and base address
#   api_via                the API it's reached through, when it has none of its own
#   auth_header            how the key is sent, as a header line (absent: see `note` and the docs)
#   unattended             false: a key alone can't run it unattended (the note says why)
#   aliases, summary       as above
#   note                   what to know before you use it
#   api_notes              checked notes on the API itself, for whoever calls it
"""


class Refused(ValueError):
    """The source, or the results, aren't what this import can take (said in plain words)."""


def _fail(msg):
    raise Refused(msg)


def _text(v, where):
    if not isinstance(v, str):
        _fail(f"{where}: {v!r} isn't text")
    if re.search(r"[\x00-\x1f\x7f-\x9f]", v):
        _fail(f"{where}: has a control character")
    return v.strip()


def _value(key, v, where):
    if key in ("official", "local", "unattended"):
        if not isinstance(v, bool):
            _fail(f"{where}: {v!r} isn't true or false")
        return v
    if key == "aliases":
        if not isinstance(v, list):
            _fail(f"{where}: {v!r} isn't a list")
        return [_text(x, where) for x in v]
    return _text(v, where)


def _map(row, kept, dropped, table):
    if not isinstance(row, dict) or not isinstance(row.get("id"), str):
        _fail(f"a {table} row has no id")
    where = f"{table} {row['id']}"
    unknown = sorted(set(row) - set(kept) - set(dropped))
    if unknown:
        _fail(f"{where}: {', '.join(unknown)} is new to this import: keep it or drop it, in the script")
    out = {}
    for src, ours in kept.items():
        if src in row:
            out[ours] = _value(ours, row[src], f"{where}.{src}")
    return out


def connector(row):
    out = _map(row, CONNECTOR_KEPT, CONNECTOR_DROPPED, "connector")
    where = f"connector {out['id']}"
    if row.get("transport") != "http":
        _fail(f"{where}: transport {row.get('transport')!r} isn't http")
    if out.get("auth") not in AUTH:
        _fail(f"{where}: authType {out.get('auth')!r} isn't one of {', '.join(AUTH)}")
    out["auth"] = AUTH[out["auth"]]
    out["url"] = urllib.parse.urldefrag(out.get("url", ""))[0]     # a fragment only tells StarNet's rows apart
    for key in ("url", "local"):
        if not out.get(key):
            out.pop(key, None)
    for test, why in LISTED_ONLY:
        if test(row):
            out["listed_only"] = why
            break
    return out


def platform(row):
    out = _map(row, PLATFORM_KEPT, PLATFORM_DROPPED, "platform")
    if out.get("unattended", True):
        out.pop("unattended", None)                                 # only false says anything
    return out


def _reword(tables):
    for table, rid, field, old, new in REWORDED:
        rows = [r for r in tables[table] if r["id"] == rid]
        if len(rows) != 1 or rows[0].get(field, "").count(old) != 1:
            _fail(f"{table} {rid}.{field}: the words this import rewords aren't there once: {old[:60]!r}")
        rows[0][field] = rows[0][field].replace(old, new)
    for table, rows in tables.items():
        for r in rows:
            for key, v in r.items():
                for s in v if isinstance(v, list) else [v]:
                    hit = [w for w in UPSTREAM_ONLY if isinstance(s, str) and w in s.lower()]
                    if hit:
                        _fail(f"{table} {r['id']}.{key}: still says {hit[0]!r}, which only means something in "
                              "StarNet: reword it (REWORDED)")


def _order(rows, cats, table):
    for r in rows:
        if r.get("category") not in cats:
            _fail(f"{table} {r['id']}: category {r.get('category')!r} isn't in the source's order")
    return sorted(rows, key=lambda r: (cats.index(r["category"]), r["name"].casefold(), r["id"]))


def build(source, checked):
    """The catalogue as a dict, from the source's JSON and the liveness results."""
    if not isinstance(source, dict) or sorted(source) != ["connectors", "order", "platformOrder", "platforms"]:
        _fail("the source isn't {connectors, order, platforms, platformOrder}")
    ccats = [_text(c, "order") for c in source["order"]]
    pcats = [_text(c, "platformOrder") for c in source["platformOrder"]]
    tables = {"connector": [connector(r) for r in source["connectors"]],
              "platform": [platform(r) for r in source["platforms"]]}
    _reword(tables)
    day = checked.get("checked")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)):
        _fail("checked.json has no `checked` day (2026-11-17)")
    results = checked.get("results") or {}
    ids = {r["id"] for r in tables["connector"]}
    stray = sorted(set(results) - ids)
    if stray:
        _fail(f"checked.json has results for rows the source lacks: {', '.join(stray)}")
    for r in tables["connector"]:
        got = results.get(r["id"])
        if asked(r) and not got:
            _fail(f"connector {r['id']}: no result in checked.json (run --probe)")
        if got:
            if not asked(r):
                _fail(f"connector {r['id']}: checked.json has a result for an address that's never asked")
            if not isinstance(got.get("answered"), bool):
                _fail(f"connector {r['id']}: checked.json's `answered` isn't true or false")
            r["answered"], r["answer"] = got["answered"], _text(got.get("answer"), f"checked.json {r['id']}")
    return {"format": 1, "checked": day, "connector_categories": ccats, "platform_categories": pcats,
            "connector": _order(tables["connector"], ccats, "connector"),
            "platform": _order(tables["platform"], pcats, "platform")}


# ------------------------------------------------------------------ writing TOML
def _string(s):
    return json.dumps(s, ensure_ascii=False)


def _fill(words, first, sep=" ", end=""):
    """words joined by sep into lines no wider than WIDTH; the first line has `first` columns taken."""
    lines, line, room = [], "", WIDTH - first - len(end)
    for word in words:
        if line and len(line) + len(sep) + len(word) > room:
            lines.append(line)
            line, room = word, WIDTH - len(end)
        else:
            line = f"{line}{sep}{word}" if line else word
    return lines + [line]


def _long(key, s):
    """A long string as a multi-line one, a backslash ending each line (as jobs.toml's notes)."""
    body = s.replace("\\", "\\\\")
    if '"""' in body or body.endswith('"'):
        body = body.replace('"', '\\"')
    lines = _fill(body.split(" "), len(key) + 6, end=" \\")
    return f'{key} = """' + " \\\n".join(lines) + '"""'


def _line(key, v):
    if isinstance(v, bool):
        return f"{key} = {'true' if v else 'false'}"
    if isinstance(v, int):
        return f"{key} = {v}"
    if isinstance(v, list):
        one = f"{key} = [" + ", ".join(_string(x) for x in v) + "]"
        if len(one) <= WIDTH:
            return one
        return f"{key} = [\n" + "".join(f"  {x}\n" for x in _fill([_string(x) + "," for x in v], 2, end="  ")) + "]"
    one = f"{key} = {_string(v)}"
    if len(one) <= WIDTH or "  " in v or " " not in v or v != v.strip():
        return one
    return _long(key, v)


def render(doc):
    out = [HEADER.rstrip("\n")]
    for key in ("format", "checked", "connector_categories", "platform_categories"):
        out.append(_line(key, doc[key]))
    for table, order, cats in (("connector", CONNECTOR_ORDER, doc["connector_categories"]),
                               ("platform", PLATFORM_ORDER, doc["platform_categories"])):
        last = None
        for r in doc[table]:
            if r["category"] != last:
                last = r["category"]
                out.append(f"\n# ---- {table}s: {last}")
            out.append(f"\n[[{table}]]")
            extra = sorted(set(r) - set(order))
            if extra:
                _fail(f"{table} {r['id']}: no place to write {', '.join(extra)}")
            out += [_line(k, r[k]) for k in order if k in r]
    text = "\n".join(out) + "\n"
    if tomllib.loads(text) != doc:                                 # what's written is what was meant
        _fail("the catalogue didn't read back as it was written (a bug in this script)")
    return text


# ------------------------------------------------------------------ the liveness check
def asked(row):
    """Whether --probe asks this row's address: never one on your own machine, never a row without one."""
    return bool(row.get("url")) and not row.get("local")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def probe_one(url, timeout=TIMEOUT):
    """One GET: {"answered", "answer"}. Something is there when a status comes back that isn't
    "not found" (404), "gone" (410) or the server's own failure (5xx)."""
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
        e.close()
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        why = getattr(e, "reason", e)
        if isinstance(why, socket.gaierror):
            return {"answered": False, "answer": "host not found"}
        if isinstance(why, (TimeoutError, socket.timeout)) or "timed out" in str(why):
            return {"answered": False, "answer": "timed out"}
        if isinstance(why, ssl.SSLError):
            return {"answered": False, "answer": "TLS error"}
        if isinstance(why, ConnectionRefusedError):
            return {"answered": False, "answer": "connection refused"}
        return {"answered": False, "answer": "no connection"}
    return {"answered": status not in (404, 410) and status < 500, "answer": str(status)}


def probe(rows, day, ask=probe_one):
    """checked.json's content: each address asked once (rows sharing one share its result)."""
    urls = sorted({r["url"] for r in rows if asked(r)})
    for u in urls:
        if not u.startswith("https://"):
            _fail(f"{u}: only https addresses are asked")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        got = dict(zip(urls, pool.map(ask, urls)))
    return {"checked": day,
            "how": f"one GET per address, User-Agent {UA}, no credentials, redirects not followed, {TIMEOUT} s",
            "results": {r["id"]: got[r["url"]] for r in sorted(rows, key=lambda r: r["id"]) if asked(r)}}


def _json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    p = argparse.ArgumentParser(description="Make the lab's connector catalogue from its source rows.")
    p.add_argument("--source", default=str(SOURCE))
    p.add_argument("--checked", default=str(CHECKED))
    p.add_argument("--out", default=str(OUT))
    p.add_argument("--check", action="store_true", help="rewrite nothing; exit 1 when the catalogue is stale")
    p.add_argument("--probe", action="store_true", help="ask each connector's address once and write --checked")
    p.add_argument("--date", default=datetime.date.today().isoformat(), help="--probe: the day to record")
    a = p.parse_args(argv)
    try:
        source = _json(a.source)
        if a.probe:
            rows = [connector(r) for r in source.get("connectors", [])]
            doc = probe(rows, a.date)
            Path(a.checked).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
            n = sum(1 for r in doc["results"].values() if r["answered"])
            print(f"{a.checked}: {n} of {len(doc['results'])} answered; {len(rows) - len(doc['results'])} never asked")
            return 0
        doc = build(source, _json(a.checked))
        text = render(doc)
    except (Refused, OSError, json.JSONDecodeError) as e:
        print(f"connectors-import: {e}", file=sys.stderr)
        return 1
    if a.out == "-":
        sys.stdout.write(text)
        return 0
    out = Path(a.out)
    if a.check:
        if not out.is_file() or out.read_text(encoding="utf-8") != text:
            print(f"connectors-import: {out} is stale: run tools/lab/connectors-import.py", file=sys.stderr)
            return 1
        return 0
    out.write_text(text, encoding="utf-8")
    print(f"{out}: {len(doc['connector'])} connectors, {len(doc['platform'])} platforms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
