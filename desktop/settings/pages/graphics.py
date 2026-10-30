"""Graphics (docs/settings.md, "Graphics"): every graphics card in the computer, any vendor
and any number of them, and what each is for: the desktop (the login screen and
Hyprland), games and heavy apps, or virtual machines (VFIO passthrough).

Everything goes through `bromigos hw` (docs/hardware.md, "What each card is for"):

- `hw graphics --json` reads the cards and the choices, every time the page is shown (a
  card swapped since counts as Automatic);
- the desktop's card: `hw display use CARD|auto`, `keep`, `cancel`. A new card is a trial:
  log out and in on it, then Keep it here. A restart before that goes back by itself, and
  `sudo bromigos hw display reset` from a text console goes back to Automatic. It asks
  for your password (pkexec): the login screen reads the choice too;
- games and heavy apps: `hw games use CARD|auto`, and `hw games steam on|off` (yours, no
  password); `bromigos hw run` starts a program on that card;
- virtual machines: `hw vfio reserve|release CARD` in a terminal (sudo, the initramfs made
  again, then a restart), after the checks the command makes.

DRIFTGLASS (docs/DRIFTGLASS.md): a GLOW page. Each card's hologram stands on its Emitter,
lit while the card draws the desktop or runs games, dim otherwise; nothing moves."""
import os
import sys

from gi.repository import Adw, Gdk, GLib, Gtk

from bromigos_settings import Entry, Page

for _p in ("/usr/lib/bromigos/lib", os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "lib")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import bromigos_driftglass as H  # noqa: E402
except ImportError:                    # a page from a plugin folder without the library
    H = None

HW = ["bromigos", "hw"]
SYSTEM_FILE = "/var/lib/bromigos/hw/graphics.json"
WICK = {"void": "#000500", "panel": "#001300", "primary": "#39ff14", "dim": "#159b09", "white": "#e8ffe0",
        "warn": "#d4af37", "danger": "#ff766f"}
# a use that's on reads as lit in the theme's colour, as a chosen toggle does elsewhere
# (over the house style, which sits at the user priority)
CSS = """
.gx-uses > button:checked {{ background-color: alpha({p}, 0.16); color: {p}; border-color: {p}; }}
"""
_prov = None


def _css(colors):
    global _prov
    p = (colors or {}).get("primary") or WICK["primary"]
    if _prov is None:
        _prov = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), _prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
    text = CSS.format(p=p)
    _prov.load_from_string(text) if hasattr(_prov, "load_from_string") else _prov.load_from_data(text.encode())


USES = [("desktop", "Desktop"), ("games", "Games and heavy apps"), ("vms", "Virtual machines")]


def _pal(ctx):
    p = dict(WICK)
    p.update({k: v for k, v in (ctx.colors or {}).items() if isinstance(v, str) and v.startswith("#")})
    return p


def _hc():
    try:
        import bromigos_theme as T
        return T.high_contrast()
    except Exception:
        return False


class GraphicsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.groups = []
        self.page = ctx.page()
        _css(ctx.colors)
        ctx.on_restyle(_css)
        self.page.set_reset(None, hint="Reading the cards…")
        g = self._group("In use", key="uses")
        self.wait = ctx.loading(g, "Reading the graphics cards…")
        self.refresh()

    # ------------------------------------------------------------------ reading
    def refresh(self):
        self.ctx.json(HW + ["graphics", "--json"], self._got)

    def _group(self, title, description=None, key=None, hint=None):
        g = self.ctx.group(self.page, title, description, key=key, hint=hint)
        self.groups.append(g)
        return g

    def _clear(self):
        for g in self.groups:
            self.page.remove_group(g)
        self.groups = []

    def _card(self, slot):
        return next((c for c in (self.doc or {}).get("cards", []) if c.get("slot") == slot), None)

    def _name(self, slot, fallback="none"):
        c = self._card(slot)
        return c["title"] if c else fallback

    def _got(self, doc, err):
        self._clear()
        self.doc = doc
        if not doc or doc.get("ok") is False:
            g = self._group("In use", key="uses")
            self.ctx.failed(g, HW + ["graphics", "--json"], (doc or {}).get("error") or err)
            return
        dk, gm = doc.get("desktop") or {}, doc.get("games") or {}
        explicit = bool(dk.get("choice") or dk.get("trial") or gm.get("choice"))
        self.page.set_reset(
            self.reset if explicit else None,
            hint=None if explicit else "The desktop and games already follow Automatic. Cards reserved for virtual "
                                       "machines stay reserved: release them on their card",
            what="The desktop's card and the games card back to Automatic, from your next login (your password is "
                 "asked for the desktop's). Cards reserved for virtual machines stay as they are.")
        self._uses(doc)
        for n, c in enumerate(doc.get("cards") or []):
            self._card_group(n, c)
        self._vms(doc)

    # ------------------------------------------------------------------ in use
    def _uses(self, doc):
        ctx = self.ctx
        g = self._group("In use", "What draws your desktop, what runs your games, and what's kept for virtual "
                                  "machines. Each card below has the same choices.", key="uses")
        dk = doc.get("desktop") or {}
        nxt = dk.get("next") or {}
        trial = dk.get("trial")
        if trial and dk.get("trial_in_force"):
            here = dk.get("running") == trial.get("slot")
            box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
            box.append(ctx.button("Keep", self.keep, "Keeps this card for the login screen and the desktop "
                                                     "(asks for your password)", primary=here))
            box.append(ctx.button("Go back", self.cancel, "Stops trying it: the next login uses "
                                                           f"{self._name((dk.get('choice') or {}).get('slot'), 'Automatic')} "
                                                           "again (asks for your password)"))
            r = ctx.row(g, f"Trying {trial.get('name')} for the desktop",
                        ("You're on it now: keep it if everything looks right." if here else
                         "Log out and back in to try it, then keep it here.") +
                        " Restarting the computer before you keep it goes back by itself.",
                        hint="A new desktop card is a trial until you keep it, so a card that shows nothing can't "
                             "lock you out. From a text console, sudo bromigos hw display reset goes back to "
                             "Automatic.", control=box, key="trial",
                        advanced={"runs": "bromigos hw display keep | cancel", "file": SYSTEM_FILE})
            r.add_css_class("bromigos-warn")
        elif trial:
            ctx.note(g, f"The last try of {trial.get('name')} ended when the computer restarted, without Keep: "
                        "the desktop went back. Choose it again below to try it again.", "warn",
                     hint="A trial lasts until the computer restarts")
        slot = nxt.get("slot") or dk.get("automatic")
        src = nxt.get("source")
        sub = {"trial": "Being tried", "chosen": "Chosen by you"}.get(src, "Automatic: the only card with a monitor, "
                                                                           "else the computer's own choice")
        if doc.get("laptop") and src == "automatic":
            sub = "Automatic: on a laptop, the built-in card (it saves the battery)"
        btns = []
        if dk.get("choice"):
            btns.append(("Automatic", lambda: self.desktop(None), "Lets bromigOS choose the desktop's card again, "
                                                                     "from your next login (asks for your password)"))
        ctx.row(g, "Desktop", f"{self._name(slot, 'the compositor’s own choice')} · {sub}" +
                (f". {nxt['note']}" if nxt.get("note") else ""), key="desktop", buttons=btns,
                hint="The card the login screen and the desktop draw on. Only a card with a monitor connected can "
                     "be chosen. It changes at your next login.",
                advanced={"runs": "bromigos hw display use CARD|auto", "file": SYSTEM_FILE,
                          "note": "the login screen and Hyprland read it at start; a restart ends a trial"})
        gm = doc.get("games") or {}
        gsub = "Chosen by you" if gm.get("source") == "chosen" else "Automatic: the strongest card"
        btns = []
        if gm.get("choice"):
            btns.append(("Automatic", lambda: self.games(None), "Games and heavy apps go back to the strongest card"))
        ctx.row(g, "Games and heavy apps", f"{self._name(gm.get('slot'))} · {gsub}" +
                ("".join(f". {n}" for n in gm.get("notes") or [])), key="games", buttons=btns,
                hint="The card programs started with bromigos hw run use, Steam too when it starts on it (below). "
                     "Automatic picks a card of its own over a built-in one, then the newest, then the one with the "
                     "most video memory.",
                advanced={"runs": "bromigos hw games use CARD|auto", "file": doc.get("user_file") or
                          "~/.config/bromigos/graphics.json"})
        if gm.get("steam_installed") or gm.get("steam"):
            ctx.switch_row(g, "Start Steam on the games card", "Steam and every game it starts, Proton's too",
                           active=bool(gm.get("steam")), key="steam",
                           on_toggle=lambda on: self.change(HW + ["games", "steam", "on" if on else "off", "--json"],
                                                            "Steam changed"),
                           hint="Your copy of Steam's launcher starts it through bromigos hw run, so it follows the "
                                "games card, whichever card that is when Steam starts. Off removes the copy.",
                           advanced={"runs": "bromigos hw games steam on|off",
                                     "file": "~/.local/share/applications/steam.desktop"})
        else:
            ctx.row(g, "Start Steam on the games card", "Steam isn't installed: bromigos game setup installs it",
                    key="steam", hint="Once Steam is installed, this starts it on the games card")
        ctx.row(g, "Run a program on the games card", "bromigos hw run -- PROGRAM. In a Steam game's launch "
                                                      "options: bromigos hw run -- %command%", key="run",
                hint="Sets each vendor's own switches for that one program (Vulkan's device order, Mesa's DRI_PRIME, "
                     "NVIDIA's PRIME render offload), and nothing when the desktop's card is the games card too",
                buttons=[("Copy", lambda: ctx.copy("bromigos hw run -- %command%"),
                          "Copies the launch option for a Steam game")],
                advanced={"runs": "bromigos hw run --print (the variables it sets)"})

    # ------------------------------------------------------------------ each card
    def _glyph(self, c):
        a = Gtk.DrawingArea(content_width=56, content_height=48)
        live = bool(c.get("desktop_next") or c.get("games"))
        pal, hc = _pal(self.ctx), _hc()

        def draw(_a, cr, w, h):
            if H is not None:
                H.glyph(cr, "gpu", (w - h) / 2, 0, h, pal, live=live, still=True, hc=hc)
        a.set_draw_func(draw)
        self.ctx.hint(a, f"{c['title']}: lit while it draws the desktop or runs games" if live else
                      f"{c['title']}: dim, nothing uses it in particular" +
                      (" (reserved for virtual machines)" if (c.get("vfio") or {}).get("reserved") else ""))
        return a

    def _card_group(self, n, c):
        ctx = self.ctx
        conns = c.get("connected_connectors") or []
        desc = " · ".join(x for x in (
            c["slot"], f"driver {c.get('driver') or 'none'}",
            ("monitor on " + ", ".join(conns)) if conns else "no monitor",
            "built in" if c.get("integrated") else None,
            "this session draws on it" if c.get("desktop_now") else None) if x)
        g = self._group(c["title"], desc, key=f"card-{n}",
                        hint=f"{c['title']} ({c.get('id')}) at PCI address {c['slot']}")
        v = c.get("vfio") or {}
        on = {"desktop": bool(c.get("desktop_next")), "games": bool(c.get("games")), "vms": bool(v.get("reserved"))}
        box = Gtk.Box(valign=Gtk.Align.CENTER)
        box.add_css_class("linked")
        box.add_css_class("gx-uses")
        for use, label in USES:
            b = Gtk.ToggleButton(label=label, active=on[use])
            b._quiet = False
            b.connect("toggled", lambda btn, u=use: btn._quiet or self._use(c, u, btn))
            ctx.hint(b, self._use_hint(c, use, on[use]))
            box.append(b)
        wrap = Adw.WrapBox(child_spacing=6, line_spacing=6, justify=Adw.JustifyMode.NONE)
        wrap.set_halign(Gtk.Align.END)
        wrap.append(box)
        r = ctx.row(g, "Use for", ", ".join(lab for u, lab in USES if on[u]) or "Nothing in particular",
                    hint="What this card is for: one card draws the desktop, one runs games and heavy apps (the "
                         "same card can do both), and cards reserved for virtual machines do nothing else",
                    control=wrap, key="use" if n == 0 else None,
                    advanced={"runs": f"bromigos hw display use {c['slot']} · bromigos hw games use {c['slot']} · "
                                      f"bromigos hw vfio reserve {c['slot']}"})
        r.add_prefix(self._glyph(c))
        # virtual machines: the checks, each with its reason
        checks = v.get("checks") or []
        failed = [x for x in checks if not x.get("ok")]
        ex = Adw.ExpanderRow(title=GLib.markup_escape_text("Virtual machines"),
                             subtitle=GLib.markup_escape_text(
                                 "Reserved: vfio-pci holds it from the next start" if v.get("reserved") else
                                 "Ready to reserve" if v.get("ready") else
                                 f"Not ready: {failed[0]['text']}" if failed else "Not checked"))
        ctx.hint(ex, "The checks before a card can be handed to a virtual machine (VFIO passthrough). Open for each "
                     "one; hover over a check for why it matters")
        if v.get("bound"):
            ex.set_subtitle(GLib.markup_escape_text("vfio-pci holds it now: a virtual machine can use it"))
        for x in checks:
            cr = Adw.ActionRow(title=GLib.markup_escape_text(x["text"]))
            cr.set_title_lines(3)
            cr.add_prefix(Gtk.Image.new_from_icon_name("object-select-symbolic" if x["ok"] else
                                                       "dialog-warning-symbolic"))
            ctx.hint(cr, x.get("hint"))
            ex.add_row(cr)
        if v.get("functions"):
            fr = Adw.ActionRow(title=GLib.markup_escape_text("Goes with it: " + ", ".join(v["functions"])))
            ctx.hint(fr, "The card's other parts (its HDMI audio, a USB-C controller) are reserved with it, by "
                         "their PCI addresses")
            ex.add_row(fr)
        if v.get("reset"):
            rr = Adw.ActionRow(title=GLib.markup_escape_text(v["reset"]))
            rr.set_title_lines(4)
            rr.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
            ctx.hint(rr, "AMD's Polaris, Vega, Navi 10, 12 and 14 cards can't reset themselves between VM runs")
            ex.add_row(rr)
        g.add(ex)

    def _use_hint(self, c, use, active):
        v = c.get("vfio") or {}
        if use == "desktop":
            if active:
                return "Draws the login screen and the desktop. Choose another card's Desktop to move it"
            if v.get("reserved"):
                return "Reserved for virtual machines: release it first"
            if not c.get("desktop_ready"):
                return "Can't draw the desktop: " + ("connect a monitor to it first" if c.get("driver") else
                                                     "its driver isn't working")
            return ("Draws the login screen and the desktop from your next login. It's tried first: keep it after "
                    "logging in on it, or restart to go back")
        if use == "games":
            if active:
                return "Games and heavy apps run on it. Choose another card's to move them"
            if not c.get("game_ready"):
                return "Can't run programs: it has no working driver (or it's reserved for virtual machines)"
            return "Runs games and heavy apps (bromigos hw run, and Steam when it starts on the games card)"
        if v.get("reserved"):
            return "Reserved for virtual machines from the next start. Turn off to give it back (sudo, then restart)"
        if v.get("ready"):
            return ("Reserves it for virtual machines by its PCI address, with its audio: vfio-pci holds it from the "
                    "next start (a terminal runs the commands with sudo)")
        failed = [x["text"] for x in v.get("checks") or [] if not x.get("ok")]
        return "Can't be reserved yet: " + "; ".join(failed) if failed else "Not checked"

    def _undo(self, btn):
        btn._quiet = True
        try:
            btn.set_active(not btn.get_active())
        finally:
            btn._quiet = False

    def _use(self, c, use, btn):
        """A Use for button flipped: act, or say why not and put it back."""
        ctx = self.ctx
        want = btn.get_active()
        v = c.get("vfio") or {}
        dk = (self.doc or {}).get("desktop") or {}
        gm = (self.doc or {}).get("games") or {}
        if use == "desktop":
            self._undo(btn)
            if not want:
                if (dk.get("choice") or {}).get("slot") == c["slot"]:
                    self.desktop(None)
                else:
                    ctx.toast("It's the automatic choice: choose Desktop on another card to move the desktop")
                return
            if v.get("reserved") or not c.get("desktop_ready"):
                ctx.toast(self._use_hint(c, "desktop", False))
                return
            if (dk.get("choice") or {}).get("slot") == c["slot"]:
                self.desktop(c["slot"])         # the kept card, while another is tried: back to it
                return
            current = self._name((dk.get("next") or {}).get("slot") or dk.get("automatic"), "the automatic choice")
            ctx.confirm(f"Try {c['title']} for the desktop?",
                        "The login screen and the desktop move to it from your next login. bromigOS asks for your "
                        "password, then you log out and back in to try it, and keep it here.\n\n"
                        f"If the screen stays dark, restart the computer: it goes back to {current} by itself. From a "
                        "text console (Ctrl+Alt+F3), sudo bromigos hw display reset goes back to Automatic.",
                        "Try it", lambda: self.desktop(c["slot"]))
        elif use == "games":
            self._undo(btn)
            if not want:
                if (gm.get("choice") or {}).get("slot") == c["slot"]:
                    self.games(None)
                else:
                    ctx.toast("It's the automatic choice: choose Games on another card to move them")
                return
            if not c.get("game_ready"):
                ctx.toast(self._use_hint(c, "games", False))
                return
            self.games(c["slot"])
        else:
            self._undo(btn)
            if want and not v.get("ready"):
                ctx.toast(self._use_hint(c, "vms", False)[:200], timeout=8)
                return
            if want:
                fn = ", ".join(v.get("functions") or []) or "none"
                ctx.confirm(f"Reserve {c['title']} for virtual machines?",
                            f"From the next start vfio-pci holds it, with its other parts ({fn}), so a virtual "
                            "machine can use it; the desktop and programs can't. A terminal opens to write three "
                            "files and make the initramfs again, with sudo. Restart the computer afterwards.",
                            "Reserve…", lambda: self._terminal(["vfio", "reserve", c["slot"]]))
            else:
                ctx.confirm(f"Give {c['title']} back?",
                            "From the next start its own driver takes it again, and the desktop and games can use it. "
                            "A terminal opens to run the commands with sudo. Restart the computer afterwards.",
                            "Give it back…", lambda: self._terminal(["vfio", "release", c["slot"]]))

    # ------------------------------------------------------------------ changes
    def change(self, argv, said, undo=None):
        self.ctx.change(argv, lambda d: d.get("said") or said, undo=undo, done=lambda *_: self.refresh(),
                        failed=lambda *_: self.refresh())

    def desktop(self, slot):
        self.change(HW + ["display", "use", slot or "auto", "--json"], "Desktop card changed")

    def games(self, slot):
        prev = ((self.doc or {}).get("games") or {}).get("choice")
        undo = HW + ["games", "use", prev["slot"] if prev else "auto", "--json"]
        self.change(HW + ["games", "use", slot or "auto", "--json"], "Games card changed", undo=undo)

    def keep(self):
        self.change(HW + ["display", "keep", "--json"], "Kept")

    def cancel(self):
        self.change(HW + ["display", "cancel", "--json"], "Not trying it")

    def _terminal(self, args):
        self.ctx.terminal(HW + args)
        self.ctx.toast("In the terminal: restart the computer when it's done", timeout=8)

    def reset(self):
        doc = self.doc or {}
        if (doc.get("games") or {}).get("choice"):
            self.change(HW + ["games", "use", "auto", "--json"], "Games: Automatic")
        if (doc.get("desktop") or {}).get("choice") or (doc.get("desktop") or {}).get("trial"):
            self.change(HW + ["display", "use", "auto", "--json"], "Desktop: Automatic")

    # ------------------------------------------------------------------ virtual machines
    def _vms(self, doc):
        ctx = self.ctx
        io = doc.get("iommu") or {}
        g = self._group("Virtual machines", "A card reserved here goes to virtual machines whole (VFIO "
                                            "passthrough), by its PCI address, so two identical cards stay apart.",
                        key="vms")
        steps = io.get("steps") or []
        ctx.row(g, "IOMMU", "On: cards can be handed to virtual machines" if io.get("on") else
                "Off: " + (steps[0] if steps else "turn it on in the firmware settings"), key="iommu",
                hint="The IOMMU keeps a VM's card to the VM's own memory." + (
                    "" if io.get("on") else " To turn it on: " + " ".join(steps)),
                buttons=[] if io.get("on") or not steps else [
                    ("Copy steps", lambda: ctx.copy("\n".join(steps)), "Copies the steps, to follow from a terminal")],
                advanced={"reads": "/sys/kernel/iommu_groups"})
        res = doc.get("reserved") or []
        ctx.row(g, "Reserved", ", ".join(r["card"]["name"] for r in res) or "No card", key="reserved",
                hint="The cards vfio-pci takes at start. A card that's gone, or another card in its slot, is left "
                     "to its own driver; so is the card the firmware starts on, and the last card with a display",
                advanced={"file": "/etc/modprobe.d/bromigos-vfio.conf, /etc/mkinitcpio.conf.d/bromigos-vfio.conf, "
                                  "/etc/bromigos/hw/vfio-pci-override.sh",
                          "runs": "bromigos hw vfio reserve|release CARD"})
        ctx.row(g, "Handing a card over while the computer runs", "Not built yet: a reserved card stays reserved "
                                                                  "until you release it and restart", key="handover",
                hint="Giving a card to a VM only while it runs (libvirt hooks) is planned. Today a card is reserved "
                     "from start to start")


def build(ctx):
    p = GraphicsPage(ctx)
    p.page._graphics = p
    return p.page


def refresh(widget):
    widget._graphics.refresh()


PAGE = Page(
    id="graphics", title="Graphics", group="system", order=15, build=build, refresh=refresh,
    docs="settings.md#graphics", icon="video-card-symbolic video-display-symbolic computer-symbolic",
    summary="what each graphics card is for",
    intro="Every graphics card in this computer, and what each is for: the desktop, games and heavy apps, or "
          "virtual machines. A new desktop card is tried first, and a restart goes back by itself.",
    keywords=["gpu", "graphics card", "video card", "nvidia", "amd", "radeon", "intel", "vfio", "passthrough",
              "prime", "dri_prime", "multi-gpu", "egpu"],
    entries=[
        Entry("desktop", "Desktop graphics card", ["login screen gpu", "render gpu", "primary gpu", "display card"],
              "In use"),
        Entry("games", "Games and heavy apps card", ["gaming gpu", "offload", "prime-run", "dri_prime"], "In use"),
        Entry("steam", "Start Steam on the games card", ["steam gpu", "proton gpu"], "In use"),
        Entry("run", "Run a program on the games card", ["bromigos hw run", "launch options"], "In use"),
        Entry("iommu", "IOMMU", ["vt-d", "amd-vi", "intel_iommu"], "Virtual machines"),
        Entry("reserved", "Cards reserved for virtual machines", ["vfio", "passthrough", "vm gpu", "vfio-pci"],
              "Virtual machines"),
    ])
