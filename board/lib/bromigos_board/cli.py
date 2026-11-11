"""bromigos-board's commands. People reach the two of theirs as `bromigos server board code` and
`bromigos server board sessions`; systemd runs `serve` and `snapshot`."""
import argparse
import datetime
import json
import os
import pwd
import sys

from . import SCHEMA, auth, paths

USAGE = """\
bromigos server board code [--json]
    a one-time code to sign a browser in to the Lab board: type it on the board's page within
    10 minutes. It works once. Needs root
bromigos server board sessions [--end ID | --end-all] [--json]
    the browsers signed in to the board, newest first; --end signs one out, --end-all every one.
    Needs root

systemd runs these two (bromigos-board.service, bromigos-board-snapshot.service):
bromigos-board serve        the API on the socket systemd hands it (bromigos-board.socket)
bromigos-board snapshot [--once]
                            read the server and write /run/bromigos-board/board.json every 15
                            seconds while a browser is connected; --once: one reading
"""

EXIT_OK, EXIT_PROBLEM, EXIT_USAGE, EXIT_CANT = 0, 1, 2, 3


def when(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).astimezone().strftime("%Y-%m-%d %H:%M")


def needs_root():
    if not paths.stand_in() and not paths.really_root():
        print("bromigos-board: this needs root: sudo bromigos server board …", file=sys.stderr)
        return True
    return False


def become_board_user():
    """Root, about to work in the board's own folder: become the board's user for good first
    (no extra groups, its group, its user), so nothing here is done as root on a path that user
    controls. In a stand-in root, and when already that user, there's nothing to do."""
    if not paths.really_root():
        return
    pw = pwd.getpwnam(paths.USER)
    os.setgroups([])
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    os.umask(0o077)
    os.environ["HOME"] = pw.pw_dir


def as_board_user():
    """needs_root, then become_board_user. An exit status when it can't, else None."""
    if needs_root():
        return EXIT_CANT
    try:
        become_board_user()
    except KeyError:
        print(f"bromigos-board: there's no user {paths.USER} here: the bromigos-board package makes it "
              "(systemd-sysusers)", file=sys.stderr)
        return EXIT_CANT
    return None


def own_folders():
    """Both of the board's folders are folders of their own (made when missing); OSError when one
    is a link or something else."""
    for d in (paths.SESSIONS, paths.CODES):
        with auth.folder(d):
            pass


def folder_trouble(e):
    print(f"bromigos-board: {e}. The board keeps its sign-in codes and sessions in {paths.STATE}, in folders of "
          "its own; something else is in their place. Nothing was changed.", file=sys.stderr)
    return EXIT_CANT


def cmd_code(a):
    stop = as_board_user()
    if stop is not None:
        return stop
    try:
        own_folders()
        code, exp = auth.new_code()
    except OSError as e:
        return folder_trouble(e)
    if a.json:
        print(json.dumps({"schema": SCHEMA, "code": code, "expires_at": exp}, indent=1))
        return EXIT_OK
    print(f"Sign-in code for the Lab board:  {code}\n")
    print(f"Open https://{paths.hostname()}.local on your home network and type it in.")
    print(f"It works once, until {when(exp)} (10 minutes). Another code doesn't cancel this one.")
    return EXIT_OK


def cmd_sessions(a):
    stop = as_board_user()
    if stop is not None:
        return stop
    try:
        own_folders()
    except OSError as e:
        return folder_trouble(e)
    if a.end_all:
        n = auth.end_all()
        print(json.dumps({"schema": SCHEMA, "ended": n}) if a.json else
              f"Signed out {n} browser{'s' if n != 1 else ''}." if n else "No browser was signed in.")
        return EXIT_OK
    if a.end:
        ok = auth.end_session(a.end)
        if a.json:
            print(json.dumps({"schema": SCHEMA, "ended": a.end if ok else None}))
        else:
            print(f"Signed out {a.end}." if ok else f"No browser is signed in as {a.end!r}: bromigos server board sessions lists them.",
                  file=sys.stdout if ok else sys.stderr)
        return EXIT_OK if ok else EXIT_PROBLEM
    auth.prune()
    rows = auth.sessions()
    if a.json:
        print(json.dumps({"schema": SCHEMA, "sessions": rows, "codes_waiting": len(auth.codes_waiting())}, indent=1))
        return EXIT_OK
    if not rows:
        print("No browser is signed in to the Lab board.")
    else:
        print(f"{'ID':<17} {'BROWSER':<24} {'SIGNED IN':<17} {'LAST SEEN':<17} UNTIL")
        for r in rows:
            print(f"{r['id']:<17} {r['browser'][:24]:<24} {when(r['created_at']):<17} {when(r['last_seen_at']):<17} "
                  f"{when(r['expires_at'])}")
        print("\nTo sign one out: sudo bromigos server board sessions --end ID")
    waiting = auth.codes_waiting()
    if waiting:
        print(f"{len(waiting)} sign-in code{'s' if len(waiting) != 1 else ''} not used yet (good until {when(waiting[-1])}).")
    return EXIT_OK


def cmd_snapshot(a):
    from . import snapshot
    return snapshot.run(once=a.once)


def cmd_serve(a):
    import uvicorn
    from . import api
    fd = int(os.environ.get("LISTEN_FDS_FIRST_FD", "3"))
    if os.environ.get("LISTEN_FDS") != "1":
        print("bromigos-board: serve runs from bromigos-board.socket (systemd hands it the socket)", file=sys.stderr)
        return EXIT_CANT
    # limit_concurrency: more connections than this at once get 503 (the board is one household's page)
    uvicorn.run(api.make_app(), fd=fd, proxy_headers=False, server_header=False, date_header=False,
                access_log=False, log_level="warning", lifespan="off", limit_concurrency=api.CONNECTIONS_MAX,
                timeout_keep_alive=15)
    return EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bromigos-board", description="The Lab board's server side (docs/board.md)",
                                 usage=USAGE, add_help=True)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("code")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("sessions")
    p.add_argument("--end", metavar="ID")
    p.add_argument("--end-all", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("snapshot")
    p.add_argument("--once", action="store_true")
    sub.add_parser("serve")
    a = ap.parse_args(argv)
    if not a.cmd:
        print(USAGE, end="")
        return EXIT_USAGE
    return {"code": cmd_code, "sessions": cmd_sessions, "snapshot": cmd_snapshot, "serve": cmd_serve}[a.cmd](a)
