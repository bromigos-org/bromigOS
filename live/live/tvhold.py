"""The remote's pause, a DVR's: hold the picture where it is, play on from there.

A den channel plays as if live: its schedule says what's on at every moment, and a screen
coming back into view jumps to where the channel is now. A pause from a remote (BRODEC's,
`bromigos-live tv pause`) is the viewer's, not the den's: it holds the picture, and play
goes on from that moment, behind the channel's schedule, until a channel change or
JUMP TO LIVE puts it back on the schedule.

    held          the screen's player is paused by the remote. The automatic pausing (a
                  window over the screen, the lock screen, no frames drawn) never undoes
                  it: tick() pauses a held screen whatever it sees.
    behind        seconds behind the schedule: the time spent held, added up. The screen
                  plays its channel's schedule as it was that long ago (now_next at
                  now - behind), its own copy of the channel: another screen on the same
                  channel stays live.
    the mark      "PAUSED · −4:12" while held, "BEHIND LIVE · −4:12" after, bottom left.

Something picked (on demand) has no schedule: a pause holds it and play goes on from there.
"""
import time

MAX_BEHIND = 6 * 3600.0          # a day's worth of TV is not a pause: past this, back to live


def clock(seconds):
    s = max(0, int(seconds))
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class Hold:
    def init_hold(self):
        self.holds = {}                    # screen -> {"shift": seconds behind so far, "held_at": wall time or None}

    # ---- state
    def held(self, screen):
        h = self.holds.get(screen)
        return bool(h and h.get("held_at") is not None)

    def behind(self, screen, now=None):
        """Seconds behind the channel's schedule, or 0 (live, or something picked)."""
        h = self.holds.get(screen)
        if not h:
            return 0.0
        now = time.time() if now is None else now
        return h["shift"] + (now - h["held_at"] if h.get("held_at") is not None else 0.0)

    def hold_tag(self, screen):
        """The mark on the screen: "PAUSED · −4:12", "BEHIND LIVE · −4:12", or None."""
        h = self.holds.get(screen)
        if not h:
            return None
        if screen in self.overrides:
            return "PAUSED" if self.held(screen) else None
        b = self.behind(screen)
        if self.held(screen):
            return f"PAUSED · −{clock(b)}"
        return f"BEHIND LIVE · −{clock(b)}" if b >= 1 else None

    def hold_describe(self, screen):
        b = self.behind(screen)
        return {"held": self.held(screen),
                "behind": round(b, 1) if b >= 1 and screen not in self.overrides else None}

    # ---- the channel and its schedule, time-shifted
    def hold_channel(self, screen, ch):
        """The screen's channel, or its own copy of it behind the schedule."""
        if screen not in self.holds or ch.get("override") or ch["kind"] == "own":
            return ch
        return dict(ch, key=f"{ch['key']}~behind-{screen}", base_key=ch["key"], behind_screen=screen)

    def hold_slot(self, ch):
        import bromigos_tv as TVL
        screen = ch["behind_screen"]
        base = {k: v for k, v in ch.items() if k not in ("behind_screen", "base_key")}
        base["key"] = ch["base_key"]
        b = self.behind(screen)
        if b > MAX_BEHIND:
            self.release_hold(screen)
            return TVL.now_next(base)
        return TVL.now_next(base, time.time() - b)

    # ---- the remote's presses
    def _rekey(self, screen):
        """The screen's player keeps what it has loaded under the channel's new key (live, or
        behind): a pause never reloads the picture."""
        d = self.decks[screen]
        if d.loaded:
            d.loaded = (self.channel(screen)[1]["key"], d.loaded[1])

    def hold(self, screen, value="toggle"):
        """Pause (on), play on from where it was (off), or toggle."""
        if screen in getattr(self, "links", {}):
            return f"{screen} is linked to a channel: its party or stream sets play and pause"
        n, ch = self.channel(screen)
        if ch["kind"] == "own":
            return f"{screen}: nothing to pause on the screen's own picture"
        on = {"on": True, "off": False}.get(value, not self.held(screen))
        now = time.time()
        h = self.holds.get(screen)
        if on:
            if self.held(screen):
                return f"{screen}: paused"
            if h is None:
                h = self.holds[screen] = {"shift": 0.0, "held_at": None}
                self._rekey(screen)
            h["held_at"] = now
            self.feedback(screen, "PAUSED")
        else:
            if not self.held(screen):
                return f"{screen}: playing"
            h["shift"] += now - h["held_at"]
            h["held_at"] = None
            self.feedback(screen, "PLAY")
        self._hold_player(screen, on)
        self.wake.set()
        self._changed()
        b = self.behind(screen, now)
        if on:
            return f"{screen}: paused"
        if screen in self.overrides:
            return f"{screen}: playing"
        return f"{screen}: playing, {clock(b)} behind live"

    def _hold_player(self, screen, on):
        d = self.decks[screen]
        try:
            if d.player is not None:
                d.player.pause(on or not d.allowed)
        except Exception:                                   # noqa: BLE001
            pass
        fs = getattr(self, "full_session", None)
        if fs and fs.screen == screen:
            fs.send("set_property", "pause", bool(on))

    def release_hold(self, screen):
        """Back on the schedule (a channel change, something picked, JUMP TO LIVE)."""
        h = self.holds.pop(screen, None)
        if h is None:
            return False
        fs = getattr(self, "full_session", None)
        if h.get("held_at") is not None and fs and fs.screen == screen:
            fs.send("set_property", "pause", False)
        return True

    def jump_live(self, screen):
        """Where the channel is now: the hold ends and the picture is put back on the schedule."""
        if screen not in self.holds:
            return f"{screen}: already live"
        on_demand = screen in self.overrides
        self.release_hold(screen)
        if on_demand:
            self._hold_player(screen, False)
            return f"{screen}: playing"
        self._unload(self.decks[screen])                    # a new stream at where the channel is now
        self.feedback(screen, "LIVE")
        fs = getattr(self, "full_session", None)
        if fs and fs.screen == screen:
            fs.retune()
        self.wake.set()
        self._changed()
        return f"{screen}: live"
