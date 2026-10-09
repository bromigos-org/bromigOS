"""The privacy check for release notes and changelogs (docs/release.md, "What the notes may
not say").

Generated text gets the repositories' own privacy guard (privacy_guard.py: private
addresses, internal host names, token shapes, plus the lab's own names from the
PRIVACY_PATTERNS secret or the private overlay) and a few rules of its own: no internal
project names (matched by salted hashes, tools/privacy/private_words.py), no other distributions named, and no names or e-mail addresses of the
people who wrote the commits (read from git at run time, so they're never written down
here).

A finding is reported as file:line and the rule's label, never the matched text.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import privacy_guard  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "privacy"))
import private_words  # noqa: E402

# Words user-facing text never carries (AGENTS.md; docs/release.md).
RELEASE_RULES = [
    ("another distribution's name (bromigOS presents as its own product)", r"(?i)omarchy"),
    ("a Kubernetes service name", r"(?i)\.svc\b"),
    # the guard's own address rule wants no "." after one (config files); prose ends sentences
    ("a private IPv4 address", r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
                               r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?!\.?\d)"),
]

# Author-name words that name the product or a bot, not a person.
NOT_PEOPLE = {"bromigos", "claude", "github", "actions", "dependabot", "bot", "ci", "catalog", "lab"}


def author_rules(repos, since=None):
    """Rules for the commit authors' names and addresses in `repos` (git directories)."""
    seen = set()
    for repo in repos:
        rng = [f"{since}..HEAD"] if since else []
        try:
            out = subprocess.run(["git", "-C", repo, "log", "--format=%an%x00%ae", *rng],
                                 capture_output=True, text=True, check=True).stdout
        except (subprocess.CalledProcessError, OSError):
            continue
        for line in out.splitlines():
            name, _, email = line.partition("\0")
            seen.add((name.strip(), email.strip()))
    rules = []
    for name, email in sorted(seen):
        if email and not email.endswith(("noreply.github.com", "noreply@anthropic.com")) and "@" in email:
            rules.append(("a commit author's e-mail address", re.escape(email)))
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", name) if w[0].isupper()]
        for w in words:
            if w.lower() not in NOT_PEOPLE:
                rules.append(("a commit author's name", rf"\b{re.escape(w)}\b"))
    return rules


def rules(repos=(), since=None):
    out = list(privacy_guard.rules())
    # internal projects' names: salted hashes (tools/privacy/private_words.py), never spelled here
    out.append(("an internal project's name", private_words.HashedWords()))
    for label, pattern in RELEASE_RULES + author_rules(repos, since):
        out.append((label, re.compile(pattern if pattern.startswith("(?i)") else "(?i)" + pattern)))
    return out


def scan(name, text, rs):
    """[(name, line, label)] for each line of `text` that breaks a rule."""
    # stricter than the repository guard: no generic exceptions (a cluster-local service
    # name is as wrong in a user's notes as a LAN host name), no `privacy: allow` marks
    bad = []
    for n, t in enumerate(text.splitlines(), 1):
        for label, r in rs:
            if r.search(t):
                bad.append((name, n, label))
                break
    return bad


def redact(text, rs, mark="(withheld by the privacy check)"):
    """Each line that breaks a rule, replaced by `mark` (keeping a trailing commit link)."""
    out = []
    for t in text.splitlines():
        if any(r.search(t) for _, r in rs):
            link = re.search(r"\s(\(\[[0-9a-f]{7}\]\([^)]*\)\))\s*$", t)
            out.append(("- " if t.lstrip().startswith("- ") else "") + mark + (" " + link.group(1) if link else ""))
        else:
            out.append(t)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def have_private_patterns():
    """True when the lab's own names are known (PRIVACY_PATTERNS, or the private overlay)."""
    return any(label.startswith("private name") for label, _ in privacy_guard.rules())


def report(bad, out=sys.stderr):
    for name, n, label in bad[:60]:
        print(f"  {name}:{n}: {label}", file=out)
    if len(bad) > 60:
        print(f"  ... and {len(bad) - 60} more", file=out)
