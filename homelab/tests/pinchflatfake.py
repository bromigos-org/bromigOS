"""A fake Pinchflat v2025.9.26 on 127.0.0.1, built from pages recorded from a real one
(fixtures/pinchflat/: GET pages only, the host, tokens and ids replaced).

It keeps media profiles and sources in memory and renders them into the recorded pages: the
Media Profiles table, a profile's Sources table, a source's Raw Attributes and counts, the
New Source form's profile list. It checks what Phoenix checks: basic auth, the session
cookie and its CSRF token on every POST, a source URL that isn't a video's. A good form
answers 302, a bad one the form again with Pinchflat's error markup. Every POST is logged.
"""
import html
import json
import os
import re
import threading
import urllib.parse
import uuid as uuidlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "pinchflat")
AUTH = "admin:hunter2"
FEED_UUID = "00000000-1111-4222-8333-444444444444"
CHANNEL_TEMPLATE = ("/channels/{{ source_custom_name }}/{{ season_by_year__episode_by_date_and_index }} - "
                    "{{ title }} [{{ id }}].{{ ext }}")
VIDEO_URL = re.compile(r"^(?:(?!youtube\.com/(watch|shorts|embed)|youtu\.be).)*$")   # Source's validation


def page(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def _attr(text, key, value):
    """Set one Raw Attributes entry (<strong>key:</strong> <code …>value</code>)."""
    pat = re.compile(r"(<strong>" + re.escape(key) + r":</strong>\s*<code[^>]*>)(.*?)(</code>)", re.S)
    return pat.sub(lambda m: m.group(1) + html.escape(str(value if value is not None else "")) + m.group(3), text, 1)


def _value(text, name, value):
    """An <input name=…>'s value attribute set to `value`."""
    def one(m):
        tag = re.sub(r'\svalue="[^"]*"', "", m.group(0))
        return tag[:-1] + f' value="{html.escape(str(value), quote=True)}">'
    return re.sub(r'<input[^>]*name="' + re.escape(name) + r'"[^>]*>', one, text, count=1)


def _selected(text, name, value):
    """A <select name=…> with `value` selected."""
    def one(m):
        body = m.group(2).replace("<option selected ", "<option ")
        body = body.replace(f'<option value="{value}">', f'<option selected value="{value}">', 1)
        return m.group(1) + body + m.group(3)
    return re.sub(r'(<select[^>]*name="' + re.escape(name) + r'"[^>]*>)(.*?)(</select>)', one, text, count=1, flags=re.S)


def _count_markup(n):
    if not n:
        return "Nothing Here!"
    return (f'Showing <span x-data x-text="Intl.NumberFormat().format({min(n, 10)})">{min(n, 10)}</span> of '
            f'<span x-data x-text="Intl.NumberFormat().format({n})">{n}</span>')


class State:
    def __init__(self):
        self.onboarding = True
        self.profiles = {
            1: {"id": 1, "name": "Channels (Media Center)", "preferred_resolution": "1080p",
                "output_path_template": CHANNEL_TEMPLATE},
            2: {"id": 2, "name": "Playlists (in order)", "preferred_resolution": "1080p",
                "output_path_template": "/playlists/{{ source_custom_name }}/{{ static_season__episode_by_index }} - "
                                        "{{ title }} [{{ id }}].{{ ext }}"}}
        self.sources = {}
        self.posts = []                    # (path, fields)
        self.next_id = 3
        self.names = {}                    # URL -> YouTube's name for it
        self.metrics = page("metrics.txt")
        self.break_form = None             # a field name to leave out of the New Source form
        self.lock = threading.Lock()

    def add_source(self, **kw):
        sid = self.next_id
        self.next_id += 1
        s = {"id": sid, "uuid": str(uuidlib.uuid4()), "custom_name": "", "collection_name": "", "collection_type": "playlist",
             "original_url": "", "enabled": "true", "media_profile_id": 2, "cookie_behaviour": "disabled",
             "download_cutoff_date": "", "last_indexed_at": "2026-10-10T07:42:31Z", "index_frequency_minutes": "1440",
             "download_media": "true", "fast_index": "false", "marked_for_deletion_at": "", "downloaded": 4,
             "pending": 0, "delete_files": None}
        s.update(kw)
        self.sources[sid] = s
        return s


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        self.state = State()
        self.sessions = {}
        super().__init__(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server_address[1]}"
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def close(self):
        self.shutdown()
        self.server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    @property
    def st(self):
        return self.server.state

    # ---- plumbing
    def _authed(self):
        import base64
        h = self.headers.get("Authorization") or ""
        return h == "Basic " + base64.b64encode(AUTH.encode()).decode()

    def _session(self):
        m = re.search(r"_pinchflat_key=([\w-]+)", self.headers.get("Cookie") or "")
        return m.group(1) if m else None

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text, sess):
        """A page for this session: its CSRF token in place of the recorded one."""
        token = f"csrf-{sess}"
        text = text.replace("FIXTURE-CSRF", token)
        return text

    def _redirect(self, to):
        self._send(302, b"", headers={"Location": to})

    # ---- GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path, q = u.path, urllib.parse.parse_qs(u.query)
        if path == "/healthcheck":
            return self._send(200, b'{"status":"ok"}', "application/json")
        m = re.fullmatch(r"/sources/([0-9a-f-]{36})/feed(?:\.xml)?", path)
        if m:
            s = next((s for s in self.st.sources.values() if s["uuid"] == m.group(1)), None)
            if not s:
                return self._send(404, b"not found")
            return self._send(200, page("feed.xml").replace(FEED_UUID, s["uuid"]), "application/rss+xml")
        if path == "/sources/opml.xml" or path == "/sources/opml":
            if q.get("route_token") != ["FIXTURE-ROUTE-TOKEN"]:
                return self._send(401, b"")
            outl = "".join(f'<outline type="rss" text="{html.escape(s["custom_name"])}" xmlUrl="{self.server.url}'
                           f'/sources/{s["uuid"]}/feed.xml" />' for s in self.live())
            return self._send(200, f'<?xml version="1.0"?><opml version="2.0"><body>{outl}</body></opml>',
                              "application/xml")
        if path == "/metrics":
            return self._send(200, self.st.metrics, "text/plain")
        if not self._authed():
            return self._send(401, b"Unauthorized", headers={"WWW-Authenticate": 'Basic realm="Pinchflat"'})
        sess = self._session()
        cookie = {}
        if not sess:
            sess = uuidlib.uuid4().hex[:12]
            cookie = {"Set-Cookie": f"_pinchflat_key={sess}; path=/; HttpOnly"}
        with self.st.lock:
            body = self.render(path, q)
        if body is None:
            return self._send(404, b"not found", headers=cookie)
        self._send(200, self._html(body, sess), headers=cookie)

    def live(self):
        return [s for s in self.st.sources.values() if not s["marked_for_deletion_at"]]

    def render(self, path, q):
        st = self.st
        if path == "/":
            return page("home_welcome.html")
        if path == "/app_info":
            return page("app_info.html")
        if path == "/sources":
            return page("sources.html")
        if path == "/media_profiles":
            text = page("profiles.html")
            head, rest = text.split("<tbody>", 1)
            body, tail = rest.split("</tbody>", 1)
            row = re.search(r"<tr.*?</tr>", body, re.S).group(0)
            rows = ""
            for p in sorted(st.profiles.values(), key=lambda p: p["name"].lower()):
                n = sum(1 for s in st.sources.values() if s["media_profile_id"] == p["id"])
                r = row.replace("/media_profiles/1", f"/media_profiles/{p['id']}")
                r = r.replace("Channels (Media Center)", html.escape(p["name"]))
                r = re.sub(r"(<td[^>]*>\s*)1080p(\s*</td>)", lambda m: m.group(1) + p["preferred_resolution"] + m.group(2), r)
                r = r.replace('format(0)">0<', f'format({n})">{n}<')
                rows += r
            return head + "<tbody>" + rows + "</tbody>" + tail
        m = re.fullmatch(r"/media_profiles/(\d+)", path)
        if m:
            p = st.profiles.get(int(m.group(1)))
            if not p:
                return None
            text = page("profile_show.html")
            head, rest = text.split("<tbody>", 1)
            body, tail = rest.split("</tbody>", 1)
            row = re.search(r"<tr.*?</tr>", body, re.S).group(0)
            rows = ""
            for s in sorted(st.sources.values(), key=lambda s: s["custom_name"].lower()):
                if s["media_profile_id"] != p["id"]:
                    continue                          # (Pinchflat lists ones being deleted too)
                r = row.replace("/sources/3", f"/sources/{s['id']}").replace("Little SDO", html.escape(s["custom_name"]))
                r = re.sub(r"(<td[^>]*>\s*)playlist(\s*</td>)", lambda m: m.group(1) + s["collection_type"] + m.group(2), r)
                rows += r
            out = head + "<tbody>" + rows + "</tbody>" + tail
            for k in ("name", "preferred_resolution", "output_path_template"):
                out = _attr(out, k, p[k])
            return _attr(out, "id", p["id"])
        if path == "/media_profiles/new":
            tid = int((q.get("template_id") or ["0"])[0] or 0)
            p = st.profiles.get(tid)
            text = page("profile_new.html")
            if p:
                text = _value(text, "media_profile[output_path_template]", p["output_path_template"])
                text = _selected(text, "media_profile[preferred_resolution]", p["preferred_resolution"])
            return text
        m = re.fullmatch(r"/media_profiles/(\d+)/edit", path)
        if m:
            p = st.profiles.get(int(m.group(1)))
            if not p:
                return None
            text = page("profile_edit.html").replace('action="/media_profiles/2"', f'action="/media_profiles/{p["id"]}"')
            text = _value(text, "media_profile[name]", p["name"])
            text = _value(text, "media_profile[output_path_template]", p["output_path_template"])
            return _selected(text, "media_profile[preferred_resolution]", p["preferred_resolution"])
        if path == "/sources/new":
            text = page("source_new.html")
            opts = "".join(f'<option value="{p["id"]}">{html.escape(p["name"])}</option>'
                           for p in sorted(st.profiles.values(), key=lambda p: p["name"].lower()))
            text = re.sub(r'(<select id="source_media_profile_id"[^>]*>).*?(</select>)',
                          lambda m: m.group(1) + opts + m.group(2), text, flags=re.S)
            if st.break_form:
                text = re.sub(r'<(input|select)[^>]*name="' + re.escape(st.break_form) + r'"', "<\\1 ", text)
            return text
        m = re.fullmatch(r"/sources/(\d+)(/edit)?", path)
        if m:
            s = st.sources.get(int(m.group(1)))
            if not s:
                return None
            if m.group(2):
                return page("source_edit.html").replace('action="/sources/3"', f'action="/sources/{s["id"]}"')
            text = page("source_show.html").replace(FEED_UUID, s["uuid"])
            for k in ("custom_name", "collection_name", "collection_type", "original_url", "enabled", "uuid",
                      "media_profile_id", "cookie_behaviour", "download_cutoff_date", "last_indexed_at",
                      "marked_for_deletion_at", "id"):
                text = _attr(text, k, s[k])
            counts = iter([s["pending"], s["downloaded"], 0])

            def sub(mm):
                try:
                    return _count_markup(next(counts))
                except StopIteration:
                    return mm.group(0)
            return re.sub(r"Showing\s*<span[^>]*>[^<]*</span>\s*of\s*<span[^>]*>[^<]*</span>|Nothing Here!", sub, text)
        return None

    # ---- POST
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        path, q = u.path, urllib.parse.parse_qs(u.query)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode()
        fields = urllib.parse.parse_qsl(raw, keep_blank_values=True)
        f = dict(fields)                                    # Plug: the last value of a name wins
        if not self._authed():
            return self._send(401, b"Unauthorized")
        sess = self._session()
        if not sess or f.get("_csrf_token") != f"csrf-{sess}":
            return self._send(403, b"invalid CSRF (Cross Site Request Forgery) token")
        with self.st.lock:
            self.st.posts.append((self.path, f))
            self.post(path, q, f, sess)

    def post(self, path, q, f, sess):
        st = self.st
        method = (f.get("_method") or "post").lower()
        if path == "/sources":
            url = f.get("source[original_url]", "")
            pid = _num(f.get("source[media_profile_id]"))
            err = None
            if not url:
                err = ("source[original_url]", "can&#39;t be blank")
            elif not VIDEO_URL.match(url):
                err = ("source[original_url]", "must be a channel or playlist URL")
            elif pid not in st.profiles:
                err = ("source[media_profile_id]", "does not exist")
            if err:
                text = page("source_new.html")
                text = text.replace(f'name="{err[0]}"', f'name="{err[0]}"', 1)
                i = text.index(f'name="{err[0]}"')
                j = text.index(">", i) + 1
                text = text[:j] + ('<p class="mt-1 mb-5 flex gap-3 text-md leading-6 text-rose-600 '
                                   'phx-no-feedback:hidden"><span class="hero-exclamation-circle-mini"></span>'
                                   f"{err[1]}</p>") + text[j:]
                return self._send(200, self._html(text, sess))
            kind = "playlist" if "list=" in url else "channel"
            name = f.get("source[custom_name]") or st.names.get(url) or ("A Playlist" if kind == "playlist" else "A Channel")
            s = st.add_source(custom_name=name, collection_name=st.names.get(url, name), collection_type=kind,
                              original_url=url, media_profile_id=pid, downloaded=0, pending=0,
                              cookie_behaviour=f.get("source[cookie_behaviour]", "disabled"),
                              download_cutoff_date=f.get("source[download_cutoff_date]", ""),
                              last_indexed_at="", form=f)
            return self._redirect("/?onboarding=1" if st.onboarding else f"/sources/{s['id']}")
        m = re.fullmatch(r"/sources/(\d+)(/force_index)?", path)
        if m:
            s = st.sources.get(int(m.group(1)))
            if not s:
                return self._send(404, b"")
            if m.group(2):
                s["indexed"] = s.get("indexed", 0) + 1
                return self._redirect(f"/sources/{s['id']}")
            if method == "delete":
                s["marked_for_deletion_at"] = "2026-10-10T08:00:00Z"
                s["delete_files"] = q.get("delete_files") == ["true"]
                return self._redirect("/sources")
            if method in ("patch", "put"):
                for k, v in f.items():
                    mm = re.fullmatch(r"source\[(\w+)\]", k)
                    if mm:
                        s[mm.group(1)] = _num(v) if mm.group(1) == "media_profile_id" else v
                return self._redirect(f"/sources/{s['id']}")
        if path == "/media_profiles":
            pid = max(st.profiles) + 1
            st.profiles[pid] = {"id": pid, "name": f.get("media_profile[name]", ""),
                                "preferred_resolution": f.get("media_profile[preferred_resolution]", "1080p"),
                                "output_path_template": f.get("media_profile[output_path_template]", ""), "form": f}
            return self._redirect(f"/media_profiles/{pid}")
        m = re.fullmatch(r"/media_profiles/(\d+)", path)
        if m and int(m.group(1)) in st.profiles:
            p = st.profiles[int(m.group(1))]
            if method == "delete":
                del st.profiles[p["id"]]
                return self._redirect("/media_profiles")
            for k, v in f.items():
                mm = re.fullmatch(r"media_profile\[(\w+)\]", k)
                if mm:
                    p[mm.group(1)] = v
            return self._redirect(f"/media_profiles/{p['id']}")
        self._send(404, b"")


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def fake_vault(tmpdir):
    """A `vault` CLI on PATH that keeps one KV store in a JSON file (kv get -format=json,
    kv put, kv patch; FIELD=@file and FIELD=- read like the real one)."""
    store = os.path.join(tmpdir, "vault.json")
    script = os.path.join(tmpdir, "vault")
    with open(script, "w") as fh:
        fh.write(f'''#!/usr/bin/env python3
import json, os, sys
STORE = {store!r}
d = json.load(open(STORE)) if os.path.exists(STORE) else {{}}
a = sys.argv[1:]
if a[:1] != ["kv"]:
    sys.exit(2)
verb, rest = a[1], [x for x in a[2:] if not x.startswith("-format")]
path = rest[0]
if verb == "get":
    if path not in d:
        print("No value found at " + path, file=sys.stderr); sys.exit(2)
    print(json.dumps({{"data": {{"data": d[path], "metadata": {{}}}}}})); sys.exit(0)
if verb == "patch" and path not in d:
    print("No value found at " + path, file=sys.stderr); sys.exit(2)
cur = dict(d.get(path, {{}})) if verb == "patch" else {{}}
for kv in rest[1:]:
    k, _, v = kv.partition("=")
    if v.startswith("@"):
        v = open(v[1:]).read()
    elif v == "-":
        v = sys.stdin.read()
    cur[k] = v
d[path] = cur
json.dump(d, open(STORE, "w"))
print("Success! Data written to: " + path)
''')
    os.chmod(script, 0o755)
    return script, store


def homelab_toml(tmpdir, url, extra=""):
    p = os.path.join(tmpdir, "homelab.toml")
    cred = os.path.join(tmpdir, "basic")
    with open(cred, "w") as fh:
        fh.write(AUTH)
    with open(p, "w") as fh:
        fh.write(f'[[source]]\nname = "pinchflat"\ntype = "pinchflat"\nendpoint = "{url}"\n'
                 f'auth_ref = "@file:{cred}"\n{extra}\n')
    return p


if __name__ == "__main__":                            # by hand: python3 pinchflatfake.py
    s = Server()
    print(s.url, "(user:password", AUTH + ")")
    threading.Event().wait()
