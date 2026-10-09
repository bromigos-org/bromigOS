"""Event overlays and summoned gadgets, each a short-lived layer-shell surface.

  intercept     login/unlock: the burn-in's canonical intercept sequence
  transmission  critical notification: interference + targeting brackets
  screensaver   idle: the live scene full screen, ends on any input
  holodeck      SUPER+H: arc rings, cluster constellation, machine hologram
  radial        SUPER+A: holographic quick-launch ring

Renderers are separate from windows so tools/offscreen.py can drive them.
"""
import math
import os
import shlex
import subprocess
import time

import numpy as np
from OpenGL import GL

from . import gadgets, glkit, motion
from .emblem import Emblem
from .glkit import col
from .stage import Stage

TAU = 2 * math.pi


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


_NO_SHIPS = np.zeros((10, 4), dtype=np.float32)


class Base:
    """Shared overlay renderer: emissive batch + bloom + ov.frag + emblem pass."""
    name = "base"
    rebuild_every = 1.0
    emblem_kit = None          # the current theme's emblem (a post's own mark); a path pins one

    def __init__(self, cfg, data, w, h, app=None, **kw):
        self.cfg, self.data, self.w, self.h, self.app = cfg, data, w, h, app
        self.st = data.static
        self.stage = Stage(w, h, "ov.frag")
        self.emblem = Emblem(1024, 128, kit_dir=self.emblem_kit)
        self.t0 = time.monotonic()
        self.built_at = None
        self.frozen = None
        self.closing_at = None
        self.done = False
        # reduced motion (live/motion.py): `reduced` is any calm mode (reduced or still).
        # Not `self.motion`: that's the pointer handler every overlay has (motion(x, y,
        # buttons)); an attribute of that name made each pointer movement a TypeError, so a
        # mouse movement no longer ended the screensaver
        self.motion_mode = motion.mode(cfg)
        self.reduced = self.motion_mode != "full"
        self.still = self.motion_mode == "still"
        self.kw = kw

    def now(self):
        return time.monotonic() - self.t0

    # subclasses
    def build(self, b, d, t):
        pass

    def frame(self, t, d):
        """Per-frame uniform state: dict for ov.frag, plus emblem calls list."""
        return {}

    def rebuild_due(self, t):
        return self.built_at is None or t - self.built_at >= self.rebuild_every

    def shader_time(self, t):
        """The time the shaders and the gadgets' motion see (reveals, spins, rain, stars):
        the overlay's own by default; the screensaver slows or stills it."""
        return t

    def render(self, fbo, fps):
        t = self.now()
        ts = self.shader_time(t)
        d = self.data.snapshot()
        if self.rebuild_due(t) or getattr(self, "theme_seen", None) != glkit.T.version():
            self.theme_seen = glkit.T.version()        # a theme switch recolours it at once
            b = glkit.Batch(self.stage.atlas)
            self.build(b, d, t)
            self.stage.painter.upload(b)
            self.built_at = t
        u = self.frame(t, d)
        st = self.stage
        st.begin_emit()
        st.painter.draw((float(self.w), float(self.h)), ts, {"fade": u.get("gadget_fade", 1.0)})
        extra = getattr(self, "emit_extra", None)
        if extra:
            extra(t, u)
        p2 = getattr(self, "p2", None)
        if p2 is not None and getattr(self, "p2_on", False):
            # a second layer that occludes: its plates first darken what is already drawn,
            # then its lines and text draw on top
            p2.rot[:] = st.painter.rot
            p2.ctr[:] = st.painter.ctr
            p2.clip[:] = st.painter.clip
            GL.glBlendFuncSeparate(GL.GL_ZERO, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ONE, GL.GL_ONE)
            p2.draw((float(self.w), float(self.h)), t, {"fade": u.get("fade", 1.0)}, which=("arcs",))
            GL.glBlendFuncSeparate(GL.GL_ONE, GL.GL_ONE, GL.GL_ONE, GL.GL_ONE)
            p2.draw((float(self.w), float(self.h)), t, {"fade": 1.0})
        for e in u.get("emblems", []):
            if e.get("bloom", True):
                st.draw_emblem(self.emblem, e["rect"], e.get("angle", 0.0), e.get("ring_t", 1.0), e.get("flame_t", 1.0),
                               e.get("mast_t", 1.0), e.get("alpha", 1.0) * 0.6, e.get("gain", 1.0), emissive=True,
                               small=e.get("small", False))
        bloom = st.bloom(1.0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
        GL.glViewport(0, 0, self.w, self.h)
        GL.glDisable(GL.GL_BLEND)
        f = st.final
        f.use()
        for i, (name, tex) in enumerate((("u_emit", st.emit.tex), ("u_bloom", bloom),
                                         ("u_frozen", self.frozen or st.emit.tex))):
            GL.glActiveTexture(GL.GL_TEXTURE0 + i)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            f.i(name, i)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        f.f("u_res", float(self.w), float(self.h))
        f.f("u_time", ts)
        f.f("u_calm", 1.0 if self.reduced else 0.0)
        f.f("u_backdrop", u.get("backdrop", 0.0))
        f.f("u_frozen_amt", u.get("frozen", 0.0) if self.frozen else 0.0)
        f.f("u_tear", u.get("tear", 0.0))
        f.f("u_tear_band", *u.get("tear_band", (0.0, 0.0, 0.0, 0.0)))
        f.f("u_glow", u.get("glow", 0.9))
        f.f("u_fade", u.get("fade", 1.0))
        f.f("u_rain_rect", *u.get("rain_rect", (0.0, 0.0, float(self.w), float(self.h))))
        f.f("u_rain", *u.get("rain", (0.0, 0.0, 0.0, 0.0)))
        f.fv("u_burst", np.zeros((6, 4), dtype=np.float32), 4)
        f.f("u_grid", *u.get("grid", (0.0, 0.0, 0.0, 0.0)))
        f.f("u_edge", *u.get("edge", (0.0, 0.0, 0.0, 0.0)))
        f.f("u_vignette", *u.get("vignette", (0.0, 0.0, 1.0, 0.0)))
        f.f("u_tear_style", u.get("tear_style", 0.0))
        f.f("u_space", *u.get("space", (0.0, -1.0, 0.0, 0.0)))
        ships = u.get("ships") or (_NO_SHIPS, _NO_SHIPS)
        f.fv("u_ship", ships[0], 4)
        f.fv("u_ship2", ships[1], 4)
        f.f("u_ship_rect", *u.get("space_rect", (0.0, 0.0, float(self.w), float(self.h))))
        f.f("u_space_rect", *u.get("space_rect", (0.0, 0.0, float(self.w), float(self.h))))
        f.f("u_planet", *u.get("planet", (0.0, 0.0, 1.0, 0.0)))
        f.f("u_sun", *u.get("sun", (0.0, 0.0, 0.0, 0.0)))
        f.f("u_beam", *u.get("beam", (0.0, 0.0, 0.0, 0.0)))
        st.fs.draw()
        post = getattr(self, "post_composite", None)
        if post:
            post(u)
        if u.get("emblems"):
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
            for e in u["emblems"]:
                st.draw_emblem(self.emblem, e["rect"], e.get("angle", 0.0), e.get("ring_t", 1.0), e.get("flame_t", 1.0),
                               e.get("mast_t", 1.0), e.get("alpha", 1.0) * u.get("fade", 1.0), e.get("gain", 1.0),
                               small=e.get("small", False))
            GL.glDisable(GL.GL_BLEND)
        if u.get("finished"):
            self.done = True

    # input (windows forward these; offscreen never calls them)
    def key(self, name):
        return False

    def click(self, x, y, button):
        return False

    def motion(self, x, y, buttons):
        pass

    def release(self, x, y):
        pass

    def close(self):
        if self.closing_at is None:
            self.closing_at = self.now()


# ======================================================================== intercept
TEAR_STYLES = {"scanlines": 0.0, "ripple": 1.0, "swell": 2.0}


def tear_style():
    """The theme's intercept static (theme.toml [intercept] static = "ripple" | "swell"; the
    Wick's scanline tears when it says nothing)."""
    import tomllib
    path = os.path.join(os.path.dirname(glkit.T.PATH), "theme.toml")
    try:
        with open(path, "rb") as f:
            name = tomllib.load(f).get("intercept", {}).get("static", "scanlines")
    except (OSError, ValueError):
        name = "scanlines"
    return TEAR_STYLES.get(name, 0.0)


class Intercept(Base):
    """Hold - tear - ring - flame - turn - sign-off - ghost (the burn-in spec)."""
    name = "intercept"
    rebuild_every = 1e9
    HOLD, TEAR, RING, FLAME = 0.25, 0.40, 0.50, 0.40
    CAPTION = "TRANSMISSION INTERCEPTED"
    SIGN = "STILL LIT."

    def __init__(self, *a, frozen_rgb=None, sound=None, **kw):
        super().__init__(*a, **kw)
        self.sound = sound
        if frozen_rgb is not None:
            fh, fw = frozen_rgb.shape[:2]
            self.frozen = glkit.texture_rgba(frozen_rgb, fw, fh, GL.GL_RGB)
        t = 0.0
        self.t_tear = t + self.HOLD
        self.t_ring = self.t_tear + self.TEAR
        self.t_flame = self.t_ring + self.RING
        self.t_turn = self.t_flame + self.FLAME
        self.t_sign = self.t_turn + 0.12 + len(self.CAPTION) * 0.028 + 0.25
        self.t_cut = self.t_sign + len(self.SIGN) * 0.045 + 0.45
        self.t_end = self.t_cut + 3.0
        self.cued = set()
        self.skip_to = None
        self.lines = self._syslines()
        self.style = tear_style()

    def _syslines(self):
        st, d = self.st, self.data.snapshot()
        out = [f"{st['sys'].upper()} {st['kernel']} {st['arch']}", f"CPU {st['cpu_model'].upper()}",
               f"GPU {st['gpu_name'].upper()}"]
        for m in (d.get("mounts") or [])[:6]:
            out.append(f"MNT {m['mount']:<22} {m['fs']:<6} {m['pct']:>3.0f}%")
        try:
            r = subprocess.run(["systemctl", "--user", "list-units", "--type=service", "--state=running",
                                "--no-legend", "--plain"], capture_output=True, text=True, timeout=2)
            for line in r.stdout.splitlines()[:7]:
                out.append("SVC " + line.split()[0].upper())
        except Exception:
            pass
        try:
            with open("/proc/sys/kernel/random/boot_id") as f:
                hexs = f.read().strip().replace("-", "").upper()
            for i in range(0, 32, 8):
                out.insert(2 + i // 8 * 3, f"0x{i:04X}  {hexs[i:i + 8]}  {hexs[::-1][i:i + 8]}")
        except OSError:
            pass
        return out

    def build(self, b, d, t):
        cx, cy = self.w / 2, self.h / 2 - 40
        D = self.h * 0.52
        y = cy + D / 2 + 70
        if self.still:
            # still (reduced motion): the finished card, faded in and out whole; no typing
            b.text(self.CAPTION, cx, y, col("soft"), font="cap", track=6, align="c")
            b.text(self.SIGN, cx, y + 44, col("phosphor"), font="cap", track=8, align="c")
            return
        b.text(self.CAPTION, cx, y, col("soft"), font="cap", track=6, align="c",
               reveal=self.t0_abs(self.t_turn + 0.12), type_rate=0.028)
        b.text(self.SIGN, cx, y + 44, col("phosphor"), font="cap", track=8, align="c",
               reveal=self.t0_abs(self.t_sign), type_rate=0.045)
        # the boot-log tuck: real system lines, scrolling faint at the left
        for i, line in enumerate(self.lines):
            b.text(line, 70, 130 + i * 26, col("phosphor", 0.75), font="s", track=1.2,
                   reveal=self.t0_abs(self.t_tear + 0.1 + i * 0.07), type_rate=0.004, flash=0.5)

    def t0_abs(self, tl):
        return max(tl, 1e-3)

    def skip(self):
        if self.skip_to is None and self.now() < self.t_cut:
            self.skip_to = self.now()

    def key(self, name):
        self.skip()
        return True

    def click(self, x, y, button):
        self.skip()
        return True

    def cue(self, name, t, at):
        if t >= at and name not in self.cued:
            self.cued.add(name)
            if self.sound:
                self.sound.play(name)

    def frame(self, t, d):
        if self.skip_to is not None:      # skipping: jump straight to the cut
            t = self.t_cut + (t - self.skip_to)
        cx, cy = self.w / 2, self.h / 2 - 40
        D = self.h * 0.52
        rect = (cx - D / 2, cy - D / 2, D, D)
        self.cue("hiss", t, 0.0)
        self.cue("sweep", t, self.t_ring)
        self.cue("signoff", t, self.t_sign)
        u = {"glow": 1.0}
        if t >= self.t_end:
            return {"finished": True, "backdrop": 0.0, "fade": 0.0}
        if self.still:
            return self._still_frame(t, rect)
        if self.reduced and t >= self.t_cut:      # reduced motion: no black frame; the card fades out
            k = min(1.0, (t - self.t_cut) / self.CALM_OUT)
            if k >= 1.0:
                return {"finished": True, "backdrop": 0.0, "fade": 0.0}
            u.update(backdrop=1.0 - k, gadget_fade=1.0 - k, glow=0.6 * (1.0 - k),
                     emblems=[{"rect": rect, "angle": 0.0, "alpha": 1.0 - k}])
            return u
        if t >= self.t_cut:                       # one frame of black, then the ghost
            k = (t - self.t_cut)
            if k < 1 / 30:
                return {"backdrop": 1.0, "gadget_fade": 0.0}
            ghost = 0.15 * (1 - (k / 3.0))
            u.update(backdrop=0.0, gadget_fade=0.0, glow=0.0,
                     emblems=[{"rect": rect, "angle": -(t - self.t_turn) * TAU / 24 * (0 if self.reduced else 1),
                               "alpha": max(ghost, 0.0), "bloom": False}])
            return u
        # hold + tear: the captured frame
        if t < self.t_ring:
            tear = 0.0 if (t < self.t_tear or self.reduced) else min((t - self.t_tear) / self.TEAR * 1.6, 1.0)
            fz = 1.0 if t < self.t_ring - 0.12 else (self.t_ring - t) / 0.12
            u.update(backdrop=1.0, frozen=fz, tear=tear, tear_style=self.style)
            if self.reduced:                      # a slow crossfade from the frozen screen, no static
                u["frozen"] = self._calm_frozen(t)
            u["gadget_fade"] = 1.0
            return u
        u["backdrop"] = 1.0
        if self.reduced and self._calm_frozen(t) > 0.0:
            u["frozen"] = self._calm_frozen(t)    # the crossfade outlasts the hold: it runs on
        ring_t = 1.0 if self.reduced else ease((t - self.t_ring) / self.RING)
        flame_t = ease((t - self.t_flame) / self.FLAME) if t >= self.t_flame else 0.0
        mast_t = max(0.0, min(1.0, (t - self.t_flame - self.FLAME * 0.7) / (self.FLAME * 0.3)))
        alpha = 1.0
        if self.reduced:
            alpha = ease((t - self.t_ring) / 0.6)
        angle = 0.0 if (t < self.t_turn or self.reduced) else -(t - self.t_turn) * TAU / 24
        gain = 1.0 + 0.45 * (1.0 - flame_t)               # the glow drains into the flame
        u["emblems"] = [{"rect": rect, "angle": angle, "ring_t": ring_t, "flame_t": flame_t, "mast_t": mast_t,
                         "alpha": alpha, "gain": gain}]
        u["glow"] = 0.6 + 0.6 * (1.0 - flame_t)
        if self.reduced:
            u["glow"] = 0.6                       # no glow draining away: a steady card
        return u

    CALM_IN, CALM_OUT = 1.0, 1.0
    CALM_FADE = 0.9                               # reduced: the frozen screen's crossfade (s)

    def _calm_frozen(self, t):
        return max(0.0, 1.0 - max(0.0, t - self.t_tear) / self.CALM_FADE)

    def _still_frame(self, t, rect):
        """Still: the frozen screen crossfades into the finished card (the burn-in whole, the
        caption and the sign-off written out), which holds, then fades away. Only opacity
        changes: nothing turns, tears, types or flashes."""
        k_in = min(1.0, t / self.CALM_IN)
        k_out = min(1.0, max(0.0, (t - self.t_cut) / self.CALM_OUT))
        if k_out >= 1.0:
            return {"finished": True, "backdrop": 0.0, "fade": 0.0}
        a = k_in * (1.0 - k_out)
        return {"glow": 0.6, "backdrop": 1.0 - k_out, "frozen": 1.0 - k_in, "tear": 0.0,
                "gadget_fade": a,
                "emblems": [{"rect": rect, "angle": 0.0, "ring_t": 1.0, "flame_t": 1.0, "mast_t": 1.0,
                             "alpha": a, "gain": 1.0}]}


# ======================================================================== transmission
class Transmission(Base):
    name = "transmission"
    rebuild_every = 1e9

    def __init__(self, *a, rect=None, rect_fn=None, summary="", **kw):
        super().__init__(*a, **kw)
        self.rect = rect or (self.w - 420, 50, 400, 110)
        self.rect_fn = rect_fn
        self.rect_at = 0.0
        self.summary = summary
        self.dismiss_at = None
        self.max_t = 9.0

    def dismissed(self):
        if self.dismiss_at is None:
            self.dismiss_at = self.now()

    def build(self, b, d, t):
        x, y, w, h = self.rect
        pad = 10
        bx, by, bw, bh = x - pad, y - pad, w + 2 * pad, h + 2 * pad
        r0 = self.t_rel(0.1)
        b.brackets(bx, by, bw, bh, col("danger"), l=22, width=2.0, reveal=r0)
        b.brackets(bx - 6, by - 6, bw + 12, bh + 12, col("amber", 0.6), l=10, width=1.0, reveal=self.t_rel(0.2))
        top = by - 14 if by > 70 else by + bh + 26          # stay clear of the bar
        sub = by + bh + 22 if by > 70 else by + bh + 48
        b.plate(bx + bw - 250, top - 18, 250, 24, 0.85)
        b.text("INCOMING TRANSMISSION", bx + bw - 8, top, col("danger"), font="s", track=3.5, align="r",
               reveal=self.t_rel(0.2), type_rate=0.022)
        b.text("PRIORITY: CRITICAL", bx + bw - 8, sub, col("amber", 0.9), font="xs", track=2.5, align="r",
               reveal=self.t_rel(0.5), type_rate=0.015)
        # crosshair ticks pointing in at the box
        mx, my = bx + bw / 2, by + bh / 2
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            ex = mx + dx * (bw / 2 + 4)
            ey = my + dy * (bh / 2 + 4)
            b.line((ex + dx * 26, ey + dy * 26), (ex + dx * 8, ey + dy * 8), col("danger", 0.9), width=1.5,
                   reveal=self.t_rel(0.3))

    def t_rel(self, k):
        return max(k, 1e-3)

    def frame(self, t, d):
        x, y, w, h = self.rect
        end = self.dismiss_at if self.dismiss_at is not None else self.max_t
        u = {"glow": 0.9}
        k = max(0.0, (t - end) / 0.35)
        u["gadget_fade"] = 1.0 - min(k, 1.0)
        tear = 0.0 if self.reduced else max(0.0, 1.0 - t / 0.15)
        u["tear"] = tear
        u["tear_band"] = (y - 50.0, y + h + 50.0, 1.0 if tear > 0 else 0.0, 0.0)
        pulse = max(0.0, 1.0 - t / 0.9) * (0.5 + 0.5 * math.cos(t * TAU * 2.2))
        if self.reduced:                          # reduced motion: a steady red edge, faded in and out
            pulse = 0.5 * min(1.0, t / 0.5) * u["gadget_fade"]
        u["edge"] = (0.55 * pulse, 2.0, 0.0, 0.0)
        # dunst already carries the burn-in at icon size (theme kit); we bracket it
        if self.rect_fn and t - self.rect_at > 0.2:
            self.rect_at = t
            r = self.rect_fn()
            if r and r != self.rect:
                self.rect = r
                self.built_at = None
        if t >= end + 0.4:
            u["finished"] = True
        return u


# ======================================================================== holo deck
class HoloDeck(Base):
    name = "holodeck"
    rebuild_every = 1.0

    def close(self):
        super().close()

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        s = self.h / 1440.0
        self.s = s
        self.L = {
            "rings": (440 * s, 640 * s, 270 * s),
            "rings_panel": (80 * s, 170 * s, 980 * s, 960 * s),
            "con": (1500 * s, 640 * s, 330 * s),
            "con_panel": (1090 * s, 170 * s, 820 * s, 960 * s),
            "holo": (2215 * s, 610 * s, 380 * s),
            "holo_panel": (1940 * s, 170 * s, 540 * s, 960 * s),
        }
        self.yaw, self.pitch = 0.6, 0.32
        self.cyaw = 0.0
        self.drag = None
        self.last_input = -10.0
        self.selected = None
        self.hover = None
        self.lerp = {}
        from .notes_panel import NotesPanel
        self.notes = NotesPanel(self)
        self.typed = ""
        self.p2 = None
        self.p2_on = False
        from . import holoview
        self.models = holoview.available()
        self.hv = holoview.CompactHolo(self.models, scale=s) if self.models else None
        self.hv_hover = None

    def rebuild_due(self, t):
        if self.built_at is None:
            return True
        if self.notes.on:                          # the caret blinks; typing shows at once
            return t - self.built_at >= 0.25
        if t < 2.2:                                # counters tick up: rebuild at ~15 Hz
            return t - self.built_at >= 1 / 15
        return t - self.built_at >= self.rebuild_every

    def _ticked(self, d, t):
        """Readings eased from zero during assembly (the counters tick up)."""
        out = dict(d)
        for key, start in (("cpu", 0.35), ("gpu", 0.45), ("mem", 0.55), ("vram", 0.65), ("cpu_temp", 0.4),
                           ("gpu_temp", 0.5)):
            v = d.get(key)
            if v is not None:
                out[key] = v * ease((t - start) / 1.2)
        if d.get("cores"):
            k = ease((t - 0.8) / 1.0)
            out["cores"] = [c * k for c in d["cores"]]
        return out

    def build(self, b, d, t):
        dd = self._ticked(d, t)
        s = self.s
        T = 0.05
        # title strip
        b.text("HOLO // LIVE TELEMETRY", 80 * s, 110 * s, col("soft"), font="l", track=6, reveal=T, type_rate=0.02)
        b.text(time.strftime("%H:%M:%S  %Y-%m-%d").upper(), self.w - 80 * s, 110 * s, col("dim"), font="s", track=2,
               align="r", reveal=T + 0.2)
        b.line((80 * s, 128 * s), (self.w - 80 * s, 128 * s), col("guard"), reveal=T)
        x, y, w, h = self.L["rings_panel"]
        gadgets.frame(b, x, y, w, h, "THE WICK // LOCAL CORE", T + 0.05, sub="THIS WORKSTATION")
        cx, cy, R = self.L["rings"]
        gadgets.rings(b, dd, self.st, cx, cy, R, t0=T + 0.25)
        x, y, w, h = self.L["con_panel"]
        gadgets.constellation_panel(b, d, x, y, w, h, t0=T + 0.25)
        cx, cy, sz = self.L["con"]
        gadgets.constellation(b, d, 0, 0, sz, space=2, t0=T + 0.5)
        x, y, w, h = self.L["holo_panel"]
        if self.hv is not None:
            self._model_panel(b, d, t, T)
        else:
            gadgets.frame(b, x, y, w, h, "HOLOGRAM // THIS RIG", T + 0.45, sub="DRAG TO SPIN · CLICK A PART")
            gadgets.hologram(b, d, self.st, space=3, t0=T + 0.7)
        # selection callout
        if self.hv is not None:
            pass
        elif self.selected:
            title, lines = gadgets.part_readings(self.selected, d, self.st)
            px, py = x + 24 * s, y + h - 150 * s
            b.plate(px - 8, py - 30, w - 32 * s, 130 * s, 0.9)
            b.brackets(px - 8, py - 30, w - 32 * s, 130 * s, col("soft"), l=10, reveal=self.sel_t)
            b.text(f"{self.selected}  ·  {title}"[:44], px + 6, py, col("soft"), font="m", track=1.5,
                   reveal=self.sel_t, type_rate=0.01)
            for i, ln in enumerate(lines):
                b.text(ln[:54], px + 6, py + 30 + i * 26, col("phosphor"), font="s", track=1, reveal=self.sel_t + 0.1,
                       type_rate=0.006)
            anchor = gadgets.PART_ANCHOR[self.selected]
            b.line(anchor, (px + 40, py - 30), col("soft", 0.8), space=3, space1=0, reveal=self.sel_t)
        else:
            b.text("CLICK A PART FOR ITS READINGS", x + w / 2, y + h - 40 * s, col("dim"), font="xs", track=2.5,
                   align="c", reveal=T + 1.4)
        if self.hover and self.hover != self.selected and not self.models:
            anchor = gadgets.PART_ANCHOR[self.hover]
            b.text(f"{self.hover} · CLICK FOR READINGS", anchor[0], anchor[1], col("white"), font="xs", track=1.5,
                   space=3, z=anchor[2], dx=12, dy=12)
        b.text("ESC CLOSES · N: FIELD NOTES · [ ] MODEL · O: GALLERY" + self.tab_hint(), self.w / 2, self.h - 40 * s,
               col("dim", 0.8), font="xs", track=3, align="c", reveal=T + 1.2)
        if self.p2 is None:
            self.p2 = glkit.Painter(self.stage.atlas)
        b2 = glkit.Batch(self.stage.atlas)
        if self.notes.on:
            self.notes.draw(b2, d)
        self.p2.upload(b2)
        self.p2_on = self.notes.on

    # ---- the compact hologram (shared bromigos-holo renderer; full viewer = SUPER+O)
    def _hv_rect(self):
        s = self.s
        x, y, w, h = self.L["holo_panel"]
        return (x + 6 * s, y + 70 * s, w - 12 * s, h - 190 * s)

    def _model_panel(self, b, d, t, T):
        s = self.s
        x, y, w, h = self.L["holo_panel"]
        hv = self.hv
        gadgets.frame(b, x, y, w, h, f"HOLOGRAM // {hv.title()}", T + 0.45,
                      sub=f"[ ] MODEL {hv.idx + 1}/{len(hv.names)}")
        if hv.stage is not None:
            b.text((hv.stage.meta.get("subtitle") or "").upper(), x + 18 * s, y + 60 * s, col("dim"), font="xs",
                   track=2, reveal=T + 0.6)
        i = self.hv_hover
        if i is not None and hv.stage is not None and i < len(hv.stage.parts):
            label, level, lines, hint = hv.reading(i)
            c = {"ok": "phosphor", "warn": "amber", "crit": "danger"}.get(level, "static")
            ph = (64 + 22 * min(len(lines), 3)) * s
            px, py = x + 18 * s, y + h - ph - 70 * s
            b.plate(px, py, w - 36 * s, ph, 0.92)
            b.brackets(px, py, w - 36 * s, ph, col(c), l=10)
            b.text(label, px + 12 * s, py + 26 * s, col("white"), font="m", track=1.5)
            for k, ln in enumerate(lines[:3]):
                b.text(str(ln).upper()[:44], px + 12 * s, py + 50 * s + k * 22 * s, col(c), font="s", track=0.6)
            b.text((hint or "").upper()[:58], px + 12 * s, py + ph - 10 * s, col("dim"), font="xs", track=0.5)
        b.plate(x + 18 * s, y + h - 58 * s, w - 36 * s, 34 * s, 0.85)
        b.text("CLICK OR O: OPEN IN THE GALLERY (SUPER+O)", x + w / 2, y + h - 36 * s, col("soft"), font="xs",
               track=1.8, align="c", reveal=T + 1.2)

    def post_composite(self, u):
        if self.hv is not None and self.hv.target is not None:
            self.hv.composite((float(self.w), float(self.h)), self._hv_rect(), u.get("fade", 1.0))

    sel_t = 0.0

    def frame(self, t, d):
        p = self.stage.painter
        idle = t - self.last_input > 4.0
        if self.drag is None and idle and not self.reduced:     # reduced motion: no idle drift
            self.yaw += 0.004
        cx, cy, sz = self.L["con"]
        p.rot[2] = glkit.rot_matrix(0.0 if self.reduced else t * 0.09, 0.42)
        p.ctr[2] = (cx, cy, sz, 3.2)
        hx, hy, hs = self.L["holo"]
        p.rot[3] = glkit.rot_matrix(self.yaw, self.pitch)
        p.ctr[3] = (hx, hy, hs, 3.0)
        if self.hv is not None:
            _x, _y, rw, rh = self._hv_rect()
            self.hv.render(rw, rh, t)
        else:
            st = gadgets.part_state(d)
            for i, (inten, heat) in enumerate(st):
                p.parts[i] = (inten, heat, 1.0 if gadgets.PARTS[i] == self.selected else 0.0, 0.0)
        fade = min(t / 0.25, 1.0)
        if self.closing_at is not None:
            k = (t - self.closing_at) / 0.25
            fade = max(0.0, 1.0 - k)
        u = {"backdrop": 0.8, "glow": 0.95, "fade": fade}
        if self.closing_at is not None and t - self.closing_at > 0.26:
            u["finished"] = True
        return u

    # ---- interaction
    def _pick(self, x, y):
        p = self.stage.painter
        names = list(gadgets.PART_ANCHOR)
        pts = glkit.project([gadgets.PART_ANCHOR[n] for n in names], p.rot[3], p.ctr[3])
        best, bd = None, 46.0 * self.s
        for n, (px, py, pz) in zip(names, pts):
            dd = math.hypot(px - x, py - y) + pz * 6
            if dd < bd:
                best, bd = n, dd
        return best

    def _in_holo(self, x, y):
        x0, y0, w, h = self.L["holo_panel"]
        return x0 <= x <= x0 + w and y0 <= y <= y0 + h

    def click(self, x, y, button):
        self.last_input = self.now()
        if self.notes.on:
            if not self.notes.click(x, y):
                self.notes.on = False
            self.built_at = None
            return True
        if self._in_holo(x, y):
            self.drag = (x, y, self.yaw, self.pitch, False)
            self.drag_last = (x, y)
            return True
        inside = any(px <= x <= px + w and py <= y <= py + h for (px, py, w, h) in
                     (self.L["rings_panel"], self.L["con_panel"]))
        if not inside:
            self.close()
        return True

    def motion(self, x, y, buttons):
        self.last_input = self.now()
        if self.drag:
            x0, y0, yaw, pitch, moved = self.drag
            if abs(x - x0) + abs(y - y0) > 4:
                moved = True
            if self.hv is not None:
                lx, ly = getattr(self, "drag_last", (x, y))
                self.hv.drag((x - lx) * 0.01, (y - ly) * 0.006)
                self.drag_last = (x, y)
            else:
                self.yaw = yaw + (x - x0) * 0.01
                self.pitch = max(-1.2, min(1.2, pitch + (y - y0) * 0.008))
            self.drag = (x0, y0, yaw, pitch, moved)
            return
        if self.hv is not None:
            rx, ry, rw, rh = self._hv_rect()
            i = self.hv.pick(x - rx, y - ry) if (rx <= x <= rx + rw and ry <= y <= ry + rh) else None
            if i != self.hv_hover:
                self.hv_hover = i
                self.hv.hover(i)
                self.built_at = None
            return
        h = self._pick(x, y) if self._in_holo(x, y) else None
        if h != self.hover:
            self.hover = h
            self.built_at = None

    def release(self, x, y):
        if self.hv is not None:
            if self.drag and not self.drag[4]:
                self.hv.open_gallery()           # the full viewer
                self.close()
            self.hv.end_drag()
            self.drag = None
            return
        if self.drag and not self.drag[4]:
            n = self._pick(x, y)
            self.selected = None if n == self.selected else n
            self.sel_t = self.now() + 0.01
            self.built_at = None
        self.drag = None

    def tab_hint(self):
        """ · TAB: <the next deck>, when Tab has one to open (decks.py)."""
        if getattr(self, "_tab_hint", None) is None:
            from .decks import label, next_deck
            try:
                nxt = next_deck(self.name, self.cfg)
            except Exception:
                nxt = None
            self._tab_hint = f" · TAB: {label(nxt).upper()}" if nxt else ""
        return self._tab_hint

    def key(self, name):
        if self.notes.on and name != "Tab":
            self.notes.key(name, self.typed)
            self.built_at = None
            return True
        if self.hv is not None and name in ("bracketleft", "bracketright"):
            self.hv.cycle(-1 if name == "bracketleft" else 1)
            self.hv_hover = None
            self.built_at = None
            return True
        if self.hv is not None and name in ("o", "O"):
            self.hv.open_gallery()
            self.close()
            return True
        if name in ("n", "N", "slash"):
            self.notes.toggle()
            if name == "slash":
                self.notes.query = ""
            self.built_at = None
            return True
        if name in ("Escape", "q"):
            self.close()
        elif name == "Tab" and self.app:
            from .decks import next_deck
            nxt = next_deck(self.name, self.cfg)
            if nxt:
                self.close()
                from gi.repository import GLib
                GLib.timeout_add(300, lambda: (self.app.overlay(nxt), False)[1])
        elif name in ("Left", "h"):
            self.yaw -= 0.2
        elif name in ("Right", "l"):
            self.yaw += 0.2
        self.last_input = self.now()
        return True


# ======================================================================== screensaver
class Screensaver(Base):
    """The Drift at rest: a gas giant whose terminator is the local hour, the
    relay station (spokes = lab services), the cluster constellation, the arc
    rings, the burn-in turning against the clock, and Drift-script rain."""
    name = "screensaver"
    rebuild_every = 1.0

    def shader_time(self, t):
        """Reduced motion: the Drift drifts slower; still: one moment of it, held (after the
        gadgets have drawn themselves in)."""
        if not self.reduced:
            return t
        if not hasattr(self, "sclock"):
            self.sclock = motion.Clock(self.motion_mode)
        return 3.0 + self.sclock(t)

    def _sun(self):
        """The planet's terminator: the local hour (still: as it was at the minute)."""
        if not self.still:
            return gadgets.local_sun_angle()
        now = time.monotonic()
        if getattr(self, "_sun_at", None) is None or now - self._sun_at >= motion.STILL_EVERY:
            self._sun_at, self._sun_v = now, gadgets.local_sun_angle()
        return self._sun_v

    def build(self, b, d, t):
        s = self.h / 1440.0
        sp = self.cfg.get("space", {})
        gadgets.rings(b, d, self.st, 330 * s, 1060 * s, 190 * s, t0=0.6, legend="right")
        gadgets.constellation(b, d, 0, 0, 230 * s, space=2, t0=0.9)
        if sp.get("station", True):
            gadgets.drift_station(b, d, space=1, t0=0.3)
        cx = self.w / 2
        b.text(time.strftime("%H:%M").upper(), cx, 1000 * s, col("soft"), font="xxl", track=6, align="c")
        b.text(time.strftime("%A %d %B").upper(), cx, 1042 * s, col("dim"), font="s", track=4, align="c")
        hl = gadgets.health(d)
        if hl:
            b.text("DEGRADED · CHECK THE LAB" if hl == 2 else "RUNNING HOT OR LINK STALE", cx, 1080 * s,
                   col("danger" if hl == 2 else "amber"), font="xs", track=3, align="c")

    def frame(self, t, d):
        s = self.h / 1440.0
        sp = self.cfg.get("space", {})
        p = self.stage.painter
        spin = 0.0 if self.reduced else t                 # reduced motion: the models hold still
        p.rot[1] = glkit.rot_matrix(spin * 0.05, 0.38, 0.12)
        p.ctr[1] = (520 * s, 380 * s, 250 * s, 3.4)
        p.rot[2] = glkit.rot_matrix(spin * 0.07, 0.4)
        p.ctr[2] = (2140 * s, 470 * s, 230 * s, 3.2)
        D = 560 * s
        cx, cy = self.w / 2, 560 * s
        fade = min(t / 0.8, 1.0)
        if self.closing_at is not None:
            fade = max(0.0, 1.0 - (t - self.closing_at) / 0.25)
        cpu = (d.get("cpu") or 0) / 100
        rps = ((d.get("cluster") or {}).get("traefik") or {}).get("rpsNow") or 0.0
        green = gadgets.all_green(d) and sp.get("relay_beam", True)
        if not hasattr(self, "traffic"):
            from .traffic import Traffic
            self.traffic = Traffic()
        ships, ships2, lvl_smooth = self.traffic.uniforms(           # reduced motion: no craft
            gadgets.traffic_level(d) if sp.get("traffic", True) and not self.reduced else -1.0,
            (0.0, 60 * s, float(self.w), 700 * s))
        u = {"backdrop": 1.0, "fade": fade, "glow": 1.0,
             "rain": (0.5 + 0.4 * cpu, 0.8 + 1.4 * cpu, 0.32, 1.0 if self.cfg["rain"].get("enabled", True) else 0.0),
             "rain_rect": (0.0, 0.0, float(self.w), float(self.h)),
             "ships": (ships, ships2),
             "space": (1.0 if sp.get("stars", True) else 0.0, lvl_smooth,
                       1.0 if green else 0.0, float(gadgets.health(d) if sp.get("health_tint", True) else 0)),
             "space_rect": (0.0, 60 * s, float(self.w), 700 * s),
             "planet": (1880 * s, 1500 * s, 760 * s, 1.0 if sp.get("planet", True) else 0.0),
             "sun": (self._sun(), 0.012, 0.35, 0.0),
             "beam": (520 * s, 380 * s - 0.9 * 250 * s, -1.75, 0.12 + min(rps, 6.0) / 12.0),
             "emblems": [{"rect": (cx - D / 2, cy - D / 2, D, D), "angle": 0.0 if self.reduced else -t * TAU / 24,
                          "alpha": fade}]}
        if self.closing_at is not None and t - self.closing_at > 0.26:
            u["finished"] = True
        return u

    def key(self, name):
        self.close()
        return True

    def click(self, x, y, button):
        self.close()
        return True

    def motion(self, x, y, buttons):
        if not hasattr(self, "_m0"):
            self._m0 = (x, y)
        elif math.hypot(x - self._m0[0], y - self._m0[1]) > 8:
            self.close()


# ======================================================================== radial
class Radial(Base):
    name = "radial"
    rebuild_every = 0.5

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.items = list(self.cfg["radial"].get("items") or [])
        from .homelab import lab_name
        # an item showing the lab's reading without a name of its own goes by the lab's name
        self.items = [dict(it, name=lab_name()) if it.get("stat") == "lab" and not it.get("name") else it
                      for it in self.items]
        self.sel = 0
        self.launched = None
        self.cx, self.cy = self.w / 2, self.h / 2
        s = self.h / 1440.0
        self.R0, self.R1 = 190 * s, 330 * s

    def item_stat(self, it, d):
        cl = d.get("cluster") or {}
        c = cl.get("cluster") or {}
        # the reading an item shows: its `stat` (fills, lab, argo, grafana, litellm, terminal),
        # else its name's
        n = (it.get("stat") or it.get("name", "")).upper()
        if n == "FILLS":
            return f"PAPER FILLS {d.get('fills_total')}" if d.get("fills_total") is not None else "TAPE UNREACHABLE"
        if n == "LAB":
            return f"NODES {c.get('nodesReady', '?')}/{c.get('nodesTotal', '?')} · PODS {c.get('podsRunning') or 0:.0f}" if c else "NO SNAPSHOT"
        if n == "ARGO":
            a = cl.get("argocd") or {}
            return f"{a.get('healthy', '?')}/{a.get('total', '?')} HEALTHY + SYNCED" if a else "NO SNAPSHOT"
        if n == "GRAFANA":
            return f"{c.get('alertsFiring') or 0:.0f} ALERTS FIRING" if c else "NO SNAPSHOT"
        if n == "LITELLM":
            ai = cl.get("ai") or {}
            return f"{ai.get('rpmNow') or 0:.1f} REQ/MIN" if ai else "NO SNAPSHOT"
        if n == "TERMINAL":
            return f"CPU {gadgets.pct(d.get('cpu'))} · RAM {gadgets.pct(d.get('mem'))}"
        return ""

    def build(self, b, d, t):
        n = max(len(self.items), 1)
        cx, cy, R0, R1 = self.cx, self.cy, self.R0, self.R1
        s = self.h / 1440.0
        T = 0.01
        b.disc_plate((cx, cy), R1 + 46 * s, 0.86)
        b.arc((cx, cy), R1 + 30 * s, R1 + 31 * s, 0, TAU, col("dim", 0.9), reveal=T)
        b.arc((cx, cy), R1 + 16 * s, R1 + 24 * s, 0, TAU, col("dim", 0.7), segs=144, gap=0.75, spin=-0.05, reveal=T + 0.05)
        b.arc((cx, cy), R1 + 12 * s, R1 + 27 * s, 0, TAU, col("soft", 0.8), segs=n, gap=0.97, spin=0.0, reveal=T + 0.1)
        b.arc((cx, cy), R0 - 22 * s, R0 - 19 * s, 0, TAU, col("dim", 0.7), segs=6, gap=0.5, spin=0.25, reveal=T + 0.1)
        seg = TAU / n
        for i, it in enumerate(self.items):
            a0, a1 = i * seg - seg / 2 + 0.02, i * seg + seg / 2 - 0.02
            on = i == self.sel
            b.arc((cx, cy), R0, R1, a0, a1, col("guard", 0.35) if not on else col("dim", 0.32), reveal=T + 0.05 + i * 0.03)
            b.arc((cx, cy), R1 - 3 * s, R1, a0, a1, col("soft" if on else "dim", 1.0), reveal=T + 0.1 + i * 0.03)
            if on:
                b.arc((cx, cy), R1 + 4 * s, R1 + 8 * s, a0, a1, col("phosphor", 1.0))
                b.arc((cx, cy), R0, R0 + 3 * s, a0, a1, col("soft", 1.0))
            am = i * seg
            lx = cx + math.sin(am) * (R0 + R1) / 2
            ly = cy - math.cos(am) * (R0 + R1) / 2
            b.text(it.get("name", "?").upper(), lx, ly + 2 * s, col("white" if on else "soft"), font="m", track=2,
                   align="c", reveal=T + 0.15 + i * 0.03, type_rate=0.01)
            b.text(it.get("sub", "").upper(), lx, ly + 22 * s, col("phosphor" if on else "dim"), font="xs", track=1.5,
                   align="c", reveal=T + 0.2 + i * 0.03)
            b.text(str(i + 1), lx, ly - 22 * s, col("dim", 0.9), font="xs", track=0, align="c",
                   reveal=T + 0.2 + i * 0.03)
        # hub
        it = self.items[self.sel] if self.items else {}
        b.arc((cx, cy), R0 - 40 * s, R0 - 39 * s, 0, TAU, col("dim", 0.8), reveal=T + 0.2)
        b.text(it.get("name", "").upper(), cx, cy - 6 * s, col("soft"), font="l", track=4, align="c")
        target = it.get("url") or it.get("cmd") or ""
        target = target.replace("https://", "").replace("http://", "")
        b.text(target[:30].upper(), cx, cy + 20 * s, col("dim"), font="xs", track=1, align="c")
        stat = self.item_stat(it, d)
        if stat:
            b.text(stat[:30], cx, cy + 44 * s, col("phosphor"), font="xs", track=1.2, align="c")
        b.text("1-8 · ARROWS · ENTER LAUNCHES · ESC CLOSES", cx, cy + R1 + 82 * s, col("dim", 0.9), font="xs",
               track=2.5, align="c", reveal=T + 0.4)

    def frame(self, t, d):
        fade = min(t / 0.15, 1.0)
        if self.closing_at is not None:
            fade = max(0.0, 1.0 - (t - self.closing_at) / 0.18)
        u = {"backdrop": 0.0, "fade": fade, "glow": 1.0,
             "vignette": (self.cx, self.cy, self.R1 * 1.6, 0.55)}
        if self.closing_at is not None and t - self.closing_at > 0.19:
            u["finished"] = True
        return u

    def _select(self, i):
        if self.items and i % len(self.items) != self.sel:
            self.sel = i % len(self.items)
            self.built_at = None

    def launch(self):
        if not self.items or self.launched is not None:
            return
        it = self.items[self.sel]
        self.launched = it
        try:
            if it.get("url"):
                browser = self.cfg["radial"].get("browser", "xdg-open")
                cmd = shlex.split(browser) + [it["url"]]
            else:
                cmd = ["sh", "-c", os.path.expanduser(it.get("cmd", "true"))]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass
        self.close()

    def key(self, name):
        if name in ("Escape", "q"):
            self.close()
        elif name in ("Return", "KP_Enter", "space"):
            self.launch()
        elif name in ("Right", "Down", "l", "j", "Tab"):
            self._select(self.sel + 1)
        elif name in ("Left", "Up", "h", "k", "ISO_Left_Tab"):
            self._select(self.sel - 1)
        elif name.isdigit() and 1 <= int(name) <= len(self.items):
            self._select(int(name) - 1)
            self.launch()
        return True

    def _hit(self, x, y):
        dx, dy = x - self.cx, y - self.cy
        r = math.hypot(dx, dy)
        if r < self.R0 * 0.6 or r > self.R1 + 60:
            return None
        n = max(len(self.items), 1)
        a = math.atan2(dx, -dy) % TAU
        return int(((a + TAU / n / 2) % TAU) // (TAU / n))

    def motion(self, x, y, buttons):
        i = self._hit(x, y)
        if i is not None:
            self._select(i)

    def click(self, x, y, button):
        i = self._hit(x, y)
        if i is None:
            if math.hypot(x - self.cx, y - self.cy) > self.R1 + 60:
                self.close()
            return True
        self._select(i)
        self.launch()
        return True


KINDS = {"intercept": Intercept, "transmission": Transmission, "holodeck": HoloDeck,
         "screensaver": Screensaver, "radial": Radial}


def kind_class(kind):
    if kind.startswith("plugin:"):                 # deck plugins (plugins/<name>.py), loaded fresh
        from .plugins import deck_class
        return deck_class(kind.split(":", 1)[1])
    if kind == "timeline" and "timeline" not in KINDS:
        from .timeline import TimelineDeck
        KINDS["timeline"] = TimelineDeck
    if kind == "codec" and "codec" not in KINDS:
        from .codec_panel import CodecPanel
        KINDS["codec"] = CodecPanel
    if kind == "driftmap" and "driftmap" not in KINDS:
        from .drift_map import DriftMap
        KINDS["driftmap"] = DriftMap
    if kind not in KINDS:
        # any other deck is a module <kind>_deck defining DECK: bromigOS's own (swarm), the
        # homelab package's (ops, netmap, mind: live.HOMELAB), or a personal plugin's from the
        # plugin folders, which join this package (live.PLUGINS)
        import importlib
        try:
            mod = importlib.import_module(f".{kind}_deck", __package__)
        except ModuleNotFoundError as e:
            if e.name != f"{__package__}.{kind}_deck":
                raise
            from . import PLUGINS
            if kind in ("ops", "netmap", "mind"):
                raise LookupError(f"no {kind!r} deck: it comes with bromigos-homelab, which isn't installed "
                                  "(docs/homelab.md)") from None
            raise LookupError(f"no {kind!r} deck: it is a plugin, not installed "
                              f"({kind}_deck.py in {' or '.join(PLUGINS)})") from None
        KINDS[kind] = mod.DECK
    return KINDS[kind]


def offscreen(kind, cfg, data, w, h):
    kw = {}
    if kind == "intercept":
        import cairo
        # the captured screen: OFF_FROZEN (an image) for testing a theme's look, else the den
        path = os.environ.get("OFF_FROZEN") or os.path.expanduser(cfg["background"].get("underlay", ""))
        if os.path.exists(path):
            from .scene import load_image
            raw, _ = load_image(path, w, h)
            kw["frozen_rgb"] = raw
    if kind == "transmission":
        kw["rect"] = (w - 440, 60, 400, 96)
        kw["summary"] = "TEST"
    if kind == "codec":
        kw["call"] = OFF_CALL["call"]
    return kind_class(kind)(cfg, data, w, h, **kw)


OFF_CALL = {"call": None}


# ======================================================================== windows
def capture(monitor):
    """The screen as it is right now (for the intercept's hold/tear)."""
    try:
        out = subprocess.run(["grim", "-t", "ppm", "-o", monitor, "-"], capture_output=True, timeout=3).stdout
        parts = out.split(b"\n", 3)
        w, h = (int(v) for v in parts[1].split())
        return np.frombuffer(parts[3], dtype=np.uint8)[:w * h * 3].reshape(h, w, 3).copy()
    except Exception:
        return None


def notification_rect(monitor):
    from . import hypr
    levels = hypr.layers_on(monitor)
    mons = hypr.request("monitors") or []
    m = next((x for x in mons if x.get("name") == monitor), {"x": 0, "y": 0})
    for lvl in ("3", "2"):
        for L in (levels.get(lvl) or []):
            if L.get("namespace") in ("notifications", "dunst"):
                return (L["x"] - m["x"], L["y"] - m["y"], L["w"], L["h"])
    return None


def make(app, kind, **kw):
    import gi
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, GtkLayerShell

    from .app import GLWindow
    cfg, data = app.cfg, app.data
    mon = cfg["general"]["monitor"]
    keyboard = GtkLayerShell.KeyboardMode.EXCLUSIVE
    input_ok = True
    extra = {}
    if kind == "intercept":
        extra["frozen_rgb"] = capture(mon)
        extra["sound"] = app.sound
    elif kind == "transmission":
        keyboard, input_ok = GtkLayerShell.KeyboardMode.NONE, False
        extra["summary"] = kw.get("summary", "")
    win_kw = {}
    if kw.get("commands"):
        extra["commands"] = kw["commands"]
    if kind == "codec":
        from .codec_panel import PANEL
        keyboard, input_ok = GtkLayerShell.KeyboardMode.NONE, False
        extra["call"] = kw.get("call")
        extra["desk"] = getattr(app, "codec", None)
        sc = float(cfg.get("codec", {}).get("scale", 1.0))
        win_kw = {"anchors": "br", "size": (int(PANEL[0] * sc), int(PANEL[1] * sc)),
                  "margins": {"r": 28, "b": 28}}
    holder = {}

    def make_renderer(w, h):
        args = dict(extra)
        if kind == "transmission":
            args["rect"] = holder.get("rect")
            args["rect_fn"] = lambda: notification_rect(mon)
        r = kind_class(kind)(cfg, data, w, h, app=app, **args)
        holder["r"] = r
        return r
    if kind == "transmission":
        holder["rect"] = notification_rect(mon)
    # decks go on the top layer (still over every window) so VECTOR's console, on the
    # overlay layer, stays in front of them while he walks the host through one
    layer = GtkLayerShell.Layer.TOP if app.is_deck(kind) else GtkLayerShell.Layer.OVERLAY
    win = GLWindow(app, layer, f"bromigos-live-{kind}", make_renderer,
                   keyboard=keyboard, alpha=True, input_ok=input_ok, **win_kw)

    class Handle:
        def __init__(self):
            self.closed = False

        @property
        def renderer(self):
            return holder.get("r")

        def close(self):
            r = holder.get("r")
            if r and not r.done:
                r.close()
            else:
                self.finish()

        def dismissed(self):
            r = holder.get("r")
            if r and hasattr(r, "dismissed"):
                r.dismissed()

        def finish(self):
            if self.closed:
                return
            self.closed = True
            win.destroy()
            app.overlay_closed(kind, self)

    handle = Handle()
    w = win.win
    w.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK |
                 Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.KEY_PRESS_MASK |
                 Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)

    def on_key(_w, ev):
        r = holder.get("r")
        if r:
            u = Gdk.keyval_to_unicode(ev.keyval)
            r.typed = chr(u) if u >= 32 else ""
            r.key(Gdk.keyval_name(ev.keyval) or "")
        return True

    def on_press(_w, ev):
        r = holder.get("r")
        if r:
            r.mods = int(ev.state)
            if ev.type == Gdk.EventType._2BUTTON_PRESS:      # after the two plain presses
                if hasattr(r, "dclick"):
                    r.dclick(ev.x, ev.y)
                return True
            if ev.type == Gdk.EventType.BUTTON_PRESS:
                r.click(ev.x, ev.y, ev.button)
        return True

    def on_scroll(_w, ev):
        r = holder.get("r")
        if r is None or not hasattr(r, "scroll"):
            return True
        if ev.direction == Gdk.ScrollDirection.SMOOTH:    # touchpads: fractions; wheels: whole notches
            ok, _dx, dy = ev.get_scroll_deltas()
            if not ok or dy == 0:
                return True
        elif ev.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            dy = -1.0 if ev.direction == Gdk.ScrollDirection.UP else 1.0
        else:
            return True
        r.mods = int(ev.state)
        r.scroll(ev.x, ev.y, dy)
        return True

    def on_release(_w, ev):
        r = holder.get("r")
        if r:
            r.release(ev.x, ev.y)
        return True

    def on_motion(_w, ev):
        r = holder.get("r")
        if r:
            r.motion(ev.x, ev.y, ev.state)
        return True
    w.connect("key-press-event", on_key)
    w.connect("button-press-event", on_press)
    w.connect("button-release-event", on_release)
    w.connect("motion-notify-event", on_motion)
    w.connect("scroll-event", on_scroll)

    def watchdog():
        r = holder.get("r")
        if handle.closed:
            return False
        if win.failed or win.dead or (r and r.done):      # dead: the output went away under it
            handle.finish()
            return False
        return True
    GLib.timeout_add(100, watchdog)
    win.set_fps(30)
    # the ghost phase of the intercept must never take input
    if kind == "intercept":
        def ghost_passthrough():
            r = holder.get("r")
            if handle.closed:
                return False
            if r and (r.now() >= r.t_cut or r.skip_to is not None):
                import cairo
                gw = w.get_window()
                if gw:
                    gw.input_shape_combine_region(cairo.Region(), 0, 0)
                GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
                return False
            return True
        GLib.timeout_add(50, ghost_passthrough)
    return handle
