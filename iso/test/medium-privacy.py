#!/usr/bin/env python3
"""The privacy check of an unpacked medium (iso/check-medium.sh unpacks it; docs/iso.md).

    medium-privacy.py ROOT ISO PKGS

ROOT is the live system (the squashfs), ISO the medium's own files (the boot menus), PKGS
bromigOS's packages from the offline repository, each unpacked in its own directory.

Two layers, with the repository's own guard (tools/release/privacy_guard.py and
tools/privacy/private_words.py):

- every text file and every file name on the medium: the lab's own names (the private
  overlay's names and machines, PRIVACY_PATTERNS, and the hashed internal words). Arch's
  packages are scanned too; a hit there is an everyday word in someone else's data, which
  the report shows apart;
- what bromigOS itself puts there (PKGS, the files no pacman package owns in ROOT, and the
  boot menus): the whole repository guard as well (private addresses, internal host names,
  MAC addresses, token shapes), honouring its `privacy: allow` marks.

A finding is file:line and the rule's label, never the matched text. It exits 1 when a
bromigOS file breaks a rule, 0 otherwise.
"""
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools", "release"))
sys.path.insert(0, os.path.join(REPO, "tools", "privacy"))
import privacy_guard as G  # noqa: E402
import private_words as P  # noqa: E402

SKIP_DIRS = {"proc", "sys", "dev", "run"}


def _accepted():
    path = os.path.join(HERE, "privacy-accepted.txt")
    if not os.path.exists(path):
        return set()
    lines = (l.split(" #", 1)[0].strip() for l in open(path, encoding="utf-8"))
    return {l for l in lines if l and not l.startswith("#")}


ACCEPTED = _accepted()
MAXSIZE = 8 << 20
FINDER = PRIV = FULL = LAB_AS_LAB = None


def init():
    global FINDER, PRIV, FULL, LAB_AS_LAB
    FINDER = P.Finder()
    lab = P.lab_name_pattern()
    LAB_AS_LAB = re.compile(lab + r"[ _]lab", re.I) if lab else None
    PRIV = []
    for label, p in G.private_patterns():
        try:
            PRIV.append((label, re.compile(p)))
        except re.error:
            pass
    FULL = G.rules()


def is_text(path):
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > MAXSIZE:
            return False
        with open(path, "rb") as f:
            return b"\0" not in f.read(8192)
    except OSError:
        return False


def walk(top):
    for d, dirs, files in os.walk(top):
        if d == top:
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            yield os.path.join(d, f)


def owned(root, mine):
    """The paths ROOT's packages own: (Arch's, bromigOS's), bromigOS's being the packages
    named in `mine`."""
    theirs, ours, local = set(), set(), os.path.join(root, "var/lib/pacman/local")
    for pkg in os.listdir(local):
        desc, fp = os.path.join(local, pkg, "desc"), os.path.join(local, pkg, "files")
        if not os.path.exists(fp):
            continue
        name = re.search(r"%NAME%\n(.+)", open(desc).read()).group(1) if os.path.exists(desc) else ""
        into = ours if name in mine else theirs
        sect = None
        for line in open(fp, errors="replace"):
            line = line.rstrip("\n")
            if line.startswith("%"):
                sect = line
            elif sect == "%FILES%" and line:
                into.add("/" + line)
    return theirs, ours


def pkg_names(pkgs):
    """The names of the packages unpacked in PKGS (their .PKGINFO)."""
    names = set()
    for d in os.listdir(pkgs):
        try:
            m = re.search(r"^pkgname = (.+)$", open(os.path.join(pkgs, d, ".PKGINFO")).read(), re.M)
        except OSError:
            continue
        if m:
            names.add(m.group(1).strip())
    return names


def private_reason(text, ours=False):
    """The first private name in `text`. In bromigOS's own files the lab's name counts only
    as a lab ("<name> lab"): it is also a public place in the lore (bromigos-live's
    catalog), as live/tests/test_driftmap.py allows."""
    for why in FINDER.reasons(text):
        if why != "the lab's name" or not ours or (LAB_AS_LAB and LAB_AS_LAB.search(text)):
            return why
    return next((label for label, r in PRIV if r.search(text)), None)


def scan(job):
    path, full, shown = job
    out = []
    try:
        text = open(path, errors="replace").read()
    except OSError:
        return out
    for n, line in enumerate(text.splitlines(), 1):
        why = private_reason(line, full)
        if not why and full and G.ALLOW_MARK not in line and not G.SKIP_FILE.search(path):
            t = G.GENERIC.sub("", line)
            why = next((label for label, r in FULL if r.search(t)), None)
        if why:
            out.append((full, f"{shown}:{n}: {why}"))
            if len(out) >= 20:
                break
    return out


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    root, iso, pkgs = sys.argv[1:4]
    init()
    if not FINDER.have_overlay and not PRIV:
        print("note: no private overlay or PRIVACY_PATTERNS here: only the hashed words and the public shapes")
    own, from_pkgs = owned(root, pkg_names(pkgs))
    jobs, bad = [], []
    for top, label, ours in ((root, "root", False), (iso, "iso", True), (pkgs, "pkgs", True)):
        for p in walk(top):
            rel = p[len(top):]
            if top == root and rel in from_pkgs:
                continue        # a bromigOS package's file: scanned in PKGS, by the whole guard
            shown = f"{label}:{rel}"
            why = private_reason(shown, ours)
            if why:
                bad.append((True, f"{shown}: (its name) {why}"))
            if not is_text(p):
                continue
            # in the live system, bromigOS's are the files no package owns (the overlay and
            # what customize_airootfs.sh made); its packages' are in PKGS
            mine = ours or (rel not in own and not rel.startswith(("/var/lib/pacman/", "/var/lib/bromigos/repo/")))
            jobs.append((p, mine, shown))
    with ProcessPoolExecutor(min(12, os.cpu_count() or 1), initializer=init) as ex:
        for res in ex.map(scan, jobs, chunksize=64):
            bad.extend(res)
    ours = [b for mine, b in bad if mine]
    theirs = [b for mine, b in bad if not mine]
    # findings judged harmless in a package already published (its file can't change any
    # more): ACCEPTED lists each one exactly, with the package's version in its path, so it
    # never covers the next build; the source is fixed for that
    accepted = [b for b in ours if b in ACCEPTED]
    ours = [b for b in ours if b not in ACCEPTED]
    print(f"{len(jobs)} text files, {sum(1 for j in jobs if j[1])} of them bromigOS's")
    if theirs:
        print(f"\nin Arch's packages ({len(theirs)}; everyday words in someone else's data, check by eye):")
        for b in theirs[:60]:
            print("  " + b)
    if accepted:
        print(f"\naccepted (iso/test/privacy-accepted.txt): {len(accepted)}")
        for b in accepted:
            print("  " + b)
    print(f"\nin bromigOS's files: {len(ours)}")
    for b in ours[:200]:
        print("  " + b)
    sys.exit(1 if ours else 0)


if __name__ == "__main__":
    main()
