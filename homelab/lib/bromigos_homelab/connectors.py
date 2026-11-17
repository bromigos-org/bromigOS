"""The lab's connector catalogue (share/lab/connectors.toml; docs/lab-connectors.md): services an
agent in your lab could reach, and what each needs. `bromigos lab connectors` reads it.

Two kinds of row. A "one-click" connector is a remote MCP server: an address, and at most a
sign-in or a key. A "key" platform has no such server: an agent reaches its REST API with a key.

    from bromigos_homelab import connectors as C
    cat = C.load()                          # the catalogue, checked; CatalogueError says what's wrong
    C.validate()                            # the same check as a list of problems ([]: none)
    C.rows(cat)                             # the rows on offer, in the file's order
    C.rows(cat, kind="key", category="payments", every=True)
    C.search(cat, "google drive")           # by id, name or alias, the closest first
    C.find(cat, "stripe")                   # every row of that id: the connector and the platform
    C.state(row)                            # "offered" | "listed only" | "no address" | "no answer"
    C.needs(row)                            # "An API key from Tavily, sent as a Bearer token."
    C.chosen(cat, ["context7", "tavily"])   # the rows an agent may be given; Refused says why not
    C.in_use()                              # {"tavily": ["hermes"]}: what the lab's saved plan gives

A row is the file's own table plus `kind`. Nothing here connects to a service, signs in, or reads,
asks for or keeps a key: `bromigos lab provision` gives an agent the connectors chosen() passes
(agentprovision.py; docs/lab-agents.md). The file is data from somewhere else
(tools/lab/connectors-import.py), so load() refuses what it doesn't expect: an unknown key, an
address that isn't https, text with a control character in it.
"""
import argparse
import json
import os
import re
import sys
import textwrap
import tomllib
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SHARE = os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos"

FORMAT = 1
KINDS = ("one-click", "key")
KIND_WORDS = {"one-click": "one-click connector", "key": "key platform"}
AUTH = ("none", "key", "sign-in")
AUTH_WORDS = {"none": "no sign-in", "key": "a key", "sign-in": "a sign-in"}
LOOPBACK = ("127.0.0.1", "localhost", "::1")
ID = re.compile(r"[a-z0-9][a-z0-9-]*")
ENV = re.compile(r"[A-Z][A-Z0-9_]*")
HEADER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
TOP_KEYS = ("format", "checked", "connector_categories", "platform_categories", "connector", "platform")
# every key a row may have, and its shape: a misspelt one is a problem, not a key nobody reads
CONNECTOR_KEYS = {"id": str, "name": str, "category": str, "auth": str, "url": str, "via": str, "local": bool,
                  "official": bool, "homepage": str, "key_header": str, "aliases": list, "summary": str,
                  "listed_only": str, "acts": str, "answered": bool, "answer": str}
PLATFORM_KEYS = {"id": str, "name": str, "category": str, "env": str, "docs": str, "api_base": str, "api_via": str,
                 "auth_header": str, "unattended": bool, "aliases": list, "summary": str, "note": str,
                 "api_notes": str, "acts": str}
CONNECTOR_NEEDS = ("id", "name", "category", "auth", "official", "homepage", "summary")
PLATFORM_NEEDS = ("id", "name", "category", "env", "docs", "api_base", "summary")
_SHAPES = {str: "words", bool: "true or false", list: "a list of words"}
MOST = 8                                 # the most connectors one plan gives its agents


class CatalogueError(ValueError):
    """The catalogue can't be used: no file, or a file with problems (each said in plain words)."""


class Refused(ValueError):
    """A choice of connectors an agent can't be given, and why (in plain words)."""


def paths():
    out = []
    if os.environ.get("BROMIGOS_LAB_CONNECTORS"):
        out.append(os.environ["BROMIGOS_LAB_CONNECTORS"])
    out += [os.path.join(SHARE, "homelab", "lab", "connectors.toml"),
            os.path.normpath(os.path.join(HERE, "..", "..", "share", "lab", "connectors.toml"))]
    return out


def where(path=None):
    """The file load() reads (None: there isn't one)."""
    for p in [path] if path else paths():
        if p and os.path.isfile(p):
            return p
    return None


def _https(u):
    try:
        p = urllib.parse.urlsplit(u)
        return p.scheme == "https" and bool(p.hostname) and "@" not in p.netloc and not re.search(r"\s", u)
    except ValueError:
        return False


def _loopback(u):
    try:
        p = urllib.parse.urlsplit(u)
        return p.scheme in ("http", "https") and p.hostname in LOOPBACK and "@" not in p.netloc
    except ValueError:
        return False


def _shape(row, keys, needs):
    """Problems with a row's keys and their shapes (problems() adds which row)."""
    out = [f"{k!r} isn't a key a row has" for k in sorted(set(row) - set(keys))]
    out += [f"no {k}" for k in needs if k not in row]
    for k, kind in keys.items():
        if k not in row:
            continue
        v = row[k]
        texts = v if isinstance(v, list) else [v]
        if type(v) is not kind or (kind is list and not all(isinstance(x, str) for x in v)):
            out.append(f"{k} is {_SHAPES[kind]}, not {v!r}")
        elif kind is not bool and any(not x or x != x.strip() or CONTROL.search(x) for x in texts):
            out.append(f"{k} is empty, has a space at an end or has a control character in it")
    return out


def _connector(row, cats, ids):
    out = _shape(row, CONNECTOR_KEYS, CONNECTOR_NEEDS)
    if out:
        return out
    if not ID.fullmatch(row["id"]):
        out.append(f"id {row['id']!r} is lower-case letters, digits and hyphens")
    if row["category"] not in cats:
        out.append(f"category {row['category']!r} isn't in connector_categories")
    if row["auth"] not in AUTH:
        out.append(f"auth {row['auth']!r} isn't one of {', '.join(AUTH)}")
    url, local = row.get("url"), row.get("local", False)
    if local and not (url and _loopback(url)):
        out.append(f"a local row's url is on this machine (127.0.0.1 or localhost), not {url!r}")
    if url and not local and not _https(url):
        out.append(f"url {url!r} isn't an https address (only a local row may use http)")
    if not url and row.get("via") not in ids:
        out.append("no url, and no via naming the connector that reaches it")
    if url and "via" in row:
        out.append("via is for a row with no url of its own")
    if not _https(row["homepage"]):
        out.append(f"homepage {row['homepage']!r} isn't an https address")
    if "key_header" in row and (row["auth"] != "key" or not HEADER_NAME.fullmatch(row["key_header"])):
        out.append(f"key_header {row['key_header']!r} is a header's name, on a row whose auth is key")
    asked = bool(url) and not local
    if ("answered" in row) != ("answer" in row):
        out.append("answered and answer go together")
    if "answered" in row and not asked:
        out.append("answered is for an address that can be asked: not a local row, not one with no url")
    return out


def _platform(row, cats):
    out = _shape(row, PLATFORM_KEYS, PLATFORM_NEEDS)
    if out:
        return out
    if not ID.fullmatch(row["id"]):
        out.append(f"id {row['id']!r} is lower-case letters, digits and hyphens")
    if row["category"] not in cats:
        out.append(f"category {row['category']!r} isn't in platform_categories")
    env = row["env"]
    if not ENV.fullmatch(env):
        out.append(f"env {env!r} isn't shaped like PRINTIFY_API_KEY (capitals, digits and underscores)")
    for k in ("docs", "api_base"):
        if not _https(row[k]):
            out.append(f"{k} {row[k]!r} isn't an https address")
    if "auth_header" in row:
        name, sep, value = row["auth_header"].partition(": ")
        named = re.findall(r"\$\{([^}]*)\}", value)
        if not sep or not HEADER_NAME.fullmatch(name) or named != [env]:
            out.append(f"auth_header {row['auth_header']!r} is a header line that names the key once, as "
                       f"${{{env}}}")
    if row.get("unattended", False):
        out.append("unattended is only ever false (leave it out otherwise)")
    return out


def problems(doc):
    """What's wrong with a catalogue as read from the file, in words ([]: nothing)."""
    if not isinstance(doc, dict):
        return ["the file isn't a table"]
    if doc.get("format") != FORMAT:
        return [f"format {doc.get('format')!r} isn't the one this bromigOS reads ({FORMAT}): update bromigos-lab"]
    out = [f"{k!r} isn't a key the file has" for k in sorted(set(doc) - set(TOP_KEYS))]
    if not DAY.fullmatch(str(doc.get("checked"))):
        out.append(f"checked is a day (2026-11-17), not {doc.get('checked')!r}")
    cats = {}
    for key in ("connector_categories", "platform_categories"):
        v = doc.get(key)
        if (not isinstance(v, list) or not v or len(set(map(str, v))) != len(v)
                or not all(isinstance(x, str) and x and not CONTROL.search(x) for x in v)):
            out.append(f"{key} is a list of category names, each once")
            v = []
        cats[key] = v
    for table, check in (("connector", _connector), ("platform", _platform)):
        rows = doc.get(table)
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            out.append(f"no [[{table}]] rows")
            continue
        ids = [r.get("id") for r in rows if isinstance(r.get("id"), str)]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            out.append(f"{table} {dup}: the id is used {ids.count(dup)} times")
        if table == "platform":
            envs = [r.get("env") for r in rows if isinstance(r.get("env"), str)]
            for dup in sorted({e for e in envs if envs.count(e) > 1}):
                out.append(f"platform env {dup}: used {envs.count(dup)} times")
        for n, row in enumerate(rows, 1):
            name = row.get("id") if isinstance(row.get("id"), str) else f"#{n}"
            found = check(row, cats["connector_categories"], set(ids)) if table == "connector" else \
                check(row, cats["platform_categories"])
            out += [f"{table} {name}: {p}" for p in found]
    return out


def _read(path=None):
    p = where(path)
    if not p:
        raise CatalogueError("no connectors.toml (the lab's connector catalogue; it comes with bromigos-lab)")
    try:
        with open(p, "rb") as f:
            return p, tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise CatalogueError(f"{p} can't be read: {e}") from e


def validate(path=None):
    """What's wrong with the catalogue file, in words ([]: nothing)."""
    try:
        return problems(_read(path)[1])
    except CatalogueError as e:
        return [str(e)]


def load(path=None):
    """The catalogue: {"path", "checked", "categories": {kind: [names]}, "rows": [row, …]}, the
    connectors first, each in the file's order. Raises CatalogueError when the file has problems."""
    p, doc = _read(path)
    bad = problems(doc)
    if bad:
        more = f"\n  … and {len(bad) - 8} more" if len(bad) > 8 else ""
        raise CatalogueError(f"{p} isn't a connector catalogue this bromigOS can use:\n  "
                             + "\n  ".join(bad[:8]) + more)
    rows = [dict(r, kind="one-click") for r in doc["connector"]] + [dict(r, kind="key") for r in doc["platform"]]
    return {"path": p, "checked": doc["checked"], "rows": rows,
            "categories": {"one-click": list(doc["connector_categories"]), "key": list(doc["platform_categories"])}}


def state(row):
    """Where a row stands: "offered", or why it isn't: "listed only" (it needs a sign-in or code
    of bromigOS's own), "no address" (it's reached through another connector), "no answer" (its
    address didn't answer when it was last checked)."""
    if row.get("listed_only"):
        return "listed only"
    if row["kind"] == "one-click" and not row.get("url"):
        return "no address"
    if row.get("answered") is False:
        return "no answer"
    return "offered"


def needs(row):
    """What a row needs from you, as a sentence."""
    if row["kind"] == "key":
        sent = "" if row.get("auth_header") else " Its note and its docs say how the key is sent."
        alone = " A key alone can't run it unattended." if row.get("unattended") is False else ""
        return f"An API key from {row['name']}, in {row['env']}.{sent}{alone}"
    if row.get("listed_only"):
        return f"Listed only. {row['listed_only']}"
    if not row.get("url"):
        return f"No address of its own: it's reached through the {row['via']} connector."
    if row.get("local"):
        return "Nothing to sign in to. The server runs on your own machine, so start it first."
    if row["auth"] == "none":
        return "Nothing: no account and no key."
    if row["auth"] == "key":
        how = f"in the {row['key_header']} header" if row.get("key_header") else "as a Bearer token"
        return f"An API key from {row['name']}, sent {how}."
    return f"A sign-in to {row['name']} in your browser (OAuth)."


def why_not(row):
    """Why an agent can't be given this row yet, as the end of a sentence (None: it can). A row
    that acts, or whose address didn't answer, can: chosen() asks for it to be named twice."""
    if row["kind"] == "key":
        return "it's a key platform, not a connector, and key platforms come in a later change"
    if row.get("listed_only"):
        return "it's listed only. " + row["listed_only"].rstrip(".")
    if not row.get("url"):
        return f"it has no address of its own: it's reached through the {row['via']} connector"
    if row.get("local"):
        return "its server runs on your own machine, where an agent in your lab can't reach it"
    if row["auth"] == "sign-in":
        return "it needs a sign-in in a browser, and sign-in connectors come in a later change"
    return None


def chosen(cat, ids, allow_acting=(), allow_unanswered=()):
    """The rows for the connector ids an agent is to be given, in the order asked for, each once.
    Raises Refused for an id nothing has, a row why_not() names, more than MOST, a row whose
    address didn't answer (unless allow_unanswered names it) and a row that acts (unless
    allow_acting names it). The two allow lists are `bromigos lab provision`'s options."""
    ids, allow_acting, allow_unanswered = ([str(i).casefold().strip() for i in dict.fromkeys(some)]
                                           for some in (ids, allow_acting, allow_unanswered))
    for option, named in (("--allow-acting", allow_acting), ("--allow-unanswered", allow_unanswered)):
        stray = [i for i in named if i not in ids]
        if stray:
            raise Refused(f"{option} names {', '.join(stray)}, which isn't among the connectors chosen.")
    if len(ids) > MOST:
        raise Refused(f"An agent is given at most {MOST} connectors, and {len(ids)} were chosen.")
    out = []
    for rid in ids:
        found = find(cat, rid, "one-click") or find(cat, rid)
        if not found:
            close = list(dict.fromkeys(r["id"] for r in search(cat, rid, "one-click")))[:5]
            raise Refused(f"No connector has the id {rid!r}. "
                          + (f"Close: {', '.join(close)}." if close else
                             "bromigos lab connectors search WORDS finds one by name."))
        row = found[0]
        named = f"{row['name']} ({rid})"
        why = why_not(row)
        if why:
            raise Refused(f"{named} can't be given to an agent: {why}.")
        if row.get("answered") is False and rid not in allow_unanswered:
            raise Refused(f"{named} didn't answer when its address was checked on {cat['checked']} "
                          f"({row['answer']}). To choose it anyway, add --allow-unanswered {rid}.")
        if row.get("acts") and rid not in allow_acting:
            raise Refused(f"{named} can act for you. {row['acts']} To give it to an agent anyway, "
                          f"add --allow-acting {rid}.")
        out.append(row)
    return out


def plans():
    """The saved lab plans this computer's console reads (homelab.toml's `provisioned` sources)."""
    from . import config
    return [s["plan"] for s in config.load().get("sources", [])
            if s.get("type") == "provisioned" and isinstance(s.get("plan"), str)]


def in_use(paths=None):
    """{connector id: [agent, …]}: the connectors the lab's saved plan gives its agents ({}: no
    plan, or one that can't be read). The plan is what was chosen: it isn't asked of the agent."""
    out = {}
    try:
        for path in plans() if paths is None else paths:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
            agents = [a for a in ("hermes", "openclaw") if a in state.get("selected", [])]
            for rid in (state.get("agents") or {}).get("connectors") or []:
                if isinstance(rid, str) and agents:
                    out[rid] = sorted(set(out.get(rid, []) + agents))
    except Exception:                                              # noqa: BLE001  a plan never stops the catalogue
        return {}
    return out


def category_named(cat, kind, name):
    """A category by its name or a part of it, whatever the case (None: no such, or several)."""
    names = [c for k in ([kind] if kind else KINDS) for c in cat["categories"][k]]
    want = name.casefold().strip()
    exact = [c for c in names if c.casefold() == want]
    close = exact or sorted({c for c in names if want and want in c.casefold()})
    return close[0] if len(set(close)) == 1 else None


def rows(cat, kind=None, category=None, every=False):
    """The rows on offer (every=True: all of them), by kind and category, in the file's order."""
    return [r for r in cat["rows"] if (not kind or r["kind"] == kind)
            and (not category or r["category"] == category) and (every or state(r) == "offered")]


def find(cat, rid, kind=None):
    """Every row of that id: at most one connector and one platform."""
    return [r for r in cat["rows"] if r["id"] == rid.casefold().strip() and (not kind or r["kind"] == kind)]


def search(cat, words, kind=None):
    """Rows whose id, name or an alias match, the closest first: the whole name, a whole alias,
    part of the name, part of an alias, then every word found somewhere among them."""
    q = " ".join(words.split()).casefold() if isinstance(words, str) else " ".join(words).casefold().strip()
    if not q:
        return []
    out = []
    for n, r in enumerate(cat["rows"]):
        if kind and r["kind"] != kind:
            continue
        names = [r["id"], r["name"].casefold()]
        aliases = [a.casefold() for a in r.get("aliases", [])]
        score = (0 if q in names else 1 if q in aliases else 2 if any(q in x for x in names) else
                 3 if any(q in x for x in aliases) else
                 4 if all(any(w in x for x in names + aliases) for w in q.split()) else None)
        if score is not None:
            out.append((score, state(r) != "offered", n, r))
    return [r for *_, r in sorted(out, key=lambda x: x[:3])]


def describe(row, used=None):
    """A row for --json: the row, its state and what it needs; `in_use` names the agents the
    lab's saved plan gives it to, when there are any."""
    out = dict(row, state=state(row), needs=needs(row))
    if row["kind"] == "one-click" and (used or {}).get(row["id"]):
        out["in_use"] = used[row["id"]]
    return out


# ------------------------------------------------------------------ bromigos lab connectors
GIVE = ("To give an agent connectors that need nothing or a key: bromigos lab provision … --connectors ID … "
        "(docs/lab-agents.md).")
NOT_YET = "Sign-in connectors and key platforms can't be given to an agent yet."
MARKS = {"listed only": "listed only: it needs a sign-in or code of our own",
         "no address": "no address of its own", "no answer": "didn't answer when last checked"}


def _short(text, width):
    return text if len(text) <= width else text[:width - 1].rstrip() + "…"


def _row_line(r):
    what = AUTH_WORDS[r["auth"]] if r["kind"] == "one-click" else r["env"]
    st = state(r)
    tail = r["summary"] if st == "offered" else f"({MARKS[st]})"
    wide, room = (11, 54) if r["kind"] == "one-click" else (24, 42)
    return f"  {r['id']:<20} {_short(r['name'], 24):<24} {what:<{wide}} {_short(tail, room)}".rstrip()


def print_list(cat, shown, kind, every, used=None):
    for k in [kind] if kind else KINDS:
        mine = [r for r in shown if r["kind"] == k]
        total = [r for r in cat["rows"] if r["kind"] == k]
        if not mine:
            continue
        head = ("ONE-CLICK CONNECTORS: remote MCP servers" if k == "one-click" else
                "KEY PLATFORMS: REST APIs, reached with a key")
        print(f"{head} ({len(mine)} of {len(total)})")
        for c in cat["categories"][k]:
            group = [r for r in mine if r["category"] == c]
            if group:
                print(f"\n{c}")
                for r in group:
                    print(_row_line(r))
        print()
    if not shown:
        print("Nothing matches.")
    left = [r for r in cat["rows"] if (not kind or r["kind"] == kind) and state(r) != "offered"]
    if left and not every:
        counts = {s: sum(1 for r in left if state(r) == s) for s in MARKS}
        print(f"{len(left)} more aren't on offer (--all lists them): "
              + ", ".join(f"{n} {MARKS[s].split(':')[0]}" for s, n in counts.items() if n) + ".")
    print(f"Addresses last checked {cat['checked']}. bromigos lab connectors show ID says what one needs.")
    if used:
        print("In your lab's plan: " + ", ".join(f"{rid} ({' and '.join(used[rid])})" for rid in sorted(used)) + ".")
    print(GIVE)
    print(NOT_YET)


def _field(label, text):
    lines = textwrap.wrap(text, 84, break_long_words=False, break_on_hyphens=False) or [""]
    print(f"  {label:<12} {lines[0]}")
    for more in lines[1:]:
        print(f"  {'':<12} {more}")


def print_show(cat, r, used=None):
    print(f"{r['name']} ({KIND_WORDS[r['kind']]}) · {r['category']}")
    for line in textwrap.wrap(r["summary"], 98):
        print(line)
    print()
    if r["kind"] == "key":
        _field("Key goes in", r["env"])
        if r.get("auth_header"):
            _field("Sent as", r["auth_header"])
        _field("Docs", r["docs"])
        _field("API base", r["api_base"] + (f" (through the {r['api_via']})" if r.get("api_via") else ""))
        _field("Needs", needs(r))
        for label, key in (("Note", "note"), ("API notes", "api_notes"), ("Can act", "acts")):
            if r.get(key):
                _field(label, r[key])
    else:
        _field("Address", r.get("url") or f"none of its own: through the {r['via']} connector")
        _field("Sign-in", {"none": "none", "key": "an API key", "sign-in": "in your browser (OAuth)"}[r["auth"]])
        _field("Needs", needs(r))
        if "answered" in r:
            _field("Last check", f"{cat['checked']}: " + (f"answered ({r['answer']})" if r["answered"] else
                                                          f"didn't answer ({r['answer']})"))
        else:
            _field("Last check", "never asked: " + ("it runs on your own machine" if r.get("local") else
                                                    "it has no address"))
        _field("Run by", "the service's own maker" if r["official"] else "someone other than the service's maker")
        if r.get("acts"):
            _field("Can act", r["acts"])
        _field("Homepage", r["homepage"])
    if r.get("aliases"):
        _field("Also called", ", ".join(r["aliases"]))
    why = why_not(r)
    if why:
        _field("Agents", f"Can't be given to an agent yet: {why}.")
    else:
        extra = (f" --allow-acting {r['id']}" if r.get("acts") else "") + \
                (f" --allow-unanswered {r['id']}" if r.get("answered") is False else "")
        _field("Agents", f"bromigos lab provision … --connectors {r['id']}{extra} gives it to an agent.")
        if (used or {}).get(r["id"]):
            _field("In use", f"Your lab's plan gives it to {' and '.join(used[r['id']])}.")


def parser():
    p = argparse.ArgumentParser(prog="bromigos lab connectors",
                                description="The lab's connector catalogue: services an agent could reach, and "
                                            "what each needs. Nothing here connects or keeps a key: "
                                            "bromigos lab provision gives an agent the ones you choose.")
    p.add_argument("verb", nargs="?", choices=["list", "search", "show"], default="list")
    p.add_argument("words", nargs="*", help="search: what to look for; show: the id")
    p.add_argument("--kind", choices=KINDS, help="one-click (remote MCP servers) or key (REST APIs with a key)")
    p.add_argument("--category", metavar="NAME", help="list: one category, by its name or a part of it")
    p.add_argument("--all", action="store_true", help="list: also the rows that aren't on offer, and why")
    p.add_argument("--json", action="store_true")
    return p


def main(argv=None):
    """0 done; 2 the command line was wrong; 3 no such id or category; 4 the catalogue can't be read."""
    a = parser().parse_args(argv)
    say = "bromigos lab connectors"
    try:
        cat = load()
    except CatalogueError as e:
        if a.json:
            print(json.dumps({"error": str(e)}))
        print(f"{say}: {e}", file=sys.stderr)
        return 4
    used = in_use()
    if a.verb == "list":
        if a.words:
            print(f"{say} list takes no words: {say} search {' '.join(a.words)}", file=sys.stderr)
            return 2
        cname = None
        if a.category:
            cname = category_named(cat, a.kind, a.category)
            if not cname:
                names = [c for k in ([a.kind] if a.kind else KINDS) for c in cat["categories"][k]]
                print(f"{say}: no one category matches {a.category!r}. They are: " + "; ".join(dict.fromkeys(names)),
                      file=sys.stderr)
                return 3
        shown = rows(cat, a.kind, cname, a.all)
        if a.json:
            print(json.dumps({"checked": cat["checked"], "rows": [describe(r, used) for r in shown]}, indent=1))
        else:
            print_list(cat, shown, a.kind, a.all, used)
        return 0
    if not a.words:
        print(f"{say} {a.verb} " + ("WORDS" if a.verb == "search" else "ID"), file=sys.stderr)
        return 2
    if a.verb == "search":
        found = search(cat, a.words, a.kind)
        if a.json:
            print(json.dumps({"query": " ".join(a.words), "checked": cat["checked"],
                              "rows": [describe(r, used) for r in found]}, indent=1))
        elif not found:
            print(f"Nothing in the catalogue is called {' '.join(a.words)!r}.")
        else:
            for r in found:
                print(f"{KIND_WORDS[r['kind']]:<20}" + _row_line(r))
        return 0
    if len(a.words) != 1:
        print(f"{say} show ID (one id; {say} search finds it)", file=sys.stderr)
        return 2
    found = find(cat, a.words[0], a.kind)
    if not found:
        close = [r["id"] for r in search(cat, a.words, a.kind)][:5]
        print(f"{say}: nothing has the id {a.words[0]!r}"
              + (f". Close: {', '.join(dict.fromkeys(close))}" if close else f" ({say} search WORDS looks by name)"),
              file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps({"checked": cat["checked"], "rows": [describe(r, used) for r in found]}, indent=1))
        return 0
    for n, r in enumerate(found):
        if n:
            print()
        print_show(cat, r, used)
    return 0


if __name__ == "__main__":
    sys.exit(main())
