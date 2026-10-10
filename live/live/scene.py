"""The live background: the theme's wallpaper as the base plate, with the den's
own screens made live (scope = network, monitor = the burn-in, meters = CPU and
GPU, main CRT = the homelab relay map), Drift-script rain in the deep-space
window, floor-grid throughput pulses, and the X-ray scanner pass."""
import math
import os
import time

import numpy as np
from OpenGL import GL

from . import gadgets, glkit, motion, schematic
from .emblem import Emblem
from .stage import Stage

TAU = 2 * math.pi

TV_UNIFORM = {"wave": "wave", "emblem": "emb", "big": "big"}   # bg.frag's den TV uniforms, per screen
DEN = {   # screen rects in the 2560x1440 den wallpaper (fitted by hand)
    "wave": (1475, 762, 124, 110),
    "emblem": (1090, 920, 158, 143),
    "big": (1188, 678, 200, 175),
    "meter0": (1545, 932, 66, 32),
    "meter1": (1555, 1050, 61, 32),
    "schem": (1000, 560, 860, 660),
}


def load_image(path, w, h):
    """The image at w x h, (h, w, 3) uint8, and its pixbuf (any width: live/pixbuf.py)."""
    from . import pixbuf
    return pixbuf.load(path, w, h)


def retint_plate(raw):
    """The den plate (painted in the Wick's green) gradient-mapped to the theme in force
    (lib/bromigos_retint.py: lightness kept, hue and chroma from the theme's background,
    dim, primary and soft); unchanged under the Wick, or without the library."""
    try:
        import bromigos_retint as R
        pal = R.palette()
        if R.is_wick(pal):
            return raw
        out = R.retint(raw, pal)
        print(f"bromigos-live: plate recoloured for {pal.get('theme')}", flush=True)
        return np.ascontiguousarray(out)
    except Exception as e:                       # never a den without its plate
        print(f"bromigos-live: plate not recoloured ({type(e).__name__}: {e})", flush=True)
        return raw


class Background:
    def __init__(self, cfg, data, w, h):
        self.cfg = cfg
        self.data = data
        self.st = data.static
        self.w, self.h = w, h
        self.stage = Stage(w, h, "bg.frag")
        self.emblem = Emblem(512, 128)
        self.under = None
        self.under_sig = None
        self.fitted = False
        self.variant = None
        self.segs = []
        self.steam_on = False
        self.face = glkit.T.rgb("soft")
        self.checked_at = 0.0
        self.shipmask = None
        self._load_under()
        self.schem_tex = None
        self.schem_next = time.monotonic() + 6.0
        self.sweep_t0 = None
        self.scan_req = False
        self.scan_pin = False
        self.scan_held = False
        self.pin_amt = 0.0
        self.hold_amt = 0.0
        self.schem_at = 0.0
        self.beam_speed = 600.0
        self.bursts = [(0.0, 0.0, 0.0, 0.0)] * 6
        self.burst_i = 0
        self.wipe_t0 = -10.0
        self.static_burst = 0.0
        self.meter_v = [0.0, 0.0]
        self.wave = np.zeros(48, dtype=np.float32)
        self.last_build = 0.0
        self.t0 = time.monotonic()
        # reduced motion (live/motion.py): the scene's own clock, calm effects, still frames
        self.motion = motion.mode(cfg)
        self.calm = self.motion != "full"
        self.clock = motion.Clock(self.motion)
        self.lclock = motion.Clock(self.motion)         # the decorative loops' clock
        self.anim_t = 0.0
        self.still_at = None                            # still: when the last frame was drawn
        self.still_seen = None                          # ... and what it showed
        from .plugins import Layers
        self.layers = Layers()          # opt-in shader layers (layers/*.frag), GPU-budgeted
        from .traffic import Traffic
        self.traffic = Traffic(clock=lambda: self.loop_clock())   # ships decided per crossing
        self.view = (0, 0)              # the visible window's top-left in this scene (cover.py's crop)
        self.sf = 1                     # the monitor's scale: logical px for the pointer
        self.tv = None                  # the den TV (live/tv.py), once the den is drawn
        self._tv_media = None
        self._hint_prog = None

    def theme_state(self):
        """Keep a held or pinned scanner visible while its coloured textures rebuild."""
        return {k: getattr(self, k) for k in ("scan_pin", "scan_held", "scan_req", "pin_amt", "hold_amt")}

    def restore_theme_state(self, state):
        for k, v in state.items():
            setattr(self, k, v)
        if self.scan_held:
            self.hold_t = time.monotonic()       # the key's remaining hold is still bounded

    def den_tv(self):
        """The den TV: its channels on the den's screens (live/tv.py). Made with the den."""
        if self.tv is None and self.den_on():
            from .tv import TV
            self.tv = TV(self.cfg, log=lambda *a: print("bromigos-live:", *a, flush=True))
        return self.tv

    def close(self):
        if self.tv is not None:
            self.tv.close()
            self.tv = None

    def _path(self):
        bg = self.cfg["background"]
        for key in ("underlay", "underlay_fallback"):
            p = os.path.expanduser(bg.get(key, "") or "")
            if p and os.path.exists(p):
                return p
        return None

    def _sig(self):
        path = self._path()
        try:
            real = os.path.realpath(path)
            st = os.stat(real)
            return (path, real, st.st_mtime_ns, st.st_size)
        except (OSError, TypeError):
            return None

    def _load_under(self):
        """(Re)load the den by path (bromigos-wallpaper switches it). An image on
        the committed allowlist (background.den_plates, sha1 -> variant) is a den
        variant on the shared v1 plate: it gets the fitted overlays and the clean
        plate (baked steam/streaks/rows removed, redrawn live as loops). Any other
        image is drawn as is, with only the generic layers."""
        import hashlib
        from . import plate
        bg = self.cfg["background"]
        lp = self.cfg.get("loops", {})
        sig = self._sig()
        self.under_sig = sig
        if self.under is not None:
            GL.glDeleteTextures([self.under])
            self.under = None
        self.fitted = False
        self.variant = None
        self.segs = []
        if not sig:
            return
        path = sig[1]
        with open(path, "rb") as fh:
            self.variant = (bg.get("den_plates") or {}).get(hashlib.sha1(fh.read()).hexdigest())
        self.fitted = self.variant is not None
        steam = self.fitted and self.variant in (lp.get("steam") or [])
        if self.fitted and (steam or lp.get("streaks", True) or lp.get("rows", True)):
            v1 = os.path.expanduser(bg.get("den_plate", "") or "")
            img, self.segs, info = plate.clean_plate(path, v1, steam=steam, streaks=bool(lp.get("streaks", True)),
                                                    rows=bool(lp.get("rows", True)))
            if (self.w, self.h) != (plate.PLATE_W, plate.PLATE_H):
                from . import pixbuf            # any width: rows at their own stride
                raw = pixbuf.scale(img, self.w, self.h)
            else:
                raw = img
        else:
            raw, _pb = load_image(path, self.w, self.h)
            if not self.fitted:
                print("bromigos-live: wallpaper is not an approved den variant; den overlays off", flush=True)
        self.steam_on = steam
        if self.fitted:                 # the painted den in a colour theme's colours (the Wick: as is)
            raw = retint_plate(raw)
        self.under = glkit.texture_rgba(raw, self.w, self.h, GL.GL_RGB)
        from . import shipmask                  # where ships may show: open sky + the window's glass
        if self.shipmask is not None:
            GL.glDeleteTextures([self.shipmask])
        m, mw, mh = shipmask.build(self.w, self.h, self.fitted)
        self.shipmask = glkit.texture_rgba(m, mw, mh, GL.GL_RGB)
        print(f"bromigos-live: plate {os.path.basename(path)} variant={self.variant} steam={steam} "
              f"streaks={len(self.segs)}", flush=True)
        # the meter faces' own colour, so the live faces match the art
        m = DEN["meter0"]
        sx, sy = self.w / 2560.0, self.h / 1440.0
        x0, y0 = int(m[0] * sx), int(m[1] * sy)
        patch = raw[y0 + 4:y0 + int(m[3] * sy) - 4, x0 + 4:x0 + int(m[2] * sx) - 4]
        if patch.size:
            rgb = patch.reshape(-1, 3).astype(np.float32) / 255.0
            lum = rgb @ np.array([0.3, 0.59, 0.11], dtype=np.float32)
            top = rgb[lum >= np.percentile(lum, 70)]
            self.face = tuple(float(x) for x in top.mean(axis=0))

    def loop_uniforms(self, f):
        """Decorative loops. Phases come from wall-clock seconds in double precision
        (time.monotonic), each wrapped by its own period, so every loop closes exactly."""
        from . import plate
        lp = self.cfg.get("loops", {})
        sx, sy = self.w / 2560.0, self.h / 1440.0
        on = self.under is not None and self.fitted      # independent of the den-screens toggle
        T_s = float(lp.get("streak_period", 10))
        T_r = float(lp.get("row_period", 12))
        T_st = float(lp.get("steam_period", 7))
        now = self.lclock(self.loop_clock())
        f.f("u_loop", (now % T_s) / T_s, (now % T_r) / T_r, (now % T_st) / T_st, T_s)
        sk = np.zeros((16, 4), dtype=np.float32)
        sk2 = np.zeros((16, 4), dtype=np.float32)
        if on and lp.get("streaks", True):
            for i, sg in enumerate(self.segs[:16]):
                sk[i] = (sg["x0"] * sx, sg["y"] * sy, sg["x1"] * sx, sg["thick"] * sy)
                sk2[i] = (sg["amp"], 0.137 * (i + 1) + 0.71, 1.0 if sg["x0"] == 0 else 0.0, 1.0)
        f.fv("u_sk", sk, 4)
        f.fv("u_sk2", sk2, 4)
        f.fv("u_rows", np.array(plate.ROWS, dtype=np.float32) * sy, 1)
        f.f("u_rowfx", 1.0 if (on and lp.get("rows", True)) else 0.0, plate.FLOOR_X1 * sx, 926.0 * sy,
            float(lp.get("row_amp", 1.0)))
        f.f("u_steam", 1347.0 * sx, 1204.0 * sy, 47.0 * sx, 1.0 if (on and self.steam_on) else 0.0)
        f.f("u_steam2", 175.0 * sy, float(lp.get("steam_intensity", 0.55)), T_st, 100.0 * sy)

    def loop_clock(self):
        return time.monotonic()

    # ------------------------------------------------------------------ events
    def burst(self, kind=0, x=None, strength=1.0):
        if not self.cfg["rain"].get("bursts", True) or self.calm:    # reduced motion: no flashes
            return
        r = self.cfg["rain"]["region"]
        if x is None:
            x = r[0] + r[2] * (0.25 + 0.5 * ((time.monotonic() * 7.31) % 1.0))
        self.bursts[self.burst_i % 6] = (float(x), self.clock.peek(self.now()), float(strength), float(kind))
        self.burst_i += 1

    def wipe(self):
        if not self.calm:                       # reduced motion: no sweep across the screen
            self.wipe_t0 = self.clock.peek(self.now())

    def now(self):
        return time.monotonic() - self.t0

    # ------------------------------------------------------------------ build
    def rebuild(self, d):
        b = glkit.Batch(self.stage.atlas)
        on_big = self.tv is not None and self.tv.showing("big")
        if self.den_on() and not on_big:              # a media channel on the big monitor: no relay map
            x, y, w, h = self._px(DEN["big"])
            gadgets.constellation(b, d, x + w / 2, y + h / 2, min(w, h) * 0.36, space=1, labels=False, mini=True)
        self.stage.painter.upload(b)

    def den_on(self):
        return bool(self.cfg["background"].get("den", True)) and self.under is not None and self.fitted

    def _px(self, r):
        sx, sy = self.w / 2560.0, self.h / 1440.0
        return (r[0] * sx, r[1] * sy, r[2] * sx, r[3] * sy)

    # ------------------------------------------------------------------ frame
    # ---- still frames (motion = "still"; App asks every few seconds)
    def picture(self, d=None):
        """What a still frame shows, coarsely: when this changes, the frame is drawn again."""
        d = d or self.data.snapshot()
        b = lambda v, step: int((v or 0.0) / step)  # noqa: E731
        return (gadgets.health(d), gadgets.all_green(d), b(d.get("cpu"), 20), b(d.get("gpu"), 20),
                b(gadgets.traffic_level(d), 0.25), self._sig(), self.scan_req, self.scan_held, self.scan_pin)

    def still_due(self):
        now = time.monotonic()
        return (self.still_at is None or now - self.still_at >= motion.STILL_EVERY
                or self.picture() != self.still_seen)

    def still_tick(self):
        self.still_at = time.monotonic()
        self.still_seen = self.picture()

    def render(self, fbo, fps):
        t = self.clock(self.now())                # the scene's time: slower in reduced, standing in still
        self.anim_t = t
        d = self.data.snapshot()
        mono = time.monotonic()
        if mono - self.checked_at > 5.0:            # wallpaper replaced in place?
            self.checked_at = mono
            if self._sig() != self.under_sig:
                self._load_under()
                self.last_build = 0.0
        tv = self.den_tv() if self.den_on() else None
        tvu = None
        if tv is not None:
            tv.layout(self.w, self.h, {k: self._px(DEN[k]) for k in ("big", "wave", "emblem")}, self.view, self.sf)
            tvu = tv.gl()
            if tvu["tv"]["big"][0] != self._tv_media:       # the relay map steps off the big monitor, or back
                self._tv_media = tvu["tv"]["big"][0]
                self.last_build = 0.0
        if mono - self.last_build > 2.0:
            self.rebuild(d)
            self.last_build = mono
        cfg = self.cfg
        # smoothed meters + scope envelope
        a = 1.0 if self.motion == "still" else min(1.0, 4.0 / max(fps, 1))   # still: the reading as it is
        for i, k in enumerate(("cpu", "gpu")):
            self.meter_v[i] += ((d.get(k) or 0.0) / 100.0 - self.meter_v[i]) * a
        hist = np.array(d.get("rx_hist") or [0] * 48, dtype=np.float32) + np.array(d.get("tx_hist") or [0] * 48, dtype=np.float32)
        self.wave = np.clip(np.log10(1.0 + hist) / 7.0, 0.0, 1.0).astype(np.float32)
        # rain follows CPU load
        cpu = (d.get("cpu") or 0.0) / 100.0
        rc = cfg["rain"]
        density = 0.22 + 0.55 * min(cpu * 1.6, 1.0)
        speed = 0.55 + 1.6 * cpu
        # network pulses
        rx, tx = d.get("rx") or 0.0, d.get("tx") or 0.0
        lv = lambda v: max(0.0, min(1.0, math.log10(1 + v) / 7.5))  # noqa: E731
        # sweep scheduling: periodic, on demand (scan), held, pinned
        sw = cfg["sweep"]
        sweep_x, sweep_on = 0.0, 0.0
        dur = float(sw.get("duration", 5.5))
        glow_hold, glow_fade = 0.0, 0.6
        if self.calm and self.scan_req:
            # reduced motion: no beam crosses the screen; a scan fades the schematic in, for
            # a few seconds, as holding the key does
            self.scan_req = False
            self._draw_schematic(d)
            self.scan_held, self.hold_t = True, mono - 7.0
        elif self.calm:
            pass                                       # no periodic sweeps either
        elif sw.get("enabled", True) or self.scan_req or self.scan_held:
            due = self.sweep_t0 is None or t - self.sweep_t0 > float(sw.get("interval", sw.get("period", 60)))
            if self.scan_req or (due and sw.get("enabled", True)):
                self.scan_req = False
                self.sweep_t0 = t
                self._draw_schematic(d)
            if self.sweep_t0 is not None:
                st = t - self.sweep_t0
                if st < dur + 2.0:
                    sweep_on = 1.0
                    sweep_x = -200 + (self.w + 400) * (st / dur)
        if self.scan_held and mono - getattr(self, "hold_t", mono) > 15.0:
            self.scan_held = False                     # a lost key release never sticks
        # pinned / held: keep the readings live (redraw every 2 s), ease in and out
        live = self.scan_pin or self.scan_held
        if live and mono - self.schem_at > 2.0:
            self._draw_schematic(d)
        dt = max(0.0, min(t - getattr(self, "_ease_t", t), 1.0))
        self._ease_t = t
        if self.motion == "still":
            k_in = k_out = 1.0                             # still: as it is now, no fade to watch
        else:
            ease_s = 0.8 if self.calm else 0.0             # reduced motion: a slow fade, no pop
            k_in = 1.0 - math.exp(-dt / (0.18 + ease_s))
            k_out = 1.0 - math.exp(-dt / (0.2 + ease_s))   # released/unpinned: the original quick fade
        self.pin_amt += ((1.0 if self.scan_pin else 0.0) - self.pin_amt) * (k_in if self.scan_pin else k_out)
        self.hold_amt += ((1.0 if self.scan_held else 0.0) - self.hold_amt) * (k_in if self.scan_held else k_out)
        self.beam_speed = (self.w + 400) / dur
        # the space constellation on the big CRT
        p = self.stage.painter
        bx, by, bw, bh = self._px(DEN["big"])
        p.rot[1] = glkit.rot_matrix(0.0 if self.calm else t * 0.25, 0.35)     # reduced motion: it doesn't turn
        p.ctr[1] = (bx + bw / 2, by + bh / 2, min(bw, bh) * 0.36, 3.0)
        # ---- passes
        self.stage.begin_emit()
        p.draw((float(self.w), float(self.h)), t)
        bloom = self.stage.bloom(1.0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
        GL.glViewport(0, 0, self.w, self.h)
        GL.glDisable(GL.GL_BLEND)
        f = self.stage.final
        f.use()
        units = [("u_under", self.under or self.stage.emit.tex), ("u_emit", self.stage.emit.tex),
                 ("u_bloom", bloom), ("u_schem", self.schem_tex or self.stage.emit.tex),
                 ("u_ring", self.emblem.ring), ("u_flame", self.emblem.flame or self.emblem.ring),
                 ("u_shipmask", self.shipmask or self.stage.emit.tex)]
        if tvu is not None:
            for s, u in TV_UNIFORM.items():
                units += [(f"u_tvtex_{u}", tvu["tvtex"][s] or self.stage.emit.tex),
                          (f"u_osd_{u}", tvu["osd"][s] or self.stage.emit.tex)]
        for i, (name, tex) in enumerate(units):
            GL.glActiveTexture(GL.GL_TEXTURE0 + i)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            f.i(name, i)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        sx, sy = self.w / 2560.0, self.h / 1440.0
        f.f("u_res", float(self.w), float(self.h))
        f.f("u_time", t)
        f.f("u_has_under", 1.0 if self.under else 0.0)
        f.f("u_under_bright", float(cfg["background"].get("underlay_brightness", 1.0)))
        f.f("u_glow", float(cfg["background"].get("glow", 0.85)))
        r = rc["region"]
        f.f("u_rain_rect", r[0] * sx, r[1] * sy, r[2] * sx, r[3] * sy)
        f.f("u_rain", density, speed, float(rc.get("brightness", 0.55)), 1.0 if rc.get("enabled", True) else 0.0)
        f.fv("u_burst", np.array(self.bursts, dtype=np.float32), 4)
        fl = cfg["floor"]
        f.f("u_floor", fl["horizon_y"] * sy, fl["vanish_x"] * sx, float(fl.get("lane_slope", 0.98)),
            float(fl.get("lane_offset", 0.71)))
        f.f("u_floor2", fl.get("max_x", 1000) * sx, 1.0 if fl.get("draw_grid") or not self.under else 0.0,
            1.0 if (fl.get("enabled", True) and (self.fitted or not self.under)) else 0.0, 0.0)
        # Pulses move by an integrated phase, not u_time * speed: with time-times-speed a
        # change in the traffic rate jumped every pulse to a new spot mid-travel. The levels
        # are smoothed (~3 s) so lanes fade in and out instead of blinking. The phase wraps at
        # 4096 (a multiple of 4; the shader's lane speeds are quarter steps), seamlessly.
        now = time.monotonic()
        dt = min(0.25, now - getattr(self, "_net_t", now))
        self._net_t = now
        nl = getattr(self, "_net_lv", None) or [lv(rx), lv(tx)]
        a = 1.0 if self.motion == "still" else 1.0 - math.exp(-dt / 3.0)     # still: the reading as it is
        dt *= motion.RATE[self.motion]                       # the pulses' travel: the scene's time
        nl = [nl[0] + (lv(rx) - nl[0]) * a, nl[1] + (lv(tx) - nl[1]) * a]
        self._net_lv = nl
        ph = getattr(self, "_net_phase", [0.0, 0.0])
        ph = [(ph[i] + (0.10 + 0.35 * nl[i]) * dt) % 4096.0 for i in (0, 1)]
        self._net_phase = ph
        f.f("u_net", nl[0], nl[1], ph[0], ph[1])
        f.f("u_sweep", sweep_x, sweep_on, 1.0, 1.0 if self.schem_tex else 0.0)
        f.f("u_scan", glow_hold, glow_fade, self.hold_amt, self.pin_amt)
        f.f("u_scan2", self.beam_speed, 0.0, 0.0, 0.0)
        f.f("u_schem_rect", *self._px(DEN["schem"]))
        wp = (t - self.wipe_t0) / 0.45
        f.f("u_wipe", wp if (0 <= wp <= 1 and cfg["events"].get("workspace_wipe", True) and not self.calm) else -1.0)
        f.f("u_calm", 1.0 if self.calm else 0.0)
        f.f("u_dark", 0.0)
        # den screens
        burst = 1.0 if (t % 17.0) < 0.18 and not self.calm else 0.0    # reduced motion: no static bursts
        f.f("u_den", 1.0 if self.den_on() else 0.0, 0.0 if self.calm else -t * TAU / 24.0, burst, 0.0)
        f.f("u_wave_rect", *self._px(DEN["wave"]))
        f.fv("u_wave", self.wave, 1)
        f.f("u_emb_rect", *self._px(DEN["emblem"]))
        f.f("u_big_rect", *self._px(DEN["big"]))
        f.f("u_meter0", *self._px(DEN["meter0"]))
        f.f("u_meter1", *self._px(DEN["meter1"]))
        f.f("u_meter_v", *self.meter_v)
        f.f("u_meter_face", *self.face)
        for s, u in TV_UNIFORM.items():
            f.f(f"u_tv_{u}", *(tvu["tv"][s] if tvu else (0.0, 0.0, 1.0, 0.0)))
            f.f(f"u_tune_{u}", *(tvu["tune"][s] if tvu else (0.0, 0.0, 0.0, 0.0)))
        sp = cfg.get("space", {})
        hl = gadgets.health(d) if sp.get("health_tint", True) else 0
        green = gadgets.all_green(d) and sp.get("relay_beam", True)
        rps = ((d.get("cluster") or {}).get("traefik") or {}).get("rpsNow") or 0.0
        # ships are planned across the whole sky and shown only through live/shipmask.py's mask:
        # the open sky left of the den and the den's window glass (behind the wall, frame and desk)
        ship_rect = (0.0, 34.0 * sy, 2400.0 * sx, (fl["horizon_y"] - 34.0) * sy)   # the sky rect, as before
        from .shipmask import FOCUS
        focus = [(x * sx, y * sy, w_ * sx, h_ * sy) for x, y, w_, h_ in FOCUS] if self.fitted else None
        ships, ships2, lvl_smooth = self.traffic.uniforms(          # reduced motion: no craft cross
            gadgets.traffic_level(d) if sp.get("traffic", True) and not self.calm else -1.0, ship_rect, focus)
        f.fv("u_ship", ships, 4)
        f.fv("u_ship2", ships2, 4)
        f.f("u_ship_rect", *ship_rect)
        f.f("u_shipmask_on", 1.0 if self.shipmask else 0.0)
        f.f("u_space", 1.0 if sp.get("stars", True) else 0.0, lvl_smooth, 1.0 if green else 0.0, float(hl))
        f.f("u_space_rect", 0.0, 34.0 * sy, 2400.0 * sx, (fl["horizon_y"] - 34.0) * sy)
        f.f("u_planet", 0.0, 0.0, 1.0, 0.0)
        f.f("u_sun", 0.0, 0.0, 0.0, 0.0)
        bx0, by0 = 2000.0 * sx, 370.0 * sy
        f.f("u_beam", bx0, by0, -2.5, 0.12 + min(rps, 6.0) / 12.0)
        self.loop_uniforms(f)
        self.stage.fs.draw()
        self.layers.draw(fbo, self.w, self.h, t, d)
        if tv is not None:
            self._draw_hint(fbo, tv)

    _HINT_VS = """#version 330 core
layout(location = 0) in vec2 a_pos;
uniform vec4 u_rect;   // x y w h px, top-left origin
uniform vec2 u_res;
out vec2 v_uv;
void main() {
    vec2 p = u_rect.xy + a_pos * u_rect.zw;
    v_uv = a_pos;
    gl_Position = vec4(p.x / u_res.x * 2.0 - 1.0, 1.0 - p.y / u_res.y * 2.0, 0.0, 1.0);
}"""
    _HINT_FS = """#version 330 core
in vec2 v_uv;
out vec4 o;
uniform sampler2D u_tex;
void main() { o = texture(u_tex, v_uv); }"""

    def _draw_hint(self, fbo, tv):
        """The den TV's hover hint, over the finished frame (premultiplied)."""
        got = tv.hint_texture(self.sf)
        if not got:
            return
        tex, (x, y, w, h) = got
        if self._hint_prog is None:
            self._hint_prog = glkit.Program(self._HINT_VS, self._HINT_FS)
            self._hint_vao = GL.glGenVertexArrays(1)
            self._hint_vbo = GL.glGenBuffers(1)
            GL.glBindVertexArray(self._hint_vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._hint_vbo)
            quad = np.array([0, 0, 1, 0, 0, 1, 1, 1], dtype=np.float32)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad, GL.GL_STATIC_DRAW)
            GL.glEnableVertexAttribArray(0)
            GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
            GL.glBindVertexArray(0)
        vx, vy = self.view
        p = self._hint_prog
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
        GL.glViewport(0, 0, self.w, self.h)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        p.use()
        p.f("u_rect", x * self.sf + vx, y * self.sf + vy, w * self.sf, h * self.sf)
        p.f("u_res", float(self.w), float(self.h))
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        p.i("u_tex", 0)
        GL.glBindVertexArray(self._hint_vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glBindVertexArray(0)
        GL.glDisable(GL.GL_BLEND)

    # ---- scanner control (bromigos-live scan / scan-pin / scan-hold on|off)
    def scan(self):
        self.scan_req = True

    def scan_pin_toggle(self):
        self.scan_pin = not self.scan_pin
        if self.scan_pin:
            self.schem_at = 0.0
        return self.scan_pin

    def scan_hold(self, on):
        if on and not self.scan_held:
            self.scan_req = True
        self.scan_held = on
        self.hold_t = time.monotonic()

    def _draw_schematic(self, d):
        self.schem_at = time.monotonic()
        surf = schematic.draw(d, self.st)
        if self.schem_tex is None:
            self.schem_tex = glkit.texture_from_cairo(surf)
        else:
            glkit.update_texture_from_cairo(self.schem_tex, surf)
