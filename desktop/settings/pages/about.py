"""About: bromigOS's version and channel, its packages and the main components', this
machine's hardware, the licences, the last update, and where the manual is
(docs/settings.md, "About"). Read from `bromigos about --json` (pacman, `bromigos hw`,
/proc, pacman's log); Copy system info puts the same as plain lines on the clipboard, for a
bug report."""
from gi.repository import Adw

from bromigos_settings import Entry, Page


def _esc(text):
    """Text for a row's title or subtitle (they take Pango markup): &, < and > escaped."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

ABOUT = ["bromigos", "about"]


def _gib(b):
    return f"{b / 2**30:.1f} GiB" if b else "?"


class AboutPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = ctx.page()
        self.page.set_reset(None, hint="About only shows: there's nothing here to reset")
        self.groups = []
        g = ctx.group(self.page, "bromigOS", key="bromigos")
        self.groups.append(g)
        self.wait = ctx.loading(g, "Reading the packages and the hardware…")
        ctx.json(ABOUT + ["--json"], self._got)

    def _clear(self):
        for g in self.groups:
            self.page.remove_group(g)
        self.groups = []

    def _group(self, title, description=None, key=None):
        g = self.ctx.group(self.page, title, description, key=key)
        self.groups.append(g)
        return g

    def _expander(self, group, title, subtitle, hint, rows):
        ex = Adw.ExpanderRow(title=_esc(title), subtitle=_esc(subtitle))
        self.ctx.hint(ex, hint)
        for t, sub, h in rows:
            r = Adw.ActionRow(title=_esc(t), subtitle=_esc(sub or ""))
            self.ctx.hint(r, h)
            ex.add_row(r)
        group.add(ex)
        return ex

    def _got(self, d, err):
        ctx = self.ctx
        self._clear()
        g = self._group("bromigOS", key="bromigos")
        if not d or d.get("ok") is False:
            ctx.failed(g, ABOUT + ["--json"], (d or {}).get("error") or err)
            return
        ctx.row(g, "Welcome tour", "Wi-Fi, your screens, a world, VECTOR, your homelab and the keys, step by step",
                hint="The tour a new install opens with (bromigos welcome): every step can be skipped", key="welcome",
                buttons=[("Open", self._welcome, "Opens the welcome tour, full screen")])
        ctx.row(g, "Version", f"bromigOS {d.get('version') or '?'}", key="version",
                hint="The bromigos command's version (bromigos --version)",
                buttons=[("Copy system info", self._copy, "Copies the version, the hardware and the packages as "
                                                          "plain lines, for a bug report")],
                advanced={"runs": "bromigos about text"})
        ctx.row(g, "Channel", f"{d.get('channel') or 'none'}" + (f" · {d['server']}" if d.get("server") else ""),
                key="channel", hint="The update channel this machine follows: switch it on Updates & recovery",
                activate=lambda: ctx.open_page("updates"), advanced={"runs": "bromigos channel"})
        u = d.get("last_update")
        ctx.row(g, "Last update", (f"{(u.get('at') or '')[:16].replace('T', ' ')}: " +
                                   (f"{u['packages']} packages" if u.get("packages") else "nothing was waiting"))
                if u else "None in pacman's log", key="last-update",
                hint="The last full system upgrade pacman recorded (pacman -Syu or bromigos update)",
                advanced={"reads": (u or {}).get("log") or "/var/log/pacman.log"})
        ctx.row(g, "This computer", f"{d.get('host')} · Linux {d.get('kernel')} ({d.get('arch')})", key="kernel",
                hint="The host name and the running kernel")

        h = d.get("hardware") or {}
        hw = self._group("Hardware", key="hardware")
        cpu = h.get("cpu") or {}
        ctx.row(hw, "Processor", f"{cpu.get('model') or '?'} · {cpu.get('threads') or '?'} threads", key="cpu",
                hint="From /proc/cpuinfo")
        ctx.row(hw, "Memory", _gib(h.get("memory")), key="memory", hint="From /proc/meminfo")
        for n, gpu in enumerate(h.get("gpus") or []):
            ctx.row(hw, "Graphics" if n == 0 else f"Graphics {n + 1}",
                    f"{gpu.get('vendor') or ''} {gpu.get('name') or '?'} · driver {gpu.get('driver') or 'none'}",
                    key="gpu" if n == 0 else None, hint="From bromigos hw (docs/hardware.md)",
                    advanced={"runs": "bromigos hw"})
        m = h.get("machine") or {}
        ctx.row(hw, "Machine", " ".join(x for x in (m.get("vendor"), m.get("product")) if x) +
                f" ({m.get('kind') or '?'}" + (f", {m['virt']}" if m.get("virt") else "") + ")", key="machine",
                hint="The firmware's vendor and product, and what kind of machine bromigos hw takes it for")
        if h.get("disk"):
            ctx.row(hw, "Disk", f"{_gib(h['disk']['size'])}, {_gib(h['disk']['free'])} free", key="disk",
                    hint="The root filesystem's size and the space left")

        pk = self._group("Packages", "bromigOS's packages, and the main pieces it's built on (pacman -Q).",
                         key="packages")
        pkgs = d.get("packages")
        if pkgs is None:
            ctx.note(pk, "pacman isn't here to ask", "warn", hint="The packages come from pacman -Q")
        else:
            ours = [p for p in pkgs if p["bromigos"]]
            theirs = [p for p in pkgs if not p["bromigos"]]
            ex = self._expander(pk, "bromigOS", f"{len(ours)} packages", "Open for each bromigOS package's version",
                                [(p["name"], p["version"], f"{p['name']} {p['version']} ({p.get('licence') or '?'})")
                                 for p in ours])
            ex._bromigos_key = "bromigos-packages"
            ex2 = self._expander(pk, "What it's built on", ", ".join(p["name"] for p in theirs) or "none",
                                 "Open for each component's version", [(p["name"], p["version"], f"{p['name']} {p['version']}")
                                                                       for p in theirs])
            ex2._bromigos_key = "components"

        lic = d.get("licences") or {}
        lg = self._group("Licences", key="licences")
        files = lic.get("files") or []
        ctx.row(lg, "bromigOS's code", lic.get("bromigos") or "MIT OR Apache-2.0", key="licence",
                hint="bromigOS's code is yours under either licence",
                buttons=[(f"{'MIT' if 'MIT' in f else 'Apache-2.0'}", lambda f=f: ctx.open_file(f),
                          f"Opens {f}") for f in files], advanced={"file": files[0] if files else "LICENSE-MIT"})
        for t in lic.get("terms") or []:
            if t["what"].startswith("bromigOS's code"):
                continue
            ctx.row(lg, t["what"], t["licence"], hint="What ships beside the code, and on what terms (docs/ASSETS.md)")
        if lic.get("packages"):
            ex = self._expander(lg, "Each package's licence", f"{len(lic['packages'])} packages",
                                "Open for the licence pacman records for each package",
                                [(p["name"], p["licence"], f"{p['name']}: {p['licence']}") for p in lic["packages"]])
            ex._bromigos_key = "package-licences"

        links = d.get("links") or {}
        hg = self._group("Help", key="help")
        ctx.row(hg, "The manual", links.get("manual", ""), key="manual",
                hint="The bromigOS manual: the copy installed on this machine (it matches your version and "
                     "works offline), else the one published next to your packages",
                buttons=[("Open", lambda: ctx.open_url(links.get("manual")), "Opens the manual in your browser")])
        if links.get("manual_installed") and links.get("manual_online"):
            ctx.row(hg, "The manual online", links["manual_online"], key="manual-online",
                    hint="The manual published next to your packages: built from the newest code, for every channel",
                    buttons=[("Open", lambda: ctx.open_url(links["manual_online"]), "Opens it in your browser")])
        ctx.row(hg, "The source", links.get("repository", ""), key="source",
                hint="bromigOS's repository: the code, the developer docs, the issues",
                buttons=[("Open", lambda: ctx.open_url(links.get("repository")), "Opens the repository in your browser")])

    def _welcome(self, *_):
        import subprocess
        subprocess.Popen(["bromigos", "welcome"], start_new_session=True)

    def _copy(self):
        def done(doc, err):
            if doc and doc.get("text"):
                self.ctx.copy(doc["text"])
            else:
                self.ctx.toast(f"bromigos about didn't answer: {err}")
        self.ctx.json(ABOUT + ["text", "--json"], done)


def build(ctx):
    return AboutPage(ctx).page


PAGE = Page(
    id="about", title="About", group="about", order=10, build=build, docs="settings.md#about",
    icon="help-about-symbolic computer-symbolic", summary="version, hardware, licences",
    intro="bromigOS on this machine: the version and channel, the packages, the hardware, the licences, and where "
          "the manual is.",
    keywords=["version", "system info", "hardware", "specs", "licence", "license", "packages", "kernel"],
    entries=[
        Entry("welcome", "Welcome tour", ["first run", "walkthrough", "tour", "onboarding", "setup"], "bromigOS"),
        Entry("version", "bromigOS version", ["version", "release", "copy system info"], "bromigOS"),
        Entry("channel", "Update channel", ["edge", "stable"], "bromigOS"),
        Entry("last-update", "Last update", ["updated", "pacman -Syu"], "bromigOS"),
        Entry("kernel", "Kernel and host name", ["linux version", "hostname"], "bromigOS"),
        Entry("cpu", "Processor", ["cpu", "threads"], "Hardware"),
        Entry("memory", "Memory", ["ram"], "Hardware"),
        Entry("gpu", "Graphics", ["gpu", "graphics card", "driver"], "Hardware"),
        Entry("machine", "Machine", ["model", "vendor", "laptop"], "Hardware"),
        Entry("disk", "Disk space", ["storage", "free space"], "Hardware"),
        Entry("bromigos-packages", "bromigOS's packages", ["versions"], "Packages"),
        Entry("components", "What it's built on", ["hyprland version", "gtk", "pipewire"], "Packages"),
        Entry("licence", "Licences", ["license", "mit", "apache", "open source", "terms"], "Licences"),
        Entry("manual", "The manual", ["help", "documentation", "docs"], "Help"),
        Entry("source", "Source code", ["github", "repository"], "Help"),
    ])

