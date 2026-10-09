"""FIELD NOTES as a floating panel inside the holo deck (N toggles it).

Type to search, Up/Down to pick an entry, Enter or a click opens the first
link chip, Esc clears the search and then closes the panel. The GTK notes
panel stays the place to write; this is the place to find."""
import os
import shlex
import subprocess
import time

from . import notes
from .glkit import col


def _ascii(s):
    return "".join(ch if 32 <= ord(ch) < 127 or ch in "·→°" else "?" for ch in s)


def _wrap(s, n):
    out, line = [], ""
    for w in s.split():
        while len(w) > n:
            out.append(w[:n])
            w = w[n:]
        if len(line) + len(w) + 1 > n:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


class NotesPanel:
    def __init__(self, deck):
        self.deck = deck
        self.on = False
        self.query = ""
        self.sel = 0
        self.entries, self.mtime = notes.load()
        self.hits = notes.search(self.entries, "")
        self.chips = []
        self.rows = []
        self.opened_t = 0.0

    def refresh(self):
        try:
            m = os.path.getmtime(notes.NOTES)
        except OSError:
            m = 0.0
        if m != self.mtime:
            self.entries, self.mtime = notes.load()
            self._filter()

    def _filter(self):
        self.hits = notes.search(self.entries, self.query)
        self.sel = min(self.sel, max(len(self.hits) - 1, 0))

    def toggle(self):
        self.on = not self.on
        self.opened_t = self.deck.now() + 0.01
        self.refresh()

    def rect(self):
        s = self.deck.s
        return (560 * s, 200 * s, 1440 * s, 920 * s)

    # ------------------------------------------------------------------ draw
    def draw(self, b, d):
        from . import gadgets
        self.refresh()
        s = self.deck.s
        x, y, w, h = self.rect()
        T = self.opened_t
        b.plate(x - 6, y - 6, w + 12, h + 12, 0.96)
        gadgets.frame(b, x, y, w, h, "FIELD NOTES", T, sub=f"{len(self.entries)} ENTRIES · ~/.local/share/bromigos/notes.md")
        # search box
        caret = "_" if int(time.monotonic() * 2) % 2 == 0 else " "
        b.rect(x + 18 * s, y + 52 * s, w - 36 * s, 36 * s, col("dim", 0.9), reveal=T + 0.1)
        b.text("SEARCH", x + 30 * s, y + 76 * s, col("dim"), font="xs", track=3, reveal=T + 0.1)
        b.text(_ascii(self.query.upper()) + caret, x + 120 * s, y + 77 * s, col("white"), font="s", track=1,
               reveal=T + 0.15)
        b.text(f"{len(self.hits)} MATCH" + ("" if len(self.hits) == 1 else "ES"), x + w - 30 * s, y + 76 * s,
               col("soft"), font="xs", track=2, align="r", reveal=T + 0.15)
        # entry list
        lx, ly, lw = x + 18 * s, y + 112 * s, 470 * s
        self.rows = []
        if not self.entries:
            b.text("NO NOTES YET · ALT+SHIFT+N ADDS ONE", lx, ly + 20 * s, col("dim"), font="xs", track=2)
        first = max(0, self.sel - 20)
        for k, i in enumerate(self.hits[first:first + 30]):
            e = self.entries[i]
            yy = ly + k * 30 * s
            if yy > y + h - 40 * s:
                break
            on = (first + k) == self.sel
            if on:
                b.plate(lx - 6, yy - 21 * s, lw, 28 * s, 0.9)
                b.rect(lx - 6, yy - 21 * s, lw, 28 * s, col("soft", 0.9))
            label = (e["when"][5:] + "  " if e["when"] else "") + e["title"]
            b.text(_ascii(label.upper())[:38], lx, yy, col("white" if on else "soft", 1.0 if on else 0.85), font="s",
                   track=0.8, reveal=T + 0.2 + k * 0.01)
            self.rows.append((lx - 6, yy - 21 * s, lw, 28 * s, first + k))
        b.line((x + 500 * s, y + 108 * s), (x + 500 * s, y + h - 20 * s), col("guard"), reveal=T + 0.2)
        # the entry
        cx, cy = x + 524 * s, y + 124 * s
        self.chips = []
        if not self.hits:
            b.text("NOTHING MATCHES", cx, cy + 10 * s, col("amber"), font="s", track=2)
            return
        e = self.entries[self.hits[self.sel]]
        b.text(_ascii(e["title"].upper())[:50], cx, cy + 8 * s, col("white"), font="l", track=1.0, reveal=T + 0.25,
               type_rate=0.004)
        if e["when"]:
            b.text(e["when"], cx, cy + 36 * s, col("dim"), font="s", track=2, reveal=T + 0.3)
        yy = cy + 72 * s
        q = [w for w in self.query.lower().split() if w]
        for para in e["body"]:
            for ln in _wrap(_ascii(para), 62) or [""]:
                if yy > y + h - 110 * s:
                    break
                hit = any(w in ln.lower() for w in q)
                b.text(ln, cx, yy, col("amber" if hit else "soft", 0.95), font="m", track=0.3, reveal=T + 0.3,
                       type_rate=0.001)
                yy += 27 * s
        # links to what the entry mentions
        cl = (d.get("cluster") or {})
        services = list((cl.get("services") or {}).keys())
        nodes_ = [n.get("name") for n in cl.get("nodes") or [] if n.get("name")]
        lk = notes.links(e, services, nodes_, self.deck.cfg.get("radial", {}).get("items") or [])
        bx, by = cx, y + h - 64 * s
        if lk:
            b.text("LINKS", bx, by - 12 * s, col("dim"), font="xs", track=3, reveal=T + 0.4)
            for label, url in lk:
                cw = (len(label) * 11 + 34) * s
                b.plate(bx, by, cw, 30 * s, 0.9)
                b.rect(bx, by, cw, 30 * s, col("soft", 0.9), reveal=T + 0.45)
                b.text(_ascii(label) + " →", bx + 12 * s, by + 21 * s, col("soft"), font="xs", track=1.2,
                       reveal=T + 0.45)
                self.chips.append((bx, by, cw, 30 * s, url))
                bx += cw + 12 * s
        b.text("TYPE TO SEARCH · ↑↓ PICK · ENTER OPENS THE FIRST LINK · ESC CLEARS / CLOSES", x + w / 2,
               y + h - 14 * s, col("dim", 0.85), font="xs", track=1.5, align="c", reveal=T + 0.5)

    # ------------------------------------------------------------------ input
    def open_url(self, url):
        browser = self.deck.cfg.get("radial", {}).get("browser", "xdg-open")
        try:
            subprocess.Popen(shlex.split(browser) + [url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            pass

    def key(self, name, ch):
        if name == "Escape":
            if self.query:
                self.query = ""
                self._filter()
            else:
                self.on = False
        elif name == "BackSpace":
            self.query = self.query[:-1]
            self._filter()
        elif name in ("Up", "KP_Up"):
            self.sel = max(0, self.sel - 1)
        elif name in ("Down", "KP_Down"):
            self.sel = min(len(self.hits) - 1, self.sel + 1) if self.hits else 0
        elif name in ("Return", "KP_Enter"):
            if self.chips:
                self.open_url(self.chips[0][4])
        elif ch and ch.isprintable() and len(self.query) < 60:
            self.query += ch
            self.sel = 0
            self._filter()
        return True

    def click(self, x, y):
        for (cx, cy, cw, chh, url) in self.chips:
            if cx <= x <= cx + cw and cy <= y <= cy + chh:
                self.open_url(url)
                return True
        for (rx, ry, rw, rh, i) in self.rows:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                self.sel = i
                return True
        x0, y0, w, h = self.rect()
        return x0 <= x <= x0 + w and y0 <= y <= y0 + h
