"""A stand-in for live/app.py in tests/test_instance.py: the daemon's lock, socket and
signals, without GTK. Copied into a throwaway tree as live/app.py; never installed.

FAKE_START_DELAY=S   start-up takes S seconds before the socket exists (a SIGTERM then
                     must still stop it, as the real daemon's QUIT does)
FAKE_IGNORE_TERM=1   SIGTERM does nothing (a hung daemon: only SIGKILL stops it)
FAKE_IGNORE_QUIT=1   the socket's quit does nothing
FAKE_NO_LOCK=1       no lock (a daemon from before it)
"""
import os
import signal
import socket
import sys
import threading
import time

from . import instance

QUIT = threading.Event()


def on_term(*_):
    if not os.environ.get("FAKE_IGNORE_TERM"):
        QUIT.set()


def main():
    signal.signal(signal.SIGTERM, on_term)
    if not os.environ.get("FAKE_NO_LOCK"):
        lock = instance.acquire()
        if lock is None:
            print("another live daemon runs", flush=True)
            sys.exit(instance.TAKEN)
    if QUIT.wait(float(os.environ.get("FAKE_START_DELAY") or 0)):
        return
    try:
        os.unlink(instance.SOCK)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(instance.SOCK)
    srv.listen(4)
    srv.settimeout(0.05)
    while not QUIT.is_set():
        try:
            c, _ = srv.accept()
        except (socket.timeout, InterruptedError):
            continue
        with c:
            cmd = c.recv(256).decode().strip()
            c.sendall(b"ok")
        if cmd == "quit" and not os.environ.get("FAKE_IGNORE_QUIT"):
            break
    try:
        os.unlink(instance.SOCK)
    except OSError:
        pass


if __name__ == "__main__":
    main()
