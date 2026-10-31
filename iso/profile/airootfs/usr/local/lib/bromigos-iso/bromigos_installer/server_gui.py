"""bromigOS Server's steps in the graphical installer (gui.py's Window mixes this in): Role,
Network, Access, Storage, Encryption, Updates and Services, and the Server briefing on
Ready to install. DRIFTGLASS like the rest: the role cards are holograms (the screen's
FLARE is VECTOR), GLOW panels, a ✓ or ▲ beside every typed field as you type, a hover hint
on every control. The words, checks and data are server.py's (the presets file); nothing
here keeps a rule of its own."""
import os
import re
import subprocess
import tempfile
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import common, server  # noqa: E402

import bromigos_glass as glass  # noqa: E402

STEP_IDS = server.STEP_IDS

# the summary's rows: their icon and the step that changes them (gui.py's brief_rows)
BRIEF_LOOK = {"Roles": ("applications-system-symbolic", "role"), "Keys and passwords": ("dialog-password-symbolic", "secrets"),
              "Reach": ("network-vpn-symbolic", "reach"), "Lab": ("network-workgroup-symbolic", "services"),
              "Runs": ("emblem-system-symbolic", "services"), "Role": ("applications-system-symbolic", "role"), "Server name": ("network-workgroup-symbolic", "network"),
              "Network": ("network-wired-symbolic", "network"), "Admin": ("avatar-default-symbolic", "access"),
              "Sign-in": ("dialog-password-symbolic", "access"), "Remote access": ("network-vpn-symbolic", "access"),
              "Lab account": ("system-users-symbolic", "access"), "Data disks": ("drive-multidisk-symbolic", "storage"),
              "Disk encryption": ("system-lock-screen-symbolic", "unlock"), "Updates": ("view-refresh-symbolic", "updates"),
              "Services": ("emblem-system-symbolic", "services"), "Apps": ("view-app-grid-symbolic", "services"),
              "Kernel": ("application-x-firmware-symbolic", None)}
STEP_ICONS = {"secrets": "dialog-password-symbolic", "reach": "network-vpn-symbolic", "role": "applications-system-symbolic", "network": "network-wired-symbolic", "access": "dialog-password-symbolic",
              "storage": "drive-multidisk-symbolic", "unlock": "system-lock-screen-symbolic", "updates": "view-refresh-symbolic",
              "services": "emblem-system-symbolic"}
for _k, _v in STEP_ICONS.items():
    glass.STEP_ICONS.setdefault(_k, _v)

# the role cards' holograms that bromigos_driftglass doesn't have yet: a hard disk, a house,
# a game controller (the same line models: a hull and its details, in -1..1)
if glass.DG is not None and hasattr(glass.DG, "MODELS"):
    _e, _r = glass.DG._ellipse, glass.DG._rect
    glass.DG.MODELS.setdefault("drive", {
        "hull": [_r(-0.62, -0.82, 0.62, 0.82, 0.06)],
        "detail": [_e(0.0, -0.12, 0.44, 0.44), _e(0.0, -0.12, 0.08, 0.08, 10), [(0.42, 0.52), (0.08, -0.06)],
                   [(-0.44, 0.64), (-0.1, 0.64)]],
        "dots": [(0.44, 0.66)]})
    glass.DG.MODELS.setdefault("house", {
        "hull": [[(-0.78, -0.04), (0.0, -0.8), (0.78, -0.04), (0.6, -0.04), (0.6, 0.74), (-0.6, 0.74), (-0.6, -0.04),
                  (-0.78, -0.04)]],
        "detail": [_r(-0.16, 0.24, 0.16, 0.74), _r(0.26, 0.06, 0.48, 0.28), _r(-0.48, 0.06, -0.26, 0.28)],
        "dots": [(0.1, 0.5)]})
    glass.DG.MODELS.setdefault("gamepad", {
        "hull": [[(-0.86, -0.18), (-0.6, -0.42), (0.6, -0.42), (0.86, -0.18), (0.92, 0.36), (0.66, 0.52), (0.42, 0.26),
                  (-0.42, 0.26), (-0.66, 0.52), (-0.92, 0.36), (-0.86, -0.18)]],
        "detail": [[(-0.58, -0.12), (-0.58, 0.12)], [(-0.7, 0.0), (-0.46, 0.0)], _e(-0.14, 0.06, 0.06, 0.06, 8),
                   _e(0.14, 0.06, 0.06, 0.06, 8)],
        "dots": [(0.5, -0.12), (0.62, 0.0), (0.5, 0.12), (0.38, 0.0)]})

CSS = """
.sv-addr {{ font-size: 2.4em; font-weight: 700; color: {p}; letter-spacing: 0.04em; }}
.sv-addr.small {{ font-size: 1.6em; }}
.sv-ssh {{ font-family: "Geist Mono", monospace; font-size: 1.35em; font-weight: 700; color: {p}; }}
.sv-panel {{ border: 1px solid {line}; background-color: {bg}; padding: 14px 18px; }}
.sv-key {{ font-family: "Geist Mono", monospace; font-size: 0.86em; color: {muted}; }}
"""


def hint(widget, text):
    widget.set_tooltip_text(text)
    try:
        widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [text])
    except Exception:
        pass
    return widget


def label(text, classes=(), wrap=True, xalign=0.0, selectable=False):
    lab = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=selectable)
    if wrap:
        lab.set_wrap_mode(2)
    for c in classes:
        lab.add_css_class(c)
    return lab


def esc(t):
    return GLib.markup_escape_text(t or "")


def qr_png(payload, size=8):
    """The payload as a QR PNG (qrencode, else python-qrcode), or None."""
    out = os.path.join(tempfile.gettempdir(), f"bromigos-ssh-qr-{abs(hash(payload))}.png")
    try:
        r = subprocess.run(["qrencode", "-o", out, "-s", str(size), "-m", "2", "-l", "M", payload], capture_output=True, timeout=10)
        if r.returncode == 0 and os.path.exists(out):
            return out
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        import qrcode
        qrcode.make(payload, border=2).save(out)
        return out
    except Exception:
        return None


class ServerPages:
    """The Window's server steps: build_<step>, server_check, the briefing, the harness's script."""

    # ── shared bits ─────────────────────────────────────────────────────────────────
    def _srv_css(self):
        if getattr(self, "_srv_css_on", False):
            return
        c = self.c
        p = Gtk.CssProvider()
        r, g, b = (int(c["primary"][i:i + 2], 16) for i in (1, 3, 5))
        p.load_from_string(CSS.format(p=c["primary"], muted=c["muted"], line=f"rgba({r},{g},{b},0.45)",
                                      bg=f"rgba({r},{g},{b},0.05)"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._srv_css_on = True

    def _s(self):
        self._srv_css()
        return server.srv(self.a)

    def _still(self):
        return self.reduced or bool(self.opts.get("render"))

    def _wide(self):
        return self.content_width() >= 900

    def _hero_size(self):
        return (380, 290) if self._wide() else (min(560, max(320, self.content_width() - 40)), 220)

    def _split(self, page, hero, under=None):
        """The step's one hero visual beside the controls (wide), or above them; returns where the
        controls go."""
        if self._wide():
            row = Gtk.Box(spacing=22)
            left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, hexpand=True)
            right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.START)
            right.append(hero)
            if under is not None:
                right.append(under)
            row.append(left)
            row.append(right)
            page.append(row)
            return left
        hero.set_halign(Gtk.Align.CENTER)
        page.append(hero)
        if under is not None:
            page.append(under)
        return page

    def _radio_rows(self, group, items, current, on_pick, tips=None):
        """Rows with a radio button each: items [(value, title, subtitle, icon)]."""
        first, rows = None, {}
        for value, title, sub, ic in items:
            row = Adw.ActionRow(title=esc(title), subtitle=esc(sub))
            row.set_subtitle_lines(0)
            if ic:
                row.add_prefix(glass.icon(ic, 20, "dg-row-icon"))
            b = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first:
                b.set_group(first)
            first = first or b
            b.set_active(value == current)
            b.connect("toggled", lambda w, v=value: w.get_active() and on_pick(v))
            row.add_suffix(b)
            row.set_activatable_widget(b)
            hint(row, (tips or {}).get(value) or f"{title}: {sub}")
            group.add(row)
            rows[value] = (row, b)
        return rows

    def _field(self, group, title, value, tip, icon_name, check=None, password=False, on_change=None):
        row = (Adw.PasswordEntryRow if password else Adw.EntryRow)(title=title)
        row.add_prefix(glass.icon(icon_name, 18, "dg-row-icon"))
        row.set_text(value or "")
        mark = glass.valid_mark()
        row.add_suffix(mark)
        hint(row, tip)
        group.add(row)

        def changed(*_):
            if on_change:
                on_change(row.get_text())
            if check:
                glass.set_valid(mark, check(row.get_text()), shown=bool(row.get_text()))
        row.connect("changed", changed)
        changed()
        row.mark = mark
        return row

    # ── Role ────────────────────────────────────────────────────────────────────────
    def build_role(self, page):
        s = self._s()
        self.heading(page, "role")
        w = self.content_width()
        ncol = 3 if w >= 900 else (2 if w >= 560 else 1)
        grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True)
        grid.update_property([Gtk.AccessibleProperty.LABEL], ["What this server will do"])
        first = None
        small = self.screen_h() < 700 or getattr(self, "compact", False)
        icons = {"lab": "applications-science-symbolic", "storage": "drive-multidisk-symbolic", "home": "user-home-symbolic",
                 "games": "input-gaming-symbolic", "plain": "network-server-symbolic"}
        self._role_cards = {}
        chosen = server.roles_of(s)
        for i, r in enumerate(server.roles()):
            card = glass.glyph_card(r.get("glyph", "rack"), self.c, icons.get(r["id"], "network-server-symbolic"), r["title"],
                                    [r["summary"]] + ([] if small else [r["hint"]]), r["id"] in chosen, None,
                                    still=self.reduced or bool(self.opts.get("render")), size=52 if small else 72)
            card.connect("toggled", lambda b, rid=r["id"]: self._toggle_role(rid, b.get_active()))
            hint(card, f"{r['title']}: {r['summary']} {r['hint']} " +
                 ("Just a server goes alone." if r["id"] == "plain" else "Combine it with other roles."))
            grid.attach(card, i % ncol, i // ncol, 1, 1)
            self._role_cards[r["id"]] = card
        page.append(grid)
        self.role_notes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page.append(self.role_notes)
        page.append(label("Pick one, or several: a Lab node can also be a Game server and Storage. Just a server is the "
                          "base on its own. The next steps follow what you pick, and bromigos server role add adds one later.",
                          ("dg-muted",)))
        self._role_notes()

    def _toggle_role(self, rid, on):
        if getattr(self, "_role_sync", False):
            return
        server.toggle_role(self.a, rid, on)
        chosen = server.roles_of(server.srv(self.a))
        self._role_sync = True
        for k, card in getattr(self, "_role_cards", {}).items():
            if card.get_active() != (k in chosen):
                card.set_active(k in chosen)
        self._role_sync = False
        if not self.a.get("host_edited"):
            first = chosen[0] if chosen else "plain"
            self.a["hostname"] = {"lab": "lab-node", "storage": "storage", "home": "home-server", "games": "game-server"}.get(
                first, "bromigos-server")
        self._role_notes()

    def _pick_role(self, rid):
        server.pick_role(self.a, rid)
        if not self.a.get("host_edited"):
            self.a["hostname"] = {"lab": "lab-node", "storage": "storage", "home": "home-server", "games": "game-server"}.get(
                rid, "bromigos-server")

    def _role_notes(self):
        from . import provision as PV
        box = getattr(self, "role_notes", None)
        if box is None:
            return
        while (ch := box.get_first_child()):
            box.remove(ch)
        rids = server.roles_of(server.srv(self.a))
        if len(rids) > 1:
            head = label("● " + server.roles_words(rids).upper(), ("dg-chip",), wrap=False)
            head.set_halign(Gtk.Align.START)
            box.append(head)
        for n in server.combo_notes(rids, PV.hardware(self.probe)):
            box.append(label("▲ " + n if "It wants" in n else n, ("dg-note",)))

    # ── Keys: where the keys and passwords go ───────────────────────────────────────
    def build_secrets(self, page):
        s = self._s()
        self.heading(page, "secrets")
        st = server.store_of(self.a)
        S = server.secretstore()
        self.vault = glass.VaultHolo(self.c, self._hero_size()[0], 260 if self._wide() else 210, still=self._still())
        hint(self.vault, "The store your keys go into, and the keys flowing into it as each is stored")
        page = self._split(page, self.vault)
        g = Adw.PreferencesGroup()
        lab_new = s.get("lab") == "new" or "vault" in (s.get("provision") or [])
        rows = []
        for b in S.backends():
            sub = b["words"]
            if b["id"] == "vault" and s.get("lab") == "join" and "Recommended" not in sub:
                sub += " Recommended: this server joins a lab."
            if b["id"] == "openbao" and not lab_new:
                sub += " Choosing it starts a new lab here, with the Secrets (OpenBao) service."
            rows.append((b["id"], b["title"], sub, {"vault": "network-server-symbolic", "openbao": "list-add-symbolic",
                                                    "local": "drive-harddisk-symbolic"}.get(b["id"], "dialog-password-symbolic")))
        self._radio_rows(g, rows, st["kind"], lambda v: (st.update(kind=v), GLib.idle_add(lambda: (self._keys_fill(), False)[1])))
        page.append(g)
        self.keys_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.append(self.keys_box)
        self._keys_fill()

    def _keys_fill(self):
        s = server.srv(self.a)
        st = server.store_of(self.a)
        S = server.secretstore()
        box = self.keys_box
        while (ch := box.get_first_child()):
            box.remove(ch)
        host = self.a.get("hostname") or "this-server"
        paths = server.secret_paths(self.a)
        where = {"vault": "your lab's Vault", "openbao": "a new Vault (OpenBao)", "local": "this server, encrypted",
                 "sops": "your lab's sops repository"}.get(st["kind"], "")
        self.vault.set_state(kind=st["kind"], typed=sum(1 for p in paths if p[3] == "typed"),
                             generated=sum(1 for p in paths if p[3] == "generated"), where=where, tpm=server.tpm())
        if st["kind"] == "vault":
            joined = (s.get("lab_join") or {})
            if joined.get("bundle") or joined.get("file"):
                box.append(label("The lab's " + ("join bundle" if joined.get("bundle") else "connection file") +
                                 " carries the Vault's address and this server's login.", ("dg-muted",)))
            else:
                g = Adw.PreferencesGroup(title=esc("YOUR LAB'S VAULT"))
                self._field(g, "Vault's address", st.get("address"), "For example https://vault.lab.example:8200.",
                            "network-server-symbolic", lambda v: None if re.match(r"^https?://\S+", v or "") else
                            "Start it with https://", on_change=lambda v: st.update(address=v.strip()))
                auths = S.AUTH if hasattr(S, "AUTH") else []
                self._radio_rows(g, [(x["id"], x["title"], x["words"], "dialog-password-symbolic") for x in auths],
                                 st.get("auth", "oidc"), lambda v: (st.update(auth=v),
                                                                    GLib.idle_add(lambda: (self._keys_fill(), False)[1])))
                if st.get("auth") == "approle":
                    self._field(g, "Role ID", st.get("role_id"), "From your lab's admin.", "user-info-symbolic", None,
                                on_change=lambda v: st.update(role_id=v.strip()))
                    self._field(g, "Secret ID", st.get("secret_id"), "From your lab's admin; kept in memory only.",
                                "dialog-password-symbolic", None, password=True, on_change=lambda v: st.update(secret_id=v.strip()))
                if st.get("auth") == "wrapped":
                    self._field(g, "One-time wrapped token", st.get("token"), "Used once to fetch this server's login. A root "
                                "token is never asked for.", "dialog-password-symbolic", None, password=True,
                                on_change=lambda v: st.update(token=v.strip()))
                box.append(g)
            t = Adw.PreferencesGroup(title=esc("WHAT IT WILL USE"))
            pol = Adw.ExpanderRow(title="The policy", subtitle=esc("What this server may read and write: its own path only."))
            pv = label(S.policy_preview(st, host), ("sv-key",), selectable=True)
            pv.set_margin_start(12)
            pol.add_row(pv)
            t.add(pol)
            kv = Adw.ActionRow(title="This server's path", subtitle=esc(S.kv_path(st, host)))
            t.add(kv)
            test = Adw.ActionRow(title="Test the connection")
            res = label("", ("bi-status",))
            b = hint(Gtk.Button(label="Test", valign=Gtk.Align.CENTER), "Try the address and login now")

            def run(*_):
                ok, words = S.test(st, host)
                res.set_label(("✓ " if ok else "▲ " if ok is False else "• ") + words)
            b.connect("clicked", run)
            test.add_suffix(b)
            t.add(test)
            box.append(t)
            box.append(res)
        elif st["kind"] == "openbao":
            box.append(label("OpenBao, compatible with HashiCorp Vault. At the first start, the welcome tour shows its unseal and "
                             "recovery keys once, with a QR code. Keep them somewhere safe and offline: without them, nobody can "
                             "open the Vault again.", ("dg-note",)))
        elif st["kind"] == "sops":
            g = Adw.PreferencesGroup(title=esc("YOUR LAB'S SOPS REPOSITORY"))
            self._field(g, "The repository", st.get("repo"), "The git repository holding the sops-encrypted files.",
                        "folder-remote-symbolic", None, on_change=lambda v: st.update(repo=v.strip()))
            g.add(Adw.ActionRow(title="This server's age key", subtitle=esc("Made at the first start; add its recipient to "
                                                                             "your .sops.yaml then.")))
            box.append(g)
        else:
            box.append(label("Kept with systemd's encrypted credentials and Podman's secrets" +
                             (", sealed to this computer's security chip" if server.tpm() else "") +
                             ". The welcome tour offers an encrypted backup (age) to download.", ("dg-muted",)))
        if paths:
            g = Adw.PreferencesGroup(title=esc("WHAT GOES IN IT"), description=esc(S.summary(st, [p[2] for p in paths])))
            for i, f, path, how in paths:
                row = Adw.ActionRow(title=esc(f"{i} · {f}"), subtitle=esc(("generated and stored · " if how == "generated" else
                                                                         "typed, stored · ") + path))
                row.add_prefix(glass.icon("dialog-password-symbolic", 16, "dg-row-icon"))
                hint(row, "Its value never goes in a file or the answer file; only where it's kept.")
                g.add(row)
            box.append(g)
        else:
            box.append(label("Nothing to store yet: what you pick to run asks for its keys there, and they come here.",
                             ("dg-muted",)))

    # ── Reach it from anywhere ──────────────────────────────────────────────────────
    def build_reach(self, page):
        s = self._s() if server.is_server(self.a) else None
        self.heading(page, "reach")
        r = self.a.setdefault("reach", {"mode": server.reach_default()})
        if not hasattr(self, "_ports"):
            self._ports = server.interfaces()
        self.net_map = glass.NetworkMap(self.c, *self._hero_size(), still=self._still())
        hint(self.net_map, "Your network, and how your devices reach this server from anywhere")
        self.addr_words = label("", ("dg-muted",))
        page = self._split(page, self.net_map)
        g = Adw.PreferencesGroup()
        self._radio_rows(g, [(c["id"], c["title"] + (" · needs a " + c["account"] + " account" if c.get("account") else ""),
                              c["words"], {"brodec": "phone-symbolic", "lab-network": "network-workgroup-symbolic",
                                           "wireguard": "network-vpn-symbolic", "tailscale": "network-vpn-symbolic"}.get(c["id"],
                                                                                                                        "network-vpn-symbolic"))
                             for c in server.reach_choices()], r.get("mode") or server.reach_default(),
                         lambda v: (r.update(mode=v), GLib.idle_add(lambda: (self._reach_fill(), False)[1])))
        page.append(g)
        page.append(label("A public way in, without a relay, is a port forwarded on your router to this server; set it "
                          "up on the router, and keep keys-only sign-in.", ("dg-muted",)))
        self.reach_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.append(self.reach_box)
        self._reach_fill()

    def _reach_fill(self):
        r = self.a.setdefault("reach", {"mode": server.reach_default()})
        box = self.reach_box
        while (ch := box.get_first_child()):
            box.remove(ch)
        mode = r.get("mode") or server.reach_default()
        title = next((c["title"] for c in server.reach_choices() if c["id"] == mode), mode)
        if server.is_server(self.a):
            self._addr_refresh()
        self.net_map.set_state(reach=title, name=self.a.get("hostname") or "this computer")
        m = server.reach_module()
        g = Adw.PreferencesGroup()
        if mode == "lab-network":
            found = m.find_bundles() if m else []
            for where, text in found[:3]:
                row = Adw.ActionRow(title=esc("Join code found: " + where), subtitle=esc(m.describe(m.decode(text))))
                use = hint(Gtk.Button(label="Use it", valign=Gtk.Align.CENTER), "Use this join code")
                use.connect("clicked", lambda *_, t=text: (r.update(bundle=t), self._reach_fill()))
                row.add_suffix(use)
                g.add(row)
            self._field(g, "Your lab's join code", r.get("bundle"), "From your lab (bromigos lab network join), BRODEC, or the "
                        "Field Kit stick.", "network-workgroup-symbolic", lambda v: server.check_reach({"mode": mode, "bundle": v}),
                        on_change=lambda v: r.update(bundle=v.strip()))
        elif mode == "wireguard":
            tv = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
            tv.get_buffer().set_text(r.get("wireguard") or "")
            mark = label("", ("bi-status",))
            tv.get_buffer().connect("changed", lambda b: (r.update(wireguard=b.get_text(b.get_start_iter(), b.get_end_iter(), False)),
                                                           mark.set_label(("▲ " + p) if (p := server.check_reach(r)) else "✓ Looks right")))
            sw = Gtk.ScrolledWindow(min_content_height=140)
            sw.set_child(tv)
            hint(tv, "Paste your whole WireGuard configuration ([Interface] and [Peer]).")
            box.append(sw)
            box.append(mark)
        elif mode == "tailscale":
            self._field(g, "Auth key (optional)", r.get("tailscale_key"), "From Tailscale's admin page. Empty: sign in after "
                        "the first start.", "dialog-password-symbolic", None, password=True,
                        on_change=lambda v: r.update(tailscale_key=v.strip()))
        if g.get_first_child() is not None:
            box.append(g)

    # ── Network ─────────────────────────────────────────────────────────────────────
    def build_network(self, page):
        s = self._s()
        self.heading(page, "network")
        if not hasattr(self, "_ports"):
            self._ports = server.interfaces()
        ports = self._ports
        server.pick_interface(s, ports)
        if not self.a.get("hostname"):
            self.a["hostname"] = "bromigos-server"
        self.net_map = glass.NetworkMap(self.c, *self._hero_size(), still=self._still())
        hint(self.net_map, "Your network: the internet, your router, this server with the address it will have, and the "
                           "lab machines found")
        self.addr_words = label("", ("dg-muted",))
        self.addr_words.set_size_request(self._hero_size()[0], -1)
        self.addr_big = self.addr_words          # (the address itself is on the map's node)
        left = self._split(page, self.net_map, self.addr_words)
        if not ports:
            left.append(label("▲ No network port found. A server needs one: plug in a network cable or a USB network "
                              "adapter, then go Back and Continue to look again.", ("dg-note", "danger")))
        if server.wifi_only(ports):
            left.append(label("▲ " + server.WIFI_ONLY_WORDS, ("dg-note",)))
        self._net_look()
        g = Adw.PreferencesGroup(title=esc("NETWORK PORT"), description=esc("Wired ports first. The one with a cable is "
                                                                            "usually the one."))
        self._port_rows = self._radio_rows(
            g, [(x["name"], x["name"], server.iface_words(x), "network-wired-symbolic" if x["kind"] == "wired"
                 else "network-wireless-symbolic") for x in ports], s.get("interface"), self._pick_port)
        left.append(g)
        g2 = Adw.PreferencesGroup(title=esc("ADDRESS"))
        how = Adw.ComboRow(title="How it gets its address", model=Gtk.StringList.new(
            ["From your router (DHCP)", "A fixed address (static)"]))
        how.add_prefix(glass.icon("network-workgroup-symbolic", 18, "dg-row-icon"))
        how.set_selected(1 if s.get("method") == "static" else 0)
        hint(how, "DHCP: your router picks it, and it may change. Fixed: always the same, best for a server others reach.")
        g2.add(how)
        x0 = server.port(s, ports) or {}
        self.net_f = {}
        for key, title, tip, ic, chk in (
                ("address", "Address", "This server's address, for example 192.0.2.20: one your router doesn't hand out.",
                 "network-server-symbolic", server.check_address),
                ("prefix", "Network size (prefix)", "24 for most home networks (the same as 255.255.255.0).",
                 "view-grid-symbolic", lambda v: server.check_prefix(server.prefix_from(v) or v, s.get("address"))),
                ("gateway", "Router (gateway)", "Your router's address, for example 192.0.2.1.", "network-wired-symbolic",
                 lambda v: server.check_gateway(v, s.get("address"), server.prefix_from(s.get("prefix")) or "24")),
                ("dns", "Name servers (DNS)", "One or more, separated by spaces: usually your router's address.",
                 "network-workgroup-symbolic", server.check_dns)):
            self.net_f[key] = self._field(g2, title, s.get(key) or (str(x0.get(key) or "") if key != "dns" else
                                                                    " ".join(x0.get("dns") or [])), tip, ic, chk,
                                          on_change=lambda v, k=key: (s.update({k: v}), self._addr_refresh()))
        host = self._field(g2, "Server name", self.a.get("hostname"), "How other computers see it on your network, and its "
                           ".local name.", "computer-symbolic", common.check_hostname,
                           on_change=lambda v: (self.a.update(hostname=v.strip(), host_edited=True)
                                                if v.strip() != self.a.get("hostname") else None, self._addr_refresh()))
        self.net_f["hostname"] = host
        left.append(g2)
        g3 = Adw.PreferencesGroup(title=esc("WAKE AND ADVANCED"))
        wol = Adw.SwitchRow(title="Wake-on-LAN", subtitle=esc("Lets your phone or desktop switch it on over the cable."))
        wol.add_prefix(glass.icon("system-shutdown-symbolic", 18, "dg-row-icon"))
        wol.set_subtitle_lines(0)
        wol.set_active(bool(s.get("wake_on_lan")))
        wol.connect("notify::active", lambda r, _p: s.update(wake_on_lan=r.get_active()))
        hint(wol, "On: a magic packet from BRODEC's Wake button or your desktop starts this server. Wired ports only.")
        g3.add(wol)
        adv = Adw.ExpanderRow(title="Advanced: VLAN and bonding", subtitle=esc("Leave these alone unless your network uses them."))
        adv.add_prefix(glass.icon("preferences-other-symbolic", 18, "dg-row-icon"))
        hint(adv, "A VLAN tag, or two ports joined as one (a bond), for networks that are set up for them.")
        vlan = Adw.EntryRow(title="VLAN number (empty: none)")
        vlan.set_text(str(s.get("vlan") or ""))
        vm = glass.valid_mark()
        vlan.add_suffix(vm)
        hint(vlan, "The VLAN tag your switch gives this server's port, from 1 to 4094. Empty for none.")

        def vlan_typed(*_):
            s["vlan"] = vlan.get_text().strip()
            glass.set_valid(vm, server.check_vlan(s["vlan"]), shown=bool(s["vlan"]))
        vlan.connect("changed", vlan_typed)
        adv.add_row(vlan)
        for x in [p for p in ports if p["kind"] == "wired"]:
            br = Adw.SwitchRow(title=esc(f"Bond {x['name']}"), subtitle=esc(server.iface_words(x)))
            br.set_active(x["name"] in (s.get("bond") or []))
            br.connect("notify::active", lambda r, _p, n=x["name"]: s.update(
                bond=[b for b in (s.get("bond") or []) if b != n] + ([n] if r.get_active() else [])))
            hint(br, "Join this port into one bond (802.3ad, active backup if the switch can't): tick two or more.")
            adv.add_row(br)
        g3.add(adv)
        left.append(g3)
        self._wol_row, self._how_row = wol, how

        def method(*_):
            s["method"] = "static" if how.get_selected() == 1 else "dhcp"
            if s["method"] == "static" and not s.get("address"):
                x = server.port(s, ports) or {}
                for k in ("address", "gateway"):
                    if x.get(k):
                        self.net_f[k].set_text(str(x[k]))
                if x.get("prefix"):
                    self.net_f["prefix"].set_text(str(x["prefix"]))
                if x.get("dns"):
                    self.net_f["dns"].set_text(" ".join(x["dns"]))
            for k in ("address", "prefix", "gateway", "dns"):
                self.net_f[k].set_visible(s["method"] == "static")
            self._addr_refresh()
        how.connect("notify::selected", method)
        method()
        self._port_sync()

    def _pick_port(self, name):
        server.srv(self.a)["interface"] = name
        self._port_sync()
        self._addr_refresh()

    def _port_sync(self):
        s = server.srv(self.a)
        x = server.port(s, getattr(self, "_ports", [])) or {}
        wired = x.get("kind") == "wired"
        ok = wired and x.get("wol") is not False
        self._wol_row.set_sensitive(ok)
        if not ok:
            self._wol_row.set_active(False)
            self._wol_row.set_subtitle(esc("Only over a cable: Wi-Fi can't wake a computer." if not wired else
                                           "This port's card can't wake the computer."))
        else:
            self._wol_row.set_subtitle(esc("Lets your phone or desktop switch it on over the cable."))

    def _addr_refresh(self):
        if not hasattr(self, "net_map"):
            return
        s = server.srv(self.a)
        addr, words = server.shown_address(self.a, getattr(self, "_ports", None))
        x = server.port(s, getattr(self, "_ports", [])) or {}
        gw = s.get("gateway") if s.get("method") == "static" else x.get("gateway", "")
        rmode = (self.a.get("reach") or {}).get("mode")
        self.net_map.set_state(reach=next((c["title"] for c in server.reach_choices() if c["id"] == rmode), None)
                               if rmode and rmode != "brodec" else None)
        self.net_map.set_state(address=addr, how="FIXED ADDRESS" if s.get("method") == "static" else "FROM YOUR ROUTER (DHCP)",
                               kind=x.get("kind", "wired"), connected=bool(x.get("carrier") or x.get("address")),
                               signal=x.get("signal"), gateway=gw or "", wifi_only=server.wifi_only(getattr(self, "_ports", [])),
                               name=self.a.get("hostname") or "server")
        self.addr_words.set_label(words + f" Sign in from another computer with: {server.ssh_line(self.a, self._ports)}")

    def _net_look(self):
        """The Sweep round the router while the gateway is looked for, and the lab's machines found."""
        if self._still():
            self.net_map.set_state(looking=False, lab=server.lab_hosts(quick=True))
            return
        self.net_map.set_state(looking=True)

        def work():
            hosts = server.lab_hosts()
            GLib.idle_add(lambda: (self.net_map.set_state(looking=False, lab=hosts), False)[1])
        threading.Thread(target=work, daemon=True).start()

    # ── Access ──────────────────────────────────────────────────────────────────────
    def build_access(self, page):
        s = self._s()
        self.heading(page, "access")
        self.acc_map = glass.AccessMap(self.c, *self._hero_size(), still=self._still())
        hint(self.acc_map, "Who can get in: your keys, the password (crossed out unless you chose it), and the lab account "
                           "on a Lab node")
        page = self._split(page, self.acc_map)
        if not self.a.get("user"):
            self.a["user"] = "admin"
        if "found_keys" not in self.a:
            self.a["found_keys"] = common.stick_keys()
            self.a["ssh_keys"] = list(dict.fromkeys(list(self.a.get("ssh_keys") or []) + [k for _, k in self.a["found_keys"]]))
        g = Adw.PreferencesGroup(title=esc("THE ADMIN"), description=esc(
            "Signs in at this console and over SSH, and uses sudo for changes. The system administrator (root) can't "
            "sign in at all."))
        self.acc_f = {}
        self.acc_f["user"] = self._field(g, "Admin's user name", self.a.get("user"), "What you type to sign in: small letters "
                                         "and digits. admin is fine.", "user-info-symbolic", server.check_admin,
                                         on_change=lambda v: self.a.update(user=v.strip()))
        self.acc_f["password"] = self._field(g, "Password", self.a.get("password"), "For the console and for sudo.",
                                             "dialog-password-symbolic", lambda v: common.check_password(v, v), password=True,
                                             on_change=lambda v: (self.a.update(password=v), self._pw_meter(v)))
        self.acc_f["password2"] = self._field(g, "Password again", self.a.get("password2"), "The same password once more.",
                                              "dialog-password-symbolic",
                                              lambda v: common.check_password(self.a.get("password", ""), v), password=True,
                                              on_change=lambda v: self.a.update(password2=v))
        page.append(g)
        meter, self._meter_set = glass.strength_meter()
        hint(meter, "How hard the password would be to guess")
        page.append(meter)
        self._pw_meter(self.a.get("password", ""))
        g2 = Adw.PreferencesGroup(title=esc("SSH: SIGNING IN FROM YOUR COMPUTER"))
        modes = [("keys", "Keys only (recommended)"), ("password", "Keys or the password"), ("off", "No SSH: only at this computer")]
        how = Adw.ComboRow(title="How to sign in", model=Gtk.StringList.new([m[1] for m in modes]))
        how.add_prefix(glass.icon("network-server-symbolic", 18, "dg-row-icon"))
        how.set_selected([m[0] for m in modes].index(s.get("ssh_mode", "keys")))
        how.set_subtitle(esc(common.SSH_KEY_WORDS))
        how.set_subtitle_lines(0)
        hint(how, common.SSH_KEY_WORDS)
        g2.add(how)
        page.append(g2)
        self.pw_warn = label("▲ " + server.PASSWORD_WARN, ("dg-note",))
        page.append(self.pw_warn)
        keys = Adw.PreferencesGroup(title=esc("KEYS ALLOWED IN"), description=esc(
            "From the USB stick's fieldkit folder, pasted, or your GitHub account's public keys."))
        for name, key in self.a["found_keys"]:
            kr = Adw.SwitchRow(title=esc(name), subtitle=esc(server.key_words(key)))
            kr.set_subtitle_lines(0)
            kr.add_prefix(glass.icon("dialog-password-symbolic", 18, "dg-row-icon"))
            kr.set_active(key in self.a["ssh_keys"])
            hint(kr, "A key from the USB stick's fieldkit folder: on lets whoever holds its private half sign in as the admin.")
            kr.connect("notify::active", lambda r, _p, k=key: (self.a.update(
                ssh_keys=[x for x in self.a["ssh_keys"] if x != k] + ([k] if r.get_active() else [])), self._acc_refresh()))
            keys.add(kr)
        for key in [k for k in self.a["ssh_keys"] if k not in [x for _, x in self.a["found_keys"]]]:
            kr = Adw.ActionRow(title="Pasted key", subtitle=esc(server.key_words(key)))
            kr.set_subtitle_lines(0)
            rm = hint(Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER), "Take this key out")
            rm.add_css_class("flat")
            rm.connect("clicked", lambda *_, k=key: (self.a.update(ssh_keys=[x for x in self.a["ssh_keys"] if x != k]),
                                                     self.show_step("access")))
            kr.add_suffix(rm)
            hint(kr, "A key you pasted: whoever holds its private half can sign in as the admin.")
            keys.add(kr)
        if not self.a["found_keys"]:
            none = Adw.ActionRow(title="No key in the USB stick's fieldkit folder",
                                 subtitle=esc("Copy your key's .pub file there and press Look again, paste it, or use GitHub."))
            none.set_subtitle_lines(0)
            again = hint(Gtk.Button(label="Look again", valign=Gtk.Align.CENTER), "Read the USB stick's fieldkit folder again.")
            again.connect("clicked", lambda *_: (self.a.pop("found_keys", None), self.show_step("access")))
            none.add_suffix(again)
            hint(none, "Keys are read from the fieldkit folder on the USB stick.")
            keys.add(none)
        paste = Adw.EntryRow(title="Paste a public key")
        paste.add_prefix(glass.icon("edit-paste-symbolic", 18, "dg-row-icon"))
        pm = glass.valid_mark()
        paste.add_suffix(pm)
        hint(paste, "One line from your other computer's .pub file, for example ~/.ssh/id_ed25519.pub. Continue adds it.")
        paste.connect("changed", lambda r: glass.set_valid(pm, common.check_key(r.get_text().strip()),
                                                           shown=bool(r.get_text().strip())))
        keys.add(paste)
        self.paste = paste
        gh = Adw.EntryRow(title="GitHub user name")
        gh.add_prefix(glass.icon("system-users-symbolic", 18, "dg-row-icon"))
        gh.set_text(s.get("github") or "")
        get = hint(Gtk.Button(label="Get keys", valign=Gtk.Align.CENTER), "Fetch the public keys GitHub shows for this name "
                   "(github.com/NAME.keys), to check and confirm. Needs the internet.")
        gh.add_suffix(get)
        hint(gh, "Your GitHub name: its public SSH keys are fetched, shown with their fingerprints, and used once you confirm.")
        keys.add(gh)

        def gh_typed(*_):
            v = gh.get_text().strip().lstrip("@")
            if v != s.get("github"):
                s.update(github=v, github_ok=False, github_keys=[])
                self._gh_rows()
        gh.connect("changed", gh_typed)
        get.connect("clicked", lambda *_: self._gh_fetch())
        self.gh_box = keys
        self._gh_extra = []
        page.append(keys)
        self.gh_line = label("", ("bi-status",))
        page.append(self.gh_line)
        self._gh_rows()
        self.keys_group = keys
        if s.get("role") == "lab":
            lg = Adw.PreferencesGroup(title=esc("THE LAB ACCOUNT"), description=esc(server.LAB_ACCOUNT_WORDS))
            same = Adw.SwitchRow(title="Use the keys above for the lab account",
                                 subtitle=esc("Off: paste your lab workstation's own key instead."))
            same.set_subtitle_lines(0)
            same.set_active(bool(s.get("lab_same_keys", True)))
            hint(same, "On: the keys above also sign in as lab. Off: only the key you paste below does.")
            lg.add(same)
            lk = self._field(lg, "Lab workstation's public key", s.get("lab_key"), "The lab workstation's .pub key: "
                             "bromigos lab provision signs in with it.", "dialog-password-symbolic",
                             lambda v: common.check_key(v.strip()), on_change=lambda v: s.update(lab_key=v.strip()))

            def same_sync(*_):
                s["lab_same_keys"] = same.get_active()
                lk.set_visible(not same.get_active())
            same.connect("notify::active", same_sync)
            same_sync()
            page.append(lg)
        rg = Adw.PreferencesGroup(title=esc("FROM OUTSIDE YOUR HOUSE"), description=esc(
            "Both are installed either way, and off unless you turn them on here or later."))
        for key, title, words in (("wireguard", "WireGuard", "Reach the server from anywhere through your own VPN, without "
                                                             "opening ports to the world. Set up its peers in the welcome tour."),
                                  ("tailscale", "Tailscale", "For people who already use it. It relies on Tailscale's "
                                                             "coordination servers, not your own.")):
            r = Adw.SwitchRow(title=title, subtitle=esc(words))
            r.set_subtitle_lines(0)
            r.add_prefix(glass.icon("network-vpn-symbolic", 18, "dg-row-icon"))
            r.set_active(bool(s.get(key)))
            r.connect("notify::active", lambda rr, _p, k=key: s.update({k: rr.get_active()}))
            hint(r, f"{title}: {words}")
            rg.add(r)
        page.append(rg)

        def mode(*_):
            s["ssh_mode"] = modes[how.get_selected()][0]
            self._acc_refresh()
            self.pw_warn.set_visible(s["ssh_mode"] == "password")
            keys.set_visible(s["ssh_mode"] != "off")
            self.gh_line.set_visible(s["ssh_mode"] != "off")
        how.connect("notify::selected", mode)
        mode()

    def _acc_refresh(self, arrived=()):
        if not hasattr(self, "acc_map"):
            return
        s = server.srv(self.a)
        keys = [server.fingerprint(k) for k in server.all_keys(self.a)]
        labels = [f"{k or 'key'} {(fp or '')[7:15]}… {c or ''}".strip() for k, fp, c in keys]
        self.acc_map.set_state(keys=labels, password=s.get("ssh_mode") == "password", ssh=s.get("ssh_mode") != "off",
                               lab=(s.get("lab_key") or "same keys") if s.get("role") == "lab" else None)
        if arrived:
            self.acc_map.keys_arrived([lb for lb, (k, fp, c) in zip(labels, keys) if any((fp or "") == server.fingerprint(a)[1]
                                                                                         for a in arrived)])

    def _pw_meter(self, v):
        if not hasattr(self, "_meter_set"):
            return
        self._meter_set(*(common.strength(v) if v else ("", "Longer is stronger: three or four unrelated words make a good one.")))

    def _gh_rows(self):
        s = server.srv(self.a)
        for r in self._gh_extra:
            self.gh_box.remove(r)
        self._gh_extra = []
        if s.get("github_keys"):
            for k in s["github_keys"]:
                kr = Adw.ActionRow(title=esc(f"GitHub: {s['github']}"), subtitle=esc(server.key_words(k)))
                kr.set_subtitle_lines(0)
                kr.add_prefix(glass.icon("dialog-password-symbolic", 18, "dg-row-icon"))
                hint(kr, "A public key GitHub shows for this name. Check the fingerprint against your own computer's.")
                self.gh_box.add(kr)
                self._gh_extra.append(kr)
            ok = Adw.SwitchRow(title="These are my keys: use them", subtitle=esc("Compare the fingerprints with "
                                                                                 "ssh-keygen -l on your computer."))
            ok.set_subtitle_lines(0)
            ok.set_active(bool(s.get("github_ok")))
            ok.connect("notify::active", lambda r, _p: (s.update(github_ok=r.get_active()),
                                                        self._acc_refresh(s["github_keys"] if r.get_active() else ())))
            hint(ok, "On: whoever holds these keys' private halves can sign in as the admin.")
            self.gh_box.add(ok)
            self._gh_extra.append(ok)

    def _gh_fetch(self):
        s = server.srv(self.a)
        self.gh_line.set_label("Asking GitHub…")

        def work():
            keys, problem = server.fetch_github_keys(s.get("github"))
            GLib.idle_add(done, keys, problem)

        def done(keys, problem):
            if problem:
                self.gh_line.set_label("▲ " + problem)
                s.update(github_keys=[], github_ok=False)
            else:
                s.update(github_keys=keys, github_ok=False)
                self.gh_line.set_label(f"✓ {len(keys)} key{'s' if len(keys) != 1 else ''} found for {s['github']}. Check "
                                       "the fingerprints, then turn on These are my keys.")
            self._gh_rows()
            return False
        threading.Thread(target=work, daemon=True).start()

    # ── Storage ─────────────────────────────────────────────────────────────────────
    def build_storage(self, page):
        s = self._s()
        self.heading(page, "storage")
        disks = server.data_disks(self.probe, self.a)
        s["data_disks"] = [p for p in s.get("data_disks", []) if p in [d["path"] for d in disks]]
        self.pool_map = glass.PoolMap(self.c, *self._hero_size(), still=self._still())
        hint(self.pool_map, "The data disks: each drive, the copies kept, the room for your data, and the shares")
        self.st_maps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.st_maps.set_size_request(self._hero_size()[0], -1)
        page = self._split(page, self.pool_map, self.st_maps)
        g = Adw.PreferencesGroup(title=esc("DATA DISKS"), description=esc("Ticked disks are erased and become one btrfs "
                                                                          "pool at /srv/data, with snapshots."))
        if not disks:
            row = Adw.ActionRow(title="No other disk", subtitle=esc("Only the system disk is here, so data stays on it, at "
                                                                    "/srv. Add disks later with bromigos storage."))
            row.set_subtitle_lines(0)
            row.add_prefix(glass.icon("drive-harddisk-symbolic", 20, "dg-row-icon"))
            hint(row, "Nothing to choose: the system disk holds the data too.")
            g.add(row)
        for d in disks:
            lost = server.erases(d)
            r = Adw.SwitchRow(title=esc(f"{d['model']} ({d['size_text']})"),
                              subtitle=esc(f"{d['path']} · {d.get('summary', '')}" + (f" · ▲ erased: {lost}" if lost else "")))
            r.set_subtitle_lines(0)
            r.add_prefix(glass.icon(glass.drive_icon(d), 20, "dg-row-icon"))
            r.set_active(d["path"] in s["data_disks"])
            r.connect("notify::active", lambda rr, _p, p=d["path"]: (s.update(
                data_disks=[x for x in s["data_disks"] if x != p] + ([p] if rr.get_active() else [])), self._storage_sync()))
            hint(r, f"Use {d['model']} for data." + (f" Everything on it is deleted: {lost}." if lost else " It's empty."))
            g.add(r)
        page.append(g)
        g2 = Adw.PreferencesGroup(title=esc("COPIES"))
        lay = Adw.ComboRow(title="How the data is kept", model=Gtk.StringList.new(
            ["One copy: all the space (single)", "Two copies: survives a failed disk (RAID1)"]))
        lay.add_prefix(glass.icon("drive-multidisk-symbolic", 18, "dg-row-icon"))
        lay.set_selected(1 if s.get("data_layout") == "raid1" else 0)
        lay.connect("notify::selected", lambda r, _p: (s.update(data_layout="raid1" if r.get_selected() == 1 else "single"),
                                                       self._storage_sync()))
        hint(lay, "Two copies (RAID1) needs two or more disks and keeps every file on two of them, so one can fail.")
        g2.add(lay)
        page.append(g2)
        self.st_lay = lay
        self.st_words = label("", ("bi-status",))
        page.append(self.st_words)
        if s.get("role") == "storage":
            g3 = Adw.PreferencesGroup(title=esc("SHARED FOLDERS"), description=esc("/srv/data/shares, on your network only."))
            for svc in [x for x in server.services_for("storage") if x["id"] in ("smb", "nfs")]:
                r = Adw.SwitchRow(title=esc(svc["title"]), subtitle=esc(svc["words"]))
                r.set_subtitle_lines(0)
                r.set_active(bool(s["services"].get(svc["id"], True)))
                r.connect("notify::active", lambda rr, _p, k=svc["id"]: (s["services"].update({k: rr.get_active()}),
                                                                         self._storage_sync()))
                hint(r, svc["words"])
                g3.add(r)
            page.append(g3)
        self._storage_sync()

    def _storage_sync(self):
        s = server.srv(self.a)
        disks = server.data_disks(self.probe, self.a)
        n = len([d for d in disks if d["path"] in s.get("data_disks", [])])
        chosen = [d for d in disks if d["path"] in s.get("data_disks", [])]
        if hasattr(self, "pool_map"):
            from .disks import plain_size
            total = sum(d["size"] for d in chosen)
            usable = total // 2 if s.get("data_layout") == "raid1" and n >= 2 else total
            sys_disk = next((d for d in (self.probe or {}).get("disks", []) if d["path"] == self.a.get("disk")), {})
            self.pool_map.set_state(disks=[(d["path"].removeprefix("/dev/"), d["size_text"]) for d in chosen],
                                    layout=s.get("data_layout", "single"), usable=plain_size(usable) if usable else "",
                                    frac=(usable / total) if total else 0.0, system=sys_disk.get("model", ""),
                                    shares=[x.upper() for x in ("smb", "nfs") if s.get("role") == "storage"
                                            and s["services"].get(x, True)])
            while (ch := self.st_maps.get_first_child()):
                self.st_maps.remove(ch)
            for d in [x for x in chosen if x.get("partitions")]:      # the disk map: what each one loses
                m = glass.DiskMap(d, self.c, "erase", still=True, height=40)
                hint(m, f"{d['model']}: " + (f"erased ({server.erases(d)})" if server.erases(d) else "empty"))
                self.st_maps.append(label(f"{d['path']} · {d['model']}", ("dg-brief-key",)))
                self.st_maps.append(m)
        self.st_lay.set_sensitive(n >= 2 or s.get("data_layout") == "raid1")
        words = server.storage_words(s, disks)
        if s.get("data_layout") == "raid1" and n < 2:
            words = "▲ Two copies needs two or more disks: tick another one, or choose One copy."
        self.st_words.set_label(words)

    # ── Encryption ──────────────────────────────────────────────────────────────────
    def build_unlock(self, page):
        s = self._s()
        self.heading(page, "unlock")
        has = server.tpm()
        self.unlock_holo = glass.UnlockHolo(self.c, self._hero_size()[0], 250 if self._wide() else 210, still=self._still())
        hint(self.unlock_holo, "How the disk opens at each start")
        chip = Gtk.Label(label="● SECURITY CHIP (TPM 2.0)" if has else "○ NO SECURITY CHIP", halign=Gtk.Align.CENTER)
        chip.add_css_class("dg-chip")
        if not has:
            chip.add_css_class("warn")
        hint(chip, "A TPM 2.0 chip was found: it can unlock the disk by itself at each start" if has else
             "No TPM 2.0 chip found (or it's off in the firmware's settings): the disk can't unlock by itself")
        right = self._split(page, self.unlock_holo, chip)
        if not has:
            right.append(label("This computer has no security chip (TPM 2.0), or it's turned off in its firmware settings. "
                               "So choose: lock the disk and type its passphrase after every restart, or leave it open.",
                               ("dg-muted",)))
        g = Adw.PreferencesGroup()
        self._radio_rows(g, [(k, server.UNLOCK[k][0], server.UNLOCK[k][1], {"tpm": "security-high-symbolic", "passphrase":
                         "dialog-password-symbolic", "none": "changes-allow-symbolic"}[k]) for k in server.unlock_choices(has)],
                         s.get("unlock"), lambda v: (s.update(unlock=v), self._unlock_sync()))
        right.append(g)
        g2 = Adw.PreferencesGroup()
        sep = Adw.SwitchRow(title="A passphrase of its own", subtitle=esc("Off: the admin's password is the passphrase."))
        sep.add_prefix(glass.icon("dialog-password-symbolic", 20, "dg-row-icon"))
        sep.set_active(bool(self.a.get("separate_passphrase")))
        hint(sep, "On: the disk gets its own passphrase. With the security chip, it's the spare key; keep it somewhere safe.")
        g2.add(sep)
        pp = Adw.PasswordEntryRow(title="Disk passphrase")
        pp2 = Adw.PasswordEntryRow(title="Passphrase again")
        pp.set_text(self.a.get("passphrase") or "")
        pp2.set_text(self.a.get("passphrase2") or "")
        marks = (glass.valid_mark(), glass.valid_mark())
        for r, m, tip in ((pp, marks[0], "The disk's passphrase."), (pp2, marks[1], "The same passphrase once more.")):
            r.add_prefix(glass.icon("dialog-password-symbolic", 18, "dg-row-icon"))
            r.add_suffix(m)
            hint(r, tip)
            g2.add(r)

        def typed(*_):
            self.a["passphrase"], self.a["passphrase2"] = pp.get_text(), pp2.get_text()
            glass.set_valid(marks[0], common.check_password(pp.get_text(), pp.get_text(), "passphrase"), shown=bool(pp.get_text()))
            glass.set_valid(marks[1], common.check_password(pp.get_text(), pp2.get_text(), "passphrase"), shown=bool(pp2.get_text()))
        pp.connect("changed", typed)
        pp2.connect("changed", typed)
        right.append(g2)
        self.unlock_note = label("", ("dg-note",))
        right.append(self.unlock_note)
        self._unlock_rows = (sep, pp, pp2, g2)

        def sep_sync(*_):
            self.a["separate_passphrase"] = sep.get_active()
            self._unlock_sync()
        sep.connect("notify::active", sep_sync)
        typed()
        self._unlock_sync()

    def _unlock_sync(self):
        s = server.srv(self.a)
        sep, pp, pp2, g2 = self._unlock_rows
        on = s.get("unlock") in ("tpm", "passphrase")
        self.unlock_holo.set_state(tpm=server.tpm(), choice=s.get("unlock"))
        g2.set_visible(on)
        for r in (pp, pp2):
            r.set_visible(on and sep.get_active())
        note = {"tpm": "At the first start, type the passphrase once: then the chip remembers this computer and opens it by "
                       "itself.",
                "passphrase": "After an update restarts it, the server waits for the passphrase. Your phone tells you.",
                "none": "Not locked: anyone who takes the disk out can read it."}.get(s.get("unlock"), "Choose one above.")
        self.unlock_note.set_label(note)

    # ── Updates ─────────────────────────────────────────────────────────────────────
    def build_updates(self, page):
        s = self._s()
        self.heading(page, "updates")
        size = 190 if self._wide() else 170
        self.upd_dial = glass.UpdateDial(self.c, s.get("update_window", "03:00-05:00"), s.get("update_mode", "auto"),
                                         still=self._still(), on_change=self._dial_moved, size=size)
        hint(self.upd_dial, "The maintenance window on a 24-hour dial (drag the arc, or ← →), and what every update does")
        page = self._split(page, self.upd_dial)
        g = Adw.PreferencesGroup(title=esc("HOW"))
        self._radio_rows(g, [(m, server.MODES[m][0], server.MODES[m][1], {"auto": "view-refresh-symbolic", "download":
                         "folder-download-symbolic", "off": "media-playback-pause-symbolic"}[m])
                         for m in server.presets().get("updates", {}).get("modes", ["auto", "download", "off"])],
                         s.get("update_mode"), lambda v: (s.update(update_mode=v), self._upd_sync()))
        page.append(g)
        g2 = Adw.PreferencesGroup(title=esc("WHEN"))
        wins = list(server.presets().get("updates", {}).get("windows") or ["03:00-05:00"])
        if s.get("update_window") not in wins:
            wins.append(s["update_window"])
        win = Adw.ComboRow(title="The maintenance window", model=Gtk.StringList.new(
            [f"{server.window_words(w)} ({w})" for w in wins]))
        win.add_prefix(glass.icon("preferences-system-time-symbolic", 18, "dg-row-icon"))
        win.set_selected(wins.index(s["update_window"]))
        win.set_subtitle(esc("In this server's time zone. It restarts only inside the window, and only when an update "
                             "needs it."))
        win.set_subtitle_lines(0)
        win.connect("notify::selected", lambda r, _p: (s.update(update_window=wins[r.get_selected()]),
                                                       self.upd_dial.set_state(window=wins[r.get_selected()])))
        self._upd_wins = wins
        hint(win, "Updates start in this window, each server at its own moment in it, so a lab's machines never all restart "
                  "at once.")
        g2.add(win)
        ph = Adw.SwitchRow(title="Tell my phone (BRODEC)", subtitle=esc("Updates, a rollback, a failing disk, a late backup: "
                                                                        "once your phone is paired in the welcome tour."))
        ph.set_subtitle_lines(0)
        ph.add_prefix(glass.icon("phone-symbolic", 18, "dg-row-icon"))
        ph.set_active(bool(s.get("notify_phone")))
        ph.connect("notify::active", lambda r, _p: s.update(notify_phone=r.get_active()))
        hint(ph, "End-to-end encrypted notices to BRODEC on your phone. Nothing goes until you pair it.")
        g2.add(ph)
        page.append(g2)
        self.upd_facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(glass.section("Every update, the same way"))
        page.append(self.upd_facts)
        self._upd_win = win
        self._upd_sync()

    def _dial_moved(self, window):
        s = server.srv(self.a)
        s["update_window"] = window
        if window not in self._upd_wins:
            self._upd_wins.append(window)
            self._upd_win.get_model().append(f"{server.window_words(window)} ({window})")
        self._upd_win.set_selected(self._upd_wins.index(window))

    def _upd_sync(self):
        s = server.srv(self.a)
        if hasattr(self, "upd_dial"):
            self.upd_dial.set_state(mode=s.get("update_mode"))
        while (ch := self.upd_facts.get_first_child()):
            self.upd_facts.remove(ch)
        self._upd_win.set_sensitive(s.get("update_mode") != "off")
        lines = [("camera-photo-symbolic", "A snapshot of the system first. Your data, containers and the update history "
                  "are kept apart, so a rollback never undoes them."),
                 ("emblem-ok-symbolic", "Then a health check: the services, the network, SSH and this role's own checks."),
                 ("edit-undo-symbolic", "Not healthy in 10 minutes? It goes back to the snapshot by itself, and says why."),
                 ("system-reboot-symbolic", "A restart only when the update needs one (a new kernel, say), and only in the window."),
                 ("dialog-information-symbolic", "When Arch's news asks for a manual step, it waits and tells you first.")]
        if s.get("role") == "lab":
            lines.append(("network-workgroup-symbolic", "In your lab's cluster, the lab restarts its machines one at a time, "
                          "moving their work away first."))
        if s.get("update_mode") == "off":
            lines = [("media-playback-pause-symbolic", "Nothing runs by itself. bromigos update, any time, takes the snapshot "
                      "and does the rest.")]
        self.upd_facts.append(glass.numbered(lines))

    # ── Services ────────────────────────────────────────────────────────────────────
    SVC_ICONS = {"sshguard": "security-high-symbolic", "disk-health": "drive-harddisk-symbolic",
                 "monitoring": "utilities-system-monitor-symbolic", "mdns": "network-workgroup-symbolic",
                 "backups": "document-save-symbolic", "ups": "battery-full-charging-symbolic", "apparmor": "security-medium-symbolic",
                 "cockpit": "web-browser-symbolic", "nfs-client": "folder-remote-symbolic", "gpu": "video-display-symbolic",
                 "smb": "folder-publicshare-symbolic", "nfs": "folder-remote-symbolic", "timeline": "document-open-recent-symbolic",
                 "replication": "emblem-synchronizing-symbolic", "spindown": "media-playback-pause-symbolic",
                 "front-door": "web-browser-symbolic", "performance": "power-profile-performance-symbolic",
                 "pelican-wings": "input-gaming-symbolic", "photos": "camera-photo-symbolic", "media": "video-x-generic-symbolic",
                 "passwords": "dialog-password-symbolic", "documents": "x-office-document-symbolic",
                 "home-assistant": "user-home-symbolic", "adblock": "action-unavailable-symbolic",
                 "sync": "emblem-synchronizing-symbolic", "uptime-kuma": "utilities-system-monitor-symbolic",
                 "homepage": "go-home-symbolic", "s3": "network-server-symbolic", "minecraft": "input-gaming-symbolic"}

    def _tile(self, key, title, words, on, on_toggle, big=False):
        """A service or app as a tile: its icon, its name, and a Reading that glows while it's on."""
        b = Gtk.ToggleButton(active=on)
        b.add_css_class("dg-card")
        b.set_size_request(230 if big else 190, 120 if big else 92)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=12,
                    margin_end=12)
        head = Gtk.Box(spacing=10)
        head.append(glass.icon(self.SVC_ICONS.get(key, "emblem-system-symbolic"), 26 if big else 22, "dg-card-icon"))
        t = label(title, ("dg-card-title",))
        t.set_hexpand(True)
        head.append(t)
        v.append(head)
        if big:
            v.append(label(words, ("dg-card-text",)))
        state = label("", ("dg-chip",))
        state.set_halign(Gtk.Align.START)
        v.append(state)
        b.set_child(v)

        def sync(*_):
            state.set_label("● ON" if b.get_active() else "○ OFF")
            (state.remove_css_class if b.get_active() else state.add_css_class)("quiet")
            on_toggle(b.get_active())
        b.connect("toggled", sync)
        state.set_label("● ON" if on else "○ OFF")
        if not on:
            state.add_css_class("quiet")
        hint(b, f"{title}: {words} Click to turn it {'off' if on else 'on'}.")
        return b

    def _tiles(self, items, big=False):
        w = self.content_width() - (400 if self._wide() else 0)
        per = max(1, min(4, int(w // (250 if big else 205))))
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=10, row_spacing=10,
                           max_children_per_line=per, min_children_per_line=per)
        for t in items:
            grid.append(t)
        return grid

    def build_services(self, page):
        """What should this server run? Its place in a lab, then the catalogue by group (the roles'
        suggestions ticked, what they need added and shown), each pick's guided setup, the model for
        model serving, and the services every server has; the budget meter fills as you pick."""
        from . import provision as PV
        s = self._s()
        self.heading(page, "services")
        self._hw = PV.hardware(self.probe)
        self.budget = glass.BudgetHolo(self.c, self._hero_size()[0], 250 if self._wide() else 200, still=self._still())
        hint(self.budget, "What the chosen services need of this computer: processor, memory, disk and graphics card")
        hw_line = label("This server: " + PV.hw_words(self._hw), ("dg-muted",))
        hw_line.set_size_request(self._hero_size()[0], -1)
        page = self._split(page, self.budget, hw_line)
        page.append(glass.section("Its place in your lab"))
        lab_row = Gtk.Box(spacing=12, homogeneous=True)
        first = None
        for k, glyph in (("new", "rack"), ("join", "cloud"), ("none", "tower")):
            title, words = PV.LAB_CHOICES[k]
            card = glass.glyph_card(glyph, self.c, {"new": "list-add-symbolic", "join": "network-workgroup-symbolic",
                                                    "none": "computer-symbolic"}[k], title, [words], s.get("lab") == k, first,
                                    still=self._still(), size=44)
            first = first or card
            card.connect("toggled", lambda b, kk=k: b.get_active() and self._pick_lab(kk))
            hint(card, f"{title}: {words}")
            lab_row.append(card)
        page.append(lab_row)
        self.join_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.append(self.join_box)
        self.cat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.append(self.cat_box)
        page.append(glass.section("On every server"))
        rid_all = server.roles_of(s) or ["plain"]
        locked = [x for x in server.services_for_roles(rid_all) if x.get("locked")]
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for x in locked:
            row = Gtk.Box(spacing=12)
            row.add_css_class("dg-pass")
            row.append(glass.icon("object-select-symbolic", 16))
            row.append(label(f"{x['title']} · always on", ("dg-pass-what",)))
            hint(row, f"{x['title']}: {x['words']} Always on.")
            box.append(row)
        page.append(box)
        tiles = []
        for x in [y for y in server.services_for_roles(rid_all) if not y.get("locked") and server.service_shown(y)
                  and y["id"] != "pelican-wings"]:
            on = bool(s["services"].get(x["id"], any(server.default_on(x, r, server.has_lab(s)) for r in rid_all)))
            tiles.append(self._tile(x["id"], x["title"], x["words"], on,
                                    lambda v, k=x["id"]: (s["services"].update({k: v}), self._svc_sync())))
        page.append(self._tiles(tiles))
        self._join_fill()
        self._cat_fill()

    def _pick_lab(self, k):
        s = server.srv(self.a)
        s.update(lab=k, lab_set=True)
        if k == "join" and not s.get("lab_join"):
            s["lab_join"] = {"pair": True}
        if not s.get("provision_edited"):
            s["provision"] = None
        self._join_fill()
        self._cat_fill()

    def _join_fill(self):
        s = server.srv(self.a)
        box = self.join_box
        while (ch := box.get_first_child()):
            box.remove(ch)
        if s.get("lab") != "join":
            return
        g = Adw.PreferencesGroup(title=esc("HOW IT JOINS"))
        j = s.get("lab_join") or {}
        cur = "bundle" if j.get("bundle") else ("file" if j.get("file") else "pair")
        self._radio_rows(g, [("pair", "Pair with BRODEC after the install", "Your phone hands it the lab's join code at the "
                              "first start.", "phone-symbolic"),
                             ("bundle", "A join bundle on the USB stick", "Made by your lab (bromigos lab network join "
                              "--bundle), copied to the stick.", "media-removable-symbolic"),
                             ("file", "The lab's connection file", "homelab.toml from your lab's workstation, on the stick.",
                              "document-open-symbolic")], cur, self._pick_join)
        if cur in ("bundle", "file"):
            self._field(g, "Where it is on the USB stick", j.get(cur, ""), "The file's path, for example "
                        "/run/media/stick/fieldkit/lab-join.bundle.", "document-open-symbolic",
                        lambda v: None if os.path.isfile(v) or server.fake() else "There's no file there.",
                        on_change=lambda v, k=cur: s.update(lab_join={k: v.strip()}))
        box.append(g)

    def _pick_join(self, how):
        s = server.srv(self.a)
        s["lab_join"] = {"pair": True} if how == "pair" else {how: (s.get("lab_join") or {}).get(how, "")}
        GLib.idle_add(lambda: (self._join_fill(), False)[1])

    def _cat_fill(self):
        """The catalogue, group by group, as tiles; rebuilt as picks change (what's added shows)."""
        from . import provision as PV
        s = server.srv(self.a)
        box = self.cat_box
        self._srv_spots = {}
        while (ch := box.get_first_child()):
            box.remove(ch)
        picks = server.provision_picks(self.a, self._hw)
        ids, auto = PV.resolve(picks)
        sugg = server.suggested_by(self.a)
        mode = s.get("lab") or "none"
        for g in PV.groups():
            its = PV.items(g["id"], mode)
            if not its:
                continue
            head = Gtk.Box(spacing=8)
            head.append(glass.icon(g.get("icon", "emblem-system-symbolic"), 18, "dg-row-icon"))
            head.append(glass.section(g["name"]))
            box.append(head)
            tiles = []
            for x in its:
                on = x["id"] in ids
                need_gpu = (x.get("requires") or {}).get("gpu") and not self._hw.get("gpu")
                badge = ("ADDED: NEEDED BY " + ", ".join((PV.item(o) or {}).get("name", o).split(" (")[0].upper()
                                                          for o in ids if x["id"] in (PV.item(o) or {}).get("needs", []))
                         if x["id"] in auto else
                         ("SUGGESTED BY " + " + ".join(sugg[x["id"]]).upper() if x["id"] in sugg else ""))
                t = self._cat_tile(x, on, badge, need_gpu)
                self._srv_spots[x["id"]] = t
                tiles.append(t)
            box.append(self._tiles(tiles, big=True))
            for x in its:
                if x["id"] in ids and PV.setup(x["id"]):
                    box.append(self._setup_form(x))
            if g["id"] == "ai" and any(i in ids for i in ("model-serving", "models", "vllm", "ollama")):
                box.append(self._model_pick())
            if g["id"] == "games" and "wings" in ids and not PV.setup("wings"):
                gp = Adw.PreferencesGroup(title=esc("YOUR LAB'S PELICAN PANEL"))
                self._field(gp, "The panel's address (optional now)", s.get("pelican_url"), "Your lab's Pelican panel, for "
                            "example https://panel.lab.example.", "network-server-symbolic",
                            lambda v: None if not v.strip() or v.strip().startswith(("https://", "http://"))
                            else "Start it with https://", on_change=lambda v: s.update(pelican_url=v.strip()))
                box.append(gp)
        for c in PV.conflicts(ids):
            box.append(label("▲ " + c, ("dg-note",)))
        b = PV.budget(ids, self._hw, s.get("models") or ())
        self.budget.set_state(need=b, have=self._hw, fits=b.get("fits", True), count=len(ids),
                              auto=[(PV.item(x) or {}).get("name", x).split(" (")[0] for x in auto])
        for n in b.get("notes", []):
            box.append(label("▲ " + n, ("dg-note",)))

    def _cat_tile(self, x, on, badge, need_gpu):
        b = Gtk.ToggleButton(active=on)
        b.add_css_class("dg-card")
        b.set_size_request(240, 130)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, margin_top=10, margin_bottom=10, margin_start=12,
                    margin_end=12)
        head = Gtk.Box(spacing=10)
        head.append(glass.icon(x.get("icon", "emblem-system-symbolic"), 24, "dg-card-icon"))
        t = label(x["name"], ("dg-card-title",))
        t.set_hexpand(True)
        head.append(t)
        tick = glass.icon("object-select-symbolic", 18, "dg-check")
        tick.set_visible(on)
        head.append(tick)
        v.append(head)
        v.append(label(x["line"], ("dg-card-text",)))
        req = x.get("requires") or {}
        meta = f"{x.get('size_text', '')} · {req.get('ram_gb', 0)} GB memory" + (" · graphics card" if req.get("gpu") else "") \
            + (" · needs the internet" if x.get("internet") else "")
        v.append(label(meta, ("dg-pass-what",)))
        if badge:
            chip = Gtk.Label(label="● " + badge if "SUGGESTED" in badge else "+ " + badge, xalign=0)
            chip.add_css_class("dg-chip")
            chip.set_halign(Gtk.Align.START)
            chip.set_wrap(True)                         # one line when it fits; the letter spacing needs room
            chip.set_width_chars(min(int(len(chip.get_label()) * 1.25) + 2, 34))
            chip.set_max_width_chars(34)
            v.append(chip)
        if need_gpu:
            v.append(label("▲ No graphics card for it here", ("bi-warn",)))
        b.set_child(v)
        hint(b, f"{x['name']}: {x['line']} {x.get('hint', '')} Needs: {meta}." + (f" {badge.capitalize()}." if badge else ""))

        def toggled(w):
            if getattr(self, "_cat_busy", False):
                return
            s = server.srv(self.a)
            picks = list(server.provision_picks(self.a, self._hw))
            s["provision"] = [i for i in picks if i != x["id"]] + ([x["id"]] if w.get_active() else [])
            s["provision_edited"] = True
            GLib.idle_add(lambda: (self._cat_fill(), False)[1])
        b.connect("toggled", toggled)
        return b

    def _setup_form(self, x):
        """An item's guided setup (its [item.setup]): notes, links, fields, the live check."""
        from . import provision as PV
        s = server.srv(self.a)
        st = PV.setup(x["id"])
        vals = s["setup"].setdefault(x["id"], PV.defaults(x["id"]))
        secrets = s["setup_secrets"].setdefault(x["id"], {})
        g = Adw.PreferencesGroup(title=esc((st.get("title") or f"Set up {x['name']}").upper()),
                                 description=esc(" ".join(PV.setup_notes(x["id"]))))
        self._srv_spots["setup:" + x["id"]] = g
        for f in PV.fields(x["id"], vals):
            kind = f.get("kind", "text")
            if kind == "choice":
                ch = f.get("choices", [])
                row = Adw.ComboRow(title=esc(f["label"]), model=Gtk.StringList.new([PV.words(c, "title") for c in ch]))
                cur = vals.get(f["id"], f.get("default"))
                row.set_selected(next((i for i, c in enumerate(ch) if c["id"] == cur), 0))
                c0 = ch[row.get_selected()] if ch else {}
                row.set_subtitle(esc(c0.get("note", "")))
                row.set_subtitle_lines(0)
                if PV.words(c0, "link"):
                    lb = Gtk.LinkButton(uri=PV.words(c0, "link"), label="Get an account", valign=Gtk.Align.CENTER)
                    hint(lb, f"{PV.words(c0, 'title')}'s sign-up page, in a browser")
                    row.add_suffix(lb)
                row.connect("notify::selected", lambda r, _p, fid=f["id"], ch=ch: (
                    vals.update({fid: ch[r.get_selected()]["id"]}), GLib.idle_add(lambda: (self._cat_fill(), False)[1])))
                hint(row, (PV.words(f, "hint") or f["label"]))
                g.add(row)
            elif kind == "bool":
                row = Adw.SwitchRow(title=esc(f["label"]), subtitle=esc(PV.words(f, "hint")))
                row.set_subtitle_lines(0)
                row.set_active(bool(vals.get(f["id"], f.get("default"))))
                row.connect("notify::active", lambda r, _p, fid=f["id"]: vals.update({fid: r.get_active()}))
                hint(row, (PV.words(f, "hint") or f["label"]))
                g.add(row)
            elif kind == "generated":
                continue                              # shown below, with the item's own secrets
            else:
                secret = kind == "secret"
                cur = secrets.get(f["id"], "") if secret else str(vals.get(f["id"], f.get("default")) or "")
                chk = (lambda v: None if not v or v.isdigit() else "A number.") if kind == "number" else None
                row = self._field(g, f["label"], cur, (PV.words(f, "hint") or f["label"]) + (" Never written to the answer file." if secret else ""),
                            "dialog-password-symbolic" if secret else "document-edit-symbolic", chk, password=secret,
                            on_change=(lambda v, fid=f["id"]: secrets.update({fid: v})) if secret else
                            (lambda v, fid=f["id"], kind=kind: vals.update({fid: int(v) if kind == "number" and v.isdigit() else v})))
                if secret:
                    bw = hint(Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER),
                              "Import it from Bitwarden or Vaultwarden (bitwarden-cli): the item named like this service")
                    bw.add_css_class("flat")

                    def from_bw(_b, row=row, iid=x["id"], fid=f["id"]):
                        val, words = server.secretstore().bitwarden(f"{iid} {fid}") if hasattr(server.secretstore(), "bitwarden") \
                            else (None, "Bitwarden import comes with the secrets module.")
                        if val:
                            row.set_text(val)
                        row.set_tooltip_text(words)
                    bw.connect("clicked", from_bw)
                    row.add_suffix(bw)

        for title, url in PV.setup_links(x["id"], self.a.get("hostname") or "server"):
            row = Adw.ActionRow(title=esc(title))
            lb = Gtk.LinkButton(uri=url, label="Open", valign=Gtk.Align.CENTER)
            row.add_suffix(lb)
            row.set_subtitle(esc(url + (" (after the install)" if ".local" in url else "")))
            hint(row, title)
            g.add(row)
        for gen in PV.generated(x["id"]):
            row = Adw.ActionRow(title=esc(PV.secret_title(gen)),
                                subtitle="Generated and stored: no one needs to type it")
            row.add_prefix(glass.icon("emblem-ok-symbolic", 16, "dg-row-icon"))
            hint(row, "Made at the first start and kept in the store you chose.")
            g.add(row)
        if st.get("check"):
            row = Adw.ActionRow(title="Check the connection", subtitle=esc("Connects once with these details."))
            res = label("", ("bi-status",))
            btn = hint(Gtk.Button(label="Check", valign=Gtk.Align.CENTER), "Try these details now (bromigos lab provision --check)")

            def run(*_):
                res.set_label("Checking…")

                def work():
                    ok, words = PV.check(x["id"], dict(vals, **secrets))
                    GLib.idle_add(lambda: (res.set_label(("✓ " if ok else "▲ " if ok is False else "• ") + words), False)[1])
                threading.Thread(target=work, daemon=True).start()
            btn.connect("clicked", run)
            row.add_suffix(btn)
            g.add(row)
            wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            wrap.append(g)
            wrap.append(res)
            return wrap
        return g

    def _model_pick(self):
        from . import provision as PV
        s = server.srv(self.a)
        ms = PV.suggest_models(self._hw)
        g = Adw.PreferencesGroup(title=esc("THE MODEL"), description=esc(f"Sized to {self._hw.get('gpu_name') or 'the card'} "
                                                                          f"({self._hw.get('gpu_vram_gb', 0)} GB)."))
        row = Adw.ComboRow(title="Model to serve", model=Gtk.StringList.new(
            [f"{m['name']} · {m['size_text']}" + ("" if m["fits"] else " · too big for this card") for m in ms]))
        if not s.get("models") and ms:
            s["models"] = [ms[0]["id"]]
        row.set_selected(next((i for i, m in enumerate(ms) if m["id"] in s["models"]), 0))
        row.set_subtitle(esc(ms[row.get_selected()]["line"] if ms else ""))
        row.set_subtitle_lines(0)
        row.connect("notify::selected", lambda r, _p: (s.update(models=[ms[r.get_selected()]["id"]]),
                                                       r.set_subtitle(esc(ms[r.get_selected()]["line"])),
                                                       GLib.idle_add(lambda: (self._cat_fill(), False)[1])))
        hint(row, "The language model vLLM serves; the biggest that fits the card comes first.")
        g.add(row)
        return g

    def _svc_sync(self):
        pass

    # ── Ready to install: the Server briefing ──────────────────────────────────────
    def server_summary_extra(self, page):
        """Under the briefing: how to sign in once it's installed, big, and as a QR to scan."""
        self._srv_css()
        ports = getattr(self, "_ports", None)
        if ports is None:
            self._ports = ports = server.interfaces()
        line = server.ssh_line(self.a, ports)
        p = server.plan(self.a)
        from .disks import plain_size
        disks = [d for d in (self.probe or {}).get("disks", []) if d["path"] in p["storage"]["disks"]]
        total = sum(d["size"] for d in disks)
        usable = total // 2 if p["storage"]["layout"] == "raid1" else total
        deck = glass.ServerDeck(self.c, max(560, self.content_width() - 20), 116, still=self._still())
        deck.set_state(address=server.shown_address(self.a, ports)[0], name=self.a.get("hostname") or "",
                       role=(server.role(p["role"]) or {}).get("title", ""), keys=len(p["access"]["keys"]),
                       password=p["access"]["password_login"], pool=plain_size(usable) if usable else "/srv",
                       frac=(usable / total) if total else 0.0,
                       copies=("TWO COPIES" if p["storage"]["layout"] == "raid1" else "ONE COPY") if disks else "SYSTEM DISK",
                       window=p["updates"]["window"], mode=p["updates"]["mode"])
        hint(deck, "This server at a glance: its address, the keys that sign in, its data, and when it updates")
        page.append(deck)
        panel = Gtk.Box(spacing=22)
        panel.add_css_class("sv-panel")
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True, valign=Gtk.Align.CENTER)
        col.append(label("ONCE IT'S INSTALLED, FROM YOUR COMPUTER", ("dg-brief-key",)))
        cmd = label(line, ("sv-ssh",), selectable=True)
        hint(cmd, "Type this on your other computer to sign in to the server")
        col.append(cmd)
        mode = server.srv(self.a).get("ssh_mode", "keys")
        col.append(label({"keys": "With one of the keys you chose. Or scan the code with an SSH app on your phone.",
                          "password": "With a key or the admin's password. Or scan the code with an SSH app on your phone.",
                          "off": "SSH is off: sign in at this computer's own screen and keyboard."}[mode], ("dg-muted",)))
        panel.append(col)
        if mode != "off":
            qr = qr_png(server.qr_payload(self.a, ports))
            if qr:
                ph = glass.PhoneFrame(self.c, 150 if self.screen_h() < 700 else 180, still=True)
                ph.set_qr(qr)
                hint(ph, f"A QR code of {server.qr_payload(self.a, ports)}: an SSH app on your phone opens it")
                panel.append(ph)
        page.append(panel)

    # ── Continue ────────────────────────────────────────────────────────────────────
    def server_check(self, sid):
        if sid == "access":
            pasted = self.paste.get_text().strip() if hasattr(self, "paste") else ""
            if pasted:
                problem = common.check_key(pasted)
                if problem:
                    return problem
                if pasted not in self.a["ssh_keys"]:
                    self.a["ssh_keys"].append(pasted)
                self.paste.set_text("")
        if sid == "network" and hasattr(self, "net_f"):
            s = server.srv(self.a)
            for k in ("address", "gateway", "dns"):
                s[k] = self.net_f[k].get_text().strip()
            s["prefix"] = server.prefix_from(self.net_f["prefix"].get_text()) or self.net_f["prefix"].get_text().strip()
            self.a["hostname"] = self.net_f["hostname"].get_text().strip()
        return server.check(sid, self.a, self.probe)

    # ── the harness's script (gui.py --script PLAN.json) ───────────────────────────
    def server_script(self, sid, plan):
        """A server step filled in from the plan's "server" part (the answer file's keys)."""
        sp = plan.get("server") or {}
        s = server.srv(self.a)
        if sid == "role":
            server.set_roles(self.a, list(sp.get("roles") or [sp.get("role", "plain")]))
            self.show_step("role")
        elif sid == "secrets":
            if sp.get("store"):
                server.store_of(self.a).update(sp["store"])
            self.show_step("secrets")
        elif sid == "reach":
            if plan.get("reach"):
                self.a["reach"] = dict(plan["reach"])
            self.show_step("reach")
        elif sid == "network":
            for k in ("interface", "method", "address", "prefix", "gateway", "dns", "vlan"):
                if k in sp:
                    s[k] = sp[k] if k != "dns" or isinstance(sp[k], str) else " ".join(sp[k])
            if plan.get("hostname"):
                self.a.update(hostname=plan["hostname"], host_edited=True)
            self.show_step("network")
        elif sid == "access":
            self.a["user"] = plan.get("user", "admin")
            self.a["password"] = self.a["password2"] = plan.get("password", "tester")
            s["ssh_mode"] = sp.get("ssh_mode", "password" if plan.get("ssh_password") else "keys")
            if plan.get("ssh_key") and plan["ssh_key"] not in (self.a.get("ssh_keys") or []):
                self.a.setdefault("ssh_keys", []).append(plan["ssh_key"])
            s.update(tailscale=bool(sp.get("tailscale")), wireguard=bool(sp.get("wireguard")))
            self.show_step("access")
        elif sid == "storage":
            s.update(data_disks=list(sp.get("data_disks", [])), data_layout=sp.get("data_layout", "single"))
            self.show_step("storage")
        elif sid == "unlock":
            s["unlock"] = sp.get("unlock") or ("passphrase" if plan.get("encrypt", True) else "none")
            self.show_step("unlock")
        elif sid == "updates":
            s.update(update_mode=sp.get("update_mode", "auto"), update_window=sp.get("update_window", "03:00-05:00"))
            self.show_step("updates")
        elif sid == "services":
            if sp.get("lab"):
                s.update(lab=sp["lab"], lab_set=True)
            if "provision" in sp:
                s["provision"], s["provision_edited"] = list(sp["provision"]), True
            for k in sp.get("services", []):
                s["services"][k] = True
            for k in sp.get("services_off", []):
                s["services"][k] = False
            if "apps" in sp:
                s["apps"] = list(sp["apps"])
            self.show_step("services")
        self._scripted = sid


# ── pictures (gui.py --render): each server step, with the recorded disks ────────────────
RENDER_PLAN = ["server-role", "server-role-multi", "server-keys-vault", "server-keys-local", "server-keys-new",
               "server-network", "server-network-static", "server-network-wifi", "server-access", "server-access-lab",
               "server-reach", "server-storage", "server-storage-raid", "server-unlock-tpm", "server-unlock-notpm",
               "server-updates", "server-run-home", "server-run-media", "server-run-media-vpn", "server-run-media-usenet",
               "server-run-lab", "server-run-games",
               "server-summary"]


def render_step(win, sid):
    """Put the window on one of RENDER_PLAN's pictures."""
    a = win.a
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheInstallerTestsOnly alex@laptop"
    a.update(edition="server", mode="erase", disk=(win.probe or {}).get("disks", [{}])[0].get("path"), user="admin",
             password="correct-horse-battery", password2="correct-horse-battery", hostname="home-server", host_edited=True)
    a.pop("reach", None)
    s = server.srv(a)
    s["provision"], s["provision_edited"] = None, False
    s.update(lab_set=False, setup={}, setup_secrets={}, store={})
    if not server.roles_of(s):
        server.set_roles(a, ["home"])
    scroll_end = sid in ("server-access-lab", "server-summary")
    if sid == "server-role":
        server.set_roles(a, ["home"])
        win.show_step("role")
    elif sid == "server-role-multi":
        server.set_roles(a, ["lab", "games", "storage"])
        win.show_step("role")
    elif sid.startswith("server-keys"):
        server.set_roles(a, ["lab", "media"])
        kind = {"server-keys-vault": "vault", "server-keys-local": "local", "server-keys-new": "openbao"}[sid]
        s.update(lab="join" if kind == "vault" else ("new" if kind == "openbao" else "none"), lab_set=True,
                 lab_join={"pair": True})
        s["store"] = {"kind": kind, "auth": "approle", "address": "https://vault.lab.example:8200", "role_id": "srv-role"}
        s["provision"], s["provision_edited"] = ["jellyfin", "gluetun", "sabnzbd", "minecraft"], True
        s["setup_secrets"] = {"gluetun": {"password": "x"}, "sabnzbd": {"password": "y"}}
        win.show_step("secrets")
    elif sid.startswith("server-network"):
        win.__dict__.pop("_ports", None)
        s.update(method="dhcp", interface=None)
        if sid == "server-network-static":
            s.update(method="static", address="192.0.2.40", prefix="24", gateway="192.0.2.1", dns="192.0.2.1 9.9.9.9")
            a["reach"] = {"mode": "lab-network"}
        if sid == "server-network-wifi":
            win._ports = [x for x in server.SAMPLE_NET if x["kind"] == "wifi"]
        win.show_step("network")
        win.__dict__.pop("_ports", None) if sid == "server-network-wifi" else None
    elif sid == "server-access":
        a["found_keys"], a["ssh_keys"] = [], [key]
        s.update(github="octocat", github_ok=True, github_keys=[
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOctocatsExampleKeyFromGitHubForPictures"])
        win.show_step("access")
    elif sid == "server-access-lab":
        server.set_roles(a, ["lab"])
        s.update(lab_same_keys=False, github="", github_keys=[], github_ok=False)
        win.show_step("access")
    elif sid == "server-reach":
        m = server.reach_module()
        a["reach"] = {"mode": "lab-network", "bundle": m.encode("https://headscale.lab.example", "0123456789abcdef0123456789abcd",
                                                                "home-lab") if m else ""}
        win.show_step("reach")
    elif sid.startswith("server-storage"):
        server.set_roles(a, ["storage"])
        disks = [d["path"] for d in server.data_disks(win.probe, a)]
        s.update(data_disks=disks[:2] if sid.endswith("raid") else disks[:1],
                 data_layout="raid1" if sid.endswith("raid") else "single")
        win.show_step("storage")
    elif sid.startswith("server-unlock"):
        os.environ["BROMIGOS_INSTALLER_TPM"] = "1" if sid.endswith("-tpm") else "0"
        s["unlock"] = "tpm" if sid.endswith("-tpm") else None
        win.show_step("unlock")
        os.environ.pop("BROMIGOS_INSTALLER_TPM", None)
    elif sid == "server-updates":
        win.show_step("updates")
    elif sid == "server-run-home":
        server.set_roles(a, ["home"])
        win.show_step("services")
    elif sid.startswith("server-run-media"):
        server.set_roles(a, ["media"])
        s["provision"], s["provision_edited"] = ["media-library", "jellyfin", "seerr", "sonarr", "radarr", "den-tv", "gluetun",
                                                 "sabnzbd", "prowlarr"], True
        s["setup"] = {"gluetun": {"provider": "pia", "kill_switch": True, "country": "Netherlands"},
                      "sabnzbd": {"port": 563, "ssl": True, "connections": 20}}
        win.show_step("services")
    elif sid == "server-run-lab":
        server.set_roles(a, ["lab", "games"])
        s.update(lab="new", lab_set=True)
        s["provision"], s["provision_edited"] = ["k3s", "argocd", "monitoring", "ollama", "models", "litellm", "pelican-panel",
                                                 "wings"], True
        win.show_step("services")
    elif sid == "server-run-games":
        server.set_roles(a, ["games"])
        win.show_step("services")
    elif sid == "server-summary":
        server.set_roles(a, ["lab", "games", "storage"])
        s.update(method="static", address="192.0.2.40", prefix="24", gateway="192.0.2.1", dns="192.0.2.1", unlock="tpm",
                 interface="enp3s0", lab="join", lab_set=True, lab_join={"pair": True})
        s["store"] = {"kind": "vault", "auth": "oidc", "address": "https://vault.lab.example:8200"}
        a["found_keys"], a["ssh_keys"] = [], [key]
        win.show_step("summary")
    spot = {"server-run-media": "jellyfin", "server-run-media-vpn": "setup:gluetun",
            "server-run-media-usenet": "setup:sabnzbd"}.get(sid)
    if spot:
        def to_spot():
            w = getattr(win, "_srv_spots", {}).get(spot)
            got = w.translate_coordinates(win.scroll.get_child(), 0, 0) if w else None
            if got and got[0] is not False:
                win.scroll.get_vadjustment().set_value(max(0, got[-1] - 70))
            return False
        GLib.timeout_add(300, to_spot)
    elif scroll_end:
        GLib.timeout_add(250, lambda: (win.scroll.get_vadjustment().set_value(win.scroll.get_vadjustment().get_upper()), False)[1])
