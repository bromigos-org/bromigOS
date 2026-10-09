"""Shared behaviour for the summoned 3D decks (Mind, Ops, Swarm, Network, Replay).

  * one 3D space (painter space 2) you drag to turn; it drifts when left alone;
  * maps that set `zoom = (min, max)` also zoom (zoomcam.py): scroll toward the cursor,
    drag pans while zoomed (Shift+drag or the right button turns), + and - keys,
    double-click empty space or 0 resets; the space is clipped to the panel, and
    `self.cam.z` is there for level of detail in build();
  * picking: subclasses publish pick_pts (model xyz) + pick_ids, hover shows a hint
    line (what it is + what a click does), click selects;
  * the Tab cycle across the decks (decks.py: the live config's [decks] cycle);
  * commands from VECTOR: `bromigos-live <deck> <verb> [args]` lands in command();
  * VECTOR's event feed: self.feed.poll(self.cursor) gives new events, on_event()
    is called for each one at most ~10 times a second.
"""
import math
import threading
import time

import numpy as np

from . import gadgets, glkit
from .glkit import col
from .overlays import Base
from .vfeed import Feed
from .zoomcam import ZoomCam

TAU = 2 * math.pi


def next_deck(kind, cfg=None):
    """The deck Tab opens after `kind` (decks.py), or None when there's no other."""
    from .decks import next_deck as nd
    return nd(kind, cfg)


def ascii_(s, n=None):
    s = "".join(ch if 32 <= ord(ch) < 127 or ch in "·→←↑↓°±×" else "" for ch in str(s or ""))
    s = " ".join(s.split())
    return s[:n] if n else s


def wrap(s, n):
    out, line = [], ""
    for w in str(s).split():
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


class Poller(threading.Thread):
    """Runs fn every `every` seconds while the deck is open (heavy reads only while visible)."""

    def __init__(self, fn, every, name):
        super().__init__(daemon=True, name=name)
        self.fn, self.every = fn, every
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                self.fn()
            except Exception as e:  # keep the last good data; never kill the deck
                print(f"bromigos-live: {self.name}: {str(e)[:160]}", flush=True)
            self.stop.wait(self.every)


class Deck3D(Base):
    rebuild_every = 0.5
    title = "DECK"
    hint = ""
    zoom = None                  # (min, max) to make this deck a zoomable map

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        s = self.h / 1440.0
        self.s = s
        self.L = {"panel": (60 * s, 150 * s, 1660 * s, 1070 * s), "center": (890 * s, 690 * s, 520 * s),
                  "side": (1750 * s, 150 * s, 750 * s, 1070 * s)}
        self.yaw, self.pitch, self.persp = 0.4, 0.55, 3.4
        self.spin = 0.03
        self.drag = None
        self.last_input = -10.0
        self.hover = None
        self.selected = None
        self.sel_t = 0.0
        self.pick_pts = np.zeros((0, 3), np.float32)
        self.pick_ids = []
        self.pick_r = 14
        self.pollers = []
        self.feed = Feed.get()
        self.feed.acquire()
        self.cursor = 0
        self.last_feed = 0.0
        self.toast = None            # (text, t, colour)
        self.pending = list(kw.get("commands") or [])
        self.mods = 0                # modifier state of the last button press (GDK mask)
        self.t_prev = None
        self.cam = ZoomCam(self.map_rect(), self.L["center"][:2], self.L["center"][2], *self.zoom) \
            if self.zoom else None

    # ------------------------------------------------------------------ lifecycle
    def poll_every(self, fn, every, name):
        p = Poller(fn, every, f"{self.name}-{name}")
        self.pollers.append(p)
        p.start()
        return p

    def close(self):
        for p in self.pollers:
            p.stop.set()
        self.feed.release()
        super().close()

    # ------------------------------------------------------------------ subclass hooks
    def on_event(self, e, t):
        pass

    def command(self, verb, args):
        return f"{self.name}: unknown verb {verb}"

    def animate(self, t, d):
        """Per frame, before the transform is set (animation state)."""

    # ------------------------------------------------------------------ frame
    def frame(self, t, d):
        if t - self.last_feed > 0.1:
            self.last_feed = t
            evs, self.cursor = self.feed.poll(self.cursor)
            for e in evs:
                try:
                    self.on_event(e, t)
                except Exception as ex:
                    print("bromigos-live: event", e.get("type"), ex, flush=True)
        while self.pending and t > 0.3:
            verb, args = self.pending.pop(0)
            self.toast = (self.command(verb, args), t, "soft")
            self.built_at = None
        self.animate(t, d)
        p = self.stage.painter
        dt = 0.0 if self.t_prev is None else min(t - self.t_prev, 0.1)
        self.t_prev = t
        # left alone it drifts round, except under reduced motion (live/motion.py): a deck you
        # summoned holds still until you turn it
        if self.drag is None and t - self.last_input > 5.0 and not (self.cam and self.cam.zoomed) \
                and not self.reduced:
            self.yaw += self.spin / 30.0
        cx, cy, R = self.L["center"]
        p.rot[2] = glkit.rot_matrix(self.yaw, self.pitch)
        if self.cam:
            self.cam.c0[:] = (cx, cy)                 # a deck may move its centre after __init__
            self.cam.R, self.cam.rect = R, self.map_rect()
            self.cam.step(dt, p.rot[2], self.persp)
            p.ctr[2] = self.cam.ctr(self.persp)
            p.clip[2] = self.cam.clip()
        else:
            p.ctr[2] = (cx, cy, R, self.persp)
        fade = min(t / 0.25, 1.0)
        if self.closing_at is not None:
            fade = max(0.0, 1.0 - (t - self.closing_at) / 0.25)
        u = {"backdrop": 0.86, "glow": 0.95, "fade": fade}
        u.update(self.extra_uniforms(t, d))
        if self.closing_at is not None and t - self.closing_at > 0.26:
            u["finished"] = True
        return u

    def extra_uniforms(self, t, d):
        return {}

    def render(self, fbo, fps):
        cam = self.cam
        if cam is not None and self.built_at is not None and cam.build_due(self.now()):
            self.built_at = None             # labels and expansion follow the view
        before = self.built_at
        super().render(fbo, fps)
        if cam is not None and self.built_at is not before:
            cam.mark_built(self.built_at)

    # ------------------------------------------------------------------ camera
    def map_rect(self):
        """The panel below its title strip: where a zoomed map draws (and is clipped)."""
        x, y, w, h = self.L["panel"]
        return (x + 4 * self.s, y + 46 * self.s, w - 8 * self.s, h - 50 * self.s)

    def fly_to(self, ident, z):
        """Ease the camera to centre a picked thing (by id, followed while it moves) at zoom z."""
        if not self.cam:
            return

        def where():
            if ident in self.pick_ids:
                return self.pick_pts[self.pick_ids.index(ident)]
            return None
        self.cam.fly_to(where, z)
        self.last_input = self.now()

    # ------------------------------------------------------------------ chrome
    def header(self, b, sub, T=0.05):
        s = self.s
        b.text(self.title, 60 * s, 110 * s, col("soft"), font="l", track=6, reveal=T, type_rate=0.02)
        b.text(sub, self.w - 60 * s, 108 * s, col("dim"), font="xs", track=1.8, align="r", reveal=T + 0.2,
               type_rate=0.004)
        b.line((60 * s, 130 * s), (self.w - 60 * s, 130 * s), col("guard"), reveal=T)
        foot = "DRAG TO TURN · HOVER FOR WHAT IT IS · CLICK TO SELECT · TAB: NEXT DECK · ESC CLOSES"
        if self.cam:
            foot = "SCROLL ZOOMS · DRAG TURNS (PANS WHEN ZOOMED) · HOVER · CLICK SELECTS · TAB: NEXT DECK · ESC CLOSES"
            self.cam.readout(b, self.s, T + 0.4)
        b.text((self.hint + " · " if self.hint else "") + foot, self.w / 2, self.h - 22 * s, col("dim", 0.85),
               font="xs", track=2, align="c", reveal=T + 1.0)
        if self.toast and self.now() - self.toast[1] < 6:
            txt, _, c = self.toast
            b.plate(self.w / 2 - 420 * s, 140 * s, 840 * s, 34 * s, 0.9)
            b.text("VECTOR · " + ascii_(txt, 80).upper(), self.w / 2, 163 * s, col(c), font="s", track=1.5,
                   align="c")

    def hover_tip(self, b, label, lines, hint="CLICK TO SELECT"):
        """The hover readout: what it is, its live values, what a click does."""
        if self.hover is None or not len(self.pick_pts):
            return
        try:
            i = self.pick_ids.index(self.hover)
        except ValueError:
            return
        s = self.s
        p = self.stage.painter
        x, y, _ = glkit.project(self.pick_pts[i:i + 1], p.rot[2], p.ctr[2])[0]
        rows = [ascii_(label, 48).upper()] + [ascii_(l, 56).upper() for l in lines[:4]] + [hint]
        w = max(len(r) for r in rows) * 10.5 * s + 32 * s
        h = (len(rows) * 21 + 18) * s
        bx = min(x + 24 * s, self.w - w - 20 * s)
        by = max(y - h - 12 * s, 150 * s)
        b.plate(bx, by, w, h, 0.93)
        b.brackets(bx, by, w, h, col("soft"), l=8)
        for k, r in enumerate(rows):
            c = "white" if k == 0 else ("dim" if k == len(rows) - 1 else "soft")
            b.text(r, bx + 14 * s, by + 26 * s + k * 21 * s, col(c), font="xs" if k else "s", track=1)

    # ------------------------------------------------------------------ input
    def pick(self, x, y):
        if not len(self.pick_pts):
            return None
        p = self.stage.painter
        pr = glkit.project(self.pick_pts, p.rot[2], p.ctr[2])
        dd = np.hypot(pr[:, 0] - x, pr[:, 1] - y) + pr[:, 2] * 4
        i = int(np.argmin(dd))
        return self.pick_ids[i] if dd[i] < self.pick_r * self.s + 4 else None

    def in_panel(self, x, y):
        x0, y0, w, h = self.L["panel"]
        return x0 <= x <= x0 + w and y0 <= y <= y0 + h

    def drag_mode(self, button):
        """What a drag does: turn, or pan when zoomed in; Shift or the other button swaps them."""
        if not self.cam:
            return "turn"
        pan = self.cam.zoomed
        if self.mods & 1:                     # GDK_SHIFT_MASK
            pan = not pan
        if button == 3:
            pan = False
        elif button == 2:
            pan = True
        return "pan" if pan else "turn"

    def click(self, x, y, button):
        self.last_input = self.now()
        if self.in_panel(x, y):
            self.drag = (x, y, self.yaw, self.pitch, False, self.drag_mode(button), x, y)
            return True
        if self.side_click(x, y):
            self.built_at = None
            return True
        sx, sy, sw, sh = self.L["side"]
        if not (sx <= x <= sx + sw and sy <= y <= sy + sh):
            self.close()
        return True

    def side_click(self, x, y):
        return False

    def motion(self, x, y, buttons):
        self.last_input = self.now()
        if self.drag:
            x0, y0, yaw, pitch, moved, mode, lx, ly = self.drag
            moved = moved or abs(x - x0) + abs(y - y0) > 4
            if mode == "pan":
                self.cam.pan_by(x - lx, y - ly)
            else:
                self.yaw = yaw + (x - x0) * 0.007
                self.pitch = max(0.05, min(1.45, pitch + (y - y0) * 0.005))
            self.drag = (x0, y0, yaw, pitch, moved, mode, x, y)
            if moved and self.hover is not None:
                self.hover = None
                self.built_at = None
            return
        h = self.pick(x, y) if self.in_panel(x, y) else None
        if h != self.hover:
            self.hover = h
            self.built_at = None

    def release(self, x, y):
        if self.drag and not self.drag[4]:
            n = self.pick(x, y)
            self.select(None if n == self.selected else n)
        self.drag = None

    def scroll(self, x, y, dy):
        """Scroll wheel or touchpad (smooth deltas): zoom toward the cursor."""
        if not self.cam or not self.in_panel(x, y):
            return False
        self.last_input = self.now()
        self.cam.wheel(x, y, dy)
        return True

    def dclick(self, x, y):
        """Double-click on empty space resets the view."""
        if self.cam and self.in_panel(x, y) and self.pick(x, y) is None:
            self.cam.reset()
            self.last_input = self.now()

    def select(self, ident):
        self.selected = ident
        self.sel_t = self.now() + 0.01
        self.built_at = None

    def key(self, name):
        self.last_input = self.now()
        if name in ("Escape", "q"):
            self.close()
        elif name == "Tab" and self.app:
            nxt = next_deck(self.name, self.cfg)
            if nxt:
                self.close()
                from gi.repository import GLib
                GLib.timeout_add(300, lambda: (self.app.overlay(nxt), False)[1])
        elif name in ("Left", "h"):
            self.yaw -= 0.2
        elif name in ("Right", "l"):
            self.yaw += 0.2
        elif self.cam and name in ("plus", "equal", "KP_Add"):
            self.cam.key_zoom(+1)
        elif self.cam and name in ("minus", "KP_Subtract"):
            self.cam.key_zoom(-1)
        elif self.cam and name in ("0", "KP_0", "Home"):
            self.cam.reset()
        else:
            return self.extra_key(name)
        return True

    def extra_key(self, name):
        return True


def frame_panel(b, x, y, w, h, title, T, sub=None):
    gadgets.frame(b, x, y, w, h, title, T, sub=sub)
