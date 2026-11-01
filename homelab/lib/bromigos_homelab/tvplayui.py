"""Textual's on-demand Den TV picker. All searches and playback use the shared library."""
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from .tvchannels import channels  # locate the packaged/shared library first
from .tui import HintTable
from .tuiux import Dialog
import bromigos_tvplay as TVP

try:                                        # STATIC, the den's host (lib/bromigos_static_term.py)
    import bromigos_static as STATIC_RIG
    import bromigos_static_term as STATIC
    if STATIC_RIG.mode() == "off":
        STATIC = None
except ImportError:
    STATIC = None


def _status(face, text):
    """The dialog's status line, with STATIC's face in front when he's on."""
    if STATIC is None:
        return text
    import os
    return f"{STATIC.glyph(face, os.environ.get('BROMIGOS_ICONS') == 'ascii')}  {text}"


class PlayTable(HintTable):
    BINDINGS = [Binding("enter,l,right", "screen.choose", "Choose"),
                Binding("h,left", "screen.back", "Back")]


class PlayOnDen(Dialog):
    AUTO_FOCUS = "#den-results"
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel"), Binding("enter,l", "choose", "Choose"),
                Binding("h", "back", "Back")]
    DEFAULT_CSS = """
    PlayOnDen { align: center middle; }
    #den-play-box { width: 86%; height: 88%; border: round $accent; background: $surface; padding: 1 2; }
    #den-play-box Horizontal { height: auto; }
    #den-play-box Button { width: 1fr; min-width: 0; margin-right: 0; }
    #den-play-box Select { width: 1fr; }
    #den-results { height: 1fr; min-height: 5; }
    #den-note { height: auto; }
    #den-head { height: auto; }
    #den-head Label { padding: 2 0 0 2; }
    """

    def __init__(self, title="", kind="all", screen="big"):
        super().__init__()
        self.title_, self.kind_, self.screen_ = title, kind, screen
        self.rows, self.parents = [], []
        self.scope = dict(kind=kind)
        self.serial = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="den-play-box"):
            with Horizontal(id="den-head"):
                if STATIC is not None and hasattr(STATIC, "Sprite"):
                    yield STATIC.Sprite("remote", face="snow", id="den-static",
                                        label="STATIC, remote in hand: tuning in while your library is read")
                yield Label("Play on den TV · pick a show, season and episode, or a movie", classes="title")
            with Horizontal():
                yield Select([(s.title(), s) for s in ("big", "scope", "small")], value=self.screen_, allow_blank=False, id="den-screen")
                yield Select([(s.title(), s) for s in ("all", "shows", "movies", "youtube")], value=self.kind_, allow_blank=False, id="den-kind")
            inp = Input(self.title_, placeholder="Title or YouTube video URL; Enter to search", id="den-search")
            inp.tooltip = "Search your Jellyfin/Plex titles or downloaded YouTube videos"
            yield inp
            yield PlayTable(id="den-results", cursor_type="row")
            yield Static(_status("snow", "Reading your library…"), id="den-note", markup=False)
            yield Checkbox("Resume where you left off", id="den-resume")
            with Horizontal():
                yield Button("Cancel", id="den-cancel")
                yield Button("Back", id="den-back")
                yield Button("Play on TV", id="den-play", variant="primary")
            yield Static("↑/↓ or j/k move · Enter choose · h back · Tab controls · Escape cancel",
                         classes="dialog-keys", markup=False)

    def on_mount(self):
        self.fetch(self.title_)

    @work(thread=True, exclusive=False, group="den-search")
    def fetch(self, query=""):
        self.app.call_from_thread(self._static, "snow", "STATIC, remote in hand: tuning in while your library is read")
        self.serial += 1
        serial = self.serial
        scope = dict(self.scope)
        try:
            rows = TVP.search(query, **scope)
            error = None
        except (ValueError, OSError) as e:
            rows, error = [], str(e)
        self.app.call_from_thread(self.got, serial, rows, error)

    def got(self, serial, rows, error):
        if serial != self.serial or not self.is_mounted: return
        self.rows = rows
        table = self.query_one("#den-results", HintTable)
        table.fill(("Title", "Kind", "Source"), [(TVP.TV.label(v), v.get("kind"), v.get("server")) for v in rows],
                   [TVP.TV.label(v) for v in rows], "Enter/l: choose · h: back · arrows/j/k: move")
        face = "whack" if error else ("happy" if rows else "fiddle")
        self.query_one("#den-note", Static).update(_status(face, error or (f"{len(rows)} found" if rows else "Nothing found on your media servers. Try another title or check that it is downloaded.")))
        self._static(face, {"whack": "STATIC whacks the set: your library couldn't be read",
                            "happy": "STATIC, remote in hand: pick something and he'll put it on",
                            "fiddle": "STATIC fiddles with the antenna: nothing matched"}[face])

    def _static(self, face, label):
        try:
            self.query_one("#den-static").set_pose("remote", face, label=label)
        except Exception:                                   # noqa: BLE001  (he's off)
            pass

    @on(Input.Submitted, "#den-search")
    def search_submitted(self, event):
        event.stop(); self.parents=[]
        self.scope=dict(kind=self.query_one("#den-kind", Select).value)
        self.query_one("#den-results", HintTable).focus()
        self.fetch(event.value)

    @on(Select.Changed, "#den-kind")
    def kind_changed(self, event):
        if not self.is_mounted: return
        self.parents=[]; self.scope=dict(kind=event.value)
        self.fetch(self.query_one("#den-search", Input).value)

    @on(HintTable.RowSelected, "#den-results")
    def row_selected(self, event):
        event.stop(); self.action_choose()

    def action_choose(self):
        if isinstance(self.focused, Input): return
        table = self.query_one("#den-results", HintTable)
        if not 0 <= table.cursor_row < len(self.rows): return
        row = self.rows[table.cursor_row]
        if row.get("kind") in ("show", "season"):
            self.parents.append((dict(self.scope), self.rows))
            self.scope = dict(kind="seasons" if row["kind"] == "show" else "episodes", id_=row["id"], source=row.get("server"))
            if row["kind"] == "season": self.scope["season"] = row["season"]
            self.fetch(); return
        self.dismiss(dict(item=row, screen=self.query_one("#den-screen", Select).value,
                          resume=self.query_one("#den-resume", Checkbox).value))

    def action_back(self):
        if self.parents:
            self.scope, rows = self.parents.pop(); self.serial += 1; self.got(self.serial, rows, None)

    def on_button_pressed(self, event):
        if event.button.id == "den-cancel": self.dismiss(None)
        elif event.button.id == "den-back": self.action_back()
        else: self.action_choose()
