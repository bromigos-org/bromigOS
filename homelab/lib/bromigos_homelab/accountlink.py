"""bromigos lab link: link this computer to your Bromigos account as a lab, from
bromigos.org/link (docs/lab.md, "Link this computer to your account").

  bromigos lab link [--intent self-hosted|hosted] [--name NAME] [--json] [--timeout S] [--no-start]

It hands the work to BRODEC's lab bridge, `brodec-lab connect` (the brodec-lab package),
which shows a short code and a QR code, waits for you to approve it on bromigos.org/link,
then pairs the lab with your account. The bridge makes the lab's keys on this computer and
they never leave it; your phone verifies VECTOR afterwards. Once paired, this starts the
bridge's service (brodec-lab), so VECTOR answers from here.

  --intent hosted   link your account for a lab Bromigos hosts instead: you choose and pay
                    for it on the website, and nothing is paired on this computer
  --json            one JSON event per line (brodec-lab connect's, then a `service` event),
                    for a setup screen
  --no-start        pair, but leave the service as it is

The bridge's data belongs to its service, so it runs through sudo (it asks for your
password). Exit codes: 0 linked (or approved for a hosted lab), 1 not linked, 3 the bridge
isn't installed, 130 cancelled.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

SERVICE = "brodec-lab"
INSTALL = "sudo pacman -S brodec-lab"


def parse(argv):
    p = argparse.ArgumentParser(prog="bromigos lab link", description=__doc__.split("\n\n")[0])
    p.add_argument("--intent", choices=["self-hosted", "hosted"], default="self-hosted")
    p.add_argument("--name", help="the lab's name on the website and in BRODEC (default: the bridge's)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--timeout", type=int, help="give up after this many seconds")
    p.add_argument("--no-start", action="store_true", help="don't start the bridge's service after pairing")
    return p.parse_args(argv)


def connect_argv(a, euid=None, kind="cli"):
    """The `brodec-lab connect` command line: through sudo unless already root."""
    euid = os.geteuid() if euid is None else euid
    argv = ([] if euid == 0 else ["sudo"]) + ["brodec-lab", "connect", "--kind", kind, "--intent", a.intent]
    if a.name:
        argv += ["--name", a.name]
    if a.json:
        argv.append("--json")
    if a.timeout:
        argv += ["--timeout", str(a.timeout)]
    return argv


def service_argv(euid=None):
    euid = os.geteuid() if euid is None else euid
    return ([] if euid == 0 else ["sudo"]) + ["systemctl", "enable", "--now", SERVICE]


def service_active(run=subprocess.run):
    try:
        return run(["systemctl", "is-active", "--quiet", SERVICE]).returncode == 0
    except OSError:
        return False


def say(a, event, text):
    if a.json:
        print(json.dumps(event), flush=True)
    else:
        print(text, flush=True)


def main(argv, run=subprocess.run, which=shutil.which):
    a = parse(argv)
    if not which("brodec-lab"):
        say(a, {"event": "failed", "code": "not_installed",
                "message": f"Linking needs BRODEC's lab bridge: {INSTALL}"},
            f"Linking this computer needs BRODEC's lab bridge. Install it with: {INSTALL}")
        return 3
    try:
        rc = run(connect_argv(a)).returncode
    except KeyboardInterrupt:
        return 130
    if rc != 0 or a.intent == "hosted" or a.no_start:
        return rc
    if service_active(run):
        say(a, {"event": "service", "state": "running"},
            "The lab bridge is running; it picks up the pairing by itself.")
        return 0
    ok = run(service_argv()).returncode == 0
    say(a, {"event": "service", "state": "started" if ok else "failed"},
        "Started the lab bridge (brodec-lab): VECTOR answers from this computer now." if ok else
        f"Paired, but the lab bridge didn't start. Start it with: sudo systemctl enable --now {SERVICE}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
