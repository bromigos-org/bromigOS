"""Tests for tools/release/go-public.sh (docs/public.md). gcloud, curl and vault are stubs
that serve a fake bucket from a folder and log every call; the two repositories are bare git
repositories on disk; the signing key is a throwaway. Nothing reaches a network.

The dry run must check everything and change nothing. With --yes, the bucket is opened, the
anonymous downloads are verified, and both prepared branches land on main."""
import os
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "go-public.sh")
URL = "https://storage.googleapis.com/test-pkgs"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}

# gcloud: `storage cat gs://BUCKET/PATH` reads $FAKE/bucket/PATH; describe and get-iam-policy
# read $FAKE/state; update and the policy bindings change it. Every call goes to $FAKE/log.
GCLOUD = r"""#!/usr/bin/env bash
echo "gcloud $*" >> "$FAKE/log"
args=(); for a in "$@"; do case $a in --project|--billing-project=*|--format=*) ;; *) args+=("$a") ;; esac; done
set -- "${args[@]}"
[[ $1 == bromigos-org ]] && shift   # the value after --project
case "$1 $2 $3" in
  "storage cat "*) f=${3#gs://*/}; exec cat "$FAKE/bucket/$f" ;;
  "storage buckets describe") cat "$FAKE/pap" ;;
  "storage buckets get-iam-policy") if [[ -f $FAKE/public ]]; then echo '{"bindings":[{"members":["allUsers"]}]}'; else echo '{"bindings":[]}'; fi ;;
  "storage buckets update") [[ " $* " == *" --no-public-access-prevention "* ]] && echo inherited > "$FAKE/pap" ;;
  "storage buckets add-iam-policy-binding") touch "$FAKE/public" ;;
  *) echo "gcloud stub: unexpected $*" >&2; exit 1 ;;
esac
"""
# curl -fsS -o OUT URL: anonymous, so only once the fake bucket is public.
CURL = r"""#!/usr/bin/env bash
echo "curl $*" >> "$FAKE/log"
out='' url=''
while (($#)); do case $1 in -o) out=$2; shift 2 ;; -*) shift ;; *) url=$1; shift ;; esac; done
[[ -f $FAKE/public ]] || exit 22
cp "$FAKE/bucket/${url#https://storage.googleapis.com/test-pkgs/}" "$out"
"""
VAULT = """#!/usr/bin/env bash\necho "vault $*" >> "$FAKE/log"\n"""


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class GoPublic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = os.path.join(self.tmp, "fake")
        os.makedirs(os.path.join(self.fake, "bucket", "bromigos"))
        with open(os.path.join(self.fake, "pap"), "w") as f:
            f.write("enforced\n")
        open(os.path.join(self.fake, "log"), "w").close()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for name, body in (("gcloud", GCLOUD), ("curl", CURL), ("vault", VAULT)):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, 0o755)
        self.gnupg = os.path.join(self.tmp, "gnupg")
        os.makedirs(self.gnupg, mode=0o700)
        self.fpr = self.make_key()
        self.make_bucket()
        self.gitbase = os.path.join(self.tmp, "remotes") + "/"
        self.make_remote("bromigos-org/bromigOS", "go-public",
                         {"install.sh": f"FPR={self.fpr}\nPUBLIC_REPO={URL}   # public\n"})
        self.make_remote("bromigos-org/bromigos.org", "os-get-public",
                         {"page.tsx": "install steps\n"})

    def tearDown(self):
        subprocess.run(["gpgconf", "--homedir", self.gnupg, "--kill", "all"], capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def gpg(self, *args):
        return subprocess.run(["gpg", "--homedir", self.gnupg, "--batch", *args],
                              check=True, capture_output=True, text=True).stdout

    def make_key(self):
        self.gpg("--passphrase", "", "--quick-gen-key", "Test <t@example.org>", "ed25519", "sign", "1d")
        out = self.gpg("--with-colons", "--list-keys")
        return next(l.split(":")[9] for l in out.splitlines() if l.startswith("fpr:"))

    def make_bucket(self):
        b = os.path.join(self.fake, "bucket", "bromigos")
        with open(os.path.join(b, "bromigos.asc"), "w") as f:
            f.write(self.gpg("--armor", "--export", self.fpr))
        with open(os.path.join(b, "install.sh"), "w") as f:
            f.write("#!/bin/sh\n")
        for prefix in ("x86_64", "rc/x86_64", "stable/x86_64"):
            d = os.path.join(b, prefix)
            os.makedirs(os.path.join(d, "pkg-1-1"))
            with open(os.path.join(d, "pkg-1-1", "desc"), "w") as f:
                f.write("%NAME%\npkg\n")
            db = os.path.join(d, "bromigos.db")
            with tarfile.open(db, "w:gz") as t:
                t.add(os.path.join(d, "pkg-1-1"), arcname="pkg-1-1")
            self.gpg("--detach-sign", "--no-armor", "-u", self.fpr, "-o", db + ".sig", db)

    def make_remote(self, name, branch, files):
        bare = os.path.join(self.tmp, "remotes", name + ".git")
        os.makedirs(bare)
        git(bare, "init", "-q", "--bare", "-b", "main")
        work = os.path.join(self.tmp, "work-" + os.path.basename(name))
        git(self.tmp, "clone", "-q", bare, work)
        with open(os.path.join(work, "README"), "w") as f:
            f.write("main\n")
        git(work, "add", "README")
        git(work, "commit", "-qm", "main")
        git(work, "push", "-q", "origin", "HEAD:main")
        git(work, "checkout", "-qb", branch)
        for path, text in files.items():
            with open(os.path.join(work, path), "w") as f:
                f.write(text)
            git(work, "add", path)
        git(work, "commit", "-qm", "go public")
        git(work, "push", "-q", "origin", branch)
        # main moves on after the branch was made: the script rebases onto it.
        git(work, "checkout", "-q", "main")
        with open(os.path.join(work, "LATER"), "w") as f:
            f.write("later\n")
        git(work, "add", "LATER")
        git(work, "commit", "-qm", "later")
        git(work, "push", "-q", "origin", "HEAD:main")

    def run_script(self, *args):
        env = {**os.environ, **GIT_ENV, "PATH": self.bin + os.pathsep + os.environ["PATH"],
               "FAKE": self.fake, "GO_PUBLIC_FPR": self.fpr, "GO_PUBLIC_BUCKET": "test-pkgs",
               "GO_PUBLIC_GIT_BASE": self.gitbase, "GO_PUBLIC_VAULT_PATH": "secret/test"}
        return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=env)

    def log(self):
        with open(os.path.join(self.fake, "log")) as f:
            return f.read()

    def main_files(self, name):
        bare = os.path.join(self.tmp, "remotes", name + ".git")
        return git(bare, "ls-tree", "--name-only", "main").split()

    def branches(self, name):
        bare = os.path.join(self.tmp, "remotes", name + ".git")
        return git(bare, "branch", "--format=%(refname:short)").split()

    def test_dry_run_checks_everything_and_changes_nothing(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = r.stdout
        self.assertIn("dry run: nothing changes", out)
        self.assertIn(f"the mirror's signing key is {self.fpr}", out)
        for ch in ("edge", "rc", "stable"):
            self.assertIn(f"{ch}: 1 packages, database signed by {self.fpr}", out)
        self.assertIn("merges cleanly", out)
        self.assertIn("would run: gcloud storage buckets add-iam-policy-binding gs://test-pkgs --member=allUsers --role=roles/storage.legacyObjectReader", out.replace("--project bromigos-org --billing-project=bromigos-org ", ""))
        self.assertIn("would run: gcloud", out)
        self.assertIn("$0.12 per GB", out)
        log = self.log()
        self.assertNotIn("buckets update", log)
        self.assertNotIn("add-iam-policy-binding", log)
        self.assertNotIn("curl", log)
        self.assertNotIn("vault", log)
        self.assertNotIn("install.sh", self.main_files("bromigos-org/bromigOS"))
        self.assertIn("go-public", self.branches("bromigos-org/bromigOS"))
        self.assertIn("os-get-public", self.branches("bromigos-org/bromigos.org"))

    def test_yes_goes_public_and_lands_both_branches(self):
        r = self.run_script("--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.log()
        self.assertIn("--no-public-access-prevention", log)
        self.assertIn("add-iam-policy-binding gs://test-pkgs --member=allUsers --role=roles/storage.legacyObjectReader", log)
        self.assertLess(log.index("add-iam-policy-binding"), log.index("curl"))
        self.assertIn("vault kv patch secret/test status=public since", log)
        for ch in ("edge", "rc", "stable"):
            self.assertIn(f"{ch}: {URL}/", r.stdout)
        os_files = self.main_files("bromigos-org/bromigOS")
        self.assertIn("install.sh", os_files)
        self.assertIn("LATER", os_files)          # rebased on main as it is now
        self.assertNotIn("go-public", self.branches("bromigos-org/bromigOS"))
        self.assertIn("page.tsx", self.main_files("bromigos-org/bromigos.org"))
        self.assertIn("packages are public", r.stdout)

    def test_a_missing_channel_stops_before_anything(self):
        os.remove(os.path.join(self.fake, "bucket", "bromigos", "rc", "x86_64", "bromigos.db"))
        r = self.run_script("--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("the rc channel isn't on the mirror", r.stderr)
        self.assertNotIn("add-iam-policy-binding", self.log())

    def test_a_bad_signature_stops_before_anything(self):
        db = os.path.join(self.fake, "bucket", "bromigos", "x86_64", "bromigos.db")
        with open(db, "ab") as f:
            f.write(b"tampered")
        r = self.run_script("--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("doesn't match its signature", r.stderr)
        self.assertNotIn("add-iam-policy-binding", self.log())

    def test_a_branch_that_sets_another_url_stops(self):
        bare = os.path.join(self.tmp, "remotes", "bromigos-org/bromigOS.git")
        work = os.path.join(self.tmp, "work-bromigOS")
        git(work, "checkout", "-q", "go-public")
        with open(os.path.join(work, "install.sh"), "w") as f:
            f.write(f"FPR={self.fpr}\nPUBLIC_REPO=''\n")
        git(work, "commit", "-qam", "oops")
        git(work, "push", "-q", "origin", "go-public")
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not " + URL, r.stderr)
        self.assertTrue(os.path.isdir(bare))

    def test_private_undoes_only_with_yes(self):
        r = self.run_script("--private")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would run: gcloud", r.stdout)
        self.assertNotIn("remove-iam-policy-binding", self.log())


if __name__ == "__main__":
    unittest.main()
