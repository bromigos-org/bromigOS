"""Den TV controls for the terminal and AI callers; the daemon owns their state."""
import argparse
import json
import os
import re
import tomllib
import sys

from bromigos_tvchannels import ChannelError, control
from bromigos_tvplay import screen_name

ACTIONS = ("volume-up", "volume-down", "channel-up", "channel-down", "mute", "skip", "previous",
           "open", "sound", "guide", "digits", "leave", "cancel") + tuple(f"digit-{n}" for n in range(10))


def set_hint(on):
    import bromigos_cli as C
    root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(root, "bromigos", "live", "overrides.toml")
    text = C.read_file(path) or ""
    lines = text.splitlines(keepends=True)
    section = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("["):
            section = "tv" if re.match(r"^\s*\[tv\]\s*(?:#.*)?$", line.strip()) else None
        if section == "tv":
            match = re.match(r"^(\s*hover_hint\s*=\s*)(?:true|false)([^\n]*)(\n?)$", line)
            if match:
                lines[i] = match[1] + ("true" if on else "false") + match[2] + match[3]
                text = "".join(lines)
                break
    else:
        text = C.toml_set(text, "tv", "hover_hint", bool(on))
    tomllib.loads(text)
    C.write_file(path, text)
    control("reload")
    return dict(ok=True, hover_hint=bool(on), message="TV hover hint " + ("on" if on else "off"))


def select(screen):
    screen = "none" if screen == "none" else screen_name(screen)
    return send("select " + screen)


def remote(action, screen=None):
    if action not in ACTIONS:
        raise ChannelError("Unknown TV remote action", 2)
    return send("remote " + action + (" --screen " + screen_name(screen) if screen else ""))


def send(command):
    answer = control("tv " + command)
    if not answer:
        raise ChannelError("The live layer is not running", 3)
    if answer.startswith(("no den TV", "Den TV is off", "Select a TV first", "Unknown TV remote", "No channel")):
        raise ChannelError(answer, 4)
    return dict(ok=True, message=answer)


def main(argv=None):
    p = argparse.ArgumentParser(description="Control the den TV and its number-pad remote")
    subs = p.add_subparsers(dest="verb", required=True)
    hint = subs.add_parser("hint"); hint.add_argument("value", choices=("on", "off"))
    sel = subs.add_parser("select"); sel.add_argument("value", choices=("big", "wave", "scope", "emblem", "small", "none"))
    rem = subs.add_parser("remote"); rem.add_argument("value", choices=ACTIONS); rem.add_argument("--screen")
    for parser in (hint, sel, rem): parser.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = set_hint(args.value == "on") if args.verb == "hint" else \
            (select(args.value) if args.verb == "select" else remote(args.value, args.screen))
        print(json.dumps(result) if args.json else result["message"]); return 0
    except (ChannelError, ValueError, OSError) as e:
        print(json.dumps(dict(ok=False, error=str(e))) if args.json else str(e)); return getattr(e, "code", 1)


if __name__ == "__main__": sys.exit(main())
