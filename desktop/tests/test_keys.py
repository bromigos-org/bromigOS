"""bromigos keys (lib/bromigos_keys.py, lib/bromigos_keycapture.py): key combinations, the
blocks it writes into a user's hyprland.lua, clash detection, the changes (bind with swap
or replace, unbind, reset), the lockout guard, the safe save (and putting every file back
when Hyprland doesn't take it), the capture window's keys and its submap, and the names
the SHORTCUTS panel gives your shortcuts. Hyprland is a stand-in here: the config is run
by lib/bromigos_keys_eval.lua, which needs `lua`.

    PYTHONPATH=lib python -m unittest discover -s tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DESKTOP = os.path.dirname(HERE)
REPO = os.path.dirname(DESKTOP)
sys.path.insert(0, os.path.join(DESKTOP, "lib"))
sys.path.insert(0, os.path.join(REPO, "widgets"))

import bromigos_hypr as H  # noqa: E402
import bromigos_keys as BK  # noqa: E402
import bromigos_keycapture as C  # noqa: E402

TEMPLATE = os.path.join(DESKTOP, "user", "hypr", "hyprland.lua")


def user_config():
    """The thin hyprland.lua a new user starts from, loading the defaults from this checkout."""
    with open(TEMPLATE) as f:
        text = f.read()
    return text.replace('dofile("/usr/share/bromigos/default/hypr/hyprland.lua")',
                        'dofile(os.getenv("BROMIGOS_SHARE_DIR") .. "/default/hypr/hyprland.lua")')


class Sandbox:
    """A HOME with the template config, the defaults from this checkout, maybe web apps."""

    def __init__(self, extra_lua="", webapps=None):
        self.tmp = tempfile.mkdtemp(prefix="bromigos-keys-")
        share = os.path.join(self.tmp, "share", "default")
        os.makedirs(share)
        os.symlink(os.path.join(DESKTOP, "hypr"), os.path.join(share, "hypr"))
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(os.path.join(self.config, "hypr"))
        os.makedirs(os.path.join(self.config, "bromigos"))
        self.lua = os.path.join(self.config, "hypr", "hyprland.lua")
        self.original = user_config() + extra_lua
        with open(self.lua, "w") as f:
            f.write(self.original)
        if webapps is not None:
            with open(os.path.join(self.config, "bromigos", "webapps.toml"), "w") as f:
                f.write(webapps)
        self.env = {"HOME": self.tmp, "PATH": os.environ.get("PATH", "/usr/bin"),
                    "XDG_STATE_HOME": os.path.join(self.tmp, "state"), "XDG_CONFIG_HOME": self.config,
                    "BROMIGOS_SHARE_DIR": os.path.join(self.tmp, "share")}
        self.paths = BK.Paths(config=self.config)

    def state(self, hypr=None):
        return BK.State.read(self.paths, hypr, env=self.env)

    def read(self, name="lua"):
        return H.read_file(getattr(self.paths, name) if name != "lua" else self.lua)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def effective(state):
    """{combo text: [(kind, payload)]} the config makes Hyprland bind (defaults not
    turned off, then the rest), from a freshly read state."""
    out = {}
    for e in state.defaults:
        if e.keys in state.unbind or e.mouse or e.release:
            continue
        out.setdefault(str(e.combo()), []).append((e.kind, e.payload))
    for e in state.user:
        if e.release:
            continue
        out.setdefault(str(e.combo()), []).append((e.kind, e.payload))
    return out


class FakeHypr:
    """Hyprland as far as commit() and the capture's submap see it. Its bind table is
    what the config file says at the last reload."""

    def __init__(self, box, running=True, verify_ok=True, errors_after=None, drop=False):
        self.box, self._running = box, running
        self.verify_ok, self.errors_after, self.drop = verify_ok, errors_after, drop
        self.events = []
        self.disable_autoreload = False
        self.errors = []
        self.submap = "default"
        self.submaps = {"bromigos-capture"}
        self.table = self._load()

    env = {"HYPRLAND_INSTANCE_SIGNATURE": "fake"}

    def _load(self):
        st = BK.State.read(self.box.paths, None, live=False, env=self.box.env)
        out = []
        for c, acts in effective(st).items():
            for kind, payload in acts:
                out.append(BK.Live(BK.Combo.parse(c), kind, payload, False))
        return out

    def running(self):
        return self._running

    def autoreload_off(self):
        return self.disable_autoreload

    def set_autoreload_off(self, off):
        self.events.append(("autoreload_off", off))
        self.disable_autoreload = off
        return "ok"

    def config_errors(self):
        return list(self.errors)

    def verify(self, path):
        self.events.append(("verify",))
        if not self.verify_ok:
            return False, "error: something broke\n==== config error"
        defaults, user, plain, unbind, error = BK.evaluate(path, self.box.env)
        return error is None, error or "config ok"

    def reload(self):
        self.events.append(("reload",))
        self.disable_autoreload = False         # the config's value comes back with a reload
        if self.errors_after:
            self.errors = list(self.errors_after)
            self.errors_after = None
        self.table = [] if self.drop else self._load()
        self.drop = False
        return "ok"

    def binds(self):
        return list(self.table)

    # the capture's submap
    def run(self, *args):
        self.events.append(("run",) + args)
        if args[0] == "binds":
            return json.dumps([{"submap": s, "key": "ESCAPE"} for s in self.submaps])
        if args[0] == "submap":
            return self.submap
        if args[0] == "dispatch":
            name = args[1].split('"')[1]
            if name == "reset":
                self.submap = "default"
                return "ok"
            if name not in self.submaps:
                return "error: Cannot set submap"
            self.submap = name
            return "ok"
        return ""

    def eval(self, code):
        self.events.append(("eval", code))
        if code.startswith("hl.define_submap"):
            self.submaps.add("bromigos-capture")
        return "ok"


def logged_writes(fake):
    """Record each file write in the fake's event list (to check the order)."""
    real = H.write_file

    def write(path, text):
        fake.events.append(("write", os.path.basename(path)))
        return real(path, text)
    H.write_file = write
    return real


@unittest.skipUnless(shutil.which("lua"), "needs lua")
class Base(unittest.TestCase):
    extra_lua = ""
    webapps = None

    def setUp(self):
        self.box = Sandbox(self.extra_lua, self.webapps)

    def tearDown(self):
        self.box.close()


# ------------------------------------------------------------------ combos
class ComboTest(unittest.TestCase):
    def test_parse_and_show(self):
        c = BK.Combo.parse("super+shift+w")
        self.assertEqual(str(c), "SUPER + SHIFT + W")
        self.assertEqual(c.display(), "SUPER + SHIFT + W")
        self.assertEqual(c.modmask, 64 + 1)
        self.assertEqual(str(BK.Combo.parse("Shift + Win + Return")), "SUPER + SHIFT + RETURN")
        self.assertEqual(BK.Combo.parse("ALT + RETURN").display(), "ALT + ENTER")   # as SHORTCUTS shows it
        self.assertEqual(str(BK.Combo.parse("ALT + ENTER")), "ALT + RETURN")        # and back
        self.assertEqual(str(BK.Combo.parse("control + alt + code:191")), "ALT + CTRL + code:191")
        self.assertEqual(str(BK.Combo.parse("SUPER + ,")), "SUPER + COMMA")             # SHORTCUTS' ","
        self.assertEqual(BK.Combo.parse("SUPER + COMMA").display(), "SUPER + ,")

    def test_same(self):
        self.assertTrue(BK.Combo.parse("SUPER + W").same(BK.Combo.parse("super + w")))
        self.assertTrue(BK.Combo.parse("ALT + b").same(BK.Combo.parse("ALT + B")))
        self.assertFalse(BK.Combo.parse("SUPER + W").same(BK.Combo.parse("SUPER + SHIFT + W")))
        # a code:N bind is the key pressed with that keycode
        self.assertTrue(BK.Combo.parse("code:191").same(BK.Combo.parse("F13", keycode=191)))
        self.assertFalse(BK.Combo.parse("code:191").same(BK.Combo.parse("F14", keycode=192)))

    def test_bad(self):
        bad = ["", "SUPER +", "SUPER + + W", "HYPERSPACE + W"]
        if BK._xkb() is not None:            # naming a key that doesn't exist needs xkbcommon's names
            bad.append("SUPER + NOTAKEY")
        for keys in bad:
            with self.assertRaises(BK.BadKeys, msg=keys):
                BK.Combo.parse(keys)

    def test_typing_keys(self):
        self.assertTrue(BK.typing_key(BK.Combo.parse("A")))
        self.assertTrue(BK.typing_key(BK.Combo.parse("SHIFT + A")))
        self.assertTrue(BK.typing_key(BK.Combo.parse("SPACE")))
        self.assertFalse(BK.typing_key(BK.Combo.parse("SUPER + A")))
        self.assertFalse(BK.typing_key(BK.Combo.parse("F13")))
        self.assertFalse(BK.typing_key(BK.Combo.parse("XF86AudioMute")))

    def test_lua_strings(self):
        for s in ('plain', 'say "hi"', "back\\slash", "two\nlines", "tab\there", "ünïcødé ✓", "$HOME ~/x"):
            q = BK.lua_str(s)
            self.assertNotIn("\n", q)
            self.assertEqual(BK.lua_unquote(q), s)
        # what string.format("%q") writes (keys.lua's descriptions)
        self.assertEqual(BK.lua_unquote('"a \\"b\\" c\\\\d\\\ne"'), 'a "b" c\\d\ne')


# ------------------------------------------------------------------ the config, read
class TitleThemeTest(unittest.TestCase):
    def test_one_quoted_string_per_line(self):
        # rofi reads a string to the line's last quote: two on a line made the menu's title
        # `BROMIGOS"; … font: "Geist Mono Bold 12`
        for line in H.title_theme("BROMIGOS", width=820, lines=12).splitlines():
            self.assertLessEqual(line.count('"'), 2, line)

    def test_the_title_takes_the_space_left(self):
        # a fixed-height title (expand: false) made rofi skip the header's layout and draw
        # the title under the input, in every titled menu (rofi 1.7.9 and 2.0.0)
        import re
        themes = {"title_theme": H.title_theme("BROMIGOS", width=820, lines=12)}
        for name in ("power-menu", "quick-note"):
            with open(os.path.join(DESKTOP, "rofi", "scripts", name)) as f:
                themes[name] = re.search(r"^theme='(.*?)^'", f.read(), re.S | re.M).group(1)
        for name, theme in themes.items():
            blocks = re.findall(r"textbox-title\s*\{([^}]*)\}", theme)
            self.assertTrue(blocks, name)
            for block in blocks:
                self.assertNotRegex(block, r"expand\s*:\s*false", name)

    @unittest.skipUnless(shutil.which("rofi"), "no rofi")
    def test_rofi_reads_the_title(self):
        import subprocess
        out = subprocess.run(["rofi", "-theme-str", H.title_theme("BROMIGOS"), "-dump-theme"],
                             capture_output=True, text=True, timeout=20,
                             env=dict(os.environ, HOME=tempfile.gettempdir())).stdout
        block = out[out.index("textbox-title {"):]
        block = block[:block.index("}")]
        self.assertIn('"BROMIGOS";', block)
        self.assertIn('font:', block)
        self.assertNotIn('"BROMIGOS"; text-color', block)
        self.assertNotRegex(block, r"expand:\s*false")


class ReadTest(Base):
    def test_defaults_and_unbind(self):
        st = self.box.state()
        self.assertIsNone(st.error)
        keys, group = st.default_group("SUPER + SPACE")
        self.assertEqual(keys, "SUPER + SPACE")
        self.assertEqual([(e.kind, e.payload) for e in group], [("exec", "bromigos-menu")])
        self.assertEqual(st.user, [])
        self.assertEqual(st.unbind, [])
        # any spelling finds the default
        self.assertEqual(st.default_group("super + space")[0], "SUPER + SPACE")


class ReadUserTest(Base):
    extra_lua = 'K.exec("ALT + W", "firefox")\nhl.bind("SUPER + CTRL + Z", hl.dsp.exec_cmd("zed"))\n'

    def test_user_binds_and_plain(self):
        st = self.box.state()
        self.assertEqual([(e.keys, e.payload) for e in st.user], [("ALT + W", "firefox")])
        self.assertEqual(st.plain, ["SUPER + CTRL + Z"])
        owners = BK.Plan(st).owners(BK.Combo.parse("ALT + W"))
        self.assertEqual([(o.source, o.what) for o in owners], [("config", "firefox")])
        self.assertEqual(BK.Plan(st).owners(BK.Combo.parse("SUPER + CTRL + Z"))[0].source, "config")


# ------------------------------------------------------------------ blocks
class BlockTest(Base):
    def test_render_places_and_removes_exactly(self):
        st = self.box.state()
        plan = BK.Plan(st)
        plan.bind(BK.default_target(st, "SUPER + SPACE"), BK.Combo.parse("SUPER + CTRL + M"), resolution="replace")
        lua = BK.render(self.box.original, plan.record)
        before, dofile, after = lua.partition('dofile(os.getenv("BROMIGOS_SHARE_DIR")')
        self.assertIn("-- >>> bromigos keys-unbind", before)
        self.assertNotIn("-- >>> bromigos keys\n", before)
        self.assertIn('table.insert(bromigos.unbind, keys)', before)
        self.assertIn('"SUPER + SPACE"', before.split("-- >>> bromigos keys-unbind")[1])
        self.assertTrue(after.rstrip().endswith("-- <<< bromigos keys"))
        self.assertIn('K.exec("SUPER + CTRL + M", "bromigos-menu")', after)
        # rendering again changes nothing; an empty record takes both blocks out, exactly
        self.assertEqual(BK.render(lua, plan.record), lua)
        self.assertEqual(BK.render(lua, BK.Record()), self.box.original)
        # nothing outside the blocks moved
        stripped = BK.drop_block(BK.drop_block(lua, BK.BLOCK), BK.UNBIND_BLOCK)
        self.assertEqual(stripped, self.box.original)

    def test_rendered_config_binds_what_it_says(self):
        st = self.box.state()
        plan = BK.Plan(st)
        plan.bind(BK.default_target(st, "SUPER + SPACE"), BK.Combo.parse("SUPER + CTRL + M"), resolution="replace")
        plan.bind(BK.Target.command('notify-send "hi there"', "Say hi"), BK.Combo.parse("SUPER + ALT + H"))
        with open(self.box.lua, "w") as f:
            f.write(BK.render(self.box.original, plan.record))
        eff = effective(self.box.state())
        self.assertEqual(eff["SUPER + CTRL + M"], [("exec", "bromigos-menu")])
        self.assertNotIn("SUPER + SPACE", eff)
        self.assertEqual(eff["SUPER + ALT + H"], [("exec", 'notify-send "hi there"')])

    def test_record_round_trip(self):
        r = BK.Record(["SUPER + SPACE"], [BK.Bind("SUPER + M", 'Desktop "menu"', "default",
                                                 [{"exec": "bromigos-menu"}, {"exec": "x", "release": True}],
                                                 origin="SUPER + SPACE"),
                                         BK.Bind("SUPER + ALT + T", "Theme: Mire", "menu",
                                                 [{"exec": "bromigos theme set mire"}], ref="style/theme/mire")])
        path = os.path.join(self.box.config, "bromigos", "keys.toml")
        with open(path, "w") as f:
            f.write(r.dumps())
        self.assertEqual(BK.Record.load(path), r)


# ------------------------------------------------------------------ clashes and changes
class ClashTest(Base):
    def test_taken_by_a_default(self):
        st = self.box.state()
        with self.assertRaises(BK.Clash) as cm:
            BK.Plan(st).bind(BK.Target.command("foot"), BK.Combo.parse("SUPER + W"))
        c = cm.exception
        self.assertEqual([(o.source, o.keys) for o in c.owners], [("default", "SUPER + W")])
        self.assertEqual(c.owners[0].what, "All desktop panels")
        self.assertFalse(c.can_swap)                       # foot has no key to give

    def test_replace_turns_the_default_off(self):
        st = self.box.state()
        plan = BK.Plan(st)
        plan.bind(BK.Target.command("foot"), BK.Combo.parse("SUPER + W"), resolution="replace")
        self.assertEqual(plan.record.unbind, ["SUPER + W"])
        self.assertEqual([(b.keys, b.actions) for b in plan.record.binds], [("SUPER + W", [{"exec": "foot"}])])

    def test_swap_two_defaults(self):
        st = self.box.state()
        plan = BK.Plan(st)
        menu = BK.default_target(st, "SUPER + SPACE")
        plan.bind(menu, BK.Combo.parse("SUPER + W"), resolution="swap")
        with open(self.box.lua, "w") as f:
            f.write(BK.render(self.box.original, plan.record))
        eff = effective(self.box.state())
        self.assertEqual(eff["SUPER + W"], [("exec", "bromigos-menu")])
        self.assertEqual(eff["SUPER + SPACE"], [("exec", "bromigos-widgets toggle all")])
        self.assertEqual(sorted(plan.record.unbind), ["SUPER + SPACE", "SUPER + W"])

    def test_move_back_home_leaves_nothing(self):
        st = self.box.state()
        plan = BK.Plan(st)
        menu = BK.default_target(st, "SUPER + SPACE")
        plan.bind(menu, BK.Combo.parse("SUPER + CTRL + M"), resolution="replace")
        self.assertTrue(plan.record.binds)
        plan.bind(menu, BK.Combo.parse("SUPER + SPACE"))
        self.assertTrue(plan.record.empty(), plan.record)

    def test_a_moved_default_goes_home_from_its_new_key(self):
        st = self.box.state()
        plan = BK.Plan(st)
        plan.bind(BK.default_target(st, "SUPER + SPACE"), BK.Combo.parse("SUPER + CTRL + M"))
        self.assertTrue(BK.commit(plan, FakeHypr(self.box), wait=0.2)[0])
        st = self.box.state()
        t = BK.yours_target(st, "SUPER + CTRL + M")
        self.assertEqual((t.kind, t.origin), ("default", "SUPER + SPACE"))
        plan = BK.Plan(st)
        self.assertEqual(str(plan.current(t)), "SUPER + CTRL + M")
        plan.bind(t, BK.Combo.parse("SUPER + SPACE"))
        self.assertTrue(plan.record.empty())

    def test_hold_bind_keeps_both_halves(self):
        # a press-and-release pair (VECTOR's push to talk when VECTOR is installed): both move
        st = self.box.state()
        st.defaults = [e for e in st.defaults if e.keys != "SUPER + V"]
        st.defaults.append(BK.Entry("SUPER + V", "exec", "holo ptt on"))
        st.defaults.append(BK.Entry("SUPER + V", "exec", "holo ptt off", release=True))
        plan = BK.Plan(st)
        plan.bind(BK.default_target(st, "SUPER + V"), BK.Combo.parse("SUPER + CTRL + ALT + V"))
        body = BK.binds_body(plan.record)
        self.assertIn('K.exec("SUPER + ALT + CTRL + V", "holo ptt on")', body)
        self.assertIn('K.exec("SUPER + ALT + CTRL + V", "holo ptt off", { release = true })', body)

    def test_already_there(self):
        st = self.box.state()
        plan = BK.Plan(st)
        plan.bind(BK.default_target(st, "SUPER + SPACE"), BK.Combo.parse("super + space"))
        self.assertFalse(plan.changed())


class ClashConfigTest(Base):
    extra_lua = 'K.exec("ALT + W", "firefox")\n'

    def test_your_own_bind_is_refused(self):
        st = self.box.state()
        with self.assertRaises(BK.Refused) as cm:
            BK.Plan(st).bind(BK.Target.command("foot"), BK.Combo.parse("ALT + W"), resolution="replace")
        self.assertIn("your own bind in hyprland.lua", str(cm.exception))


class HandUnbindTest(Base):
    """A default the user turned off in their own table, and bound the key themselves."""
    def setUp(self):
        super().setUp()
        text = self.box.original.replace("    -- unbind = { },", '    unbind = { "SUPER + W" },')
        text += 'K.exec("SUPER + W", "foot")\n'
        with open(self.box.lua, "w") as f:
            f.write(text)
        self.box.original = text

    def test_their_bind_owns_the_key(self):
        st = self.box.state()
        self.assertEqual(st.unbind, ["SUPER + W"])
        plan = BK.Plan(st)
        self.assertEqual([o.source for o in plan.owners(BK.Combo.parse("SUPER + W"))], ["config"])
        target = BK.default_target(st, "SUPER + W")
        self.assertIsNone(plan.current(target))           # off, by their hand
        with self.assertRaises(BK.Refused):
            plan.reset("SUPER + W")
        # given another key it's bound there; their unbind stays theirs
        plan.bind(target, BK.Combo.parse("SUPER + CTRL + W"))
        self.assertEqual([b.keys for b in plan.record.binds], ["SUPER + CTRL + W"])
        self.assertTrue(BK.commit(plan, FakeHypr(self.box), wait=0.2)[0])
        self.assertIn('unbind = { "SUPER + W" },', self.box.read())


def with_mod(text, mod):
    return text.replace('    -- mod = "ALT",', f'    mod = "{mod}",')


def dumped(box):
    """{keys: [payload]} the config binds, as widgets/keybinds-dump.lua (Hyprland stand-in,
    bromigos.unbind applied) lists them."""
    import subprocess
    out = subprocess.run(["lua", os.path.join(REPO, "widgets", "keybinds-dump.lua"), box.lua],
                         capture_output=True, text=True, env=box.env, check=True).stdout
    binds = {}
    for line in out.splitlines():
        f = line.split("\t")
        if len(f) == 5 and f[0] == "0":
            binds.setdefault(f[2], []).append(f[4])
    return binds


class ModSuperTest(Base):
    """mod = "SUPER": the window keys on Super. A desktop key a window key would share
    (Super+L: lock, and focus right) moves to Alt in the defaults themselves (keys.lua,
    K.finish), so bromigos keys' own clash check finds no key doing two things."""

    def setUp(self):
        super().setUp()
        self.box.original = with_mod(self.box.original, "SUPER")
        with open(self.box.lua, "w") as f:
            f.write(self.box.original)

    def test_no_key_does_two_things(self):
        for mod in ("SUPER", "super", "SUPER + ALT", "ALT", "CTRL"):
            with open(self.box.lua, "w") as f:
                f.write(with_mod(user_config(), mod))
            st = self.box.state()
            self.assertIsNone(st.error)
            plan = BK.Plan(st)
            for keys, group in st.default_groups():
                owners = plan.owners(group[0].combo())
                self.assertEqual([o.keys for o in owners], [keys], f"mod {mod}: {[o.says() for o in owners]}")

    def test_the_window_keys_keep_super_and_the_desktops_go_to_alt(self):
        plan = BK.Plan(self.box.state())
        what = lambda k: [o.what for o in plan.owners(BK.Combo.parse(k))]  # noqa: E731
        self.assertEqual(what("SUPER + L"), ["Focus right"])
        self.assertEqual(what("ALT + L"), ["Lock"])
        self.assertEqual(what("SUPER + K"), ["Previous window"])
        self.assertEqual(what("ALT + K"), ["This shortcuts panel"])
        # the live layer's (VECTOR's keys are only there where he's installed)
        self.assertEqual(what("SUPER + SHIFT + S"), ["Send window to scratchpad"])
        self.assertEqual(what("ALT + SHIFT + S"), ["Swarm: repos and agent starships"])
        self.assertEqual(what("SUPER + SPACE"), ["Desktop menu"])        # no window key there: stays
        # as many binds as with Alt: none left out
        alt = Sandbox()
        try:
            self.assertEqual(len(self.box.state().defaults), len(alt.state().defaults))
        finally:
            alt.close()

    def test_a_moved_key_is_bromigos_keys_like_any_default(self):
        st = self.box.state()
        with self.assertRaises(BK.Clash) as cm:
            BK.Plan(st).bind(BK.Target.command("foot"), BK.Combo.parse("ALT + L"))
        self.assertEqual([(o.source, o.keys, o.what) for o in cm.exception.owners], [("default", "ALT + L", "Lock")])
        plan = BK.Plan(st)
        plan.bind(BK.default_target(st, "ALT + L"), BK.Combo.parse("SUPER + CTRL + L"))
        self.assertTrue(BK.commit(plan, FakeHypr(self.box), wait=0.2)[0])
        eff = effective(self.box.state())
        self.assertEqual(eff["SUPER + CTRL + L"], [("exec", "loginctl lock-session")])
        self.assertNotIn("ALT + L", eff)
        self.assertEqual(eff["SUPER + L"], [("lua", 'hl.dsp.focus({ direction = "right" })')])

    def test_unbind_takes_the_keys_the_defaults_end_on(self):
        text = self.box.original.replace("    -- unbind = { },", '    unbind = { "ALT + L" },')
        with open(self.box.lua, "w") as f:
            f.write(text)
        binds = dumped(self.box)
        self.assertNotIn("ALT + L", binds)                                   # the lock is off
        self.assertEqual(binds["SUPER + l"], ['hl.dsp.focus({ direction = "right" })'])
        self.assertEqual(binds["ALT + K"], ["bromigos-widgets toggle shortcuts"])

    def test_with_alt_nothing_moves(self):
        with open(self.box.lua, "w") as f:
            f.write(user_config())
        binds = dumped(self.box)
        self.assertEqual(binds["SUPER + L"], ["loginctl lock-session"])
        self.assertEqual(binds["ALT + l"], ['hl.dsp.focus({ direction = "right" })'])
        self.assertNotIn("ALT + K", binds)


PERIPHERAL = '''return {
    {
        id = "razer-keyboard",
        tag = "bromigos-razer-keyboard",
        devices = { "razer-razer-blackwidow-v4-pro" },
        kb_options = { "fkeys:basic_13-24" },
        exclusive = { "XF86AudioMicMute" },
        binds = {
            { keys = "code:191", cmd = "/usr/bin/bromigos-holo vector", hint = "M1" },
        },
    },
}
'''


class PeripheralTest(Base):
    """With a peripheral module on (bromigos/peripherals.lua, loaded before the default binds):
    its keys are defaults like the rest (replaced through bromigos.unbind), and a shortcut on a
    key it keeps for its keyboard (K.exclude) is spelled so it gets the exclusion."""

    def setUp(self):
        super().setUp()
        d = os.path.join(self.box.tmp, "state", "bromigos", "peripherals")
        os.makedirs(d)
        with open(os.path.join(d, "hypr.lua"), "w") as f:
            f.write(PERIPHERAL)

    def record_binds(self):
        import subprocess
        r = subprocess.run(["lua", os.path.join(HERE, "hl-record.lua"), self.box.lua], env=self.box.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [ln.split("\t") for ln in r.stdout.splitlines() if ln.startswith("bind\t")]

    def test_module_keys_and_exclusions(self):
        st = self.box.state()
        self.assertEqual(st.exclusive, ["XF86AudioMicMute"])
        self.assertIn("code:191", [k for k, _ in st.default_groups()])
        # M1 pressed (keycode 191 reads F13 on that keyboard): the module's bind holds it
        owners = BK.Plan(st).owners(BK.Combo.parse("F13", keycode=191))
        self.assertEqual([(o.source, o.keys) for o in owners], [("default", "code:191")])
        plan = BK.Plan(st)
        plan.bind(BK.Target.command("foot"), BK.Combo.parse("F13", keycode=191), resolution="replace")
        plan.bind(BK.Target.command("mic-thing"), BK.Combo.parse("xf86audiomicmute"), resolution="replace")
        self.assertEqual(sorted(plan.record.unbind), ["XF86AudioMicMute", "code:191"])
        self.assertTrue(BK.commit(plan, FakeHypr(self.box), wait=0.2)[0])
        binds = self.record_binds()
        self.assertFalse([b for b in binds if b[1] == "code:191"])            # the module's M1 off
        mic = [b for b in binds if b[1] == "XF86AudioMicMute"]
        self.assertEqual([(b[3], b[4]) for b in mic], [("!bromigos-razer-keyboard", '"mic-thing"')])


class ClashLiveTest(Base):
    def test_a_bind_only_hyprland_has(self):
        st = self.box.state()
        st.live = [BK.Live(BK.Combo.parse("SUPER + Y"), "exec", "plugin-thing", False)]
        owners = BK.Plan(st).owners(BK.Combo.parse("SUPER + Y"))
        self.assertEqual([o.source for o in owners], ["live"])
        with self.assertRaises(BK.Refused):
            BK.Plan(st).bind(BK.Target.command("foot"), BK.Combo.parse("SUPER + Y"), resolution="replace")


WEBAPPS = '''[[app]]
name = "gmail"
title = "Gmail"
url = "https://mail.google.com"
hotkey = "SUPER + SHIFT + G"
'''


class WebappTest(Base):
    webapps = WEBAPPS
    extra_lua = ('\n-- >>> bromigos webapps\ndo\n    local K = require("bromigos.keys")\n'
                 '    K.exec("SUPER + SHIFT + G", "bromigos-webapp launch gmail")\nend\n-- <<< bromigos webapps\n')

    def test_webapp_key_is_the_webapps(self):
        st = self.box.state()
        plan = BK.Plan(st)
        o = plan.owners(BK.Combo.parse("SUPER + SHIFT + G"))
        self.assertEqual([(x.source, x.ref) for x in o], [("webapp", "gmail")])
        self.assertEqual(st.your_user_entries(), [])          # the block isn't "your own bind"
        # binding the web app to another key moves its hotkey
        plan.bind(BK.Target.webapp("gmail", "Gmail"), BK.Combo.parse("SUPER + ALT + G"))
        self.assertEqual(plan.webapps[0]["hotkey"], "SUPER + ALT + G")
        self.assertTrue(plan.record.empty())

    def test_replace_a_webapps_key(self):
        st = self.box.state()
        plan = BK.Plan(st)
        plan.bind(BK.Target.command("foot"), BK.Combo.parse("SUPER + SHIFT + G"), resolution="replace")
        self.assertNotIn("hotkey", plan.webapps[0])
        fake = FakeHypr(self.box)
        ok, msg = BK.commit(plan, fake, wait=0.2)
        self.assertTrue(ok, msg)
        lua = self.box.read()
        self.assertNotIn("-- >>> bromigos webapps", lua)          # no web app keys left: no block
        self.assertNotIn("hotkey =", self.box.read("webapps"))
        self.assertIn('K.exec("SUPER + SHIFT + G", "foot")', lua)


class LockoutTest(Base):
    def test_taking_the_menus_only_key(self):
        st = self.box.state()
        with self.assertRaises(BK.Lockout) as cm:
            BK.Plan(st).bind(BK.Target.command("foot"), BK.Combo.parse("SUPER + SPACE"), resolution="replace")
        self.assertIn("the menu", str(cm.exception))
        plan = BK.Plan(st)
        plan.bind(BK.Target.command("foot"), BK.Combo.parse("SUPER + SPACE"), resolution="replace", confirm=True)
        self.assertIn("SUPER + SPACE", plan.record.unbind)

    def test_moving_the_menu_is_fine(self):
        st = self.box.state()
        BK.Plan(st).bind(BK.default_target(st, "SUPER + SPACE"), BK.Combo.parse("SUPER + CTRL + M"), resolution="replace")

    def test_a_typing_key(self):
        st = self.box.state()
        with self.assertRaises(BK.Lockout):
            BK.Plan(st).bind(BK.Target.command("foot"), BK.Combo.parse("Q"))

    def test_unbinding_the_terminal(self):
        st = self.box.state()
        with self.assertRaises(BK.Lockout) as cm:
            BK.Plan(st).unbind(BK.Combo.parse("ALT + SHIFT + RETURN"))
        self.assertIn("the terminal", str(cm.exception))


class ResetTest(Base):
    def test_unbind_then_reset_one(self):
        st = self.box.state()
        plan = BK.Plan(st)
        plan.unbind(BK.Combo.parse("SUPER + W"))
        self.assertEqual(plan.record.unbind, ["SUPER + W"])
        self.assertTrue(BK.commit(plan, FakeHypr(self.box), wait=0.2)[0])
        st = self.box.state()
        rows, off = BK.listing(st)
        self.assertEqual([(o["keys"], o["what"]) for o in off], [("SUPER + W", "All desktop panels")])
        plan = BK.Plan(st)
        plan.reset("SUPER + W")
        self.assertTrue(BK.commit(plan, FakeHypr(self.box), wait=0.2)[0])
        self.assertEqual(self.box.read(), self.box.original)

    def test_reset_all(self):
        st = self.box.state()
        plan = BK.Plan(st)
        plan.bind(BK.default_target(st, "SUPER + SPACE"), BK.Combo.parse("SUPER + W"), resolution="swap")
        plan.bind(BK.Target.command("foot"), BK.Combo.parse("SUPER + ALT + F"))
        self.assertTrue(BK.commit(plan, FakeHypr(self.box), wait=0.2)[0])
        self.assertNotEqual(self.box.read(), self.box.original)
        plan = BK.Plan(self.box.state())
        plan.reset()
        self.assertTrue(BK.commit(plan, FakeHypr(self.box), wait=0.2)[0])
        self.assertEqual(self.box.read(), self.box.original)


VERIFY = """#!/bin/sh
# a stand-in for `Hyprland --verify-config -c FILE` (the package builder has no Hyprland):
# the file must load as Lua
[ "$1" = --verify-config ] || exit 1
lua -e "local f, e = loadfile('$3'); if not f then print(e); os.exit(1) end" && echo "config ok"
"""


def stand_in_hyprland(box):
    """A bin folder with the stand-in Hyprland, for PATH."""
    d = os.path.join(box.tmp, "stand-in")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "Hyprland"), "w") as f:
        f.write(VERIFY)
    os.chmod(os.path.join(d, "Hyprland"), 0o755)
    return d


class CommandTest(Base):
    """bin/bromigos-keys itself, without Hyprland: --json outcomes, undo, list --all."""

    def keys(self, *args):
        import subprocess
        env = dict(self.box.env, XDG_RUNTIME_DIR=os.path.join(self.box.tmp, "run"),
                   DBUS_SESSION_BUS_ADDRESS="disabled:",
                   PATH=stand_in_hyprland(self.box) + os.pathsep + self.box.env["PATH"])
        r = subprocess.run([sys.executable, os.path.join(DESKTOP, "bin", "bromigos-keys"), *args], env=env,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def test_json_outcomes_and_undo(self):
        code, out, _ = self.keys("bind", "SUPER + CTRL + M", "--default", "SUPER + SPACE", "--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["ok"]), (0, True), out)
        self.assertIn("Desktop menu", doc["notes"][0])
        moved = self.box.read()
        code, out, _ = self.keys("unbind", "SUPER + CTRL + M", "--json")     # the menu's only key
        doc = json.loads(out)
        self.assertEqual((code, doc["ok"], doc.get("confirm")), (1, False, True), out)
        code, out, _ = self.keys("bind", "SUPER + D", "--exec", "foo", "--json")
        doc = json.loads(out)
        self.assertEqual([t["what"] for t in doc["taken"]], ["Storage panel"])
        code, out, _ = self.keys("undo", "--json")
        self.assertTrue(json.loads(out)["ok"], out)
        self.assertEqual(self.box.read(), self.box.original)                # undone
        code, out, _ = self.keys("undo", "--json")                          # and again: redone
        self.assertEqual(json.loads(out)["notes"][0], "Desktop menu: SUPER + CTRL + M (was SUPER + SPACE)")
        self.assertEqual(self.box.read(), moved)

    def test_list_all(self):
        self.keys("bind", "SUPER + ALT + T", "--exec", "kitty -e btop", "--what", "System monitor")
        code, out, _ = self.keys("list", "--all", "--json")
        doc = json.loads(out)
        rows = {r["keys"]: r for r in doc["all"]}
        self.assertEqual((rows["SUPER + SPACE"]["source"], rows["SUPER + SPACE"]["movable"]), ("default", True))
        self.assertEqual((rows["SUPER + ALT + T"]["source"], rows["SUPER + ALT + T"]["section"]), ("yours", "YOURS"))
        self.assertFalse(rows["ALT + mouse:272"]["movable"])
        sections = [r["section"] for r in doc["all"]]
        self.assertEqual(sections, sorted(sections, key=lambda s: sections.index(s)))   # grouped


# ------------------------------------------------------------------ the safe save
class CommitTest(Base):
    def plan(self):
        st = self.box.state()
        plan = BK.Plan(st)
        plan.bind(BK.default_target(st, "SUPER + SPACE"), BK.Combo.parse("SUPER + CTRL + M"), resolution="replace")
        return plan

    def assertUntouched(self):
        self.assertEqual(self.box.read(), self.box.original)
        self.assertIsNone(self.box.read("record"))
        self.assertIsNone(self.box.read("webapps"))

    def test_saved_in_order(self):
        fake = FakeHypr(self.box)
        real = logged_writes(fake)
        try:
            ok, msg = BK.commit(self.plan(), fake, wait=0.2)
        finally:
            H.write_file = real
        self.assertTrue(ok, msg)
        self.assertEqual(msg, "saved and live")
        kinds = [e[0] for e in fake.events]
        self.assertEqual(fake.events[0], ("autoreload_off", True))                  # off before anything is written
        self.assertLess(kinds.index("autoreload_off"), kinds.index("write"))
        writes = [e[1] for e in fake.events if e[0] == "write"]
        self.assertEqual(writes[-1], "hyprland.lua")                                # the config last
        self.assertLess(kinds.index("write"), kinds.index("verify"))
        self.assertLess(kinds.index("verify"), kinds.index("reload"))
        self.assertEqual(kinds.count("reload"), 1)
        self.assertEqual(fake.events[-1], ("autoreload_off", False))                # back as it was
        self.assertIn('K.exec("SUPER + CTRL + M", "bromigos-menu")', self.box.read())
        self.assertIn('unbind = ["SUPER + SPACE"]', self.box.read("record"))

    def test_a_symlinked_config_stays_a_symlink(self):
        # a hyprland.lua kept in dotfiles and linked into ~/.config: the link stays, the
        # file it points at changes (and goes back the same way)
        dot = os.path.join(self.box.tmp, "dotfiles")
        os.makedirs(dot)
        real = os.path.join(dot, "hyprland.lua")
        os.replace(self.box.lua, real)
        os.symlink(os.path.relpath(real, os.path.dirname(self.box.lua)), self.box.lua)
        self.assertTrue(BK.commit(self.plan(), FakeHypr(self.box), wait=0.2)[0])
        self.assertTrue(os.path.islink(self.box.lua))
        self.assertIn("SUPER + CTRL + M", H.read_file(real))
        before = H.read_file(real)
        plan = BK.Plan(self.box.state())
        plan.bind(BK.Target.command("foot"), BK.Combo.parse("SUPER + CTRL + F"))
        self.assertFalse(BK.commit(plan, FakeHypr(self.box, verify_ok=False), wait=0.2)[0])
        self.assertTrue(os.path.islink(self.box.lua))
        self.assertEqual(H.read_file(real), before)                           # put back through the link
        self.assertEqual(sorted(os.listdir(dot)), ["hyprland.lua"])          # no temporary left

    def test_autoreload_comes_back_as_it_was(self):
        fake = FakeHypr(self.box)
        fake.disable_autoreload = True            # the user keeps it off
        self.assertTrue(BK.commit(self.plan(), fake, wait=0.2)[0])
        self.assertEqual(fake.events[-1], ("autoreload_off", True))

    def test_verify_fails_everything_back(self):
        fake = FakeHypr(self.box, verify_ok=False)
        ok, msg = BK.commit(self.plan(), fake, wait=0.2)
        self.assertFalse(ok)
        self.assertIn("didn't accept", msg)
        self.assertUntouched()
        self.assertNotIn(("reload",), fake.events)                                  # never reloaded
        self.assertEqual(fake.events[-1], ("autoreload_off", False))

    def test_new_config_errors_everything_back(self):
        fake = FakeHypr(self.box, errors_after=["hl.bind: something is wrong"])
        ok, msg = BK.commit(self.plan(), fake, wait=0.2)
        self.assertFalse(ok)
        self.assertIn("something is wrong", msg)
        self.assertUntouched()
        self.assertEqual([e for e in fake.events if e[0] == "reload"], [("reload",), ("reload",)])
        self.assertEqual(fake.events[-1], ("autoreload_off", False))

    def test_old_config_errors_dont_count(self):
        fake = FakeHypr(self.box)
        fake.errors = ["an error the user already had"]
        fake.errors_after = ["an error the user already had"]
        self.assertTrue(BK.commit(self.plan(), fake, wait=0.2)[0])

    def test_bind_not_live_everything_back(self):
        fake = FakeHypr(self.box, drop=True)
        ok, msg = BK.commit(self.plan(), fake, wait=0.2)
        self.assertFalse(ok)
        self.assertIn("SUPER + CTRL + M isn't bound", msg)
        self.assertUntouched()

    def test_no_hyprland_running(self):
        fake = FakeHypr(self.box, running=False)
        ok, msg = BK.commit(self.plan(), fake, wait=0.2)
        self.assertTrue(ok, msg)
        self.assertIn("next starts", msg)
        self.assertNotIn(("reload",), fake.events)
        self.assertIn("SUPER + CTRL + M", self.box.read())

    def test_a_broken_block_is_refused_by_verify(self):
        # the real evaluation of the written file is the stand-in's verify: a bind the
        # config can't run stops it, and the file goes back
        fake = FakeHypr(self.box)
        plan = self.plan()
        plan.record.binds[0].actions = [{"lua": "hl.dsp.this_is(not lua"}]
        orig = BK.binds_body

        def broken(record, exclusive=()):
            return orig(record, exclusive) + "\nerror('boom')"
        BK.binds_body = broken
        try:
            ok, msg = BK.commit(plan, fake, wait=0.2)
        finally:
            BK.binds_body = orig
        self.assertFalse(ok)
        self.assertUntouched()


# ------------------------------------------------------------------ the capture window
class KeysTest(unittest.TestCase):
    """The capture window's keys (bromigos_keycapture.Keys), without a display."""

    def test_hold_release_settles_then_saves(self):
        k = C.Keys(settle=1.0)
        self.assertIsNone(k.press("Super_L", 133))
        self.assertEqual(k.shown(), (["SUPER"], False))
        k.press("Shift_L", 50)
        k.press("w", 25)
        self.assertEqual(k.shown(), (["SUPER", "SHIFT", "W"], True))
        k.release(25)
        self.assertEqual(k.phase, "hold")                 # modifiers still down
        k.release(50)
        k.release(133)
        self.assertEqual(k.phase, "settle")
        self.assertIsNone(k.tick(0.5))
        self.assertEqual(k.tick(0.6), "confirm")
        self.assertEqual(k.result()["keys"], "SUPER + SHIFT + W")
        self.assertEqual(k.result()["keycode"], 25)

    def test_enter_backspace_escape(self):
        k = C.Keys()
        self.assertEqual(k.press("Escape", 9), "cancel")
        k = C.Keys()
        self.assertIsNone(k.press("Return", 36))          # nothing to save yet
        self.assertIn("Enter alone", k.note)
        k.press("Alt_L", 64)
        k.press("Return", 36)                             # with a modifier it's a key
        self.assertEqual(k.shown(), (["ALT", "RETURN"], True))
        k.release(36)
        k.release(64)
        self.assertEqual(k.press("Return", 36), "confirm")
        k = C.Keys()
        k.press("Control_L", 37)
        k.press("x", 53)
        k.release(53)
        k.release(37)
        self.assertIsNone(k.press("BackSpace", 22))       # clears
        self.assertEqual((k.phase, k.combo), ("listen", None))

    def test_modifier_alone_isnt_a_shortcut(self):
        k = C.Keys()
        k.press("Super_L", 133)
        k.release(133)
        self.assertEqual((k.phase, k.combo), ("listen", None))

    def test_repeat_and_altgr_ignored(self):
        k = C.Keys()
        k.press("Super_L", 133)
        k.press("ISO_Level3_Shift", 108)
        k.press("a", 38)
        k.press("a", 38)                                  # key repeat
        self.assertEqual(k.shown(), (["SUPER", "A"], True))

    def test_times_out(self):
        k = C.Keys(limit=1.0)
        self.assertIsNone(k.tick(0.6))
        self.assertEqual(k.tick(0.6), "timeout")


class SuppressTest(Base):
    def test_enter_and_leave(self):
        fake = FakeHypr(self.box)
        s = C.Suppress(fake)
        s._watchdog = lambda: None
        ok, why = s.enter()
        self.assertTrue(ok, why)
        self.assertEqual(fake.submap, "bromigos-capture")
        timer = [e for e in fake.events if e[0] == "eval" and "hl.timer" in e[1]]
        self.assertEqual(len(timer), 1)                   # Hyprland's own way out
        s.leave()
        self.assertEqual(fake.submap, "default")

    def test_defines_the_submap_for_an_old_config(self):
        fake = FakeHypr(self.box)
        fake.submaps = set()
        s = C.Suppress(fake)
        s._watchdog = lambda: None
        self.assertTrue(s.enter()[0])
        self.assertTrue(any(e[0] == "eval" and e[1].startswith("hl.define_submap") for e in fake.events))
        s.leave()

    def test_never_left_in_a_submap_it_couldnt_enter(self):
        fake = FakeHypr(self.box)
        fake.submaps = set()
        fake.eval = lambda code: "error"                  # Hyprland won't define it
        s = C.Suppress(fake)
        s._watchdog = lambda: None
        ok, why = s.enter()
        self.assertFalse(ok)
        self.assertEqual(fake.submap, "default")

    def test_no_hyprland(self):
        self.assertFalse(C.Suppress(FakeHypr(self.box, running=False)).enter()[0])

    def test_the_default_config_defines_it(self):
        with open(os.path.join(DESKTOP, "hypr", "bromigos", "binds.lua")) as f:
            text = f.read()
        self.assertIn('hl.define_submap("bromigos-capture"', text)
        self.assertIn("non_consuming = true", text)


def _gtk4_layer_shell():
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        return True
    except (ImportError, ValueError):
        return False


class Weston(unittest.TestCase):
    """A headless weston of the test's own (a runtime directory of its own: no window
    anywhere) to draw on."""

    def setUp(self):
        import subprocess
        import time
        self.sp = subprocess
        self.tmp = tempfile.mkdtemp(prefix="bkr-", dir="/tmp")      # short: a socket path
        os.chmod(self.tmp, 0o700)
        self.weston = subprocess.Popen(
            ["weston", "--backend=headless", "--renderer=pixman", "--width=1200", "--height=700",
             "--socket=w", "--idle-time=0", "--no-config"],
            env={"HOME": self.tmp, "XDG_RUNTIME_DIR": self.tmp, "PATH": os.environ.get("PATH", "/usr/bin")},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if os.path.exists(os.path.join(self.tmp, "w")):
                break
            time.sleep(0.05)

    def tearDown(self):
        self.weston.terminate()
        self.weston.wait(5)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, palette=None, **kw):
        state = os.path.join(self.tmp, "state")
        if palette is not None:
            os.makedirs(os.path.join(state, "bromigos", "theme", "current"), exist_ok=True)
            with open(os.path.join(state, "bromigos", "theme", "current", "palette.json"), "w") as f:
                json.dump(palette, f)
        out = os.path.join(self.tmp, "cap.png")
        code = ("import sys, json; import bromigos_keycapture as C; "
                f"print(json.dumps(C.render({out!r}, **json.loads(sys.argv[1]))))")
        env = {"HOME": self.tmp, "XDG_RUNTIME_DIR": self.tmp, "WAYLAND_DISPLAY": "w", "XDG_STATE_HOME": state,
               "PATH": os.environ.get("PATH", "/usr/bin"), "GDK_BACKEND": "wayland", "GSK_RENDERER": "cairo",
               "PYTHONPATH": os.pathsep.join([os.path.join(DESKTOP, "lib"), os.path.join(REPO, "lib"),
                                              os.path.join(REPO, "widgets")]),
               "DBUS_SESSION_BUS_ADDRESS": "disabled:"}
        r = self.sp.run([sys.executable, "-c", code, json.dumps(kw)], env=env, capture_output=True, text=True,
                        timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        from PIL import Image
        return Image.open(out).convert("RGBA")

    @staticmethod
    def has(img, hexcolour, tol=6, least=20):
        want = tuple(int(hexcolour[i:i + 2], 16) for i in (1, 3, 5))
        n = 0
        for px in img.getdata():
            if px[3] > 200 and all(abs(a - b) <= tol for a, b in zip(px[:3], want)):
                n += 1
                if n >= least:
                    return True
        return False


@unittest.skipUnless(shutil.which("weston") and _gtk4_layer_shell(), "needs weston and GTK 4")
class RenderTest(Weston):
    """The capture window drawn offscreen: the theme's colours, and high contrast's opaque
    frame."""

    def test_the_wick(self):
        img = self.render(what="Desktop menu", current="SUPER + SPACE", keys="SUPER + SHIFT + W", phase="hold")
        self.assertTrue(560 <= img.size[0] < 700 and 150 < img.size[1] < 400, img.size)
        self.assertTrue(self.has(img, C.WICK["panel"]), "the panel colour")
        self.assertTrue(self.has(img, C.WICK["selection"]), "the keycaps")
        self.assertTrue(self.has(img, C.WICK["primary"]), "the keycaps' edge, the eyebrow")

    def test_a_theme_and_high_contrast(self):
        mire = {"schema": 1, "name": "Mire", "colors": {"panel": "#0c1513", "selection": "#1c2d27",
                                                      "primary": "#b8e05a", "soft": "#d6e8b4", "dim": "#5d7a4b"}}
        img = self.render(mire, what="Theme", keys="ALT + RETURN", phase="settle")
        self.assertTrue(self.has(img, "#0c1513"))
        self.assertTrue(self.has(img, "#b8e05a"))
        self.assertFalse(self.has(img, C.WICK["primary"], least=5))      # no Wick left over
        mire["contrast"] = {"mode": "high"}
        img = self.render(mire, what="Theme", keys="ALT + RETURN", phase="hold")
        edge = img.getpixel((0, img.size[1] // 2))                         # the frame's left side
        inside = img.getpixel((12, img.size[1] // 2))
        self.assertEqual((edge[3], inside[3]), (255, 255))                 # opaque
        self.assertTrue(all(abs(a - b) <= 12 for a, b in zip(edge[:3], (0xd6, 0xe8, 0xb4))), edge)


def _adw():
    try:
        import gi
        gi.require_version("Adw", "1")
        return True
    except (ImportError, ValueError):
        return False


@unittest.skipUnless(shutil.which("weston") and shutil.which("lua") and _adw(), "needs weston, lua and libadwaita")
class SettingsPageTest(Weston):
    """The Settings app's Shortcuts page (settings/pages/shortcuts.py) drawn offscreen with
    real data: `bromigos keys list --all --json` from a sandbox with a moved default and a
    turned-off one (a stub `bromigos` routes `keys` to this checkout)."""

    def test_the_page_with_your_keys(self):
        box = Sandbox()
        self.addCleanup(box.close)
        bin_ = os.path.join(box.tmp, "bin")
        os.makedirs(bin_)
        with open(os.path.join(bin_, "bromigos"), "w") as f:
            f.write("#!/bin/sh\ncase \"$1\" in\n"
                    "  commands) echo '{\"builtins\": [], \"commands\": [{\"route\": \"bromigos keys\"}]}' ;;\n"
                    f"  keys) shift; exec {sys.executable} {os.path.join(DESKTOP, 'bin', 'bromigos-keys')} \"$@\" ;;\n"
                    "  *) exit 1 ;;\nesac\n")
        os.chmod(os.path.join(bin_, "bromigos"), 0o755)
        env = dict(box.env, PATH=f"{bin_}:{stand_in_hyprland(box)}:" + os.environ.get("PATH", "/usr/bin"),
                   XDG_RUNTIME_DIR=self.tmp,
                   WAYLAND_DISPLAY="w", GDK_BACKEND="wayland", GSK_RENDERER="cairo", DBUS_SESSION_BUS_ADDRESS="disabled:",
                   PYTHONPATH=os.pathsep.join([os.path.join(REPO, "lib"), os.path.join(REPO, "widgets")]))
        for args in (["bind", "SUPER + CTRL + M", "--default", "SUPER + SPACE"], ["unbind", "SUPER + D"]):
            r = self.sp.run([os.path.join(bin_, "bromigos"), "keys", *args], env=env, capture_output=True, text=True,
                            timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
        out = os.path.join(self.tmp, "page.png")
        r = self.sp.run([sys.executable, os.path.join(DESKTOP, "settings", "bromigos-settings"), "--render", out,
                         "--page", "shortcuts", "--size", "1120x680"], env=env, capture_output=True, text=True,
                        timeout=90)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        from PIL import Image
        self.assertEqual(Image.open(out).size, (1120, 680))


# ------------------------------------------------------------------ SHORTCUTS
class ShortcutsTest(Base):
    def test_your_shortcuts_by_name(self):
        import keybinds as KB
        st = self.box.state()
        plan = BK.Plan(st)
        plan.bind(BK.Target("menu", "Theme: Mire", [{"exec": "bromigos theme set mire"}], ref="style/theme/mire"),
                  BK.Combo.parse("SUPER + ALT + T"))
        plan.bind(BK.default_target(st, "SUPER + SPACE"), BK.Combo.parse("SUPER + CTRL + M"), resolution="replace")
        self.assertTrue(BK.commit(plan, FakeHypr(self.box), wait=0.2)[0])
        binds = KB._parse_dump("\n".join(
            "\t".join(["1" if e.release else "0", "1" if e.mouse else "0", e.keys, e.kind, e.payload])
            for e in self.box.state().defaults + self.box.state().user
            if e.keys not in self.box.state().unbind))
        saved = (KB._hypr_binds, KB._peripherals, os.environ.get("XDG_CONFIG_HOME"))
        KB._hypr_binds, KB._peripherals = (lambda: binds), (lambda: {})
        os.environ["XDG_CONFIG_HOME"] = self.box.config
        try:
            rows = KB.shortcuts()
        finally:
            KB._hypr_binds, KB._peripherals = saved[0], saved[1]
            if saved[2] is None:
                os.environ.pop("XDG_CONFIG_HOME")
            else:
                os.environ["XDG_CONFIG_HOME"] = saved[2]
        yours = [(s, " + ".join(k), d) for s, k, d, a in rows if s == "YOURS"]
        self.assertEqual(yours, [("YOURS", "SUPER + ALT + T", "Theme: Mire")])
        menu = [(" + ".join(k), d) for s, k, d, a in rows if d.startswith("Desktop menu")]
        self.assertEqual(menu[0][0], "SUPER + CTRL + M")         # a moved default keeps its own name


if __name__ == "__main__":
    unittest.main()
