"""The den's physical controls and number-pad remote. All inputs call TV's same actions."""
import json
import math
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
        self.analog_hover = None
        self.analog_press = None
        self.control_tex = {}
        self.control_sig = {}
        self.control_rects = {}

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

    def analog_regions(self):
        out = []
        if not self.enabled():
            return out
        for s, (x, y, w, h) in self.rects.items():
            unit = max(12, min(23, w / 8))
            cy = y + h + unit * .9
            for i, act in enumerate(("volume", "channel", "mute", "skip")):
                cx = x + w * (.17 + i * .21)
                out.append((s, act, (cx - unit / 2, cy - unit / 2, unit, unit)))
        return out

    def analog_target(self, x, y):
        return next(((s, a) for s, a, r in self.analog_regions()
                     if r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]), None)

    def analog_action(self, screen, action, step=None):
        if action == "volume":
            return self.set_sound(screen, volume=self.screens[screen]["volume"] + 5 * step) if step else \
                self.set_sound(screen, on=not self.screens[screen]["sound"])
        if action == "channel":
            return self.tune_to(screen, step=step or 1)
        if action == "mute":
            return self.set_sound(screen, on=not self.screens[screen]["sound"])
        return self.skip_item(screen)

    def analog_textures(self, sf=1):
        """Physical knobs below each screen, plus its selected bezel. No TV: no pixels."""
        if not self.enabled():
            return []
        import cairo
        from OpenGL import GL
        from . import glkit
        out = []
        palette = glkit.T.version(0.0)
        for s, (x, y, w, h) in self.rects.items():
            unit = max(12, min(23, w / 8))
            rect = (x - 4, y - 4, w + 8, h + unit * 2.0 + 8)
            n, ch = self.channel(s)
            state = self.screens[s]
            pressed = self.analog_press if self.motion == "full" else None
            sig = (rect, state["volume"], state["sound"], n, self.selected == s, self.analog_hover, pressed, palette, sf)
            if self.control_sig.get(s) != sig:
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, math.ceil(rect[2] * sf)),
                                           max(1, math.ceil(rect[3] * sf)))
                cr = cairo.Context(surf); cr.scale(sf, sf)
                if self.selected == s:
                    cr.set_source_rgba(*glkit.col("phosphor", .9)); cr.set_line_width(1.5)
                    cr.rectangle(2, 2, w + 4, h + 4); cr.stroke()
                for _, act, r in (v for v in self.analog_regions() if v[0] == s):
                    cx, cy = r[0] + unit / 2 - rect[0], r[1] + unit / 2 - rect[1]
                    cr.set_source_rgba(*glkit.col("panel", .92)); cr.arc(cx, cy, unit * .5, 0, math.tau); cr.fill()
                    cr.set_source_rgba(*glkit.col("dim", .8)); cr.set_line_width(.8)
                    cr.arc(cx, cy, unit * .45, 0, math.tau); cr.stroke()
                    if act in ("volume", "channel"):
                        frac = state["volume"] / 100 if act == "volume" else (n - 1) / max(1, len(self.lineup(s)) - 1)
                        start, sweep = math.pi * .75, math.pi * 1.5
                        for i in range(11):
                            angle = start + sweep * i / 10
                            cr.move_to(cx + math.cos(angle) * unit * .39, cy + math.sin(angle) * unit * .39)
                            cr.line_to(cx + math.cos(angle) * unit * .47, cy + math.sin(angle) * unit * .47)
                        cr.stroke()
                        cr.set_source_rgba(*glkit.col("phosphor", .95)); cr.set_line_width(1.4)
                        cr.arc(cx, cy, unit * .33, start, start + max(.001, sweep * frac)); cr.stroke()
                        angle = start + sweep * frac
                        cr.move_to(cx, cy); cr.line_to(cx + math.cos(angle) * unit * .24, cy + math.sin(angle) * unit * .24)
                        cr.stroke()
                    else:
                        down = pressed == (s, act)
                        cr.set_source_rgba(*glkit.col("phosphor", .65 if down else .95))
                        cr.select_font_face("Geist Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                        cr.set_font_size(unit * .38)
                        text = "M" if act == "mute" else ">|"
                        e = cr.text_extents(text); cr.move_to(cx - e.x_advance / 2, cy + unit * .13 + (1 if down else 0))
                        cr.show_text(text)
                cr.set_source_rgba(*glkit.col("phosphor", .95 if self.showing(s) else .25))
                cr.arc(w + 1, h + unit, 1.5, 0, math.tau); cr.fill()
                if self.analog_hover and self.analog_hover[0] == s:
                    act = self.analog_hover[1]
                    label = f"VOL {state['volume']}%" if act == "volume" else \
                        (f"CH {n} {ch['name']}" if act == "channel" else ("MUTE / SOUND" if act == "mute" else "NEXT ITEM"))
                    cr.set_source_rgba(*glkit.col("panel", .94)); cr.rectangle(4, h + unit * 1.5 + 4, w, unit * .55); cr.fill()
                    cr.set_source_rgba(*glkit.col("phosphor")); cr.set_font_size(unit * .42)
                    cr.move_to(6, h + unit * 2 + 3); cr.show_text(label[:int(w / (unit * .26))])
                surf.flush()
                if self.control_tex.get(s): GL.glDeleteTextures([self.control_tex[s]])
                self.control_tex[s] = glkit.texture_from_cairo(surf)
                self.control_sig[s] = sig
            out.append((self.control_tex[s], rect))
        return out
