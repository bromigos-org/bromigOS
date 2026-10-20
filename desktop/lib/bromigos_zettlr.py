"""Zettlr in the theme's colours (docs/theming.md, "Zettlr").

`bromigos theme set` renders `zettlr.css` from the palette (theme/templates/zettlr.css.tpl).
The theme-set hook `zettlr` runs this file with the rendered theme's folder. It changes
two things in Zettlr's settings folder (~/.config/Zettlr, Electron's userData), and
nothing else:

- custom.css: the rendered colours go between the bromigOS markers. Everything outside
  the markers is the user's and stays as it is. With no markers yet, the block goes at
  the top, after any @charset and @import lines (CSS needs those first), so the user's
  own rules come after it.
- config.json: `darkMode` is set to the theme's mode. Only when the file exists (a missing
  one means Zettlr hasn't run: its first-start setup must still happen) and Zettlr isn't
  running (it keeps its settings in memory and writes them back over ours).

Zettlr reads custom.css when it starts, so a running Zettlr takes the colours when it's
next opened.

    python3 bromigos_zettlr.py THEME_DIR [ZETTLR_DIR]
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

BEGIN = "/* >>> bromigOS theme: written by `bromigos theme set`. Edits inside this block are replaced; put your own rules after it. */"
END = "/* <<< bromigOS theme */"
# What Zettlr writes into a new custom.css (source/app/service-providers/css/index.ts)
ZETTLR_START = "/* Enter your custom CSS here */\n"
# A leading statement that must stay before any rule: @charset, @import, @layer a, b;
STATEMENT = re.compile(r"@(?:charset|import|layer)\b[^;{]*;")
LEADING = re.compile(r"\A(?:\s|/\*.*?\*/|" + STATEMENT.pattern + ")*", re.S)


def block(css):
    return f"{BEGIN}\n{css.strip()}\n{END}\n"


def merge(existing, css):
    """custom.css with the bromigOS block set to `css`; the rest of `existing` unchanged.

    Raises ValueError when the file has only one of the two markers, or them out of order:
    then which part is the user's isn't clear, so nothing is written."""
    new = block(css)
    if existing is None or not existing.strip():
        return new + "\n" + ZETTLR_START
    b, e = existing.find(BEGIN), existing.find(END)
    if b == -1 and e == -1:
        cut = 0
        for m in STATEMENT.finditer(LEADING.match(existing).group(0)):
            cut = m.end()
        head, rest = existing[:cut], existing[cut:].lstrip("\n")
        return (head + "\n" if head else "") + new + ("\n" + rest if rest else "")
    if b == -1 or e == -1 or e < b or existing.count(BEGIN) > 1 or existing.count(END) > 1:
        raise ValueError("custom.css has an incomplete bromigOS block: fix or remove its markers")
    after = existing[e + len(END):]
    if after.startswith("\n"):
        after = after[1:]
    return existing[:b] + new + after


def atomic_write(path, text):
    """Replaces the file in one step. A link (a dotfiles checkout, say) stays a link: the
    file it points at is the one replaced."""
    path = Path(path)
    if path.is_symlink():
        path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def zettlr_running():
    """A Zettlr of this user's running (the packaged one runs `electron… /usr/lib/zettlr/app.asar`;
    an AppImage or a Flatpak runs a `zettlr` binary). BROMIGOS_ZETTLR_RUNNING=0 or 1 answers
    instead, for tests."""
    forced = os.environ.get("BROMIGOS_ZETTLR_RUNNING")
    if forced in ("0", "1"):
        return forced == "1"
    uid = os.getuid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                args = f.read().split(b"\0")
        except OSError:
            continue
        if not args or not args[0]:
            continue
        if os.path.basename(args[0]).lower() == b"zettlr" or any(a.endswith(b"zettlr/app.asar") for a in args[1:3]):
            return True
    return False


def set_dark_mode(config_path, dark, running=None):
    """Sets config.json's darkMode. Returns what happened: set, unchanged, absent, running, unreadable."""
    path = Path(config_path)
    if not path.is_file():
        return "absent"
    if running if running is not None else zettlr_running():
        return "running"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    if not isinstance(data, dict):
        return "unreadable"
    if data.get("darkMode") is dark:
        return "unchanged"
    data["darkMode"] = dark
    # as Zettlr writes it: JSON.stringify(data, undefined, '  ')
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))
    return "set"


def zettlr_dirs():
    """Zettlr's settings folders: the package's, and the Flatpak's when it's there. The
    package's is made when Zettlr is installed but hasn't run yet, so its first start is
    already in the theme's colours."""
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    out = []
    native = config / "Zettlr"
    if native.is_dir() or shutil.which("zettlr"):
        out.append(native)
    flatpak = home / ".var/app/com.zettlr.Zettlr/config/Zettlr"
    if flatpak.is_dir():
        out.append(flatpak)
    return out


def update(theme_dir, zdir, running=None):
    """Writes the theme's colours into one Zettlr settings folder. Returns (css, mode) results."""
    theme_dir, zdir = Path(theme_dir), Path(zdir)
    css = (theme_dir / "zettlr.css").read_text(encoding="utf-8")
    try:
        mode = json.loads((theme_dir / "palette.json").read_text(encoding="utf-8")).get("mode", "dark")
    except (OSError, ValueError):
        mode = "dark"
    target = zdir / "custom.css"
    existing = target.read_text(encoding="utf-8") if target.exists() else None
    text = merge(existing, css)
    if text != existing:
        atomic_write(target, text)
    return ("written" if text != existing else "unchanged",
            set_dark_mode(zdir / "config.json", mode != "light", running))


def main(argv):
    if not argv or len(argv) > 2:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    theme_dir = Path(argv[0])
    if not (theme_dir / "zettlr.css").is_file():
        return 0  # a theme rendered before Zettlr had a template
    dirs = [Path(argv[1])] if len(argv) == 2 else zettlr_dirs()
    status = 0
    for zdir in dirs:
        try:
            update(theme_dir, zdir)
        except (OSError, ValueError) as e:
            print(f"zettlr: {zdir}: {e}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
