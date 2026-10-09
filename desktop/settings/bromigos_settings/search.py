"""The search across all settings: every page, every setting a page declares (its Entry
list, and its sections'), found by its name, its synonyms, the group on the page it sits
in and the page itself. Pure Python (no toolkit), so it's tested without a display.

    idx = Index(pages)
    for r in idx.search("wifi"):        # [Result], best first
        r.page, r.key, r.title, r.where  # "network", "wifi", "Wi-Fi", "System › Network"

Words match by prefix ("blue" finds Bluetooth), each word of the query must match
somewhere, and synonyms widen a word ("dnd" finds Do not disturb, "speakers" finds the
output device). A title match beats a keyword match beats a page's description beats the
page it's on.
"""
import re
import unicodedata
from dataclasses import dataclass, field

# Words that mean the same thing to the person typing. Each set is one meaning; a query word
# found in a set also matches the set's other words (phrases are matched as phrases).
SYNONYMS = [
    {"wifi", "wireless", "wlan", "ssid", "hotspot", "access point"},
    {"bluetooth", "bt", "pair", "pairing"},
    {"sound", "audio", "volume", "loudness"},
    {"speaker", "speakers", "headphones", "headset", "output device"},
    {"microphone", "mic", "input device", "recording"},
    {"display", "displays", "monitor", "monitors", "screen", "screens", "output"},
    {"resolution", "mode", "pixels"},
    {"refresh", "refresh rate", "hz", "hertz", "fps"},
    {"scale", "scaling", "hidpi", "dpi", "zoom", "size"},
    {"arrangement", "arrange", "position", "layout"},
    {"power", "energy", "battery", "charge"},
    {"suspend", "sleep", "standby", "hibernate"},
    {"lid", "laptop lid", "close the lid"},
    {"profile", "power profile", "performance", "balanced", "power saver"},
    {"keyboard", "keymap", "xkb", "layout"},
    {"repeat", "key repeat", "repeat rate", "repeat delay"},
    {"caps", "caps lock", "capslock", "escape", "ctrl"},
    {"mouse", "pointer", "cursor"},
    {"touchpad", "trackpad", "tap", "tap to click", "natural scroll", "scrolling"},
    {"notification", "notifications", "alerts", "banners", "popups", "dunst"},
    {"do not disturb", "dnd", "quiet", "silence"},
    {"time", "clock", "date", "calendar"},
    {"timezone", "time zone", "zone", "tz"},
    {"ntp", "network time", "automatic time", "sync"},
    {"24 hour", "24h", "12 hour", "12h", "am pm", "time format"},
    {"startup", "autostart", "login", "start at login", "launch at login"},
    {"theme", "themes", "colours", "colors", "appearance"},
    {"dark mode", "light mode", "night mode", "dark theme", "light theme", "colour scheme", "color scheme"},
    {"wallpaper", "background", "live background", "desktop background"},
    {"screensaver", "screen saver", "saver"},
    {"vector", "assistant", "ai", "copilot"},
    {"voice", "speech", "tts", "talk", "speak"},
    {"brain", "model", "llm", "endpoint"},
    {"memory", "history", "forget", "privacy", "conversation log"},
    {"terminal", "shell", "kill switch", "console"},
    {"update", "updates", "upgrade", "pacman", "packages"},
    {"channel", "stable", "edge", "rc", "branch"},
    {"rollback", "roll back", "snapshot", "snapshots", "snapper", "recovery", "restore", "undo update"},
    {"boot", "boot menu", "grub", "bootloader"},
    {"account", "profile", "user", "me", "name", "avatar", "picture", "photo"},
    {"about", "version", "system info", "hardware", "specs", "licence", "license", "licences"},
    {"widgets", "widget", "panels", "panel"},
    {"weather", "forecast", "location"},
    {"extensions", "extension", "plugins", "plugin", "addons", "add ons", "catalog"},
    {"default apps", "default applications", "default", "open with", "mime", "handler"},
    {"browser", "web browser", "firefox", "chromium"},
    {"editor", "text editor"},
    {"file manager", "files", "folders"},
    {"web apps", "webapp", "web app", "pwa"},
    {"network", "internet", "connection", "connections", "online"},
    {"wired", "ethernet", "cable", "lan"},
    {"vpn", "wireguard", "tunnel"},
    {"lock", "lock screen", "password"},
    {"idle", "inactivity", "away", "dpms", "caffeine", "stay awake", "inhibit"},
    {"shortcuts", "shortcut", "keys", "hotkeys", "hotkey", "keybindings", "keybinds", "binds"},
    {"accessibility", "a11y", "contrast", "high contrast", "reduced motion", "motion"},
    {"peripherals", "peripheral", "razer", "macro keys", "dial", "lighting", "rgb"},
    {"holograms", "hologram", "decks", "deck", "holo"},
    {"mute", "silent", "unmute"},
    {"targets", "where ai runs", "local", "lab", "cloud", "homelab"},
]

_WS = re.compile(r"\s+")


def norm(text):
    """Lowercase, no accents, hyphens joined ("Wi-Fi" -> "wifi"), other punctuation spaced."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"(?<=\w)[-'’](?=\w)", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return _WS.sub(" ", t).strip()


def _split_forms(text):
    """The words of `text`: each hyphenated word both joined and split ("24-hour" gives
    "24hour", "24" and "hour")."""
    raw = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    words = set(norm(raw).split())
    for part in re.split(r"[\s/,;:()]+", raw):
        if "-" in part:
            words |= set(norm(part.replace("-", " ")).split())
    return words


_SYN = [{norm(w) for w in s} for s in SYNONYMS]


def expand(word):
    """`word` and every synonym of it (normalized; phrases stay phrases)."""
    out = {word}
    for s in _SYN:
        if word in s:
            out |= s
    return out


@dataclass
class Item:
    kind: str                  # "page", "setting" or "section"
    page: str                  # the page's id
    key: str                   # the setting's key on its page ("" for a page)
    title: str
    page_title: str
    group: str                 # the sidebar group's title
    section: str = ""
    keywords: list = field(default_factory=list)
    order: tuple = ()
    about: list = field(default_factory=list)    # a page's summary and intro: prose, weaker
    _fields: dict = field(default_factory=dict, repr=False)

    def prepare(self):
        # field -> (its words, its normalized text); weights in Index.WEIGHTS
        f = {"title": self.title, "keywords": " , ".join(self.keywords), "about": " , ".join(self.about),
             "section": self.section, "page": self.page_title if self.kind != "page" else ""}
        self._fields = {k: (_split_forms(v), " " + norm(v) + " ") for k, v in f.items()}
        return self

    @property
    def where(self):
        bits = [self.group, self.page_title] + ([self.section] if self.section and self.kind == "setting" else [])
        return " › ".join(b for b in bits if b)


@dataclass
class Result:
    item: Item
    score: float

    def __getattr__(self, name):
        return getattr(self.item, name)


class Index:
    # a page's summary and intro are sentences: a word in them ("a screen gone dark") is a
    # weaker sign than a keyword someone chose for the setting
    WEIGHTS = {"title": 10.0, "keywords": 6.0, "about": 3.0, "section": 3.0, "page": 2.0}

    def __init__(self, pages, group_titles=None):
        from .registry import GROUPS
        titles = dict((g, t) for g, t, _ in GROUPS)
        titles.update(group_titles or {})
        self.items = []
        for n, p in enumerate(pages):
            gt = titles.get(p.group_id, "")
            self.items.append(Item("page", p.id, "", p.title, p.title, gt, "",
                                   [p.id] + list(p.keywords), (n, 0), [p.summary, p.intro]).prepare())
            entries = [(e, "") for e in p.entries]
            for s in p.sections:
                self.items.append(Item("section", p.id, f"section:{s.id}", s.title, p.title, gt, "",
                                       list(s.keywords), (n, 1)).prepare())
                entries += [(e, s.title) for e in s.entries]
            seen = set()
            for m, (e, sec_title) in enumerate(entries):
                if e.key in seen:
                    continue
                seen.add(e.key)
                self.items.append(Item("setting", p.id, e.key, e.title, p.title, gt, e.section or sec_title,
                                       list(e.keywords), (n, 2 + m)).prepare())

    def _word_score(self, item, word):
        """The best field match for one query word (with its synonyms), 0 for none."""
        best = 0.0
        for alt in expand(word):
            phrase = " " in alt
            for name, (words, text) in item._fields.items():
                w = self.WEIGHTS[name]
                if phrase:
                    hit = w * 0.9 if f" {alt} " in text else 0.0
                elif alt in words:
                    hit = w
                elif any(x.startswith(alt) for x in words):
                    hit = w * (0.8 if len(alt) >= 3 else 0.5)
                else:
                    hit = 0.0
                if alt != word:
                    hit *= 0.7               # a synonym counts a little less than the word itself
                best = max(best, hit)
        return best

    def search(self, query, limit=40):
        q = norm(query)
        if not q:
            return []
        words = q.split()
        out = []
        for it in self.items:
            total = 0.0
            for w in words:
                s = self._word_score(it, w)
                if s == 0.0:
                    # a phrase synonym spanning words ("do not disturb" typed out): checked below
                    total = None
                    break
                total += s
            title = norm(it.title)
            if total is None:
                # the whole query as one phrase, or a synonym phrase of it
                if any(f" {alt} " in it._fields["title"][1] or f" {alt} " in it._fields["keywords"][1]
                       for alt in expand(q)):
                    total = 8.0 * len(words)
                else:
                    continue
            if title == q:
                total += 20
            elif title.startswith(q):
                total += 12
            if it.kind == "page" and norm(it.page_title).startswith(q):
                total += 4
            out.append(Result(it, total))
        out.sort(key=lambda r: (-r.score, r.item.order))
        return out[:limit]
