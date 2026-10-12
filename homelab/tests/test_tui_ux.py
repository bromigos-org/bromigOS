"""Shared dialogs exercised without a desktop, network or real service actions."""
import asyncio
import unittest
from unittest import mock

try:
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Input, Select
    from bromigos_homelab.tuiux import Dialog, HelpDialog, UXApp
except ImportError:
    UXApp = None


if UXApp is not None:
    class Form(Dialog):
        def compose(self):
            with Vertical():
                yield Input(id="words")
                yield Select([("One", "one"), ("Two", "two")], value="one", id="option", allow_blank=False)
                with Horizontal():
                    yield Button("Cancel", id="cancel")
                    yield Button("Apply", id="apply")

        def on_button_pressed(self, event):
            self.dismiss(self.query_one(Input).value if event.button.id == "apply" else None)

    class TestApp(UXApp):
        BINDINGS = [Binding("x", "danger", "Change", priority=True),
                    Binding("question_mark", "help", "Help"),
                    Binding("ctrl+c", "interrupt", "Quit", priority=True)]
        HELP = [(f"Section {n}", "A long section\n" * 6) for n in range(8)]

        def compose(self):
            yield Button("Open form", id="open")

        def on_mount(self):
            self.changed = 0
            self.results = []

        def action_danger(self):
            self.changed += 1

        def open_form(self):
            self.push_screen(Form(), self.results.append)


@unittest.skipIf(UXApp is None, "needs Textual")
class KeyboardDialogs(unittest.TestCase):
    def test_text_tabs_confirmation_and_background_isolation(self):
        async def run():
            app = TestApp()
            async with app.run_test(size=(80, 24)) as pilot:
                app.open_form()
                await pilot.pause()
                await pilot.press("q", "h", "j", "k", "l", "H", "L", "[", "]", "x")
                self.assertEqual(app.screen.query_one(Input).value, "qhjklHL[]x")
                self.assertEqual(app.changed, 0)
                await pilot.press("tab", "tab")
                self.assertEqual(app.focused.id, "cancel")
                await pilot.press("right", "enter")
                await pilot.pause()
                self.assertEqual(app.results, ["qhjklHL[]x"])
                self.assertEqual(app.focused.id, "open")
        asyncio.run(run())

    def test_escape_closes_dropdown_then_dialog_and_ctrl_c_cancels(self):
        async def run():
            app = TestApp()
            async with app.run_test(size=(80, 24)) as pilot:
                app.open_form()
                await pilot.pause()
                await pilot.press("tab", "enter")
                select = app.screen.query_one(Select)
                self.assertTrue(select.expanded)
                await pilot.press("escape")
                self.assertFalse(select.expanded)
                self.assertIsInstance(app.screen, Form)
                await pilot.press("enter", "ctrl+c")
                await pilot.pause()
                self.assertEqual(app.results, [None])
                self.assertFalse(app._exit)
                self.assertEqual(app.focused.id, "open")
        asyncio.run(run())

    def test_help_starts_at_top_with_close_visible_at_small_sizes(self):
        async def run(size):
            app = TestApp()
            async with app.run_test(size=size) as pilot:
                await pilot.press("question_mark")
                await pilot.pause()
                self.assertIsInstance(app.screen, HelpDialog)
                scroll = app.screen.query_one("#tui-help-scroll")
                self.assertEqual(scroll.scroll_y, 0)
                button = app.screen.query_one("#help-close")
                self.assertGreater(button.region.width, 0)
                self.assertLessEqual(button.region.right, size[0])
                self.assertLessEqual(button.region.bottom, size[1])
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app.focused.id, "open")
        for size in ((80, 24), (60, 18), (40, 12)):
            with self.subTest(size=size):
                asyncio.run(run(size))

    def test_den_results_preserve_typing_focus_and_buttons_fit(self):
        from bromigos_homelab import tvplayui as den

        async def run(size):
            app = TestApp()
            async with app.run_test(size=size) as pilot:
                app.push_screen(den.PlayOnDen(), app.results.append)
                await app.workers.wait_for_complete()
                await pilot.pause()
                screen = app.screen
                field = screen.query_one("#den-search", Input)
                field.focus()
                await pilot.pause()
                screen.got(screen.serial, [{"id": "movie", "title": "Example film", "kind": "movie"}], None)
                self.assertIs(app.focused, field)
                await pilot.press("q", "j", "h")
                self.assertEqual(field.value, "qjh")
                for button in screen.query(Button):
                    self.assertLessEqual(button.region.right, size[0])
                await pilot.press("enter")
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual(app.focused.id, "den-results")
                await pilot.press("escape")
                await pilot.pause()
                self.assertEqual(app.results, [None])
        with mock.patch.object(den.TVP, "search", return_value=[]):
            for size in ((80, 24), (40, 12)):
                with self.subTest(size=size):
                    asyncio.run(run(size))


if __name__ == "__main__":
    unittest.main()
