"""`bromigos fieldkit make-stick`: a Field Kit USB stick that already knows you (docs/fieldkit.md,
"Bake your own stick"). The medium is written as it is (never rebuilt); your settings go on a
small partition after it, labelled FIELDKIT, which Field Kit reads at every start
(medium.py): your SSH key, Wi-Fi networks, the lab connection, startup scripts.

Your settings are gathered as you (your keys, your lab file), then the writing runs as root.
"""

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import system

IMAGE = "/usr/share/bromigos/fieldkit/bromigos-fieldkit.iso"


def toml_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def gather(a, out):
    """The fieldkit/ folder, as the person running it: config.toml and the files it names."""
    keys = []
    for path in a.ssh_key or sorted(glob.glob(os.path.expanduser("~/.ssh/id_*.pub"))):
        try:
            keys += [line.strip() for line in open(os.path.expanduser(path)) if line.strip()]
        except OSError as e:
            sys.exit(f"make-stick: {path}: {e}")
    lines = ["# bromigOS Field Kit's settings (docs/fieldkit.md, \"Your settings on the stick\")",
             f"# written by bromigos fieldkit make-stick, {time.strftime('%Y-%m-%d')}", "", "[ssh]",
             "authorized_keys = [" + ", ".join(toml_str(k) for k in keys) + "]",
             f"start = {'true' if a.remote else 'false'}", ""]
    for w in a.wifi:
        ssid, _, pw = w.partition(":")
        lines += ["[[wifi]]", f"ssid = {toml_str(ssid)}"] + ([f"password = {toml_str(pw)}"] if pw else []) + [""]
    lab = a.lab or os.path.expanduser("~/.config/bromigos/homelab.toml")
    if os.path.isfile(lab):
        shutil.copyfile(lab, os.path.join(out, "homelab.toml"))
        lines += ["[lab]", 'config = "homelab.toml"', ""]
    os.makedirs(os.path.join(out, "autorun"), exist_ok=True)
    with open(os.path.join(out, "autorun", "README.txt"), "w") as f:
        f.write("Scripts here (*.sh) run at every start, as root, in name order.\n"
                "What each printed is in /run/bromigos-fieldkit/autorun-<name>.log; the menu says how they ended.\n")
    with open(os.path.join(out, "config.toml"), "w") as f:
        f.write("\n".join(lines))
    return len(keys)


def source_image(a):
    if getattr(a, "iso", None):
        return a.iso
    if os.path.isfile(IMAGE):
        return IMAGE
    sys.exit("make-stick: no Field Kit image here (sudo pacman -S bromigos-fieldkit)")


def partitions(dev):
    r = system.run(["lsblk", "-nrpo", "NAME,LABEL", dev], check=False)
    return [line.split(" ", 1) for line in r.stdout.splitlines()]


def settings_partition(dev):
    for parts in partitions(dev):
        if len(parts) == 2 and parts[1] == "FIELDKIT":
            return parts[0]
    return None


def add_partition(dev):
    """A FAT partition labelled FIELDKIT in the space after the medium, on its own partition
    table (the medium's GPT has its backup header at the image's end: moved to the disk's)."""
    pt = system.run(["blkid", "-o", "value", "-s", "PTTYPE", dev], check=False).stdout.strip()
    if pt == "gpt":
        system.run(["sgdisk", "-e", dev], check=False)
        system.run(["sgdisk", "-n", "0:0:+256M", "-t", "0:0700", "-c", "0:FIELDKIT", dev])
    else:
        system.run(["sfdisk", "--append", dev], input=",256M,c\n")
    system.run(["partprobe", dev], check=False)
    system.run(["udevadm", "settle"], check=False)
    time.sleep(1)
    new = partitions(dev)[-1][0]
    system.run(["mkfs.fat", "-F", "32", "-n", "FIELDKIT", new])
    return new


def write_settings(part, folder):
    mnt = tempfile.mkdtemp(prefix="fieldkit-stick-")
    system.run(["mount", part, mnt])
    try:
        dst = os.path.join(mnt, "fieldkit")
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(folder, dst)
    finally:
        system.run(["sync"], check=False)
        system.run(["umount", mnt], check=False)
        os.rmdir(mnt)


def make_stick(a, need_root, argv):
    dev = a.device
    if os.geteuid() != 0:
        folder = tempfile.mkdtemp(prefix="fieldkit-settings-")
        n = gather(a, folder)
        print(f"Your settings: {n} SSH key(s), {len(a.wifi)} Wi-Fi network(s)"
              + (", the lab connection" if os.path.isfile(os.path.join(folder, "homelab.toml")) else "") + ".")
        os.environ["BROMIGOS_FIELDKIT_SETTINGS"] = folder
        need_root(argv)                          # sudo, with the folder named in the environment
    folder = os.environ.get("BROMIGOS_FIELDKIT_SETTINGS")
    if not folder or not os.path.isdir(folder):
        folder = tempfile.mkdtemp(prefix="fieldkit-settings-")
        gather(a, folder)
    drives = [p for p in system.block_devices() if getattr(p, "type", "") == "disk" and (p.removable or p.tran == "usb")]
    if not dev:
        print("USB drives:" if drives else "No USB drive found: plug one in.")
        for p in drives:
            print(f"  {p.path}  {p.size}  {p.model}")
        return 2
    if dev not in [p.path for p in drives] and not os.environ.get("BROMIGOS_FIELDKIT_ANY_DISK"):
        sys.exit(f"make-stick: {dev} isn't a USB drive")
    if a.settings_only:
        part = settings_partition(dev)
        if not part:
            sys.exit(f"make-stick: {dev} has no FIELDKIT partition (make the stick first)")
        write_settings(part, folder)
        print(f"Settings written to {part}.")
        return 0
    iso = source_image(a)
    if not a.yes:
        ans = input(f"Everything on {dev} will be replaced by Field Kit. Type the drive's name ({os.path.basename(dev)}) to go ahead: ")
        if ans.strip() != os.path.basename(dev):
            print("Nothing written.")
            return 1
    print(f"Writing {os.path.basename(iso)} to {dev}…")
    rc = subprocess.call(["dd", f"if={iso}", f"of={dev}", "bs=4M", "conv=fsync", "oflag=direct", "status=progress"])
    if rc != 0:
        sys.exit("make-stick: writing the medium failed")
    part = add_partition(dev)
    write_settings(part, folder)
    print(f"Done: {dev} starts Field Kit, with your settings on {part} (FIELDKIT).")
    return 0
