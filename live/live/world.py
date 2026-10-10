"""Worlds: a theme's whole live scene, drawn instead of the Wick's den.

When the current theme (bromigOS `bromigos theme set <name>`, rendered into
~/.local/state/bromigos/theme/current/) has `live/world.toml`, the background is that
world: layered art with parallax, a water plane, effects and actors, every one bound to
a real signal. Without it (the Wick) the den (live/scene.py) is drawn exactly as before.

The format is documented in bromigOS docs/theming.md ("`live/world.toml`") and in
docs/ELEMENTS.md ("Worlds"); in short, paths relative to the theme directory:

  [camera] [clock] [water]       how the layers sway, the light by the hour, the water
  [[layers]]                     art files back to front: depth, parallax, sky/water/fog
  [[effects]]                    reusable effect blocks, each bound to a signal
  [[actors]]                     creatures and craft (live/actors.py), bound to signals;
                                 kind = "flyby": craft crossing the sky now and then
  [sounds] [rollcall]            ambient cues by the user's activity; the login roll call

Signals (World.signals): cpu, gpu, mem, net, net_rx, net_tx, health (0/1/2), lab_green,
storm, lab (a lab snapshot), fills (the fills feed answers), ingress, user
(working/dozing/asleep), activity, vector, agents, agents_working
(herdr's working agents + busy Claude Code sessions outside herdr), models (the homelab's
local models generating, 0..1: LiteLLM requests and output tokens), hour, daylight,
moon_phase, tide. Events: notify, critical, fill, fill_win, fill_loss, fill_open,
lab_alert, login (the roll call), flyby[:<craft id>] (a pass now, for testing).

Frame: every layer and actor group shallower than the water is drawn into the back
target; the water/effects pass (shaders/world.frag) composes the frame from it (the
mirror reflects it); deeper layers and actors are drawn over that. Pause rules are the
den's (App.refresh_state): the world simply isn't rendered while paused.
"""
import math
import os
import random
import time
import tomllib

import numpy as np
from OpenGL import GL

from . import actors as A
from . import gadgets, glkit, motion, skyclock
from .activity import get as activity

PLATE_W, PLATE_H = 2560.0, 1440.0
STATE = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
CURRENT = os.path.join(STATE, "bromigos", "theme", "current")


def log(*a):
    print("bromigos-live: world:", *a, flush=True)


# ------------------------------------------------------------------ finding the world
def world_file(cfg):
    """The world.toml in force, or None (the den). $BROMIGOS_WORLD (a theme directory or a
    world.toml) wins, then [world] dir, then the current theme."""
    w = cfg.get("world", {})
    if not w.get("enabled", True):
        return None
    for base in (os.environ.get("BROMIGOS_WORLD"), w.get("dir") or None, CURRENT):
        if not base:
            continue
        base = os.path.expanduser(base)
        p = base if base.endswith(".toml") else os.path.join(base, "live", "world.toml")
        if os.path.isfile(p):
            return p
    return None


def signature(cfg):
    """Changes when the world to draw changes (a theme switch, an edited world.toml)."""
    p = world_file(cfg)
    if not p:
        return None
    try:
        real = os.path.realpath(p)
        st = os.stat(real)
        return (real, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def make_scene(cfg, data, w, h):
    """The background renderer: the theme's world, or the Wick's den, fitted to the screen
    (cover.py: a screen that isn't 16:9 gets the 16:9 scene cropped, never stretched). A
    world that fails to load falls back to the den (and says why in the log)."""
    from . import cover
    p = world_file(cfg)
    if p:
        try:
            return cover.wrap(lambda cw, ch: World(cfg, data, cw, ch, p), w, h)
        except Exception as e:
            import traceback
            traceback.print_exc()
            log(f"{p} failed to load ({type(e).__name__}: {e}); drawing the den")
    from .scene import Background
    return cover.wrap(lambda cw, ch: Background(cfg, data, cw, ch), w, h)


# ------------------------------------------------------------------ images
def load_rgba(path):
    """(premultiplied RGBA uint8 array h x w x 4, w, h)."""
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im, dtype=np.uint8).copy()
    al = a[..., 3:4].astype(np.uint16)
    a[..., :3] = (a[..., :3].astype(np.uint16) * al // 255).astype(np.uint8)
    return a, im.width, im.height


def sprite_frames(root, rel):
    """A sprite's frame files: <rel>.webp (or .png), or <rel>/NN.webp in order."""
    base = os.path.join(root, rel)
    for ext in (".webp", ".png"):
        if os.path.isfile(base + ext):
            return [base + ext]
    if os.path.isfile(base):
        return [base]
    if os.path.isdir(base):
        fs = sorted(f for f in os.listdir(base) if f.lower().endswith((".webp", ".png")))
        return [os.path.join(base, f) for f in fs]
    return []


def build_atlas(root, rels, width=4096, pad=3, loops=None, sync=False, crops=None):
    """Pack every sprite's frames into one premultiplied atlas. Returns (pixels, w, h,
    {rel: actors.Sprite}). A missing sprite becomes a grey block and is logged. A sprite
    that names a video file is a loop (live/videoloop.py), drawn from its own texture."""
    from .videoloop import VideoLoop, is_video
    imgs = {}
    videos = {}
    for rel in rels:
        if is_video(rel):
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                o = (loops or {}).get(rel, {})
                once = bool(o.get("once", "/clips/" in rel))      # live/clips/: one-shot clips
                v = VideoLoop(path, o.get("alpha"), o.get("fps"), float(o.get("scale", 1.0)), sync=sync, once=once,
                              mask=os.path.join(root, o["mask"]) if o.get("mask") else None)
                videos[rel] = A.Sprite([(0.0, 0.0, 1.0, 1.0, v.aspect)], video=v)
                continue
            log(f"loop {rel} not found; a placeholder block stands in")
        files = sprite_frames(root, rel)
        if not files:
            log(f"sprite {rel} not found; a placeholder block stands in")
            blk = np.zeros((64, 48, 4), np.uint8)
            blk[...] = (60, 60, 60, 255)
            imgs[rel] = [blk]
            continue
        frames = [load_rgba(f)[0] for f in files]
        crop = (crops or {}).get(rel)
        if crop:                                  # a full-frame mask, cut to its piece's rect
            x, y, w, h = (int(round(v)) for v in crop)
            frames = [f[y:y + h, x:x + w].copy() if f.shape[:2] == (int(PLATE_H), int(PLATE_W)) else f for f in frames]
        imgs[rel] = frames
    x = y = row = 0
    place = {}
    for rel, frames in imgs.items():
        for i, im in enumerate(frames):
            h, w = im.shape[:2]
            if x + w + pad > width:
                x, y, row = 0, y + row + pad, 0
            place[(rel, i)] = (x, y, w, h)
            x += w + pad
            row = max(row, h)
    H = max(64, y + row + pad)
    atlas = np.zeros((H, width, 4), np.uint8)
    out = {}
    for rel, frames in imgs.items():
        fl = []
        for i, im in enumerate(frames):
            px, py, w, h = place[(rel, i)]
            atlas[py:py + h, px:px + w] = im
            fl.append(((px + 0.5) / width, (py + 0.5) / H, (px + w - 0.5) / width, (py + h - 0.5) / H, w / h))
        out[rel] = A.Sprite(fl)
    out.update(videos)
    return atlas, width, H, out


# ------------------------------------------------------------------ the world
class Layer:
    def __init__(self, t, root, loops=None, sync=False):
        self.t = t
        self.id = t.get("id") or os.path.splitext(os.path.basename(t.get("file") or t.get("video", "layer")))[0]
        self.depth = float(t.get("depth", 0))
        self.parallax = float(t.get("parallax", 0.0))
        self.sky = bool(t.get("sky", False))
        self.water = bool(t.get("water", False))
        fog = t.get("fog", False)                 # true, or how much of the fog reaches it (0..1)
        self.fog = float(fog) if not isinstance(fog, bool) else (1.0 if fog else 0.0)
        self.video = None
        if t.get("file"):                         # the art (or a video's poster, until it plays)
            px, w, h = load_rgba(os.path.join(root, t["file"]))
        else:
            px, w, h = np.zeros((2, 2, 4), np.uint8), 2, 2
        self.tex = glkit.texture_rgba(np.ascontiguousarray(px), w, h, GL.GL_RGBA)
        if t.get("video"):                        # a living backdrop: a seamless video loop
            from .videoloop import VideoLoop
            o = (loops or {}).get(t["video"], {})
            self.video = VideoLoop(os.path.join(root, t["video"]), o.get("alpha", t.get("alpha")),
                                   o.get("fps"), float(o.get("scale", t.get("scale", 1.0))), sync=sync)


class Effects:
    """The world's [[effects]], by type (one block of each type per world)."""

    def __init__(self, world, items):
        self.world = world
        self.by = {}
        for e in items:
            self.by[e["type"]] = e
        self.strike_at = None
        self.strike = None          # (t0, x, seed)
        self.line_taut_until = -1.0
        self.line_jerk = 0.0
        self.beam_phase = 0.0
        self.mist_phase = 0.0
        self.swell_phase = 0.0

    def has(self, kind):
        return kind in self.by

    def defines(self):
        d = []
        for k, flag in (("rain", "FX_RAIN"), ("mist", "FX_MIST"),
                        ("line", "FX_LINE"), ("beam", "FX_BEAM"), ("spray", "FX_SPRAY"), ("rays", "FX_RAYS")):
            if k in self.by:
                d.append(flag)
        return d


class World:
    is_world = True

    def __init__(self, cfg, data, w, h, path):
        self.cfg, self.data = cfg, data
        self.w, self.h = w, h
        self.path = path
        self.root = os.path.dirname(os.path.dirname(os.path.abspath(path)))   # <theme>/live/world.toml
        with open(path, "rb") as f:
            self.spec = tomllib.load(f)
        sp = self.spec
        # where a screen that isn't 16:9 keeps its window on the scene (cover.py), plate px
        self.focus = tuple((sp.get("view") or {}).get("focus") or ()) or None
        self.name = sp.get("name", os.path.basename(self.root))
        self.sx, self.sy = w / PLATE_W, h / PLATE_H
        t0 = time.monotonic()
        self.sync = bool(os.environ.get("BROMIGOS_WORLD_SYNC"))     # offscreen: wait for each video frame
        loops = sp.get("loops", {})
        self.layers = sorted((Layer(L, self.root, loops, self.sync) for L in sp.get("layers", [])), key=lambda L: L.depth)
        self.water_layer = next((L for L in self.layers if L.water), None)
        self.sky_layer = next((L for L in self.layers if L.sky), None)
        self.sky_luma = None                      # the sky layer's luminance at 1/8 size: what hides a flyby's lamps
        if self.sky_layer is not None and self.sky_layer.t.get("file"):
            from PIL import Image
            im = Image.open(os.path.join(self.root, self.sky_layer.t["file"])).convert("L")
            self.sky_luma = np.asarray(im.resize((max(1, im.width // 8), max(1, im.height // 8)), Image.BILINEAR),
                                       dtype=np.float32) / 255.0
        self.water = sp.get("water", {})
        self.water_depth = self.water_layer.depth if self.water_layer else 1e9
        self.split = self.water.get("mode", "mirror") == "split"
        self.surface_y = float(self.water.get("line", 900))
        self.fx = Effects(self, sp.get("effects", []))
        # actors and their sprites
        rels = []
        for a in sp.get("actors", []):
            if a.get("sprite"):
                rels.append(a["sprite"])
            rels += [c["sprite"] for c in a.get("craft", []) if c.get("sprite")]
            if a.get("emissive"):
                rels.append(a["emissive"])
            rels += [a[k] for k in ("front_sprite",) if a.get(k)]
            rels += list(a.get("sprites") or [])        # a crowd's own art per member (actors.py, "sprites")
            if isinstance(a.get("tow"), dict) and a["tow"].get("sprite"):
                rels.append(a["tow"]["sprite"])          # a trawler's net (actors.py, "tow")
            rels += list((a.get("poses") or {}).values())
            rels += [ev["sprite"] for ev in (a.get("events") or {}).values() if ev.get("sprite")]
            for sl in a.get("slots", []):
                rels += [sl[k] for k in ("sprite", "emissive", "rise_clip", "submerge_clip") if sl.get(k)]
                for st in (sl.get("states") or {}).values():
                    rels += [st[k] for k in ("sprite", "clip") if st.get(k)]
            for st in (a.get("states") or {}).values():
                if isinstance(st, dict) and st.get("clip"):
                    rels.append(st["clip"])
            for v in a.get("on", []):
                if v.get("sprite"):
                    rels.append(v["sprite"])
            for st in (a.get("states") or {}).values():
                if isinstance(st, dict) and st.get("sprite"):
                    rels.append(st["sprite"])
        rels = list(dict.fromkeys(rels))
        crops = {}
        for a in sp.get("actors", []):
            for sl in a.get("slots", []):
                if sl.get("emissive") and isinstance(sl.get("patch"), (list, tuple)):
                    crops[sl["emissive"]] = sl["patch"]
        # an additive actor's loop is glow art on black: its coverage is its brightness, so
        # fog and the water's tint stay on the creature, not on the frame around it
        loops = {k: dict(v) for k, v in loops.items()}
        for a in sp.get("actors", []):
            if a.get("blend") == "add":
                # its one sprite, or a crowd's own art per member (sprites = [...]): all glow art
                for spr in [a.get("sprite")] + list(a.get("sprites") or []):
                    if isinstance(spr, str):
                        loops.setdefault(spr, {}).setdefault("alpha", "luma")
        atlas, aw, ah, sprites = build_atlas(self.root, rels, loops=loops, sync=self.sync, crops=crops)
        self.videos = [s.video for s in sprites.values() if s.video] + [L.video for L in self.layers if L.video]
        self.atlas = glkit.texture_rgba(np.ascontiguousarray(atlas), aw, ah, GL.GL_RGBA)
        self.manifest = {}                        # live/clips/manifest.toml: where each clip's patch sits
        mf = os.path.join(self.root, "live", "clips", "manifest.toml")
        if os.path.isfile(mf):
            with open(mf, "rb") as f:
                self.manifest = tomllib.load(f)
        self.defs = [A.Def(a, sprites, self) for a in sp.get("actors", [])]
        self.actors = A.Actors(self.defs)
        # reduced motion (live/motion.py): the scene's own clock; calm lights; still frames
        self.motion = motion.mode(cfg)
        self.calm = self.motion != "full"
        self.clock = motion.Clock(self.motion)
        self.actors.calm, self.actors.still = self.calm, self.motion == "still"
        self.settle = False                       # still: the next frame moves the scene on first
        self.still_at = None
        self.still_seen = None
        self.keeper = next((d for d in self.defs if d.kind == "keeper"), None)
        self.fireflies = None
        if self.fx.has("fireflies"):
            from .fireflies import Fireflies
            self.fireflies = Fireflies(self.fx.by["fireflies"], self.water.get("line", 900))
            self.fireflies.calm = self.calm
        # GL
        defs = self.fx.defines() + (["WATER_SPLIT"] if self.split else [])
        src = glkit.read_shader("world.frag").replace(
            "#version 330 core", "#version 330 core\n" + "".join(f"#define {x}\n" for x in defs), 1)
        self.p_world = glkit.Program(glkit.read_shader("fs.vert"), src)
        self.p_layer = glkit.program("fs.vert", "world_layer.frag")
        self.p_world.cache, self.p_layer.cache = {}, {}
        self.sprites_gl = []
        self.glows_gl = []
        self.fs = glkit.Fullscreen()
        self.back = glkit.Target(w, h)
        self.t0 = time.monotonic()
        self.t_last = None
        self.cam = [0.0, 0.0]
        self.sig = {}
        self.smooth = {}
        self.forced = {}
        self.spray = [(0.0, 0.0, -10.0, 0.0)] * 6
        self.spray_i = 0
        self.rings = [(0.0, 0.0, -10.0, 0.0)] * 8        # ripple rings spreading on the water
        self.ring_i = 0
        self.bubbles = [(0.0, 0.0, -10.0, 0.0)] * 8      # bubbles rising and popping at the surface
        self.bubble_i = 0
        self.line_hook = None
        self.queue = []             # (t, event) staggered fills
        self.sound_next = {}
        from .worldfeed import Feed
        self.feed = Feed(data)
        self.feed.start()
        act = activity()
        act.idle_after = float(cfg.get("world", {}).get("idle_after", 90))
        act.start(cfg["general"].get("monitor", ""))     # app.py resolved it (lib/bromigos_monitors)
        log(f"{self.name}: {len(self.layers)} layers, {len(self.defs)} actors, effects "
            f"{sorted(self.fx.by)} ({(time.monotonic() - t0) * 1000:.0f} ms) from {self.root}")

    # ---- the den's hooks, for App (the world has no scanner or rain bursts)
    def now(self):
        return time.monotonic() - self.t0

    def loop_clock(self):
        return time.monotonic()

    def burst(self, kind=0, x=None, strength=1.0):
        self.event({0: "notify", 1: "fill", 2: "critical"}.get(int(kind), "notify"))

    def wipe(self):
        pass

    def scan(self):
        pass

    def scan_pin_toggle(self):
        return False

    def scan_hold(self, on):
        pass

    def close(self):
        for v in self.videos:
            v.close()
        self.feed.halt()
        activity().halt()

    # ---- events
    def event(self, name, **info):
        t = self.clock.peek(self.now())          # the scene's time (slower in reduced, standing in still)
        if self.motion == "still":
            return                                # a still picture: events show as their states do
        if name == "fill":
            results = info.get("results") or ["open"]
            for i, r in enumerate(results[:3]):
                self.queue.append((t + i * 2.8, "fill_" + str(r)))
            return
        if name == "login":
            self.actors.event("rollcall", t)
            rc = self.spec.get("rollcall", {})
            if rc.get("sound"):
                self._play(rc["sound"])
            return
        self._fire(name, t)

    def _fire(self, name, t):
        if name.startswith("fill_"):
            self.fx.line_taut_until = t + 2.6
            self.fx.line_jerk = t
            if name == "fill_open":
                end = self.line_end()
                self._spray(end[0], end[1], t, 0.25)
        self.actors.event(name, t + (1.1 if name in ("fill_win", "fill_loss") else 0.0))

    def _spray(self, x, y, t, s):
        self.spray[self.spray_i % 6] = (x * self.sx, y * self.sy, t, s)
        self.spray_i += 1

    def _ring(self, x, y, t, s):
        self.rings[self.ring_i % 8] = (x * self.sx, y * self.sy, t, s)
        self.ring_i += 1

    def _bubble(self, x, y, t, s):
        self.bubbles[self.bubble_i % 8] = (x * self.sx, y * self.sy, t, s)
        self.bubble_i += 1

    # ---- the control socket: bromigos-live ctl world …
    def command(self, verb, args):
        if verb in ("", "state"):
            return self.describe()
        if verb == "event":
            name, *rest = (args or "notify").split()
            if name == "fill":
                self.event("fill", results=rest or ["win"])
            else:
                self.event(name)
            return f"event {name}"
        if verb == "set":                          # set <signal> <value>: hold a signal (testing)
            k, _, v = args.partition(" ")
            if k == "agents":                      # agents a:working,b:needs_you,c:finished[,d:error]
                out = []
                for item in filter(None, v.replace(" ", ",").split(",")):
                    key, _, st = item.partition(":")
                    out.append({"key": key, "status": "needs_you" if st == "error" else (st or "working"),
                                "error": st == "error", "cwd": "", "name": key})
                self.forced["agents"] = out
                return f"agents = {len(out)}"
            try:
                self.forced[k] = float(v)
            except ValueError:
                self.forced[k] = v
            return f"{k} = {self.forced[k]}"
        if verb == "clear":
            self.forced.clear()
            return "signals live"
        if verb == "rollcall":
            self.event("login")
            return "roll call"
        if verb == "still":                        # motion = "still": draw a new still frame now
            self.still_tick()
            return f"still frame (motion {self.motion})"
        return "world verbs: state, event <name> [win|loss|open], set <signal> <value>, clear, rollcall, still"

    def describe(self):
        s = self.sig
        n = {}
        for inst in self.actors.insts.values():
            n[inst.d.id] = n.get(inst.d.id, 0) + 1
        return (f"world {self.name} ({self.root})" + (f" motion {self.motion}" if self.calm else "") + "\n"
                f"user={s.get('user')} vector={s.get('vector')} health={s.get('health')} cpu={s.get('cpu', 0):.2f} "
                f"net={s.get('net', 0):.2f} hour={s.get('hour', 0):.2f} moon={s.get('moon_phase', 0):.2f} "
                f"tide={s.get('tide', 0):+.2f}\n"
                f"agents={len(s.get('agents') or [])} actors: " + ", ".join(f"{k}×{v}" for k, v in sorted(n.items()))
                + (f"\nforced: {self.forced}" if self.forced else "")
                + self._describe_agents())

    def _describe_agents(self):
        """One line per agent creature: whose it is, its state, where it swims (plate px)."""
        names = {str(a.get("key")): (a.get("name") or os.path.basename(a.get("cwd") or "") or a.get("key"))
                 for a in (self.sig.get("agents") or [])}
        rows = []
        for (did, key), inst in sorted(self.actors.insts.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
            if inst.d.t.get("kind") != "agents":
                continue
            far = " far" if "zscale" in inst.extra else ""
            rows.append(f"  {did} {names.get(str(key), key)}: {inst.state}{far} at ({inst.x:.0f}, {inst.y:.0f})")
        return ("\n" + "\n".join(rows)) if rows else ""

    # ---- signals
    def _ease(self, key, v, dt, tau):
        if self.motion == "still":                # a still frame shows the reading as it is
            self.smooth[key] = v
            return v
        cur = self.smooth.get(key, v)
        cur = cur + (v - cur) * (1.0 - math.exp(-dt / tau)) if tau > 0 else v
        self.smooth[key] = cur
        return cur

    def signals(self, d, dt):
        f = self.forced
        act = activity()
        lv = lambda v: max(0.0, min(1.0, math.log10(1.0 + v) / 7.3))  # noqa: E731
        hour = float(f.get("hour", skyclock.local_hour()))
        ph = float(f.get("moon_phase", skyclock.phase()))
        health = int(f.get("health", gadgets.health(d)))
        s = {
            "cpu": self._ease("cpu", float(f.get("cpu", (d.get("cpu") or 0.0) / 100.0)), dt, 3.0),
            "gpu": (d.get("gpu") or 0.0) / 100.0,
            "mem": (d.get("mem") or 0.0) / 100.0,
            "net": self._ease("net", float(f.get("net", gadgets.traffic_level(d))), dt, 4.0),
            "net_rx": self._ease("rx", float(f.get("net_rx", lv(d.get("rx") or 0.0))), dt, 4.0),
            "net_tx": self._ease("tx", float(f.get("net_tx", lv(d.get("tx") or 0.0))), dt, 4.0),
            "health": health,
            "lab_green": bool(f.get("lab_green", gadgets.all_green(d))) if "lab_green" not in f else bool(float(f["lab_green"])),
            "storm": 1.0 if health >= 2 else 0.0,
            "fills": bool(float(f["fills"])) if "fills" in f else d.get("fills_total") is not None,
            "lab": bool(float(f["lab"])) if "lab" in f else bool(d.get("cluster_ok") or d.get("cluster")),
            "ingress": float(f.get("ingress", ((d.get("cluster") or {}).get("traefik") or {}).get("rpsNow") or 0.0)),
            "user": str(f.get("user", act.state())),
            "vector": str(f.get("vector", self.feed.vector)),
            "hour": hour,
            "moon_phase": ph,
            "tide": skyclock.tide(hour, ph),
        }
        s["activity"] = {"working": 1.0, "dozing": 0.4, "asleep": 0.0}.get(s["user"], 1.0)
        if "agents" in f:
            s["agents"] = f["agents"]
        else:
            s["agents"] = self.feed.agents
        if "agents_working" in f:
            s["agents_working"] = float(f["agents_working"])
        elif "agents" in f:
            s["agents_working"] = float(sum(1 for a in f["agents"] if a.get("status") == "working"))
        else:
            s["agents_working"] = float(self.feed.working)
        m = self.feed.models
        if m is None:                            # no Prometheus: the lab snapshot's requests/min
            m = min(1.0, (((d.get("cluster") or {}).get("ai") or {}).get("rpmNow") or 0.0) / 30.0)
        s["models"] = float(f.get("models", m))
        return s

    def _rain(self, sig, dt):
        """The rain effect's level, 0..1. Either one signal mapped from..full, or a `mix` of
        terms {signal, from, full, floor, max}: each 0 at or below `from`, else `floor` rising
        to `max` at `full`; terms combine like layers of cloud (1 - product of 1 - term), so
        drizzle + models + CPU build toward a downpour. `onset`/`tail` (s) ease it in and out
        so the weather never flickers."""
        e = self.fx.by.get("rain")
        if not e:
            return 0.0
        def term(v, lo, hi, floor=0.0, top=1.0):
            if v <= lo:
                return 0.0
            return floor + (top - floor) * max(0.0, min(1.0, (v - lo) / max(hi - lo, 1e-3)))
        mix = e.get("mix")
        if mix:
            dry = 1.0
            for m in mix:
                v = float(sig.get(m.get("signal", "cpu"), 0.0) or 0.0)
                dry *= 1.0 - term(v, float(m.get("from", 0.0)), float(m.get("full", 1.0)),
                                  float(m.get("floor", 0.0)), float(m.get("max", 1.0)))
            want = 1.0 - dry
        else:
            v = float(sig.get(e.get("signal", "cpu"), 0.0) or 0.0)
            want = term(v, float(e.get("from", 0.3)), float(e.get("full", 0.85)))
        onset, tail = float(e.get("onset", 0.0)), float(e.get("tail", 0.0))
        if self.calm:                              # reduced motion: the weather turns slowly, never at once
            onset, tail = max(onset, 8.0), max(tail, 8.0)
        if (onset <= 0.0 and tail <= 0.0) or self.motion == "still":
            self.smooth["rain"] = want
            return want
        cur = self.smooth.get("rain", want)
        tau = onset if want > cur else tail
        cur = cur + (want - cur) * (1.0 - math.exp(-dt / tau)) if tau > 0 and dt > 0 else want
        self.smooth["rain"] = cur
        return cur

    def moon_xy(self, sig):
        """The moon's place in its window (0..1 across, 0..1 up), from the clock or held."""
        if "moon_x" in self.forced:
            return float(self.forced["moon_x"]), float(self.forced.get("moon_y", 0.8))
        return skyclock.moon_place(sig["hour"], sig["moon_phase"])

    # ---- geometry helpers (plate px)
    def line_tip(self):
        """The keeper's rod tip (its `rod` anchor for the frame showing), plate px."""
        inst = self.actors.insts.get((self.keeper.id, "keeper")) if self.keeper else None
        pl = getattr(inst, "placed", None) if inst else None
        anc = (self.keeper.anchors.get("rod") if self.keeper else None)
        if not pl or not anc:
            e = self.fx.by.get("line", {})
            return tuple(e.get("tip", (1400, 760)))
        x, base, w, h, rot, fi = pl
        u, v = anc[fi % len(anc)]
        if w < 0:
            u = 1.0 - u
        lx, ly = (u - 0.5) * abs(w), -(1.0 - v) * h
        ca, sa = math.cos(rot), math.sin(rot)
        return (x + lx * ca - ly * sa, base + lx * sa + ly * ca)

    def sky_cover(self, x, y, luma):
        """How much of the sky layer's lit cloud is in front of plate point (x, y): 0..1, the
        moon's disc clear (luma = [cloud from, cloud full, moon from, moon full])."""
        a = self.sky_luma
        if a is None:
            return 0.0
        h, w = a.shape
        l = float(a[min(h - 1, max(0, int(y * h / PLATE_H))), min(w - 1, max(0, int(x * w / PLATE_W)))])
        lu = list(luma) + [2.0, 3.0]

        def ss(e0, e1, v):
            v = max(0.0, min(1.0, (v - e0) / max(e1 - e0, 1e-6)))
            return v * v * (3 - 2 * v)
        return ss(lu[0], lu[1], l) * (1.0 - ss(lu[2], lu[3], l))

    def line_end(self):
        e = self.fx.by.get("line", {})
        return tuple(e.get("float", (1200, 960)))

    # ---- still frames (motion = "still"; App asks every few seconds)
    def picture(self):
        """What a still frame shows, coarsely: when this changes the frame is drawn again."""
        d = self.data.snapshot()
        f = self.forced
        act = activity()
        agents = f.get("agents", self.feed.agents) or []
        hour = float(f.get("hour", skyclock.local_hour()))
        e = self.fx.by.get("rain")
        rain = 0.0
        if e:
            sig = self.signals(d, 1.0)
            rain = round(self._rain(sig, 1.0) * 4)
        clips = any(i.clip is not None and i.clip.video is not None and not i.clip.video.finished()
                    and not i.clip_hold for i in self.actors.insts.values())
        return (tuple((str(a.get("key")), a.get("status"), bool(a.get("error"))) for a in agents),
                str(f.get("user", act.state())), str(f.get("vector", self.feed.vector)),
                int(f.get("health", gadgets.health(d))), bool(gadgets.all_green(d)), rain,
                int(hour * 4), round(float(f.get("moon_phase", skyclock.phase())) * 8), clips,
                repr(sorted((k, str(v)) for k, v in f.items() if k != "agents")))

    def still_due(self):
        now = time.monotonic()
        return (self.still_at is None or now - self.still_at >= motion.STILL_EVERY
                or self.picture() != self.still_seen)

    def still_tick(self):
        """The next frame is a new still: the scene's time moves on by STILL_STEP first (in
        simulation steps, nothing drawn), so whatever was rising or going under has landed."""
        self.settle = True
        self.still_at = time.monotonic()
        self.still_seen = self.picture()

    # ---- frame
    def render(self, fbo, fps):
        d = self.data.snapshot()
        if self.settle or (self.motion == "still" and self.t_last is None):   # still: the first frame settles too
            self.settle = False
            end = self.clock.step(motion.STILL_STEP)
            for off, sub in motion.still_steps():
                self._simulate(end + off, sub, d, settling=True)
            self.t_last = end
        t = self.clock(self.now())                # the scene's time: slower in reduced, standing in still
        dt = 0.0 if self.t_last is None else max(0.0, min(t - self.t_last, 0.1))
        self.t_last = t
        sprites, glows, wakes, sig = self._simulate(t, dt, d)
        self._draw(fbo, t, sig, sprites, glows, wakes)

    def _simulate(self, t, dt, d, settling=False):
        """Everything but drawing: the signals, the weather, the actors, the loops, the light.
        Returns (sprites, glows, wakes, signals)."""
        sig = self.signals(d, dt if dt > 0 else 1.0)
        self.sig = sig
        self.rain_level = self._rain(sig, dt)
        self.frame_dt = dt
        self._advanced = {}
        if self.videos and int(t) % 10 == 0:
            mono = time.monotonic()
            for v in self.videos:
                v.idle_check(mono)
        while self.queue and self.queue[0][0] <= t:
            _, name = self.queue.pop(0)
            self._fire(name, t)
        # the water line follows the tide
        wl = float(self.water.get("line", 900))
        if self.water.get("tide") == "moon":
            wl -= sig["tide"] * float(self.water.get("tide_range", 12))
        self.surface_y = wl
        self.line_hook = None
        sprites, glows, wakes = self.actors.update(t, dt, sig)
        for L in self.layers:                     # video loops: new frames before any pass begins
            if L.video and L.video not in self._advanced:
                self._advanced[L.video] = L.video.advance(dt)
        for _, s in sprites:
            v = s.get("video")
            if v is not None and v not in self._advanced:
                self._advanced[v] = v.advance(dt)
        for (x, y, t0, s) in self.actors.spray:
            self._spray(x, y, t0, s)
        for (x, y, t0, s) in self.actors.rings:
            self._ring(x, y, t0, s)
        for (x, y, t0, s) in self.actors.bubbles:
            self._bubble(x, y, t0, s)
        if self.fireflies:
            for (x, y, t0) in self.actors.disturb:
                self.fireflies.scatter(x, y, t0)
            e = self.fx.by["fireflies"]
            night = 1.0 - skyclock.daylight(sig["hour"])
            lvl = float(sig.get(e.get("signal", "net"), 0.0) or 0.0)
            shelter = float(e.get("rain_hides", 0.0)) * getattr(self, "rain_level", 0.0)   # they go to ground in rain
            for dep, arr in self.fireflies.update(t, dt, lvl, night, shelter).items():
                glows.append((dep, arr))
        if not settling:
            self._sounds(t, sig)
        if not settling and not getattr(self, "offscreen", False) and self.cfg.get("world", {}).get("ambient_sounds", True):
            for rel in self.actors.sounds[:1]:
                if rel and t - getattr(self, "_cue_t", -9) > 1.5:
                    self._cue_t = t
                    self._play(rel, 0.45)
        # camera: the pointer, eased; settles home when the user is idle
        cam = self.spec.get("camera", {})
        # reduced motion: no parallax, the layers hold their place
        cx, cy = activity().cursor() if cam.get("parallax", "cursor") == "cursor" and not self.forced.get("still") \
            and not self.calm else (0.0, 0.0)
        if "cam_x" in self.forced:
            cx, cy = float(self.forced["cam_x"]), float(self.forced.get("cam_y", 0.0))
        k = 1.0 - math.exp(-dt / 1.4) if dt > 0 else 1.0
        self.cam[0] += (cx - self.cam[0]) * k
        self.cam[1] += (cy - self.cam[1]) * k
        sway = cam.get("sway", (20, 8))
        self.sway = (float(sway[0]), float(sway[1]))
        # light: the hour's grade, the lightning
        cl = self.spec.get("clock", {})
        g = skyclock.grade(sig["hour"], {
            "night": cl.get("night", glkit.T.rgb("dim")), "day": cl.get("day", glkit.T.rgb("white")),
            "dawn_tint": cl.get("dawn_tint", glkit.T.rgb("soft")), "dusk_tint": cl.get("dusk_tint", glkit.T.rgb("warn")),
            "dawn": cl.get("dawn", (5.5, 7.5)), "dusk": cl.get("dusk", (18.0, 20.5))})
        if sig.get("storm") and self.split:
            g = (g[0] * 0.7, g[1] * 0.72, g[2] * 0.8, g[3])
        self.grade = g
        day = skyclock.daylight(sig["hour"], tuple(cl.get("dawn", (5.5, 7.5))), tuple(cl.get("dusk", (18.0, 20.5))))
        lift = cl.get("day_lift", (0.0, 0.0, 0.0))
        self.lift = tuple(float(x) * day * (0.5 if sig.get("storm") else 1.0) for x in lift)
        flash = self._lightning(t, sig)
        self.flash = flash
        return sprites, glows, wakes, sig

    def _draw(self, fbo, t, sig, sprites, glows, wakes):
        # ---- the back: everything shallower than the water
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        self.back.bind()
        GL.glClearColor(0, 0, 0, 1)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        items = self._draw_list(sprites, glows)
        back = [it for it in items if it[0] < self.water_depth]
        front = [it for it in items if it[0] > self.water_depth]
        self._draw_items(back, t, sig)
        # ---- the water and effects pass, into the frame
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
        GL.glViewport(0, 0, self.w, self.h)
        GL.glDisable(GL.GL_BLEND)
        self._world_pass(t, sig, wakes)
        # ---- in front of the water
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
        self._draw_items(front, t, sig)
        GL.glDisable(GL.GL_BLEND)

    def _draw_list(self, sprites, glows):
        by = {}
        for L in self.layers:
            if not L.water:
                by.setdefault(L.depth, [[], [], []])[0].append(L)
        for dep, s in sprites:
            by.setdefault(dep, [[], [], []])[1].append(s)
        for dep, g in glows:
            by.setdefault(dep, [[], [], []])[2].append(g)
        for e in (self.fx.by.get("beacon"),):
            if e:
                gl = self._beacon(e)
                if gl:
                    by.setdefault(float(e.get("depth", 20.5)), [[], [], []])[2].append(gl)
        return sorted(((k,) + tuple(v) for k, v in by.items()), key=lambda it: it[0])

    def _par(self, depth, par=None):
        """Parallax offset in screen px for a depth (interpolated between the layers)."""
        if par is None:
            ls = [L for L in self.layers]
            par = 0.0
            for i, L in enumerate(ls):
                if L.depth <= depth:
                    par = L.parallax
                    nxt = ls[i + 1] if i + 1 < len(ls) else None
                    if nxt and nxt.depth > depth:
                        f = (depth - L.depth) / (nxt.depth - L.depth)
                        par = L.parallax + (nxt.parallax - L.parallax) * f
        return (-self.cam[0] * self.sway[0] * par * self.sx, -self.cam[1] * self.sway[1] * par * self.sy)

    def _layer_view(self, L):
        ox, oy = self._par(L.depth, L.parallax)
        margin = 1.0 + 2.0 * max(self.sway[0] * self.sx / self.w, self.sway[1] * self.sy / self.h) * max(L.parallax, 0.0)
        return (-ox / self.w, -oy / self.h, margin)

    def _common(self, p):
        p.f("u_res", float(self.w), float(self.h))
        p.f("u_grade", *self.grade)
        p.f("u_flash", float(self.flash))
        p.f("u_lift", *self.lift)

    def _fog(self, p, amount=None):
        wt = self.water
        p.f("u_fog", self.surface_y * self.sy, float(wt.get("fog_distance", 260)) * self.sy, 1.0 if self.split else 0.0,
            float(wt.get("fog_actors", 0.6)) if amount is None else amount)
        p.f("u_fogcol", *[float(x) for x in wt.get("fog", glkit.T.rgb("panel"))])

    def _draw_items(self, items, t, sig):
        gi = si = 0
        for depth, layers, sprs, glows in items:
            for L in layers:
                self._draw_layer(L, t, sig)
            if sprs:
                self._draw_sprites(si, sprs, depth, t)
                si += 1
            if glows:
                GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE)
                self._draw_glows(gi, glows, depth)
                GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
                gi += 1

    def _draw_layer(self, L, t, sig):
        p = self.p_layer
        p.use()
        p.f("u_calm", 1.0 if self.calm else 0.0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        tex = (self._advanced.get(L.video) if L.video else None) or L.tex
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        p.i("u_tex", 0)
        self._common(p)
        vx, vy, z = self._layer_view(L)
        p.f("u_view", vx, vy, z, 0.0)
        sw = L.t.get("sway")
        if sw:                                    # kelp and moss swaying with a signal (the swell: CPU)
            lv = float(sig.get(sw.get("signal", "cpu"), 0.0) or 0.0)
            amp = float(sw.get("min", 2)) + (float(sw.get("max", 10)) - float(sw.get("min", 2))) * lv
            amp = self._ease("sway_" + L.id, amp, self.frame_dt or 1.0, 2.0)
            L.sway_ph = getattr(L, "sway_ph", 0.0) + (self.frame_dt or 0.0) * (0.5 + 1.2 * lv)
            p.f("u_sway", amp * self.sx / self.w, L.sway_ph, float(sw.get("top", 300)) * self.sy, float(sw.get("bottom", 1440)) * self.sy)
        else:
            p.f("u_sway", 0.0, 0.0, 0.0, 1.0)
        if L.sky:
            p.f("u_sky", 1.0, self.surface_y * self.sy, 0.55, 0.0)
            tw = self.spec.get("clock", {}).get("twilight", glkit.T.rgb("warn"))
            p.f("u_twi", *[float(x) for x in tw])
            m = self.fx.by.get("moon")
            if m:
                ph = sig["moon_phase"]
                mx, my = self.moon_xy(sig)
                win = m.get("window", (200, 60, 2300, 600))
                x = win[0] + (win[2] - win[0]) * mx
                y = win[3] - (win[3] - win[1]) * max(my, -0.3)
                r = float(m.get("radius", 36))
                bright = max(0.0, min(1.0, (my + 0.15) / 0.3)) * (1.0 - 0.7 * skyclock.daylight(sig["hour"]))
                if sig.get("storm") and m.get("storm_hides", True):
                    bright *= 0.15
                p.f("u_moon", x * self.sx, y * self.sy, r * self.sy, ph)
                p.f("u_moon2", bright, 0.0, 0.0, 0.0)
            else:
                p.f("u_moon", 0.0, 0.0, 0.0, 0.0)
            e = self.fx.by.get("stars")
            if e:
                day = skyclock.daylight(sig["hour"])
                tw = skyclock.twilight(sig["hour"])
                b = float(e.get("brightness", 0.5)) * (1.0 - day) * (1.0 - 0.6 * tw)
                if sig.get("storm"):
                    b *= 0.1
                p.f("u_stars", b, float(e.get("density", 0.35)), float(e.get("horizon", self.surface_y)) * self.sy,
                    float(e.get("fade", 260)) * self.sy)
                p.f("u_starcell", float(e.get("cell", 26)) * self.sy)
                p.f("u_time", t)
            else:
                p.f("u_stars", 0.0, 0.0, 0.0, 1.0)
            st = self.fx.strike
            if st and t - st[0] < 0.28:
                p.f("u_bolt", st[1] * self.sx, st[3] * self.sy, 1.0 - (t - st[0]) / 0.28, st[2])
            else:
                p.f("u_bolt", 0.0, 0.0, 0.0, 0.0)
        else:
            p.f("u_sky", 0.0, 0.0, 0.0, 0.0)
            p.f("u_moon", 0.0, 0.0, 0.0, 0.0)
            p.f("u_bolt", 0.0, 0.0, 0.0, 0.0)
            p.f("u_stars", 0.0, 0.0, 0.0, 1.0)
        if L.fog:
            self._fog(p, L.fog)
        else:
            p.f("u_fog", 0.0, 1.0, 0.0, 0.0)
        self.fs.draw()

    def _inst_buf(self, pool, i, vs, fs, n):
        while len(pool) <= i:
            pool.append(glkit.Instanced(vs, fs, n))
            pool[-1].prog.cache = {}
        return pool[i]

    def _draw_sprites(self, i, sprs, depth, t):
        groups = {}
        for s in sprs:
            groups.setdefault((1 if s.get("add") else 0, id(s.get("video")) if s.get("video") else 0), []).append(s)
        for k, (key, grp) in enumerate(sorted(groups.items(), key=lambda kv: kv[0])):
            tex = self.atlas
            v = grp[0].get("video")
            if v is not None:
                tex = self._advanced.get(v)
                if tex is None:
                    continue                      # no frame decoded yet
            if key[0]:
                GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE)             # emissive masks: light, added
            self._draw_sprite_group(i * 8 + k, grp, depth, t, tex)
            if key[0]:
                GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)

    def _draw_sprite_group(self, i, sprs, depth, t, tex):
        rows = []
        sx, sy = self.sx, self.sy
        for s in sprs:
            ox, oy = self._par(depth, s.get("par"))
            x, y = s["x"] * sx + ox, s["y"] * sy + oy
            w, h = s["w"] * sx, s["h"] * sy
            cut = s["cut"] * sy + oy if s["cut"] >= 0 else -1.0
            tint = s.get("tint")
            tr = (tint[0], tint[1], tint[2], tint[3] if len(tint) > 3 else 0.5) if tint else (0.0, 0.0, 0.0, 0.0)
            craft = s.get("craft")                # a flyby: tint = the air's haze; clouds in the sky layer hide it
            base = [x, y, w, h, *s["uv"], s["rot"], s["alpha"], cut, 2.0 if craft else 0.0, *tr,
                    s.get("clouds", 0.0) if craft else s["reflect"],
                    1.0 if s["fog"] else 0.0, s["bright"], 1.0 if s.get("emissive") else 0.0]
            if s["reflect"] > 0 and cut > 0:
                r = list(base)
                r[11] = 1.0
                rows.append(r)
            rows.append(base)
        buf = self._inst_buf(self.sprites_gl, i, "world_sprite.vert", "world_sprite.frag", 5)
        buf.upload(np.array(rows, np.float32))
        p = buf.prog
        p.use()
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        p.i("u_atlas", 0)
        self._common(p)
        p.f("u_time", t)
        p.f("u_water", *[float(x) for x in self.water.get("tint", glkit.T.rgb("panel"))])
        self._fog(p)
        rim = next((s["rim"] for s in sprs if s.get("rim")), None)
        p.f("u_rim", *([float(x) for x in rim] if rim else (0.0, 0.0, 0.0, 0.0)))
        cloudy = next((s for s in sprs if s.get("clouds")), None)
        sky = self.sky_layer if cloudy else None
        if sky is not None:                       # the sky's own clouds pass in front of craft behind them
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, sky.tex)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            p.i("u_sky", 1)
            p.f("u_skyview", *self._layer_view(sky), 1.0)
            cl = [float(x) for x in cloudy.get("cloud_luma", (0.1, 0.3))]
            p.f("u_cloud", *(cl + [2.0, 3.0])[:4])       # [cloud from, cloud full, moon from, moon full]
        else:
            p.f("u_skyview", 0.0, 0.0, 1.0, 0.0)
        buf.draw()

    def _draw_glows(self, i, glows, depth):
        """glows: tuples (x, y, rx, ry, r, g, b, intensity, fog) or row blocks (n x 12), plate px."""
        tup = [g for g in glows if not isinstance(g, np.ndarray)]
        blocks = [g for g in glows if isinstance(g, np.ndarray)]
        if tup:
            a = np.zeros((len(tup), 12))
            a[:, :9] = np.array(tup, dtype=np.float64)
            blocks.append(a)
        rows = np.concatenate(blocks).astype(np.float32)
        ox, oy = self._par(depth)
        rows[:, 0] = rows[:, 0] * self.sx + ox
        rows[:, 1] = rows[:, 1] * self.sy + oy
        rows[:, 2:4] *= self.sy
        buf = self._inst_buf(self.glows_gl, i, "world_glow.vert", "world_glow.frag", 3)
        buf.upload(rows)
        p = buf.prog
        p.use()
        p.f("u_res", float(self.w), float(self.h))
        self._fog(p)
        buf.draw()

    # ---- effects
    def _lightning(self, t, sig):
        e = self.fx.by.get("lightning")
        if not e or self.calm:                    # reduced motion: no bolts, no flash (the storm stays dark)
            return 0.0
        v = float(sig.get(e.get("signal", "cpu"), 0.0) or 0.0)
        on = v >= float(e.get("above", 0.88))
        fx = self.fx
        if on:
            if fx.strike_at is None:
                fx.strike_at = t + 1.0 + random.random() * 2.0
            if t >= fx.strike_at:
                zone = e.get("zone", (200, 2300))
                fx.strike = (t, zone[0] + (zone[1] - zone[0]) * random.random(), random.random() * 100.0,
                             float(e.get("ground", self.surface_y)))
                ev = e.get("every", (5, 14))
                fx.strike_at = t + ev[0] + (ev[1] - ev[0]) * random.random()
        else:
            fx.strike_at = None
        st = fx.strike
        if not st:
            return 0.0
        a = t - st[0]
        if a > 0.6:
            return 0.0
        return float(e.get("flash", 0.9)) * (math.exp(-a / 0.06) + 0.6 * math.exp(-((a - 0.18) ** 2) / 0.002))

    def _ok(self, e):
        """An effect or actor with `requires = "<signal>"` isn't drawn while that source is
        unavailable (the shared rule: no data, no inhabitant)."""
        req = e.get("requires")
        return not req or bool(self.sig.get(req))

    def _beacon(self, e):
        on = bool(self.sig.get(e.get("signal", "lab_green"))) and self._ok(e)
        if not on:
            return None
        t = self.clock.peek(self.now())
        per = float(e.get("period", 2.4))
        u = (t % per) / per
        k = 0.75 if self.calm else math.exp(-((u - 0.1) ** 2) / 0.004) + 0.15    # reduced motion: steady
        c = e.get("color", glkit.T.rgb("danger"))
        r = float(e.get("radius", 7))
        at = e.get("at", (1800, 300))
        return (at[0], at[1], r, r, c[0], c[1], c[2], k)  + (0.0,)

    def _world_pass(self, t, sig, wakes):
        p = self.p_world
        p.use()
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.back.tex)
        p.i("u_back", 0)
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.water_layer.tex if self.water_layer else self.back.tex)
        p.i("u_water", 1)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        sx, sy = self.sx, self.sy
        self._common(p)
        p.f("u_time", t)
        p.f("u_scale", sy)
        if self.water_layer:
            vx, vy, z = self._layer_view(self.water_layer)
            p.f("u_wview", vx, vy, z, 0.0)
        wt = self.water
        fx = self.fx
        cpu = sig["cpu"]
        dt = max(0.0, min(t - getattr(self, "_fx_t", t), 0.1))
        self._fx_t = t
        # rain and mist (the den's CPU rain, as weather)
        rain = getattr(self, "rain_level", 0.0)
        p.f("u_rain", rain, 0.0, 0.0, 0.0)
        base_ripple = float(wt.get("ripple", 0.6)) * (0.35 + 0.65 * min(1.0, cpu * 2.5))
        p.f("u_line", self.surface_y * sy, 0.0, float(wt.get("reflect", 0.7)), base_ripple)
        e = fx.by.get("mist")
        if e:
            v = float(sig.get(e.get("signal", "cpu"), 0.0) or 0.0)
            band = e.get("band", (700, 1100))
            strength = float(e.get("base", 0.25)) + float(e.get("gain", 0.6)) * min(1.0, v / max(float(e.get("full", 0.35)), 1e-3))
            strength *= 1.0 - 0.4 * rain
            fx.mist_phase = (fx.mist_phase + dt * (0.015 + 0.06 * v)) % 1000.0
            p.f("u_mist", strength, band[0] * sy, band[1] * sy, fx.mist_phase)
            p.f("u_mistcol", *[float(x) for x in e.get("color", glkit.T.rgb("muted"))])
        e = fx.by.get("line")
        if e:
            tip = self.line_tip()
            end = self.line_hook or self.line_end()
            taut = t < fx.line_taut_until or self.line_hook is not None
            sag = 0.0 if taut else float(e.get("sag", 26.0))
            kp = self.actors.insts.get((self.keeper.id, "keeper")) if self.keeper else None
            show = (taut or e.get("slack", True)) and not (kp and self.actors._override(kp, t))
            if taut and self.line_hook is None:
                a = t - fx.line_jerk
                end = (end[0] + math.sin(a * 21.0) * 2.0 * math.exp(-a), end[1] + 7.0 * math.exp(-a * 0.8))
            ox, oy = self._par(float(e.get("depth", 31)))
            p.f("u_fline", tip[0] * sx + ox, tip[1] * sy + oy, end[0] * sx + ox, end[1] * sy + oy)
            p.f("u_fline2", sag * sy, 1.0 if show else 0.0, 0.0, 0.0)
            p.f("u_flinecol", *[float(x) for x in e.get("color", glkit.T.rgb("soft"))])
        e = fx.by.get("beam")
        if e and not self._ok(e):
            p.f("u_beam", 0.0, 0.0, 0.0, 0.0)
        elif e:
            rate = float(e.get("rate", 0.35)) + float(e.get("rate_gain", 0.12)) * min(float(sig.get(e.get("rate_signal", "ingress"), 0.0) or 0.0), 6.0)
            fx.beam_phase = (fx.beam_phase + dt * rate) % (2 * math.pi)
            cols = e.get("colors", [glkit.T.rgb("white"), glkit.T.rgb("warn"), glkit.T.rgb("danger")])
            lvl = int(sig.get(e.get("signal", "health"), 0) or 0)
            c = cols[max(0, min(lvl, len(cols) - 1))]
            at = e.get("at", (1880, 225))
            ox, oy = self._par(float(e.get("depth", 20)))
            p.f("u_beam", at[0] * sx + ox, at[1] * sy + oy, fx.beam_phase, 1.0)
            p.f("u_beam2", float(e.get("reach", 2400)) * sx, 0.0, 0.0, 0.0)
            p.f("u_beamcol", *[float(x) for x in c])
        e = fx.by.get("swell")
        if e:
            v = float(sig.get(e.get("signal", "cpu"), 0.0) or 0.0)
            amp = float(e.get("min", 3)) + (float(e.get("max", 26)) - float(e.get("min", 3))) * v
            amp = self._ease("swell_amp", amp, dt if dt > 0 else 1.0, 2.5)
            fx.swell_phase = (fx.swell_phase + dt * (0.5 + 1.2 * v)) % (2 * math.pi * 1000)
            p.f("u_swell", amp * sy, float(e.get("wavelength", 420)) * sx, fx.swell_phase, min(1.0, amp / 18.0))
            p.f("u_caus", float(e.get("caustics", 0.6)) * (0.4 + 0.6 * v), 0.0, 0.0, 0.0)
        else:
            p.f("u_swell", 0.0, 400.0, 0.0, 0.0)
            p.f("u_caus", 0.3, 0.0, 0.0, 0.0)
        e = fx.by.get("rays")
        if e:
            day = skyclock.daylight(sig["hour"])
            mx, my = self.moon_xy(sig)
            moon = skyclock.illumination(sig["moon_phase"]) * max(0.0, min(1.0, (my + 0.1) / 0.3))
            light = max(day, moon * 0.8) * (0.4 if sig.get("storm") else 1.0)
            follow = -1.0                          # the x the shafts gather under (-1: everywhere)
            m = fx.by.get("moon")
            if e.get("follow_moon") and m and day < 0.5 and moon > 0.05:
                win = m.get("window", (200, 60, 2300, 600))
                follow = (win[0] + (win[2] - win[0]) * mx) * sx
            p.f("u_rays", float(e.get("gain", 0.25)) * (float(e.get("base", 0.15)) + (1.0 - float(e.get("base", 0.15))) * light),
                float(e.get("slant", 0.18)), float(e.get("reach", 520)) * sy, follow)
            p.f("u_rayscol", *[float(x) for x in e.get("color", glkit.T.rgb("cyan"))])
        wk = np.zeros((12, 4), np.float32)
        ox, oy = self._par(self.water_depth)
        for i, (x, y, s) in enumerate(wakes[:12]):
            wk[i] = (x * sx + ox, y * sy + oy, s, 0.0)
        p.fv("u_wake", wk, 4)
        p.fv("u_spray", np.array(self.spray, np.float32), 4)
        p.fv("u_ring", np.array(self.rings, np.float32), 4)
        p.fv("u_bubble", np.array(self.bubbles, np.float32), 4)
        self.fs.draw()

    # ---- ambient sound: the creatures follow the user
    def _sounds(self, t, sig):
        snd = self.spec.get("sounds", {})
        amb = snd.get("ambient") or []
        if not amb or not self.cfg.get("world", {}).get("ambient_sounds", True):
            return
        if getattr(self, "offscreen", False):
            return
        mult = {"working": 1.0, "dozing": 3.0}.get(sig["user"])
        for i, a in enumerate(amb):
            nxt = self.sound_next.get(i)
            ev = a.get("every", (10, 30))
            if mult is None:
                self.sound_next[i] = None
                continue
            if nxt is None:
                self.sound_next[i] = t + (ev[0] + (ev[1] - ev[0]) * random.random()) * mult
                continue
            if t >= nxt:
                self._play(a["file"], float(a.get("gain", 0.5)))
                self.sound_next[i] = t + (ev[0] + (ev[1] - ev[0]) * random.random()) * mult

    def _play(self, rel, gain=0.6):
        app = getattr(self, "app", None)
        snd = getattr(app, "sound", None) if app else None
        path = os.path.join(self.root, rel)
        if snd and os.path.isfile(path):
            snd.play_file(path, gain=gain)
