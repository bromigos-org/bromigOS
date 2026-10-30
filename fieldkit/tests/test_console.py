"""The first console's loop: a missing or failing menu is never retried in a loop."""
import io
import os
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

from bromigos_fieldkit import cli


class Console(unittest.TestCase):
    def run_console(self, menu, rounds):
        calls = []
        real = cli.subprocess.call

        def call(argv, *a, **k):
            calls.append(argv)
            if argv[0] == "/bin/true-shell":
                return 0
            return real(argv, *a, **k)
        env = {"BROMIGOS_FIELDKIT_MENU": menu, "BROMIGOS_FIELDKIT_SHELL": "/bin/true-shell"}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(cli.subprocess, "call", side_effect=call), \
                mock.patch("bromigos_fieldkit.medium.remote_state", return_value={"on": False}), \
                mock.patch.object(cli.time, "sleep"), redirect_stdout(out):
            cli.console(max_rounds=rounds)
        return calls, out.getvalue()

    def test_missing_menu_stops_after_three_and_says_so_once_each(self):
        calls, out = self.run_console("no-such-fieldkit-menu", 10)
        menus = [c for c in calls if c[0] != "/bin/true-shell"]
        self.assertEqual(menus, [])                      # never executed: it isn't there
        self.assertEqual(out.count("Field Kit's menu didn't open"), 3)
        self.assertIn("won't be opened again by itself", out)
        self.assertEqual(len([c for c in calls if c[0] == "/bin/true-shell"]), 10)

    def test_failing_menu_is_tried_three_times_only(self):
        calls, out = self.run_console("false", 8)
        self.assertEqual(len([c for c in calls if c == ["false"]]), 3)

    def test_working_menu_comes_back_after_the_shell(self):
        calls, out = self.run_console("true", 3)
        self.assertEqual(len([c for c in calls if c == ["true"]]), 3)
        self.assertIn("The menu is closed", out)


if __name__ == "__main__":
    unittest.main()
