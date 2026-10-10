"""The worlds' actors: creatures and craft bound to real signals (live/world.py draws them).

An actor definition is one `[[actors]]` table in a world's `live/world.toml`; its `kind`
says where its instances come from and which states they have:

  agents   one instance per herdr agent (the Swarm deck's data). States: working,
           needs_you, finished; `gone` when the agent closes (then it leaves).
  keeper   the world's keeper, one instance mirroring the user: working (active),
           dozing (idle), asleep (session locked). Its `lamp` dims with it.
  signal   one instance whose state is a signal's value (lab health 0/1/2, VECTOR's
           state ...). A state with `hidden = true` hides it.
  crowd    a fixed flock at `spots`, following the user's activity like the keeper
           (working, dozing, asleep).
  traffic  craft crossing on lanes; whether a crossing carries one is decided once, as it
           starts off-screen, from its signal (the Wick's ship rule: nothing pops).
  event    spawned by events (notify, critical, fill_win, fill_loss, ...): `[[actors.on]]`
           variants, each with its own motion, sprite, depth and lifetime.
  flyby    craft crossing the sky now and then: one of its `[[actors.craft]]` at a time, at
           a random distance (nearer = bigger, faster, clearer), its gap shrinking with its
           signal; nav lights, strobes and an exhaust trail that stays where it was laid.
           Off with the `ships` animation switch and under reduced motion.

Every state names a `motion` (below) and how its lights burn. The "needs you" gesture is
shared by every kind: `turn = true` stops the actor, turns it to face the viewer (the
`front` frame when the strip has one, else a squash-turn) and `signal = true` blinks its
lights in the signal colour at 0.55 Hz, after one bright flash.

Motions: still, hold, bob, rock, wander, settle, hover, circle, drift, pace, croak,
breach, dive, rise, approach, reel, drift_up, dart, glide, cross. Positions are plate pixels
(2560x1440); `update()` returns sprite and glow instances in plate pixels, the renderer
scales them.
"""
import math

from . import glkit
import random

TAU = 2 * math.pi


def _rng(*key):
    return random.Random(hash(key) & 0xFFFFFFFF)


def _ease(cur, target, dt, tau):
    if tau <= 0:
        return target
    return cur + (target - cur) * (1.0 - math.exp(-dt / tau))


def _smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


class Sprite:
    """A sprite's frames in the atlas: list of (u0, v0, u1, v1, aspect w/h)."""

    def __init__(self, frames, video=None):
        self.frames = frames
        self.video = video          # a VideoLoop: the frame is its texture (uv 0..1)

    def frame(self, i):
        return self.frames[int(i) % len(self.frames)]


class Def:
    def __init__(self, t, sprites, world):
        self.t = t
        self.id = t["id"]
        self.kind = t.get("kind", "signal")
        self.sprite = sprites[t["sprite"] if t.get("sprite") else t["craft"][0]["sprite"]]
        self.sprites = sprites
        self.height = float(t.get("height", 100))
        self.depth = float(t.get("depth", 25))
        self.parallax = t.get("parallax")
        self.wade = float(t.get("wade", 0.0))
        self.reflect = float(t.get("reflect", 0.0))
        self.fog = bool(t.get("fog", False))
        self.at = tuple(t.get("at", (1280, 900)))
        self.zones = [tuple(z) for z in t.get("zones", [])] or ([tuple(t["zone"])] if "zone" in t else [])
        self.frames = {k: list(v) for k, v in (t.get("frames") or {}).items()}
        self.lights = t.get("lights") or []
        self.anchors = t.get("anchors") or {}
        self.states = t.get("states") or {}
        self.lamp = t.get("lamp")
        self.signal = t.get("signal")
        self.max = int(t.get("max", 12))
        self.signal_color = tuple(t.get("signal_color", glkit.T.rgb("warn")))
        self.error_color = tuple(t.get("error_color", glkit.T.rgb("danger")))
        self.on = t.get("on") or []
        self.spots = [tuple(s) for s in t.get("spots", [])]
        self.world = world

    def state_cfg(self, state):
        return self.states.get(state) or {}

    def frame_list(self, name, default=None):
        f = self.frames.get(name)
        if f:
            return f
        return default if default is not None else [0]


class Inst:
    def __init__(self, d, key, t):
        self.d = d
        self.key = key
        self.born = t
        self.state = None
        self.state_t = t
        self.x, self.y = d.at
        self.face = 1.0
        self.turn = 0.0
        self.light = 0.0
        self.lamp = 1.0
        self.sink = 1.0 if d.kind == "agents" else 0.0
        self.alpha = 0.0
        self.dist = 0.0
        self.target = None
        self.pause_until = 0.0
        self.scale = 1.0
        self.error = False
        self.dead = False
        self.flare = 0.0           # roll call: a brief light flare
        self.flare_t = -1.0
        self.v = None               # event / traffic: the variant table and path
        self.path = None
        self.life = 0.0
        self.extra = {}
        self.dx = self.dy = self.rot = 0.0
        self.frame = None
        self.turn_target = 0.0
        self.spot = d.at
        self.zone = None
        self.placed = None
        self.slot = None
        self.slot_cfg = {}
        self.clip = None
        self.clip_hold = False
        r = _rng(d.id, key)
        self.r = r
        self.seed = r.random()


# --------------------------------------------------------------------------- the system
class Actors:
    def __init__(self, defs):
        self.defs = defs
        # reduced motion (live/motion.py; the world sets these): `calm` holds every light
        # steady (no flash, blink, pulse or flicker); `still` spawns no one-off creatures
        self.calm = False
        self.still = False
        self.insts = {}            # (def id, key) -> Inst
        self.events = []           # (variant, def, t) waiting to spawn
        self.spray = []            # (x, y, t0, strength) new this frame
        self.n_event = 0
        self.lanes = {}
        self.sounds = []           # cues the actors asked for this frame (relative paths)

    # ---- events
    def event(self, name, t, **info):
        if self.still:
            return                                   # a still picture: no one-off creatures, no roll call
        for d in self.defs:
            if d.kind != "event":
                continue
            for v in d.on:
                if v.get("event") == name:
                    base = random.randrange(1 << 16)      # one event's creatures share it: distinct targets
                    for k in range(int(v.get("count", 1))):
                        self.n_event += 1
                        inst = Inst(d, f"ev{self.n_event}", t + k * float(v.get("stagger", 0.35)))
                        inst.v = v
                        inst.extra["ev"] = (base, k)
                        self.insts[(d.id, inst.key)] = inst
        for d in self.defs:                          # a keeper's pose for an event: Hollis lands the catch
            ev = (d.t.get("events") or {}).get(name) if d.kind == "keeper" else None
            inst = self.insts.get((d.id, "keeper")) if ev else None
            if inst is not None and inst.state == "working":
                t0 = t + float(ev.get("after", 0.0))
                inst.override = (ev, t0, t0 + float(ev.get("seconds", 3.0)))
        if name.startswith("flyby"):                # a pass now (testing): "flyby" or "flyby:<craft id>"
            for d in self.defs:
                if d.kind == "flyby" and not self._flyby(d, t, name.partition(":")[2] or None):
                    self.lanes.setdefault(d.id, {}).setdefault("waiting", []).append(name.partition(":")[2] or None)
        if name == "rollcall":
            i = 0
            for inst in sorted(self.insts.values(), key=lambda s: (s.d.depth, s.x)):
                if inst.d.kind in ("agents", "keeper", "signal"):
                    inst.flare_t = t + 0.6 + 0.45 * i
                    i += 1

    # ---- per frame
    def update(self, t, dt, sig):
        """Advance every actor. sig: the world's signals (see world.Signals). Returns
        (sprites, glows, wakes): sprites = [(depth, dict)], glows = [(depth, (x, y, rx, ry, r, g, b, i, fog))],
        wakes = [(x, y, strength)]."""
        self.spray = []
        self.sounds = []
        self.rings, self.bubbles, self.disturb = [], [], []
        sprites, glows, wakes = [], [], []
        for d in self.defs:
            getattr(self, "_sync_" + d.kind, lambda *a: None)(d, t, sig)
        for key in list(self.insts):
            inst = self.insts[key]
            if t < inst.born:
                continue
            self._step(inst, t, dt, sig)
            if inst.dead:
                del self.insts[key]
                continue
            if inst.d.kind == "flyby":
                self._emit_flyby(inst, t, sprites, glows)
                continue
            self._emit(inst, t, sig, sprites, glows, wakes)
        lamp_glows = []
        for d in self.defs:
            if d.kind == "keeper" and d.lamp:
                inst = self.insts.get((d.id, "keeper"))
                lv = inst.lamp if inst else 1.0
                lp = d.lamp
                flick = 1.0 if self.calm else 1.0 + 0.04 * math.sin(t * 7.3) * math.sin(t * 2.9)
                fl = (1.0 + 1.5 * inst.flare) if inst else 1.0
                c = lp.get("color", glkit.T.rgb("warn"))
                r = float(lp.get("radius", 90))
                lamp_glows.append((float(lp.get("depth", d.depth)),
                                   (lp["at"][0], lp["at"][1], r, r, c[0], c[1], c[2], lv * flick * fl, 0.0)))
        return sprites, glows + lamp_glows, wakes

    # ---- populations
    @staticmethod
    def _band(inst, depth):
        """Put an instance in its own depth band for its whole life (a zone's 5th number, a
        spot's 3rd): behind a layer it stays behind it, so nothing pops through. Deeper than
        its actor's own depth means farther off: smaller and hazier (`far_scale`, `far_bright`)."""
        if depth is None:
            return
        d = inst.d
        inst.extra["depth"] = float(depth)
        if float(depth) < d.depth:
            inst.extra["zscale"] = float(d.t.get("far_scale", 0.72))
            inst.extra["zbright"] = float(d.t.get("far_bright", 0.6))

    def _sync_agents(self, d, t, sig):
        agents = sig.get("agents") or []
        take = d.t.get("take", (0, d.max))
        live = {}
        for a in agents[int(take[0]):int(take[1])][:d.max]:
            live[a["key"]] = a
        slots = d.t.get("slots")
        used = {getattr(o, "slot", None) for (did, _), o in self.insts.items() if did == d.id and o.state != "gone"}
        for k, a in live.items():
            inst = self.insts.get((d.id, k))
            if inst is None and slots:                 # a fixed place (a foreground head), the first free one
                free = [i for i in range(len(slots)) if i not in used]
                if not free:
                    continue
                inst = Inst(d, k, t)
                inst.slot = free[0]
                used.add(free[0])
                sl = slots[free[0]]
                inst.x, inst.y = sl["at"]
                inst.face = float(sl.get("face", 1.0))
                inst.slot_cfg = sl
                self.insts[(d.id, k)] = inst
            if inst is None:
                inst = Inst(d, k, t)
                zones = d.zones or [(d.at[0] - 200, d.at[1], d.at[0] + 200, d.at[1] + 30)]
                others = [(o.x, o.y) for (did, _), o in self.insts.items() if did == d.id and o.state != "gone"]
                # the far bands (a zone's 5th number, behind a layer) are overflow: the first
                # `far_after` (3) creatures at work swim in the near water where they're seen,
                # so one agent never ends up small and dim behind the kelp
                near = [z for z in zones if len(z) < 5 or z[4] >= d.depth]
                busy = sum(1 for (did, _), o in self.insts.items()
                           if did == d.id and o.state in ("working", "needs_you") and "zscale" not in o.extra)
                pool = near if near and busy < int(d.t.get("far_after", 3)) else zones
                best = None
                for _ in range(10):                 # the spot farthest from the others
                    z = pool[inst.r.randrange(len(pool))]
                    p = (z[0] + (z[2] - z[0]) * inst.r.random(), z[1] + (z[3] - z[1]) * inst.r.random())
                    gap = min((abs(p[0] - ox) + 2 * abs(p[1] - oy) for ox, oy in others), default=1e9)
                    if best is None or gap > best[0]:
                        best = (gap, z, p)
                _, z, (inst.x, inst.y) = best
                inst.zone = z
                self._band(inst, z[4] if len(z) > 4 else None)
                inst.face = 1.0 if inst.r.random() < 0.5 else -1.0
                self.insts[(d.id, k)] = inst
            inst.error = bool(a.get("error"))
            self._set_state(inst, a["status"], t)
        for (did, k), inst in self.insts.items():
            if did == d.id and k not in live:
                self._set_state(inst, "gone", t)

    def _sync_keeper(self, d, t, sig):
        inst = self.insts.get((d.id, "keeper"))
        if inst is None:
            inst = Inst(d, "keeper", t)
            inst.sink = 0.0
            inst.alpha = 1.0
            inst.lamp = 0.15
            self.insts[(d.id, "keeper")] = inst
        self._set_state(inst, sig.get("user", "working"), t)

    def _sync_signal(self, d, t, sig):
        inst = self.insts.get((d.id, "one"))
        if inst is None:
            inst = Inst(d, "one", t)
            inst.sink = 0.0
            self.insts[(d.id, "one")] = inst
        v = sig.get(d.signal)
        key = str(int(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
        if isinstance(v, bool):
            key = "1" if v else "0"
        self._set_state(inst, key, t)

    def _sync_crowd(self, d, t, sig):
        for i, spot in enumerate(d.spots):
            inst = self.insts.get((d.id, i))
            if inst is None:
                inst = Inst(d, i, t)
                inst.sink = 0.0
                inst.x, inst.y = spot[0], spot[1]
                inst.spot = (spot[0], spot[1])
                inst.face = 1.0 if inst.r.random() < 0.5 else -1.0
                self._band(inst, spot[2] if len(spot) > 2 else None)
                sizes = d.t.get("sizes")              # each one its own size: [lo, hi] x height
                if sizes:
                    inst.extra["zscale"] = inst.extra.get("zscale", 1.0) * (sizes[0] + (sizes[1] - sizes[0]) * inst.r.random())
                tints = d.t.get("tints")              # and its own colour, from these, dealt in turn
                if tints:                             # so five residents are five colours
                    inst.extra["tint"] = tuple(tints[i % len(tints)])
                own = d.t.get("sprites")              # its own art (a colour variant), dealt in turn
                if own:
                    inst.extra["sprite"] = own[i % len(own)]
                lc = d.t.get("light_colors")          # its light organs' colour, dealt in turn
                if lc:
                    inst.extra["light_color"] = tuple(lc[i % len(lc)])
                self.insts[(d.id, i)] = inst
            self._set_state(inst, sig.get("user", "working"), t)

    def _sync_traffic(self, d, t, sig):
        lv = float(sig.get(d.signal, 0.0) or 0.0)
        n = int(d.t.get("lanes", 3))
        for k in range(n):
            inst = self.insts.get((d.id, k))
            if inst is None or inst.path is None or t - inst.path[0] >= inst.path[1]:
                cyc = 0 if inst is None else inst.extra.get("cyc", 0) + 1
                first = inst is None
                inst = Inst(d, k, t)
                inst.sink = 0.0
                inst.extra["cyc"] = cyc
                r = _rng(d.id, k, cyc)
                band = d.t.get("band", (d.at[1], d.at[1]))
                inst.y = band[0] + (band[1] - band[0]) * r.random()
                sp = d.t.get("speed", (20, 40))
                v = sp[0] + (sp[1] - sp[0]) * r.random()
                direction = float(d.t.get("dir", 1)) or (1.0 if r.random() < 0.5 else -1.0)
                x0, x1 = d.t.get("span", (-300, 2860))
                length = x1 - x0
                dur = length / v
                t0 = t - (dur * r.random() if first else 0.0)
                inst.path = (t0, dur, x0, x1, direction)
                inst.face = direction
                inst.busy = r.random() < float(d.t.get("base", 0.1)) + float(d.t.get("gain", 0.9)) * lv
                inst.state = "crossing"
                self.insts[(d.id, k)] = inst

    # ---- craft overhead
    SWITCHES = {"ships": ("space", "traffic")}       # `bromigos anim off ships`

    @classmethod
    def _flyby_on(cls, d):
        cfg = d.world.cfg if d.world is not None else {}
        sec, key = cls.SWITCHES.get(d.t.get("switch", "ships"), ("space", "traffic"))
        return bool(cfg.get(sec, {}).get(key, True)) and not cfg.get("general", {}).get("reduced_motion", False)

    def _sync_flyby(self, d, t, sig):
        """Now and then a craft crosses: time runs toward the next pass faster with the
        signal (1 + gain x level), so a busy network brings them more often."""
        st = self.lanes.setdefault(d.id, {})
        dt = max(0.0, min(t - st.get("t", t), 1.0))
        st["t"] = t
        if not self._flyby_on(d):
            for key in [k for k in self.insts if k[0] == d.id]:
                del self.insts[key]                      # switched off: the sky clears at once
            return
        if "need" not in st:
            f = d.t.get("first", (30, 120))
            st["need"], st["acc"] = f[0] + (f[1] - f[0]) * random.random(), 0.0
        if st.get("waiting") and self._flyby(d, t, st["waiting"][0]):
            st["waiting"].pop(0)                         # a pass held back for a clear altitude
        lv = float(sig.get(d.signal, 0.0) or 0.0) if d.signal else 0.0
        st["acc"] += dt * (1.0 + float(d.t.get("gain", 1.0)) * max(0.0, min(lv, 1.0)))
        if st["acc"] >= st["need"]:
            if sum(1 for k in self.insts if k[0] == d.id) < int(d.t.get("max", 1)):
                self._flyby(d, t)
            ev = d.t.get("every", (240, 600))
            st["need"], st["acc"] = ev[0] + (ev[1] - ev[0]) * random.random(), 0.0

    def _flyby(self, d, t, which=None):
        crafts = d.t.get("craft") or []
        if which:
            crafts = [c for c in crafts if c.get("id") == which] or crafts
        if not crafts:
            return True
        self.n_event += 1
        inst = Inst(d, f"fly{self.n_event}", t)
        r = inst.r
        tot = sum(float(c.get("weight", 1.0)) for c in crafts)
        pick, c = r.random() * tot, crafts[-1]
        for cand in crafts:
            pick -= float(cand.get("weight", 1.0))
            if pick <= 0:
                c = cand
                break
        lo, hi = c.get("distance", (0.0, 1.0))
        z = lo + (hi - lo) * r.random()                  # 0 near .. 1 far
        hs, sp, ys = c.get("height", (60, 30)), c.get("speed", (140, 60)), c.get("y", (200, 400))
        h = hs[0] + (hs[1] - hs[0]) * z
        direction = float(c.get("dir", 0)) or (1.0 if r.random() < 0.5 else -1.0)
        sprite = d.sprites[c["sprite"]]
        w = h * sprite.frame(0)[4]
        climb = (r.random() - 0.5) * float(c.get("climb", 40))
        room = h * 0.5 + abs(climb) * 0.5 + float(c.get("bob", 3.0)) * 1.3   # its half-height in flight
        band = d.t.get("sky")                            # the whole craft stays inside [top, bottom], climb and bob too
        speed = sp[0] + (sp[1] - sp[0]) * z
        x0, x1 = d.t.get("span", (0, 2560))
        x0, x1 = x0 - w * 0.6 - 40, x1 + w * 0.6 + 40
        dur = (x1 - x0) / speed
        start = x0 if direction > 0 else x1
        # never through another craft: an altitude and a path that never share a place and a
        # moment with any craft already in the sky (else the pass waits for the sky to clear)
        others = [o for (did, _), o in self.insts.items() if did == d.id and "room" in o.extra]
        y = None
        for k in range(12):
            u = 0.55 * z + 0.45 * r.random() if k == 0 else r.random()          # the farther, the lower toward the horizon
            cand = ys[0] + (ys[1] - ys[0]) * u
            if band:
                cand = max(float(band[0]) + room, min(cand, float(band[1]) - room))
            if all(not self._clash(cand, room, w, start, direction * speed, t, t + dur, o) for o in others):
                y = cand
                break
        if y is None:
            return False
        inst.v = None
        inst.state = "flying"
        inst.extra.update(craft=c, z=z, h=h, w=w, y=y, room=room, dir=direction, speed=speed, x0=x0, x1=x1,
                          dur=dur, climb=climb, trails={})
        inst.face = direction
        self.insts[(d.id, inst.key)] = inst
        return True

    @staticmethod
    def _clash(y, room, w, x_start, vx, t0, t1, o):
        """Would a new pass (altitude y, half-height room, width w, at x_start moving vx px/s
        from t0 to t1) overlap craft o at some moment? Both move in straight lines, so their
        gap is linear in time: check the window's ends."""
        e = o.extra
        if abs(y - e["y"]) > room + e["room"] + 6:
            return False                                 # different altitudes
        o_t1 = o.born + e["dur"]
        a, b = max(t0, o.born), min(t1, o_t1)
        if a >= b:
            return False                                 # never in the sky together
        ovx = (e["x1"] - e["x0"]) / e["dur"] * e["dir"]
        ox_start = e["x0"] if e["dir"] > 0 else e["x1"]
        reach = (w + e["w"]) * 0.5 + 30

        def gap(tt):
            return (x_start + vx * (tt - t0)) - (ox_start + ovx * (tt - o.born))
        ga, gb = gap(a), gap(b)
        return min(ga, gb) < reach and max(ga, gb) > -reach

    def _step_flyby(self, inst, t):
        e = inst.extra
        a = t - inst.born
        f = a / e["dur"]
        if f >= 1.0:
            inst.dead = True
            return
        c = e["craft"]
        inst.x = e["x0"] + (e["x1"] - e["x0"]) * f if e["dir"] > 0 else e["x1"] - (e["x1"] - e["x0"]) * f
        ph = inst.seed * TAU
        bob = float(c.get("bob", 3.0)) * (1.0 - 0.5 * e["z"])
        inst.y = e["y"] + e["climb"] * (f - 0.5) + math.sin(a * 0.7 + ph) * bob + math.sin(a * 1.9 + 2 * ph) * bob * 0.3
        # a gentle bank with the bob, and the climb's pitch
        inst.rot = math.radians(float(c.get("bank", 2.0))) * math.sin(a * 0.45 + ph) - e["dir"] * math.atan2(e["climb"], e["x1"] - e["x0"])
        inst.alpha = min(1.0, a / 1.5, (e["dur"] - a) / 1.5)

    def _emit_flyby(self, inst, t, sprites, glows):
        d, e = inst.d, inst.extra
        c = e["craft"]
        sprite = d.sprites[c["sprite"]]
        u0, v0, u1, v1, asp = sprite.frame(0)
        h = e["h"]
        w = h * asp
        sx = e["dir"] * (-1.0 if c.get("faces", "right") == "left" else 1.0)
        z = e["z"]
        hz = d.t.get("haze", glkit.col("panel", 0.5))
        haze = float(hz[3]) * (float(c.get("haze", 0.15)) + (1.0 - float(c.get("haze", 0.15))) * z ** 0.8)
        bright = float(c.get("bright", 0.6)) * (1.0 - 0.35 * z)
        depth = float(c.get("depth", d.depth))
        if d.t.get("near_depth") is not None and z < float(d.t.get("near", 0.5)):
            depth = float(d.t["near_depth"])            # a near craft passes in front of a small far landmark, never behind it
        depth += 0.2 * (1.0 - z)                         # nearer craft over farther ones
        x, base = inst.x, inst.y + h * 0.5                               # inst.y is the craft's middle
        sprites.append((depth, {"x": x, "y": base, "w": w * sx, "h": h, "uv": (u0, v0, u1, v1), "rot": inst.rot,
                                "video": sprite.video, "alpha": inst.alpha, "cut": -1.0, "tint": (hz[0], hz[1], hz[2], haze),
                                "bright": bright, "fog": False, "reflect": 0.0, "par": d.parallax, "add": False,
                                "craft": True, "clouds": float(d.t.get("clouds", 0.0)),
                                "cloud_luma": tuple(d.t.get("cloud_luma", (0.1, 0.3))),
                                "rim": tuple(d.t.get("rim", glkit.col("soft", 0.5)))}))
        lit = inst.alpha * (1.0 - 0.6 * haze)
        cloud = float(d.t.get("clouds", 0.0))
        luma = d.t.get("cloud_luma", (0.1, 0.3))
        cover = (lambda px, py: 1.0 - cloud * d.world.sky_cover(px, py, luma)) if cloud and d.world is not None \
            else (lambda px, py: 1.0)
        ca, sa = math.cos(inst.rot), math.sin(inst.rot)
        scale = (h / max(float(c.get("height", (60, 30))[0]), 1.0)) ** 0.5

        def place(u, v):
            if sx < 0:
                u = 1.0 - u
            lx, ly = (u - 0.5) * w, -(1.0 - v) * h
            return x + lx * ca - ly * sa, base + lx * sa + ly * ca

        for L in c.get("lights") or []:
            k = 1.0
            blink = L.get("blink")
            if blink == "strobe":                        # a double white flash
                u = (t + inst.seed * 3.0) % float(L.get("period", 1.6))
                k = math.exp(-((u - 0.05) ** 2) / 0.0006) + 0.8 * math.exp(-((u - 0.2) ** 2) / 0.0006)
            elif isinstance(blink, (int, float)) and blink > 0:   # a beacon's slow pulse
                u = ((t + inst.seed * blink) % blink) / blink
                k = math.exp(-((u - 0.1) ** 2) / 0.006) + float(L.get("floor", 0.08))
            if k * lit < 0.01:
                continue
            gx, gy = place(*L["at"])
            col = L.get("color", glkit.T.rgb("white"))
            rad = float(L.get("radius", 4)) * scale
            k *= cover(gx, gy)                           # a lamp behind a cloud goes with the hull
            glows.append((depth + 0.01, (gx, gy, rad, rad, col[0], col[1], col[2], k * lit * float(L.get("gain", 1.0)), 0.0)))
        # trails: puffs laid where the exhaust was, drifting and spreading as they fade
        for i, T in enumerate(c.get("trails") or []):
            hist = e["trails"].setdefault(i, [])
            every = float(T.get("every", 0.12))
            if inst.alpha > 0.05 and (not hist or t - hist[-1][2] >= every):
                hist.append((*place(*T["at"]), t))
            life = float(T.get("life", 3.0))
            while hist and t - hist[0][2] > life:
                hist.pop(0)
            col = T.get("color", glkit.T.rgb("soft"))
            rad0 = float(T.get("radius", 3)) * scale
            gap = every * e["speed"] * 0.8          # puffs stretched along the path, so they join into one streak
            for (px, py, t0) in hist:
                age = (t - t0) / life
                k = float(T.get("gain", 0.2)) * (1.0 - age) ** 2 * (1.0 - 0.6 * haze) * min(1.0, (t - t0) / 0.15 + 0.3) \
                    * cover(px, py)
                if k < 0.004:
                    continue
                r = rad0 * (1.0 + age * float(T.get("spread", 2.5)))
                glows.append((depth - 0.01, (px, py + age * float(T.get("sink", 6.0)), max(r * 1.6, gap * 0.6), r, col[0], col[1], col[2], k, 0.0)))

    @staticmethod
    def _play_clip(inst, rel, hold):
        sp = inst.d.sprites.get(rel) if rel else None
        if sp is not None and sp.video is not None:
            inst.clip = sp
            inst.clip_hold = hold
            sp.video.restart()

    # ---- state machine
    def _set_state(self, inst, state, t):
        if state == inst.state:
            return
        prev = inst.state
        inst.state = state
        inst.state_t = t
        cfg = inst.d.state_cfg(state)
        if not cfg.get("turn"):
            inst.turn_target = 0.0
        else:
            inst.turn_target = 1.0
        sc = inst.slot_cfg or {}
        clip = ((sc.get("states") or {}).get(state, {}).get("clip")) or cfg.get("clip")
        inst.clip = None
        if clip and inst.d.sprites.get(clip) and inst.d.sprites[clip].video:
            inst.clip = inst.d.sprites[clip]        # a one-shot clip: plays once, then holds or chains
            inst.clip.video.restart()
            inst.clip_hold = bool(((sc.get("states") or {}).get(state, {}).get("hold")) or cfg.get("hold"))
        if inst.d.kind == "agents":
            under = prev is None or prev in ("finished", "gone")
            if state in ("working", "needs_you") and under:
                # an agent starts (or works again): bubbles, a swell, then it breaks the surface
                inst.sink = max(inst.sink, 1.0) if prev is None else inst.sink
                inst.rise_t = t
                inst.extra.pop("booted", None)
                self._play_clip(inst, (inst.slot_cfg or {}).get("rise_clip"), hold=False)
                if not (inst.slot_cfg or {}).get("rise_clip"):          # a clip paints its own
                    self.bubbles.append((inst.x, inst.y, t, 1.0))
                    self.bubbles.append((inst.x + 20, inst.y + 4, t + 0.7, 0.8))
            elif state in ("finished", "gone") and prev in ("working", "needs_you"):
                # it submerges: rings spread, the last bubbles rise, the fireflies scatter
                inst.rise_t = None
                inst.sub_t = t
                self._play_clip(inst, (inst.slot_cfg or {}).get("submerge_clip"), hold=True)
                if not (inst.slot_cfg or {}).get("submerge_clip"):
                    self.rings.append((inst.x, inst.y, t, 1.0))
                self.disturb.append((inst.x, inst.y - inst.d.height * 0.4, t))
        if state == "gone":
            inst.gone_t = t

    # ---- motions
    def _step(self, inst, t, dt, sig):
        d = inst.d
        if d.kind == "flyby":
            return self._step_flyby(inst, t)
        if inst.v is not None:
            return self._step_event(inst, t, dt, sig)
        if d.kind == "traffic":
            t0, dur, x0, x1, direction = inst.path
            f = (t - t0) / dur
            inst.x = x0 + (x1 - x0) * f if direction > 0 else x1 - (x1 - x0) * f
            inst.alpha = 1.0 if inst.busy else 0.0
            inst.light = 1.0
            inst.frame = int((t * float(d.t.get("fps", 0))) % max(len(d.sprite.frames), 1))
            return
        cfg = d.state_cfg(inst.state)
        req = d.t.get("requires")
        hidden = bool(cfg.get("hidden")) or bool(req and not sig.get(req))
        inst.alpha = _ease(inst.alpha, 0.0 if hidden else 1.0, dt, 0.8)
        inst.turn = _ease(inst.turn, getattr(inst, "turn_target", 0.0), dt, 0.35)
        target_light = float(cfg.get("light", 1.0))
        inst.light = _ease(inst.light, target_light, dt, 0.6)
        inst.lamp = _ease(inst.lamp, float(cfg.get("lamp", 1.0)), dt, 1.4)
        if inst.flare_t > 0:
            a = t - inst.flare_t
            inst.flare = math.exp(-((a - 0.3) ** 2) / 0.06) if -0.5 < a < 1.6 else 0.0
            if a > 1.6:
                inst.flare_t = -1.0
        m = cfg.get("motion", "hold")
        rise_t = getattr(inst, "rise_t", None)
        if d.kind == "agents" and rise_t is not None:
            a = t - rise_t
            hold = float(d.t.get("rise_hold", 1.2))          # bubbles first, still under
            dur = float(d.t.get("rise_seconds", 2.6))
            if a < hold:
                inst.sink = max(inst.sink, 1.0)
            elif a < hold + dur:
                if not inst.extra.get("swell"):
                    inst.extra["swell"] = True
                    if not (inst.slot_cfg or {}).get("rise_clip"):
                        self.rings.append((inst.x, inst.y, t, 0.9))   # the swell, as it breaks the surface
                    self.disturb.append((inst.x, inst.y - d.height * 0.3, t))
                f = _smooth((a - hold) / dur)
                inst.sink = 1.0 + (float(cfg.get("sink", 0.0)) - 1.0) * f
            else:
                inst.rise_t = None
                inst.extra.pop("swell", None)
            # the eyes boot with a flicker as they clear the water
            eye_v = float(d.t.get("eye_v", 0.3))                    # how far down the sprite the eyes sit
            wade = float(d.wade)
            clear = inst.sink + wade < (1.0 - eye_v)
            if clear and "booted" not in inst.extra:
                inst.extra["booted"] = t
        sub_t = getattr(inst, "sub_t", None)
        if sub_t is not None:
            for k, at in enumerate((2.6, 3.4)):                   # the last bubbles
                if t - sub_t >= at and not inst.extra.get(f"lastbub{k}"):
                    inst.extra[f"lastbub{k}"] = True
                    self.bubbles.append((inst.x + 14 * k, inst.y, t, 0.7))
            if t - sub_t > 4.0:
                inst.sub_t = None
                inst.extra.pop("lastbub0", None)
                inst.extra.pop("lastbub1", None)
        if "at" in cfg and d.kind in ("keeper", "signal"):     # a state can have its own place
            inst.x, inst.y = cfg["at"]
        elif "at" not in cfg and d.kind in ("keeper", "signal") and m != "pace":
            inst.x, inst.y = d.at
        inst.dx = inst.dy = inst.rot = 0.0
        inst.frame = None
        sink_target = float(cfg.get("sink", 0.0))
        if getattr(inst, "rise_t", None) is not None:
            pass                                    # the rise sets the sink itself
        elif m == "settle":
            inst.sink = _ease(inst.sink, sink_target, dt, 1.2)
        else:
            inst.sink = _ease(inst.sink, sink_target, dt, 1.5)
        if inst.state == "gone":
            fade = float(cfg.get("fade", 5.0))
            if t - getattr(inst, "gone_t", t) > fade:
                inst.dead = True
            inst.alpha = max(0.0, 1.0 - (t - inst.gone_t) / fade)
        amp, rate = float(cfg.get("amp", 2.0)), float(cfg.get("rate", 0.3))
        ph = inst.seed * TAU
        if m == "wander" and inst.turn < 0.05:
            z = getattr(inst, "zone", None) or (inst.x - 100, inst.y, inst.x + 100, inst.y)
            hid = d.t.get("hidden_x") if "depth" in inst.extra else None
            if inst.target is None or (abs(inst.target - inst.x) < 2 and t > inst.pause_until):
                inst.target = z[0] + (z[2] - z[0]) * inst.r.random()
                for _ in range(6):                  # never stop where it can't be seen (behind the kelp)
                    if not hid or not any(a <= inst.target <= b for a, b in hid):
                        break
                    inst.target = z[0] + (z[2] - z[0]) * inst.r.random()
            if abs(inst.target - inst.x) >= 2:
                sp = float(cfg.get("speed", 8.0)) * dt
                if hid and any(a <= inst.x <= b for a, b in hid):
                    sp *= 2.5                       # out from behind the kelp quickly
                step = max(-sp, min(sp, inst.target - inst.x))
                inst.x += step
                inst.dist += abs(step)
                inst.face = 1.0 if step > 0 else -1.0
                if abs(inst.target - inst.x) < 2:
                    inst.pause_until = t + 2 + 5 * inst.r.random()
            inst.dy = math.sin(t * 1.3 + ph) * float(cfg.get("bob", 1.5))
        elif m in ("bob", "hold"):
            inst.dy = math.sin(t * TAU * rate + ph) * (amp if m == "bob" else amp * 0.4)
        elif m == "rock":
            inst.rot = math.sin(t * TAU * rate + ph) * math.radians(amp)
        elif m == "hover":                             # `pace` < 1 slows it (a whole swarm drifting)
            k = float(cfg.get("pace", 1.0))
            inst.dx = math.sin(t * 0.7 * k + ph) * amp
            inst.dy = math.sin(t * 1.1 * k + ph) * amp * 0.8
        elif m == "roam":
            # a resident drifter (a jellyfish): wanders slowly round its spot in both axes, by
            # pulses (`rate` Hz: a push as the bell contracts, then coasting), bobbing, tilting a
            # little toward where it's going, never mirrored. `range` [rx, ry] round the spot;
            # `top` the highest its top may come (under the surface band); `hidden_x` spans it
            # never stops in
            ex = inst.extra
            rx, ry = cfg.get("range", (200, 120))
            hx, hy = inst.spot
            top = float(cfg.get("top", 0.0))
            hh = d.height * inst.scale * ex.get("zscale", 1.0)
            pos = ex.get("roam_at")
            if pos is None:
                pos = ex["roam_at"] = [inst.x, inst.y]
            tgt = ex.get("roam_to")
            if tgt is None or math.hypot(tgt[0] - pos[0], tgt[1] - pos[1]) < 6:
                hid = cfg.get("hidden_x") or d.t.get("hidden_x") or []
                for _ in range(8):
                    tgt = [hx + (inst.r.random() * 2 - 1) * rx, max(hy + (inst.r.random() * 2 - 1) * ry, top + hh)]
                    if not any(a <= tgt[0] <= b for a, b in hid):
                        break
                ex["roam_to"] = tgt
            rate = float(cfg.get("rate", 0.35))
            ph = t * TAU * rate + inst.seed * TAU
            push = max(0.0, math.sin(ph)) ** 2           # the bell contracting
            sp = float(cfg.get("speed", 9.0)) * (0.2 + 0.8 * push) * dt
            vx, vy = tgt[0] - pos[0], tgt[1] - pos[1]
            dist = math.hypot(vx, vy) or 1.0
            pos[0] += vx / dist * min(sp, dist)
            pos[1] += vy / dist * min(sp, dist)
            inst.x, inst.y = pos
            ex["flap"] = -0.07 * push                   # the bell squeezes as it pushes
            want = max(-0.22, min(0.22, vx / dist * 0.22))
            ex["tilt"] = _ease(ex.get("tilt", 0.0), want, dt, 4.0)
            inst.rot = ex["tilt"]
            inst.dy = math.sin(ph * 0.5) * float(cfg.get("bob", 4.0))
        elif m == "circle":
            inst.dx = math.cos(t * TAU * rate + ph) * amp
            inst.dy = math.sin(t * TAU * rate + ph) * amp * 0.35
            inst.face = -1.0 if math.sin(t * TAU * rate + ph) > 0 else 1.0
        elif m == "drift":
            inst.dx = math.sin(t * TAU * rate + ph) * amp
            inst.dy = math.sin(t * TAU * rate * 1.7 + ph) * amp * 0.1
            inst.face = 1.0 if math.cos(t * TAU * rate + ph) > 0 else -1.0
        elif m == "pace":
            path = cfg.get("path") or d.t.get("path") or (inst.x - 40, inst.x + 40)
            sp = float(cfg.get("speed", 6.0))
            span = abs(path[1] - path[0]) or 1.0
            per = 2 * span / sp + 2 * float(cfg.get("pause", 3.0))
            u = ((t + inst.seed * per) % per) / per
            pause = float(cfg.get("pause", 3.0)) / per
            if u < 0.5 - pause:
                f, inst.face = u / (0.5 - pause), 1.0
            elif u < 0.5:
                f = 1.0
            elif u < 1.0 - pause:
                f, inst.face = 1.0 - (u - 0.5) / (0.5 - pause), -1.0
            else:
                f = 0.0
            inst.x = path[0] + (path[1] - path[0]) * f
            inst.dist = inst.x
        elif m == "croak":
            puff = max(0.0, math.sin(t * TAU * rate + ph)) ** 8
            if puff > 0.5 and not inst.extra.get("puffing"):
                self.sounds.append(cfg.get("sound") or d.t.get("sound"))     # one croak, one cue
            inst.extra["puffing"] = puff > 0.5
            inst.extra["throat"] = puff
            every = float(cfg.get("hop_every", 0))
            if every and d.spots:                      # hop to another pad now and then
                k = int((t + inst.seed * every) // every)
                if k != inst.extra.get("hop_k"):
                    if inst.extra.get("hop_k") is not None:
                        free = [sp for sp in d.spots if sp != inst.spot]
                        inst.extra["hop"] = (inst.spot, free[inst.r.randrange(len(free))] if free else inst.spot, t)
                    inst.extra["hop_k"] = k
        elif m == "breach":
            self._breach(inst, t, cfg)
        elif m == "dive":
            a = t - inst.state_t
            inst.dy = min(a, 12.0) * float(cfg.get("speed", 30.0))
            inst.extra["shrink"] = math.exp(-a / 10.0)
        if d.kind == "crowd" and m == "circle":
            around = d.t.get("around", inst.spot)
            rad = float(cfg.get("radius", 120))
            spread = float(d.t.get("spread", 1.0))      # 1 = round the whole circle; small = one school
            a = t * TAU * rate * (1.0 + (0.4 * inst.seed - 0.2) * spread) + ph * spread
            inst.x = around[0] + math.cos(a) * rad * (0.7 + 0.5 * inst.seed)
            inst.y = around[1] + math.sin(a) * rad * 0.25 + (inst.seed - 0.5) * 60
            inst.dx = inst.dy = 0.0
            inst.face = -1.0 if math.sin(a) > 0 else 1.0
        elif d.kind == "crowd":
            hop = inst.extra.get("hop")
            if hop and t - hop[2] < 0.7:
                f = (t - hop[2]) / 0.7
                (x0, y0), (x1, y1) = hop[0], hop[1]
                inst.x, inst.y = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
                inst.dy = -math.sin(f * math.pi) * float(cfg.get("hop_height", 60))
                inst.face = 1.0 if x1 >= x0 else -1.0
            else:
                if hop:
                    inst.spot = hop[1]
                    inst.extra["hop"] = None
                inst.x, inst.y = inst.spot

    def _breach(self, inst, t, cfg):
        """Needs you, for swimmers: rise until just under the surface and wait there, glowing
        through it; leap clear once on arrival, then again now and then (`every`: seconds, or
        [lo, hi] for a random gap) so a long wait stays a signal and never a twitch. `hold`
        is how deep its feet (the sprite's bottom edge) wait, in body heights below the surface:
        above 1.0 it's all under; `leap_height` above `hold` clears the water."""
        world = inst.d.world
        surf = world.surface_y if world else 640.0
        a = t - inst.state_t
        rise = _smooth(a / 4.0)
        y_hold = surf + inst.d.height * float(cfg.get("hold", 1.15))
        inst.dy = (y_hold - inst.y) * rise + math.sin(a * 0.9) * 3.0
        every = cfg.get("every", 7.0)
        lo, hi = (float(every[0]), float(every[1])) if isinstance(every, (list, tuple)) else (float(every),) * 2
        hop = float(cfg.get("leap", 1.6))
        ex = inst.extra
        if ex.get("breach_state_t") != inst.state_t:       # a new wait: the first leap once it's up
            ex["breach_state_t"] = inst.state_t
            ex["leap_at"] = inst.state_t + 4.0
            ex["leaps"] = 0
        u = t - ex["leap_at"]
        if u >= hop:                                        # that leap is over: schedule the next
            ex["leap_at"] = t + lo + (hi - lo) * inst.r.random()
            ex["leaps"] += 1
        elif u >= 0.0:
            f = u / hop
            inst.dy += -math.sin(f * math.pi) * inst.d.height * float(cfg.get("leap_height", 1.3))
            inst.rot = (0.5 - f) * 0.7 * inst.face
            for edge, ff in (("up", 0.08), ("down", 0.86)):
                tag = (inst.state_t, ex["leaps"], edge)
                if f > ff and tag not in ex.setdefault("sprayed", set()):
                    ex["sprayed"].add(tag)
                    self.spray.append((inst.x, surf, t, 1.0))

    def _step_event(self, inst, t, dt, sig):
        v, d = inst.v, inst.d
        dur = float(v.get("seconds", 6.0))
        a = t - inst.born
        f = a / dur
        if f >= 1.0:
            inst.dead = True
            return
        fin, fout = float(v.get("fade_in", 0.35)), float(v.get("fade_out", 0.8))
        inst.alpha = _smooth(a / max(fin, 1e-3)) * _smooth((dur - a) / max(fout, 1e-3))
        inst.light = 1.0
        inst.dx = inst.dy = inst.rot = 0.0
        r = inst.r
        m = v.get("motion", "rise")
        if inst.path is None:
            zones = v.get("from") or d.t.get("from") or [[d.at[0], d.at[1], d.at[0], d.at[1]]]
            z = zones[r.randrange(len(zones))]
            self._band(inst, z[4] if len(z) > 4 else None)
            p0 = (z[0] + (z[2] - z[0]) * r.random(), z[1] + (z[3] - z[1]) * r.random())
            to = v.get("to") or d.t.get("to") or [[p0[0] + 400, p0[1] - 600]]
            if to and not isinstance(to[0], (list, tuple)):
                to = [to]
            if v.get("distinct") and "ev" in inst.extra:   # each of the event's creatures its own target
                b, k = inst.extra["ev"]
                p1 = tuple(to[(b + k) % len(to)])
            else:
                p1 = tuple(to[r.randrange(len(to))])
            if v.get("under") is not None:               # start beneath its target (± under px), not anywhere
                p0 = (p1[0] + (r.random() * 2 - 1) * float(v["under"]), p0[1])
            if m == "drift_up":                      # a bloom rises from the deep toward the surface
                p1 = (p0[0] + (r.random() - 0.5) * 160, float(v.get("rise_to", 700)) + r.random() * 60)
            if m == "reel":
                w = d.world
                p0 = w.line_end() if w else p0
                p1 = w.line_tip() if w else p1
                self.spray.append((p0[0], p0[1], t, 0.5))
            inst.path = (p0, p1)
            inst.face = 1.0 if p1[0] >= p0[0] else -1.0
            sc = v.get("scale")
            if isinstance(sc, (list, tuple)):              # a size range: each one its own distance
                inst.scale = float(sc[0]) + (float(sc[1]) - float(sc[0])) * r.random()
            elif sc is not None:
                inst.scale = float(sc)
        (x0, y0), (x1, y1) = inst.path
        if m == "rise":
            e = f * f * (3 - 2 * f) * 0.4 + f * 0.6
            inst.x = x0 + (x1 - x0) * e
            inst.y = y0 + (y1 - y0) * e - math.sin(f * math.pi) * 60
            inst.scale = 1.0 - 0.45 * f
            inst.frame = int(a * float(v.get("fps", 3.0)))
        elif m == "approach":
            e = f ** 1.8
            inst.x = x0 + (x1 - x0) * e
            inst.y = y0 + (y1 - y0) * e
            inst.scale = 0.35 + (float(v.get("grow", 5.0)) - 0.35) * e
            inst.extra["flap"] = math.sin(a * TAU * float(v.get("fps", 2.4))) * 0.08
            inst.frame = None
        elif m == "reel":
            w = d.world
            if w:
                (x1, y1) = w.line_tip()
            hold = 0.75
            e = _smooth(min(f / hold, 1.0))
            inst.x = x0 + (x1 - x0) * e
            inst.y = y0 + (y1 - y0) * e - math.sin(e * math.pi) * 90
            inst.rot = math.sin(a * TAU * float(v.get("wriggle", 5.0))) * 0.35 * (1.0 - 0.6 * e)
            inst.frame = 0
            if w:
                w.line_hook = (inst.x, inst.y - d.height * 0.5)
        elif m == "drift_up":
            e = f
            inst.x = x0 + math.sin(a * 0.6 + inst.seed * TAU) * 18 + (x1 - x0) * e
            inst.y = y0 + (y1 - y0) * e
            inst.frame = int(a * float(v.get("fps", 0.9)))
            inst.scale = 0.8 + 0.4 * inst.seed
        elif m == "glide":
            # a calm pass through the water: steady with soft ends, on a shallow arc, a slow
            # bob, banking with its path (`bank`, 0..1), turning on itself at `spin` rad/s
            def at(ff):
                ee = _smooth(ff) * 0.4 + ff * 0.6
                arc = float(v.get("arc", 60.0)) * (0.6 + 0.8 * inst.seed)
                return (x0 + (x1 - x0) * ee,
                        y0 + (y1 - y0) * ee - math.sin(ee * math.pi) * arc)
            inst.x, inst.y = at(f)
            nx, ny = at(min(f + 0.01, 1.0))
            px, py = at(max(f - 0.01, 0.0))
            bob = float(v.get("bob", 5.0))
            inst.dy = math.sin(a * float(v.get("bob_rate", 0.8)) + inst.seed * TAU) * bob
            slope = math.atan2(ny - py, abs(nx - px) or 1e-3)
            inst.rot = max(-0.4, min(0.4, slope * float(v.get("bank", 0.6)))) * inst.face \
                + a * float(v.get("spin", 0.0)) * (1.0 if inst.seed > 0.5 else -1.0)
            inst.frame = None
        elif m == "dart":
            e = 1.0 - (1.0 - f) ** 3
            inst.x = x0 + (x1 - x0) * e
            inst.y = y0 + (y1 - y0) * e + math.sin(a * 9) * 3
            inst.extra["glint"] = math.exp(-((a - 0.4) ** 2) / 0.05) + 0.5 * math.exp(-((a - 1.3) ** 2) / 0.04)
            inst.frame = int(a * float(v.get("fps", 0.0)))   # a swim cycle when the event gives one

    # ---- output
    @staticmethod
    def _rect(d, r):
        """[x, y, w, h] on the plate, or a clip's name (its rect from live/clips/manifest.toml)."""
        if isinstance(r, str):
            m = (d.world.manifest.get(r) or d.world.manifest.get("clips", {}).get(r) or {}) if d.world else {}
            r = m.get("rect") if isinstance(m, dict) else m
        return tuple(float(v_) for v_ in r) if r else None

    @staticmethod
    def _override(inst, t):
        o = getattr(inst, "override", None)
        if o and o[1] <= t < o[2]:
            return o[0]
        return None

    @staticmethod
    def _pose(inst, d):
        poses = d.t.get("poses")
        if not poses:
            return None
        hop = inst.extra.get("hop")
        key = "hop" if hop else ("croak" if inst.extra.get("throat", 0.0) > 0.35 else "sit")
        return d.sprites.get(poses.get(key) or poses.get("sit"))

    def _blink(self, inst, t, cfg):
        """The lights' level for the state: a double flash then a calm 0.55 Hz blink for "needs
        you" (`signal`), a pulse, a flicker; for a rising agent, dark until its eyes clear the
        water, then a boot flicker. Under reduced motion (`calm`) they hold steady: "needs
        you" is the signal colour burning brighter, a rising agent's eyes come up smoothly."""
        if self.calm:
            if inst.d.kind == "agents" and (getattr(inst, "rise_t", None) is not None or "booted" in inst.extra):
                b = inst.extra.get("booted")
                if b is None:
                    return 0.0                          # still under: the eyes are dark
                if t - b > 6.0:
                    inst.extra.pop("booted", None)
                return min(1.0, 0.25 + (t - b) / 1.5)   # up over a second and a half, no flicker
            return 1.3 if cfg.get("signal") else 1.0
        blink = 1.0
        if inst.d.kind == "agents" and getattr(inst, "rise_t", None) is not None or "booted" in inst.extra:
            b = inst.extra.get("booted")
            if b is None:
                return 0.0                              # still under: the eyes are dark
            a = t - b
            if a < 0.9:                                 # the boot: an uneven flicker, settling
                on = (math.sin(a * 61.0) * math.sin(a * 23.0 + 1.3)) > (-0.3 + a * 0.5)
                return (1.3 if on else 0.15) * min(1.0, 0.3 + a)
            if a > 6.0:
                inst.extra.pop("booted", None)
        if cfg.get("signal"):
            a = t - inst.state_t
            if a > 1.2:
                blink = 0.55 + 0.45 * math.sin(TAU * 0.55 * (a - 1.2) - math.pi / 2)
            else:                                       # the double flash
                blink = 1.7 * (math.exp(-((a - 0.2) ** 2) / 0.005) + math.exp(-((a - 0.6) ** 2) / 0.005)) + 0.35
        if cfg.get("pulse"):
            blink *= 0.7 + 0.3 * math.sin(t * TAU * float(cfg["pulse"]))
        if cfg.get("flicker"):
            blink *= 0.5 + 0.5 * (math.sin(t * 23.0) * math.sin(t * 7.1) > -0.2)
        return blink

    def _emit(self, inst, t, sig, sprites, glows, wakes):
        d = inst.d
        v = inst.v or {}
        if inst.alpha <= 0.003:
            return
        cfg = d.state_cfg(inst.state) if inst.v is None else v
        sc = inst.slot_cfg
        st_sprite = (sc.get("states") or {}).get(inst.state, {}).get("sprite") if sc else None
        sprite = d.sprites.get(v.get("sprite")) if v.get("sprite") else None
        clip = getattr(inst, "clip", None)
        if clip is not None and clip.video.finished() and not getattr(inst, "clip_hold", False):
            inst.clip = clip = None                 # the clip is over: chain into the state's loop or sprite
        sprite = sprite or clip or (d.sprites.get(st_sprite) if st_sprite else None) \
            or (d.sprites.get(cfg.get("sprite")) if cfg.get("sprite") else None) \
            or (d.sprites.get(sc.get("sprite")) if sc.get("sprite") else None) \
            or (d.sprites.get(inst.extra["sprite"]) if inst.extra.get("sprite") else None) or d.sprite
        ov = self._override(inst, t)                 # a keeper's pose for an event (Hollis's catch)
        if ov:
            sprite = d.sprites.get(ov.get("sprite")) or sprite
        pose = self._pose(inst, d)                   # a crowd's pose still (a frog sitting, croaking, hopping)
        if pose is not None:
            sprite = pose
        h = float(sc.get("height") or cfg.get("height", d.height)) * inst.scale * inst.extra.get("shrink", 1.0) \
            * inst.extra.get("zscale", 1.0)
        depth = float(v.get("depth", cfg.get("depth", inst.extra.get("depth", d.depth))))
        # frame: the turn gesture, the state's strip, or the walk cycle
        front = d.frames.get("front")
        fsprite = d.sprites.get(d.t.get("front_sprite")) if d.t.get("front_sprite") else None
        if fsprite is not None:
            front = front or [0]
        if inst.turn > 0.5 and front:
            fi = front[0]
            sx = (inst.turn - 0.5) * 2.0
            if fsprite is not None:
                sprite = fsprite
        else:
            # turning without a front view: squash to the edge and open out the other way
            sx = inst.face * abs(1.0 - 2.0 * inst.turn) if inst.turn > 0.02 else inst.face
            if inst.frame is not None:
                fl = d.frame_list(v.get("frames_key", "fly") if inst.v is not None else inst.state, d.frame_list("walk"))
                fi = fl[inst.frame % len(fl)] if inst.v is not None or d.kind == "traffic" else inst.frame
            elif inst.state in d.frames:
                fl = d.frames[inst.state]
                fps = float(cfg.get("fps", 0.5))
                fi = fl[int(t * fps + inst.seed * 7) % len(fl)]
            elif "walk" in d.frames and cfg.get("motion") == "wander":
                fl = d.frames["walk"]
                stride = max(d.height * 0.12, 4.0)
                fi = fl[int(inst.dist / stride) % len(fl)]
            elif "frame" in cfg:
                fi = int(cfg["frame"])
            else:
                fi = 0
            if inst.v is not None and v.get("motion") == "approach" and front:
                fi, sx = front[0], 1.0
        if inst.v is not None and "frame" in v:
            fi = int(v["frame"])
        if d.t.get("faces") == "left":               # art drawn facing left: flip it so `face` reads the same
            sx = -sx
        u0, v0, u1, v1, asp = sprite.frame(fi)
        w = h * asp
        patch = (ov or {}).get("rect") or cfg.get("rect") or sc.get("patch") or d.t.get("patch") or d.t.get("rect")
        patch = self._rect(d, patch)
        sy = 1.0 + inst.extra.get("flap", 0.0) + (0.0 if d.t.get("poses") else 0.12 * inst.extra.get("throat", 0.0))
        wade = float(cfg.get("wade", d.wade)) if (d.wade or "wade" in cfg) and not patch else 0.0
        x = inst.x + inst.dx
        cut = inst.y + inst.dy * 0.0 if wade > 0 else -1.0
        base = inst.y + inst.dy + (wade + inst.sink) * h
        if wade <= 0:
            base = inst.y + inst.dy + inst.sink * h
        if patch:                                   # placed by its rect on the plate (a patch of the scene, a still)
            px0, py0, pw, ph = patch
            x, base, w, h, sy = px0 + pw / 2 + inst.dx, py0 + ph + inst.dy, pw, ph, 1.0
            sx = 1.0
        tint = cfg.get("tint") or v.get("tint") or inst.extra.get("tint")
        bright = float(cfg.get("bright", v.get("bright", 1.0))) * inst.extra.get("zbright", 1.0)
        br = cfg.get("breathe")                      # a slow swell of its own light: [amount, Hz]
        if br:
            bright *= 1.0 + float(br[0]) * math.sin(t * TAU * float(br[1]) + inst.seed * TAU)
        par = d.parallax
        spr = {"x": x, "y": base, "w": w * sx, "h": h * sy, "uv": (u0, v0, u1, v1), "rot": inst.rot, "video": sprite.video,
               "alpha": inst.alpha, "cut": cut, "tint": tint, "bright": bright, "fog": d.fog,
               "reflect": d.reflect if wade > 0 else 0.0, "par": par,
               "add": (v.get("blend") or cfg.get("blend") or d.t.get("blend")) == "add"}   # glow creatures on black
        sprites.append((depth, spr))
        inst.placed = (x, base, w * sx, h * sy, inst.rot, fi)
        # a tow (a trawler's net): its own sprite hung from a point on the actor, drawn just
        # behind it, trailing aft whichever way the actor faces, swaying on its cable
        tow = d.t.get("tow")
        if tow and d.sprites.get(tow.get("sprite")) and not patch:
            ts = d.sprites[tow["sprite"]]
            tu0, tv0, tu1, tv1, tasp = ts.frame(0)
            th = h * sy * float(tow.get("height", 0.5))
            tw = th * tasp * (1.0 if sx >= 0 else -1.0)
            au, av = tow.get("at", (0.1, 0.5))         # on the actor, as drawn facing right
            ca, sa = math.cos(inst.rot), math.sin(inst.rot)
            lx, ly = (au - 0.5) * w * sx, (av - 1.0) * h * sy
            px, py = x + lx * ca - ly * sa, base + lx * sa + ly * ca
            sway = math.sin(t * TAU * float(tow.get("rate", 0.2)) + inst.seed * TAU)
            ang = math.radians(float(tow.get("angle", 0.0)) + float(tow.get("sway", 3.0)) * sway)
            rot = inst.rot + (ang if sx >= 0 else -ang)  # + swings the bottom aft (left) of a boat facing right
            pu, pv = tow.get("pivot", (1.0, 0.0))       # on the tow sprite, as drawn for an actor facing right
            qx, qy = (pu - 0.5) * tw, (pv - 1.0) * th
            cr, sr = math.cos(rot), math.sin(rot)
            sprites.append((depth - float(tow.get("behind", 0.01)),
                            dict(spr, x=px - (qx * cr - qy * sr), y=py - (qx * sr + qy * cr), w=tw, h=th,
                                 uv=(tu0, tv0, tu1, tv1), rot=rot, video=ts.video, add=False)))
        # an emissive mask (eye-lamps painted as light): drawn additively in the light's colour
        em = sc.get("emissive") or d.t.get("emissive")
        if em and d.sprites.get(em):
            es = d.sprites[em]
            col = (d.error_color if inst.error else d.signal_color) if cfg.get("signal") else \
                tuple(cfg.get("color") or sc.get("light_color") or d.t.get("light_color", glkit.T.rgb("cyan")))
            lit_e = inst.light * inst.alpha * self._blink(inst, t, cfg) * (1.0 + (0.5 if self.calm else 1.8) * inst.flare)
            if lit_e > 0.01:
                e_uv = es.frame(fi)
                er = self._rect(d, sc.get("emissive_rect"))
                place = {}
                if er:                              # the mask has its own rect (a piece inside a bigger patch)
                    place = {"x": er[0] + er[2] / 2 + inst.dx, "y": er[1] + er[3] + inst.dy, "w": er[2], "h": er[3]}
                sprites.append((depth + 0.005, dict(spr, **place, uv=e_uv[:4], video=es.video, tint=(col[0], col[1], col[2], 1.0),
                                                     bright=lit_e * float(d.t.get("emissive_gain", 1.4)), add=True, emissive=True,
                                                     reflect=0.0)))
        # a diver leaves a fading trail of light above it
        if cfg.get("motion") == "dive" and inst.v is None:
            a = t - inst.state_t
            c = tuple(cfg.get("trail", glkit.T.rgb("cyan")))
            for k in range(1, 9):
                ty = base - h * 0.5 - k * 34.0 * min(a, 12.0) / 12.0 * 3.0
                inten = 0.5 * math.exp(-k / 3.0) * math.exp(-a / 9.0) * inst.alpha
                if inten > 0.01:
                    glows.append((depth + 0.01, (x + math.sin(k * 1.7 + a) * 6, ty, 5.0, 5.0, c[0], c[1], c[2], inten,
                                                 1.0 if d.fog else 0.0)))
        # wakes: wading things that move ruffle the water
        if wade > 0 and inst.alpha > 0.2:
            moving = 1.0 if (cfg.get("motion") == "wander" and inst.target is not None
                             and abs(inst.target - inst.x) >= 2) else 0.25
            wakes.append((x, inst.y, moving * inst.alpha * (1.0 - min(inst.sink, 1.0) * 0.6)))
        # lights
        col_sig = None
        if cfg.get("signal"):
            col_sig = d.error_color if inst.error else d.signal_color
        blink = self._blink(inst, t, cfg)
        lit = (inst.light * inst.alpha * blink * (1.0 + (0.5 if self.calm else 1.8) * inst.flare) + inst.extra.get("glint", 0.0)) \
            * inst.extra.get("zbright", 1.0)
        lights = cfg.get("lights") or v.get("lights") or ([v["light"]] if v.get("light") else None) \
            or sc.get("lights") or d.lights
        if lit > 0.01 and lights:
            ca, sa = math.cos(inst.rot), math.sin(inst.rot)
            for L in lights:
                if inst.turn > 0.5 and front:
                    if "front_at" not in L and any("front_at" in M for M in lights):
                        continue                    # a side light the front view doesn't show
                    lu, lv = L.get("front_at", L["at"])
                    lu = 0.5 + (lu - 0.5) * abs(sx)
                else:
                    lu, lv = L["at"]
                    if sx < 0:
                        lu = 1.0 - lu
                    lu = 0.5 + (lu - 0.5) * abs(sx) if abs(sx) < 1 else lu
                lx = (lu - 0.5) * abs(w)
                ly = -(1.0 - lv) * h * sy
                gx = x + lx * ca - ly * sa
                gy = base + lx * sa + ly * ca
                if wade > 0 and gy > cut + 1:
                    continue
                own = inst.extra.get("light_color") or inst.extra.get("tint")   # its own colour: its lights wear it
                c = col_sig or tuple(cfg.get("color") or (own[:3] if own else None) or L.get("color", glkit.T.rgb("white")))
                rad = float(L.get("radius", 6)) * (h / max(d.height, 1)) ** 0.5
                if col_sig:
                    rad *= float(d.t.get("signal_radius", 1.8))
                glows.append((depth + 0.01, (gx, gy, rad, rad, c[0], c[1], c[2], lit * float(L.get("gain", 1.0)),
                                             1.0 if d.fog else 0.0)))
                spill = float(L.get("spill", d.t.get("spill", 0.0)))
                if spill > 0:                       # light spilling on the water and the pads around it
                    glows.append((depth + 0.01, (gx, gy + rad * 3, rad * 9, rad * 4, c[0], c[1], c[2], lit * spill, 0.0)))
                if wade > 0 and d.reflect > 0:      # the lamp's streak in the water
                    glows.append((depth + 0.01, (gx, 2 * cut - gy, rad * 1.3, rad * 3.2, c[0], c[1], c[2],
                                                 lit * d.reflect * 0.45, 0.0)))
