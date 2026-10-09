"""bromigos-live: the animated, data-reactive live layer for the Hyprland desktop.

Where things are (docs/plugins.md):
  LIB       the shared Python libs (bromigos_theme, bromigos_private): /usr/lib/bromigos/lib
            installed, lib/ in a bromigOS checkout, ~/.config/bromigos/lib in the dotfiles
  PLUGINS   personal plugin folders. Their Python modules join this package (they are
            imported as live.<name>, so their relative imports work), which is how a deck
            that isn't part of bromigOS is added: <kind>_deck.py defining DECK, opened with
            `bromigos-live deck <kind>`. Shader layers go in <folder>/layers/.
            $BROMIGOS_LIVE_PLUGINS (colon-separated) or ~/.config/bromigos/plugins/live.
  HOMELAB   bromigOS's homelab integrations (bromigos-homelab: docs/homelab.md):
            /usr/lib/bromigos/homelab, homelab/ in a bromigOS checkout, or $BROMIGOS_HOMELAB.
            Its decks (Ops, Netmap, Mind) join this package after bromigOS's own modules
            and before the user's; its data module is bromigos_homelab (live.homelab.H).
            None without it: the lab's readings, decks and signals step aside.
  VECTOR    VECTOR's tree, for the codec's voice, the shared model reader and asking him:
            /usr/lib/bromigos/vector (bromigos-vector) or the dotfiles' ~/.config/bromigos/holo,
            or $BROMIGOS_VECTOR; None without VECTOR (those features step aside).
"""
import os
import sys

_HOME = os.path.expanduser("~")
_CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(_HOME, ".config")
_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))   # live/ (code, shaders, sounds)


def _first_dir(*cands):
    return next((c for c in cands if c and os.path.isdir(c)), None)


LIB = _first_dir(os.environ.get("BROMIGOS_PYLIB"),
                 os.path.join(os.path.dirname(_ROOT), "lib"),          # /usr/lib/bromigos/lib, <checkout>/lib
                 os.path.join(_CONFIG, "bromigos", "lib"))             # the dotfiles
if LIB and LIB not in sys.path:
    sys.path.insert(0, LIB)

VECTOR = _first_dir(os.environ.get("BROMIGOS_VECTOR"), "/usr/lib/bromigos/vector",
                    os.path.join(_CONFIG, "bromigos", "holo"))
VECTOR_CMD = next((c for c in ("/usr/bin/bromigos-holo", os.path.join(VECTOR or "", "bin", "bromigos-holo"))
                   if VECTOR and os.path.isfile(c)), None)

HOMELAB = _first_dir(os.environ.get("BROMIGOS_HOMELAB"), "/usr/lib/bromigos/homelab",
                     os.path.join(os.path.dirname(_ROOT), "homelab"))   # a bromigOS checkout
if HOMELAB and os.path.isdir(os.path.join(HOMELAB, "lib")) and os.path.join(HOMELAB, "lib") not in sys.path:
    sys.path.insert(1, os.path.join(HOMELAB, "lib"))                    # a checkout keeps its lib beside it

PLUGINS = [d for d in (os.environ.get("BROMIGOS_LIVE_PLUGINS") or
                       os.path.join(_CONFIG, "bromigos", "plugins", "live")).split(":") if d]
# installed extensions' decks and layers (`bromigos ext`; docs/extensions.md), after the user's
EXT = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                   "bromigos", "ext", "active", "live")
PLUGINS.append(EXT)
# bromigOS's own modules first: a plugin can add modules, never replace one
# then the homelab's decks, then the user's
__path__ += [d for d in ([os.path.join(HOMELAB, "live")] if HOMELAB else []) + PLUGINS  # noqa: F821
             if os.path.isdir(d) and d not in __path__]  # noqa: F821
