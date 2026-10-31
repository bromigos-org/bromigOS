"""bromigOS Server's steps in the text installer (tui.py's Installer mixes this in): Role,
Network, Access, Storage, Encryption, Updates and Services, and the Server briefing on Ready
to install, the same steps and words as the graphical installer's (server_gui.py) from the
same model (server.py). DRIFTGLASS in Textual: Glass cards for the choices, a ✓ or ▲ beside
each typed field as you type, the address big, the hint line saying what the focused control
does. Fits from 150×45 down to 40×15: everything stacks on narrow screens and the page scrolls."""
from . import common, server

try:
    from rich.text import Text
    from textual import on
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Checkbox, Collapsible, Input, Label, RadioButton, RadioSet, Select, Static, Switch
    HAVE = True
except ImportError:          # the plain questions still work
    HAVE = False

    def on(*_a, **_k):
        return lambda f: f

import sys as _sys
if "/usr/lib/bromigos/lib" not in _sys.path:          # bromigos-core's DRIFTGLASS for Textual (tui.py adds it too)
    _sys.path.append("/usr/lib/bromigos/lib")
try:
    import bromigos_textual as BT
except ImportError:
    BT = None

STEP_IDS = server.STEP_IDS

# the summary's rows: the step that changes each (tui.py's BRIEF_STEP), and each step's title and icon
BRIEF_STEP = {"Roles": "role", "Keys and passwords": "secrets", "Reach": "reach", "Lab": "services", "Runs": "services",
              "Role": "role", "Server name": "network", "Network": "network", "Admin": "access", "Sign-in": "access",
              "Remote access": "access", "Lab account": "access", "Data disks": "storage", "Disk encryption": "unlock",
              "Updates": "updates", "Services": "services", "Apps": "services", "Kernel": None}
BRIEF_TITLE = {"secrets": ("Keys", "key"), "reach": ("Reach", "remote"), "role": ("Role", "server"), "network": ("Network", "network"), "access": ("Access", "key"),
               "storage": ("Storage", "disk"), "unlock": ("Encryption", "lock"), "updates": ("Updates", "update"),
               "services": ("Services", "settings")}
ICONS = {"secrets": ("\uf084", "§", "k"), "reach": ("\uf1cd", "∞", "r"), "role": ("", "≡", "="), "access": ("", "§", "k"), "storage": ("", "■", "o"),
         "unlock": ("", "§", "L"), "updates": ("", "↕", "u"), "services": ("", "*", "s"),
         "gamepad": ("", "♠", "g"), "house": ("", "⌂", "h"), "gpu": ("", "∩", "c")}
if BT is not None:
    for _k, _v in ICONS.items():
        BT.ICONS.setdefault(_k, _v)

CSS = """
    #srv-roles, #srv-ports, #srv-modes, #srv-unlocks, #srv-labs, #srv-stores, #srv-reaches, #srv-catalogue,
    #srv-store-box, #srv-reach-box { height: auto; width: 100%; }
    #srv-roles Choice, #srv-ports Choice, #srv-modes Choice, #srv-unlocks Choice, #srv-labs Choice, #srv-stores Choice,
    #srv-reaches Choice { width: 100%; margin: 0 0 0 0; }
    #srv-addr { height: auto; margin: 1 0 0 0; }
    #srv-static-box, #srv-keys, #srv-gh, #srv-lab, #srv-pp-box, #srv-pelican { height: auto; }
    .srv-row { height: auto; margin-top: 1; border: round $secondary 60%; background: $surface 85%; padding: 0 1; }
    .srv-row Label { padding: 1 0 0 0; width: 1fr; }
    Screen.-narrow .srv-row Label { padding: 0; }
    .srv-mark { height: auto; }
    #srv-qr-row { height: auto; margin-top: 1; }
    #srv-qr { width: auto; height: auto; margin-right: 2; }
    #srv-qr-side { width: 1fr; height: auto; }
    Screen.-compact #srv-qr, Screen.-narrow #srv-qr { display: none; }
    .srv-split { height: auto; }
    .srv-ctl { width: 1fr; height: auto; }
    .srv-hero { width: auto; height: auto; margin: 1 0 1 0; border: round $primary 40%; background: $surface 60%; padding: 0 1; }
    .srv-split .srv-hero { margin: 0 0 0 2; }
    .srv-group { height: auto; margin-top: 1; }
    .srv-group-head { height: 1; color: $primary; text-style: bold; }
    .srv-note { color: $text-muted; padding-left: 4; }
    #step-network Checkbox, #step-access Checkbox, #step-storage Checkbox, #step-unlock Checkbox,
    #step-services Checkbox, #step-access RadioSet, #step-storage RadioSet, #step-secrets RadioSet,
    #step-reach Checkbox { width: 100%; max-width: 100%; }
"""


def _t():
    from . import tui
    return tui


def _collect(cls):
    """The mixin's @on handlers, where Textual looks for them (its metaclass only fills a
    MessagePump subclass's own)."""
    handlers = {}
    for v in cls.__dict__.values():
        for message_type, selectors in getattr(v, "_textual_on", []) or []:
            handlers.setdefault(message_type, []).append((v, selectors))
    cls._decorated_handlers = handlers
    return cls


class _Base:
    pass


_CARD = None


def _card_cls():
    """A Choice card that ticks on and off by itself (the roles: several at once)."""
    global _CARD
    if _CARD is None:
        T = _t()

        class Card(T.Choice):
            def render(self):
                c = common.theme()[0]
                mark = Text(("☑ " if self.value else "☐ ") if T.look() != "ascii" else ("[x] " if self.value else "[ ] "),
                            style="bold " + (c["primary"] if self.value else c["faint"]))
                return Text.assemble(mark, self.content)

            def watch_value(self, v):
                self.set_class(v, "-on")
                self.post_message(T.Choice.Picked(self))

            def action_pick(self):
                if not self.off:
                    self.value = not self.value

            def action_step(self, d):
                sibs = [w for w in self.parent.query(Card) if not w.off]
                if self in sibs:
                    sibs[(sibs.index(self) + d) % len(sibs)].focus()
        _CARD = Card
    return _CARD


if HAVE:
    _ON_INPUT = on(Input.Changed)
    _ON_SWITCH = on(Switch.Changed)
    _ON_CHECK = on(Checkbox.Changed)
    _ON_RADIO = on(RadioSet.Changed)
    _ON_SELECT = on(Select.Changed, "#srv-window")
else:
    _ON_INPUT = _ON_SWITCH = _ON_CHECK = _ON_RADIO = _ON_SELECT = (lambda f: f)


@_collect
class ServerPages(_Base):
    """The Installer's server steps: build_<step>, server_check, the briefing's sign-in panel."""

    # ── shared bits ─────────────────────────────────────────────────────────────────
    def _s(self):
        return server.srv(self.a)

    def _mark(self, key, icon_name, words, problem, shown):
        """A field's label with its live ✓ / ▲ and why."""
        T = _t()
        t = Text()
        t.append(T.ic(icon_name) + " ", style=T.col("primary"))
        t.append(words, style=T.col("soft"))
        if shown:
            t.append("  " + (T.ic("check") if not problem else T.ic("cross")),
                     style="bold " + T.col("primary" if not problem else "danger"))
            if problem:
                t.append(" " + problem, style=T.col("danger"))
        return t

    def _field(self, key, icon_name, words, value, tip, check=None, password=False, placeholder=""):
        T = _t()
        lab = Static(self._mark(key, icon_name, words, check(value) if check and value else None, bool(value)),
                     classes="vlabel srv-mark", id=f"lab-{key}")
        lab.words, lab.icon_name, lab.check = words, icon_name, check
        return Vertical(lab, T.hint(Input(value or "", password=password, id=key, placeholder=placeholder), tip), classes="field")

    def _remark(self, key, value):
        for lab in self.query(f"#lab-{key}"):
            chk = getattr(lab, "check", None)
            lab.update(self._mark(key, lab.icon_name, lab.words, chk(value) if chk and value else None, bool(value)))

    def _switch_row(self, sid, on_, words, tip):
        T = _t()
        return Horizontal(T.hint(Switch(bool(on_), id=sid), tip), Label("  " + words), classes="srv-row")

    def _choice(self, cid, title, lines, chosen, icon_name, tip):
        T = _t()
        t = Text()
        t.append(f"{T.ic(icon_name)} {title}\n", style="bold")
        for i, ln in enumerate(lines):
            t.append(ln + ("\n" if i < len(lines) - 1 else ""), style=T.col("muted") if i == 0 else T.col("faint"))
        return T.hint(T.Choice(t, value=chosen, id=cid), tip)

    def _hero(self, box, fn, hid):
        """The step's one hero: fn(t) draws it (t moves its Pulse; 0 under reduced motion). Beside the
        controls on a wide screen, above them otherwise; returns where the controls go. Without
        bromigos_textual's pictures (an older bromigos-core), no hero."""
        if BT is None or not hasattr(BT, "net_map"):
            return box
        w = Static(fn(0.0), id=hid, classes="srv-hero")
        self._hero_w, self._hero_fn = w, fn
        if not self.reduced and BT is not None and not getattr(self, "_srv_timer", None):
            self._srv_t = 0.0
            self._srv_timer = self.set_interval(0.3, self._hero_tick)
        if self.size.width >= 150 and not self.narrow():
            row = Horizontal(classes="srv-split")
            ctl = Vertical(classes="srv-ctl")
            box.mount(row)
            row.mount(ctl, w)
            return ctl
        box.mount(w)
        return box

    def _hero_tick(self):
        w = getattr(self, "_hero_w", None)
        if w is None or not w.is_attached or self.step not in STEP_IDS:
            return
        self._srv_t = getattr(self, "_srv_t", 0.0) + 0.3
        try:
            w.update(self._hero_fn(self._srv_t))
        except Exception:
            pass

    def _hero_redraw(self):
        w = getattr(self, "_hero_w", None)
        if w is not None and w.is_attached:
            w.update(self._hero_fn(0.0 if self.reduced else getattr(self, "_srv_t", 0.0)))

    def _hero_width(self):
        return max(30, min(64, (self.size.width - (0 if self.narrow() else 26)) // (2 if self.size.width >= 150 else 1) - 8))

    def _small(self):
        return getattr(self, "bp", "normal") in ("compact", "narrow", "too-small") or self.size.height < 30

    # ── Role ────────────────────────────────────────────────────────────────────────
    def build_role(self, box):
        s = self._s()
        self.heading(box, "role")
        row = Vertical(id="srv-roles")
        box.mount(row)
        icons = {"lab": "gpu", "storage": "disk", "home": "house", "games": "gamepad", "media": "desktop", "plain": "server"}
        chosen = server.roles_of(s)
        Card = _card_cls()
        for r in server.roles():
            t = Text()
            t.append(f"{_t().ic(icons.get(r['id'], 'server'))} {r['title']}\n", style="bold")
            t.append(r["summary"], style=_t().col("muted"))
            if not self._small():
                t.append("\n" + r["hint"], style=_t().col("faint"))
            row.mount(_t().hint(Card(t, value=r["id"] in chosen, id=f"srole-{r['id']}"),
                                f"{r['title']}: {r['summary']} Space or Enter ticks it; several can be ticked. "
                                + ("Just a server goes alone." if r["id"] == "plain" else "")))
        self.role_notes = Static("", classes="muted")
        box.mount(self.role_notes)
        box.mount(Static("Tick one or several: a Lab node can also be a Game server and Storage. Just a server is the base on "
                         "its own. bromigos server role add adds one later.", classes="muted"))
        self._role_notes()

    def _role_notes(self):
        from . import provision as PV
        w = getattr(self, "role_notes", None)
        if w is None:
            return
        rids = server.roles_of(self._s())
        t = Text()
        if len(rids) > 1:
            t.append(server.roles_words(rids).upper() + "\n", style="bold " + _t().col("primary"))
        for n in server.combo_notes(rids, PV.hardware(self.probe)):
            t.append(("▲ " if "It wants" in n else "• ") + n + "\n", style=_t().col("warn") if "It wants" in n else _t().col("text"))
        w.update(t)

    def on_choice_picked(self, ev):
        cid = ev.choice.id or ""
        s = self._s()
        if cid.startswith("srole-"):
            if getattr(self, "_role_busy", False):
                return
            rid = cid.removeprefix("srole-")
            server.toggle_role(self.a, rid, ev.choice.value)
            chosen = server.roles_of(s)
            self._role_busy = True
            for w in self.query("#srv-roles Choice"):
                want = (w.id or "").removeprefix("srole-") in chosen
                if w.value != want:
                    w.value = want
            self._role_busy = False
            if not self.a.get("host_edited"):
                first = chosen[0] if chosen else "plain"
                self.a["hostname"] = {"lab": "lab-node", "storage": "storage", "home": "home-server", "games": "game-server",
                                      "media": "media-server"}.get(first, "bromigos-server")
            self._role_notes()
        elif cid.startswith("sstore-"):
            server.store_of(self.a)["kind"] = cid.removeprefix("sstore-")
            self.call_later(self._fill_store)
        elif cid.startswith("sreach-"):
            self.a.setdefault("reach", {})["mode"] = cid.removeprefix("sreach-")
            self.call_later(self._fill_reach)
        elif cid.startswith("slab-"):
            s.update(lab=cid.removeprefix("slab-"), lab_set=True)
            if s["lab"] == "join" and not s.get("lab_join"):
                s["lab_join"] = {"pair": True}
            if not s.get("provision_edited"):
                s["provision"] = None
            self.call_later(self._fill_catalogue)
        elif cid.startswith("sport-"):
            s["interface"] = cid.removeprefix("sport-")
            self._addr_refresh()
            self._wol_sync()
        elif cid.startswith("sunlock-"):
            s["unlock"] = cid.removeprefix("sunlock-")
            self.call_later(self._fill_unlock)
        elif cid.startswith("supd-"):
            s["update_mode"] = cid.removeprefix("supd-")
            self._upd_facts()

    # ── Network ─────────────────────────────────────────────────────────────────────
    def build_network(self, box):
        T = _t()
        s = self._s()
        self.heading(box, "network")
        if not hasattr(self, "_ports"):
            self._ports = server.interfaces()
        ports = self._ports
        server.pick_interface(s, ports)
        if not self.a.get("hostname"):
            self.a["hostname"] = "bromigos-server"
        self.addr_view = None
        box = self._hero(box, lambda t: BT.net_map(self._net_state(), self._hero_width(), t), "srv-netmap")
        self.addr_line = Static("", classes="muted")
        box.mount(self.addr_line)
        if not ports:
            box.mount(Static("▲ No network port found. A server needs one: plug in a network cable or a USB network adapter, "
                             "then go Back and Continue to look again.", classes="warn"))
        if server.wifi_only(ports):
            box.mount(Static("▲ " + server.WIFI_ONLY_WORDS, classes="warn"))
        box.mount(Static(Text.assemble((T.ic("wired") + "  ", T.col("primary")), ("Network port", T.col("soft"))), classes="vlabel"))
        rows = Vertical(id="srv-ports")
        box.mount(rows)
        for x in ports:
            rows.mount(self._choice(f"sport-{x['name']}", x["name"], [server.iface_words(x)], x["name"] == s.get("interface"),
                                    "wired" if x["kind"] == "wired" else "wifi",
                                    f"Use {x['name']}: {server.iface_words(x)}. ← → choose."))
        box.mount(self._switch_row("srv-static", s.get("method") == "static", "A fixed address (off: from your router, DHCP)",
                                   "On: always the same address, best for a server others reach. Off: your router picks it."))
        self.static_box = Vertical(id="srv-static-box")
        box.mount(self.static_box)
        box.mount(Horizontal(self._field("srv-hostname", "computer", "Server name", self.a.get("hostname"),
                                         "How other computers see it on your network, and its .local name.",
                                         common.check_hostname), classes="fields"))
        box.mount(self._switch_row("srv-wol", s.get("wake_on_lan"), "Wake-on-LAN: switch it on over the cable",
                                   "On: BRODEC's Wake button or your desktop can start this server. Wired ports only."))
        kids = [Horizontal(self._field("srv-vlan", "network", "VLAN number (empty: none)", str(s.get("vlan") or ""),
                                       "The VLAN tag your switch gives this port, 1 to 4094. Empty for none.", server.check_vlan),
                           classes="fields")]
        for x in [p for p in ports if p["kind"] == "wired"]:
            kids.append(T.hint(Checkbox(f"Bond {x['name']}", x["name"] in (s.get("bond") or []), id=f"sbond-{x['name']}"),
                               "Join this port into one bond with the others ticked: tick two or more."))
        box.mount(T.hint(Collapsible(*kids, title="Advanced: VLAN and bonding", collapsed=not (s.get("vlan") or s.get("bond")),
                                     id="srv-adv"),
                         "A VLAN tag, or two ports joined as one, for networks set up for them."))
        self.call_later(self._fill_static)
        self.call_after_refresh(self._addr_refresh)
        self.call_after_refresh(self._wol_sync)

    async def _fill_static(self):
        async with self.redraw:
            box = getattr(self, "static_box", None)
            if box is None:
                return
            await box.remove_children()
            s = self._s()
            if s.get("method") != "static":
                return
            x = server.port(s, self._ports) or {}
            for k in ("address", "gateway"):
                if not s.get(k) and x.get(k):
                    s[k] = x[k]
            if not s.get("dns") and x.get("dns"):
                s["dns"] = " ".join(x["dns"])
            box.mount(Horizontal(self._field("srv-address", "network", "Address", s.get("address"),
                                             "This server's address, for example 192.0.2.20: one your router doesn't hand out.",
                                             server.check_address, placeholder="192.0.2.20"),
                                 self._field("srv-prefix", "network", "Network size", str(s.get("prefix") or "24"),
                                             "24 for most home networks (the same as 255.255.255.0).",
                                             lambda v: server.check_prefix(server.prefix_from(v) or v, s.get("address")),
                                             placeholder="24"), classes="fields"),
                      Horizontal(self._field("srv-gateway", "wired", "Router (gateway)", s.get("gateway"),
                                             "Your router's address, for example 192.0.2.1.",
                                             lambda v: server.check_gateway(v, s.get("address"),
                                                                            server.prefix_from(s.get("prefix")) or "24"),
                                             placeholder="192.0.2.1"),
                                 self._field("srv-dns", "network", "Name servers (DNS)", s.get("dns"),
                                             "One or more, separated by spaces: usually your router's address.",
                                             server.check_dns, placeholder="192.0.2.1"), classes="fields"))

    def _net_state(self):
        s = self._s()
        addr, words = server.shown_address(self.a, getattr(self, "_ports", []))
        x = server.port(s, getattr(self, "_ports", [])) or {}
        rmode = (self.a.get("reach") or {}).get("mode")
        return {"address": addr, "how": "FIXED ADDRESS" if s.get("method") == "static" else "FROM YOUR ROUTER (DHCP)",
                "kind": x.get("kind", "wired"), "connected": bool(x.get("carrier") or x.get("address")),
                "gateway": (s.get("gateway") if s.get("method") == "static" else x.get("gateway")) or "",
                "lab": server.lab_hosts(quick=True), "name": self.a.get("hostname") or "server",
                "wifi_only": server.wifi_only(getattr(self, "_ports", [])),
                "reach": next((c["title"] for c in server.reach_choices() if c["id"] == rmode), None) if rmode and rmode != "brodec" else None}

    def _addr_refresh(self):
        T = _t()
        if self.step not in ("network", "reach") or getattr(self, "addr_line", None) is None:
            return
        addr, words = server.shown_address(self.a, self._ports)
        self._hero_redraw()
        self.addr_line.update(Text.assemble((words + " ", T.col("muted")), ("Then: ", T.col("muted")),
                                            (server.ssh_line(self.a, self._ports), "bold " + T.col("text"))))

    def _wol_sync(self):
        s = self._s()
        x = server.port(s, getattr(self, "_ports", [])) or {}
        ok = x.get("kind") == "wired" and x.get("wol") is not False
        for w in self.query("#srv-wol"):
            w.disabled = not ok
            if not ok:
                w.value = False

    # ── Access ──────────────────────────────────────────────────────────────────────
    def build_access(self, box):
        T = _t()
        s = self._s()
        self.heading(box, "access")
        if not self.a.get("user"):
            self.a["user"] = "admin"
        if "found_keys" not in self.a:
            self.a["found_keys"] = common.stick_keys()
            self.a["ssh_keys"] = list(dict.fromkeys(list(self.a.get("ssh_keys") or []) + [k for _, k in self.a["found_keys"]]))
        box = self._hero(box, lambda t: BT.key_cards(self._key_labels(), s.get("ssh_mode") == "password",
                                                     s.get("ssh_mode") != "off",
                                                     "lab" if "lab" in server.roles_of(s) else None, self._hero_width()),
                         "srv-keymap")
        box.mount(Static("The admin signs in at this console and over SSH, and uses sudo. The system administrator (root) "
                         "can't sign in at all.", classes="muted"))
        box.mount(Horizontal(self._field("srv-user", "user", "Admin's user name", self.a.get("user"),
                                         "What you type to sign in: small letters and digits. admin is fine.", server.check_admin),
                             classes="fields"),
                  Horizontal(self._field("srv-password", "key", "Password", self.a.get("password", ""), "For the console and sudo.",
                                         lambda v: common.check_password(v, v), password=True),
                             self._field("srv-password2", "key", "Password again", self.a.get("password2", ""),
                                         "The same password once more.",
                                         lambda v: common.check_password(self.a.get("password", ""), v), password=True),
                             classes="fields"))
        self.srv_meter = Static("", classes="meter")
        box.mount(self.srv_meter)
        self._strength(self.srv_meter, self.a.get("password", ""), "password")
        box.mount(Static(Text.assemble((T.ic("shell") + "  ", T.col("primary")), ("SSH: signing in from your computer", T.col("soft"))),
                         classes="vlabel"))
        mode = s.get("ssh_mode", "keys")
        rs = RadioSet(id="srv-sshmode")
        box.mount(T.hint(rs, common.SSH_KEY_WORDS))
        for m, words, tip in (("keys", "Keys only (recommended)", "Sign in with a key file from your other computer. Nobody can guess it."),
                              ("password", "Keys or the password", "Also the admin's password, which anyone who can reach it "
                                                                   "can try to guess."),
                              ("off", "No SSH: only at this computer", "SSH stays off; turn it on later in the welcome tour.")):
            rs.mount(T.hint(RadioButton(words, value=m == mode, id=f"srv-ssh-{m}"), tip))
        self.pw_warn = Static("▲ " + server.PASSWORD_WARN, classes="warn")
        box.mount(self.pw_warn)
        self.keys_box = Vertical(id="srv-keys")
        box.mount(self.keys_box)
        if "lab" in server.roles_of(s):
            lab = Vertical(id="srv-lab", classes="panel")
            box.mount(lab)
            lab.mount(Static(Text.assemble((T.ic("lab") + "  ", T.col("primary")), ("THE LAB ACCOUNT", "bold " + T.col("soft"))),
                             classes="panel-head"),
                      Static(server.LAB_ACCOUNT_WORDS, classes="muted"),
                      T.hint(Checkbox("Use the keys above for the lab account", bool(s.get("lab_same_keys", True)), id="srv-labsame"),
                             "On: the keys above also sign in as lab. Off: only the key you paste below does."))
            lab.mount(Horizontal(self._field("srv-labkey", "key", "Lab workstation's public key", s.get("lab_key"),
                                             "The lab workstation's .pub key: bromigos lab provision signs in with it.",
                                             lambda v: common.check_key(v.strip())), classes="fields"))
        box.mount(Static(Text.assemble((T.ic("remote") + "  ", T.col("primary")), ("From outside your house", T.col("soft"))),
                         classes="vlabel"),
                  Static("Both are installed either way, and off unless you turn them on.", classes="muted"),
                  self._switch_row("srv-wireguard", s.get("wireguard"), "WireGuard: your own VPN",
                                   "Reach the server from anywhere without opening ports to the world. Peers: in the welcome tour."),
                  self._switch_row("srv-tailscale", s.get("tailscale"), "Tailscale",
                                   "For people who already use it. It relies on Tailscale's coordination servers, not your own."))
        self.call_later(self._fill_keys)
        self.call_after_refresh(self._access_sync)

    def _key_labels(self):
        out = []
        for k in server.all_keys(self.a):
            kind, fp, c = server.fingerprint(k)
            out.append(f"{kind} {(fp or '')[7:15]}… {c or ''}".strip())
        return out

    def _access_sync(self):
        s = self._s()
        self._hero_redraw()
        if getattr(self, "pw_warn", None) is not None:
            self.pw_warn.display = s.get("ssh_mode") == "password"
        if getattr(self, "keys_box", None) is not None:
            self.keys_box.display = s.get("ssh_mode") != "off"
        for w in self.query("#lab-srv-labkey"):
            w.parent.display = not s.get("lab_same_keys", True)

    async def _fill_keys(self):
        async with self.redraw:
            T = _t()
            s = self._s()
            box = getattr(self, "keys_box", None)
            if box is None:
                return
            await box.remove_children()
            box.mount(Static(Text.assemble((T.ic("key") + "  ", T.col("primary")), ("Keys allowed in", T.col("soft"))),
                             classes="vlabel"))
            found = self.a.get("found_keys") or []
            for i, (name, key) in enumerate(found):
                box.mount(T.hint(Checkbox(f"{name}: {server.key_words(key)}", key in self.a["ssh_keys"], id=f"skey-{i}"),
                                 "A key from the USB stick's fieldkit folder: whoever holds its private half signs in as the admin."))
            pasted = [k for k in self.a["ssh_keys"] if k not in [x for _, x in found]]
            for k in pasted:
                box.mount(Static(Text.assemble((T.ic("check") + " ", T.col("primary")), ("Pasted: " + server.key_words(k), T.col("text"))),
                                 classes="muted"))
            if not found:
                box.mount(Static("No key in the USB stick's fieldkit folder. Copy your .pub file there and press Look again, "
                                 "paste it below, or get it from GitHub.", classes="muted"))
            box.mount(Horizontal(T.hint(Button("Look again", id="srv-rescan"), "Read the USB stick's fieldkit folder for keys again."),
                                 classes="buttons"))
            box.mount(Horizontal(self._field("srv-paste", "edit", "Paste a public key", "",
                                             "One line from your other computer's .pub file. Continue adds it.",
                                             lambda v: common.check_key(v.strip()), placeholder="ssh-ed25519 AAAA… you@laptop"),
                                 classes="fields"))
            box.mount(Horizontal(self._field("srv-github", "people", "GitHub user name", s.get("github"),
                                             "Your GitHub name: its public SSH keys are fetched, shown with their fingerprints, "
                                             "and used once you confirm.", server.check_github_user, placeholder="octocat"),
                                 classes="fields"),
                      Horizontal(T.hint(Button("Get keys", id="srv-ghget"),
                                        "Fetch the public keys GitHub shows for this name (github.com/NAME.keys). Needs the internet."),
                                 classes="buttons"))
            self.gh_box = Vertical(id="srv-gh")
            box.mount(self.gh_box)
            self._gh_fill()

    def _gh_fill(self):
        T = _t()
        s = self._s()
        box = getattr(self, "gh_box", None)
        if box is None:
            return
        box.remove_children()
        if s.get("gh_problem"):
            box.mount(Static("▲ " + s["gh_problem"], classes="warn"))
        if s.get("github_keys"):
            t = Text()
            for i, k in enumerate(s["github_keys"]):
                t.append(("\n" if i else "") + T.ic("key") + "  ", style=T.col("primary"))
                t.append(f"GitHub {s['github']}: {server.key_words(k)}", style=T.col("text"))
            box.mount(Static(t))
            box.mount(T.hint(Checkbox("These are my keys: use them", bool(s.get("github_ok")), id="srv-ghok"),
                             "Compare the fingerprints with ssh-keygen -l on your computer first. On: whoever holds these "
                             "keys' private halves can sign in as the admin."))

    def _gh_fetch(self):
        s = self._s()
        self.a.update()
        s["gh_problem"] = None
        user = s.get("github")

        def work():
            keys, problem = server.fetch_github_keys(user)
            self.call_from_thread(done, keys, problem)

        def done(keys, problem):
            s.update(github_keys=[] if problem else keys, github_ok=False, gh_problem=problem)
            self._gh_fill()
        import threading
        threading.Thread(target=work, daemon=True).start()

    # ── Storage ─────────────────────────────────────────────────────────────────────
    def build_storage(self, box):
        T = _t()
        s = self._s()
        self.heading(box, "storage")
        disks = server.data_disks(self.probe, self.a)
        s["data_disks"] = [p for p in s.get("data_disks", []) if p in [d["path"] for d in disks]]
        box = self._hero(box, lambda t: self._drives_art(t), "srv-drives")
        box.mount(Static("Ticked disks are erased and become one btrfs pool at /srv/data, with snapshots.", classes="muted"))
        if not disks:
            box.mount(Static("No other disk: data stays on the system disk, at /srv. Add disks later with bromigos storage.",
                             classes="card"))
        for i, d in enumerate(disks):
            lost = server.erases(d)
            words = (f"{d['size_text']} {d['model']}" + (" ▲ has files" if lost else "") if self.narrow() else
                     f"{d['model']} ({d['size_text']}) {d['path']}: {d.get('summary', '')}" + (f" · erased: {lost}" if lost else ""))
            box.mount(T.hint(Checkbox(words, d["path"] in s["data_disks"], id=f"sdisk-{i}"),
                             f"Use {d['model']} for data." + (f" Everything on it is deleted: {lost}." if lost else " It's empty.")))
        self._disks = disks
        box.mount(Static(Text.assemble((T.ic("disk") + "  ", T.col("primary")), ("Copies", T.col("soft"))), classes="vlabel"))
        rs = RadioSet(id="srv-layout")
        box.mount(T.hint(rs, "Two copies (RAID1) needs two or more disks and keeps every file on two of them."))
        rs.mount(RadioButton("One copy: all the space (single)", value=s.get("data_layout") != "raid1", id="srv-lay-single"),
                 RadioButton("Two copies: survives a failed disk (RAID1)", value=s.get("data_layout") == "raid1", id="srv-lay-raid1"))
        self.st_words = T.BT.Reading("", "idle") if T.BT is not None else Static("")
        box.mount(self.st_words)
        if "storage" in server.roles_of(s):
            box.mount(Static(Text.assemble((T.ic("people") + "  ", T.col("primary")), ("Shared folders, /srv/data/shares", T.col("soft"))),
                             classes="vlabel"))
            for svc in [x for x in server.services_for("storage") if x["id"] in ("smb", "nfs")]:  # noqa: B007
                box.mount(self._switch_row(f"ssvc-{svc['id']}", s["services"].get(svc["id"], True), svc["title"], svc["words"]))
        self._storage_sync()

    def _drives_art(self, t):
        from .disks import plain_size
        s = self._s()
        disks = [d for d in getattr(self, "_disks", []) if d["path"] in s.get("data_disks", [])]
        total = sum(d["size"] for d in disks)
        usable = total // 2 if s.get("data_layout") == "raid1" and len(disks) >= 2 else total
        return BT.drives([(d["path"].removeprefix("/dev/"), d["size_text"]) for d in disks], s.get("data_layout", "single"),
                         plain_size(usable) if usable else "", round(100 * usable / total) if total else 0, t,
                         [x.upper() for x in ("smb", "nfs") if "storage" in server.roles_of(s) and s["services"].get(x, True)])

    def _storage_sync(self):
        s = self._s()
        self._hero_redraw()
        if getattr(self, "st_words", None) is None:
            return
        disks = getattr(self, "_disks", [])
        n = len([d for d in disks if d["path"] in s.get("data_disks", [])])
        if s.get("data_layout") == "raid1" and n < 2:
            words, state = "Two copies needs two or more disks: tick another one, or choose One copy.", "warn"
        else:
            words, state = server.storage_words(s, disks), "ok" if n else "idle"
        if hasattr(self.st_words, "set"):
            self.st_words.set(words, state)
        else:
            self.st_words.update(words)

    # ── Encryption ──────────────────────────────────────────────────────────────────
    def build_unlock(self, box):
        T = _t()
        s = self._s()
        self.heading(box, "unlock")
        has = server.tpm()
        box = self._hero(box, lambda t: self._unlock_art(t), "srv-unlock-art")
        self.srv_lock = None
        side = box
        side.mount(Static(Text.assemble((T.ic("chip") + "  ", T.col("primary") if has else T.col("warn")),
                                        ("Security chip (TPM 2.0) found" if has else "No security chip (TPM 2.0)",
                                         "bold " + (T.col("primary") if has else T.col("warn"))))))
        if not has:
            side.mount(Static("None found, or it's off in the firmware settings. So choose: lock the disk and type its "
                              "passphrase after every restart, or leave it open.", classes="muted"))
        ch = Vertical(id="srv-unlocks")
        box.mount(ch)
        for k in server.unlock_choices(has):
            title, words = server.UNLOCK[k]
            ch.mount(self._choice(f"sunlock-{k}", title, [words] if not self._small() else [], s.get("unlock") == k,
                                  {"tpm": "chip", "passphrase": "key", "none": "unlock"}[k], f"{title}. {words}"))
        self.pp_box = Vertical(id="srv-pp-box")
        box.mount(self.pp_box)
        self.call_later(self._fill_unlock)

    async def _fill_unlock(self):
        async with self.redraw:
            T = _t()
            s = self._s()
            box = getattr(self, "pp_box", None)
            if box is None or self.step != "unlock":
                return
            on_ = s.get("unlock") in ("tpm", "passphrase")
            self._hero_redraw()
            await box.remove_children()
            note = {"tpm": ("At the first start, type the passphrase once: then the chip opens it by itself.", "ok"),
                    "passphrase": ("After an update restarts it, it waits for the passphrase. Your phone tells you.", "warn"),
                    "none": ("Not locked: anyone who takes the disk out can read it.", "warn")}.get(
                s.get("unlock"), ("Choose one above.", "idle"))
            box.mount(T.BT.Reading(*note) if T.BT is not None else Static(note[0]))
            if not on_:
                return
            box.mount(T.hint(Checkbox("A passphrase of its own (off: the admin's password)", bool(self.a.get("separate_passphrase")),
                                      id="srv-sep"), "On: the disk gets its own passphrase. With the chip, it's the spare key."))
            if self.a.get("separate_passphrase"):
                box.mount(Horizontal(self._field("srv-pp", "key", "Disk passphrase", self.a.get("passphrase", ""),
                                                 "The disk's passphrase.", lambda v: common.check_password(v, v, "passphrase"),
                                                 password=True),
                                     self._field("srv-pp2", "key", "Passphrase again", self.a.get("passphrase2", ""),
                                                 "The same passphrase once more.",
                                                 lambda v: common.check_password(self.a.get("passphrase", ""), v, "passphrase"),
                                                 password=True), classes="fields"))

    def _unlock_art(self, t):
        """With a TPM, the chip with the lock seated in it; without one, the two choices side by side."""
        s = self._s()
        look = BT.icon_look()
        c = BT.palette()
        lit = "bold " + (BT.rich16("primary") if BT.color_mode() == "16" else c["primary"])
        dim = BT.rich16("secondary") if BT.color_mode() == "16" else c["dim"]
        out = Text(no_wrap=True)
        if server.tpm() and s.get("unlock") in ("tpm", None):
            pin = "┬" if look != "ascii" else "+"
            rows = [f"  {pin} {pin} {pin} {pin} {pin}", " ╭─────────────╮" if look != "ascii" else " +-------------+",
                    " │   TPM 2.0   │" if look != "ascii" else " |   TPM 2.0   |"]
            lock = BT.lock_plain(True, True) if look != "nerd" else BT.lock(True, True, 8, 3)
            for r in rows:
                out.append(r + "\n", style=lit)
            for ln in str(lock).split("\n"):
                out.append((" │ " if look != "ascii" else " | ") + ln.ljust(11)[:11] + (" │\n" if look != "ascii" else " |\n"),
                           style=lit)
            out.append((" ╰─────────────╯\n" if look != "ascii" else " +-------------+\n") + f"  {pin.replace('┬', '┴')} " * 1 +
                       "\n", style=lit)
            out.append("OPENS BY ITSELF AT EVERY START", style=lit)
            return out
        for key, title in (("passphrase", "TYPE IT AT EVERY RESTART"), ("none", "UNLOCKED DISK")):
            on = s.get("unlock") == key
            st = lit if on else dim
            art = ("⌨ + ⚿" if look != "ascii" else "kbd + key") if key == "passphrase" else ("▐█▌ ○" if look != "ascii" else "[#] o")
            out.append(("◉ " if on else "○ ") + f"{art}  {title}\n", style=st)
        return out

    # ── Updates ─────────────────────────────────────────────────────────────────────
    def build_updates(self, box):
        T = _t()
        s = self._s()
        self.heading(box, "updates")
        box = self._hero(box, lambda t: Text.assemble(BT.dial(s.get("update_window", "03:00-05:00"), s.get("update_mode", "auto")),
                                                      "\n", BT.pipeline(s.get("update_mode", "auto"), t)), "srv-dial")
        ch = Vertical(id="srv-modes")
        box.mount(ch)
        for m in server.presets().get("updates", {}).get("modes", ["auto", "download", "off"]):
            title, words = server.MODES[m]
            ch.mount(self._choice(f"supd-{m}", title, [words] if not self._small() else [], s.get("update_mode") == m,
                                  {"auto": "update", "download": "copy", "off": "power"}[m], f"{title}. {words}"))
        wins = list(server.presets().get("updates", {}).get("windows") or ["03:00-05:00"])
        if s.get("update_window") not in wins:
            wins.append(s["update_window"])
        box.mount(Static(Text.assemble((T.ic("clock") + "  ", T.col("primary")), ("The maintenance window", T.col("soft"))),
                         classes="vlabel"),
                  T.hint(Select([(f"{server.window_words(w)} ({w})", w) for w in wins], value=s["update_window"],
                                allow_blank=False, id="srv-window"),
                         "In this server's time zone. It restarts only inside the window, and only when an update needs it."),
                  self._switch_row("srv-notify", s.get("notify_phone"), "Tell my phone (BRODEC)",
                                   "Updates, a rollback, a failing disk, a late backup: once your phone is paired in the tour."))
        self.upd_facts = Static("", classes="card")
        box.mount(self.upd_facts)
        self._upd_facts()

    def _upd_facts(self):
        T = _t()
        s = self._s()
        if getattr(self, "upd_facts", None) is None:
            return
        lines = [("rollback", "A snapshot first. Your data, containers and the update history are kept apart, so a rollback "
                              "never undoes them."),
                 ("check", "Then a health check: services, network, SSH and this role's own."),
                 ("rollback", "Not healthy in 10 minutes? It goes back by itself, and says why."),
                 ("power", "A restart only when the update needs one, and only in the window."),
                 ("info", "When Arch's news asks for a manual step, it waits and tells you first.")]
        if "lab" in server.roles_of(s):
            lines.append(("lab", "In your lab's cluster, the lab restarts its machines one at a time."))
        if s.get("update_mode") == "off":
            lines = [("power", "Nothing runs by itself. bromigos update, any time, takes the snapshot and does the rest.")]
        self.upd_facts.update(T.icon_rows(lines, style=T.col("text")))
        self._hero_redraw()
        for w in self.query("#srv-window"):
            w.disabled = s.get("update_mode") == "off"

    # ── Run: what should this server run? ───────────────────────────────────────────
    def build_services(self, box):
        from . import provision as PV
        T = _t()
        s = self._s()
        self.heading(box, "services")
        self._hw = PV.hardware(self.probe)
        box = self._hero(box, lambda t: self._budget_art(), "srv-budget")
        box.mount(Static("This server: " + PV.hw_words(self._hw), classes="muted"))
        box.mount(Static(Text.assemble((T.ic("lab") + "  ", T.col("primary")), ("Its place in your lab", T.col("soft"))),
                         classes="vlabel"))
        row = Vertical(id="srv-labs")
        box.mount(row)
        for k in ("new", "join", "none"):
            title, words = PV.LAB_CHOICES[k]
            row.mount(self._choice(f"slab-{k}", title, [words] if not self._small() else [], s.get("lab") == k,
                                   {"new": "free", "join": "lab", "none": "computer"}[k], f"{title}. {words}"))
        self.cat_box = Vertical(id="srv-catalogue")
        box.mount(self.cat_box)
        rid_all = server.roles_of(s) or ["plain"]
        box.mount(Static(Text.assemble((T.ic("settings") + "  ", T.col("primary")), ("On every server", T.col("soft"))),
                         classes="vlabel"),
                  Static(T.icon_rows([("check", f"{x['title']}: always on") for x in server.services_for_roles(rid_all)
                                      if x.get("locked")], style=T.col("muted"))))
        for x in [y for y in server.services_for_roles(rid_all) if not y.get("locked") and server.service_shown(y)
                  and y["id"] != "pelican-wings"]:
            box.mount(self._switch_row(f"ssvc-{x['id']}", s["services"].get(x["id"], any(
                server.default_on(x, r, server.has_lab(s)) for r in rid_all)), x["title"], x["words"]))
        self.call_later(self._fill_catalogue)

    def _budget_art(self):
        from . import provision as PV
        ids, auto = PV.resolve(server.provision_picks(self.a, getattr(self, "_hw", None)))
        b = PV.budget(ids, getattr(self, "_hw", {}) or {}, server.srv(self.a).get("models") or ())
        t = Text(f"{len(ids)} CHOSEN · " + ("FITS THIS SERVER" if b.get("fits", True) else "▲ MORE THAN IT HAS") + "\n",
                 style="bold " + _t().col("primary" if b.get("fits", True) else "warn"))
        t.append_text(BT.budget(b, getattr(self, "_hw", {}) or {}, self._hero_width()))
        return t

    async def _fill_catalogue(self):
        async with self.redraw:
            from . import provision as PV
            T = _t()
            s = self._s()
            box = getattr(self, "cat_box", None)
            if box is None or self.step != "services" or not box.is_attached:
                return
            await box.remove_children()
            if s.get("lab") == "join":
                j = s.get("lab_join") or {}
                rs = RadioSet(id="srv-join")
                box.mount(T.hint(rs, "How this server joins your lab"))
                for k, words in (("pair", "Pair with BRODEC after the install"), ("bundle", "A join bundle on the USB stick"),
                                 ("file", "The lab's connection file")):
                    rs.mount(RadioButton(words, value=(k in j) or (k == "pair" and not j), id=f"srv-join-{k}"))
                if j.get("bundle") is not None or j.get("file") is not None:
                    k = "bundle" if "bundle" in j else "file"
                    box.mount(Horizontal(self._field("srv-joinpath", "usb", "Where it is on the USB stick", j.get(k, ""),
                                                     "The file's path on the stick.", None), classes="fields"))
            picks = server.provision_picks(self.a, self._hw)
            ids, auto = PV.resolve(picks)
            sugg = server.suggested_by(self.a)
            mode = s.get("lab") or "none"
            for g in PV.groups():
                its = PV.items(g["id"], mode)
                if not its:
                    continue
                grp = Vertical(classes="srv-group")
                box.mount(grp)
                grp.mount(Static(Text.assemble((T.ic(g.get("glyph") or "settings") + "  ", T.col("primary")),
                                               (g["name"].upper(), "bold " + T.col("soft"))), classes="srv-group-head"))
                for x in its:
                    req = x.get("requires") or {}
                    tag = ""
                    if x["id"] in auto:
                        need_by = [(PV.item(o) or {}).get("name", o).split(" (")[0] for o in ids if x["id"] in (PV.item(o) or {}).get("needs", [])]
                        tag = "  + added: needed by " + ", ".join(need_by)
                    elif x["id"] in sugg:
                        tag = "  · suggested by " + " + ".join(sugg[x["id"]])
                    words = f"{x['name']} · {x.get('size_text', '')}" + tag
                    grp.mount(T.hint(Checkbox(words, x["id"] in ids, id=f"sprov-{x['id']}"),
                                     f"{x['line']} Needs {req.get('ram_gb', 0)} GB memory" + (", a graphics card" if req.get("gpu") else "")
                                     + (", the internet" if x.get("internet") else "") + "."))
                    if not self._small():
                        grp.mount(Static(x["line"], classes="srv-note"))
                for x in its:
                    if x["id"] in ids and PV.setup(x["id"]):
                        self._setup_form(grp, x)
                if g["id"] == "ai" and any(i in ids for i in ("model-serving", "models", "vllm", "ollama")):
                    ms = PV.suggest_models(self._hw)
                    if not s.get("models") and ms:
                        s["models"] = [ms[0]["id"]]
                    grp.mount(T.hint(Select([(f"{m['name']} · {m['size_text']}" + ("" if m["fits"] else " · too big"), m["id"])
                                             for m in ms], value=(s.get("models") or [ms[0]["id"]])[0], allow_blank=False,
                                            id="srv-model"), "The model vLLM serves, sized to the graphics card."))
            for c in PV.conflicts(ids):
                box.mount(Static("▲ " + c, classes="warn"))
            for n in PV.budget(ids, self._hw, server.srv(self.a).get("models") or ()).get("notes", []):
                box.mount(Static("▲ " + n, classes="warn"))
            self._hero_redraw()

    def _setup_form(self, grp, x):
        """An item's guided setup in the terminal: its notes, fields, links and check."""
        from . import provision as PV
        T = _t()
        s = self._s()
        st = PV.setup(x["id"])
        vals = s["setup"].setdefault(x["id"], PV.defaults(x["id"]))
        secrets = s["setup_secrets"].setdefault(x["id"], {})
        kids = []
        for n in PV.setup_notes(x["id"]):
            kids.append(Static(n, classes="muted"))
        shown = {f["id"] for f in PV.fields(x["id"], vals)}
        for f in PV.setup(x["id"]).get("field", []):          # all of them; show_if hides some (_setup_vis)
            kind = f.get("kind", "text")
            fid = f"sset-{x['id']}-{f['id']}"
            wrap = f"sfw-{x['id']}-{f['id']}"
            if kind == "choice":
                ch = f.get("choices", [])
                cur = vals.get(f["id"], f.get("default"))
                kids.append(Vertical(T.hint(Select([(PV.words(c, "title"), c["id"]) for c in ch],
                                                   value=cur if any(c["id"] == cur for c in ch) else Select.BLANK,
                                                   allow_blank=not any(c["id"] == cur for c in ch), id=fid),
                                            (PV.words(f, "hint") or f["label"])),
                                     Static(self._choice_note(ch, cur), classes="srv-note", id=f"snote-{x['id']}-{f['id']}"),
                                     id=wrap, classes="srv-group"))
                continue
            if kind == "bool":
                w = self._switch_row(fid, vals.get(f["id"], f.get("default")), f["label"], PV.words(f, "hint"))
                w.id = wrap
                w.display = f["id"] in shown
                kids.append(w)
                continue
            if kind == "generated":
                continue
            if True:
                cur = secrets.get(f["id"], "") if kind == "secret" else str(vals.get(f["id"], f.get("default")) or "")
                w = Horizontal(self._field(fid, "key" if kind == "secret" else "edit", f["label"], cur,
                                           (PV.words(f, "hint") or f["label"]) + (" Never written to the answer file."
                                                                                  if kind == "secret" else ""),
                                           (lambda v: None if not v or v.isdigit() else "A number.") if kind == "number" else None,
                                           password=kind == "secret"), classes="fields", id=wrap)
                w.display = f["id"] in shown
                kids.append(w)
        for title, url in PV.setup_links(x["id"], self.a.get("hostname") or "server"):
            kids.append(Static(f"{title}: {url}" + (" (after the install)" if ".local" in url else ""), classes="srv-note"))
        for gen in PV.generated(x["id"]):
            kids.append(Static(f"✓ {PV.secret_title(gen)}: generated and stored", classes="srv-note"))
        if st.get("check"):
            kids.append(Horizontal(T.hint(Button("Check", id=f"scheck-{x['id']}"), "Try these details now"),
                                   Static("", id=f"scheck-out-{x['id']}", classes="muted"), classes="buttons"))
        grp.mount(T.hint(Collapsible(*kids, title=f"Set up {x['name']}", collapsed=False, id=f"ssetup-{x['id']}"),
                         f"{x['name']}'s guided setup"))

    @staticmethod
    def _choice_note(ch, cur):
        from . import provision as PV
        c0 = next((c for c in ch if c["id"] == cur), {})
        link = PV.words(c0, "link")
        return (c0.get("note") or "") + (f"  Get an account: {link}" if link else "")

    def _setup_vis(self, item):
        """Which of an item's fields show, for its choices now (show_if); the notes follow."""
        from . import provision as PV
        vals = self._s()["setup"].get(item, {})
        shown = {f["id"] for f in PV.fields(item, vals)}
        for f in PV.setup(item).get("field", []):
            for w in self.query(f"#sfw-{item}-{f['id']}"):
                w.display = f["id"] in shown or f.get("kind") == "choice"
            if f.get("kind") == "choice":
                for w in self.query(f"#snote-{item}-{f['id']}"):
                    w.update(self._choice_note(f.get("choices", []), vals.get(f["id"], f.get("default"))))

    def _svc_sync(self):
        self._hero_redraw()

    # ── Keys: where the keys and passwords go ───────────────────────────────────────
    def build_secrets(self, box):
        T = _t()
        s = self._s()
        self.heading(box, "secrets")
        st = server.store_of(self.a)
        box = self._hero(box, lambda t: self._vault_art(t), "srv-vault")
        row = Vertical(id="srv-stores")
        box.mount(row)
        for b in server.secretstore().backends():
            row.mount(self._choice(f"sstore-{b['id']}", b["title"], [b["words"]] if not self._small() else [],
                                   st["kind"] == b["id"], {"vault": "lab", "openbao": "free", "local": "lock",
                                                           "sops": "key"}.get(b["id"], "key"), f"{b['title']}. {b['words']}"))
        self.store_box = Vertical(id="srv-store-box")
        box.mount(self.store_box)
        self.call_later(self._fill_store)

    def _vault_art(self, t):
        st = server.store_of(self.a)
        paths = server.secret_paths(self.a)
        return BT.vault(st["kind"], sum(1 for p in paths if p[3] == "typed"), sum(1 for p in paths if p[3] == "generated"), t,
                        server.tpm())

    async def _fill_store(self):
        async with self.redraw:
            T = _t()
            st = server.store_of(self.a)
            S = server.secretstore()
            box = getattr(self, "store_box", None)
            if box is None or self.step != "secrets":
                return
            await box.remove_children()
            host = self.a.get("hostname") or "this-server"
            if st["kind"] == "vault":
                j = self._s().get("lab_join") or {}
                if j.get("bundle") or j.get("file"):
                    box.mount(Static("The lab's join bundle or connection file carries the Vault's address and login.", classes="muted"))
                else:
                    box.mount(Horizontal(self._field("srv-vault-addr", "lab", "Vault's address", st.get("address"),
                                                     "For example https://vault.lab.example:8200.",
                                                     lambda v: None if v.startswith(("https://", "http://")) else "Start it with https://",
                                                     placeholder="https://vault.lab.example:8200"), classes="fields"))
                    rs = RadioSet(id="srv-vault-auth")
                    box.mount(T.hint(rs, "How this server signs in to your lab's Vault. A root token is never asked for."))
                    for x in getattr(S, "AUTH", []):
                        rs.mount(RadioButton(f"{x['title']}: {x['words']}", value=st.get("auth", "oidc") == x["id"],
                                             id=f"srv-auth-{x['id']}"))
                    if st.get("auth") == "approle":
                        box.mount(Horizontal(self._field("srv-vault-role", "user", "Role ID", st.get("role_id"), "From your lab's admin."),
                                             self._field("srv-vault-secret", "key", "Secret ID", st.get("secret_id"),
                                                         "Kept in memory only.", password=True), classes="fields"))
                    if st.get("auth") == "wrapped":
                        box.mount(Horizontal(self._field("srv-vault-token", "key", "One-time wrapped token", st.get("token"),
                                                         "Used once to fetch this server's login. Never a root token.",
                                                         password=True), classes="fields"))
                box.mount(Static(f"This server's path: {S.kv_path(st, host)}", classes="muted"),
                          T.hint(Collapsible(Static(S.policy_preview(st, host)), title="The policy it uses", collapsed=True),
                                 "What this server may read and write: its own path only."),
                          Horizontal(T.hint(Button("Test", id="srv-vault-test"), "Try the address and login now"),
                                     Static("", id="srv-vault-out", classes="muted"), classes="buttons"))
            elif st["kind"] == "openbao":
                box.mount(Static("OpenBao, compatible with HashiCorp Vault. At the first start, the welcome tour shows its unseal "
                                 "and recovery keys once, with a QR code. Keep them safe and offline.", classes="warn"))
            elif st["kind"] == "sops":
                box.mount(Horizontal(self._field("srv-sops-repo", "lab", "Your lab's secrets repository", st.get("repo"),
                                                 "The git repository with the sops-encrypted files."),
                                     self._field("srv-sops-age", "key", "This server's age recipient", st.get("age"),
                                                 "Made at the first start; add it to your .sops.yaml then."), classes="fields"))
            else:
                box.mount(Static("Encrypted with systemd's credentials (TPM2 plus the host key) and Podman's secrets. The tour "
                                 "offers a recovery bundle (age) to download or print as a QR code.", classes="muted"))
            paths = server.secret_paths(self.a)
            if paths:
                box.mount(Static(S.summary(st, [p[2] for p in paths]), classes="vlabel"),
                          Static(_t().icon_rows([("key", f"{i}.{f}: {'generated and stored' if how == 'generated' else 'typed, stored'} · {p}")
                                                 for i, f, p, how in paths], style=_t().col("text"))))
            self._hero_redraw()

    # ── Reach it from anywhere ──────────────────────────────────────────────────────
    def build_reach(self, box):
        T = _t()
        self.heading(box, "reach")
        r = self.a.setdefault("reach", {"mode": server.reach_default()})
        if not hasattr(self, "_ports"):
            self._ports = server.interfaces()
        box = self._hero(box, lambda t: BT.net_map(self._net_state() if server.is_server(self.a) else
                                                   {"address": self.a.get("hostname") or "this computer",
                                                    "reach": self._reach_title()}, self._hero_width(), t), "srv-reachmap")
        self.addr_line = None
        row = Vertical(id="srv-reaches")
        box.mount(row)
        for c in server.reach_choices():
            row.mount(self._choice(f"sreach-{c['id']}", c["title"] + (f" · needs a {c['account']} account" if c.get("account") else ""),
                                   [c["words"]] if not self._small() else [], (r.get("mode") or server.reach_default()) == c["id"],
                                   {"brodec": "phone", "lab-network": "lab"}.get(c["id"], "remote"), c["words"]))
        box.mount(Static("A public way in without a relay is a port forwarded on your router to this server: set it up on the "
                         "router, and keep keys-only sign-in.", classes="muted"))
        self.reach_box = Vertical(id="srv-reach-box")
        box.mount(self.reach_box)
        self.call_later(self._fill_reach)

    def _reach_title(self):
        mode = (self.a.get("reach") or {}).get("mode") or server.reach_default()
        return next((c["title"] for c in server.reach_choices() if c["id"] == mode), mode)

    async def _fill_reach(self):
        async with self.redraw:
            r = self.a.setdefault("reach", {"mode": server.reach_default()})
            box = getattr(self, "reach_box", None)
            if box is None or self.step != "reach":
                return
            await box.remove_children()
            mode = r.get("mode") or server.reach_default()
            m = server.reach_module()
            if mode == "lab-network":
                for where, text in (m.find_bundles() if m else [])[:2]:
                    box.mount(Static(f"Found: {where}: {m.describe(m.decode(text))}", classes="muted"))
                box.mount(Horizontal(self._field("srv-reach-bundle", "lab", "Your lab's join code", r.get("bundle"),
                                                 "From your lab, BRODEC, or the Field Kit stick.",
                                                 lambda v: server.check_reach({"mode": "lab-network", "bundle": v})), classes="fields"))
            elif mode == "wireguard":
                box.mount(Horizontal(self._field("srv-reach-wg", "remote", "WireGuard configuration (paste it, one line per [ ] block)",
                                                 r.get("wireguard"), "Your whole WireGuard configuration.",
                                                 lambda v: server.check_reach({"mode": "wireguard", "wireguard": v})), classes="fields"))
            elif mode == "tailscale":
                box.mount(Horizontal(self._field("srv-reach-ts", "key", "Auth key (optional)", r.get("tailscale_key"),
                                                 "From Tailscale's admin page; empty: sign in after the first start.", password=True),
                                     classes="fields"))
            self._hero_redraw()

    # ── events ──────────────────────────────────────────────────────────────────────
    @_ON_INPUT
    def srv_typed(self, ev):
        iid = ev.input.id or ""
        if iid.startswith("sset-"):
            self._setup_typed(iid, ev.value)
            return
        if not iid.startswith("srv-"):
            return
        s = self._s()
        v = ev.value
        key = iid.removeprefix("srv-")
        if key in ("address", "gateway", "dns"):
            s[key] = v.strip()
            self._addr_refresh()
        elif key == "prefix":
            s["prefix"] = server.prefix_from(v) or v.strip()
        elif key == "hostname":
            if v.strip() != self.a.get("hostname"):
                self.a.update(hostname=v.strip(), host_edited=True)
            self._addr_refresh()
        elif key == "vlan":
            s["vlan"] = v.strip()
        elif key == "user":
            self.a["user"] = v.strip()
        elif key == "password":
            self.a["password"] = v
            if getattr(self, "srv_meter", None) is not None:
                self._strength(self.srv_meter, v, "password")
            self._remark("srv-password2", self.a.get("password2", ""))
        elif key == "password2":
            self.a["password2"] = v
        elif key == "github":
            u = v.strip().lstrip("@")
            if u != s.get("github"):
                s.update(github=u, github_ok=False, github_keys=[], gh_problem=None)
                self._gh_fill()
        elif key == "labkey":
            s["lab_key"] = v.strip()
        elif key == "pp":
            self.a["passphrase"] = v
        elif key == "pp2":
            self.a["passphrase2"] = v
        elif key == "pelican-url":
            s["pelican_url"] = v.strip()
        elif key == "vault-addr":
            server.store_of(self.a)["address"] = v.strip()
        elif key == "vault-role":
            server.store_of(self.a)["role_id"] = v.strip()
        elif key == "vault-secret":
            server.store_of(self.a)["secret_id"] = v.strip()
        elif key == "vault-token":
            server.store_of(self.a)["token"] = v.strip()
        elif key in ("sops-repo", "sops-age"):
            server.store_of(self.a)[key[5:]] = v.strip()
        elif key == "reach-bundle":
            self.a.setdefault("reach", {})["bundle"] = v.strip()
        elif key == "reach-wg":
            self.a.setdefault("reach", {})["wireguard"] = v
        elif key == "reach-ts":
            self.a.setdefault("reach", {})["tailscale_key"] = v.strip()
        elif key == "joinpath":
            j = s.get("lab_join") or {}
            k = "bundle" if "bundle" in j else "file"
            s["lab_join"] = {k: v.strip()}
        elif key == "mirror":
            s["registry_mirror"] = v.strip()
        self._remark(iid, v)

    def _setup_typed(self, fid, v):
        from . import provision as PV
        s = self._s()
        _, item, field = fid.split("-", 2) if fid.count("-") >= 2 else (None, None, None)
        for x in PV.items():                 # item ids can hold dashes: match the longest
            if fid.startswith(f"sset-{x['id']}-"):
                item, field = x["id"], fid[len(f"sset-{x['id']}-"):]
        kinds = {f["id"]: f.get("kind") for f in PV.setup(item).get("field", [])}
        if kinds.get(field) == "secret":
            s["setup_secrets"].setdefault(item, {})[field] = v
        elif kinds.get(field) == "number":
            s["setup"].setdefault(item, {})[field] = int(v) if str(v).isdigit() else v
        else:
            s["setup"].setdefault(item, {})[field] = v
        if kinds.get(field) == "choice":
            self._setup_vis(item)
        self._remark(fid, v)

    @_ON_SWITCH
    def srv_switched(self, ev):
        sid = ev.switch.id or ""
        s = self._s()
        if sid.startswith("sset-"):
            self._setup_typed(sid, ev.value)
            return
        if sid == "srv-static":
            s["method"] = "static" if ev.value else "dhcp"
            self.call_later(self._fill_static)
            self._addr_refresh()
        elif sid == "srv-wol":
            s["wake_on_lan"] = ev.value
        elif sid in ("srv-wireguard", "srv-tailscale"):
            s[sid.removeprefix("srv-")] = ev.value
        elif sid == "srv-notify":
            s["notify_phone"] = ev.value
        elif sid.startswith("ssvc-"):
            s["services"][sid.removeprefix("ssvc-")] = ev.value
            self._svc_sync()

    @_ON_CHECK
    def srv_ticked(self, ev):
        cid = ev.checkbox.id or ""
        s = self._s()
        if cid.startswith("skey-"):
            key = self.a["found_keys"][int(cid[5:])][1]
            self.a["ssh_keys"] = [k for k in self.a["ssh_keys"] if k != key] + ([key] if ev.value else [])
        elif cid.startswith("sbond-"):
            n = cid.removeprefix("sbond-")
            s["bond"] = [b for b in (s.get("bond") or []) if b != n] + ([n] if ev.value else [])
        elif cid.startswith("sdisk-"):
            p = self._disks[int(cid[6:])]["path"]
            s["data_disks"] = [x for x in s["data_disks"] if x != p] + ([p] if ev.value else [])
            self._storage_sync()
        elif cid.startswith("sprov-"):
            from . import provision as PV
            if getattr(self, "_prov_busy", False):
                return
            picks = list(server.provision_picks(self.a, getattr(self, "_hw", None)))
            k = cid.removeprefix("sprov-")
            s["provision"] = [i for i in picks if i != k] + ([k] if ev.value else [])
            s["provision_edited"] = True
            self.call_later(self._fill_catalogue)
        elif cid.startswith("sapp-"):
            k = cid.removeprefix("sapp-")
            s["apps"] = [x for x in (s.get("apps") or []) if x != k] + ([k] if ev.value else [])
        elif cid == "srv-ghok":
            s["github_ok"] = ev.value
        elif cid == "srv-labsame":
            s["lab_same_keys"] = ev.value
            self._access_sync()
        elif cid == "srv-sep":
            self.a["separate_passphrase"] = ev.value
            self.call_later(self._fill_unlock)

    @_ON_RADIO
    def srv_radio(self, ev):
        rid = ev.radio_set.id or ""
        s = self._s()
        if rid == "srv-sshmode":
            s["ssh_mode"] = ev.pressed.id.removeprefix("srv-ssh-")
            self._access_sync()
        elif rid == "srv-vault-auth":
            server.store_of(self.a)["auth"] = ev.pressed.id.removeprefix("srv-auth-")
            self.call_later(self._fill_store)
        elif rid == "srv-join":
            k = ev.pressed.id.removeprefix("srv-join-")
            s["lab_join"] = {"pair": True} if k == "pair" else {k: (s.get("lab_join") or {}).get(k, "")}
            self.call_later(self._fill_catalogue)
        elif rid == "srv-layout":
            s["data_layout"] = "raid1" if ev.pressed.id == "srv-lay-raid1" else "single"
            self._storage_sync()

    @_ON_SELECT
    def srv_window(self, ev):
        if ev.value:
            self._s()["update_window"] = ev.value
            self._hero_redraw()

    @(on(Select.Changed) if HAVE else (lambda f: f))
    def srv_selected(self, ev):
        sid = ev.select.id or ""
        if sid == "srv-model" and ev.value:
            self._s()["models"] = [ev.value]
            self._hero_redraw()                         # the budget counts the model
        elif sid.startswith("sset-") and ev.value:
            self._setup_typed(sid, ev.value)

    def on_button_pressed(self, ev):
        bid = ev.button.id or ""
        if bid.startswith("scheck-"):
            from . import provision as PV
            item = bid.removeprefix("scheck-")
            s = self._s()
            ok, words = PV.check(item, dict(s["setup"].get(item, {}), **s["setup_secrets"].get(item, {})))
            for w in self.query(f"#scheck-out-{item}"):
                w.update(("✓ " if ok else "▲ " if ok is False else "• ") + words)
        elif bid == "srv-vault-test":
            ok, words = server.secretstore().test(server.store_of(self.a), self.a.get("hostname") or "")
            for w in self.query("#srv-vault-out"):
                w.update(("✓ " if ok else "▲ " if ok is False else "• ") + words)
        if bid == "srv-ghget":
            self._gh_fetch()
        elif bid == "srv-rescan":
            self.a["found_keys"] = common.stick_keys()
            self.a["ssh_keys"] = sorted(set(self.a["ssh_keys"]) | {k for _, k in self.a["found_keys"]})
            self.call_later(self._fill_keys)

    # ── Ready to install: the Server briefing ──────────────────────────────────────
    def server_summary_extra(self, box):
        T = _t()
        ports = getattr(self, "_ports", None)
        if ports is None:
            self._ports = ports = server.interfaces()
        line = server.ssh_line(self.a, ports)
        mode = self._s().get("ssh_mode", "keys")
        row = Horizontal(id="srv-qr-row", classes="panel")
        box.mount(row)
        side = Vertical(id="srv-qr-side")
        if mode != "off" and BT is not None and hasattr(BT, "qr_matrix"):
            m = BT.qr_matrix(server.qr_payload(self.a, ports))
            if m and BT.qr_size(m)[0] <= self.size.width - 60:
                row.mount(Static(BT.qr_text(m), id="srv-qr"))
        row.mount(side)
        side.mount(Static(Text.assemble((T.ic("shell") + "  ", T.col("primary")),
                                        ("ONCE IT'S INSTALLED, FROM YOUR COMPUTER", "bold " + T.col("soft"))), classes="panel-head"),
                   Static(Text(line, style="bold " + T.col("primary"))),
                   Static({"keys": "With one of the keys you chose. Or scan the code with an SSH app on your phone.",
                           "password": "With a key or the admin's password. Or scan the code with an SSH app on your phone.",
                           "off": "SSH is off: sign in at this computer's own screen and keyboard."}[mode], classes="muted"))

    # ── Continue ────────────────────────────────────────────────────────────────────
    def server_check(self, sid):
        q = self.query
        if sid == "access":
            for w in q("#srv-paste"):
                pasted = w.value.strip()
                if pasted:
                    problem = common.check_key(pasted)
                    if problem:
                        return problem
                    if pasted not in self.a["ssh_keys"]:
                        self.a["ssh_keys"].append(pasted)
                    w.value = ""
                    self.call_later(self._fill_keys)
            for k, key in (("srv-user", "user"), ("srv-password", "password"), ("srv-password2", "password2")):
                for w in q(f"#{k}"):
                    self.a[key] = w.value.strip() if key == "user" else w.value
        if sid == "network":
            for w in q("#srv-hostname"):
                self.a["hostname"] = w.value.strip()
        return server.check(sid, self.a, self.probe)
