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

systemd runs these (bromigos-board.service, bromigos-board-snapshot.service, bromigos-board-act.service):
bromigos-board serve        the API on the socket systemd hands it (bromigos-board.socket)
bromigos-board snapshot [--once]
                            read the server and write /run/bromigos-board/board.json every 15
                            seconds while a browser is connected; --once: one reading
bromigos-board act [ID]     (root, bromigos-board-act.service) take the page's requests out of
                            their folder, check each again and start its job; ID: that one only
bromigos-board keep-actions FILE
                            (root, the package's upgrade) a server with no [board] actions keeps
                            what the board could do before: the list in FILE (JSON), written in
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
    if needs_root():
        return EXIT_CANT
    # root's own note of the code first, in a folder only root reads: without it no code can
    # approve deleting an app's data (actions.use_delete_code). Then root steps down
    from . import actions
    now, code = paths.now_ms(), auth.fresh_code()
    try:
        actions.note_code(code, now + auth.CODE_MS, now)
    except OSError as e:
        print(f"bromigos-board: root's note of the code couldn't be written ({e}): no code was made", file=sys.stderr)
        return EXIT_CANT
    stop = as_board_user()
    if stop is not None:
        return stop
    try:
        own_folders()
        code, exp = auth.new_code(now, code)
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


def cmd_act(a):
    """Root, from bromigos-board-act.service (started by bromigos-board-act.path when the requests
    folder isn't empty): take every request out of the folder, check each again and start its
    job. With an ID, that one request only.

    It ends 0 once the answers are written, a refusal included: the refusal is the answer, and a
    unit that failed for each one would stay failed (the Server's update check counts failed
    units)."""
    if needs_root():
        return EXIT_CANT
    from . import actions
    try:
        if a.id:
            out = actions.act(a.id)
            print(out["words"], file=sys.stdout if out["ok"] else sys.stderr)
        else:
            n = actions.drain()
            print(f"bromigos-board: {n} request{'s' if n != 1 else ''} handled", file=sys.stderr)
    except Exception as e:              # nothing a request holds may fail root's unit
        print(f"bromigos-board: the helper stopped early: {type(e).__name__}: {e}", file=sys.stderr)
    return EXIT_OK


def cmd_activity_folder(a):
    """Root, before the helper's sandbox is put up (the unit's ExecStartPre=+): make sure the
    activity records' folder is there, where bromigos-core puts it, so the sandbox can be given
    that folder and no more."""
    if needs_root():
        return EXIT_CANT
    try:
        import bromigos_activity
        os.umask(0o022)             # the records, and the folders they're in, are for everyone to read
        bromigos_activity.Env().ensure_dir()
    except Exception as e:
        print(f"bromigos-board: the activity folder couldn't be made: {e}", file=sys.stderr)
    return EXIT_OK


def keep_actions(was):
    """On an upgrade: a server whose server.toml doesn't say `[board] actions` gets the list the
    board allowed before the upgrade written in, so the browsers already signed in can't do more
    than they could. Nothing changes when the file says, when the old list is the new one, or
    when the server has no server.toml. The words it wrote, or None."""
    import tomllib
    from . import actions
    was = [w for w in was if w in actions.DEFAULT_ACTIONS] if isinstance(was, list) else []
    path = paths.at(paths.SERVER_TOML)
    try:
        with open(path, "rb") as f:
            text = f.read().decode()
        doc = tomllib.loads(text)
    except (OSError, ValueError):
        return None                        # no settings to keep, or ones this can't read: left alone
    board = doc.get("board")
    if (isinstance(board, dict) and "actions" in board) or was == list(actions.DEFAULT_ACTIONS):
        return None
    line = "actions = [" + ", ".join(json.dumps(w) for w in was) + "]"
    note = ("# what the board's page may do: kept as it was before an upgrade gave the board more "
            "(docs/board.md, \"What a session can do\")")
    lines = text.splitlines()
    at = next((i for i, x in enumerate(lines) if x.strip() == "[board]"), None)
    if at is None:
        lines += ([""] if lines and lines[-1].strip() else []) + ["[board]", note, line]
    else:
        lines[at + 1:at + 1] = [note, line]
    st = os.stat(path)
    tmp = f"{path}.bromigos-board.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, st.st_mode & 0o7777)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return line


def cmd_keep_actions(a):
    if needs_root():
        return EXIT_CANT
    try:
        with open(a.file) as f:
            was = json.load(f)
    except (OSError, ValueError):
        was = []                           # unreadable: the narrowest, nothing
    line = keep_actions(was)
    if line:
        print(f"bromigos-board: kept what the board's page could do before this upgrade, in {paths.SERVER_TOML}: "
              f"[board] {line}. The new default is wider; to have it, remove that line.")
    return EXIT_OK


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
    p = sub.add_parser("act")
    p.add_argument("id", nargs="?")
    sub.add_parser("activity-folder")
    p = sub.add_parser("keep-actions")
    p.add_argument("file")
    a = ap.parse_args(argv)
    if not a.cmd:
        print(USAGE, end="")
        return EXIT_USAGE
    return {"code": cmd_code, "sessions": cmd_sessions, "snapshot": cmd_snapshot, "serve": cmd_serve,
            "act": cmd_act, "activity-folder": cmd_activity_folder, "keep-actions": cmd_keep_actions}[a.cmd](a)
