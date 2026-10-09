"""Power: the power profile, the batteries, what closing the lid does, and sleep
(docs/settings.md, "Power").

Everything goes through `bromigos power … --json`: the profile is power-profiles-daemon's,
the batteries are read from the kernel, the lid is logind's setting (a file in /etc, so it
asks for your password), the suspend timer is Idle & lock's (linked, not copied)."""
from gi.repository import GLib, Gtk

from bromigos_settings import Entry, Page

CMD = ["bromigos", "power"]
PROFILES = {"power-saver": ("Power saver", "Slower and cooler: the battery lasts longest"),
            "balanced": ("Balanced", "Fast when it's needed, quiet when it isn't"),
            "performance": ("Performance", "As fast as it goes: louder and warmer, the battery drains sooner")}
LID = {"suspend": "Suspend", "lock": "Lock the screen", "ignore": "Nothing", "poweroff": "Power off",
       "hibernate": "Hibernate"}
LID_ROWS = [("on_battery", "On battery", "Closing the lid with the charger out"),
            ("on_power", "Plugged in", "Closing the lid on the charger"),
            ("docked", "With a display connected", "Closing the lid with an external display (docked)")]
DROPIN = "/etc/systemd/logind.conf.d/50-bromigos-lid.conf"


def _left(m):
    if m is None:
        return None
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


class PowerPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.lid_sig = None
        self.page = ctx.page()
        self._build()
        self.refresh()
        GLib.timeout_add_seconds(15, self._tick)

    def _build(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Power profile", "How hard the machine works, against how long the battery "
                                                  "lasts and how warm it runs.", key="profile")
        self.profile_group = g
        self.profiles = None
        self.profile_rows = []
        self.bat_group = ctx.group(self.page, "Battery", key="battery")
        self.bat_rows = []
        self.lid_group = ctx.group(self.page, "The lid", "What closing the lid does. It's logind's setting, for the "
                                                         "whole machine: changing it asks for your password.", key="lid")
        self.lid_rows = []
        g = ctx.group(self.page, "Sleep", GLib.markup_escape_text("When the machine sleeps by itself is Idle & lock's."))
        self.idle_row = ctx.row(g, "Suspend when idle", "", key="idle-suspend", activate=lambda: ctx.open_page("idle"),
                                hint="Opens Idle & lock, where the suspend timer is (with the screensaver, the lock "
                                     "and the displays off)")
        self.hib_row = ctx.row(g, "Hibernation", "", key="hibernation",
                               hint="Whether this machine can hibernate (save everything to disk and power off)")
        ctx.row(g, "Suspend now", "The machine sleeps at once; a key or the power button wakes it", key="suspend",
                hint="Suspends the machine now (asks first)",
                buttons=[("Suspend…", self._suspend, "Suspends now, after you say yes")],
                advanced={"runs": "bromigos power suspend", "note": "systemctl suspend; the screen locks first "
                                                                    "(Lock before sleep, in Idle and lock)"})

    # ------------------------------------------------------------------ the parts that depend on the machine
    def _profiles(self, p):
        ctx = self.ctx
        ctx.clear_group(self.profile_group, self.profile_rows)
        if self.profiles is not None:
            self.profile_group.remove(self.profiles_box)
            self.profiles = None
        if not p.get("available"):
            self.profile_rows.append(ctx.note(self.profile_group, f"No power profiles: {p.get('why', '')}", "note",
                                              hint="power-profiles-daemon switches profiles; bromigos hw setup "
                                                   "installs it on laptops"))
            self.profile_rows.append(ctx.row(
                self.profile_group, "Set up this machine's hardware", "bromigos hw setup: drivers, and on a laptop "
                "the power profiles", hint="Opens the hardware setup in a terminal (it asks for your password)",
                buttons=[("Set up…", lambda: ctx.terminal(["bromigos", "hw", "setup"]), "bromigos hw setup, in a terminal")],
                advanced={"runs": "bromigos hw setup"}))
            return
        order = ["power-saver", "balanced", "performance"]
        ps = sorted(p["list"], key=lambda x: order.index(x["name"]) if x["name"] in order else 9)
        opts = [(x["name"], PROFILES.get(x["name"], (x["name"].title(), ""))[0],
                 PROFILES.get(x["name"], ("", x["name"]))[1]) for x in ps]
        self.profiles = ctx.toggle_group(opts, p.get("active"), on_select=self._profile,
                                         hint="Power saver, Balanced or Performance (power-profiles-daemon); the bar's "
                                              "profile button cycles them too")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self.profiles)
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        rows.add_css_class("boxed-list")
        box.append(rows)
        self.profile_group.add(box)
        self.profiles_box = box
        cur = next((x for x in p["list"] if x["name"] == p.get("active")), {})
        name, what = PROFILES.get(p.get("active"), (p.get("active") or "", ""))
        ctx.row(rows, name, what + (f" (driver: {cur['driver']})" if cur.get("driver") else ""),
                hint="The profile in force", advanced={"runs": "bromigos power profile NAME",
                                                       "note": "powerprofilesctl set"})
        for x in p["list"]:
            if x.get("degraded"):
                self.profile_rows.append(ctx.note(self.profile_group, f"{x['name']} is held back: {x['degraded']}",
                                                  "warn", hint="power-profiles-daemon degrades a profile when the "
                                                               "machine is too hot or a lap is detected"))

    def _batteries(self, d):
        ctx = self.ctx
        ctx.clear_group(self.bat_group, self.bat_rows)
        if not d["batteries"]:
            self.bat_rows.append(ctx.row(self.bat_group, "No battery", "This machine runs on mains power",
                                         hint="No battery is reported by the kernel (/sys/class/power_supply)"))
        for b in d["batteries"]:
            state = {"Discharging": "on battery", "Charging": "charging", "Full": "full",
                     "Not charging": "plugged in, not charging"}.get(b["status"], b["status"].lower())
            left = _left(b["time_left_min"])
            sub = f"{state}" + (f" · {left} {'to full' if b['charging'] else 'left'}" if left else "")
            r = ctx.row(self.bat_group, f"{b['capacity']}%" if b["capacity"] is not None else b["model"], sub,
                        hint=f"{b['model']}: its charge, what it's doing and the time left at the present draw",
                        advanced={"reads": f"/sys/class/power_supply/{b['name']}/"})
            lvl = Gtk.LevelBar(min_value=0, max_value=100, value=b["capacity"] or 0)
            lvl.set_size_request(140, 10)
            lvl.set_valign(Gtk.Align.CENTER)
            ctx.hint(lvl, f"{b['capacity']}% charged")
            r.add_suffix(lvl)
            self.bat_rows.append(r)
            if b["health"] is not None:
                self.bat_rows.append(ctx.row(
                    self.bat_group, "Health", f"It holds {b['health']}% of what it did new"
                    + (f" · {b['cycles']} charge cycles" if b.get("cycles") else ""),
                    hint="The battery's full charge now against its design capacity"))
        if d["ac"]["present"]:
            self.bat_rows.append(ctx.row(self.bat_group, "Charger", "plugged in" if d["ac"]["online"] else "unplugged",
                                         hint="The mains adapter, as the kernel sees it"))
        for x in d["devices"]:
            self.bat_rows.append(ctx.row(self.bat_group, x["model"],
                                         f"{x['capacity']}% charged" if x["capacity"] is not None else (x.get("level") or ""),
                                         hint=f"{x['model']}: a device's own battery (a mouse, a headset)"))

    def _lid(self, d):
        ctx = self.ctx
        lid = d["lid"]
        sig = (lid["present"], lid.get("on_battery"), lid.get("on_power"), lid.get("docked"),
               d["hibernation"]["possible"])
        if sig == self.lid_sig:
            return
        self.lid_sig = sig
        g = self.lid_group
        ctx.clear_group(g, self.lid_rows)
        if not lid["present"]:
            self.lid_rows.append(ctx.row(g, "No lid", "This machine isn't a laptop", hint="No lid switch is reported "
                                         "(/proc/acpi/button/lid, or an input called Lid Switch)"))
            return
        acts = [a for a in lid["actions"] if a != "hibernate" or d["hibernation"]["possible"]]
        for k, title, what in LID_ROWS:
            self.lid_rows.append(ctx.combo_row(g, title, what, options=[(a, LID[a]) for a in acts], current=lid.get(k),
                          key=f"lid-{k}", on_select=lambda a, k=k: self._lid_change(k, a),
                          hint=f"{what}: suspend, lock, nothing, power off" +
                               (" or hibernate" if d["hibernation"]["possible"] else ""),
                          advanced={"file": DROPIN, "key": {"on_battery": "HandleLidSwitch",
                                                            "on_power": "HandleLidSwitchExternalPower",
                                                            "docked": "HandleLidSwitchDocked"}[k],
                                    "runs": "bromigos power lid ACTION --on-power ACTION --docked ACTION",
                                    "note": "through pkexec; logind reloads it"}))

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(CMD + ["--json"], self._got)

    def _tick(self):
        if self.page.get_mapped():
            self.refresh()
        return True

    def _got(self, doc, err):
        if not doc or doc.get("ok") is False:
            self.ctx.clear_group(self.profile_group, self.profile_rows)
            self.profile_rows.append(self.ctx.failed(self.profile_group, CMD + ["--json"], (doc or {}).get("error") or err))
            return
        self.sync(doc)

    def sync(self, d):
        self.doc = d
        self._profiles(d["profiles"])
        self._batteries(d)
        self._lid(d)
        s = d.get("suspend")
        self.idle_row.set_subtitle(GLib.markup_escape_text(
            "Idle & lock didn't answer" if s is None else
            (f"After {s['minutes']} min without input" if s["enabled"] else
             "Off: the machine never suspends by itself") + " · change it in Idle & lock"))
        h = d["hibernation"]
        self.hib_row.set_subtitle(("Set up" if h["possible"] else "Not set up") + f": {h['why']}")
        self.page.set_reset(self.reset if (d["profiles"].get("available") or d["lid"].get("yours")) else None,
                            what="The power profile goes back to Balanced"
                                 + (" and the lid to logind's own (suspend; nothing when docked), which asks "
                                    "for your password" if d["lid"].get("yours") else "") + ".")

    # ------------------------------------------------------------------ changes
    def _profile(self, name):
        old = ((self.doc or {}).get("profiles") or {}).get("active")
        if name == old:
            return
        self.ctx.change(CMD + ["profile", name, "--json"], lambda d: d.get("said"),
                        undo=CMD + ["profile", old, "--json"] if old else None, done=self.sync,
                        failed=lambda *_: self.refresh())

    def _lid_args(self, lid):
        return ["lid", lid["on_battery"], "--on-power", lid["on_power"], "--docked", lid["docked"]]

    def _lid_change(self, key, action):
        lid = dict((self.doc or {}).get("lid") or {})
        if lid.get(key) == action:
            return
        old = self._lid_args(lid)
        lid[key] = action
        self.ctx.toast("Asking for your password (logind's setting is the machine's)…", timeout=3)
        self.ctx.change(CMD + self._lid_args(lid) + ["--json"], lambda d: d.get("said"), undo=CMD + old + ["--json"],
                        done=self.sync, failed=lambda *_: self._refresh_lid())

    def _refresh_lid(self):
        self.lid_sig = None
        self.refresh()

    def _suspend(self):
        self.ctx.confirm("Suspend now?", "The machine sleeps at once. A key or the power button wakes it; the lock "
                                         "screen comes first.", "Suspend",
                         lambda: self.ctx.run(CMD + ["suspend", "--json"]))

    def reset(self):
        d = self.doc or {}
        if d.get("profiles", {}).get("available"):
            self._profile("balanced")
        if d.get("lid", {}).get("yours"):
            self.ctx.change(CMD + ["lid", "suspend", "--on-power", "suspend", "--docked", "ignore", "--json"],
                            "The lid: logind's defaults", done=self.sync)
        return None


def build(ctx):
    p = PowerPage(ctx)
    p.page._power = p
    return p.page


def refresh(widget):
    widget._power.refresh()


PAGE = Page(
    id="power", title="Power", group="system", order=50, build=build, refresh=refresh, docs="settings.md#power",
    icon="battery-good-symbolic power-profile-balanced-symbolic system-shutdown-symbolic",
    summary="profile, battery, the lid, sleep",
    intro="The power profile, the battery, what closing the lid does, and sleep.",
    keywords=["battery", "energy", "laptop", "lid", "suspend", "sleep", "power profile", "charger"],
    entries=[
        Entry("profile", "Power profile", ["power saver", "balanced", "performance", "power mode"], "Power profile"),
        Entry("battery", "Battery", ["charge", "battery level", "time left", "percentage", "battery health",
                                     "cycles", "charger"], "Battery"),
        Entry("lid", "What closing the lid does", ["lid", "laptop lid", "close the lid", "docked", "clamshell"],
              "The lid"),
        Entry("idle-suspend", "Suspend when idle", ["sleep timer", "auto suspend", "inactivity"], "Sleep"),
        Entry("hibernation", "Hibernation", ["hibernate", "suspend to disk"], "Sleep"),
        Entry("suspend", "Suspend now", ["sleep now", "standby"], "Sleep"),
    ])
