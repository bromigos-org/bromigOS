"""__TITLE__: a live-layer deck (made by `bromigos ext new live-deck`; docs/extensions.md).

Open it with `bromigos-live plugin __NAME__`; Esc closes it. A deck is a full-screen
hologram built on deckkit (live/deckkit.py): a poller samples data off the render
thread, build() draws the scene from it (again every `rebuild_every` seconds), and
picking (pick_pts + pick_ids) gives the hover hint and the click. This one shows the
machine's load averages; replace _sample() and build() with your own.

Render it without a window (from a bromigOS checkout, with the extension installed):
    python live/tools/offscreen.py plugin:__NAME__ OUT.png 2
"""
import os

import numpy as np

from live.deckkit import TAU, Deck3D, frame_panel
from live.glkit import col

CPUS = os.cpu_count() or 1
# where each reading sits in the deck's 3D space (x, y, z; about -1..1)
SPOTS = {"1 MIN": (-0.7, 0.0, 0.0), "5 MIN": (0.0, 0.0, 0.0), "15 MIN": (0.7, 0.0, 0.0)}


class __CAMEL__Deck(Deck3D):
    name = "__NAME__"
    title = "__UPPER__ // LOAD"
    hint = "A STARTER DECK: EDIT deck.py"
    rebuild_every = 1.0

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.load = (0.0, 0.0, 0.0)
        self.ready_ = False
        self.poll_every(self._sample, 2.0, "load")

    def _sample(self):
        """Runs on a poller thread: fetch here, never draw."""
        self.load = os.getloadavg()
        self.ready_ = True

    def ready(self):
        return self.ready_

    def build(self, b, d, t):
        s, T = self.s, 0.05
        self.header(b, f"THIS MACHINE'S LOAD AVERAGE · {CPUS} CPUS · A STARTER DECK")
        x, y, w, h = self.L["panel"]
        frame_panel(b, x, y, w, h, "LOAD AVERAGE", T + 0.05, sub="1 · 5 · 15 MINUTES")
        for (label, c), v in zip(SPOTS.items(), self.load):
            frac = min(v / CPUS, 1.0)
            tone = "danger" if frac > 0.9 else "amber" if frac > 0.7 else "soft"
            b.arc(c, 0, 6 * s, 0, TAU, col("white"), kind=2, space=2, reveal=T + 0.2)
            b.arc(c, 70 * s, 72 * s, 0, TAU, col("dim", 0.8), segs=24, gap=0.3, spin=0.05, space=2,
                  reveal=T + 0.3)
            b.arc(c, 78 * s, 90 * s, 0, TAU * max(frac, 0.01), col(tone), space=2, reveal=T + 0.4)
            b.text(label, *c[:2], col("soft"), font="s", track=2, space=2, z=c[2], dx=-24 * s, dy=-110 * s,
                   reveal=T + 0.4)
            b.text(f"{v:.2f}", *c[:2], col(tone), font="l", track=1, space=2, z=c[2], dx=-30 * s, dy=130 * s,
                   reveal=T + 0.5)
        self.pick_pts = np.array(list(SPOTS.values()), np.float32)
        self.pick_ids = list(SPOTS)
        if self.hover in self.pick_ids:
            v = self.load[self.pick_ids.index(self.hover)]
            self.hover_tip(b, f"LOAD · {self.hover}", [f"{v:.2f} RUNNABLE TASKS", f"{CPUS} CPUS"],
                           "CLICK TO SELECT")

    def command(self, verb, args):
        """`bromigos-live plugin __NAME__ <verb> [args]` (and VECTOR) land here."""
        if verb == "ping":
            return "__NAME__: pong"
        return f"__NAME__: unknown verb {verb}"


DECK = __CAMEL__Deck
