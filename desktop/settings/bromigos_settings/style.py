"""The window in the theme's colours: libadwaita's colour variables set from the theme in
force (palette.json, through bromigos_theme), and the house style over its shapes:
square corners, 1px rules, Geist Mono, wide-tracked uppercase headings, glow only on what
is live. Rebuilt when the theme changes."""
import sys

sys.path.insert(0, "/usr/lib/bromigos/lib")
try:
    import bromigos_theme as T
except ImportError:              # no bromigos-core: the Wick's colours
    T = None

WICK = {
    "background": "#000500", "void": "#000500", "panel": "#001300", "selection": "#003b00",
    "primary": "#39ff14", "soft": "#9cff8a", "dim": "#159b09", "text": "#c4f5bb",
    "muted": "#7e927e", "faint": "#4e6b4e", "warn": "#d4af37", "danger": "#ff766f",
    "warn_surface": "#4a3a0a", "danger_surface": "#1a0503", "danger_text": "#ffd9d6",
    "cyan": "#3fe0c5", "gold": "#f0d36a", "white": "#e8ffe0",
}


def colors():
    """The theme's roles, resolved."""
    if T is None:
        return dict(WICK), "dark", "wick"
    T.version()
    c = dict(WICK)
    c.update(T.colors())
    return c, T._doc.get("mode", "dark"), T.name()


def version():
    return T.version() if T is not None else 0


def palette_path():
    """The palette.json a theme switch rewrites (watched for a restyle), or None."""
    return getattr(T, "PATH", None) if T is not None else None


def _rgba(h, a):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{a})"


def css(c):
    a = _rgba
    return f"""
:root {{
  --window-bg-color: {c['background']};
  --window-fg-color: {c['text']};
  --view-bg-color: {c['background']};
  --view-fg-color: {c['text']};
  --headerbar-bg-color: {c['panel']};
  --headerbar-fg-color: {c['soft']};
  --headerbar-border-color: {a(c['dim'], .55)};
  --headerbar-backdrop-color: {c['panel']};
  --headerbar-shade-color: {a(c['dim'], .35)};
  --sidebar-bg-color: {c['panel']};
  --sidebar-fg-color: {c['soft']};
  --sidebar-backdrop-color: {c['panel']};
  --sidebar-border-color: {a(c['dim'], .55)};
  --sidebar-shade-color: {a(c['dim'], .35)};
  --secondary-sidebar-bg-color: {c['panel']};
  --secondary-sidebar-fg-color: {c['soft']};
  --card-bg-color: {a(c['panel'], .85)};
  --card-fg-color: {c['text']};
  --card-shade-color: {a(c['dim'], .35)};
  --popover-bg-color: {c['void']};
  --popover-fg-color: {c['text']};
  --popover-shade-color: {a(c['dim'], .4)};
  --dialog-bg-color: {c['panel']};
  --dialog-fg-color: {c['text']};
  --thumbnail-bg-color: {c['panel']};
  --thumbnail-fg-color: {c['text']};
  --accent-bg-color: {c['primary']};
  --accent-fg-color: {c['void']};
  --accent-color: {c['primary']};
  --destructive-bg-color: {c['danger']};
  --destructive-fg-color: {c['void']};
  --destructive-color: {c['danger']};
  --success-bg-color: {c['primary']};
  --success-fg-color: {c['void']};
  --success-color: {c['primary']};
  --warning-bg-color: {c['warn']};
  --warning-fg-color: {c['void']};
  --warning-color: {c['warn']};
  --error-bg-color: {c['danger']};
  --error-fg-color: {c['void']};
  --error-color: {c['danger']};
  --border-color: {a(c['dim'], .5)};
  --shade-color: {a(c['void'], .5)};
  --window-radius: 0px;
}}

* {{ font-family: "Geist Mono", "MesloLGM Nerd Font Propo", monospace; }}
window, window.background {{ border-radius: 0; }}

/* square corners and 1px rules everywhere */
button, row, list, .boxed-list, .card, popover > contents, toast, entry, spinbutton,
switch, switch > slider, scale > trough, scale > trough > highlight, scale > trough > slider,
headerbar, banner > revealer > widget, toggle-group, toggle-group > toggle,
.navigation-sidebar > row, dropdown > button, tooltip {{ border-radius: 0; }}
.boxed-list, list.boxed-list {{ box-shadow: none; border: 1px solid {a(c['dim'], .45)}; }}
.boxed-list > row {{ border-bottom: 1px solid {a(c['dim'], .22)}; }}
headerbar {{ box-shadow: inset 0 -1px {a(c['dim'], .55)}; }}

/* headings: wide-tracked, the primary colour */
preferencesgroup > box > box > box > label.heading,
preferencesgroup .heading {{ color: {c['primary']}; letter-spacing: 0.16em; font-weight: 700; }}
preferencesgroup .description, row .subtitle {{ color: {c['muted']}; }}
headerbar .title {{ letter-spacing: 0.14em; font-weight: 700; color: {c['primary']}; }}

/* the sidebar */
.navigation-sidebar > row {{ padding: 6px 10px; margin: 1px 6px; }}
.navigation-sidebar > row:selected {{ background-color: {a(c['primary'], .13)};
  color: {c['primary']}; box-shadow: inset 2px 0 {c['primary']}; }}
.navigation-sidebar > row:hover:not(:selected) {{ background-color: {a(c['primary'], .06)}; }}
.navigation-sidebar .page-title {{ letter-spacing: 0.08em; font-weight: 600; }}
.navigation-sidebar .page-summary {{ color: {c['muted']}; font-size: 0.85em; }}

/* controls */
switch {{ border: 1px solid {a(c['dim'], .7)}; background-color: {a(c['dim'], .25)}; }}
switch:checked {{ background-color: {c['primary']}; border-color: {c['primary']}; }}
switch > slider {{ background-color: {c['muted']}; box-shadow: none; }}
switch:checked > slider {{ background-color: {c['void']}; }}
scale > trough {{ background-color: {a(c['dim'], .35)}; min-height: 3px; }}
scale > trough > highlight {{ background-color: {c['primary']}; }}
scale > trough > slider {{ background-color: {c['primary']}; border: 1px solid {c['void']};
  min-width: 10px; min-height: 16px; margin: -7px -3px; box-shadow: 0 0 6px {a(c['primary'], .5)}; }}
scale:disabled > trough > highlight, scale:disabled > trough > slider {{ background-color: {c['faint']}; box-shadow: none; }}
scale marks label {{ color: {c['muted']}; font-size: 0.8em; }}
button {{ border: 1px solid {a(c['dim'], .6)}; background-color: {a(c['panel'], .6)}; color: {c['soft']}; }}
button:hover {{ background-color: {a(c['primary'], .12)}; color: {c['primary']}; }}
button.suggested-action {{ background-color: {c['primary']}; color: {c['void']}; border-color: {c['primary']}; }}
button.destructive-action {{ background-color: transparent; color: {c['danger']}; border-color: {a(c['danger'], .6)}; }}
button.suggested-action:disabled {{ background-color: transparent; color: {c['faint']}; border-color: {a(c['dim'], .4)}; }}
/* dialogs: square, like everything else */
dialog.alert .dialog-contents, dialog > sheet, floating-sheet > sheet, dialog.alert > sheet {{ border-radius: 0; }}
headerbar button {{ border: none; background: none; }}
toggle-group {{ border: 1px solid {a(c['dim'], .6)}; background-color: {a(c['panel'], .6)}; padding: 0; }}
toggle-group > toggle {{ padding: 6px 14px; letter-spacing: 0.06em; }}
toggle-group > toggle:checked {{ background-color: {a(c['primary'], .16)}; color: {c['primary']};
  box-shadow: inset 0 -2px {c['primary']}; }}
tooltip {{ background-color: {c['void']}; border: 1px solid {c['dim']}; color: {c['soft']}; }}
toast {{ background-color: {c['void']}; border: 1px solid {c['primary']}; color: {c['soft']}; }}
toast button {{ color: {c['primary']}; }}

/* the live summary: what the desktop will do, in plain words */
.bromigos-summary {{ font-size: 1.25em; font-weight: 600; color: {c['primary']};
  text-shadow: 0 0 6px {a(c['primary'], .28)}; }}
.bromigos-state {{ color: {c['soft']}; letter-spacing: 0.04em; }}
.bromigos-value {{ color: {c['soft']}; font-weight: 600; min-width: 5.5em; }}
.bromigos-value.off {{ color: {c['faint']}; }}
row.bromigos-warn {{ background-color: {a(c['warn_surface'], .55)}; }}
row.bromigos-warn image {{ color: {c['warn']}; }}
row.bromigos-warn .title {{ color: {c['warn']}; }}
row.bromigos-note image {{ color: {c['cyan']}; }}
row.bromigos-note .title {{ color: {c['soft']}; }}
row.bromigos-error {{ background-color: {a(c['danger_surface'], .8)}; }}
row.bromigos-error image, row.bromigos-error .title {{ color: {c['danger']}; }}
.bromigos-awake {{ color: {c['warn']}; font-weight: 700; letter-spacing: 0.06em; }}
.bromigos-swatch {{ min-width: 26px; min-height: 26px; border: 1px solid {a(c['dim'], .7)}; }}
.bromigos-placeholder .description {{ color: {c['muted']}; }}

/* the page's header: its title, what it's for, Reset to defaults */
.bromigos-page-header {{ padding-bottom: 6px; border-bottom: 1px solid {a(c['dim'], .35)}; }}
.bromigos-page-title {{ font-size: 1.45em; font-weight: 700; letter-spacing: 0.14em; color: {c['primary']};
  text-shadow: 0 0 8px {a(c['primary'], .25)}; }}
.bromigos-page-intro {{ color: {c['muted']}; }}
button.bromigos-reset {{ font-size: 0.9em; padding: 4px 12px; }}
button.bromigos-reset:disabled {{ color: {c['faint']}; border-color: {a(c['dim'], .3)}; background: none; }}

/* the sidebar's groups and the search's results */
.bromigos-group-title {{ color: {c['dim']}; font-size: 0.78em; font-weight: 700; letter-spacing: 0.2em;
  margin: 14px 18px 4px 18px; }}
.bromigos-results > row .page-summary {{ color: {c['faint']}; }}

/* a row's Advanced disclosure: what it writes and runs */
button.bromigos-adv-toggle {{ border: none; background: none; color: {c['faint']}; min-width: 24px; padding: 2px; }}
button.bromigos-adv-toggle:hover, button.bromigos-adv-toggle:checked {{ color: {c['primary']}; background: none; }}
row.bromigos-advanced {{ background-color: {a(c['void'], .55)}; }}
row.bromigos-advanced .title {{ font-size: 0.82em; color: {c['muted']}; }}
row.bromigos-loading .title {{ color: {c['muted']}; }}

/* a search result's row, found: lit for a moment */
.bromigos-found {{ box-shadow: inset 3px 0 {c['primary']}, inset 0 0 0 1px {a(c['primary'], .7)};
  background-color: {a(c['primary'], .10)}; }}

/* narrow windows: tighter margins */
window.narrow .bromigos-page > viewport > clamp > box {{ margin-left: 10px; margin-right: 10px; }}
window.narrow .bromigos-page-title {{ font-size: 1.2em; }}
"""
