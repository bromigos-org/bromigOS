#!/usr/bin/env python3
"""The Drift map's packaged lore catalog (live/lore/catalog.json), from bromigos.org's
public export.

bromigos.org's scripts/export_site_content.py turns the canon catalog into the site's
public lore (public/lore/data/lore.json): canon only, nothing private, checked by its
check_private. This copies that export's entries and timeline, keeping only the fields the
Drift map reads (live/live/drift_map.py, load_catalog), and runs the export's own
check_private over the result again, with the operators export's secret phrases, as the
export does. Every repository is read at a committed ref, never a working tree.

Run it when the site's lore changes, then commit live/lore/catalog.json:

  tools/lore/sync-catalog.py [--org DIR] [--ref origin/main] [--no-fetch] [--check]

--org is the folder holding the bromigos.org and platform checkouts (default: the one
holding this repository). --check writes nothing and fails when the file is out of date.
"""
import argparse
import json
import subprocess
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "live" / "lore" / "catalog.json"
SITE_EXPORT = "scripts/export_site_content.py"
SITE_LORE = "public/lore/data/lore.json"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout


def site_export(site, ref):
    """The site's export script at `ref`, as a module (for its check_private)."""
    mod = types.ModuleType("export_site_content")
    mod.__file__ = str(site / SITE_EXPORT)
    exec(compile(git(site, "show", f"{ref}:{SITE_EXPORT}"), SITE_EXPORT, "exec"), mod.__dict__)
    return mod


def build(org, ref, fetch):
    site, plat = org / "bromigos.org", org / "platform"
    for repo in (site, plat):
        if fetch:
            git(repo, "fetch", "-q", "origin")
    lore = json.loads(git(site, "show", f"{ref}:{SITE_LORE}"))
    out = {
        "source": ("bromigos.org " + SITE_LORE + ", the public lore export; regenerate with "
                   "tools/lore/sync-catalog.py"),
        "site": git(site, "rev-parse", "--short", ref).strip(),
        "canon": (lore.get("generatedFrom") or {}).get("platform", ""),
        "entries": [{"id": e["id"], "name": e["name"], "kind": e["kind"], "status": e.get("status", ""),
                     "summary": e.get("summary", ""),
                     "relationships": [{"target": r["target"], "relation": r.get("relation", "")}
                                       for r in e.get("relationships") or [] if r.get("target")]}
                    for e in lore["entries"]],
        "timeline": [{"order": t.get("order", 0), "period": t.get("period", ""), "event": t.get("event", "")}
                     for t in lore.get("timeline") or []],
    }
    ex = site_export(site, ref)
    secrets = ex.secret_phrases(git(plat, "show", f"{ref}:{ex.SECRET_PHRASES_SOURCE}"))
    ex.check_private(out, "catalog", secrets)        # raises SystemExit naming what it found
    return json.dumps(out, indent=1, ensure_ascii=False) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--org", type=Path, default=REPO.parent, help="the folder holding the org's checkouts")
    ap.add_argument("--ref", default="origin/main", help="the committed ref to read in each repository")
    ap.add_argument("--no-fetch", action="store_true", help="don't fetch before reading the ref")
    ap.add_argument("--check", action="store_true", help="write nothing; fail if the file is out of date")
    args = ap.parse_args()
    text = build(args.org, args.ref, not args.no_fetch)
    old = OUT.read_text() if OUT.exists() else ""
    if args.check:
        same = json.loads(old or "{}").get("entries") == json.loads(text)["entries"] and \
            json.loads(old or "{}").get("timeline") == json.loads(text)["timeline"]
        print(f"{OUT.relative_to(REPO)}: " + ("current" if same else "out of date (run tools/lore/sync-catalog.py)"))
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    n = json.loads(text)
    print(f"{OUT.relative_to(REPO)}: {len(n['entries'])} entries, {len(n['timeline'])} timeline events "
          f"(site {n['site']}, canon {n['canon']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
