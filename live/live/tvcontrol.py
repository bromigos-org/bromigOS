"""The den's number-pad remote and playback. All inputs call TV's same actions."""
import json
import subprocess
import time

import bromigos_tv as TVL


class Controls:
    def init_controls(self):
        self.overrides = {}
        self.history = {s: [] for s in TVL.SCREENS}
        self.selected = None
        self.remote_at = 0.0
        self.digits = None
        self.digits_at = 0.0

    def feedback(self, screen, text):
        self.decks[screen].feedback = (time.monotonic(), text)
        self._changed()

    def play_json(self, text):
        try:
            from bromigos_tvplay import public_item, screen_name, youtube_url
            req = json.loads(text)
            screen = screen_name(req.get("screen", "big"))
            item = public_item(req["item"])
            if not self.enabled():
                raise ValueError("Den TV is off")
            if not item.get("id") or item.get("kind") in ("show", "season"):
                raise ValueError("Pick a playable episode or movie")
            if item.get("server") == "youtube" and not youtube_url(item.get("url", "")):
                raise ValueError("Use a YouTube video URL")
            if item.get("server") == "files":
                # Files are played only by the trusted channel-cache skip path below.
                raise ValueError("Use the downloaded YouTube library or a media source")
            self.override(screen, item, resume=bool(req.get("resume")))
            return json.dumps(dict(ok=True, screen=screen, item=item, message=f"Playing {TVL.label(item)} on {screen}"))
        except (ValueError, KeyError, TypeError) as e:
            return json.dumps(dict(ok=False, error=str(e)))

    def override(self, screen, item, resume=False, reason="ON DEMAND", channel=None):
        old = self.slot(self.channel(screen)[1])
        if old:
            self.history[screen].append(dict(old.item))
            self.history[screen] = self.history[screen][-12:]
        offset = max(0, float(item.get("position") or 0)) if resume else 0.0
        self.overrides[screen] = dict(item=dict(item), at=time.monotonic(), offset=offset, reason=reason,
                                      channel=channel or self.channel(screen)[1])
        self._unload(self.decks[screen])
        self.feedback(screen, reason)
        if self.full_session and self.full_session.screen == screen:
            self.full_session.retune()
        self.wake.set()

    def override_channel(self, screen, ch):
        o = self.overrides.get(screen)
        if not o:
            return ch
        item = o["item"]
        kind = {"youtube": "youtube", "files": "files"}.get(item.get("server"), "server")
        return dict(o["channel"], key=f"on-demand-{screen}-{o['at']}", kind=kind,
                    source=item.get("server") or o["channel"].get("source"), name=TVL.label(item),
                    override=screen, bumpers=False)

    def override_slot(self, ch):
        s = ch.get("override")
        o = self.overrides.get(s)
        if not o:
            return None
        d = self.decks[s]
        if self.full_session and self.full_session.screen == s and self.full_session.proc.poll() is None:
            offset = o.get("full_position", o["offset"])
        elif d.player and d.loaded and d.loaded[0] == ch["key"] and d.player.started:
            pos = d.player.position()
            offset = o["offset"] if pos is None else pos
            if (d.stream or {}).get("from_start"): offset += o["offset"]
        else:
            offset = o["offset"]
        duration = float(o["item"].get("duration") or 0)
        if duration and offset >= duration:
            self.overrides.pop(s, None)
            self._unload(self.decks[s])
            self.feedback(s, "BACK TO CHANNEL")
            return self.slot(self.channel(s)[1])
        start = time.time() - offset
        return TVL.Slot(item=o["item"], offset=offset, start=start,
                        end=start + duration if duration else None, index=0, next=None)

    def skip_item(self, screen, previous=False):
        ch = self.channel(screen)[1]
        if not ch.get("override"):
            moved = TVL.channel_step(ch, previous)
            if moved:
                self.last_slot.pop(ch["key"], None)
                self._unload(self.decks[screen])
                self.feedback(screen, "PREVIOUS" if previous else "NEXT ITEM")
                if self.full_session and self.full_session.screen == screen:
                    self.full_session.retune()
                self.wake.set()
                return f"{screen}: {TVL.label(moved.item)}"
        slot = self.slot(ch)
        if previous and self.history[screen]:
            item = self.history[screen].pop()
        elif slot and slot.next and not previous:
            item = slot.next
        else:
            base = self.overrides.get(screen, {}).get("channel", ch)
            seq = (TVL.cached_items(base) or {}).get("items", [])
            if not seq:
                self.feedback(screen, "NOTHING TO SKIP")
                return "Nothing to skip"
            current = (slot.item if slot else {}).get("id")
            idx = next((i for i, v in enumerate(seq) if v.get("id") == current), 0)
            item = seq[(idx + (-1 if previous else 1)) % len(seq)]
        self.override(screen, item, reason="PREVIOUS" if previous else "NEXT ITEM",
                      channel=self.overrides.get(screen, {}).get("channel", ch))
        return f"{screen}: {TVL.label(item)}"

    def _submap(self, name):
        # Only the session that owns this live layer. Never search for another desktop.
        if not __import__("os").environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return
        try:
            subprocess.run(["hyprctl", "dispatch", f'hl.dsp.submap("{name}")'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def select_screen(self, value):
        from bromigos_tvplay import screen_name
        if value == "none":
            old = self.selected
            self.selected, self.digits = None, None
            self._submap("reset")
            if old:
                self.feedback(old, "REMOTE OFF")
            return "TV remote off"
        if not self.enabled():
            self.select_screen("none")
            return "Den TV is off"
        self.selected = screen_name(value)
        self.remote_at = time.monotonic()
        self.digits = None
        self._submap("bromigos-tv-remote")
        self.feedback(self.selected, "REMOTE")
        return f"TV remote: {self.selected}"

    def remote(self, action, screen=None):
        s = screen or self.selected
        if action == "cancel":
            return self.select_screen("none")
        if action == "leave":
            if s and self.digits is not None:
                return self.remote("digit-0")
            return self.select_screen("none")
        if not s:
            return "Select a TV first: bromigos-live tv select big|scope|small"
        if not screen: self.remote_at = time.monotonic()
        digit = {"channel-up": "8", "channel-down": "2", "mute": "5", "skip": "6", "previous": "4"}.get(action)
        if digit and self.digits is not None and not screen:
            action = "digit-" + digit
        if action.startswith("digit-") and action[6:].isdigit() and len(action[6:]) == 1:
            self.digits = ((self.digits or "") + action[6:])[-3:]
            self.digits_at = time.monotonic()
            self.feedback(s, "CH " + self.digits + "_")
            return "Channel " + self.digits
        if action == "digits":
            self.digits, self.digits_at = "", time.monotonic()
            self.feedback(s, "CH ___")
            return "Type the channel number"
        if action == "open" and self.digits is not None and not screen:
            return self.commit_digits()
        if action in ("volume-up", "volume-down"):
            return self.set_sound(s, volume=self.screens[s]["volume"] + (5 if action.endswith("up") else -5))
        if action in ("channel-up", "channel-down"):
            return self.tune_to(s, step=1 if action.endswith("up") else -1)
        if action in ("skip", "previous"):
            return self.skip_item(s, action == "previous")
        if action in ("mute", "sound"):
            return self.set_sound(s, on=True if action == "sound" else not self.screens[s]["sound"])
        if action in ("open", "guide"):
            self.feedback(s, "FULL SCREEN" if action == "open" else "GUIDE")
            return self.open_full(s) if action == "open" else self.open_guide(s)
        return "Unknown TV remote action"

    def commit_digits(self):
        digits, self.digits = self.digits, None
        if digits and self.selected:
            n = int(digits)
            if 1 <= n <= len(self.lineup(self.selected)):
                return self.tune_to(self.selected, number=n)
            self.feedback(self.selected, "NO CHANNEL " + digits)
            return "No channel " + digits
        return "Channel entry cancelled"

    def controls_tick(self):
        now = time.monotonic()
        if self.selected and (not self.enabled() or now - self.remote_at >= 15):
            self.select_screen("none")
        elif self.digits is not None and now - self.digits_at >= 1:
            self.commit_digits()
