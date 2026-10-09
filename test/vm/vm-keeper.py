#!/usr/bin/env python3
"""Runs a test VM's QEMU so it can't outlive whoever started it (test/vm/arch-vm.sh and
iso/test.sh start their VMs through this).

    vm-keeper.py --ready SOCKET [--owner PID|none] [--log FILE] -- qemu-system-x86_64 …

QEMU used to run with -daemonize, on its own. When the session driving a test died (a
terminal closed, a coding assistant stopped by its usage limit), the VM ran on: once for
45 minutes, holding 5 GB. Now:

- The keeper starts QEMU as its child, without -daemonize, and QEMU gets
  PR_SET_PDEATHSIG: if the keeper dies, however it dies, the kernel stops QEMU.
- The keeper watches the owner: the process that started the test (below). When the owner
  exits, the keeper stops QEMU (SIGTERM, then SIGKILL after 15 s) and exits.
- SIGTERM, SIGINT or SIGHUP to the keeper stops QEMU the same way. When QEMU exits by
  itself (the guest powered off, `down` killed it), the keeper exits too.
- Like -daemonize, the command returns once QEMU is up (its QMP socket, --ready, exists),
  with QEMU and the keeper detached in their own session. It exits 1, with QEMU's last
  lines, when QEMU stops before that.

The owner is BROMIGOS_VM_OWNER (a PID; `none` lets the VM run until `down`, as before),
or --owner. Otherwise it's the nearest ancestor that isn't a passing shell or wrapper: a
`bash script.sh`, a `zsh -c …`, `timeout`, `env` and the like end with the command, so the
owner is what ran them. That's the interactive shell at a terminal, or the assistant's own
process when it runs each command in a fresh shell. A process is identified by its PID and
its start time, so a reused PID isn't mistaken for it.
"""
import ctypes
import os
import signal
import subprocess
import sys
import time

SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh", "mksh"}
WRAPPERS = {"timeout", "env", "nice", "ionice", "nohup", "stdbuf", "time", "sudo", "setsid", "flock",
            "systemd-run", "unbuffer"}
PR_SET_PDEATHSIG = 1


def proc_argv(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return []


def proc_start(pid):
    """Its start time (clock ticks since boot), or None when it's gone."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(") ", 1)[1].split()[19])
    except (OSError, IndexError, ValueError):
        return None


def proc_parent(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(") ", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return 0


def passing(argv):
    """A process that ends when the command it runs ends: a shell running a script or -c,
    or a wrapper such as timeout."""
    if not argv:
        return False
    name = os.path.basename(argv[0]).lstrip("-")
    if name in WRAPPERS:
        return True
    if name in SHELLS:
        return any(a == "-c" or not a.startswith("-") for a in argv[1:])
    return False


def find_owner(start):
    pid = start
    while pid > 1:
        if not passing(proc_argv(pid)):
            return pid
        pid = proc_parent(pid)
    return None


def log(path, line):
    if path:
        with open(path, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} vm-keeper: {line}\n")


def pdeathsig():
    """In QEMU, before exec: SIGTERM when the keeper dies. If it died already, go."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    if os.getppid() != KEEPER:
        os._exit(1)


KEEPER = 0


def stop(qemu, logf, why):
    log(logf, f"stopping QEMU (PID {qemu.pid}): {why}")
    if qemu.poll() is None:
        qemu.terminate()
        try:
            qemu.wait(15)
        except subprocess.TimeoutExpired:
            log(logf, "QEMU didn't stop in 15 s: SIGKILL")
            qemu.kill()
            qemu.wait()


def tell(fd, msg):
    """A line to the command waiting for QEMU to be up (gone once it has its answer)."""
    try:
        os.write(fd, msg)
    except OSError:
        pass


def keep(argv, owner, ready, logf, report):
    """The keeper itself: QEMU as a child, watched until it or the owner is gone."""
    global KEEPER
    KEEPER = os.getpid()
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    if ready:                                   # a socket left by an earlier run isn't "up"
        try:
            os.unlink(ready)
        except OSError:
            pass
    out = open(logf, "a") if logf else subprocess.DEVNULL
    qemu = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=out, preexec_fn=pdeathsig)
    owner_start = proc_start(owner) if owner else None
    if owner and owner_start is None:
        stop(qemu, logf, f"the owner (PID {owner}) was gone before QEMU started")
        tell(report, b"owner gone\n")
        return 1
    log(logf, f"QEMU PID {qemu.pid}; owner "
        + (f"PID {owner} ({' '.join(proc_argv(owner))[:120]})" if owner else "none: runs until down"))
    stopping = []
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, lambda n, _f: stopping.append(signal.Signals(n).name))
    told = False
    while True:
        if not told and (not ready or os.path.exists(ready)):
            tell(report, b"ok\n")
            told = True
        code = qemu.poll()
        if code is not None:
            log(logf, f"QEMU exited ({code})")
            if not told:
                tell(report, f"QEMU exited ({code}) before it was up\n".encode())
            return code
        if stopping:
            stop(qemu, logf, f"the keeper got {stopping[0]}")
            return 0
        if owner and proc_start(owner) != owner_start:
            stop(qemu, logf, f"its owner (PID {owner}) is gone")
            return 0
        time.sleep(0.5)


def main():
    a = sys.argv[1:]
    if "--" not in a:
        sys.exit(__doc__)
    i = a.index("--")
    opts, argv = a[:i], a[i + 1:]

    def opt(flag):
        return opts[opts.index(flag) + 1] if flag in opts and opts.index(flag) + 1 < len(opts) else None
    ready, logf = opt("--ready"), opt("--log")
    want = opt("--owner") or os.environ.get("BROMIGOS_VM_OWNER") or ""
    if want == "none":
        owner = None
    elif want:
        owner = int(want)
    else:
        owner = find_owner(os.getppid())
    argv = [x for x in argv if x != "-daemonize"]
    r, w = os.pipe()
    child = os.fork()
    if child == 0:                          # the keeper: its own session, no terminal
        os.close(r)
        os.setsid()
        if os.fork() != 0:
            os._exit(0)
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        try:
            code = keep(argv, owner, ready, logf, w)
        except Exception as e:
            log(logf, f"failed: {e}")
            tell(w, f"failed: {e}\n".encode())
            code = 1
        os._exit(code if isinstance(code, int) and code >= 0 else 1)
    os.close(w)
    os.waitpid(child, 0)
    with os.fdopen(r) as f:
        first = f.readline().strip()
    if first == "ok":
        return 0
    print(f"vm-keeper: {first or 'the keeper stopped'}", file=sys.stderr)
    if logf and os.path.exists(logf):
        with open(logf) as f:
            sys.stderr.write("".join(f.readlines()[-10:]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
