"""`bromigos media` (and `bromigos lab media` with no subcommand, in a terminal): your media
library in a terminal UI (Textual), on the same code as `bromigos lab media` (mediareq.py).

Tabs: TV (Sonarr), MOVIES (Radarr), MUSIC (Lidarr), YOUTUBE (Pinchflat), DOWNLOADS (what the
download clients are fetching), UPCOMING (the calendar of what you track) and ADD (search
and request, as `media get`). The header has the library's totals and the free space.

On a selected title, season, album or episode file: m monitors or stops, n picks up new
episodes or not, p changes the quality profile, f searches now, o opens it in Jellyfin,
O in Seerr, t plays it full screen, D deletes it. A delete says exactly what goes and how
much space it frees, then needs the title typed, or D pressed a second time. / filters, s
sorts (added, size, name, missing, profile). Vim keys beside the arrows; every key, tab,
row and button has a hint.

The colours are the desktop theme's, like `bromigos lab`'s dashboard.
"""
import subprocess

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, Footer, Input, Label, RichLog, Select, Static, TabbedContent,
                             TabPane)

from . import mediareq as M
from .tui import HintTable, bromigos_theme

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


# ------------------------------------------------------------------ dialogs
class Confirm(ModalScreen):
    """Delete, in two steps: what goes and the space it frees; then type the title, or press D
    again. Escape cancels."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel", tooltip="Close without deleting anything"),
                Binding("D", "again", "Delete (press twice)", tooltip="Press D again to delete")]

    def __init__(self, plan):
        super().__init__()
        self.plan = plan

    def compose(self):
        p = self.plan
        with Vertical(id="delbox"):
            yield Label(f"Delete {p['what']}?", classes="title", id="del-what")
            yield Static(f"It frees {M.human(p['size'])}. The files go from the disk; Jellyfin and Plex rescan."
                         + ("" if p["scope"] != "season" else " The season stops being monitored, so it isn't "
                            "fetched again."), classes="dim")
            i = Input(placeholder=f"Type {p['title']} to delete it", id="del-name")
            i.tooltip = "Type the title exactly (any case), then Enter; or press D again"
            yield i
            c = Checkbox("Don't fetch it again (an import exclusion)", id="del-exclude",
                         value=False, disabled=p["scope"] not in ("title", "album"))
            c.tooltip = "Sonarr, Radarr or Lidarr won't add it again from a list"
            yield c
            with Horizontal():
                b = Button("Cancel", id="del-no")
                b.tooltip = "Keep it (Escape)"
                yield b
                b = Button("Delete", id="del-yes", variant="error", disabled=True)
                b.tooltip = "Enabled once the title is typed"
                yield b

    def on_mount(self):
        self.armed = False
        self.query_one("#del-name", Input).focus()

    @on(Input.Changed, "#del-name")
    def typed(self, ev):
        self.query_one("#del-yes", Button).disabled = M._norm_title(ev.value) != M._norm_title(self.plan["title"])

    @on(Input.Submitted, "#del-name")
    def entered(self, ev):
        if not self.query_one("#del-yes", Button).disabled:
            self.go()

    def action_again(self):
        if self.armed:
            self.go()
        else:
            self.armed = True
            self.query_one("#del-what", Label).update(f"Delete {self.plan['what']}? Press D once more to delete.")

    @on(Button.Pressed, "#del-no")
    def no(self):
        self.dismiss(None)

    @on(Button.Pressed, "#del-yes")
    def go(self):
        self.dismiss({"exclude": self.query_one("#del-exclude", Checkbox).value})


class PickProfile(ModalScreen):
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
                yield Button("Use it", id="prof-yes", variant="primary")

    @on(Button.Pressed, "#prof-no")
    def no(self):
        self.dismiss(None)

    @on(Button.Pressed, "#prof-yes")
    def yes(self):
        self.dismiss(self.query_one("#prof", Select).value)


class Request(ModalScreen):
    """`media get` as a form: seasons, quality, audio, new episodes; the plan, then Request."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel", tooltip="Close without requesting anything")]

    def __init__(self, src, item):
        super().__init__()
        self.src, self.item, self.plan = src, item, None

    def compose(self):
        it = self.item
        with Vertical(id="reqbox"):
            yield Label(M.summary(it), classes="title")
            if it["kind"] == "tv":
                s = Select([("All seasons", "all"), ("The latest season", "latest"), ("Only new episodes", "future")],
                           value="all", id="req-seasons", allow_blank=False)
                s.tooltip = "What to fetch now"
                yield s
                i = Input(placeholder="or seasons: 1,3 or 2-4 · or episodes: S02E05,S03E01", id="req-pick")
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
                b = Button("Plan", id="req-planbtn")
                b.tooltip = "Show what it would do: the profile and why, the size, the free space"
                yield b
                b = Button("Request", id="req-yes", variant="primary")
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

    @on(Button.Pressed, "#req-planbtn")
    def show_plan(self):
        log = self.query_one("#req-plan", RichLog)
        log.clear()
        try:
            self.plan = self.src.plan(self.item, **self._opts())
            for ln in M.plan_lines(self.plan):
                log.write(ln)
        except M.MediaError as e:
            log.write(f"Can't: {e}")

    @on(Button.Pressed, "#req-no")
    def no(self):
        self.dismiss(None)

    @on(Button.Pressed, "#req-yes")
    def yes(self):
        try:
            plan = self.src.plan(self.item, **self._opts())
            self.dismiss(self.src.request(plan))
        except M.MediaError as e:
            self.query_one("#req-plan", RichLog).write(f"Not requested: {e}")


# ------------------------------------------------------------------ the app
class MediaApp(App):
    TITLE = "MEDIA"
    CSS = """
    Screen { background: $background; }
    #top { height: 1; padding: 0 1; background: $panel; color: $foreground; }
    .list { width: 3fr; }
    .side { width: 2fr; border-left: solid $panel; }
    .detail { height: auto; max-height: 14; padding: 0 1; }
    .filter { display: none; }
    .filter.-on { display: block; }
    HintTable { height: 1fr; }
    #hint { height: 2; padding: 0 1; color: $text-muted; border-top: solid $panel; }
    .title { text-style: bold; color: $primary; }
    .dim { color: $text-muted; }
    Confirm, PickProfile, Request { align: center middle; }
    #delbox, #profbox, #reqbox { width: 90; height: auto; padding: 1 2; border: solid $primary; background: $surface; }
    #delbox { border: solid $error; }
    #reqbox RichLog { height: 10; }
    #delbox Horizontal, #profbox Horizontal, #reqbox Horizontal { height: auto; margin-top: 1; }
    Select, Input, Checkbox { margin: 1 0 0 0; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit", tooltip="Leave"),
        Binding("r", "refresh", "Refresh", tooltip="Read the library again"),
        Binding("1", "tab('tv')", "TV", show=False, tooltip="Shows in Sonarr"),
        Binding("2", "tab('movies')", "Movies", show=False, tooltip="Films in Radarr"),
        Binding("3", "tab('music')", "Music", show=False, tooltip="Artists and albums in Lidarr"),
        Binding("4", "tab('youtube')", "YouTube", show=False, tooltip="Pinchflat's channels and playlists"),
        Binding("5", "tab('downloads')", "Downloads", show=False, tooltip="What's downloading, and why it's stuck"),
        Binding("6", "tab('upcoming')", "Upcoming", show=False, tooltip="What you track and when it comes out"),
        Binding("7,a", "tab('add')", "Add", tooltip="Find something and request it (as bromigos lab media get)"),
        Binding("slash", "filter", "Filter", tooltip="Show only the titles matching what you type"),
        Binding("s", "sort", "Sort", tooltip="Sort by added, size, name, missing or profile"),
        Binding("m", "monitor", "Monitor", tooltip="Monitor or stop monitoring the title, season or album under the cursor"),
        Binding("n", "new_items", "New eps", tooltip="Pick up new episodes and seasons, or stop (TV, music)"),
        Binding("p", "profile", "Profile", tooltip="Change the quality profile"),
        Binding("f", "search_now", "Search now", tooltip="Ask the indexers for it now"),
        Binding("o", "open('jellyfin')", "Open", tooltip="Open it in Jellyfin (O: in Seerr)"),
        Binding("O", "open('seerr')", "Seerr", show=False, tooltip="Open it in Seerr"),
        Binding("t", "play", "Play", tooltip="Play it full screen (a show: its next unwatched episode), from Jellyfin"),
        Binding("e", "episodes", "Episodes", show=False, tooltip="Show the season's episode files (TV)"),
        Binding("D", "delete", "Delete", tooltip="Delete the title, season, album or file under the cursor (asks twice)"),
        Binding("],L", "tab_step(1)", "Next tab", show=False),
        Binding("[,H", "tab_step(-1)", "Previous tab", show=False),
    ]
    TABS = ("tv", "movies", "music", "youtube", "downloads", "upcoming", "add")
    KIND = {"tv": "tv", "movies": "movies", "music": "music"}

    def __init__(self, source=None, start="tv"):
        super().__init__()
        self.src = source or Live()
        self.start = start
        self.recs = {"tv": [], "movies": [], "music": []}
        self.shown = {"tv": [], "movies": [], "music": []}
        self.subrows = {"tv": [], "movies": [], "music": []}
        self.sub_mode = {"tv": "seasons", "movies": None, "music": "albums"}
        self.sort = {"tv": "added", "movies": "added", "music": "added"}
        self.filter = {"tv": "", "movies": "", "music": ""}
        self.found = []
        self._season = None

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Static("MEDIA · reading the library…", id="top")
        with TabbedContent(initial=self.start, id="tabs"):
            for tid, name in (("tv", "TV"), ("movies", "MOVIES"), ("music", "MUSIC")):
                with TabPane(name, id=tid):
                    with Horizontal():
                        with Vertical(classes="list"):
                            f = Input(placeholder="filter: type part of a title, Enter to keep, Escape to clear",
                                      id=f"{tid}-filter", classes="filter")
                            f.tooltip = "Only titles containing this"
                            yield f
                            yield HintTable(id=f"{tid}-list", cursor_type="row", zebra_stripes=True)
                        with Vertical(classes="side"):
                            yield Static("", id=f"{tid}-detail", classes="detail")
                            yield HintTable(id=f"{tid}-sub", cursor_type="row", zebra_stripes=True)
            with TabPane("YOUTUBE", id="youtube"):
                yield HintTable(id="yt-list", cursor_type="row", zebra_stripes=True)
            with TabPane("DOWNLOADS", id="downloads"):
                with Vertical():
                    yield Static("", id="dl-sum", classes="dim")
                    yield HintTable(id="dl-list", cursor_type="row", zebra_stripes=True)
            with TabPane("UPCOMING", id="upcoming"):
                yield HintTable(id="up-list", cursor_type="row", zebra_stripes=True)
            with TabPane("ADD", id="add"):
                with Vertical():
                    with Horizontal(classes="detail"):
                        i = Input(placeholder="a film, show, anime, artist or album, or a YouTube link", id="add-q")
                        i.tooltip = "What to look for; Enter searches"
                        yield i
                        s = Select([("Films and TV", ""), ("Films", "movie"), ("TV", "tv"), ("Anime", "anime"),
                                    ("Music", "music")], value="", id="add-kind", allow_blank=False)
                        s.tooltip = "Narrow the search"
                        yield s
                    yield HintTable(id="add-list", cursor_type="row", zebra_stripes=True)
        yield Static("", id="hint")
        yield Footer()

    def on_mount(self):
        self.register_theme(bromigos_theme())
        self.theme = "bromigos"
        for tid, hint in (("tv", "Shows in Sonarr: seasons, size, profile, monitoring"), ("movies", "Films in Radarr"),
                          ("music", "Artists and albums in Lidarr"), ("youtube", "Pinchflat's channels and playlists"),
                          ("downloads", "What the download clients are fetching"),
                          ("upcoming", "What you track and when it comes out"), ("add", "Find and request")):
            try:
                self.query_one(f"#tabs Tab#--content-tab-{tid}").tooltip = hint
            except Exception:
                pass
        self.action_refresh()
        self.set_interval(5.0, self.load_downloads)

    # ------------------------------------------------------------------ loading
    def action_refresh(self):
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
        tid = ev.data_table.id or ""
        if tid.endswith("-list") and tid.split("-")[0] in self.shown:
            self.select(tid.split("-")[0], ev.cursor_row)
        self.query_one("#hint", Static).update(ev.data_table.tooltip or "")

    @on(HintTable.RowSelected)
    def _enter(self, ev):
        tid = ev.data_table.id or ""
        if tid.endswith("-list") and tid.split("-")[0] in self.shown:
            self.query_one(f"#{tid.split('-')[0]}-sub", HintTable).focus()
        elif tid == "add-list" and 0 <= ev.cursor_row < len(self.found):
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
                   [(a["title"], a.get("year") or "", f"{a['tracks']}/{a['of']}", a["format"], M.human(a["size"]),
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
        t = self.query_one("#dl-list", HintTable)
        t.fill(("title", "items", "status", "progress", "speed", "left", "audio"),
               [(g["title"], g["items"], ", ".join(f"{n} {k}" for k, n in g["states"].items()),
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
        self.query_one("#up-list", HintTable).fill(
            ("date", "title", "what", "", "on disk"),
            [(r["date"], r["title"], r["what"], r.get("name") or "", "yes" if r.get("has_file") else "") for r in rows],
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
        if not rows:
            self.query_one("#yt-list", HintTable).fill(
                ("",), [("No channels or playlists yet: bromigos lab youtube add URL, or paste a link in ADD",)], [],
                "Pinchflat downloads YouTube channels and playlists into your library")
            return
        self.query_one("#yt-list", HintTable).fill(
            ("", "name", "kind", "quality", "videos", "waiting", "newest"),
            [(GLYPH["youtube"], r["name"], r.get("kind") or "?", r.get("quality") or "?", r.get("downloaded") or 0,
              r.get("pending") or 0, (r.get("newest") or "-")[:40]) for r in rows],
            [f"{r['name']}: {'paused' if not r.get('enabled', True) else 'checking daily'}; "
             "bromigos lab youtube remove|pause|quality changes it" for r in rows],
            "Pinchflat's channels and playlists (bromigos lab youtube)")

    # ------------------------------------------------------------------ add
    @on(Input.Submitted, "#add-q")
    def _search(self, ev):
        self.run_search(ev.value, self.query_one("#add-kind", Select).value)

    @work(thread=True, group="search", exclusive=True)
    def run_search(self, q, kind):
        try:
            found = self.src.search(q, kind)
        except Exception as e:                       # noqa: BLE001
            found = []
            self.call_from_thread(self.notify, str(e), severity="error")
        self.call_from_thread(self.show_found, found)

    def show_found(self, found):
        self.found = found
        t = self.query_one("#add-list", HintTable)
        t.fill(("", "title", "year", "kind", "release", "profile", "size", "have it"),
               [(GLYPH.get(i["kind"], "·"), i.get("title") or "", i.get("year") or "",
                 ("anime " if i.get("anime") else "") + i["kind"], i.get("release") or "",
                 (i.get("profile") or {}).get("name") or "-", M.human(i.get("size")) if i.get("size") else "-",
                 ", ".join(list((i.get("library") or {})) + ([i["arr"]["app"]] if i.get("arr") else [])) or "-")
                for i in found],
               [M.summary(i) for i in found], "Enter: request it (seasons, quality, audio)")
        if found:
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

    def action_tab(self, tid):
        self.query_one("#tabs", TabbedContent).active = tid
        target = {"youtube": "#yt-list", "downloads": "#dl-list", "upcoming": "#up-list", "add": "#add-q"}.get(
            tid, f"#{tid}-list")
        try:
            self.query_one(target).focus()
        except Exception:
            pass

    def action_tab_step(self, step):
        cur = self.query_one("#tabs", TabbedContent).active
        self.action_tab(self.TABS[(self.TABS.index(cur) + step) % len(self.TABS)])

    def action_pane(self, step):
        kind = self.query_one("#tabs", TabbedContent).active
        if kind in self.shown:
            self.query_one(f"#{kind}-{'sub' if step > 0 else 'list'}", HintTable).focus()


def main(argv=None):
    start = (argv or [None])[0] if argv else None
    MediaApp(start=start if start in MediaApp.TABS else "tv").run()
    return 0
