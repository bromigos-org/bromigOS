"""`bromigos lab` with no arguments: the live terminal dashboard (Textual).

Six tabs use the command data and reviewed plans: STATUS (every card `bromigos lab status` has),
MODELS (`lab models`), JOBS (`lab jobs`, with a log, cancel, retry and a new-job form),
DOCTOR (`lab doctor`, each finding's fix), PROVISION (services, VMs and cluster plans) and
NETWORK (`lab network`: the lab's private network, its members, add with a join QR, remove).
Everything has a hover hint: a card says what it
shows, a row what it is (the table's tooltip follows the row under the pointer), a key in
the footer what it does. Reads run in worker threads: the screen never waits on the lab.

The colours are the theme's (bromigos_theme's palette.json), so the dashboard follows
`bromigos theme set` like the rest of the desktop.
"""
import os
import time

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from .tuiux import Dialog, HelpDialog, UXApp
from textual.theme import Theme
from textual.worker import get_current_worker
from textual.widgets import (Button, DataTable, Footer, Input, Label, RichLog, Select, Static, TabbedContent,
                             TabPane, Tabs, Tree)

MARK = {"ok": "●", "warn": "▲", "crit": "✖", "unreachable": "?", "empty": "·", "unknown": "·", "fail": "✖",
        "skip": "·"}
STYLE = {"ok": "$success", "warn": "$warning", "crit": "$error", "unreachable": "$error", "fail": "$error"}


class Live:
    """Where the dashboard's data comes from (a test passes a fixture with the same methods)."""

    def status(self):
        from . import console
        return console.status()

    def inventory(self):
        from . import labmodels
        return labmodels.inventory()

    def jobs(self):
        from . import jobqueue
        return {"jobs": jobqueue.list_jobs(limit=40), "service": jobqueue.service_state()}

    def job_log(self, jid):
        from . import jobqueue
        return jobqueue.read_log(jid)

    def doctor(self):
        from . import doctor
        return doctor.run()

    def kinds(self):
        from . import jobs
        return [k.describe() for k in jobs.kinds()] + [dict(p.describe(), preset=True) for p in jobs.presets()]

    def submit(self, kind, preset, prompt, text):
        from . import jobqueue
        j = jobqueue.submit(kind, preset, prompt or None, (), text or None, by="you")
        jobqueue.ensure_service()
        return j

    def cancel(self, jid):
        from . import jobqueue
        return jobqueue.cancel(jid)

    def retry(self, jid):
        from . import jobqueue
        j = jobqueue.retry(jid)
        jobqueue.ensure_service()
        return j

    def youtube_add(self, url, kind=None, since=None, name=None, quality=None):
        """The YouTube card's form: what `bromigos lab youtube add` does, in its words."""
        from . import pinchflat
        pf, s = pinchflat.connect()
        return pinchflat.describe_add(pinchflat.add_source(pf, s, url, kind, since, name, quality))

    def youtube_quality(self):
        from . import pinchflat
        return pinchflat.settings().get("quality") or pinchflat.DEFAULT_QUALITY

    def network_status(self):
        from . import labnet
        try:
            return labnet.status()
        except labnet.NetError as e:
            return {"configured": True, "error": str(e), "devices": [], "codes": []}

    def network_join(self, tag, expires):
        from . import labnet
        doc = labnet.join(tag, expires)
        doc["qr"] = labnet.qr_lines(doc["bundle"])
        return doc

    def network_remove(self, device_id):
        from . import labnet
        return labnet.remove(str(device_id))

    def network_approve(self, code):
        from . import labnet
        return labnet.approve(code)

    def now(self):
        return time.time()


def bromigos_theme():
    """A Textual theme from the desktop theme's palette (the Wick's without one)."""
    try:
        import bromigos_theme as T
        h = T.hex
        return Theme(name="bromigos", primary=h("primary"), secondary=h("soft"), accent=h("cyan"),
                     warning=h("warn"), error=h("danger"), success=h("primary"), foreground=h("text"),
                     background=h("background"), surface=h("panel"), panel=h("selection"), dark=True)
    except Exception:
        return Theme(name="bromigos", primary="#39ff14", secondary="#9cff8a", accent="#3fe0c5", warning="#d4af37",
                     error="#ff766f", success="#39ff14", foreground="#c4f5bb", background="#000500",
                     surface="#001300", panel="#003b00", dark=True)


def cell(v):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.1f}" if abs(v) < 1000 else f"{v:.0f}"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k} {x}" for k, x in list(v.items())[:4])
    return str(v)


def marked(state, text=""):
    m = MARK.get(state, "·")
    style = {"ok": "green", "warn": "yellow", "crit": "red", "unreachable": "red", "fail": "red"}.get(state, "dim")
    from rich.text import Text
    return Text(f"{m} {text}".rstrip(), style=style)


# Vim keys beside the arrows everywhere (hidden from the footer; ? and the manual list them)
VIM = [
    Binding("j", "cursor_down", "Down", show=False),
    Binding("k", "cursor_up", "Up", show=False),
    Binding("g", "scroll_top", "First", show=False),
    Binding("G", "scroll_bottom", "Last", show=False),
    Binding("ctrl+d", "page_down", "Page down", show=False),
    Binding("ctrl+u", "page_up", "Page up", show=False),
    Binding("h,left", "app.pane(-1)", "Cards", show=False),
    Binding("l,right", "app.pane(1)", "Detail", show=False),
]


class HintTable(DataTable):
    """A table whose hover hint is the hint of the row under the pointer. Moves with the arrows
    and with Vim's keys: j/k, g/G, Ctrl+D/U; h/l (or left/right) between the STATUS panes."""

    BINDINGS = VIM

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.hints = []           # one per row
        self.base_hint = ""

    def action_cursor_up(self):
        if self.cursor_row == 0 and len(self.app.screen_stack) == 1:
            self.app.query_one("#tabs Tabs", Tabs).focus()
        else:
            super().action_cursor_up()

    def watch_hover_coordinate(self, old, new):
        super().watch_hover_coordinate(old, new)
        r = new.row if new is not None else -1
        self.tooltip = (self.hints[r] if 0 <= r < len(self.hints) and self.hints[r] else self.base_hint) or None

    def fill(self, columns, rows, hints, base_hint=""):
        """Replace everything, keeping the cursor's row where it can."""
        keep = self.cursor_row
        self.clear(columns=True)
        self.add_columns(*columns)
        for r in rows:
            self.add_row(*r)
        self.hints = list(hints)
        self.base_hint = base_hint
        self.tooltip = base_hint or None
        if rows:
            self.move_cursor(row=min(keep, len(rows) - 1))


class CardButton(Static):
    """One card in the STATUS list: its mark, title and summary. Click to see it in full.
    Up/down or j/k move between cards (and show each one), g/G go to the first and last,
    right or l moves into the card's detail table."""

    can_focus = True
    BINDINGS = [
        Binding("down,j", "app.card_step(1)", "Next card", show=False),
        Binding("up,k", "app.card_step(-1)", "Previous card", show=False),
        Binding("g,home", "app.card_step(-999)", "First card", show=False),
        Binding("G,end", "app.card_step(999)", "Last card", show=False),
        Binding("right,l", "app.pane(1)", "Detail", show=False),
    ]

    def __init__(self, card, **kw):
        super().__init__(**kw)
        self.card = card
        self.update_card(card)

    def update_card(self, card):
        self.card = card
        st = card["state"]
        from rich.text import Text
        t = Text()
        t.append(f"{MARK.get(st, '·')} ", style={"ok": "green", "warn": "yellow", "crit": "red",
                                                "unreachable": "red"}.get(st, "dim"))
        t.append(card["title"].upper(), style="bold")
        t.append(f"\n  {card.get('summary') or ''}", style="dim" if st in ("ok", "empty") else "")
        self.update(t)
        self.tooltip = f"{card['title']}: {card.get('hint') or ''}\nClick (or Enter) to see every item."
        self.set_class(st in ("warn",), "-warn")
        self.set_class(st in ("crit", "unreachable"), "-crit")

    def on_click(self):
        self.app.show_card(self.card["id"])

    def key_enter(self):
        self.app.show_card(self.card["id"])


class RunJob(Dialog):
    """The new-job form: a kind (or preset), its prompt or text. Homelab only: the cloud is
    the command line's --cloud, never a default here."""


    def __init__(self, choices):
        super().__init__()
        self.choices = choices

    def compose(self):
        opts = [(f"{c['title']}" + ("  (preset)" if c.get("preset") else ""), ("p:" if c.get("preset") else "k:") + c["id"])
                for c in self.choices if c.get("available")]
        with Vertical(id="runbox"):
            yield Label("NEW LAB JOB", classes="title")
            s = Select(opts, prompt="What to make", id="kind")
            s.tooltip = "The kind of job (or a preset of one). Only what this lab can run is listed."
            yield s
            i = Input(placeholder="prompt (an image, a hologram's subject) or the text to speak", id="prompt")
            i.tooltip = "What to make: the prompt for an image or a hologram, the words for a voice line"
            yield i
            yield Static("Runs on the lab, for no credits.\nResults: ~/Pictures/bromigos/lab/<kind>/", classes="dim")
            with Horizontal():
                yield Button("Cancel", id="no", tooltip="Close without queuing anything")
                b = Button("Queue job", variant="primary", id="go")
                b.tooltip = "Add the job to the lab's queue (bromigos lab run)"
                yield b

    @on(Button.Pressed, "#no")
    def no(self):
        self.dismiss(None)

    @on(Button.Pressed, "#go")
    def go(self):
        v = self.query_one("#kind", Select).value
        if not isinstance(v, str):
            self.notify("Pick what to make first", severity="warning")
            return
        self.dismiss((v, self.query_one("#prompt", Input).value.strip()))


QUALITY_WORDS = {"best": "the best there is, up to 8K", "4320p": "8K, where a video has it",
                 "2160p": "4K, about 5-10 GB an hour", "1440p": "about 2-3.5 GB an hour",
                 "1080p": "about 1-2 GB an hour", "720p": "about 0.5-1 GB an hour", "480p": "about 0.3 GB an hour",
                 "360p": "under 0.3 GB an hour", "audio": "sound only, about 0.06 GB an hour"}


class AddYouTube(Dialog):
    """The YouTube card's "Add a channel or playlist…" form: `bromigos lab youtube add`."""


    def __init__(self, quality="1080p"):
        super().__init__()
        self.quality = quality

    def compose(self):
        from .pinchflat import CHOICES
        with Vertical(id="ytbox"):
            yield Label("ADD A CHANNEL OR PLAYLIST", classes="title")
            i = Input(placeholder="https://www.youtube.com/@channel or …/playlist?list=…", id="yt-url")
            i.tooltip = "The YouTube channel's or playlist's address. A video in a playlist works too: its playlist is added."
            yield i
            s = Select([("Work it out from the address", "auto"), ("A playlist (kept in its order)", "playlist"),
                        ("A channel (every upload)", "channel")], value="auto", allow_blank=False, id="yt-kind")
            s.tooltip = "Whether it's a playlist or a channel. The address usually says; pick one if it doesn't."
            yield s
            q = Select([(f"{c} · {QUALITY_WORDS.get(c, '')}", c) for c in CHOICES], value=self.quality,
                       allow_blank=False, id="yt-quality")
            q.tooltip = "The most it downloads. Higher costs more disk: 4K takes about five times the space of 1080p."
            yield q
            i = Input(placeholder="only videos after (YYYY-MM-DD), or leave empty for all", id="yt-since")
            i.tooltip = "Skip older videos: only ones uploaded after this date are downloaded"
            yield i
            i = Input(placeholder="a name (YouTube's, if left empty)", id="yt-name")
            i.tooltip = "The name in Pinchflat, its folder on disk and the playlist in your media server"
            yield i
            with Horizontal():
                yield Button("Cancel", id="yt-no", tooltip="Close without adding anything")
                b = Button("Add channel or playlist", variant="primary", id="yt-go")
                b.tooltip = "Add it to Pinchflat, which starts downloading (bromigos lab youtube add)"
                yield b

    @on(Button.Pressed, "#yt-no")
    def no(self):
        self.dismiss(None)

    @on(Button.Pressed, "#yt-go")
    def go(self):
        url = self.query_one("#yt-url", Input).value.strip()
        if not url:
            self.notify("Give the channel's or playlist's address first", severity="warning")
            return
        since = self.query_one("#yt-since", Input).value.strip()
        if since:
            import datetime
            try:
                datetime.date.fromisoformat(since)
            except ValueError:
                self.notify("The date is YYYY-MM-DD, such as 2025-01-31", severity="warning")
                return
        kind = self.query_one("#yt-kind", Select).value
        self.dismiss({"url": url, "kind": None if kind == "auto" else kind, "since": since or None,
                      "name": self.query_one("#yt-name", Input).value.strip() or None,
                      "quality": self.query_one("#yt-quality", Select).value})


class CancelJob(Dialog):
    """Cancel is safe by default; the exact selected job stays fixed during refreshes."""
    DEFAULT_CSS = """
    CancelJob { align: center middle; }
    #cancel-job-box { width: 76; max-width: 96%; height: auto; padding: 1 2;
        border: solid $warning; background: $surface; }
    #cancel-job-box Horizontal { height: auto; margin-top: 1; }
    """

    def __init__(self, job):
        super().__init__()
        self.job = job

    def compose(self):
        with Vertical(id="cancel-job-box"):
            yield Label("Cancel this job?", classes="title")
            yield Static(self.job["id"], markup=False)
            yield Static(self.job.get("prompt") or self.job.get("text") or
                         self.job.get("preset") or self.job["kind"], markup=False)
            yield Static("Stops this job or removes it from the queue. Existing results stay on disk.")
            with Horizontal():
                yield Button("Keep job", id="keep-job")
                yield Button("Cancel job", variant="error", id="confirm-cancel-job")
            yield Static("←/→ choose · Enter activate · Esc go back", classes="dim")

    def on_mount(self):
        self.query_one("#keep-job", Button).focus()

    @on(Button.Pressed)
    def choose(self, event):
        self.dismiss(event.button.id == "confirm-cancel-job")


class AddMachine(Dialog):
    """NETWORK's "Add a machine…": which kind of machine and how long the code lasts. The code is
    made after this (`bromigos lab network join`), then shown with its QR code."""

    def compose(self):
        with Vertical(id="netbox"):
            yield Label("ADD A MACHINE TO THE LAB NETWORK", classes="title")
            s = Select([("A server (bromigOS Server, a VPS, a NAS): reached by you and the lab", "server"),
                        ("A lab machine (a cluster node, a GPU box): reaches the other lab machines", "lab")],
                       value="server", allow_blank=False, id="net-tag")
            s.tooltip = ("What the machine is. Servers are reached by your devices and the lab, and reach nothing "
                         "on their own. Lab machines also reach each other.")
            yield s
            e = Select([("Good for a day", "24h"), ("Good for an hour", "1h"), ("Good for a week (a Field Kit stick)", "7d")],
                       value="24h", allow_blank=False, id="net-expires")
            e.tooltip = "How long the code works if it isn't used. It works once either way."
            yield e
            yield Static("The code works once. Paste it into the installer, Field Kit or bromigOS Server, or "
                         "scan its QR code with BRODEC.", classes="dim")
            with Horizontal():
                yield Button("Cancel", id="net-no", tooltip="Close without making a code")
                yield Button("Make a join code", variant="primary", id="net-go",
                             tooltip="Make a one-time join code (bromigos lab network join)")

    @on(Button.Pressed, "#net-no")
    def no(self):
        self.dismiss(None)

    @on(Button.Pressed, "#net-go")
    def go(self):
        self.dismiss((self.query_one("#net-tag", Select).value, self.query_one("#net-expires", Select).value))


class JoinCode(Dialog):
    """A join code just made: its QR code, the code to paste and the plain Tailscale command."""

    def __init__(self, doc):
        super().__init__()
        self.doc = doc

    def compose(self):
        from rich.text import Text
        d = self.doc
        with VerticalScroll(id="joinbox"):
            yield Label("JOIN CODE", classes="title")
            yield Static(f"Good once, until {d.get('expires', '')[:16].replace('T', ' ')} UTC, for a "
                         f"{', '.join(t.removeprefix('tag:') for t in d.get('tags') or [])} machine.", classes="dim")
            if d.get("qr"):
                q = Static(Text.from_ansi("\n".join(d["qr"])), id="join-qr")
                q.tooltip = "Scan with BRODEC, or with the installer's camera step. It holds the code below."
                yield q
            b = Static(d["bundle"], id="join-bundle", markup=False)
            b.tooltip = "The join code. Paste it into the installer, Field Kit or bromigOS Server's setup."
            yield b
            c = Static("On any Linux machine with Tailscale: " + d.get("command", ""), id="join-command", markup=False,
                       classes="dim")
            c.tooltip = "The same join, as Tailscale's own command (no exit node, no routes)"
            yield c
            with Horizontal():
                yield Button("Done", variant="primary", id="join-done", tooltip="Close. The code stays valid until used or expired.")

    @on(Button.Pressed, "#join-done")
    def done(self):
        self.dismiss(None)


class ApproveDevice(Dialog):
    """A phone or laptop that signed in through the Tailscale app shows a code: approve it here."""

    def compose(self):
        with Vertical(id="netbox"):
            yield Label("APPROVE A DEVICE", classes="title")
            yield Static("In the Tailscale app, choose your lab's server; it shows a code. Type it here to add the "
                         "device as yours.", classes="dim")
            i = Input(placeholder="the code the device shows", id="approve-code")
            i.tooltip = "The code from the device's sign-in page (bromigos lab network approve CODE)"
            yield i
            with Horizontal():
                yield Button("Cancel", id="approve-no", tooltip="Close without approving")
                yield Button("Approve", variant="primary", id="approve-go", tooltip="Add the device to the lab network as yours")

    @on(Button.Pressed, "#approve-no")
    def no(self):
        self.dismiss(None)

    @on(Button.Pressed, "#approve-go")
    def go(self):
        code = self.query_one("#approve-code", Input).value.strip()
        if not code:
            self.notify("Type the code the device shows first", severity="warning")
            return
        self.dismiss(code)


class RemoveDevice(Dialog):
    """Remove is a choice you make twice: Keep is focused first."""
    DEFAULT_CSS = """
    RemoveDevice { align: center middle; }
    #remove-box { width: 76; max-width: 96%; height: auto; padding: 1 2; border: solid $warning; background: $surface; }
    #remove-box Horizontal { height: auto; margin-top: 1; }
    """

    def __init__(self, device):
        super().__init__()
        self.device = device

    def compose(self):
        d = self.device
        with Vertical(id="remove-box"):
            yield Label(f"Take {d['name']} off the lab network?", classes="title")
            yield Static(", ".join(d.get("ips") or []) or "no address yet", markup=False)
            yield Static("It can't reach your lab or be reached until it joins again with a new code.")
            with Horizontal():
                yield Button("Keep it", id="keep-device")
                yield Button("Remove", variant="error", id="confirm-remove-device")
            yield Static("←/→ choose · Enter activate · Esc go back", classes="dim")

    def on_mount(self):
        self.query_one("#keep-device", Button).focus()

    @on(Button.Pressed)
    def choose(self, event):
        self.dismiss(event.button.id == "confirm-remove-device")


class LabApp(UXApp):
    class ReadReady(Message):
        """Deliver a completed read through the app's normal message lifecycle."""

        def __init__(self, kind, data):
            super().__init__()
            self.kind, self.data = kind, data
            self.worker = get_current_worker()

    TITLE = "LAB"
    CSS = """
    Screen { background: $background; }
    #top { height: 1; padding: 0 1; background: $panel; color: $foreground; }
    #cards { width: 34%; min-width: 20; max-width: 46; border-right: solid $panel; }
    HintTable:focus { border: solid $primary; }
    #job-actions { height: auto; padding: 0 1; }
    #job-actions Button { margin-right: 1; }
    CardButton { padding: 0 1; margin: 0 0 1 0; height: auto; border-left: tall $success; }
    CardButton:focus { background: $panel; }
    CardButton.-warn { border-left: tall $warning; }
    CardButton.-crit { border-left: tall $error; }
    #detail-title { padding: 0 1; text-style: bold; color: $primary; }
    #detail-hint, .dim { padding: 0 1; color: $text-muted; }
    #hint { height: 3; padding: 0 1; color: $text-muted; border-top: solid $panel; }
    HintTable { height: 1fr; }
    #gpus { height: auto; max-height: 14; }
    #joblog { height: 12; border-top: solid $panel; }
    #runbox { width: 76; max-width: 96%; height: auto; padding: 1 2; border: solid $primary; background: $surface; }
    RunJob { align: center middle; }
    AddYouTube { align: center middle; }
    #ytbox { width: 84; max-width: 96%; height: auto; padding: 1 2; border: solid $primary; background: $surface; }
    #ytbox Horizontal { height: auto; margin-top: 1; }
    #yt-add { margin: 0 1; }
    .title { text-style: bold; color: $primary; }
    Select, Input { margin: 1 0 0 0; }
    #runbox Horizontal { height: auto; margin-top: 1; }
    AddMachine, ApproveDevice, JoinCode { align: center middle; }
    #netbox { width: 84; max-width: 96%; height: auto; padding: 1 2; border: solid $primary; background: $surface; }
    #netbox Horizontal, #joinbox Horizontal { height: auto; margin-top: 1; }
    #joinbox { width: 96; max-width: 98%; height: 90%; padding: 1 2; border: solid $primary; background: $surface; }
    #join-qr { width: auto; margin: 1 0; }
    #join-bundle { margin: 1 0; }
    #net-actions { height: auto; padding: 0 1; }
    #net-actions Button { margin-right: 1; }
    """
    BINDINGS = [
        Binding("question_mark", "help", "Help"),
        Binding("down,j", "content", "Content", priority=True),
        Binding("h", "tab_bar(-1)", "Previous tab", priority=True, show=False),
        Binding("l", "tab_bar(1)", "Next tab", priority=True, show=False),
        Binding("ctrl+c", "interrupt", "Quit", show=False),
        Binding("5", "tab('provision')", "Provision", show=False),
        Binding("6", "tab('network')", "Network", show=False,
                tooltip="Your lab's private network: its members, add a machine, remove one"),
        Binding("q", "quit", "Quit", tooltip="Leave the dashboard"),
        Binding("r", "refresh", "Refresh", tooltip="Read the lab again now (it refreshes every 15 s by itself)"),
        Binding("1", "tab('status')", "Status", show=False, tooltip="Every card: nodes, GPUs, services, apps, storage, alerts, jobs"),
        Binding("2", "tab('models')", "Models", show=False, tooltip="What's installed and loaded where, with VRAM"),
        Binding("3", "tab('jobs')", "Jobs", show=False, tooltip="The lab job queue: progress, logs, cancel, retry"),
        Binding("4", "tab('doctor')", "Doctor", show=False, tooltip="Checks with fixes in plain words"),
        Binding("n", "new_job", "New job", tooltip="Queue a job on the lab (image, hologram, voice line…)"),
        Binding("c", "cancel_job", "Cancel job", tooltip="Cancel the job under the cursor (Jobs tab)"),
        Binding("R", "retry_job", "Retry", tooltip="Queue the job under the cursor again (Jobs tab)"),
        Binding("d", "doctor", "Run doctor", tooltip="Run every check now (Doctor tab)"),
        Binding("M", "media", "Media", tooltip="Your media library: TV, films, music, downloads, requests "
                                                "(bromigos media)"),
        Binding("A", "net_add", "Add machine", tooltip="Make a join code for a machine, with its QR code (Network tab)"),
        Binding("x", "net_remove", "Remove device", tooltip="Take the device under the cursor off the lab network (Network tab)"),
        Binding("p", "net_approve", "Approve device", tooltip="Approve a phone or laptop that shows a code (Network tab)"),
        Binding("a", "youtube_add", "Add YouTube", show=False,
                tooltip="Add a YouTube channel or playlist to Pinchflat (the YouTube downloads card)"),
        Binding("],L", "tab_step(1)", "Next tab", show=False),
        Binding("[,H", "tab_step(-1)", "Previous tab", show=False),
    ]
    HELP = (
        ("Navigation", "1–6 switch tabs · [ / ] or H / L previous / next tab\n"
                       "↑/↓ or j/k move · g/G first / last · Ctrl+U/D page\n"
                       "Tab / Shift+Tab change focus · first row: ↑/k returns to tabs\n"
                       "Tab bar: ←/→ or h/l switch · ↓/j enters content\n"
                       "STATUS: ←/→ or h/l cards / details"),
        ("Actions", "r refresh · n new lab job · M open Media\n"
                    "JOBS: c review cancellation · R retry selected job\n"
                    "DOCTOR: d run checks · YouTube card: a add channel / playlist"),
        ("Forms and confirmations", "Tab or ↑/↓ moves between fields and buttons\n"
                                    "←/→ or h/l chooses buttons · Enter activates the focused control\n"
                                    "Esc / Ctrl+C cancels · job cancellation defaults to Keep job\n"
                                    "Letter shortcuts stay inactive while you type or a dialog is open"),
        ("Network", "A add a machine (a join code and its QR) · p approve a device's code\n"
                    "x review removing the device under the cursor (Keep is the default)"),
        ("Provision", "Choose services, then run the shown plan command. Apply and destructive\n"
                      "infrastructure commands keep their explicit approval in your terminal."),
    )
    TABS = ("status", "models", "jobs", "doctor", "provision", "network")
    MAIN = {"models": "#modeltable", "jobs": "#jobtable", "doctor": "#findings", "network": "#nettable"}

    def __init__(self, source=None, clock=None, interval=15.0):
        super().__init__()
        self.src = source or Live()
        self.clock = clock or time.time
        self.interval = interval
        self.doc = None
        self.inv = None
        self.jobsdoc = None
        self.doctor_doc = None
        self.net_doc = None
        self.pending_net = False
        self.current = None
        self.loaded_at = None
        self.pending_jobs = set()
        self.pending_submit = False
        from . import services
        self.provision_cat = services.load()
        from . import provision
        self.provision_selected = provision.preset_selection(self.provision_cat, 'core')

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Static("LAB · reading the lab…", id="top")
        with TabbedContent(initial="status", id="tabs"):
            with TabPane("STATUS", id="status"):
                with Horizontal():
                    yield VerticalScroll(id="cards")
                    with Vertical():
                        yield Static("", id="detail-title")
                        yield Static("", id="detail-hint")
                        b = Button("Add a channel or playlist…", id="yt-add")
                        b.tooltip = ("Add a YouTube channel or playlist to Pinchflat: it downloads every video into "
                                     "your media library (bromigos lab youtube add). Key: a")
                        b.display = False
                        yield b
                        yield HintTable(id="detail", cursor_type="row", zebra_stripes=True)
            with TabPane("MODELS", id="models"):
                with Vertical():
                    yield Static("GPUS", classes="title")
                    yield HintTable(id="gpus", cursor_type="row")
                    yield Static("MODELS", classes="title")
                    yield HintTable(id="modeltable", cursor_type="row", zebra_stripes=True)
            with TabPane("JOBS", id="jobs"):
                with Vertical():
                    yield Static("", id="jobsum", classes="dim")
                    with Horizontal(id="job-actions"):
                        yield Button("New job (n)", id="job-new", variant="primary")
                        yield Button("Cancel job… (c)", id="job-cancel", variant="error")
                        yield Button("Retry job (R)", id="job-retry")
                    yield HintTable(id="jobtable", cursor_type="row", zebra_stripes=True)
                    yield RichLog(id="joblog", wrap=True, markup=False)
            with TabPane("DOCTOR", id="doctor"):
                with Vertical():
                    yield Static("Press d to run the checks.", id="docsum", classes="dim")
                    yield HintTable(id="findings", cursor_type="row", zebra_stripes=True)
                    yield Static("", id="fix")
            with TabPane("PROVISION", id="provision"):
                with VerticalScroll():
                    yield Static("Choose services. The terminal command takes inventory and generates a reviewable plan.")
                    yield Tree("Your lab", id="provision-tree")
                    yield Static("", id="provision-hint")
                    with Horizontal():
                        yield Button("Core", id="provision-core")
                        yield Button("Advanced", id="provision-advanced")
                    yield Static("", id="provision-command")
                    yield Input(placeholder='Generated lab repository path', id='infra-repo')
                    yield Input(placeholder='Cluster or new-node specification JSON path', id='infra-spec')
                    yield Input(placeholder='Node name for drain/removal', id='infra-name')
                    yield Select([('Worker', 'worker'), ('GPU (prepared driver/runtime)', 'gpu')], value='worker', allow_blank=False, id='infra-role')
                    with Horizontal():
                        yield Button('Read plan', id='infra-read')
                        yield Button('Plan cluster', id='infra-plan')
                        yield Button('Apply', id='infra-apply')
                    with Horizontal():
                        yield Button('Add node', id='infra-grow')
                        yield Button('Drain node', id='infra-remove')
                    yield Static('', id='infra-review')
                    yield Input(placeholder='Provider name for VM actions', id='infra-provider')
                    yield Select([(name.title(), name) for name in ('list', 'start', 'stop', 'delete', 'snapshot', 'console')], value='list', allow_blank=False, id='infra-vm-action')
                    yield Input(placeholder='Snapshot name, when taking a snapshot', id='infra-snapshot')
                    with Horizontal():
                        yield Button('Read storage', id='infra-storage')
                        yield Button('VM command', id='infra-vm')
            with TabPane("NETWORK", id="network"):
                with Vertical():
                    yield Static("reading the lab network…", id="netsum", classes="dim")
                    with Horizontal(id="net-actions"):
                        yield Button("Add a machine… (A)", id="net-add", variant="primary",
                                     tooltip="Make a one-time join code with its QR code (bromigos lab network join)")
                        yield Button("Approve a device… (p)", id="net-approve",
                                     tooltip="A phone or laptop signed in through the Tailscale app and shows a code")
                        yield Button("Remove… (x)", id="net-remove", variant="error",
                                     tooltip="Take the device under the cursor off the network, after you confirm")
                    yield HintTable(id="nettable", cursor_type="row", zebra_stripes=True)
                    yield Static("", id="net-hint", classes="dim")
        yield Static("", id="hint")
        yield Footer()

    def on_mount(self):
        self.register_theme(bromigos_theme())
        self.theme = "bromigos"
        for tid, hint in (("status", "Every part of the lab, one card each"), ("models", "Installed and loaded models"),
                          ("jobs", "The lab job queue"), ("doctor", "Checks with fixes"),
                          ("network", "Your lab's private network: who's on it, add and remove")):
            try:
                self.query_one(f"#tabs Tab#--content-tab-{tid}").tooltip = hint
            except Exception:
                pass
        self.show_provision_tree()
        self.load_status()
        self.load_jobs()
        self.set_interval(self.interval, self.load_status)
        self.set_interval(2.0, self.load_jobs)

    # ------------------------------------------------------------------ data (worker threads)
    @work(thread=True, exclusive=True, group="status")
    def load_status(self):
        doc = self.src.status()
        self.post_message(self.ReadReady("status", doc))

    @work(thread=True, exclusive=True, group="models")
    def load_models(self):
        inv = self.src.inventory()
        self.post_message(self.ReadReady("models", inv))

    @work(thread=True, exclusive=True, group="jobs")
    def load_jobs(self):
        d = self.src.jobs()
        self.post_message(self.ReadReady("jobs", d))

    @work(thread=True, exclusive=True, group="doctor")
    def load_doctor(self):
        d = self.src.doctor()
        self.post_message(self.ReadReady("doctor", d))

    @work(thread=True, exclusive=True, group="network")
    def load_network(self):
        read = getattr(self.src, "network_status", None)        # a source without a network: none yet
        d = read() if read else {"configured": False}
        self.post_message(self.ReadReady("network", d))

    @on(ReadReady)
    def _read_ready(self, event):
        if self.is_running and not event.worker.is_cancelled:
            getattr(self, f"show_{event.kind}")(event.data)

    # ------------------------------------------------------------------ STATUS
    def show_status(self, doc):
        self.doc = doc
        self.loaded_at = self.clock()
        st = doc.get("state", "empty")
        when = time.strftime("%H:%M:%S", time.localtime(doc.get("generatedAt") or self.clock()))
        bad = [c for c in doc.get("cards", []) if c["state"] in ("warn", "crit", "unreachable")]
        words = {"ok": "all well", "warn": f"{len(bad)} to look at", "crit": f"{len(bad)} need attention",
                 "unreachable": "something doesn't answer", "empty": "nothing connected"}.get(st, st)
        top = self.query_one("#top", Static)
        top.update(marked(st, f"LAB · {words} · read at {when}" + (f" in {doc['seconds']} s" if doc.get("seconds") else "")))
        top.tooltip = "The whole lab's state: the worst of its cards. r reads it again."
        box = self.query_one("#cards", VerticalScroll)
        have = {w.card["id"]: w for w in box.query(CardButton)}
        if not doc.get("configured", True) and not doc.get("cards"):
            box.remove_children()
            box.mount(Static("No homelab connected.\n\nbromigos lab connect\nfinds your services and writes "
                             "homelab.toml.", classes="dim"))
            return
        ids = [c["id"] for c in doc["cards"]]
        for cid, w in have.items():
            if cid not in ids:
                w.remove()
        for c in doc["cards"]:
            if c["id"] in have:
                have[c["id"]].update_card(c)
            else:
                box.mount(CardButton(c, id=f"card-{c['id']}"))
        if self.current not in ids and ids:
            pick = next((c["id"] for c in doc["cards"] if c["state"] in ("crit", "unreachable", "warn")), ids[0])
            self.current = pick
        self.show_card(self.current, focus=False)

    def show_card(self, cid, focus=True):
        if not self.doc:
            return
        c = next((x for x in self.doc["cards"] if x["id"] == cid), None)
        if not c:
            return
        self.current = cid
        self.query_one("#detail-title", Static).update(marked(c["state"], f"{c['title'].upper()} · {c.get('summary') or ''}"))
        self.query_one("#detail-hint", Static).update(c.get("hint") or "")
        self.query_one("#yt-add", Button).display = cid == "youtube-downloader"
        cols = [k for k in (c.get("columns") or []) if k != "state"]
        rows, hints = [], []
        for it in c.get("items", []):
            rows.append([marked(it.get("state", "unknown"))] + [cell(it.get(k)) for k in cols])
            hints.append(it.get("hint") or ", ".join(f"{k}: {cell(it.get(k))}" for k in cols[:6]))
        for s, e in (c.get("errors") or {}).items():
            rows.append([marked("crit")] + [s] + [e] + [""] * max(0, len(cols) - 2))
            hints.append(f"{s} didn't answer: {e}")
        t = self.query_one("#detail", HintTable)
        t.fill([""] + [k.replace("_", " ") for k in cols] if cols else ["", "source", "error"], rows, hints,
               c.get("hint") or "")
        if focus:
            t.focus()
        self.query_one("#hint", Static).update(c.get("hint") or "")

    # ------------------------------------------------------------------ MODELS
    def show_models(self, inv):
        self.inv = inv
        g = self.query_one("#gpus", HintTable)
        rows, hints = [], []
        for x in inv.get("gpus", []):
            vram = (f"{(x.get('vram_used') or 0) / 2**30:.1f} / {x['vram_total'] / 2**30:.1f} GiB"
                    if x.get("vram_total") else "unified memory")
            holds = ", ".join(x.get("holds") or []) or "-"
            if x.get("group"):
                holds += f" ({x['group']}, tensor parallel)"
            rows.append([x.get("name"), x.get("host") or "-", vram, cell(x.get("util_pct")), cell(x.get("temp_c")),
                         cell(x.get("power_w")), holds])
            hints.append(f"{x.get('name')} on {x.get('host')}: {vram}; held by {', '.join(x.get('holds') or []) or 'nothing'}")
        g.fill(["GPU", "host", "VRAM", "busy %", "°C", "W", "holds"], rows, hints,
               "Each GPU, its VRAM, and the pods or servers holding it")
        t = self.query_one("#modeltable", HintTable)
        rows, hints = [], []
        for s in inv.get("servers", []):
            for m in s.get("models", []):
                if m.get("folder") and not m.get("loaded"):
                    continue                       # model files on disk: the command's --all lists them
                st = m.get("state") or ("loaded" if m.get("loaded") else "installed" if m.get("loaded") is False
                                        else "on disk")
                rows.append([marked("ok" if m.get("loaded") else "unknown"), m.get("name"), s["kind"], s["source"], st,
                             f"{m['vram'] / 2**30:.1f} GiB" if m.get("vram") else "-", " / ".join(m.get("can") or []) or "-"])
                hints.append(f"{m.get('name')} on {s['source']} ({s['kind']}): {st}. {m.get('note') or ''}".strip())
        t.fill(["", "model", "server", "source", "state", "VRAM", "can"], rows, hints,
               "What each server has: bromigos lab models load|unload NAME changes what's loaded")

    # ------------------------------------------------------------------ JOBS
    def show_jobs(self, d):
        self.jobsdoc = d
        js = d.get("jobs", [])
        run = sum(1 for j in js if j["state"] == "running")
        q = sum(1 for j in js if j["state"] in ("queued", "waiting"))
        self.query_one("#jobsum", Static).update(
            f"{run} running · {q} queued · the queue's service is {d.get('service', '?')} · n: a new job")
        t = self.query_one("#jobtable", HintTable)
        st = {"succeeded": "ok", "failed": "crit", "waiting": "warn", "running": "ok"}
        rows, hints = [], []
        for j in js:
            detail = j.get("why") if j["state"] in ("waiting", "failed", "cancelled") else (
                f"{int((j.get('progress') or 0) * 100)}% {j.get('progress_text') or ''}" if j["state"] == "running" else
                ", ".join(os.path.basename(o) for o in (j.get("outputs") or [])[:2]) or (j.get("prompt") or j.get("text") or ""))
            rows.append([marked(st.get(j["state"], "unknown")), j["id"], j.get("preset") or j["kind"], j["state"],
                         (detail or "")[:80]])
            hints.append(f"{j['id']}: {j['state']}. " + (j.get("why") or "") +
                         (f" Results: {', '.join(j.get('outputs') or [])}" if j.get("outputs") else "") +
                         " (c cancels, R retries)")
        t.fill(["", "job", "what", "state", "detail"], rows, hints, "The lab's jobs, newest first")
        self._show_log()
        self._job_actions()
        self.refresh_bindings()

    @on(DataTable.RowHighlighted, "#jobtable")
    def _job_row(self, _ev):
        self._show_log()
        self._job_actions()
        self.refresh_bindings()

    def _job_actions(self):
        job = self._selected_job()
        pending = bool(job and job["id"] in self.pending_jobs)
        self.query_one("#job-cancel", Button).disabled = not job or pending or job["state"] not in ("queued", "waiting", "running")
        self.query_one("#job-retry", Button).disabled = not job or pending
        self.query_one("#job-new", Button).disabled = self.pending_submit

    def _selected_job(self):
        js = (self.jobsdoc or {}).get("jobs", [])
        r = self.query_one("#jobtable", HintTable).cursor_row
        return js[r] if 0 <= r < len(js) else None

    def _show_log(self):
        j = self._selected_job()
        log = self.query_one("#joblog", RichLog)
        text = self.src.job_log(j["id"]) if j else ""
        if getattr(log, "_shown", None) != (j and j["id"], len(text)):
            log.clear()
            log.write(text or "(select a job to see its log)")
            log._shown = (j and j["id"], len(text))

    # ------------------------------------------------------------------ DOCTOR
    def show_doctor(self, d):
        self.doctor_doc = d
        s = d.get("summary", {})
        self.query_one("#docsum", Static).update(
            f"{s.get('ok', 0)} ok · {s.get('warn', 0)} to look at · {s.get('fail', 0)} failing · {s.get('skip', 0)} "
            f"skipped · read in {d.get('seconds', '?')} s (d: again)")
        t = self.query_one("#findings", HintTable)
        rows = [[marked({"ok": "ok", "warn": "warn", "fail": "fail"}.get(f["status"], "skip")), f["title"],
                 f.get("detail") or ""] for f in d.get("findings", [])]
        hints = [(f.get("fix") or f.get("detail") or "") for f in d.get("findings", [])]
        t.fill(["", "check", "what it found"], rows, hints, "Each finding; its fix shows below and on hover")
        self._show_fix()

    @on(DataTable.RowHighlighted, "#findings")
    def _finding_row(self, _ev):
        self._show_fix()

    def _show_fix(self):
        fs = (self.doctor_doc or {}).get("findings", [])
        r = self.query_one("#findings", HintTable).cursor_row
        f = fs[r] if 0 <= r < len(fs) else None
        self.query_one("#fix", Static).update(f"FIX: {f['fix']}" if f and f.get("fix") else "")

    def show_provision_tree(self):
        from . import provision
        tree = self.query_one("#provision-tree", Tree)
        tree.clear()
        for group, rows in provision.picker_rows(self.provision_cat):
            parent = tree.root.add(group.upper(), expand=True)
            for sid, title, hint in rows:
                parent.add_leaf(f"[{'x' if sid in self.provision_selected else ' '}] {title}", data=sid)
        tree.root.expand()
        self.query_one("#provision-command", Static).update(
            "bromigos lab provision --repo <folder> --ssh <user@host> --services " +
            " ".join(self.provision_selected) +
            "\nAdd --backup-path and --age-recipient for Core; --git-url for Argo CD. "
            "Apply waits for an explicit yes in your terminal.")

    @on(Button.Pressed, '#infra-read')
    @on(Button.Pressed, '#infra-plan')
    @on(Button.Pressed, '#infra-apply')
    @on(Button.Pressed, '#infra-grow')
    @on(Button.Pressed, '#infra-remove')
    @on(Button.Pressed, '#infra-storage')
    @on(Button.Pressed, '#infra-vm')
    def infrastructure_action(self, event):
        import json, subprocess
        from pathlib import Path
        repo = self.query_one('#infra-repo', Input).value.strip()
        spec = self.query_one('#infra-spec', Input).value.strip()
        review = self.query_one('#infra-review', Static)
        if not repo:
            review.update('Enter your generated lab repository path.'); return
        if event.button.id == 'infra-read':
            try:
                state = json.loads((Path(repo) / 'plan.json').read_text())
                rows = [n['name'] + ': ' + n['role'] + ', ' + n.get('on', 'existing SSH') + ', ' + str(n.get('vm', {}).get('cpu', '?')) + ' CPUs, ' + str(n.get('vm', {}).get('ram_mib', '?')) + ' MiB RAM, ' + str(n.get('vm', {}).get('disk_gib', '?')) + ' GiB at ' + n.get('vm', {}).get('storage', 'existing') for n in state['infrastructure']['nodes']]
                review.update('\n'.join(rows + ['Volume class: ' + state['infrastructure'].get('storage_class', 'local-path')] + state['review_notes'] + ['Storage inventory: ' + json.dumps(state.get('storage_inventory', {})), 'Services: ' + ', '.join(state['selected']), 'Monitoring: private ports 9090, 9093, 3000 and 3100']))
            except (OSError, ValueError, KeyError): review.update('No valid cluster plan at that path.')
            return
        provider = self.query_one('#infra-provider', Input).value.strip()
        argv = {'infra-plan': ['cluster', '--spec', spec], 'infra-apply': ['apply'],
                'infra-grow': ['add-node', '--role', self.query_one('#infra-role', Select).value] + (['--node-spec', spec] if spec else []) + (['--on', provider] if provider else []),
                'infra-remove': ['remove-node', '--name', self.query_one('#infra-name', Input).value.strip()],
                'infra-storage': ['storage', 'list'],
                'infra-vm': ['vm', self.query_one('#infra-vm-action', Select).value, '--on', provider, '--name', self.query_one('#infra-name', Input).value.strip()]}[event.button.id]
        if event.button.id == 'infra-vm' and self.query_one('#infra-vm-action', Select).value == 'snapshot':
            argv += ['--snapshot-name', self.query_one('#infra-snapshot', Input).value.strip()]
        executable = Path(__file__).resolve().parents[2] / 'bin/bromigos-lab'
        # Credential prompts and approval stay in this terminal, outside the dashboard.
        with self.suspend():
            result = subprocess.run([str(executable), 'provision'] + argv + ['--repo', repo])
        review.update('Command finished.' if result.returncode == 0 else 'Command stopped; review its terminal explanation.')

    @on(Tree.NodeHighlighted, "#provision-tree")
    def provision_hint(self, event):
        if event.node.data:
            row = self.provision_cat["service"][event.node.data]
            self.query_one("#provision-hint", Static).update(row["summary"] + " · ports " + str(row["ports"]) +
                " · RAM " + str(row["needs"].get("ram_gib", 0)) + " GiB · disk " + str(row["needs"].get("disk_gib", 0)) + " GiB")

    @on(Tree.NodeSelected, "#provision-tree")
    def provision_toggle(self, event):
        from . import observability
        if event.node.data in observability.SERVICES:
            self.notify('Monitoring is included in every provision plan.'); return
        from . import services
        sid = event.node.data
        if not sid:
            return
        picked = list(self.provision_selected)
        if sid in picked:
            picked.remove(sid)
            warning = self.provision_cat["service"][sid].get("untick_warning")
            if warning:
                self.notify(warning, severity="warning", timeout=12)
        else:
            picked.append(sid)
        result = services.resolve(self.provision_cat, picked)
        for _, words in result["added"]:
            self.notify(words)
        self.provision_selected = result["services"]
        self.show_provision_tree()

    @on(Button.Pressed, "#provision-core")
    @on(Button.Pressed, "#provision-advanced")
    def provision_preset(self, event):
        from . import provision
        self.provision_selected = provision.preset_selection(self.provision_cat, event.button.id.removeprefix("provision-"))
        self.show_provision_tree()

    # ------------------------------------------------------------------ NETWORK
    def show_network(self, d):
        self.net_doc = d
        from . import labnet
        summary = self.query_one("#netsum", Static)
        t = self.query_one("#nettable", HintTable)
        if not d.get("configured"):
            summary.update("No lab network yet. In a terminal: bromigos lab network setup (it shows the plan "
                           "before it changes anything).")
            t.fill(["", "device"], [], [], "")
        elif d.get("error"):
            summary.update(marked("crit", "The lab network didn't answer: " + d["error"]))
        else:
            summary.update(f"{d.get('name')} · {d.get('login_server')} · {d.get('summary')}")
            rows, hints = [], []
            for x in d.get("devices", []):
                what = {"lab": "lab machine", "server": "server", "device": f"{x['user']}'s device"}[x["kind"]]
                seen = "online" if x["online"] else ("seen " + labnet.ago(x["seen_ago"]) if x["seen_ago"] is not None
                                                     else "never seen")
                rows.append([marked("ok" if x["online"] else "unknown"), x["name"], what,
                             ", ".join(x["ips"][:1]) or "-", seen, ", ".join(t_.removeprefix("tag:") for t_ in x["tags"]) or "-"])
                hints.append(f"{x['name']}: {what}, {seen}. Addresses: {', '.join(x['ips']) or 'none'}."
                             + (" Its key expired: it must sign in again." if x["expired"] else "") + " (x removes it)")
            for k in d.get("codes", []):
                rows.append([marked("warn"), f"join code {k['id']}", "unused join code", "-",
                             "until " + k["expires"][:16].replace("T", " "),
                             ", ".join(t_.removeprefix("tag:") for t_ in k["tags"]) or "-"])
                hints.append("A join code nobody has used yet. bromigos lab network rotate expires every unused one.")
            t.fill(["", "name", "what", "address", "seen", "tags"], rows, hints,
                   "Everything on your lab's private network, online first")
        self._net_actions()
        self.refresh_bindings()

    def _selected_device(self):
        devs = (self.net_doc or {}).get("devices", [])
        tables = self.screen_stack[0].query("#nettable") if self.screen_stack else []
        if not tables:
            return None
        r = tables.first().cursor_row
        return devs[r] if 0 <= r < len(devs) else None

    def _net_actions(self):
        from textual.css.query import NoMatches
        try:
            self._net_buttons()
        except NoMatches:                                # the dashboard is closing
            pass

    def _net_buttons(self):
        ok = bool(self.net_doc and self.net_doc.get("configured") and not self.net_doc.get("error"))
        self.query_one("#net-add", Button).disabled = not ok or self.pending_net
        self.query_one("#net-approve", Button).disabled = not ok or self.pending_net
        self.query_one("#net-remove", Button).disabled = not ok or self.pending_net or not self._selected_device()

    @on(DataTable.RowHighlighted, "#nettable")
    def _net_row(self, _ev):
        if not self.is_running or not self.query("#nettable"):
            return
        t = self.query_one("#nettable", HintTable)
        r = t.cursor_row
        self.query_one("#net-hint", Static).update(t.hints[r] if 0 <= r < len(t.hints) else "")
        self._net_actions()
        self.refresh_bindings()

    @on(Button.Pressed, "#net-add")
    def _net_add_pressed(self):
        self.action_net_add()

    @on(Button.Pressed, "#net-remove")
    def _net_remove_pressed(self):
        self.action_net_remove()

    @on(Button.Pressed, "#net-approve")
    def _net_approve_pressed(self):
        self.action_net_approve()

    def action_net_add(self):
        self.push_screen(AddMachine(), self._net_add_chosen)

    def _net_add_chosen(self, choice):
        if choice and not self.pending_net:
            self.pending_net = True
            self._net_actions()
            self.notify("Making a join code…")
            self.net_join(*choice)

    @work(thread=True, group="network-change")
    def net_join(self, tag, expires):
        try:
            doc = self.src.network_join(tag, expires)
        except Exception as e:
            self.call_from_thread(self._net_done, f"Couldn't make a join code: {e}", True)
            return
        self.call_from_thread(self._net_done, None, False)
        self.call_from_thread(self.push_screen, JoinCode(doc))

    def action_net_remove(self):
        d = self._selected_device()
        if d and not self.pending_net:
            did = d["id"]
            self.push_screen(RemoveDevice(d), lambda yes: self._net_remove_confirmed(did, yes))

    def _net_remove_confirmed(self, did, yes):
        if yes and not self.pending_net:
            self.pending_net = True
            self._net_actions()
            self.net_change("remove", did)

    def action_net_approve(self):
        if not self.pending_net:
            self.push_screen(ApproveDevice(), lambda code: code and self._net_approve_typed(code))

    def _net_approve_typed(self, code):
        self.pending_net = True
        self._net_actions()
        self.net_change("approve", code)

    @work(thread=True, group="network-change")
    def net_change(self, what, arg):
        try:
            doc = self.src.network_remove(arg) if what == "remove" else self.src.network_approve(arg)
        except Exception as e:
            self.call_from_thread(self._net_done, f"Couldn't {what}: {e}", True)
            return
        self.call_from_thread(self._net_done, doc.get("words") or "Done", False)

    def _net_done(self, words, error):
        self.pending_net = False
        self._net_actions()
        self.refresh_bindings()
        if words:
            self.notify(words, severity="error" if error else "information", timeout=10)
        self.load_network()

    # ------------------------------------------------------------------ actions
    @on(TabbedContent.TabActivated)
    def _tab(self, ev):
        tid = ev.pane.id if ev.pane else None
        if tid:
            if not isinstance(self.focused, Tabs):
                self.call_after_refresh(self._focus_main, tid)
            self.refresh_bindings()
        if tid == "models" and self.inv is None:
            self.load_models()
        if tid == "doctor" and self.doctor_doc is None:
            self.load_doctor()
        if tid == "network" and self.net_doc is None:
            self.load_network()

    @on(DataTable.RowHighlighted, "#detail")
    def _item_row(self, ev):
        t = self.query_one("#detail", HintTable)
        r = t.cursor_row
        if 0 <= r < len(t.hints):
            self.query_one("#hint", Static).update(t.hints[r])

    def check_action(self, action, parameters):
        if not super().check_action(action, parameters):
            return False
        if action in ("content", "tab_bar"):
            return isinstance(self.focused, Tabs)
        tab = self.query_one("#tabs", TabbedContent).active if self.is_mounted else "status"
        if action in ("cancel_job", "retry_job"):
            if tab != "jobs":
                return False
            job = self._selected_job()
            return bool(job and job["id"] not in self.pending_jobs and
                        (action == "retry_job" or job["state"] in ("queued", "waiting", "running")))
        if action == "new_job":
            return not self.pending_submit
        if action == "doctor":
            return tab == "doctor"
        if action == "youtube_add":
            return tab == "status" and self.current == "youtube-downloader"
        if action in ("net_add", "net_approve", "net_remove"):
            ready = bool(tab == "network" and self.net_doc and self.net_doc.get("configured")
                         and not self.net_doc.get("error") and not self.pending_net)
            return ready and (action != "net_remove" or bool(self._selected_device()))
        return True

    def action_tab_bar(self, step):
        bar = self.query_one("#tabs Tabs", Tabs)
        bar.action_next_tab() if step > 0 else bar.action_previous_tab()

    def action_content(self):
        self._focus_main(self.query_one("#tabs", TabbedContent).active)

    def action_tab(self, tid):
        if self.query_one("#tabs", TabbedContent).active != tid:
            self.set_focus(None)              # a focused card on the old tab would pull it back
        self.query_one("#tabs", TabbedContent).active = tid
        self.call_after_refresh(self._focus_main, tid)

    def action_tab_step(self, step):
        cur = self.query_one("#tabs", TabbedContent).active
        i = self.TABS.index(cur) if cur in self.TABS else 0
        self.action_tab(self.TABS[(i + step) % len(self.TABS)])

    def _focus_main(self, tid):
        """Put the keyboard where the tab's keys act: the current card, or the tab's table.
        Only for the tab still showing: focusing a widget on a hidden tab would switch to it."""
        if len(self.screen_stack) > 1 or self.query_one("#tabs", TabbedContent).active != tid:
            return
        try:
            if tid == "status":
                w = self.query_one(f"#card-{self.current}", CardButton) if self.current else None
                (w or self.query_one("#cards").query(CardButton).first()).focus()
            elif tid == "provision":
                self.query_one("#provision-tree", Tree).focus()
            else:
                self.query_one(self.MAIN[tid], HintTable).focus()
        except Exception:
            pass

    def action_card_step(self, step):
        cards = list(self.query_one("#cards", VerticalScroll).query(CardButton))
        if not cards:
            return
        try:
            i = next(n for n, w in enumerate(cards) if w.has_focus)
        except StopIteration:
            i = next((n for n, w in enumerate(cards) if w.card["id"] == self.current), 0)
        if i == 0 and step == -1:
            self.query_one("#tabs Tabs", Tabs).focus()
            return
        w = cards[max(0, min(len(cards) - 1, i + step))]
        w.focus()
        w.scroll_visible()
        self.show_card(w.card["id"], focus=False)

    def action_pane(self, step):
        """STATUS: left/h to the card list, right/l to the card's detail table."""
        if self.query_one("#tabs", TabbedContent).active != "status":
            return
        if step > 0:
            self.query_one("#detail", HintTable).focus()
        else:
            self._focus_main("status")

    def action_refresh(self):
        self.load_status()
        self.load_jobs()
        tab = self.query_one("#tabs", TabbedContent).active
        if tab == "models":
            self.load_models()
        if tab == "doctor":
            self.load_doctor()
        if tab == "network":
            self.load_network()

    def action_doctor(self):
        self.action_tab("doctor")
        self.query_one("#docsum", Static).update("running the checks…")
        self.load_doctor()

    @on(Button.Pressed, "#yt-add")
    def _yt_add_pressed(self):
        self.action_youtube_add()

    def action_youtube_add(self):
        try:
            q = self.src.youtube_quality()
        except Exception:
            q = "1080p"
        self.push_screen(AddYouTube(q), self._youtube_added)

    def _youtube_added(self, form):
        if form:
            self.notify(f"adding {form['url']}…")
            self.youtube_add(form)

    @work(thread=True, group="youtube")
    def youtube_add(self, form):
        try:
            words = self.src.youtube_add(form["url"], form["kind"], form["since"], form["name"], form["quality"])
        except Exception as e:                        # PinchflatError's words, or what broke
            self.call_from_thread(self.notify, str(e), severity="error", timeout=12)
            return
        self.call_from_thread(self.notify, words, timeout=12)
        self.call_from_thread(self.load_status)

    def action_new_job(self):
        if not self.pending_submit:
            self.push_screen(RunJob(self.src.kinds()), self._queued)

    def _queued(self, choice):
        if not choice or self.pending_submit:
            return
        v, prompt = choice
        kind, preset = (None, v[2:]) if v.startswith("p:") else (v[2:], None)
        text = prompt if (kind == "voice" or preset == "voice-line") else None
        self.pending_submit = True
        self._job_actions()
        self.refresh_bindings()
        self.notify("Queuing job…")
        self.submit_job(kind, preset, None if text else prompt, text)

    @work(thread=True, group="job-submit")
    def submit_job(self, kind, preset, prompt, text):
        try:
            job = self.src.submit(kind, preset, prompt, text)
        except Exception as error:
            self.call_from_thread(self._job_finished, None, None, f"Could not queue job: {error}", True)
        else:
            self.call_from_thread(self._job_finished, None, f"Queued {job['id']}", None, True)

    def _job_finished(self, jid, message, error, submit=False):
        if submit:
            self.pending_submit = False
        else:
            self.pending_jobs.discard(jid)
        self._job_actions()
        self.refresh_bindings()
        self.notify(error or message, severity="error" if error else "information", timeout=8)
        if submit and not error and len(self.screen_stack) == 1:
            self.action_tab("jobs")
        self.load_jobs()

    def action_media(self):
        """The media library (bromigos media), in this terminal; back here when it's closed."""
        exe = _media_bin()
        if not exe:
            self.notify("bromigos media isn't installed", severity="warning")
            return
        import subprocess
        with self.suspend():
            subprocess.run([exe])
        self.load_status()

    @on(Button.Pressed, "#job-new")
    def _new_pressed(self):
        self.action_new_job()

    @on(Button.Pressed, "#job-cancel")
    def _cancel_pressed(self):
        self.action_cancel_job()

    @on(Button.Pressed, "#job-retry")
    def _retry_pressed(self):
        self.action_retry_job()

    def action_cancel_job(self):
        j = self._selected_job()
        if not j or j["id"] in self.pending_jobs or self.query_one("#tabs", TabbedContent).active != "jobs":
            return
        if j["state"] not in ("running", "queued", "waiting"):
            self.notify("This job has already finished", severity="warning")
            return
        jid = j["id"]
        self.push_screen(CancelJob(j), lambda yes: self._cancel_confirmed(jid, yes))

    def _cancel_confirmed(self, jid, yes):
        if not yes or jid in self.pending_jobs:
            return
        self._start_job_action(jid, "cancel")

    def _start_job_action(self, jid, action):
        if jid in self.pending_jobs:
            return
        self.pending_jobs.add(jid)
        self._job_actions()
        self.refresh_bindings()
        self.notify(f"{'Cancelling' if action == 'cancel' else 'Retrying'} {jid}…")
        self.change_job(jid, action)

    @work(thread=True, group="job-change")
    def change_job(self, jid, action):
        try:
            result = self.src.cancel(jid) if action == "cancel" else self.src.retry(jid)
        except Exception as error:
            self.call_from_thread(self._job_finished, jid, None, f"Could not {action} {jid}: {error}")
        else:
            message = f"Cancellation requested for {jid}" if action == "cancel" else f"Queued {result['id']}"
            self.call_from_thread(self._job_finished, jid, message, None)

    def action_retry_job(self):
        j = self._selected_job()
        if j and self.query_one("#tabs", TabbedContent).active == "jobs":
            self._start_job_action(j["id"], "retry")


def _media_bin():
    import shutil
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    return next((p for p in (os.path.join(here, "bin", "bromigos-media"), "/usr/lib/bromigos/bin/bromigos-media",
                             shutil.which("bromigos-media")) if p and os.path.exists(p)), None)


def main():
    LabApp().run()
    return 0
