"""`bromigos server` and the apps' data (docs/server.md, "Where the apps keep their data"): the
status line is the lab's own answer (bromigos lab app-data, bromigos-lab's: its tests are
homelab/tests/test_appdata.py), and `bromigos server app-data` is that command."""
import json

from test_server import Rig

ON_SYSTEM_DISK = {
    "path": "/srv/apps", "pool": "/srv/data", "pool_mounted": True, "where": "system", "state": "not-on-pool",
    "has_data": True, "move": "", "raid1": True, "leftover": "",
    "words": ["on the system disk, not the data disks: one copy, not two",
              "sudo bromigos lab app-data move puts it on the data disks (--dry-run shows what it would do)"]}


class AppData(Rig):
    def test_the_status_says_where_the_apps_keep_their_data(self):
        (self.fake / "app-data.json").write_text(json.dumps(ON_SYSTEM_DISK))
        out = self.run_server("status").stdout
        self.assertIn("  App data     on the system disk, not the data disks: one copy, not two\n"
                      "               sudo bromigos lab app-data move puts it on the data disks (--dry-run shows what it would do)\n", out)
        self.assertEqual(json.loads(self.run_server("status", "--json").stdout)["app_data"], ON_SYSTEM_DISK)

    def test_no_answer_from_the_lab_is_no_line_and_no_failure(self):
        for text in (None, "not json", "[]"):
            with self.subTest(answer=text):
                if text is not None:
                    (self.fake / "app-data.json").write_text(text)
                r = self.run_server("status")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("App data", r.stdout)
                self.assertEqual(json.loads(self.run_server("status", "--json").stdout)["app_data"], {})

    def test_app_data_is_the_labs_command(self):
        for args, lab in ((["app-data"], "bromigos-lab app-data"), (["app-data", "move", "--dry-run"], "bromigos-lab app-data move --dry-run"),
                          (["app-data", "remove-old"], "bromigos-lab app-data remove-old")):
            with self.subTest(args=args):
                (self.fake / "log").write_text("")
                r = self.run_server(*args)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.log().strip(), lab)
        (self.fake / "app-data.json").write_text(json.dumps(ON_SYSTEM_DISK))
        self.assertEqual(json.loads(self.run_server("app-data", "status", "--json").stdout), ON_SYSTEM_DISK)
