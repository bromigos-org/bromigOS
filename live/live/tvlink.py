"""Linked channels: a den screen showing a BRODEC channel for its owner (live/README.md,
"Linked channels").

BRODEC's desktop app, signed in as the den's owner, links a screen to a channel: a faction's
voice channel, a channel's stream, or a watch party. It writes what the screen should show
into a feed file and runs

    bromigos-live tv link --screen big --feed $XDG_RUNTIME_DIR/bromigos-live/link-big.json
    bromigos-live tv unlink --screen big

The feed (BRODEC's DenFeed, version 1) says the badge, the stream (an HLS address on the
owner's lab network and its Authorization header), the people in the channel (a picture or
their initial, speaking or not, den screens marked) and, for a watch party, where the
player should be. The den reads it again whenever it changes. Nothing of it is kept on
disk by the den: a restart forgets the link, and the app links again.

The file carries a short-lived viewer token, so it must be the user's own regular file,
readable by nobody else (mode 0600 or stricter), under $XDG_RUNTIME_DIR, and never a
symlink. The token and the address never reach a log, `tv state` or the screen.
"""
import json
import math
import os
import stat

FEED_VERSION = 1
MAX_FEED = 256 * 1024                 # bytes
MAX_PEOPLE = 24
MAX_PICTURE = 4 * 1024 * 1024
POLL = 0.4                            # seconds between the feed's stat checks
# The same numbers as BRODEC's watch parties (brodec-proto party::correct): alone within
# 300 ms, nudged 5 % faster or slower up to 2 s, a seek beyond.
IN_SYNC_MS = 300
NUDGE_MS = 2000
NUDGE_RATE = 0.05


class FeedError(ValueError):
    """A feed path or feed that the den refuses, in words for the person."""


def runtime_dir():
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def _inside(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def check_path(path, runtime=None, uid=None):
    """The feed's path, checked: absolute, under $XDG_RUNTIME_DIR, the user's own regular
    file (not a symlink), readable by nobody else, not too big. Returns the path with its
    folder resolved; raises FeedError."""
    uid = os.getuid() if uid is None else uid
    if not isinstance(path, str) or not path or "\0" in path:
        raise FeedError("no feed file")
    if not os.path.isabs(path):
        raise FeedError("the feed file needs a full path")
    root = os.path.realpath(runtime or runtime_dir())
    if not os.path.isdir(root):
        raise FeedError("no runtime folder ($XDG_RUNTIME_DIR)")
    folder = os.path.realpath(os.path.dirname(path))
    real = os.path.join(folder, os.path.basename(path))
    if not _inside(real, root) or real == root:
        raise FeedError("the feed file must be under $XDG_RUNTIME_DIR")
    try:
        st = os.lstat(real)
    except FileNotFoundError:
        raise FeedError("no such feed file") from None
    except OSError as e:
        raise FeedError(f"can't read the feed file ({e.strerror})") from None
    _check_stat(st, uid)
    return real


def _check_stat(st, uid):
    if stat.S_ISLNK(st.st_mode):
        raise FeedError("the feed file is a symlink")
    if not stat.S_ISREG(st.st_mode):
        raise FeedError("the feed file isn't a regular file")
    if st.st_uid != uid:
        raise FeedError("the feed file isn't yours")
    if st.st_mode & 0o077:
        raise FeedError("others can read the feed file: it must be mode 0600")
    if st.st_size > MAX_FEED:
        raise FeedError("the feed file is too big")


def signature(path):
    """What changes when the file is rewritten (cheap: one stat), or None when it's gone."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size, st.st_mode)


def read_feed(path, uid=None):
    """Read and check the feed at a checked path (opened without following a symlink,
    checked again once open). Raises FeedError."""
    uid = os.getuid() if uid is None else uid
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as e:
        raise FeedError("the feed file is a symlink" if e.errno == 40 else f"can't open the feed file ({e.strerror})") from None
    try:
        _check_stat(os.fstat(fd), uid)
        data = os.read(fd, MAX_FEED + 1)
    finally:
        os.close(fd)
    return parse_feed(data)


def _text(v, most):
    if not isinstance(v, str):
        return ""
    v = "".join(c for c in v if c.isprintable())
    return v.strip()[:most]


def _num(v, lo, hi, default):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return max(lo, min(hi, v))


def parse_feed(data, screen=None):
    """The feed's JSON, checked and cut down to what the den draws:
    {screen, badge, title, video {hls, authorization} | None, people [...], sync | None,
    voice, mic}. Raises FeedError."""
    if isinstance(data, bytes):
        if len(data) > MAX_FEED:
            raise FeedError("the feed file is too big")
        data = data.decode("utf-8", "replace")
    try:
        raw = json.loads(data)
    except (ValueError, TypeError):
        raise FeedError("the feed isn't JSON") from None
    if not isinstance(raw, dict):
        raise FeedError("the feed isn't an object")
    if raw.get("version") != FEED_VERSION:
        raise FeedError(f"the feed's version isn't {FEED_VERSION}")
    out = {"screen": _text(raw.get("screen"), 16), "badge": _text(raw.get("badge"), 48),
           "title": _text(raw.get("title"), 80), "voice": raw.get("voice") is True, "mic": raw.get("mic") is True,
           "video": None, "sync": None, "people": []}
    if screen and out["screen"] and out["screen"] != screen:
        raise FeedError(f"the feed is for the {out['screen']} screen")
    if not out["badge"]:
        raise FeedError("the feed has no badge")
    v = raw.get("video")
    if isinstance(v, dict) and isinstance(v.get("hls"), str):
        url = v["hls"].strip()
        if not url.startswith(("http://", "https://")) or any(c.isspace() for c in url) or len(url) > 2048:
            raise FeedError("the feed's stream isn't an http(s) address")
        auth = v.get("authorization") if isinstance(v.get("authorization"), str) else ""
        if any(c in auth for c in "\r\n") or len(auth) > 4096:
            raise FeedError("the feed's authorization isn't one header value")
        out["video"] = {"hls": url, "authorization": auth.strip()}
    s = raw.get("sync")
    if isinstance(s, dict):
        out["sync"] = {"playing": s.get("playing") is True,
                       "position_ms": int(_num(s.get("position_ms"), 0, 10 ** 13, 0)),
                       "rate": float(_num(s.get("rate"), 0.25, 4.0, 1.0)),
                       "at_ms": int(_num(s.get("at_ms"), 0, 10 ** 14, 0))}
    people = raw.get("people")
    if isinstance(people, list):
        for p in people[:MAX_PEOPLE]:
            if not isinstance(p, dict):
                continue
            name = _text(p.get("name"), 40)
            if not name:
                continue
            pic = p.get("picture") if isinstance(p.get("picture"), str) and os.path.isabs(p.get("picture")) else None
            out["people"].append({"name": name, "picture": pic, "face": _text(p.get("face"), 40),
                                  "speaking": p.get("speaking") is True, "endpoint": p.get("endpoint") is True})
    return out


def public(feed):
    """What `tv state` says about a linked screen: never the address or the token."""
    return {"linked": True, "badge": feed["badge"], "title": feed["title"], "video": bool(feed["video"]),
            "people": len(feed["people"]), "speaking": sum(1 for p in feed["people"] if p["speaking"]),
            "voice": feed["voice"], "mic": feed["mic"], "party": feed["sync"] is not None}


def expected_ms(sync, now_ms):
    """Where a party's player should be at now_ms (wall clock, ms)."""
    if not sync["playing"]:
        return sync["position_ms"]
    gone = max(0.0, (now_ms - sync["at_ms"]) * sync["rate"])
    return int(sync["position_ms"] + gone)


def correct(expected, actual, rate=1.0):
    """("none",), ("nudge", speed) or ("seek", ms): how a player at `actual` ms catches
    up with `expected` ms. The same as brodec-proto party::correct."""
    drift = int(actual) - int(expected)
    if abs(drift) <= IN_SYNC_MS:
        return ("none",)
    if abs(drift) <= NUDGE_MS:
        return ("nudge", rate * (1 - NUDGE_RATE) if drift > 0 else rate * (1 + NUDGE_RATE))
    return ("seek", int(expected))


def redact(text):
    """A log line from mpv about a stream, with any address and key taken out."""
    words = []
    for w in str(text).split():
        low = w.lower()
        if low.startswith(("authorization", "bearer", "x-emby-token", "x-plex-token", "x-mediabrowser-token",
                           "x-emby-authorization")):
            words.append("<redacted>")                          # a header: the rest of the line is its value
            break
        words.append("<stream>" if "://" in w or "token=" in low or "api_key=" in low else w)
    return " ".join(words)


# ------------------------------------------------------------------ pictures
_pictures = {}


def picture(path, uid=None):
    """A person's picture as (rgba bytes, w, h), square, at most 256 px; None when it isn't
    the user's own readable image file. Cached by the file's signature."""
    uid = os.getuid() if uid is None else uid
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_size > MAX_PICTURE:
        return None
    key = (path, st.st_mtime_ns, st.st_size)
    if key in _pictures:
        return _pictures[key]
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGBA")
            side = min(im.width, im.height)
            im = im.crop(((im.width - side) // 2, (im.height - side) // 2,
                          (im.width + side) // 2, (im.height + side) // 2))
            im.thumbnail((256, 256))
            out = (im.tobytes(), im.width, im.height)
    except Exception:                                           # noqa: BLE001
        out = None
    if len(_pictures) > 64:
        _pictures.clear()
    _pictures[key] = out
    return out


def _hue(name):
    """A stable tint for a person without a picture (their initial's disc)."""
    h = 0
    for c in name:
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return (h % 360) / 360.0


# ------------------------------------------------------------------ drawing
def tile_layout(n, w, h, video):
    """(size, [(cx, cy)]) for n tiles: a row along the bottom over a stream, or a centred
    grid filling the screen when there's no stream (voice only)."""
    if n <= 0:
        return 0.0, []
    if video:
        size = min(h * 0.24, (w * 0.92) / max(n, 1))
        gap = size * 0.12
        total = n * size + (n - 1) * gap
        x0 = (w - total) / 2 + size / 2
        cy = h - size * 0.72
        return size, [(x0 + i * (size + gap), cy) for i in range(n)]
    top, bottom = h * 0.20, h * 0.04                      # the badge and title above
    area_w, area_h = w * 0.92, h - top - bottom
    best = (0.0, 1, n)
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        size = min(area_w / cols, area_h / (rows * 1.22))
        if size > best[0]:
            best = (size, cols, rows)
    size, cols, rows = best
    size *= 0.86
    cell_w, cell_h = area_w / cols, area_h / rows
    out = []
    for i in range(n):
        r, c = divmod(i, cols)
        in_row = min(cols, n - r * cols)
        x0 = (w - in_row * cell_w) / 2
        out.append((x0 + (c + 0.5) * cell_w, top + (r + 0.45) * cell_h))
    return size, out


def draw(cr, w, h, feed, colours, t=0.0, motion="full", uid=None):
    """Draw a linked screen's overlay with cairo, in the den's phosphor: the badge, the
    title, the people as hologram tiles (lit while speaking, a TV on den screens) and, with
    no stream, a dark glass behind them. `colours(name, alpha)` is glkit.col."""
    import cairo
    u = h / 100.0
    pr, pg, pb, _ = colours("phosphor")
    video = feed["video"] is not None
    if not video:
        cr.set_source_rgba(*colours("panel", 0.92))
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgba(pr, pg, pb, 0.06)                      # the glass's scanlines
        for y in range(0, int(h), max(2, int(2 * u))):
            cr.rectangle(0, y, w, max(1.0, 0.5 * u))
        cr.fill()
    else:
        grad = cairo.LinearGradient(0, h * 0.62, 0, h)
        nr, ng, nb, _ = colours("panel")
        grad.add_color_stop_rgba(0, nr, ng, nb, 0.0)
        grad.add_color_stop_rgba(1, nr, ng, nb, 0.78)
        cr.set_source(grad)
        cr.rectangle(0, h * 0.62, w, h * 0.38)
        cr.fill()
    cr.select_font_face("Geist Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    _badge(cr, w, h, u, feed, colours, t, motion)
    if not video and feed["title"] and feed["title"].upper() not in feed["badge"].upper():
        cr.set_font_size(6 * u)
        title = feed["title"].upper()
        while title and cr.text_extents(title).x_advance > w - 12 * u:
            title = title[:-2] + "…"
        e = cr.text_extents(title)
        cr.set_source_rgba(pr, pg, pb, 0.85)
        cr.move_to((w - e.x_advance) / 2, 22 * u)
        cr.show_text(title)
    people = feed["people"]
    size, centres = tile_layout(len(people), w, h, video)
    room = 1.08 if video else 1.4                               # how wide a name may run past its tile
    for p, (cx, cy) in zip(people, centres):
        _tile(cr, cx, cy, size, p, colours, t, motion, u, uid, room)


def _badge(cr, w, h, u, feed, colours, t, motion):
    pr, pg, pb, _ = colours("phosphor")
    text = feed["badge"].upper()
    live = text.startswith("LIVE")
    size = 6.5 * u
    cr.set_font_size(size)
    while size > 4 * u and cr.text_extents(text).x_advance > w * 0.62:
        size *= 0.92
        cr.set_font_size(size)
    while text and cr.text_extents(text).x_advance > w * 0.62:
        text = text[:-2] + "…"
    e = cr.text_extents(text)
    dot = 4.2 * u if live else 0.0
    mic = 5.5 * u if feed["mic"] else 0.0
    x, y, bh = 4 * u, 4 * u, 10 * u
    bw = e.x_advance + dot + mic + 6 * u + (1.5 * u if dot else 0) + (1.5 * u if mic else 0)
    cr.set_source_rgba(*colours("panel", 0.82))
    _round(cr, x, y, bw, bh, 2 * u)
    cr.fill()
    cr.set_source_rgba(pr, pg, pb, 0.75)
    cr.set_line_width(max(1.0, 0.45 * u))
    _round(cr, x, y, bw, bh, 2 * u)
    cr.stroke()
    tx = x + 3 * u
    if live:
        a = 1.0 if motion != "full" else 0.65 + 0.35 * (0.5 + 0.5 * math.sin(t * 3.2))
        cr.set_source_rgba(*colours("danger", a))
        cr.arc(tx + dot / 2 - 0.4 * u, y + bh / 2, 1.6 * u, 0, 2 * math.pi)
        cr.fill()
        tx += dot + 1.5 * u
    cr.set_source_rgba(pr, pg, pb, 0.95)
    cr.move_to(tx, y + bh / 2 + e.height / 2 - 0.2 * u)
    cr.show_text(text)
    tx += e.x_advance + 1.5 * u
    if mic:
        _mic(cr, tx + mic / 2, y + bh / 2, 3.6 * u, colours("amber"))


def _round(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


def _mic(cr, cx, cy, s, c):
    """A lit microphone: the TV is listening (the owner turned it on)."""
    cr.set_source_rgba(*c)
    _round(cr, cx - s * 0.28, cy - s * 0.55, s * 0.56, s * 0.8, s * 0.28)
    cr.fill()
    cr.set_line_width(max(1.0, s * 0.14))
    cr.arc(cx, cy - s * 0.1, s * 0.48, 0.15 * math.pi, 0.85 * math.pi)
    cr.stroke()
    cr.move_to(cx, cy + s * 0.38)
    cr.line_to(cx, cy + s * 0.6)
    cr.stroke()


def _tv_glyph(cr, cx, cy, s, c):
    """A small TV: this tile is a den screen in the channel."""
    cr.set_source_rgba(*c)
    cr.set_line_width(max(1.0, s * 0.12))
    _round(cr, cx - s * 0.5, cy - s * 0.38, s, s * 0.62, s * 0.08)
    cr.stroke()
    cr.move_to(cx - s * 0.22, cy + s * 0.4)
    cr.line_to(cx + s * 0.22, cy + s * 0.4)
    cr.stroke()
    cr.move_to(cx, cy + s * 0.24)
    cr.line_to(cx, cy + s * 0.4)
    cr.stroke()


def _tile(cr, cx, cy, size, p, colours, t, motion, u, uid, room=1.08):
    import colorsys

    import cairo
    pr, pg, pb, _ = colours("phosphor")
    r = size * 0.38
    speaking = p["speaking"]
    # the glass disc
    glass = cairo.RadialGradient(cx, cy - r * 0.3, r * 0.1, cx, cy, r)
    nr, ng, nb, _ = colours("panel")
    glass.add_color_stop_rgba(0, pr * 0.25 + nr, pg * 0.25 + ng, pb * 0.25 + nb, 0.9)
    glass.add_color_stop_rgba(1, nr, ng, nb, 0.92)
    cr.set_source(glass)
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.fill()
    img = picture(p["picture"], uid) if p["picture"] else None
    cr.save()
    cr.arc(cx, cy, r * 0.92, 0, 2 * math.pi)
    cr.clip()
    if img:
        data, iw, ih = img
        surf = _surface(data, iw, ih)
        scale = (2 * r * 0.92) / iw
        cr.translate(cx - r * 0.92, cy - r * 0.92)
        cr.scale(scale, scale)
        cr.set_source_surface(surf, 0, 0)
        cr.paint_with_alpha(0.88)
        cr.identity_matrix()
        cr.set_source_rgba(pr, pg, pb, 0.18)                        # the hologram's tint
        cr.paint()
    else:
        hr, hg, hb = colorsys.hsv_to_rgb(_hue(p["name"]), 0.45, 0.5)
        cr.set_source_rgba(hr * 0.5 + pr * 0.3, hg * 0.5 + pg * 0.3, hb * 0.5 + pb * 0.3, 0.55)
        cr.paint()
        cr.set_font_size(r * 0.95)
        initial = p["name"][0].upper()
        e = cr.text_extents(initial)
        cr.set_source_rgba(pr, pg, pb, 0.95)
        cr.move_to(cx - e.x_advance / 2 - e.x_bearing * 0.2, cy + e.height / 2)
        cr.show_text(initial)
    cr.set_source_rgba(pr, pg, pb, 0.12)                            # scanlines over the face
    step = max(2.0, r / 9)
    y = cy - r
    while y < cy + r:
        cr.rectangle(cx - r, y, 2 * r, max(1.0, step * 0.35))
        y += step
    cr.fill()
    cr.restore()
    # the ring: dim, or lit while speaking (a pulse in full motion)
    if speaking:
        pulse = 1.0 if motion != "full" else 0.5 + 0.5 * math.sin(t * 6.0)
        cr.set_source_rgba(pr, pg, pb, 0.25 + 0.25 * pulse)
        cr.set_line_width(max(2.0, r * 0.22))
        cr.arc(cx, cy, r * 1.12, 0, 2 * math.pi)
        cr.stroke()
        cr.set_source_rgba(pr, pg, pb, 1.0)
        cr.set_line_width(max(1.5, r * 0.09))
    else:
        cr.set_source_rgba(pr, pg, pb, 0.38)
        cr.set_line_width(max(1.0, r * 0.05))
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.stroke()
    if p["endpoint"]:
        gx, gy, gs = cx + r * 0.78, cy + r * 0.72, r * 0.52
        cr.set_source_rgba(*colours("panel", 0.95))
        cr.arc(gx, gy, gs * 0.72, 0, 2 * math.pi)
        cr.fill()
        _tv_glyph(cr, gx, gy, gs * 0.8, (pr, pg, pb, 0.95))
    # the name: a den screen by its own label ("LIVING ROOM TV"), its owner's initial above
    fs = max(5.0, min(r * 0.36, 6 * u))
    cr.set_font_size(fs)
    name = p["name"].upper()
    if p["endpoint"] and " · " in name:
        name = name.split(" · ", 1)[1]
    while name and cr.text_extents(name).x_advance > size * room:
        name = name[:-2] + "…"
    e = cr.text_extents(name)
    cr.set_source_rgba(pr, pg, pb, 0.95 if speaking else 0.72)
    cr.move_to(cx - e.x_advance / 2, cy + r + fs * 1.25)
    cr.show_text(name)


_surfaces = {}


def _surface(data, w, h):
    """RGBA bytes (PIL's) as a cairo ARGB32 surface (premultiplied BGRA), cached per picture."""
    import cairo
    import numpy as np
    key = (id(data), w, h)
    hit = _surfaces.get(key)
    if hit is not None and hit[0] is data:
        return hit[1]
    a = np.frombuffer(data, np.uint8).reshape(h, w, 4).astype(np.uint16)
    alpha = a[..., 3:4]
    out = np.empty((h, w, 4), np.uint8)
    out[..., 0] = (a[..., 2] * alpha[..., 0] // 255)
    out[..., 1] = (a[..., 1] * alpha[..., 0] // 255)
    out[..., 2] = (a[..., 0] * alpha[..., 0] // 255)
    out[..., 3] = alpha[..., 0]
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, w)
    buf = bytearray(stride * h)
    view = np.frombuffer(buf, np.uint8).reshape(h, stride)
    view[:, :w * 4] = out.reshape(h, w * 4)
    surf = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, w, h, stride)
    if len(_surfaces) > 64:
        _surfaces.clear()
    _surfaces[key] = (data, surf, buf)
    return surf


# ------------------------------------------------------------------ the TV's side (live/live/tv.py)
def _mono():
    import time
    return time.monotonic()


def _now_ms():
    import time
    return time.time() * 1000.0


class Links:
    """Linked screens, mixed into live.tv.TV: `tv link` / `tv unlink`, the feed read again
    when it changes, the screen's channel while linked, its stream, its party sync and the
    overlay. A link lives in memory only."""

    SYNC_EVERY = 2.0                                    # seconds between a party's sync checks

    def init_links(self):
        self.links = {}                                 # screen -> {path, sig, feed, gen, ...}

    # ---- the commands
    def link_command(self, verb, screen, rest):
        js = "--json" in rest
        words = [w for w in rest if w != "--json"]

        def answer(ok, **kw):
            if js:
                return json.dumps(dict(ok=ok, **kw))
            return kw.get("message") or kw.get("error") or ("ok" if ok else "failed")
        if not screen:
            return answer(False, error="name the screen: --screen big|wave|emblem")
        if verb == "unlink":
            if screen not in self.links:
                return answer(False, error=f"{screen} isn't linked", screen=screen)
            self.unlink(screen)
            return answer(True, screen=screen, linked=False, message=f"{screen}: unlinked; back to its channel")
        path = None
        for i, w in enumerate(words):
            if w == "--feed" and i + 1 < len(words):
                path = words[i + 1]
            elif w.startswith("--feed="):
                path = w.split("=", 1)[1]
        if not path:
            return answer(False, error="bromigos-live tv link --screen S --feed PATH")
        if not self.enabled():
            return answer(False, error="Den TV is off")
        try:
            feed = self.link(screen, path)
        except FeedError as e:
            return answer(False, error=str(e), screen=screen)
        return answer(True, screen=screen, linked=True, badge=feed["badge"],
                      message=f"{screen}: linked to {feed['badge']}")

    def link(self, screen, path):
        real = check_path(path)
        feed = read_feed(real)
        if feed["screen"] and feed["screen"] != screen:
            raise FeedError(f"the feed is for the {feed['screen']} screen")
        old = self.links.get(screen)
        self.links[screen] = {"path": real, "sig": signature(real), "feed": feed, "gen": (old["gen"] + 1) if old else 1,
                              "checked": _mono(), "synced": 0.0, "bad": None,
                              "sound_before": old["sound_before"] if old else self.screens[screen]["sound"]}
        d = self.decks[screen]
        self._unload(d)
        d.osd_sig = None
        if feed["video"]:
            self.set_sound(screen, on=True)              # it joins as a viewer and a listener
        self.log(f"tv: {screen}: linked to {feed['badge']}")
        self.wake.set()
        self._changed()
        return feed

    def unlink(self, screen, why="BACK TO CHANNEL"):
        link = self.links.pop(screen, None)
        if link is None:
            return
        d = self.decks[screen]
        self._unload(d)
        if d.player is not None:
            _set(d.player, "redact", None)
        d.osd_sig = None
        self.set_sound(screen, on=link["sound_before"])
        self.feedback(screen, why)
        self.log(f"tv: {screen}: unlinked")
        self.wake.set()

    def links_tick(self):
        """Each linked screen's feed, checked at most every POLL seconds: read again when it
        changed, unlinked when it's gone; a bad rewrite keeps the last good feed."""
        now = _mono()
        for screen, link in list(self.links.items()):
            if now - link["checked"] < POLL:
                continue
            link["checked"] = now
            sig = signature(link["path"])
            if sig is None:
                self.unlink(screen, "LINK ENDED")
                continue
            if sig == link["sig"]:
                continue
            link["sig"] = sig
            try:
                feed = read_feed(link["path"])
            except FeedError as e:
                if link["bad"] != str(e):
                    link["bad"] = str(e)
                    self.log(f"tv: {screen}: the link's feed was refused ({e}); keeping the last one")
                continue
            link["bad"] = None
            if (feed["video"] or {}).get("hls") != (link["feed"]["video"] or {}).get("hls") or \
                    (feed["video"] or {}).get("authorization") != (link["feed"]["video"] or {}).get("authorization"):
                link["gen"] += 1                         # a new stream or token: load it again
            link["feed"] = feed
            self.decks[screen].osd_sig = None
            self._changed()

    # ---- the screen's channel, slot and stream while linked
    def link_channel(self, screen):
        feed = self.links[screen]["feed"]
        return {"key": f"link-{screen}", "kind": "link", "name": feed["badge"], "screens": [screen],
                "bumpers": False, "link": screen}

    def link_feed(self, screen):
        link = self.links.get(screen)
        return link["feed"] if link else None

    def link_slot(self, ch):
        link = self.links.get(ch.get("link"))
        if link is None:
            return None
        feed = link["feed"]
        item = {"id": f"{ch['key']}-{link['gen']}", "title": feed["title"] or feed["badge"], "kind": "live"}
        offset = expected_ms(feed["sync"], _now_ms()) / 1000.0 if feed["sync"] else None
        return _tvl().Slot(item=item, offset=offset, start=None, end=None, index=0, next=None)

    def link_stream(self, ch, slot):
        feed = self.link_feed(ch.get("link"))
        if not feed or not feed["video"]:
            return None
        v = feed["video"]
        return {"url": v["hls"], "headers": {"Authorization": v["authorization"]} if v["authorization"] else {},
                "ytdl_format": None, "title": feed["badge"], "start": slot.offset if slot else None, "web": None,
                "server": "BRODEC", "private": True}

    def link_paused(self, screen):
        feed = self.link_feed(screen)
        return bool(feed and feed["sync"] and not feed["sync"]["playing"])

    def link_check(self, d, ch, slot):
        """A party's player kept with the host's: every SYNC_EVERY seconds, the same
        correction as BRODEC's (alone, nudged or seeked)."""
        link = self.links.get(ch.get("link"))
        p = d.player
        if link is None or p is None or not link["feed"]["sync"]:
            return None
        sync = link["feed"]["sync"]
        now = _mono()
        if now - link["synced"] < self.SYNC_EVERY or not p.started or p.seeking():
            return None
        link["synced"] = now
        pos = p.position()
        if pos is None:
            return None
        c = correct(expected_ms(sync, _now_ms()), pos * 1000.0, sync["rate"])
        if c[0] == "seek":
            p.seek(c[1] / 1000.0)
            _speed(p, sync["rate"])
        elif c[0] == "nudge":
            _speed(p, c[1])
        else:
            _speed(p, sync["rate"])
        return c

    def link_overlay(self, screen):
        """(feed, animation clock) for a linked screen's overlay, else None. The clock moves
        at 10 steps a second only while something on it moves (full motion, someone
        speaking or LIVE), so a still overlay is drawn once."""
        feed = self.link_feed(screen)
        if feed is None:
            return None
        moving = self.motion == "full" and (any(p["speaking"] for p in feed["people"])
                                            or feed["badge"].upper().startswith("LIVE"))
        return feed, (round(_mono() * 10) / 10 if moving else 0.0)


def _tvl():
    from . import LIB  # noqa: F401
    import bromigos_tv
    return bromigos_tv


def _set(obj, name, value):
    try:
        setattr(obj, name, value)
    except AttributeError:
        pass


def _speed(player, rate):
    f = getattr(player, "speed", None)
    if callable(f):
        f(rate)
