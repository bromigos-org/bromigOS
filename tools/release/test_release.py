"""Tests for the release tool (python3 -m unittest discover -s tools/release): versions, the
files a release writes, the GitHub Release text, the privacy rules and the checksums.
Everything runs on throwaway git repositories; nothing reaches a network."""
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard  # noqa: E402
import release  # noqa: E402

ENV = {"GIT_AUTHOR_NAME": "Jane Q. Hacker", "GIT_AUTHOR_EMAIL": "jane@example.org",
       "GIT_COMMITTER_NAME": "Jane Q. Hacker", "GIT_COMMITTER_EMAIL": "jane@example.org"}


def sh(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **ENV}).stdout.strip()


def repo_with(tags_at):
    d = tempfile.mkdtemp()
    sh(d, "init", "-q", "-b", "main")
    for i, tag in enumerate(tags_at):
        sh(d, "commit", "-q", "--allow-empty", "-m", f"core: change {i}")
        if tag:
            sh(d, "tag", "-a", tag, "-m", tag)
    return d


PLAN = {"version": "0.1.2", "tag": "v0.1.2-rc1", "kind": "rc", "rc": 1, "since": "v0.1.1", "date": "2026-10-09",
        "bromigos": {"base": "a" * 40, "since": "v0.1.1"}, "vector": {"base": "b" * 40, "since": "v0.1.1"}}
NOTES = {"drafted_by": "test", "bromigos_commits": 3, "vector_commits": 1, "private_patterns": True,
         "bromigos": {"summary": "Better themes.", "before_you_update": [], "new": ["A new thing."],
                      "improved": [], "fixed": ["A fix."], "known_issues": []},
         "vector": {"summary": "VECTOR listens.", "before_you_update": ["Log out once."], "new": [],
                    "improved": ["VECTOR answers faster."], "fixed": [], "known_issues": []},
         "bromigos_changelog": "### Desktop\n\n- desktop: x ([abcdef1](u))",
         "vector_changelog": "### Added\n\n- Y ([abcdef2](u))"}


class Versions(unittest.TestCase):
    def test_bumps_and_rc_numbers(self):
        d = repo_with(["v0.1.0", "v0.1.1", None])
        with mock.patch.object(release, "ROOT", d):
            p = release.plan_release("patch", "stable", None)
            self.assertEqual((p["version"], p["tag"], p["since"]), ("0.1.2", "v0.1.2", "v0.1.1"))
            self.assertEqual(release.plan_release("minor", "stable", None)["tag"], "v0.2.0")
            self.assertEqual(release.plan_release("major", "rc", None)["tag"], "v1.0.0-rc1")
            sh(d, "tag", "v0.1.2-rc1")
            sh(d, "commit", "-q", "--allow-empty", "-m", "desktop: more")
            sh(d, "tag", "v0.1.2-rc2")
            # rcs don't move the base: the next patch is still 0.1.2, its third candidate
            self.assertEqual(release.plan_release("patch", "rc", None)["tag"], "v0.1.2-rc3")
            self.assertEqual(release.plan_release("patch", "stable", None)["since"], "v0.1.1")
            with self.assertRaises(SystemExit):
                release.plan_release("0.1.1", "stable", None)        # not newer
            sh(d, "tag", "v0.1.2")
            with self.assertRaises(SystemExit):
                release.plan_release("0.1.2", "rc", None)            # released already

    def test_vector_tags_count(self):
        b, v = repo_with(["v0.1.1"]), repo_with(["v0.1.1", None])
        sh(v, "tag", "v0.1.2-rc1")
        with mock.patch.object(release, "ROOT", b):
            p = release.plan_release("patch", "rc", v)
        self.assertEqual(p["tag"], "v0.1.2-rc2")
        self.assertEqual(p["vector"]["since"], "v0.1.1")


class Files(unittest.TestCase):
    def test_notes_section(self):
        s = release.notes_section(PLAN, NOTES)
        self.assertTrue(s.startswith("## 0.1.2\n<!-- release: 0.1.2-rc1 -->\n"))
        self.assertIn("Release candidate 0.1.2-rc1", s)
        self.assertIn("### Before you update\n\n- VECTOR: Log out once.", s)
        self.assertIn("### New\n\n- A new thing.", s)
        self.assertNotIn("\n### Improved", s)          # bromigOS has none; VECTOR's are its own
        self.assertIn("### VECTOR\n\nVECTOR listens.\n\n#### Improved\n\n- VECTOR answers faster.", s)
        self.assertIn("### Known issues\n\nNone known.", s)

    def test_upsert_inserts_then_replaces(self):
        page = "# What's new\n\nIntro.\n\n" + release.MARKER + "\n"
        one = release.upsert(page, "0.1.2", "## 0.1.2\n<!-- release: 0.1.2-rc1 -->\n\nFIRSTBODY\n")
        two = release.upsert(one, "0.1.3", "## 0.1.3\n<!-- release: 0.1.3 -->\n\nnewer\n")
        self.assertLess(two.index("## 0.1.3"), two.index("## 0.1.2"))
        again = release.upsert(two, "0.1.2", "## 0.1.2\n<!-- release: 0.1.2-rc2 -->\n\nsecond\n")
        self.assertNotIn("FIRSTBODY", again)
        self.assertIn("second", again)
        self.assertEqual(again.count("## 0.1.2"), 1)
        self.assertTrue(again.index("## 0.1.3") < again.index("## 0.1.2"))
        # changelog headings: [version] - date
        cl = release.upsert("# Changelog\n\n" + release.MARKER + "\n\n## [0.1.1] - x\n\nold\n", "0.1.2",
                            release.changelog_section(PLAN, NOTES))
        self.assertLess(cl.index("## [0.1.2] - 2026-10-09"), cl.index("## [0.1.1]"))
        self.assertIn("#### Added", cl)

    def test_cargo_version(self):
        d = tempfile.mkdtemp()
        os.makedirs(f"{d}/core/crates/a")
        os.makedirs(f"{d}/core/crates/b")
        open(f"{d}/core/Cargo.toml", "w").write(
            '[workspace]\nmembers = []\n\n[workspace.package]\nversion = "0.1.0"\nedition = "2024"\n\n'
            '[workspace.dependencies]\nfoo = { version = "0.1.0" }\n')
        for n in "ab":
            open(f"{d}/core/crates/{n}/Cargo.toml", "w").write(
                f'[package]\nname = "crate-{n}"\nversion.workspace = true\n')
        open(f"{d}/core/Cargo.lock", "w").write(
            '# lock\nversion = 4\n\n[[package]]\nname = "crate-a"\nversion = "0.1.0"\n\n'
            '[[package]]\nname = "crate-b"\nversion = "0.1.0"\ndependencies = [\n "foo",\n]\n\n'
            '[[package]]\nname = "foo"\nversion = "0.1.0"\nsource = "registry+https://x"\n')
        release.bump_cargo(d, "0.1.2")
        toml, lock = open(f"{d}/core/Cargo.toml").read(), open(f"{d}/core/Cargo.lock").read()
        self.assertIn('[workspace.package]\nversion = "0.1.2"', toml)
        self.assertIn('foo = { version = "0.1.0" }', toml)
        self.assertEqual(lock.count('version = "0.1.2"'), 2)
        self.assertIn('name = "foo"\nversion = "0.1.0"', lock, "a dependency of the same version stays")

    def test_real_cargo_files_have_what_the_bump_needs(self):
        root = release.ROOT
        if not os.path.isfile(os.path.join(root, "core/Cargo.lock")):
            self.skipTest("no checkout")
        t = open(os.path.join(root, "core/Cargo.toml")).read()
        self.assertRegex(t, r'(?ms)^\[workspace\.package\]\n.*?^version = "\d+\.\d+\.\d+"')


class Bodies(unittest.TestCase):
    def setUp(self):
        self.d = repo_with([])
        os.makedirs(f"{self.d}/manual/src")
        page = "# What's new\n\n" + release.MARKER + "\n"
        page = release.upsert(page, "0.1.2", release.notes_section(PLAN, NOTES))
        open(f"{self.d}/manual/src/whats-new.md", "w").write(page)
        sh(self.d, "add", ".")
        sh(self.d, "commit", "-q", "-m", "release: v0.1.2-rc1")
        sh(self.d, "tag", "v0.1.2-rc1")

    def body(self, **kw):
        a = SimpleNamespace(tag="v0.1.2-rc1", ref=None, promoted_from=None, **{"for": "bromigos"})
        for k, v in kw.items():
            setattr(a, k, v)
        out = io.StringIO()
        with mock.patch.object(release, "ROOT", self.d), redirect_stdout(out):
            release.body_cmd(a)
        return out.getvalue()

    def test_release_body(self):
        b = self.body()
        self.assertTrue(b.startswith("*9 October 2026"))
        self.assertNotIn("<!--", b)
        self.assertIn("`bromigos update --channel rc`", b)
        self.assertIn("SHA256SUMS", b)
        self.assertIn("/blob/v0.1.2-rc1/manual/src/whats-new.md", b)

    def test_promoted_and_vector(self):
        b = self.body(tag="v0.1.2", ref="v0.1.2-rc1", promoted_from="v0.1.2-rc1")
        self.assertIn("v0.1.2 is v0.1.2-rc1, promoted to the stable channel unchanged", b)
        self.assertIn("on the stable channel.", b)
        v = self.body(**{"for": "vector"})
        self.assertTrue(v.startswith("VECTOR listens.\n\n### Improved"), v)
        self.assertIn("part of [bromigOS 0.1.2-rc1]", v)


class Privacy(unittest.TestCase):
    def test_rules(self):
        d = repo_with(["v0.1.1", None])
        rs = guard.rules([d])
        bad = lambda t: guard.scan("notes", t, rs)  # noqa: E731
        self.assertEqual(bad("The theme switcher shows previews."), [])
        # the shapes each rule stops (fixtures, not anyone's real names)
        for t in ["Runs on 192.168.1.20 now.",  # privacy: allow (a shape the rule must stop)
                  "Talks to nas.example.lan.",  # privacy: allow (a shape the rule must stop)
                  "Thanks to Jane for this.",
                  "Mail jane@example.org.", "Like Omarchy does.",
                  "From api.tools.svc:4000.",
                  "Token sk-abcdefghijklmnopqrstuvwxyz123456."]:  # privacy: allow (a shape the rule must stop)
            self.assertTrue(bad(t), t)
        self.assertEqual([x[2] for x in bad("Hacker news")], ["a commit author's name"])

    def test_documentation_ranges_pass(self):
        """Fixtures use RFC 5737 / RFC 3849 / RFC 7042 ranges; the rules let them through."""
        rs = guard.rules([])
        for t in ["Joins 192.0.2.41/24 via 198.51.100.1 and 203.0.113.2.", "Has 2001:db8::1/64.",
                  "Pairs 00:00:5E:00:53:10 and 00:00:5e:00:53:4f."]:
            self.assertEqual(guard.scan("notes", t, rs), [], t)
        for t in ["Pairs AC:80:0A:00:00:01.", "Pairs 00:00:5E:00:54:10."]:  # privacy: allow (MACs the rule must stop)
            self.assertTrue(guard.scan("notes", t, rs), t)

    def test_redact_keeps_the_commit_link(self):
        rs = guard.rules([])
        out = guard.redact("- docs: as omarchy does ([abc1234](https://x/commit/abc))\n- fine\n", rs)
        self.assertEqual(out, "- (withheld by the privacy check) ([abc1234](https://x/commit/abc))\n- fine\n")

    def test_draft_retries_past_a_leak(self):
        good = json.dumps({"summary": "S.", "before_you_update": [], "new": ["Fine."], "improved": [],
                           "fixed": [], "known_issues": []})
        leak = good.replace("Fine.", "Runs on 10.1.2.3.")  # privacy: allow (the leak the draft must retry past)
        answers = iter([leak, good])
        with mock.patch.object(release, "chat", lambda m: next(answers)):
            n = release.draft("bromigOS", PLAN, [], {}, [], guard.rules([]), "bromigOS")
        self.assertEqual(n["new"], ["Fine."])

    def test_model_input_is_redacted(self):
        with self.internal_project("Quillmoor"):
            self.assertEqual(release.private("on 10.0.0.7 via Quillmoor", guard.rules([])),  # privacy: allow (the address redaction must hide)
                             "on <private> via <private>")

    @staticmethod
    def internal_project(name):
        """A made-up internal project's name, known to the guard by its salted hash as the real
        ones are (tools/privacy/private_words.py)."""
        return mock.patch.dict(guard.private_words.HASHED,
                               {guard.private_words.digest(name.lower()): "an internal project's name"})

    def test_an_internal_project_is_stopped(self):
        with self.internal_project("Quillmoor"):
            rs = guard.rules([])
            self.assertTrue(guard.scan("notes", "Quillmoor's dashboards.", rs))
            self.assertTrue(guard.scan("notes", "the quillmoor-live service", rs))
        self.assertEqual(guard.scan("notes", "Quillmoor's dashboards.", guard.rules([])), [])


class Checksums(unittest.TestCase):
    def db(self, entries):
        d = tempfile.mkdtemp()
        p = f"{d}/bromigos.db.tar.gz"
        with tarfile.open(p, "w:gz") as t:
            for name, ver, sha in entries:
                desc = (f"%FILENAME%\n{name}-{ver}-1-any.pkg.tar.zst\n\n%NAME%\n{name}\n\n%VERSION%\n{ver}-1\n\n"
                        f"%SHA256SUM%\n{sha}\n\n").encode()
                info = tarfile.TarInfo(f"{name}-{ver}-1/desc")
                info.size = len(desc)
                t.addfile(info, io.BytesIO(desc))
        return p

    def run_cmd(self, db, **kw):
        a = SimpleNamespace(db=db, expect_version=kw.get("v"), expect=kw.get("e"))
        out = io.StringIO()
        with redirect_stdout(out):
            release.checksums_cmd(a)
        return out.getvalue()

    def test_sums_and_expectations(self):
        db = self.db([("bromigos-core", "0.1.2.r5.gabc", "a" * 64), ("herdr", "1.0", "b" * 64)])
        self.assertEqual(self.run_cmd(db), f"{'a' * 64}  bromigos-core-0.1.2.r5.gabc-1-any.pkg.tar.zst\n"
                                           f"{'b' * 64}  herdr-1.0-1-any.pkg.tar.zst\n")
        self.run_cmd(db, v="0.1.2", e=["bromigos-core"])
        with self.assertRaises(SystemExit):
            self.run_cmd(db, v="0.1.3", e=["bromigos-core"])        # not this release's yet
        with self.assertRaises(SystemExit):
            self.run_cmd(db, v="0.1.2", e=["bromigos-vector"])      # missing


class Cliff(unittest.TestCase):
    """git-cliff's grouping, when it's installed (CI installs it)."""

    def test_groups(self):
        if subprocess.run(["sh", "-c", "command -v git-cliff"], capture_output=True).returncode:
            self.skipTest("git-cliff isn't installed")
        d = repo_with(["v0.1.1"])
        for m in ["desktop: a menu", "live, homelab: decks", "desktop/tests: more", "Added: a voice",
                  "Fixed: the dial", "docs: words", "release: v0.1.2 (the notes)", "iso: grub"]:
            sh(d, "commit", "-q", "--allow-empty", "-m", m)
        out = release.cliff(d, "--tag", "v0.1.2", "v0.1.1..HEAD", url="https://x")
        groups = re.findall(r"(?m)^### (.+)$", out)
        self.assertEqual(groups, ["Added", "Fixed", "Desktop", "Live layer", "Boot and the ISO",
                                  "Tests and tools", "Docs"])
        self.assertIn("- desktop: a menu ([", out)
        self.assertIn("- A voice ([", out)
        self.assertNotIn("release:", out)


if __name__ == "__main__":
    unittest.main()
