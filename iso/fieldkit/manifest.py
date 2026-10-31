#!/usr/bin/env python3
"""Field Kit's package list, from its one source, packages.toml (docs/fieldkit.md).

  manifest.py live                  the medium's packages, one per line (packages.x86_64)
  manifest.py store                 what else the offline store must hold: the edition's and
                                    the installer's hardware extras, one per line
  manifest.py edition               the edition's packages, as JSON (fieldkit/edition.json's)
  manifest.py optional              the packages marked if_available ("NAME live|store"): the
                                    build adds each one a repository has (a package not yet
                                    published, such as brodec-machine before its first release)
  manifest.py docs --sizes FILE [--closure FILE] --out docs/fieldkit-packages.md
                                    the manifest page: every package by section with its
                                    installed size and reason, the largest, and what was left
                                    out. FILE: "name<TAB>bytes" lines (the build writes them,
                                    iso/build-in-container.sh: fieldkit-sizes.tsv)
"""

import argparse
import json
import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ["Boot & hardware", "Repair", "Lab", "Tools", "Server"]


def load(path=os.path.join(HERE, "packages.toml")):
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    pkgs = doc.get("package", [])
    # bromigOS Server's own additions (server-packages.toml): in the offline store, not running
    server = os.path.join(os.path.dirname(path), "server-packages.toml")
    if os.path.isfile(server):
        with open(server, "rb") as f:
            extra = tomllib.load(f)
        pkgs += extra.get("package", [])
        doc.setdefault("left_out", []).extend(extra.get("left_out", []))
    seen = {}
    for p in pkgs:
        p.setdefault("live", True)
        p.setdefault("edition", False)
        p.setdefault("store", False)
        p.setdefault("if_available", False)
        if p["name"] in seen:                        # listed twice: one row, either's flags
            q = seen[p["name"]]
            for k in ("live", "edition", "store"):
                q[k] = q[k] or p[k]
            continue
        seen[p["name"]] = p
    return list(seen.values()), doc.get("left_out", [])


def mib(n):
    return f"{n / (1 << 20):.1f} MiB" if n >= 1 << 20 else f"{n / 1024:.0f} KiB"


def docs(pkgs, left, sizes, closure, out):
    lines = [
        "# Field Kit's packages",
        "",
        "<!-- Made by iso/fieldkit/manifest.py from iso/fieldkit/packages.toml and the build's sizes. Edit those, not this page. -->",
        "",
        "Every package on the Field Kit medium is here for a reason. A package goes on it only when",
        "one of these needs it: (a) a Field Kit menu item, (b) booting and hardware support on",
        "unknown machines, (c) bromigOS Server, the installed edition, or (d) a documented server or lab",
        "job. [fieldkit.md](fieldkit.md) describes Field Kit.",
        "",
        "Sizes are each package's own installed size. Their dependencies come with them; the",
        "totals below count those too.",
        "",
    ]
    if closure:
        live_total = sum(closure.get("live", {}).values())
        store_total = sum(closure.get("store", {}).values())
        lines += [f"- The running medium: {len(closure.get('live', {}))} packages with their dependencies, "
                  f"{mib(live_total)} installed.",
                  f"- The offline store: {len(closure.get('store', {}))} package files, {mib(store_total)} "
                  "(compressed, as downloaded).", ""]
    for section in ORDER:
        rows = [p for p in pkgs if p["section"] == section]
        if not rows:
            continue
        lines += [f"## {section}", "", "| Package | Size | On | Why |", "|---|---:|---|---|"]
        for p in rows:
            where = ", ".join(w for w, on in (("medium", p["live"]), ("Server", p["edition"]), ("store only", p["store"])) if on)
            size = mib(sizes[p["name"]]) if p["name"] in sizes else "?"
            lines.append(f"| `{p['name']}` | {size} | {where} | {p['reason']} |")
        lines.append("")
    if sizes:
        named = {p["name"] for p in pkgs}
        live = closure.get("live", {}) or {n: 1 for n in named}
        biggest = sorted(((n, s) for n, s in sizes.items() if n in live),
                         key=lambda x: -x[1])[:20]
        lines += ["## The largest", "", "The 20 largest packages on the medium, dependencies included:", "",
                  "| Package | Size |", "|---|---:|"]
        lines += [f"| `{n}` | {mib(s)} |" for n, s in biggest]
        lines.append("")
    lines += ["## Left out", "", "Arch's own live medium (archiso's releng profile) carries these; Field Kit doesn't.", "",
              "| Packages | Why not |", "|---|---|"]
    lines += [f"| {r['names']} | {r['reason']} |" for r in left]
    lines.append("")
    with open(out, "w") as f:
        f.write("\n".join(lines))


def read_sizes(path):
    out = {}
    if path and os.path.isfile(path):
        with open(path) as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[1].isdigit():
                    out[parts[0]] = int(parts[1])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=["live", "store", "edition", "optional", "docs"])
    ap.add_argument("--sizes", help="name<TAB>installed bytes, for every package of the closure")
    ap.add_argument("--live-closure", help="the medium's closure: name<TAB>installed bytes")
    ap.add_argument("--store-closure", help="the offline store: name<TAB>file bytes")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    pkgs, left = load()
    sure = [p for p in pkgs if not p["if_available"]]
    if a.what == "live":
        print("\n".join(p["name"] for p in sure if p["live"]))
    elif a.what == "store":
        print("\n".join(p["name"] for p in sure if p["edition"] or p["store"]))
    elif a.what == "edition":
        print(json.dumps([p["name"] for p in sure if p["edition"]]))
    elif a.what == "optional":
        # if_available: on the medium once a repository has it (iso/build-in-container.sh asks
        # pacman), so a build before its first publish leaves it out: "NAME live|store" lines
        print("\n".join(f"{p['name']} {'live' if p['live'] else 'store'}" for p in pkgs if p["if_available"]))
    else:
        sizes = read_sizes(a.sizes)
        closure = {"live": read_sizes(a.live_closure), "store": read_sizes(a.store_closure)}
        docs(pkgs, left, sizes, closure, a.out or os.path.join(HERE, "..", "..", "docs", "fieldkit-packages.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
