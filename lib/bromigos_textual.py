"""DRIFTGLASS for Python terminal apps built on Textual (docs/DRIFTGLASS.md): the theme's
colours from the same source as everything else (bromigos_theme: palette.json; the Rust
TUIs read the same file), in truecolour where the terminal has it and as a 16-colour
mapping on a bare Linux console, plus the building blocks every bromigOS terminal screen
uses: Glass panels, the Emitter under a heading, the Sweep over a progress bar, a Reading
for a status, and the burn-in emblem (the screen's one FLARE).

  import bromigos_textual as BT
  app.register_theme(BT.theme()); app.theme = "bromigos"
  CSS = BT.CSS + "…"                       # .glass, .glass-hot, Emitter, Sweep, Reading
  Emitter("WHERE TO INSTALL")               # a heading on its glowing base
  Sweep(total=100)                          # a progress bar; .update(progress=N)
  Reading("Copying bromigOS", state="busy") # ok | busy | warn | fail
  BT.emblem()                               # the emblem as text (braille in truecolour,
                                            # the wordmark on a 16-colour console)

Motion follows the user's setting (bromigos_theme.motion(); BROMIGOS_REDUCED_MOTION=1, or
the boot's accessibility=on): reduced or still, nothing sweeps or pulses.
"""
import colorsys
import os
import sys

sys.path.insert(0, "/usr/lib/bromigos/lib")
try:
    import bromigos_theme as T
except ImportError:
    T = None

WICK = {"background": "#000500", "void": "#000500", "panel": "#001300", "selection": "#003b00",
        "primary": "#39ff14", "soft": "#9cff8a", "dim": "#159b09", "text": "#c4f5bb", "muted": "#7e927e",
        "faint": "#4e6b4e", "warn": "#d4af37", "danger": "#ff766f", "cyan": "#3fe0c5", "gold": "#f0d36a"}
WORDMARK = """\
 ██████  ██████   ██████  ███    ███ ██  ██████   ██████  ███████
 ██   ██ ██   ██ ██    ██ ████  ████ ██ ██       ██    ██ ██
 ██████  ██████  ██    ██ ██ ████ ██ ██ ██   ███ ██    ██ ███████
 ██   ██ ██   ██ ██    ██ ██  ██  ██ ██ ██    ██ ██    ██      ██
 ██████  ██   ██  ██████  ██      ██ ██  ██████   ██████  ███████"""
EMBLEMS = ["/usr/share/bromigos/themes/{theme}/emblem/emblem.braille", "/usr/share/bromigos/themes/wick/emblem/emblem.braille",
           "/usr/local/share/bromigos-iso/emblem.braille"]
TRUECOLOR_TERMS = ("xterm-kitty", "kitty", "foot", "foot-extra", "alacritty", "wezterm", "xterm-ghostty", "ghostty",
                   "xterm-direct", "tmux-direct", "kmscon")


def palette():
    """The theme's roles, resolved (the Wick's without bromigos-core)."""
    c = dict(WICK)
    if T is not None:
        try:
            T.version()
            c.update(T.colors())
        except Exception:
            pass
    return c


def motion():
    if os.environ.get("BROMIGOS_REDUCED_MOTION"):
        return "reduced"
    try:
        if "accessibility=on" in open("/proc/cmdline").read():
            return "reduced"
    except OSError:
        pass
    if T is not None:
        try:
            return T.motion()
        except Exception:
            pass
    return "full"


def color_mode(env=None):
    """truecolor, 256 or 16: what this terminal shows. A bare Linux console has 16; kmscon,
    kitty, foot and friends (and anything that says COLORTERM=truecolor, SSH and herdr
    passing it on) have truecolour. BROMIGOS_COLORS=16|256|truecolor decides it outright."""
    env = os.environ if env is None else env
    forced = env.get("BROMIGOS_COLORS")
    if forced in ("16", "256", "truecolor"):
        return forced
    term = env.get("TERM", "")
    if term in ("linux", "vt100", "vt102", "vt220", "dumb") or term.startswith("vt"):
        return "16"
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit") or term in TRUECOLOR_TERMS or term.endswith("-direct"):
        return "truecolor"
    return "256"


def prepare_terminal(env=None):
    """Tell Textual what the terminal has (it reads COLORTERM): truecolour where we know it is."""
    env = os.environ if env is None else env
    mode = color_mode(env)
    if mode == "truecolor":
        env["COLORTERM"] = "truecolor"
    return mode


def _ansi_hue(h):
    """The 16-colour console's name nearest a colour's hue."""
    r, g, b = (int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    if sat < 0.15:
        return "white"
    deg = hue * 360
    for name, lo, hi in (("red", 0, 20), ("yellow", 20, 70), ("green", 70, 160), ("cyan", 160, 200),
                         ("blue", 200, 260), ("magenta", 260, 330), ("red", 330, 361)):
        if lo <= deg < hi:
            return name
    return "green"


def ansi16(c=None):
    """The theme's roles as the console's 16 colours: the primary's hue, bright for what
    glows (primary, the heading, the selection's text), plain for the dim, so the Wick reads
    as phosphor green on black and a world theme keeps its own hue."""
    c = c or palette()
    hue = _ansi_hue(c["primary"])
    return {"primary": f"ansi_bright_{hue}", "secondary": f"ansi_{hue}", "accent": f"ansi_bright_{_ansi_hue(c['cyan'])}",
            "warning": "ansi_bright_yellow", "error": "ansi_bright_red", "success": f"ansi_bright_{hue}",
            "foreground": "ansi_white", "background": "ansi_black", "surface": "ansi_black", "panel": f"ansi_{hue}"}


def theme(mode=None, name="bromigos"):
    """A Textual theme from the palette: hex colours, or the 16-colour mapping."""
    from textual.theme import Theme
    c = palette()
    mode = mode or color_mode()
    if mode == "16":
        a = ansi16(c)
        return Theme(name=name, dark=True, **a)
    return Theme(name=name, primary=c["primary"], secondary=c["soft"], accent=c["cyan"], warning=c["warn"],
                 error=c["danger"], success=c["primary"], foreground=c["text"], background=c["background"],
                 surface=c["panel"], panel=c["selection"], dark=True)


def emblem(mode=None):
    """The burn-in emblem as text: the theme's braille art in truecolour (ANSI colour codes
    in it), the wordmark on a 16-colour console (its font has no braille)."""
    mode = mode or color_mode()
    if mode != "16":
        theme_name = T.name() if T is not None else "wick"
        for p in EMBLEMS:
            p = p.format(theme=theme_name)
            if os.path.exists(p):
                with open(p) as f:
                    return f.read(), True
    return WORDMARK, False


# Layout breakpoints, the same for every bromigOS terminal screen (Field Kit's Rust widgets
# use these widths too): wide consoles, a normal terminal, 80×24 (a VT, a serial line) and
# a phone's SSH or BRODEC window (50–60 columns). Below MIN, a screen asks to be made bigger.
BREAKPOINTS = (("wide", 150), ("normal", 110), ("compact", 80), ("narrow", 0))
MIN_COLS, MIN_ROWS = 40, 15


def breakpoint(cols):
    """wide (≥150), normal (110–149), compact (80–109) or narrow (<80)."""
    return next(name for name, at in BREAKPOINTS if cols >= at)


def too_small(cols, rows):
    return cols < MIN_COLS or rows < MIN_ROWS


TOO_SMALL_WORDS = f"Make the window bigger: this needs at least {MIN_COLS}×{MIN_ROWS} characters."

# CSS classes a screen gets for its breakpoint (Screen.-wide, .-normal, .-compact, .-narrow,
# .-too-small): the apps' CSS hangs their layouts on them
BREAKPOINT_CLASSES = ["-wide", "-normal", "-compact", "-narrow", "-too-small"]


def apply_breakpoint(screen, cols, rows):
    """Set the screen's breakpoint classes; returns the breakpoint (or "too-small")."""
    bp = "too-small" if too_small(cols, rows) else breakpoint(cols)
    for c in BREAKPOINT_CLASSES:
        screen.set_class(c == f"-{bp}", c)
    if bp == "too-small":
        screen.set_class(True, f"-{breakpoint(cols)}")
    return bp


def rich16(role):
    """A role's 16-colour console name, as Rich writes it (bright_green, green, …)."""
    return ansi16().get(role, "ansi_white").removeprefix("ansi_")


CSS = """
#too-small { display: none; dock: top; width: 100%; height: 100%; content-align: center middle;
             text-align: center; background: $background; color: $warning; text-style: bold; padding: 1 2; }
Screen.-too-small #too-small { display: block; layer: overlay; }
.glass { border: round $secondary 60%; background: $surface 85%; padding: 0 1; height: auto; }
.glass-hot { border: round $primary; }
Emitter { height: auto; margin-bottom: 1; }
Sweep { height: 1; margin: 1 0 0 0; }
Reading { height: auto; }
"""

try:
    from rich.text import Text
    from textual.reactive import reactive
    from textual.widget import Widget

    class Emitter(Widget):
        """A heading on its glowing base: the words in the primary colour over a rule that
        is brightest under them and fades out (DRIFTGLASS's Emitter)."""

        def __init__(self, words, **kw):
            super().__init__(**kw)
            self.words = words

        def render(self):
            c = palette()
            w = max(len(self.words) + 4, self.size.width or 40)
            sixteen = color_mode() == "16"
            t = Text(self.words.upper(), style="bold " + (rich16("primary") if sixteen else c["primary"]))
            t.append("\n")
            n = len(self.words)
            if sixteen:
                t.append("━" * n, style="bold " + rich16("primary"))
                t.append("─" * max(0, min(w - n, 24)), style=rich16("secondary"))
            else:
                t.append("━" * n, style=c["primary"])
                for i, ch in enumerate("━━──────────────────────"[: max(0, w - n)]):
                    t.append(ch, style=c["dim"] if i < 6 else c["faint"])
            return t

    class Sweep(Widget):
        """A progress bar with the Sweep: a soft band that runs along the part still to do
        while the work goes on (still with reduced motion)."""
        progress = reactive(0.0)
        phase = reactive(0)

        def __init__(self, total=100, **kw):
            super().__init__(**kw)
            self.total = total
            self.still = motion() != "full"

        def on_mount(self):
            if not self.still:
                self.set_interval(0.08, self._tick)

        def _tick(self):
            if 0 < self.progress < self.total:
                self.phase = (self.phase + 1) % 1000

        def update(self, progress=None, total=None):
            if total is not None:
                self.total = total
            if progress is not None:
                self.progress = float(progress)

        def render(self):
            c = palette()
            sixteen = color_mode() == "16"
            w = max(10, (self.size.width or 60) - 7)
            frac = max(0.0, min(1.0, self.progress / (self.total or 1)))
            done = int(w * frac)
            t = Text()
            t.append("█" * done, style=("bold " + rich16("primary")) if sixteen else c["primary"])
            rest = w - done
            band = (self.phase % max(1, rest + 6)) - 3 if not self.still and 0 < frac < 1 else -99
            for i in range(rest):
                d = abs(i - band)
                ch, st = ("▓", c["soft"]) if d == 0 else (("▒", c["dim"]) if d == 1 else ("░", c["faint"]))
                t.append(ch, style=rich16("secondary") if sixteen else st)
            t.append(f" {frac * 100:3.0f}%", style="bold")
            return t

    class Reading(Widget):
        """A status that glows only with what it means (DRIFTGLASS's Reading): a dot and the
        words, the dot breathing while busy (the Pulse; still with reduced motion)."""
        words = reactive("")
        state = reactive("busy")
        lit = reactive(True)
        COLOR = {"ok": "primary", "busy": "cyan", "warn": "warn", "fail": "danger", "idle": "muted"}

        def __init__(self, words="", state="busy", **kw):
            super().__init__(**kw)
            self.words, self.state = words, state
            self.still = motion() != "full"

        def on_mount(self):
            if not self.still:
                self.set_interval(0.9, lambda: setattr(self, "lit", not self.lit) if self.state == "busy" else None)

        def set(self, words, state=None):
            self.words = words
            if state:
                self.state = state

        def render(self):
            c = palette()
            col = c[self.COLOR.get(self.state, "muted")]
            sixteen = color_mode() == "16"
            dot = "●" if (self.lit or self.state != "busy") else "○"
            if sixteen:
                col16 = {"ok": rich16("primary"), "busy": rich16("accent"), "warn": "bright_yellow",
                         "fail": "bright_red"}.get(self.state, "white")
                t = Text(dot + " ", style="bold " + col16)
                t.append(self.words, style=col16 if self.state != "busy" else "white")
                return t
            t = Text(dot + " ", style="bold " + col)
            t.append(self.words, style=col if self.state != "busy" else c["text"])
            return t
except ImportError:      # no Textual: the colours and the emblem still work
    pass
