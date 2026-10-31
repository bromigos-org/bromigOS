"""The lab console's NETWORK tab, driven by Textual's pilot: members, Add a machine (its join code and
QR), Approve a device, and Remove with Keep as the default.

    PYTHONPATH=lib:../lib python -m unittest test_labnet_tui

Skipped without Textual (python-textual).
"""
import asyncio
import json
import os
import unittest

try:
    import textual  # noqa: F401
    from textual.widgets import Button, Input, Static
    from bromigos_homelab import tui
    from bromigos_homelab import labnet as L
except ImportError:
    tui = None

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = 1793414000


def fixture(name):
    with open(os.path.join(HERE, "fixtures", "labnet", name)) as f:
        return json.load(f)


class Source:
    """Just enough lab for the dashboard, and a lab network from Headscale's recorded answers."""

    def __init__(self, configured=True):
        self.configured = configured
        self.removed, self.approved, self.joined = [], [], []

    def status(self):
        return {"configured": False, "state": "empty", "cards": [], "generatedAt": NOW, "seconds": 0.1}

    def inventory(self):
        return {"gpus": [], "servers": [], "errors": {}}

    def jobs(self):
        return {"jobs": [], "service": "running"}

    def job_log(self, jid):
        return ""

    def doctor(self):
        return {"configured": False, "findings": [], "summary": {}}

    def kinds(self):
        return []

    def network_status(self):
        if not self.configured:
            return {"configured": False}
        phone = dict(fixture("nodes.json")[0], id=2, online=False, tags=[], given_name="pixel",
                     user={"id": 1, "name": "alice"}, last_seen={"seconds": NOW - 7200})
        devs = [d for d in L.devices(fixture("nodes.json") + [phone], now=NOW) if d["id"] not in self.removed]
        return {"configured": True, "name": "Home", "login_server": "https://net.example.org", "devices": devs,
                "codes": L.codes(fixture("preauthkeys.json"), now=NOW),
                "summary": f"{len(devs)} devices, 1 online, 2 unused join codes"}

    def network_join(self, tag, expires):
        self.joined.append((tag, expires))
        from bromigos_homelab import reach as R
        b = R.encode("https://net.example.org", "hskey-auth-" + "a" * 40, tags=[f"tag:{tag}"])
        return {"bundle": b, "tags": [f"tag:{tag}"], "expires": "2026-10-31T03:31:08Z", "qr": L.qr_lines(b),
                "command": "sudo tailscale up --login-server https://net.example.org --auth-key hskey-auth-…"}

    def network_remove(self, device_id):
        self.removed.append(device_id)
        return {"words": "box1 is off the lab network."}

    def network_approve(self, code):
        self.approved.append(code)
        return {"words": "pixel is on the lab network, as alice's device."}


@unittest.skipUnless(tui, "needs python-textual")
class NetworkTab(unittest.TestCase):
    def drive(self, source, script):
        async def go():
            app = tui.LabApp(source=source, clock=lambda: NOW, interval=3600)
            async with app.run_test(size=(140, 48)) as pilot:
                await pilot.pause()
                await pilot.press("6")
                for _ in range(20):
                    await pilot.pause(0.05)
                    if app.net_doc is not None:
                        break
                await script(app, pilot)
        asyncio.run(go())

    def test_members_and_codes(self):
        async def script(app, pilot):
            self.assertEqual(app.query_one("#tabs").active, "network")
            summary = str(app.query_one("#netsum", Static).render())
            self.assertIn("https://net.example.org", summary)
            t = app.query_one("#nettable")
            self.assertEqual(t.row_count, 4, "two devices and two unused join codes")
            first = [str(c) for c in t.get_row_at(0)]
            self.assertEqual(first[1:4], ["box1", "server", "100.64.0.1"])
            second = [str(c) for c in t.get_row_at(1)]
            self.assertEqual(second[1:3], ["pixel", "alice's device"])
            self.assertEqual(second[4], "seen 2h ago")
            self.assertIn("x removes it", t.hints[0])
            self.assertTrue(all(b.tooltip for b in app.query("#net-actions Button")), "every button explains itself")
        self.drive(Source(), script)

    def test_add_a_machine_shows_the_code_and_qr(self):
        src = Source()

        async def script(app, pilot):
            await pilot.press("A")
            await pilot.pause()
            self.assertIsInstance(app.screen, tui.AddMachine)
            app.screen.query_one("#net-go", Button).press()
            for _ in range(40):
                await pilot.pause(0.05)
                if isinstance(app.screen, tui.JoinCode):
                    break
            self.assertIsInstance(app.screen, tui.JoinCode)
            await pilot.pause()
            self.assertEqual(src.joined, [("server", "24h")])
            bundle = str(app.screen.query_one("#join-bundle", Static).render())
            self.assertTrue(bundle.startswith("bromigos-net:1:"))
            if L.qr_lines("x"):
                self.assertTrue(app.screen.query("#join-qr"), "the QR code is drawn")
            app.screen.query_one("#join-done", Button).press()
            await pilot.pause()
            self.assertNotIsInstance(app.screen, tui.JoinCode)
        self.drive(src, script)

    def test_remove_defaults_to_keep(self):
        src = Source()

        async def script(app, pilot):
            app.query_one("#nettable").focus()
            await pilot.press("x")
            await pilot.pause()
            self.assertIsInstance(app.screen, tui.RemoveDevice)
            self.assertEqual(app.screen.focused.id, "keep-device")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(src.removed, [], "Enter on Keep removes nothing")
            await pilot.press("x")
            await pilot.pause()
            app.screen.query_one("#confirm-remove-device", Button).press()
            for _ in range(40):
                await pilot.pause(0.05)
                if src.removed:
                    break
            self.assertEqual(src.removed, [1])
            for _ in range(40):
                await pilot.pause(0.05)
                if app.query_one("#nettable").row_count == 3:
                    break
            self.assertEqual(app.query_one("#nettable").row_count, 3)
        self.drive(src, script)

    def test_approve_a_device(self):
        src = Source()

        async def script(app, pilot):
            await pilot.press("p")
            await pilot.pause()
            self.assertIsInstance(app.screen, tui.ApproveDevice)
            app.screen.query_one("#approve-code", Input).value = "AbCd-1234"
            app.screen.query_one("#approve-go", Button).press()
            for _ in range(40):
                await pilot.pause(0.05)
                if src.approved:
                    break
            self.assertEqual(src.approved, ["AbCd-1234"])
        self.drive(src, script)

    def test_no_network_yet(self):
        async def script(app, pilot):
            self.assertIn("bromigos lab network setup", str(app.query_one("#netsum", Static).render()))
            self.assertTrue(app.query_one("#net-add", Button).disabled)
            await pilot.press("A")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, tui.AddMachine)
        self.drive(Source(configured=False), script)


if __name__ == "__main__":
    unittest.main()
