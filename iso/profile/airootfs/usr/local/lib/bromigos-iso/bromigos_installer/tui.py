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
try:                         # VECTOR's lines and his voice (docs/voice-guide.md), bromigos-core's
    import bromigos_guide as guide
except ImportError:          # an older bromigos-core: no captions, no voice
    guide = None
HIGH_CONTRAST = False        # the first step's High contrast: col() gives every muted role the text's colour

try:
    from rich.text import Text
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.css.query import NoMatches
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


def textual_theme(high_contrast=False):
    if BT is not None:
        return BT.theme(name="bromigos-hc" if high_contrast else "bromigos", high_contrast=high_contrast)
    c, _ = common.theme()
    if high_contrast:        # the first step's High contrast: white on black, nothing faded
        return Theme(name="bromigos-hc", primary=c["primary"], secondary=c["primary"], accent=c["cyan"], warning=c["warn"],
                     error=c["danger"], success=c["primary"], foreground="#ffffff", background="#000000",
                     surface="#000000", panel="#000000", dark=True, variables={"text-muted": "#ffffff"})
    return Theme(name="bromigos", primary=c["primary"], secondary=c["soft"], accent=c["cyan"], warning=c["warn"],
                 error=c["danger"], success=c["primary"], foreground=c["text"], background=c["background"],
                 surface=c["panel"], panel=c["selection"], dark=True)


def look():
    return BT.icon_look() if BT is not None else "ascii"


def sixteen():
    return BT is not None and BT.color_mode() == "16"


def col(role):
    """A palette role as a Rich colour: the theme's hex, or its 16-colour console name."""
    if HIGH_CONTRAST and role in ("muted", "faint", "dim", "soft"):
        role = "text"
    if sixteen():
        return {"primary": BT.rich16("primary"), "soft": BT.rich16("primary"), "dim": BT.rich16("secondary"),
                "faint": "bright_black", "muted": "white", "text": "white", "danger": "bright_red", "warn": "bright_yellow",
                "cyan": BT.rich16("accent"), "gold": "yellow", "background": "black"}.get(role, "white")
    c = common.theme()[0]
    return c.get(role) or c["text"]


def ic(name):
    return BT.icon(name) if BT is not None else "*"


def icon_rows(items, style=None, icon_style=None):
    """Lines that each start with an icon, wrapped under their own words (not under the icon)."""
    from rich.table import Table
    t = Table.grid(padding=(0, 2), expand=True)
    t.add_column(no_wrap=True, width=1)
    t.add_column(ratio=1)
    for name, words in items:
        t.add_row(Text(ic(name), style=icon_style or "bold " + col("primary")), Text(words, style=style or ""))
    return t


def strength_level(pw):
    """0 (nothing typed) to 3: how many of the strength meter's segments light."""
    if not pw:
        return 0
    return {"weak": 1, "fair": 2, "strong": 3}[common.strength(pw)[0]]


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
    #mok { height: auto; margin-top: 1; }
    #mok-row { height: auto; }
    #mok-code { width: auto; height: auto; margin: 1 3 0 1; }
    #mok-steps { width: 1fr; height: auto; }
    Screen.-narrow #mok-row, Screen.-compact #mok-row { layout: vertical; }
    /* the chosen row lit, its words still readable: Textual's cursor colours put the label in
       the same green as its highlight */
    RadioSet:focus > RadioButton.-selected > .toggle--label { background: $primary 28%; color: $foreground; text-style: bold; }
    RadioSet:blur > RadioButton.-selected > .toggle--label { background: $primary 12%; color: $foreground; }
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
    /* the hero row: the emblem (the screen's FLARE) beside the heading */
    #hero { height: auto; }
    #hero-art { width: auto; height: auto; margin-right: 3; }
    #hero-side { width: 1fr; height: auto; }
    /* fields two to a row where there's room, one under another where there isn't */
    .fields { height: auto; }
    .field { width: 1fr; height: auto; margin-right: 2; }
    .field:last-of-type { margin-right: 0; }
    Screen.-compact .fields, Screen.-narrow .fields { layout: vertical; }
    Screen.-compact .field, Screen.-narrow .field { margin-right: 0; }
    .field Input, .field Select { max-width: 100%; }
    .panel { border: round $secondary 60%; background: $surface 85%; padding: 0 1 1 1; height: auto; margin-top: 1; }
    .panel-head { height: 1; margin-bottom: 0; }
    .row { height: auto; }
    .row Button { margin-left: 2; }
    Screen.-narrow .row { layout: vertical; }
    Screen.-narrow .row Button { margin-left: 0; }
    .check { border: round $warning 60%; background: $surface 85%; padding: 0 1; height: auto; margin-bottom: 1; }
    /* About you: an operator ID card */
    #idcard { border: round $primary 70%; background: $surface 85%; padding: 0 1 1 1; height: auto; }
    #id-head { height: 1; margin: 0 -1 0 -1; padding: 0 1; }
    #id-body { height: auto; }
    #portrait { width: 17; height: auto; border: round $secondary 60%; padding: 0 1; margin: 1 2 0 0; content-align: center top; }
    Screen.-compact #portrait, Screen.-narrow #portrait { display: none; }
    #id-fields { width: 1fr; height: auto; }
    #id-foot { height: auto; margin-top: 1; color: $text-muted; }
    .vlabel { height: 1; margin-top: 1; }
    .meter { height: auto; margin-top: 1; }
    /* Lock the disk: the lock beside its switch */
    #lock-row { height: auto; }
    #lock { width: auto; height: auto; margin: 1 3 0 1; }
    Screen.-narrow #lock { display: none; }
    #lock-side { width: 1fr; height: auto; }
    /* Ready to install: the briefing, one row a step, each with its Change button */
    #briefing { border: round $primary 60%; background: $surface 85%; padding: 0 1; height: auto; }
    .brief-row { height: auto; margin-top: 1; }
    #briefing.-tight .brief-row { margin-top: 0; }
    .brief-text { width: 1fr; height: auto; }
    .brief-row Button { height: 1; min-width: 10; border: none; padding: 0 1; margin: 0 0 0 1; }
    /* the countdown, the failure's frozen ring */
    #count-row { height: auto; margin: 1 0; }
    #count { width: auto; height: auto; margin-right: 3; }
    #count-side { width: 1fr; height: auto; }
    .buttons { height: auto; margin-top: 1; }
    .buttons Button { margin-right: 2; }
    Screen.-narrow .buttons { layout: vertical; }
    .fail-head { color: $error; text-style: bold; }
    #ssh-box, #pp { height: auto; }
    .card > Label { width: 1fr; }
    #hero-art.flare { margin-bottom: 1; }
    Screen.-c16 Choice.-on { background: $surface; border: double $primary; }
    .vlabel.-top { margin-top: 0; }
    """
    BINDINGS = [Binding("escape", "back", "Back"), Binding("ctrl+n", "next", "Continue"),
                Binding("f12", "shell", "Shell", show=False),
                Binding("f2", "details", "Details", show=False), Binding("ctrl+c", "quit_ask", "Quit", show=False)] + \
        [Binding(str(n), f"brief('{n}')", show=False) for n in range(1, 10)] + \
        ([Binding(guide.TEXTUAL_KEYS, "voice", "Voice", show=False)] if guide else [])   # Ctrl+Alt+V

    def __init__(self, fake=False):
        super().__init__()
        self.a = common.defaults()
        self.probe = None
        self.step = "guide"
        self.running = None
        self.done = False
        self.reduced = common.reduced_motion()
        self.on_console = os.environ.get("TERM", "") == "linux"
        # VECTOR's voice: one player (the console's: aplay when no PipeWire runs); its on and
        # muted are root's on the live system, copied to the new user at the end
        self.voice = guide.Guide("console", notify=self._voice_notice) if guide else None
        if self.voice and backend.FAKE:      # --fake (pictures, tests): it never makes a sound
            self.voice._out = (None, "The fake installer makes no sound.")
        self._spoken = None
        if self.voice:
            self.a["guidance"].update(voice=self.voice.enabled, voice_muted=self.voice.muted)
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
                with ContentSwitcher(initial="step-guide", id="steps"):
                    for sid, *_ in common.STEPS:
                        yield Vertical(id=f"step-{sid}")
        yield Static("", id="error")
        with Horizontal(id="nav"):
            yield hint(Button("Back", id="back"), "Go back one step. Nothing changes on any disk until you press Install.")
            yield hint(Button("Continue", id="next", variant="primary"), "Go on to the next step (Ctrl+N).")
        yield Static("", id="hint")

    async def on_mount(self):
        self.register_theme(textual_theme())
        self.register_theme(textual_theme(high_contrast=True))
        self.theme = "bromigos"
        # the Linux console's 16 colours can't mix a tint: a chosen card keeps the plain surface
        self.screen.set_class(sixteen(), "-c16")
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
        await self.show("auto" if self.a.get("auto") else self.first_step())
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
        if sid == "done" and self.done is not True:
            text = f"BROMIGOS // INSTALL{' ' * 4}STOPPED  ·  THE INSTALL DIDN'T FINISH" if not self.narrow() else "INSTALL  STOPPED"
        elif self.narrow():
            text = f"INSTALL  {n}/{len(steps)}  {common.STEP[sid][1].upper()}"
        else:
            text = f"BROMIGOS // INSTALL{' ' * 4}STEP {n} OF {len(steps)}  ·  {common.STEP[sid][1].upper()}"
        self.query_one("#top", Static).update(text)

    HINT = "Tab moves between choices · Enter picks · Esc goes back"

    def _focused(self, w):
        tip = getattr(w, "tooltip", None) if w else None
        if tip and self.voice and not self.narrow():      # the voice key stays in sight beside the hint
            tip = f"{tip}  ·  {self.voice_word()}"
        self.query_one("#hint", Static).update(str(tip) if tip else self.default_hint())

    def default_hint(self):
        """The hint line with nothing focused: the keys, and VECTOR's voice key with its state."""
        if not self.voice:
            return self.HINT
        return f"{self.HINT} · {self.voice_word()}"

    def voice_word(self):
        word = {"on": "voice on", "muted": "voice muted", "off": "voice off", "screen-reader": "voice quiet",
                "no-sound": "no sound"}[self.voice.status()]
        return f"{guide.HOTKEY} {word}"

    def first_step(self):
        return self.steps()[0]

    # ── VECTOR's voice ──────────────────────────────────────────────────────────────
    def _voice_notice(self, words):
        """No sound device (a serial console, SSH): said once, where problems are said."""
        try:
            self.error("▲ " + words)
        except Exception:
            pass

    def line_id(self, sid):
        """The catalogue's id for a step's line (its .short form where there is one: the
        rail is narrow), and its {values}."""
        if sid == "done" and self.done is not True:
            return guide.pick("installer.failed", short=True), {}
        if sid == "disk" and self.a.get("mode") in ("alongside", "erase", "reinstall"):
            al = (self.disk() or {}).get("options", {}).get("alongside", {})
            return guide.pick(f"installer.disk.{self.a['mode']}", short=True), {"who": al.get("who") or "Windows"}
        return guide.pick(f"installer.{sid}", short=True), {}

    def speak_step(self, sid=None):
        """VECTOR says the step's line, once: a redraw of the same step doesn't repeat it."""
        if not self.voice:
            return
        lid, values = self.line_id(sid or self.step)
        key = (lid, tuple(sorted(values.items())))
        if key == self._spoken:
            return
        self._spoken = key
        self.voice.play(lid, **values)

    def action_voice(self):
        """Ctrl+Alt+V (ctrl+v on the Linux console): on when it's off, then muted and back."""
        if not self.voice:
            return
        self.voice.toggle()
        self.a["guidance"].update(voice=self.voice.enabled, voice_muted=self.voice.muted)
        self._spoken = None
        if self.voice.status() == "on":
            self.speak_step()
        self._voice_shown()

    def _voice_shown(self):
        try:
            self._focused(self.focused)
        except Exception:
            return
        if self.step == "guide":
            for sw in self.query("#g-voice"):
                if sw.value != self.voice.enabled:
                    self._voice_sync = True
                    sw.value = self.voice.enabled
            for st in self.query("#g-voice-state"):
                (st.set(self.voice.describe(), "ok" if self.voice.status() == "on" else "idle") if BT is not None
                 else st.update(self.voice.describe()))

    def steps(self):
        self.a["edition_info"] = common.edition(self.a["edition"])
        d = self.disk()
        # BitLocker matters only when Windows stays: erasing the disk takes it with it
        self.a["bitlocker"] = bool(d and d.get("bitlocker") and self.a.get("mode") not in ("erase", "reinstall"))
        return common.steps_for(self.a)

    @property
    def redraw(self):
        """One redraw at a time: the disks can arrive while a step is being drawn (os-prober
        takes seconds), and two at once would mount the same widgets twice."""
        import asyncio
        if not hasattr(self, "_redraw"):
            self._redraw = asyncio.Lock()
        return self._redraw

    async def _mount_all(self, box, build):
        """Run build(), then wait until everything it mounted into box is mounted, before the
        redraw lock lets the next redraw remove it: a Select torn down mid-mount fails inside
        Textual ("No nodes match '#label'"), and a slow console (the stick's VT, a serial
        line) widens that window."""
        pending = []

        def mount(*widgets, **kw):
            aw = type(box).mount(box, *widgets, **kw)
            pending.append(aw)
            return aw
        box.mount = mount
        try:
            r = build()
            if hasattr(r, "__await__"):
                await r
        finally:
            del box.mount
        for aw in pending:
            await aw

    async def show(self, sid):
        async with self.redraw:
            if not self.is_running:         # quitting: nothing left to draw into
                return
            try:
                await self._show(sid)
            except NoMatches:
                if self.is_running:
                    raise

    async def _show(self, sid):
        self.step = sid
        self.visited = getattr(self, "visited", set()) | {sid}
        if sid in ("summary", "install", "done", "auto"):
            self.from_summary = False
        box = self.query_one(f"#step-{sid}", Vertical)
        await box.remove_children()
        await self._mount_all(box, lambda: getattr(self, f"build_{sid}")(box))
        self.query_one("#steps", ContentSwitcher).current = f"step-{sid}"
        steps = self.steps()
        self._top()
        self._rail(steps, sid)
        self.error("")
        back, nxt = self.query_one("#back", Button), self.query_one("#next", Button)
        back.display = sid not in ("guide", "install", "done", "auto")
        nxt.display = sid not in ("install", "done", "auto")
        nxt.label = "Continue"
        nxt.variant = "primary"
        if sid == "summary":
            erase = self.a["mode"] == "erase"
            nxt.label = "Erase and install" if erase else "Install"
            nxt.variant = "error" if erase else "primary"
            hint(nxt, "Start the install. " + ("Everything on the disk is deleted." if erase else "Nothing you have is deleted."))
        elif getattr(self, "from_summary", False):
            nxt.label = "Back to summary"
            hint(nxt, "Keep this and go back to the summary (Ctrl+N).")
        else:
            hint(nxt, "Go on to the next step (Ctrl+N).")
        self.call_after_refresh(self._focus_first, box)
        self.speak_step(sid)
        self._focused(self.focused)

    FLARE_STEPS = ("welcome", "install", "done", "auto")     # the screen has its own FLARE: the orb holds still

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
                rail.append(">" if look() == "ascii" else "▌", style="bold " + (BT.rich16("primary") if sixteen else c["primary"]))
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
        # his line: the voice guide's catalogue (lib/guide/lines.toml), the caption his clip says
        lid, values = self.line_id(sid) if guide else (None, {})
        line = guide.line(lid, **values) if guide else ""
        self.query_one("#vector-line", Static).update(Text.assemble(("VECTOR  ", "bold " + c["primary"]), line) if line else "")

    def _orb_tick(self):
        if self.step in self.FLARE_STEPS or self.reduced:      # one FLARE a screen: the ring, the emblem, the countdown
            return
        self.orb_t = getattr(self, "orb_t", 0.0) + 0.15
        try:
            self.query_one("#orb", Static).update(BT.orb(self.orb_t, 12, 6))
        except Exception:
            pass

    def _focus_first(self, box):
        for w in box.query("Choice.-on, Input, Select, RadioSet, Switch, Checkbox, Split, Button"):
            if w.focusable:
                self._arriving = w
                w.focus(scroll_visible=False)
                self.call_after_refresh(self._first_view, w)
                return
        self.query_one("#next", Button).focus()

    def _first_view(self, w):
        """A step opens at its top, heading first; it scrolls only when the first choice
        wouldn't be in view from there (a small screen)."""
        self._arriving = None
        self.query_one("#page", VerticalScroll).scroll_home(animate=False, immediate=True)
        self.call_after_refresh(self._peek, w)

    def _peek(self, w):
        """After the layout: the first choice's first lines in view, or scroll to it."""
        if not w.is_mounted:
            return
        page = self.query_one("#page", VerticalScroll)
        if w.region.y + min(w.region.height, 3) > page.region.bottom or not page.region.overlaps(w.region):
            w.scroll_visible(animate=False)

    def on_descendant_focus(self, event):
        # the selection stays in view, whatever the size: the page scrolls to what has the focus
        w = event.widget
        if w is not None and w.id not in ("next", "back") and w is not getattr(self, "_arriving", None):
            self.call_after_refresh(w.scroll_visible, animate=False)

    def error(self, text):
        self.query_one("#error", Static).update(Text(text) if text else "")

    def heading(self, box, sid):
        _, _, head, intro = common.STEP[sid]
        box.mount(BT.Emitter(head) if BT is not None else Static(head.upper(), classes="heading"), Static(intro, classes="intro"))

    # ── the steps ───────────────────────────────────────────────────────────────────
    def build_auto(self, box):
        self.heading(box, "auto")
        box.mount(Static(Text.assemble((ic("book") + "  ", col("primary")), ("From ", col("muted")), (str(self.answer_file), "bold")),
                         classes="vlabel"))
        row = Horizontal(id="count-row")
        box.mount(row)
        self.count_art = Static("", id="count")
        side = Vertical(id="count-side")
        row.mount(self.count_art, side)
        self.auto_line = BT.Reading("Looking at the disks…", "busy") if BT is not None else Static("Looking at the disks…")
        side.mount(self.auto_line)
        side.mount(Horizontal(hint(Button("Cancel", id="auto-cancel", variant="error"),
                                   "Stop the automatic install and answer the questions yourself. Nothing has changed yet."),
                              classes="buttons"))
        self.auto_rows = Static("", id="briefing")
        box.mount(self.auto_rows)
        self.auto_total = max(1, int(getattr(self, "countdown", 10)))
        self._count(None)
        self.set_interval(1, self.auto_tick, name="auto")

    def _count(self, n):
        """The countdown in big digits (the screen's FLARE), the time left as a meter under it."""
        t = Text()
        if n is None:
            t.append("· · ·", style=col("faint"))
        elif BT is not None and hasattr(BT, "big_code"):
            t.append_text(BT.big_code(str(n), style="bold " + col("warn" if self.a.get("mode") == "erase" else "primary"), scale=2))
            t.append("\n")
            t.append_text(BT.meter(n, self.auto_total, self.auto_total * 3, role="warn" if self.a.get("mode") == "erase" else "primary")
                          if hasattr(BT, "meter") else Text(""))
        else:
            t.append(str(n), style="bold")
        self.count_art.update(t)

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
            await self.show(self.first_step())
            self.error("▲ " + problem + " The installer asks instead.")
            return
        rows, warn = common.summary(self.a, self.disk())
        t = Text()
        t.append(ic("summary") + "  WHAT IT WILL DO\n", style="bold " + col("primary"))
        for i, (k, v) in enumerate(rows):
            t.append(("\n" if i else "") + k.upper().ljust(20), style="bold " + col("soft"))
            t.append(v, style=col("text"))
        self.auto_rows.update(t)
        self._count(max(0, self.countdown))
        if self.countdown <= 0:
            self.a["auto"] = False
            self.a["auto_started"] = True
            await self.start_install()
            return
        self._auto_say(f"Installing in {self.countdown} s. " + (warn or ""), "warn" if self.a["mode"] == "erase" else "busy")
        self.countdown -= 1

    def hero(self, box, sid, art=None):
        """The heading, with the emblem beside it when the screen has the room (the FLARE)."""
        if art is not None and self.size.height >= 30 and not self.narrow():
            if max(len(line) for line in str(art).split("\n")) > 40:      # the wordmark: above the heading
                box.mount(Static(art, id="hero-art", classes="flare"))
                self.heading(box, sid)
                return box
            row, side = Horizontal(id="hero"), Vertical(id="hero-side")
            box.mount(row)
            row.mount(Static(art, id="hero-art"), side)
            self.heading(side, sid)
            return side
        self.heading(box, sid)
        return box

    def flabel(self, icon_name, words, key=None, top=False):
        """A field's label: its icon and words; with `key`, the live check glyph after them."""
        t = Text()
        t.append(ic(icon_name) + " ", style=col("primary"))
        t.append(words, style=col("soft"))
        lab = Static(t, classes="vlabel -top" if top else "vlabel", id=f"lab-{key}" if key else None)
        lab.words, lab.icon_name = words, icon_name
        return lab

    def build_guide(self, box):
        """How would you like to be guided? VECTOR's voice (off until it's turned on, with a
        sample), the console's screen reader, bigger letters (the console's font: a terminal
        can't make its own text bigger), high contrast, no motion; and the language."""
        g = self.a["guidance"]
        self.heading(box, "guide")
        voice = Vertical(classes="panel", id="g-voice-panel")
        box.mount(voice)
        row = Horizontal(classes="row")
        voice.mount(row)
        sw = hint(Switch(bool(self.voice and self.voice.enabled), id="g-voice", disabled=not self.voice),
                  "On: VECTOR reads each step aloud. Off: his words stay on screen.")
        row.mount(sw, Vertical(Static(Text.assemble((ic("voice") + "  ", "bold " + col("primary")),
                                                     ("VECTOR'S VOICE GUIDE", "bold " + col("primary")))),
                               Static("He reads each step aloud, in his own voice." +
                                      (f" {guide.HOTKEY} turns him on, then mutes him." if guide else ""), classes="muted"),
                               classes="brief-text"),
                  hint(Button("Play a sample", id="g-sample", disabled=not self.voice), "Hear VECTOR's voice now, once"))
        words = self.voice.describe() if self.voice else "VECTOR's voice isn't on this USB stick: his words are on screen."
        voice.mount(BT.Reading(words, "idle", id="g-voice-state") if BT is not None else Static(words, id="g-voice-state"))
        more = Vertical(classes="panel", id="g-more")
        box.mount(more)
        more.mount(Static(Text.assemble((ic("guide") + "  ", "bold " + col("primary")), ("MORE HELP", "bold " + col("soft"))),
                          classes="panel-head"))
        big_ok = self.on_console
        for key, icon_name, title, tip in (
                ("screen_reader", "reader", "Screen reader: speech reads the console aloud",
                 "Start or stop the console's screen reader (espeakup). VECTOR stays quiet while it talks."),
                ("console_font", "text", "Bigger letters on this screen" if big_ok else
                 "Bigger letters: a terminal can't change its own; use its settings (often Ctrl and +)",
                 "The console's bigger font." if big_ok else "This terminal's text size is the terminal's own setting."),
                ("high_contrast", "contrast", "High contrast: white on black, nothing faded",
                 "Stronger colours here and on your new system"),
                ("reduce_motion", "motion", "Reduce motion: nothing moves on its own", "No animation here or on your new system")):
            r = Horizontal(classes="row")
            more.mount(r)
            r.mount(hint(Switch(bool(g.get(key)), id=f"g-{key}", disabled=key == "console_font" and not big_ok), tip),
                    Static(Text.assemble((ic(icon_name) + "  ", col("primary")), title), classes="brief-text"))
        self.guide_said = BT.Reading("", "idle", id="g-said") if BT is not None else Static("", id="g-said")
        more.mount(self.guide_said)
        lang = Vertical(self.flabel("language", "Language for your new system"),
                        hint(Select([(n, loc) for loc, n, _ in common.LANGUAGES], value=self.a["locale"], allow_blank=False,
                                    id="locale"),
                             "The language bromigOS uses once it's installed: menus, dates and numbers. The installer itself is in English."),
                        classes="field")
        box.mount(lang)

    def _guide_said(self, words, state="idle"):
        if BT is not None:
            self.guide_said.set(words, state)
        else:
            self.guide_said.update(words)

    @on(Switch.Changed, "#g-voice")
    def voice_switched(self, ev):
        if getattr(self, "_voice_sync", False):
            self._voice_sync = False
            return
        if not self.voice:
            return
        self.voice.set_enabled(ev.value)
        if ev.value and self.voice.muted:
            self.voice.set_muted(False)
        self.a["guidance"].update(voice=ev.value, voice_muted=self.voice.muted)
        self._spoken = None
        if ev.value:
            self.speak_step()
        self._voice_shown()

    @on(Switch.Changed, "#g-screen_reader, #g-console_font, #g-high_contrast, #g-reduce_motion")
    def guidance_switched(self, ev):
        key = ev.switch.id.removeprefix("g-")
        if getattr(self, "_guidance_sync", None) == key:
            self._guidance_sync = None
            return
        self.a["guidance"][key] = ev.value
        if key in ("screen_reader", "console_font"):
            self.guidance_work(key, ev.value)
        elif key == "high_contrast":
            global HIGH_CONTRAST
            HIGH_CONTRAST = ev.value
            self.theme = "bromigos-hc" if ev.value else "bromigos"
            self._rail(self.steps(), self.step)
            self._guide_said("High contrast is on." if ev.value else "High contrast is off.", "ok")
        elif key == "reduce_motion":
            if ev.value:
                os.environ["BROMIGOS_REDUCED_MOTION"] = "1"     # the widgets drawn from now on hold still too
            else:
                os.environ.pop("BROMIGOS_REDUCED_MOTION", None)
            self.reduced = common.reduced_motion()
            self.animation_level = "none" if self.reduced else "full"
            self._guide_said("Reduced motion is on: nothing moves on its own." if self.reduced else "Reduced motion is off.", "ok")

    @work(thread=True)
    def guidance_work(self, key, on):
        """The screen reader (systemctl, as root) and the console's font (setfont): off the UI's thread."""
        self.call_from_thread(self._guide_said, "Starting the screen reader…" if key == "screen_reader" and on else "…", "busy")
        ok, words = backend.screen_reader(on, "console") if key == "screen_reader" else backend.console_font(on)

        def done():
            if not ok:
                self.a["guidance"][key] = False
                for sw in self.query(f"#g-{key}"):
                    if sw.value:
                        self._guidance_sync = key
                        sw.value = False
            self._guide_said(("▲ " if not ok else "") + words, "ok" if ok else "warn")
            self._voice_shown()
        self.call_from_thread(done)

    def build_welcome(self, box):
        art = None
        if BT is not None:
            art = BT.emblem_text(wide=not self.narrow() and getattr(self, "bp", "normal") != "compact")
        elif not self.on_console:
            for p in EMBLEM_PATHS:
                if os.path.exists(p):
                    art = Text.from_ansi(_read(p))
                    break
        side = self.hero(box, "welcome", art if art is not None else Text(WORDMARK))
        side.mount(Static(icon_rows((("clock", "About ten minutes"), ("shield", "Nothing changes until you press Install"),
                                     ("shell", "F12 opens a shell, any time")), style=col("muted")), classes="notes"))
        panel = Vertical(classes="panel", id="welcome-panel")
        box.mount(panel)
        # the language is on the first step, with how you're guided
        tz = Vertical(self.flabel("clock", "Time zone"),
                      hint(Input(self.a["timezone"], id="timezone", suggester=SuggestFromList(self.zones, case_sensitive=False),
                                 placeholder="Region/City, for example Europe/Berlin"),
                           "Where you are, for the clock. Start typing a city or region; → takes the suggestion."),
                      classes="field")
        panel.mount(Horizontal(tz, classes="fields"))
        panel.mount(self.flabel("wifi", "Network"))
        self.net_line = BT.Reading("Checking the network…", "busy") if BT is not None else Static("", classes="muted")
        tool = common.wifi_tool()
        wifi = [hint(Button("Connect to Wi-Fi…", id="wifi"), "Open the Wi-Fi settings to join a network. Only needed to download "
                                                              "something that isn't on this USB stick.")] if tool else []
        panel.mount(Horizontal(Vertical(self.net_line, classes="brief-text"), *wifi, classes="row"))
        self.refresh_network()

    @work(thread=True)
    def refresh_network(self):
        ed = common.edition(self.a["edition"])
        download, is_online = common.needs_download(ed), common.online()
        words = common.network_words(download, is_online)
        state = "ok" if is_online else ("warn" if download else "idle")

        def put():
            line = getattr(self, "net_line", None)
            if line is None:
                return
            if BT is not None:
                line.set(words, state)
            else:
                line.update(words)
        self.call_from_thread(put)

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
        box.mount(self.flabel("keyboard", "Layout"))
        box.mount(hint(Select([(k[1], k[0]) for k in common.KEYBOARDS], value=self.a["keyboard"], allow_blank=False, id="kb"),
                       "Your keyboard's layout. It changes here at once, so you can try it below."))
        panel = Vertical(classes="panel")
        box.mount(panel)
        self.caps = Static("", id="keycaps")
        panel.mount(self.flabel("edit", "Try your keyboard here", top=True))
        panel.mount(hint(Input(placeholder="Type a few letters, numbers and symbols…", id="kbtest"),
                         "A box to try the layout in: what you type here isn't kept. The key you type lights up on the keys below."))
        panel.mount(self.caps)
        self._caps()
        if not self.on_console:
            box.mount(Static("In this window the layout follows the terminal's; your new system uses the one chosen here.", classes="muted"))

    def _caps(self, lit=None):
        """The chosen layout's letter keys, the one just typed lit (none for a non-Latin layout)."""
        if BT is None or not hasattr(BT, "keycaps") or not getattr(self, "caps", None):
            return
        k = common.KEYBOARD.get(self.a["keyboard"], common.KEYBOARDS[0])
        rows = BT.keyrows(k[3], k[4])
        self.caps.display = rows is not None
        if rows:
            t = Text("\n")
            t.append_text(BT.keycaps(rows, lit))
            self.caps.update(t)

    @on(Input.Changed, "#kbtest")
    def kb_typed(self, ev):
        self._caps(ev.value[-1:] or None)

    @on(Select.Changed, "#kb")
    def kb_changed(self, ev):
        if ev.value != self.a["keyboard"]:
            self.a["keyboard_chosen"] = True
        self.a["keyboard"] = ev.value
        backend.keyboard_live(ev.value, "console" if self.on_console else "")
        self._caps()

    @on(Select.Changed, "#locale")
    def locale_changed(self, ev):
        if ev.value != self.a["locale"]:
            self.a["locale"] = ev.value
            self.a["timezone"] = common.tz_guess(ev.value)       # the next step's time zone starts from it

    @work(thread=True)
    def load_disks(self):
        doc = backend.probe()
        found = [c for c in common.checks(doc) if c["level"] == "warn"]
        self.call_from_thread(self._disks_loaded, doc, found)

    def _disks_loaded(self, doc, found=()):
        self.probe = doc
        self.a["other_os"] = doc.get("other_os", False)
        self.a["checks"] = list(found)
        if self.step == "guide":              # the rail only (a Checks step may come in): the switches keep the focus
            self._rail(self.steps(), "guide")
            self._top()
        elif self.step in ("disk", "welcome"):
            self.call_later(self._reshow, self.step)

    async def _reshow(self, sid):
        """Draw a step again for what just arrived, if it's still the one on screen."""
        async with self.redraw:
            if self.step == sid:
                await self._show(sid)

    def build_checks(self, box):
        self.heading(box, "checks")
        found = self.a.get("checks") or []
        for c in found:
            card = Vertical(classes="check")
            box.mount(card)
            card.mount(Static(Text.assemble((ic("alert") + "  ", "bold " + col("warn")), (c["title"], "bold " + col("warn")))),
                       Static(c["what"], classes="muted"))
            if c.get("fix"):
                card.mount(Static(Text.assemble((ic("info") + "  ", col("primary")), ("What to do: ", "bold"), c["fix"])))
        if BT is not None:
            n = len(found)
            box.mount(BT.Reading(f"{n} thing{'s' if n != 1 else ''} worth knowing. None of them stops the install: "
                                 "Continue when you're ready.", "ok"))

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
            if not self.narrow() and len(head) > avail - len(badge) - 2:     # the model gives way, never the badge
                cut = avail - len(badge) - 2 - len(f" · {d['size_text']}") - 3
                head = f"{BT.icon(kind) if BT is not None else ''} {d['model'][:max(4, cut)].rstrip()}… · {d['size_text']}"
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
            await self._mount_all(self.disk_detail, self._fill_disk_detail)

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

    def build_bitlocker(self, box):
        self.heading(box, "bitlocker")
        panel = Vertical(classes="panel")
        box.mount(panel)
        head = Text()
        head.append(ic("key") + "  ", style="bold " + col("warn"))
        head.append("WINDOWS' BITLOCKER RECOVERY KEY", style="bold " + col("warn"))
        sample = "-".join(["000000"] * 8)
        panel.mount(Static(head, classes="panel-head"),
                    Static("It's 48 digits in eight groups, like this:", classes="muted"),
                    Static(Text.assemble((sample, "bold " + col("soft"))), classes="notes"),
                    Static(common.BITLOCKER_WORDS, classes="muted"))
        row = Horizontal(classes="card")
        box.mount(row)
        row.mount(hint(Switch(bool(self.a.get("bitlocker_saved")), id="bitlocker-saved"),
                       "Turn this on once the key is saved. bromigOS never changes Windows' BitLocker drive."),
                  Label("  I've saved the BitLocker recovery key, somewhere that isn't this computer"))

    @on(Switch.Changed, "#bitlocker-saved")
    def bitlocker_ticked(self, ev):
        self.a["bitlocker_saved"] = ev.value

    # ── About you: an operator ID card ─────────────────────────────────────────────────
    USER_FIELDS = [("full_name", "Your name", "user", "Your name, as the login screen shows it. Optional.", False, "Alex Rivera"),
                   ("user", "User name", "idcard", "What you type to sign in: small letters and digits, no spaces.", False, "alex"),
                   ("password", "Password", "key", "The password for signing in and for changes that need your permission.", True, ""),
                   ("password2", "Password again", "key", "The same password once more, to be sure it's typed right.", True, ""),
                   ("hostname", "Computer's name", "computer", "How this computer shows up to other devices on your network.", False,
                    "alex-pc")]

    def build_user(self, box):
        self.heading(box, "user")
        card = Vertical(id="idcard")
        box.mount(card)
        self.id_head = Static("", id="id-head")
        self.portrait = Static("", id="portrait")
        fields = Vertical(id="id-fields")
        self.id_foot = Static("", id="id-foot")
        body = Horizontal(id="id-body")
        card.mount(self.id_head, body, self.id_foot)
        body.mount(self.portrait, fields)

        def field(key):
            k, label, icon_name, tip, pw, ph = next(f for f in self.USER_FIELDS if f[0] == key)
            return Vertical(self.flabel(icon_name, label, key), hint(Input(self.a.get(k, ""), password=pw, id=k, placeholder=ph), tip),
                            classes="field")
        fields.mount(Horizontal(field("full_name"), field("user"), classes="fields"),
                     Horizontal(field("password"), field("password2"), classes="fields"))
        self.strength_line = Static("", classes="meter")
        fields.mount(Horizontal(field("hostname"), Vertical(self.strength_line, classes="field"), classes="fields"))
        self.call_after_refresh(self._id_refresh)

    def field_state(self, key):
        """(state, words) for one About-you field as it's typed: ok, bad (and why), or empty."""
        q = lambda k: self.query_one(f"#{k}", Input).value      # noqa: E731
        v = q(key)
        if key == "full_name":
            why = common.check_full_name(v)
            return ("bad", why) if why else (("ok", "") if v.strip() else ("empty", "optional"))
        if not v:
            return "empty", ""
        if key == "user":
            why = common.check_username(v.strip())
        elif key == "password":
            why = "at least 4 characters" if len(v) < 4 else None
        elif key == "password2":
            why = "not the same as the password yet" if v != q("password") else None
        else:
            why = common.check_hostname(v.strip())
        return ("bad", why) if why else ("ok", "")

    def _id_refresh(self):
        """The card follows what's typed: each field's ✓ or ✗, the portrait's initials, the line at its foot."""
        if self.step != "user" or not self.query("#user"):
            return
        for key, label, icon_name, *_ in self.USER_FIELDS:
            state, why = self.field_state(key)
            t = Text()
            t.append(ic(icon_name) + " ", style=col("primary"))
            t.append(label, style=col("soft"))
            glyph, style = {"ok": (ic("check"), "bold " + col("primary")), "bad": (ic("cross"), "bold " + col("danger")),
                            "empty": ("." if look() == "ascii" else "·", col("faint"))}[state]
            t.append("  " + glyph, style=style)
            if why:
                t.append(" " + why, style=col("danger") if state == "bad" else col("faint"))
            t.truncate(80, overflow="ellipsis")
            for lab in self.query(f"#lab-{key}"):
                lab.update(t)
        name = self.query_one("#full_name", Input).value.strip()
        user = self.query_one("#user", Input).value.strip()
        host = self.query_one("#hostname", Input).value.strip()
        head = Text(no_wrap=True, overflow="ellipsis")
        on = "black" if sixteen() else col("primary")
        head.append(ic("idcard") + "  OPERATOR ID", style="bold " + on)
        right = "BROMIGOS · ADMIN"
        w = max(len(right) + 16, (self.id_head.size.width or 60) - 2)
        head.append(" " * max(2, w - 14 - len(right)))
        head.append(right, style="bold " + on)
        self.id_head.update(head)
        self.id_head.styles.background = BT.rich16("secondary") if sixteen() else common.theme()[0]["selection"]
        initials = "".join(w[0] for w in name.split()[:2]).upper() or (user[:1].upper() or "?")
        initials = "".join(ch for ch in common._ascii(initials) if ch.isalnum()) or "?"
        p = BT.big_code(initials) if BT is not None and hasattr(BT, "big_code") else Text(initials, style="bold")
        p.append("\n\n")
        p.append((name or "Your name")[:13] + "\n", style="bold " + col("text") if name else col("faint"))
        p.append((user or "user")[:13], style=col("primary") if user else col("faint"))
        self.portrait.update(p)
        foot = Text()
        foot.append("SIGNS IN AS ", style=col("muted"))
        foot.append(user or "…", style="bold " + col("primary"))
        foot.append("   ON ", style=col("muted"))
        foot.append(host or "…", style="bold " + col("primary"))
        foot.append("   ·   admin: may install apps and change the system", style=col("faint"))
        self.id_foot.update(foot)
        self._strength(self.strength_line, self.query_one("#password", Input).value, "password")

    def _strength(self, where, pw, what):
        """The strength meter: three segments of block cells (one thickness, like the disk map),
        lit by how hard the password is to guess, and what that means in words."""
        level = strength_level(pw)
        t = Text()
        t.append("Strength", style=col("muted"))
        if pw:
            word, advice = common.strength(pw)
            t.append(f"  {word}", style="bold " + col({1: "danger", 2: "warn", 3: "primary"}[level]))
        t.append("\n")
        # the meter on a line of its own, narrower than the field: its cells are spaces with a
        # background, which wrapping would trim
        if BT is not None and hasattr(BT, "meter"):
            t.append_text(BT.meter(level, 3, 17))
        else:
            t.append("#" * (level * 5) + "." * ((3 - level) * 5))
        t.append("\n")
        t.append(advice if pw else f"Type a {what} to see how strong it is.", style=col("muted") if pw else col("faint"))
        where.update(t)

    @on(Input.Changed, "#password, #password2, #hostname")
    def id_typed(self, ev):
        self._id_refresh()

    @on(Input.Changed, "#full_name")
    def name_typed(self, ev):
        u = self.query_one("#user", Input)
        if not self.a.get("user_edited"):
            u.value = common.suggest_username(ev.value)
        self._id_refresh()

    @on(Input.Changed, "#user")
    def user_typed(self, ev):
        if self.focused is ev.input:
            self.a["user_edited"] = True
        h = self.query_one("#hostname", Input)
        if not self.a.get("host_edited"):
            h.value = common.suggest_hostname(ev.value, self.a["edition"])
        self._id_refresh()

    @on(Input.Changed, "#hostname")
    def host_typed(self, ev):
        if self.focused is ev.input:
            self.a["host_edited"] = True


    def build_encryption(self, box):
        self.heading(box, "encryption")
        self.lock_art = Static("", id="lock")
        side, lock_row = Vertical(id="lock-side"), Horizontal(id="lock-row")
        box.mount(lock_row)
        lock_row.mount(self.lock_art, side)
        row = Horizontal(classes="card")
        side.mount(row)
        row.mount(hint(Switch(self.a["encrypt"], id="encrypt"), "On: the disk is locked until its passphrase is typed at start. Off: no passphrase."))
        row.mount(Label("  Encrypt the disk (recommended)"))
        self.lock_line = BT.Reading("", "ok") if BT is not None else Static("")
        side.mount(self.lock_line)
        side.mount(Static(common.ENCRYPT_WORDS, classes="muted"))
        box.mount(hint(Checkbox("Use a different passphrase from my password", self.a.get("separate_passphrase", False), id="separate"),
                       "Off: your password unlocks the disk too, one less thing to remember. On: the disk gets a passphrase of its own."))
        self.pp = Vertical(id="pp")
        box.mount(self.pp)
        self.lock_lit = True
        self._lock()
        if not self.reduced and not getattr(self, "_lock_timer", None):
            self._lock_timer = self.set_interval(1.1, self._lock_pulse)     # the Pulse: a slow breath while it's on
        self.call_later(self.fill_pp)

    def _lock(self):
        """The lock: shut and glowing while encryption is on, open and dim when it's off."""
        on = bool(self.a["encrypt"])
        if BT is not None and hasattr(BT, "lock"):
            self.lock_art.update(BT.lock(on, self.lock_lit, 14, 8))
        else:
            self.lock_art.display = False
        words = (("On. The disk opens only with its passphrase, typed at every start.", "ok") if on else
                 ("Off. Anyone with this disk in hand can read its files.", "warn"))
        if BT is not None:
            self.lock_line.set(*words)
        else:
            self.lock_line.update(words[0])

    def _lock_pulse(self):
        if self.step != "encryption" or not self.a["encrypt"] or self.reduced:
            return
        self.lock_lit = not getattr(self, "lock_lit", True)
        try:
            self._lock()
        except Exception:
            pass

    async def fill_pp(self):
        async with self.redraw:
            await self._fill_pp()

    async def _fill_pp(self):
        await self.pp.remove_children()
        if not self.a["encrypt"]:
            return
        self.pp_meter = Static("", classes="meter")
        if self.a.get("separate_passphrase"):
            self.pp.mount(Horizontal(Vertical(self.flabel("key", "Disk passphrase"),
                                              hint(Input(self.a.get("passphrase", ""), password=True, id="passphrase"),
                                                   "The passphrase you'll type at every start."), classes="field"),
                                     Vertical(self.flabel("key", "Passphrase again"),
                                              hint(Input(self.a.get("passphrase", ""), password=True, id="passphrase2"),
                                                   "The same passphrase once more."), classes="field"), classes="fields"),
                          self.pp_meter)
            self._strength(self.pp_meter, self.a.get("passphrase", ""), "passphrase")
        else:
            self.pp.mount(Static(Text.assemble((ic("key") + "  ", col("primary")), "Your password unlocks the disk. How strong it is:"),
                                 classes="vlabel"), self.pp_meter)
            self._strength(self.pp_meter, self.a.get("password", ""), "password")

    @on(Input.Changed, "#passphrase")
    def pp_typed(self, ev):
        if getattr(self, "pp_meter", None):
            self._strength(self.pp_meter, ev.value, "passphrase")

    @on(Switch.Changed, "#encrypt")
    def enc_changed(self, ev):
        self.a["encrypt"] = ev.value
        self.lock_lit = True
        self._lock()
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

    # ── Ready to install: the briefing ─────────────────────────────────────────────────
    BRIEF_STEP = {"Kind": "edition", "Language": "guide", "Time zone": "welcome", "Keyboard": "keyboard", "Disk": "disk",
                  "Boot menu": "disk", "Name": "user", "User name": "user", "Computer name": "user", "Encryption": "encryption",
                  "Remote access (SSH)": "ssh", "Firewall": "ssh", "Automatic updates": "ssh", "Packages": "edition"}
    BRIEF_TITLE = {"guide": ("Language", "language"), "welcome": ("Time zone", "clock"), "edition": ("Kind", "edition"), "keyboard": ("Keyboard", "keyboard"),
                   "disk": ("Where", "disk"), "user": ("You", "user"), "encryption": ("Encryption", "encryption"),
                   "ssh": ("Remote access", "ssh"), None: ("Packages", "copy")}

    def briefing(self):
        """The summary's rows, grouped by the step that changes them: [(step or None, [(label, value)])]."""
        rows, warn = common.summary(self.a, self.disk())
        steps = self.steps()
        groups = []
        for k, v in rows:
            sid = self.BRIEF_STEP.get(k)
            if sid == "encryption" and "encryption" not in steps:
                sid = "disk"                      # a reinstall keeps the disk's encryption: the Where step decides
            if sid not in steps:
                sid = None
            g = next((g for g in groups if g[0] == sid), None)
            if g is None:
                groups.append((sid, [(k, v)]))
            else:
                g[1].append((k, v))
        return groups, warn

    def build_summary(self, box):
        self.heading(box, "summary")
        groups, warn = self.briefing()
        panel = Vertical(id="briefing")
        box.mount(panel)
        head = Text(no_wrap=True, overflow="ellipsis")
        head.append(ic("summary") + "  BRIEFING", style="bold " + col("primary"))
        head.append(f"   {len(groups)} parts · Change any of them, or press Install", style=col("muted"))
        panel.mount(Static(head, classes="panel-head"))
        self.brief_keys = {}
        wide = getattr(self, "bp", "normal") in ("wide", "normal")     # the title beside its rows; else above them
        n = 0
        from rich.table import Table
        keyw = max(len(k) for _, items in groups for k, _ in items)
        panel.set_class(self.size.height < 40, "-tight")       # a short screen: the rows close up
        for sid, items in groups:
            title, icon_name = self.BRIEF_TITLE.get(sid, (sid or "Packages", "copy"))
            if sid:
                n += 1
                self.brief_keys[str(n)] = sid
            head = Text.assemble((ic(icon_name) + " ", "bold " + col("primary")), (title.upper(), "bold " + col("soft")))
            tb = Table.grid(padding=(0, 2), expand=True)
            if wide:
                tb.add_column(width=15, no_wrap=True)
            tb.add_column(no_wrap=True, width=keyw if wide else None)
            tb.add_column(ratio=1)
            if not wide:
                tb.add_row(head, "")
            for i, (k, v) in enumerate(items):
                cells = [Text(k if k.lower() != title.lower() else "", style=col("muted")), Text(v, style=col("text"))]
                tb.add_row(*(([head if i == 0 else ""] if wide else []) + cells))
            parts = [Static(tb, classes="brief-text")]
            if sid:
                what = {"guide": "the language", "welcome": "the time zone", "edition": "what kind of computer this is",
                        "keyboard": "the keyboard layout", "disk": "the disk and how bromigOS goes on it",
                        "user": "your name, user name, password or the computer's name", "encryption": "the disk's encryption",
                        "ssh": "remote access, the firewall and updates"}.get(sid, title)
                parts.append(hint(Button("Change" if self.narrow() else f"Change {n}", id=f"edit-{sid}"),
                                  f"Go back and change {what} (or press {n}). Continue brings you back here."))
            panel.mount(Horizontal(*parts, classes="brief-row"))
        if warn:
            box.mount(Static(Text.assemble((ic("alert") + "  ", "bold"), warn), classes="danger" if self.a["mode"] == "erase" else "warn"))
        self.what = Static("Open this to see the commands and archinstall's configuration.", classes="muted")
        box.mount(hint(Collapsible(self.what, title="Show what will run", collapsed=True, id="what"),
                       "The exact commands, and the configuration archinstall gets (passwords hidden)."))

    async def jump(self, sid):
        """From the summary to one step, to change it; Continue comes back (through any step
        the change brought in that hasn't been seen yet)."""
        if self.step != "summary" or sid not in self.steps():
            return
        await self.show(sid)
        self.from_summary = True
        nxt = self.query_one("#next", Button)
        nxt.label = "Back to summary"
        hint(nxt, "Keep this and go back to the summary (Ctrl+N).")

    async def action_brief(self, key):
        sid = getattr(self, "brief_keys", {}).get(key)
        if self.step == "summary" and sid:
            await self.jump(sid)

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
        self.last_pct = pct
        if BT is not None and hasattr(BT, "ring") and getattr(self, "bp", "normal") != "narrow":
            self.ring.update(self.ring_art(pct, small))
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

    def ring_art(self, pct, small, failed=False):
        """The emblem's ring filled to `pct` in braille, the number under it; where braille can't
        show (the Linux console, ASCII), the number in block letters. Red when it stopped."""
        if look() == "nerd":
            colors = (col("dim"), col("danger"), "bold " + col("danger")) if failed else None
            r = BT.ring(pct, 10 if small else 16, 5 if small else 8, colors=colors)
            r.append(f"\n{pct:>{(10 if small else 16) // 2 + 2}} %", style="bold " + col("danger" if failed else "primary"))
            return r
        r = BT.big_code(f"{pct}%", style="bold " + col("danger" if failed else "primary"))
        r.append("\n" + ("stopped" if failed else "done").center(len(str(r).split("\n")[0])), style=col("muted"))
        return r

    def build_done(self, box):
        if self.done is True:
            art = BT.emblem_text(spark=not self.reduced, wide=getattr(self, "bp", "normal") not in ("compact", "narrow")) \
                if BT is not None else Text(WORDMARK)
            side = self.hero(box, "done", art)
            if not self.reduced and BT is not None:
                # the Spark: the emblem glows once, about a second, then holds still
                self.set_timer(1.0, lambda: [w.update(BT.emblem_text(wide=getattr(self, "bp", "normal") not in ("compact", "narrow")))
                                             for w in box.query("#hero-art")])
            ed = common.edition(self.a["edition"])
            lines = [("usb", "When the screen goes dark, take out the USB stick.")]
            sb = common.secureboot_steps(backend.SECUREBOOT_CODE)
            if sb:
                lines.append(("shield", f"At the first start, approve bromigOS on the blue screen with the code {sb['code']} "
                                        "(the steps are below)."))
            if self.a["encrypt"]:
                lines.append(("lock", "At start, type the disk's passphrase" +
                              (" (your password)." if not self.a.get("separate_passphrase") else ".")))
            if self.a["mode"] == "alongside":
                lines.append(("boot", "The boot menu lets you choose bromigOS or "
                              f"{(self.disk() or {}).get('options', {}).get('alongside', {}).get('name') or 'the other system'} each time."))
            lines.append(("user", "Then sign in at the login screen." if ed.get("desktop", True) else "Then sign in at the text console."))
            side.mount(Static(icon_rows(lines), classes="card"))
            side.mount(Horizontal(hint(Button("Restart now", id="reboot", variant="primary"), "Restart the computer into bromigOS."),
                                  classes="buttons"))
            if sb:
                # Secure Boot's one-time approval: the code big, the blue screen's steps in order
                code = BT.big_code(sb["code"]) if BT is not None else Text(sb["code"], style="bold")
                steps = Text()
                steps.append(sb["intro"] + "\n\n")
                for i, t in enumerate(sb["steps"], 1):
                    steps.append(f" {i} ", style="bold reverse " + col("primary"))
                    steps.append(f"  {t}\n")
                steps.append("\n" + sb["lost"], style=col("muted"))
                card = Vertical(id="mok", classes="card")
                box.mount(card)
                card.mount(Static(Text.assemble((ic("shield") + "  " + sb["title"].upper(), "bold " + col("primary"))), id="mok-head"),
                           Horizontal(hint(Static(code, id="mok-code"), "Type this on the blue screen at the first start. It's needed once."),
                                      Static(steps, id="mok-steps"), id="mok-row"))
        else:
            pct = int(getattr(self, "last_pct", 0) or 0)
            row = Horizontal(id="count-row")
            box.mount(row)
            if BT is not None and hasattr(BT, "ring") and not self.narrow():
                row.mount(Static(self.ring_art(pct, getattr(self, "bp", "normal") == "compact", failed=True), id="count"))
            side = Vertical(id="count-side")
            row.mount(side)
            head = Text.assemble((ic("alert") + "  THE INSTALL DIDN'T FINISH", "bold " + col("danger")))
            side.mount(Static(head, classes="fail-head"),
                       Static(Text.assemble(("━" * 26 if look() != "ascii" else "=" * 26, col("danger")))))
            side.mount(Static(self.done or "The install stopped.", classes="card"))
            side.mount(Static(icon_rows((("summary", "Back to the summary: change something if you like, and try again."),
                                         ("usb", "Save a problem report: the logs on a USB drive, to send when you ask for help."),
                                         ("shell", "F12 opens a shell, to look around yourself.")), style=col("muted"))))
            box.mount(Horizontal(hint(Button("Back to the summary", id="retry", variant="primary"),
                                      "Go back, change something if you like, and try the install again."),
                                 hint(Button("Save a problem report", id="report"),
                                      "Put the install's logs, a hardware summary and your answers (without passwords) on a USB "
                                      "drive, to send when you ask for help."),
                                 hint(Button("Show details", id="details"), "Every step the install took, and where it stopped (F2)."),
                                 classes="buttons"))
            self.report_line = BT.Reading("", "idle") if BT is not None else Static("")
            self.report_line.display = False
            box.mount(self.report_line)
            self.log_view = RichLog(id="log", wrap=True, max_lines=4000)
            box.mount(self.log_view)
            for line in getattr(self, "lines", [])[-400:]:
                self.log_view.write(line)

    @work(thread=True)
    def save_report(self):
        def say(words, state):
            self.report_line.display = True
            if BT is not None:
                self.report_line.set(words, state)
            else:
                self.report_line.update(words)
        self.call_from_thread(say, "Saving the report…", "busy")
        path, words = common.save_report(self.a)
        self.call_from_thread(say, words, "ok" if path else "warn")

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
        elif s == "bitlocker" and not self.a.get("bitlocker_saved"):
            return "Save the BitLocker recovery key first, then turn on I've saved the BitLocker recovery key."
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
        if getattr(self, "from_summary", False):
            # back to the summary, unless the change brought in a step not seen yet
            ahead = steps[steps.index(self.step) + 1: steps.index("summary")] if "summary" in steps else []
            new = [s for s in ahead if s not in getattr(self, "visited", set())]
            await self.show(new[0] if new else "summary")
            if new:
                self.from_summary = True
            return
        await self.show(steps[steps.index(self.step) + 1])

    async def action_back(self):
        steps = self.steps()
        if self.voice:
            self.voice.stop()                    # Esc and Back quiet him: the step before isn't read again
        if self.step in steps and steps.index(self.step) > 0 and self.step not in ("install", "done"):
            prev = steps[steps.index(self.step) - 1]
            lid, values = self.line_id(prev)
            self._spoken = (lid, tuple(sorted(values.items())))
            await self.show(prev)

    def action_details(self):
        if hasattr(self, "log_view"):
            self.log_view.toggle_class("shown")

    def action_quit_ask(self):
        if self.running:
            self.error("▲ The install is running. Leaving now would leave the disk half done: wait for it to finish.")
            return
        if self.voice:
            self.voice.stop()
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
        elif bid == "g-sample":
            if self.voice and not self.voice.play("installer.guide.sample", force=True):
                self._guide_said("VECTOR stays quiet while your screen reader talks." if self.voice.screen_reader()
                                 else self.voice.notice or self.voice.describe(), "warn")
            elif self.voice:
                self._guide_said("Playing a sample of VECTOR's voice.", "ok")
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
            await self.show(self.first_step())
        elif bid == "adv-menu":
            await self.partition_myself()
        elif bid == "rescan-keys":
            self.a["found_keys"] = common.stick_keys()
            self.a["ssh_keys"] = sorted(set(self.a["ssh_keys"]) | {k for _, k in self.a["found_keys"]})
            self.call_later(self.fill_ssh)
        elif bid == "retry":
            self.done = False
            await self.show("summary")
        elif bid == "report":
            self.save_report()
        elif bid and bid.startswith("edit-"):
            await self.jump(bid.removeprefix("edit-"))

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
