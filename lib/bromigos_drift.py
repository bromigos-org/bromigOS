"""DRIFTGLASS's shapes for Python terminal apps, drawn the same as Field Kit's screens
(docs/fieldkit.md, "Shapes shared with the installer"). The shapes come from their source in
Rust, `bromigos fieldkit shapes --json` (bromigos-core), asked once and kept: the palette in
use, the emblem, the orb hologram's frames and the disk map's rules. This module turns them
into rich Text for Textual or rich.

  import bromigos_drift as D
  D.orb_text(i)                  # the orb, frame i (one every D.frame_seconds()), or the
                                 # plain ring on a 16-colour console and in ASCII
  D.emblem_text()                # the burn-in emblem, or the wordmark
  D.disk_map_text(disk, width)   # a disk from `lsblk -J -b -o NAME,SIZE,FSTYPE,LABEL,
                                 # PARTTYPENAME,…` as one bar of its partitions

Without bromigos (or when it fails) every renderer still returns Text: empty for the orb,
the plain wordmark for the emblem, the disk map from the same rules kept here.
"""
import functools
import json
import os
import subprocess

try:
    from rich.text import Text
except ImportError:                     # rich comes with Textual; without it, plain strings
    Text = None

BROMIGOS = os.environ.get("BROMIGOS_BIN", "bromigos")
ORB = "22x11"
FRAMES = 24


def shapes(orb=ORB, frames=FRAMES):
    """`bromigos fieldkit shapes --json`'s document (asked once for each size), or {}."""
    return _ask(orb, int(frames))


def clear():
    """Forget the shapes (a theme change): the next renderer asks again."""
    _ask.cache_clear()


@functools.lru_cache(maxsize=8)
def _ask(orb, frames):
    try:
        r = subprocess.run([BROMIGOS, "fieldkit", "shapes", "--json", "--orb", orb, "--frames", str(frames)],
                           capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout) if r.returncode == 0 else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _text(s="", style=None):
    if Text is None:
        return s
    return Text(s, style=style or "")


def _palette(doc):
    return doc.get("palette") or {}


def colour(role, doc=None):
    """A role's colour for this terminal: the theme's hex in 24-bit colour, the console's
    name on its 16 colours, none without colour."""
    pal = _palette(doc if doc is not None else shapes())
    mode = pal.get("mode", "truecolor")
    if mode == "mono":
        return ""
    if mode == "ansi16":
        return pal.get("ansi16", {}).get(role, "")
    return pal.get("colors", {}).get(role, "")


def braille(doc=None):
    """Braille shows here (24-bit colour terminals' fonts; not the console's, not ASCII)."""
    return bool(_palette(doc if doc is not None else shapes()).get("braille"))


def frame_seconds(doc=None):
    return ((doc if doc is not None else shapes()).get("orb") or {}).get("seconds_per_frame", 0.12)


def orb_text(i=0, orb=ORB, frames=FRAMES):
    """The orb's frame i (it loops), its glowing cells white and bold, the rest the primary
    colour. Under reduced motion, keep i at 0."""
    doc = shapes(orb, frames)
    o = doc.get("orb") or {}
    if not braille(doc):
        o = o.get("plain") or {}
    fr = o.get("frames") or []
    if not fr:
        return _text()
    f = fr[i % len(fr)]
    if Text is None:
        return "\n".join(f["rows"])
    out = Text()
    base, hot = colour("primary", doc), f"bold {colour('white', doc)}".strip()
    for n, (row, glow) in enumerate(zip(f["rows"], f["hot"])):
        if n:
            out.append("\n")
        for ch, g in zip(row, glow):
            out.append(ch, style=hot if g == "*" else base)
    return out


def emblem_text():
    """The burn-in emblem in braille where it shows, else the wordmark (ASCII's in ASCII)."""
    doc = shapes()
    pal = _palette(doc)
    if braille(doc):
        rows = doc.get("emblem") or []
    elif pal.get("ascii"):
        rows = doc.get("wordmark_ascii") or []
    else:
        rows = doc.get("wordmark") or []
    return _text("\n".join(rows) or "B R O M I G O S", colour("primary", doc))


# the disk map's rules when bromigos can't be asked (bromigos-tui's diskmap.rs has the source)
RULES = {
    "kinds": [
        {"kind": "efi", "role": "muted", "label": "EFI", "fstypes": [], "parttype_words": ["EFI System"]},
        {"kind": "bromigos", "role": "primary", "label": "bromigOS", "fstypes": ["crypto_LUKS"], "parttype_words": []},
        {"kind": "windows", "role": "accent", "label": "Windows", "fstypes": ["ntfs", "BitLocker"],
         "parttype_words": ["Microsoft", "Windows"]},
        {"kind": "swap", "role": "faint", "label": "swap", "fstypes": ["swap"], "parttype_words": ["swap"]},
        {"kind": "linux", "role": "soft", "label": "", "fstypes": ["ext4", "ext3", "ext2", "xfs", "btrfs", "f2fs",
                                                                  "bcachefs"], "parttype_words": ["Linux"]},
        {"kind": "other", "role": "dim", "label": "", "fstypes": [], "parttype_words": []},
    ],
    "free": {"role": "faint", "label": "free", "fill": " "},
    "fill": " ",
    "background": True,
    "console_fill": {"part": "█", "free": "░"},
    "ascii_fill": {"efi": ":", "bromigos": "#", "windows": "=", "swap": "~", "linux": "+", "other": "%", "free": "."},
}


def _rules(doc):
    return doc.get("disk_map") or RULES


def kind_of(fstype, parttype, rules=RULES):
    """A partition's kind: the first whose filesystems or partition-type words match."""
    pt = (parttype or "").lower()
    for k in rules["kinds"]:
        if fstype in k["fstypes"] or any(w.lower() in pt for w in k["parttype_words"]):
            return k
    return rules["kinds"][-1]


def segments(disk, rules=RULES):
    """[(kind, label, bytes)]: the partitions in order, then the space none of them uses."""
    parts = disk.get("parts") or disk.get("children") or []
    out = []
    for p in parts:
        size = int(p.get("size") or 0)
        if size <= 0:
            continue
        k = kind_of(p.get("fstype") or "", p.get("parttypename") or "", rules)
        out.append((k["kind"], k["label"] or p.get("fstype") or p.get("label") or "", size))
    used = sum(s for _, _, s in out)
    total = int(disk.get("size") or 0)
    if total > used:
        out.append(("free", rules["free"]["label"], total - used))
    return out


def cells(segs, width):
    """Each segment's cells: its share floored, a partition at least one, free space maybe
    none; over the width off the biggest, left over to the largest remainders."""
    total = sum(s for _, _, s in segs)
    if not total or width <= 0:
        return [0] * len(segs)
    exact = [s * width / total for _, _, s in segs]
    mins = [0 if k == "free" else 1 for k, _, _ in segs]
    n = [max(int(e), m) for e, m in zip(exact, mins)]
    while sum(n) > width:
        spare = [i for i in range(len(n)) if n[i] > mins[i]] or [i for i in range(len(n)) if n[i] > 0]
        if not spare:
            break
        n[max(spare, key=lambda i: (n[i], -i))] -= 1
    order = sorted(range(len(n)), key=lambda i: -(exact[i] - n[i]))
    k = 0
    while sum(n) < width:
        n[order[k % len(order)]] += 1
        k += 1
    return n


def disk_map_text(disk, width):
    """A disk as one bar `width` cells wide: each partition in its kind's colour with its
    label on it where there's room, the free space faint; ASCII tells kinds apart by fill."""
    doc = shapes()
    rules = _rules(doc)
    pal = _palette(doc)
    ascii_ = pal.get("ascii") or pal.get("mode") == "mono"
    roles = {k["kind"]: k["role"] for k in rules["kinds"]}
    segs = segments(disk, rules)
    out = _text()
    plain = []
    for (kind, label, _), w in zip(segs, cells(segs, width)):
        if not w:
            continue
        free = kind == "free"
        # background-coloured cells (one thickness in every font), but the Linux console's own
        # blocks there (its font fills the cell; it has only 8 backgrounds)
        console = pal.get("mode") == "ansi16" and "console_fill" in rules
        fill = (rules["ascii_fill"].get(kind, "%") if ascii_ else
                rules["console_fill"]["free" if free else "part"] if console else
                (rules["free"]["fill"] if free else rules["fill"]))
        if label and len(label) + 2 <= w:
            head, rest = f" {label} ", fill * (w - len(label) - 2)
        else:
            head, rest = "", fill * w
        if Text is None or ascii_:
            plain.append(head + rest)
            continue
        c = colour(rules["free"]["role"] if free else roles.get(kind, "dim"), doc)
        bg = rules.get("background") and not console
        fill_style = (f"on {c}" if bg else c) if c else None
        if free:
            out.append(head, style=(f"{colour('text', doc)} on {c}" if bg else colour("muted", doc)) if c else None)
            out.append(rest, style=fill_style)
        else:
            out.append(head, style=f"bold {colour('void', doc)} on {c}" if c else "bold")
            out.append(rest, style=fill_style)
    if plain:
        return _text("".join(plain))
    return out
