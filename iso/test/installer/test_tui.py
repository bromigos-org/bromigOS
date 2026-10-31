"""The text installer, driven by keys like a person would (Textual's Pilot, headless), on a
recorded probe (fixtures/) and the fake install: every step, then the answers it hands to
bromigos-iso-install. Also run in the test VM against the real disks (iso/test.sh tui).

  python -m unittest discover -s iso/test/installer
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
LIB = os.path.join(HERE, "../../profile/airootfs/usr/local/lib/bromigos-iso")
SHARE = os.path.join(HERE, "../../profile/airootfs/usr/local/share/bromigos-iso")
STORE = tempfile.mkdtemp(prefix="bromigos-store-")
for name in ("bromigos-1-1-x86_64", "bromigos-desktop-1-1-x86_64", "bromigos-core-1-1-x86_64", "bromigos-lab-1-1-any"):
    os.makedirs(os.path.join(STORE, "bromigos", "x86_64"), exist_ok=True)
    open(os.path.join(STORE, "bromigos", "x86_64", name + ".pkg.tar.zst"), "w").close()
os.environ.update(BROMIGOS_INSTALLER_FAKE="1", BROMIGOS_NO_USB="1", BROMIGOS_INSTALLER_FAKE_DELAY="0.01", BROMIGOS_ISO_REPO_DIR=STORE,
                  BROMIGOS_INSTALLER_PROBE=os.environ.get("BROMIGOS_INSTALLER_PROBE") or os.path.join(HERE, "fixtures/probe-windows-uefi.json"),
                  BROMIGOS_EDITION_DIRS=os.path.join(SHARE, "editions"), BROMIGOS_REDUCED_MOTION="1")
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(HERE, "../../../lib"))

try:
    import textual  # noqa: F401
    from bromigos_installer import backend, common, tui
    sys.path.insert(0, HERE)
    from tuidrive import drive
    HAVE = True
except ImportError:
    HAVE = False

SHOTS = os.environ.get("BROMIGOS_INSTALLER_SHOTS")


class TUI(unittest.TestCase):
    def setUp(self):
        if not HAVE:
            self.skipTest("textual isn't installed")
        self.sent = []
        real = backend.Install.__init__

        def spy(inst, doc, *a, **k):
            self.sent.append(doc)
            real(inst, doc, *a, **k)
        backend.Install.__init__ = spy
        self.addCleanup(setattr, backend.Install, "__init__", real)

    def run_plan(self, plan, finish=True, size=(120, 42)):
        async def go():
            app = tui.Installer()
            async with app.run_test(size=size) as pilot:
                target, shots = await drive(app, pilot, plan)
                if finish:
                    await pilot.press("ctrl+n")
                    for _ in range(100):
                        if app.step == "done":
                            break
                        await pilot.pause(0.05)
                    if SHOTS:
                        app.save_screenshot(os.path.join(SHOTS, "tui-done.svg"))
                    return app, target
                return app, target
        return asyncio.run(go())

    def test_alongside_windows(self):
        app, disk = self.run_plan({"mode": "alongside", "gib": 64})
        self.assertEqual(app.step, "done")
        self.assertIs(app.done, True)
        doc = self.sent[-1]
        self.assertEqual((doc["mode"], doc["disk"], doc["esp"]), ("alongside", "/dev/nvme0n1", "/dev/nvme0n1p1"))
        self.assertEqual(doc["shrink"]["partition"], "/dev/nvme0n1p3")
        self.assertEqual(doc["shrink"]["bromigos_bytes"], 64 * 1024 ** 3)
        self.assertEqual((doc["user"], doc["full_name"], doc["hostname"]), ("alex", "Alex Rivera", "alex-pc"))
        self.assertTrue(doc["encrypt"] and doc["other_os"] and doc["desktop"])
        self.assertIsNone(doc["passphrase"])

    def test_erase_plain_second_disk(self):
        app, disk = self.run_plan({"mode": "erase", "disk_index": 1, "encrypt": False})
        doc = self.sent[-1]
        self.assertEqual((doc["mode"], doc["disk"], doc["encrypt"], doc["shrink"]), ("erase", "/dev/sda", False, None))

    def test_server_separate_passphrase(self):
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheInstallerTestsOnly tester@lab"
        app, disk = self.run_plan({"edition": "server", "mode": "erase", "disk_index": 1, "separate": True, "ssh_key": key})
        doc = self.sent[-1]
        self.assertEqual(doc["edition"], "server")
        self.assertFalse(doc["desktop"])
        self.assertTrue(doc["ssh"])
        self.assertFalse(doc["ssh_password"])
        self.assertEqual(doc["ssh_keys"], [key])
        self.assertTrue(doc["firewall"] and doc["auto_updates"])
        self.assertEqual(doc["passphrase"], "disk-pass")
        self.assertEqual(doc["hostname"], "alex-server")
        self.assertTrue(doc["edition_file"].endswith("server.json"))
        self.assertIn('ssh_keys = ["ssh-ed25519', doc["answers_toml"])
        self.assertNotIn("disk-pass", doc["answers_toml"])

    def test_server_key_only_needs_a_key(self):
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                app.a["edition"] = "server"
                await app.show("ssh")
                app.query_one("#ssh").value = True
                await pilot.pause(0.3)
                await pilot.press("ctrl+n")
                return app.step, str(app.query_one("#error").render())
        step, msg = asyncio.run(go())
        self.assertEqual(step, "ssh")
        self.assertIn("needs a key", msg)

    def test_reinstall_keeps_files(self):
        """An installed (encrypted) bromigOS on the second disk: reinstall it, keeping the files."""
        import copy
        with open(os.environ["BROMIGOS_INSTALLER_PROBE"]) as f:
            doc = json.load(f)
        d = doc["disks"][1]
        d["summary"] = "bromigOS · 2 partitions"
        d["partitions"] = [{"path": "/dev/sda1", "size": 2 * 1024 ** 3, "fstype": "vfat", "what": "EFI system partition", "esp": True,
                            "mounted": False, "bitlocker": False, "start": 1048576},
                           {"path": "/dev/sda2", "size": 900 * 10 ** 9, "fstype": "crypto_LUKS", "what": "Encrypted Linux", "esp": False,
                            "mounted": False, "bitlocker": False, "start": 3 * 1024 ** 3}]
        d["options"]["reinstall"] = {"ok": True, "boot": "/dev/sda1", "root": "/dev/sda2", "encrypted": True, "esp": None,
                                     "boot_is_esp": True, "users": [], "label": "Reinstall bromigOS and keep my files",
                                     "words": "A fresh bromigOS system; your home folder and everything in it stay."}
        path = os.path.join(tempfile.mkdtemp(), "probe.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        old = os.environ["BROMIGOS_INSTALLER_PROBE"]
        os.environ["BROMIGOS_INSTALLER_PROBE"] = path
        try:
            async def go():
                app = tui.Installer()
                async with app.run_test(size=(120, 42)) as pilot:
                    await pilot.pause(0.5)
                    app.a["disk"] = "/dev/sda"
                    await app.show("disk")
                    await pilot.pause(0.3)
                    self.assertEqual(app.a["mode"], "reinstall")
                    await pilot.press("ctrl+n")
                    err = str(app.query_one("#error").render())
                    app.query_one("#old_passphrase").value = "old-disk-pass"
                    await pilot.press("ctrl+n")
                    self.assertEqual(app.step, "user")
                    self.assertNotIn("encryption", app.steps())
                    return err
            err = asyncio.run(go())
            self.assertIn("passphrase", err)
        finally:
            os.environ["BROMIGOS_INSTALLER_PROBE"] = old
        from bromigos_installer import common as c
        a = dict(c.defaults(), disk="/dev/sda", mode="reinstall", user="alex", password="p", hostname="h", old_passphrase="old-disk-pass")
        b = c.backend_answers(a, d)
        self.assertEqual((b["mode"], b["encrypt"], b["old_passphrase"]), ("reinstall", True, "old-disk-pass"))
        rows = dict(c.summary(a, d)[0])
        self.assertIn("home folder", rows["Disk"])

    def test_checks_step_says_secure_boot(self):
        """The medium's Secure Boot reader (exit 1: on) becomes the Checks step, in its own words."""
        tool = os.path.join(tempfile.mkdtemp(), "sb")
        with open(tool, "w") as f:
            f.write("#!/bin/sh\n[ \"$1\" = check ] || exit 0\nprintf 'Secure Boot is on.\\n\\nThe installed system can\\047t start with it on yet. How: https://bromigos.org/download#secure-boot\\n'; exit 1\n")
        os.chmod(tool, 0o755)
        os.environ["BROMIGOS_ISO_SECUREBOOT"] = tool
        self.addCleanup(os.environ.pop, "BROMIGOS_ISO_SECUREBOOT", None)

        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                for _ in range(100):
                    if app.probe is not None:
                        break
                    await pilot.pause(0.05)
                await pilot.pause(0.3)
                await pilot.press("ctrl+n")
                await pilot.pause(0.3)
                words = " ".join(str(w.render()) for w in app.query("#step-checks Static"))
                return app.step, words
        step, words = asyncio.run(go())
        self.assertEqual(step, "checks")
        self.assertIn("Secure Boot is on", words)
        self.assertIn("can't start with it on yet", words)
        self.assertIn("bromigos.org/download#secure-boot", words)

    def test_small_screen_scrolls_to_everything(self):
        """At 80×24 the Where step is taller than the screen: the page scrolls, and the split
        at its foot can be brought into view (the step's containers don't clip it)."""
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause(0.5)
                await app.show("disk")
                for _ in range(60):
                    if app.query("#split"):
                        break
                    await pilot.pause(0.05)
                page, split = app.query_one("#page"), app.query_one("#split")
                split.focus()
                await pilot.pause(0.2)
                page.scroll_to_widget(split, animate=False)
                await pilot.pause(0.3)
                return page.max_scroll_y, split.region.bottom <= app.size.height
        scrollable, seen = asyncio.run(go())
        self.assertGreater(scrollable, 0)
        self.assertTrue(seen)

    def test_disks_arriving_mid_draw(self):
        """The disks can arrive while the Where step is drawn: two redraws at once must not collide."""
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                await pilot.pause(0.5)
                await asyncio.gather(app.show("disk"), app.show("disk"), app.fill_disk_detail())
                await pilot.pause(0.3)
                return app.step, len(app.query("#disks"))
        self.assertEqual(asyncio.run(go()), ("disk", 1))

    def test_picking_disks_fast(self):
        """Picking disk after disk with no pause between (a person on a slow console, the VM's
        driver): each pick redraws the choices and Advanced (its Select), and a redraw must
        never tear down one still mounting ("No nodes match '#label'")."""
        async def go():
            app = tui.Installer()
            errors = []
            app._handle_exception = lambda e: errors.append(e)
            async with app.run_test() as pilot:          # 80x24, as tuidrive runs in the VM
                await pilot.pause(0.5)
                for _ in range(50):
                    if app.probe is not None:
                        break
                    await pilot.pause(0.1)
                await app.show("disk")
                app.query_one("#disks").focus()
                for key in ("down", "enter", "up", "enter", "down", "enter", "up", "enter", "down", "enter", "up", "enter"):
                    await pilot.press(key)      # no pause: each pick redraws while the last still mounts
                for mode in ("erase", "alongside", "erase", "alongside"):
                    for _ in range(100):
                        if app.query(f"#mode-{mode}"):
                            break
                        await pilot.pause(0.02)
                    async with app.redraw:      # the card on screen, not one being replaced
                        pass
                    app.query_one(f"#mode-{mode}").value = True
                    await pilot.pause(0)
                async with app.redraw:
                    pass
                await pilot.pause(0.3)
                return errors, app.a["mode"], len(app.query("#adv-fs")), len(app.query("#modes"))
        errors, mode, fs, modes = asyncio.run(go())
        self.assertEqual(errors, [])
        self.assertEqual((mode, fs, modes), ("alongside", 1, 1))

    def test_every_step_at_80x24_and_on_the_console(self):
        """The whole walk, key by key, at the VM driver's 80x24 and as the stick's console
        draws it (TERM=linux: its icons and 16 colours) and a serial line (vt220): a widget id
        that's missing on any step fails here."""
        plans = [{"mode": "alongside", "gib": 40}, {"mode": "erase", "disk_index": 1, "encrypt": False},
                 {"edition": "server", "mode": "erase", "disk_index": 1, "separate": True,
                  "ssh_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheInstallerTestsOnly tester@lab"}]
        for term in ("xterm-256color", "linux", "vt220"):
            for plan in plans:
                with self.subTest(term=term, plan=plan["mode"], edition=plan.get("edition", "desktop")):
                    old = {k: os.environ.get(k) for k in ("TERM", "COLORTERM")}
                    os.environ["TERM"] = term
                    os.environ.pop("COLORTERM", None)
                    try:
                        app, _ = self.run_plan(dict(plan), size=(80, 24))
                    finally:
                        for k, v in old.items():
                            if v is None:
                                os.environ.pop(k, None)
                            else:
                                os.environ[k] = v
                    self.assertEqual(app.step, "done")
                    self.assertIs(app.done, True)

    def test_done_shows_the_secure_boot_code_big(self):
        """When the install set up Secure Boot, the last page carries its code in block letters
        and the blue screen's steps in order."""
        self.addCleanup(setattr, backend, "SECUREBOOT_CODE", backend.SECUREBOOT_CODE)
        backend.SECUREBOOT_CODE = "4821"

        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                app.done = True
                await app.show("done")
                await pilot.pause(0.3)
                if SHOTS:
                    app.save_screenshot(os.path.join(SHOTS, "tui-done-secureboot.svg"))
                return (str(app.query_one("#mok-code").render()), str(app.query_one("#mok-steps").render()))
        code, steps = asyncio.run(go())
        self.assertIn("█", code)
        self.assertIn("Enroll MOK", steps)
        self.assertIn("Type 4821", steps)
        self.assertLess(steps.index("Enroll MOK"), steps.index("Type 4821"))

    def test_disk_badges_fit_whole(self):
        """Each disk's badge ([● HEALTHY], [THIS STICK]) is shown in full at 120x35 and 80x24:
        the description gives way first, then the model."""
        from rich.cells import cell_len

        async def go(size):
            app = tui.Installer()
            async with app.run_test(size=size) as pilot:
                for _ in range(100):
                    if app.probe is not None:
                        break
                    await pilot.pause(0.05)
                await app.show("disk")
                await pilot.pause(0.3)
                return [(rb.label.plain, rb.size.width) for rb in app.query("#disks RadioButton")]
        for size in ((120, 35), (80, 24)):
            for plain, width in asyncio.run(go(size)):
                with self.subTest(size=size, row=plain[:30]):
                    self.assertTrue(plain.rstrip().endswith("]"), plain)
                    self.assertLessEqual(cell_len(plain) + 3, width, plain)   # the radio, its gap

    def test_a_step_opens_at_its_heading(self):
        """On a small screen the page doesn't scroll past a step's heading to its first choice."""
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause(0.5)
                for _ in range(50):
                    if app.probe is not None:
                        break
                    await pilot.pause(0.1)
                await app.show("disk")
                await pilot.pause(0.5)
                return app.query_one("#page").scroll_y
        self.assertEqual(asyncio.run(go()), 0)

    def test_advanced_and_what_will_run(self):
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                await pilot.pause(0.5)
                app.a.update(disk="/dev/sda", mode="erase", user="alex", password="pw", hostname="alex-pc")
                await app.show("disk")
                await pilot.pause(0.3)
                app.query_one("#advanced").collapsed = False
                await pilot.pause(0.2)
                app.query_one("#adv-fs").value = "ext4"
                app.query_one("#adv-kernel").value = "linux-lts"
                app.query_one("#adv-zram").value = False
                await pilot.pause(0.2)
                await app.show("summary")
                await pilot.pause(0.2)
                app.query_one("#what").collapsed = False
                for _ in range(40):
                    await pilot.pause(0.1)
                    if "archinstall" in str(app.what.render()):
                        break
                return dict(app.a["advanced"]), str(app.what.render())
        adv, what = asyncio.run(go())
        self.assertEqual(adv, {"fs": "ext4", "kernel": "linux-lts", "zram": False})
        self.assertIn("archinstall --config", what)
        self.assertIn("********", what)
        self.assertNotIn("rollback setup", what)       # ext4: no snapshots
        doc = common.backend_answers(dict(common.defaults(), disk="/dev/sda", mode="erase", user="a", password="p",
                                          hostname="h", advanced=adv), None)
        self.assertEqual(doc["advanced"]["kernel"], "linux-lts")

    def test_failure_is_plain(self):
        os.environ["BROMIGOS_INSTALLER_FAKE_FAIL"] = "1"
        try:
            app, disk = self.run_plan({"mode": "erase", "disk_index": 1})
        finally:
            del os.environ["BROMIGOS_INSTALLER_FAKE_FAIL"]
        self.assertEqual(app.step, "done")
        self.assertIn("didn't finish", app.done)

    def test_every_control_has_a_hint(self):
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                await drive(app, pilot, {"mode": "alongside"})
                missing = []
                for sid in app.steps():
                    if sid in ("install", "done"):
                        continue
                    await app.show(sid)
                    await pilot.pause()
                    for w in app.query("#steps Input, #steps Select, #steps RadioSet, #steps RadioButton, #steps Switch, "
                                       "#steps Checkbox, #steps Button, #steps Split, #nav Button"):
                        if w.display and not w.tooltip:
                            missing.append(f"{sid}: {w!r}")
                return missing
        self.assertEqual(asyncio.run(go()), [])

    def test_strength_meter_levels(self):
        """The strength meter: none lit before anything's typed, then one, two or three segments
        for weak, fair and strong, always the same width (one thickness, like the disk map)."""
        import bromigos_textual as BT
        self.assertEqual([tui.strength_level(p) for p in ("", "abc", "correct-horse", "Correct-Horse-9!")], [0, 1, 2, 3])
        widths = set()
        for level in range(4):
            m = BT.meter(level, 3, 17)
            widths.add(m.cell_len)
            lit = [s for s in m.spans if str(s.style).startswith("on ") and m.plain[s.start:s.end].strip() == ""
                   and "on " + BT._dim(BT.palette()["muted"]) != str(s.style)]
            self.assertEqual(len(lit), level, f"level {level}")
            self.assertNotIn("\n", m.plain)
        self.assertEqual(len(widths), 1)

    def test_briefing_changes_jump_to_their_step(self):
        """Ready to install: each Change (its button or its number key) opens that step, and
        Continue comes straight back to the summary."""
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                await drive(app, pilot, {"mode": "alongside"})
                keys = dict(app.brief_keys)
                got = []
                for n, sid in sorted(keys.items()):
                    await pilot.press(n)
                    await pilot.pause(0.2)
                    got.append((sid, app.step, str(app.query_one("#next").label)))
                    await pilot.press("ctrl+n")
                    await pilot.pause(0.2)
                    got.append(("summary", app.step, ""))
                app.query_one("#edit-user").press()
                await pilot.pause(0.3)
                got.append(("user", app.step, ""))
                return keys, got
        keys, got = asyncio.run(go())
        self.assertEqual(set(keys.values()) >= {"welcome", "keyboard", "disk", "user", "encryption"}, True, keys)
        for want, step, label in got:
            self.assertEqual(want, step)
            if want != "summary" and label:
                self.assertEqual(label, "Back to summary")

    def test_bitlocker_asks_for_the_key_first(self):
        """Windows with BitLocker, kept alongside: a step that asks for its recovery key to be
        saved, and won't go on until it's said to be."""
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                for _ in range(60):
                    if app.probe is not None:
                        break
                    await pilot.pause(0.05)
                app.probe["disks"][0]["bitlocker"] = True
                app.a.update(disk="/dev/nvme0n1", mode="alongside")
                steps = app.steps()
                await app.show("bitlocker")
                await pilot.pause(0.2)
                await pilot.press("ctrl+n")
                first = (app.step, str(app.query_one("#error").render()))
                app.query_one("#bitlocker-saved").value = True
                await pilot.pause(0.1)
                await pilot.press("ctrl+n")
                app.a["mode"] = "erase"
                return steps, first, app.step, app.steps()
        steps, first, then, erase_steps = asyncio.run(go())
        self.assertIn("bitlocker", steps)
        self.assertEqual(first[0], "bitlocker")
        self.assertIn("recovery key", first[1])
        self.assertEqual(then, "user")
        self.assertNotIn("bitlocker", erase_steps)

    def test_wrong_input_says_what_to_do(self):
        async def go():
            app = tui.Installer()
            async with app.run_test(size=(120, 42)) as pilot:
                await pilot.pause(0.3)
                app.query_one("#timezone").value = "Mars/Olympus"
                await pilot.press("ctrl+n")
                tz = str(app.query_one("#error").render())
                return app.step, tz
        step, msg = asyncio.run(go())
        self.assertEqual(step, "welcome")
        self.assertIn("time zone", msg)


class AnswerFile(unittest.TestCase):
    """An answer file: the countdown, then the install with its answers; a wrong one is said plainly."""

    def run_file(self, text):
        if not HAVE:
            self.skipTest("textual isn't installed")
        path = os.path.join(tempfile.mkdtemp(), "install.toml")
        with open(path, "w") as f:
            f.write(text)
        os.environ["BROMIGOS_ANSWERS"] = path
        sent = []
        real = backend.Install.__init__

        def spy(inst, doc, *a, **k):
            sent.append(doc)
            real(inst, doc, *a, **k)
        backend.Install.__init__ = spy
        try:
            async def go():
                app = tui.Installer()
                async with app.run_test(size=(120, 42)) as pilot:
                    for _ in range(120):
                        await pilot.pause(0.1)
                        if app.step == "done":
                            break
                    return app.step, str(app.query_one("#error").render()), app.done
            return asyncio.run(go()), sent
        finally:
            backend.Install.__init__ = real
            del os.environ["BROMIGOS_ANSWERS"]

    def test_unattended_server(self):
        (step, err, done), sent = self.run_file('[install]\nedition = "server"\ndisk = "/dev/sda"\nmode = "erase"\n'
                                                'user = "tester"\npassword = "tester-pass"\nkeyboard = "de"\n'
                                                'timezone = "Europe/Berlin"\nssh = true\nssh_password = true\ncountdown = 1\n')
        self.assertEqual(step, "done", err)
        doc = sent[-1]
        self.assertEqual((doc["edition"], doc["disk"], doc["keymap"], doc["timezone"]), ("server", "/dev/sda", "de-latin1", "Europe/Berlin"))
        self.assertTrue(doc["ssh_password"])
        self.assertEqual(doc["hostname"], "tester-server")

    def test_wrong_file_asks_instead(self):
        (step, err, done), sent = self.run_file('[install]\ndisk = "/dev/sdz"\nmode = "erase"\nuser = "tester"\n'
                                                'password = "x1234"\ncountdown = 0\n')
        self.assertEqual(step, "welcome")
        self.assertIn("/dev/sdz", err)
        self.assertEqual(sent, [])


class Plain(unittest.TestCase):
    """The plain questions (a screen reader's): bromigOS Server on the empty disk, by typed answers."""

    def test_server_by_questions(self):
        if not HAVE:
            self.skipTest("textual isn't installed")
        import builtins
        import getpass
        from unittest import mock
        from bromigos_installer import plain
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheInstallerTestsOnly x"
        answers = iter(["", "", "2", "", "2", "", "Test Er", "tester", "", "", "", "yes", "", key, "", "", "yes", "no"])
        sent = []
        real = backend.Install.__init__

        def spy(inst, doc, *a, **k):
            sent.append(doc)
            real(inst, doc, *a, **k)
        out = []
        with mock.patch.object(builtins, "input", lambda prompt="": (out.append(prompt), next(answers))[1]), \
                mock.patch.object(getpass, "getpass", lambda prompt="": "tester-pass"), \
                mock.patch.object(builtins, "print", lambda *a, **k: out.append(" ".join(map(str, a)))), \
                mock.patch.object(backend.Install, "__init__", spy):
            rc = plain.main()
        self.assertEqual(rc, 0, "\n".join(out[-20:]))
        doc = sent[-1]
        self.assertEqual((doc["edition"], doc["disk"], doc["mode"], doc["user"]), ("server", "/dev/sda", "erase", "tester"))
        self.assertEqual(doc["ssh_keys"], [key])
        self.assertTrue(doc["firewall"] and doc["auto_updates"] and doc["encrypt"])
        self.assertTrue(any("percent" in line for line in out))


class ServerWelcome(unittest.TestCase):
    """bromigOS Server's welcome tour (bin/bromigos-welcome-console): quiet unless pending; every step draws."""
    BIN = os.path.join(HERE, "../../../bin/bromigos-welcome-console")

    def test_quiet_unless_pending(self):
        import subprocess
        env = dict(os.environ, XDG_STATE_HOME=tempfile.mkdtemp())
        r = subprocess.run([sys.executable, self.BIN, "--if-pending"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_every_step_draws(self):
        if not HAVE:
            self.skipTest("textual isn't installed")
        import subprocess
        out = tempfile.mkdtemp()
        env = dict(os.environ, PYTHONPATH=os.path.join(HERE, "../../../lib"))
        r = subprocess.run([sys.executable, self.BIN, "--render", out], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(sorted(os.listdir(out)), sorted(f"server-welcome-{s}.svg" for s in ("network", "ssh", "vector", "lab", "phone", "tour", "done")))

    def test_phone_pairs_from_the_agents_events(self):
        """Pair your phone shows brodec-machine pair --json's code, then ticks when it's paired."""
        if not HAVE:
            self.skipTest("textual isn't installed")
        import subprocess
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "bin"))
        with open(os.path.join(tmp, "bin", "brodec-machine"), "w") as f:
            f.write("#!/bin/sh\n[ \"$1\" = pair ] || exit 2\n"
                    "echo '{\"event\":\"code\",\"qr\":\"https://example.org/p\",\"qr_text\":\"QRQR\",\"user_code_display\":\"KPGG-ZFVT\"}'\n"
                    "sleep 2\necho '{\"event\":\"paired\",\"owner\":\"@alex:example.org\"}'\n")
        os.chmod(os.path.join(tmp, "bin", "brodec-machine"), 0o755)
        open(os.path.join(tmp, "machine.toml"), "w").close()
        env = dict(os.environ, PYTHONPATH=os.path.join(HERE, "../../../lib"), PATH=os.path.join(tmp, "bin") + ":" + os.environ["PATH"],
                   BRODEC_MACHINE_TOML=os.path.join(tmp, "machine.toml"))
        r = subprocess.run([sys.executable, self.BIN, "--live-shots", tmp, "phone", "1,4", "--size", "100x40"], env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        first = open(os.path.join(tmp, "server-welcome-phone-1s.svg")).read()
        then = open(os.path.join(tmp, "server-welcome-phone-4s.svg")).read()
        self.assertIn("KPGG-ZFVT", first)
        self.assertIn("Paired", then)
        self.assertIn("Allow", then)


class Words(unittest.TestCase):
    def test_secure_boot_from_the_medium(self):
        from bromigos_installer import common as c
        tool = os.path.join(tempfile.mkdtemp(), "sb")
        with open(tool, "w") as f:
            f.write("#!/bin/sh\ncase $1 in check) [ -e \"$0.off\" ] && exit 0; printf 'Secure Boot is on.\\n\\nTurn it off after installing. How: https://bromigos.org/download#secure-boot\\n'; exit 1 ;; esac\n")
        os.chmod(tool, 0o755)
        os.environ["BROMIGOS_ISO_SECUREBOOT"] = tool
        try:
            got = c.secure_boot()
        finally:
            del os.environ["BROMIGOS_ISO_SECUREBOOT"]
        self.assertEqual((got["level"], got["title"]), ("warn", "Secure Boot is on"))
        self.assertEqual(got["what"], "Turn it off after installing.")
        self.assertIn("bromigos.org/download#secure-boot", got["fix"])
        open(tool + ".off", "w").close()            # check exits 0: off, or a BIOS start
        os.environ["BROMIGOS_ISO_SECUREBOOT"] = tool
        try:
            self.assertIsNone(c.secure_boot())
        finally:
            del os.environ["BROMIGOS_ISO_SECUREBOOT"]

    def test_secure_boot_set_up_by_the_install(self):
        """bromigos-secureboot on the medium: check exits 0 with its words, a note (not a
        warning: nothing stops or warns), and the last page says how to approve the key."""
        from bromigos_installer import common as c
        tool = os.path.join(tempfile.mkdtemp(), "sb")
        with open(tool, "w") as f:
            f.write("#!/bin/sh\ncase $1 in check) printf 'Secure Boot is on.\\n\\nSecure Boot can stay on. How: https://bromigos.org/download#secure-boot\\n'; exit 0 ;; esac\n")
        os.chmod(tool, 0o755)
        os.environ["BROMIGOS_ISO_SECUREBOOT"] = tool
        try:
            got = c.secure_boot()
        finally:
            del os.environ["BROMIGOS_ISO_SECUREBOOT"]
        self.assertEqual((got["level"], got["what"]), ("info", "Secure Boot can stay on."))
        self.assertIsNone(c.secureboot_done(None))
        line = c.secureboot_done("4827")
        for words in ("Enroll MOK", "Continue", "Yes", "4827", "Reboot", "ENROLL_THIS_KEY_FOR_THIS_PC.cer"):
            self.assertIn(words, line)

    def test_boot_parameters(self):
        from bromigos_installer import common as c
        self.assertTrue(c.wants_text(["bromigos.install", "bromigos.edition=server"]))
        self.assertTrue(c.wants_text(["bromigos.install", "bromigos.text"]))
        self.assertTrue(c.wants_text(["bromigos.install=text"]))
        self.assertFalse(c.wants_text(["bromigos.install", "bromigos.edition=desktop"]))
        self.assertFalse(c.wants_text(["bromigos.install"]))
        real = c.cmdline
        try:
            c.cmdline = lambda: ["bromigos.install", "bromigos.edition=server"]
            self.assertEqual((c.boot_edition(), c.defaults()["edition"]), ("server", "server"))
            c.cmdline = lambda: ["bromigos.install", "bromigos.edition=fieldkit"]
            self.assertEqual(c.boot_edition(), "server")
            c.cmdline = lambda: ["bromigos.install"]
            self.assertEqual((c.boot_edition(), c.defaults()["edition"]), (None, "desktop"))
        finally:
            c.cmdline = real

    def test_checks(self):
        sys.path.insert(0, LIB)
        from bromigos_installer import common as c
        self.assertIsNone(c.check_username("alex"))
        self.assertIn("small letters", c.check_username("Alex R"))
        self.assertIn("used by the system", c.check_username("root"))
        self.assertIsNone(c.check_hostname("alex-pc"))
        self.assertIn("no spaces", c.check_hostname("alex pc"))
        self.assertIn("aren't the same", c.check_password("abcd", "abce"))
        self.assertEqual(c.suggest_username("Zoë Ångström"), "zoe")
        self.assertEqual(c.strength("correct horse battery staple")[0], "strong")


if __name__ == "__main__":
    unittest.main()
