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
import math
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
           "/usr/local/share/bromigos-iso/emblem.braille",
           os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "themes", "wick", "emblem", "emblem.braille")]
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


# ── icons: a Nerd Font glyph where the terminal has one, else the console's, else ASCII
#    (the same table as Field Kit's core/crates/bromigos-tui/src/icons.rs) ─────────────────
ICONS = {
    "welcome": ("\uf024", "►", ">"), "checks": ("\uf132", "Θ", "s"), "edition": ("\uf108", "◘", "@"),
    "keyboard": ("\uf11c", "≡", "k"), "disk": ("\uf0a0", "■", "o"), "bitlocker": ("\uf084", "§", "k"),
    "user": ("\uf007", "☺", "u"), "encryption": ("\uf023", "§", "L"), "ssh": ("\uf233", "≡", "="),
    "summary": ("\uf0ae", "≡", "="), "install": ("\uf019", "↓", "v"), "done": ("\uf00c", "✓", "+"),
    "auto": ("\uf01e", "↕", "a"), "network": ("\uf1eb", "≈", "~"), "vector": ("\uf27a", "♦", "V"),
    "lab": ("\uf0c3", "Φ", "%"), "phone": ("\uf10b", "▌", "p"), "tour": ("\uf02d", "¶", "?"),
    "server": ("\uf233", "≡", "="), "desktop": ("\uf108", "◘", "@"), "windows": ("\uf17a", "W", "W"),
    "linux": ("\uf17c", "L", "L"), "bromigos": ("\uf06d", "▲", "*"), "chip": ("\uf2db", "∩", "c"),
    "usb": ("\uf287", "▬", "u"), "check": ("\uf00c", "✓", "+"), "cross": ("\uf00d", "✗", "x"),
    "alert": ("\uf071", "‼", "!"), "erase": ("\uf12d", "×", "e"), "split": ("\uf0db", "║", "|"),
    "recovery": ("\uf1da", "←", "<"), "free": ("\uf067", "+", "+"), "power": ("\uf011", "Ø", "0"),
    "boot": ("\uf0e7", "↑", "b"), "people": ("\uf0c0", "☺", "u"), "copy": ("\uf019", "↓", "v"),
    # the same glyphs as Field Kit's icons.rs for the same things
    "key": ("\uf084", "§", "k"), "lock": ("\uf023", "§", "L"), "unlock": ("\uf09c", "○", "U"), "clock": ("\uf017", "°", ":"),
    "info": ("\uf05a", "•", "i"), "edit": ("\uf040", "±", "e"), "shell": ("\uf120", "»", ">"), "wired": ("\uf1e6", "↔", "="),
    "wifi": ("\uf1eb", "≈", "~"), "nonet": ("\uf05e", "×", "x"), "remote": ("\uf1cd", "∞", "r"), "update": ("\uf021", "↕", "u"),
    "settings": ("\uf013", "*", "s"), "search": ("\uf002", "?", "?"), "shield": ("\uf132", "Θ", "s"),
    "language": ("\uf1ab", "α", "a"), "idcard": ("\uf2c2", "■", "#"), "computer": ("\uf108", "◘", "@"),
    "cloud": ("\uf0c2", "≈", "~"), "book": ("\uf02d", "¶", "?"), "rollback": ("\uf1da", "←", "<"), "fieldkit": ("\uf0b1", "►", "*"),
}


def icon_look(env=None):
    """nerd, console or ascii: BROMIGOS_ICONS decides, else Nerd glyphs in truecolour (kmscon
    carries Symbols Nerd Font, desktop terminals a Nerd Font), the console's own on 16 colours."""
    env = os.environ if env is None else env
    forced = env.get("BROMIGOS_ICONS")
    if forced in ("nerd", "console", "ascii"):
        return forced
    return "nerd" if color_mode(env) == "truecolor" else "console"


def icon(name, look=None):
    g = ICONS.get(name, ("•", "•", "*"))
    return g[{"nerd": 0, "console": 1, "ascii": 2}[look or icon_look()]]


# ── braille drawing: VECTOR's orb, the emblem ring, the holograms ────────────────────────
class Dots:
    """A braille canvas, `w` cells by `h` (2×4 dots a cell); a cell glows if any dot in it
    was drawn hot."""
    BITS = {(0, 0): 1, (0, 1): 2, (0, 2): 4, (1, 0): 8, (1, 1): 16, (1, 2): 32, (0, 3): 64, (1, 3): 128}

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.dots = [0] * (w * h)
        self.hot = [0] * (w * h)       # 0 cold, 1 lit, 2 hot

    def put(self, x, y, heat=1):
        x, y = int(round(x)), int(round(y))
        if 0 <= x < self.w * 2 and 0 <= y < self.h * 4:
            i = (y // 4) * self.w + x // 2
            self.dots[i] |= self.BITS[(x % 2, y % 4)]
            self.hot[i] = max(self.hot[i], heat)

    def line(self, x0, y0, x1, y1, heat=1):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for k in range(n + 1):
            self.put(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, heat)

    def rect(self, x0, y0, x1, y1, heat=1):
        for a, b, c, d in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
            self.line(a, b, c, d, heat)

    def ellipse(self, cx, cy, rx, ry, heat=1, step=4):
        for i in range(0, 360, step):
            a = math.radians(i)
            self.put(cx + rx * math.cos(a), cy + ry * math.sin(a), heat)

    def text(self, colors):
        """Rich Text: colors = (cold, lit, hot) styles."""
        out = Text()
        for r in range(self.h):
            for col in range(self.w):
                i = r * self.w + col
                ch = chr(0x2800 + self.dots[i]) if self.dots[i] else " "
                out.append(ch, style=colors[self.hot[i]] if self.dots[i] else None)
            if r < self.h - 1:
                out.append("\n")
        return out


def styles(sixteen=None):
    c = palette()
    sixteen = color_mode() == "16" if sixteen is None else sixteen
    if sixteen:
        return (rich16("secondary"), rich16("primary"), "bold " + rich16("primary"))
    return (c["dim"], c["primary"], "bold " + c["soft"])


RING = ["  .-'''''-.  ", " /  .---.  \\ ", "|  ( (@) )  |", " \\  '---'  / ", "  '-.....-'  "]


def orb_plain(t=0.0):
    """The orb for the Linux console and ASCII (no braille in its font): Field Kit's plain
    ring, the scan lit where it is, the core breathing."""
    sweep = (t * 40) % 360
    big = math.sin(t * 3) >= 0
    hot, cold = ("bold " + rich16("primary"), rich16("secondary"))
    out = Text()
    for y, row in enumerate(RING):
        for x, ch in enumerate(row):
            dx, dy = x - 6, (y - 2) * 2.4
            if ch == "@":
                out.append("@" if big else "o", style=hot)
                continue
            a = math.degrees(math.atan2(dy, dx)) % 360
            lit = math.hypot(dx, dy) > 4.6 and ch != " " and (a - sweep) % 360 < 70
            out.append(ch, style=hot if lit else cold)
        if y < len(RING) - 1:
            out.append("\n")
    return out


def orb(t=0.0, w=14, h=7):
    """VECTOR's presence, the screen's one FLARE: a ring with a dashed inner ring and ticks, a
    scan arc going round and a pulsing core (Field Kit's orb, after the same mock-up). t stays
    0 under reduced motion. The Linux console (no braille in its font) gets the plain ring."""
    if icon_look() != "nerd":
        return orb_plain(t)
    d = Dots(w, h)
    cx, cy = w - 0.5, h * 2 - 0.5
    rad = min(cx, cy * 0.95)
    k = rad / 21.5
    for i in range(0, 360, 2):
        a = math.radians(i)
        d.put(cx + rad * math.cos(a), cy + rad * math.sin(a))
        if i % 6 < 3:
            d.put(cx + (rad - 6 * k) * math.cos(a), cy + (rad - 6 * k) * math.sin(a))
        if i % 30 == 0:
            for dd in (1, 2):
                d.put(cx + (rad - dd) * math.cos(a), cy + (rad - dd) * math.sin(a))
    sweep = (t * 40) % 360
    for i in range(70):
        a = math.radians(sweep + i)
        for dd in (0, 1):
            d.put(cx + (rad - dd) * math.cos(a), cy + (rad - dd) * math.sin(a), 2)
    pulse = (6 + 1.5 * math.sin(t * 3)) * k
    for yy in range(h * 4):
        for xx in range(w * 2):
            r = math.hypot(xx - cx, yy - cy)
            if 2.2 * k < r < pulse:
                d.put(xx, yy, 2 if r > pulse - 1.2 * k else 1)
    return d.text(styles())


def ring(pct, w=18, h=9, t=0.0, colors=None):
    """The install's progress as the emblem's ring in braille: a faint track all round, the
    part done thick and lit, ticks every 30°, the flame at its heart."""
    d = Dots(w, h)
    cx, cy = w - 0.5, h * 2 - 0.5
    rad = min(cx, cy) - 0.5
    for i in range(0, 360, 2):
        a = math.radians(i - 90)
        lit = i / 360 <= pct / 100
        if lit:
            for dd in (0, 1, 2):
                d.put(cx + (rad - dd) * math.cos(a), cy + (rad - dd) * math.sin(a), 2 if dd == 0 else 1)
        elif i % 6 == 0:
            d.put(cx + rad * math.cos(a), cy + rad * math.sin(a), 0)
        if i % 30 == 0:
            d.put(cx + (rad - 4) * math.cos(a), cy + (rad - 4) * math.sin(a), 1 if lit else 0)
    k = rad / 16
    for (x0, y0, x1, y1) in ((0, -7, 4, 1), (4, 1, 0, 7), (0, 7, -4, 1), (-4, 1, 0, -7), (0, -2, 0, 5), (-2, 2, 2, 2)):
        d.line(cx + x0 * k, cy + y0 * k, cx + x1 * k, cy + y1 * k, 1)
    return d.text(colors or styles())


def holo(kind, w=20, h=8):
    """A hologram on its Emitter, drawn in braille: a desktop's monitor, or a server rack (in box
    lines where braille can't show: holo_plain)."""
    if icon_look() != "nerd":
        return holo_plain(kind)
    d = Dots(w, h)
    W, H = w * 2, h * 4
    cx = W / 2
    if kind == "server":
        x0, x1, y0, y1 = cx - W * 0.16, cx + W * 0.16, 1, H * 0.72
        d.rect(x0, y0, x1, y1, 1)
        n = 6
        for i in range(1, n):
            y = y0 + (y1 - y0) * i / n
            d.line(x0, y, x1, y, 1)
        for i in range(n):
            y = y0 + (y1 - y0) * (i + 0.5) / n
            d.put(x1 - 3, y, 2)
            d.put(x1 - 5, y, 2)
    else:
        x0, x1, y0, y1 = cx - W * 0.3, cx + W * 0.3, 1, H * 0.58
        d.rect(x0, y0, x1, y1, 1)
        d.rect(x0 + 2, y0 + 2, x1 - 2, y1 - 2, 0)
        for i in range(3):                      # a wave on the screen
            for xx in range(int(x0 + 4), int(x1 - 4)):
                d.put(xx, (y0 + y1) / 2 + math.sin((xx + i * 5) / 3) * 2 - 3 + i * 3, 2 if i == 1 else 0)
        d.line(cx, y1, cx, H * 0.72, 1)
        d.line(cx - W * 0.1, H * 0.72, cx + W * 0.1, H * 0.72, 1)
    d.ellipse(cx, H * 0.86, W * 0.32, H * 0.08, 2, 3)     # the Emitter
    d.ellipse(cx, H * 0.86, W * 0.2, H * 0.045, 1, 5)
    return d.text(styles())


def holo_plain(kind, look=None):
    """The hologram for the Linux console and ASCII (no braille in its font): a monitor or a
    server rack in box lines over its Emitter, the same size as holo()'s small one."""
    look = look or icon_look()
    a = look == "ascii"
    if kind == "server":
        top, mid, bot = ("+--------+", "+--------+", "+--------+") if a else ("╭────────╮", "├────────┤", "╰────────╯")
        unit = "| o o == |" if a else "│ ■ ■ ══ │"
        rows = [top, unit, mid, unit, mid, unit, bot]
    else:
        rows = (["+------------+", "| ~~~~~~~~~~ |", "| ~~~~~~~~~~ |", "+-----++-----+", "    --++--"] if a else
                ["╭────────────╮", "│ ≈≈≈≈≈≈≈≈≈≈ │", "│ ≈≈≈≈≈≈≈≈≈≈ │", "╰─────┬┬─────╯", "    ──┴┴──"])
    base = ("=" if a else "═") * 10
    rows.append(" " * ((max(len(r) for r in rows) - len(base)) // 2) + base)
    lit, cold = ("bold " + rich16("primary"), rich16("secondary")) if color_mode() == "16" else \
        ("bold " + palette()["primary"], palette()["dim"])
    out = Text()
    w = max(len(r) for r in rows)
    for i, r in enumerate(rows):
        pad = " " * ((w - len(r)) // 2) if i < len(rows) - 1 else ""
        out.append(pad + r, style=lit if i == len(rows) - 1 or r[:1] in "╭╰├+" else cold)
        if i < len(rows) - 1:
            out.append("\n")
    return out


def lock(on=True, lit=True, w=10, h=6):
    """The disk's lock in braille: the shackle shut and the body glowing while encryption is on
    (lit toggles: the Pulse), the shackle lifted open and dim when it's off. The Linux console
    and ASCII get lock_plain()."""
    if icon_look() != "nerd":
        return lock_plain(on, lit)
    d = Dots(w, h)
    W, H = w * 2, h * 4
    cx = W / 2 - 0.5
    body_top = H * 0.46
    lift = 0 if on else H * 0.16
    r = W * 0.24
    heat = 2 if (on and lit) else 1 if on else 0
    arc_y = H * 0.06 + r * 0.9 + 1 - lift
    for i in range(180, 361, 4):                       # the shackle's arc
        a = math.radians(i)
        for dd in (0, 1):
            d.put(cx + (r - dd) * math.cos(a), arc_y + (r - dd) * 0.9 * math.sin(a), heat)
    for side in (-1, 1):                               # its legs (the right one clear of the body when open)
        x = cx + side * (r - 0.5)
        end = body_top if (on or side < 0) else body_top - H * 0.12
        d.line(x, arc_y, x, end, heat)
    x0, x1, y1 = cx - W * 0.4, cx + W * 0.4, H - 1
    d.rect(x0, body_top, x1, y1, heat)
    d.rect(x0 + 1, body_top + 1, x1 - 1, y1 - 1, 1 if on else 0)
    ky = body_top + (y1 - body_top) * 0.42
    d.ellipse(cx, ky, 1.6, 1.6, 2 if on else 0, 30)
    d.line(cx, ky + 1.5, cx, ky + 5, 2 if on else 0)
    c = palette()
    st = styles() if on else (c["faint"], c["muted"], c["muted"])
    if on and not lit:
        st = (st[0], st[1], st[1])
    return d.text(st)


def lock_plain(on=True, lit=True, look=None):
    """The lock in box lines for the Linux console (and in ASCII): shut while encryption is on,
    open when it's off; the frame breathes (lit) while it's on."""
    look = look or icon_look()
    a = look == "ascii"
    if on:
        rows = ["         ", "  ╭───╮  ", "  │   │  ", "╭─┴───┴─╮", "│   •   │", "│   │   │", "╰───────╯"]
    else:
        rows = ["  ╭───╮  ", "  │   │  ", "  │      ", "╭─┴─────╮", "│   •   │", "│   │   │", "╰───────╯"]
    if a:
        tr = str.maketrans("╭╮╰╯─│┴•", "++++-|+o")
        rows = [r.translate(tr) for r in rows]
    sixteen = color_mode() == "16"
    c = palette()
    if on:
        frame = ("bold " + (rich16("primary") if sixteen else c["primary"])) if lit else (rich16("secondary") if sixteen else c["dim"])
    else:
        frame = "bright_black" if sixteen else c["faint"]
    out = Text()
    for i, r in enumerate(rows):
        out.append(r, style=frame)
        if i < len(rows) - 1:
            out.append("\n")
    return out


STRENGTH_COLOR = {1: "danger", 2: "warn", 3: "primary"}


def meter(level, levels=3, width=24, look=None):
    """A meter of `levels` segments in one row, built of background-coloured cells so it keeps
    one thickness in every terminal (the disk map's rule): the first `level` lit in what the
    level means (1 danger, 2 warn, 3 or more the primary), the rest a dark track (░ on the
    Linux console, . in ASCII, where a dark background wouldn't show)."""
    look = look or icon_look()
    level = max(0, min(levels, level))
    seg = max(2, (width - (levels - 1)) // levels)
    sixteen = color_mode() == "16"
    c = palette()
    role = STRENGTH_COLOR.get(min(level, 3), "primary")
    if sixteen:
        lit = {"danger": "red", "warn": "yellow", "primary": rich16("secondary")}[role]
    else:
        lit = c[role]
    out = Text(no_wrap=True)
    for i in range(levels):
        if i:
            out.append(" ")
        if i < level:
            out.append(" " * seg, style="on " + lit)
        elif look == "nerd" and not sixteen:
            out.append(" " * seg, style="on " + _dim(c["muted"]))
        else:
            out.append(("." if look == "ascii" else "░") * seg, style=rich16("secondary") if sixteen else c["faint"])
    return out


# the letter keys of the layouts the installer offers, by (xkb layout, variant): the strip on
# the keyboard step shows the right one and lights the key just typed
KEYROWS = {
    "qwerty": ("QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"), "qwertz": ("QWERTZUIOP", "ASDFGHJKL", "YXCVBNM"),
    "azerty": ("AZERTYUIOP", "QSDFGHJKLM", "WXCVBN"), "dvorak": ("',.PYFGCRL", "AOEUIDHTNS", ";QJKXBMWVZ"),
    "colemak": ("QWFPGJLUY;", "ARSTDHNEIO", "ZXCVBKM"),
}


def keyrows(layout, variant=""):
    """The letter rows for an xkb layout and variant, or None where they aren't Latin letters."""
    if variant in ("dvorak", "colemak"):
        return KEYROWS[variant]
    if layout in ("de", "ch", "at", "cz", "hu") and variant != "fr":
        return KEYROWS["qwertz"]
    if layout in ("fr", "be") or (layout == "ch" and variant == "fr"):
        return KEYROWS["azerty"]
    if layout in ("gr", "ru", "ua"):
        return None
    return KEYROWS["qwerty"]


def keycaps(rows, lit=None):
    """The letter keys as caps of background-coloured cells, each row set in like a keyboard's;
    `lit` (a letter) glows: the key just typed."""
    sixteen = color_mode() == "16"
    c = palette()
    cap, cap_lit = (("bold black on " + rich16("secondary")), "bold black on white") if sixteen else \
        (f"{c['text']} on {_dim(c['dim'])}", f"bold {c['background']} on {c['primary']}")
    out = Text(no_wrap=True)
    for r, keys in enumerate(rows):
        out.append(" " * (r * 2))
        for i, k in enumerate(keys):
            if i:
                out.append(" ")
            out.append(f" {k} ", style=cap_lit if lit and k == lit.upper() else cap)
        if r < len(rows) - 1:
            out.append("\n")
    return out


def emblem_text(spark=False, wide=True):
    """The emblem as Rich Text for a hero spot: the braille art where braille shows, else the
    wordmark (or, on a narrow screen, Field Kit's plain ring); `spark` lights all of it in the
    soft glow (the Spark: about a second after a success, never under reduced motion)."""
    text, ansi = emblem()
    sixteen = color_mode() == "16"
    c = palette()
    t = Text()
    if ansi:
        t = Text.from_ansi(text)
    else:
        t.append(text if wide else "\n".join(RING), style="bold " + (rich16("primary") if sixteen else c["primary"]))
    if spark:
        t.stylize("bold " + ("bright_white" if sixteen else c["soft"]))
    return t


def _dim(colour):
    """A colour's darker shade for the cells a side can't give up: a hex one mixed toward
    black; a console colour name becomes the console's grey."""
    if colour.startswith("#"):
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % (int(r * 0.42), int(g * 0.42), int(b * 0.42))
    return "bright_black"


def disk_map(segs, width, colors, split=None, erase=False, look=None):
    """The disk as a bar two rows tall, built only of background-coloured cells so it keeps
    one thickness in every terminal (kmscon, kitty, foot, the bare VT), and a marker row under
    it with each part's icon centred under its segment.

    segs: [(role, bytes, …)] in disk order. split: (lo, hi, value, total) GB for alongside,
    inside the 'windows' segment: what it keeps on the left, bromigOS on the right, the
    divider a full-height cell across both rows, each side's minimum a darker shade.
    erase: all bromigOS, with a danger edge. Returns Rich Text (three lines)."""
    look = look or icon_look()
    total = sum(s[1] for s in segs) or 1
    minw = 3
    big = [s for s in segs if s[1] / total * width >= minw]
    room = width - (len(segs) - len(big)) * minw
    bigsum = sum(s[1] for s in big) or 1
    cells, marks = [], []                  # cells: each column's background; marks: (column, icon, colour)
    if erase:
        cells = [colors["danger"]] + [colors["bromigos"]] * (width - 2) + [colors["danger"]]
        marks.append((width // 2, icon("bromigos", look), colors["bromigos"]))
        marks.append((0, icon("alert", look), colors["danger"]))
    else:
        widths = [minw if s not in big else max(minw, int(round(room * s[1] / bigsum))) for s in segs]
        widths[-1] += width - sum(widths)              # the rounding's leftover goes to the last
        x = 0
        for s, n in zip(segs, widths):
            role = s[0]
            if role == "windows" and split:
                lo, hi, value, tot = split
                cut = max(1, min(n - 2, int(round(n * value / tot))))
                lo_c, hi_c = int(round(n * lo / tot)), int(round(n * hi / tot))
                for i in range(n):
                    if i == cut:
                        cells.append(colors["text"])               # the divider: both rows
                    elif i < cut:
                        cells.append(_dim(colors["windows"]) if i < lo_c else colors["windows"])
                    else:
                        cells.append(_dim(colors["bromigos"]) if i >= hi_c else colors["bromigos"])
                marks.append((x + cut // 2, icon("windows", look), colors["windows"]))
                marks.append((x + cut, "^" if look == "ascii" else "▲", colors["text"]))
                marks.append((x + (cut + n) // 2, icon("bromigos", look), colors["bromigos"]))
            else:
                col = colors.get(role, colors["other"])
                cells += [col] * n
                ic = {"efi": "chip", "windows": "windows", "recovery": "recovery", "linux": "linux", "free": "free",
                      "msr": "chip", "bromigos": "bromigos"}.get(role)
                if ic and n >= 2:
                    marks.append((x + n // 2, icon(ic, look), col))
            x += n
    t = Text()
    for row in range(2):
        for col in cells[:width]:
            t.append(" ", style="on " + col)
        t.append("\n")
    line = [" "] * width
    styles_at = [None] * width
    for x, glyph, col in marks:                         # one glyph a column, nothing overlapping
        if 0 <= x < width and line[x] == " ":
            line[x], styles_at[x] = glyph, "bold " + col
    for ch, st in zip(line, styles_at):
        t.append(ch, style=st)
    return t


def phone_frame(qr_text, state="waiting", lit=True, tight=False):
    """The pairing QR inside a phone, drawn with box lines: the frame breathes while it waits
    (lit toggles: the Pulse), glows when paired with a ✓ in place of the code (the Spark);
    on its Emitter unless the screen is tight."""
    c = palette()
    sixteen = color_mode() == "16"
    if sixteen:
        frame = ("bold " + rich16("primary")) if (lit or state == "paired") else rich16("secondary")
        glow = "bold " + rich16("primary")
    else:
        frame = ("bold " + (c["soft"] if state == "paired" else c["primary"])) if lit else c["dim"]
        glow = "bold " + c["primary"]
    lines = (qr_text or "").split("\n") if state != "paired" else []
    width = max([len(x) for x in lines] + [24])
    if state == "paired":                         # a big ✓ in braille, and the word
        rows = 3 if tight else 6
        d = Dots(width, rows)
        W, H = width * 2, rows * 4
        cx = W / 2
        for off in (0, 1, 2):
            d.line(cx - H * 0.7, H * 0.5 + off, cx - H * 0.2, H * 0.9 + off, 2)
            d.line(cx - H * 0.2, H * 0.9 + off, cx + H * 0.8, H * 0.05 + off, 2)
        lines = [str(x) for x in d.text(("", "", "")).split()] + ["", "PAIRED".center(width)]
    t = Text()
    t.append("╭" + "─" * (width + 2) + "╮\n", style=frame)
    for ln in lines:
        t.append("│ ", style=frame)
        t.append(ln.ljust(width), style=glow if state == "paired" else None)
        t.append(" │\n", style=frame)
    t.append("╰" + "─" * (width + 2) + "╯", style=frame)
    if not tight:
        base = "▁▂▃▅▆▅▃▂▁"
        pad = (width + 4 - len(base)) // 2
        t.append("\n" + " " * pad + base, style=c["dim"] if not sixteen else rich16("secondary"))
    return t


# ── the pairing QR, scannable in every terminal ─────────────────────────────────────────
QUIET = 4          # modules of light all round: the standard's quiet zone


def qr_matrix(payload):
    """The QR's modules (True = dark) at error correction L (the smallest version for the
    payload), from qrencode, else python-qrcode; None when neither is there."""
    import subprocess
    try:
        r = subprocess.run(["qrencode", "-l", "L", "-m", "0", "-t", "ASCII", payload], capture_output=True,
                           text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return [[ln[i] == "#" for i in range(0, len(ln), 2)] for ln in r.stdout.rstrip("\n").split("\n")]
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        import qrcode
        q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=0)
        q.add_data(payload)
        q.make(fit=True)
        return [list(row) for row in q.get_matrix()]
    except Exception:
        return None


def qr_size(matrix):
    """(columns, rows) the QR takes as half blocks, quiet zone included."""
    n = len(matrix) + 2 * QUIET
    return n, (n + 1) // 2


def qr_text(matrix):
    """The QR as half blocks, two modules a cell: ▀ with the top module as the foreground
    and the bottom one as the background, both set in every cell (so no gap between lines
    can show), dark modules on light, with its quiet zone. Terminals draw ▀ themselves
    (kitty, foot, WezTerm, Alacritty, kmscon) and the console font has it."""
    n = len(matrix)
    size = n + 2 * QUIET
    dark_at = lambda r, c: 0 <= r - QUIET < n and 0 <= c - QUIET < n and matrix[r - QUIET][c - QUIET]   # noqa: E731
    sixteen = color_mode() == "16"
    # the Linux console has only 8 background colours: "white" (not bright) is one it can
    # paint as both halves, so the light modules are one even shade there
    dark, light = ("black", "white") if sixteen else ("#000000", "#ffffff")
    t = Text(no_wrap=True, overflow="crop")
    for r in range(0, size + (size % 2), 2):
        for c in range(size):
            top, bottom = dark_at(r, c), dark_at(r + 1, c)
            t.append("▀", style=f"{dark if top else light} on {dark if bottom else light}")
        if r + 2 < size + (size % 2):
            t.append("\n")
    return t


BIG = {   # a 3×5 block font for the pairing code, when the QR can't fit
    "A": ["███", "█ █", "███", "█ █", "█ █"], "B": ["██ ", "█ █", "██ ", "█ █", "██ "], "C": ["███", "█  ", "█  ", "█  ", "███"],
    "D": ["██ ", "█ █", "█ █", "█ █", "██ "], "E": ["███", "█  ", "██ ", "█  ", "███"], "F": ["███", "█  ", "██ ", "█  ", "█  "],
    "G": ["███", "█  ", "█ █", "█ █", "███"], "H": ["█ █", "█ █", "███", "█ █", "█ █"], "I": ["███", " █ ", " █ ", " █ ", "███"],
    "J": ["  █", "  █", "  █", "█ █", "███"], "K": ["█ █", "█ █", "██ ", "█ █", "█ █"], "L": ["█  ", "█  ", "█  ", "█  ", "███"],
    "M": ["█ █", "███", "███", "█ █", "█ █"], "N": ["██ ", "█ █", "█ █", "█ █", "█ █"], "O": ["███", "█ █", "█ █", "█ █", "███"],
    "P": ["███", "█ █", "███", "█  ", "█  "], "Q": ["███", "█ █", "█ █", "███", "  █"], "R": ["███", "█ █", "██ ", "█ █", "█ █"],
    "S": ["███", "█  ", "███", "  █", "███"], "T": ["███", " █ ", " █ ", " █ ", " █ "], "U": ["█ █", "█ █", "█ █", "█ █", "███"],
    "V": ["█ █", "█ █", "█ █", "█ █", " █ "], "W": ["█ █", "█ █", "███", "███", "█ █"], "X": ["█ █", "█ █", " █ ", "█ █", "█ █"],
    "Y": ["█ █", "█ █", " █ ", " █ ", " █ "], "Z": ["███", "  █", " █ ", "█  ", "███"], "0": ["███", "█ █", "█ █", "█ █", "███"],
    "1": [" █ ", "██ ", " █ ", " █ ", "███"], "2": ["███", "  █", "███", "█  ", "███"], "3": ["███", "  █", "███", "  █", "███"],
    "4": ["█ █", "█ █", "███", "  █", "  █"], "5": ["███", "█  ", "███", "  █", "███"], "6": ["███", "█  ", "███", "█ █", "███"],
    "7": ["███", "  █", "  █", "  █", "  █"], "8": ["███", "█ █", "███", "█ █", "███"], "9": ["███", "█ █", "███", "  █", "███"],
    "-": ["   ", "   ", "███", "   ", "   "], " ": ["   "] * 5, ".": [" ", " ", " ", " ", "█"],
    "%": ["█ █", "  █", " █ ", "█  ", "█ █"], ":": [" ", "█", " ", "█", " "],
}


def big_code(code, style=None, scale=1):
    """A code (the pairing code, an address, a countdown) in 3×5 block letters, for when it
    must be read from across the room; `scale` 2 doubles each block's width."""
    c = palette()
    style = style or ("bold " + (rich16("primary") if color_mode() == "16" else c["primary"]))
    rows = ["", "", "", "", ""]
    for ch in code.upper():
        g = BIG.get(ch, BIG[" "])
        for i in range(5):
            rows[i] += "".join(x * scale for x in g[i]) + " " * scale
    out = Text()                     # the style on the spans: a Text's base style loses ANSI colours in Textual
    out.append("\n".join(r.rstrip() for r in rows), style=style)
    return out


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
            t = Text()          # styles on the spans: a base style loses ANSI colours in Textual
            t.append(self.words.upper(), style="bold " + (rich16("primary") if sixteen else c["primary"]))
            t.append("\n")
            n = len(self.words)
            heavy, light = ("=", "-") if icon_look() == "ascii" else ("━", "─")
            if sixteen:
                t.append(heavy * n, style="bold " + rich16("primary"))
                t.append(light * max(0, min(w - n, 24)), style=rich16("secondary"))
            else:
                t.append(heavy * n, style=c["primary"])
                for i, ch in enumerate((heavy * 2 + light * 22)[: max(0, w - n)]):
                    t.append(ch, style=c["dim"] if i < 6 else c["faint"])
            return t

    class Sweep(Widget):
        """A progress bar with the Sweep: a soft band that runs along the part still to do
        while the work goes on (still with reduced motion)."""
        progress = reactive(0.0)
        phase = reactive(0)
        looking = reactive(False)

        def __init__(self, total=100, looking=False, **kw):
            super().__init__(**kw)
            self.total = total
            self.looking = looking
            self.still = motion() != "full"

        def on_mount(self):
            if not self.still:
                self.set_interval(0.08, self._tick)

        def _tick(self):
            if 0 < self.progress < self.total or self.looking:
                self.phase = (self.phase + 1) % 1000

        def update(self, progress=None, total=None):
            if total is not None:
                self.total = total
            if progress is not None:
                self.progress = float(progress)

        def render(self):
            c = palette()
            sixteen = color_mode() == "16"
            ascii_ = icon_look() == "ascii"
            full, shades = ("#", ("=", "-", ".")) if ascii_ else ("█", ("▓", "▒", "░"))
            if self.looking:            # searching: no amount, the band runs the whole way along
                w = max(10, self.size.width or 60)
                band = (self.phase % (w + 8)) - 4 if not self.still else -99
                t = Text(no_wrap=True)
                for i in range(w):
                    d = abs(i - band)
                    ch, st = (full, c["primary"]) if d <= 1 else ((shades[0], c["soft"]) if d == 2 else
                                                                  ((shades[1], c["dim"]) if d <= 4 else (shades[2], c["faint"])))
                    t.append(ch, style=(("bold " + rich16("primary")) if d <= 2 else rich16("secondary")) if sixteen else st)
                return t
            w = max(10, (self.size.width or 60) - 7)
            frac = max(0.0, min(1.0, self.progress / (self.total or 1)))
            done = int(w * frac)
            t = Text()
            t.append(full * done, style=("bold " + rich16("primary")) if sixteen else c["primary"])
            rest = w - done
            band = (self.phase % max(1, rest + 6)) - 3 if not self.still and 0 < frac < 1 else -99
            for i in range(rest):
                d = abs(i - band)
                ch, st = (shades[0], c["soft"]) if d == 0 else ((shades[1], c["dim"]) if d == 1 else (shades[2], c["faint"]))
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
                t = Text()
                t.append(dot + " ", style="bold " + col16)
                t.append(self.words, style=col16 if self.state != "busy" else "white")
                return t
            t = Text()
            t.append(dot + " ", style="bold " + col)
            t.append(self.words, style=col if self.state != "busy" else c["text"])
            return t
except ImportError:      # no Textual: the colours and the emblem still work
    pass
