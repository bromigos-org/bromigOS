"""One live daemon per user, and stopping exactly that one (bin/bromigos-live).

The daemon holds an exclusive lock on `$XDG_RUNTIME_DIR/bromigos-live.lock` for its whole
life, with `PID START` in it (START: the process's start time, field 22 of
/proc/PID/stat); a second daemon finds the lock held and exits with code 4, so two never
draw at once. The supervisor's PID file (`bromigos-live.pid`) holds `PID START` too.

`stop` stops exactly those processes, by PID checked against the recorded start time (a
PID the kernel has given to another process is never signalled): the supervisor first
(so nothing starts the daemon again), then the daemon: asked to quit on its socket, then
SIGTERM, then SIGKILL, waiting until it's gone. A daemon from before the lock (an older
package, still running after an upgrade) is found as the supervisor's child running
`-m live.app`, by its parent's PID. Never a pattern over every process.

    python3 -m live.instance pid | daemon | supervisor | session
    python3 -m live.instance started SUPERVISOR_PID     record the supervisor just started
    python3 -m live.instance stop [--timeout S]         exit 1 if a process outlived SIGKILL
"""
import fcntl
import os
import signal
import socket
import sys
import time

RUN = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
LOCK = os.path.join(RUN, "bromigos-live.lock")
PIDF = os.path.join(RUN, "bromigos-live.pid")
SOCK = os.path.join(RUN, "bromigos-live.sock")
TAKEN = 4                      # the daemon's exit code when another holds the lock


def starttime(pid):
    """The process's start time in clock ticks since boot (None when it's gone, or a zombie:
    it has exited, only no one has reaped it yet, as in a container whose PID 1 doesn't)."""
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as f:
            stat = f.read()
    except (OSError, ValueError):
        return None
    try:            # the name is in parentheses and may hold spaces or parentheses itself
        fields = stat[stat.rindex(b")") + 2:].split()
        if fields[0] in (b"Z", b"X"):
            return None
        return int(fields[19])
    except (ValueError, IndexError):
        return None


def cmdline(pid):
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            return [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
    except (OSError, ValueError):
        return []


def is_daemon(argv):
    """`python3 -m live.app [--login]`, whatever the interpreter's path."""
    return len(argv) >= 3 and os.path.basename(argv[0]).startswith("python") and argv[1:3] == ["-m", "live.app"]


def read(path):
    """(pid, start) from a `PID START` file; start None for a bare PID (an older file)."""
    try:
        with open(path) as f:
            parts = f.read().split()
        pid = int(parts[0])
        start = int(parts[1]) if len(parts) > 1 else None
    except (OSError, ValueError, IndexError):
        return None
    return (pid, start) if pid > 0 else None


def alive(rec, check=None):
    """The recorded process is the one running under that PID now."""
    if not rec:
        return False
    pid, start = rec
    now = starttime(pid)
    if now is None:
        return False
    if start is not None:
        return now == start
    return check(pid) if check else True


def write(path, pid):
    start = starttime(pid)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(f"{pid} {start if start is not None else ''}".strip() + "\n")
    os.replace(tmp, path)


def acquire(path=LOCK, wait=2.0):
    """The daemon's lock: an open file it keeps for its life, or None when another live
    daemon holds it. Retried for `wait` seconds (a stop in progress lets go of it)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+")                       # not inherited by children (O_CLOEXEC)
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                f.close()
                return None
            time.sleep(0.05)
    f.seek(0)
    f.truncate()
    f.write(f"{os.getpid()} {starttime(os.getpid())}\n")
    f.flush()
    return f


def daemon():
    """The daemon holding the lock: (pid, start), or None."""
    rec = read(LOCK)
    return rec if alive(rec, lambda p: is_daemon(cmdline(p))) else None


def _script_check(pid):
    """An older bare-PID file: the process must be this script (a supervisor's subshell:
    `bash …/bromigos-live start`)."""
    argv = cmdline(pid)
    return len(argv) >= 2 and os.path.basename(argv[1]) == "bromigos-live"


def supervisor():
    rec = read(PIDF)
    return rec if alive(rec, _script_check) else None


def children(pid):
    """Daemons whose parent is `pid` (a supervisor from before the lock)."""
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/stat", "rb") as f:
                stat = f.read()
            ppid = int(stat[stat.rindex(b")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == pid and is_daemon(cmdline(d)):
            start = starttime(d)
            if start is not None:
                out.append((int(d), start))
    return out


def _signal(rec, sig):
    if alive(rec):
        try:
            os.kill(rec[0], sig)
        except (ProcessLookupError, PermissionError):
            pass


def _wait_gone(recs, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not any(alive(r) for r in recs):
            return True
        time.sleep(0.05)
    return not any(alive(r) for r in recs)


def _ask_quit():
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(2)
        s.connect(SOCK)
        s.sendall(b"quit")
        s.recv(64)
        s.close()
    except OSError:
        pass


def stop(timeout=3.0, say=print):
    """Stop the supervisor and the daemon, exactly. True when nothing of them is left."""
    sup = supervisor()
    daemons = [d for d in [daemon()] if d]
    if sup:
        daemons += [c for c in children(sup[0]) if c not in daemons]    # one from before the lock
        _signal(sup, signal.SIGTERM)          # bash waiting on its child dies at once: no restart
        if not _wait_gone([sup], 2.0):
            _signal(sup, signal.SIGKILL)
            _wait_gone([sup], 1.0)
    if daemons:
        _ask_quit()                           # a clean quit saves the history
        if not _wait_gone(daemons, timeout):
            for d in daemons:
                _signal(d, signal.SIGTERM)
            if not _wait_gone(daemons, timeout):
                for d in daemons:
                    _signal(d, signal.SIGKILL)
                _wait_gone(daemons, 2.0)
    left = [r for r in ([sup] if sup else []) + daemons if alive(r)]
    if supervisor() is None:
        try:
            os.unlink(PIDF)
        except FileNotFoundError:
            pass
    stopped = [str(r[0]) for r in ([sup] if sup else []) + daemons if r not in left]
    if stopped:
        say("stopped " + " ".join(stopped))
    if left:
        say("still running: " + " ".join(str(r[0]) for r in left))
    return not left


def session(pid):
    """The Hyprland instance a process was started for."""
    try:
        with open(f"/proc/{int(pid)}/environ", "rb") as f:
            for kv in f.read().split(b"\0"):
                if kv.startswith(b"HYPRLAND_INSTANCE_SIGNATURE="):
                    return kv.split(b"=", 1)[1].decode(errors="replace")
    except (OSError, ValueError):
        pass
    return ""


def main(argv):
    cmd = argv[0] if argv else "pid"
    if cmd == "daemon":
        d = daemon()
        print(d[0] if d else "")
        return 0 if d else 1
    if cmd == "supervisor":
        s = supervisor()
        print(s[0] if s else "")
        return 0 if s else 1
    if cmd == "pid":                         # running at all: the daemon, else its supervisor
        r = daemon() or supervisor()
        print(r[0] if r else "")
        return 0 if r else 1
    if cmd == "session":                     # the session the running daemon draws on
        d = daemon()
        if not d:
            sup = supervisor()
            kids = children(sup[0]) if sup else []
            d = kids[0] if kids else None
        print(session(d[0]) if d else "")
        return 0 if d else 1
    if cmd == "started" and len(argv) == 2:
        write(PIDF, int(argv[1]))
        return 0
    if cmd == "stop":
        t = float(argv[argv.index("--timeout") + 1]) if "--timeout" in argv else 3.0
        return 0 if stop(t) else 1
    print("usage: python3 -m live.instance pid|daemon|supervisor|session|started PID|stop [--timeout S]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
