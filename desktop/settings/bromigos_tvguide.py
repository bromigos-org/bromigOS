"""Den TV: the channel guide. Every channel, once, as a TV guide: what's on now and next,
with its poster, its source, its order and how far through it is, and a tune button for
each of the den's three screens (the big monitor, the scope, the small monitor), lit where
it's on air. Add a channel (a library, collection or playlist from your Jellyfin or Plex,
shows or movies you pick, a YouTube playlist or channel, a folder, your downloaded YouTube
videos), remove one (with Undo), drag one to reorder it, rename it, keep it to some
screens, give it bumpers.

The channels are the [[tv.channel]] tables of ~/.config/bromigos-live/config.toml, changed
in place by lib/bromigos_tvconfig.py (comments and other tables kept, written atomically
through a symlink); the live layer reads them again by itself, without a restart. What's
on comes from the den TV's own cache (lib/bromigos_tv.py), so the page never waits on a
server; a new channel's list is read in the background. Tuning is `bromigos-live tv set N
--screen S`. Opened by `bromigos-live tv guide`, SUPER+ALT+G, the hover hint's GUIDE and
the MEDIA panel's settings (docs/settings.md, "Den TV")."""
import hashlib
import io
import os
import ssl
import sys
import threading
import time
import tomllib
import urllib.request

from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from bromigos_settings import Entry, Page

# a bromigOS checkout's own libs first (its tests run the page from there), else the installed ones
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if os.path.isfile(os.path.join(_REPO, "lib", "bromigos_tvconfig.py")):
    for _p in (os.path.join(_REPO, "homelab", "lib"), os.path.join(_REPO, "lib")):
        if _p in sys.path:
            sys.path.remove(_p)
        sys.path.insert(0, _p)
elif "/usr/lib/bromigos/lib" not in sys.path:
    sys.path.append("/usr/lib/bromigos/lib")

try:
    import bromigos_tv as TVL
    import bromigos_tvconfig as C
    import bromigos_tvchannels as CHANNELS
except ImportError:                        # an older bromigos-core: no guide
    TVL = C = None

SCREENS = [("big", "The big monitor"), ("wave", "The scope"), ("emblem", "The small monitor")]
SCREEN_NAME = dict(SCREENS)
SHORT = {"big": "big", "wave": "scope", "emblem": "small"}
LIVE = ["bromigos-live", "tv"]
CARD_W, POSTER_H = 216, 122
ORDERS = [("", "Its own (playlists in order, the rest shuffled)"), ("shuffle", "Shuffled, the same all day"),
          ("in order", "In order (picked shows take turns)"), ("alternate", "Alternate shows")]
POSTERS = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "bromigos", "tv",
                       "posters")


def _cards_css(c):
    def a(h, al):
        h = h.lstrip("#")
        return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{al})"
    return f"""
flowboxchild.tv-card {{ padding: 0; border: 1px solid {a(c['dim'], .5)}; background-color: {a(c['panel'], .7)}; }}
flowboxchild.tv-card:focus-visible {{ outline: 2px solid {c['primary']}; outline-offset: -2px; }}
flowboxchild.tv-card:hover {{ background-color: {a(c['primary'], .07)}; }}
flowboxchild.tv-card.on-air {{ border-color: {c['primary']}; box-shadow: inset 0 0 0 1px {c['primary']},
  0 0 10px {a(c['primary'], .25)}; }}
flowboxchild.tv-card.drop {{ box-shadow: inset 4px 0 {c['warn']}; }}
.tv-poster {{ background-color: {c['void']}; }}
.tv-chnum {{ color: {c['primary']}; font-weight: 700; letter-spacing: 0.08em; }}
.tv-name {{ color: {c['soft']}; font-weight: 700; }}
.tv-onair {{ color: {c['void']}; background-color: {c['primary']}; font-size: 0.75em; font-weight: 700;
  letter-spacing: 0.12em; padding: 0 5px; }}
.tv-sound {{ color: {c['warn']}; font-size: 0.75em; font-weight: 700; letter-spacing: 0.1em; }}
.tv-now {{ color: {c['text']}; }}
.tv-next, .tv-meta {{ color: {c['muted']}; font-size: 0.85em; }}
.tv-error {{ color: {c['warn']}; font-size: 0.85em; }}
progressbar.tv-progress > trough {{ min-height: 3px; background-color: {a(c['dim'], .35)}; }}
progressbar.tv-progress > trough > progress {{ min-height: 3px; background-color: {c['primary']}; }}
.tv-screen-drop {{ box-shadow: inset 0 0 0 1px {c['warn']}; }}
.tv-pick {{ border: 1px solid {a(c['dim'], .45)}; padding: 4px; }}
.tv-pick.picked {{ border-color: {c['primary']}; background-color: {a(c['primary'], .12)}; }}
.tv-pick-title {{ font-size: 0.85em; color: {c['soft']}; }}
"""


def _channel_text(ch):
    """Where a channel's videos come from, in a few words."""
    if ch is None:
        return ""
    if ch.get("picks"):
        parts = []
        for key, what in (("shows", "show"), ("items", "movie"), ("collections", "collection")):
            v = ch.get(key)
            n = len(v) if isinstance(v, list) else (1 if v else 0)
            if n:
                parts.append(f"{n} {what}{'s' if n != 1 else ''}")
        return "Picked: " + ", ".join(parts) + (f" on {ch['source']}" if ch.get("source") else "")
    if ch["kind"] == "server":
        for k in ("library", "collection", "playlist"):
            if ch.get(k):
                return f"{(ch.get('source') or 'media server').capitalize()} {k}: {ch[k]}"
    if ch["kind"] == "youtube":
        return "YouTube " + ("playlist" if "list=" in str(ch.get("youtube")) else "channel")
    if ch["kind"] == "files":
        f = ch.get("files")
        return "Folder: " + (f if isinstance(f, str) else f"{len(f)} files")
    return ch.get("what") or ""


def _order_text(ch):
    if ch.get("kind") == "own":
        return ""
    if ch.get("order") == "in order":
        return "takes turns, in order" if ch.get("picks") else "in order"
    return "shuffled"


class Guide:
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = ctx.page()
        self.page.set_reset(None, hint="The channels are yours: nothing here has a default. Remove one with its menu "
                                       "(Undo puts it back)")
        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        self.css.load_from_string(_cards_css(ctx.colors))
        ctx.on_restyle(lambda c: self.css.load_from_string(_cards_css(c)))
        self.live = None                          # bromigos-live tv state --json, or None (not running)
        self.posters = {}                         # item id -> poster file, or None
        self.fetching = set()
        self.cards = {}
        self.entries = []                         # [(index in the file, channel dict or None, table)]
        self.panel = None
        if TVL is None:
            ctx.placeholder(self.page, "The den TV", "This needs bromigOS's den TV library (bromigos-core 0.1.2 or "
                                                     "newer).")
            return
        playback = ctx.group(self.page, "The screens", "Play something now, or return to a channel. Only one screen has sound.", key="playback")
        self.screen_rows = {}
        for screen, title in SCREEN_NAME.items():
            self.screen_rows[screen] = ctx.row(playback, title, "", key="screen-" + screen,
                hint="Choose an item to play now, from the start or where you left off",
                buttons=[("Play…", lambda s=screen: self.play_dialog(s), "Shows, seasons, episodes, movies and YouTube"),
                         ("Full screen", lambda s=screen: ctx.run(LIVE + ["open", "--screen", s]), "Open this TV in its own full-screen player"),
                         ("Sound", lambda s=screen: ctx.run(LIVE + ["sound", "toggle", "--screen", s]), "Move sound here or mute it")])
        ctx.json(["bromigos", "scene", "get", "tv.hover_hint", "--json"],
                 lambda doc, err: ctx.switch_row(playback, "Floating controls on hover", key="hover-hint",
                     active=((doc or {}).get("values") or {}).get("tv.hover_hint", True),
                     hint="Off leaves the MEDIA widget and number-pad remote",
                     on_toggle=lambda v: ctx.change(["bromigos", "scene", "set", "tv.hover_hint", str(v).lower()], "TV hover hint updated")))
        top = ctx.group(self.page, "Channels", None, key="channels")
        self.top = top
        self.status = ctx.row(top, "The den's three screens", "", key="status",
                              hint="Each screen plays its own channel at once, and every channel can play on any "
                                   "screen; channel 1 is each screen's own picture",
                              buttons=[("Add channel…", self.add_dialog,
                                        "Makes a new channel: a library, shows you pick, YouTube or a folder"),
                                       ("Refresh", self.refresh, "Reads the channels and what's on again")],
                              advanced={"file": C.path() if C else "", "runs": "bromigos-live tv set N --screen S"})
        g = ctx.group(self.page, "The guide", "Every channel, once. Each card has a button for each screen: "
                                              "the lit one is on air there.", key="grid",
                      hint="Drag a card onto another to put it before that one; its menu chooses its screens")
        flow = Gtk.FlowBox(homogeneous=True, column_spacing=10, row_spacing=10,
                           selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=False)
        flow.set_min_children_per_line(1)
        flow.set_max_children_per_line(5)
        flow.set_valign(Gtk.Align.START)
        flow.set_margin_top(6)
        ctx.hint(flow, "Every channel: on a card, 1, 2 and 3 tune the big monitor, the scope and the small monitor; "
                       "Delete removes, F2 renames, Alt and an arrow move it")
        g.add(flow)
        self.flow = flow
        self.grid = g
        self.refresh()
        GLib.timeout_add_seconds(20, self._tick)
        want = os.environ.get("BROMIGOS_DEN_TV_OPEN")         # the tests' renders: a dialog open
        if want == "add":
            GLib.idle_add(lambda: (self.add_dialog(), False)[1])
        elif want == "play":
            GLib.idle_add(lambda: (self.play_dialog("big"), False)[1])
        elif want == "picker":
            GLib.idle_add(lambda: (self.picker(None, lambda *_: None, {"shows": ["Test Card"], "items": [], "collections": []}, "in order"), False)[1])

    # ------------------------------------------------------------------ reading
    def _cfg(self):
        try:
            with open(C.path(), "rb") as f:
                return tomllib.load(f)
        except (OSError, ValueError):
            return {}

    def refresh(self):
        """The channels from the file, what's on from the cache, what's tuned from the live layer."""
        if TVL is None:
            return
        try:
            doc = C.load()
            tables = doc.channels()
        except Exception as e:                                # noqa: BLE001  (a file that doesn't parse)
            self.status.set_subtitle(GLib.markup_escape_text(f"{C.path()}: {e}"[:300]))
            tables = []
        tv = self._cfg().get("tv") or {}
        default = TVL.screens_of(tv.get("screens"), TVL.DEFAULT_SCREENS) if tv.get("screens") else TVL.DEFAULT_SCREENS
        seen = set()
        self.entries = [(i, TVL._entry(t, seen, default), t) for i, t in enumerate(tables)]
        pc = TVL.panel_channel()
        self.panel = TVL._entry(pc, seen, default) if pc else None
        self.ctx.pending += 1
        self.ctx.json(LIVE + ["state", "--json"], self._got_live)

    def _got_live(self, doc, _err):
        self.ctx.pending -= 1
        self.live = doc if isinstance(doc, dict) and doc.get("screens") else None
        for s, row in self.screen_rows.items():
            state = ((self.live or {}).get("screens") or {}).get(s) or {}
            row.set_subtitle(("ON DEMAND · " if state.get("on_demand") else "") +
                             str(state.get("now") or state.get("name") or "Its own picture"))
        self._draw()
        self._fetch_missing()

    def _tuned(self, s):
        """The key of the channel a screen is on (the live layer's, else its remembered state)."""
        if self.live:
            return ((self.live.get("screens") or {}).get(s) or {}).get("key") or "own"
        return TVL.screen_state(TVL.state(), s)["channel"]

    def lineup(self, s):
        """[(number, channel, file index or None)] for a screen, as the live layer numbers them."""
        out = [(1, TVL.own_channel(s), None)]
        for i, ch, _t in self.entries:
            if ch and s in ch["screens"]:
                out.append((len(out) + 1, ch, i))
        if self.panel and s in self.panel["screens"]:
            out.append((len(out) + 1, self.panel, "panel"))
        return out

    def _number(self, s, key):
        """A channel's number on a screen (None when it isn't on that screen)."""
        return next((num for num, ch, _i in self.lineup(s) if ch["key"] == key), None)

    def _draw(self):
        running = self.live is not None
        n = sum(1 for _i, ch, _t in self.entries if ch)
        bad = sum(1 for _i, ch, _t in self.entries if ch is None)
        snd = (self.live or {}).get("sound_from")
        tuned = {s: self._tuned(s) for s, _t in SCREENS}
        on = []
        for s, title in SCREENS:
            ch = next((c for _num, c, _i in self.lineup(s) if c["key"] == tuned[s]), None) or TVL.own_channel(s)
            on.append(f"{SHORT[s]}: {ch['name']}" + (" (sound)" if snd == s else ""))
        self.status.set_subtitle(GLib.markup_escape_text(
            f"{n} channel{'s' if n != 1 else ''}" + (f" (and {bad} that can't play: no name or nothing to play)"
                                                     if bad else "") + " · " + " · ".join(on)
            + (" · the live layer isn't running: tuning waits for it" if not running else "")))
        while (c := self.flow.get_first_child()) is not None:
            self.flow.remove(c)
        self.flow.append(self._card(None, None, tuned, snd))                  # channel 1: each screen's own
        for idx, ch, _t in self.entries:
            if ch:
                self.flow.append(self._card(ch, idx, tuned, snd))
        if self.panel:
            self.flow.append(self._card(self.panel, "panel", tuned, snd))

    # ------------------------------------------------------------------ a card
    def _card(self, ch, idx, tuned, snd):
        """A channel's card: its poster, what's on now and next, how far in, its source and
        order, and a tune button for each screen (lit where it's on air). ch None: channel 1."""
        ctx = self.ctx
        own = ch is None
        child = Gtk.FlowBoxChild()
        child.add_css_class("tv-card")
        child.set_focusable(True)
        child._index, child._ch = idx, ch
        key = "own" if own else ch["key"]
        airing = [s for s, _t in SCREENS if tuned.get(s) == key]
        if airing:
            child.add_css_class("on-air")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_size_request(CARD_W, -1)
        slot = None if own else TVL.now_next(ch)
        item = slot.item if slot else None
        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        pic.set_size_request(CARD_W, POSTER_H)
        pic.add_css_class("tv-poster")
        if not own:
            self._set_poster(pic, ch, item)
        frame = Gtk.Overlay()
        frame.set_child(pic)
        if own:
            lab = Gtk.Label(label="RELAY MAP · SCOPE · BURN-IN", wrap=True, justify=Gtk.Justification.CENTER)
            lab.add_css_class("tv-chnum")
            frame.add_overlay(lab)
        box.append(frame)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        for side in ("start", "end"):
            getattr(inner, f"set_margin_{side}")(8)
        inner.set_margin_bottom(8)
        head = Gtk.Box(spacing=6)
        nums = {s: (1 if own else self._number(s, key)) for s, _t in SCREENS}
        shown = sorted({v for v in nums.values() if v})
        lab = Gtk.Label(label="CH " + "/".join(map(str, shown)) if shown else "CH –", xalign=0)
        lab.add_css_class("tv-chnum")
        ctx.hint(lab, "Its number: " + ", ".join(f"{SCREEN_NAME[s].lower()} {v}" if v else
                                                 f"not on {SCREEN_NAME[s].lower()}" for s, v in nums.items()))
        head.append(lab)
        name = Gtk.Label(label="Own picture" if own else ch["name"], xalign=0, hexpand=True,
                         ellipsize=Pango.EllipsizeMode.END, max_width_chars=14)
        name.add_css_class("tv-name")
        head.append(name)
        if airing:
            badge = Gtk.Label(label="ON AIR")
            badge.add_css_class("tv-onair")
            ctx.hint(badge, "On now on " + ", ".join(SCREEN_NAME[s].lower() for s in airing))
            head.append(badge)
        inner.append(head)
        if own:
            for line in ("Each screen's own picture: the relay map, the scope's traffic, the burn-in",
                         "As bromigOS draws them, before any channel"):
                lb = Gtk.Label(label=line, xalign=0, wrap=True, max_width_chars=24)
                lb.add_css_class("tv-meta" if "As" in line else "tv-now")
                inner.append(lb)
        else:
            nowt = TVL.label(item) if item else "Nothing yet: reading its list…"
            cached = TVL.cached_items(ch) or {}
            if not item and cached.get("error"):
                nowt = "Can't play: " + cached["error"]
            now = Gtk.Label(label=nowt, xalign=0, ellipsize=Pango.EllipsizeMode.END, lines=2, wrap=True,
                            max_width_chars=24)
            now.add_css_class("tv-now" if item else "tv-error")
            ctx.hint(now, f"On now: {nowt}" + (f" ({TVL.fmt_time(slot.offset)} of "
                                               f"{TVL.fmt_time(item.get('duration'))})"
                                               if slot and slot.offset is not None and item.get("duration") else ""))
            inner.append(now)
            bar = Gtk.ProgressBar()
            bar.add_css_class("tv-progress")
            if slot and slot.offset is not None and item.get("duration"):
                bar.set_fraction(max(0.0, min(1.0, slot.offset / float(item["duration"]))))
            ctx.hint(bar, "How far through what's on it is: a channel plays as if it had been on all along")
            inner.append(bar)
            nxt = Gtk.Label(label="Next: " + (TVL.label(slot.next) if slot and slot.next else "—"), xalign=0,
                            ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
            nxt.add_css_class("tv-next")
            ctx.hint(nxt, "What comes on after it" + (f", at {time.strftime('%H:%M', time.localtime(slot.end))}"
                                                      if slot and slot.end else ""))
            inner.append(nxt)
            only = [x for x, _t in SCREENS if x in ch["screens"]]
            meta = Gtk.Label(label=f"{_channel_text(ch)} · {_order_text(ch)}"
                             + ("" if len(only) == len(SCREENS) else " · only " + ", ".join(SHORT[x] for x in only))
                             + (" · bumpers" if ch.get("bumpers") else ""),
                             xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
            meta.add_css_class("tv-meta")
            ctx.hint(meta, _channel_text(ch) + f"; {_order_text(ch)}"
                     + ("; on every screen" if len(only) == len(SCREENS) else
                        "; only on " + ", ".join(SCREEN_NAME[x].lower() for x in only))
                     + ("; a bumper card opens each item" if ch.get("bumpers") else "")
                     + ("; from the MEDIA panel's settings" if idx == "panel" else ""))
            inner.append(meta)
        acts = Gtk.Box(spacing=4)
        acts.set_margin_top(4)
        for s, title in SCREENS:
            num = nums[s]
            b = Gtk.Button(label=SHORT[s].upper())
            b.set_hexpand(True)
            if s in airing:
                b.add_css_class("suggested-action")
                ctx.hint(b, f"{title} is on this channel now" + (" (its sound is on)" if snd == s else ""))
            elif num is None:
                b.set_sensitive(False)
                ctx.hint(b, f"Not on {title.lower()}: its menu's screens leave it out")
            else:
                ctx.hint(b, f"Tunes {title.lower()} to channel {num} (bromigos-live tv set {num} --screen {s})")
                b.connect("clicked", lambda *_a, s=s, num=num: self.tune(s, num))
            acts.append(b)
        if not own:
            acts.append(self._menu(child, ch, idx))
        child._nums = nums
        inner.append(acts)
        box.append(inner)
        child.set_child(box)
        ctx.hint(child, ("Channel 1, each screen's own picture" if own else ch["name"])
                 + (f": on air on {', '.join(SHORT[s] for s in airing)}" if airing else "")
                 + ". 1, 2, 3: tune the big monitor, the scope, the small monitor"
                 + ("" if own else " · Delete: remove · F2: rename · Alt+←/→: move"))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, _code, st, c=child: self._key(c, kv, st))
        child.add_controller(keys)
        if isinstance(idx, int):
            src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
            src.connect("prepare", lambda *_a, i=idx: Gdk.ContentProvider.new_for_value(str(i)))
            child.add_controller(src)
            drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
            drop.connect("drop", lambda _t, v, _x, _y, i=idx: self._dropped(v, i))
            drop.connect("enter", lambda t, *_: (t.get_widget().add_css_class("drop"), Gdk.DragAction.MOVE)[1])
            drop.connect("leave", lambda t: t.get_widget().remove_css_class("drop"))
            child.add_controller(drop)
        self.cards[key] = child
        return child

    def _menu(self, child, ch, idx):
        """The card's menu: a popover of plain buttons (Settings exports no actions)."""
        ctx = self.ctx
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(6)

        def item(label, cb, hint, destructive=False):
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            if destructive:
                b.add_css_class("destructive-action")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda *_: (pop.popdown(), cb()))
            ctx.hint(b, hint)
            box.append(b)
        if idx == "panel":
            item("Edit in the MEDIA panel's settings…", lambda: ctx.open_page("widgets"),
                 "This channel is the MEDIA panel's own: its settings are in Settings › Widgets")
        else:
            item("Contents…", lambda: self.contents_dialog(idx, ch), "See titles, reorder picks, add or remove items")
            item("Rename…", lambda: self.rename_dialog(idx, ch), f"A new name for {ch['name']} (F2)")
            if ch.get("picks"):
                item("Pick shows…", lambda: self.edit_picks(idx, ch), "Add or leave out shows, movies and collections")
            item("Move earlier", lambda: self.move(idx, -1), "One place earlier in every screen's numbers (Alt+←)")
            item("Move later", lambda: self.move(idx, +1), "One place later in every screen's numbers (Alt+→)")
            for order, label in (("shuffle", "Shuffle"), ("in-order", "In order"), ("alternate", "Alternate")):
                item(label, lambda order=order: self._write(lambda d: d.set(idx, "order", order),
                     f"{ch['name']}: {order}"), "How this channel plays its items")
            bump = Gtk.CheckButton(label="Bumpers between items", active=bool(ch.get("bumpers")))
            bump.connect("toggled", lambda w: (pop.popdown(), self.set_key(idx, ch, "bumpers", True if w.get_active()
                                                                           else None)))
            ctx.hint(bump, "A few seconds' card, like a TV network's block, opens each item: the channel's name, "
                           "what's on and the time")
            box.append(bump)
            head = Gtk.Label(label="ON THESE SCREENS", xalign=0)
            head.add_css_class("tv-meta")
            head.set_margin_top(6)
            box.append(head)
            for x, title in SCREENS:
                cb = Gtk.CheckButton(label=title, active=x in ch["screens"])
                cb.connect("toggled", lambda w, x=x: (pop.popdown(), self.set_screen(idx, ch, x, w.get_active())))
                ctx.hint(cb, f"Whether {title.lower()} carries {ch['name']} (every screen does unless you say)")
                box.append(cb)
            sep = Gtk.Separator()
            sep.set_margin_top(4)
            box.append(sep)
            item("Remove", lambda: self.remove(idx, ch), f"Takes {ch['name']} off every screen (Undo puts it back)",
                 destructive=True)
        pop.set_child(box)
        b = Gtk.MenuButton(icon_name="view-more-symbolic", popover=pop)
        ctx.hint(b, f"{ch['name']}: rename, pick its shows, bumpers, move it, choose its screens, or remove it")
        return b

    def _key(self, child, kv, state):
        idx, ch = child._index, child._ch
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        for k, (s, _t) in zip((Gdk.KEY_1, Gdk.KEY_2, Gdk.KEY_3), SCREENS):
            if kv == k and child._nums.get(s):
                self.tune(s, child._nums[s])
                return True
        if not isinstance(idx, int):
            return False
        if kv in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.remove(idx, ch)
            return True
        if kv == Gdk.KEY_F2:
            self.rename_dialog(idx, ch)
            return True
        if alt and kv in (Gdk.KEY_Left, Gdk.KEY_Up):
            self.move(idx, -1)
            return True
        if alt and kv in (Gdk.KEY_Right, Gdk.KEY_Down):
            self.move(idx, +1)
            return True
        return False

    # ------------------------------------------------------------------ posters (a thread; a cache on disk)
    def _poster_file(self, iid):
        return os.path.join(POSTERS, hashlib.sha1(str(iid).encode()).hexdigest()[:20] + ".img")

    def _set_poster(self, pic, ch, item):
        if not item:
            return
        f = self._poster_file(item.get("id"))
        if os.path.isfile(f):
            try:
                pic.set_paintable(Gdk.Texture.new_from_filename(f))
            except GLib.Error:
                pass
            return
        key = str(item.get("id"))
        if key in self.fetching:
            return
        self.fetching.add(key)
        self.ctx.pending += 1
        threading.Thread(target=self._fetch_poster, args=(pic, ch, item, f), daemon=True).start()

    def _fetch_poster(self, pic, ch, item, f):
        ok = False
        try:
            url, headers = None, {}
            if ch["kind"] in ("youtube", "live") or item.get("server") == "youtube":
                url = item.get("thumbnail") or item.get("poster")
            elif ch["kind"] == "server":
                a = TVL.server_of(ch)
                if a is not None:
                    url, headers = a.video_poster(item)
            if url:
                body = _get(url, headers)
                os.makedirs(POSTERS, exist_ok=True)
                with open(f + ".tmp", "wb") as out:
                    out.write(body)
                os.replace(f + ".tmp", f)
                ok = True
        except Exception:                                     # noqa: BLE001  no poster: the card says what's on anyway
            pass

        def done():
            self.ctx.pending -= 1
            if ok:
                try:
                    pic.set_paintable(Gdk.Texture.new_from_filename(f))
                except GLib.Error:
                    pass
            return False
        GLib.idle_add(done)

    def _fetch_missing(self):
        """A channel with no list cached yet (just added): read it in the background, then redraw."""
        want = [ch for _i, ch, _t in self.entries if ch and TVL.cached_items(ch) is None]
        if not want:
            return
        self.ctx.pending += 1

        def run():
            for ch in want:
                try:
                    TVL.fetch_items(ch, max_age=0)
                except Exception:                             # noqa: BLE001
                    pass

            def done():
                self.ctx.pending -= 1
                self._draw()
                return False
            GLib.idle_add(done)
        threading.Thread(target=run, daemon=True).start()

    def _tick(self):
        if self.page.get_mapped():
            self.refresh()
        return True

    # ------------------------------------------------------------------ changes
    def _write(self, change, said, undo=None, after=None):
        """change(doc) on the file as it is now, checked and saved; a toast (with Undo)."""
        try:
            back = CHANNELS.Store().edit(change)
        except Exception as e:                                # noqa: BLE001  (ConfigError, OSError)
            self.ctx.toast(f"Not changed: {e}"[:200], timeout=8)
            return None
        if after:
            after()
        u = (lambda: undo(back)) if undo else None
        self.ctx.toast(said, undo=u)
        self.refresh()
        return back

    def tune(self, s, num):
        self.ctx.pending += 1

        def done(ok, out, err):
            self.ctx.pending -= 1
            self.ctx.toast(out.strip() if ok and out.strip() else f"Not tuned: {(err or out).strip() or 'no answer'}"
                           [:200])
            self.refresh()
        self.ctx.run(LIVE + ["set", str(num), "--screen", s], done)

    def remove(self, idx, ch):
        store = CHANNELS.Store()
        def restore():
            try:
                result = store.undo(); self.ctx.toast(result['message']); self.refresh()
            except (ValueError,OSError) as e: self.ctx.toast(str(e),timeout=8)
        def confirmed():
            try:
                result = store.remove(ch['name'])
                self.ctx.toast(result['message'],undo=restore); self.refresh()
            except (ValueError,OSError) as e: self.ctx.toast(str(e),timeout=8)
        return self.ctx.confirm(f"Remove channel {ch['name']}?", "Its media files stay. Undo puts the channel back.",
                                "Remove", confirmed, destructive=True)

    def move(self, idx, step):
        n = len(self.entries)
        j = max(0, min(n - 1, idx + step))
        if j == idx:
            return
        self._write(lambda d: d.move(idx, j), f"Moved {self.entries[idx][2].get('name') or 'the channel'}",
                    undo=lambda _b: self._write(lambda d: d.move(j, idx), "Moved back"))

    def set_screen(self, idx, ch, screen, on):
        now = list(ch["screens"])
        new = [x for x, _t in SCREENS if (x in now and x != screen) or (on and x == screen)]
        self.set_screens(idx, new, ch["name"])

    def set_screens(self, idx, screens, name=None):
        """Which screens carry channel idx: every screen writes no `screens` key at all."""
        name = name or self.entries[idx][2].get("name") or "the channel"
        if not screens:
            self.ctx.toast("A channel needs at least one screen: remove it instead")
            self.refresh()
            return
        old = (self.entries[idx][2] or {}).get("screens")
        val = None if len(screens) == len(SCREENS) else list(screens)
        self._write(lambda d: d.set(idx, "screens", val),
                    f"{name}: " + ("on every screen" if val is None else
                                   "only on " + ", ".join(SCREEN_NAME[x].lower() for x in screens)),
                    undo=lambda _b: self._write(lambda d: d.set(idx, "screens", old), "Screens put back"))

    def set_key(self, idx, ch, key, value):
        old = (self.entries[idx][2] or {}).get(key)
        self._write(lambda d: d.set(idx, key, value), f"{ch['name']}: {key} {'on' if value else 'off'}",
                    undo=lambda _b: self._write(lambda d: d.set(idx, key, old), "Put back"))

    @staticmethod
    def _screens_value(screens):
        return None if len(screens) == len(SCREENS) else list(screens)

    def _dropped(self, value, target):
        """A card dropped on another: it goes before that one, in every screen's numbers."""
        try:
            i = int(str(value).split(":", 1)[0])
        except ValueError:
            return False
        if not (0 <= i < len(self.entries)) or target == i or not isinstance(target, int):
            return False
        j = target if target < i else target - 1
        what = self.entries[i][2].get("name") or "the channel"
        self._write(lambda d: d.move(i, j), f"Moved {what}",
                    undo=lambda _b: self._write(lambda d: d.move(j, i), "Put back"))
        return True

    # ------------------------------------------------------------------ dialogs
    def _dialog(self, title, content, ok_label, on_ok, width=560, height=640):
        d = Adw.Dialog(title=title, content_width=width, content_height=height)
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: d.close())
        self.ctx.hint(cancel, "Closes this without changing anything")
        hb.pack_start(cancel)
        ok = Gtk.Button(label=ok_label)
        ok.add_css_class("suggested-action")
        ok.connect("clicked", lambda *_: on_ok(d))
        self.ctx.hint(ok, f"{ok_label}: writes it to config.toml; the den follows at once")
        hb.pack_end(ok)
        tv.add_top_bar(hb)
        tv.set_content(content)
        d.set_child(tv)
        d.set_default_widget(ok)
        d.present(self.ctx.window)
        return d, ok

    def play_dialog(self, screen):
        import bromigos_tvplay as TVP
        ctx = self.ctx
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"): getattr(content, "set_margin_" + side)(12)
        toolbar = Gtk.Box(spacing=8)
        back = Gtk.Button(label="Back")
        search = Gtk.SearchEntry(placeholder_text="Title or YouTube video URL", hexpand=True)
        ctx.hint(search, "Search Jellyfin/Plex, or downloaded YouTube; a show opens seasons then episodes")
        types = Gtk.DropDown.new_from_strings(["All", "Shows", "Movies", "Downloaded YouTube"])
        ctx.hint(types, "Which library to search")
        toolbar.append(back); toolbar.append(search); toolbar.append(types); content.append(toolbar)
        note = Gtk.Label(label="Reading your library…", xalign=0)
        content.append(note)
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        listing.add_css_class("boxed-list")
        ctx.hint(listing, "Double-click or Enter: choose a show, season or episode; Play starts a selected item")
        scroller = Gtk.ScrolledWindow(vexpand=True, min_content_height=260); scroller.set_child(listing)
        content.append(scroller)
        resume = Gtk.CheckButton(label="Resume where you left off")
        ctx.hint(resume, "Off plays from the start; on uses the media server's saved position")
        content.append(resume)
        state = dict(scope={"kind": "all"}, parents=[], rows=[], serial=0)
        def chosen():
            row = listing.get_selected_row()
            return state["rows"][row.get_index()] if row and row.get_index() < len(state["rows"]) else None
        def populate(rows, error=None):
            while listing.get_first_child(): listing.remove(listing.get_first_child())
            state["rows"] = rows
            for item in rows:
                row = Gtk.ListBoxRow()
                label = Gtk.Label(label=TVL.label(item) + " · " + str(item.get("server") or "YouTube"),
                                  xalign=0, ellipsize=Pango.EllipsizeMode.END)
                for side in ("top", "bottom", "start", "end"): getattr(label, "set_margin_" + side)(9)
                row.set_child(label); ctx.hint(row, TVL.label(item)); listing.append(row)
            note.set_text(error or (str(len(rows)) + " found" if rows else "Nothing found. Try another title or check that it is downloaded."))
        def fetch(query=""):
            state["serial"] += 1; serial = state["serial"]; scope = dict(state["scope"])
            note.set_text("Reading your library…")
            def run():
                try: rows, err = TVP.search(query, **scope), None
                except Exception as e: rows, err = [], str(e)
                def done():
                    if serial == state["serial"] and dialog.get_visible(): populate(rows, err)
                    return False
                GLib.idle_add(done)
            threading.Thread(target=run, daemon=True).start()
        def drill(item):
            state["parents"].append((dict(state["scope"]), state["rows"]))
            state["scope"] = dict(kind="seasons" if item["kind"] == "show" else "episodes",
                                  id_=item["id"], source=item.get("server"))
            if item["kind"] == "season": state["scope"]["season"] = item["season"]
            fetch()
        def play(_dialog):
            item = chosen()
            if not item: ctx.toast("Choose a title first"); return
            if item.get("kind") in ("show", "season"): drill(item); return
            ok.set_sensitive(False)
            use_resume = resume.get_active()
            def run():
                try: result = TVP.play(screen=screen, item=item, resume=use_resume); err = None
                except Exception as e: result, err = {}, str(e)
                def done():
                    ok.set_sensitive(True)
                    if err: ctx.toast(err)
                    else: ctx.toast(result.get("message", "Playing")); dialog.close(); self.refresh()
                    return False
                GLib.idle_add(done)
            threading.Thread(target=run, daemon=True).start()
        dialog, ok = self._dialog("Play on " + SCREEN_NAME.get(screen, screen), content, "Play", play, width=720, height=620)
        ctx.hint(ok, "Play the selected episode, movie or YouTube video now")
        def activate(_list, row):
            item = chosen()
            if item and item.get("kind") in ("show", "season"): drill(item)
            else: play(dialog)
        listing.connect("row-activated", activate)
        def go_back(*_):
            if state["parents"]:
                state["serial"] += 1; state["scope"], rows = state["parents"].pop(); populate(rows)
        back.connect("clicked", go_back); ctx.hint(back, "Back to the previous list")
        def find(*_):
            state["parents"] = []; state["scope"] = dict(kind=("all", "shows", "movies", "youtube")[types.get_selected()])
            fetch(search.get_text())
        search.connect("activate", find); types.connect("notify::selected", find)
        dialog.connect("closed", lambda *_: state.update(serial=state["serial"] + 1))
        fetch()
        return dialog

    def rename_dialog(self, idx, ch):
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup()
        e = Adw.EntryRow(title="Name", text=ch["name"])
        self.ctx.hint(e, "What the TV and the guide call it (its number stays)")
        g.add(e)
        page.add(g)

        def ok(d):
            new = e.get_text().strip()
            if not new or new == ch["name"]:
                d.close()
                return
            old_key, new_key = ch["key"], TVL._slug(new)
            d.close()
            self._write(lambda doc: doc.set(idx, "name", new), f"Renamed {ch['name']} to {new}",
                        undo=lambda _b: self._write(lambda doc: doc.set(idx, "name", ch["name"]), "Name put back",
                                                    after=lambda: self.ctx.run(LIVE + ["rename", new_key, old_key])),
                        after=lambda: self.ctx.run(LIVE + ["rename", old_key, new_key]))
        self._dialog(f"Rename {ch['name']}", page, "Rename", ok, height=220)
        e.grab_focus()

    def add_dialog(self, preset=None):
        """A new channel: its source, a name, an order and its screens."""
        ctx = self.ctx
        cat = TVL.catalog(refresh=False)
        boxes = cat.get("boxes") or []
        servers = cat.get("servers") or []
        keep = self._keep_folder()
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title="WHAT IT PLAYS")
        page.add(g)
        kinds = [("box", "A library, collection or playlist"), ("picks", "Shows or movies you pick"),
                 ("youtube", "A YouTube playlist or channel"), ("folder", "A folder of videos")]
        if keep:
            kinds.append(("kept", "Your downloaded YouTube videos"))
        kind = Adw.ComboRow(title="Source")
        kind.set_model(Gtk.StringList.new([t for _k, t in kinds]))
        ctx.hint(kind, "Where the channel's videos come from")
        g.add(kind)
        box = Adw.ComboRow(title="Library, collection or playlist", enable_search=True)
        box_vals = [(b, f"{b['title']} ({b['kind']}, {b.get('server') or ''})") for b in boxes]
        box.set_model(Gtk.StringList.new([t for _b, t in box_vals] or ["Nothing listed yet: is a media server set up?"]))
        ctx.hint(box, "What your Jellyfin or Plex offers (as the den TV last read it)")
        g.add(box)
        server = Adw.ComboRow(title="Server")
        server.set_model(Gtk.StringList.new(servers or ["The first media server"]))
        ctx.hint(server, "The Jellyfin or Plex source in homelab.toml to pick from")
        g.add(server)
        picks = {"shows": [], "items": [], "collections": []}
        pick_row = Adw.ActionRow(title="Pick shows…", subtitle="None picked yet")
        pick_row.set_activatable(True)
        pick_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        ctx.hint(pick_row, "A searchable list of the server's shows, movies and collections, with their posters")
        g.add(pick_row)
        yt = Adw.EntryRow(title="YouTube playlist or channel address")
        ctx.hint(yt, "https://www.youtube.com/playlist?list=… or https://www.youtube.com/@name")
        g.add(yt)
        folder = Adw.ActionRow(title="Folder", subtitle="~/Videos")
        folder._path = os.path.expanduser("~/Videos")
        fb = ctx.button("Choose…", lambda: ctx.choose_file("A folder of videos", lambda p: (
            setattr(folder, "_path", os.path.dirname(p) if os.path.isfile(p) else p),
            folder.set_subtitle(GLib.markup_escape_text(folder._path)))), "Picks the folder (choose any video in it)")
        folder.add_suffix(fb)
        ctx.hint(folder, "Every video in this folder and the folders inside it")
        g.add(folder)
        g2 = Adw.PreferencesGroup(title="THE CHANNEL")
        page.add(g2)
        name = Adw.EntryRow(title="Name")
        ctx.hint(name, "What the TV calls it; by default the library's or playlist's name")
        g2.add(name)
        order = Adw.ComboRow(title="Order")
        order.set_model(Gtk.StringList.new([t for _v, t in ORDERS]))
        ctx.hint(order, "Shuffled (the same all day, on every machine), or in order; picked shows in order take "
                        "turns: one episode of each, then the next")
        g2.add(order)
        g3 = Adw.PreferencesGroup(title="ON THESE SCREENS",
                                  description="Every screen by default: turn one off to keep the channel from it")
        page.add(g3)
        checks = {}
        for x, title in SCREENS:
            r = Adw.SwitchRow(title=title, active=True)
            ctx.hint(r, f"Whether {title.lower()} carries this channel")
            g3.add(r)
            checks[x] = r

        def shown(*_):
            k = kinds[kind.get_selected()][0]
            box.set_visible(k == "box")
            server.set_visible(k == "picks" and len(servers) > 1)
            pick_row.set_visible(k == "picks")
            yt.set_visible(k == "youtube")
            folder.set_visible(k == "folder")
        kind.connect("notify::selected", shown)
        if preset:
            kind.set_selected(next((n for n, (k, _t) in enumerate(kinds) if k == preset), 0))
        shown()

        def picked(sel, ordr):
            picks.update(sel)
            n = sum(len(v) for v in picks.values())
            pick_row.set_subtitle(GLib.markup_escape_text(", ".join(picks["shows"] + picks["items"] +
                                                                    picks["collections"])[:120] or "None picked yet")
                                  if n else "None picked yet")
            if ordr is not None:
                order.set_selected(next((k for k, (v, _t) in enumerate(ORDERS) if v == ordr), 0))
        pick_row.connect("activated", lambda *_: self.picker(
            servers[server.get_selected()] if servers else None, picked, picks))

        def ok(d):
            k = kinds[kind.get_selected()][0]
            t = {}
            if k == "box":
                if not box_vals:
                    ctx.toast("Nothing to pick from yet: set up a Jellyfin or Plex source (Settings › Lab)")
                    return
                b = box_vals[box.get_selected()][0]
                t = {b["kind"]: b["title"], "source": b.get("server") or None}
            elif k == "picks":
                if not any(picks.values()):
                    ctx.toast("Pick at least one show, movie or collection")
                    return
                t = {key: v for key, v in picks.items() if v}
                if servers:
                    t["source"] = servers[server.get_selected()]
            elif k == "youtube":
                u = yt.get_text().strip()
                if "youtube.com" not in u and "youtu.be" not in u:
                    ctx.toast("That isn't a YouTube address")
                    return
                t = {"youtube": u}
            elif k == "folder":
                t = {"files": _home(folder._path)}
            elif k == "kept":
                t = {"files": _home(keep)}
            nm = name.get_text().strip() or str(t.get("library") or t.get("collection") or t.get("playlist") or
                                                ("Picked shows" if k == "picks" else "YouTube" if k in ("youtube",)
                                                 else "Downloaded YouTube" if k == "kept" else
                                                 os.path.basename(str(t.get("files", "")).rstrip("/")) or "Files"))
            if TVL._slug(nm) in {ch["key"] for _i, ch, _t in self.entries if ch}:
                ctx.toast(f"There's already a channel called {nm}")
                return
            ordv = ORDERS[order.get_selected()][0]
            scr = [x for x, _t in SCREENS if checks[x].get_active()]
            if not scr:
                ctx.toast("Pick at least one screen")
                return
            table = {"name": nm, **t}
            if ordv:
                table["order"] = ordv
            if self._screens_value(scr):
                table["screens"] = self._screens_value(scr)
            d.close()
            self._write(lambda doc: doc.add(table), f"Added {nm}",
                        undo=lambda i: self._write(lambda doc: doc.remove(i), f"Removed {nm}"))
        d, okb = self._dialog("Add channel", page, "Add", ok)
        d._fields = {"kind": kind, "kinds": [k for k, _t in kinds], "box": box, "server": server, "youtube": yt,
                     "folder": folder, "name": name, "order": order, "screens": checks, "picks": picks}
        d._ok = okb                                           # the tests' driver fills it in and clicks Add
        return d

    def _keep_folder(self):
        """The folder the YouTube channels keep videos in (the first `keep`), if it's there."""
        for _i, ch, t in self.entries:
            k = (t or {}).get("keep")
            if k and os.path.isdir(os.path.expanduser(k)):
                return os.path.expanduser(k)
        d = os.path.expanduser("~/Videos/YouTube")
        return d if os.path.isdir(d) else None

    def contents_dialog(self, idx, ch):
        """Read and edit through the same library as the media app and CLI."""
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Contents")
        page.add(group)
        store = CHANNELS.Store()
        def changed(fn):
            try:
                result = fn()
                self.ctx.toast(result['message']); fill(); self.refresh()
            except (ValueError, OSError) as e:
                self.ctx.toast(str(e), timeout=8)
        def fill():
            for row in getattr(group, '_contents', []): group.remove(row)
            group._contents = []
            try:
                current = store.snapshot(live={})['channels'][store.index(store.load(), ch['name'])]
            except (ValueError,OSError): return
            for n, content in enumerate(current['contents']):
                row = Adw.ActionRow(title=GLib.markup_escape_text(content['title']),
                                    subtitle=content['kind'])
                if current['kind'] == 'picked':
                    key = content['kind'] + 's'
                    values = TVL._as_list(current['table'].get(key))
                    position = values.index(content['value']) + 1
                    for label, icon, delta in (("Earlier", "go-up-symbolic", -1),("Later", "go-down-symbolic", 1)):
                        button = self.ctx.button(None, lambda value=content['value'],pos=position,delta=delta:
                            changed(lambda: store.move_item(ch['name'], value, pos+delta)), label + " in the picked list",
                            icon=icon)
                        button.set_sensitive(1 <= position+delta <= len(values)); row.add_suffix(button)
                    row.add_suffix(self.ctx.button("Remove",lambda value=content['value']:
                        changed(lambda: store.item(ch['name'],value,remove=True)), "Remove this pick; keep its media files"))
                self.ctx.hint(row, content['title']);group.add(row);group._contents.append(row)
        fill()
        if ch.get('picks'):
            add = Adw.PreferencesGroup(title="Add a pick")
            title = Adw.EntryRow(title="Title or YouTube URL")
            self.ctx.hint(title,"A show, movie, YouTube address or music title")
            add.add(title)
            kinds = ['show','movie','youtube','music']
            choose = Gtk.DropDown.new_from_strings(['Show','Movie','YouTube','Music'])
            self.ctx.hint(choose,"The kind of item to add")
            row = Adw.ActionRow(title="Kind"); row.add_suffix(choose); add.add(row)
            button = self.ctx.button('Add',lambda: changed(lambda: store.item(ch['name'],title.get_text(),
                                     item_kind=kinds[choose.get_selected()])),"Add the pick to this channel")
            row.add_suffix(button); page.add(add)
        self._dialog(f"{ch['name']}: contents",page,'Done',lambda dialog: dialog.close(),height=620)

    def edit_picks(self, idx, ch):
        cur = {k: [str(x) for x in (ch.get(k) or [])] if isinstance(ch.get(k), list) else ([str(ch[k])] if ch.get(k)
                                                                                        else [])
               for k in ("shows", "items", "collections")}

        def done(sel, ordr):
            def change(d):
                for k in ("shows", "items", "collections"):
                    d.set(idx, k, sel.get(k) or None)
                if ordr is not None:
                    d.set(idx, "order", ordr or None)
            self._write(change, f"{ch['name']}: {sum(len(v) for v in sel.values())} picked")
        self.picker(ch.get("source"), done, cur, ch.get("order"))

    def picker(self, source, then, current=None, order=None):
        """Pick shows, movies and collections from a server: a searchable grid with posters.
        then({"shows": [titles], "items": [titles], "collections": [titles]}, order or None)."""
        ctx = self.ctx
        sel = {k: list(v) for k, v in (current or {"shows": [], "items": [], "collections": []}).items()}
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{side}")(12)
        bar = Gtk.Box(spacing=8)
        search = Gtk.SearchEntry(placeholder_text="Search", hexpand=True)
        ctx.hint(search, "Type part of a title")
        tg = Adw.ToggleGroup(homogeneous=False)
        for k, t in (("shows", "Shows"), ("items", "Movies"), ("collections", "Collections")):
            tg.add(Adw.Toggle(name=k, label=t))
        tg.set_active_name("shows")
        ctx.hint(tg, "What to pick from: a show's episodes, single movies, or a collection")
        bar.append(tg)
        content.append(bar)
        content.append(search)
        count = Gtk.Label(xalign=0, label="Reading the server's list…")
        count.add_css_class("tv-meta")
        ctx.hint(count, "What's picked so far")
        content.append(count)
        flow = Gtk.FlowBox(homogeneous=True, column_spacing=8, row_spacing=8, selection_mode=Gtk.SelectionMode.NONE,
                           activate_on_single_click=True, min_children_per_line=3, max_children_per_line=5,
                           valign=Gtk.Align.START)
        ctx.hint(flow, "Click a poster (or Enter) to pick it or leave it out")
        sc = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sc.set_child(flow)
        content.append(sc)
        orow = Gtk.Box(spacing=8)
        ol = Gtk.Label(label="Order", xalign=0)
        orow.append(ol)
        ordd = Gtk.DropDown.new_from_strings(["Shuffled: episodes of all of them mixed",
                                              "Taking turns: one episode of each, in order"])
        ordd.set_selected(1 if order in ("in order", "alternate") else 0)
        ctx.hint(ordd, "Shuffled mixes them the same way all day; taking turns plays each show's next episode in "
                       "turn, each going on from where it left off")
        orow.append(ordd)
        content.append(orow)
        lists = {"shows": None, "items": None, "collections": None}

        def label():
            n = {k: len(v) for k, v in sel.items()}
            count.set_label(f"{n['shows']} shows, {n['items']} movies, {n['collections']} collections picked"
                            + ("" if lists.get(tg.get_active_name()) is not None else " · reading the server's list…"))

        def fill():
            k = tg.get_active_name()
            while (c := flow.get_first_child()) is not None:
                flow.remove(c)
            q = search.get_text().strip().lower()
            for rec in (lists.get(k) or []):
                if q and q not in str(rec.get("title", "")).lower():
                    continue
                flow.append(tile(k, rec))
            label()

        def tile(k, rec):
            child = Gtk.FlowBoxChild()
            child._rec, child._kind = rec, k
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            b.add_css_class("tv-pick")
            on = rec["title"] in sel[k] or str(rec.get("id")) in sel[k]
            if on:
                b.add_css_class("picked")
            pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
            pic.set_size_request(110, 160)
            pic.add_css_class("tv-poster")
            self._set_poster(pic, {"kind": "server", "source": source}, rec)
            b.append(pic)
            row = Gtk.Box(spacing=4)
            cb = Gtk.CheckButton(active=on, can_focus=False)
            cb.set_can_target(False)
            row.append(cb)
            t = Gtk.Label(label=rec["title"] + (f" ({rec['year']})" if rec.get("year") else ""), xalign=0, wrap=True,
                          lines=2, ellipsize=Pango.EllipsizeMode.END, max_width_chars=16)
            t.add_css_class("tv-pick-title")
            row.append(t)
            b.append(row)
            child.set_child(b)
            child._check, child._box = cb, b
            what = {"shows": f"{rec.get('count') or 'its'} episodes", "items": "a movie",
                    "collections": f"{rec.get('count') or 'its'} items"}[k]
            ctx.hint(child, f"{rec['title']}: {what}. Click to {'leave it out' if on else 'pick it'}")
            return child

        def toggle(_f, child):
            k, rec = child._kind, child._rec
            names = sel[k]
            if rec["title"] in names or str(rec.get("id")) in names:
                sel[k] = [x for x in names if x not in (rec["title"], str(rec.get("id")))]
                child._box.remove_css_class("picked")
                child._check.set_active(False)
            else:
                sel[k].append(rec["title"])
                child._box.add_css_class("picked")
                child._check.set_active(True)
            label()
        flow.connect("child-activated", toggle)
        search.connect("search-changed", lambda *_: fill())
        tg.connect("notify::active-name", lambda *_: (load(tg.get_active_name()), fill()))

        def load(k):
            if lists.get(k) is not None:
                return
            lists[k] = None
            ctx.pending += 1

            def run():
                recs, err = [], None
                try:
                    import bromigos_homelab as H
                    a = H.video_source(source or None)
                    if a is None:
                        raise LookupError("no Jellyfin or Plex source in homelab.toml")
                    recs = (a.video_shows() if k == "shows" else a.video_movies() if k == "items" else
                            [b for b in a.video() if b.get("kind") == "collection"])
                except Exception as e:                        # noqa: BLE001
                    err = f"{type(e).__name__}: {e}"

                def done():
                    ctx.pending -= 1
                    lists[k] = recs
                    if err:
                        count.set_label(f"Couldn't read the server's list: {err}"[:200])
                    if tg.get_active_name() == k:
                        fill()
                        if err:
                            count.set_label(f"Couldn't read the server's list: {err}"[:200])
                    return False
                GLib.idle_add(done)
            threading.Thread(target=run, daemon=True).start()

        def ok(d):
            d.close()
            then({k: list(v) for k, v in sel.items()}, "in order" if ordd.get_selected() == 1 else "shuffle")
        load("shows")
        label()
        self._dialog("Pick shows", content, "Done", ok, width=720, height=680)
        search.grab_focus()


def _home(p):
    h = os.path.expanduser("~")
    return "~" + p[len(h):] if p.startswith(h + "/") else p


def _get(url, headers):
    """A poster's bytes: the system's CAs, and the homelab's added (its own servers)."""
    ctx = ssl.create_default_context()
    try:
        import bromigos_homelab as H
        ca = H.config.expand(H.config.setting("tls", "ca_file", ""))
        if ca and os.path.isfile(ca):
            ctx.load_verify_locations(cafile=ca)
    except Exception:                                         # noqa: BLE001
        pass
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10, context=ctx) as r:
        body = r.read(4 << 20)
    try:                                                      # small and in a format GTK reads (webp may not be)
        from PIL import Image
        im = Image.open(io.BytesIO(body)).convert("RGB")
        im.thumbnail((360, 360))
        out = io.BytesIO()
        im.save(out, "PNG")
        return out.getvalue()
    except Exception:                                         # noqa: BLE001
        return body


def build(ctx):
    g = Guide(ctx)
    g.page._guide = g
    return g.page


def refresh(page):
    g = getattr(page, "_guide", None)
    if g is not None:
        g.refresh()


PAGE = Page(
    id="den-tv", title="Den TV", group="desktop", order=46, build=build, refresh=refresh,
    docs="themes-and-worlds.md#the-channel-guide", icon="video-display-symbolic tv-symbolic",
    summary="channels on the den's screens",
    intro="The channel guide: every channel on the den's three screens, what's on now and next. Add one from your "
          "Jellyfin or Plex, shows you pick, YouTube or a folder; tune any screen to any channel.",
    keywords=["tv", "den", "channels", "guide", "jellyfin", "plex", "youtube", "shows", "movies", "scope",
              "monitor", "media"],
    entries=[Entry("channels", "The den TV's channels", ["add channel", "guide", "tv"], "Channels"),
             Entry("status", "Add a channel", ["new channel", "library", "playlist", "youtube", "shows"], "Channels"),
             Entry("grid", "Tune a screen", ["big monitor", "scope", "small monitor", "tune", "on air", "bumpers"],
                   "The guide")])

# The guide uses the Settings toolkit for rows, commands, colours and offscreen renders.
# Its window has no Settings sidebar or search: it is an independent application.
from bromigos_settings import app as settings_app
from bromigos_settings.context import Context
from gi.repository import Gio


class Window(Adw.ApplicationWindow):
    _fit = settings_app.Window._fit
    toast = settings_app.Window.toast
    undo = settings_app.Window.undo
    restyle = settings_app.Window.restyle
    _theme_tick = settings_app.Window._theme_tick
    _watch_theme = settings_app.Window._watch_theme
    manual_url = settings_app.Window.manual_url

    def __init__(self, app, size=None):
        super().__init__(application=app, title="Den TV")
        self._fit(size)
        self.ctx = Context(self)
        self.colors = {}; self.undo_last = None; self._channel_base = None
        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self._css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.restyle(); self._watch_theme()
        GLib.timeout_add_seconds(2,self._theme_tick)
        self.pages = {"den-tv": PAGE}; self.order = ['den-tv']; self.current = 'den-tv'
        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Den TV",subtitle="Your channels on the den's screens"))
        toolbar.add_top_bar(header)
        self.ctx.building = PAGE
        page = build(self.ctx)
        page.reset_button.set_visible(False)
        self.ctx.building = None
        self.built = {'den-tv': page}
        toolbar.set_content(page)
        self.toasts.set_child(toolbar); self.set_content(self.toasts)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed',self._key)
        self.add_controller(keys)

    def _key(self, _controller, key, _code, mods):
        if mods & Gdk.ModifierType.CONTROL_MASK:
            if key == Gdk.KEY_z: self.undo(); return True
            if key == Gdk.KEY_w: self.close(); return True
        return False

    def open_page(self, page_id, key=None):
        if page_id != 'den-tv':
            self.ctx.launch(['bromigos-settings',page_id + ('#'+key if key else '')])


class App(settings_app.App):
    def __init__(self, render=None):
        flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if render: flags |= Gio.ApplicationFlags.NON_UNIQUE
        Adw.Application.__init__(self,application_id='org.bromigos.DenTV',flags=flags)
        self.render = render; self.win = None

    def _window(self):
        if self.win is None: self.win = Window(self,size=(self.render or {}).get('size'))
        return self.win


def main(argv):
    render = None
    if '--render' in argv or '--audit' in argv:
        def opt(key, default): return argv[argv.index(key)+1] if key in argv else default
        render = dict(out=opt('--render','-'), page='den-tv', key=None, search=None,
                      size=tuple(int(v) for v in opt('--size','1180x980').split('x')),
                      audit='--audit' in argv, advanced=False)
        argv = [argv[0]]
    return App(render).run(argv)
