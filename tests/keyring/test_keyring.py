"""The keyring check and the login's unlock (lib/bromigos_keyring.py, `bromigos keyring`).

Everything runs on copies: PAM files in a temporary root, kwalletrc in a temporary HOME, and
a stand-in session bus. Nothing reads or changes this machine's /etc, starts a keyring or
asks for sudo.

    PYTHONPATH=lib python -m unittest discover -s tests/keyring
"""
import io
import os
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import bromigos_keyring as K

# Arch's /etc/pam.d/login (util-linux), sddm's and passwd's, as shipped
LOGIN = """#%PAM-1.0

auth       requisite    pam_nologin.so
auth       include      system-local-login
account    include      system-local-login
session    include      system-local-login
password   include      system-local-login
"""
SDDM = """#%PAM-1.0

auth        include     system-login
-auth       optional    pam_gnome_keyring.so
-auth       optional    pam_kwallet5.so

account     include     system-login

password    include     system-login
-password   optional    pam_gnome_keyring.so    use_authtok

session     optional    pam_keyinit.so          force revoke
session     include     system-login
-session    optional    pam_gnome_keyring.so    auto_start
-session    optional    pam_kwallet5.so         auto_start
"""
PASSWD = "#%PAM-1.0\nauth\t\tinclude\t\tsystem-auth\naccount\t\tinclude\t\tsystem-auth\npassword\tinclude\t\tsystem-auth\n"
# the operator's way: gnome-keyring's two lines added at the end by hand
BY_HAND = LOGIN + "-auth optional pam_gnome_keyring.so\n-session optional pam_gnome_keyring.so auto_start\n"

AUTH = "-auth      optional     pam_oo7.so"
SESSION = "-session   optional     pam_oo7.so auto_start"
PASSWORD = "-password  optional     pam_oo7.so"


class Root(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix="bromigos-keyring-test-")
        self.addCleanup(t.cleanup)
        self.root = t.name
        self.home = os.path.join(self.root, "home")
        os.makedirs(os.path.join(self.root, "etc/pam.d"))
        os.makedirs(os.path.join(self.root, "usr/lib/security"))
        os.makedirs(os.path.join(self.root, "usr/bin"))
        os.makedirs(self.home)
        env = mock.patch.dict(os.environ, {"HOME": self.home, "XDG_CONFIG_HOME": os.path.join(self.home, ".config")})
        env.start()
        self.addCleanup(env.stop)

    def pam(self, name, text=None):
        path = os.path.join(self.root, "etc/pam.d", name)
        if text is not None:
            with open(path, "w") as f:
                f.write(text)
        with open(path) as f:
            return f.read()

    def oo7(self):
        open(os.path.join(self.root, "usr/lib/security/pam_oo7.so"), "w").close()

    def kwallet(self):
        open(os.path.join(self.root, "usr/bin/ksecretd"), "w").close()


class PamEdit(Root):
    def test_arch_login_gets_both_lines_after_its_own(self):
        new = K.pam_edit(LOGIN, K.WANT["login"])
        lines = new.splitlines()
        self.assertEqual(lines[lines.index("auth       include      system-local-login") + 1], AUTH)
        self.assertEqual(lines[lines.index("session    include      system-local-login") + 1], SESSION)
        self.assertEqual([x for x in lines if x not in (AUTH, SESSION)], LOGIN.splitlines())
        self.assertTrue(new.endswith("\n"))
        K._check_edit(LOGIN, new)                                   # passes its own check

    def test_lines_added_by_hand_stay_and_ours_follow_them(self):
        new = K.pam_edit(BY_HAND, K.WANT["login"])
        lines = new.splitlines()
        self.assertEqual(lines[lines.index("-auth optional pam_gnome_keyring.so") + 1], AUTH)
        self.assertEqual(lines[lines.index("-session optional pam_gnome_keyring.so auto_start") + 1], SESSION)
        self.assertIn("-auth optional pam_gnome_keyring.so", lines)

    def test_a_line_already_there_in_any_form_is_enough(self):
        for text in (LOGIN + "auth optional pam_oo7.so\nsession optional pam_oo7.so auto_start\n",
                     LOGIN + "-auth\toptional\t/usr/lib/security/pam_oo7.so\n-session [success=ok default=ignore] pam_oo7.so\n"):
            self.assertEqual(K.pam_edit(text, K.WANT["login"]), text)

    def test_a_comment_or_another_kind_doesnt_count(self):
        text = LOGIN + "# session optional pam_oo7.so auto_start\naccount optional pam_oo7.so\n"
        self.assertFalse(K.pam_has(text, "session"))
        self.assertFalse(K.pam_has(text, "auth"))
        self.assertIn(SESSION, K.pam_edit(text, K.WANT["login"]))

    def test_tabs_and_bracket_controls_are_read(self):
        self.assertEqual(K._fields("password\tinclude\t\tsystem-auth"), ("password", "include", "system-auth", []))
        self.assertEqual(K._fields("-session [success=1 default=ignore] pam_oo7.so auto_start"),
                         ("session", "[success=1 default=ignore]", "pam_oo7.so", ["auto_start"]))
        self.assertIsNone(K._fields("#%PAM-1.0"))
        self.assertIsNone(K._fields("   "))

    def test_lines_this_parser_doesnt_read_are_kept_as_they_are(self):
        text = "#%PAM-1.0\n@include common-auth\n" + LOGIN.split("\n", 1)[1]
        new = K.pam_edit(text, K.WANT["login"])
        K._check_edit(text, new)
        self.assertIn("@include common-auth", new)

    def test_no_line_of_a_kind_to_follow_is_refused(self):
        with self.assertRaises(K.PamError):
            K.pam_edit("#%PAM-1.0\nauth include system-auth\n", K.WANT["login"])

    def test_the_check_refuses_an_edit_that_changes_other_lines(self):
        with self.assertRaises(K.PamError):
            K._check_edit(LOGIN, LOGIN.replace("requisite", "optional") + AUTH + "\n")
        with self.assertRaises(K.PamError):
            K._check_edit(LOGIN, LOGIN.replace("auth       include      system-local-login\n", ""))


class PamPlan(Root):
    def test_plan_and_apply_on_a_copy_keep_owner_mode_and_leave_nothing_behind(self):
        self.pam("login", BY_HAND)
        self.pam("sddm", SDDM)
        self.pam("passwd", PASSWD)
        os.chmod(os.path.join(self.root, "etc/pam.d/login"), 0o640)
        plan = K.pam_plan(self.root)
        self.assertEqual({p["name"]: p["missing"] for p in plan},
                         {"login": ["auth", "session"], "sddm": ["auth", "session"], "passwd": ["password"]})
        written = K.pam_apply(plan)
        self.assertEqual(len(written), 3)
        self.assertIn(AUTH, self.pam("login"))
        self.assertIn(SESSION, self.pam("sddm"))
        self.assertIn(PASSWORD, self.pam("passwd"))
        self.assertIn("-session    optional    pam_kwallet5.so         auto_start", self.pam("sddm"))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.root, "etc/pam.d/login")).st_mode), 0o640)
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "etc/pam.d"))), ["login", "passwd", "sddm"])
        # again: nothing to do, nothing written
        self.assertEqual(K.pam_apply(K.pam_plan(self.root)), [])
        self.assertTrue(all(not p["missing"] for p in K.pam_plan(self.root)))

    def test_only_the_files_that_exist_but_login_is_expected(self):
        self.pam("login", LOGIN)
        plan = {p["name"]: p for p in K.pam_plan(self.root)}
        self.assertTrue(plan["login"]["new"])
        self.assertFalse(plan["sddm"]["exists"] or plan["sddm"]["new"] or plan["sddm"]["note"])
        os.unlink(os.path.join(self.root, "etc/pam.d/login"))
        self.assertIn("isn't there", {p["name"]: p for p in K.pam_plan(self.root)}["login"]["note"])

    def test_a_file_changed_meanwhile_is_left_alone(self):
        self.pam("login", LOGIN)
        plan = K.pam_plan(self.root)
        self.pam("login", LOGIN + "# changed by someone else\n")
        with self.assertRaises(K.PamError):
            K.pam_apply(plan)
        self.assertNotIn("pam_oo7", self.pam("login"))

    def test_a_file_it_cant_place_lines_in_is_noted_not_written(self):
        self.pam("login", "#%PAM-1.0\nauth include system-auth\n")
        item = {p["name"]: p for p in K.pam_plan(self.root)}["login"]
        self.assertIsNone(item["new"])
        self.assertIn("no session lines", item["note"])
        out = []
        self.assertEqual(K.pam_step(self.root, say=out.append), 0)
        self.assertNotIn("pam_oo7", self.pam("login"))
        self.assertTrue(any("left alone" in line for line in out))


class KWallet(Root):
    def rc(self, text=None):
        path = os.path.join(self.home, ".config/kwalletrc")
        if text is not None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
        with open(path) as f:
            return f.read()

    def test_off_in_every_shape_of_file_and_the_rest_kept(self):
        self.assertIsNone(K.kwallet_api())
        self.assertTrue(K.kwallet_api_off())
        self.assertEqual(self.rc(), "[org.freedesktop.secrets]\napiEnabled=false\n")
        self.assertFalse(K.kwallet_api_off())                        # already off
        self.rc("[Wallet]\nFirst Use=false\n")
        K.kwallet_api_off()
        self.assertEqual(self.rc(), "[Wallet]\nFirst Use=false\n\n[org.freedesktop.secrets]\napiEnabled=false\n")
        self.rc("[org.freedesktop.secrets]\napiEnabled=true\n\n[Wallet]\nEnabled=true\n")
        self.assertTrue(K.kwallet_api())
        K.kwallet_api_off()
        self.assertEqual(self.rc(), "[org.freedesktop.secrets]\napiEnabled=false\n\n[Wallet]\nEnabled=true\n")
        self.assertFalse(K.kwallet_api())


class FakeBus:
    def __init__(self, owner=None, activatable=False, locked=None, broken=None):
        self._owner, self._activatable, self._locked, self.broken = owner, activatable, locked, broken
        self.asked = []

    def has_owner(self):
        if self.broken:
            raise OSError(self.broken)
        return self._owner is not None

    def activatable(self):
        return self._activatable

    def owner(self):
        return self._owner

    def locked(self):
        if self._locked is None:
            raise OSError("no default collection")
        return self._locked


class Service(unittest.TestCase):
    def test_what_the_bus_says(self):
        s = K.service(FakeBus(owner="oo7-daemon", activatable=True, locked=False))
        self.assertEqual((s["bus"], s["running"], s["provider"], s["locked"]), (True, True, "oo7", False))
        self.assertEqual(K.service(FakeBus(owner="gnome-keyring-d", locked=True))["provider"], "gnome-keyring")
        self.assertEqual(K.service(FakeBus(owner="ksecretd"))["provider"], "KWallet")
        self.assertIsNone(K.service(FakeBus(owner="oo7-daemon"))["locked"])     # no default keyring yet
        s = K.service(FakeBus(broken="Failed to connect to user scope bus"))
        self.assertFalse(s["bus"])
        self.assertIn("Failed to connect", s["error"])

    def test_ready_only_when_a_sign_in_can_be_kept(self):
        up = {"bus": True, "running": True, "activatable": True, "provider": "oo7", "locked": False, "error": ""}
        self.assertIsNone(K.ready(up, True, prompt=False, credential=False))
        self.assertIn("libsecret", K.ready(up, False))
        self.assertEqual(K.ready(dict(up, bus=False), True), K.NO_BUS)
        none = dict(up, running=False, activatable=False, locked=None)
        self.assertEqual(K.ready(none, True, prompt=True), K.NO_KEYRING)
        self.assertIn("sudo pacman -S bromigos/oo7", K.NO_KEYRING)
        locked = dict(up, locked=True)
        self.assertEqual(K.ready(locked, True, prompt=False, credential=False), K.LOCKED)
        self.assertIsNone(K.ready(locked, True, prompt=True))         # the password window can show
        self.assertIsNone(K.ready(locked, True, prompt=False, credential=True))
        idle = dict(up, running=False, locked=None)                   # starts on first use
        self.assertEqual(K.ready(idle, True, prompt=False, credential=False), K.LOCKED)
        self.assertIsNone(K.ready(idle, True, prompt=True))

    def test_a_prompt_can_show_where_the_session_has_a_desktop(self):
        self.assertTrue(K.can_prompt({"WAYLAND_DISPLAY": "wayland-1"}, ""))
        self.assertTrue(K.can_prompt({}, "HOME=/home/a\nWAYLAND_DISPLAY=wayland-1\n"))
        self.assertFalse(K.can_prompt({}, "HOME=/home/a\n"))


class Explain(unittest.TestCase):
    def test_the_operators_error_and_its_kin_are_plain_words(self):
        for raw in ("g-dbus-error-quark: The name is not activatable (2)",
                    "g-dbus-error-quark: GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: The name is not activatable (2)",
                    "secret-tool: The name org.freedesktop.secrets was not provided by any .service files"):
            self.assertEqual(K.explain(RuntimeError(raw)), K.NO_KEYRING)
        self.assertEqual(K.explain("Cannot autolaunch D-Bus without X11 $DISPLAY"), K.NO_BUS)
        self.assertIn("window was closed", K.explain("Prompt dismissed"))
        self.assertEqual(K.explain("Cannot create an item in a locked collection"), K.LOCKED)
        # oo7 asked for the password where no window could show it (a client outside the desktop)
        self.assertEqual(K.explain("secret-tool: org.freedesktop.DBus.Error.Failed: CLI prompter failed: "
                                   "org.freedesktop.DBus.Error.NameHasNoOwner: Destination does not exist"), K.LOCKED)
        self.assertIn("didn't answer", K.explain("timed out"))

    def test_anything_else_keeps_its_reason_without_the_d_bus_names(self):
        said = K.explain(RuntimeError("g-dbus-error-quark: GDBus.Error:org.freedesktop.Secret.Error.NoSuchObject: "
                                      "The collection is gone (19)"))
        self.assertEqual(said, "The keyring couldn't store it (The collection is gone). bromigos keyring status "
                               "checks the keyring.")
        self.assertNotIn("quark", said)

    def test_a_glib_error_with_a_message_attribute(self):
        e = RuntimeError("x")
        e.message = "GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: The name is not activatable"
        self.assertEqual(K.explain(e), K.NO_KEYRING)


class Setup(Root):
    def test_setup_on_a_copy_adds_the_lines_and_turns_kwallets_off_once(self):
        self.oo7()
        self.kwallet()
        self.pam("login", BY_HAND)
        self.pam("sddm", SDDM)
        out = []
        self.assertEqual(K.setup(self.root, say=out.append, home=self.home), 0)
        self.assertIn(AUTH, self.pam("login"))
        self.assertIn("-auth optional pam_gnome_keyring.so", self.pam("login"))   # left alone
        self.assertFalse(K.kwallet_api(self.home))
        out.clear()
        before = self.pam("login"), self.pam("sddm")
        self.assertEqual(K.setup(self.root, say=out.append, home=self.home), 0)
        self.assertEqual((self.pam("login"), self.pam("sddm")), before)
        self.assertIn("PAM: every login already unlocks the keyring.", out)

    def test_dry_run_changes_nothing(self):
        self.oo7()
        self.kwallet()
        self.pam("login", LOGIN)
        out = []
        self.assertEqual(K.setup(self.root, dry=True, say=out.append, home=self.home), 0)
        self.assertEqual(self.pam("login"), LOGIN)
        self.assertIsNone(K.kwallet_api(self.home))
        self.assertTrue(any("would add" in line for line in out))

    def test_before_oo7_is_installed_it_waits(self):
        self.pam("login", LOGIN)
        self.assertEqual(K.setup(self.root, say=[].append, home=self.home), 75)
        self.assertEqual(self.pam("login"), LOGIN)

    def test_on_the_real_root_it_asks_sudo_and_waits_when_it_cant(self):
        plan = [{"name": "login", "path": "/etc/pam.d/login", "exists": True, "missing": ["auth"], "new": "x",
                 "text": LOGIN, "note": ""}]
        with mock.patch.object(K, "module_installed", return_value=True), \
                mock.patch.object(K, "pam_plan", return_value=plan), \
                mock.patch.object(K, "kwallet_installed", return_value=False), \
                mock.patch.object(K.os, "geteuid", return_value=1000):
            refused = mock.Mock(return_value=mock.Mock(returncode=1))
            self.assertEqual(K.setup("/", say=[].append, interactive=False, run=refused), 75)
            self.assertEqual(refused.call_args[0][0][:2], ["sudo", "-n"])   # no terminal: never asks
            ok = mock.Mock(return_value=mock.Mock(returncode=0))
            self.assertEqual(K.setup("/", say=[].append, interactive=True, run=ok), 0)
            argv = ok.call_args[0][0]
            self.assertEqual(argv[0], "sudo")
            self.assertEqual(argv[-1], "pam")
            self.assertEqual(K.setup("/", say=[].append, interactive=True, run=refused), 75)

    def test_status_names_each_problem_with_its_fix(self):
        self.oo7()
        self.kwallet()
        self.pam("login", LOGIN)
        up = {"bus": True, "running": True, "activatable": True, "provider": "gnome-keyring", "locked": False,
              "error": ""}
        st = K.status(self.root, self.home, svc=up)
        self.assertFalse(st["ok"])
        text = "\n".join(st["problems"])
        self.assertIn("gnome-keyring answers for the keyring, not oo7", text)
        self.assertIn("doesn't unlock the keyring", text)
        self.assertIn("KWallet's own Secret Service is on", text)
        K.setup(self.root, say=[].append, home=self.home)
        st = K.status(self.root, self.home, svc=dict(up, provider="oo7"))
        self.assertTrue(st["ok"], st["problems"])
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            K._say_status(st)
        self.assertIn("All set", out.getvalue())


class Migration(unittest.TestCase):
    """migrations/20261026120000-keyring-unlock.sh with stand-in pacman and bromigos commands."""
    SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "migrations", "20261026120000-keyring-unlock.sh")

    def run_it(self, desktop, setup_rc):
        with tempfile.TemporaryDirectory() as d:
            for name, body in (("pacman", f"exit {0 if desktop else 1}"),
                               ("bromigos", f'echo "ran: $*"; exit {setup_rc}')):
                path = os.path.join(d, name)
                with open(path, "w") as f:
                    f.write(f"#!/bin/sh\n{body}\n")
                os.chmod(path, 0o755)
            r = subprocess.run(["bash", self.SCRIPT], capture_output=True, text=True,
                               env={"PATH": d + ":/usr/bin:/bin", "HOME": d})
        return r.returncode, r.stdout

    def test_it_runs_setup_and_passes_on_its_answer(self):
        code, out = self.run_it(True, 0)
        self.assertEqual(code, 0)
        self.assertIn("ran: keyring setup", out)
        self.assertIn("sign out and in again", out)
        self.assertEqual(self.run_it(True, 75)[0], 75)               # not yet: the next update tries again

    def test_without_the_desktop_it_is_done_and_changes_nothing(self):
        code, out = self.run_it(False, 1)
        self.assertEqual(code, 0)
        self.assertNotIn("ran:", out)


if __name__ == "__main__":
    unittest.main()
