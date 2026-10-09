#!/usr/bin/env python3
"""bromigOS releases: the version, the notes, the files a release changes, the GitHub
Release's text and checksums, and the guards. The release workflows
(.github/workflows/release-prepare.yml, release.yml, release-promote.yml) run it;
docs/release.md is the process in plain words.

  release.py plan        --bump patch|minor|major|X.Y.Z --kind rc|stable [--vector DIR]
  release.py notes       --plan PLAN [--vector DIR] --out NOTES [--fallback]
  release.py write-vector --plan PLAN --notes NOTES --vector DIR
  release.py write       --plan PLAN --notes NOTES [--vector-commit SHA] [--vector-branch B]
  release.py pr-body     --plan PLAN --notes NOTES [--vector-pr URL] [--dry-run] [--for vector]
  release.py body        --tag TAG [--ref REF] [--promoted-from TAG] [--for vector]
  release.py check       FILE... [--repos DIR...] [--since TAG]
  release.py ci-green    --repo OWNER/NAME [--wait-sha SHA] [--timeout MIN]
  release.py checksums   DB [--expect-version X.Y.Z --expect NAME...]
  release.py history     [--vector DIR]

The network: the model (LITELLM_BASE_URL and LITELLM_API_KEY; the key is only ever a
request header, and scrubbed from any error printed) and GitHub (gh, with GH_TOKEN).
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CLIFF = os.path.join(HERE, "cliff.toml")
sys.path.insert(0, HERE)
import guard  # noqa: E402

REPOS = {"bromigos": "bromigos-org/bromigOS", "vector": "bromigos-org/vector"}
URL = {k: f"https://github.com/{v}" for k, v in REPOS.items()}
MODEL = os.environ.get("RELEASE_MODEL", "qwen3.8-flash-next")
TZ = "America/Los_Angeles"
STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
ANY_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?$")
MARKER = "<!-- releases: tools/release/release.py adds each release below this line, newest first -->"
SECTIONS = [("before_you_update", "Before you update"), ("new", "New"), ("improved", "Improved"),
            ("fixed", "Fixed"), ("known_issues", "Known issues")]
# groups whose commits users never see: their bodies aren't sent to the model
QUIET_GROUPS = {"Docs", "Tests and tools", "Packaging and CI"}


def die(msg, code=1):
    print(f"release: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd, cwd=None, env=None, check=True):
    e = dict(os.environ, **(env or {}))
    r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True)
    if check and r.returncode != 0:
        die(f"{' '.join(cmd[:3])}…: exit {r.returncode}: {r.stderr.strip()[-800:]}")
    return r.stdout


def git(repo, *args, check=True):
    return run(["git", "-C", repo, *args], check=check).strip()


def today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(TZ)).date()
    except Exception:  # no tz database: the UTC date
        return datetime.datetime.now(datetime.timezone.utc).date()


def long_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def load(path):
    with open(path) as f:
        return json.load(f)


def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ------------------------------------------------------------------ versions

def tags(repo):
    return [t for t in git(repo, "tag", "-l", "v*").split() if ANY_TAG.match(t)]


def last_stable(repo, ref="HEAD"):
    """The newest vX.Y.Z tag reachable from `ref` (rc tags don't count)."""
    t = git(repo, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "--exclude", "*-rc*", ref,
            check=False)
    return t if STABLE_TAG.match(t or "") else None


def vtuple(tag):
    m = ANY_TAG.match(tag)
    return tuple(int(x) for x in m.groups()[:3]) if m else None


def plan_release(bump, kind, vector):
    if kind not in ("rc", "stable"):
        die("--kind is rc or stable")
    since = last_stable(ROOT)
    base = vtuple(since) if since else (0, 0, 0)
    if re.fullmatch(r"\d+\.\d+\.\d+", bump):
        ver = tuple(int(x) for x in bump.split("."))
    elif bump in ("patch", "minor", "major"):
        a, b, c = base
        ver = {"patch": (a, b, c + 1), "minor": (a, b + 1, 0), "major": (a + 1, 0, 0)}[bump]
    else:
        die(f"--bump: patch, minor, major or X.Y.Z, not {bump!r}")
    if ver <= base:
        die(f"{'.'.join(map(str, ver))} isn't newer than the last stable release {since}")
    version = ".".join(map(str, ver))
    known = set(tags(ROOT)) | (set(tags(vector)) if vector else set())
    rc = None
    if kind == "rc":
        rcs = [int(m.group(4)) for t in known if (m := ANY_TAG.match(t)) and m.group(4)
               and vtuple(t) == ver]
        rc = max(rcs, default=0) + 1
        tag = f"v{version}-rc{rc}"
    else:
        tag = f"v{version}"
    if f"v{version}" in known:
        die(f"v{version} is already released")
    if tag in known:
        die(f"{tag} exists already")
    p = {"version": version, "tag": tag, "kind": kind, "rc": rc, "since": since,
         "date": today().isoformat(), "model": MODEL,
         "bromigos": {"repo": REPOS["bromigos"], "since": since, "base": git(ROOT, "rev-parse", "HEAD")}}
    if vector:
        vs = last_stable(vector)
        if vs != since:
            print(f"release: note: VECTOR's last stable tag is {vs}, bromigOS's {since}", file=sys.stderr)
        p["vector"] = {"repo": REPOS["vector"], "since": vs, "base": git(vector, "rev-parse", "HEAD")}
    return p


# ------------------------------------------------------------------ what changed

def cliff(repo, *args, url):
    return run(["git-cliff", "--config", CLIFF, *args], cwd=repo, env={"CLIFF_REPO_URL": url})


def strip_group(g):
    return re.sub(r"<!--.*?-->", "", g or "").strip()


TRAILER = re.compile(r"^[A-Za-z][A-Za-z-]+: .+$")


def commits(repo, since, url, rs):
    """Every commit in since..HEAD as git-cliff groups it: {id, group, subject, body}, the
    text redacted by the privacy rules (the model never sees what the notes can't say)."""
    rng = f"{since}..HEAD" if since else "HEAD"
    ctx = json.loads(cliff(repo, "--context", rng, url=url) or "[]")
    out = []
    for rel in ctx:
        for c in rel.get("commits", []):
            msg = (c.get("raw_message") or c.get("message") or "").strip()
            subject, _, body = msg.partition("\n")
            lines = body.strip().splitlines()
            while lines and (TRAILER.match(lines[-1]) or not lines[-1].strip()):
                lines.pop()
            group = strip_group(c.get("group"))
            body = "\n".join(lines).strip()
            body = "" if group in QUIET_GROUPS else body[:1500]
            out.append({"id": c["id"][:7], "group": group,
                        "subject": private(subject, rs), "body": private(body, rs)})
    return out


def private(text, rs):
    """Text with whatever a rule matches replaced by <private>."""
    for _, r in rs:
        text = r.sub("<private>", text)
    return text


def changelog(repo, since, tag, url, rs):
    """git-cliff's log of since..HEAD as `tag`, each line the privacy check stops withheld."""
    rng = f"{since}..HEAD" if since else "HEAD"
    return guard.redact(cliff(repo, "--tag", tag, rng, url=url).strip() + "\n", rs).strip()


def facts(repo, since):
    """What an update does by itself: new migrations (each one's leading comment), and the
    package dependency lines that changed."""
    rng = f"{since}..HEAD" if since else "HEAD"
    out = {"migrations": [], "dependency_changes": []}
    for f in git(repo, "diff", "--diff-filter=A", "--name-only", rng, "--", "migrations/", check=False).split():
        try:
            with open(os.path.join(repo, f)) as fh:
                head = [ln[1:].strip() for ln in fh.read().splitlines()[1:12] if ln.startswith("#")]
        except OSError:
            head = []
        out["migrations"].append({"name": os.path.basename(f), "says": " ".join(head)[:600]})
    diff = git(repo, "diff", "--unified=0", rng, "--", "packaging/*/PKGBUILD", check=False)
    for ln in diff.splitlines():
        if ln[:1] in "+-" and not ln.startswith(("+++", "---")) and re.search(r"\b(opt)?depends=", ln):
            out["dependency_changes"].append(ln[:200])
    out["dependency_changes"] = out["dependency_changes"][:40]
    return out


def known_issues(slug):
    """Open issues labelled known-issue (none when gh can't tell)."""
    r = subprocess.run(["gh", "issue", "list", "-R", slug, "--label", "known-issue", "--state", "open",
                        "--json", "number,title,body", "--limit", "30"], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [{"title": i["title"], "body": (i.get("body") or "")[:800]} for i in json.loads(r.stdout or "[]")]


# ------------------------------------------------------------------ the model

ITEMS = {"type": "array", "items": {"type": "string"}}
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["summary"] + [k for k, _ in SECTIONS],
          "properties": {"summary": {"type": "string"}, **{k: ITEMS for k, _ in SECTIONS}}}


def chat(messages):
    """The model's answer (streamed, so a long think shows progress and no proxy times it out)."""
    base, key = os.environ.get("LITELLM_BASE_URL", ""), os.environ.get("LITELLM_API_KEY", "")
    body = {"model": MODEL, "messages": messages, "temperature": 0.3, "stream": True,
            "stream_options": {"include_usage": True},
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "release_notes", "schema": SCHEMA, "strict": True}}}
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    last = None
    for attempt in range(3):
        try:
            content, thought, usage = [], 0, None
            t0 = tick = time.time()
            with urllib.request.urlopen(req, timeout=300) as r:
                for raw in r:
                    line = raw.decode(errors="replace").strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    ev = json.loads(line[5:])
                    usage = ev.get("usage") or usage
                    for ch in ev.get("choices") or []:
                        d = ch.get("delta") or {}
                        thought += len(d.get("reasoning_content") or d.get("reasoning") or "")
                        content.append(d.get("content") or "")
                    if time.time() - tick > 60:
                        tick = time.time()
                        print(f"release: the model is thinking ({time.time() - t0:.0f} s, {thought} characters of "
                              f"reasoning, {sum(map(len, content))} of answer)", file=sys.stderr)
            if usage:
                print(f"release: the model answered in {time.time() - t0:.0f} s: {usage.get('prompt_tokens')} tokens "
                      f"in, {usage.get('completion_tokens')} out", file=sys.stderr)
            return "".join(content)
        except urllib.error.HTTPError as e:
            text = e.read()[:400].decode(errors="replace")
            last = f"HTTP {e.code}: {text}"
            if e.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last = str(e)
        print(f"release: the model's request failed ({(last or '').replace(key, '***') if key else last}); "
              "trying again", file=sys.stderr)
        time.sleep(10 * (attempt + 1))
    die(f"the model ({MODEL}) didn't answer: {(last or '').replace(key, '***') if key else last}")


def clean(notes):
    out = {"summary": " ".join(str(notes.get("summary", "")).split())}
    for k, _ in SECTIONS:
        seen, items = set(), []
        for it in notes.get(k) or []:
            it = re.sub(r"^\s*[-*•]\s*", "", " ".join(str(it).split()))
            if it and it.lower() not in seen:
                seen.add(it.lower())
                items.append(it)
        out[k] = items
    return out


def problems(notes, rs):
    bad = []
    for k in ["summary"] + [k for k, _ in SECTIONS]:
        vals = [notes[k]] if k == "summary" else notes[k]
        for i, v in enumerate(vals):
            for _, n, label in guard.scan(k, v, rs):
                bad.append(f"{k}[{i}]: {label}")
    return bad


def draft(product, plan, cs, fx, issues, rs, names):
    with open(os.path.join(HERE, "prompt.md")) as f:
        system = f.read().format(product=product, product_names=names, max_items=18 if product == "bromigOS" else 8)
    release = {"product": product, "version": plan["version"], "tag": plan["tag"],
               "release_candidate": plan["kind"] == "rc", "since": plan["since"]}
    user = json.dumps({"release": release, "facts": fx, "known_issues": issues, "commits": cs}, ensure_ascii=False)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in range(4):
        raw = chat(messages)
        try:
            notes = clean(json.loads(raw))
        except (ValueError, AttributeError):
            messages += [{"role": "assistant", "content": raw[:4000]},
                         {"role": "user", "content": "That wasn't the JSON asked for. Answer with the JSON object only."}]
            continue
        bad = problems(notes, rs)
        if not bad and notes["summary"]:
            return notes
        why = "; ".join(bad) or "the summary is empty"
        print(f"release: {product}: draft {attempt + 1} rejected by the privacy check: {why}", file=sys.stderr)
        messages += [{"role": "assistant", "content": raw[:8000]},
                     {"role": "user", "content": f"These items break the rules ({why}). Write the whole answer "
                      "again without naming any host, address, person, internal project or other distribution."}]
    die(f"{product}: no draft passed the privacy check after 4 tries")


def fallback(cs):
    """Notes without a model (a dry run with no key): each user-facing commit's subject."""
    loud = [c["subject"] for c in cs if c["group"] not in QUIET_GROUPS]
    return {"summary": "Drafted without the model (no LITELLM_API_KEY): the commit subjects, unedited.",
            "before_you_update": [], "new": [], "improved": loud[:25], "fixed": [], "known_issues": []}


def notes_cmd(a):
    plan = load(a.plan)
    vector = a.vector
    repos = [ROOT] + ([vector] if vector else [])
    rs = guard.rules(repos)
    have_model = bool(os.environ.get("LITELLM_API_KEY") and os.environ.get("LITELLM_BASE_URL"))
    if not have_model and not a.fallback:
        die("LITELLM_BASE_URL and LITELLM_API_KEY aren't set (docs/release.md, \"What CI needs\"); "
            "--fallback drafts from the commit subjects (dry runs only)")
    out = {"plan": plan, "drafted_by": MODEL if have_model else "fallback (no model)",
           "private_patterns": guard.have_private_patterns()}
    for key, product, slug, names in (("bromigos", "bromigOS", REPOS["bromigos"], "bromigOS and VECTOR"),
                                      ("vector", "VECTOR", REPOS["vector"], "VECTOR and bromigOS")):
        repo = ROOT if key == "bromigos" else vector
        if not repo:
            continue
        since = plan[key]["since"]
        cs = commits(repo, since, URL[key], rs)
        fx = facts(repo, since)
        issues = known_issues(slug)
        print(f"release: {product}: {len(cs)} commits since {since}, {len(fx['migrations'])} new migrations, "
              f"{len(issues)} known issues", file=sys.stderr)
        t = time.time()
        out[key] = draft(product, plan, cs, fx, issues, rs, names) if have_model else fallback(cs)
        print(f"release: {product}: notes drafted in {time.time() - t:.0f} s", file=sys.stderr)
        out[key + "_changelog"] = changelog(repo, since, plan["tag"], URL[key], rs)
        out[key + "_commits"] = len(cs)
    save(a.out, out)


# ------------------------------------------------------------------ the files

def channel_line(plan):
    if plan["kind"] == "rc":
        return (f"Release candidate {plan['tag'][1:]}, on the rc channel. When it's ready, this same build "
                "becomes the stable release.")
    return "On the stable channel."


def bullets(items):
    return "\n".join(f"- {i}" for i in items)


def notes_section(plan, notes):
    """The release's section of manual/src/whats-new.md."""
    nb, nv = notes["bromigos"], notes.get("vector")
    out = [f"## {plan['version']}", f"<!-- release: {plan['tag'][1:]} -->", "",
           f"*{long_date(plan['date'])} · {channel_line(plan)}*", "", nb["summary"], ""]

    def merged(k):
        items = list(nb[k])
        if nv:
            items += [i if "VECTOR" in i else f"VECTOR: {i}" for i in nv[k]]
        return items

    before = merged("before_you_update")
    out += ["### Before you update", "",
            bullets(before) if before else "Nothing to do: `bromigos update` takes care of everything.", ""]
    for k, title in SECTIONS[1:4]:
        if nb[k]:
            out += [f"### {title}", "", bullets(nb[k]), ""]
    if nv and any(nv[k] for k, _ in SECTIONS[1:4]):
        out += ["### VECTOR", "", nv["summary"], ""]
        for k, title in SECTIONS[1:4]:
            if nv[k]:
                out += [f"#### {title}", "", bullets(nv[k]), ""]
    issues = merged("known_issues")
    out += ["### Known issues", "", bullets(issues) if issues else "None known.", ""]
    return "\n".join(out)


def changelog_section(plan, notes):
    """The release's section of CHANGELOG.md."""
    out = [f"## [{plan['version']}] - {plan['date']}", f"<!-- release: {plan['tag'][1:]} -->", ""]
    if plan["kind"] == "rc":
        out += [f"Release candidate {plan['tag']}.", ""]
    out += [f"Since {plan['since'] or 'the beginning'}. In plain words: the manual's What's new "
            "(manual/src/whats-new.md).", "", notes["bromigos_changelog"] or "No changes.", ""]
    if notes.get("vector_changelog"):
        vc = re.sub(r"(?m)^### ", "#### ", notes["vector_changelog"])
        out += ["### VECTOR (bromigos-vector)", "", vc, ""]
    return "\n".join(out)


def upsert(text, version, section):
    """`text` with the section for `version` replaced by `section`, or inserted newest first."""
    head = re.compile(rf"^## \[?{re.escape(version)}\]?(?=[ \n])", re.M)
    m = head.search(text)
    if m:
        nxt = re.compile(r"^## ", re.M).search(text, m.end())
        end = nxt.start() if nxt else len(text)
        return text[:m.start()] + section.rstrip("\n") + "\n\n" + text[end:].lstrip("\n")
    i = text.find(MARKER)
    if i < 0:
        die(f"no release marker ({MARKER}) to insert after")
    i += len(MARKER)
    return text[:i] + "\n\n" + section.rstrip("\n") + "\n" + ("\n" + text[i:].lstrip("\n") if text[i:].strip() else "")


def edit(path, fn):
    with open(path) as f:
        text = f.read()
    new = fn(text)
    with open(path, "w") as f:
        f.write(new)
    return new != text


def bump_cargo(root, version):
    """core/Cargo.toml's workspace version, and Cargo.lock's entries for the workspace's
    crates (cargo --locked must still agree). The base of every bromigOS package version."""
    def toml(t):
        m = re.search(r"(?ms)^\[workspace\.package\]\n(.*?)(?=^\[|\Z)", t)
        if not m:
            die("core/Cargo.toml has no [workspace.package]")
        block = re.sub(r'(?m)^version = "[^"]*"', f'version = "{version}"', m.group(1), count=1)
        return t[:m.start(1)] + block + t[m.end(1):]
    edit(os.path.join(root, "core/Cargo.toml"), toml)
    names = set()
    for d in os.listdir(os.path.join(root, "core/crates")):
        p = os.path.join(root, "core/crates", d, "Cargo.toml")
        if os.path.isfile(p):
            t = open(p).read()
            n = re.search(r'(?m)^name = "([^"]+)"', t)
            if n and re.search(r"(?m)^version\.workspace = true", t):
                names.add(n.group(1))
    changed = set()

    def lock(t):
        blocks = t.split("\n\n")
        for i, b in enumerate(blocks):
            n = re.search(r'(?m)^name = "([^"]+)"$', b)
            if b.startswith("[[package]]") and n and n.group(1) in names and "\nsource = " not in b:
                blocks[i] = re.sub(r'(?m)^version = "[^"]*"$', f'version = "{version}"', b, count=1)
                changed.add(n.group(1))
        return "\n\n".join(blocks)
    edit(os.path.join(root, "core/Cargo.lock"), lock)
    if changed != names:
        die(f"Cargo.lock: the workspace crates {sorted(names - changed)} weren't found")


def write_cmd(a):
    plan, notes = load(a.plan), load(a.notes)
    edit(os.path.join(ROOT, "manual/src/whats-new.md"), lambda t: upsert(t, plan["version"], notes_section(plan, notes)))
    edit(os.path.join(ROOT, "CHANGELOG.md"), lambda t: upsert(t, plan["version"], changelog_section(plan, notes)))
    bump_cargo(ROOT, plan["version"])
    cur = {k: plan[k] for k in ("version", "tag", "kind", "since", "date")}
    cur["bromigos"] = {"base": plan["bromigos"]["base"]}
    if plan.get("vector"):
        cur["vector"] = {"base": plan["vector"]["base"], "since": plan["vector"]["since"],
                         "commit": a.vector_commit, "branch": a.vector_branch}
    cur["drafted_by"] = notes["drafted_by"]
    save(os.path.join(HERE, "current.json"), cur)


def write_vector_cmd(a):
    plan, notes = load(a.plan), load(a.notes)
    v = a.vector
    with open(os.path.join(v, "VERSION"), "w") as f:
        f.write(plan["version"] + "\n")
    path = os.path.join(v, "CHANGELOG.md")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(vector_changelog_header())
    sec = [f"## [{plan['version']}] - {plan['date']}", f"<!-- release: {plan['tag'][1:]} -->", ""]
    if plan["kind"] == "rc":
        sec += [f"Release candidate {plan['tag']}.", ""]
    sec += [f"Since {plan['vector']['since']}. Released with bromigOS {plan['version']} "
            "(its notes: bromigOS's manual, What's new).", "", notes.get("vector_changelog") or "No changes.", ""]
    edit(path, lambda t: upsert(t, plan["version"], "\n".join(sec)))


def vector_changelog_header():
    return ("# Changelog\n\nEvery change to VECTOR (bromigos-vector), release by release: the technical log, "
            "made from the\ncommit subjects by git-cliff when bromigOS prepares a release (bromigOS "
            "docs/release.md).\nVECTOR is released with bromigOS: the same version, tagged together.\n\n" + MARKER + "\n")


# ------------------------------------------------------------------ texts for GitHub

def section_of(text, version=None):
    """The section of whats-new.md for `version` (the newest when None), without its marker."""
    heads = list(re.finditer(r"^## (\S+)\n<!-- release: ([^ ]+) -->\n", text, re.M))
    for i, m in enumerate(heads):
        if version is None or m.group(1) == version:
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            return m.group(1), m.group(2), text[m.end():end].strip()
    return None


def vector_part(sec):
    m = re.search(r"(?ms)^### VECTOR\n(.*?)(?=^### |\Z)", sec)
    return re.sub(r"(?m)^#### ", "### ", m.group(1).strip()) if m else ""


def body_cmd(a):
    ref = a.ref or a.tag
    m = ANY_TAG.match(a.tag)
    if not m:
        die(f"{a.tag} isn't a release tag")
    version = ".".join(m.groups()[:3])
    text = git(ROOT, "show", f"{ref}:manual/src/whats-new.md")
    found = section_of(text, version)
    if not found:
        die(f"{ref}: whats-new.md has no section for {version}")
    _, rid, sec = found
    rc = "-rc" in a.tag
    channel = "rc" if rc else "stable"
    lines = []
    if a.promoted_from:
        lines += [f"**{a.tag} is {a.promoted_from}, promoted to the stable channel unchanged:** the same "
                  "packages, so the notes are the release candidate's.", ""]
    if getattr(a, "for") == "vector":
        vp = vector_part(sec) or "No user-facing changes in this release."
        lines += [vp, "", "---", "",
                  f"VECTOR {version} is part of [bromigOS {a.tag[1:]}]({URL['bromigos']}/releases/tag/{a.tag}): "
                  "the same version, tagged together, published to the same channel.",
                  f"Technical changelog: [CHANGELOG.md]({URL['vector']}/blob/{a.tag}/CHANGELOG.md)."]
    else:
        lines += [sec, "", "---", "",
                  f"- **Update:** `bromigos update` on the {channel} channel"
                  + (" (`bromigos update --channel rc` to follow it)." if rc else "."),
                  "- **On your computer:** `bromigos whats-new` shows these notes, offline; the manual's "
                  f"[What's new]({URL['bromigos']}/blob/{a.tag}/manual/src/whats-new.md) page has every release.",
                  f"- **Every change:** [CHANGELOG.md]({URL['bromigos']}/blob/{a.tag}/CHANGELOG.md) "
                  f"(VECTOR's: [vector {a.tag}]({URL['vector']}/releases/tag/{a.tag})).",
                  f"- **Packages:** `SHA256SUMS` lists every package of the {channel} channel at this release, "
                  "bromigOS's and VECTOR's; `SHA256SUMS.sig` is its signature by the repository's key "
                  "(`gpg --verify SHA256SUMS.sig SHA256SUMS`, with `packaging/keys/bromigos.asc`).",
                  "- **ISO:** the installer image is built and tested by hand (docs/iso.md); when one is made "
                  "from this release it is attached here with its `.sha256`."]
    print("\n".join(lines).strip())


def pr_body_cmd(a):
    plan, notes = load(a.plan), load(a.notes)
    tag = plan["tag"]
    if getattr(a, "for") == "vector":
        lines = [f"VECTOR's side of bromigOS {tag}: `VERSION` {plan['version']} and its CHANGELOG.md section.", ""]
        if a.dry_run:
            lines += ["**Dry run: don't merge; close it.**", ""]
        lines += ["Merging bromigOS's release PR lands this commit on main and tags it (bromigOS docs/release.md); "
                  "there's nothing to do here by hand.", "", "<details><summary>CHANGELOG section</summary>", "",
                  notes.get("vector_changelog") or "No changes.", "", "</details>"]
        print("\n".join(lines))
        return
    sec = notes_section(plan, notes)
    lines = []
    if a.dry_run:
        lines += [f"> **Dry run.** Nothing is tagged or published from this PR: its branch is `release-dryrun/…`, "
                  "which the release workflow ignores. Close it when you've read it.", ""]
    lines += [f"Release **{tag}** ({'release candidate' if plan['kind'] == 'rc' else 'stable'}), "
              f"{notes['bromigos_commits']} bromigOS commits and {notes.get('vector_commits', 0)} VECTOR commits "
              f"since {plan['since']}. Notes drafted by `{notes['drafted_by']}`; edit them here before merging.", "",
              "**What this PR changes**", "",
              "- `manual/src/whats-new.md`: the user notes (shown by `bromigos whats-new` and in the manual)",
              "- `CHANGELOG.md`: the technical log (git-cliff)",
              f"- `core/Cargo.toml`, `core/Cargo.lock`: version {plan['version']}, the base of every package version",
              "- `tools/release/current.json`: what the release workflow tags", ""]
    if a.vector_pr:
        lines += [f"VECTOR's side: {a.vector_pr} (`VERSION` and its CHANGELOG.md). Don't merge it by hand: "
                  "merging this PR lands it.", ""]
    lines += ["**Merging** (use *Create a merge commit*: the tag goes on this PR's release commit, which must "
              f"stay in main's history): the release workflow checks main's CI, tags `{tag}` here and in "
              f"vector, which publishes the {'rc' if plan['kind'] == 'rc' else 'stable'} channel "
              "(packages.yml), then creates both GitHub Releases with these notes and the packages' checksums.",
              "", "---", "", "### The notes, as users will read them", "", sec]
    if not notes.get("private_patterns"):
        lines += ["", "> The lab's own names weren't checked (PRIVACY_PATTERNS isn't set): read the notes for them."]
    print("\n".join(lines))


# ------------------------------------------------------------------ checks

def check_cmd(a):
    rs = guard.rules(a.repos or [ROOT], a.since)
    bad = []
    for f in a.files:
        with open(f) as fh:
            bad += guard.scan(f, fh.read(), rs)
    if not guard.have_private_patterns():
        print("release: note: the lab's own names aren't checked (PRIVACY_PATTERNS isn't set)", file=sys.stderr)
    if bad:
        print("release: the privacy check stopped these lines:", file=sys.stderr)
        guard.report(bad)
        sys.exit(1)
    print(f"release: privacy check: {len(a.files)} file(s) clean")


def gh_api(path):
    return json.loads(run(["gh", "api", "-H", "Accept: application/vnd.github+json", path]) or "null")


IGNORED_WORKFLOWS = {"release", "release-prepare", "release-promote"}
GREEN = {"success", "neutral", "skipped"}


def ci_green_cmd(a):
    repo, me = a.repo, os.environ.get("GITHUB_RUN_ID")
    if a.wait_sha:
        deadline = time.time() + a.timeout * 60
        while True:
            runs = gh_api(f"repos/{repo}/actions/runs?head_sha={a.wait_sha}&per_page=100")["workflow_runs"]
            runs = [r for r in runs if r["name"] not in IGNORED_WORKFLOWS and str(r["id"]) != me]
            pending = [r["name"] for r in runs if r["status"] != "completed"]
            if not pending:
                break
            if time.time() > deadline:
                die(f"{repo}: still running after {a.timeout} min on {a.wait_sha[:7]}: {', '.join(pending)}")
            print(f"release: waiting for {', '.join(sorted(set(pending)))} on {a.wait_sha[:7]}", file=sys.stderr)
            time.sleep(30)
        red = [f"{r['name']} ({r['conclusion']})" for r in runs if r["conclusion"] not in GREEN | {"cancelled"}]
        if red:
            die(f"{repo}: {a.wait_sha[:7]}'s CI failed: {', '.join(red)}")
    wfs = gh_api(f"repos/{repo}/actions/workflows?per_page=100")["workflows"]
    red, rows = [], []
    for w in wfs:
        if w["state"] != "active" or w["name"] in IGNORED_WORKFLOWS:
            continue
        runs = gh_api(f"repos/{repo}/actions/workflows/{w['id']}/runs?branch=main&event=push"
                      "&status=completed&per_page=20")["workflow_runs"]
        last = next((r for r in runs if r["conclusion"] not in ("cancelled", "stale")), None)
        if last is None:
            continue
        rows.append(f"  {w['name']:<16} {last['conclusion']:<10} {last['head_sha'][:7]}")
        if last["conclusion"] not in GREEN:
            red.append(f"{w['name']} ({last['conclusion']} on {last['head_sha'][:7]}: {last['html_url']})")
    print(f"release: {repo}: main's CI, each workflow's newest finished run:", file=sys.stderr)
    print("\n".join(rows), file=sys.stderr)
    if red:
        die(f"{repo}: main's CI is red: {'; '.join(red)}. Fix main first; no release is cut from a red main.")
    print(f"release: {repo}: main's CI is green")


def checksums_cmd(a):
    pkgs = {}
    with tarfile.open(a.db) as t:
        for m in t.getmembers():
            if m.name.endswith("/desc"):
                fields, cur = {}, None
                for ln in t.extractfile(m).read().decode().splitlines():
                    if ln.startswith("%") and ln.endswith("%"):
                        cur = ln
                    elif ln and cur:
                        fields.setdefault(cur, ln)
                pkgs[fields["%NAME%"]] = (fields["%VERSION%"], fields["%FILENAME%"], fields["%SHA256SUM%"])
    if a.expect_version:
        for n in a.expect or []:
            v = pkgs.get(n, ("",))[0]
            if not v.startswith(a.expect_version + ".r"):
                die(f"{n} {v or '(missing)'} in this channel isn't {a.expect_version}'s yet")
    for n in sorted(pkgs):
        print(f"{pkgs[n][2]}  {pkgs[n][1]}")


# ------------------------------------------------------------------ the past

def split_history(repo, url, rs):
    """{tag: log} for every stable tag, from one git-cliff run over the whole history."""
    text = run(["git-cliff", "--config", CLIFF], cwd=repo, env={"CLIFF_REPO_URL": url, "CLIFF_SPLIT": "1"})
    out = {}
    for part in text.split("@@release ")[1:]:
        tag, _, body = part.partition("\n")
        out[tag.strip()] = guard.redact(body.strip() + "\n", rs).strip()
    return out


def history_cmd(a):
    """CHANGELOG.md's sections for the stable tags made before release CI (once)."""
    rs = guard.rules([ROOT] + ([a.vector] if a.vector else []))

    def sections(repo, url, vec=None):
        logs = split_history(repo, url, rs)
        vlogs = split_history(vec, URL["vector"], rs) if vec else {}
        stable = sorted((t for t in logs if STABLE_TAG.match(t)), key=vtuple)
        secs, prev = [], None
        for t in stable:
            date = git(repo, "log", "-1", "--format=%cs", t)
            sec = [f"## [{t[1:]}] - {date}", f"<!-- release: {t[1:]} -->", "",
                   f"Since {prev}." if prev else "The first release.", "", logs[t] or "No changes.", ""]
            if vlogs.get(t):
                sec += ["### VECTOR (bromigos-vector)", "", re.sub(r"(?m)^### ", "#### ", vlogs[t]), ""]
            secs.insert(0, "\n".join(sec))
            prev = t
        return "\n".join(secs)

    header = ("# Changelog\n\nEvery change to bromigOS and VECTOR, release by release: the technical log, made "
              "from the commit\nsubjects by git-cliff (tools/release/cliff.toml) when a release is prepared "
              "(docs/release.md).\nWhat a release means for the people using it, in plain words, is the manual's "
              "What's new\n(manual/src/whats-new.md).\n\n" + MARKER + "\n\n")
    with open(os.path.join(ROOT, "CHANGELOG.md"), "w") as f:
        f.write(header + sections(ROOT, URL["bromigos"], a.vector))
    if a.vector:
        with open(os.path.join(a.vector, "CHANGELOG.md"), "w") as f:
            f.write(vector_changelog_header() + "\n" + sections(a.vector, URL["vector"]))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("--bump", required=True)
    s.add_argument("--kind", required=True)
    s.add_argument("--vector")
    s.add_argument("--out")
    s = sub.add_parser("notes")
    s.add_argument("--plan", required=True)
    s.add_argument("--vector")
    s.add_argument("--out", required=True)
    s.add_argument("--fallback", action="store_true")
    s = sub.add_parser("write")
    s.add_argument("--plan", required=True)
    s.add_argument("--notes", required=True)
    s.add_argument("--vector-commit")
    s.add_argument("--vector-branch")
    s = sub.add_parser("write-vector")
    s.add_argument("--plan", required=True)
    s.add_argument("--notes", required=True)
    s.add_argument("--vector", required=True)
    s = sub.add_parser("pr-body")
    s.add_argument("--plan", required=True)
    s.add_argument("--notes", required=True)
    s.add_argument("--vector-pr")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--for", default="bromigos", choices=["bromigos", "vector"])
    s = sub.add_parser("body")
    s.add_argument("--tag", required=True)
    s.add_argument("--ref")
    s.add_argument("--promoted-from")
    s.add_argument("--for", default="bromigos", choices=["bromigos", "vector"])
    s = sub.add_parser("check")
    s.add_argument("files", nargs="+")
    s.add_argument("--repos", nargs="*")
    s.add_argument("--since")
    s = sub.add_parser("ci-green")
    s.add_argument("--repo", required=True)
    s.add_argument("--wait-sha")
    s.add_argument("--timeout", type=int, default=60)
    s = sub.add_parser("checksums")
    s.add_argument("db")
    s.add_argument("--expect-version")
    s.add_argument("--expect", nargs="*")
    s = sub.add_parser("history")
    s.add_argument("--vector")
    a = p.parse_args()
    if a.cmd == "plan":
        plan = plan_release(a.bump, a.kind, a.vector)
        if a.out:
            save(a.out, plan)
        print(json.dumps(plan, indent=2))
    else:
        {"notes": notes_cmd, "write": write_cmd, "write-vector": write_vector_cmd, "pr-body": pr_body_cmd,
         "body": body_cmd, "check": check_cmd, "ci-green": ci_green_cmd, "checksums": checksums_cmd,
         "history": history_cmd}[a.cmd](a)


if __name__ == "__main__":
    main()
