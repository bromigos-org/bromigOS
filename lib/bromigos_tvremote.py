"""Den TV controls for the terminal and AI callers; the daemon owns their state."""
import argparse
import json
import os
import re
import tomllib
import sys

from bromigos_tvchannels import ChannelError, control, live_state
from bromigos_tvplay import json_args, screen_name

SOUND = re.compile(r"^(\w+): sound (on|off), volume (\d+)%")

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


def _screen_arg(screen):
    return " --screen " + screen_name(screen) if screen else ""


def _sound_result(answer):
    m = SOUND.match(answer or "")
    if not m:
        raise ChannelError(answer or "The live layer is not running", 4 if answer else 3)
    return dict(ok=True, screen=m[1], sound=m[2] == "on", volume=int(m[3]), message=answer)


def volume(value, screen=None):
    """A level from 0 to 100, or up/down by 5, the same path as the knobs and the remote."""
    value = str(value)
    if value not in ("up", "down") and not (value.isdigit() and 0 <= int(value) <= 100):
        raise ChannelError("Volume: up, down or a level from 0 to 100", 2)
    return _sound_result(send("volume " + value + _screen_arg(screen))["message"])


def sound(value, screen=None):
    if value not in ("on", "off", "toggle"):
        raise ChannelError("Sound: on, off or toggle", 2)
    return _sound_result(send("sound " + value + _screen_arg(screen))["message"])


def close(screen=None):
    """Back to the den: the full-screen player closes."""
    result = send("close" + _screen_arg(screen))
    return dict(result, screen=screen_name(screen) if screen else None)


def back_to_channel(screen=None):
    """The screen's channel again, after something played on demand."""
    result = send("live" + _screen_arg(screen))
    return dict(result, screen=screen_name(screen) if screen else None)


def poster(screen=None, next_=False, size=160, id_=None, source=None):
    """The poster of what's on a screen (or next on it), or of one item by --id."""
    from bromigos_tvplay import poster as fetch, resolve
    if id_:
        item, screen = resolve(id_=id_, source=source), None
    else:
        state = live_state()
        if not state:
            raise ChannelError("The live layer is not running", 3)
        name = screen_name(screen or "big")
        row = (state.get("screens") or {}).get(name) or {}
        item = row.get("next_item" if next_ else "item")
        source = source or row.get("source")
        screen = name
    return dict(fetch(item, size, source), ok=True, screen=screen)


def send(command):
    answer = control("tv " + command)
    if not answer:
        raise ChannelError("The live layer is not running", 3)
    if answer.startswith(("no den TV", "Den TV is off", "Select a TV first", "Unknown TV remote", "No channel",
                          "no screen called", "bromigos-live tv")):
        raise ChannelError(answer, 4)
    return dict(ok=True, message=answer)


def main(argv=None):
    p = argparse.ArgumentParser(description="Control the den TV and its number-pad remote")
    subs = p.add_subparsers(dest="verb", required=True)
    hint = subs.add_parser("hint"); hint.add_argument("value", choices=("on", "off"))
    sel = subs.add_parser("select"); sel.add_argument("value", choices=("big", "wave", "scope", "emblem", "small", "none"))
    rem = subs.add_parser("remote"); rem.add_argument("value", choices=ACTIONS); rem.add_argument("--screen")
    vol = subs.add_parser("volume", help="up, down or a level from 0 to 100"); vol.add_argument("value")
    snd = subs.add_parser("sound", help="the screen's sound"); snd.add_argument("value", choices=("on", "off", "toggle"))
    cls = subs.add_parser("close", help="back to the den: close the full-screen player")
    liv = subs.add_parser("live", help="back to the channel after something played on demand")
    pos = subs.add_parser("poster", help="the poster of what's on, as a small base64 JPEG")
    pos.add_argument("--next", action="store_true", help="what's on next instead")
    pos.add_argument("--size", type=int, default=160, help="the longest side in pixels (at most 320)")
    pos.add_argument("--id"); pos.add_argument("--source")
    for parser in (vol, snd, cls, liv, pos): parser.add_argument("--screen")
    for parser in (hint, sel, rem, vol, snd, cls, liv, pos): parser.add_argument("--json", action="store_true")
    try:
        args = json_args(p, argv)
    except SystemExit as e:
        return e.code
    try:
        if args.verb == "hint": result = set_hint(args.value == "on")
        elif args.verb == "select": result = select(args.value)
        elif args.verb == "remote": result = remote(args.value, args.screen)
        elif args.verb == "volume": result = volume(args.value, args.screen)
        elif args.verb == "sound": result = sound(args.value, args.screen)
        elif args.verb == "close": result = close(args.screen)
        elif args.verb == "live": result = back_to_channel(args.screen)
        else: result = poster(args.screen, args.next, args.size, args.id, args.source)
        print(json.dumps(result) if args.json else result.get("message") or f"{result.get('w')}x{result.get('h')} JPEG")
        return 0
    except (ChannelError, ValueError, OSError) as e:
        print(json.dumps(dict(ok=False, error=str(e), code=getattr(e, "code", 1))) if args.json else str(e))
        return getattr(e, "code", 1)


if __name__ == "__main__": sys.exit(main())
