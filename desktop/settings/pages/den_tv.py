"""Den TV: the channel guide. Every channel of the den's three screens (the big monitor,
the scope, the small monitor) as a TV guide: what's on now and next, with its poster, its
source, its order and how far through it is, the channel each screen is on marked. Add a
channel (a library, collection or playlist from your Jellyfin or Plex, shows or movies you
pick, a YouTube playlist or channel, a folder, your downloaded YouTube videos), remove one
(with Undo), drag one to reorder it or onto another screen, rename it, tune a screen to it.

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

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from bromigos_settings import Entry, Page

# a bromigOS checkout's own libs first (its tests run the page from there), else the installed ones
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
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
except ImportError:                        # an older bromigos-core: no guide
    TVL = C = None

SCREENS = [("big", "The big monitor"), ("wave", "The scope"), ("emblem", "The small monitor")]
SCREEN_NAME = dict(SCREENS)
LIVE = ["bromigos-live", "tv"]
CARD_W, POSTER_H = 216, 122
ORDERS = [("", "Its own (playlists in order, the rest shuffled)"), ("shuffle", "Shuffled, the same all day"),
          ("in order", "In order (picked shows take turns)")]
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
        self.flows = {}
        self.groups = {}
        self.entries = []                         # [(index in the file, channel dict or None, table)]
        self.panel = None
        if TVL is None:
            ctx.placeholder(self.page, "The den TV", "This needs bromigOS's den TV library (bromigos-core 0.1.2 or "
                                                     "newer).")
            return
        top = ctx.group(self.page, "Channels", None, key="channels")
        self.top = top
        self.status = ctx.row(top, "The den's three screens", "", key="status",
                              hint="Each screen plays its own channel at once; channel 1 is the screen's own picture",
                              buttons=[("Add channel…", self.add_dialog,
                                        "Makes a new channel: a library, shows you pick, YouTube or a folder"),
                                       ("Refresh", self.refresh, "Reads the channels and what's on again")],
                              advanced={"file": C.path() if C else "", "runs": "bromigos-live tv set N --screen S"})
        for s, title in SCREENS:
            g = ctx.group(self.page, title, None, key=f"screen-{s}",
                          hint=f"{title}'s channels, channel 1 first. Drag a card to reorder it, or onto another "
                               "screen to move it there")
            flow = Gtk.FlowBox(homogeneous=True, column_spacing=10, row_spacing=10,
                               selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=False)
            flow.set_min_children_per_line(1)
            flow.set_max_children_per_line(5)
            flow.set_valign(Gtk.Align.START)
            flow.set_margin_top(6)
            flow.connect("child-activated", lambda _f, child: self.tune(child._screen, child._number))
            ctx.hint(flow, f"{title}'s channels: Enter tunes it, Delete removes, F2 renames, Alt+arrows move")
            drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
            drop.connect("drop", lambda _t, v, _x, _y, s=s: self._dropped(v, s, None))
            drop.connect("enter", lambda t, *_: (t.get_widget().add_css_class("tv-screen-drop"), Gdk.DragAction.MOVE)[1])
            drop.connect("leave", lambda t: t.get_widget().remove_css_class("tv-screen-drop"))
            flow.add_controller(drop)
            g.add(flow)
            self.flows[s] = flow
            self.groups[s] = g
        self.refresh()
        GLib.timeout_add_seconds(20, self._tick)
        want = os.environ.get("BROMIGOS_DEN_TV_OPEN")         # the tests' renders: a dialog open
        if want == "add":
            GLib.idle_add(lambda: (self.add_dialog(), False)[1])
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

    def _draw(self):
        running = self.live is not None
        n = sum(1 for _i, ch, _t in self.entries if ch)
        bad = sum(1 for _i, ch, _t in self.entries if ch is None)
        snd = (self.live or {}).get("sound_from")
        self.status.set_subtitle(GLib.markup_escape_text(
            f"{n} channel{'s' if n != 1 else ''}" + (f" (and {bad} that can't play: no name or nothing to play)"
                                                     if bad else "")
            + (" · the live layer isn't running: tuning waits for it" if not running else "")
            + (f" · sound from {SCREEN_NAME.get(snd, snd).lower()}" if snd else "")))
        for s, _title in SCREENS:
            flow = self.flows[s]
            while (c := flow.get_first_child()) is not None:
                flow.remove(c)
            tuned = self._tuned(s)
            lu = self.lineup(s)
            on = next((num for num, ch, _i in lu if ch["key"] == tuned), 1)
            self.groups[s].set_description(GLib.markup_escape_text(
                f"{len(lu)} channel{'s' if len(lu) != 1 else ''} · on channel {on}"
                + (" · its sound is on" if snd == s else "")))
            for num, ch, idx in lu:
                flow.append(self._card(s, num, ch, idx, num == on, snd == s and num == on))

    # ------------------------------------------------------------------ a card
    def _card(self, s, num, ch, idx, on_air, sound):
        ctx = self.ctx
        child = Gtk.FlowBoxChild()
        child.add_css_class("tv-card")
        child.set_focusable(True)
        child._screen, child._number, child._index, child._ch = s, num, idx, ch
        if on_air:
            child.add_css_class("on-air")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_size_request(CARD_W, -1)
        slot = None if ch["kind"] == "own" else TVL.now_next(ch)
        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        pic.set_size_request(CARD_W, POSTER_H)
        pic.add_css_class("tv-poster")
        item = slot.item if slot else None
        self._set_poster(pic, ch, item)
        frame = Gtk.Overlay()
        frame.set_child(pic)
        if ch["kind"] == "own":
            own = Gtk.Label(label=ch["name"], wrap=True, justify=Gtk.Justification.CENTER)
            own.add_css_class("tv-chnum")
            frame.add_overlay(own)
        box.append(frame)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        for side in ("start", "end"):
            getattr(inner, f"set_margin_{side}")(8)
        inner.set_margin_bottom(8)
        head = Gtk.Box(spacing=6)
        lab = Gtk.Label(label=f"CH {num}", xalign=0)
        lab.add_css_class("tv-chnum")
        head.append(lab)
        name = Gtk.Label(label=ch["name"], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                         max_width_chars=14)
        name.add_css_class("tv-name")
        head.append(name)
        if sound:
            sp = Gtk.Label(label="SOUND")
            sp.add_css_class("tv-sound")
            ctx.hint(sp, f"The den's sound comes from {SCREEN_NAME[s].lower()} (one screen at a time)")
            head.append(sp)
        if on_air:
            badge = Gtk.Label(label="ON AIR")
            badge.add_css_class("tv-onair")
            ctx.hint(badge, f"{SCREEN_NAME[s]} is on this channel now")
            head.append(badge)
        inner.append(head)
        if ch["kind"] == "own":
            now = Gtk.Label(label=ch.get("what", "").capitalize(), xalign=0, wrap=True, max_width_chars=24)
            now.add_css_class("tv-now")
            inner.append(now)
            meta = Gtk.Label(label="The screen's own picture, as bromigOS draws it", xalign=0, wrap=True,
                             max_width_chars=24)
            meta.add_css_class("tv-meta")
            inner.append(meta)
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
            meta = Gtk.Label(label=f"{_channel_text(ch)} · {_order_text(ch)}", xalign=0,
                             ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
            meta.add_css_class("tv-meta")
            others = [SCREEN_NAME[x].lower() for x in ch["screens"] if x != s]
            ctx.hint(meta, _channel_text(ch) + f"; {_order_text(ch)}" +
                     (f"; also on {', '.join(others)}" if others else "; on this screen only") +
                     ("; from the MEDIA panel's settings" if idx == "panel" else ""))
            inner.append(meta)
        acts = Gtk.Box(spacing=6)
        acts.set_margin_top(4)
        tune = ctx.button("Tune now" if not on_air else "On now", lambda: self.tune(s, num),
                          f"Puts {SCREEN_NAME[s].lower()} on channel {num}, {ch['name']} "
                          f"(bromigos-live tv set {num} --screen {s})")
        tune.set_sensitive(not on_air)
        tune.set_hexpand(True)
        acts.append(tune)
        if ch["kind"] != "own":
            acts.append(self._menu(child, s, num, ch, idx))
        inner.append(acts)
        box.append(inner)
        child.set_child(box)
        ctx.hint(child, f"Channel {num} on {SCREEN_NAME[s].lower()}: {ch['name']}"
                 + (" (on now)" if on_air else "") + ". Enter: tune · Delete: remove · F2: rename · Alt+←/→: move")
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, _code, st, c=child: self._key(c, kv, st))
        child.add_controller(keys)
        if isinstance(idx, int):
            src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
            src.connect("prepare", lambda *_a, i=idx, s=s: Gdk.ContentProvider.new_for_value(f"{i}:{s}"))
            child.add_controller(src)
            drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
            drop.connect("drop", lambda _t, v, _x, _y, i=idx, s=s: self._dropped(v, s, i))
            drop.connect("enter", lambda t, *_: (t.get_widget().add_css_class("drop"), Gdk.DragAction.MOVE)[1])
            drop.connect("leave", lambda t: t.get_widget().remove_css_class("drop"))
            child.add_controller(drop)
        self.cards[(s, num)] = child
        return child

    def _menu(self, child, s, num, ch, idx):
        ctx = self.ctx
        group = Gio.SimpleActionGroup()
        menu = Gio.Menu()

        def act(name, cb, label):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: cb())
            group.add_action(a)
            menu.append(label, f"card.{name}")
        if idx == "panel":
            act("panel", lambda: ctx.open_page("widgets"), "Edit in the MEDIA panel's settings…")
        else:
            act("rename", lambda: self.rename_dialog(idx, ch), "Rename…")
            if ch.get("picks"):
                act("shows", lambda: self.edit_picks(idx, ch), "Pick shows…")
            act("earlier", lambda: self.move(idx, -1), "Move earlier")
            act("later", lambda: self.move(idx, +1), "Move later")
            sub = Gio.Menu()
            for x, title in SCREENS:
                a = Gio.SimpleAction.new_stateful(f"on-{x}", None, GLib.Variant.new_boolean(x in ch["screens"]))
                a.connect("change-state", lambda a_, v, x=x: self.set_screen(idx, ch, x, v.get_boolean()))
                group.add_action(a)
                sub.append(title, f"card.on-{x}")
            menu.append_section("On these screens", sub)
            rm = Gio.Menu()
            a = Gio.SimpleAction.new("remove", None)
            a.connect("activate", lambda *_: self.remove(idx, ch))
            group.add_action(a)
            rm.append("Remove", "card.remove")
            menu.append_section(None, rm)
        child.insert_action_group("card", group)
        b = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu)
        ctx.hint(b, f"{ch['name']}: rename, pick its shows, move it, choose its screens, or remove it")
        return b

    def _key(self, child, kv, state):
        idx, ch, s = child._index, child._ch, child._screen
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space) and not alt:
            self.tune(s, child._number)
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
            if ch["kind"] in ("youtube", "live"):
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
            doc = C.load()
            back = change(doc)
            doc.save()
        except Exception as e:                                # noqa: BLE001  (ConfigError, OSError)
            self.ctx.toast(f"Not changed: {e}"[:200], timeout=8)
            return None
        self.ctx.run(LIVE + ["reload"])                       # at once (the live layer would see it anyway)
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
        self._write(lambda d: d.remove(idx), f"Removed {ch['name']}",
                    undo=lambda back: self._write(lambda d: d.restore(*back), f"{ch['name']} is back"))

    def move(self, idx, step):
        n = len(self.entries)
        j = max(0, min(n - 1, idx + step))
        if j == idx:
            return
        self._write(lambda d: d.move(idx, j), f"Moved {self.entries[idx][2].get('name') or 'the channel'}",
                    undo=lambda _b: self._write(lambda d: d.move(j, idx), "Moved back"))

    def set_screen(self, idx, ch, screen, on):
        now = list(ch["screens"])
        new = [x for x, _t in SCREENS if (x in now or (on and x == screen)) and not (not on and x == screen)]
        if not new:
            self.ctx.toast("A channel needs at least one screen: remove it instead")
            self.refresh()
            return
        old = (self.entries[idx][2] or {}).get("screens")
        self._write(lambda d: d.set(idx, "screens", self._screens_value(new)),
                    f"{ch['name']}: on {', '.join(SCREEN_NAME[x].lower() for x in new)}",
                    undo=lambda _b: self._write(lambda d: d.set(idx, "screens", old), "Screens put back"))

    @staticmethod
    def _screens_value(screens):
        return "any" if len(screens) == len(SCREENS) else list(screens)

    def _dropped(self, value, screen, target):
        """A card dropped on another card (before it) or on a screen's empty space (its end):
        reordered, and moved to that screen when it came from another."""
        try:
            i, from_ = str(value).split(":", 1)
            i = int(i)
        except ValueError:
            return False
        if not (0 <= i < len(self.entries)):
            return False
        ch = self.entries[i][1]
        table = self.entries[i][2]
        j = target if isinstance(target, int) else None
        screens = list(ch["screens"]) if ch else [from_]
        moved_screen = from_ != screen
        if moved_screen:
            screens = [screen if x == from_ else x for x in screens]
            screens = [x for k, x in enumerate(screens) if x not in screens[:k]]
            if screen not in screens:
                screens.append(screen)
        old_screens = table.get("screens")

        def change(d):
            if moved_screen:
                d.set(i, "screens", self._screens_value(screens))
            if j is not None and j != i:
                d.move(i, j if j < i else j - 1)
            return None
        what = table.get("name") or "the channel"
        said = f"{what}: moved to {SCREEN_NAME[screen].lower()}" if moved_screen else f"Moved {what}"

        def undo(_b):
            def back(d):
                now = j if j is not None and j < i else (j - 1 if j is not None else i)
                if j is not None and now != i:
                    d.move(now, i)
                if moved_screen:
                    d.set(i, "screens", old_screens)
            self._write(back, "Put back")
        self._write(change, said, undo=undo)
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
                                  description="Any screen by default: each screen numbers its own channels")
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
    docs="settings.md#den-tv", icon="video-display-symbolic tv-symbolic",
    summary="channels on the den's screens",
    intro="The channel guide: every channel on the den's three screens, what's on now and next. Add one from your "
          "Jellyfin or Plex, shows you pick, YouTube or a folder; drag to reorder or move it to another screen.",
    keywords=["tv", "den", "channels", "guide", "jellyfin", "plex", "youtube", "shows", "movies", "scope",
              "monitor", "media"],
    entries=[Entry("channels", "The den TV's channels", ["add channel", "guide", "tv"], "Channels"),
             Entry("status", "Add a channel", ["new channel", "library", "playlist", "youtube", "shows"], "Channels"),
             Entry("screen-big", "The big monitor's channels", ["big", "monitor"], "The big monitor"),
             Entry("screen-wave", "The scope's channels", ["scope", "wave"], "The scope"),
             Entry("screen-emblem", "The small monitor's channels", ["small monitor", "emblem"], "The small monitor")])
