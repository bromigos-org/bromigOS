#!/usr/bin/env python3
"""This machine's hardware packages and services, added to an archinstall configuration
so they come from the medium like the rest (docs/iso.md, "Installing from it").

  bromigos hw detect --json | hardware.py IN.json OUT.json

Reads the plan `bromigos hw` makes on the live system (its /sys is the machine's): the
GPU's driver packages (NVIDIA's open modules, Intel's or AMD's video decoding, the
firmware), a laptop's brightnessctl and power-profiles-daemon, and the services to
enable. Writes IN with them added to OUT and prints one line saying what. The rest of
the setup (NVIDIA's early KMS, a hybrid laptop's GPU names, Hyprland's GPU environment)
is `bromigos install`'s hardware step, in the new system.
"""
import json
import sys


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    cfg = json.load(open(sys.argv[1]))
    cfg.pop("_comment", None)
    hw = json.load(sys.stdin)
    want = hw.get("plan", {}).get("want", {})
    # the medium has no multilib: its 32-bit packages wait for the installed system
    pkgs = [p for p in want.get("packages", []) if not p.startswith("lib32-")]
    services = [s.removesuffix(".service") for s in want.get("services", [])]
    cfg["packages"] = sorted(set(cfg.get("packages", [])) | set(pkgs))
    cfg["services"] = sorted(set(cfg.get("services", [])) | set(services))
    json.dump(cfg, open(sys.argv[2], "w"), indent=2)
    machine = hw.get("detection", {}).get("machine", {}).get("kind", "?")
    gpus = ", ".join(g.get("vendor", "?") + " " + (g.get("name") or g.get("id", "")) for g in hw.get("detection", {}).get("gpus", []))
    print(f"{machine}; {gpus or 'no GPU found'}; packages: {' '.join(pkgs) or 'none'}; services: {' '.join(services) or 'none'}")


if __name__ == "__main__":
    main()
