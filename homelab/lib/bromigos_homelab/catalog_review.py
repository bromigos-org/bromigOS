"""The lab model catalog's review queue (docs/lab-models.md, "Reviewing what the refresh finds").

    bromigos lab models review                 what the weekly refresh found and nobody decided yet,
                                               each with a recommendation: adopt, watch or ignore
    bromigos lab models review --json          the same, for scripts
    bromigos lab models review accept ID       mark it accepted: research it and add it as a [[model]]
    bromigos lab models review ignore ID [--reason TEXT]
                                               dismiss it: the refresh never proposes it again

The recommendation is computed from the catalog's own rules, never from a person's taste:
whether bromigOS's stack runs it, its licence tier (the [licence] its Hub licence id means),
whether it fits a setup the catalog plans for (its parameter count), whether it's a newer
member of a family the catalog picks, and the Hub signals the refresh reads (likes, downloads,
age). `accept` and `ignore` edit models.toml in a bromigOS checkout (they need tomlkit, which
keeps the file's layout); commit the change and open a pull request as for any data edit.

The weekly CI run (.github/workflows/lab-catalog.yml) keeps one open "Lab catalog review"
issue up to date with this queue (`issue-sync`) instead of filing a new issue every week, and
archives entries that waited more than eight weeks without a decision (`archive`).
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import catalog as C

ACTIONS = ("adopt", "watch", "ignore")
ARCHIVE_AFTER_DAYS = 56          # eight weeks with no decision: out of the queue, into [[archived]]
ISSUE_TITLE = "Lab catalog review"
ISSUE_MARK = "<!-- bromigos-lab-catalog-review -->"
STRONG_LIKES, STRONG_DOWNLOADS = 300, 20000      # many people use it
WEAK_LIKES, WEAK_DOWNLOADS = 100, 5000           # few people use it yet
SMALL_SHARE = 0.35               # smaller than this share of the catalog's smallest model for the job
NEAR_BEST = 8.0                  # an incumbent within this many quality points of the job's best
# GiB per billion parameters, by bits, and a little for the runtime (the catalog's own sizing is
# per variant; a candidate has only its parameter count)
GIB_PER_B = {4: 0.56, 8: 1.05, 16: 2.0}
OVERHEAD_GIB = 1.5
ONE_CARD_GIB = 32.0              # the biggest consumer card the catalog plans for (RTX 5090)
TIER_RANK = {"clean": 0, "conditional": 1, "unknown": 2, "non-commercial": 3}
DEFAULT_CATALOG = os.path.normpath(os.path.join(C.HERE, "..", "..", "share", "lab", "models.toml"))


# ------------------------------------------------------------------ the signals
def _today(today=None):
    if isinstance(today, datetime.date):
        return today
    return datetime.date.fromisoformat(today) if today else datetime.date.today()


def age_days(entry, today=None):
    try:
        return (_today(today) - datetime.date.fromisoformat(str(entry.get("found"))[:10])).days
    except ValueError:
        return None


def params_of(entry):
    """(total, active) billions of parameters: the refresh's figure, else the repository's name
    ("Qwen3.6-35B-A3B" -> (35, 3), "GPT-X3-150M" -> (0.15, 0.15)); (None, None) when neither says."""
    if entry.get("params_b"):
        p = float(entry["params_b"])
        return p, float(entry.get("active_b") or p)
    name = (entry.get("repo") or "").split("/")[-1]
    total = active = None
    for m in re.finditer(r"(?<![\w.])(A)?(\d+(?:\.\d+)?)([BbMm])(?![a-zA-Z0-9])", name):
        v = float(m.group(2)) / (1000.0 if m.group(3) in "Mm" else 1.0)
        if m.group(1):
            active = v
        elif total is None:
            total = v
    if total is None:
        return None, None
    return total, active or total


def _hub_signals(entry):
    """likes, downloads: the fields the refresh records, else read back from its `why`."""
    why = entry.get("why") or ""
    out = {}
    for k, pat in (("likes", r"(\d[\d,]*) likes"), ("downloads", r"(\d[\d,]*) downloads")):
        if entry.get(k) is not None:
            out[k] = int(entry[k])
            continue
        m = re.search(pat, why)
        out[k] = int(m.group(1).replace(",", "")) if m else None
    return out


def fit(params_b):
    """{"gib4", "gib8", "where"}: the memory a candidate needs at 4 and 8 bits, and the smallest
    kind of setup the catalog plans for that holds it; None when its size isn't known."""
    if not params_b:
        return None
    g4 = params_b * GIB_PER_B[4] + OVERHEAD_GIB
    g8 = params_b * GIB_PER_B[8] + OVERHEAD_GIB
    if g8 <= 24:
        where = "one 24 GB card at 8-bit"
    elif g4 <= 24:
        where = "one 24 GB card at 4-bit"
    elif g4 <= ONE_CARD_GIB:
        where = "one 32 GB card at 4-bit"
    elif g4 <= 2 * 108:
        where = "two linked unified-memory boxes or a 96 GB card"
    elif g4 <= 8 * 75:
        where = "eight 80 GB cards"
    elif g4 <= 8 * 180:
        where = "eight B200s"
    else:
        where = None
    return {"gib4": round(g4, 1), "gib8": round(g8, 1), "where": where}


SURVEY_TIER = {"clean": "clean", "conditional": "conditional", "no": "non-commercial",
               "non-commercial": "non-commercial"}


def licence_tier(cat, entry):
    """(tier, words): the tier of the [licence] the entry's Hub licence id means, or the tier a
    survey worked out over the whole chain (its `tier`, `tier_reason`), whichever is worse."""
    hub = entry.get("licence") or ""
    lic = cat.hub_licence(hub)
    st = SURVEY_TIER.get(entry.get("tier") or "")
    if st and (lic is None or TIER_RANK[st] > TIER_RANK[lic.tier]):
        why = entry.get("tier_reason") or entry.get("licence_name") or hub
        return st, f"{entry.get('licence_name') or hub} ({st}: {why})"
    if lic is None:
        return "unknown", ("the Hub names no licence" if not hub or hub == "unknown"
                           else f"its licence is '{hub}' on the Hub: read the card")
    return lic.tier, f"{lic.name} ({lic.tier})"


def _smallest(cat, cap):
    sizes = [m.params_b for m in cat.models.values() if cap in m.caps and m.params_b]
    return min(sizes) if sizes else None


def _incumbent_near_best(cat, mid):
    m = cat.models.get(mid or "")
    if not m:
        return None, False
    cap = m.caps[0]
    best = max((v.quality(cap) for v in cat.variants(cap) if v.ready), default=0.0)
    q = m.quality.get(cap, m.quality.get("*", 0.0))
    return m, q >= best - NEAR_BEST


def _num(n):
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 10_000:
        return f"{n / 1e3:.0f}k"
    return str(n)


# ------------------------------------------------------------------ the recommendation
def recommend(cat, entry, today=None):
    """{"action": adopt|watch|ignore, "reason": plain words, "signals": {...}} for one
    [[pending]] entry, from the catalog's rules (module docstring)."""
    cap = entry.get("capability") or ""
    kind = entry.get("kind") or ""
    stack = entry.get("stack") or ""
    ready = stack.startswith("ready")
    tier, lic_words = licence_tier(cat, entry)
    total, active = params_of(entry)
    f = fit(total)
    hub = _hub_signals(entry)
    likes, dl = hub["likes"], hub["downloads"]
    age = age_days(entry, today)
    sig = {"stack": "ready" if ready else "needs support", "licence_tier": tier, "params_b": total,
           "active_b": active, "fit": f, "likes": likes, "downloads": dl, "age_days": age}
    used = ", ".join(x for x in (f"{_num(likes)} likes" if likes is not None else "",
                                 f"{_num(dl)} downloads" if dl is not None else "") if x)

    def out(action, *why):
        return {"action": action, "reason": "; ".join(w for w in why if w), "signals": sig}

    name = (entry.get("repo") or "").split("/")[-1]
    if kind == "licence changed":
        m = cat.models.get(entry.get("model") or "")
        have = m.licence.name if m else "the catalog's"
        return out("adopt", f"the Hub now says '{entry.get('licence')}' ({lic_words}); the catalog has {have}",
                   "read the card, then set the model's licence: the licence filter and region checks depend on it")
    if kind == "survey":
        return _survey(entry, out, ready, tier, lic_words, f, stack)
    if f and f["where"] is None:
        return out("ignore", f"too big for any setup the catalog plans for (about {f['gib4']:.0f} GiB at 4-bit)")
    small = _smallest(cat, cap)
    if total and small and cap in C.SERVED and total < SMALL_SHARE * small:
        return out("ignore", f"{total:g}B parameters: far smaller than the smallest {cap} model the catalog keeps "
                             f"({small:g}B), so it won't be a pick")
    if cap in ("llm", "code", "vision") and re.search(r"(^|[-_])base($|[-_])", name, re.I):
        return out("ignore", "a base model, not tuned for chat and tools")
    if tier == "non-commercial" and not ready:
        return out("ignore", f"{lic_words} and bromigOS's stack can't run it ({stack or 'no runtime'})")
    inc, near = _incumbent_near_best(cat, entry.get("model")) if kind == "newer in family" else (None, False)
    strong = (likes or 0) >= STRONG_LIKES or (dl or 0) >= STRONG_DOWNLOADS or near
    weak = (likes or 0) < WEAK_LIKES and (dl or 0) < WEAK_DOWNLOADS and not near
    size = f"about {f['gib4']:.0f} GiB at 4-bit, fits {f['where']}" if f else "its size isn't known yet"
    family = (f"a newer {inc.family or inc.name} (the catalog's {inc.name} is "
              f"{'near the top' if near else 'not the top'} for {inc.caps[0]})") if inc else ""
    if not ready:
        if weak:
            return out("ignore", f"bromigOS's stack can't run it yet ({stack.removeprefix('needs support: ')})",
                       f"and few people use it ({used})" if used else "")
        return out("watch", f"waiting for support: {stack.removeprefix('needs support: ')}", family, lic_words, used)
    if tier == "unknown":
        return out("watch", lic_words, "the licence decides whether it can be a pick", family, size, used)
    if tier == "non-commercial":
        return out("watch", f"{lic_words}: a pick only under the 'any' licence filter", family, size, used)
    if re.search(r"preview", name, re.I) and not near:
        return out("watch", "a preview: wait for the release", lic_words, size, used)
    if strong:
        return out("adopt", f"ready ({stack.removeprefix('ready').strip(' ()') or 'runs today'})", lic_words, size,
                   family or used, "research its quality, peak VRAM and speed, then add it as a [[model]]")
    if weak and age is not None and age > 28:
        return out("ignore", f"few people use it a month on ({used})", lic_words)
    return out("watch", "ready and licensed, but little evidence yet", used, lic_words, size)


def _survey(entry, out, ready, tier, lic_words, f, stack):
    """A survey's candidate: researched by hand already, so the evidence is the survey's word;
    what's left is the licence and whether bromigOS can run it."""
    size = f"about {f['gib4']:.0f} GiB at 4-bit, fits {f['where']}" if f else ""
    if entry.get("memory_gb"):
        size = f"about {float(entry['memory_gb']):g} GB as the survey sized it"
    use = f"in use: {entry['in_use']}" if entry.get("in_use") else ""
    if tier == "non-commercial":
        return out("ignore" if not entry.get("in_use") else "watch", lic_words, use)
    if not ready:
        return out("watch", f"needs a way to run it: {stack.removeprefix('needs support: ')}", lic_words, size, use)
    if tier in ("clean", "conditional"):
        return out("adopt", "the survey recommends it", stack,
                   lic_words, size, use, "measure its peak VRAM and speed, then add it as a [[model]]")
    return out("watch", lic_words, "the licence decides whether it can be a pick", size, use)


# ------------------------------------------------------------------ importing a survey
def _public(text):
    """The catalog is public: a survey's notes lose any path on someone's computer."""
    return re.sub(r"(~|/home/[^/\s]+|/mnt|/srv|/var/home/[^/\s]+)(/[^\s,;)]*)?", "a local folder", text)


def import_survey(path, survey, today=None):
    """Add a survey's candidates (a candidates.toml: one [[model]] per candidate, with
    capability, licence, tier, built_on, …) to models.toml at `path` as [[pending]] entries of
    kind "survey". Skips what the catalog already has (by id or repository) and what's
    pending or archived already. capability "mesh-parts" becomes mesh with parts = true.
    -> {"added": [ids], "skipped": {reason: [ids]}}."""
    import tomllib
    tomlkit = _tomlkit()
    today = _today(today)
    with open(survey, "rb") as f:
        sv = tomllib.load(f)
    with open(path) as f:
        doc = tomlkit.parse(f.read())
    have_ids = {m.get("id") for m in doc.get("model", [])}
    have_repos = {(m.get("repo") or "").lower() for m in doc.get("model", []) if m.get("repo")}
    for m in doc.get("model", []):                             # a variant's own weights repository counts too
        for v in m.get("variant", []):
            w = str(v.get("weights") or "").split(" ")[0].split(":")[0].lower()
            if re.fullmatch(r"[\w.-]+/[\w.-]+", w):
                have_repos.add(w)
    known = {p.get("id") for p in list(doc.get("pending") or []) + list(doc.get("archived") or [])}
    known_repos = {(p.get("repo") or "").lower() for p in list(doc.get("pending") or []) + list(doc.get("archived") or [])
                   if p.get("repo")}
    pend = doc.get("pending")
    if pend is None:
        pend = tomlkit.aot()
        doc["pending"] = pend
    added, skipped = [], {}
    stamp = str(sv.get("surveyed") or today.isoformat())
    for m in sv.get("model") or []:
        mid = m.get("id") or ""
        repo = (m.get("hf_id") or m.get("repo") or "").strip()
        pid = f"survey:{mid}"
        if mid in have_ids or (repo and repo.lower() in have_repos):
            skipped.setdefault("in the catalog", []).append(mid)
            continue
        if pid in known or (repo and repo.lower() in known_repos):
            skipped.setdefault("already pending or archived", []).append(mid)
            continue
        cap = m.get("capability") or ""
        parts = bool(m.get("parts")) or cap == "mesh-parts"
        if cap == "mesh-parts":
            cap = "mesh"
        comfy = str(m.get("comfyui") or "")
        stack = ("ready (ComfyUI: " + comfy + ")") if comfy.lower().startswith("yes") else \
            f"needs support: {comfy or 'no runtime named'}"
        t = tomlkit.table()
        t["id"] = pid
        t["kind"] = "survey"
        t["capability"] = cap
        if m.get("also_capabilities"):
            t["also_capabilities"] = list(m["also_capabilities"])
        t["title"] = f"{m.get('name', mid)}: the {stamp[:7]} survey"
        why = _public(" ".join(str(m.get("quality_notes") or "").split()))
        if m.get("replaces"):
            why = f"would replace {m['replaces']}. " + why
        t["why"] = (why[:400] + "…") if len(why) > 400 else (why or "listed by the survey")
        if repo:
            t["repo"] = repo
        t["evidence"] = [x for x in [m.get("url"), m.get("licence_url"), *(m.get("cite") or [])] if x][:6]
        t["stack"] = stack
        for k in ("licence", "licence_name", "tier", "tier_reason"):
            if m.get(k):
                t[k] = str(m[k])
        if m.get("built_on"):
            t["built_on"] = [{k: str(v) for k, v in b.items()} for b in m["built_on"]]
        if m.get("memory_gb"):
            t["memory_gb"] = float(m["memory_gb"])
        if parts:
            t["parts"] = True
        if m.get("in_use"):
            t["in_use"] = _public(str(m["in_use"]))
        t["found"] = today.isoformat()
        t["state"] = "pending review"
        pend.append(t)
        added.append(pid)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(tomlkit.dumps(doc))
    os.replace(tmp, path)
    return {"added": added, "skipped": skipped}


# ------------------------------------------------------------------ the queue
def queue(cat, today=None, every=False):
    """[{id, kind, capability, repo, title, found, age_days, state, action, reason, signals, …}]:
    every entry waiting for a decision (state "pending review"), and those accepted but not yet
    added; with every, dismissed ones too."""
    out = []
    in_catalog = {m.repo.lower() for m in cat.models.values() if m.repo}
    for p in cat.pending:
        st = p.get("state", "pending review")
        if st in ("dismissed", "noted") and not every:
            continue
        r = recommend(cat, p, today)
        row = {k: p.get(k) for k in ("id", "kind", "capability", "repo", "title", "why", "stack", "licence", "model",
                                     "found", "accepted", "dismissed") if p.get(k) is not None}
        row.update(state=st, age_days=age_days(p, today), action=r["action"], reason=r["reason"],
                   signals=r["signals"], evidence=list(p.get("evidence") or []),
                   added=(p.get("repo") or "").lower() in in_catalog)
        out.append(row)
    order = {"accepted": 1, "pending review": 0}
    out.sort(key=lambda r: (order.get(r["state"], 2), ACTIONS.index(r["action"]), r.get("capability") or "",
                            -(r["signals"].get("likes") or 0)))
    return out


def counts(rows):
    c = {a: 0 for a in ACTIONS}
    c["accepted"] = 0
    for r in rows:
        if r["state"] == "accepted":
            c["accepted"] += 1
        elif r["state"] == "pending review":
            c[r["action"]] += 1
    c["to_review"] = c["adopt"] + c["watch"] + c["ignore"]
    return c


# ------------------------------------------------------------------ editing models.toml (tomlkit)
def _tomlkit():
    try:
        import tomlkit
    except ImportError as e:
        raise C.CatalogError("editing the catalog needs tomlkit (sudo pacman -S python-tomlkit), which keeps "
                             "the file's comments and layout") from e
    return tomlkit


def archive(doc, cat, today=None):
    """Move what waited more than ARCHIVE_AFTER_DAYS without a decision, and what has since been
    added to the catalog as a [[model]], from [[pending]] to [[archived]] with the reason.
    doc: a tomlkit document of models.toml (changed in place). -> [ids moved]."""
    tomlkit = _tomlkit()
    today = _today(today)
    pend = doc.get("pending")
    if not pend:
        return []
    in_catalog = {(m.get("repo") or "").lower(): m.get("id") for m in doc.get("model", []) if m.get("repo")}
    keep, moved = tomlkit.aot(), []
    arch = doc.get("archived")
    if arch is None:
        arch = tomlkit.aot()
    for p in pend:
        st = p.get("state", "pending review")
        repo = (p.get("repo") or "").lower()
        reason = None
        if st in ("pending review", "accepted") and repo and repo in in_catalog and p.get("kind") != "licence changed":
            reason = f"added to the catalog as {in_catalog[repo]}"
        elif st == "pending review":
            age = age_days(p, today)
            if age is not None and age > ARCHIVE_AFTER_DAYS:
                r = recommend(cat, dict(p), today)
                reason = (f"no decision in {age // 7} weeks; the last recommendation was {r['action']}: {r['reason']}")
        if reason:
            t = tomlkit.table()
            for k, v in p.items():
                t[k] = v
            t["state"] = "archived"
            t["archived"] = today.isoformat()
            t["reason"] = reason
            arch.append(t)
            moved.append(p.get("id"))
        else:
            keep.append(p)
    if moved:
        doc["pending"] = keep
        doc["archived"] = arch
    return moved


def decide(path, ident, action, reason=None, today=None):
    """accept | ignore one [[pending]] entry in models.toml at `path` (by id or repo, any case).
    -> the entry's id. CatalogError when it isn't there."""
    tomlkit = _tomlkit()
    today = _today(today)
    with open(path) as f:
        doc = tomlkit.parse(f.read())
    want = ident.strip().lower()
    hit = None
    for p in doc.get("pending") or []:
        if want in ((p.get("id") or "").lower(), (p.get("repo") or "").lower(), "hf:" + want):
            hit = p
            break
    if hit is None:
        raise C.CatalogError(f"nothing in the review queue is {ident!r} (bromigos lab models review lists them)")
    if action == "accept":
        hit["state"] = "accepted"
        hit["accepted"] = today.isoformat()
        if reason:
            hit["note"] = reason
    elif action == "ignore":
        hit["state"] = "dismissed"
        hit["dismissed"] = reason or f"ignored in review on {today.isoformat()}"
    else:
        raise C.CatalogError(f"review {action}: accept or ignore")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(tomlkit.dumps(doc))
    os.replace(tmp, path)
    return hit.get("id")


# ------------------------------------------------------------------ the rolling issue
def issue_body(cat, report="", today=None, limit=80):
    """The "Lab catalog review" issue's Markdown: the whole queue by recommendation, then this
    week's report folded away."""
    today = _today(today)
    rows = queue(cat, today)
    c = counts(rows)
    lines = [ISSUE_MARK,
             f"The lab model catalog's review queue, as of the weekly refresh on {today.isoformat()} "
             f"(catalog version {cat.version}).", "",
             f"**{c['to_review']} to review:** {c['adopt']} adopt, {c['watch']} watch, {c['ignore']} ignore. "
             f"{c['accepted']} accepted and waiting to be added.", "",
             "The recommendation comes from the catalog's own rules: whether bromigOS's stack runs it, its licence "
             "tier, whether it fits a setup the catalog plans for, whether it's a newer member of a family the "
             "catalog picks, and how many people use it. To decide, in a checkout:", "",
             "```bash",
             "bromigos lab models review                      # the same list, in plain words",
             "bromigos lab models review accept ID            # research it and add it as a [[model]]",
             'bromigos lab models review ignore ID --reason "…"   # never proposed again',
             "```", "",
             "Then commit `homelab/share/lab/models.toml` in a pull request. Entries with no decision after "
             f"{ARCHIVE_AFTER_DAYS // 7} weeks move to `[[archived]]` with the reason "
             "([docs/lab-models.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/lab-models.md"
             "#reviewing-what-the-refresh-finds)). This issue is updated every week; it is never re-filed.", ""]
    for action, head in (("adopt", "Adopt: research it and add it"), ("watch", "Watch: not yet"),
                         ("ignore", "Ignore: dismiss it")):
        rs = [r for r in rows if r["state"] == "pending review" and r["action"] == action]
        if not rs:
            continue
        lines += [f"### {head} ({len(rs)})", "", "| ID | Job | Why | Found |", "|---|---|---|---|"]
        for r in rs[:limit]:
            link = (r.get("evidence") or [""])[0]
            ident = f"[`{r['id']}`]({link})" if link else f"`{r['id']}`"
            lines.append(f"| {ident} | {r.get('capability', '')} | {r['reason'].replace('|', '/')} | "
                         f"{r.get('found', '')} |")
        if len(rs) > limit:
            lines.append(f"| … | | {len(rs) - limit} more: `bromigos lab models review` | |")
        lines.append("")
    acc = [r for r in rows if r["state"] == "accepted"]
    if acc:
        lines += [f"### Accepted, waiting to be added ({len(acc)})", ""]
        lines += [f"- `{r['id']}` ({r.get('capability', '')}), accepted {r.get('accepted', '')}" for r in acc]
        lines.append("")
    if report:
        lines += ["<details><summary>This week's refresh</summary>", "", report.strip(), "", "</details>"]
    body = "\n".join(lines)
    return body[:60000]


def issue_plan(issues, nonempty=True):
    """What to do with the open lab-catalog issues: {"update": number|None, "reopen": bool,
    "create": bool, "close": [numbers], "close_rolling": bool}. issues: `gh issue list --label
    lab-catalog --state all --json number,title,state,url`. The oldest issue titled ISSUE_TITLE
    is the rolling one; every other open lab-catalog issue is closed with a link to it."""
    rolling = sorted((i for i in issues if (i.get("title") or "").strip() == ISSUE_TITLE),
                     key=lambda i: int(i["number"]))
    keep = rolling[0] if rolling else None
    plan = {"update": keep["number"] if keep else None, "url": keep.get("url") if keep else None,
            "reopen": bool(keep and nonempty and str(keep.get("state", "")).upper() == "CLOSED"),
            "create": keep is None and nonempty, "close": [], "close_rolling": False}
    for i in sorted(issues, key=lambda i: int(i["number"])):
        if keep and i["number"] == keep["number"]:
            continue
        if str(i.get("state", "OPEN")).upper() == "OPEN":
            plan["close"].append(i["number"])
    if keep and not nonempty and str(keep.get("state", "")).upper() == "OPEN":
        plan["close_rolling"] = True
    return plan


def issue_sync(cat, repo, report="", issues=None, dry_run=False, today=None, run=None):
    """Apply issue_plan with gh: update (or create, or reopen) the rolling issue with
    issue_body, close the old weekly issues with a link to it. dry_run: print the gh commands.
    -> {"plan", "url", "commands"}."""
    rows = queue(cat, today)
    c = counts(rows)
    nonempty = bool(c["to_review"] or c["accepted"])
    gh = shutil.which("gh") or "gh"
    run = run or (lambda args: subprocess.run([gh] + args, capture_output=True, text=True, timeout=120, check=True)
                  .stdout)
    cmds = []

    def do(args):
        cmds.append(["gh"] + args)
        if dry_run:
            print(" ".join(_q(a) for a in ["gh"] + args))
            return ""
        return run(args)

    if issues is None:
        issues = json.loads(run(["issue", "list", "-R", repo, "--label", "lab-catalog", "--state", "all", "--json",
                                 "number,title,state,url", "--limit", "200"]) or "[]")
    plan = issue_plan(issues, nonempty)
    body = issue_body(cat, report, today)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        body_file = f.name
    try:
        url = plan["url"]
        labels = "lab-catalog,pending-review" if c["to_review"] else "lab-catalog"
        if plan["create"]:
            url = (do(["issue", "create", "-R", repo, "--title", ISSUE_TITLE, "--body-file", body_file,
                       "--label", labels]) or "").strip() or "(the new issue)"
        elif plan["update"] is not None:
            if plan["reopen"]:
                do(["issue", "reopen", str(plan["update"]), "-R", repo])
            do(["issue", "edit", str(plan["update"]), "-R", repo, "--body-file", body_file,
                "--add-label", "lab-catalog"] + (["--add-label", "pending-review"] if c["to_review"] else
                                                 ["--remove-label", "pending-review"]))
            if plan["close_rolling"]:
                do(["issue", "close", str(plan["update"]), "-R", repo, "--comment",
                    "Nothing is waiting for review. The weekly refresh reopens this issue when it finds something."])
        for n in plan["close"]:
            target = url or "the rolling review issue"
            do(["issue", "close", str(n), "-R", repo, "--comment",
                f"The weekly refresh now keeps one issue up to date instead of filing a new one each week: "
                f"{target}. Everything this issue listed that still waits for a decision is there, with a "
                "recommendation (adopt, watch or ignore)."])
    finally:
        os.unlink(body_file)
    return {"plan": plan, "url": url, "commands": cmds, "counts": c}


def _q(a):
    return a if re.fullmatch(r"[\w@%+=:,./-]+", a) else "'" + a.replace("'", "'\\''") + "'"


# ------------------------------------------------------------------ the command
def _print_queue(cat, rows):
    c = counts(rows)
    print(f"catalog: {cat.path} · version {cat.version} · refreshed {cat.refreshed}")
    if not c["to_review"] and not c["accepted"]:
        print("Nothing is waiting for review.")
        return
    print(f"The weekly refresh found {c['to_review']} model{'s' if c['to_review'] != 1 else ''} nobody has decided "
          f"on yet: {c['adopt']} to adopt, {c['watch']} to watch, {c['ignore']} to ignore.")
    words = {"adopt": "Adopt (research it, then add it to the catalog)",
             "watch": "Watch (not yet: the reason says what's missing)",
             "ignore": "Ignore (dismiss it: it won't be proposed again)"}
    for action in ACTIONS:
        rs = [r for r in rows if r["state"] == "pending review" and r["action"] == action]
        if not rs:
            continue
        print(f"\n{words[action]}: {len(rs)}")
        for r in rs:
            print(f"  {r['id']}  [{r.get('capability', '')}, {r.get('kind', '')}, found {r.get('found', '?')}]")
            print(f"      {r['reason']}")
    acc = [r for r in rows if r["state"] == "accepted"]
    if acc:
        print(f"\nAccepted, waiting to be added as a [[model]]: {len(acc)}")
        for r in acc:
            print(f"  {r['id']}  [{r.get('capability', '')}] accepted {r.get('accepted', '?')}"
                  + (" · now in the catalog" if r.get("added") else ""))
    print("\nTo decide: bromigos lab models review accept ID, or ignore ID --reason \"…\" (in a bromigOS checkout; "
          "then commit homelab/share/lab/models.toml). docs/lab-models.md explains the rules.")


def main(argv):
    argv = list(argv)
    js = "--json" in argv
    pos = C._positional([a for a in argv if a not in ("--json", "--all", "--dry-run")])
    try:
        if pos and pos[0] in ("accept", "ignore"):
            if len(pos) < 2:
                print(f"bromigos lab models review {pos[0]} ID (bromigos lab models review lists them)",
                      file=sys.stderr)
                return 2
            path = C._arg(argv, "--catalog") or DEFAULT_CATALOG
            if not os.path.isfile(path) or not os.access(path, os.W_OK):
                print(f"bromigos lab models review {pos[0]} edits the catalog in a bromigOS checkout: "
                      "--catalog homelab/share/lab/models.toml", file=sys.stderr)
                return 2
            ident = decide(path, pos[1], pos[0], C._arg(argv, "--reason"))
            done = "accepted: research it, then add it as a [[model]]" if pos[0] == "accept" else \
                "dismissed: the refresh won't propose it again"
            if js:
                print(json.dumps({"id": ident, "action": pos[0], "catalog": path}))
            else:
                print(f"{ident}: {done}. Commit {os.path.relpath(path)} in a pull request.")
            return 0
        if pos and pos[0] == "import":
            # import SURVEY_CANDIDATES.toml [--catalog PATH]: a survey's candidates, as [[pending]] entries
            if len(pos) < 2:
                print("bromigos lab models review import CANDIDATES.toml", file=sys.stderr)
                return 2
            path = C._arg(argv, "--catalog") or DEFAULT_CATALOG
            r = import_survey(path, pos[1], C._arg(argv, "--today"))
            if js:
                print(json.dumps(r, indent=1))
            else:
                print(f"added {len(r['added'])} survey candidates to the review queue"
                      + "".join(f"; skipped {len(v)} ({k})" for k, v in r["skipped"].items()))
            return 0
        if pos and pos[0] == "issue-sync":
            # CI: issue-sync --catalog PATH --repo OWNER/NAME [--report FILE] [--issues FILE] [--dry-run]
            cat = C.load(C._arg(argv, "--catalog") or DEFAULT_CATALOG)
            rep = ""
            if C._arg(argv, "--report") and os.path.isfile(C._arg(argv, "--report")):
                with open(C._arg(argv, "--report")) as f:
                    rep = f.read()
            issues = None
            if C._arg(argv, "--issues"):
                with open(C._arg(argv, "--issues")) as f:
                    issues = json.load(f)
            r = issue_sync(cat, C._arg(argv, "--repo", "bromigos-org/bromigOS"), rep, issues,
                           dry_run="--dry-run" in argv, today=C._arg(argv, "--today"))
            print(json.dumps({"url": r["url"], "plan": r["plan"], "counts": r["counts"]}), file=sys.stderr
                  if "--dry-run" in argv else sys.stdout)
            return 0
        if pos and pos[0] == "issue-body":
            cat = C.load(C._arg(argv, "--catalog") or DEFAULT_CATALOG)
            print(issue_body(cat, today=C._arg(argv, "--today")))
            return 0
        if pos:
            print("bromigos lab models review [--json] | accept ID | ignore ID [--reason TEXT]", file=sys.stderr)
            return 2
        cat = C.load(C._arg(argv, "--catalog"))
        rows = queue(cat, C._arg(argv, "--today"), every="--all" in argv)
    except (C.CatalogError, OSError, ValueError) as e:
        print(f"bromigos lab models review: {e}", file=sys.stderr)
        return 2
    if js:
        print(json.dumps({"catalog": {"path": cat.path, "version": cat.version, "refreshed": cat.refreshed},
                          "counts": counts(rows), "entries": rows}, indent=1, default=str))
        return 0
    _print_queue(cat, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
