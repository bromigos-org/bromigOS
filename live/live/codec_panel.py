"""The codec call panel: a compact transmission card in the corner — channel
glyph, tuning dial with the channel readout, the voice's real amplitude as a
codec waveform, and the message typed in step with the voice."""
import math

from .codec import CHANNELS
from .glkit import col
from .overlays import Base

TAU = 2 * math.pi
PANEL = (820, 236)


class CodecPanel(Base):
    name = "codec"
    rebuild_every = 1 / 30

    def __init__(self, *a, call=None, desk=None, **kw):
        super().__init__(*a, **kw)
        self.call = call
        self.desk = desk
        self.s = self.h / PANEL[1]
        self.ready_at = None
        self.end_at = None

    play_t = None

    def _state(self, t):
        c = self.call
        if self.play_t is None and c.ready.is_set() and t > 0.7:
            self.play_t = t
            if self.desk:
                self.desk.play(c)
        if self.play_t is None:
            return "tuning", 0.0
        el = t - self.play_t
        if el > c.duration + 1.6:
            return "over", el
        return "live", el

    def build(self, b, d, t):
        s = self.s
        W, H = self.w, self.h
        c = self.call
        ch, name = CHANNELS.get(c.channel, ("CH --", c.channel))
        state, el = self._state(t)
        b.plate(0, 0, W, H, 0.9)
        rv = 0.02
        b.rect(1, 1, W - 2, H - 2, col("dim", 0.9), reveal=rv)
        b.brackets(4, 4, W - 8, H - 8, col("soft"), l=14 * s, width=1.5, reveal=rv + 0.05)
        # channel glyph
        gx, gy, gr = 104 * s, H / 2 + 6 * s, 62 * s
        b.arc((gx, gy), gr - 2, gr, 0, TAU, col("dim", 0.9), reveal=rv + 0.1)
        b.arc((gx, gy), gr - 14 * s, gr - 9 * s, 0, TAU, col("soft", 0.85), segs=24, gap=0.45, spin=-0.4,
              reveal=rv + 0.15)
        live = state == "live"
        lvl = self._level(el) if live else 0.0
        b.arc((gx, gy), 0, (10 + 26 * lvl) * s, 0, TAU, col("soft", 0.5 + 0.5 * lvl), kind=2, reveal=rv + 0.2)
        b.text(ch, gx, gy - gr - 12 * s, col("soft"), font="m", track=2, align="c", reveal=rv + 0.2)
        b.text(name, gx, gy + gr + 22 * s, col("phosphor"), font="xs", track=2, align="c", reveal=rv + 0.25)
        # header + tuning dial
        x0 = 196 * s
        blink = (int(t * 2.5) % 2 == 0)
        head = {"tuning": "INCOMING · TUNING" + ("…" if blink else ""), "live": "TRANSMISSION · LIVE",
                "over": "TRANSMISSION · OVER"}[state]
        b.text(head, x0, 34 * s, col("amber" if state == "tuning" else "soft"), font="s", track=3, reveal=rv + 0.2,
               type_rate=0.01)
        dx0, dx1, dy = W - 300 * s, W - 26 * s, 30 * s
        b.line((dx0, dy), (dx1, dy), col("dim"), reveal=rv + 0.2)
        for k in range(29):
            x = dx0 + (dx1 - dx0) * k / 28
            hgt = (9 if k % 7 == 0 else 4) * s
            b.line((x, dy - hgt), (x, dy), col("dim", 0.9), reveal=rv + 0.25)
        target = 0.18 + 0.64 * (list(CHANNELS).index(c.channel) / max(len(CHANNELS) - 1, 1)) \
            if c.channel in CHANNELS else 0.5
        settle = min(t / 1.1, 1.0)
        pos = target + (1 - settle) * 0.35 * math.sin(t * 9.0) * (1 - settle)
        nx = dx0 + (dx1 - dx0) * pos
        b.line((nx, dy - 14 * s), (nx, dy + 8 * s), col("amber"), width=2.0, reveal=rv + 0.3)
        b.text(f"BAND 140 · {ch}", dx1, dy + 26 * s, col("soft"), font="xs", track=2, align="r", reveal=rv + 0.3)
        # waveform: the voice's real envelope, newest at the right
        wx0, wx1, wy, wh = x0, W - 26 * s, 112 * s, 44 * s
        b.line((wx0, wy), (wx1, wy), col("guard"), reveal=rv + 0.3)
        n = 64
        env = c.env
        fps = 60.0
        for k in range(n):
            x = wx0 + (wx1 - wx0) * (k + 0.5) / n
            if live and env is not None and len(env):
                fi = int((el - (n - 1 - k) * 0.03) * fps)
                a = float(env[fi]) if 0 <= fi < len(env) else 0.0
                a = a * (0.75 + 0.25 * math.sin(k * 1.7 + t * 23.0))
            else:
                a = 0.04 + 0.03 * math.sin(k * 0.9 + t * 6.0)
            hh = max(1.0, a * wh)
            cc = col("soft" if live else "dim", 0.95 if live else 0.7)
            b.line((x, wy - hh), (x, wy + hh), cc, width=max(2.0, (wx1 - wx0) / n * 0.55))
        # the message, typed in step with the voice
        txt = c.text.upper()
        if state == "tuning":
            shown = ""
        elif c.wav and c.env is not None:
            span = max(c.voice_end - c.voice_at, 0.5)
            k = max(0.0, min(1.0, (el - c.voice_at) / span))
            shown = txt[:int(len(txt) * k + 0.999)]
        else:
            shown = txt[:int(len(txt) * min(el / max(len(txt) * 0.03, 0.5), 1.0) + 0.999)]
        # the whole message stays readable; what has been said brightens (karaoke)
        lines, line = [], ""
        for w in txt.split(" "):
            if len(line) + len(w) + 1 > 52:
                lines.append(line)
                line = w
            else:
                line = (line + " " + w).strip()
        lines.append(line)
        if state != "tuning":
            done = len(shown)
            for i, ln in enumerate(lines[:3]):
                y = 184 * s + i * 21 * s
                b.text(ln, x0, y, col("soft", 0.5), font="s", track=0.8)
                k = min(max(done, 0), len(ln))
                if k:
                    b.text(ln[:k], x0, y, col("white"), font="s", track=0.8)
                done -= len(ln) + 1

    def _level(self, el):
        env = self.call.env
        if env is None or not len(env):
            return 0.3 + 0.2 * math.sin(el * 11.0)
        i = int(el * 60.0)
        return float(env[i]) if 0 <= i < len(env) else 0.0

    def frame(self, t, d):
        state, el = self._state(t)
        fade = min(t / 0.2, 1.0)
        if state == "over" and self.end_at is None:
            self.end_at = t
        if self.closing_at is not None and self.end_at is None:
            self.end_at = t
        if not self.call.ready.is_set() and t > 45:
            self.call.ready.set()
        if self.end_at is not None:
            fade = max(0.0, 1.0 - (t - self.end_at) / 0.4)
        u = {"backdrop": 0.0, "glow": 0.8, "fade": fade}
        if t < 0.18 and not self.reduced:      # a short interference burst as the line opens
            u["tear"] = 1.0 - t / 0.18
            u["tear_band"] = (0.0, float(self.h), 1.0, 0.0)
        if self.end_at is not None and t - self.end_at > 0.42:
            u["finished"] = True
            if self.desk:
                self.desk.done(self.call)
                self.desk = None
        return u
