"""The asset licence check (docs/lab-models.md, "Licence lineage"; docs/ASSETS.md).

`bromigos lab models check`, in a bromigOS checkout, also reads every provenance log the
repository keeps beside its generated art (mascot/provenance.jsonl, themes/*/art.log.jsonl,
**/holo/generations.jsonl). For each model a log names it finds the catalog's entry, a
[[model]] (by id, alias or workflow name) or an [api] (a model used through someone's
API), and computes its effective licence tier over its whole chain (catalog.effective).

Anything that isn't clean (conditional or non-commercial) must be covered by a row of
docs/ASSETS.md's checklist that names the asset's folder in backticks and carries an
explicit owner decision in its "Ships?" cell: **yes** (who, YYYY-MM-DD) or **no**. A
model the catalog doesn't know is a problem too: its terms can't be checked. A model whose
terms are too unclear to call (its licence has a `decision`) is reported as a note even when
an older decision covers the folder, so the owner can decide again.
"""
import fnmatch
import json
import os
import re

LOGS = ("provenance.jsonl", "generations.jsonl", "art.log.jsonl")
SKIP_DIRS = {".git", "node_modules", "target", "pkg", "src-tauri", "__pycache__"}
DECISION = re.compile(r"\*\*(yes|no)\*\*\s*\(([^)]*?)(\d{4}-\d{2}-\d{2})\)|\*\*no\*\*|\*\*never\*\*", re.I)


CATALOG_IN_REPO = os.path.join("homelab", "share", "lab", "models.toml")


def repo_root(catalog_path):
    """The bromigOS checkout whose own catalog this is (<root>/homelab/share/lab/models.toml,
    with docs/ASSETS.md beside it), or None: an installed copy, or another file, isn't checked."""
    p = os.path.abspath(catalog_path)
    if not p.endswith(os.sep + CATALOG_IN_REPO):
        return None
    root = p[:-len(os.sep + CATALOG_IN_REPO)]
    return root if os.path.isfile(os.path.join(root, "docs", "ASSETS.md")) else None


def logs(root):
    """The provenance logs under root: [relative path]."""
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        rel = os.path.relpath(d, root)
        if rel.startswith("packaging" + os.sep) and os.sep + "pkg" in rel:
            continue
        for f in sorted(files):
            if f in LOGS:
                out.append(os.path.normpath(os.path.join(rel, f)))
    return out


def names(rec):
    """The model names one log record gives: "seedvr2-7b (int8) + rife 4.9" -> [seedvr2-7b, rife 4.9]."""
    raw = rec.get("model") or ""
    if not isinstance(raw, str):
        return []
    out = []
    for part in raw.split("+"):
        n = re.sub(r"\s*\(.*?\)\s*", " ", part).strip().lower()
        n = n.split(":", 1)[1] if re.match(r"^(homelab|comfyui|nolgia)[:/]", n) else n
        if n:
            out.append(n)
    return out


def index(cat):
    """{name: ("model", Model) | ("api", Api)}: ids, aliases and workflow names."""
    idx = {}
    for m in cat.models.values():
        for n in (m.id, *m.aliases, *(v.workflow for v in m.variants if v.workflow)):
            idx.setdefault(n.lower(), ("model", m))
    for a in cat.apis.values():
        idx.setdefault(a.id.lower(), ("api", a))
    return idx


def tier_of(cat, kind, obj):
    """{tier, reason, decision} for a model or an API."""
    if kind == "model":
        e = cat.effective(obj)
        return {"tier": e["tier"], "reason": e["reason"], "decision": e["decision"], "name": obj.name}
    lic = obj.licence
    return {"tier": lic.tier, "reason": f"{lic.name}: {lic.why}", "name": obj.name,
            "decision": [f"{obj.name}: {lic.decision}"] if lic.decision else []}


def decisions(assets_md):
    """[{paths, decision, who, date, row}] from docs/ASSETS.md's checklist table: every row whose
    "Ships?" cell is an explicit decision, with the backticked paths it names."""
    out = []
    in_table = False
    for line in assets_md.splitlines():
        if line.startswith("## "):
            in_table = line.strip() == "## The checklist"
            continue
        if not in_table or not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "Asset":
            continue
        m = DECISION.search(cells[2])
        if not m:
            continue
        paths = [p.rstrip("/") for p in re.findall(r"`([^`\s]+/[^`\s]*)`", line)]
        out.append({"paths": paths, "decision": (m.group(1) or m.group(0).strip("*")).lower(),
                    "who": (m.group(2) or "").strip(" ,") if m.group(1) else "", "date": m.group(3) or "",
                    "row": cells[0][:80]})
    return out


def covers(paths, folder):
    folder = folder.rstrip("/")
    for p in paths:
        if any(ch in p for ch in "*?["):
            # a folder pattern (themes/*/holo), or a file in one (themes/*/holo/generations.jsonl)
            if any(fnmatch.fnmatch(folder, q) or fnmatch.fnmatch(folder + "/x", q + "/*")
                   for q in (p, os.path.dirname(p)) if q):
                return True
            continue
        if folder == p or p.startswith(folder + "/") or folder.startswith(p + "/"):
            return True
    return False


def check(cat, root):
    """{"problems": [...], "notes": [...], "assets": [{folder, log, models: [{name, tier, reason}],
    decision}]}. A problem: a non-clean model in a folder no explicit decision covers, or a
    model the catalog doesn't know."""
    idx = index(cat)
    with open(os.path.join(root, "docs", "ASSETS.md")) as f:
        rows = decisions(f.read())
    problems, notes, assets = [], [], []
    for rel in logs(root):
        folder = os.path.dirname(rel) or "."
        seen = {}
        with open(os.path.join(root, rel)) as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    problems.append(f"{rel}:{n}: not a JSON line")
                    continue
                for name in names(rec):
                    if name in seen:
                        continue
                    hit = idx.get(name)
                    if hit is None:
                        seen[name] = {"name": name, "tier": "unknown", "reason": "not in the catalog", "decision": []}
                        problems.append(f"{rel}: {name!r} isn't in the catalog ([[model]], its aliases, or [api]): "
                                        "its terms can't be checked")
                        continue
                    seen[name] = tier_of(cat, *hit)
        bad = {k: v for k, v in seen.items() if v["tier"] != "clean"}
        row = next((r for r in rows if covers(r["paths"], folder)), None)
        assets.append({"folder": folder, "log": rel, "models": list(seen.values()),
                       "decision": ({k: row[k] for k in ("decision", "who", "date", "row")} if row else None)})
        known_bad = [v for v in bad.values() if v["tier"] != "unknown"]
        if known_bad and row is None:
            problems.append(f"{folder}/: made with " + ", ".join(f"{v['name']} ({v['tier']})" for v in known_bad)
                            + "; docs/ASSETS.md has no checklist row naming this folder with an explicit decision "
                              "(**yes** (who, date) or **no**). bromigos lab models check --json gives the reasons")
        for v in known_bad:
            for d in v["decision"]:
                notes.append(f"{folder}/: needs a decision: {d}"
                             + (f" (the row \"{row['row']}\" decided on {row['date']}, before this was known)"
                                if row and row["date"] else ""))
    return {"problems": problems, "notes": list(dict.fromkeys(notes)), "assets": assets}
