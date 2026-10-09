"""Privacy guard for the public dotfiles: what may never be committed, and the check.

bromigOS: a copy of VECTOR's lib/privacy_guard.py (itself the dotfiles' guard), used by
tools/release/guard.py to check generated release notes. Keep it in step with VECTOR's.

The dotfiles repo is public. Private infrastructure details (LAN addresses, internal
hostnames, Vault paths, device and node names) belong in the encrypted overlay
(linux/.config/bromigos/private.sops.yaml); real secrets belong in Vault. This module is
the one list of patterns, used by the git pre-commit hook (.githooks/pre-commit), the
GitHub Action (.github/workflows/privacy.yml) and VECTOR's build guard.

Two layers of patterns:
  * PUBLIC: generic shapes (private IPv4 addresses, internal DNS names, MAC addresses,
    token shapes). Safe to publish; they name nothing about this lab.
  * PRIVATE: the operator's specific names (subnet, domain, Vault tree, host names), kept
    in the encrypted overlay under guard.patterns, so this public file doesn't have to
    spell them out. Read from ~/.config/bromigos/private/config.json, or from the
    PRIVACY_PATTERNS environment variable (one regex per line; a repo secret in CI).

A line that really must carry such a shape (a test fixture, a generic CIDR) can end with
the marker `privacy: allow`. Use it rarely; reviewers see it.

    python3 privacy_guard.py check-staged     # the pre-commit hook
    python3 privacy_guard.py check-tree [dir] # every tracked file (CI, audits)
    python3 privacy_guard.py check-sops FILE  # a *.sops.* file is really encrypted
"""
import json
import os
import re
import subprocess
import sys

PUBLIC = [
    ("private IPv4 address", r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|(?:192\.168|172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2})(?![\d.])"),
    ("private IPv4 address (regex-escaped)", r"(?<![\d.])(?:10|192\\\.168|172\\\.(?:1[6-9]|2\d|3[01]))\\\.\d{1,3}\\\."),
    ("internal DNS name", r"(?i)\b[a-z0-9-]+\.[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:local|lan|internal|home\.arpa|localdomain)\b"),
    ("internal DNS name (regex-escaped)", r"(?i)\b[a-z0-9-]+\\\.[a-z0-9-]+\\\.(?:local|lan|internal)\b"),
    ("MAC address", r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f:])"),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    ("Vault token", r"\bhv[sb]\.[A-Za-z0-9_-]{20,}"),
    ("AWS key id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("API key", r"\b(?:sk|rk)-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"),
    ("nolgia token", r"\bnol_[A-Za-z0-9]{12,}"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("JWT", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("private key block", r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    ("age secret key", r"AGE-SECRET-KEY-1[0-9A-Z]{50,}"),
]
ALLOW_MARK = "privacy: allow"
# generic shapes that look private but aren't: Kubernetes' cluster domain, placeholder MACs
GENERIC = re.compile(r"(?i)svc\\?\.cluster\\?\.local|cluster\\?\.local|\b(?:AA:BB:CC:DD:EE:FF|00(?::00){5}|FF(?::FF){5})\b")
OVERLAY = os.path.expanduser("~/.config/bromigos/private/config.json")
SOPS_FILE = re.compile(r"(^|/)[^/]+\.sops\.(ya?ml|json)$")
SKIP_FILE = re.compile(r"(^|/)(\.sops\.yaml|privacy_guard\.py)$|\.(png|jpe?g|gif|webp|ico|svg|wav|mp3|ogg|glb|ttf|otf|woff2?)$|(^|/)package-lock\.json$", re.I)


def private_patterns():
    pats = []
    env = os.environ.get("PRIVACY_PATTERNS", "")
    pats += [p.strip() for p in env.splitlines() if p.strip()]
    try:
        with open(OVERLAY) as f:
            pats += list((json.load(f).get("guard") or {}).get("patterns") or [])
    except (OSError, ValueError):
        pass
    return [(f"private name ({i + 1})", "(?i)" + p) for i, p in enumerate(dict.fromkeys(pats))]


def rules():
    out = []
    for label, p in PUBLIC + private_patterns():
        try:
            out.append((label, re.compile(p)))
        except re.error:
            pass
    return out


def combined():
    """One compiled regex of every rule (for callers that only need a yes/no)."""
    return re.compile("|".join(f"(?:{r.pattern})" if not r.pattern.startswith("(?i)") else f"(?i:{r.pattern[4:]})"
                               for _, r in rules()))


def scan_lines(lines, rs=None):
    """[(path, lineno, text)] -> [(path, lineno, label)] for lines that break a rule."""
    rs = rs or rules()
    bad = []
    for path, n, text in lines:
        if ALLOW_MARK in text or SKIP_FILE.search(path) or SOPS_FILE.search(path):
            continue
        text = GENERIC.sub("", text)
        for label, r in rs:
            if r.search(text):
                bad.append((path, n, label))
                break
    return bad


def check_sops(path, text):
    """Problems with a *.sops.* file: it must carry sops metadata and every value must be ENC[...]."""
    probs = []
    if not re.search(r"(?m)^sops:\s*$", text) or "mac: ENC[" not in text:
        probs.append("no sops metadata (not encrypted with sops)")
    in_meta = False
    for n, line in enumerate(text.splitlines(), 1):
        if re.match(r"^sops:\s*$", line):
            in_meta = True
            continue
        if in_meta:
            if line and not line.startswith((" ", "\t")):
                in_meta = False
            else:
                continue
        s = line.strip()
        if not s or s.startswith("#ENC[") or s == "---":
            continue
        if s.startswith("#"):
            probs.append(f"line {n}: plaintext comment")
            continue
        val = re.sub(r"^(?:-\s+)+", "", s)          # a list item, or a list's list (- - ENC[…])
        if not val.startswith("ENC["):
            m = re.match(r"^[A-Za-z0-9_.\-\"']+:(?:\s+(.*))?$", val)
            val = ((m.group(1) or "") if m else val).strip()
        if val and not val.startswith("ENC[") and val not in ("|", ">", "|-", ">-"):
            probs.append(f"line {n}: plaintext value")
    return probs


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def staged():
    """Added lines of the staged diff, as (path, lineno, text), plus staged sops files."""
    diff = _git("diff", "--cached", "--no-color", "--unified=0", "--diff-filter=ACMR", "--no-ext-diff")
    out, path, n = [], None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            n = int(m.group(1)) if m else 0
        elif line.startswith("+") and path:
            out.append((path, n, line[1:]))
            n += 1
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").split()
    return out, [p for p in names if SOPS_FILE.search(p)]


def tree(root="."):
    files = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, text=True).stdout.split("\0")
    lines, sops = [], []
    for p in filter(None, files):
        full = os.path.join(root, p)
        if os.path.isdir(full) or not os.path.isfile(full):
            continue                                  # submodules
        if SOPS_FILE.search(p):
            sops.append(p)
            continue
        if SKIP_FILE.search(p):
            continue
        try:
            with open(full, errors="strict") as f:
                for i, t in enumerate(f, 1):
                    lines.append((p, i, t.rstrip("\n")))
        except (UnicodeDecodeError, OSError):
            continue
    return lines, sops


def gitleaks(mode):
    """Run gitleaks when it's installed: 'staged' (protect) or 'tree' (dir). True = clean."""
    exe = None
    for c in ("gitleaks", os.path.expanduser("~/.local/bin/gitleaks")):
        if subprocess.run(["sh", "-c", f"command -v {c}"], capture_output=True).returncode == 0 or os.path.exists(c):
            exe = c
            break
    if not exe:
        return True
    args = [exe, "git", "--staged", "--redact", "--no-banner", "-v", "."] if mode == "staged" else \
        [exe, "dir", "--redact", "--no-banner", "."]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:] + r.stderr[-1000:], file=sys.stderr)
        return False
    return True


def report(bad, sops_probs):
    if not bad and not sops_probs:
        return 0
    print("\nPRIVACY GUARD: this repo is PUBLIC. Blocked:\n", file=sys.stderr)
    for path, n, label in bad[:60]:
        print(f"  {path}:{n}: {label}", file=sys.stderr)
    if len(bad) > 60:
        print(f"  ... and {len(bad) - 60} more", file=sys.stderr)
    for path, probs in sops_probs:
        for p in probs[:10]:
            print(f"  {path}: {p}", file=sys.stderr)
    print("""
Move private values into the encrypted overlay and read them in code:
  bromigos-private edit          # sops edit linux/.config/bromigos/private.sops.yaml
  code: bromigos_private.url("lab"), .get("lan.ping"), .vault("lab_api")   (lib/bromigos_private.py)
  docs/skills: write {{endpoints.lab}}-style placeholders or name the key
Real secrets (tokens, keys) go to Vault, never into the repo; `bromigos-secrets sync` copies them.
A false positive can end its line with `privacy: allow`. See AGENTS.md, "Private values".
""", file=sys.stderr)
    return 1


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check-staged"
    if cmd == "check-staged":
        lines, sops = staged()
        bad = scan_lines(lines)
        sp = [(p, check_sops(p, _git("show", f":{p}"))) for p in sops]
        rc = report(bad, [x for x in sp if x[1]])
        ok = gitleaks("staged")
        return rc or (0 if ok else 1)
    if cmd == "check-tree":
        root = sys.argv[2] if len(sys.argv) > 2 else "."
        lines, sops = tree(root)
        bad = scan_lines(lines)
        sp = []
        for p in sops:
            with open(os.path.join(root, p)) as f:
                sp.append((p, check_sops(p, f.read())))
        rc = report(bad, [x for x in sp if x[1]])
        if rc == 0:
            print(f"privacy guard: {len(lines)} lines in tracked files clean; {len(sops)} sops file(s) encrypted")
        return rc
    if cmd == "check-sops":
        with open(sys.argv[2]) as f:
            probs = check_sops(sys.argv[2], f.read())
        return report([], [(sys.argv[2], probs)] if probs else [])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
