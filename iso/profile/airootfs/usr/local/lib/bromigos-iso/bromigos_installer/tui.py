"""The text installer (docs/iso.md, "Installing from it"): the graphical installer's steps,
in a terminal, for a machine with no graphics, a serial console, the boot menu's "Install
bromigOS (text mode)" and `sudo bromigos-iso-install`. Textual, in DRIFTGLASS: the
theme's colours, a GLOW step rail and panels, one FLARE (the emblem, on the first step),
and no motion when motion is reduced.

  python3 -m bromigos_installer.tui [--plain] [--fake]

--plain (also chosen by itself with the screen reader on, accessibility=on, or a dumb
terminal): the same steps as plain questions, one after another, which a screen reader
reads in order. --fake: stand-in disks and install (backend.FAKE), for pictures and tests.
"""
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    __package__ = "bromigos_installer"

from . import backend, common  # noqa: E402
from .disks import GiB, plain_size  # noqa: E402


def _read(path):
    with open(path) as f:
        return f.read()

sys.path.append("/usr/lib/bromigos/lib")   # a checkout's own lib (PYTHONPATH) first
try:                         # DRIFTGLASS for Textual, bromigos-core's (lib/bromigos_textual.py)
    import bromigos_textual as BT
except ImportError:          # an older bromigos-core: the theme's colours, plainer widgets
    BT = None

try:
    from rich.text import Text
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.reactive import reactive
    from textual.suggester import SuggestFromList
    from textual.theme import Theme
    from textual.widget import Widget
    from textual.message import Message
    from textual.widgets import (Button, Checkbox, Collapsible, ContentSwitcher, Input, Label, ProgressBar, RadioButton,
                                 RadioSet, RichLog, Select, Static, Switch)
    HAVE_TEXTUAL = True
except ImportError:          # the plain questions still work
    HAVE_TEXTUAL = False
    App = object
    Widget = object
    Message = object

WORDMARK = """\
 ██████  ██████   ██████  ███    ███ ██  ██████   ██████  ███████
 ██   ██ ██   ██ ██    ██ ████  ████ ██ ██       ██    ██ ██
 ██████  ██████  ██    ██ ██ ████ ██ ██ ██   ███ ██    ██ ███████
 ██   ██ ██   ██ ██    ██ ██  ██  ██ ██ ██    ██ ██    ██      ██
 ██████  ██   ██  ██████  ██      ██ ██  ██████   ██████  ███████"""
EMBLEM_PATHS = ["/usr/share/bromigos/themes/wick/emblem/emblem.braille", "/usr/local/share/bromigos-iso/emblem.braille"]


def textual_theme():
    if BT is not None:
        return BT.theme()
    c, _ = common.theme()
    return Theme(name="bromigos", primary=c["primary"], secondary=c["soft"], accent=c["cyan"], warning=c["warn"],
                 error=c["danger"], success=c["primary"], foreground=c["text"], background=c["background"],
                 surface=c["panel"], panel=c["selection"], dark=True)


def hint(widget, text):
    """Every control says what it is and what it does: on hover (a tooltip) and, for the
    keyboard, in the hint line when it has the focus."""
    widget.tooltip = text
    return widget


class Split(Widget, can_focus=True):
    """How the disk is shared: the other system's part and bromigOS's, moved with ← and →
    (Shift: 10 GB at a time) or a click."""
    BINDINGS = [Binding("left", "move(-1)", "Smaller", show=False), Binding("right", "move(1)", "Bigger", show=False),
                Binding("shift+left", "move(-10)", show=False), Binding("shift+right", "move(10)", show=False),
                Binding("home", "move(-100000)", show=False), Binding("end", "move(100000)", show=False)]
    DEFAULT_CSS = "Split { height: 7; width: 1fr; padding: 0 1; border: round $primary 40%; } Split:focus { border: double $primary; }"
    value = reactive(0)

    def __init__(self, who, total, lo, hi, value, segs=None, partition=None, **kw):
        super().__init__(**kw)
        self.who, self.total, self.lo, self.hi = who, total, lo, hi
        self.segs, self.partition = segs or [], partition
        self.value = value

    def action_move(self, gib):
        self.value = max(self.lo, min(self.hi, self.value + gib * GiB))

    def on_click(self, event):
        w = max(1, self.size.width - 2)
        frac = min(1, max(0, (event.x - 1) / w))
        self.value = max(self.lo, min(self.hi, ((self.total - int(frac * self.total)) // GiB) * GiB))

    def watch_value(self, v):
        self.post_message(SplitChanged(self))

    def render(self):
        c = common.theme()[0]
        width = max(10, self.size.width - 2)
        left = self.total - self.value
        label = Text(f"{self.who.upper()} {plain_size(left)}", style="bold " + c.get("cyan", c["soft"]))
        gap = max(3, width - len(label) - len(f"BROMIGOS {plain_size(self.value)}"))
        label.append(" " * gap)
        label.append(f"BROMIGOS {plain_size(self.value)}", style="bold " + c["primary"])
        if BT is not None and hasattr(BT, "disk_map") and self.segs:
            gb = 2 ** 30
            segs = [s if not (s[0] == "windows" and s[3] and s[3]["path"] == self.partition) else ("windows", s[1], s[2], s[3])
                    for s in self.segs]
            segs = [s if s[0] != "windows" or (s[3] and s[3]["path"] == self.partition) else ("other",) + s[1:] for s in segs]
            bar = BT.disk_map(segs, width, map_colors(), split=((self.total - self.hi) / gb, (self.total - self.lo) / gb,
                                                                 left / gb, self.total / gb))
        else:
            cells = int(width * left / self.total) if self.total else 0
            bar = Text("█" * cells, style="bold " + c["soft"])
            bar.append("░" * (width - cells), style=c["primary"])
        lims = Text(f"◂ {self.who} needs {plain_size(self.total - self.hi)}", style=c.get("cyan", c["soft"]))
        right = f"bromigOS needs {plain_size(self.lo)} ▸"
        lims.append(" " * max(1, width - len(lims) - len(right)))
        lims.append(right, style=c["primary"])
        return Text("\n").join([label, bar, lims])


def map_colors():
    """The disk map's colours: the other system cyan, bromigOS the primary, the small
    partitions dim, free space faint (the console's 16 when that's what there is)."""
    c = common.theme()[0]
    if BT is not None and BT.color_mode() == "16":
        return {"windows": "cyan", "bromigos": "bright_green", "efi": "yellow", "msr": "white", "recovery": "cyan",
                "linux": "green", "other": "white", "free": "bright_black", "danger": "bright_red", "text": "bright_white"}
    return {"windows": c.get("cyan", c["soft"]), "bromigos": c["primary"], "efi": c.get("gold", c["warn"]), "msr": c["faint"],
            "recovery": c["dim"], "linux": c["soft"], "other": c["muted"], "free": c["faint"], "danger": c["danger"],
            "text": c["text"]}


def legend(segs, extra=None):
    """The map's key: each partition's icon and words."""
    c = common.theme()[0]
    t = Text()
    roles = {"efi": "chip", "windows": "windows", "recovery": "recovery", "linux": "linux", "free": "free", "msr": "chip",
             "other": "disk"}
    col = map_colors()
    for i, s in enumerate(segs):
        ic = BT.icon(roles.get(s[0], "disk")) if BT is not None else "•"
        t.append(f"{ic} ", style=col.get(s[0], c["muted"]))
        t.append((s[2] if s[0] != "free" else f"Free space, {plain_size(s[1])}") + "   ", style=c["muted"])
    if extra:
        t.append(extra[0], style="bold " + extra[1])
    return t


if HAVE_TEXTUAL:
    class SplitChanged(Message):
        def __init__(self, split):
            super().__init__()
            self.split = split


class Choice(Widget, can_focus=True):
    """A choice as a card (DRIFTGLASS Glass): its hologram, icon, title and lines, glowing when
    chosen. One of its row (the parent) is chosen at a time: ← → or ↑ ↓ move and pick, Enter
    or Space or a click picks. `value` as a RadioButton's, so the same code and tests drive it."""
    BINDINGS = [Binding("left,up", "step(-1)", show=False), Binding("right,down", "step(1)", show=False),
                Binding("enter,space", "pick", show=False)]
    DEFAULT_CSS = """Choice { width: 1fr; height: auto; border: round $secondary 45%; background: $surface 80%;
        padding: 0 1; margin-right: 1; }
    Choice.-on { border: round $primary; background: $primary 8%; }
    Choice:focus { border: double $primary; }
    Choice.-danger.-on { border: round $error; }
    Choice.-disabled { color: $text-disabled; }"""
    value = reactive(False)

    def __init__(self, content, value=False, disabled=False, **kw):
        super().__init__(**kw)
        self.content = content
        self.set_reactive(Choice.value, bool(value))
        self.off = disabled
        self.set_class(bool(value), "-on")
        self.set_class(disabled, "-disabled")
        if disabled:
            self.can_focus = False

    class Picked(Message if HAVE_TEXTUAL else object):
        def __init__(self, choice):
            super().__init__()
            self.choice = choice

    def render(self):
        c = common.theme()[0]
        mark = Text("◉ " if self.value else "○ ", style="bold " + (c["primary"] if self.value else c["faint"]))
        return Text.assemble(mark, self.content)

    def watch_value(self, v):
        self.set_class(v, "-on")
        if v:
            for sib in self.parent.query(Choice) if self.parent else []:
                if sib is not self and sib.value:
                    sib.value = False
            self.post_message(Choice.Picked(self))

    def action_pick(self):
        if not self.off:
            self.value = True

    def on_click(self):
        self.action_pick()
        self.focus()

    def action_step(self, d):
        sibs = [w for w in self.parent.query(Choice) if not w.off]
        if self in sibs:
            nxt = sibs[(sibs.index(self) + d) % len(sibs)]
            nxt.value = True
            nxt.focus()


class Installer(App):
    TITLE = "Install bromigOS"
    CSS = (BT.CSS if BT is not None else "") + """
    Screen { background: $background; }
    #top { height: 1; padding: 0 1; background: $surface; color: $primary; text-style: bold; }
    #body { height: 1fr; }
    #rail { width: 26; height: 1fr; padding: 1 1; border-right: solid $primary 30%; background: $surface; }
    #rail-steps { height: auto; }
    #orb { height: auto; margin-top: 1; content-align: center top; width: 100%; }
    #vector-line { height: auto; color: $text; margin-top: 0; }
    Screen.-compact #orb, Screen.-compact #vector-line { display: none; }
    #editions, #modes { height: auto; width: 100%; max-width: 200; }
    Screen.-narrow #editions, Screen.-narrow #modes { layout: vertical; }
    #phases { height: auto; margin-top: 1; }
    #ring-row { height: auto; }
    #ring { width: auto; height: auto; margin-right: 3; }
    #ring-side { width: 1fr; height: auto; }
    #page { padding: 1 2; scrollbar-gutter: stable; }
    #steps, #steps > Vertical, #disk-detail { height: auto; }      /* the page scrolls to all of it; nothing clips */
    .heading { color: $primary; text-style: bold; margin-bottom: 1; }
    .intro { color: $text-muted; margin-bottom: 1; }
    .label { margin-top: 1; color: $secondary; }
    .muted { color: $text-muted; }
    .warn { color: $warning; margin-top: 1; }
    .danger { color: $error; }
    .fix { color: $text; margin: 0 0 1 2; }
    .flare { color: $primary; margin-bottom: 1; }
    .card { border: round $primary 40%; background: $surface 85%; padding: 0 1; margin-top: 1; height: auto; width: 1fr; }
    #error { height: auto; padding: 0 2; color: $error; }
    #nav { height: 3; padding: 0 2; align-horizontal: right; }
    #nav Button { margin-left: 2; min-width: 14; }
    #hint { height: 2; padding: 0 2; color: $text-muted; border-top: solid $primary 25%; }
    Input, Select, RadioSet { margin-top: 0; width: 100%; max-width: 90; }
    RadioSet { height: auto; }
    ProgressBar { margin-top: 1; }
    ProgressBar Bar { width: 1fr; }
    #log { height: 1fr; min-height: 6; border: round $primary 30%; display: none; }
    #log.shown { display: block; }
    Button.-danger { color: $error; }
    /* re-flowed by width (bromigos_textual's breakpoints): a narrower rail, then none (the top
       line still names the step), less padding, smaller buttons */
    .notes { color: $text-muted; padding: 0 1; }
    Screen.-compact #rail { width: 20; }
    Screen.-narrow #rail { display: none; }
    Screen.-narrow #page { padding: 0 1; }
    Screen.-narrow #nav { padding: 0 1; }
    Screen.-narrow #nav { height: 1; }
    Screen.-narrow #nav Button { min-width: 8; margin-left: 1; height: 1; border: none; padding: 0 1; }
    Screen.-narrow #error, Screen.-narrow #hint { padding: 0 1; }
    Screen.-narrow #hint { height: 1; border-top: none; }
    Screen.-narrow .fix { margin: 0 0 1 0; }
    """
    BINDINGS = [Binding("escape", "back", "Back"), Binding("ctrl+n", "next", "Continue"),
                Binding("f12", "shell", "Shell", show=False),
                Binding("f2", "details", "Details", show=False), Binding("ctrl+c", "quit_ask", "Quit", show=False)]

    def __init__(self, fake=False):
        super().__init__()
        self.a = common.defaults()
        self.probe = None
        self.step = "welcome"
        self.running = None
        self.done = False
        self.reduced = common.reduced_motion()
        self.on_console = os.environ.get("TERM", "") == "linux"
        self.zones = common.timezones()
        self.eds = common.editions()

    # ── layout ──────────────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        if BT is not None:
            yield Static(BT.TOO_SMALL_WORDS, id="too-small")
        yield Static("", id="top")
        with Horizontal(id="body"):
            with Vertical(id="rail"):
                yield Static("", id="rail-steps")
                yield Static("", id="orb")
                yield Static("", id="vector-line")
            with VerticalScroll(id="page"):
                with ContentSwitcher(initial="step-welcome", id="steps"):
                    for sid, *_ in common.STEPS:
                        yield Vertical(id=f"step-{sid}")
        yield Static("", id="error")
        with Horizontal(id="nav"):
            yield hint(Button("Back", id="back"), "Go back one step. Nothing changes on any disk until you press Install.")
            yield hint(Button("Continue", id="next", variant="primary"), "Go on to the next step (Ctrl+N).")
        yield Static("", id="hint")

    async def on_mount(self):
        self.register_theme(textual_theme())
        self.theme = "bromigos"
        if self.reduced:
            self.animation_level = "none"
        self.watch(self.screen, "focused", self._focused)
        self.load_disks()
        self.answer_file, problems = None, []
        path = common.find_answer_file()
        if path:
            a, problems = common.read_answer_file(path)
            self.answer_file = path
            self.a.update({k: v for k, v in a.items() if v not in (None, "")})
            if not problems:
                self.a["auto"] = True
                self.countdown = int(a.get("countdown", 10))
        await self.show("auto" if self.a.get("auto") else "welcome")
        if problems:
            self.error(f"▲ The answer file {path} has problems, so the installer asks instead: " + " ".join(problems))

    def on_resize(self, event):
        if BT is None:
            return
        before = getattr(self, "bp", None)
        self.bp = BT.apply_breakpoint(self.screen, event.size.width, event.size.height)
        narrow = self.bp in ("narrow", "too-small")
        # the words that change with the width: the top line, and a narrow screen's two-line choices
        if before is not None and (before in ("narrow", "too-small")) != narrow and self.step not in ("install", "done", "auto"):
            self.call_later(self.show, self.step)
        elif self.step:
            try:
                self._top()
            except Exception:           # before the first step is drawn
                pass

    def narrow(self):
        return getattr(self, "bp", "normal") in ("narrow", "too-small")

    def _top(self):
        steps = self.steps()
        sid = self.step
        n = steps.index(sid) + 1 if sid in steps else 1
        if self.narrow():
            text = f"INSTALL  {n}/{len(steps)}  {common.STEP[sid][1].upper()}"
        else:
            text = f"BROMIGOS // INSTALL{' ' * 4}STEP {n} OF {len(steps)}  ·  {common.STEP[sid][1].upper()}"
        self.query_one("#top", Static).update(text)

    def _focused(self, w):
        tip = getattr(w, "tooltip", None) if w else None
        self.query_one("#hint", Static).update(str(tip) if tip else "Tab moves between choices · Enter picks · Esc goes back")

    def steps(self):
        self.a["edition_info"] = common.edition(self.a["edition"])
        return common.steps_for(self.a)

    @property
    def redraw(self):
        """One redraw at a time: the disks can arrive while a step is being drawn (os-prober
        takes seconds), and two at once would mount the same widgets twice."""
        import asyncio
        if not hasattr(self, "_redraw"):
            self._redraw = asyncio.Lock()
        return self._redraw

    async def show(self, sid):
        async with self.redraw:
            await self._show(sid)

    async def _show(self, sid):
        self.step = sid
        box = self.query_one(f"#step-{sid}", Vertical)
        await box.remove_children()
        getattr(self, f"build_{sid}")(box)
        self.query_one("#steps", ContentSwitcher).current = f"step-{sid}"
        steps = self.steps()
        self._top()
        self._rail(steps, sid)
        self.error("")
        back, nxt = self.query_one("#back", Button), self.query_one("#next", Button)
        back.display = sid not in ("welcome", "install", "done", "auto")
        nxt.display = sid not in ("install", "done", "auto")
        nxt.label = "Continue"
        nxt.variant = "primary"
        if sid == "summary":
            erase = self.a["mode"] == "erase"
            nxt.label = "Erase and install" if erase else "Install"
            nxt.variant = "error" if erase else "primary"
            hint(nxt, "Start the install. " + ("Everything on the disk is deleted." if erase else "Nothing you have is deleted."))
        else:
            hint(nxt, "Go on to the next step (Ctrl+N).")
        self.call_after_refresh(self._focus_first, box)

    VECTOR_LINES = {
        "welcome": "I'm VECTOR. Nothing changes until you say Install.",
        "edition": "Pick what this computer is for. A server can get the desktop later.",
        "disk": "Pick a disk, then how bromigOS goes on it.",
        "disk:alongside": "{who} keeps its files. I'll make room beside it.",
        "disk:erase": "Everything on this disk goes. Copy off what you need first.",
        "install": "Sit back. I'll say if anything needs you.",
        "summary": "Check it over. Nothing changes until you press Install.",
        "done": "All set. Restart, and take out the stick.",
    }

    def _rail(self, steps, sid):
        """The rail: each step's icon, a ✓ on the finished ones, the current one lit; VECTOR's
        orb under it (still while installing: the ring has the screen), with his line."""
        c = common.theme()[0]
        sixteen = BT is not None and BT.color_mode() == "16"
        here = steps.index(sid) if sid in steps else 0
        rail = Text()
        for i, s in enumerate(steps):
            ic = BT.icon(s) if BT is not None else "•"
            done = i < here
            if i == here:
                rail.append("▌", style="bold " + (BT.rich16("primary") if sixteen else c["primary"]))
                rail.append(f"{ic} {common.STEP[s][1]}", style="bold " + (BT.rich16("primary") if sixteen else c["primary"]))
            else:
                rail.append(" ")
                rail.append(f"{ic} {common.STEP[s][1]}", style=("" if done else "dim"))
                if done:
                    rail.append(" " + (BT.icon("check") if BT is not None else "✓"),
                                style=BT.rich16("primary") if sixteen else c["primary"])
            rail.append("\n")
        self.query_one("#rail-steps", Static).update(rail)
        if BT is not None and hasattr(BT, "orb"):
            self.orb_t = 0.0
            self.query_one("#orb", Static).update(BT.orb(0.0, 12, 6))
            if not self.reduced and not getattr(self, "_orb_timer", None):
                self._orb_timer = self.set_interval(0.15, self._orb_tick)
        line = self.VECTOR_LINES.get(sid, "")
        if sid == "disk" and self.a.get("mode") in ("alongside", "erase"):
            al = (self.disk() or {}).get("options", {}).get("alongside", {})
            line = self.VECTOR_LINES[f"disk:{self.a['mode']}"].format(who=al.get("who") or "Windows")
        self.query_one("#vector-line", Static).update(Text.assemble(("VECTOR  ", "bold " + c["primary"]), line) if line else "")

    def _orb_tick(self):
        if self.step == "install" or self.reduced:      # one FLARE: the ring, while installing
            return
        self.orb_t = getattr(self, "orb_t", 0.0) + 0.15
        try:
            self.query_one("#orb", Static).update(BT.orb(self.orb_t, 12, 6))
        except Exception:
            pass

    def _focus_first(self, box):
        for w in box.query("Choice.-on, Input, Select, RadioSet, Switch, Checkbox, Split, Button"):
            if w.focusable:
                w.focus()
                self.call_after_refresh(w.scroll_visible, animate=False)
                return
        self.query_one("#next", Button).focus()

    def on_descendant_focus(self, event):
        # the selection stays in view, whatever the size: the page scrolls to what has the focus
        w = event.widget
        if w is not None and w.id not in ("next", "back"):
            self.call_after_refresh(w.scroll_visible, animate=False)

    def error(self, text):
        self.query_one("#error", Static).update(Text(text) if text else "")

    def heading(self, box, sid):
        _, _, head, intro = common.STEP[sid]
        box.mount(BT.Emitter(head) if BT is not None else Static(head.upper(), classes="heading"), Static(intro, classes="intro"))

    # ── the steps ───────────────────────────────────────────────────────────────────
    def build_auto(self, box):
        self.heading(box, "auto")
        box.mount(Static(f"From {self.answer_file}", classes="muted"))
        self.auto_rows = Static("", classes="card")
        box.mount(self.auto_rows)
        self.auto_line = BT.Reading("Looking at the disks…", "busy") if BT is not None else Static("Looking at the disks…")
        box.mount(self.auto_line)
        box.mount(hint(Button("Cancel", id="auto-cancel", variant="error"),
                       "Stop the automatic install and answer the questions yourself. Nothing has changed yet."))
        self.set_interval(1, self.auto_tick, name="auto")

    def _auto_say(self, text, state="busy"):
        if BT is not None:
            self.auto_line.set(text, state)
        else:
            self.auto_line.update(text)

    async def auto_tick(self):
        if self.step != "auto" or not self.a.get("auto"):
            return
        if self.probe is None:
            return
        problem = common.auto_check(self.a, self.probe)
        if problem:
            self.a["auto"] = False
            await self.show("welcome")
            self.error("▲ " + problem + " The installer asks instead.")
            return
        from rich.table import Table
        rows, warn = common.summary(self.a, self.disk())
        t = Table.grid(padding=(0, 2))
        t.add_column(style="bold")
        t.add_column()
        for k, v in rows:
            t.add_row(k.upper(), v)
        self.auto_rows.update(t)
        if self.countdown <= 0:
            self.a["auto"] = False
            self.a["auto_started"] = True
            await self.start_install()
            return
        self._auto_say(f"Installing in {self.countdown} s. " + (warn or ""), "warn" if self.a["mode"] == "erase" else "busy")
        self.countdown -= 1

    def build_welcome(self, box):
        art = None
        if BT is not None:
            text, ansi = BT.emblem()
            art = Text.from_ansi(text) if ansi else (text if not self.narrow() else Text("BROMIGOS", style="bold"))
        elif not self.on_console:
            for p in EMBLEM_PATHS:
                if os.path.exists(p):
                    art = Text.from_ansi(_read(p))
                    break
        if self.size.height >= 30:          # the FLARE needs the room; a short screen goes straight to the words
            box.mount(Static(art if art is not None else WORDMARK, classes="flare"))
        self.heading(box, "welcome")
        box.mount(Label("Language for your new system", classes="label"))
        box.mount(hint(Select([(n, loc) for loc, n, _ in common.LANGUAGES], value=self.a["locale"], allow_blank=False, id="locale"),
                       "The language bromigOS uses once it's installed: menus, dates and numbers. The installer itself is in English."))
        box.mount(Label("Time zone", classes="label"))
        box.mount(hint(Input(self.a["timezone"], id="timezone", suggester=SuggestFromList(self.zones, case_sensitive=False),
                             placeholder="Region/City, for example Europe/Berlin"),
                       "Where you are, for the clock. Start typing a city or region; → takes the suggestion."))
        self.net_line = Static("", classes="muted")
        box.mount(Label("Network", classes="label"), self.net_line)
        tool = common.wifi_tool()
        if tool:
            box.mount(hint(Button("Connect to Wi-Fi…", id="wifi"), "Open the Wi-Fi settings to join a network. Only needed to download "
                                                                     "something that isn't on this USB stick."))
        self.refresh_network()

    @work(thread=True)
    def refresh_network(self):
        ed = common.edition(self.a["edition"])
        words = common.network_words(common.needs_download(ed), common.online())
        self.call_from_thread(lambda: getattr(self, "net_line", None) and self.net_line.update(words))

    def build_edition(self, box):
        self.heading(box, "edition")
        row = Horizontal(id="editions")
        box.mount(row)
        c = common.theme()[0]
        small = getattr(self, "bp", "normal") in ("compact", "narrow", "too-small")
        for e in self.eds:
            kind = "server" if e["id"] == "server" else "desktop"
            t = Text()
            t.append(f"{BT.icon(kind) if BT else ''} {e['title']}\n", style="bold")
            if BT is not None and hasattr(BT, "holo") and getattr(self, "bp", "normal") != "narrow":
                t.append_text(BT.holo(kind, 16 if small else 22, 5 if small else 7))
                t.append("\n")
            t.append(e.get("summary", ""), style=c["muted"])
            if not small and e.get("hint"):
                t.append("\n" + e["hint"], style=c["faint"])
            if common.needs_download(e):
                t.append("\n" + common.download_words(e), style=c["warn"])
            row.mount(hint(Choice(t, value=e["id"] == self.a["edition"], id=f"ed-{e['id']}"),
                           f"{e['title']}: {e.get('summary', '')} ← → choose.".strip()))

    def build_keyboard(self, box):
        self.heading(box, "keyboard")
        if not self.a.get("keyboard_chosen"):
            self.a["keyboard"] = common.LANG_KEYBOARD.get(self.a["locale"], "us")
        box.mount(hint(Select([(k[1], k[0]) for k in common.KEYBOARDS], value=self.a["keyboard"], allow_blank=False, id="kb"),
                       "Your keyboard's layout. It changes here at once, so you can try it below."))
        box.mount(Label("Try your keyboard here", classes="label"))
        box.mount(hint(Input(placeholder="Type a few letters, numbers and symbols…", id="kbtest"),
                       "A box to try the layout in: what you type here isn't kept."))
        if not self.on_console:
            box.mount(Static("In this window the layout follows the terminal's; your new system uses the one chosen here.", classes="muted"))

    @on(Select.Changed, "#kb")
    def kb_changed(self, ev):
        self.a["keyboard"] = ev.value
        self.a["keyboard_chosen"] = True
        backend.keyboard_live(ev.value, "console" if self.on_console else "")

    @on(Select.Changed, "#locale")
    def locale_changed(self, ev):
        if ev.value != self.a["locale"]:
            self.a["locale"] = ev.value
            self.query_one("#timezone", Input).value = common.tz_guess(ev.value)

    @work(thread=True)
    def load_disks(self):
        doc = backend.probe()
        found = [c for c in common.checks(doc) if c["level"] == "warn"]
        self.call_from_thread(self._disks_loaded, doc, found)

    def _disks_loaded(self, doc, found=()):
        self.probe = doc
        self.a["other_os"] = doc.get("other_os", False)
        self.a["checks"] = list(found)
        if self.step in ("disk", "welcome"):
            self.call_later(self.show, self.step)

    def build_checks(self, box):
        self.heading(box, "checks")
        for c in self.a.get("checks") or []:
            box.mount(Static(Text.assemble(("! ", "bold"), (c["title"], "bold")), classes="warn"),
                      Static(c["what"], classes="muted"))
            if c.get("fix"):
                box.mount(Static(Text.assemble(("What to do: ", "bold"), c["fix"]), classes="fix"))

    def disk(self):
        return next((d for d in (self.probe or {}).get("disks", []) if d["path"] == self.a["disk"]), None)

    def build_disk(self, box):
        self.heading(box, "disk")
        if self.probe is None:
            box.mount(Static("Looking at the disks… (this takes a few seconds)", classes="muted"))
            return
        if self.probe.get("error"):
            box.mount(Static(self.probe["error"], classes="danger"),
                      Static("Restart the computer and start the installer again. If it happens again, the disk may be failing.", classes="fix"))
            return
        usable = [d for d in self.probe["disks"] if not d["medium"]]
        if not usable:
            box.mount(Static("No disk found to install on.", classes="danger"),
                      Static("Check that the disk is connected (and, in the computer's settings, that it's switched on; "
                             "some laptops need SATA mode set to AHCI instead of RAID). Then restart.", classes="fix"))
            return
        if self.a["disk"] not in [d["path"] for d in usable]:
            self.a["disk"] = usable[0]["path"]
        rs = RadioSet(id="disks")
        box.mount(Label("Disk", classes="label"), hint(rs, "The disks in this computer: their size, model and what's on them."))
        c = common.theme()[0]
        # each disk on one line: its icon, model and size; its badge in a fixed column on the
        # right that never truncates; the description between them gives way first (…), and on
        # a narrow screen goes to its own dim line under the choices
        page_w = self.query_one("#page").size.width or (self.size.width - 30)
        avail = max(30, page_w - 12)                    # the page's padding, the set's frame, the radio
        for i, d in enumerate(self.probe["disks"]):
            kind = "usb" if d.get("removable") or d.get("kind") == "USB" else "disk"
            health = (d.get("health") or {}).get("state")
            badge, col = (("THIS STICK", c["muted"]) if d["medium"] else
                          (("▲ FAILING", c["danger"]) if health == "failing" else ("● HEALTHY", c["primary"])))
            badge = f"[{badge}]"
            head = f"{BT.icon(kind) if BT is not None else ''} {d['model']} · {d['size_text']}"
            label = Text(head[:2], style=c["primary"])
            label.append(head[2:], style="bold")
            if not self.narrow():
                desc = " · " + d["summary"] + (f" · {d['kind']}" if d["kind"] else "")
                room = avail - len(head) - len(badge) - 2
                if room < len(desc):
                    desc = desc[:max(0, room - 1)].rstrip(" ·") + "…" if room > 4 else ""
                label.append(desc, style=c["muted"])
                label.append(" " * max(1, avail - len(head) - len(desc) - len(badge)))
            else:
                label.append("  ")
            label.append(badge, style="bold " + col)
            rb = RadioButton(label, value=d["path"] == self.a["disk"], id=f"disk-{i}", disabled=d["medium"])
            rb.disk_path = d["path"]
            rs.mount(hint(rb, d["options"]["erase"]["why"] if d["medium"] else f"{d['path']}: " +
                          "; ".join(p["what"] for p in d["partitions"]) or "empty"))
        if self.narrow():           # each disk's notes on their own line, under the choices
            notes = Text()
            for d in self.probe["disks"]:
                notes.append(f"{d['model']}: ", style="bold")
                notes.append(d["summary"] + (f" · {d['kind']}" if d["kind"] else "") + "\n")
            box.mount(Static(notes, classes="notes"))
        self.disk_detail = Vertical(id="disk-detail")
        box.mount(self.disk_detail)
        self.call_later(self.fill_disk_detail)

    @on(RadioSet.Changed, "#disks")
    def disk_changed(self, ev):
        self.a["disk"] = getattr(ev.pressed, "disk_path", self.a["disk"])
        self.a["mode"] = None
        self.call_later(self.fill_disk_detail)

    async def fill_disk_detail(self):
        async with self.redraw:
            await self._fill_disk_detail()

    async def _fill_disk_detail(self):
        box = self.disk_detail
        await box.remove_children()
        d = self.disk()
        if not d:
            return
        al, er = d["options"]["alongside"], d["options"]["erase"]
        ri = d["options"].get("reinstall", {})
        if self.a["mode"] is None:
            self.a["mode"] = "reinstall" if ri.get("ok") else ("alongside" if al.get("ok") else ("erase" if er.get("ok") else None))
        row = Horizontal(id="modes")
        box.mount(Label("How", classes="label"), row)
        c = common.theme()[0]
        ic = (lambda n: BT.icon(n) + " ") if BT is not None else (lambda n: "")

        def card(icon_name, title, words):
            t = Text(ic(icon_name) + title + "\n", style="bold")
            t.append(words, style=c["muted"])
            return t
        if ri.get("ok"):
            row.mount(hint(Choice(card("recovery", ri["label"], ri["words"]), value=self.a["mode"] == "reinstall", id="mode-reinstall"),
                           ri["words"]))
        al_words = ("Keep " + (al.get("name") or "what's there") + " and its files. At every start, choose which one to use."
                    if al.get("ok") else al["why"])
        row.mount(hint(Choice(card("split", al["label"], al_words), value=self.a["mode"] == "alongside", id="mode-alongside",
                              disabled=not al.get("ok")), al_words))
        er_words = (f"Delete everything on it ({er.get('loses')}) and give it all to bromigOS." if er.get("ok") else er["why"])
        row.mount(hint(Choice(card("erase", "Erase the whole disk", er_words), value=self.a["mode"] == "erase", id="mode-erase",
                              disabled=not er.get("ok"), classes="-danger"), er_words))
        if not al.get("ok") and al.get("code") not in ("empty",):
            box.mount(Static(Text.assemble(("Why not alongside: ", "bold"), al["why"]), classes="warn"),
                      Static(Text.assemble(("What to do: ", "bold"), al["fix"]), classes="fix"))
        if self.a["mode"] == "reinstall" and ri.get("ok"):
            box.mount(Static(ri["words"], classes="muted"))
            if ri.get("encrypted"):
                box.mount(Label("The disk's passphrase (the one you type at start)", classes="label"))
                box.mount(hint(Input(self.a.get("old_passphrase", ""), password=True, id="old_passphrase"),
                               "The passphrase that unlocks this disk now. It stays the disk's passphrase."))
            if ri.get("users") and not self.a.get("user"):
                u = ri["users"][0]
                self.a.update(user=u["name"], full_name=u["gecos"].split(",")[0], user_edited=True)
        if self.a["mode"] == "alongside" and al.get("ok"):
            if al["mode"] == "shrink":
                box.mount(Label(f"The disk, and how it's shared (← → move the divider, Shift by 10 GB)", classes="label"))
                v = int(self.a.get("bromigos_bytes") or al["default"])
                v = max(al["min"], min(al["max"], v))
                self.a["bromigos_bytes"] = v
                box.mount(hint(Split(al["who"], al["part_size"] + al["free_after"], al["min"], al["max"], v,
                                     segs=common.disk_segments(d), partition=al.get("partition"), id="split"),
                               f"← gives {al['who']} more room, → gives bromigOS more. {al['who']} keeps at least "
                               f"{plain_size(al['keep_min'])}: what it uses now and room to grow."))
                box.mount(Static(legend(common.disk_segments(d), ("bromigOS: the room made beside it", common.theme()[0]["primary"])),
                                 classes="notes"))
                box.mount(Static(f"{al['who']} is made smaller to make room. Its files stay where they are.", classes="muted"))
            else:
                box.mount(Static(f"bromigOS goes in the {al['size_text']} of free space. {al.get('name') or 'What is there'} isn't touched.",
                                 classes="muted"))
            if al.get("warn"):
                box.mount(Static(al["warn"], classes="warn"))
        elif self.a["mode"] == "erase" and er.get("ok") and d["partitions"]:
            if BT is not None and hasattr(BT, "disk_map"):
                box.mount(Static(BT.disk_map(common.disk_segments(d), 60, map_colors(), erase=True), classes="card"))
            box.mount(Static(f"Everything on this disk is deleted: {er['loses']}. Copy anything you want to keep first.", classes="danger"))
        box.mount(self.advanced_box())

    def advanced_box(self):
        """Advanced, folded away: the file system, the kernel, zram, the boot loader, and
        archinstall's own menu for partitioning it yourself."""
        adv = self.a.setdefault("advanced", {"fs": "btrfs", "kernel": "linux", "zram": True})
        fs = hint(Select([(w, k) for k, w in common.FILESYSTEMS], value=adv["fs"], allow_blank=False, id="adv-fs"),
                  "The root's file system. btrfs keeps snapshots you can go back to from the boot menu.")
        kernel = hint(Select([(w, k) for k, w in common.KERNELS], value=adv["kernel"], allow_blank=False, id="adv-kernel"),
                      "Which Linux kernel. Arch's own suits nearly everyone.")
        zram = hint(Switch(adv["zram"], id="adv-zram"), "Compressed swap in memory (zram): more room when memory runs short.")
        row = Horizontal(zram, Label("  Compressed swap in memory (zram)"), classes="card")
        menu = hint(Button("Partition it myself…", id="adv-menu"),
                    "archinstall's own menu, filled in with everything chosen so far: change the partitions, the boot "
                    "loader or anything else there, then it installs.")
        c = Collapsible(Static(common.ADVANCED_WORDS, classes="muted"), Label("File system", classes="label"), fs,
                        Label("Kernel", classes="label"), kernel, row, Static(common.BOOTLOADER_WORDS, classes="muted"), menu,
                        title="Advanced", collapsed=True, id="advanced")
        return hint(c, "Options for people who know what they want. Nothing here is needed.")

    @on(Select.Changed, "#adv-fs")
    def adv_fs(self, ev):
        self.a.setdefault("advanced", {})["fs"] = ev.value

    @on(Select.Changed, "#adv-kernel")
    def adv_kernel(self, ev):
        self.a.setdefault("advanced", {})["kernel"] = ev.value

    @on(Switch.Changed, "#adv-zram")
    def adv_zram(self, ev):
        self.a.setdefault("advanced", {})["zram"] = ev.value

    def on_choice_picked(self, ev):
        cid = ev.choice.id or ""
        if cid.startswith("mode-"):
            mode = cid.removeprefix("mode-")
            if mode != self.a.get("mode"):
                self.a["mode"] = mode
                self.call_later(self.fill_disk_detail)
                self._rail(self.steps(), self.step)
        elif cid.startswith("ed-"):
            self.a["edition"] = cid.removeprefix("ed-")

    def on_split_changed(self, ev):  # SplitChanged
        self.a["bromigos_bytes"] = ev.split.value

    def build_user(self, box):
        self.heading(box, "user")
        fields = [("full_name", "Your name", "Your name, as the login screen shows it. Optional.", False, "Alex Rivera"),
                  ("user", "User name", "What you type to sign in: small letters and digits, no spaces.", False, "alex"),
                  ("password", "Password", "The password for signing in and for changes that need your permission.", True, ""),
                  ("password2", "Password again", "The same password once more, to be sure it's typed right.", True, ""),
                  ("hostname", "Computer's name", "How this computer shows up to other devices on your network.", False, "alex-pc")]
        for key, label, tip, pw, ph in fields:
            box.mount(Label(label, classes="label"))
            box.mount(hint(Input(self.a.get(key, ""), password=pw, id=key, placeholder=ph), tip))
        self.strength_line = Static("", classes="muted")
        box.mount(self.strength_line)

    @on(Input.Changed, "#full_name")
    def name_typed(self, ev):
        u = self.query_one("#user", Input)
        if not self.a.get("user_edited"):
            u.value = common.suggest_username(ev.value)

    @on(Input.Changed, "#user")
    def user_typed(self, ev):
        if self.focused is ev.input:
            self.a["user_edited"] = True
        h = self.query_one("#hostname", Input)
        if not self.a.get("host_edited"):
            h.value = common.suggest_hostname(ev.value, self.a["edition"])

    @on(Input.Changed, "#hostname")
    def host_typed(self, ev):
        if self.focused is ev.input:
            self.a["host_edited"] = True

    @on(Input.Changed, "#password")
    def pw_typed(self, ev):
        word, advice = common.strength(ev.value)
        self.strength_line.update(f"Strength: {word}. {advice}" if ev.value else "")

    def build_encryption(self, box):
        self.heading(box, "encryption")
        row = Horizontal(classes="card")
        box.mount(row)
        row.mount(hint(Switch(self.a["encrypt"], id="encrypt"), "On: the disk is locked until its passphrase is typed at start. Off: no passphrase."))
        row.mount(Label("  Encrypt the disk (recommended)"))
        box.mount(Static(common.ENCRYPT_WORDS, classes="muted"))
        box.mount(hint(Checkbox("Use a different passphrase from my password", self.a.get("separate_passphrase", False), id="separate"),
                       "Off: your password unlocks the disk too, one less thing to remember. On: the disk gets a passphrase of its own."))
        self.pp = Vertical(id="pp")
        box.mount(self.pp)
        self.call_later(self.fill_pp)

    async def fill_pp(self):
        async with self.redraw:
            await self._fill_pp()

    async def _fill_pp(self):
        await self.pp.remove_children()
        if self.a["encrypt"] and self.a.get("separate_passphrase"):
            self.pp.mount(Label("Disk passphrase", classes="label"),
                          hint(Input(self.a.get("passphrase", ""), password=True, id="passphrase"), "The passphrase you'll type at every start."),
                          Label("Passphrase again", classes="label"),
                          hint(Input(self.a.get("passphrase", ""), password=True, id="passphrase2"), "The same passphrase once more."))

    @on(Switch.Changed, "#encrypt")
    def enc_changed(self, ev):
        self.a["encrypt"] = ev.value
        self.call_later(self.fill_pp)

    @on(Checkbox.Changed, "#separate")
    def sep_changed(self, ev):
        self.a["separate_passphrase"] = ev.value
        self.call_later(self.fill_pp)

    def build_ssh(self, box):
        self.heading(box, "ssh")
        row = Horizontal(classes="card")
        box.mount(row)
        row.mount(hint(Switch(self.a.get("ssh", False), id="ssh"), "On: sign in from other computers on your network (SSH). Off: only at this computer."))
        row.mount(Label("  Turn on SSH"))
        box.mount(Static(common.SSH_WORDS, classes="muted"))
        self.ssh_box = Vertical(id="ssh-box")
        box.mount(self.ssh_box)
        for key, title, words, tip in (("firewall", "Firewall", common.FIREWALL_WORDS, "On: other computers can't connect, except to SSH when it's on."),
                                       ("auto_updates", "Automatic updates", common.AUTO_UPDATE_WORDS,
                                        "On: security fixes install by themselves, each after a snapshot you can go back to.")):
            row = Horizontal(classes="card")
            box.mount(row)
            row.mount(hint(Switch(self.a.get(key, True), id=key), tip))
            row.mount(Label(f"  {title}"))
            box.mount(Static(words, classes="muted"))
        if "found_keys" not in self.a:
            self.a["found_keys"] = common.stick_keys()
            self.a["ssh_keys"] = [k for _, k in self.a["found_keys"]]
        self.call_later(self.fill_ssh)

    async def fill_ssh(self):
        async with self.redraw:
            await self._fill_ssh()

    async def _fill_ssh(self):
        await self.ssh_box.remove_children()
        if not self.a.get("ssh"):
            return
        rs = RadioSet(id="ssh-how")
        self.ssh_box.mount(hint(rs, common.SSH_KEY_WORDS))
        rs.mount(hint(RadioButton("Keys only (recommended)", value=not self.a.get("ssh_password"), id="ssh-keys"),
                      "Sign in with a key file from your other computer. Nobody can guess it."))
        rs.mount(hint(RadioButton("Keys or my password", value=bool(self.a.get("ssh_password")), id="ssh-pw"),
                      "Also allow signing in with your password, which anyone on the network can try to guess."))
        self.ssh_box.mount(Static(common.SSH_KEY_WORDS, classes="muted"))
        found = self.a.get("found_keys") or []
        if found:
            self.ssh_box.mount(Label("Keys found in the USB stick's fieldkit folder", classes="label"))
            for i, (name, key) in enumerate(found):
                self.ssh_box.mount(hint(Checkbox(f"{name}: {key[:40]}…", key in self.a["ssh_keys"], id=f"key-{i}"),
                                        "Let whoever holds this key's private half sign in as you."))
        else:
            self.ssh_box.mount(Static("No key found in the USB stick's fieldkit folder. Copy your key's .pub file there "
                                      "and press Look again, or paste it below.", classes="muted"))
        self.ssh_box.mount(hint(Button("Look again", id="rescan-keys"), "Read the USB stick's fieldkit folder for keys again."))
        self.ssh_box.mount(Label("Paste a public key (optional)", classes="label"))
        self.ssh_box.mount(hint(Input(id="pasted-key", placeholder="ssh-ed25519 AAAA… you@laptop"),
                                "One line from your other computer's .pub file, for example ~/.ssh/id_ed25519.pub."))

    @on(Switch.Changed, "#ssh")
    def ssh_changed(self, ev):
        self.a["ssh"] = ev.value
        self.call_later(self.fill_ssh)

    @on(Switch.Changed, "#firewall")
    def fw_changed(self, ev):
        self.a["firewall"] = ev.value

    @on(Switch.Changed, "#auto_updates")
    def au_changed(self, ev):
        self.a["auto_updates"] = ev.value

    @on(RadioSet.Changed, "#ssh-how")
    def ssh_how(self, ev):
        self.a["ssh_password"] = ev.pressed.id == "ssh-pw"

    @on(Checkbox.Changed)
    def key_ticked(self, ev):
        cid = ev.checkbox.id or ""
        if cid.startswith("key-"):
            key = self.a["found_keys"][int(cid[4:])][1]
            keys = [k for k in self.a["ssh_keys"] if k != key]
            self.a["ssh_keys"] = keys + ([key] if ev.value else [])

    def build_summary(self, box):
        self.heading(box, "summary")
        from rich.table import Table
        rows, warn = common.summary(self.a, self.disk())
        t = Table.grid(padding=(0, 2))
        t.add_column(style="bold " + common.theme()[0]["dim"], no_wrap=True)
        t.add_column()
        for k, v in rows:
            t.add_row(k.upper(), v)
        box.mount(Static(t, classes="card"))
        if warn:
            box.mount(Static(warn, classes="danger" if self.a["mode"] == "erase" else "warn"))
        self.what = Static("Open this to see the commands and archinstall's configuration.", classes="muted")
        box.mount(hint(Collapsible(self.what, title="Show what will run", collapsed=True, id="what"),
                       "The exact commands, and the configuration archinstall gets (passwords hidden)."))

    @on(Collapsible.Expanded, "#what")
    def what_opened(self, ev):
        self.load_preview()

    @work(thread=True)
    def load_preview(self):
        cfg, creds, lines = backend.preview(common.backend_answers(self.a, self.disk()))
        text = Text("\n".join(lines) + "\n\n", style="bold")
        if cfg:
            text.append("archinstall's configuration (config.json):\n", style="bold")
            text.append(cfg + "\n\ncredentials (creds.json, secrets hidden):\n" + creds)
        self.call_from_thread(self.what.update, text)

    def action_shell(self):
        """A shell, one keystroke away (F12); exit it to come back here."""
        if self.running:
            self.error("▲ The install is running: the shell opens once it's done.")
            return
        with self.suspend():
            print("A shell. The installer waits: type exit to go back to it.")
            os.system(os.environ.get("SHELL") or "/bin/bash")

    PHASES = [("room", "disk", "Making room", ("Making room",)),
              ("disk", "chip", "Preparing the disk", ("Preparing the disk", "Opening your")),
              ("copy", "copy", "Copying bromigOS onto the disk", ("Copying", "Installing")),
              ("people", "people", "Your account and your desktop", ("Setting up", "Bringing back", "Your account")),
              ("boot", "boot", "The boot menu and snapshots", ("boot menu", "Boot", "snapshots"))]

    def build_install(self, box):
        self.heading(box, "install")
        self.bar = BT.Sweep(total=100, id="bar") if BT is not None else ProgressBar(total=100, show_eta=False, id="bar")
        self.status = BT.Reading("Starting…", "busy") if BT is not None else Static("Starting…", classes="label")
        self.log_view = RichLog(id="log", wrap=True, max_lines=4000)
        self.ring = Static("", id="ring")
        self.phases = Static("", id="phases")
        self.status.display = False          # the phases carry the same words, lit
        side = Vertical(self.status, self.phases, id="ring-side")
        row = Horizontal(self.ring, side, id="ring-row")
        box.mount(row, self.bar, hint(Button("Show details", id="details"), "Show or hide every step the install takes (F2)."),
                  self.log_view)
        self._ring(0, "Starting…")

    def _ring(self, pct, text):
        """The ring fills as the install goes (the screen's FLARE), the phases beside it."""
        c = common.theme()[0]
        small = getattr(self, "bp", "normal") in ("compact", "narrow", "too-small")
        if BT is not None and hasattr(BT, "ring") and getattr(self, "bp", "normal") != "narrow":
            r = BT.ring(pct, 10 if small else 16, 5 if small else 8)
            r.append(f"\n{pct:>{(10 if small else 16) // 2 + 2}} %", style="bold " + c["primary"])
            self.ring.update(r)
        else:
            self.ring.display = False
        al = (self.disk() or {}).get("options", {}).get("alongside", {})
        shrink = self.a.get("mode") == "alongside" and al.get("mode") == "shrink"
        phases = [p for p in self.PHASES if shrink or p[0] != "room"]
        cur = 0
        for i, p in enumerate(phases):
            if any(w.lower() in (text or "").lower() for w in p[3]):
                cur = i
        if pct >= 100:
            cur = len(phases)
        t = Text()
        for i, (key, ic, words, _) in enumerate(phases):
            glyph = (BT.icon("check") if i < cur else BT.icon(ic)) if BT is not None else ("✓" if i < cur else "•")
            if i < cur:
                t.append(f"{glyph} {words}\n", style=c["soft"])
            elif i == cur:
                t.append(f"{glyph} {text if text else words}\n", style="bold " + c["primary"])
            else:
                t.append(f"{glyph} {words}\n", style=c["faint"])
        self.phases.update(t)

    def build_done(self, box):
        if self.done is True:
            self.heading(box, "done")
            ed = common.edition(self.a["edition"])
            lines = ["When the screen goes dark, take out the USB stick."]
            if self.a["encrypt"]:
                lines.append("At start, type the disk's passphrase" + (" (your password)." if not self.a.get("separate_passphrase") else "."))
            if self.a["mode"] == "alongside":
                lines.append(f"The boot menu lets you choose bromigOS or {self.disk()['options']['alongside'].get('name') or 'the other system'} each time.")
            lines.append("Then sign in at the login screen." if ed.get("desktop", True) else "Then sign in at the text console.")
            box.mount(Static("✓ " + "\n  ".join(lines), classes="card"))
            box.mount(hint(Button("Restart now", id="reboot", variant="primary"), "Restart the computer into bromigOS."))
        else:
            box.mount(Static("THE INSTALL DIDN'T FINISH", classes="heading danger"))
            box.mount(Static(self.done or "The install stopped.", classes="card"))
            box.mount(Horizontal(hint(Button("Back to the summary", id="retry", variant="primary"),
                                      "Go back, change something if you like, and try the install again."),
                                 hint(Button("Show details", id="details"), "Every step the install took, and where it stopped."),
                                 classes="card"))
            self.log_view = RichLog(id="log", wrap=True, max_lines=4000)
            box.mount(self.log_view)
            for line in getattr(self, "lines", [])[-400:]:
                self.log_view.write(line)

    # ── moving between steps ────────────────────────────────────────────────────────
    def check(self):
        """The step's answers read and checked: None, or what to fix, in plain words."""
        s = self.step
        q = self.query_one
        if s == "welcome":
            tz = q("#timezone", Input).value.strip()
            match = next((z for z in self.zones if z.lower() == tz.lower()), None)
            if not match:
                return "Choose a time zone from the suggestions, for example America/New_York or Europe/London."
            self.a["timezone"] = match
        elif s == "disk":
            d = self.disk()
            if not d:
                return "Choose a disk to install on."
            if self.a["mode"] not in ("alongside", "erase", "reinstall") or not d["options"][self.a["mode"]].get("ok"):
                return "Choose how to install on this disk."
            if self.a["mode"] == "reinstall" and d["options"]["reinstall"].get("encrypted"):
                self.a["old_passphrase"] = q("#old_passphrase", Input).value
                if not self.a["old_passphrase"]:
                    return "Type the disk's passphrase: the one you type when the computer starts."
        elif s == "user":
            for k in ("full_name", "user", "password", "password2", "hostname"):
                self.a[k] = q(f"#{k}", Input).value.strip() if k not in ("password", "password2") else q(f"#{k}", Input).value
            return (common.check_full_name(self.a["full_name"]) or common.check_username(self.a["user"])
                    or common.check_password(self.a["password"], self.a["password2"]) or common.check_hostname(self.a["hostname"]))
        elif s == "encryption" and self.a["encrypt"] and self.a.get("separate_passphrase"):
            self.a["passphrase"] = q("#passphrase", Input).value
            return common.check_password(self.a["passphrase"], q("#passphrase2", Input).value, "passphrase")
        elif s == "ssh" and self.a.get("ssh"):
            pasted = q("#pasted-key", Input).value.strip()
            if pasted:
                problem = common.check_key(pasted)
                if problem:
                    return problem
                if pasted not in self.a["ssh_keys"]:
                    self.a["ssh_keys"].append(pasted)
            if not self.a.get("ssh_password") and not self.a["ssh_keys"]:
                return ("Keys only needs a key: copy your .pub file into the USB stick's fieldkit folder and press Look again, "
                        "paste it in the box, or choose Keys or my password.")
        elif s == "edition":
            ed = common.edition(self.a["edition"])
            if common.needs_download(ed) and not common.online():
                return common.network_words(True, False)
        return None

    async def action_next(self):
        if self.step in ("install", "done"):
            return
        problem = self.check()
        if problem:
            self.error("▲ " + problem)
            return
        if self.step == "summary":
            return await self.start_install()
        steps = self.steps()
        await self.show(steps[steps.index(self.step) + 1])

    async def action_back(self):
        steps = self.steps()
        if self.step in steps and steps.index(self.step) > 0 and self.step not in ("install", "done"):
            await self.show(steps[steps.index(self.step) - 1])

    def action_details(self):
        if hasattr(self, "log_view"):
            self.log_view.toggle_class("shown")

    def action_quit_ask(self):
        if self.running:
            self.error("▲ The install is running. Leaving now would leave the disk half done: wait for it to finish.")
            return
        self.exit()

    @on(Button.Pressed)
    async def pressed(self, ev):
        bid = ev.button.id
        if bid == "next":
            await self.action_next()
        elif bid == "back":
            await self.action_back()
        elif bid == "details":
            self.action_details()
        elif bid == "wifi":
            tool = common.wifi_tool()
            with self.suspend():
                os.system("nmtui connect" if tool == "nmtui" else "iwctl")
            self.refresh_network()
        elif bid == "reboot":
            backend.reboot()
            self.exit()
        elif bid == "auto-cancel":
            self.a["auto"] = False
            await self.show("welcome")
        elif bid == "adv-menu":
            await self.partition_myself()
        elif bid == "rescan-keys":
            self.a["found_keys"] = common.stick_keys()
            self.a["ssh_keys"] = sorted(set(self.a["ssh_keys"]) | {k for _, k in self.a["found_keys"]})
            self.call_later(self.fill_ssh)
        elif bid == "retry":
            await self.show("summary")

    async def on_input_submitted(self, ev):
        if ev.input.id != "kbtest":
            await self.action_next()

    async def partition_myself(self):
        """archinstall's own menu, filled in with what's chosen so far (the power user's way)."""
        if not self.a.get("user") or not self.a.get("password"):
            self.error("▲ Fill in About you first (your user name and password), then come back to this.")
            return
        doc = common.backend_answers(self.a, self.disk())
        path = backend.answers_file(doc)
        with self.suspend():
            import subprocess
            subprocess.run(backend.as_root([backend.INSTALL, "--answers", path, "--menu", "--no-reboot"]))
            input("Press Enter to go back to the installer.")

    async def start_install(self):
        self.lines = []
        doc = common.backend_answers(self.a, self.disk())
        await self.show("install")

        def stage(pct, text):
            self.call_from_thread(self._stage, pct, text)

        def line(text):
            self.lines.append(text)
            self.call_from_thread(self.log_view.write, text)

        def done(ok, err):
            self.call_from_thread(self._done, ok, err)
        self.running = backend.Install(doc, stage, line, done).start()

    def _stage(self, pct, text):
        self.bar.update(progress=pct)
        self._ring(pct, text)
        if BT is not None:
            self.status.set(text, "ok" if pct >= 100 else "busy")
        else:
            self.status.update(text)

    def _done(self, ok, err):
        self.running = None
        self.done = True if ok else err
        self.call_later(self.show, "done")


# ── the plain questions (a screen reader, a dumb terminal) ──────────────────────────────
def plain():
    from . import plain as P
    return P.main()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--fake" in argv:
        os.environ["BROMIGOS_INSTALLER_FAKE"] = "1"
        backend.FAKE = True
    if os.geteuid() != 0 and not backend.FAKE:
        print("The installer changes disks, so it needs to run as the system administrator.\n"
              "Start it from the boot menu (Install bromigOS), or from the live desktop's Install bromigOS icon.")
        return 2
    try:
        cmd = _read("/proc/cmdline")
    except OSError:
        cmd = ""
    if BT is not None:
        BT.prepare_terminal()
    if "--plain" in argv or not HAVE_TEXTUAL or os.environ.get("TERM") in ("dumb", "") or \
            ("accessibility=on" in cmd and "--no-plain" not in argv):
        return plain()
    Installer().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
