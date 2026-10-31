"""`bromigos fieldkit repair …`: the scriptable layer, with a stand-in engine."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from bromigos_fieldkit import cli


class Scripted(unittest.TestCase):
    def run_cli(self, argv, answers):
        calls = []

        def call(args, stdin=None):
            calls.append(list(args))
            return answers(args)
        out = io.StringIO()
        with mock.patch.object(cli, "engine_call", side_effect=call), mock.patch.object(cli, "need_root"), redirect_stdout(out):
            rc = cli.main(argv)
        return rc, calls, out.getvalue()

    def test_dry_run_shows_commands_and_runs_nothing(self):
        rc, calls, out = self.run_cli(["repair", "rollback", "3", "--dry-run"],
                                      lambda a: {"ok": True, "commands": ["btrfs subvolume snapshot /x/@.snapshots/3/snapshot /x/@"], "touches": ["the @ subvolume"]})
        self.assertEqual(calls, [["plan", "rollback", "3"]])
        self.assertIn("$ btrfs subvolume snapshot", out)
        self.assertIn("touches: the @ subvolume", out)

    def test_yes_runs_after_the_plan(self):
        rc, calls, out = self.run_cli(["repair", "boot-menu", "--yes"], lambda a: {"ok": True, "message": "done", "commands": []})
        self.assertEqual(calls, [["plan", "grub-repair"], ["grub-repair"]])

    def test_without_yes_and_no_terminal_nothing_runs(self):
        with mock.patch.object(cli.sys.stdin, "isatty", return_value=False):
            rc, calls, out = self.run_cli(["repair", "boot-menu"], lambda a: {"ok": True, "commands": []})
        self.assertEqual(calls, [["plan", "grub-repair"]])
        self.assertEqual(rc, 1)

    def test_black_screen_json(self):
        doc = {"ok": True, "findings": [{"id": "0", "title": "t", "ok": False, "fix": "Move it out", "commands": ["mv a b"], "touches": ["a"]}]}
        rc, calls, out = self.run_cli(["repair", "black-screen", "--json"], lambda a: doc)
        self.assertEqual(json.loads(out)["findings"][0]["commands"], ["mv a b"])


if __name__ == "__main__":
    unittest.main()
