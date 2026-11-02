"""Which Field Kit ISO `bromigos fieldkit usb` and `make-stick` write (docs/fieldkit.md, "Make
your own stick"). No package carries the ISO: people download it from the Download page,
beside the desktop's. In order:

1. --iso FILE, when it's given;
2. this Field Kit medium itself, when it's running from one (the stick's device);
3. a downloaded Field Kit ISO, bromigos-fieldkit-<version>-x86_64.iso, the newest version in
   your Downloads folder (XDG's, else ~/Downloads), your home folder or the current folder;
4. else, at a terminal, an offer to download it: the address and SHA-256 from
   https://pkgs.bromigos.org/iso/latest.json, into Downloads, checked before it's used.

It runs as you, before sudo, so "your Downloads" is yours; under sudo or pkexec it looks in
the home of whoever ran it.
"""

import hashlib
import json
import os
import pwd
import re
import sys
import urllib.request

from . import system

DOWNLOAD_PAGE = "https://bromigos.org/download"
LATEST = os.environ.get("BROMIGOS_ISO_LATEST", "https://pkgs.bromigos.org/iso/latest.json")
EDITION = "bromigos-fieldkit"
MEDIUM_MARK = "/etc/bromigos-fieldkit/medium"
NAME = re.compile(r"^bromigos-fieldkit-([0-9][0-9A-Za-z._+-]*)-x86_64\.iso$")

MISSING = ("Field Kit isn't on this computer yet.\n"
           f"Download the Field Kit ISO from {DOWNLOAD_PAGE} into your Downloads folder, "
           "then run this again.")


class NoImage(Exception):
    """Why there's nothing to write, in words for the person at the keyboard."""


def home():
    """The home of whoever ran the command (sudo and pkexec keep theirs apart from root's)."""
    for var, look in (("SUDO_USER", pwd.getpwnam), ("PKEXEC_UID", lambda v: pwd.getpwuid(int(v)))):
        v = os.environ.get(var)
        if os.geteuid() == 0 and v:
            try:
                return look(v).pw_dir
            except (KeyError, ValueError):
                pass
    return os.path.expanduser("~")


def downloads_dir(h=None):
    """XDG's download folder (~/.config/user-dirs.dirs), else ~/Downloads."""
    h = h or home()
    try:
        for line in open(os.path.join(h, ".config", "user-dirs.dirs")):
            m = re.match(r'\s*XDG_DOWNLOAD_DIR="(.*)"\s*$', line)
            if m:
                return m.group(1).replace("$HOME", h)
    except OSError:
        pass
    return os.path.join(h, "Downloads")


def places(h=None):
    h = h or home()
    out = []
    for d in (downloads_dir(h), os.path.join(h, "Downloads"), h, os.getcwd()):
        if d and os.path.isdir(d) and os.path.realpath(d) not in [os.path.realpath(x) for x in out]:
            out.append(d)
    return out


def version_key(v):
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"[._+-]", v))


def downloaded(dirs=None):
    """The newest downloaded Field Kit ISO in `dirs`, or None."""
    found = []
    for d in dirs if dirs is not None else places():
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            m = NAME.match(n)
            p = os.path.join(d, n)
            if m and os.path.isfile(p) and os.path.getsize(p) > 0:
                found.append((version_key(m.group(1)), os.path.getmtime(p), p))
    return max(found)[2] if found else None


def running_medium():
    """The device this Field Kit medium was started from, when it's a stick (not an ISO file
    looped). The desktop medium's Field Kit entry doesn't count: that stick is the desktop's."""
    if not (os.path.exists(MEDIUM_MARK) and os.path.isdir("/run/archiso/bootmnt")):
        return None
    src = system.run(["findmnt", "-no", "SOURCE", "/run/archiso/bootmnt"], check=False).stdout.strip()
    return src if src and "/dev/loop" not in src else None


def latest(url=LATEST):
    """The Field Kit entry of the newest release's latest.json, or None when it has none."""
    with urllib.request.urlopen(url, timeout=30) as r:
        index = json.load(r)
    for m in index.get("isos") or []:
        if m.get("edition") == EDITION and m.get("url") and m.get("sha256") and NAME.match(m.get("file", "")):
            return m
    return None


def download(entry, folder, out=sys.stdout):
    """entry's ISO into folder, its SHA-256 checked as it arrives; the file only gets its name
    once it matches."""
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, entry["file"])
    part = dest + ".part"
    h = hashlib.sha256()
    size, done, last = int(entry.get("size") or 0), 0, -1
    try:
        with urllib.request.urlopen(entry["url"], timeout=60) as r, open(part, "wb") as f:
            while chunk := r.read(4 << 20):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                pct = done * 100 // size if size else -1
                if pct != last and out.isatty():
                    print(f"\r  {done / 1e9:.1f} of {size / 1e9:.1f} GB", end="", file=out, flush=True)
                    last = pct
        if out.isatty():
            print(file=out)
        if h.hexdigest() != entry["sha256"]:
            raise NoImage("The download didn't match its checksum, so it wasn't kept. Try again, "
                          f"or download it from {DOWNLOAD_PAGE}.")
        os.replace(part, dest)
    finally:
        if os.path.exists(part):
            os.unlink(part)
    return dest


def offer(ask=input, out=sys.stdout):
    """At a terminal: download the newest Field Kit ISO, if they say yes. None otherwise."""
    if not (sys.stdin.isatty() and out.isatty()):
        return None
    try:
        entry = latest()
    except (OSError, ValueError):
        return None                     # no network, or no answer: the plain words instead
    if not entry:
        return None
    size = f", {int(entry['size']) / 1e9:.1f} GB" if entry.get("size") else ""
    folder = downloads_dir()
    ans = ask(f"Field Kit isn't on this computer yet. Download it now ({entry['file']}{size}) "
              f"into {folder}? [y/N] ")
    if ans.strip().lower() not in ("y", "yes"):
        return None
    print("Downloading Field Kit. It's checked before it's used.", file=out)
    try:
        return download(entry, folder, out)
    except OSError:
        raise NoImage(f"The download stopped. Check the network and try again, or download it from {DOWNLOAD_PAGE}.")


def find(explicit=None, use_running=True, may_download=True):
    """The Field Kit ISO (or stick) to write. Raises NoImage with words to show."""
    if explicit:
        p = os.path.abspath(os.path.expanduser(explicit))
        if not os.path.exists(p):
            raise NoImage(f"There's no file at {explicit}. Check the name, or leave out --iso to use "
                          "the Field Kit ISO in your Downloads folder.")
        return p
    if use_running:
        dev = running_medium()
        if dev:
            return dev
    p = downloaded()
    if p:
        return p
    if may_download:
        p = offer()
        if p:
            return p
    raise NoImage(MISSING)


def with_image(a, argv):
    """The Field Kit ISO, found as the person who ran the command (their Downloads), before
    sudo: argv with --iso naming it, for the root half. None, with the reason printed, when
    there's none."""
    try:
        src = find(a.iso)
    except NoImage as e:
        print(e, file=sys.stderr)
        return None
    a.iso = src
    out, skip = [], False
    for x in argv:
        if skip:
            skip = False
        elif x == "--iso":
            skip = True
        elif not x.startswith("--iso="):
            out.append(x)
    return out + ["--iso", src]
