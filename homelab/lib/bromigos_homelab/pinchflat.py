"""Pinchflat from the command line: `bromigos lab youtube add|list|remove|pause|resume|refresh|
status|quality|cookies` (docs/lab.md, "YouTube downloads").

Pinchflat has no JSON API: it is a Phoenix app whose pages are HTML forms. This drives it the
way its own pages do. It GETs a page, takes the CSRF token and the session cookie, and POSTs
the form back. Phoenix answers a good form with a redirect (302) and a bad one with the same
form and its errors, which are shown as they are.

Tested against Pinchflat v2025.9.26 (TESTED). Every form and page is checked for the fields
this needs; when one is missing, Pinchflat has changed and the command stops and says so
(FormChanged) before it sends anything.

What each command uses:
  list       /media_profiles (each profile's quality), /media_profiles/ID (its sources),
             /sources/ID (a source's settings and counts), /sources/UUID/feed.xml (its newest video)
  add        /sources/new, then POST /sources; a quality other than the base profile's makes
             a profile copy: /media_profiles/new?template_id=BASE, then POST /media_profiles
  remove     DELETE /sources/ID (?delete_files=true with --delete-files)
  pause      PATCH /sources/ID with enabled=false (what the Enabled toggle on the Sources page
             sends); resume sends true
  refresh    POST /sources/ID/force_index (the source's Actions › Force Index)
  quality    PATCH /sources/ID with another media profile
  status     /metrics (the queue, failed jobs), the home page (active tasks, recent downloads),
             each source's page and feed
  cookies    a cookie store (below), then each source's Cookie Behaviour

Configuration: the first [[source]] of type pinchflat in homelab.toml (or --source NAME), with
the same keys the console's card reads (adapters/labmedia.py): endpoint, auth_ref (basic auth,
"user:password"; or user_ref plus auth_ref holding the password), tls_ca. And:

    cookies_store = "vault:secret/lab/pinchflat#cookies"    # where Pinchflat's cookies.txt
                                        # comes from: a Vault KV field (written with the `vault`
                                        # CLI and its login), or "file:/path/cookies.txt" (a
                                        # file Pinchflat reads, such as its extras/ folder)

    [youtube]
    quality = "1080p"                   # the default for `add`
    channel_profile = "Channels (Media Center)"   # the media profile a channel gets
    playlist_profile = "Playlists (in order)"     # and a playlist

PINCHFLAT_URL and PINCHFLAT_AUTH ("user:password") replace the source's endpoint and auth.
"""
import argparse
import base64
import datetime
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

TESTED = "2025.9.26"
QUALITIES = ("4320p", "2160p", "1440p", "1080p", "720p", "480p", "360p", "audio")   # MediaProfile's enum
CHOICES = ("best",) + QUALITIES
BEST = "4320p"                      # Pinchflat's highest: yt-dlp takes the best there is up to it
DEFAULT_QUALITY = "1080p"
BASE_PROFILES = {"channel": "Channels (Media Center)", "playlist": "Playlists (in order)"}
SEP = " · "                         # "Playlists (in order) · 2160p": a base profile's quality copy
COOKIE_MAX_DAYS = 30
COOKIE_ON, COOKIE_OFF = "when_needed", "disabled"


class PinchflatError(Exception):
    pass


class FormChanged(PinchflatError):
    def __init__(self, page, missing):
        super().__init__(f"Pinchflat's {page} isn't what this was built for (tested with v{TESTED}): no "
                         f"{', '.join(missing)}. Pinchflat has probably been updated; nothing was sent. Use its "
                         f"web page for this, and update bromigOS.")


class NotFound(PinchflatError):
    pass


# ------------------------------------------------------------------ the pages
class Page(HTMLParser):
    """What this needs from one of Pinchflat's pages: the CSRF token, its forms (each field's
    value as the browser would send it), its tables (cells' text and links), the "Raw
    Attributes" list (key: value) and the form errors."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.csrf = None
        self.forms = []
        self.tables = []
        self.attrs = {}
        self.errors = []
        self.text = text
        self._form = None
        self._select = None
        self._textarea = None
        self._enabled = None          # the last toggle's x-data "{ enabled: true }"
        self._last_field = None
        self._cell = None
        self._strong = self._code = None
        self._key = None
        self._err = None
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        xd = a.get("x-data") or ""
        m = re.match(r"\{\s*enabled:\s*(true|false)\s*\}", xd)
        if m:
            self._enabled = m.group(1)
        if tag == "meta" and a.get("name") == "csrf-token":
            self.csrf = a.get("content")
        elif tag == "form":
            self._form = {"action": a.get("action") or "", "method": (a.get("method") or "get").lower(), "fields": []}
            self.forms.append(self._form)
        elif tag == "input" and self._form is not None and a.get("name"):
            typ = (a.get("type") or "text").lower()
            name = a["name"]
            if typ in ("submit", "button", "image", "file", "reset"):
                return
            if typ in ("checkbox", "radio"):
                if "checked" in a:
                    self._form["fields"].append((name, a.get("value") or "on"))
            elif a.get("value") is None and a.get("x-bind:value") == "enabled":
                self._form["fields"].append((name, self._enabled or "false"))     # a toggle
            else:
                self._form["fields"].append((name, a.get("value") or ""))
            self._last_field = name
        elif tag == "select" and self._form is not None and a.get("name"):
            self._select = {"name": a["name"], "options": [], "selected": None, "multiple": "multiple" in a}
            self._last_field = a["name"]
        elif tag == "option" and self._select is not None:
            v = a.get("value") or ""
            self._select["options"].append(v)
            if "selected" in a and self._select["selected"] is None:
                self._select["selected"] = v
        elif tag == "textarea" and self._form is not None and a.get("name"):
            self._textarea = [a["name"], ""]
            self._last_field = a["name"]
        elif tag == "table":
            self.tables.append({"head": [], "rows": []})
        elif tag == "tr" and self.tables:
            self.tables[-1]["rows"].append([])
        elif tag in ("td", "th") and self.tables and self.tables[-1]["rows"]:
            self._cell = {"text": "", "links": [], "th": tag == "th"}
            self.tables[-1]["rows"][-1].append(self._cell)
        elif tag == "a" and self._cell is not None and a.get("href"):
            self._cell["links"].append(a["href"])
        elif tag == "strong":
            self._strong = ""
        elif tag == "code" and self._key:
            self._code = ""
        elif tag == "p" and "text-rose-600" in (a.get("class") or ""):
            self._err = ""

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        elif tag == "select" and self._select is not None:
            s = self._select
            if not s["multiple"]:
                v = s["selected"] if s["selected"] is not None else (s["options"][0] if s["options"] else "")
                self._form["fields"].append((s["name"], v))
            self._select = None
        elif tag == "textarea" and self._textarea is not None:
            self._form["fields"].append(tuple(self._textarea))
            self._textarea = None
        elif tag in ("td", "th"):
            if self._cell is not None:
                self._cell["text"] = " ".join(self._cell["text"].split())
            self._cell = None
        elif tag == "strong" and self._strong is not None:
            s = self._strong.strip()
            self._key = s[:-1] if s.endswith(":") else None
            self._strong = None
        elif tag == "code" and self._code is not None:
            self.attrs[self._key] = " ".join(self._code.split())
            self._code = self._key = None
        elif tag == "p" and self._err is not None:
            msg = " ".join(self._err.split())
            if msg:
                self.errors.append((self._last_field, msg))
            self._err = None

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea[1] += data
        if self._cell is not None:
            self._cell["text"] += data
        if self._strong is not None:
            self._strong += data
        if self._code is not None:
            self._code += data
        if self._err is not None:
            self._err += data

    # ---- reading
    def form(self, action, what, need=()):
        """The form posting to `action`, checked for the fields in `need`."""
        f = next((f for f in self.forms if f["action"].split("?")[0] == action), None)
        if f is None:
            raise FormChanged(what, [f"form for {action}"])
        names = {k for k, _ in f["fields"]}
        missing = [n for n in ("_csrf_token",) + tuple(need) if n not in names]
        if missing:
            raise FormChanged(what, missing)
        return f

    def table(self, header):
        """The rows (lists of cells) of the first table whose header has `header`."""
        for t in self.tables:
            rows = t["rows"]
            if rows and any(c["th"] and c["text"] == header for c in rows[0]):
                return rows[1:]
        return None

    def counts(self):
        """The record counts of the page's LiveView tables, in page order: "Showing 10 of N"
        gives N, "Nothing Here!" 0."""
        out = []
        for m in re.finditer(r"Showing\s*<span[^>]*>[^<]*</span>\s*of\s*<span[^>]*>([^<]*)</span>|Nothing Here!",
                             self.text):
            out.append(_int(m.group(1)) if m.group(1) is not None else 0)
        return out


def _int(s):
    try:
        return int(re.sub(r"[^\d]", "", str(s)) or "x")
    except ValueError:
        return None


def _none(v):
    return None if v in (None, "", "nil") else v


# ------------------------------------------------------------------ HTTP
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


class Pinchflat:
    """One Pinchflat, its session (cookie jar) and its pages."""

    def __init__(self, url, auth=None, ctx=None, timeout=60, base_profiles=None):
        if not url:
            raise PinchflatError("no Pinchflat: add a [[source]] of type pinchflat to homelab.toml "
                                 "(bromigos lab connect finds it), or set PINCHFLAT_URL")
        self.base = url.rstrip("/")
        self.headers = {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode()} if auth else {}
        self.jar = http.cookiejar.CookieJar()
        hs = [urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect]
        if ctx is not None:
            hs.append(urllib.request.HTTPSHandler(context=ctx))
        self.opener = urllib.request.build_opener(*hs)
        self.timeout = timeout
        self.base_profiles = dict(BASE_PROFILES, **(base_profiles or {}))
        self._profiles = None

    def _open(self, method, path, body=None, timeout=None):
        url = path if path.startswith(("http://", "https://")) else self.base + path
        h = dict(self.headers)
        data = None
        if body is not None:
            data = urllib.parse.urlencode(body).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise PinchflatError("Pinchflat refused the login: check its user and password (auth_ref "
                                     "in homelab.toml)") from None
            return e.code, e.headers, e.read()
        except (OSError, ValueError) as e:
            raise PinchflatError(f"Pinchflat at {self.base} doesn't answer: {e}") from None

    def get(self, path, raw=False):
        status, _, body = self._open("GET", path)
        if status == 404:
            raise NotFound(f"Pinchflat has no {path}")
        if status != 200:
            raise PinchflatError(f"Pinchflat answered {path} with HTTP {status}")
        return body if raw else Page(body.decode("utf-8", "replace"))

    def post(self, path, fields, what, timeout=None):
        """POST a form; the redirect's target on success. A form shown again means Pinchflat
        refused it: its errors are raised."""
        status, headers, body = self._open("POST", path, fields, timeout)
        if status in (302, 303):
            return headers.get("Location") or ""
        errs = []
        if status == 200:
            errs = Page(body.decode("utf-8", "replace")).errors
        if errs:
            raise PinchflatError(f"Pinchflat refused {what}: " + "; ".join(
                f"{_label(k)} {m}" if k else m for k, m in errs))
        raise PinchflatError(f"Pinchflat refused {what} (HTTP {status})")

    def submit(self, page_path, action, what, changes, need=(), full=False, query=""):
        """GET the page with the form, then POST it back with `changes`. full: every field the
        page has (a new record, as the browser sends it); else only the changes, the CSRF token
        and the form's _method (an edit: everything else stays as it is)."""
        page = self.get(page_path)
        form = page.form(action, what, tuple(need) + tuple(k for k in changes if full))
        fields = dict(form["fields"]) if full else {k: v for k, v in form["fields"] if k in ("_csrf_token", "_method")}
        if full:
            fields = {k: v for k, v in fields.items() if k == "_csrf_token" or "[" in k}
        fields.update(changes)
        return self.post(action + query, fields, what, timeout=180 if full else None)

    def action(self, path, what, method=None, page_path=None):
        """A link with data-method (Actions menu, Delete): POST with the page's CSRF token."""
        page = self.get(page_path or "/sources")
        if not page.csrf:
            raise FormChanged(page_path or "/sources", ["csrf-token"])
        fields = {"_csrf_token": page.csrf}
        if method:
            fields["_method"] = method
        return self.post(path, fields, what)

    # ---- media profiles
    def profiles(self, fresh=False):
        """[{id, name, quality, sources}] from the Media Profiles page."""
        if self._profiles is not None and not fresh:
            return self._profiles
        rows = self.get("/media_profiles").table("Preferred Resolution")
        if rows is None:
            raise FormChanged("Media Profiles page", ["its table"])
        out = []
        for r in rows:
            link = next((l for c in r for l in c["links"] if re.fullmatch(r"/media_profiles/\d+", l)), None)
            if not link or len(r) < 3:
                continue
            out.append({"id": int(link.rsplit("/", 1)[1]), "name": r[0]["text"], "quality": r[1]["text"] or None,
                        "sources": _int(r[2]["text"])})
        self._profiles = out
        return out

    def profile_sources(self, pid):
        rows = self.get(f"/media_profiles/{pid}").table("Should Download?")
        if rows is None:
            raise FormChanged(f"media profile {pid}'s page", ["its Sources table"])
        out = []
        for r in rows:
            link = next((l for c in r for l in c["links"] if re.fullmatch(r"/sources/\d+", l)), None)
            if link:
                out.append({"id": int(link.rsplit("/", 1)[1]), "name": r[0]["text"],
                            "kind": (r[1]["text"] if len(r) > 1 else "") or None})
        return out

    def base_profile(self, kind):
        """The media profile a kind of source gets: [youtube] channel_profile/playlist_profile,
        or the only profile there is."""
        want = self.base_profiles[kind]
        profs = self.profiles()
        p = next((p for p in profs if p["name"] == want), None)
        if p:
            return p
        if len(profs) == 1:
            return profs[0]
        names = ", ".join(repr(p["name"]) for p in profs) or "none"
        raise PinchflatError(f"Pinchflat has no media profile named {want!r} for a {kind} (it has {names}). "
                             f"Set {kind}_profile in homelab.toml's [youtube], or make that profile in Pinchflat.")

    def profile_for(self, kind, quality):
        """(profile, made): the base profile at that quality, or its copy at another one, made
        the first time (named "<base> · <quality>"; everything but the quality copied)."""
        quality = resolve_quality(quality)
        base = self.base_profile(kind)
        if base["quality"] == quality:
            return base, False
        name = f"{base['name']}{SEP}{quality}"
        have = next((p for p in self.profiles() if p["name"] == name), None)
        if have and have["quality"] == quality:
            return have, False
        if have:                                   # someone changed its quality: put it back
            self.submit(f"/media_profiles/{have['id']}/edit", f"/media_profiles/{have['id']}",
                        f"the quality of {name!r}", {"media_profile[preferred_resolution]": quality},
                        need=("media_profile[preferred_resolution]",))
            self._profiles = None
            return dict(have, quality=quality), False
        loc = self.submit(f"/media_profiles/new?template_id={base['id']}", "/media_profiles",
                          f"a {quality} copy of {base['name']!r}",
                          {"media_profile[name]": name, "media_profile[preferred_resolution]": quality},
                          need=("media_profile[output_path_template]",), full=True)
        self._profiles = None
        m = re.search(r"/media_profiles/(\d+)", loc)
        p = next((p for p in self.profiles() if p["name"] == name), None)
        if not p and m:
            p = {"id": int(m.group(1)), "name": name, "quality": quality, "sources": 0}
        if not p:
            raise PinchflatError(f"Pinchflat made no profile {name!r}")
        return p, True

    # ---- sources
    def source(self, sid, feed=True):
        """One source's settings, counts and newest video, from its page and its feed."""
        page = self.get(f"/sources/{sid}")
        a = page.attrs
        if "original_url" not in a or "uuid" not in a:
            raise FormChanged(f"source {sid}'s page", ["its Raw Attributes"])
        pending, downloaded, other = (page.counts() + [None, None, None])[:3]
        rec = {"id": int(sid), "name": a.get("custom_name") or a.get("collection_name") or "", "kind": _none(
            a.get("collection_type")), "url": a.get("original_url"), "uuid": a.get("uuid"),
            "enabled": a.get("enabled") != "false", "profile_id": _int(a.get("media_profile_id")),
            "profile": None, "quality": None, "last_check": _none(a.get("last_indexed_at")),
            "since": _none(a.get("download_cutoff_date")), "cookies": a.get("cookie_behaviour") or None,
            "downloaded": downloaded, "pending": pending, "other": other,
            "deleting": bool(_none(a.get("marked_for_deletion_at"))), "newest": None, "newest_at": None}
        p = next((p for p in self.profiles() if p["id"] == rec["profile_id"]), None)
        if p:
            rec["profile"], rec["quality"] = p["name"], p["quality"]
        if feed and rec["uuid"]:
            try:
                from .youtube import parse_feed
                f = parse_feed(self.get(f"/sources/{rec['uuid']}/feed.xml", raw=True))
                if f["items"]:
                    rec["newest"] = f["items"][0]["title"]
                    rec["newest_at"] = _iso(f["items"][0]["at"])
                rec["recent"] = [{"title": i["title"], "uploaded": _iso(i["at"]), "source": rec["name"]}
                                 for i in f["items"][:5]]
            except Exception:
                pass
        return rec

    def source_ids(self):
        """Every source's id, through the media profiles' pages (the Sources page shows ten
        at a time, and only to a browser)."""
        ids = []
        for p in self.profiles():
            for s in self.profile_sources(p["id"]):
                if s["id"] not in ids:
                    ids.append(s["id"])
        return ids

    def sources(self, feed=True, deleting=False):
        out = [self.source(i, feed) for i in self.source_ids()]
        return sorted([s for s in out if deleting or not s["deleting"]], key=lambda s: s["name"].lower())

    def find(self, what):
        """The source called `what` (its name, case aside), or with that URL or id."""
        key = str(what or "").strip()
        srcs = self.sources(feed=False)
        if key.isdigit():
            hit = [s for s in srcs if s["id"] == int(key)]
            if hit:
                return hit[0]
        hit = [s for s in srcs if s["name"].lower() == key.lower()] or \
              [s for s in srcs if _same_url(s["url"], key)]
        if not hit:
            hit = [s for s in srcs if key.lower() in s["name"].lower()]
        if len(hit) == 1:
            return hit[0]
        if not hit:
            raise NotFound(f"no source called {key!r}: `bromigos lab youtube list` shows them")
        raise PinchflatError(f"{key!r} could be {', '.join(repr(s['name']) for s in hit)}: give the whole name")

    def add(self, url, kind=None, since=None, name=None, quality=None, cookies=None):
        url, kind = normalise_url(url, kind)
        prof, made = self.profile_for(kind, quality or DEFAULT_QUALITY)
        changes = {"source[original_url]": url, "source[media_profile_id]": str(prof["id"])}
        if name:
            changes["source[custom_name]"] = name
        if since:
            changes["source[download_cutoff_date]"] = since
        if cookies:
            changes["source[cookie_behaviour]"] = COOKIE_ON
        loc = self.submit("/sources/new", "/sources", f"the {kind} {url}", changes, full=True,
                          need=("source[custom_name]", "source[download_cutoff_date]", "source[cookie_behaviour]",
                                "source[index_frequency_minutes]", "source[download_media]"))
        m = re.search(r"/sources/(\d+)", loc)
        if m:
            rec = self.source(int(m.group(1)), feed=False)
        else:                                       # Pinchflat's welcome page sends it home
            rec = next((s for s in self.sources(feed=False) if _same_url(s["url"], url)), None)
            if not rec:
                raise PinchflatError(f"Pinchflat took {url} but it isn't in its list of sources")
        rec["made_profile"] = made
        rec["asked_kind"] = kind
        return rec

    def remove(self, src, delete_files=False):
        q = "?delete_files=true" if delete_files else ""
        self.action(f"/sources/{src['id']}{q}", f"removing {src['name']!r}", method="delete",
                    page_path=f"/sources/{src['id']}")

    def set_enabled(self, src, on):
        self.submit(f"/sources/{src['id']}/edit", f"/sources/{src['id']}",
                    f"{'resuming' if on else 'pausing'} {src['name']!r}", {"source[enabled]": "true" if on else "false"})

    def set_profile(self, src, prof):
        self.submit(f"/sources/{src['id']}/edit", f"/sources/{src['id']}", f"the quality of {src['name']!r}",
                    {"source[media_profile_id]": str(prof["id"])}, need=("source[media_profile_id]",))

    def set_cookies(self, src, on):
        self.submit(f"/sources/{src['id']}/edit", f"/sources/{src['id']}", f"the cookie setting of {src['name']!r}",
                    {"source[cookie_behaviour]": COOKIE_ON if on else COOKIE_OFF}, need=("source[cookie_behaviour]",))

    def refresh(self, src):
        self.action(f"/sources/{src['id']}/force_index", f"checking {src['name']!r}", page_path=f"/sources/{src['id']}")

    def home(self):
        """{onboarding, active: [{task, subject}], recent: [{title, source, at, error}]} from the
        home page (Pinchflat's welcome page has none of it)."""
        page = self.get("/")
        if "Welcome to Pinchflat" in page.text and page.table("Downloaded At") is None:
            return {"onboarding": True, "active": [], "recent": []}
        active = [{"task": r[0]["text"], "subject": r[1]["text"] if len(r) > 1 else ""}
                  for r in page.table("Attempt No.") or []]
        recent = [{"title": r[0]["text"], "at": r[3]["text"] or None, "source": r[4]["text"] if len(r) > 4 else ""}
                  for r in page.table("Downloaded At") or [] if len(r) >= 4]
        return {"onboarding": False, "active": active, "recent": recent, "pending_total": (page.counts() + [None, None])[1]}

    def metrics(self):
        """(waiting downloads, failed jobs) from its Prometheus metrics, or (None, None)."""
        from .adapters import labcommon as L
        from .adapters.labmedia import QUEUE_METRIC, queue_from_metrics
        try:
            rows = L.rows_of(L.parse_prom(self.get("/metrics", raw=True)), QUEUE_METRIC)
        except Exception:
            return None, None
        return queue_from_metrics(rows)

    def version(self):
        try:
            m = re.search(r"Version:\s*v?([0-9][0-9.]+)", self.get("/app_info").text)
            return m.group(1) if m else None
        except Exception:
            return None


def _label(field):
    m = re.search(r"\[(\w+)\]", field or "")
    return (m.group(1) if m else field or "").replace("_", " ")


def _iso(t):
    if t is None:
        return None
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _same_url(a, b):
    def norm(u):
        u = str(u or "").strip().lower().rstrip("/")
        return re.sub(r"^https?://(www\.|m\.)?", "", u)
    return norm(a) == norm(b)


# ------------------------------------------------------------------ URLs and qualities
def resolve_quality(q):
    q = str(q or DEFAULT_QUALITY).strip().lower()
    q = {"4k": "2160p", "8k": "4320p", "1080": "1080p", "720": "720p", "audio-only": "audio"}.get(q, q)
    if q == "best":
        return BEST
    if q not in QUALITIES:
        raise PinchflatError(f"no quality {q!r}: one of {', '.join(CHOICES)}")
    return q


def normalise_url(url, kind=None):
    """(url, kind) for a YouTube channel or playlist. A video in a playlist (watch?v=…&list=…)
    becomes the playlist; a lone video is refused (Pinchflat downloads channels and playlists)."""
    u = str(url or "").strip()
    if not u:
        raise PinchflatError("give the URL of a YouTube channel or playlist")
    if not re.match(r"https?://", u):
        u = "https://" + u.lstrip("/") if re.match(r"(www\.|m\.)?youtube\.com/|youtu\.be/", u) else \
            ("https://www.youtube.com/" + u if u.startswith("@") else u)
    p = urllib.parse.urlparse(u)
    q = urllib.parse.parse_qs(p.query)
    host = p.netloc.lower()
    is_yt = host.endswith("youtube.com") or host == "youtu.be"
    if host in ("youtube.com", "m.youtube.com"):
        u = urllib.parse.urlunparse(p._replace(netloc="www.youtube.com"))
    if is_yt and q.get("list"):
        u = "https://www.youtube.com/playlist?list=" + q["list"][0]
    elif is_yt and (host == "youtu.be" or p.path.startswith(("/watch", "/shorts/", "/embed/", "/live/"))):
        raise PinchflatError(f"{url} is one video. Pinchflat downloads channels and playlists: give the "
                             f"channel's URL (youtube.com/@name) or a playlist's (youtube.com/playlist?list=…)")
    guess = "playlist" if "list=" in u or "/playlist" in p.path else "channel"
    if kind and kind != guess and is_yt:
        if kind == "playlist" and guess == "channel":
            raise PinchflatError(f"{url} is a channel's URL, not a playlist's; leave out --playlist, or give the "
                                 f"playlist's URL (youtube.com/playlist?list=…)")
    return u, kind or guess


# ------------------------------------------------------------------ cookies
class CookieError(PinchflatError):
    pass


def check_cookies(path):
    """{lines, youtube, expires} for a Netscape cookies.txt with youtube.com cookies, or
    CookieError. Never returns or prints a value."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        raise CookieError(f"can't read {path}: {e.strerror}") from None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise CookieError(f"{path} is empty")
    if text.lstrip().startswith(("{", "[")):
        raise CookieError(f"{path} is JSON. Pinchflat needs the Netscape cookies.txt format: export it with a "
                          f"cookies.txt exporter (the browser add-on 'Get cookies.txt LOCALLY', or yt-dlp "
                          f"--cookies-from-browser … --cookies FILE)")
    yt, other, bad, expires = 0, 0, 0, []
    for ln in lines:
        if ln.startswith("#HttpOnly_"):
            ln = ln[len("#HttpOnly_"):]
        elif ln.startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) != 7:
            bad += 1
            continue
        dom = parts[0].lower().lstrip(".")
        if dom == "youtube.com" or dom.endswith(".youtube.com"):
            yt += 1
            if parts[4].isdigit() and int(parts[4]) > 0:
                expires.append(int(parts[4]))
        else:
            other += 1
    if bad and not (yt or other):
        raise CookieError(f"{path} isn't a Netscape cookies.txt (each line: seven fields separated by tabs)")
    if not yt:
        raise CookieError(f"{path} has no youtube.com cookies: export them while signed in to YouTube")
    return {"youtube": yt, "other": other, "skipped": bad, "expires": min(expires) if expires else None}


class CookieStore:
    """Where Pinchflat's cookies.txt comes from. "vault:PATH#FIELD": a Vault KV field (and
    FIELD_set_at beside it), written with the `vault` CLI and its login; on a lab whose
    Pinchflat reads its cookies from Vault (an ExternalSecret), that's all it takes.
    "file:PATH": the file Pinchflat reads."""

    def __init__(self, spec, vault="vault"):
        self.spec = str(spec or "").strip()
        self.vault = vault
        kind, _, rest = self.spec.partition(":")
        self.kind = kind if rest else ""
        if self.kind == "vault":
            self.path, _, self.field = rest.partition("#")
            self.field = self.field or "cookies"
        elif self.kind == "file":
            self.path = os.path.expanduser(rest)
        else:
            raise PinchflatError(
                "no cookie store: set cookies_store on the pinchflat source in homelab.toml, to "
                "\"vault:KV_PATH#FIELD\" (a lab whose Pinchflat reads its cookies from Vault) or \"file:PATH\" (the "
                "cookies.txt Pinchflat reads, in its config folder's extras/)")

    def where(self):
        return "Vault" if self.kind == "vault" else self.path

    def _vault(self, *args, stdin=None):
        try:
            p = subprocess.run([self.vault, *args], capture_output=True, text=True, timeout=30, input=stdin)
        except FileNotFoundError:
            raise PinchflatError("the cookie store is Vault, and the vault CLI isn't installed") from None
        except subprocess.TimeoutExpired:
            raise PinchflatError("Vault didn't answer in 30 s") from None
        if p.returncode:
            err = (p.stderr or "").strip().splitlines()
            raise PinchflatError("Vault refused: " + (err[-1][:200] if err else f"exit {p.returncode}") +
                                 " (is `vault login` done?)")
        return p.stdout

    def _read(self):
        """{field: value} of the KV path ({} when it has none)."""
        try:
            d = json.loads(self._vault("kv", "get", "-format=json", self.path) or "{}")
        except PinchflatError as e:
            if "No value found" in str(e):
                return {}
            raise
        data = (d.get("data") or {})
        return data.get("data", data) or {}

    def status(self):
        """{present, set_at, age_days, youtube}: never the cookies themselves."""
        if self.kind == "vault":
            d = self._read()
            val = d.get(self.field) or ""
            at = d.get(self.field + "_set_at") or None
        else:
            try:
                with open(self.path, encoding="utf-8", errors="replace") as f:
                    val = f.read()
                at = _iso(os.path.getmtime(self.path))
            except OSError:
                val, at = "", None
        present = bool(val.strip())
        yt = sum(1 for ln in val.splitlines() if "youtube.com" in ln.split("\t", 1)[0]) if present else 0
        del val
        age = None
        if present and at:
            try:
                t = datetime.datetime.fromisoformat(at.replace("Z", "+00:00"))
                age = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 86400
            except ValueError:
                age = None
        return {"present": present, "set_at": at if present else None, "age_days": round(age, 1) if age is not None else None,
                "youtube": yt, "store": self.where()}

    def set(self, path):
        now = _iso(time.time())
        if self.kind == "vault":
            have = self._read()
            verb = "patch" if have else "put"
            self._vault("kv", verb, self.path, f"{self.field}=@{os.path.abspath(path)}", f"{self.field}_set_at={now}")
        else:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(path, "rb") as src:
                data = src.read()
            fd = os.open(self.path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(self.path + ".tmp", self.path)

    def clear(self):
        """Empty, not deleted: an empty cookies.txt is no cookies to Pinchflat, and a store
        another system copies from (an ExternalSecret) copies the empty one too."""
        if self.kind == "vault":
            if self._read():
                self._vault("kv", "patch", self.path, f"{self.field}=-", f"{self.field}_set_at=", stdin="")
        elif os.path.exists(self.path):
            with open(self.path, "w"):
                pass


# ------------------------------------------------------------------ configuration
def settings(name=None):
    """{url, auth, ctx, store, quality, base_profiles} from the environment and homelab.toml."""
    src, yt, ctx, auth = None, {}, None, ""
    try:
        from . import config
        from .adapters.labmedia import Pinchflat as Adapter
        srcs = [s for s in config.sources() if s.get("type") == "pinchflat"]
        if name:
            srcs = [s for s in srcs if s.get("name") == name]
            if not srcs:
                raise PinchflatError(f"no pinchflat source called {name!r} in homelab.toml")
        src = srcs[0] if srcs else None
        yt = config.table("youtube")
        if src:
            a = Adapter(src)
            ctx = a._ctx()
            auth = a.credentials()
    except ImportError:
        pass
    env = os.environ.get
    url = env("PINCHFLAT_URL") or (src or {}).get("endpoint")
    if env("PINCHFLAT_AUTH"):
        auth = env("PINCHFLAT_AUTH")
    bases = {k: yt.get(f"{k}_profile") for k in ("channel", "playlist") if yt.get(f"{k}_profile")}
    return {"url": url, "auth": auth, "ctx": ctx, "store": env("PINCHFLAT_COOKIES_STORE") or (src or {}).get("cookies_store"),
            "quality": env("YOUTUBE_QUALITY") or yt.get("quality") or DEFAULT_QUALITY, "base_profiles": bases,
            "name": (src or {}).get("name") or "pinchflat"}


def connect(name=None):
    s = settings(name)
    return Pinchflat(s["url"], s["auth"], s["ctx"], base_profiles=s["base_profiles"]), s


# ------------------------------------------------------------------ the commands
def add_source(pf, s, url, kind=None, since=None, name=None, quality=None):
    """`add` for the command line and the lab console's form: checks the date, uses the YouTube
    cookies when the store has some, and the lab's default quality."""
    if since:
        try:
            datetime.date.fromisoformat(since)
        except ValueError:
            raise PinchflatError(f"--since {since!r}: give a date as YYYY-MM-DD") from None
    cookies = False
    if s.get("store"):
        try:
            cookies = CookieStore(s["store"]).status()["present"]
        except PinchflatError:
            cookies = False
    return pf.add(url, kind, since, name or None, quality or s.get("quality"), cookies)


def cmd_add(pf, s, a):
    kind = "playlist" if a.playlist else "channel" if a.channel else None
    return add_source(pf, s, a.url, kind, a.since, a.name, a.quality)


def describe_add(rec):
    kind = rec.get("kind") or rec.get("asked_kind") or "source"
    q = rec.get("quality") or "?"
    what = "every video in the playlist, in its order" if kind == "playlist" else "every video on the channel"
    if rec.get("since"):
        what += f" uploaded after {rec['since']}"
    lines = [f"Added {rec['name']!r} ({kind}) to Pinchflat.",
             f"  It will download {what}, at {'audio only' if q == 'audio' else q}"
             f" ({rec.get('profile') or 'its media profile'}).",
             "  Pinchflat reads the list now; the first videos usually arrive within minutes, then it checks "
             "again once a day."]
    if rec.get("made_profile"):
        lines.append(f"  Made the media profile {rec['profile']!r} for that quality (a copy of the usual one).")
    if rec.get("cookies") == COOKIE_ON:
        lines.append("  It uses the YouTube cookies when YouTube asks for a sign-in.")
    return "\n".join(lines)


def _when(iso):
    return (iso or "")[:16].replace("T", " ") or "never"


def print_list(rows):
    if not rows:
        print("No sources yet. Add one: bromigos lab youtube add URL")
        return
    print(f"{'name':<34} {'kind':<9} {'quality':<8} {'videos':>6} {'waiting':>7}  {'last check':<16}  newest")
    for r in rows:
        name = r["name"][:33] + ("" if r["enabled"] else " (paused)")[: max(0, 34 - len(r["name"][:33]))]
        print(f"{name:<34} {r['kind'] or '?':<9} {r['quality'] or '?':<8} {_n(r['downloaded']):>6} "
              f"{_n(r['pending']):>7}  {_when(r['last_check']):<16}  {(r['newest'] or '-')[:50]}")


def _n(v):
    return "?" if v is None else str(v)


def status(pf):
    queue, failed = pf.metrics()
    home = pf.home()
    srcs = pf.sources(feed=True, deleting=True)
    recent = home["recent"]           # the home page's, with when each downloaded
    if not recent:                    # its welcome page has none: the feeds', by upload date
        recent = sorted((i for s in srcs if not s["deleting"] for i in s.get("recent") or []),
                        key=lambda r: r["uploaded"] or "", reverse=True)
    return {"version": pf.version(), "tested": TESTED, "queue": queue, "failed": failed, "active": home["active"],
            "pending": sum(s["pending"] or 0 for s in srcs if not s["deleting"]),
            "downloaded": sum(s["downloaded"] or 0 for s in srcs if not s["deleting"]),
            "sources": len([s for s in srcs if not s["deleting"]]),
            "paused": [s["name"] for s in srcs if not s["enabled"] and not s["deleting"]],
            "deleting": [s["name"] for s in srcs if s["deleting"]], "recent": recent[:8]}


def print_status(d):
    v = d.get("version")
    print(f"Pinchflat {('v' + v) if v else ''}".rstrip() + (f"  (this was tested with v{TESTED})" if v and v != TESTED else ""))
    print(f"  {d['sources']} sources · {d['downloaded']} videos downloaded · {d['pending']} waiting to download"
          + (f" · paused: {', '.join(d['paused'])}" if d["paused"] else ""))
    if d["deleting"]:
        print(f"  Being removed: {', '.join(d['deleting'])}")
    print("  Download queue: " + (f"{d['queue']} jobs" if d["queue"] is not None else
                                  "unknown (turn on Pinchflat's metrics: ENABLE_PROMETHEUS=true)"))
    if d["failed"]:
        print(f"  Failed in the last 30 days: {d['failed']} jobs (Pinchflat's History page says why)")
    elif d["failed"] == 0:
        print("  Failed in the last 30 days: none")
    for t in d["active"]:
        print(f"  Now: {t['task']}: {t['subject']}")
    if d["recent"]:
        up = "uploaded" in d["recent"][0]
        print("  Recent downloads" + (" (newest uploads first):" if up else ":"))
        for r in d["recent"]:
            when = (r.get("uploaded") or "")[:10] if up else (r.get("at") or "")
            print(f"    {when:<16}  {r['title'][:60]}  ({r['source']})")


def cmd_cookies(pf, s, a):
    store = CookieStore(s.get("store"))
    if a.verb == "status":
        st = store.status()
        st["sources_using"] = None
        try:
            st["sources_using"] = sum(1 for x in pf.sources(feed=False) if x["cookies"] and x["cookies"] != COOKIE_OFF)
        except PinchflatError:
            pass
        st["stale"] = bool(st["present"] and st["age_days"] is not None and st["age_days"] > COOKIE_MAX_DAYS)
        return st
    if a.verb == "set":
        info = check_cookies(a.file)
        store.set(a.file)
        changed = []
        for x in pf.sources(feed=False):
            if x["cookies"] != COOKIE_ON:
                pf.set_cookies(x, True)
                changed.append(x["name"])
        return {"set": True, "youtube": info["youtube"], "store": store.where(), "sources_changed": changed}
    store.clear()
    changed = []
    for x in pf.sources(feed=False):
        if x["cookies"] not in (None, COOKIE_OFF):
            pf.set_cookies(x, False)
            changed.append(x["name"])
    return {"cleared": True, "store": store.where(), "sources_changed": changed}


def print_cookies(verb, d):
    if verb == "status":
        if not d["present"]:
            print(f"No YouTube cookies (store: {d['store']}). Pinchflat downloads without signing in.")
        else:
            age = f", {d['age_days']:.0f} days ago" if d["age_days"] is not None else ""
            print(f"YouTube cookies are set ({d['youtube']} youtube.com cookies; set {_when(d['set_at'])}{age}; "
                  f"store: {d['store']}).")
            if d["stale"]:
                print(f"  They're over {COOKIE_MAX_DAYS} days old: YouTube may have signed them out. Export fresh "
                      "ones and run: bromigos lab youtube cookies set FILE")
        if d.get("sources_using") is not None:
            print(f"  {d['sources_using']} sources use them when YouTube asks.")
    elif verb == "set":
        print(f"Stored {d['youtube']} youtube.com cookies ({d['store']}); none was shown.")
        print(f"  Cookie Behaviour is now \"When Needed\" on {len(d['sources_changed'])} sources.")
        print("  Delete the exported file now: the store has its own copy.")
    else:
        print(f"Removed the YouTube cookies ({d['store']}); Cookie Behaviour is off on {len(d['sources_changed'])} sources.")


def confirm(question):
    if not sys.stdin.isatty():
        raise PinchflatError("this asks first, and there's no terminal to ask in: add --yes")
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def parser():
    p = argparse.ArgumentParser(prog="bromigos lab youtube", description="Control Pinchflat, the YouTube "
                                "downloader, without its web page (docs/lab.md).")
    p.add_argument("--source", dest="pinchflat", help="the pinchflat source in homelab.toml (the first one)")
    sub = p.add_subparsers(dest="cmd")

    def cmd(name, help):
        c = sub.add_parser(name, help=help, description=help)
        c.add_argument("--json", action="store_true", help="print JSON")
        return c
    c = cmd("add", "download a channel or a playlist")
    c.add_argument("url", help="the channel's or playlist's URL")
    k = c.add_mutually_exclusive_group()
    k.add_argument("--playlist", action="store_true", help="it's a playlist (the URL says, usually)")
    k.add_argument("--channel", action="store_true", help="it's a channel (the URL says, usually)")
    c.add_argument("--since", metavar="DATE", help="only videos uploaded after this date (YYYY-MM-DD)")
    c.add_argument("--name", help="the name in Pinchflat and on disk (YouTube's, if left out)")
    c.add_argument("--quality", choices=CHOICES, help="the most it downloads: best (the highest there is), 2160p "
                   "(4K) … 480p, or audio. Default: [youtube] quality in homelab.toml, else 1080p")
    cmd("list", "every source: kind, quality, videos, last check, newest video")
    c = cmd("remove", "stop downloading a source (asks first)")
    c.add_argument("source", metavar="NAME|URL")
    c.add_argument("--delete-files", action="store_true", help="delete its downloaded videos too (kept by default)")
    c.add_argument("--yes", "-y", action="store_true", help="don't ask")
    for v, h in (("pause", "stop checking and downloading a source (keeps it)"), ("resume", "start it again")):
        c = cmd(v, h)
        c.add_argument("source", metavar="NAME|URL")
    c = cmd("refresh", "check a source (or every source) for new videos now")
    c.add_argument("source", metavar="NAME|URL", nargs="?")
    cmd("status", "the download queue, failures and recent downloads")
    c = cmd("quality", "change a source's quality (new downloads only)")
    c.add_argument("source", metavar="NAME|URL")
    c.add_argument("quality", choices=CHOICES)
    c = cmd("cookies", "YouTube cookies for when YouTube asks Pinchflat to sign in")
    cs = c.add_subparsers(dest="verb")
    x = cs.add_parser("set", help="store a cookies.txt (Netscape format, youtube.com) and use it")
    x.add_argument("file")
    x.add_argument("--json", action="store_true")
    for v, h in (("clear", "remove the cookies and stop using them"), ("status", "are there cookies, and how old")):
        x = cs.add_parser(v, help=h)
        x.add_argument("--json", action="store_true")
    return p


def main(argv=None):
    p = parser()
    a = p.parse_args(argv)
    if not a.cmd or (a.cmd == "cookies" and not a.verb):
        p.print_help(sys.stderr)
        return 2
    js = getattr(a, "json", False)
    try:
        pf, s = connect(a.pinchflat)
        out = run(pf, s, a)
    except PinchflatError as e:
        if js:
            print(json.dumps({"error": str(e)}))
        print(f"youtube {a.cmd}: {e}", file=sys.stderr)
        return 1 if not isinstance(e, NotFound) else 4
    if out is None:
        return 1
    if js:
        print(json.dumps(out, indent=1))
    return 0


def run(pf, s, a):
    """One command; prints its words unless --json, and returns its record (None: declined)."""
    js = getattr(a, "json", False)
    say = (lambda *x: None) if js else print
    if a.cmd == "add":
        rec = cmd_add(pf, s, a)
        say(describe_add(rec))
        return rec
    if a.cmd == "list":
        rows = pf.sources()
        if not js:
            print_list(rows)
        return rows
    if a.cmd == "status":
        d = status(pf)
        if not js:
            print_status(d)
        return d
    if a.cmd == "cookies":
        d = cmd_cookies(pf, s, a)
        if not js:
            print_cookies(a.verb, d)
        return d
    if a.cmd == "refresh":
        srcs = [pf.find(a.source)] if a.source else pf.sources(feed=False)
        for x in srcs:
            pf.refresh(x)
        say(f"Checking {', '.join(repr(x['name']) for x in srcs)} for new videos now." if srcs else "No sources to check.")
        return {"refreshed": [x["name"] for x in srcs]}
    src = pf.find(a.source)
    if a.cmd in ("pause", "resume"):
        on = a.cmd == "resume"
        pf.set_enabled(src, on)
        say(f"{'Resumed' if on else 'Paused'} {src['name']!r}" + (": it checks for new videos and downloads again."
                                                                   if on else ": no checking or downloading until "
                                                                   "`bromigos lab youtube resume`."))
        return dict(src, enabled=on)
    if a.cmd == "quality":
        prof, made = pf.profile_for(src["kind"] or "channel", a.quality)
        if prof["id"] != src["profile_id"]:
            pf.set_profile(src, prof)
        say(f"{src['name']!r} now downloads at {prof['quality']} ({prof['name']}). This is for new downloads only: "
            f"the videos already on disk stay as they are.")
        return dict(src, profile=prof["name"], profile_id=prof["id"], quality=prof["quality"], made_profile=made)
    if a.cmd == "remove":
        full = pf.source(src["id"], feed=False)
        n = full["downloaded"]
        files = (f"and delete its {n if n is not None else ''} downloaded videos from disk".replace("  ", " ")
                 if a.delete_files else "Its downloaded videos stay on disk")
        if not a.yes and not confirm(f"Remove {src['name']!r} ({src['kind'] or 'source'}) from Pinchflat"
                                     + (f" {files}?" if a.delete_files else f"? {files}.")):
            say("Nothing removed.")
            return None
        pf.remove(src, a.delete_files)
        say(f"Removing {src['name']!r}" + (" and its files" if a.delete_files else "") +
            ". Pinchflat finishes in the background, usually within a minute.")
        return {"removed": src["name"], "id": src["id"], "delete_files": bool(a.delete_files)}
    raise PinchflatError(f"no command {a.cmd!r}")


if __name__ == "__main__":
    sys.exit(main())
