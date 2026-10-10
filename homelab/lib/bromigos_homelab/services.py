"""The lab's service catalog (share/lab/profiles.toml): load it, check it, and resolve a
selection the way the provisioning picker will (docs/lab-provision.md).

    from bromigos_homelab import services as S
    cat = S.load()
    S.validate(cat)                          # [] or ["pinchflat: depends on 'x', which nothing provides", …]
    r = S.resolve(cat, ["arr"])              # {"services", "added", "conflicts", "storage", "unknown"}
    r["added"]                               # [("jellyfin", "The arr apps needs a media library: Jellyfin is ticked too.")]
    S.preset(cat, "media")                   # {"services": [...], "offered": [...]}
    S.targets(cat, r["services"], "pinchflat", step)   # where a configure step applies

Nothing here provisions anything: provisioning is Phase 3. This is the picker's logic, kept
with the data so the catalog's tests can check every entry against it.
"""
import os
import re
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SHARE = os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos"

GROUPS = ("core", "ai", "games", "media", "home", "advanced", "network")
KINDS = ("compose", "helm", "host", "cluster")
STEPS = ("folder", "first-run", "secret", "sign-in", "library", "setting", "timer")
LOCAL = ("state", "scratch")                    # mounts that stay on the box's own disk
PLACEHOLDER = re.compile(r"(?<!\{)\{([a-z]+)(?::([a-z0-9-]+))?\}(?!\})")
PLACEHOLDERS = ("tz", "media", "downloads", "backups", "url", "secret")

# how the picker names a role in words ("needs a media library")
ROLE_WORDS = {"media-library": "a media library", "llm-server": "an LLM server", "reverse-proxy": "a reverse proxy",
              "youtube-downloader": "a YouTube downloader"}


def paths():
    out = []
    if os.environ.get("BROMIGOS_LAB_PROFILES"):
        out.append(os.environ["BROMIGOS_LAB_PROFILES"])
    out += [os.path.join(SHARE, "homelab", "lab", "profiles.toml"),
            os.path.normpath(os.path.join(HERE, "..", "..", "share", "lab", "profiles.toml"))]
    return out


def load(path=None):
    """The catalog as a dict ({"service": {...}, "preset": {...}, "storage": {...}, "sizing": {...}})."""
    for p in [path] if path else paths():
        if p and os.path.isfile(p):
            with open(p, "rb") as f:
                return tomllib.load(f)
    raise FileNotFoundError("no profiles.toml (the lab's service catalog)")


def providers(cat, need):
    """The services that satisfy a depends entry: the service of that id, or every service
    providing that role, in catalog order."""
    svc = cat.get("service") or {}
    if need in svc:
        return [need]
    return [k for k, v in svc.items() if need in (v.get("provides") or [])]


def _words(cat, need):
    svc = cat.get("service") or {}
    return svc[need]["title"] if need in svc else ROLE_WORDS.get(need, need.replace("-", " "))


def resolve(cat, selected):
    """Tick what a selection depends on, as the picker will: {"services" (in catalog order),
    "added": [(id, why in words)], "conflicts": [(a, b)], "storage": [purposes], "unknown": [ids]}.
    A dependency already met by a ticked service (by id, or by a role it provides) adds nothing;
    otherwise the first provider in the catalog that doesn't conflict is ticked, and the reason
    says so."""
    svc = cat.get("service") or {}
    want = [s for s in dict.fromkeys(selected) if s in svc]
    unknown = [s for s in selected if s not in svc]
    added = []
    i = 0
    while i < len(want):
        for need in svc[want[i]].get("depends") or []:
            have = [p for p in providers(cat, need) if p in want]
            if have:
                continue
            ok = [p for p in providers(cat, need)
                  if not any(p in (svc[w].get("conflicts") or []) or w in (svc[p].get("conflicts") or []) for w in want)]
            if ok:
                want.append(ok[0])
                added.append((ok[0], f"{svc[want[i]]['title']} needs {_words(cat, need)}: {svc[ok[0]]['title']} is ticked too."))
        i += 1
    conflicts = sorted({tuple(sorted((a, b))) for a in want for b in svc[a].get("conflicts") or [] if b in want})
    order = list(svc)
    picked = sorted(want, key=order.index)
    storage = sorted({p for s in picked for p in svc[s].get("storage") or []})
    return {"services": picked, "added": added, "conflicts": conflicts, "storage": storage, "unknown": unknown}


def preset(cat, name):
    p = (cat.get("preset") or {})[name]
    return {"services": list(p.get("services") or []), "offered": list(p.get("offered") or [])}


def targets(cat, picked, service, step):
    """Where a configure step applies: the service itself, or (with on = "<role>") every
    ticked service providing that role."""
    on = step.get("on")
    if not on:
        return [service]
    return [p for p in providers(cat, on) if p in picked]


def placeholders(value):
    """[(name, arg)] of the provisioner's placeholders in a string: {media}, {url:plex}. Pinchflat's
    own {{ … }} templates aren't placeholders."""
    return [(m.group(1), m.group(2)) for m in PLACEHOLDER.finditer(str(value))]


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)


def validate(cat):
    """Problems with the catalog, in words ([] when it's consistent)."""
    out = []
    svc = cat.get("service") or {}
    purposes = set(((cat.get("storage") or {}).get("purpose") or {}))
    roles = {r for v in svc.values() for r in v.get("provides") or []}
    for k, v in svc.items():
        for f in ("title", "summary", "group", "kind", "needs", "ports"):
            if f not in v:
                out.append(f"{k}: no {f}")
        if v.get("group") not in GROUPS:
            out.append(f"{k}: group {v.get('group')!r} isn't one of {GROUPS}")
        if v.get("kind") not in KINDS:
            out.append(f"{k}: kind {v.get('kind')!r} isn't one of {KINDS}")
        for d in v.get("depends") or []:
            if d not in svc and d not in roles:
                out.append(f"{k}: depends on {d!r}, which nothing provides")
        for c in v.get("conflicts") or []:
            if c not in svc:
                out.append(f"{k}: conflicts with {c!r}, which isn't in the catalog")
        img = v.get("image")
        if img and (img.endswith(":latest") or (":" not in img.rsplit("/", 1)[-1] and "@" not in img)):
            out.append(f"{k}: image {img!r} isn't pinned to a version or a digest")
        for p in v.get("storage") or []:
            if p not in purposes:
                out.append(f"{k}: storage {p!r} isn't a purpose in [storage]")
        for path, where in (v.get("mounts") or {}).items():
            base = where.split(":", 1)[0]
            if base not in LOCAL and base not in (v.get("storage") or []):
                out.append(f"{k}: mount {path} uses {where!r}, but its storage doesn't list {base!r}")
        for step in v.get("configure") or []:
            if step.get("do") not in STEPS:
                out.append(f"{k}: configure step {step.get('do')!r} isn't one of {STEPS}")
            if step.get("on") and step["on"] not in roles:
                out.append(f"{k}: configure step on {step['on']!r}, which nothing provides")
            if step.get("do") == "library" and not (step.get("name") and step.get("path")):
                out.append(f"{k}: a library step needs a name and a path")
        if v.get("account") and not any(s.get("do") == "sign-in" for s in v.get("configure") or []):
            out.append(f"{k}: it has an account but no sign-in step")
        for text in _strings({x: v.get(x) for x in ("env", "source", "configure")}):
            for name, arg in placeholders(text):
                if name not in PLACEHOLDERS:
                    out.append(f"{k}: unknown placeholder {{{name}}}")
                elif name == "url" and arg not in svc:
                    out.append(f"{k}: {{url:{arg}}} names no service")
                elif name in ("media", "downloads", "backups") and name not in purposes:
                    out.append(f"{k}: {{{name}}} isn't a storage purpose")
    for k, p in (cat.get("preset") or {}).items():
        for s in (p.get("services") or []) + (p.get("offered") or []):
            if s not in svc:
                out.append(f"preset {k}: {s!r} isn't in the catalog")
        for s in p.get("offered") or []:
            if s in (p.get("services") or []):
                out.append(f"preset {k}: {s!r} is both ticked and offered")
    st = cat.get("storage") or {}
    for k, b in (st.get("brand") or {}).items():
        for f in ("title", "creates_shares", "squash", "fix"):
            if f not in b:
                out.append(f"storage brand {k}: no {f}")
        if b.get("creates_shares") and not b.get("create"):
            out.append(f"storage brand {k}: creates shares, but names no API calls to do it with")
        if not b.get("creates_shares") and k not in ("generic", "linux") and not b.get("steps"):
            out.append(f"storage brand {k}: uses an existing share, but gives no steps to make one")
    for k, p in (st.get("purpose") or {}).items():
        if not p.get("folders"):
            out.append(f"storage purpose {k}: no folders")
    return out
