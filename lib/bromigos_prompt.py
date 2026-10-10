"""Generate mehshell's theme colours without replacing the user's other options."""
import json
import os
from pathlib import Path
import re
import tempfile

ROLES = {75: "dim", 39: "primary", 170: "terminal.color6", 76: "primary",
         196: "danger", 220: "warn", 208: "terminal.color11", 242: "muted",
         246: "faint", 238: "selection"}
# Rainbow backgrounds use the same terminal hues as the matching segments.
ROLES.update({24: "selection", 31: "primary", 97: "terminal.color6", 34: "primary",
              136: "warn", 37: "terminal.color6", 130: "terminal.color11", 124: "danger",
              94: "warn", 25: "terminal.color4", 57: "terminal.color5", 166: "terminal.color11",
              22: "primary", 0: "background", 255: "text"})
BEGIN = "# >>> bromigOS theme colours"
END = "# <<< bromigOS theme colours"


def generate(palette):
    colours = palette["colors"]
    tables = palette["tables"]
    lines = [BEGIN]
    for index, role in sorted(ROLES.items()):
        if "." in role:
            table, key = role.split(".")
            colour = tables[table][key]
        else:
            colour = colours[role]
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
            raise ValueError(f"Invalid colour for {role}")
        lines.append(f"color_{index} = {colour}")
    return "\n".join(lines + [END, ""])


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".prompt-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def update(palette_path=None, config_path=None):
    home = Path.home()
    state = Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state")
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    palette_path = Path(palette_path or state / "bromigos/theme/current/palette.json")
    config_path = Path(config_path or config / "mehshell/config")
    if not palette_path.is_file():
        return False
    block = generate(json.loads(palette_path.read_text()))
    text = config_path.read_text() if config_path.exists() else "# mehshell options: see mehshell config init\n"
    if (BEGIN in text) != (END in text):
        raise ValueError("Incomplete bromigOS theme colours block")
    if BEGIN in text:
        text = text[:text.index(BEGIN)] + block + text[text.index(END)+len(END):].lstrip("\n")
    else:
        text = text.rstrip("\n") + "\n\n" + block
    atomic_write(config_path, text)
    # Cached prompts must never bring back colours from the previous theme.
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    (cache / "mehshell-prompt-cache").unlink(missing_ok=True)
    return True
