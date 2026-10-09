"""The page registry: every Settings page is a module in one of the page folders that
defines `PAGE` (a Page) or `PAGES` (a list of them). A module may also define `SECTION`
or `SECTIONS`: groups it adds to another package's page (a package that owns a feature
adds its part of a page without editing the page's file).

Folders, read in this order; a page whose id was already seen replaces the earlier one
(so a user can replace a packaged page):

1. the app's own `pages/` (`/usr/lib/bromigos/settings/pages/`): bromigOS's pages, and any
   package's (bromigos-homelab, a hardware module …: pacman owns each file there);
2. `$BROMIGOS_SETTINGS_PAGES` (colon-separated; for tests and development);
3. installed extensions' (`~/.local/share/bromigos/ext/active/settings/`);
4. the user's plugin folder (`~/.config/bromigos/plugins/settings/`).

A module that fails to import, or a PAGE that isn't a Page, is skipped and reported
(`bromigos-settings --list` prints the registry with any problems); it never stops the
window. Pages are listed by group (GROUPS), then `order`, then title.
"""
import importlib.util
import os
import sys
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# The sidebar's groups, in order: (id, title, what's in it)
GROUPS = [
    ("system", "System", "the machine: displays, sound, network, power, input, updates"),
    ("desktop", "Desktop", "how the desktop looks and behaves"),
    ("vector", "VECTOR & AI", "VECTOR, and where AI work runs"),
    ("lab", "Lab", "your homelab"),
    ("personal", "Personal", "who you are"),
    ("about", "About", "this machine and bromigOS"),
]
GROUP_IDS = [g for g, _, _ in GROUPS]
# Pages that name no group (written before groups, or by another package): where they go.
DEFAULT_GROUP = {
    "theme": "desktop", "idle": "desktop", "shortcuts": "desktop", "accessibility": "desktop",
    "targets": "vector", "updates": "system", "lab": "lab", "lab-models": "lab", "homelab": "lab",
}


@dataclass
class Entry:
    """One setting on a page, for the search across all settings.

    key       unique on its page ("output"); the row built with `ctx.row(…, key=…)` is
              the one a search result opens
    title     the row's name ("Output device")
    keywords  synonyms and words people search for ("speakers", "headphones")
    section   the group on the page it sits in ("Output")
    """
    key: str
    title: str
    keywords: list = field(default_factory=list)
    section: str = ""


@dataclass
class Page:
    """One page of Settings.

    id        a short lowercase name, unique: what `bromigos settings ID` opens
    title     the sidebar's and the header's name ("Idle & lock")
    build     build(ctx) -> Gtk.Widget, called the first time the page is shown
    icon      a symbolic icon name for the sidebar, or several (a list, or names separated by
              spaces): the first the icon theme has
    order     where it sits in its group (leave gaps)
    summary   the sidebar row's second line (a few words)
    keywords  more words the search matches for the page itself
    refresh   refresh(widget) -> None, called each time the page is shown again
    group     the sidebar group: system, desktop, vector, lab, personal, about
    intro     the page's short explanation, under its title (default: the summary)
    entries   the settings on it (Entry), so the search finds each one
    docs      the manual page that explains it ("displays.md", a path in the manual)
    """
    id: str
    title: str
    build: Callable
    icon: str = "preferences-system-symbolic"
    order: int = 100
    summary: str = ""
    keywords: list = field(default_factory=list)
    refresh: Optional[Callable] = None
    group: str = ""
    intro: str = ""
    entries: list = field(default_factory=list)
    docs: str = ""
    source: str = ""            # the file it came from (set by discover)
    sections: list = field(default_factory=list)   # Sections other modules add (set by discover)

    @property
    def group_id(self):
        g = self.group or DEFAULT_GROUP.get(self.id, "desktop")
        return g if g in GROUP_IDS else "desktop"


@dataclass
class Section:
    """A group another module adds to a page: `build(ctx, page_box)` adds its groups to the
    page's box (`ctx.group(page_box, …)`), after the page's own.

    page        the page it goes on ("lab"); when no such page is installed, a page of
                that id is made for it (titled `page_title`, in `group`)
    id          its own id ("lab-models")
    title       what it's called (the search lists it)
    entries     its settings, for the search (Entry)
    """
    page: str
    id: str
    title: str
    build: Callable
    order: int = 100
    entries: list = field(default_factory=list)
    page_title: str = ""
    group: str = ""
    keywords: list = field(default_factory=list)
    source: str = ""


def page_dirs():
    """The page folders, in reading order."""
    home = os.path.expanduser("~")
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local/share")
    dirs = [os.path.join(HERE, "pages")]
    dirs += [d for d in os.environ.get("BROMIGOS_SETTINGS_PAGES", "").split(":") if d]
    dirs += [os.path.join(data, "bromigos/ext/active/settings"),
             os.path.join(config, "bromigos/plugins/settings")]
    return dirs


def _load(path, n):
    name = f"bromigos_settings_page_{n}_{os.path.splitext(os.path.basename(path))[0]}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _orphan_page(sec):
    """A page made for sections whose page isn't installed (the lab console's, say)."""
    def build(ctx):
        return ctx.page()
    return Page(id=sec.page, title=sec.page_title or sec.page.replace("-", " ").title(), build=build,
                group=sec.group or DEFAULT_GROUP.get(sec.page, "desktop"), order=500,
                summary=sec.title, icon="preferences-other-symbolic", source=sec.source)


def discover(dirs=None):
    """(pages, problems): the pages sorted, and [(file, message)] for what was skipped.
    Each page's `sections` holds the Sections other modules add to it."""
    found, sections, problems, n = {}, [], [], 0
    for d in dirs if dirs is not None else page_dirs():
        try:
            names = sorted(f for f in os.listdir(d) if f.endswith(".py") and not f.startswith("_"))
        except OSError:
            continue
        for f in names:
            path = os.path.join(d, f)
            n += 1
            try:
                mod = _load(path, n)
            except Exception:
                problems.append((path, traceback.format_exc(limit=3).strip().splitlines()[-1]))
                continue
            pages = getattr(mod, "PAGES", None) or ([mod.PAGE] if hasattr(mod, "PAGE") else [])
            secs = getattr(mod, "SECTIONS", None) or ([mod.SECTION] if hasattr(mod, "SECTION") else [])
            if not pages and not secs:
                problems.append((path, "defines no PAGE, PAGES, SECTION or SECTIONS"))
            for p in pages:
                if not isinstance(p, Page) or not p.id or not callable(p.build):
                    problems.append((path, f"not a Page: {p!r}"[:200]))
                    continue
                p.source = path
                p.sections = []
                found[p.id] = p
            for s in secs:
                if not isinstance(s, Section) or not s.page or not s.id or not callable(s.build):
                    problems.append((path, f"not a Section: {s!r}"[:200]))
                    continue
                s.source = path
                sections.append(s)
    seen = {}
    for s in sections:                      # a later section of the same id replaces an earlier one
        seen[(s.page, s.id)] = s
    for s in sorted(seen.values(), key=lambda s: (s.order, s.title.lower())):
        if s.page not in found:
            found[s.page] = _orphan_page(s)
        found[s.page].sections.append(s)
    return sort_pages(found.values()), problems


def sort_pages(pages):
    return sorted(pages, key=lambda p: (GROUP_IDS.index(p.group_id), p.order, p.title.lower()))
