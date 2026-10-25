"""Account: who you are (your name, full name, pronouns, aliases, the forms of address
VECTOR uses), your picture, who can see them, and your Bromigos account (docs/settings.md,
"Account").

The Bromigos account is optional. Its row reads `bromigos whoami --json`; Sign in… runs
`bromigos login` (or `bromigos login --ssh`) in a terminal, the same sign-in as on the
command line, and the row checks again every few seconds until it's done. Sign out runs
`bromigos logout --json`.

Your profile goes through `bromigos profile … --json` (~/.config/bromigos/profile.toml); the
picture through `bromigos avatar` (~/.face, which the login screen shows). profile.toml is a
plain file: when it sits in your dotfiles (often public) the page says so, and points at the
private overlay (`bromigos private`), the encrypted place for what shouldn't be shared."""
import os

from gi.repository import Adw, Gdk, GLib, Gtk

from bromigos_settings import Entry, Page


def _esc(text):
    """Text for a row's title or subtitle (they take Pango markup): &, < and > escaped."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

PROFILE = ["bromigos", "profile"]
AVATAR = ["bromigos", "avatar"]
WHOAMI = ["bromigos", "whoami", "--json"]
HOW = {"device": "with a code on the website", "browser": "in the browser", "ssh": "with an SSH key",
       "token": "with a personal access token", "env": "with the token in BROMIGOS_TOKEN"}
FIELDS = [("name", "Name", "What you're usually called; VECTOR uses it when no form of address is set"),
          ("full_name", "Full name", "Your full name"),
          ("pronouns", "Pronouns", "e.g. he/him, she/her, they/them; VECTOR uses them")]


def _home(path):
    h = os.path.expanduser("~")
    return "~" + path[len(h):] if path and path.startswith(h + "/") else path


def _split(text):
    return [x.strip() for x in (text or "").split(",") if x.strip()]


class AccountPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.prof = None
        self.av = None
        self.page = ctx.page()
        self.page.set_reset(None, hint="Your name and picture are yours: there's no bromigOS default to go back to")
        self.share_rows = []
        self.watch = None
        self._you()
        self._picture()
        self._sharing()
        self._bromigos()
        self.refresh()

    # ------------------------------------------------------------------ building
    def _you(self):
        ctx = self.ctx
        g = ctx.group(self.page, "You", "Who you are, and what VECTOR calls you. Press Enter (or ✓) to save a "
                                        "field; an empty one is cleared.", key="you")
        self.entries = {}
        for key, title, hint in FIELDS:
            self.entries[key] = ctx.entry_row(
                g, title, hint=hint, key=key, on_apply=lambda text, k=key: self._set(k, text),
                advanced={"file": "~/.config/bromigos/profile.toml", "key": f"[you] {key}",
                          "runs": f"bromigos profile set {key} VALUE"})
        self.aliases = ctx.entry_row(
            g, "Aliases (commas between)", hint="Other names you go by: handles, callsigns", key="aliases",
            on_apply=self._set_aliases,
            advanced={"file": "~/.config/bromigos/profile.toml", "key": "[you] aliases",
                      "runs": "bromigos profile alias add|remove NAME"})
        self.address = ctx.entry_row(
            g, "Forms of address, preferred first", hint="What VECTOR calls you, most preferred first "
                                                         "(Captain, Sam); he mostly uses the first", key="address",
            on_apply=self._set_address,
            advanced={"file": "~/.config/bromigos/profile.toml", "key": "[you] address",
                      "runs": "bromigos profile address set A B …"})
        self.called = ctx.row(g, "VECTOR calls you", "", key="addressed",
                              hint="The form of address VECTOR uses now: the first of yours, else your name")

    def _picture(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Your picture", "Shown on the login screen. Any picture: it's cropped square "
                                                 "from its centre.", key="picture-group")
        self.avatar = Adw.Avatar(size=64, show_initials=True)
        ctx.hint(self.avatar, "Your picture (~/.face)")
        self.remove_button = ctx.button("Remove", self._clear, "No picture (the old one is kept as ~/.face.previous)")
        box = Gtk.Box(spacing=6)
        box.append(ctx.button("Choose…", self._choose, "Pick a picture file"))
        box.append(self.remove_button)
        self.pic_row = ctx.row(g, "Picture", "", key="picture", control=box,
                               hint="Your picture: ~/.face, and ~/.face.icon for the login screen",
                               advanced={"file": "~/.face", "note": "~/.face.icon links to it",
                                         "runs": "bromigos avatar set FILE"})
        self.pic_row.add_prefix(self.avatar)

    def _sharing(self):
        self.share_group = self.ctx.group(self.page, "Who can see it", "profile.toml is a plain file. Programs you "
                                                                       "run can read it, and so can anyone you share "
                                                                       "it with.", key="sharing")

    def _bromigos(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Bromigos account", "Optional. Sign in to use your Bromigos account on this "
                                                      "computer, such as adding its SSH keys to a new lab box.",
                      key="bromigos-group")
        self.signin_button = ctx.button("Sign in…", lambda: self._sign_in([]),
                                        "Runs bromigos login in a terminal: it shows a code to enter on the website",
                                        primary=True)
        self.ssh_button = ctx.button("Sign in with SSH key…", lambda: self._sign_in(["--ssh"]),
                                     "Runs bromigos login --ssh in a terminal: an SSH key on your account signs you "
                                     "in, with no browser")
        self.signout_button = ctx.button("Sign out", self._sign_out, "Forgets the sign-in on this computer "
                                         "(bromigos logout)", destructive=True)
        box = Adw.WrapBox(child_spacing=6, line_spacing=6, justify=Adw.JustifyMode.NONE)
        box.set_halign(Gtk.Align.END)
        for b in (self.signin_button, self.ssh_button, self.signout_button):
            box.append(b)
        self.bromigos_row = ctx.row(g, "Bromigos account", "Reading…", key="bromigos-account", control=box,
                                    hint="Your Bromigos account: who's signed in here, and how. The sign-in is kept "
                                         "in your keyring",
                                    advanced={"runs": "bromigos login · bromigos whoami · bromigos logout",
                                              "note": "bromigos account token says how to make a personal access token"})

    # ------------------------------------------------------------------ state
    def refresh(self):
        self.ctx.json(PROFILE + ["--json"], self._got_profile)
        self.ctx.json(AVATAR + ["--json"], self._got_avatar)
        self.ctx.json(WHOAMI, self._got_bromigos)

    def _got_bromigos(self, doc, err):
        if not doc or "signed_in" not in doc:
            self.bromigos_row.set_subtitle(_esc(f"bromigos whoami didn't answer: {err or 'no reply'}"))
            for b in (self.signin_button, self.ssh_button, self.signout_button):
                b.set_visible(False)
            return
        signed = bool(doc["signed_in"])
        if signed:
            who = doc.get("who") or "your account"
            if doc.get("email") and doc["email"] != who:
                who += f" ({doc['email']})"
            text = f"Signed in as {who}, {HOW.get(doc.get('how'), 'on this computer')}"
            if doc.get("via") == "env":
                text = "Using the token in BROMIGOS_TOKEN"
        else:
            text = "Not signed in. You don't need an account to use bromigOS"
        self.bromigos_row.set_subtitle(_esc(text))
        self.signin_button.set_visible(not signed)
        self.ssh_button.set_visible(not signed)
        self.signout_button.set_visible(signed and doc.get("via") != "env")
        if signed and self.watch:
            GLib.source_remove(self.watch)
            self.watch = None

    def _sign_in(self, extra):
        self.ctx.terminal(["bromigos", "login"] + extra)
        if self.watch:
            GLib.source_remove(self.watch)
        tries = [100]                                        # every 3 s for five minutes

        def check():
            tries[0] -= 1
            self.ctx.json(WHOAMI, self._got_bromigos)
            if tries[0] <= 0:
                self.watch = None
                return False
            return True
        self.watch = GLib.timeout_add_seconds(3, check)

    def _sign_out(self):
        self.ctx.confirm("Sign out of your Bromigos account?",
                         "This computer forgets the sign-in. Your account and its keys stay as they are.",
                         "Sign out", lambda: self.ctx.change(["bromigos", "logout", "--json"], "Signed out",
                                                             done=lambda d: self._got_bromigos(d, "")),
                         destructive=True)

    def _got_profile(self, doc, err):
        if not doc or "you" not in doc:
            self.called.set_subtitle(_esc(f"bromigos profile didn't answer: {err or 'no reply'}"))
            return
        self.prof = doc
        you = doc["you"]
        for k, _, _ in FIELDS:
            self.entries[k].set_quiet(you.get(k) or "")
        self.aliases.set_quiet(", ".join(you.get("aliases") or []))
        self.address.set_quiet(", ".join(you.get("address") or []))
        self.called.set_subtitle(_esc(doc.get("addressed_as") or "nothing yet: set a name"))
        self.avatar.set_text(you.get("full_name") or you.get("name") or "")

    def _got_avatar(self, doc, err):
        ctx = self.ctx
        if not doc or doc.get("ok") is False:
            self.pic_row.set_subtitle(_esc(f"bromigos avatar didn't answer: {(doc or {}).get('error') or err}"))
            return
        self.av = doc
        face = doc.get("face")
        self.pic_row.set_subtitle(_esc(
            f"{_home(face)} ({doc['size'][0]}×{doc['size'][1]})" if face and doc.get("size") else
            (_home(face) if face else "None: the login screen shows your initials")))
        tex = None
        if face:
            try:
                tex = Gdk.Texture.new_from_filename(face)
            except GLib.Error:
                tex = None
        self.avatar.set_custom_image(tex)
        self.remove_button.set_sensitive(bool(face))
        ctx.clear_group(self.share_group, self.share_rows)
        s = doc.get("sharing") or {}
        if s.get("warning"):
            self.share_rows.append(ctx.note(self.share_group, s["warning"] + ". Keep anything private in the "
                                            "private overlay instead.", "warn",
                                            hint="A git repository that's pushed (dotfiles often are, publicly) "
                                                 "carries profile.toml with it"))
        where = s.get("profile") or "~/.config/bromigos/profile.toml"
        sub = _home(where) + (f" → {_home(s['real_path'])}" if s.get("real_path") else "")
        if s.get("repo"):
            sub += f"\nin the git repository {s['repo']}" + (f" ({s['remote']})" if s.get("remote") else "") + \
                   (", ignored by git" if s.get("ignored") else ", tracked")
        elif not s.get("exists"):
            sub += " (none yet: saving a field makes it)"
        self.share_rows.append(ctx.row(
            self.share_group, "Your profile file", sub, key="profile-file",
            hint="Where your name and forms of address are kept",
            buttons=[("Open", lambda: ctx.open_file(where), "Opens profile.toml in your editor")]
            if s.get("exists") else [], advanced={"file": where}))
        o = s.get("overlay") or {}
        if o.get("encrypted"):
            osub = ("Encrypted in your dotfiles, decrypted at login" +
                    ("; its operator: section seeds your profile when there's none" if o.get("operator") else
                     "; it has no operator: section") if o.get("decrypted") else
                    "Encrypted, not decrypted on this machine (no age key here)")
            buttons = [("Edit…", lambda: ctx.terminal(["bromigos", "private", "edit"], hold=False),
                        "Opens the encrypted overlay with sops, in a terminal")]
        else:
            osub = "None here. Private values (your real name, your hosts) belong in an encrypted overlay " \
                   "(bromigos private), not in a file you might publish"
            buttons = []
        self.share_rows.append(ctx.row(
            self.share_group, "The private overlay", osub, key="overlay",
            hint="bromigos private: values kept encrypted (sops + age) in your dotfiles, decrypted at login",
            buttons=buttons, advanced={"file": o.get("file") or "~/.config/bromigos/private.sops.yaml",
                                       "key": "operator:", "runs": "bromigos private edit"}))

    # ------------------------------------------------------------------ changes
    def _you_now(self, key):
        return ((self.prof or {}).get("you") or {}).get(key)

    def _set(self, key, text):
        old = self._you_now(key) or ""
        if text.strip() == old:
            return
        title = dict((k, t) for k, t, _ in FIELDS)[key]
        self.ctx.change(PROFILE + ["set", key, text.strip(), "--json"], f"{title}: {text.strip() or 'cleared'}",
                        undo=PROFILE + ["set", key, old, "--json"], done=lambda d: self._got_profile(d, ""),
                        failed=lambda *_: self.refresh())

    def _set_aliases(self, text):
        old, new = self._you_now("aliases") or [], _split(text)
        gone, added = [a for a in old if a not in new], [a for a in new if a not in old]
        if not gone and not added:
            return

        def then(_d=None):
            if added:
                self.ctx.change(PROFILE + ["alias", "add", *added, "--json"], "Aliases saved",
                                undo=lambda: self._restore_aliases(old), done=lambda d: self._got_profile(d, ""))
            else:
                self.refresh()
        if gone:
            self.ctx.change(PROFILE + ["alias", "remove", *gone, "--json"], "Aliases saved",
                            undo=lambda: self._restore_aliases(old), done=then)
        else:
            then()

    def _restore_aliases(self, old):
        self.aliases.set_quiet(", ".join(old))
        self._set_aliases(", ".join(old))

    def _set_address(self, text):
        old, new = self._you_now("address") or [], _split(text)
        if old == new:
            return
        self.ctx.change(PROFILE + ["address", "set", *new, "--json"], "Forms of address saved",
                        undo=PROFILE + ["address", "set", *old, "--json"], done=lambda d: self._got_profile(d, ""))

    def _choose(self):
        self.ctx.choose_file("Choose your picture", self._set_picture,
                             filters=[("Pictures", ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.bmp"])])

    def _undo_picture(self, had):
        prev = os.path.expanduser("~/.face.previous")
        return (AVATAR + ["set", prev, "--json"]) if had else (AVATAR + ["clear", "--json"])

    def _set_picture(self, path):
        had = bool((self.av or {}).get("face"))
        self.ctx.change(AVATAR + ["set", path, "--json"], "Picture set", undo=self._undo_picture(had),
                        done=lambda d: self._got_avatar(d, ""))

    def _clear(self):
        if not (self.av or {}).get("face"):
            self.ctx.toast("No picture to remove")
            return
        self.ctx.change(AVATAR + ["clear", "--json"], "Picture removed",
                        undo=AVATAR + ["set", os.path.expanduser("~/.face.previous"), "--json"],
                        done=lambda d: self._got_avatar(d, ""))


def build(ctx):
    p = AccountPage(ctx)
    p.page._account = p
    return p.page


def refresh(widget):
    widget._account.refresh()


PAGE = Page(
    id="account", title="Account", group="personal", order=10, build=build, refresh=refresh, docs="settings.md#account",
    icon="avatar-default-symbolic system-users-symbolic", summary="your name, picture, privacy, sign-in",
    intro="Who you are and what VECTOR calls you, your picture, who can see them, and your Bromigos account.",
    keywords=["profile", "user", "me", "name", "avatar", "picture", "face", "privacy", "pronouns", "sign in", "login"],
    entries=[Entry(k, t, [k.replace("_", " ")], "You") for k, t, _ in FIELDS] + [
        Entry("aliases", "Aliases", ["handles", "callsigns", "nicknames"], "You"),
        Entry("address", "Forms of address", ["what vector calls me", "title", "captain"], "You"),
        Entry("addressed", "What VECTOR calls you", ["address"], "You"),
        Entry("picture", "Your picture (avatar)", ["photo", "face", "login picture"], "Your picture"),
        Entry("profile-file", "Your profile file", ["profile.toml", "dotfiles", "shared"], "Who can see it"),
        Entry("overlay", "The private overlay", ["private", "sops", "encrypted", "secrets"], "Who can see it"),
        Entry("bromigos-account", "Bromigos account", ["sign in", "login", "log in", "sign out", "ssh key", "token"],
              "Bromigos account"),
    ])
