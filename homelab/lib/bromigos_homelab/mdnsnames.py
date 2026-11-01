"""The web apps' names on the local network: one mDNS name per app, such as
photos-myserver.local, each pointing at this server's address (docs/lab-provision.md, "App names").

Why one label (photos-myserver.local) and not a subdomain (photos.<server>.local): every mDNS
resolver answers a one-label .local name (Linux's nss-mdns and systemd-resolved, Apple's
mDNSResponder, Android's resolver, Windows' DNS client), while multi-label .local names are
answered by some and not others. Caddy serves each name (localprovision.caddy_routes) and this
publishes it, because nothing else does: avahi announces only the host's own name.

  bromigos lab mdns-names publish   keep publishing NAMES_FILE's names (the service runs this)
  bromigos lab mdns-names list      the names, and the address they'd point at now

The address is the one the default route leaves from (or the first global IPv4 when there is no
default route); when it changes (a DHCP renewal), the names move with it within POLL seconds.
"""
import os
import signal
import subprocess
import sys
import time

NAMES_FILE = "/etc/bromigos/lab/mdns-names"
POLL = 15


def read_names(path=NAMES_FILE):
    try:
        with open(path) as f:
            return [n.strip() for n in f if n.strip() and not n.lstrip().startswith("#")]
    except OSError:
        return []


def primary_ipv4(run=subprocess.run):
    """This server's address on its network: the default route's source, else the first global one."""
    try:
        out = run(["ip", "-4", "-o", "route", "get", "1.1.1.1"], capture_output=True, text=True, timeout=5).stdout
        words = out.split()
        if "src" in words:
            return words[words.index("src") + 1]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        pass
    try:
        out = run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            words = line.split()
            if "inet" in words:
                return words[words.index("inet") + 1].split("/")[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        pass
    return None


def commands(names, address):
    """One avahi-publish per name: an A record without the reverse (PTR) record, which is the host's own."""
    return [["avahi-publish", "--address", "--no-reverse", name, address] for name in names]


class Publisher:
    def __init__(self, names, spawn=subprocess.Popen, address=primary_ipv4):
        self.names, self.spawn, self.address = names, spawn, address
        self.procs, self.current = [], None

    def stop(self):
        for p in self.procs:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self.procs = []

    def tick(self):
        """Publish (again) when the address changed or a publisher ended; returns the address."""
        addr = self.address()
        dead = any(p.poll() is not None for p in self.procs)
        if addr != self.current or dead or (addr and not self.procs):
            self.stop()
            self.current = addr
            if addr:
                self.procs = [self.spawn(c) for c in commands(self.names, addr)]
        return addr


def main(argv):
    cmd = argv[0] if argv else "list"
    names = read_names()
    if cmd == "list":
        addr = primary_ipv4()
        for n in names:
            print(f"{n}\t{addr or 'no address yet'}")
        if not names:
            print("No app names: Caddy's step writes them (bromigos lab provision --local).")
        return 0
    if cmd == "publish":
        if not names:
            print("No app names to publish.", file=sys.stderr)
            return 0
        pub = Publisher(names)

        def bye(*_):
            pub.stop()
            sys.exit(0)
        signal.signal(signal.SIGTERM, bye)
        signal.signal(signal.SIGINT, bye)
        while True:
            pub.tick()
            time.sleep(POLL)
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
