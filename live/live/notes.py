"""FIELD NOTES (~/.local/share/bromigos/notes.md) for the holo deck's notes
panel: entries per heading (or per dated quick note / paragraph when the file
has no headings), case-insensitive search, and links to what an entry
obviously mentions (a lab service, a cluster node, the switchboard)."""
import os
import re


NOTES = os.environ.get("BROMIGOS_NOTES") or os.path.expanduser("~/.local/share/bromigos/notes.md")
DATED = re.compile(r"^\s*[-*]\s*(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)\s+(.*)$")
HEAD = re.compile(r"^(#{1,4})\s+(.*)$")


def parse(text):
    lines = text.splitlines()
    entries = []
    if any(HEAD.match(l) for l in lines):
        cur = None
        for l in lines:
            m = HEAD.match(l)
            if m:
                cur = {"title": m.group(2).strip(), "when": "", "body": [], "level": len(m.group(1))}
                entries.append(cur)
            elif cur is None:
                if l.strip():
                    cur = {"title": "(before the first heading)", "when": "", "body": [l], "level": 1}
                    entries.append(cur)
            else:
                cur["body"].append(l)
    else:
        para = []

        def flush():
            if para:
                t = " ".join(x.strip() for x in para)
                entries.append({"title": t[:60], "when": "", "body": para[:], "level": 1})
                para.clear()
        for l in lines:
            m = DATED.match(l)
            if m:
                flush()
                entries.append({"title": m.group(2).strip()[:60], "when": m.group(1), "body": [m.group(2)],
                                "level": 1})
            elif not l.strip():
                flush()
            else:
                para.append(l)
        flush()
    for e in entries:
        while e["body"] and not e["body"][-1].strip():
            e["body"].pop()
        w = DATED.match(e["body"][0]) if e["body"] else None
        if not e["when"] and w:
            e["when"] = w.group(1)
    return entries


def load():
    try:
        with open(NOTES, encoding="utf-8", errors="replace") as f:
            return parse(f.read()), os.path.getmtime(NOTES)
    except OSError:
        return [], 0.0


def search(entries, q):
    q = q.strip().lower()
    if not q:
        return list(range(len(entries)))
    words = q.split()
    out = []
    for i, e in enumerate(entries):
        hay = (e["title"] + " " + " ".join(e["body"])).lower()
        if all(w in hay for w in words):
            out.append(i)
    return out


def links(entry, services, nodes, radial):
    """(label, url) for what the entry obviously mentions."""
    hay = (entry["title"] + " " + " ".join(entry["body"])).lower()
    out, seen = [], set()

    def add(label, url):
        if url not in seen:
            seen.add(url)
            out.append((label, url))
    for it in radial:
        n = (it.get("name") or "").lower()
        if n and it.get("url") and re.search(r"\b" + re.escape(n) + r"\b", hay):
            add(it["name"].upper(), it["url"])
    from .homelab import H
    domain = (H.config.setting("services", "domain", "") if H else "") or ""
    lab = (H.lab_url() if H else "") or ""
    for sid in services:
        if len(sid) >= 4 and re.search(r"\b" + re.escape(sid.lower()) + r"\b", hay):
            if domain:
                add(sid.upper(), f"https://{sid}.{domain}")
    for n in nodes:
        if re.search(r"\b" + re.escape(n.lower()) + r"\b", hay):
            if lab:
                add(n.upper(), lab)
    return out[:6]
