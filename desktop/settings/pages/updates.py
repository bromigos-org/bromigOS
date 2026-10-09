"""Updates & recovery: the channel this machine follows, updating, what's waiting, the last
update, snapshots and rolling an update back, and the boot menu's theme (docs/settings.md,
"Updates and recovery"; docs/update.md).

What changes the system runs in a terminal, because it needs sudo (or a FIDO key) and asks
questions no window can answer for you: `bromigos update` (and `--channel NAME`,
`--rollback`), `bromigos restart`, `bromigos rollback setup`, `bromigos boot theme on|off`.
The page shows the command each button runs. The reads are `--json`: `bromigos channel`,
`bromigos update --check`, `bromigos rollback status`, `bromigos boot theme status`."""
from gi.repository import Adw

from bromigos_settings import Entry, Page


def _esc(text):
    """Text for a row's title or subtitle (they take Pango markup): &, < and > escaped."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

CHANNELS = [("stable", "stable"), ("rc", "rc"), ("edge", "edge"), ("dev", "dev")]
WHAT = {"stable": "tagged releases", "rc": "release candidates", "edge": "every change, as CI publishes it",
        "dev": "your own builds"}


def _last(u):
    if not u:
        return "None in pacman's log"
    at = (u.get("at") or "")[:16].replace("T", " ")
    return f"{at}: {u['packages']} packages" if u.get("packages") else f"{at}: nothing was waiting"


def _snap_summary(s):
    """How this machine snapshots updates, in plain words (bromigos rollback status)."""
    if not s:
        return "Unknown", None
    if not s.get("btrfs"):
        return f"Not snapshotted: / is {s.get('fs') or 'not btrfs'} (snapshots need btrfs)", None
    if not s.get("snapper") or not s.get("config"):
        return "Not snapshotted yet: / is btrfs, but snapper isn't set up", "setup"
    bits = ["Every update is snapshotted before and after (snapper" + (", snap-pac" if s.get("snap_pac") else "") + ")"]
    if not s.get("snap_pac"):
        bits = ["snapper is set up, but snap-pac isn't: updates aren't snapshotted by themselves"]
    if s.get("boot_menu"):
        bits.append("the boot menu lists them")
    if not s.get("readable"):
        return "; ".join(bits) + "; this user can't list root's snapshots yet", "allow"
    return "; ".join(bits), None


class UpdatesPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = ctx.page()
        self.page.set_reset(None, hint="Updates follow the channel you chose: there's no default here to go back to")
        self.wait_rows, self.snap_rows, self.boot_rows = [], [], []
        self.channel = None
        self._channel()
        self._update()
        self.wait_group = ctx.group(self.page, "Waiting", "What an update would do now.", key="waiting")
        self.wait_rows.append(ctx.loading(self.wait_group, "Checking (checkupdates)…"))
        self.snap_group = ctx.group(self.page, "Snapshots and rolling back",
                                    "An update is undone from the snapshots taken around it.", key="snapshots")
        self.boot_group = ctx.group(self.page, "Boot menu", "GRUB's menu in your theme's colours.", key="boot-group")
        self.refresh()
        self.check()

    # ------------------------------------------------------------------ building
    def _channel(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Channel", "Which builds this machine follows. Switching asks for your password "
                                            "in a terminal, then updates.")
        self.chan_row = ctx.combo_row(
            g, "Channel", "", options=CHANNELS, current=None, key="channel", on_select=self._switch,
            hint="stable: tagged releases; rc: release candidates; edge: every change; dev: your own builds. "
                 "Choosing one opens a terminal running bromigos update --channel NAME",
            advanced={"file": "/etc/pacman.conf", "key": "[bromigos] Server", "runs": "bromigos update --channel NAME"})
        self.chan_row.set_use_markup(True)       # a ComboRow's text isn't markup by default; ctx escaped it

    def _update(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Update", "Packages, then migrations, the theme, and restarts of whatever runs "
                                           "older code.")
        ctx.row(g, "Update now", "In a terminal: pacman asks for your password (or your key) there", key="update",
                hint="Opens a terminal running bromigos update: it needs sudo or a FIDO key, and can't answer "
                     "pacman's questions from a window",
                buttons=[("Update now", lambda: ctx.terminal(["bromigos", "update"]), "bromigos update, in a terminal")],
                advanced={"runs": "bromigos update"})
        self.last_row = ctx.row(g, "Last update", "", key="last-update",
                                hint="The last full system upgrade pacman recorded",
                                advanced={"reads": "/var/log/pacman.log", "runs": "bromigos about last-update"})

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(["bromigos", "channel", "--json"], self._got_channel)
        self.ctx.json(["bromigos", "about", "last-update", "--json"], self._got_last)
        self.ctx.json(["bromigos", "rollback", "status", "--json"], self._got_rollback)
        if self.ctx.has_command("boot"):
            self.ctx.json(["bromigos", "boot", "theme", "status", "--json"], self._got_boot)
        else:
            self._got_boot(None, None)

    def check(self):
        self.ctx.clear_group(self.wait_group, self.wait_rows)
        self.wait_rows.append(self.ctx.loading(self.wait_group, "Checking (checkupdates)…"))
        self.ctx.json(["bromigos", "update", "--check", "--json"], self._got_check)

    def _got_channel(self, doc, err):
        ch = (doc or {}).get("channel") or {}
        self.channel = ch.get("channel")
        self.chan_row.set_quiet(self.channel)
        self.chan_row.set_subtitle(_esc(
            (f"{WHAT[self.channel]} · " if self.channel in WHAT else "") +
            (ch.get("server") or f"no [bromigos] repository in pacman.conf{': ' + err if err else ''}")))

    def _got_last(self, doc, _err):
        u = (doc or {}).get("last_update")
        self.last_row.set_subtitle(_esc(_last(u)))

    def _got_check(self, doc, err):
        ctx = self.ctx
        g = self.wait_group
        ctx.clear_group(g, self.wait_rows)
        c = (doc or {}).get("check")
        if not c:
            self.wait_rows.append(ctx.failed(g, ["bromigos", "update", "--check", "--json"], err))
            return
        pk = c.get("packages")
        if pk is None:
            self.wait_rows.append(ctx.row(g, "Packages", "Can't tell (install pacman-contrib for checkupdates)",
                                          key="packages", hint="checkupdates comes with pacman-contrib"))
        else:
            ex = Adw.ExpanderRow(title="Packages", subtitle=f"{len(pk)} upgrade{'s' if len(pk) != 1 else ''} waiting"
                                 if pk else "Up to date")
            ctx.hint(ex, "Open for each package, from the version installed to the one waiting")
            for p in pk[:200]:
                r = Adw.ActionRow(title=_esc(p["name"]),
                                  subtitle=_esc(f"{p['from']} → {p['to']}"))
                ctx.hint(r, f"{p['name']}: {p['from']} → {p['to']}")
                ex.add_row(r)
            ex.set_enable_expansion(bool(pk))
            ex._bromigos_key = "packages"
            g.add(ex)
            self.wait_rows.append(ex)
        mig = c.get("migrations") or []
        self.wait_rows.append(ctx.row(
            g, "Migrations", (f"{len(mig)} to run: " + ", ".join(m.split("-", 1)[-1] for m in mig[:6]) +
                              ("…" if len(mig) > 6 else "")) if mig else "None pending", key="migrations",
            hint="Scripts an update runs once, to bring this install's files forward (bromigos update runs them)"))
        rs = c.get("restarts") or []
        self.wait_rows.append(ctx.row(
            g, "Restarts", "\n".join(f"{r['what']}: {r['need']} ({r['why']})" for r in rs[:6]) if rs
            else "Everything runs the installed code", key="restarts",
            hint="What runs older code than is installed, and what it needs",
            buttons=[("Restart", lambda: ctx.terminal(["bromigos", "restart"]), "bromigos restart, in a terminal")]
            if rs else [], advanced={"runs": "bromigos restart"}))
        self.wait_rows.append(ctx.row(g, "Check again", "Asks the mirrors again (checkupdates)", key="check",
                                      hint="Checks what's waiting now",
                                      buttons=[("Check", self.check, "Runs bromigos update --check again")],
                                      advanced={"runs": "bromigos update --check"}))

    def _got_rollback(self, doc, err):
        ctx = self.ctx
        g = self.snap_group
        ctx.clear_group(g, self.snap_rows)
        if not doc:
            self.snap_rows.append(ctx.failed(g, ["bromigos", "rollback", "status", "--json"], err))
            return
        said, fix = _snap_summary(doc.get("snapshots"))
        buttons = []
        if fix == "setup":
            buttons = [("Set up…", lambda: ctx.terminal(["bromigos", "rollback", "setup"]),
                        "bromigos rollback setup, in a terminal: snapper's root configuration, snap-pac and the boot "
                        "menu's entries")]
        elif fix == "allow":
            buttons = [("Allow…", lambda: ctx.terminal(["bromigos", "rollback", "allow"]),
                        "bromigos rollback allow, in a terminal: lets your group list root's snapshots")]
        self.snap_rows.append(ctx.row(g, "Snapshots", said, key="snapshot-setup", buttons=buttons,
                                      hint="How updates are snapshotted on this machine (bromigos rollback status)",
                                      advanced={"runs": "bromigos rollback setup"}))
        rb = doc.get("rollbacks") or []
        if rb:
            sub = "\n".join(f"{(r.get('at') or '')[:16].replace('T', ' ')}  {r.get('what') or ''}".strip() for r in rb[:5])
        else:
            sub = "Nothing to undo yet: an update snapshotted before and after shows here"
        self.snap_rows.append(ctx.row(
            g, "Updates that can be undone", sub, key="rollback",
            hint="Rolling an update back brings back every file / had before it (snapper undochange), after a "
                 "summary and a question, in a terminal",
            buttons=[("Roll back…", lambda: ctx.terminal(["bromigos", "update", "--rollback"]),
                      "bromigos update --rollback, in a terminal: it shows what comes back and asks first")]
            if rb else [], advanced={"runs": "bromigos update --rollback [PRE]"}))

    def _got_boot(self, doc, err):
        ctx = self.ctx
        g = self.boot_group
        ctx.clear_group(g, self.boot_rows)
        if doc is None and err is None:
            self.boot_rows.append(ctx.row(g, "Boot menu theme", "Comes with a newer bromigos (bromigos boot)",
                                          key="boot", hint="bromigos boot isn't installed here yet"))
            return
        if not doc:
            self.boot_rows.append(ctx.failed(g, ["bromigos", "boot", "theme", "status", "--json"], err))
            return
        grub = doc.get("bootloader") == "grub" and doc.get("grub_installed") is not False
        applied = doc.get("applied") or {}
        want = doc.get("want") or {}
        if not grub:
            sub = f"This machine boots with {doc.get('bootloader') or 'another loader'}: the theme is GRUB's"
        elif doc.get("on"):
            sub = f"On: {applied.get('theme') or want.get('theme') or '?'} in /boot" + (
                "" if doc.get("current") in (True, None) else f"; {want.get('theme')} waits to be applied")
        else:
            sub = "Off: GRUB's own menu" + (" (you turned it off)" if applied.get("opted_out") else "")
        if doc.get("note"):
            sub += f"\n{doc['note']}"
        sw = ctx.switch_row(g, "Boot menu theme", sub, active=bool(doc.get("on")), key="boot",
                            on_toggle=lambda on: self._boot(on, sw),
                            hint="bromigOS's GRUB theme in your theme's colours. Switching asks for your password "
                                 "in a terminal (it writes /etc/default/grub and /boot)",
                            advanced={"file": "/etc/default/grub", "runs": "bromigos boot theme on|off"})
        sw.set_sensitive(grub)
        self.boot_rows.append(sw)
        if grub and doc.get("on") and doc.get("current") is False:
            self.boot_rows.append(ctx.row(g, "Apply the theme now", "/boot gets the theme in force",
                                          key="boot-apply", hint="bromigos boot theme apply, in a terminal (sudo)",
                                          buttons=[("Apply…", lambda: ctx.terminal(["bromigos", "boot", "theme", "apply"]),
                                                    "bromigos boot theme apply, in a terminal")]))

    # ------------------------------------------------------------------ changes
    def _switch(self, name):
        if name == self.channel:
            return
        self.chan_row.set_quiet(self.channel)        # it's switched when the terminal's update has run
        self.ctx.terminal(["bromigos", "update", "--channel", name])
        self.ctx.toast(f"Switching to {name} in a terminal: bromigos update --channel {name}")

    def _boot(self, on, sw):
        sw.set_quiet(not on)                         # switched when the terminal's command has run
        self.ctx.terminal(["bromigos", "boot", "theme", "on" if on else "off"])
        self.ctx.toast(f"In a terminal: bromigos boot theme {'on' if on else 'off'}")


def build(ctx):
    p = UpdatesPage(ctx)
    p.page._updates = p
    return p.page


def refresh(widget):
    widget._updates.refresh()


PAGE = Page(
    id="updates", title="Updates & recovery", group="system", order=90, build=build, refresh=refresh,
    docs="settings.md#updates-and-recovery",
    icon="system-software-update-symbolic software-update-available-symbolic",
    summary="channel, updates, rollback, boot menu",
    intro="The channel this machine follows, updating, what's waiting, and rolling an update back. What needs your "
          "password runs in a terminal, and says which command.",
    keywords=["update", "upgrade", "pacman", "channel", "rollback", "snapshot", "snapper", "grub", "recovery"],
    entries=[
        Entry("channel", "Update channel", ["stable", "rc", "edge", "dev", "branch"], "Channel"),
        Entry("update", "Update now", ["upgrade", "pacman -Syu", "bromigos update"], "Update"),
        Entry("last-update", "Last update", ["when updated"], "Update"),
        Entry("packages", "Upgrades waiting", ["pending updates", "available updates"], "Waiting"),
        Entry("migrations", "Migrations", ["pending migrations"], "Waiting"),
        Entry("restarts", "Restarts needed", ["restart", "stale"], "Waiting"),
        Entry("check", "Check for updates", ["checkupdates", "refresh"], "Waiting"),
        Entry("snapshot-setup", "Snapshots", ["snapper", "btrfs", "snap-pac"], "Snapshots and rolling back"),
        Entry("rollback", "Roll back an update", ["undo update", "restore", "recovery"], "Snapshots and rolling back"),
        Entry("boot", "Boot menu theme", ["grub", "bootloader", "boot screen"], "Boot menu"),
    ])
