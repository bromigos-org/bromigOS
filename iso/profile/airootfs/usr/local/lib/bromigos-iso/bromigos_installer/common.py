"""What the graphical and the text installer share (docs/iso.md, "Installing from it"): the
steps and their words, the choices offered, the checks on what's typed, the summary,
the editions, and the network. Both front ends show exactly these words, so they read
the same; neither keeps a rule of its own."""
import glob
import json
import os
import re
import subprocess
import sys


def _read(path):
    with open(path) as f:
        return f.read()

LIB = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SHARE = os.environ.get("BROMIGOS_ISO_SHARE", "/usr/local/share/bromigos-iso")
OFFLINE_REPO = os.environ.get("BROMIGOS_ISO_REPO_DIR", "/var/lib/bromigos/repo")
EDITION_DIRS = [d for d in os.environ.get("BROMIGOS_EDITION_DIRS", "").split(":") if d] or \
    ["/usr/share/bromigos/fieldkit", "/usr/share/bromigos/editions", os.path.join(SHARE, "editions")]
EDITION_NAMES = {"fieldkit": "server"}     # the Field Kit package's file names the edition by its old name

# ── the steps ───────────────────────────────────────────────────────────────────────────
# (id, title in the step list, heading, the line under it)
STEPS = [
    ("auto", "Automatic", "Installing from an answer file",
     "An answer file on the USB stick has every answer, so bromigOS installs by itself. Cancel "
     "to answer the questions yourself."),
    ("welcome", "Welcome", "Install bromigOS",
     "This puts bromigOS on this computer's disk. It takes about ten minutes, and you can go "
     "back and change anything until you press Install."),
    ("checks", "Checks", "Before you start",
     "A few things about this computer worth knowing first. None of them stops the install."),
    ("edition", "Kind", "What kind of computer is this?",
     "Choose what to install. A server can have the desktop added later."),
    ("keyboard", "Keyboard", "Your keyboard",
     "Choose the layout that matches the keys on your keyboard, then try it in the box."),
    ("disk", "Where", "Where to install",
     "Choose a disk, then whether bromigOS goes beside what's on it or replaces it."),
    ("bitlocker", "BitLocker", "Save Windows' recovery key",
     "Windows on this computer is locked with BitLocker. Installing bromigOS changes how the "
     "computer starts, and Windows may then ask for its BitLocker recovery key once. Without the "
     "key, Windows' files can't be opened."),
    ("user", "You", "About you",
     "Your name and password, for signing in. The computer's name is how other devices on your "
     "network see it."),
    ("encryption", "Encryption", "Lock the disk",
     "Encryption keeps your files private if this computer is lost or stolen."),
    ("ssh", "Remote access", "Remote access and protection",
     "How other computers may reach this one, and how it keeps itself up to date."),
    ("summary", "Summary", "Ready to install",
     "Check your choices. Nothing on the disk changes until you press Install."),
    ("install", "Installing", "Installing bromigOS",
     "You can leave it now: it finishes by itself."),
    ("done", "Done", "bromigOS is installed",
     "Restart to start using it."),
]
STEP = {s[0]: s for s in STEPS}


def steps_for(answers):
    """The steps this install shows: a server has no desktop-only steps but asks about SSH."""
    ed = answers.get("edition_info") or {}
    desktop = ed.get("desktop", True)
    out = []
    for s in STEPS:
        if s[0] == "auto":
            if answers.get("auto"):
                return ["auto", "install", "done"]
            continue
        if s[0] == "edition" and len(editions()) < 2:
            continue
        if s[0] == "checks" and not answers.get("checks"):
            continue
        if s[0] == "bitlocker" and not answers.get("bitlocker"):
            continue
        if s[0] == "encryption" and answers.get("mode") == "reinstall":
            continue                    # a reinstall keeps the disk's encryption as it is
        if s[0] == "ssh" and desktop:
            continue
        out.append(s[0])
    return out


# ── editions ────────────────────────────────────────────────────────────────────────────
DESKTOP_EDITION = {
    "id": "desktop", "title": "bromigOS (desktop)", "desktop": True, "default": True,
    "summary": "The full desktop: apps, games, VECTOR, the live wallpaper and the widgets.",
    "hint": "For a computer you sit at, with a screen. This is the usual choice.",
    "check_packages": ["bromigos", "bromigos-desktop"], "download_size": "3 GB",
}


_EDITIONS = None


def editions():
    global _EDITIONS
    if _EDITIONS is None:
        _EDITIONS = _editions()
    return _EDITIONS


def _editions():
    """The editions the installer offers: the desktop (archinstall.json's packages) and any
    edition file found (bromigOS Server's, from the bromigos-server package or this medium).
    An edition file is JSON: {id, title, summary, hint, desktop: false, meta, packages: [...],
    services: [...]}; its packages replace the desktop's (its meta package alone, once that's
    on the medium), the boot and snapshot packages are always added (answers.py's REQUIRED)."""
    found, seen = [dict(DESKTOP_EDITION)], {"desktop"}
    for d in EDITION_DIRS:
        for path in sorted(glob.glob(os.path.join(d, "edition.json")) + glob.glob(os.path.join(d, "server.json"))
                           + [p for p in glob.glob(os.path.join(d, "*.json")) if os.path.basename(p) not in ("edition.json", "server.json")]):
            try:
                with open(path) as f:
                    e = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(e, dict):
                continue
            # the Field Kit package's form (fieldkit/edition.json): name, default_target,
            # skip_desktop_install, user_commands, ssh: {default}
            e["id"] = EDITION_NAMES.get(e.get("id") or e.get("name"), e.get("id") or e.get("name"))
            if e["id"] == "server":
                e["title"] = "bromigOS Server"
                e.setdefault("summary", "No desktop, for servers and lab machines.")
            if "desktop" not in e:
                e["desktop"] = not (e.get("skip_desktop_install") or e.get("default_target") == "multi-user.target")
            if not e.get("id") or e["id"] in seen:
                continue
            e["source"] = path
            if e.get("meta") and _in_store(e["meta"]):
                e["packages"] = [e["meta"]]
                e["check_packages"] = [e["meta"]]
            seen.add(e["id"])
            found.append(e)
    return found


def edition(eid):
    return next((e for e in editions() if e["id"] == eid), DESKTOP_EDITION)


# ── language, keyboard, time zone ───────────────────────────────────────────────────────
LANGUAGES = [   # (locale, name in its own words, a likely time zone)
    ("en_US", "English (United States)", "America/New_York"),
    ("en_GB", "English (United Kingdom)", "Europe/London"),
    ("en_CA", "English (Canada)", "America/Toronto"),
    ("en_AU", "English (Australia)", "Australia/Sydney"),
    ("en_IE", "English (Ireland)", "Europe/Dublin"),
    ("en_IN", "English (India)", "Asia/Kolkata"),
    ("de_DE", "Deutsch (Deutschland)", "Europe/Berlin"),
    ("de_AT", "Deutsch (Österreich)", "Europe/Vienna"),
    ("de_CH", "Deutsch (Schweiz)", "Europe/Zurich"),
    ("fr_FR", "Français (France)", "Europe/Paris"),
    ("fr_CA", "Français (Canada)", "America/Toronto"),
    ("fr_BE", "Français (Belgique)", "Europe/Brussels"),
    ("es_ES", "Español (España)", "Europe/Madrid"),
    ("es_MX", "Español (México)", "America/Mexico_City"),
    ("es_AR", "Español (Argentina)", "America/Argentina/Buenos_Aires"),
    ("it_IT", "Italiano", "Europe/Rome"),
    ("pt_BR", "Português (Brasil)", "America/Sao_Paulo"),
    ("pt_PT", "Português (Portugal)", "Europe/Lisbon"),
    ("nl_NL", "Nederlands", "Europe/Amsterdam"),
    ("sv_SE", "Svenska", "Europe/Stockholm"),
    ("nb_NO", "Norsk bokmål", "Europe/Oslo"),
    ("da_DK", "Dansk", "Europe/Copenhagen"),
    ("fi_FI", "Suomi", "Europe/Helsinki"),
    ("pl_PL", "Polski", "Europe/Warsaw"),
    ("cs_CZ", "Čeština", "Europe/Prague"),
    ("hu_HU", "Magyar", "Europe/Budapest"),
    ("ro_RO", "Română", "Europe/Bucharest"),
    ("el_GR", "Ελληνικά", "Europe/Athens"),
    ("tr_TR", "Türkçe", "Europe/Istanbul"),
    ("ru_RU", "Русский", "Europe/Moscow"),
    ("uk_UA", "Українська", "Europe/Kyiv"),
    ("ja_JP", "日本語", "Asia/Tokyo"),
    ("ko_KR", "한국어", "Asia/Seoul"),
    ("zh_CN", "中文 (简体)", "Asia/Shanghai"),
    ("zh_TW", "中文 (繁體)", "Asia/Taipei"),
]

KEYBOARDS = [   # (id, name, the console's keymap, xkb layout, xkb variant)
    ("us", "English (US)", "us", "us", ""),
    ("us-intl", "English (US, international, with dead keys)", "us-acentos", "us", "intl"),
    ("gb", "English (UK)", "uk", "gb", ""),
    ("ie", "English (Ireland)", "ie", "ie", ""),
    ("de", "German", "de-latin1", "de", ""),
    ("de-ch", "German (Switzerland)", "de_CH-latin1", "ch", ""),
    ("at", "German (Austria)", "de-latin1", "at", ""),
    ("fr", "French (AZERTY)", "fr-latin1", "fr", ""),
    ("fr-ch", "French (Switzerland)", "fr_CH-latin1", "ch", "fr"),
    ("be", "Belgian", "be-latin1", "be", ""),
    ("ca-fr", "French (Canada)", "cf", "ca", ""),
    ("es", "Spanish", "es", "es", ""),
    ("latam", "Spanish (Latin America)", "la-latin1", "latam", ""),
    ("it", "Italian", "it", "it", ""),
    ("pt", "Portuguese", "pt-latin1", "pt", ""),
    ("br", "Portuguese (Brazil)", "br-abnt2", "br", ""),
    ("nl", "Dutch", "nl", "nl", ""),
    ("se", "Swedish", "sv-latin1", "se", ""),
    ("no", "Norwegian", "no-latin1", "no", ""),
    ("dk", "Danish", "dk-latin1", "dk", ""),
    ("fi", "Finnish", "fi", "fi", ""),
    ("pl", "Polish", "pl", "pl", ""),
    ("cz", "Czech", "cz-qwertz", "cz", ""),
    ("hu", "Hungarian", "hu", "hu", ""),
    ("ro", "Romanian", "ro_win", "ro", ""),
    ("gr", "Greek", "gr", "gr", ""),
    ("tr", "Turkish", "trq", "tr", ""),
    ("ru", "Russian", "ru", "ru", ""),
    ("ua", "Ukrainian", "ua-utf", "ua", ""),
    ("jp", "Japanese", "jp106", "jp", ""),
    ("kr", "Korean", "us", "kr", ""),
    ("dvorak", "English (Dvorak)", "dvorak", "us", "dvorak"),
    ("colemak", "English (Colemak)", "colemak", "us", "colemak"),
]
KEYBOARD = {k[0]: k for k in KEYBOARDS}
LANG_KEYBOARD = {"en_US": "us", "en_GB": "gb", "en_IE": "ie", "en_CA": "us", "en_AU": "us", "en_IN": "us",
                 "de_DE": "de", "de_AT": "at", "de_CH": "de-ch", "fr_FR": "fr", "fr_CA": "ca-fr", "fr_BE": "be",
                 "es_ES": "es", "es_MX": "latam", "es_AR": "latam", "it_IT": "it", "pt_BR": "br", "pt_PT": "pt",
                 "nl_NL": "us-intl", "sv_SE": "se", "nb_NO": "no", "da_DK": "dk", "fi_FI": "fi", "pl_PL": "pl",
                 "cs_CZ": "cz", "hu_HU": "hu", "ro_RO": "ro", "el_GR": "gr", "tr_TR": "tr", "ru_RU": "ru",
                 "uk_UA": "ua", "ja_JP": "jp", "ko_KR": "kr", "zh_CN": "us", "zh_TW": "us"}


def timezones():
    try:
        r = subprocess.run(["timedatectl", "list-timezones"], capture_output=True, text=True, timeout=10)
        zones = [z for z in r.stdout.split() if "/" in z or z == "UTC"]
        if zones:
            return zones
    except (OSError, subprocess.TimeoutExpired):
        pass
    out = []
    for line in (_read("/usr/share/zoneinfo/tzdata.zi").splitlines() if os.path.exists("/usr/share/zoneinfo/tzdata.zi") else []):
        if line.startswith("Z "):
            out.append(line.split()[1])
    return sorted(out) or ["UTC"]


def tz_guess(locale):
    return next((tz for loc, _, tz in LANGUAGES if loc == locale), "UTC")


def language_name(locale):
    return next((n for loc, n, _ in LANGUAGES if loc == locale), locale)


# ── what's typed ────────────────────────────────────────────────────────────────────────
RESERVED_USERS = {"root", "bin", "daemon", "mail", "ftp", "http", "nobody", "dbus", "systemd-journal",
                  "live", "sddm", "polkitd", "git", "admin", "user", "test", "wheel", "users", "audio",
                  "video", "input", "render", "storage", "lp", "kvm", "uucp", "adm", "sys", "tty"}


def suggest_username(full_name):
    first = (full_name or "").strip().split(" ")[0].lower() if full_name else ""
    first = re.sub(r"[^a-z0-9_-]", "", _ascii(first))
    if first and not first[0].isalpha():
        first = "u" + first
    return first[:32]


def _ascii(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def check_full_name(v):
    if ":" in v or "\n" in v:
        return "A name can't have a colon in it."
    return None


def check_username(v):
    if not v:
        return "Choose a user name: it's what you type to sign in."
    if len(v) > 32:
        return "Keep the user name to 32 letters or fewer."
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", v):
        return "Use small letters, digits, - or _, and start with a letter (for example: alex)."
    if v in RESERVED_USERS:
        return f"\"{v}\" is used by the system. Choose another user name."
    return None


def check_hostname(v):
    if not v:
        return "Give the computer a name, for example: alex-laptop."
    if len(v) > 63:
        return "Keep the computer's name to 63 letters or fewer."
    if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?", v):
        return "Use letters, digits and -, with no spaces, and not starting or ending with -."
    return None


def suggest_hostname(user, edition_id="desktop"):
    base = user or "bromigos"
    return f"{base}-{'server' if edition_id != 'desktop' else 'pc'}"[:63]


def check_password(pw, again, what="password"):
    if not pw:
        return f"Choose a {what}."
    if pw != again:
        return f"The two {what}s aren't the same. Type it again in both boxes."
    if len(pw) < 4:
        return f"Use at least 4 characters for the {what}."
    return None


def strength(pw):
    """(word, advice): a rough strength, said plainly."""
    n = len(pw)
    kinds = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if n < 8 or (n < 12 and kinds < 2):
        return "weak", "Longer is stronger: three or four unrelated words make a good one."
    if n >= 14 or (n >= 10 and kinds >= 3):
        return "strong", "That's a strong one."
    return "fair", "Fine. A few more characters makes it stronger."


# ── the network ─────────────────────────────────────────────────────────────────────────
def _in_store(name):
    pat = re.compile(re.escape(name) + r"-[^-]+-[^-]+-[^-]+\.pkg\.tar\.(zst|xz)$")
    for d in glob.glob(os.path.join(OFFLINE_REPO, "**", "x86_64"), recursive=True):
        try:
            if any(pat.match(f) for f in os.listdir(d)):
                return True
        except OSError:
            pass
    return False


def needs_download(ed):
    """Whether this edition's packages are missing from the medium's offline repository: the
    full ISO carries both editions, the small Field Kit stick only bromigOS Server, so only the
    desktop chosen on the small stick downloads."""
    if os.environ.get("BROMIGOS_ISO_ONLINE"):
        return True
    keys = ed.get("check_packages") or ed.get("packages") or ["bromigos", "bromigos-desktop"]
    return not all(_in_store(p) for p in keys)


def download_words(ed):
    return (f"{ed['title']} isn't on this USB stick, so it's downloaded while it installs: about "
            f"{ed.get('download_size', '3 GB')}. That needs the internet for the whole install.")


def offline_store():
    """Kept for the summary's wording: the chosen edition installs from the stick."""
    return True


def online(timeout=4):
    """Is the internet reachable? (NetworkManager's check, else a route and a name.)"""
    try:
        r = subprocess.run(["nmcli", "-t", "networking", "connectivity"], capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip() == "full"
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        import socket
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo("pkgs.bromigos.org", 443)
        return True
    except OSError:
        return False


def network_words(download, is_online):
    if not download and is_online:
        return "Connected to the internet. The install doesn't need it: everything is on this USB stick."
    if not download:
        return "Not connected. That's fine: everything the install needs is on this USB stick."
    if is_online:
        return "Connected to the internet. The install downloads what isn't on this USB stick."
    return ("Not connected. What you chose has to be downloaded while it installs, so it needs the "
            "internet: plug in a network cable, or connect to Wi-Fi. Or choose bromigOS Server, which "
            "is on this USB stick, or install from the full bromigOS USB stick, which has everything.")


def wifi_tool():
    """What the text installer offers for Wi-Fi: nmtui, else iwd's iwctl."""
    for t in ("nmtui", "iwctl"):
        if any(os.access(os.path.join(p, t), os.X_OK) for p in os.environ.get("PATH", "/usr/bin").split(":")):
            return t
    return None


# ── motion and colours (DRIFTGLASS) ─────────────────────────────────────────────────────
WICK = {"background": "#000500", "void": "#000500", "panel": "#001300", "selection": "#003b00",
        "primary": "#39ff14", "soft": "#9cff8a", "dim": "#159b09", "text": "#c4f5bb", "muted": "#7e927e",
        "faint": "#4e6b4e", "warn": "#d4af37", "danger": "#ff766f", "cyan": "#3fe0c5", "gold": "#f0d36a"}


def theme():
    sys.path.insert(0, "/usr/lib/bromigos/lib")
    try:
        import bromigos_theme as T
        T.version()
        c = dict(WICK)
        c.update(T.colors())
        return c, T.motion()
    except Exception:
        return dict(WICK), "full"


def reduced_motion():
    if os.environ.get("BROMIGOS_REDUCED_MOTION"):
        return True
    try:
        if "accessibility=on" in _read("/proc/cmdline"):
            return True
    except OSError:
        pass
    return theme()[1] in ("reduced", "still")


# ── checks before the install (warnings, not blocks) ────────────────────────────────────
BITLOCKER_WORDS = (
    "Before you go on, save the recovery key: in Windows, open Settings › Privacy & security › "
    "Device encryption › BitLocker drive encryption › Back up your recovery key, or sign in at "
    "aka.ms/myrecoverykey on another device and write the key down. It's 48 digits. Keep it "
    "somewhere that isn't this computer.")


def checks(probe=None):
    """[{id, level: warn|info, title, what, fix}]: this computer, in plain words."""
    out = []
    ac = None
    for d in glob.glob("/sys/class/power_supply/*"):
        try:
            kind = open(os.path.join(d, "type")).read().strip()
            if kind == "Mains":
                ac = (ac or False) or open(os.path.join(d, "online")).read().strip() == "1"
        except OSError:
            pass
    if ac is False:
        out.append({"id": "battery", "level": "warn", "title": "Running on battery",
                    "what": "If the battery runs out during the install, the disk is left half done.",
                    "fix": "Plug in the charger before you start."})
    try:
        with open("/proc/meminfo") as f:
            mem = int(next(l for l in f if l.startswith("MemTotal")).split()[1]) * 1024
    except (OSError, StopIteration, ValueError):
        mem = None
    if mem and mem < 4 * 10 ** 9 - 300 * 10 ** 6:
        out.append({"id": "ram", "level": "warn", "title": f"Only {mem / 10 ** 9:.1f} GB of memory",
                    "what": "bromigOS's desktop wants 4 GB or more; with less it runs, but slowly.",
                    "fix": "bromigOS Server (no desktop) runs well in less. More memory makes the desktop smooth."})
    fw = "uefi" if os.path.isdir("/sys/firmware/efi") else "bios"
    out.append({"id": "firmware", "level": "info", "title": "Started the " + ("newer way (UEFI)" if fw == "uefi" else "older way (BIOS)"),
                "what": "bromigOS installs either way, and its boot menu matches." + (
                    "" if fw == "uefi" else " If Windows is on this computer and was installed the newer way, restart and "
                                            "choose the USB stick's UEFI entry so the two can share a boot menu."),
                "fix": ""})
    sb = secure_boot()
    if sb:
        out.append(sb)
    for d in (probe or {}).get("disks", []):
        if (d.get("health") or {}).get("state") == "failing" and not d.get("medium"):
            out.append({"id": "disk-" + d["path"], "level": "warn", "title": f"{d['model']} may be failing",
                        "what": d["health"]["why"] + " Anything installed on it may be lost.",
                        "fix": "Copy what you want to keep off it, and install on another disk. To install on it anyway, "
                               "tick the box under it on the Where step."})
    out += gpu_checks()
    return out


def secure_boot():
    """Secure Boot, in the medium's own words (the release pipeline's bromigos-iso-secureboot
    check, docs/secureboot.md): exit 1 means it's on and the installed system can't start
    with it on yet, so a warning with its words and what to do; exit 0 (off, a BIOS start)
    or no reader: nothing to say."""
    tool = os.environ.get("BROMIGOS_ISO_SECUREBOOT", "/usr/local/bin/bromigos-iso-secureboot")
    if not os.access(tool, os.X_OK):
        return None
    try:
        r = subprocess.run([tool, "check"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 1:
        return None
    paras = [" ".join(p.split()) for p in r.stdout.split("\n\n") if p.strip()]
    what = paras[1] if len(paras) > 1 else "The installed system can't start with Secure Boot on yet."
    what, _, how = what.partition(" How: ")     # its words already say what to do; the link, how
    fix = f"How to turn it off, step by step: {how.strip()}" if how.strip() else ""
    return {"id": "secureboot", "level": "warn", "title": (paras[0].rstrip(".") if paras else "Secure Boot is on"),
            "what": what, "fix": fix}


def gpu_checks():
    try:
        r = subprocess.run(["bromigos", "hw", "detect", "--json"], capture_output=True, text=True, timeout=30)
        hw = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    out = []
    plan = hw.get("plan") or {}
    # warnings only: the plan's notes are for Settings › Graphics (how several cards share the
    # screens), not something to stop and read before an install
    for note in plan.get("warnings") or []:
        text = note.get("text") if isinstance(note, dict) else str(note)
        if text:
            out.append({"id": "gpu", "level": "warn", "title": "Graphics", "what": text,
                        "fix": "The desktop still starts with basic graphics; Settings › Graphics says what's possible."})
    for g in (hw.get("detection") or {}).get("gpus") or []:
        if g.get("supported") is False:
            out.append({"id": "gpu", "level": "warn", "title": f"{g.get('vendor', '')} {g.get('name', '')}".strip(),
                        "what": "bromigOS can't drive this graphics card well: the desktop may be slow or plain.",
                        "fix": "bromigOS Server doesn't need graphics. For the desktop, a newer card helps."})
    return out


def save_report(answers=None, where=None):
    """A problem report (the install's log, archinstall's, the hardware, the answers without
    passwords) on a writable USB drive: another stick, else this stick's own small FAT
    partition. Returns (path, words) or (None, words)."""
    import shutil
    import tarfile
    import time
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = tempfile_dir()
    files = {"install.log": "/var/log/bromigos-iso-install.log", "archinstall.log": "/var/log/archinstall/install.log"}
    for name, src in files.items():
        try:
            shutil.copy(src, os.path.join(work, name))
        except OSError:
            pass
    for name, argv in (("hardware.json", ["bromigos", "hw", "detect", "--json"]), ("lsblk.txt", ["lsblk", "-o", "NAME,SIZE,FSTYPE,PARTTYPENAME,MODEL"]),
                       ("journal.txt", ["journalctl", "-b", "--no-pager", "-n", "3000"])):
        try:
            open(os.path.join(work, name), "w").write(subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if answers:
        open(os.path.join(work, "answers.toml"), "w").write(answers_toml(answers))
    tar = os.path.join(work + ".tar.gz")
    with tarfile.open(tar, "w:gz") as t:
        t.add(work, arcname=f"bromigos-problem-{stamp}")
    for mnt, label in writable_usb(where):
        dest = os.path.join(mnt, f"bromigos-problem-{stamp}.tar.gz")
        try:
            shutil.copy(tar, dest)
            subprocess.run(["sync"])
            return dest, f"Saved to {label} as bromigos-problem-{stamp}.tar.gz. Attach it when you ask for help."
        except OSError:
            continue
    return None, (f"There's no USB drive to save it on. Plug one in (any stick with room) and press the button again. "
                  f"Until then it's at {tar} on this live system.")


def tempfile_dir():
    import tempfile
    return tempfile.mkdtemp(prefix="bromigos-report-")


def writable_usb(where=None):
    """(mount point, words) for each writable removable partition: other sticks first, then
    this stick's own FAT partition (archiso's EFI image partition, which has a little room)."""
    if where:
        yield where, where
        return
    if os.geteuid() != 0 or os.environ.get("BROMIGOS_NO_USB"):      # it mounts: root's job, never a test's
        return
    try:
        doc = json.loads(subprocess.run(["lsblk", "-J", "-o", "PATH,FSTYPE,LABEL,RM,TRAN,MOUNTPOINTS,TYPE"],
                                        capture_output=True, text=True).stdout)
    except (OSError, ValueError):
        return
    medium, others = [], []

    def walk(devs, usb=False):
        for d in devs:
            u = usb or d.get("tran") == "usb" or d.get("rm")
            # a partition, or a whole stick formatted without a partition table
            if d.get("type") in ("part", "disk") and u and d.get("fstype") in ("vfat", "exfat", "ntfs"):
                (medium if (d.get("label") or "").startswith("ARCHISO") else others).append(d)
            walk(d.get("children") or [], u)
    walk(doc.get("blockdevices", []))
    for d in others + medium:
        mp = next((m for m in d.get("mountpoints") or [] if m), None)
        if not mp:
            mp = f"/run/bromigos-usb-{os.path.basename(d['path'])}"
            try:
                os.makedirs(mp, exist_ok=True)
            except OSError:
                continue
            if subprocess.run(["mount", d["path"], mp], capture_output=True).returncode != 0:
                continue
        yield mp, ("the USB stick bromigOS started from" if d in medium else f"the USB drive {d.get('label') or d['path']}")


# ── answer files (unattended installs) ──────────────────────────────────────────────────
ANSWER_KEYS = ["edition", "locale", "timezone", "keyboard", "disk", "mode", "bromigos_bytes", "full_name", "user",
               "hostname", "encrypt", "separate_passphrase", "ssh", "ssh_password", "ssh_keys", "firewall", "auto_updates",
               "password", "passphrase"]


def answers_toml(a, secrets=False):
    """The answers as TOML (docs/iso.md, "Answer files"): what install-answers.toml keeps, without
    the password and passphrase unless secrets."""
    lines = ["# bromigOS install answers (docs/iso.md, \"Answer files\")", "[install]"]
    for k in ANSWER_KEYS:
        if k in ("password", "passphrase") and not secrets:
            continue
        v = a.get(k)
        if v in (None, ""):
            continue
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, list):
            lines.append(f"{k} = [" + ", ".join(json.dumps(str(x)) for x in v) + "]")
        elif isinstance(v, int):
            lines.append(f"{k} = {v}")
        else:
            lines.append(f'{k} = "{str(v)}"'.replace("\\", "\\\\"))
    return "\n".join(lines) + "\n"


ANSWER_FILE_PLACES = ["bromigos/install.toml", "fieldkit/install.toml", "bromigos/install.yaml", "fieldkit/install.yaml"]


def find_answer_file():
    """An answer file: bromigos.answers=PATH on the kernel line (a path on any partition of the
    stick, or a file), else bromigos/install.toml or fieldkit/install.toml on a USB partition."""
    try:
        cmd = _read("/proc/cmdline").split()
    except OSError:
        cmd = []
    given = next((w.split("=", 1)[1] for w in cmd if w.startswith("bromigos.answers=")), None)
    if os.environ.get("BROMIGOS_ANSWERS"):
        given = os.environ["BROMIGOS_ANSWERS"]
    roots = ["/run/archiso/bootmnt"] + [mp for mp, _ in writable_usb()]
    if given:
        if os.path.isfile(given):
            return given
        roots = [r for r in roots]
        for r in roots:
            if os.path.isfile(os.path.join(r, given.lstrip("/"))):
                return os.path.join(r, given.lstrip("/"))
        return None
    for r in roots:
        for rel in ANSWER_FILE_PLACES:
            if os.path.isfile(os.path.join(r, rel)):
                return os.path.join(r, rel)
    return None


def read_answer_file(path):
    """The answers in it, over the defaults; and the problems with them, in plain words."""
    text = _read(path)
    if path.endswith((".yaml", ".yml")):
        doc = {"install": _mini_yaml(text)}
    else:
        import tomllib
        doc = tomllib.loads(text)
    got = doc.get("install", doc)
    a = defaults()
    problems = []
    for k, v in got.items():
        if k in ANSWER_KEYS or k in ("countdown", "failing_ok", "bitlocker_saved"):
            a[k] = v
        else:
            problems.append(f"\"{k}\" isn't an answer the installer knows; it's ignored.")
    a["countdown"] = int(got.get("countdown", 10))
    if not a.get("password"):
        problems.append("The answer file has no password: add password = \"…\" under [install].")
    if a.get("mode") not in ("erase", "alongside", "reinstall"):
        problems.append("mode must be \"erase\", \"alongside\" or \"reinstall\".")
    if not a.get("disk"):
        problems.append("disk must name the disk, for example disk = \"/dev/nvme0n1\".")
    if not a.get("hostname"):
        a["hostname"] = suggest_hostname(a.get("user"), a.get("edition", "desktop"))
    for check, key in ((check_username, "user"), (check_hostname, "hostname")):
        p = check(a.get(key) or "")
        if p:
            problems.append(f"{key}: {p}")
    if a.get("keyboard") not in KEYBOARD:
        problems.append(f"keyboard \"{a.get('keyboard')}\" isn't one of: " + ", ".join(KEYBOARD))
    return a, problems


def auto_check(a, probe):
    """An answer file's choices against the disks found: None, or what's wrong."""
    d = next((x for x in (probe or {}).get("disks", []) if x["path"] == a.get("disk")), None)
    if not d:
        return f"The answer file names the disk {a.get('disk')}, which isn't in this computer."
    opt = d["options"].get(a.get("mode"), {})
    if not opt.get("ok"):
        return f"The answer file asks to {a.get('mode')} on {d['model']}, which can't be done here: {opt.get('why', '')}"
    if (d.get("health") or {}).get("state") == "failing" and not a.get("failing_ok"):
        return f"{d['model']} says it's failing; add failing_ok = true to the answer file to install on it anyway."
    if d.get("bitlocker") and a.get("mode") == "alongside" and not a.get("bitlocker_saved"):
        return "Windows here uses BitLocker: add bitlocker_saved = true once its recovery key is saved."
    return None


def _mini_yaml(text):
    """The answers' flat YAML form (key: value per line), without a YAML library."""
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line or ":" not in line or line.startswith(("install:", "---")):
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        v = v.strip("\"'")
        out[k] = {"true": True, "false": False}.get(v.lower(), int(v) if v.isdigit() else v)
    return out


# ── the answers, and the summary ────────────────────────────────────────────────────────
def cmdline():
    try:
        return _read("/proc/cmdline").split()
    except OSError:
        return []


def boot_edition():
    """The edition the boot menu's entry chose (bromigos.edition=server|desktop), else None."""
    v = next((w.split("=", 1)[1] for w in cmdline() if w.startswith("bromigos.edition=")), None)
    v = EDITION_NAMES.get(v, v)
    return v if v in [e["id"] for e in editions()] else None


def wants_text(words=None):
    """This boot asks for the text installer: "Install bromigOS (text mode)" (bromigos.install=text),
    bromigos.text, or a bromigOS Server entry (bromigos.edition=server)."""
    words = cmdline() if words is None else words
    return ("bromigos.install=text" in words or "bromigos.text" in words
            or any(w in ("bromigos.edition=server", "bromigos.edition=fieldkit") for w in words))


def defaults():
    return {"edition": boot_edition() or "desktop", "locale": "en_US", "keyboard": "us", "timezone": tz_guess("en_US"),
            "disk": None, "mode": None, "bromigos_bytes": None, "full_name": "", "user": "",
            "password": "", "hostname": "", "encrypt": True, "separate_passphrase": False,
            "passphrase": "", "ssh": False, "ssh_password": False, "ssh_keys": [], "firewall": True,
            "auto_updates": True}


def backend_answers(a, disk):
    """What bromigos-iso-install --answers reads: the choices, resolved."""
    kb = KEYBOARD.get(a["keyboard"], KEYBOARDS[0])
    ed = edition(a.get("edition", "desktop"))
    opt = (disk or {}).get("options", {}).get("alongside", {}) if a.get("mode") == "alongside" else {}
    re_opt = (disk or {}).get("options", {}).get("reinstall", {}) if a.get("mode") == "reinstall" else {}
    out = {
        "schema": 1, "edition": ed["id"], "answers_toml": answers_toml(a), "edition_file": ed.get("source"), "desktop": bool(ed.get("desktop", True)),
        "disk": a["disk"], "mode": a["mode"], "esp": opt.get("esp"),
        "shrink": None, "user": a["user"], "full_name": a["full_name"], "password": a["password"],
        "hostname": a["hostname"], "encrypt": bool(re_opt.get("encrypted")) if re_opt else bool(a["encrypt"]),
        "old_passphrase": a.get("old_passphrase") or None,
        "passphrase": a["passphrase"] if a["encrypt"] and a.get("separate_passphrase") else None,
        "keymap": kb[2], "xkb_layout": kb[3], "xkb_variant": kb[4], "locale": a["locale"],
        "timezone": a["timezone"], "ssh": bool(a.get("ssh")), "online": needs_download(ed),
        "ssh_password": bool(a.get("ssh") and a.get("ssh_password")), "ssh_keys": list(a.get("ssh_keys") or []) if a.get("ssh") else [],
        "firewall": bool(a.get("firewall", True)) and not ed.get("desktop", True),
        "auto_updates": bool(a.get("auto_updates", True)) and not ed.get("desktop", True),
        "auto_update_units": ed.get("auto_update_units") or [],
        "advanced": dict(a.get("advanced") or {}),
        "user_commands": ed.get("user_commands") or [], "default_target": ed.get("default_target") or
        ("graphical.target" if ed.get("desktop", True) else "multi-user.target"),
        "other_os": a["mode"] == "alongside" or bool(a.get("other_os")),
    }
    if a["mode"] == "alongside" and opt.get("mode") == "shrink":
        out["shrink"] = {"partition": opt["partition"], "fs": opt["fs"], "who": opt.get("who"),
                         "bromigos_bytes": int(a.get("bromigos_bytes") or opt["default"])}
    return out


def summary(a, disk):
    """[(label, value)] in plain words, and the one warning line (or None)."""
    from .disks import plain_size
    ed = edition(a.get("edition", "desktop"))
    kb = KEYBOARD.get(a["keyboard"], KEYBOARDS[0])
    rows = []
    if len(editions()) > 1:
        rows.append(("Kind", ed["title"]))
    rows += [("Language", language_name(a["locale"])), ("Time zone", a["timezone"].replace("_", " ")),
             ("Keyboard", kb[1])]
    where = f"{disk['model']} ({disk['size_text']})" if disk else "?"
    warn = None
    if a["mode"] == "reinstall":
        rows.append(("Disk", f"{where}: bromigOS made fresh; your home folder and its files stay, the old system "
                             "is kept as a snapshot"))
    elif a["mode"] == "erase":
        rows.append(("Disk", f"{where}: erased, then bromigOS on all of it"))
        lost = disk["options"]["erase"].get("loses") if disk else ""
        warn = f"Everything on {where} is deleted: {lost}." if disk and disk["partitions"] else None
    else:
        opt = disk["options"]["alongside"]
        if opt.get("mode") == "shrink":
            b = int(a.get("bromigos_bytes") or opt["default"])
            rows.append(("Disk", f"{where}: {opt.get('who')} made smaller to {plain_size(opt['part_size'] + opt['free_after'] - b)}, "
                                 f"bromigOS gets {plain_size(b)}"))
            warn = (f"{opt.get('who')} keeps its files, but back up anything important first: changing a "
                    "disk always carries a small risk.")
        else:
            rows.append(("Disk", f"{where}: bromigOS in the {opt['size_text']} of free space, beside {opt.get('name') or 'what is there'}"))
        rows.append(("Boot menu", f"bromigOS and {opt.get('name') or 'the other system'}: you choose at every start"))
        if opt.get("warn"):
            warn = (warn + " " if warn else "") + opt["warn"]
    rows.append(("Name", a["full_name"] or a["user"]))
    rows.append(("User name", a["user"]))
    rows.append(("Computer name", a["hostname"]))
    if a["mode"] == "reinstall":
        rows.append(("Encryption", "As it was" + (" (on)" if (disk or {}).get("options", {}).get("reinstall", {}).get("encrypted") else " (off)")))
    elif a["encrypt"]:
        rows.append(("Encryption", "On: a passphrase of its own at every start" if a.get("separate_passphrase")
                     else "On: your password unlocks the disk at every start"))
    else:
        rows.append(("Encryption", "Off"))
    if not ed.get("desktop", True):
        if a.get("ssh"):
            n = len(a.get("ssh_keys") or [])
            rows.append(("Remote access (SSH)", ("On, with a password or " if a.get("ssh_password") else "On, keys only: ")
                         + (f"{n} key{'s' if n != 1 else ''}" if n else "no key yet")))
        else:
            rows.append(("Remote access (SSH)", "Off"))
        rows.append(("Firewall", "On" if a.get("firewall", True) else "Off"))
        rows.append(("Automatic updates", "On, with a snapshot before each" if a.get("auto_updates", True) else "Off"))
    rows.append(("Packages", f"Downloaded from the internet (about {ed.get('download_size', '3 GB')})" if needs_download(ed)
                 else "From this USB stick (no internet needed)"))
    return rows, warn


ADVANCED_WORDS = (
    "For people who know what they want. The defaults suit almost everyone: btrfs with snapshots, "
    "Arch's own kernel, compressed swap in memory, GRUB.")
KERNELS = [("linux", "linux: Arch's own, the newest (recommended)"), ("linux-lts", "linux-lts: long-term support, changes less"),
           ("linux-zen", "linux-zen: tuned for desktops and games")]
FILESYSTEMS = [("btrfs", "btrfs, with snapshots and rollback (recommended)"), ("ext4", "ext4, no snapshots")]
BOOTLOADER_WORDS = ("GRUB: it lists the snapshots and the other systems at every start. For another boot loader "
                    "(systemd-boot, Limine), partition it yourself in archinstall's menu.")


def what_will_run(doc):
    """The commands the install runs, in order, as a power user would type them (no secrets)."""
    desktop = doc.get("desktop", True)
    lines = ["# as root, on this USB stick:",
             "bromigos-iso-install --answers ANSWERS.json --no-reboot"]
    if doc.get("shrink"):
        s = doc["shrink"]
        lines.append(f"  disks.py shrink: {s['partition']} ({s['fs']}) made smaller by "
                     f"{s['bromigos_bytes'] / 2 ** 30:.0f} GiB (ntfsresize/resize2fs, then sfdisk)")
    lines += ["  answers.py --answers ANSWERS.json --out DIR       # writes DIR/config.json and DIR/creds.json (0600)",
              "  archinstall --config DIR/config.json --creds DIR/creds.json " + ("" if doc.get("online") else "--offline ")
              + "--silent"]
    lines.append("# then in the new system, as you:")
    if desktop:
        kb = f" --set kb_layout {doc.get('xkb_layout')}" + (f" --set kb_variant {doc['xkb_variant']}" if doc.get("xkb_variant") else "")
        lines += ["bromigos install --yes --no-services --no-setup",
                  "bromigos setup --monitors auto --theme wick --vector none --voice off --create none",
                  "bromigos setup input" + kb]
    else:
        lines += [c for c in doc.get("user_commands") or []]
        lines.append(f"systemctl set-default {doc.get('default_target') or 'multi-user.target'}")
    if (doc.get("advanced") or {}).get("fs", "btrfs") == "btrfs":
        lines.append("bromigos rollback setup --yes")
    if doc.get("other_os"):
        lines.append("GRUB_DISABLE_OS_PROBER=false in /etc/default/grub; grub-mkconfig -o /boot/grub/grub.cfg")
    lines.append("# what you chose is kept, without passwords, in /var/log/bromigos/install-answers.toml")
    return lines


def redact_creds(creds):
    """archinstall's credentials with every secret shown as ********."""
    def walk(v, key=""):
        if isinstance(v, dict):
            return {k: walk(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, key) for x in v]
        return "********" if any(w in key for w in ("password", "passphrase", "secret", "enc_")) else v
    return walk(creds)


ENCRYPT_WORDS = (
    "With encryption on, the disk can only be read after you type its passphrase when the "
    "computer starts. If it's lost or stolen, your files stay private. If you forget the "
    "passphrase, nobody can get your files back, not even with the disk in hand.")
SSH_WORDS = (
    "SSH lets you use this computer from another one on your network. Turn it on if you'll "
    "manage it from elsewhere; leave it off if you'll use its own keyboard and screen.")
SSH_KEY_WORDS = (
    "Keys only (recommended): you sign in with a key file from your other computer, which "
    "nobody can guess. A password login is easier to set up, but anyone on the network can try "
    "passwords.")
FIREWALL_WORDS = "Firewall: blocks connections from other computers, except SSH when it's on."
AUTO_UPDATE_WORDS = ("Automatic updates: installs security fixes by itself, with a snapshot first, "
                     "so a bad update can be rolled back from the boot menu.")


def stick_keys():
    """SSH public keys in the USB stick's fieldkit/ folder (any *.pub): [(file, key line)]."""
    out = []
    roots = ["/run/archiso/bootmnt"] + [mp for mp, _ in writable_usb()]
    for r in roots:
        for path in sorted(glob.glob(os.path.join(r, "fieldkit", "*.pub")) + glob.glob(os.path.join(r, "fieldkit", "authorized_keys"))):
            try:
                for line in open(path):
                    line = line.strip()
                    if check_key(line) is None and line not in [k for _, k in out]:
                        out.append((os.path.basename(path), line))
            except OSError:
                pass
    return out


def check_key(line):
    if re.match(r"^(ssh-(ed25519|rsa)|ecdsa-sha2-nistp\d+|sk-(ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com) [A-Za-z0-9+/=]{20,}( .*)?$", line or ""):
        return None
    return ("That isn't an SSH public key. It's one line that starts with ssh-ed25519 or ssh-rsa, then a long run of "
            "letters: the .pub file from your other computer.")



def disk_segments(d):
    """The disk in order, for the maps: [(role, bytes, words, partition or None)], role one
    of efi, msr, windows, recovery, linux, other, free."""
    out, pos = [], 0
    parts = sorted(d.get("partitions") or [], key=lambda p: p.get("start", 0))
    frees = sorted(d.get("free") or [], key=lambda f: f["start"])
    big = 64 * 2 ** 20
    for p in parts:
        for f in frees:
            if pos <= f["start"] < p.get("start", 0) and f["size"] > big:
                out.append(("free", f["size"], "Free space", None))
        what = p.get("what") or p["path"]
        if p.get("esp"):
            role = "efi"
        elif "Microsoft reserved" in what:
            role = "msr"
        elif p.get("windows"):
            role = "windows"
        elif "recovery" in what.lower():
            role = "recovery"
        elif p.get("fstype") in ("btrfs", "ext4", "crypto_LUKS", "xfs"):
            role = "linux"
        else:
            role = "other"
        out.append((role, p["size"], what, p))
        pos = p.get("start", 0) + p["size"]
    for f in frees:
        if f["start"] >= pos and f["size"] > big:
            out.append(("free", f["size"], "Free space", None))
    return out
