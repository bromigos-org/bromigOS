"""Lab jobs (docs/activity.md, "Lab jobs"): what the lab is making, read as activity records,
so `bromigos activity`, the Lab board and the start page show it beside the server's own jobs.

Two sources:

  ComfyUI        each configured ComfyUI's queue and history (GET /queue, /history), and its
                 websocket (/ws) for the node that runs, the sampler's steps and the preview
                 frames. One record per prompt: its workflow, a short prompt, its stages as
                 steps, how far it is, the queue behind it, and its outputs.
  job feeds      JSON lines a multi-step tool appends to, one file per run (the format below):
                 the house progress lines `bromigos activity run` reads (::step, ::stage,
                 ::item, ::note, ::error), plus thumbnails and outputs. A feed reads exactly as
                 a job run under `bromigos activity run` would: the lines go through the same
                 record (bromigos_activity.Job.feed), in memory.

  instances(where)            the ComfyUIs this machine is set to watch
  jobs(env, …)                every lab job as a record (newest first)
  find(env, id)               one
  cancel(env, id)             take a queued prompt out of the queue, or interrupt a running one
  Feed(run, title)            write a feed: the house lines' methods, plus media() and end()
  Follower(where)             keeps <state>/jobs.json and a media folder, live (polls and the
                              websocket); `bromigos activity follow` runs it

ComfyUI sends a prompt's progress and preview frames only to the client that queued it. A
ComfyUI with the relay node (lib/comfyui_relay) copies them to every `bromigos-watch-*` client
too; without it a watcher sees the queue, the ends and the outputs, and progress is estimated
from how long the same workflow took before.

The feed format, one JSON object per line, appended (each line whole, under 4096 bytes):

  {"v": 1, "at": MS, "start": {"title": WORDS, "kind": "lab.pipeline", "subject": "TYPE:ID[:NAME]",
                               "pid": N, "boot_id": "…"}}
  {"at": MS, "line": "::step cutout running Cutting out ship-a"}
  {"at": MS, "media": {"path": "out/ship-a/cut.png", "step": "cutout", "role": "preview"}}
  {"at": MS, "media": {"path": "out/ship-a/ship-a.glb", "role": "output"}}
  {"at": MS, "end": {"state": "succeeded", "words": "4 ships made"}}

A relative media path is relative to the feed file's folder. The file is
<feed folder>/<run>.jsonl; the run's id is `feed-<run>`.
"""
import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import pwd
import socket
import stat
import statistics
import struct
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

SCHEMA = 1
HERE = os.path.dirname(os.path.realpath(__file__))

SYSTEM_CONFIG = "/etc/bromigos/labjobs.toml"
SYSTEM_FEED = "/var/lib/bromigos/activity/feed"
SYSTEM_STATE = "/run/bromigos-labjobs"          # the follower's (bromigos-board-lab.service): jobs.json, answers/
SYSTEM_MEDIA = "/var/cache/bromigos-labjobs"    # its media: previews, thumbnails, outputs
SYSTEM_ASKS = "/run/bromigos-labjobs-asks"      # root's: what root asks the follower to do (cancel)
LOCAL_URL = "http://127.0.0.1:8188"
WATCH_PREFIX = "bromigos-watch-"                # the relay node copies progress to these clients (with its token)
FOLLOWER_USER = "bromigos-labjobs"              # the machine's follower's user: its files are the only ones trusted

COMFY_ID = re.compile(r"comfy-([a-z0-9]{1,24})-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\Z")
FEED_ID = re.compile(r"feed-([a-z0-9][a-z0-9._-]{0,63})\Z")
RUN_OK = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
PROMPT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
MEDIA_NAME = re.compile(r"(pv|th|of|fm)-[0-9a-f]{16}\.(png|jpg|webp|gif|mp4|webm|glb)\Z")
ASK_ID = re.compile(r"[0-9a-f]{16}\Z")

HISTORY_ITEMS = 20          # ended prompts asked for, per ComfyUI
FEED_KEEP_MS = 7 * 86400_000            # a feed run that ended this long ago isn't listed
FEED_RUNS = 30              # feed runs listed at most, per folder
FEED_READ_MAX = 512 * 1024  # bytes of a feed file read (its end)
FEED_LINE_MAX = 4096
FEED_QUIET_MS = 3600_000    # a feed run that said nothing for this long reads as interrupted
MEDIA_MAX = 64 * 1024 * 1024            # bytes of one cached file
JSON_MAX = 16 * 1024 * 1024             # bytes of one ComfyUI answer read
DEADLINE_S = 15.0                       # seconds one ComfyUI answer may take, whole (not per read)
FETCH_DEADLINE_S = 60.0                 # seconds one output file may take, whole
OUTPUTS_PER_RECORD = 8                  # outputs a record lists (a batch of 4096 lists 8)
WS_MAX = 4 * 1024 * 1024                # bytes of one websocket message (a preview frame is far smaller)
IMAGE_PIXELS_MAX = 40_000_000           # pixels of a picture decoded for a thumbnail or the terminal
MEDIA_TOTAL = 512 * 1024 * 1024         # bytes of the whole media folder; the oldest go first
OUTPUTS_CACHED = 12         # ended prompts whose outputs the follower keeps, per ComfyUI
THUMB_PX = 512
TIMEOUT_S = 4.0
STATE_FRESH_MS = 15_000     # a follower's jobs.json older than this isn't used
PREVIEW_EVERY_S = 1.0       # a running prompt's preview is written at most this often
IDLE_POLL_S = 30.0          # the follower's look while nothing runs or waits (the websocket still says when one starts)

# the stages a graph's nodes fall in, in the order they run, and how much of a job each is
STAGES = (("load", "Load the models", 10), ("inputs", "Read the inputs", 2), ("prompt", "Read the prompt", 5),
          ("sample", "Sample", 70), ("decode", "Decode", 8), ("save", "Save", 5))
STAGE_INDEX = {s[0]: i for i, s in enumerate(STAGES)}

# what each capability is called, and its record's kind
CAP_KIND = {"image.generate": ("lab.image", "Image"), "image.edit": ("lab.edit", "Edit"),
            "image.cutout": ("lab.cutout", "Cut-out"), "image.upscale": ("lab.upscale", "Upscale"),
            "video.loop": ("lab.video", "Video"), "video.upscale": ("lab.video", "Video upscale"),
            "model3d.generate": ("lab.model3d", "3D")}
# the shipped workflows' names, as people write them
NAMES = {"qwen-image-2512": "Qwen-Image-2512", "qwen-image-2512-lightning": "Qwen-Image-2512 Lightning",
         "qwen-image-edit-2511": "Qwen-Image-Edit-2511", "qwen-image-edit-2511-lightning": "Qwen-Image-Edit-2511 Lightning",
         "qwen-image-2.1": "Qwen-Image 2.1", "lucida": "Lucida", "birefnet": "BiRefNet", "pixal3d": "Pixal3D",
         "hunyuan3d-2.1": "Hunyuan3D 2.1", "seedvr2-7b": "SeedVR2 7B", "seedvr2-7b-video": "SeedVR2 7B",
         "wan2.2-ti2v-5b": "Wan 2.2 TI2V 5B", "wan2.2-i2v-a14b": "Wan 2.2 I2V A14B"}
MODEL_EXT = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".sft", ".bin", ".onnx")
EXT_KIND = {"png": "image", "jpg": "image", "jpeg": "image", "webp": "image", "gif": "image", "mp4": "video",
            "webm": "video", "mov": "video", "glb": "model3d", "gltf": "model3d"}


def _activity():
    import bromigos_activity
    return bromigos_activity


def is_lab_id(text):
    return bool(isinstance(text, str) and (COMFY_ID.match(text) or FEED_ID.match(text)))


def _slug(text, n=24):
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())[:n] or "comfyui"


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")


def _cut(text, n):
    text = " ".join(_CONTROL.sub(" ", str(text or "")).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def clean(text):
    """Text that is safe to print in a terminal: every control character (an escape sequence's
    ESC, OSC 52's clipboard write, a carriage return, bidi overrides) becomes a space. Newlines
    are the caller's to put back: clean each line."""
    return _CONTROL.sub(" ", str(text if text is not None else ""))


def clean_doc(doc):
    """A record read back from a file, with every string cleaned (clean): a follower's jobs.json
    is printed by root's terminal and shown by pages."""
    if isinstance(doc, dict):
        return {clean(k): clean_doc(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [clean_doc(v) for v in doc]
    if isinstance(doc, str):
        return clean(doc)
    return doc


def owner_uid(name=FOLLOWER_USER):
    try:
        return pwd.getpwnam(name).pw_uid
    except KeyError:
        return None


def read_regular(path, cap, owners=None, dir_fd=None):
    """A file's bytes, or None: opened without following a link and without waiting on a pipe
    (O_NOFOLLOW, O_NONBLOCK), and read only when it is a regular file, of at most `cap` bytes
    (its end when longer: see tail), owned by one of `owners` when given."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or (owners is not None and st.st_uid not in owners):
            return None
        if st.st_size > cap:
            return None
        chunks, left = [], cap + 1
        while left > 0:
            b = os.read(fd, min(left, 1 << 20))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        data = b"".join(chunks)
        return None if len(data) > cap else data
    except OSError:
        return None
    finally:
        os.close(fd)


def open_regular(path, owners=None):
    """(fd, stat) of a regular file opened without following a link or waiting on a pipe, owned
    by one of `owners` when given; (None, None) otherwise. The caller closes fd."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None, None
    try:
        st = os.fstat(fd)
    except OSError:
        os.close(fd)
        return None, None
    if not stat.S_ISREG(st.st_mode) or (owners is not None and st.st_uid not in owners):
        os.close(fd)
        return None, None
    return fd, st


# ------------------------------------------------------------------ where things are

class Where:
    """The folders and settings one reader uses. `system`: the machine's own (root, and the
    board's follower): /etc/bromigos/labjobs.toml, the system feed folder and state. A person's:
    their own config, feed folder and state too, and the system's feed and state as well."""

    def __init__(self, env=None, system=None):
        A = _activity()
        self.env = env or A.Env()
        e = self.env.environ
        self.system = (os.geteuid() == 0 and not self.env.stand_in) if system is None else bool(system)
        home = e.get("HOME") or os.path.expanduser("~")
        self.config_home = e.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        self.state_home = e.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")
        self.cache_home = e.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
        self.runtime = e.get("XDG_RUNTIME_DIR") or ""

    def path(self, p):
        return self.env.path(p)

    def config_files(self):
        if self.env.environ.get("BROMIGOS_LABJOBS_CONFIG"):
            return [self.env.environ["BROMIGOS_LABJOBS_CONFIG"]]
        out = [self.path(SYSTEM_CONFIG)]
        if not self.system:
            out.append(os.path.join(self.config_home, "bromigos", "labjobs.toml"))
        return out

    def feed_dirs(self):
        """Where feeds are read from. BROMIGOS_ACTIVITY_FEED (folders, : between) replaces the
        defaults: the person's own folder (not for system), the system's, and labjobs.toml's."""
        over = self.env.environ.get("BROMIGOS_ACTIVITY_FEED")
        if over:
            return [d for d in over.split(":") if d]
        out = [] if self.system else [self.user_feed()]
        out.append(self.path(SYSTEM_FEED))
        out += config(self)["feed_dirs"]
        return list(dict.fromkeys(out))

    def user_feed(self):
        return os.path.join(self.state_home, "bromigos", "activity", "feed")

    def write_feed(self):
        """Where a new feed goes: the first BROMIGOS_ACTIVITY_FEED folder, else the system's for
        root and the person's own for anyone else."""
        over = self.env.environ.get("BROMIGOS_ACTIVITY_FEED")
        if over:
            return over.split(":")[0]
        return self.path(SYSTEM_FEED) if self.system else self.user_feed()

    def state_dir(self):
        over = self.env.environ.get("BROMIGOS_LABJOBS_STATE")
        if over:
            return over
        if self.system:
            return self.path(SYSTEM_STATE)
        return os.path.join(self.runtime or os.path.join(self.state_home, "bromigos"), "bromigos-labjobs")

    def media_dir(self):
        over = self.env.environ.get("BROMIGOS_LABJOBS_MEDIA")
        if over:
            return over
        return self.path(SYSTEM_MEDIA) if self.system else os.path.join(self.cache_home, "bromigos", "labjobs")

    def asks_dir(self):
        return self.env.environ.get("BROMIGOS_LABJOBS_ASKS") or self.path(SYSTEM_ASKS)

    def state_dirs(self):
        """The followers' state folders a reader may use, its own first."""
        out = [(self.state_dir(), self.media_dir())]
        if not self.system and not self.env.environ.get("BROMIGOS_LABJOBS_STATE"):
            out.append((self.path(SYSTEM_STATE), self.path(SYSTEM_MEDIA)))
        return out


# ------------------------------------------------------------------ settings

def resolve(value, environ=None):
    """A URL, or a reference to one, as create.toml and homelab.toml write them: `@env:NAME`,
    `@private:dotted.key` (the private overlay), `@file:~/path`, `@homelab:<source name>`.
    "" when it doesn't resolve. `@vault:` isn't followed here: a reader never asks Vault."""
    environ = os.environ if environ is None else environ
    if not isinstance(value, str):
        return ""
    v = value.strip()
    if v.startswith("@env:"):
        return (environ.get(v[5:]) or "").strip()
    if v.startswith("@private:"):
        try:
            import bromigos_private
            got = bromigos_private.get(v[9:], "")
        except Exception:
            return ""
        return resolve(got, environ) if isinstance(got, str) else ""
    if v.startswith("@file:"):
        try:
            with open(os.path.expanduser(v[6:])) as f:
                return f.read().strip()
        except OSError:
            return ""
    if v.startswith("@homelab:"):
        try:
            from bromigos_homelab import config as HC
            for s in HC.load().get("sources") or []:
                if s.get("name") == v[9:]:
                    return resolve(s.get("endpoint") or "", environ) if str(s.get("endpoint", "")).startswith("@") \
                        else str(s.get("endpoint") or "")
        except Exception:
            return ""
        return ""
    if v.startswith("@"):
        return ""
    return v


def _url_ok(url):
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.hostname) and not u.username and not u.password


def _toml(path):
    try:
        with open(path, "rb") as f:
            doc = tomllib.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def config(where):
    """{"comfyui": [{"name", "url", "from"}], "feed_dirs": [...], "media_roots": [...]}.

    The ComfyUIs: labjobs.toml's [[comfyui]] (name, url), then for a person their creation
    settings: create.toml's [comfyui.<name>] endpoints, BROMIGOS_COMFYUI_URL (as "homelab")
    and art.toml's comfyui_url. Each address once. Nothing is followed without being set:
    this machine's own ComfyUI too is named (`url = "http://127.0.0.1:8188"`), so no other
    program on the port can pose as it."""
    env = where.env.environ
    out, seen = [], set()

    def add(name, url, origin):
        url = (url or "").strip().rstrip("/")
        name = _slug(name)
        if not _url_ok(url) or url in seen or any(c["name"] == name for c in out):
            return
        seen.add(url)
        out.append({"name": name, "url": url, "from": origin})

    home = env.get("HOME") or os.path.expanduser("~")

    def expand(d):
        return os.path.join(home, d[2:]) if d.startswith("~/") else d
    feed_dirs, media_roots = [], []
    for path in where.config_files():
        doc = _toml(path)
        for c in doc.get("comfyui") or []:
            if isinstance(c, dict):
                add(c.get("name") or "comfyui", resolve(c.get("url") or c.get("endpoint") or "", env), path)
        feed = doc.get("feed") if isinstance(doc.get("feed"), dict) else {}
        feed_dirs += [expand(d) for d in feed.get("dirs") or [] if isinstance(d, str)]
        media_roots += [expand(d) for d in feed.get("media") or [] if isinstance(d, str)]
    if not where.system and not env.get("BROMIGOS_LABJOBS_CONFIG"):
        create = _toml(os.path.join(where.config_home, "bromigos", "create.toml"))
        for name, t in (create.get("comfyui") or {}).items():
            if isinstance(t, dict):
                add(name, resolve(t.get("endpoint") or "", env), "create.toml")
        add("homelab", resolve("@env:BROMIGOS_COMFYUI_URL", env), "BROMIGOS_COMFYUI_URL")
        art = _toml(os.path.join(where.config_home, "bromigos", "art.toml"))
        if isinstance(art.get("comfyui_url"), str):
            add("homelab", art["comfyui_url"], "art.toml")
    for c in out:                     # (a relay token: [[comfyui]] relay_token, a reference)
        c.setdefault("relay_token", "")
    for path in where.config_files():
        for c in _toml(path).get("comfyui") or []:
            if isinstance(c, dict) and c.get("relay_token"):
                for o in out:
                    if o["name"] == _slug(c.get("name") or "comfyui"):
                        o["relay_token"] = resolve(str(c["relay_token"]), env).strip()
    return {"comfyui": out, "feed_dirs": feed_dirs, "media_roots": media_roots}


def instances(where):
    return config(where)["comfyui"]


def allow_addresses(where, resolve_host=None):
    """The exact addresses the machine's follower may connect to: each configured ComfyUI's host,
    resolved now (systemd's IPAddressAllow takes addresses, not names). Nothing else: no other
    private range, no link-local, and this machine only when an instance names it."""
    resolve_host = resolve_host or (lambda host: {a[4][0] for a in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    out = set()
    for inst in instances(where):
        host = urllib.parse.urlsplit(inst["url"]).hostname
        if not host:
            continue
        try:
            out |= {a.split("%")[0] for a in resolve_host(host)}
        except (OSError, UnicodeError):
            continue
    return sorted(out)


def allow_dropin(where, resolve_host=None):
    """The systemd drop-in for the machine's follower's unit: IPAddressAllow= emptied, then only
    allow_addresses (none: it may connect nowhere)."""
    addrs = allow_addresses(where, resolve_host)
    lines = ["# Written by bromigos activity follow --allow-dropin from /etc/bromigos/labjobs.toml's",
             "# ComfyUIs (docs/board.md, \"The lab's jobs\"): the follower connects to these addresses only.",
             "[Service]", "IPAddressAllow="]
    if addrs:
        lines.append("IPAddressAllow=" + " ".join(addrs))
    return "\n".join(lines) + "\n"


def write_allow_dropin(where, path, resolve_host=None):
    """Write the drop-in at `path` when it changed; whether it did."""
    text = allow_dropin(where, resolve_host)
    try:
        with open(path) as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    tmp = f"{path}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def reachable(url, timeout=0.6):
    """Whether anything listens at the URL's host and port: a ComfyUI that isn't running is
    passed over at once, without an HTTP timeout."""
    u = urllib.parse.urlsplit(url)
    try:
        with socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 80)), timeout):
            return True
    except OSError:
        return False


# ------------------------------------------------------------------ talking to a ComfyUI

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A ComfyUI that answers with a redirect gets no second request: it might point anywhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# no proxy from the environment, and no redirect followed
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


class Http:
    """GET and POST JSON, and GET bytes, from one ComfyUI (urllib). Each answer has a whole
    deadline, not one per read, and a size cap; a redirect is an error. Tests pass their own."""

    def __init__(self, url, timeout=TIMEOUT_S, deadline=DEADLINE_S):
        self.url, self.timeout, self.deadline = url.rstrip("/"), timeout, deadline

    def _open(self, path, body=None):
        req = urllib.request.Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"} if body is not None else {},
                                     method="POST" if body is not None else "GET")
        return _OPENER.open(req, timeout=self.timeout)

    def _read(self, r, cap, deadline):
        """At most cap + 1 bytes, by `deadline` seconds from now: a server that sends a byte a
        second is cut off, whatever each read's own timeout."""
        end = time.monotonic() + deadline
        chunks, n = [], 0
        while n <= cap:
            if time.monotonic() > end:
                raise TimeoutError("the answer took too long")
            b = r.read(min(64 * 1024, cap + 1 - n))
            if not b:
                break
            chunks.append(b)
            n += len(b)
        return b"".join(chunks)

    def get(self, path):
        with self._open(path) as r:
            data = self._read(r, JSON_MAX, self.deadline)
        if len(data) > JSON_MAX:
            raise ValueError("the answer is too big")
        return json.loads(data)

    def post(self, path, body):
        with self._open(path, body) as r:
            data = self._read(r, 1024 * 1024, self.deadline)
        try:
            return json.loads(data) if data else {}
        except ValueError:
            return {}

    def fetch(self, path, cap=MEDIA_MAX):
        with self._open(path) as r:
            data = self._read(r, cap, FETCH_DEADLINE_S)
        return None if len(data) > cap else data


def _why(e):
    """A failure in plain words, without the address."""
    if isinstance(e, urllib.error.HTTPError):
        return f"it answered HTTP {e.code}"
    if isinstance(e, (TimeoutError, socket.timeout)):
        return "it didn't answer in time"
    if isinstance(e, ValueError):
        return "its answer wasn't JSON"
    return "it isn't answering"


# ------------------------------------------------------------------ recognising a workflow

def workflow_dirs(where):
    e = where.env.environ
    out = [os.path.join(where.config_home, "bromigos", "create", "workflows")]
    if e.get("BROMIGOS_SHARE_DIR"):
        out.append(os.path.join(e["BROMIGOS_SHARE_DIR"], "art", "workflows"))
    out += ["/usr/share/bromigos/art/workflows", os.path.join(HERE, "..", "core", "crates", "bromigos-art", "workflows")]
    return out


_wf_cache = {}


def workflows(where):
    """The workflows bromigos art knows (the shipped ones and the person's own), by what each
    needs: [{id, caps, output, files, classes, seconds}]. A person's own wins by name."""
    key = tuple(workflow_dirs(where))
    if key in _wf_cache:
        return _wf_cache[key]
    found = {}
    for d in key:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if not n.endswith(".json") or n[:-5] in found:
                continue
            try:
                with open(os.path.join(d, n)) as f:
                    doc = json.load(f)
            except (OSError, ValueError):
                continue
            meta = doc.get("_meta") if isinstance(doc.get("_meta"), dict) else {}
            graph = {k: v for k, v in doc.items() if isinstance(v, dict) and "class_type" in v}
            files = {os.path.basename(str(r.get("file") or "")).lower() for r in meta.get("requires") or [] if isinstance(r, dict)}
            found[n[:-5]] = {"id": n[:-5], "caps": [c for c in meta.get("capabilities") or [] if isinstance(c, str)],
                             "output": meta.get("output"), "files": {f for f in files if f},
                             "classes": {v["class_type"] for v in graph.values()},
                             "seconds": meta.get("seconds") if isinstance(meta.get("seconds"), (int, float)) else None}
    _wf_cache[key] = list(found.values())
    return _wf_cache[key]


def _files_in(graph):
    out = set()
    for node in graph.values():
        for v in (node.get("inputs") or {}).values():
            if isinstance(v, str) and v.lower().endswith(MODEL_EXT):
                out.add(os.path.basename(v).lower())
    return out


def recognise(graph, wfs):
    """The workflow this graph was made from, or None: the one whose model files it loads, the
    most of them, then the closest set of nodes (a Lightning LoRA tells the two apart)."""
    files, classes = _files_in(graph), {n.get("class_type") for n in graph.values()}
    best, score = None, (0, 0.0)
    for w in wfs:
        hit = len(files & w["files"])
        if not hit:
            continue
        near = len(classes & w["classes"]) / max(1, len(classes | w["classes"]))
        if (hit, near) > score:
            best, score = w, (hit, near)
    return best


def _output_kind(graph):
    for n in graph.values():
        c = str(n.get("class_type") or "").lower()
        if "glb" in c or "save3d" in c or "mesh" in c and c.startswith("save"):
            return "model3d"
        if c.startswith("save") and ("video" in c or "webm" in c or "animated" in c) or "videocombine" in c:
            return "video"
    return "image"


def describe(graph):
    """(kind, label, workflow name, prompt words, workflow) for a graph, without its workflow
    list: see describe_with."""
    return describe_with(graph, [])


def describe_with(graph, wfs):
    w = recognise(graph, wfs)
    has_input = any(str(n.get("class_type")) in ("LoadImage", "LoadVideo") for n in graph.values())
    if w and w["caps"]:
        cap = "image.edit" if "image.edit" in w["caps"] and has_input and "image.generate" in w["caps"] else w["caps"][0]
        kind, label = CAP_KIND.get(cap, ("lab.comfyui", "ComfyUI"))
        name = NAMES.get(w["id"]) or w["id"]
    else:
        out = _output_kind(graph)
        kind, label = {"model3d": ("lab.model3d", "3D"), "video": ("lab.video", "Video")}.get(out, ("lab.image", "Image"))
        model = next((os.path.splitext(f)[0] for f in sorted(_files_in(graph))), None)
        name = model or "ComfyUI"
    return kind, label, name, prompt_words(graph), w


def prompt_words(graph):
    """What the job is of, in a few words: the sampler's positive prompt, else the first prompt
    text, else the input file's name."""
    texts = {}
    for nid, n in graph.items():
        ins = n.get("inputs") or {}
        for k in ("text", "prompt", "positive"):
            if isinstance(ins.get(k), str) and ins[k].strip():
                texts[nid] = ins[k]
                break
    for n in graph.values():
        pos = (n.get("inputs") or {}).get("positive")
        if isinstance(pos, list) and pos and str(pos[0]) in texts:
            return texts[str(pos[0])]
    if texts:
        return texts[sorted(texts, key=lambda k: (len(k), k))[0]]
    for n in graph.values():
        if n.get("class_type") in ("LoadImage", "LoadVideo"):
            v = (n.get("inputs") or {}).get("image") or (n.get("inputs") or {}).get("file") or (n.get("inputs") or {}).get("video")
            if isinstance(v, str):
                return os.path.basename(v)
    return ""


def stage_of(class_type):
    """The stage a node's class belongs to (STAGES), or None for glue that belongs to none."""
    c = str(class_type or "").lower()
    if c.startswith(("save", "preview")) or "export" in c or "videocombine" in c:
        return "save"
    if c in ("loadimage", "loadvideo", "loadimagemask", "loadaudio") or (
            c.startswith("load") and ("image" in c or "video" in c) and "model" not in c):
        return "inputs"
    if "loader" in c or (c.startswith("load") and "model" in c):
        return "load"
    if "sampler" in c or c.endswith("stage") or "temporalchunk" in c:
        return "sample"
    if "decode" in c or "mesh" in c or "createvideo" in c or "postprocess" in c or "temporalmerge" in c:
        return "decode"
    if "encode" in c or "conditioning" in c:
        return "prompt"
    return None


def stages(graph):
    """{node id: stage id} and the stages present, in order."""
    by = {nid: stage_of(n.get("class_type")) for nid, n in graph.items()}
    present = [s for s in STAGES if s[0] in by.values()]
    return {k: v for k, v in by.items() if v}, present


# ------------------------------------------------------------------ a prompt as a record

def _client(extra):
    cid = str((extra or {}).get("client_id") or "")
    if not cid or cid.startswith(WATCH_PREFIX):
        return None
    return _cut(re.sub(r"[-_][0-9a-f]{6,}$", "", cid), 40) or None


def _messages(history):
    out = {}
    for m in ((history or {}).get("status") or {}).get("messages") or []:
        if isinstance(m, list) and len(m) == 2 and isinstance(m[1], dict):
            out.setdefault(m[0], m[1])
    return out


def outputs_of(history):
    """[{kind, name, filename, subfolder, type, width, height}] of what a prompt wrote (type
    output; a temp preview only when nothing else was written)."""
    found, temp = [], []
    for node in ((history or {}).get("outputs") or {}).values():
        if not isinstance(node, dict):
            continue
        for items in node.values():
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict) or not isinstance(it.get("filename"), str):
                    continue
                ext = it["filename"].rsplit(".", 1)[-1].lower()
                meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
                o = {"kind": EXT_KIND.get(ext, "file"), "name": _cut(os.path.basename(it["filename"]), 120),
                     "filename": _cut(it["filename"], 255), "subfolder": _cut(it.get("subfolder") or "", 255),
                     "type": "temp" if it.get("type") == "temp" else "output",
                     "width": meta.get("width"), "height": meta.get("height"), "media": None, "thumb": None}
                (found if o["type"] == "output" else temp).append(o)
    return (found or temp)[:OUTPUTS_PER_RECORD]


def estimate_ms(wf, durations):
    """How long a job of this workflow takes: the median of its last runs here, else what the
    workflow says it measured."""
    if durations:
        return int(statistics.median(durations[-8:]))
    if wf and wf.get("seconds"):
        return int(wf["seconds"] * 1000)
    return None


def comfy_record(inst, p, now, wfs, live=None, durations=None):
    """One prompt as an activity record. `p`: {prompt_id, number, graph, extra, state
    (queued|running|ended), history, position, ahead}. `live`: what the websocket said of it
    (node, progress, done nodes, preview media) or None."""
    A = _activity()
    graph = p.get("graph") or {}
    extra = p.get("extra") or {}
    kind, label, name, words, wf = describe_with(graph, wfs)
    nodes, present = stages(graph)
    msgs = _messages(p.get("history"))
    created = extra.get("create_time") if isinstance(extra.get("create_time"), int) else None
    ran = (msgs.get("execution_start") or {}).get("timestamp")
    ended_at = next((msgs[k].get("timestamp") for k in ("execution_success", "execution_error", "execution_interrupted")
                     if k in msgs), None)
    state = p.get("state")
    if state == "ended":
        state = "cancelled" if "execution_interrupted" in msgs else "failed" if (
            "execution_error" in msgs or ((p.get("history") or {}).get("status") or {}).get("status_str") == "error") else "succeeded"
    elif state not in ("queued", "running"):
        state = "queued"
    live = live or {}
    if state == "running" and not ran:
        # ComfyUI runs one prompt at a time: without the websocket's word, this one began when
        # the one before it ended (or when it was queued, if that was later)
        ran = live.get("started") or (max(x for x in (created, p.get("after")) if x) if (created or p.get("after")) else None)
    started = created or ran or now
    durations = durations or []
    est = estimate_ms(wf, durations.get(wf["id"]) if isinstance(durations, dict) and wf else durations)
    steps, at, pct, stage, estimated = [], None, None, None, False
    weights = sum(w for _, _, w in present) or 1
    seen = live.get("stage_max")
    done_nodes = set(live.get("done") or ()) | set(live.get("cached") or ())
    for i, (sid, slabel, weight) in enumerate(present):
        st = "todo"
        if state == "succeeded":
            st = "done"
        elif state in ("failed", "cancelled"):
            st = "skipped"
        elif state == "running" and seen is not None:
            k = STAGE_INDEX[sid]
            st = "done" if k < seen else "running" if k == seen else "todo"
        step = {"id": sid, "label": slabel, "state": st, "started_at": None, "ended_at": None, "detail": None, "progress": None}
        if st == "running":
            at = i
            prog = live.get("progress") or {}
            if prog.get("max") and nodes.get(str(prog.get("node"))) == sid:
                step["progress"] = {"done": float(prog.get("value") or 0), "total": float(prog["max"]), "unit": "steps"}
                step["detail"] = f"{int(prog.get('value') or 0)} of {int(prog['max'])} steps"
        steps.append(step)
    if state in ("failed", "cancelled") and live.get("node") and nodes.get(str(live["node"])):
        for s in steps:
            if s["id"] == nodes[str(live["node"])]:
                s["state"] = "failed" if state == "failed" else "skipped"
    if state == "running":
        if at is not None:
            done_w = sum(w for (sid, _, w) in present[:at])
            here = present[at][2]
            s = steps[at]
            frac = (s["progress"]["done"] / s["progress"]["total"]) if s["progress"] else 0.0
            sampler_nodes = [n for n, sid in nodes.items() if sid == present[at][0]]
            if len(sampler_nodes) > 1:
                frac = (len([n for n in sampler_nodes if n in done_nodes]) + frac) / len(sampler_nodes)
            pct = int(min(99, (done_w + here * min(1.0, frac)) * 100 / weights))
            stage = s["label"] + (f" · {s['detail']}" if s["detail"] else "")
        elif est and ran:
            pct, estimated = int(min(95, (now - ran) * 100 / est)), True
            stage = "Running"
        else:
            stage = "Running"
    elif state == "queued":
        ahead = p.get("ahead")
        stage = "Next in the queue" if not ahead else f"In the queue: {ahead} ahead"
    title = f"{label}: {name}" + (f" · {_cut(words, 60)}" if words else "")
    err, result = None, None
    outs = outputs_of(p.get("history"))
    if state == "failed":
        e = msgs.get("execution_error") or {}
        why = _cut(A.redact(str(e.get("exception_message") or "").strip()), 300) or "ComfyUI stopped the job with an error."
        node_step = nodes.get(str(e.get("node_id"))) if e.get("node_id") is not None else None
        err = {"step": node_step, "words": why, "code": "comfyui",
               "fix": f"It failed in {_cut(e['node_type'], 80)}." if e.get("node_type") else None}
        result = {"ok": False, "undo": None, "summary": "It didn't finish.", "outputs": outs}
    elif state == "cancelled":
        result = {"ok": False, "undo": None, "summary": "Interrupted before it finished.", "outputs": outs}
    elif state == "succeeded":
        n = len(outs)
        what = {"image": "image", "video": "video", "model3d": "3D model"}.get(outs[0]["kind"], "file") if outs else "file"
        result = {"ok": True, "undo": None, "outputs": outs,
                  "summary": f"{n} {what}{'s' if n != 1 else ''} made" if n else "Finished, with nothing saved."}
    rec = {
        "schema": A.SCHEMA, "id": f"comfy-{inst['name']}-{p['prompt_id']}", "kind": kind, "title": _cut(title, A.MAX_TITLE),
        "subject": {"type": "comfyui", "id": inst["name"], "name": inst["name"]},
        "state": state, "waiting_for": None, "question": None, "steps": steps, "step": at, "pct": pct,
        "stage": stage, "notes": [], "started_at": started,
        # what changes it: a running prompt moves on every look; a queued one when it moves up
        "updated_at": ended_at or (now if state == "running" else (created or started) + (p.get("position") or 0)),
        "ended_at": ended_at if state in A.FINAL else None,
        "requested_by": {"via": "lab", "device": _client(extra)}, "unit": None, "locks": [], "can": [],
        "cancel_safe": state in ("queued", "running"),
        "cancel_note": None, "result": result, "error": err, "exit_code": None, "command": [], "log": None,
        "parent": None, "children": [], "boot_id": None,
        "lab": {"source": "comfyui", "instance": inst["name"], "prompt_id": p["prompt_id"], "number": p.get("number"),
                "workflow": _cut(name, 120), "workflow_id": wf["id"] if wf else None, "label": label, "prompt": _cut(words, 300),
                "client": _client(extra), "position": p.get("position"), "ahead": p.get("ahead"),
                "queued_at": created, "ran_at": ran if state != "queued" else None,
                "elapsed_ms": ((ended_at or now) - ran) if ran and state != "queued" else None,
                "estimate_ms": est, "estimated": estimated, "live": bool(live.get("seen")),
                "preview": live.get("preview"), "media": [],
                "interrupt": state == "running"},
    }
    if state == "running":
        rec["cancel_note"] = None
    rec["can"] = ["cancel"] if rec["cancel_safe"] else []
    return rec


def _entries(queue, history):
    """The prompts of one ComfyUI, from its /queue and /history: running first, then the queue
    in its order, then the ended, newest first."""
    out, seen = [], set()

    def item(row, state, position=None, ahead=None, hist=None):
        if not isinstance(row, list) or len(row) < 3 or not isinstance(row[1], str) or not PROMPT_ID.match(row[1]):
            return None
        return {"number": row[0], "prompt_id": row[1], "graph": row[2] if isinstance(row[2], dict) else {},
                "extra": row[3] if len(row) > 3 and isinstance(row[3], dict) else {}, "state": state,
                "position": position, "ahead": ahead, "history": hist}

    running = [r for r in (queue or {}).get("queue_running") or []]
    pending = sorted((queue or {}).get("queue_pending") or [], key=lambda r: r[0] if isinstance(r, list) and r and isinstance(r[0], (int, float)) else 0)
    for r in running:
        e = item(r, "running", 0, 0)
        if e and e["prompt_id"] not in seen:
            seen.add(e["prompt_id"])
            out.append(e)
    for i, r in enumerate(pending):
        e = item(r, "queued", i + 1, i + len(running))
        if e and e["prompt_id"] not in seen:
            seen.add(e["prompt_id"])
            out.append(e)
    ended = []
    for pid, h in (history or {}).items():
        if pid in seen or not isinstance(h, dict) or not isinstance(h.get("prompt"), list):
            continue
        e = item(h["prompt"], "ended", hist=h)
        if e:
            ended.append(e)
    ended.sort(key=lambda e: (-(_messages(e["history"]).get("execution_start") or {}).get("timestamp", 0), e["prompt_id"]))
    last_end = max((m.get("timestamp") or 0 for e in ended for k, m in _messages(e["history"]).items()
                    if k in ("execution_success", "execution_error", "execution_interrupted")), default=0)
    for e in out:
        if e["state"] == "running" and last_end:
            e["after"] = last_end
    return out + ended


def durations_of(history, wfs):
    """How long each workflow's successful runs took here, oldest first: {workflow id: [ms]}."""
    out = {}
    rows = []
    for h in (history or {}).values():
        if not isinstance(h, dict) or not isinstance(h.get("prompt"), list) or len(h["prompt"]) < 3:
            continue
        m = _messages(h)
        a, b = (m.get("execution_start") or {}).get("timestamp"), (m.get("execution_success") or {}).get("timestamp")
        if a and b and b > a and m.get("execution_cached", {}).get("nodes") is not None:
            w = recognise(h["prompt"][2] if isinstance(h["prompt"][2], dict) else {}, wfs)
            if w:
                rows.append((a, w["id"], b - a))
    for _, wid, ms in sorted(rows):
        out.setdefault(wid, []).append(ms)
    return out


def comfy_records(inst, queue, history, now, wfs, live=None):
    """Every prompt one ComfyUI knows, as records."""
    durations = durations_of(history, wfs)
    live = live or {}
    return [comfy_record(inst, e, now, wfs, live.get(e["prompt_id"]), durations) for e in _entries(queue, history)]


def poll(inst, http=None, now=None, wfs=(), live=None):
    """(records, None) or ([], why) for one ComfyUI, read now (GET /queue and /history)."""
    http = http or Http(inst["url"])
    try:
        queue = http.get("/queue")
        history = http.get(f"/history?max_items={HISTORY_ITEMS}")
    except Exception as e:      # down, refused, not JSON: said in words, never a crash
        return [], _why(e)
    if not isinstance(queue, dict) or not isinstance(history, dict):
        return [], "its answer wasn't ComfyUI's"
    return comfy_records(inst, queue, history, now or int(time.time() * 1000), list(wfs), live), None


# ------------------------------------------------------------------ job feeds

class _MemoryEnv:
    """bromigos_activity.Env's clock, set by each feed line."""

    def __init__(self, env):
        self.inner, self.now = env, env.now_ms()

    def now_ms(self):
        return self.now

    def boot_id(self):
        return self.inner.boot_id()

    def file(self, job_id, ext):
        return None


def _job_in_memory(env, job_id, kind, title, subject, started):
    """A bromigos_activity.Job that never touches a file: a feed's lines go through the same
    record a job run under `bromigos activity run` keeps."""
    A = _activity()
    clock = _MemoryEnv(env)
    clock.now = started
    j = A.Job.__new__(A.Job)
    j.env, j.id, j.path = clock, job_id, None
    j.rec = A.new_record(clock, job_id, kind if A.KIND_OK.match(kind or "") else "lab.pipeline", title, subject)
    j.rec["log"], j.rec["requested_by"] = None, {"via": "lab", "device": None}
    j.errors, j.sticky, j.offline, j.last_line = [], set(), set(), ""
    j._wrote, j._dirty, j._lock, j.retry, j._cancel_safe = 0.0, False, None, None, False
    j._held, j._answers, j._kids_read, j._told = [], None, 0, None

    def save(force=True):
        j.rec["updated_at"] = clock.now
        j.rec["can"] = []
    j.save, j.adopt, j.close = save, (lambda: False), (lambda: None)
    return j, clock


def feed_owners(path):
    """Whose feed files are read in this file's folder: root's, and the folder owner's (a
    person's own folder, or one labjobs.toml names). Anyone else's file there is passed over."""
    try:
        return {0, os.stat(os.path.dirname(path) or ".").st_uid}
    except OSError:
        return {0}


def _read_feed_lines(path):
    """A feed file's lines: its first (the start) and its last FEED_READ_MAX bytes. A link, a
    pipe, or a file that isn't root's or its folder owner's is no feed (read_regular's rules)."""
    fd, st = open_regular(path, feed_owners(path))
    if fd is None:
        return []
    try:
        with os.fdopen(fd, "rb") as f:
            if st.st_size > FEED_READ_MAX:
                head = f.readline(FEED_LINE_MAX + 1)
                f.seek(st.st_size - FEED_READ_MAX)
                f.readline()                    # the first, cut line goes
                data = head + f.read(FEED_READ_MAX)
            else:
                data = f.read(FEED_READ_MAX)
    except OSError:
        return []
    out = []
    for raw in data.splitlines():
        if len(raw) > FEED_LINE_MAX:
            continue
        try:
            doc = json.loads(raw)
        except ValueError:
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def _alive(pid, boot, env):
    if not isinstance(pid, int) or pid <= 0 or (boot and boot != env.boot_id()):
        return None if not boot else False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def feed_record(env, path, now=None):
    """A feed file as a record, or None. The lines are replayed in order through the record's
    own rules; a run whose writer is gone, or that said nothing for an hour, reads as
    interrupted."""
    A = _activity()
    run = os.path.basename(path)[:-6] if path.endswith(".jsonl") else ""
    if not RUN_OK.match(run):
        return None
    lines = _read_feed_lines(path)
    if not lines:
        return None
    first = lines[0].get("start") if isinstance(lines[0].get("start"), dict) else {}
    at0 = lines[0].get("at") if isinstance(lines[0].get("at"), int) else int(os.path.getmtime(path) * 1000)
    subject = None
    if isinstance(first.get("subject"), str):
        with contextlib.suppress(A.ActivityError):
            subject = A.parse_subject(first["subject"])
    title = _cut(first.get("title") or run, A.MAX_TITLE) or run
    j, clock = _job_in_memory(env, f"feed-{run}", str(first.get("kind") or "lab.pipeline"), title, subject, at0)
    j.set_state("running")
    media, last, ended = [], at0, None
    folder = os.path.dirname(path)
    for doc in lines:
        at = doc.get("at") if isinstance(doc.get("at"), int) and not isinstance(doc.get("at"), bool) else last
        clock.now = last = max(last, at)
        if isinstance(doc.get("line"), str):
            j.feed(_cut(A.redact(doc["line"]), FEED_LINE_MAX))
        elif isinstance(doc.get("media"), dict):
            m = doc["media"]
            p = m.get("path")
            if isinstance(p, str) and p:
                full = p if os.path.isabs(p) else os.path.normpath(os.path.join(folder, p))
                ext = full.rsplit(".", 1)[-1].lower()
                media.append({"path": full, "name": _cut(os.path.basename(full), 120), "kind": EXT_KIND.get(ext, "file"),
                              "step": _cut(m.get("step"), A.MAX_ID) if isinstance(m.get("step"), str) else (j.current or None),
                              "role": "output" if m.get("role") == "output" else "preview", "at": at,
                              "media": None, "thumb": None})
        elif isinstance(doc.get("end"), dict) and ended is None:
            ended = doc["end"]
            st = ended.get("state") if ended.get("state") in ("succeeded", "failed", "cancelled") else "succeeded"
            j.finish(0 if st == "succeeded" else 1, cancelled=st == "cancelled", words=_cut(A.redact(str(ended.get("words") or "")), A.MAX_WORDS) or None)
    rec = j.rec
    now = now or env.now_ms()
    if rec["state"] not in A.FINAL:
        gone = _alive(first.get("pid"), first.get("boot_id"), env) is False
        quiet = now - last > (first.get("quiet_ms") if isinstance(first.get("quiet_ms"), int) else FEED_QUIET_MS)
        if gone or quiet:
            clock.now = last
            j.finish(None, state="failed", words=None)
            rec["state"] = "interrupted"
            rec["error"] = {"step": rec["error"]["step"] if rec.get("error") else None, "code": "interrupted", "fix": None,
                            "words": "The program writing it stopped without a last word." if gone else
                                     "It hasn't said anything for a long time: the program writing it may have stopped."}
            rec["result"] = {"ok": False, "summary": "It didn't finish.", "undo": None}
    rec["updated_at"] = last
    outputs = [m for m in media if m["role"] == "output"]
    previews = [m for m in media if m["role"] == "preview"]
    rec.setdefault("result", None)
    if rec["result"] is not None:
        rec["result"]["outputs"] = outputs
    rec["can"], rec["cancel_safe"] = [], False
    rec["cancel_note"] = rec["cancel_note"] or (None if rec["state"] in A.FINAL else
                                                "A pipeline run is stopped by the program that runs it.")
    rec["lab"] = {"source": "feed", "run": run, "file": path, "media": media[-24:],
                  "preview": previews[-1] if previews else None, "outputs": outputs[-24:],
                  "elapsed_ms": (rec["ended_at"] or now) - rec["started_at"], "estimate_ms": None, "estimated": False,
                  "live": False, "position": None, "ahead": None, "client": None, "workflow": None, "label": "Pipeline",
                  "interrupt": False}
    return rec


def feed_files(where):
    out = []
    for d in where.feed_dirs():
        try:
            names = os.listdir(d)
        except OSError:
            continue
        files = []
        for n in names:
            if n.endswith(".jsonl") and RUN_OK.match(n[:-6]):
                p = os.path.join(d, n)
                with contextlib.suppress(OSError):
                    st = os.lstat(p)
                    if stat.S_ISREG(st.st_mode):        # a link or a pipe in its place is no feed
                        files.append((st.st_mtime, p))
        out += [p for _, p in sorted(files, reverse=True)[:FEED_RUNS]]
    return out


def feed_records(where, now=None):
    now = now or where.env.now_ms()
    out, seen = [], set()
    for p in feed_files(where):
        rec = feed_record(where.env, p, now)
        if not rec or rec["id"] in seen:
            continue
        if rec["ended_at"] and now - rec["ended_at"] > FEED_KEEP_MS:
            continue
        seen.add(rec["id"])
        out.append(rec)
    return out


class Feed:
    """Write a job feed (the format at the top): what a multi-step tool is doing, for every face
    that shows jobs. The house lines' methods (bromigos_activity.Lines: step, stage, note,
    error) plus media() and output() for thumbnails and results, and end().

        from bromigos_labjobs import Feed
        with Feed("ships-20261112", "Universe assets: ships") as feed:
            feed.step("cutout", "Cut out ship-a")
            feed.media("out/ship-a/cut.png")           # a thumbnail of this step
            feed.output("out/ship-a/ship-a.glb")       # a result

    Leaving the `with` ends the run: succeeded, or failed with the exception's words. A line
    that can't be written is dropped: a feed never stops the tool that writes it."""

    def __init__(self, run, title, kind="lab.pipeline", subject=None, folder=None, env=None, resume=False, pid=-1):
        A = _activity()
        run = str(run).lower()
        if not RUN_OK.match(run):
            raise A.ActivityError(f"a feed's run is short lower-case words, digits, dots and dashes (ships-20261112), not {run!r}")
        if not A.KIND_OK.match(kind or "") or not str(kind).startswith("lab."):
            raise A.ActivityError(f"a feed's kind starts with lab. (lab.pipeline), not {kind!r}")
        self.env = env or A.Env()
        self.folder = folder or Where(self.env).write_feed()
        self.path = os.path.join(self.folder, run + ".jsonl")
        self.run, self.current, self.ended = run, None, False
        os.makedirs(self.folder, mode=0o755, exist_ok=True)
        if not resume or not os.path.exists(self.path):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.path)
            # pid: the process doing the work (this one by default); when it's gone the run reads
            # as interrupted. None leaves it out (`bromigos activity emit`, a short-lived process)
            pid = os.getpid() if pid == -1 else pid
            start = {"title": _cut(title, A.MAX_TITLE), "kind": kind}
            if isinstance(pid, int) and pid > 0:
                start.update(pid=pid, boot_id=self.env.boot_id())
            if subject:
                start["subject"] = subject
            self._write({"v": SCHEMA, "start": start})

    def _write(self, doc):
        doc = dict(doc, at=self.env.now_ms())
        data = (json.dumps(doc, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        if len(data) > FEED_LINE_MAX:
            return False
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o644)
        except OSError:
            return False
        try:
            os.write(fd, data)              # one write under 4096 bytes: whole, never interleaved
            return True
        except OSError:
            return False
        finally:
            os.close(fd)

    def _emit(self, line):
        self._write({"line": line})

    def line(self, line):
        """A house progress line as it is (::step, ::stage, ::item, ::note, ::error)."""
        A = _activity()
        if A.parse(line) is None:
            raise A.ActivityError(f"not a progress line: {line!r} (::step ID STATE WORDS, ::stage PCT WORDS, …)")
        self._emit(line)

    def stage(self, pct, words):
        self._emit(_activity().line_stage(pct, words))

    def step(self, step_id, words="", state="running"):
        A = _activity()
        if state == "running" and self.current and self.current != step_id:
            self._emit(A.line_step(self.current, "done"))
        self.current = step_id if state == "running" else (None if self.current == step_id else self.current)
        self._emit(A.line_step(step_id, state, words))

    def note(self, words, step_id=None):
        self._emit(_activity().line_note(step_id, words))

    def error(self, words, step_id=None):
        self._emit(_activity().line_error(step_id, words))

    def media(self, path, step=None, output=False):
        """A picture, clip or model of this step (a thumbnail), or with output=True a result."""
        self._write({"media": {"path": os.path.abspath(str(path)), "step": step or self.current,
                               "role": "output" if output else "preview"}})

    def output(self, path, step=None):
        self.media(path, step, output=True)

    def end(self, state="succeeded", words=""):
        if self.ended:
            return
        if self.current and state == "succeeded":
            self.step(self.current, state="done")
        self.ended = True
        self._write({"end": {"state": state, "words": _cut(words, 600)}})

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, tb):
        if kind is None:
            self.end("succeeded")
        else:
            self.end("cancelled" if issubclass(kind, KeyboardInterrupt) else "failed",
                     "" if issubclass(kind, KeyboardInterrupt) else str(exc) or kind.__name__)
        return False


# ------------------------------------------------------------------ reading everything

def read_state(where):
    """(jobs.json, media folder) of the freshest follower this reader may use, or (None, None)."""
    now = where.env.now_ms()
    for state, media in where.state_dirs():
        doc = None
        data = read_regular(os.path.join(state, "jobs.json"), JSON_MAX * 2, state_owners(where, state))
        with contextlib.suppress(ValueError, TypeError):
            doc = json.loads(data) if data else None
        if isinstance(doc, dict) and isinstance(doc.get("at"), int) and 0 <= now - doc["at"] <= STATE_FRESH_MS \
                and isinstance(doc.get("jobs"), list):
            return clean_doc(doc), media
    return None, None


def state_owners(where, state):
    """Whose jobs.json a reader trusts: the machine's follower's (or root's) in the machine's
    folder; this person's own in theirs. None in a stand-in root (the tests' own files)."""
    if where.env.stand_in or where.env.environ.get("BROMIGOS_LABJOBS_STATE"):
        return None
    if state == where.path(SYSTEM_STATE):
        uid = owner_uid()
        return {0} | ({uid} if uid is not None else set())
    return {os.getuid()}


def jobs(env=None, where=None, live=True, feeds=True, comfy=True, http=None, files=True):
    """Every lab job as a record, newest first. From a follower's fresh jobs.json when there is
    one; else, with `live`, read now from each ComfyUI. Feed runs from their files too, unless
    `files` is False. The board's API passes live=False and files=False: it has no network, and
    a feed's own paths aren't for a browser."""
    where = where or Where(env)
    now = where.env.now_ms()
    out, have = [], set()
    doc, _ = read_state(where)
    if doc is not None:
        for j in doc["jobs"]:
            if isinstance(j, dict) and isinstance(j.get("id"), str) and (
                    comfy and COMFY_ID.match(j["id"]) or feeds and FEED_ID.match(j["id"])):
                out.append(j)
                have.add(j["id"])
    elif comfy and live:
        out += read_now(where, now, http)[0]
    if feeds and files:
        out += [r for r in feed_records(where, now) if r["id"] not in have]
    return sorted(out, key=_order)


def read_now(where, now=None, http=None):
    """([records], [instance notes]) read straight from each ComfyUI, without a follower."""
    now = now or where.env.now_ms()
    wfs = workflows(where)
    recs, notes = [], []
    for inst in instances(where):
        if http is None and not reachable(inst["url"]):
            if not inst.get("quiet"):
                notes.append({"name": inst["name"], "state": "down", "words": "it isn't answering", "live": False})
            continue
        got, why = poll(inst, (http or {}).get(inst["name"]) if isinstance(http, dict) else None, now, wfs)
        recs += got
        notes.append({"name": inst["name"], "state": "down" if why else "ok", "words": why or "", "live": False})
    return recs, notes


def _order(r):
    A = _activity()
    return (r["state"] in A.FINAL, r["state"] != "running", -(r.get("ended_at") or r.get("started_at") or 0), r["id"])


def find(env, text, where=None, http=None):
    """A lab job by its whole id, or by a part only one has. KeyError otherwise. A ComfyUI
    prompt's id reads no feed file, and a feed's no ComfyUI."""
    all_jobs = jobs(env, where, http=http, feeds=not COMFY_ID.match(text or ""), comfy=not FEED_ID.match(text or ""))
    hits = [j for j in all_jobs if j["id"] == text] or [j for j in all_jobs if text and text in j["id"]]
    if len(hits) != 1:
        raise KeyError(f"no job {text!r}" if not hits else f"{text!r} matches {len(hits)} jobs: " + ", ".join(h["id"] for h in hits[:5]))
    return hits[0]


# ------------------------------------------------------------------ stopping a prompt

def _outcome(rec, refused=None, words=""):
    return {"ok": refused is None, "refused": refused, "words": words, "job": rec}


def stop_prompt(http, prompt_id):
    """Take a queued prompt out of the queue, or interrupt it while it runs: (refused, words).
    Only this prompt: the queue is read first, and /interrupt names it."""
    q = http.get("/queue")
    pending = {r[1] for r in q.get("queue_pending") or [] if isinstance(r, list) and len(r) > 1}
    running = {r[1] for r in q.get("queue_running") or [] if isinstance(r, list) and len(r) > 1}
    if prompt_id in pending:
        http.post("/queue", {"delete": [prompt_id]})
        return None, "Taken out of the queue."
    if prompt_id in running:
        http.post("/interrupt", {"prompt_id": prompt_id})
        return None, "Interrupted."
    return "ended", "It has already ended."


def cancel(env, text, where=None, http=None, wait=10.0):
    """Stop lab job `text`: a queued prompt leaves the queue, a running one is interrupted. A
    feed run is the program's own to stop. Returns {"ok", "refused", "words", "job"}.

    Without the network (root's board helper) the follower does it: the request goes in root's
    folder of asks, and its answer comes back in the follower's state folder."""
    where = where or Where(env)
    rec = find(env, text, where, http=http)
    A = _activity()
    if rec["state"] in A.FINAL:
        return _outcome(rec, "ended", f"That job has already ended ({A.WORDS[rec['state']]}).")
    if not rec.get("cancel_safe"):
        return _outcome(rec, "unsafe", rec.get("cancel_note") or "It can't be stopped from here.")
    lab = rec.get("lab") or {}
    inst = next((i for i in instances(where) if i["name"] == lab.get("instance")), None)
    asks = where.asks_dir()
    if http is None and where.system and os.path.isdir(asks) and os.access(asks, os.W_OK):
        out = hand_off(where, rec["id"], wait)
        if out is not None:
            return _outcome(rec, out.get("refused"), str(out.get("words") or ""))
    if inst is None:
        return _outcome(rec, "unsafe", "That ComfyUI isn't one this machine is set to watch any more.")
    try:
        refused, words = stop_prompt(http.get(inst["name"]) if isinstance(http, dict) else (http or Http(inst["url"])),
                                     lab.get("prompt_id"))
    except Exception as e:
        raise A.ActivityError(f"ComfyUI {inst['name']} couldn't be asked: {_why(e)}") from None
    return _outcome(rec, refused, words)


def hand_off(where, job_id, wait=10.0):
    """Ask the follower to stop `job_id`; its answer ({refused, words}) or None when it didn't
    answer in time."""
    A = _activity()
    rid = secrets.token_hex(8)
    folder = where.asks_dir()
    try:
        A.write_json(os.path.join(folder, rid + ".json"), {"id": rid, "verb": "cancel", "job": job_id, "at": where.env.now_ms()}, 0o640)
    except OSError:
        return None
    end = time.monotonic() + wait
    answer = os.path.join(where.state_dir(), "answers", rid + ".json")
    try:
        uid = owner_uid()
        owners = None if where.env.stand_in or uid is None else {uid}
        while time.monotonic() < end:
            data = read_regular(answer, 64 * 1024, owners)
            with contextlib.suppress(ValueError, TypeError):
                doc = json.loads(data) if data else None
                if isinstance(doc, dict) and doc.get("id") == rid:
                    return clean_doc(doc)
            time.sleep(0.1)
        return None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(folder, rid + ".json"))


# ------------------------------------------------------------------ media

MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF8", "gif"), (b"glTF", "glb"),
         (b"\x1a\x45\xdf\xa3", "webm"))


def sniff(data):
    """A file's type by its first bytes: png, jpg, webp, gif, mp4, webm or glb; None otherwise."""
    if not data:
        return None
    for head, ext in MAGIC:
        if data.startswith(head):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp":
        return "mp4"
    return None


MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "mp4": "video/mp4",
               "webm": "video/webm", "glb": "model/gltf-binary"}


class Media:
    """The follower's media folder: files named by what they hold (<kind>-<16 hex>.<type>), so a
    name never changes meaning and a browser may keep it. Bounded, hard: a file that would take
    it past `total` makes room (the oldest go, the ones shown last), or isn't kept."""

    def __init__(self, folder, total=MEDIA_TOTAL):
        self.folder, self.total = folder, total
        os.makedirs(folder, mode=0o750, exist_ok=True)
        self.keep = set()

    def _files(self):
        out = []
        try:
            names = os.listdir(self.folder)
        except OSError:
            return out
        for n in names:
            if MEDIA_NAME.match(n):
                with contextlib.suppress(OSError):
                    st = os.lstat(os.path.join(self.folder, n))
                    out.append((st.st_mtime, st.st_size, n))
        return out

    def used(self):
        return sum(s for _, s, _ in self._files())

    def put(self, data, prefix="of"):
        ext = sniff(data)
        if ext is None or len(data) > MEDIA_MAX or len(data) > self.total:
            return None
        name = f"{prefix}-{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
        path = os.path.join(self.folder, name)
        if os.path.lexists(path):
            with contextlib.suppress(OSError):
                os.utime(path, follow_symlinks=False)
            return name
        if self.used() + len(data) > self.total:
            self.prune(self.keep, room=len(data))
            if self.used() + len(data) > self.total:
                return None
        tmp = os.path.join(self.folder, f".{name}.{secrets.token_hex(4)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o640)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
        os.replace(tmp, path)
        return name

    def thumb(self, data):
        """A small WebP of an image (Pillow), or None when it can't make one: a picture of more
        than IMAGE_PIXELS_MAX pixels is never decoded (safe_image)."""
        try:
            import io
            im = safe_image(data)
            if im is None:
                return None
            im.thumbnail((THUMB_PX, THUMB_PX))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            out = io.BytesIO()
            im.save(out, format="WEBP", quality=82)
            return self.put(out.getvalue(), "th")
        except Exception:
            return None

    def prune(self, keep=(), room=0):
        """The folder within `total` less `room`: files not in `keep` go first, oldest first;
        then, if it is still over, the kept ones too, oldest first. The total is a hard limit."""
        files = sorted(self._files())                 # oldest first
        size = sum(s for _, s, _ in files) + room
        for pass_keep in (False, True):
            for _, s, n in files:
                if size <= self.total:
                    return
                if (n in keep) != pass_keep:
                    continue
                with contextlib.suppress(OSError):
                    os.unlink(os.path.join(self.folder, n))
                    size -= s


def safe_image(data):
    """A Pillow image of `data`, or None: its size is read from its header first, and a picture
    of more than IMAGE_PIXELS_MAX pixels (a decompression bomb) is never decoded."""
    try:
        import io
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = IMAGE_PIXELS_MAX
        im = Image.open(io.BytesIO(data))
        w, h = im.size
        if w * h > IMAGE_PIXELS_MAX:
            return None
        im.load()
        return im
    except Exception:
        return None


def media_path(folder, name):
    """The file of a media name in `folder`, or None: the name must be one the follower makes,
    and the file a regular one (not a link). Who serves it opens it with open_media."""
    if not isinstance(name, str) or not MEDIA_NAME.match(name):
        return None
    p = os.path.join(folder, name)
    try:
        return p if stat.S_ISREG(os.lstat(p).st_mode) else None
    except OSError:
        return None


def open_media(folder, name, owners=None):
    """(fd, stat) of a media file by its name, opened without following a link, a regular file
    owned by one of `owners` (the follower's user), or (None, None). For whoever serves it: the
    file it checked is the file it sends."""
    if not isinstance(name, str) or not MEDIA_NAME.match(name):
        return None, None
    return open_regular(os.path.join(folder, name), owners)


def _under(path, roots):
    real = os.path.realpath(path)
    return any(real == r or real.startswith(r.rstrip("/") + "/") for r in (os.path.realpath(x) for x in roots))


# ------------------------------------------------------------------ the follower

def _ws_connect(connect, url):
    """A websocket to a ComfyUI: messages of WS_MAX bytes at most, four waiting at most, and no
    proxy from the environment (websockets 15 and newer use one by default)."""
    kw = dict(max_size=WS_MAX, max_queue=4, open_timeout=TIMEOUT_S, close_timeout=1)
    try:
        return connect(url, proxy=None, **kw)
    except TypeError:                # websockets before 15: no proxy support, so none is used
        return connect(url, **kw)


class Follower:
    """Follows every configured ComfyUI and feed folder and keeps <state>/jobs.json and the media
    folder, for readers without the network (the board's API) or that want previews (the start
    page, `bromigos activity watch`).

    Each ComfyUI: /queue and /history every `poll` seconds, and its websocket (clientId
    bromigos-watch-<hex>) for the node that runs, the sampler's steps and the preview frames.
    Outputs of the newest ended prompts are fetched once (/view) and kept, with a thumbnail."""

    def __init__(self, where, poll=2.0, websocket=True, http=None, log=None, idle_poll=IDLE_POLL_S):
        self.where, self.poll_s, self.use_ws, self.idle_poll_s = where, poll, websocket, idle_poll
        self.http = http or {}
        self.log = log or (lambda words: print(words, file=sys.stderr, flush=True))
        self.state = where.state_dir()
        self.media = Media(where.media_dir())
        self.live = {}           # instance -> prompt id -> {node, progress, done, cached, stage_max, preview, …}
        self.ws_up = {}          # instance -> bool
        self.relay = {}          # instance -> whether another client's progress was seen
        self.cached = {}         # (instance, prompt id) -> outputs with media
        self.feed_media = {}     # path -> (mtime, media, thumb)
        self.preview_at = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.threads = {}
        self.answered = set()
        self.said = {}
        self.graphs = {}          # (instance, prompt id) -> its graph, for the stage of a node
        self._current = None      # (instance, prompt id) the websocket last said runs
        self._pending_preview = None

    # -- the websocket
    def on_message(self, inst, msg):
        """One websocket message: JSON text, or a binary frame (a preview image)."""
        name = inst["name"]
        with self.lock:
            prompts = self.live.setdefault(name, {})
            if isinstance(msg, (bytes, bytearray)):
                self._preview(name, prompts, bytes(msg))
                return
            try:
                doc = json.loads(msg)
            except ValueError:
                return
            if not isinstance(doc, dict) or not isinstance(doc.get("data"), dict):
                return
            kind, data = doc.get("type"), doc["data"]
            pid = data.get("prompt_id")
            if not isinstance(pid, str) or not PROMPT_ID.match(pid):
                return
            p = prompts.setdefault(pid, {"done": [], "cached": [], "stage_max": None, "node": None, "progress": None,
                                         "preview": None, "seen": True, "started": None})
            self.relay[name] = True
            if kind == "execution_start":
                p["started"] = data.get("timestamp") if isinstance(data.get("timestamp"), int) else self.where.env.now_ms()
            elif kind == "execution_cached":
                p["cached"] = [str(n) for n in data.get("nodes") or []][:500]
            elif kind == "executing":
                node = data.get("node")
                if node is None:
                    p["node"] = None
                    return
                if p["node"] is not None and str(p["node"]) not in p["done"]:
                    p["done"].append(str(p["node"]))
                p["node"] = str(node)
                st = self._stage_of(name, pid, str(node))
                if st is not None:
                    p["stage_max"] = max(p["stage_max"] or 0, STAGE_INDEX[st])
                p["progress"] = None
            elif kind == "progress":
                p["progress"] = {"value": data.get("value"), "max": data.get("max"), "node": str(data.get("node"))}
                st = self._stage_of(name, pid, str(data.get("node")))
                if st is not None:
                    p["stage_max"] = max(p["stage_max"] or 0, STAGE_INDEX[st])
            elif kind == "executed":
                if data.get("node") is not None and str(data["node"]) not in p["done"]:
                    p["done"].append(str(data["node"]))
            elif kind in ("execution_error", "execution_interrupted"):
                if data.get("node_id") is not None:
                    p["node"] = str(data["node_id"])
            p["last"] = self.where.env.now_ms()
            self._current = (name, pid)

    def _stage_of(self, name, pid, node):
        graph = self.graphs.get((name, pid))
        if not graph or node not in graph:
            return None
        return stage_of(graph[node].get("class_type"))

    def _preview(self, name, prompts, frame):
        if len(frame) < 8:
            return
        kind = struct.unpack(">I", frame[:4])[0]
        pid, data = None, None
        if kind == 1:
            data = frame[8:]
            cur = self._current
            pid = cur[1] if cur and cur[0] == name else None
        elif kind == 4:
            n = struct.unpack(">I", frame[4:8])[0]
            if n > 4096 or 8 + n > len(frame):
                return
            with contextlib.suppress(ValueError):
                meta = json.loads(frame[8:8 + n])
                pid = meta.get("prompt_id") if isinstance(meta, dict) else None
            data = frame[8 + n:]
        if not isinstance(pid, str) or not PROMPT_ID.match(pid) or not data:
            return
        now = time.monotonic()
        if now - self.preview_at.get((name, pid), 0) < PREVIEW_EVERY_S:
            self._pending_preview = (name, pid, data)
            return
        self.preview_at[(name, pid)] = now
        self._store_preview(name, pid, data, prompts)

    def _store_preview(self, name, pid, data, prompts):
        media = self.media.put(data, "pv")
        if media:
            p = prompts.setdefault(pid, {"done": [], "cached": [], "stage_max": None, "node": None, "progress": None,
                                         "preview": None, "seen": True, "started": None})
            p["preview"] = {"media": media, "at": self.where.env.now_ms()}
            p["seen"] = True

    def _ws_loop(self, inst, gone):
        """`gone` ends this instance's socket alone (it left labjobs.toml, or its address changed)."""
        try:
            from websockets.sync.client import connect
        except ImportError:
            self._say(inst["name"], "ws", "live progress needs python-websockets: queue and results only")
            return
        delay = 1.0
        # the relay node copies other clients' progress only to a watcher that names its token
        token = re.sub(r"[^A-Za-z0-9]", "", inst.get("relay_token") or "")
        cid = WATCH_PREFIX + (token + "-" if token else "") + secrets.token_hex(8)
        url = inst["url"].replace("http", "ws", 1) + "/ws?clientId=" + cid
        while not self.stop.is_set() and not gone.is_set():
            try:
                with _ws_connect(connect, url) as ws:
                    self.ws_up[inst["name"]] = True
                    delay = 1.0
                    while not self.stop.is_set() and not gone.is_set():
                        try:
                            msg = ws.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        self.on_message(inst, msg)
            except Exception:
                pass
            self.ws_up[inst["name"]] = False
            gone.wait(delay)
            delay = min(30.0, delay * 2)

    # -- one pass
    def _say(self, name, what, words):
        if self.said.get((name, what)) != words:
            self.said[(name, what)] = words
            self.log(f"bromigos activity follow: {name}: {words}")

    def _fetch_outputs(self, inst, http, rec):
        key = (inst["name"], rec["lab"]["prompt_id"])
        if key in self.cached:
            return self.cached[key]
        outs = []
        for o in (rec.get("result") or {}).get("outputs") or []:
            o = dict(o)
            outs.append(o)
            if self.media.used() >= self.media.total * 0.9:      # no room: listed, not fetched
                continue
            q = urllib.parse.urlencode({"filename": o["filename"], "subfolder": o["subfolder"], "type": o["type"]})
            with contextlib.suppress(Exception):
                data = http.fetch("/view?" + q)
                if data:
                    o["media"] = self.media.put(data, "of")
                    if o["media"] and o["kind"] == "image":
                        o["thumb"] = self.media.thumb(data) or o["media"]
        self.cached[key] = outs
        return outs

    def _feed_media(self, rec, seen):
        roots = [os.path.dirname(rec["lab"]["file"])] + config(self.where)["media_roots"]
        for m in rec["lab"]["media"] + rec["lab"]["outputs"] + ([rec["lab"]["preview"]] if rec["lab"]["preview"] else []):
            p = m.get("path")
            if not p:
                continue
            if self.where.system and not _under(p, roots):
                continue
            # opened once, not followed through a link, a regular file; and where it really is
            # (the open file's own path) is checked again against the roots
            fd, st = open_regular(p)
            if fd is None:
                continue
            seen.add(p)
            try:
                if self.where.system and not _under(os.readlink(f"/proc/self/fd/{fd}"), roots):
                    continue
                hit = self.feed_media.get(p)
                data = None
                if (not hit or hit[0] != st.st_mtime) and st.st_size <= MEDIA_MAX:
                    with contextlib.suppress(OSError):
                        data = os.read(fd, MEDIA_MAX + 1)
            except OSError:
                continue
            finally:
                os.close(fd)
            if not hit or hit[0] != st.st_mtime:
                name = self.media.put(data, "fm") if data else None
                thumb = self.media.thumb(data) if name and sniff(data) in ("png", "jpg", "webp", "gif") else None
                hit = self.feed_media[p] = (st.st_mtime, name, thumb or name)
            m["media"], m["thumb"] = hit[1], hit[2]

    def pass_once(self):
        """Read every ComfyUI and feed once, and write jobs.json."""
        now = self.where.env.now_ms()
        wfs = workflows(self.where)
        records, notes = [], []
        insts = instances(self.where)
        # an instance that left the settings: its socket ends, and what was kept of it goes
        names = {i["name"] for i in insts}
        for name in [n for n in self.threads if n not in names]:
            self.threads.pop(name)[0].set()
        with self.lock:
            for name in [n for n in self.live if n not in names]:
                del self.live[name]
        for key in [k for k in list(self.cached) + list(self.preview_at) if k[0] not in names]:
            self.cached.pop(key, None)
            self.preview_at.pop(key, None)
        for inst in insts:
            http = self.http.get(inst["name"]) or Http(inst["url"])
            if not self.http and not reachable(inst["url"]):
                if not inst.get("quiet"):
                    notes.append({"name": inst["name"], "state": "down", "words": "it isn't answering", "live": False, "relay": False})
                continue
            try:
                queue = http.get("/queue")
                history = http.get(f"/history?max_items={HISTORY_ITEMS}")
            except Exception as e:
                notes.append({"name": inst["name"], "state": "down", "words": _why(e), "live": False, "relay": False})
                continue
            key = (inst["url"], inst.get("relay_token") or "")
            if self.use_ws and (inst["name"] not in self.threads or self.threads[inst["name"]][1] != key):
                if inst["name"] in self.threads:
                    self.threads[inst["name"]][0].set()
                gone = threading.Event()
                threading.Thread(target=self._ws_loop, args=(inst, gone), daemon=True, name=f"ws-{inst['name']}").start()
                self.threads[inst["name"]] = (gone, key)
            with self.lock:
                for e in _entries(queue, history):
                    self.graphs[(inst["name"], e["prompt_id"])] = e["graph"]
                live = {k: json.loads(json.dumps(v)) for k, v in self.live.get(inst["name"], {}).items()}
            recs = comfy_records(inst, queue, history, now, wfs, live)
            ended = [r for r in recs if r["state"] in ("succeeded", "failed", "cancelled")]
            for r in ended[:OUTPUTS_CACHED]:
                outs = self._fetch_outputs(inst, http, r)
                if r.get("result") is not None:
                    r["result"]["outputs"] = outs
            records += recs
            notes.append({"name": inst["name"], "state": "ok", "words": "", "live": bool(self.ws_up.get(inst["name"])),
                          "relay": bool(self.relay.get(inst["name"]))})
            # forget what the websocket said of prompts that are gone
            known = {r["lab"]["prompt_id"] for r in recs}
            with self.lock:
                for pid in [p for p in self.live.get(inst["name"], {}) if p not in known]:
                    del self.live[inst["name"]][pid]
                for key in [k for k in list(self.cached) + list(self.preview_at) if k[0] == inst["name"] and k[1] not in known]:
                    self.cached.pop(key, None)
                    self.preview_at.pop(key, None)
                for key in [k for k in self.graphs if k[0] == inst["name"] and k[1] not in known]:
                    del self.graphs[key]
                pend = self._pending_preview
                if pend and pend[0] == inst["name"]:
                    self._pending_preview = None
                    self._store_preview(pend[0], pend[1], pend[2], self.live.setdefault(inst["name"], {}))
        seen = set()
        for r in feed_records(self.where, now):
            self._feed_media(r, seen)
            records.append(r)
        for p in [p for p in self.feed_media if p not in seen]:
            del self.feed_media[p]
        records.sort(key=_order)
        self.handle_asks()
        keep = set()
        for r in records:
            lab = r.get("lab") or {}
            for m in [lab.get("preview")] + list(lab.get("media") or []) + list((r.get("result") or {}).get("outputs") or []):
                if isinstance(m, dict):
                    keep.update(x for x in (m.get("media"), m.get("thumb")) if x)
        self.media.keep = keep
        self.media.prune(keep)
        self.write({"schema": SCHEMA, "at": now, "instances": notes, "jobs": records})
        return records

    def write(self, doc):
        A = _activity()
        os.makedirs(self.state, mode=0o750, exist_ok=True)
        public = json.loads(json.dumps(doc))
        for r in public["jobs"]:          # the files' own paths stay on this machine's side
            lab = r.get("lab") or {}
            lab.pop("file", None)
            for m in [lab.get("preview")] + list(lab.get("media") or []) + list(lab.get("outputs") or []) + \
                    list((r.get("result") or {}).get("outputs") or []):
                if isinstance(m, dict):
                    m.pop("path", None)
        A.write_json(os.path.join(self.state, "jobs.json"), public, 0o640)

    def handle_asks(self):
        """Root's requests to stop a prompt (cancel's hand-off): each answered once, in the state
        folder's answers/."""
        folder = self.where.asks_dir()
        try:
            names = os.listdir(folder)
        except OSError:
            return
        A = _activity()
        out_dir = os.path.join(self.state, "answers")
        for n in names:
            rid = n[:-5] if n.endswith(".json") else ""
            if not ASK_ID.match(rid) or rid in self.answered:
                continue
            self.answered.add(rid)
            doc = None
            data = read_regular(os.path.join(folder, n), 64 * 1024, None if self.where.env.stand_in else {0})
            with contextlib.suppress(ValueError, TypeError):
                doc = json.loads(data) if data else None
            if not isinstance(doc, dict) or doc.get("id") != rid or doc.get("verb") != "cancel":
                continue
            if not isinstance(doc.get("at"), int) or abs(self.where.env.now_ms() - doc["at"]) > 60_000:
                continue
            m = COMFY_ID.match(str(doc.get("job") or ""))
            if not m:
                answer = {"refused": "unsafe", "words": "That job can't be stopped from here."}
            else:
                inst = next((i for i in instances(self.where) if i["name"] == m.group(1)), None)
                if inst is None:
                    answer = {"refused": "unsafe", "words": "That ComfyUI isn't one this machine watches."}
                else:
                    try:
                        refused, words = stop_prompt(self.http.get(inst["name"]) or Http(inst["url"]), m.group(2))
                        answer = {"refused": refused, "words": words}
                    except Exception as e:
                        answer = {"refused": "unsafe", "words": f"ComfyUI couldn't be asked: {_why(e)}."}
            os.makedirs(out_dir, mode=0o750, exist_ok=True)
            A.write_json(os.path.join(out_dir, rid + ".json"), dict(answer, id=rid, at=self.where.env.now_ms()), 0o640)
        # old answers go
        with contextlib.suppress(OSError):
            for n in os.listdir(out_dir):
                p = os.path.join(out_dir, n)
                if time.time() - os.path.getmtime(p) > 120:
                    os.unlink(p)

    def run(self, once=False, idle_s=None, wanted=None, sleep=None):
        """Pass after pass, every `poll` seconds. With `wanted` (a file) and `idle_s`: stop once
        nobody touched it for that long (the board's reader works the same way)."""
        sleep = sleep or self.stop.wait
        try:
            while True:
                t0 = time.monotonic()
                try:
                    got = self.pass_once()
                except OSError as e:
                    self.log(f"bromigos activity follow: can't write {getattr(e, 'filename', None) or self.state}: {e.strerror}")
                    return 1
                if once or self.stop.is_set():
                    return 0
                if wanted and idle_s is not None:
                    try:
                        age = time.time() - os.stat(wanted).st_mtime
                    except OSError:
                        age = None
                    if age is None or age > idle_s:
                        return 0
                # while nothing runs or waits, a look every 30 s; the websocket's first word of a
                # prompt (another client's, through the relay) brings the next look forward
                busy = any(r["state"] in ("queued", "running") for r in got) or any(self.live.values())
                every = self.poll_s if busy else self.idle_poll_s
                waited = 0.0
                while waited < every - (time.monotonic() - t0) and not self.stop.is_set():
                    sleep(min(self.poll_s, max(0.2, every - (time.monotonic() - t0))))
                    waited += self.poll_s
                    if any(self.live.values()):
                        break
        finally:
            self.stop.set()


# ------------------------------------------------------------------ the terminal

def kitty_image(data, cols=40, rows=14, image_id=7311):
    """The escape codes that draw a PNG in kitty (its graphics protocol), or None when the
    picture isn't a PNG and Pillow can't make it one."""
    if sniff(data) != "png":
        try:
            import io
            im = safe_image(data)            # (never a picture of more than IMAGE_PIXELS_MAX pixels)
            if im is None:
                return None
            out = io.BytesIO()
            im.convert("RGBA").save(out, format="PNG")
            data = out.getvalue()
        except Exception:
            return None
    b64 = base64.standard_b64encode(data).decode()
    chunks = [b64[i:i + 4096] for i in range(0, len(b64), 4096)] or [""]
    out = [f"\x1b_Ga=d,d=I,i={image_id},q=2\x1b\\"]
    for k, c in enumerate(chunks):
        more = 1 if k < len(chunks) - 1 else 0
        head = f"a=T,f=100,i={image_id},c={cols},r={rows},C=1,q=2,m={more}" if k == 0 else f"m={more}"
        out.append(f"\x1b_G{head};{c}\x1b\\")
    return "".join(out)


def is_kitty(environ=None):
    e = os.environ if environ is None else environ
    return bool(e.get("KITTY_WINDOW_ID")) or e.get("TERM") == "xterm-kitty"


def bar(pct, width=24):
    if pct is None:
        return "·" * width
    n = int(round(width * max(0, min(100, pct)) / 100))
    return "█" * n + "░" * (width - n)


def _secs(ms):
    if ms is None:
        return None
    return _activity().took(ms)


def plain_lab(rec, now_ms):
    """The lines `bromigos activity show` adds for a lab job: where it runs, its timing, its
    preview and its outputs."""
    lab = rec.get("lab") or {}
    lines = [""]
    if lab.get("source") == "comfyui":
        lines.append(f"ComfyUI  {lab.get('instance')}  ·  prompt {lab.get('prompt_id')}" +
                     (f"  ·  from {lab['client']}" if lab.get("client") else ""))
        lines.append(f"Workflow {lab.get('workflow')}" + (f" ({lab['workflow_id']})" if lab.get("workflow_id") else ""))
        if lab.get("prompt"):
            lines.append(f"Prompt   {lab['prompt']}")
    else:
        lines.append(f"Feed     {lab.get('file') or lab.get('run')}")
    timing = []
    if lab.get("elapsed_ms") is not None:
        timing.append(f"ran {_secs(lab['elapsed_ms'])}")
    if lab.get("estimate_ms") and rec["state"] in ("queued", "running"):
        timing.append(f"usually takes {_secs(lab['estimate_ms'])}")
    if lab.get("estimated"):
        timing.append("progress estimated (no live progress from this ComfyUI)")
    if timing:
        lines.append("Time     " + ", ".join(timing))
    if rec["state"] == "queued" and lab.get("ahead") is not None:
        lines.append(f"Queue    position {lab.get('position')}, {lab['ahead']} ahead")
    outs = (rec.get("result") or {}).get("outputs") or lab.get("outputs") or []
    if outs:
        lines += ["", "Outputs"] + [f"  {o.get('kind', 'file'):<8} {o.get('subfolder') + '/' if o.get('subfolder') else ''}"
                                    f"{o.get('name')}" + (f"  ({o['width']}×{o['height']})" if o.get("width") and o.get("height") else "")
                                    for o in outs[:12]]
    return lines
