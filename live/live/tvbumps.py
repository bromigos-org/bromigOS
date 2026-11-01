"""Den TV's bumps on the den's screens and in full screen (lib/bromigos_bumps.py has the
packs, the night block and the caps; live/README.md, "Bumps").

A bump plays as a screen's on-demand item (Controls.overrides, reason "BUMP"): its clip is a
local file, so it opens at once and needs no server. Between items the channel waits for it
(bromigos_tv.channel_hold), so nothing is missed; on a channel change it covers the tune and
the channel plays on underneath. Changing channel again, `skip` or `live` ends it.

A bump plays only where someone can see it: the screen drawn, in view and decoding, full
motion, not while the desktop is locked or the screensaver runs, nor while VECTOR speaks.
Screens on the same channel show the same bump from one player.
"""
import time

import bromigos_bumps as B
import bromigos_tv as TVL

TUNE_SETTLE = 1.0       # seconds after a tune before its bump may start (a second press in that time: none)
BOUNDARY = 3.0          # seconds into an item that still count as "between items"


class Bumps:
    def init_bumps(self):
        self.bump_state = B.load_state()
        self._bump_cache = (0.0, [])
        self.bump_rng = None                   # tests set a seeded random.Random
        self._tune_pending = {}                # screen -> (monotonic when, channel key)

    # ------------------------------------------------------------------ what's installed
    def bump_list(self):
        """The allowed bumps, read again every 30 s at most (a pack installed meanwhile)."""
        now = time.monotonic()
        at, cached = self._bump_cache
        if now - at > 30.0:
            cached = B.all_bumps(self.cfg)
            self._bump_cache = (now, cached)
        return cached

    def _bump_ok(self, screen):
        d = self.decks[screen]
        return (self.enabled() and d.allowed and not d.capped and self.motion == "full" and not self.quiet
                and not self.ducked and not (self.full_session and self.full_session.screen == screen))

    def bumping(self, screen):
        o = self.overrides.get(screen)
        return o if o and o.get("reason") == "BUMP" else None

    # ------------------------------------------------------------------ when one plays
    def bump_between(self, d, ch, slot):
        """An item on the channel just ended on this screen: a bump, if one is due. True when
        one started (the caller loads nothing else)."""
        if ch.get("override") or ch["kind"] in ("own", "live") or slot is None or slot.offset is None:
            return False
        if slot.offset > BOUNDARY or not self._bump_ok(d.name):
            return False
        pick = B.choose("between", time.time(), self.cfg, self.bump_state, self.bump_list(), self.bump_rng)
        if not pick:
            return False
        bump, role = pick
        TVL.channel_hold(ch, bump.seconds + slot.offset)
        self.last_slot.pop(ch["key"], None)
        screens = [s for s, c in self.media_screens() if c["key"] == ch["key"]]
        self._play_bump(screens or [d.name], bump, role, ch)
        return True

    def bump_tuned(self, screen):
        """A person changed channel on this screen: a short bump may cover the tune, once it
        settles (bumps_tick), never while they're flicking through."""
        n, ch = self.channel(screen)
        if ch["kind"] == "own":
            self._tune_pending.pop(screen, None)
            return
        self._tune_pending[screen] = (time.monotonic(), ch["key"])

    def bumps_tick(self):
        now = time.monotonic()
        for screen, (at, key) in list(self._tune_pending.items()):
            if now - at < TUNE_SETTLE:
                continue
            del self._tune_pending[screen]
            n, ch = self.channel(screen)
            if ch["key"] != key or not self._bump_ok(screen) or self.bumping(screen):
                continue
            pick = B.choose("tune", time.time(), self.cfg, self.bump_state, self.bump_list(), self.bump_rng)
            if pick:
                self._play_bump([screen], pick[0], pick[1], ch)

    def _play_bump(self, screens, bump, role, ch, record=True):
        at = time.monotonic()
        item = {"id": bump.id, "title": bump.caption or "Bump", "duration": bump.seconds, "server": "files",
                "kind": "bump", "url": bump.path}
        for s in screens:
            self.overrides[s] = dict(item=item, at=at, offset=0.0, reason="BUMP", channel=ch, bump=bump, role=role)
            self._unload(self.decks[s])
        if record:
            self.bump_state = B.record(self.bump_state, bump, role, time.time(), self.cfg)
            try:
                B.save_state(self.bump_state)
            except OSError:
                pass
        self.log(f"tv: bump {bump.id} ({role}) on {', '.join(screens)}")
        self.wake.set()
        self._changed()

    def bump_audio(self, screen):
        """The sting's path for a bump starting on this screen, when stings are on."""
        o = self.bumping(screen)
        if not o or not B.settings(self.cfg)["sting"]:
            return None
        return o["bump"].sting

    def bump_caption(self, screen):
        """("bump", caption, channel name, alpha) while a bump with a caption plays, else None.
        The caption fades in after a second and out before the end."""
        o = self.bumping(screen)
        if not o or not o["bump"].caption:
            return None
        age = time.monotonic() - o["at"]
        secs = o["bump"].seconds
        if age < 0.8 or age > secs - 0.2:
            return None
        alpha = min(1.0, (age - 0.8) / 0.5, (secs - 0.2 - age) / 0.5) if self.motion == "full" else 1.0
        return ("bump", o["bump"].caption, o["channel"]["name"], round(max(0.0, alpha), 1))

    # ------------------------------------------------------------------ full screen
    def full_bump(self, screen):
        """The full-screen player's item ended on a channel: a bump to play before the next,
        with the channel held for it, or None."""
        n, ch = self.channel(screen)
        if ch.get("override") or ch["kind"] in ("own", "live") or not self.enabled():
            return None
        pick = B.choose("between", time.time(), self.cfg, self.bump_state, self.bump_list(), self.bump_rng)
        if not pick:
            return None
        bump, role = pick
        TVL.channel_hold(ch, bump.seconds)
        self.last_slot.pop(ch["key"], None)
        self.bump_state = B.record(self.bump_state, bump, role, time.time(), self.cfg)
        try:
            B.save_state(self.bump_state)
        except OSError:
            pass
        self.log(f"tv: bump {bump.id} ({role}) in full screen")
        return bump

    # ------------------------------------------------------------------ commands
    def bump_command(self, rest, screen):
        """bromigos-live tv bumps [status] | bump [ID] [--screen S]: what's set, or play one now."""
        if rest[:1] in ([], ["status"]):
            import json
            return json.dumps(B.status(self.cfg), indent=1)
        return "bromigos-live tv bumps [status]  (on, night or off: bromigos-live tv bumps-mode, Settings › Den TV)"

    def bump_now(self, screen, want=None):
        """Play a bump now on a screen (a test, or the remote's ident button): one by id, or any."""
        n, ch = self.channel(screen)
        if ch["kind"] == "own":
            return f"{screen}: tune a channel first (channel 1 is the screen's own picture)"
        bumps = self.bump_list() if not want else [b for b in B.all_bumps(self.cfg) if b.id == want
                                                   or b.id.endswith("/" + want)]
        if not bumps:
            return "No bumps installed (bromigos-mascot-art)" if not want else f"No bump called {want}"
        import random
        bump = (self.bump_rng or random).choice(sorted(bumps, key=lambda b: b.id))
        self._play_bump([screen], bump, "now", ch, record=False)
        return f"{screen}: bump {bump.id}"
