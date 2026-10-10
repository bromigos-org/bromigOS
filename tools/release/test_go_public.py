"""Tests for tools/release/go-public.sh (docs/public.md). curl is a stub that plays the
Cloudflare API, the bucket's S3 endpoint and its public address, from a folder, and logs
every call; vault is a stub too. The two repositories are bare git repositories on disk,
and the signing key is a throwaway. Nothing reaches a network.

The dry run must check everything and change nothing. With --yes, the bucket's public
address is turned on, the anonymous downloads are verified, and both prepared branches
land on main.

--ci moves CI to GitHub's runners (and --ci --private back): gh is a stub too, playing the
repositories' variables, secrets, visibility and queued runs from folders."""
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "go-public.sh")
R2DEV = "https://pub-0123abcd.r2.dev"
TOKEN = "cf-token-must-never-show"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}

# The stub: the API at http://cf.test/v4, S3 at http://s3.test/<bucket>/<key> (only with the
# key, from -K), the public address only once $FAKE/public names it.
CURL = r"""#!/usr/bin/env bash
echo "curl $*" >> "$FAKE/log"
out='' url='' method=GET data='' conf=''
while (($#)); do
  case $1 in
    -o) out=$2; shift 2 ;; -X) method=$2; shift 2 ;; --data) data=$2; shift 2 ;;
    -K) conf=$(cat "$2"); shift 2 ;; -H|--aws-sigv4) shift 2 ;; -*) shift ;; *) url=$1; shift ;;
  esac
done
put() { if [[ -n $out ]]; then cp "$1" "$out"; else cat "$1"; fi; }
ok() { printf '{"success":true,"errors":[],"result":%s}\n' "$1"; }
case $url in
  http://cf.test/v4/*)
    [[ $conf == *"Bearer $EXPECT_TOKEN"* ]] || { echo '{"success":false,"errors":[{"message":"auth"}]}'; exit 0; }
    echo "api $method ${url#http://cf.test/v4} $data" >> "$FAKE/changes"
    case "$method ${url#http://cf.test/v4}" in
      "GET /accounts/acct/r2/buckets/bromigos-pkgs/domains/managed")
        en=false; grep -qx managed "$FAKE/public" 2>/dev/null && en=true
        ok "{\"bucketId\":\"b\",\"domain\":\"pub-0123abcd.r2.dev\",\"enabled\":$en}" ;;
      "PUT /accounts/acct/r2/buckets/bromigos-pkgs/domains/managed")
        [[ $data == *true* ]] && echo managed > "$FAKE/public"; ok '{}' ;;
      "GET /zones?name=bromigos.org") ok '[{"id":"zone1"}]' ;;
      "GET /zones?name="*) ok '[]' ;;
      "GET /accounts/acct/r2/buckets/bromigos-pkgs/domains/custom")
        if grep -qx custom "$FAKE/public" 2>/dev/null; then ok '{"domains":[{"domain":"pkgs.bromigos.org","enabled":true}]}'; else ok '{"domains":[]}'; fi ;;
      "POST /accounts/acct/r2/buckets/bromigos-pkgs/domains/custom") echo custom > "$FAKE/public"; ok '{}' ;;
      *) echo '{"success":false,"errors":[{"message":"unexpected"}]}' ;;
    esac ;;
  http://s3.test/bromigos-pkgs/*)
    [[ $conf == *'user = "AKID:SECRET"'* ]] || exit 22
    f="$FAKE/bucket/${url#http://s3.test/bromigos-pkgs/}"; [[ -f $f ]] || exit 22; put "$f" ;;
  https://pub-0123abcd.r2.dev/*)
    grep -qx managed "$FAKE/public" 2>/dev/null || exit 22
    f="$FAKE/bucket/${url#https://pub-0123abcd.r2.dev/}"; [[ -f $f ]] || exit 22; put "$f" ;;
  https://model.test/*)
    if [[ -f $FAKE/model-up ]]; then printf 200; else printf 000; exit 7; fi ;;
  https://pkgs.bromigos.org/*)
    grep -qx custom "$FAKE/public" 2>/dev/null || exit 22
    f="$FAKE/bucket/${url#https://pkgs.bromigos.org/}"; [[ -f $f ]] || exit 22; put "$f" ;;
  *) exit 6 ;;
esac
"""
VAULT = """#!/usr/bin/env bash\necho "vault $*" >> "$FAKE/log"\n"""

# gh: $FAKE/gh/<owner_repo>/{vars,secrets}/<NAME> hold values; visibility, install.sh and
# queued runs are files beside them. Every call is logged (values never are: they're stdin
# or --body, and the log keeps only the words before them).
GH = r"""#!/usr/bin/env bash
echo "gh ${*%%--body*}" >> "$FAKE/log"
repo='' args=()
while (($#)); do case $1 in -R) repo=$2; shift 2 ;; *) args+=("$1"); shift ;; esac; done
set -- "${args[@]}"
d="$FAKE/gh/${repo//\//_}"
case "$1 $2" in
  "repo view") d="$FAKE/gh/${3//\//_}"; cat "$d/visibility" 2>/dev/null || echo PRIVATE ;;
  "variable list")
    for f in "$d"/vars/*; do [[ -f $f ]] && jq -n --arg n "${f##*/}" --arg v "$(cat "$f")" '{name: $n, value: $v}'; done | jq -s . ;;
  "variable set") mkdir -p "$d/vars"; printf '%s' "$5" > "$d/vars/$3" ;;
  "variable delete") rm "$d/vars/$3" ;;
  "secret list") for f in "$d"/secrets/*; do [[ -f $f ]] && echo "${f##*/}"; done ;;
  "secret set") mkdir -p "$d/secrets"; cat > "$d/secrets/$3" ;;
  "api repos/"*) base64 < "$FAKE/gh/install.sh" ;;
  "run list") cat "$d/queued" 2>/dev/null || true ;;
  *) echo "gh stub: $*" >&2; exit 1 ;;
esac
"""


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class GoPublic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = os.path.join(self.tmp, "fake")
        os.makedirs(os.path.join(self.fake, "bucket", "bromigos"))
        for f in ("log", "changes"):
            open(os.path.join(self.fake, f), "w").close()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for name, body in (("curl", CURL), ("vault", VAULT), ("gh", GH)):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, 0o755)
        self.gnupg = os.path.join(self.tmp, "gnupg")
        os.makedirs(self.gnupg, mode=0o700)
        self.fpr = self.make_key()
        self.make_bucket()
        self.gitbase = "file://" + os.path.join(self.tmp, "remotes") + "/"
        self.make_remote("bromigos-org/bromigOS", "go-public",
                         {"install.sh": f"FPR={self.fpr}\nPUBLIC_REPO={R2DEV}   # public\n",
                          "README.md": f"curl -fsSLO {R2DEV}/bromigos/install.sh\n",
                          # a diff far bigger than a pipe's buffer, after the address
                          "zz-big.md": "".join(f"line {i}\n" for i in range(50000))})
        self.make_remote("bromigos-org/bromigos.org", "os-get-public",
                         {"page.tsx": f"curl -fsSLO {R2DEV}/bromigos/install.sh\n"})

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
                f.write("%NAME%\npkg\n\n%LICENSE%\nLicenseRef-Test-Proprietary\n")
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
        with open(os.path.join(work, "MAIN"), "w") as f:
            f.write("main\n")
        git(work, "add", "MAIN")
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
               "FAKE": self.fake, "EXPECT_TOKEN": TOKEN, "GO_PUBLIC_FPR": self.fpr,
               "GO_PUBLIC_GIT_BASE": self.gitbase, "GO_PUBLIC_CF_API": "http://cf.test/v4",
               "GO_PUBLIC_S3_ENDPOINT": "http://s3.test", "GO_PUBLIC_TRIES": "2",
               "GO_PUBLIC_WAIT": "0", "CLOUDFLARE_API_TOKEN": TOKEN, "CF_ACCOUNT_ID": "acct",
               "PKGS_PUBLIC_ACCESS_KEY_ID": "AKID", "PKGS_PUBLIC_SECRET_ACCESS_KEY": "SECRET"}
        env.pop("GO_PUBLIC_VAULT_PATH", None)
        return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=env)

    def read(self, name):
        with open(os.path.join(self.fake, name)) as f:
            return f.read()

    def show(self, name, path):
        bare = os.path.join(self.tmp, "remotes", name + ".git")
        return git(bare, "show", "main:" + path)

    def main_files(self, name):
        bare = os.path.join(self.tmp, "remotes", name + ".git")
        return git(bare, "ls-tree", "--name-only", "main").split()

    def branches(self, name):
        bare = os.path.join(self.tmp, "remotes", name + ".git")
        return git(bare, "branch", "--format=%(refname:short)").split()

    def assert_no_secrets(self, r):
        for text in (r.stdout, r.stderr, self.read("log")):
            self.assertNotIn(TOKEN, text)
            self.assertNotIn("SECRET", text)

    def test_dry_run_checks_everything_and_changes_nothing(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = r.stdout
        self.assertIn("dry run: nothing changes", out)
        self.assertIn(f"bromigos-pkgs is private; it will be public at {R2DEV}", out)
        self.assertIn(f"the mirror's signing key is {self.fpr}", out)
        for ch in ("edge", "rc", "stable"):
            self.assertIn(f"{ch}: 1 packages, database signed by {self.fpr}", out)
        self.assertIn("note: pkg (LicenseRef-Test-Proprietary) is proprietary", out)
        self.assertIn("merges cleanly", out)
        self.assertIn('would run: PUT /accounts/acct/r2/buckets/bromigos-pkgs/domains/managed {"enabled":true}', out)
        self.assertIn("rate-limits r2.dev", out)
        changes = self.read("changes")
        self.assertNotIn("PUT", changes)
        self.assertNotIn("POST", changes)
        self.assertNotIn("r2.dev/", self.read("log"))      # no anonymous fetches
        self.assertNotIn("vault", self.read("log"))
        self.assertNotIn("install.sh", self.main_files("bromigos-org/bromigOS"))
        self.assertIn("go-public", self.branches("bromigos-org/bromigOS"))
        self.assertIn("os-get-public", self.branches("bromigos-org/bromigos.org"))
        self.assert_no_secrets(r)

    def test_yes_goes_public_on_r2dev_and_lands_both_branches(self):
        r = self.run_script("--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        changes = self.read("changes")
        self.assertIn('PUT /accounts/acct/r2/buckets/bromigos-pkgs/domains/managed {"enabled":true}', changes)
        log = self.read("log")
        self.assertLess(log.index("-X PUT"), log.index(R2DEV + "/bromigos/bromigos.asc"))
        for ch in ("edge", "rc", "stable"):
            self.assertIn(f"{ch}: {R2DEV}/", r.stdout)
        self.assertIn(f"PUBLIC_REPO={R2DEV}", self.show("bromigos-org/bromigOS", "install.sh"))
        self.assertIn("LATER", self.main_files("bromigos-org/bromigOS"))   # rebased on today's main
        self.assertNotIn("go-public", self.branches("bromigos-org/bromigOS"))
        self.assertIn("page.tsx", self.main_files("bromigos-org/bromigos.org"))
        self.assertIn(f"packages are public at {R2DEV}", r.stdout)
        self.assert_no_secrets(r)

    def test_a_custom_domain_rewrites_the_address(self):
        r = self.run_script("--domain", "pkgs.bromigos.org", "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('POST /accounts/acct/r2/buckets/bromigos-pkgs/domains/custom {"domain":"pkgs.bromigos.org","zoneId":"zone1"',
                      self.read("changes"))
        self.assertNotIn("domains/managed {", self.read("changes"))
        self.assertIn("PUBLIC_REPO=https://pkgs.bromigos.org", self.show("bromigos-org/bromigOS", "install.sh"))
        self.assertIn("https://pkgs.bromigos.org/bromigos/install.sh", self.show("bromigos-org/bromigOS", "README.md"))
        self.assertIn("https://pkgs.bromigos.org/bromigos/install.sh", self.show("bromigos-org/bromigos.org", "page.tsx"))

    def test_a_domain_outside_cloudflare_stops(self):
        r = self.run_script("--domain", "pkgs.example.net")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't a zone in this Cloudflare account", r.stderr)

    def test_a_missing_channel_stops_before_anything(self):
        os.remove(os.path.join(self.fake, "bucket", "bromigos", "rc", "x86_64", "bromigos.db"))
        r = self.run_script("--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("the rc channel isn't on the mirror", r.stderr)
        self.assertNotIn("PUT", self.read("changes"))

    def test_a_bad_signature_stops_before_anything(self):
        db = os.path.join(self.fake, "bucket", "bromigos", "x86_64", "bromigos.db")
        with open(db, "ab") as f:
            f.write(b"tampered")
        r = self.run_script("--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("doesn't match its signature", r.stderr)
        self.assertNotIn("PUT", self.read("changes"))

    def test_a_branch_with_another_address_stops(self):
        work = os.path.join(self.tmp, "work-bromigOS")
        git(work, "checkout", "-q", "go-public")
        with open(os.path.join(work, "install.sh"), "w") as f:
            f.write(f"FPR={self.fpr}\nPUBLIC_REPO=''\n")
        git(work, "commit", "-qam", "oops")
        git(work, "push", "-q", "origin", "go-public")
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not " + R2DEV, r.stderr)

    def test_private_undoes_only_with_yes(self):
        r = self.run_script("--private")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('would run: PUT /accounts/acct/r2/buckets/bromigos-pkgs/domains/managed {"enabled":false}', r.stdout)
        self.assertNotIn("PUT", self.read("changes"))
        r = self.run_script("--private", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('{"enabled":false}', self.read("changes"))


class GoPublicCI(GoPublic):
    """--ci: the repositories' CI settings, through the gh stub."""
    OS, VEC = "bromigos-org_bromigOS", "bromigos-org_vector"
    LAB = {"RUNNER_PACKAGES": "runner-big", "RUNNER_SMOKE": "runner-small", "LITELLM_LAB_URL": "http://model.example:4000"}

    def setUp(self):
        super().setUp()
        self.put(self.OS, "vars/CI_RUNNER_PACKAGES", "runner-big")
        self.put(self.OS, "vars/CI_RUNNER_SMOKE", "runner-small")
        self.put(self.OS, "vars/LITELLM_BASE_URL", "http://model.example:4000")
        self.put(self.OS, "secrets/LITELLM_API_KEY", "key")
        self.put(self.VEC, "vars/CI_RUNNER_PACKAGES", "runner-big")
        with open(os.path.join(self.fake, "gh", "install.sh"), "w") as f:
            f.write("FPR=x\nPUBLIC_REPO=''\n")
        open(os.path.join(self.fake, "model-up"), "w").close()

    def put(self, repo, path, text):
        f = os.path.join(self.fake, "gh", repo, path)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w") as fh:
            fh.write(text)

    def names(self, repo, kind):
        d = os.path.join(self.fake, "gh", repo, kind)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def value(self, repo, path):
        with open(os.path.join(self.fake, "gh", repo, path)) as f:
            return f.read()

    def ci(self, *args, **env):
        os.environ.update(env)
        try:
            return self.run_script("--ci", *args)
        finally:
            for k in env:
                os.environ.pop(k)

    def test_ci_dry_run_changes_nothing(self):
        r = self.ci(GO_PUBLIC_LITELLM_PUBLIC_URL="https://model.test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("would run: gh variable delete CI_RUNNER_PACKAGES -R bromigos-org/bromigOS", r.stdout)
        self.assertIn("would run: gh variable delete CI_RUNNER_PACKAGES -R bromigos-org/vector", r.stdout)
        self.assertIn("count against the account's free minutes", r.stdout)
        self.assertEqual(self.names(self.OS, "vars"), ["CI_RUNNER_PACKAGES", "CI_RUNNER_SMOKE", "LITELLM_BASE_URL"])
        self.assertNotIn("variable delete", self.read("log"))
        self.assertNotIn("cf.test", self.read("log"))      # --ci never touches the bucket

    def test_ci_yes_moves_ci_to_githubs_runners(self):
        self.put(self.OS, "visibility", "PUBLIC")
        self.put(self.VEC, "queued", "42 packages\n")
        r = self.ci("--yes", GO_PUBLIC_LITELLM_PUBLIC_URL="https://model.test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.names(self.OS, "vars"), [])
        self.assertEqual(self.names(self.VEC, "vars"), [])
        self.assertEqual(self.value(self.OS, "secrets/LITELLM_BASE_URL"), "https://model.test")
        self.assertIn("run 42 (packages) is queued", r.stdout)
        gh_calls = [l for l in self.read("log").splitlines() if l.startswith("gh ")]
        self.assertFalse([l for l in gh_calls if "model.test" in l])   # the secret goes on stdin

    def test_ci_names_the_public_repository_for_the_iso_check(self):
        with open(os.path.join(self.fake, "gh", "install.sh"), "w") as f:
            f.write(f"FPR=x\nPUBLIC_REPO='{R2DEV}'   # set by go-public\n")
        r = self.ci("--yes", GO_PUBLIC_LITELLM_PUBLIC_URL="https://model.test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.value(self.OS, "vars/ISO_REPO_URL"), R2DEV)

    def test_ci_stops_when_the_model_doesnt_answer(self):
        os.remove(os.path.join(self.fake, "model-up"))
        r = self.ci("--yes", GO_PUBLIC_LITELLM_PUBLIC_URL="https://model.test")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("doesn't answer", r.stderr)
        self.assertEqual(len(self.names(self.OS, "vars")), 3)

    def test_ci_needs_the_public_address(self):
        r = self.ci("--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("GO_PUBLIC_LITELLM_PUBLIC_URL", r.stderr)

    def test_ci_private_puts_the_lab_back(self):
        self.ci("--yes", GO_PUBLIC_LITELLM_PUBLIC_URL="https://model.test")
        r = self.ci("--private", "--yes", **{"GO_PUBLIC_" + k: v for k, v in self.LAB.items()})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.value(self.OS, "vars/CI_RUNNER_PACKAGES"), "runner-big")
        self.assertEqual(self.value(self.OS, "vars/CI_RUNNER_SMOKE"), "runner-small")
        self.assertEqual(self.value(self.VEC, "vars/CI_RUNNER_PACKAGES"), "runner-big")
        self.assertEqual(self.value(self.OS, "secrets/LITELLM_BASE_URL"), "http://model.example:4000")

    def test_ci_private_needs_the_lab_settings(self):
        r = self.ci("--private", "--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("GO_PUBLIC_RUNNER_PACKAGES", r.stderr)


# GoPublicCI inherits GoPublic's tests too; they'd only run twice.
for _n in [n for n in vars(GoPublic) if n.startswith("test_")]:
    setattr(GoPublicCI, _n, None)


if __name__ == "__main__":
    unittest.main()
