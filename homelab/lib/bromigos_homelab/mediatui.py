"""`bromigos media` (and `bromigos lab media` with no subcommand, in a terminal): your media
library in a terminal UI (Textual), on the same code as `bromigos lab media` (mediareq.py).

Tabs: TV (Sonarr), MOVIES (Radarr), MUSIC (Lidarr), YOUTUBE (Pinchflat), DOWNLOADS (what the
download clients are fetching), UPCOMING (the calendar of what you track) and SEARCH (search
and request, as `media get`) and CHANNELS (the den TV). The header has the library's totals and the free space.

On a selected title, season, album or episode file: m monitors or stops, n picks up new
episodes or not, P changes the quality profile, p plays on a den TV, f searches now, o opens it in Jellyfin,
O in Seerr, t plays it full screen, D deletes it. A delete says exactly what goes and how
much space it frees, then asks for Delete or Cancel. / filters, s
sorts (added, size, name, missing, profile). Vim keys beside the arrows; every key, tab,
row and button has a hint.

The colours are the desktop theme's, like `bromigos lab`'s dashboard.
"""
import subprocess

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, Footer, Input, Label, RichLog, Select, Static, TabbedContent,
                             TabPane, Tabs)

from . import mediareq as M
from .tvchannels import channels as CH
from .tui import HintTable, bromigos_theme
from .tuiux import Dialog, UXApp

GLYPH = {"tv": "▤", "movie": "▣", "artist": "♫", "album": "◉", "youtube": "▶"}
SORTS = ("added", "size", "name", "missing", "profile")


def _short(v, n=26):
    """A cell no wider than n (the hint has it in full)."""
    v = "" if v is None else v
    return v if not isinstance(v, str) or len(v) <= n else v[:n - 1] + "…"


class Live:
    """Where the library comes from and where changes go (a test passes its own Lab)."""

    def __init__(self, lab=None):
        self.lab = lab or M.Lab()

    def totals(self):
        return M.totals(self.lab)

    def library(self, kind):
        return M.library(self.lab, kind)

    def seasons(self, rec):
        return rec.get("seasons") or []

    def episode_files(self, rec, season=None):
        return M.episode_files(self.lab, rec["id"], season)

    def albums(self, rec):
        return M.albums(self.lab, rec["id"])

    def downloads(self):
        return M.status(self.lab, finish=False)

    def upcoming(self, days=60):
        return M.upcoming(self.lab, days)

    def youtube(self):
        from . import pinchflat
        if not self.lab.src("pinchflat"):
            return []
        pf, _ = pinchflat.connect()
        return pf.sources()

    def profiles(self, app):
        return [(p["name"], p["id"]) for p in self.lab.profiles(app)]

    def search(self, q, kind):
        return M.search(self.lab, q, kind or None)

    def plan(self, item, **kw):
        return M.plan(self.lab, item, **kw)

    def request(self, plan):
        return M.run(self.lab, plan)

    def monitor(self, rec, on, season=None, new_items=None, album=None):
        if album is not None:
            M.set_album_monitored(self.lab, album, on)
            return "album " + ("monitored" if on else "not monitored")
        return M.set_monitored(self.lab, rec["app"], rec["id"], on, season, new_items)

    def set_profile(self, rec, pid):
        return M.set_profile(self.lab, rec["app"], rec["id"], pid)

    def search_now(self, rec, season=None, album=None):
        return M.search_now(self.lab, rec["app"], rec["id"], season, album)

    def delete_plan(self, rec, season=None, files=None, album=None):
        return M.delete_plan(self.lab, rec["app"], rec["id"], season, files, album)

    def delete(self, rec, season=None, files=None, album=None, exclude=False):
        return M.delete(self.lab, rec["app"], rec["id"], season, files, album, exclude)

    def link(self, rec, where):
        return M.web_link(self.lab, rec, where)

    def open(self, url):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def play(self, rec):
        return M.play(self.lab, rec)


class MediaInput(Input):
    """Text fields keep printable keys, including app shortcuts."""


class MediaTable(HintTable):
    """Keep the lab's shared Vim bindings; Up at the first row returns to tabs."""

    def action_cursor_up(self):
        if self.cursor_row == 0:
            self.app.query_one("#tabs Tabs", Tabs).focus()
        else:
            super().action_cursor_up()

    def fill(self, columns, rows, hints, base_hint=""):
        self.channel_base_hints = list(hints)
        hints = [self.app.channel_hint(self, index, hint) for index, hint in enumerate(self.channel_base_hints)]
        super().fill(columns, rows, hints, base_hint)

    def refresh_membership(self):
        self.hints = [self.app.channel_hint(self, index, hint)
                      for index, hint in enumerate(getattr(self, "channel_base_hints", []))]
        self.watch_hover_coordinate(self.hover_coordinate, self.hover_coordinate)


# ------------------------------------------------------------------ dialogs
class Confirm(Dialog):
    """Show what goes, then ask for Delete or Cancel. Cancel has focus by default."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel", tooltip="Close without deleting anything"),
                Binding("left", "choose_button(-1)", "Previous", priority=True, show=False),
                Binding("right", "choose_button(1)", "Next", priority=True, show=False),
                Binding("up", "choice_step(-1)", "Previous", priority=True, show=False),
                Binding("down", "choice_step(1)", "Next", priority=True, show=False),
                Binding("enter", "activate_choice", "Choose", priority=True, show=False)]

    def __init__(self, plan):
        super().__init__()
        self.plan = plan

    def compose(self):
        p = self.plan
        with Vertical(id="delbox"):
            yield Label(f"Delete {p['what']}?", classes="title", id="del-what")
            yield Static(("Only the channel is removed. Its media files stay. Ctrl+Z restores it." if p["scope"] == "channel" else f"It frees {M.human(p['size'])}. The files go from the disk; Jellyfin and Plex rescan."
                         + ("" if p["scope"] != "season" else " The season stops being monitored, so it isn't "
                            "fetched again.")), classes="dim")
            c = Checkbox("Don't download it again", id="del-exclude",
                         value=False, disabled=p["scope"] not in ("title", "album"))
            c.tooltip = "Sonarr, Radarr or Lidarr won't add it again from a list"
            yield c
            with Horizontal():
                b = Button("Cancel", id="del-no")
                b.tooltip = "Keep it (Escape)"
                yield b
                b = Button("Delete", id="del-yes", variant="error")
                b.tooltip = "Delete only the files listed above"
                yield b
            yield Label("←/→ choose · Enter select · Tab fields · Esc cancel", classes="dim")

    def on_mount(self):
        self.query_one("#del-no", Button).focus()

    def action_choose_button(self, step):
        buttons = [self.query_one("#del-no", Button), self.query_one("#del-yes", Button)]
        current = buttons.index(self.focused) if self.focused in buttons else 0
        buttons[(current + step) % len(buttons)].focus()

    def action_activate_choice(self):
        if isinstance(self.focused, Button):
            self.focused.press()
        elif isinstance(self.focused, Checkbox) and not self.focused.disabled:
            self.focused.toggle()

    def action_choice_step(self, step):
        choices = [self.query_one(selector) for selector in ("#del-exclude", "#del-no", "#del-yes")]
        choices = [choice for choice in choices if not choice.disabled]
        current = choices.index(self.focused) if self.focused in choices else 0
        choices[(current + step) % len(choices)].focus()

    @on(Button.Pressed, "#del-no")
    def no(self):
        self.dismiss(None)

    @on(Button.Pressed, "#del-yes")
    def go(self):
        self.dismiss({"exclude": self.query_one("#del-exclude", Checkbox).value})


class PickProfile(Dialog):
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel", tooltip="Keep its profile")]

    def __init__(self, title, options, current):
        super().__init__()
        self.title_, self.options, self.current = title, options, current

    def compose(self):
        with Vertical(id="profbox"):
            yield Label(f"Quality profile for {self.title_}", classes="title")
            s = Select(self.options, value=self.current if any(v == self.current for _, v in self.options)
                       else Select.BLANK, id="prof", allow_blank=False)
            s.tooltip = "The profile decides the quality and the audio rule (Recyclarr's TRaSH profiles)"
            yield s
            with Horizontal():
                yield Button("Cancel", id="prof-no")
                yield Button("Apply profile", id="prof-yes", variant="primary")

    @on(Button.Pressed, "#prof-no")
    def no(self):
        self.dismiss(None)

    @on(Button.Pressed, "#prof-yes")
    def yes(self):
        self.dismiss(self.query_one("#prof", Select).value)


class Request(Dialog):
    """`media get` as a form: seasons, quality, audio, new episodes; the plan, then Request."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel", tooltip="Close without requesting anything")]

    def __init__(self, src, item):
        super().__init__()
        self.src, self.item, self.plan = src, item, None

    def compose(self):
        it = self.item
        with Vertical(id="reqbox"):
            yield Static(M.summary(it), classes="title", markup=False)
            if it["kind"] == "tv":
                s = Select([("All seasons", "all"), ("The latest season", "latest"), ("Only new episodes", "future")],
                           value="all", id="req-seasons", allow_blank=False)
                s.tooltip = "What to fetch now"
                yield s
                i = MediaInput(placeholder="or seasons: 1,3 or 2-4 · or episodes: S02E05,S03E01", id="req-pick")
                i.tooltip = "Some seasons (1,3 or 2-4) or episodes (S02E05,S03E01); leave empty for the choice above"
                yield i
                c = Checkbox("Keep up with new episodes", value=True, id="req-new")
                c.tooltip = "Sonarr picks up new episodes and seasons as they come"
                yield c
                c = Checkbox("Specials too", value=False, id="req-specials")
                yield c
            if it["kind"] in ("tv", "movie"):
                s = Select([(q, q) for q in M.QUALITIES], value="best", id="req-quality", allow_blank=False)
                s.tooltip = "best, or a ceiling"
                yield s
                s = Select([("My languages", ""), ("English", "en"), ("Japanese", "ja"), ("Any", "any")], value="",
                           id="req-audio", allow_blank=False)
                s.tooltip = "This request's audio (your [media] setting by default)"
                yield s
            yield RichLog(id="req-plan", wrap=True, markup=False)
            with Horizontal():
                yield Button("Cancel", id="req-no")
                b = Button("Preview", id="req-planbtn")
                b.tooltip = "Show what it would do: the profile and why, the size, the free space"
                yield b
                b = Button("Request", id="req-yes", variant="primary", disabled=True)
                b.tooltip = "Request it now"
                yield b

    def _opts(self):
        kw = {}
        if self.item["kind"] == "tv":
            pick = self.query_one("#req-pick", Input).value.strip()
            if pick and "e" in pick.lower():
                kw["episodes"] = pick
            else:
                kw["seasons"] = pick or self.query_one("#req-seasons", Select).value
            kw["new"] = self.query_one("#req-new", Checkbox).value
            kw["specials"] = self.query_one("#req-specials", Checkbox).value
        if self.item["kind"] in ("tv", "movie"):
            q = self.query_one("#req-quality", Select).value
            kw["quality"] = None if q == "best" else q
            kw["audio"] = self.query_one("#req-audio", Select).value or None
        return kw

    def on_mount(self):
        self._preview_serial = 0
        self.show_plan()

    @on(Input.Changed, "#req-pick")
    @on(Select.Changed)
    @on(Checkbox.Changed)
    def options_changed(self):
        if getattr(self, "_submitting", False):
            return
        if self.is_mounted and hasattr(self, "_preview_serial"):
            self.show_plan()

    @on(Button.Pressed, "#req-planbtn")
    def show_plan(self):
        if getattr(self, "_submitting", False):
            return
        opts = self._opts()
        self.plan = None
        self._preview_serial = getattr(self, "_preview_serial", 0) + 1
        self.query_one("#req-yes", Button).disabled = True
        self.query_one("#req-plan", RichLog).clear().write("Reading the request plan…")
        self.preview_plan(opts, self._preview_serial)

    @work(thread=True, group="request-preview", exclusive=True)
    def preview_plan(self, opts, serial):
        try:
            plan = self.src.plan(self.item, **opts)
            error = None
        except M.MediaError as e:
            plan, error = None, str(e)
        self.app.call_from_thread(self.show_preview, opts, serial, plan, error)

    def show_preview(self, opts, serial, plan, error):
        if not self.is_mounted or serial != self._preview_serial or opts != self._opts():
            return
        log = self.query_one("#req-plan", RichLog)
        log.clear()
        if error:
            log.write(f"Can't request: {error}")
            return
        self.plan, self._plan_opts = plan, opts
        for line in M.plan_lines(plan):
            log.write(line)
        self.query_one("#req-yes", Button).disabled = False

    def check_action(self, action, parameters):
        if getattr(self, "_submitting", False):
            return False
        return super().check_action(action, parameters)

    @on(Button.Pressed, "#req-no")
    def no(self):
        if not getattr(self, "_submitting", False):
            self.dismiss(None)

    @on(Button.Pressed, "#req-yes")
    def yes(self):
        if self.plan is None or self._opts() != self._plan_opts:
            self.show_plan()
            return
        self._submitting = True
        for control in self.query("Button, Input, Select, Checkbox"):
            control.disabled = True
        self.query_one("#req-plan", RichLog).write("Requesting… Please wait for the result.")
        self.submit_request(self.plan)

    @work(thread=True, group="request-submit", exclusive=True)
    def submit_request(self, plan):
        try:
            result = self.src.request(plan)
            if self.is_mounted:
                self.app.call_from_thread(self.dismiss, result)
        except M.MediaError as e:
            if self.is_mounted:
                self.app.call_from_thread(self.request_error, str(e))

    def request_error(self, error):
        self._submitting = False
        for control in self.query("Button, Input, Select, Checkbox"):
            control.disabled = False
        self.query_one("#req-plan", RichLog).write(f"Not requested: {error}")
        self.query_one("#req-yes", Button).disabled = False


class ChannelForm(Dialog):
    """A name, title or new channel source; Escape cancels without writing."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title="New channel", value="", create=False):
        super().__init__(); self.title_, self.value, self.create = title, value, create

    def compose(self):
        with Vertical(id="channel-box"):
            yield Label(self.title_)
            yield MediaInput(value=self.value, placeholder="Name", id="channel-name")
            if self.create:
                yield Select([(t, k) for t, k in (("Picked shows", "shows"), ("Picked items", "items"),
                             ("Library", "library"), ("YouTube playlist", "youtube"), ("Folder", "folder"))],
                             value="shows", allow_blank=False, id="channel-kind")
                yield MediaInput(placeholder="Titles separated by |, library name, URL or folder", id="channel-source")
            with Horizontal():
                yield Button("Cancel", id="channel-cancel")
                yield Button("Save channel", id="channel-save", variant="primary")

    @on(Button.Pressed, "#channel-cancel")
    def cancel(self): self.dismiss(None)

    @on(Button.Pressed, "#channel-save")
    def save(self):
        name = self.query_one("#channel-name", Input).value.strip()
        if not name: return
        result = {"name": name}
        if self.create:
            key = self.query_one("#channel-kind", Select).value
            value = self.query_one("#channel-source", Input).value.strip()
            result[key] = [v.strip() for v in value.split("|") if v.strip()] if key in ("shows", "items") else value
        self.dismiss(result)


class ChannelPicker(Dialog):
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title, rows):
        super().__init__(); self.title_, self.rows = title, rows

    def compose(self):
        options = [("New channel…", "new")]
        for row in self.rows:
            if row['kind'] == 'picked':
                if CH.membership(self.title_, [row]):
                    options.append(("Already in " + row['name'] + " — remove", f"remove:{row['number']}"))
                else:
                    options.append(("Add to " + row['name'], f"add:{row['number']}"))
        with Vertical(id="channel-box"):
            yield Label("Add to channel… / Remove from channel…")
            label = self.title_.split(':',2)[-1] if self.title_.startswith('music:') else self.title_
            yield Label(label)
            names = [row['name'] for row in CH.membership(self.title_, self.rows)]
            yield Label("Channels: " + (", ".join(names) or "none"), id="channel-membership", markup=False)
            yield Select(options, value=options[0][1], allow_blank=False, id="channel-pick")
            if any(r['kind'] == 'library' for r in self.rows):
                yield Label("Library channels already include everything in their library.")
            with Horizontal():
                yield Button("Cancel", id="channel-cancel")
                yield Button("Apply channel choice", id="channel-use", variant="primary")

    @on(Button.Pressed, "#channel-use")
    def choose(self): self.dismiss(self.query_one("#channel-pick", Select).value)

    @on(Button.Pressed, "#channel-cancel")
    def cancel(self): self.dismiss(None)


# ------------------------------------------------------------------ the app
class MediaApp(UXApp):
    TITLE = "MEDIA"
    HELP = (
        ("Library", "1 TV · 2 Movies · 3 Music · / filter · s sort\n"
         "m toggle monitoring · n new episodes · P quality profile · f search indexers\n"
         "e episode files · D review deletion · o Jellyfin · O request service"),
        ("Playback and channels", "p play on a den TV · t full-screen playback · c add/remove channel membership\n"
         "8 Channels · Ctrl+N new · F2 rename · v order · b bumpers · x remove item\n"
         "Channels: c tunes a TV · Alt+↑/↓ reorder · Ctrl+Z undo channel edits"),
        ("Find and download", "4 YouTube · 5 Downloads · 6 Upcoming · 7 / a / Ctrl+F Search\n"
         "Search finds titles outside your library. Enter on a result reviews its request."),
    )
    CSS = """
    Screen { background: $background; }
    #tabs { height: 1fr; min-height: 0; }
    #top { height: 1; padding: 0 1; background: $panel; color: $foreground; }
    .list { width: 3fr; }
    .side { width: 2fr; border-left: solid $panel; }
    MediaTable { border: solid $panel; }
    MediaTable:focus { border: solid $primary; }
    .detail { height: auto; max-height: 14; padding: 0 1; }
    .filter { display: none; }
    .filter.-on { display: block; }
    HintTable { height: 1fr; }
    #search-q { width: 1fr; }
    #search-kind { width: 22; }
    #search-go { margin: 1 0 0 1; }
    #search-status { height: 2; padding: 0 1; color: $text-muted; }
    #nav { height: 2; color: $text-muted; }
    #hint { height: 2; padding: 0 1; color: $text-muted; border-top: solid $panel; }
    #title-actions { height: 3; padding: 0 1; }
    .channel-actions { height: 3; }
    .channel-actions Button { width: 1fr; min-width: 10; }
    #title-actions Static { width: 1fr; padding: 1 1; color: $text-muted; }
    .title { text-style: bold; color: $primary; }
    .dim { color: $text-muted; }
    #channel-box { width: 90%; max-width: 80; max-height: 90%; overflow-y: auto; height: auto; padding: 1 2; border: solid $primary; background: $surface; }
    Confirm, PickProfile, Request, ChannelForm, ChannelPicker, Tune { align: center middle; }
    #delbox, #profbox, #reqbox { width: 90%; max-width: 90; max-height: 90%; overflow-y: auto; height: auto; padding: 1 2; border: solid $primary; background: $surface; }
    #delbox { border: solid $error; }
    #reqbox RichLog { height: 6; }
    #reqbox Select, #reqbox Input, #reqbox Checkbox { margin: 0; }
    #reqbox Button { width: 1fr; min-width: 0; margin: 0; }
    #reqbox Checkbox { width: 1fr; }
    #delbox Horizontal, #profbox Horizontal, #reqbox Horizontal { height: auto; margin-top: 1; }
    Select, Input, Checkbox { margin: 1 0 0 0; }
    """
    BINDINGS = [
        Binding("question_mark", "help", "Help"),
        Binding("q", "leave", "Quit", priority=True, show=False),
        Binding("ctrl+c", "interrupt", "Quit", priority=True, tooltip="Leave the media app"),
        Binding("down,j", "content", "Content", priority=True),
        Binding("h", "tab_bar(-1)", "Previous tab", priority=True, show=False),
        Binding("l", "tab_bar(1)", "Next tab", priority=True, show=False),
        Binding("r", "refresh", "Refresh", tooltip="Read the library again"),
        Binding("1", "tab('tv')", "TV", show=False, tooltip="Shows in Sonarr"),
        Binding("2", "tab('movies')", "Movies", show=False, tooltip="Films in Radarr"),
        Binding("3", "tab('music')", "Music", show=False, tooltip="Artists and albums in Lidarr"),
        Binding("4", "tab('youtube')", "YouTube", show=False, tooltip="Pinchflat's channels and playlists"),
        Binding("5", "tab('downloads')", "Downloads", show=False, tooltip="What's downloading, and why it's stuck"),
        Binding("6", "tab('upcoming')", "Upcoming", show=False, tooltip="What you track and when it comes out"),
        Binding("7,a,ctrl+f", "tab('search')", "Search", tooltip="Find something and request it (as bromigos lab media get)"),
        Binding("8", "tab('channels')", "Channels", show=False),
        Binding("c", "channel_picker", "Add to channel…"),
        Binding("ctrl+n", "channel_new", "New channel", show=False),
        Binding("f2", "channel_rename", "Rename channel", show=False),
        Binding("b", "channel_bumpers", "Bumpers", show=False),
        Binding("v", "channel_order", "Order", show=False),
        Binding("x", "channel_remove_item", "Remove item", show=False),
        Binding("alt+up", "channel_move(-1)", "Move up", show=False),
        Binding("alt+down", "channel_move(1)", "Move down", show=False),
        Binding("ctrl+z", "channel_undo", "Undo", show=False),
        Binding("slash", "filter", "Filter", tooltip="Show only the titles matching what you type"),
        Binding("s", "sort", "Sort", tooltip="Sort by added, size, name, missing or profile"),
        Binding("m", "monitor", "Monitor", tooltip="Monitor or stop monitoring the title, season or album under the cursor"),
        Binding("n", "new_items", "New eps", tooltip="Pick up new episodes and seasons, or stop (TV, music)", show=False),
        Binding("P", "profile", "Profile", tooltip="Change the quality profile", show=False),
        Binding("f", "search_now", "Search now", tooltip="Ask the indexers for it now", show=False),
        Binding("o", "open('jellyfin')", "Open", tooltip="Open it in Jellyfin (O: in Seerr)", show=False),
        Binding("O", "open('seerr')", "Seerr", show=False, tooltip="Open it in Seerr"),
        Binding("p", "den_play", "Den TV", tooltip="Play the selected title on a den TV screen", show=False),
        Binding("t", "play", "Play", tooltip="Play it full screen (a show: its next unwatched episode), from Jellyfin", show=False),
        Binding("e", "episodes", "Episodes", show=False, tooltip="Show the season's episode files (TV)"),
        Binding("D", "delete", "Delete", tooltip="Review what goes, then choose Delete or Cancel"),
        Binding("],L", "tab_step(1)", "Next tab", priority=True, show=False),
        Binding("[,H", "tab_step(-1)", "Previous tab", priority=True, show=False),
    ]
    TABS = ("tv", "movies", "music", "youtube", "downloads", "upcoming", "search", "channels")
    KIND = {"tv": "tv", "movies": "movies", "music": "music"}

    def __init__(self, source=None, start="tv"):
        super().__init__()
        self.src = source or Live()
        self.start = start
        self.channel_focus = None
        self.recs = {"tv": [], "movies": [], "music": []}
        self.shown = {"tv": [], "movies": [], "music": []}
        self.subrows = {"tv": [], "movies": [], "music": []}
        self.sub_mode = {"tv": "seasons", "movies": None, "music": "albums"}
        self.sort = {"tv": "added", "movies": "added", "music": "added"}
        self.filter = {"tv": "", "movies": "", "music": ""}
        self.found = []
        self._season = None
        self.channel_store = CH.Store()
        self.channel_rows = []
        self.youtube_rows = []
        self.upcoming_rows = []
        self.download_rows = []

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Static("MEDIA · reading the library…", id="top")
        with TabbedContent(initial=self.start, id="tabs"):
            for tid, name in (("tv", "TV"), ("movies", "MOVIES"), ("music", "MUSIC")):
                with TabPane(name, id=tid):
                    with Horizontal():
                        with Vertical(classes="list"):
                            f = MediaInput(placeholder="filter: type part of a title, Enter to keep, Escape to clear",
                                      id=f"{tid}-filter", classes="filter")
                            f.tooltip = "Only titles containing this"
                            yield f
                            yield MediaTable(id=f"{tid}-list", cursor_type="row", zebra_stripes=True)
                        with Vertical(classes="side"):
                            yield Static("", id=f"{tid}-detail", classes="detail")
                            yield MediaTable(id=f"{tid}-sub", cursor_type="row", zebra_stripes=True)
            with TabPane("YOUTUBE", id="youtube"):
                yield MediaTable(id="yt-list", cursor_type="row", zebra_stripes=True)
            with TabPane("DOWNLOADS", id="downloads"):
                with Vertical():
                    yield Static("", id="dl-sum", classes="dim")
                    yield MediaTable(id="dl-list", cursor_type="row", zebra_stripes=True)
            with TabPane("UPCOMING", id="upcoming"):
                yield MediaTable(id="up-list", cursor_type="row", zebra_stripes=True)
            with TabPane("SEARCH", id="search"):
                with Vertical():
                    with Horizontal(classes="detail"):
                        i = MediaInput(placeholder="a film, show, anime, artist or album, or a YouTube link", id="search-q")
                        i.tooltip = "What to look for; Enter searches"
                        yield i
                        s = Select([("Films and TV", ""), ("Films", "movie"), ("TV", "tv"), ("Anime", "anime"),
                                    ("Music", "music")], value="", id="search-kind", allow_blank=False)
                        s.tooltip = "Narrow the search"
                        yield s
                        yield Button("Search", id="search-go", variant="primary")
                    yield Static("Find media you don’t have yet. Type a title, then press Enter or Search.",
                                 id="search-status", markup=False)
                    yield MediaTable(id="search-list", cursor_type="row", zebra_stripes=True)
            with TabPane("CHANNELS", id="channels"):
                with Horizontal():
                    yield MediaTable(id="ch-list", cursor_type="row", zebra_stripes=True, classes="list")
                    with Vertical(classes="side"):
                        yield Static("", id="ch-detail", classes="detail")
                        yield MediaTable(id="ch-items", cursor_type="row")
                with Vertical(classes="detail"):
                    for actions in ((("New channel", "new"), ("Rename", "rename"), ("Order", "order"), ("Bumpers", "bumpers")),
                                    (("Remove item", "remove-item"), ("Delete channel", "delete"), ("Undo", "undo"), ("Tune TV", "tune"))):
                        with Horizontal(classes="channel-actions"):
                            for label, ident in actions:
                                yield Button(label, id="ch-" + ident)
        with Horizontal(id="title-actions"):
            yield Button("Add to channel… (c)", id="title-channel", tooltip="Choose a channel for the selected title")
            yield Static("Select a title to see its channels. Use c or the button to change them.",
                         id="title-membership", markup=False)
        yield Static("", id="hint")
        yield Static("↑/↓ j/k move · ←/→ h/l switch pane · Tab next control · Enter open\n"
                     "[/] previous/next tab · / filter · ? help · Esc cancel · q quit outside text fields", id="nav", markup=False)
        yield Footer()

    def on_mount(self):
        self.register_theme(bromigos_theme())
        self.theme = "bromigos"
        for tid, hint in (("tv", "Shows in Sonarr: seasons, size, profile, monitoring"), ("movies", "Films in Radarr"),
                          ("music", "Artists and albums in Lidarr"), ("youtube", "Pinchflat's channels and playlists"),
                          ("downloads", "What the download clients are fetching"),
                          ("upcoming", "What you track and when it comes out"), ("search", "Find and request")):
            try:
                self.query_one(f"#tabs Tab#--content-tab-{tid}").tooltip = hint
            except Exception:
                pass
        self.action_refresh()
        self.set_interval(5.0, self.load_downloads)
        self.set_interval(5.0, self.poll_channels)

    def on_descendant_focus(self, event: events.DescendantFocus):
        if isinstance(event.widget, HintTable) and not isinstance(self.screen, ModalScreen):
            self.channel_focus = event.widget
            self.update_membership(event.widget, event.widget.cursor_row)

    def channel_title(self, table, index):
        tid = table.id or ""
        if tid.endswith("-list") and tid.split("-")[0] in self.shown:
            records = self.shown[tid.split("-")[0]]
        elif tid == "music-sub":
            records = self.subrows["music"]
            return "music:album:" + records[index]["title"] if 0 <= index < len(records) else None
        elif tid == "tv-sub":
            return (self.current("tv")[1] or {}).get("title")
        else:
            records = {"search-list": self.found, "up-list": self.upcoming_rows,
                       "dl-list": self.download_rows, "yt-list": self.youtube_rows}.get(tid, [])
        if not 0 <= index < len(records):
            return None
        record = records[index]
        return (record.get("original_url") or record.get("url")) if tid == "yt-list" else record.get("title")

    def channel_hint(self, table, index, hint):
        title = self.channel_title(table, index)
        if not title:
            return hint
        names = [row["name"] for row in CH.membership(title, self.channel_rows)]
        return hint + " · Channels: " + (", ".join(names) or "none")

    def update_membership(self, table, index):
        title = self.channel_title(table, index)
        names = [row["name"] for row in CH.membership(title, self.channel_rows)] if title else []
        self.query_one("#title-membership", Static).update(
            "Channels: " + (", ".join(names) or "none") + " · c to add or remove"
            if title else "Select a title to see its channels. Use c or the button to change them.")

    @on(TabbedContent.TabActivated, "#tabs")
    def title_actions(self, event):
        self.bind("c", "channel_picker", description="Tune TV" if event.pane.id == "channels" else "Add to channel…")
        self.refresh_bindings()
        try:
            self.query_one("#title-actions").display = event.pane.id != "channels"
            if event.pane.id != "channels":
                table = event.pane.query_one(MediaTable)
                self.update_membership(table, table.cursor_row)
        except NoMatches:
            pass

    @on(Button.Pressed, "#title-channel")
    def title_channel(self):
        # Clicking the button must retain the selected album in a side table.
        table = self.channel_focus
        pane = next((w for w in table.ancestors if isinstance(w, TabPane)), None) if table else None
        if pane and pane.id == self.query_one("#tabs", TabbedContent).active:
            self.set_focus(table)
        self.action_channel_picker()

    # ------------------------------------------------------------------ loading
    def action_refresh(self):
        self.load_channels()
        self.load_totals()
        for k in ("tv", "movies", "music"):
            self.load_library(k)
        self.load_downloads()
        self.load_upcoming()
        self.load_youtube()

    @work(thread=True, group="totals")
    def load_totals(self):
        try:
            t = self.src.totals()
        except Exception as e:                       # noqa: BLE001
            t = {"error": str(e)}
        self.call_from_thread(self.show_totals, t)

    def show_totals(self, t):
        bits = []
        for k, one, many in (("tv", "show", "shows"), ("movies", "film", "films"), ("music", "artist", "artists")):
            if k in t:
                n = t[k]["count"]
                bits.append(f"{n} {one if n == 1 else many} {M.human(t[k]['size'])}")
        free = f" · {M.human(t['free'])} free" if t.get("free") else ""
        self.query_one("#top", Static).update("MEDIA · " + (" · ".join(bits) or t.get("error", "")) + free)

    @work(thread=True, group="library")
    def load_library(self, kind):
        try:
            recs = self.src.library(kind)
        except Exception as e:                       # noqa: BLE001
            self.call_from_thread(self.notify, f"{kind}: {e}", severity="error")
            recs = []
        self.call_from_thread(self.show_library, kind, recs)

    def show_library(self, kind, recs):
        self.recs[kind] = recs
        f = self.filter[kind].lower()
        rows = [r for r in recs if not f or f in (r["title"] or "").lower()]
        key = self.sort[kind]
        sorter = {"added": lambda r: r.get("added") or "", "size": lambda r: r.get("size") or 0,
                  "name": lambda r: (r["title"] or "").lower(), "missing": lambda r: r.get("missing") or 0,
                  "profile": lambda r: r.get("profile") or ""}[key]
        rows.sort(key=sorter, reverse=key in ("added", "size", "missing"))
        self.shown[kind] = rows
        t = self.query_one(f"#{kind}-list", HintTable)
        if kind == "tv":
            cols = ("", "title", "year", "seasons", "on disk", "size", "profile", "new eps")
            data = [(GLYPH["tv"], r["title"], r.get("year") or "", len([z for z in r["seasons"] if z["season"]]),
                     f"{r['files']}/{r['episodes']}", M.human(r["size"]), r["profile"], "yes" if r["new_items"] else "no")
                    for r in rows]
        elif kind == "movies":
            cols = ("", "title", "year", "on disk", "size", "quality", "profile", "release")
            data = [(GLYPH["movie"], r["title"], r.get("year") or "", "yes" if r["has_file"] else "no",
                     M.human(r["size"]), r.get("quality") or "-", r["profile"], r.get("release") or "") for r in rows]
        else:
            cols = ("", "artist", "albums", "tracks", "size", "profile", "new")
            data = [(GLYPH["artist"], r["title"], r["albums"], f"{r['tracks']}/{r['of']}", M.human(r["size"]),
                     r["profile"], "yes" if r.get("new_items") else "no") for r in rows]
        data = [(str(row[0]) + (" ◇" if CH.membership(r['title'], self.channel_rows) else ""), *row[1:])
                for row, r in zip(data, rows)]
        data = [tuple(_short(c) for c in row) for row in data]
        hints = [self._hint(kind, r) for r in rows]
        t.fill(cols, data, hints, f"Sorted by {key} (s to change); Enter or l: its seasons, albums or files")
        if rows:
            self.select(kind, t.cursor_row)

    def _hint(self, kind, r):
        mon = "monitored" if r.get("monitored") else "NOT monitored"
        if kind == "tv":
            return (f"{r['title']} ({r.get('year')}): {r['files']} of {r['episodes']} episodes on disk, "
                    f"{M.human(r['size'])}, {r['profile']}, {mon}, new episodes "
                    f"{'picked up' if r['new_items'] else 'not picked up'}"
                    + (f", {r['missing']} missing" if r.get("missing") else ""))
        if kind == "movies":
            return (f"{r['title']} ({r.get('year')}): " + ("on disk" if r["has_file"] else "not on disk") +
                    f", {M.human(r['size'])}, {r['profile']}, {mon}" +
                    (f", audio {'+'.join(M.lang_name(a) for a in r['audio'])}" if r.get("audio") else "") +
                    (f", {r['release']}" if r.get("release") and r["release"] != "released" else ""))
        return f"{r['title']}: {r['albums']} albums, {r['tracks']} of {r['of']} tracks, {M.human(r['size'])}, {mon}"

    def current(self, kind=None):
        kind = kind or self.query_one("#tabs", TabbedContent).active
        if kind not in self.shown:
            return kind, None
        t = self.query_one(f"#{kind}-list", HintTable)
        rows = self.shown[kind]
        return kind, (rows[t.cursor_row] if rows and 0 <= t.cursor_row < len(rows) else None)

    @on(HintTable.RowHighlighted)
    def _highlight(self, ev):
        if ev.data_table.id == "ch-list":
            self.show_channel(ev.cursor_row)
        tid = ev.data_table.id or ""
        if tid.endswith("-list") and tid.split("-")[0] in self.shown:
            self.select(tid.split("-")[0], ev.cursor_row)
        pane = next((w for w in ev.data_table.ancestors if isinstance(w, TabPane)), None)
        if pane and pane.id == self.query_one("#tabs", TabbedContent).active:
            self.query_one("#hint", Static).update(ev.data_table.tooltip or "")
            if self.focused is ev.data_table or self.channel_focus is ev.data_table:
                self.update_membership(ev.data_table, ev.cursor_row)

    @on(HintTable.RowSelected)
    def _enter(self, ev):
        if ev.data_table.id == "ch-list":
            self.query_one("#ch-items", HintTable).focus()
            return
        tid = ev.data_table.id or ""
        if tid.endswith("-list") and tid.split("-")[0] in self.shown:
            self.query_one(f"#{tid.split('-')[0]}-sub", HintTable).focus()
        elif tid == "search-list" and 0 <= ev.cursor_row < len(self.found):
            self.push_screen(Request(self.src, self.found[ev.cursor_row]), self._requested)

    def select(self, kind, row):
        rows = self.shown[kind]
        if not (0 <= row < len(rows)):
            return
        r = rows[row]
        self.query_one(f"#{kind}-detail", Static).update(self._detail_text(kind, r))
        self.sub_mode[kind] = {"tv": "seasons", "music": "albums"}.get(kind)
        self.load_sub(kind, r)

    def _detail_text(self, kind, r):
        lines = [f"{GLYPH.get(r['kind'], '·')}  {r['title']}" + (f" ({r['year']})" if r.get("year") else ""),
                 f"Profile {r['profile']} · {M.human(r['size'])} on disk · "
                 + ("monitored" if r.get("monitored") else "not monitored")]
        if kind == "tv":
            lines.append(("New episodes and seasons are picked up" if r["new_items"] else
                          "New episodes are not picked up") + (f" · {r['missing']} missing" if r.get("missing") else ""))
        if kind == "movies":
            lines.append(r.get("release") or "")
            if r.get("audio"):
                lines.append("Audio " + "+".join(M.lang_name(a) for a in r["audio"]))
        return "\n".join(x for x in lines if x)

    def load_sub(self, kind, r):
        """The side table (seasons, files, albums), one worker group per tab: a newer selection in
        a tab replaces its own older read, never another tab's."""
        self.run_worker(lambda: self._read_sub(kind, r), thread=True, group=f"sub-{kind}", exclusive=True)

    def _read_sub(self, kind, r):
        try:
            if kind == "tv" and self.sub_mode["tv"] == "files":
                rows = self.src.episode_files(r, self._season)
            elif kind == "tv":
                rows = self.src.seasons(r)
            elif kind == "music":
                rows = self.src.albums(r)
            else:
                rows = []
        except Exception as e:                       # noqa: BLE001
            rows = []
            self.call_from_thread(self.notify, str(e), severity="error")
        self.call_from_thread(self.show_sub, kind, r, rows)

    def show_sub(self, kind, r, rows):
        self.subrows[kind] = rows
        t = self.query_one(f"#{kind}-sub", HintTable)
        if kind == "tv" and self.sub_mode["tv"] == "files":
            t.fill(("episode", "size", "quality", "audio", "subs"),
                   [(f["code"], M.human(f["size"]), f["quality"] or "-", "+".join(f["audio"]) or "-",
                     "+".join(f["subtitles"]) or "-") for f in rows],
                   [f"{f['code']} {f.get('title') or ''}: {f.get('path')}" + (" · below the profile's target"
                                                                               if f["below_target"] else "")
                    for f in rows], "Episode files: D deletes the one under the cursor; Escape or e: back to seasons")
        elif kind == "tv":
            t.fill(("season", "monitored", "on disk", "size"),
                   [("Specials" if z["season"] == 0 else f"Season {z['season']}", "yes" if z["monitored"] else "no",
                     f"{z['files']}/{z['aired']}", M.human(z.get("size"))) for z in rows],
                   [f"{'Specials' if z['season'] == 0 else 'Season ' + str(z['season'])}: {z['files']} of {z['aired']} "
                    f"aired episodes on disk ({z['episodes']} in all). m monitors or stops it; e lists its files; "
                    "D deletes its files" for z in rows], "Seasons")
        elif kind == "music":
            t.fill(("album", "year", "tracks", "format", "size", "monitored"),
                   [(a["title"] + (" ◇" if CH.membership("music:album:" + a["title"], self.channel_rows) else ""), a.get("year") or "", f"{a['tracks']}/{a['of']}", a["format"], M.human(a["size"]),
                     "yes" if a["monitored"] else "no") for a in rows],
                   [f"{a['title']} ({a.get('type')}): {a['tracks']} of {a['of']} tracks, {a['format']}. m monitors "
                    "or stops it; D deletes it" for a in rows], "Albums")
        else:
            t.fill(("",), [], [], "")

    # ------------------------------------------------------------------ the other tabs
    @work(thread=True, group="downloads", exclusive=True)
    def load_downloads(self):
        try:
            d = self.src.downloads()
        except Exception as e:                       # noqa: BLE001
            d = {"downloads": [], "errors": [str(e)]}
        self.call_from_thread(self.show_downloads, d)

    def show_downloads(self, d):
        gs = d.get("downloads") or []
        self.download_rows = gs
        t = self.query_one("#dl-list", HintTable)
        t.fill(("title", "items", "status", "progress", "speed", "left", "audio"),
               [(g["title"] + (" ◇" if CH.membership(g["title"], self.channel_rows) else ""), g["items"], ", ".join(f"{n} {k}" for k, n in g["states"].items()),
                 "?" if g["progress"] is None else f"{g['progress']:.0f}%",
                 f"{M.human(g['speed'])}/s" if g.get("speed") else "-", M.hm(g["eta_s"]) if g.get("eta_s") else "-",
                 "+".join(g["audio"]) or "-") for g in gs],
               ["; ".join(g["why"][:2]) or f"{g['title']}: {g['items']} item(s)" for g in gs],
               "What Sonarr, Radarr and Lidarr are downloading, with the clients' own progress")
        extra = [f"{len(d.get('requests') or [])} requested in Seerr"] if d.get("requests") else []
        if d.get("subtitle_warning"):
            extra.append(d["subtitle_warning"])
        self.query_one("#dl-sum", Static).update(f"{len(gs)} downloading" + "".join(f" · {x}" for x in extra)
                                                 + "".join(f" · couldn't read: {e}" for e in d.get("errors") or []))

    @work(thread=True, group="upcoming")
    def load_upcoming(self):
        try:
            rows = self.src.upcoming()
        except Exception:                            # noqa: BLE001
            rows = []
        self.call_from_thread(self.show_upcoming, rows)

    def show_upcoming(self, rows):
        self.upcoming_rows = rows
        self.query_one("#up-list", HintTable).fill(
            ("date", "title", "what", "", "on disk"),
            [(r["date"], r["title"] + (" ◇" if CH.membership(r["title"], self.channel_rows) else ""), r["what"], r.get("name") or "", "yes" if r.get("has_file") else "") for r in rows],
            [f"{r['title']} {r['what']} {r.get('name') or ''} on {r['date']}" for r in rows],
            "New episodes and films' cinema, digital and disc dates, from Sonarr's and Radarr's calendars")

    @work(thread=True, group="youtube")
    def load_youtube(self):
        try:
            rows = self.src.youtube()
        except Exception:                            # noqa: BLE001
            rows = []
        self.call_from_thread(self.show_youtube, rows)

    def show_youtube(self, rows):
        self.youtube_rows = rows
        if not rows:
            self.query_one("#yt-list", HintTable).fill(
                ("",), [("No channels or playlists yet: bromigos lab youtube add URL, or paste a link in SEARCH",)], [],
                "Pinchflat downloads YouTube channels and playlists into your library")
            return
        self.query_one("#yt-list", HintTable).fill(
            ("", "name", "kind", "quality", "videos", "waiting", "newest"),
            [(GLYPH["youtube"] + (" ◇" if CH.membership(r.get("url"), self.channel_rows) else ""), r["name"], r.get("kind") or "?", r.get("quality") or "?", r.get("downloaded") or 0,
              r.get("pending") or 0, (r.get("newest") or "-")[:40]) for r in rows],
            [f"{r['name']}: {'paused' if not r.get('enabled', True) else 'checking daily'}; "
             "bromigos lab youtube remove|pause|quality changes it" for r in rows],
            "Pinchflat's channels and playlists (bromigos lab youtube)")

    # ------------------------------------------------------------------ search
    @on(Input.Submitted, "#search-q")
    def _search(self, ev):
        self.search_titles()

    @on(Button.Pressed, "#search-go")
    def search_button(self):
        self.search_titles()

    def search_titles(self):
        q = self.query_one("#search-q", Input).value.strip()
        if not q:
            self.query_one("#search-status", Static).update("Enter a title to search for.")
            self.query_one("#search-q", Input).focus()
            return
        self.query_one("#search-status", Static).update("Searching…")
        self.run_search(q, self.query_one("#search-kind", Select).value)

    @work(thread=True, group="search", exclusive=True)
    def run_search(self, q, kind):
        try:
            found = self.src.search(q, kind)
        except Exception as e:                       # noqa: BLE001
            found = []
            self.call_from_thread(self.notify, str(e), severity="error")
        self.call_from_thread(self.show_found, found)

    def show_found(self, found, focus=True):
        self.found = found
        self.query_one("#search-status", Static).update(
            f"Results: {len(found)} · Enter a result to request it · Have it shows what’s already in your library"
            if found else "No results. Try another title or media type.")
        t = self.query_one("#search-list", HintTable)
        t.fill(("", "title", "year", "kind", "release", "profile", "size", "have it"),
               [(GLYPH.get(i["kind"], "·") + (" ◇" if CH.membership(i.get("title"), self.channel_rows) else ""), i.get("title") or "", i.get("year") or "",
                 ("anime " if i.get("anime") else "") + i["kind"], i.get("release") or "",
                 (i.get("profile") or {}).get("name") or "-", M.human(i.get("size")) if i.get("size") else "-",
                 ", ".join(list((i.get("library") or {})) + ([i["arr"]["app"]] if i.get("arr") else [])) or "-")
                for i in found],
               [M.summary(i) for i in found], "Enter: request it (seasons, quality, audio)")
        if found and focus:
            t.focus()

    def _requested(self, res):
        if res:
            self.notify(" ".join(M.result_lines(res))[:300])
            self.action_refresh()

    # ------------------------------------------------------------------ actions on the selection
    def _target(self):
        """(kind, title record, what's under the cursor in the side table: season | album | file | None)."""
        kind, r = self.current()
        if r is None:
            return kind, None, None
        sub = self.query_one(f"#{kind}-sub", HintTable)
        if self.focused is sub and self.subrows[kind] and 0 <= sub.cursor_row < len(self.subrows[kind]):
            x = self.subrows[kind][sub.cursor_row]
            if kind == "tv" and self.sub_mode["tv"] == "files":
                return kind, r, ("file", x)
            if kind == "tv":
                return kind, r, ("season", x)
            if kind == "music":
                return kind, r, ("album", x)
        return kind, r, None

    def _do(self, fn, said):
        try:
            out = fn()
        except M.MediaError as e:
            self.notify(str(e), severity="error", timeout=8)
            return None
        self.notify(said(out) if callable(said) else said)
        return out

    def action_monitor(self):
        kind, r, sub = self._target()
        if r is None:
            return
        if sub and sub[0] == "season":
            z = sub[1]
            self._do(lambda: self.src.monitor(r, not z["monitored"], season=z["season"]), lambda s: f"{r['title']}: {s}")
        elif sub and sub[0] == "album":
            a = sub[1]
            self._do(lambda: self.src.monitor(r, not a["monitored"], album=a["id"]), lambda s: f"{a['title']}: {s}")
        else:
            self._do(lambda: self.src.monitor(r, not r.get("monitored")), lambda s: f"{r['title']}: {s}")
        self.load_library(kind)

    def action_new_items(self):
        kind, r, _ = self._target()
        if r is None or kind == "movies":
            return
        self._do(lambda: self.src.monitor(r, True, new_items=not r.get("new_items")), lambda s: f"{r['title']}: {s}")
        self.load_library(kind)

    def action_profile(self):
        kind, r, _ = self._target()
        if r is None:
            return
        opts = self.src.profiles(r["app"])

        def picked(pid):
            if pid is not None:
                self._do(lambda: self.src.set_profile(r, pid), lambda n: f"{r['title']} now uses {n}")
                self.load_library(kind)
        self.push_screen(PickProfile(r["title"], opts, r.get("profile_id")), picked)

    def action_search_now(self):
        kind, r, sub = self._target()
        if r is None:
            return
        season = sub[1]["season"] if sub and sub[0] == "season" else None
        album = sub[1]["id"] if sub and sub[0] == "album" else None
        self._do(lambda: self.src.search_now(r, season, album), lambda n: f"Searching for {r['title']} now ({n})")

    def action_open(self, where):
        kind, r, _ = self._target()
        if r is None:
            return
        url = self.src.link(r, where)
        if not url:
            self.notify(f"{r['title']} isn't in {where.title()}", severity="warning")
            return
        self.src.open(url)
        self.notify(f"Opening {r['title']} in {where.title()}")

    def action_den_play(self):
        from .tvplayui import PlayOnDen, TVP
        title, kind = "", "all"
        tab = self.query_one("#tabs", TabbedContent).active
        if tab in self.shown:
            _, r, sub = self._target()
            if r:
                title = r.get("title", "")
                kind = "shows" if tab == "tv" else ("movies" if tab == "movies" else "all")
                if sub and sub[0] == "file":
                    title = sub[1].get("code", "")
        elif tab == "youtube":
            kind = "youtube"
        def picked(req):
            if req:
                self._do(lambda: TVP.play(**req), lambda v: v.get("message", "Playing on den TV"))
        self.push_screen(PlayOnDen(title, kind), picked)

    def action_play(self):
        kind, r, _ = self._target()
        if r is not None:
            self._do(lambda: self.src.play(r), lambda t: f"Playing {t}")

    def action_episodes(self):
        kind, r, sub = self._target()
        if kind != "tv" or r is None:
            return
        if self.sub_mode["tv"] == "files":
            self.sub_mode["tv"] = "seasons"
        elif sub and sub[0] == "season":
            self.sub_mode["tv"], self._season = "files", sub[1]["season"]
        else:
            return
        self.load_sub("tv", r)

    def action_delete(self):
        if self.query_one("#tabs", TabbedContent).active == "channels":
            self.action_channel_delete()
            return
        kind, r, sub = self._target()
        if r is None:
            return
        season = sub[1]["season"] if sub and sub[0] == "season" else None
        files = [sub[1]["id"]] if sub and sub[0] == "file" else None
        album = sub[1]["id"] if sub and sub[0] == "album" else None
        try:
            plan = self.src.delete_plan(r, season, files, album)
        except M.MediaError as e:
            self.notify(str(e), severity="error")
            return

        def answered(ok):
            if not ok:
                self.notify("Nothing deleted.")
                return
            res = self._do(lambda: self.src.delete(r, season, files, album, ok.get("exclude")),
                           lambda x: f"Deleted {x['what']} ({M.human(x['size'])})"
                           + (", and removed from Seerr" if x.get("seerr") else ""))
            if res:
                self.action_refresh()
        self.push_screen(Confirm(plan), answered)

    # ------------------------------------------------------------------ filter, sort, tabs
    def action_filter(self):
        kind = self.query_one("#tabs", TabbedContent).active
        if kind not in self.shown:
            return
        f = self.query_one(f"#{kind}-filter", Input)
        f.add_class("-on")
        f.focus()

    @on(Input.Changed)
    def _filtering(self, ev):
        tid = ev.input.id or ""
        if tid.endswith("-filter"):
            kind = tid.split("-")[0]
            self.filter[kind] = ev.value
            self.show_library(kind, self.recs[kind])

    @on(Input.Submitted)
    def _filtered(self, ev):
        if (ev.input.id or "").endswith("-filter"):
            self.query_one(f"#{ev.input.id.split('-')[0]}-list", HintTable).focus()

    def key_escape(self):
        kind = self.query_one("#tabs", TabbedContent).active
        if kind == "tv" and self.sub_mode["tv"] == "files":
            self.action_episodes()
            return
        if kind in self.shown:
            f = self.query_one(f"#{kind}-filter", Input)
            if f.has_class("-on"):
                f.value = ""
                f.remove_class("-on")
                self.query_one(f"#{kind}-list", HintTable).focus()

    def action_sort(self):
        kind = self.query_one("#tabs", TabbedContent).active
        if kind in self.sort:
            self.sort[kind] = SORTS[(SORTS.index(self.sort[kind]) + 1) % len(SORTS)]
            self.show_library(kind, self.recs[kind])
            self.notify(f"Sorted by {self.sort[kind]}")

    def check_action(self, action, parameters):
        if super().check_action(action, parameters) is False:
            return False
        if action in ("content", "tab_bar"):
            return isinstance(self.focused, Tabs) and not isinstance(self.screen, ModalScreen)
        library_actions = ('monitor','new_items','profile','search_now','play','open','episodes','filter','sort')
        channel_actions = ('channel_rename','channel_order','channel_bumpers','channel_remove_item','channel_move','channel_tune')
        if action in library_actions + channel_actions + ('delete',):
            if isinstance(self.screen, ModalScreen): return False
            try: tab = self.query_one('#tabs',TabbedContent).active
            except NoMatches: return False
            if action in library_actions: return tab in self.shown
            if action in channel_actions: return tab == 'channels'
            return tab in self.shown or tab == 'channels'
        return True

    def action_interrupt(self):
        self.action_leave()

    def action_leave(self):
        if not isinstance(self.screen, ModalScreen):
            self.exit()

    def action_tab_bar(self, step):
        bar = self.query_one("#tabs Tabs", Tabs)
        if step > 0:
            bar.action_next_tab()
        else:
            bar.action_previous_tab()

    def action_content(self):
        tid = self.query_one("#tabs", TabbedContent).active
        target = {"youtube": "yt-list", "downloads": "dl-list", "upcoming": "up-list",
                  "search": "search-list", "channels": "ch-list"}.get(tid, f"{tid}-list")
        self.query_one(f"#{target}", HintTable).focus()

    def action_tab(self, tid):
        tid = "search" if tid == "add" else tid
        self.set_focus(None)
        self.query_one("#tabs", TabbedContent).active = tid
        self.call_after_refresh(self._focus_tab, tid)

    def _focus_tab(self, tid):
        if self.query_one("#tabs", TabbedContent).active != tid:
            return
        if tid == "search":
            self.query_one("#search-q", Input).focus()
        else:
            self.action_content()

    def action_tab_step(self, step):
        if isinstance(self.screen, ModalScreen):
            return
        cur = self.query_one("#tabs", TabbedContent).active
        self.action_tab(self.TABS[(self.TABS.index(cur) + step) % len(self.TABS)])

    def action_pane(self, step):
        if self.query_one("#tabs", TabbedContent).active == "channels":
            self.query_one("#ch-items" if step > 0 else "#ch-list", HintTable).focus()
            return
        kind = self.query_one("#tabs", TabbedContent).active
        if kind in self.shown:
            self.query_one(f"#{kind}-{'sub' if step > 0 else 'list'}", HintTable).focus()


    # ------------------------------------------------------------------ shared den TV channels
    @work(thread=True, group="channels", exclusive=True)
    def load_channels(self):
        try:
            doc = self.channel_store.snapshot(refresh=True)
            if not self._exit:
                self.call_from_thread(self.show_channels, self.channel_store.snapshot()['channels'])
        except (CH.ChannelError, ValueError, OSError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")

    @work(thread=True, group="channel-state", exclusive=True)
    def poll_channels(self):
        """Live screens and clock, from local cache; leave slow content fetches alone."""
        try:
            rows = self.channel_store.snapshot()['channels']
            if not self._exit: self.call_from_thread(self.show_channels, rows)
        except (CH.ChannelError, ValueError, OSError):
            pass

    def show_channels(self, rows):
        table = self.query_one('#ch-list', HintTable)
        old_index = table.cursor_row
        old_row = self.channel_rows[old_index] if 0 <= old_index < len(self.channel_rows) else None
        item_index = self.query_one('#ch-items', HintTable).cursor_row
        old_item = old_row['contents'][item_index]['value'] if old_row and 0 <= item_index < len(old_row['contents']) else None
        def members(data):
            return [(r['name'], [(c['kind'], c['value'], c['title']) for c in r['contents']]) for r in data]
        changed = members(rows) != members(self.channel_rows)
        self.channel_rows = rows
        table.fill(
            ("#", "Channel", "Kind", "Order", "Bumpers", "On now"),
            [(r['number'], r['name'], r['kind'], r['order'], "on" if r['bumpers'] else "off",
              ", ".join(r['on_screens']) or "-") for r in rows],
            [(r['now'] or "Nothing playing") + " → " + (r['next'] or "Nothing next") for r in rows],
            "Enter/l: contents · F2 rename · v order · b bumpers · Alt+↑/↓ reorder · D delete · Ctrl+Z undo")
        index = next((i for i,r in enumerate(rows) if old_row and r['key']==old_row['key']), min(old_index,max(0,len(rows)-1)))
        table.move_cursor(row=index)
        self.show_channel(index)
        if rows and old_item is not None:
            position = next((i for i,c in enumerate(rows[index]['contents']) if c['value']==old_item), None)
            if position is not None: self.query_one('#ch-items', HintTable).move_cursor(row=position)
        if changed:
            for kind, recs in self.recs.items(): self.show_library(kind, recs)
            self.show_upcoming(self.upcoming_rows)
            self.show_youtube(self.youtube_rows)
            self.show_found(self.found, focus=False)
            for media_table in self.query(MediaTable):
                media_table.refresh_membership()
            focused = self.channel_focus
            pane = next((w for w in focused.ancestors if isinstance(w, TabPane)), None) if focused else None
            if pane and pane.id == self.query_one("#tabs", TabbedContent).active:
                self.update_membership(focused, focused.cursor_row)

    def show_channel(self, index):
        row = self.channel_rows[index] if 0 <= index < len(self.channel_rows) else None
        self.query_one("#ch-detail", Static).update(
            (f"{row['name']}\nNow: {row['now'] or '-'}\nNext: {row['next'] or '-'}\n" +
             (row['error'] or "")) if row else "No channels yet. Ctrl+N adds one.")
        contents = row['contents'] if row else []
        self.query_one("#ch-items", HintTable).fill(("Title", "Kind"),
            [(c['title'], c.get('media_kind') or c['kind']) for c in contents], [c['title'] for c in contents],
            "x removes a pick · Alt+↑/↓ moves it. Library titles are included automatically.")

    def selected_channel(self):
        if self.query_one("#tabs", TabbedContent).active != "channels": return None
        index = self.query_one("#ch-list", HintTable).cursor_row
        return self.channel_rows[index] if 0 <= index < len(self.channel_rows) else None

    def channel_change(self, fn):
        try:
            result = fn()
            self.notify(result.get('message', 'Channel updated'))
            self.show_channels(self.channel_store.snapshot(live={})['channels'])
            self.load_channels()
        except (CH.ChannelError, ValueError, OSError) as e:
            self.notify(str(e), severity="error")

    def action_channel_picker(self):
        tid = self.query_one("#tabs", TabbedContent).active
        if tid == 'channels':
            self.action_channel_tune(); return
        title, kind = None, 'show'
        if tid in self.shown:
            _, record, sub = self._target()
            if record:
                title = record['title']; kind = 'show' if tid == 'tv' else 'movie' if tid == 'movies' else 'music'
                if tid == 'music':
                    title = 'music:' + ('album:' + sub[1]['title'] if sub and sub[0] == 'album'
                                      else 'artist:' + title)
        elif tid == 'youtube':
            index = self.query_one("#yt-list", HintTable).cursor_row
            if 0 <= index < len(self.youtube_rows):
                r = self.youtube_rows[index]; title = r.get('original_url') or r.get('url'); kind = 'youtube'
        elif tid in ('search','upcoming','downloads'):
            records, table = {'search': (self.found,'search-list'), 'upcoming': (self.upcoming_rows,'up-list'),
                              'downloads': (self.download_rows,'dl-list')}[tid]
            index = self.query_one('#'+table,HintTable).cursor_row
            if 0 <= index < len(records):
                record = records[index]; title = record.get('title')
                media_kind = record.get('kind') or {'sonarr':'tv','radarr':'movie','lidarr':'artist'}.get(record.get('app'))
                kind = 'show' if media_kind in ('tv','anime') else 'movie' if media_kind=='movie' else 'music'
                if kind=='music': title = 'music:' + ('album:' if media_kind=='album' else 'artist:') + title
        if not title:
            self.notify('Choose a title or YouTube source first'); return
        choices = list(self.channel_rows)
        def selected(choice):
            if choice == 'new':
                self.action_channel_new(title, kind)
            elif choice:
                verb, number = choice.split(':')
                row = next(r for r in choices if str(r['number']) == number)
                self.channel_change(lambda: self.channel_store.item(row['name'], title, remove=verb=='remove', item_kind=kind))
        self.push_screen(ChannelPicker(title, self.channel_rows), selected)

    def action_channel_new(self, title=None, kind='show'):
        def saved(data):
            if not data: return
            if title and not any(data.get(key) for key in ('library','youtube','folder')):
                key = 'shows' if kind=='show' else 'items'
                data[key] = list(data.get(key) or [])
                if title not in data[key]: data[key].append(title)
            self.channel_change(lambda: self.channel_store.create(**data))
        self.push_screen(ChannelForm(create=True), saved)

    def action_channel_rename(self):
        row = self.selected_channel()
        if row:
            self.push_screen(ChannelForm('Rename channel', row['name']),
                lambda data: self.channel_change(lambda: self.channel_store.set(row['name'], 'name', data['name'])) if data else None)

    def action_channel_order(self):
        row = self.selected_channel()
        if row:
            order = CH.ORDERS[(CH.ORDERS.index(row['order']) + 1) % len(CH.ORDERS)]
            self.channel_change(lambda: self.channel_store.set(row['name'], 'order', order))

    def action_channel_bumpers(self):
        row = self.selected_channel()
        if row: self.channel_change(lambda: self.channel_store.set(row['name'], 'bumpers', not row['bumpers']))

    def action_channel_move(self, step):
        row = self.selected_channel()
        if not row: return
        table = self.query_one("#ch-items", HintTable)
        if self.focused is table and row['kind']=='picked' and row['contents']:
            item = row['contents'][table.cursor_row]
            values = CH._list(row['table'].get(item['kind']+'s'))
            pos = values.index(item['value']) + 1 + step
            self.channel_change(lambda: self.channel_store.move_item(row['name'], item['value'], pos))
        else:
            self.channel_change(lambda: self.channel_store.move(row['name'], row['number'] + step))

    def action_channel_remove_item(self):
        row = self.selected_channel()
        if row and row['contents']:
            i = self.query_one("#ch-items", HintTable).cursor_row
            title = row['contents'][i]['value']
            self.channel_change(lambda: self.channel_store.item(row['name'], title, remove=True))

    def action_channel_delete(self):
        row = self.selected_channel()
        if not row: return
        plan = {'what': 'channel ' + row['name'], 'title': row['name'], 'size': 0, 'scope': 'channel'}
        self.push_screen(Confirm(plan), lambda ok: self.channel_change(lambda: self.channel_store.remove(row['name'])) if ok else None)

    def action_channel_undo(self): self.channel_change(self.channel_store.undo)

    def action_channel_tune(self):
        row = self.selected_channel()
        if not row: return
        class Tune(Dialog):
            BINDINGS = [Binding('escape', 'dismiss(None)', 'Cancel')]
            def compose(self):
                with Vertical(id='channel-box'):
                    yield Select([('Big monitor','big'),('Scope','wave'),('Small monitor','emblem')],
                                 value='big', allow_blank=False, id='channel-screen')
                    yield Label(f"Tune {row['name']} on…", markup=False)
                    with Horizontal():
                        yield Button('Cancel', id='channel-tune-cancel')
                        yield Button('Tune TV',id='channel-tune', variant='primary')
            @on(Button.Pressed, '#channel-tune-cancel')
            def cancel(self): self.dismiss(None)
            @on(Button.Pressed, '#channel-tune')
            def choose(self): self.dismiss(self.query_one('#channel-screen',Select).value)
        self.push_screen(Tune(), lambda screen: self.channel_change(lambda: self.channel_store.tune(row['name'],screen)) if screen else None)

    @on(Button.Pressed)
    def channel_button(self, event):
        if not (event.button.id or '').startswith('ch-'): return
        action = event.button.id[3:].replace('-', '_')
        getattr(self, 'action_channel_' + action)()


def main(argv=None):
    start = (argv or [None])[0] if argv else None
    start = "search" if start == "add" else start
    MediaApp(start=start if start in MediaApp.TABS else "tv").run()
    return 0
