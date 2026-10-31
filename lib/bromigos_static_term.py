"""STATIC in a terminal (docs/lab.md, the media TUI): crisp pictures through kitty's graphics protocol
where the terminal has it, half-block pixel art in the theme's colours elsewhere, and a few
characters of plain text where neither works (a bare Linux console, ASCII icons).

  look(env=None) -> "kitty" | "blocks" | "text"   BROMIGOS_STATIC_TERM decides outright
  glyph(face, ascii=False) -> "[•_•]"             a status line's STATIC, one face in five cells
  head(face, frame=0, pal=None) -> rows of colours  his monitor as 16x14 pixel art (no rasterizer)
  figure(pose, cols, rows, frame=0, pal=None)      a pose as cols x (rows*2) pixels (rsvg-convert)
  blocks(px) -> rich Text                          pixels as half-blocks: two to a cell
  Sprite(...)                                       the Textual widget: picks the look, animates a few
                                                    frames off the input path, never blocks

Pixels are lists of rows of "#rrggbb" or None (clear). Everything is cached: a frame is drawn
once. The kitty path uses Unicode placeholders (the image is sent once, then each cell is an
ordinary character), so Textual's redraws never smear it.
"""
import base64
import os
import random
import shutil
import struct
import subprocess
import sys
import zlib

import bromigos_static as S

# ------------------------------------------------------------------ which look
GLYPHS = {"neutral": "[•_•]", "watching": "[•_•]", "happy": "[^_^]", "laughing": "[^▽^]", "smug": "[¬‿¬]",
          "startled": "[O_O]", "suspicious": "[¬_¬]", "glum": "[;_;]", "listening": "[∿∿∿]",
          "asleep": "[-_-]ᶻ", "snow": "[▒▒▒]", "onair": "[■‿■]", "popcorn": "[•ω•]", "whack": "[×_×]",
          "fiddle": "[°_°]"}
ASCII = {"neutral": "[o_o]", "watching": "[o_o]", "happy": "[^_^]", "laughing": "[^D^]", "smug": "[-_~]",
         "startled": "[O_O]", "suspicious": "[-_-]", "glum": "[;_;]", "listening": "[~~~]", "asleep": "[-_-]z",
         "snow": "[###]", "onair": "[#_#]", "popcorn": "[o_o]", "whack": "[x_x]", "fiddle": "[o_O]"}


def _colours(env):
    if env.get("BROMIGOS_COLORS") in ("16", "256", "truecolor"):
        return env["BROMIGOS_COLORS"]
    if env.get("TERM") in ("linux", "dumb", "vt100", "vt220"):
        return "16"
    return "truecolor" if env.get("COLORTERM") in ("truecolor", "24bit") or "kitty" in env.get("TERM", "") \
        else "256"


def look(env=None):
    """kitty (pictures), blocks (half-block pixel art) or text (a few characters)."""
    env = os.environ if env is None else env
    forced = (env.get("BROMIGOS_STATIC_TERM") or "").lower()
    if forced in ("kitty", "blocks", "text"):
        return forced
    if env.get("BROMIGOS_ICONS") == "ascii" or _colours(env) == "16":
        return "text"
    kitty = bool(env.get("KITTY_WINDOW_ID")) or env.get("TERM") == "xterm-kitty"
    if kitty and not env.get("TMUX") and not env.get("STY") and not env.get("SSH_TTY"):
        return "kitty"
    return "blocks"


def glyph(face, ascii=False):
    return (ASCII if ascii else GLYPHS).get(face, "[•_•]")


# ------------------------------------------------------------------ pixel art: the head, by hand
def head(face="neutral", frame=0, pal=None, hc=False):
    """His monitor as 16x14 pixels, drawn straight onto the grid (crisp at any terminal size):
    the antenna and its bead, the amber tally lamp, the casing with its side and knob, and the
    face's half-size pixels on the screen."""
    R = S.roles(pal, hc)
    W, H = 16, 14
    g = [[None] * W for _ in range(H)]

    def put(x, y, c):
        if 0 <= x < W and 0 <= y < H:
            g[y][x] = c
    bead = 1 if frame % 4 in (1, 2) and face != "asleep" else 0           # the antenna wiggles
    for x, y in ((10, 3), (11, 2), (12, 1)):
        put(x, y, R["line"])
    put(13 - bead, 0, R["line"])
    put(3, 2, R["amberhot"] if face == "onair" else R["amber"])
    put(4, 2, R["amber"])
    for y in range(3, 14):                                                # the casing
        for x in range(0, 14):
            edge = y in (3, 13) or x in (0, 13)
            put(x, y, R["line"] if edge else R["fill"])
    for y in range(4, 13):                                                # its right side
        put(14, y, R["fill2"])
        put(15, y, R["line"] if y not in (4, 12) else None)
    put(14, 3, R["line"])
    put(15, 8, R["px"])
    face_px = S.face_grid(face, frame, mini=True)
    for y in range(7):
        for x in range(10):
            c = face_px[y][x] if y < len(face_px) else "."
            put(2 + x, 5 + y, R["px"] if c == "#" else (S.mix(R["screen"], R["px2"], .5) if c == "+" else
                                                            R["amber"] if c == "a" else R["screen"]))
    for y in range(4, 13):                                                # the bezel
        put(1, y, R["fill2"])
        put(12, y, R["fill2"])
    for x in range(1, 13):
        put(x, 4, R["fill2"])
        put(x, 12, R["fill2"])
    return g


# ------------------------------------------------------------------ pixels from the SVG
_CACHE = {}


def _png(data):
    """(width, height, rows of RGBA bytes) from an 8-bit RGBA or RGB PNG (rsvg-convert's)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat = 8, b""
    w = h = ctype = 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            if depth != 8 or ctype not in (2, 6):
                raise ValueError("unsupported PNG")
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + n
    bpp = 4 if ctype == 6 else 3
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev, i = [], bytearray(stride), 0
    for _y in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        if bpp == 3:
            line = bytearray(b"".join(bytes(line[k:k + 3]) + b"\xff" for k in range(0, stride, 3)))
        rows.append(bytes(line))
        prev = line if bpp == 4 else bytearray(raw[i - stride:i])
    return w, h, rows


def render_png(svg, width=None, height=None):
    """An SVG as PNG bytes through rsvg-convert, or None without it."""
    exe = shutil.which("rsvg-convert")
    if not exe:
        return None
    cmd = [exe] + (["-w", str(width)] if width else []) + (["-h", str(height)] if height else [])
    try:
        r = subprocess.run(cmd, input=svg.encode(), capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 and r.stdout else None


def figure(pose, cols, rows, frame=0, pal=None, hc=False, crop=None):
    """A pose as cols x rows*2 pixels (for half-blocks): rendered flat (EMBER), every pixel
    either clear or a solid colour; None without rsvg-convert."""
    key = ("fig", pose, cols, rows, frame, tuple(sorted((pal or {}).items())), hc, crop)
    if key in _CACHE:
        return _CACHE[key]
    doc = S.svg(pose, frame=frame, pal=pal, level="ember", hc=hc, size=rows * 2, crop=crop, line_px=0.8)
    doc = doc.replace("<svg ", '<svg shape-rendering="crispEdges" ', 1)        # pixels, not smears
    data = render_png(doc, height=rows * 2)
    out = None
    if data:
        w, h, lines = _png(data)
        out = []
        for y in range(h):
            row = []
            for x in range(min(w, cols)):
                r, g, b, a = lines[y][x * 4:x * 4 + 4]
                row.append("#%02x%02x%02x" % (min(255, r * 255 // a), min(255, g * 255 // a), min(255, b * 255 // a))
                           if a >= 110 else None)
            out.append(row + [None] * (cols - len(row)))
    _CACHE[key] = out
    return out


def blocks(px, bg=None):
    """Pixels as rich Text, two pixel rows to a cell: ▀ in the top's colour over the bottom's."""
    from rich.style import Style
    from rich.text import Text
    t = Text(no_wrap=True, overflow="crop")
    for y in range(0, len(px), 2):
        top, bot = px[y], (px[y + 1] if y + 1 < len(px) else [None] * len(px[y]))
        for a, b in zip(top, bot):
            if a is None and b is None:
                t.append(" ", Style(bgcolor=bg) if bg else None)
            elif a is None:
                t.append("▄", Style(color=b, bgcolor=bg))
            elif b is None:
                t.append("▀", Style(color=a, bgcolor=bg))
            else:
                t.append("▀", Style(color=a, bgcolor=b))
        if y + 2 < len(px):
            t.append("\n")
    return t


# ------------------------------------------------------------------ kitty: pictures in cells
# the row/column marks of kitty's Unicode placeholders (kitty's rowcolumn-diacritics.txt)
DIACRITICS = [0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F, 0x0346, 0x034A, 0x034B, 0x034C,
              0x0350, 0x0351, 0x0352, 0x0357, 0x035B, 0x0363, 0x0364, 0x0365, 0x0366, 0x0367, 0x0368, 0x0369,
              0x036A, 0x036B, 0x036C, 0x036D, 0x036E, 0x036F, 0x0483, 0x0484, 0x0485, 0x0486, 0x0487, 0x0592,
              0x0593, 0x0594, 0x0595, 0x0597, 0x0598, 0x0599, 0x059C, 0x059D, 0x059E, 0x059F, 0x05A0, 0x05A1]
PLACEHOLDER = "\U0010EEEE"


def cell_pixels(fd=None):
    """A cell's size in pixels, from the terminal (TIOCGWINSZ), else 10x20."""
    try:
        import fcntl
        import termios
        fd = sys.__stdout__.fileno() if fd is None else fd
        rows, cols, xp, yp = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
        if cols and rows and xp and yp:
            return xp / cols, yp / rows
    except (OSError, ValueError, AttributeError, ImportError):
        pass
    return 10.0, 20.0


def kitty_transmit(png, image_id, cols, rows):
    """The escape codes that send a PNG once and place it virtually over cols x rows cells
    (shown wherever the placeholders for image_id are drawn)."""
    b64 = base64.standard_b64encode(png).decode()
    chunks = [b64[i:i + 4096] for i in range(0, len(b64), 4096)] or [""]
    out = []
    for n, c in enumerate(chunks):
        more = 1 if n < len(chunks) - 1 else 0
        if n == 0:
            out.append(f"\x1b_Ga=T,U=1,f=100,q=2,i={image_id},c={cols},r={rows},m={more};{c}\x1b\\")
        else:
            out.append(f"\x1b_Gm={more};{c}\x1b\\")
    return "".join(out)


def kitty_cells(image_id, cols, rows):
    """rich Text of placeholder cells for an image: its id in the foreground colour."""
    from rich.style import Style
    from rich.text import Text
    colour = "#%06x" % (image_id & 0xFFFFFF)
    t = Text(no_wrap=True, overflow="crop")
    for r in range(rows):
        t.append("".join(PLACEHOLDER + chr(DIACRITICS[r]) + chr(DIACRITICS[c]) for c in range(cols)),
                 Style(color=colour))
        if r < rows - 1:
            t.append("\n")
    return t


# ------------------------------------------------------------------ the Textual widget
try:
    from textual.widgets import Static as _Static
except ImportError:                                                         # no Textual: the helpers still work
    _Static = None


def _palette():
    try:
        import bromigos_textual as BT
        return BT.palette()
    except Exception:                                                       # noqa: BLE001
        return dict(S.WICK)


def _motion():
    try:
        import bromigos_textual as BT
        return BT.motion()
    except Exception:                                                       # noqa: BLE001
        return "full"


if _Static is not None:
    class Sprite(_Static):
        """STATIC in a Textual app. kind "head" (his monitor, 16 cells by 7), "status" (one line
        of text) or "figure" (a whole pose, cols x rows cells). He animates a few frames at about
        4 a second while shown, never under reduced motion; the frames are drawn in a worker
        thread, so input never waits on him."""

        DEFAULT_CSS = "Sprite { width: auto; height: auto; }"
        _ids = random.Random().randrange(1, 1 << 20) << 4

        def __init__(self, pose="watching", face=None, kind="head", cols=24, rows=12, label="", **kw):
            super().__init__("", **kw)
            self.pose, self.face, self.kind, self.cols, self.rows, self.label = pose, face, kind, cols, rows, label
            self.look = look()
            self.frame, self.frames, self.timer, self.sent = 0, {}, None, set()
            if self.kind == "head":
                self.cols, self.rows = 16, 7
            self.tooltip = label or "STATIC, the den's host"

        def on_mount(self):
            if self.look == "kitty" and getattr(self.app, "is_headless", False):
                self.look = "blocks"                                        # tests and recordings: no terminal
            self._st_draw()
            if _motion() == "full" and self._st_count() > 1:
                self.timer = self.set_interval(0.25, self._st_tick)

        def set_pose(self, pose, face=None, label=None):
            if label:
                self.tooltip = label
            if (pose, face) != (self.pose, self.face):
                self.pose, self.face, self.frame = pose, face, 0
                self._st_draw()

        def _st_face(self):
            return self.face or S.POSES.get(self.pose, {}).get("face", "neutral")

        def _st_count(self):
            if self.kind == "status":
                return 1
            if self.kind == "head":
                return 4 if self._st_face() in ("snow", "listening", "asleep", "whack", "fiddle", "watching") else 1
            return S.frames(self.pose)

        def _st_tick(self):
            n = self._st_count()
            if n > 1 and self.display:
                self.frame = (self.frame + 1) % n
                self._st_draw()

        def _st_draw(self):
            key = (self.pose, self.face, self.frame, self.kind, self.look)
            if key in self.frames:
                self._st_show(self.frames[key])
            elif self.kind == "status" or self.look == "text":
                self._st_show(self._st_text())
            elif self.kind == "head" and self.look == "blocks":
                self.frames[key] = blocks(head(self._st_face(), self.frame, _palette()))
                self._st_show(self.frames[key])
            else:
                self.run_worker(lambda k=key: self._st_make(k), thread=True, group="static-" + str(id(self)),
                                exclusive=False)

        def _st_text(self):
            ascii_ = os.environ.get("BROMIGOS_ICONS") == "ascii"
            g = glyph(self._st_face(), ascii_)
            return g if self.kind == "status" else g + (" STATIC" if self.kind == "figure" else "")

        def _st_make(self, key):
            pal = _palette()
            if self.look == "kitty":
                cw, ch = cell_pixels()
                face = self._st_face()
                crop = "head" if self.kind == "head" else None
                doc = S.svg(self.pose, face=face if self.face else None, frame=self.frame, pal=pal,
                            level="glow", size=int(self.rows * ch), crop=crop)
                png = render_png(doc, height=int(self.rows * ch))
                if png:
                    image_id = Sprite._ids + len(self.sent) + 1 + (id(self) & 0xFF) * 64
                    seq = kitty_transmit(png, image_id, self.cols, self.rows)
                    out = ("kitty", image_id, seq)
                else:
                    out = blocks(head(face, self.frame, pal)) if self.kind == "head" else self._st_text()
            else:
                px = figure(self.pose, self.cols, self.rows, self.frame, pal)
                out = blocks(px) if px else self._st_text()
            self.app.call_from_thread(self._st_landed, key, out)

        def _st_landed(self, key, out):
            self.frames[key] = out
            if key == (self.pose, self.face, self.frame, self.kind, self.look):
                self._st_show(out)

        def _st_show(self, out):
            if isinstance(out, tuple) and out[0] == "kitty":
                _k, image_id, seq = out
                if image_id not in self.sent:
                    try:
                        self.app._driver.write(seq)                         # once per frame: then just cells
                        self.sent.add(image_id)
                    except Exception:                                       # noqa: BLE001
                        self.look = "blocks"
                        return self._st_draw()
                out = kitty_cells(image_id, self.cols, self.rows)
            self.update(out)
