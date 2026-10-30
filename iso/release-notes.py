#!/usr/bin/env python3
"""Puts a release's ISO on its GitHub Release's text (docs/iso.md, "Where the ISO lives").

    iso/release-notes.py --tag vX.Y.Z --index index.json [--repo OWNER/NAME] [--dry-run]

index.json is the version's index from `iso/publish.sh pointers` (every ISO of the
version: its address, size, checksum and signature). The line that starts `- **ISO:**`
in the Release's text is replaced with the download links (release.py writes a
placeholder there); a Release without one gets the line at the end. Running it again
gives the same text. It needs `gh`, signed in (GH_TOKEN).
"""
import argparse
import json
import re
import subprocess
import sys

DOWNLOAD_PAGE = "https://bromigos.org/download"
LABELS = {"bromigos": "the desktop and installer", "bromigos-fieldkit": "Field Kit, tools and repair"}


def human(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "bytes" else f"{n} bytes"
        n /= 1000


def iso_line(index):
    parts = []
    for m in index["isos"]:
        what = LABELS.get(m["edition"], m["edition"])
        parts.append(f"[{m['file']}]({m['url']}) ({what}, {human(m['size'])}, SHA-256 `{m['sha256']}`, "
                     f"[signature]({m['sig_url']}))")
    return ("- **ISO:** " + "; ".join(parts) + ". One file each, built, checked and tested by CI from this "
            f"release. The [Download page]({DOWNLOAD_PAGE}) says how to put it on a USB stick. Check it with "
            "`sha256sum -c <file>.sha256` and `gpg --verify <file>.sig <file>`, with `packaging/keys/bromigos.asc`.")


def replace(body, line):
    lines = body.rstrip("\n").split("\n")
    hits = [i for i, l in enumerate(lines) if l.startswith("- **ISO:**")]
    if hits:
        lines[hits[0]] = line
        for i in reversed(hits[1:]):
            del lines[i]
    else:
        lines += ["", line] if lines and lines[-1].strip() else [line]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--repo", default="bromigos-org/bromigOS")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    index = json.load(open(a.index))
    if not index.get("isos"):
        sys.exit("release-notes.py: the index lists no ISO")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", a.tag):
        sys.exit(f"release-notes.py: {a.tag} isn't a stable release's tag")
    body = subprocess.run(["gh", "release", "view", a.tag, "-R", a.repo, "--json", "body", "--jq", ".body"],
                          check=True, capture_output=True, text=True).stdout
    new = replace(body, iso_line(index))
    if a.dry_run:
        print(new)
        return
    if new.strip() == body.strip():
        print(f"{a.tag}: the Release already says it")
        return
    subprocess.run(["gh", "release", "edit", a.tag, "-R", a.repo, "--notes-file", "-"], input=new, text=True,
                   check=True, stdout=subprocess.DEVNULL)
    print(f"{a.tag}: the Release's text has the ISO")


if __name__ == "__main__":
    main()
