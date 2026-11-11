#!/usr/bin/env python3
"""Fails when the repository holds a file that must never ship (tools/assets/blocked.sha256):
the meshes made with Pixal3D, whose DINOv3 licence isn't cleared, and everything baked or
rendered from them (docs/ASSETS.md, 3D holograms).

    tools/assets/check-blocked.py            the files git tracks, and the ones a commit would add
    tools/assets/check-blocked.py PATH ...   these files (a folder: every file under it)

Only files of a listed size are hashed, so it takes a moment however big the checkout is.
"""
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def blocked(path=os.path.join(HERE, "blocked.sha256")):
    """{size: {sha256: what it is}}"""
    out = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            h, size, what = line.split(None, 2)
            out.setdefault(int(size), {})[h.lower()] = what
    return out


def candidates(args):
    if args:
        for a in args:
            if os.path.isdir(a):
                for d, _, files in os.walk(a):
                    for f in files:
                        yield os.path.join(d, f)
            else:
                yield a
        return
    # tracked files, and untracked ones that aren't ignored (what `git add -A` would commit)
    names = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           check=True, capture_output=True).stdout.split(b"\0")
    for n in names:
        if n:
            yield os.path.join(ROOT, os.fsdecode(n))


def main(argv):
    bad = blocked()
    found = []
    for p in candidates(argv):
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        if size not in bad or not os.path.isfile(p):
            continue
        with open(p, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        if h in bad[size]:
            found.append(f"{os.path.relpath(p, ROOT)}: {bad[size][h]}")
    if found:
        print("These files must never be committed (tools/assets/blocked.sha256; docs/ASSETS.md, 3D holograms):\n  "
              + "\n  ".join(found), file=sys.stderr)
        return 1
    print(f"no blocked file ({sum(len(v) for v in bad.values())} listed)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
