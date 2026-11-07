"""`bromigos fieldkit make-stick`: a Field Kit USB stick that already knows you (docs/fieldkit.md,
"Bake your own stick"). The medium is written as it is (never rebuilt); your settings go on a
small partition after it, labelled FIELDKIT, which Field Kit reads at every start
(medium.py): your SSH key, Wi-Fi networks, the lab connection, startup scripts.

Your settings are gathered as you (your keys, your lab file), then the writing runs as root.
With --answers, an installer answer file goes in the folder too, as install-server.toml or
install-desktop.toml (its edition): the boot menu then installs from it unattended. With
--image FILE, the same stick is written to an image file instead of a drive, as you (no root):
the medium, then the FIELDKIT partition, made with mkfs.fat and mtools' mcopy.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import image, system


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
    if getattr(a, "answers", None):
        edition, text = answer_file(a.answers)
        with open(os.path.join(out, f"install-{edition}.toml"), "w") as f:
            f.write(text)
        os.chmod(os.path.join(out, f"install-{edition}.toml"), 0o600)
        print(f"The answer file: install-{edition}.toml (the boot menu installs from it unattended; "
              "it holds the password as written)")
    return len(keys)


ANSWER_EDITIONS = ("server", "desktop")


def answer_file(path):
    """(edition, text) of an installer answer file (docs/iso.md, "Answer files"), checked enough
    to know where it goes; the installer checks the rest when it starts."""
    import tomllib
    try:
        with open(os.path.expanduser(path)) as f:
            text = f.read()
        doc = tomllib.loads(text)
    except (OSError, ValueError) as e:
        sys.exit(f"make-stick: the answer file {path}: {e}")
    edition = (doc.get("install") or {}).get("edition", "desktop")
    if edition not in ANSWER_EDITIONS:
        sys.exit(f"make-stick: the answer file's edition is \"{edition}\"; it's \"server\" or \"desktop\"")
    return edition, text


def source_image(a):
    """--iso FILE, this Field Kit stick when it's running from one, else a downloaded Field Kit
    ISO (image.py). Exits with plain words when there's none."""
    try:
        return image.find(getattr(a, "iso", None))
    except image.NoImage as e:
        sys.exit(str(e))


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


SETTINGS_MIB = 256


def make_image(a):
    """The stick as an image file (--image FILE), as you: the medium, a FIELDKIT partition after
    it (as add_partition makes it on a drive), and the settings folder in it. Write the file to a
    stick later with `bromigos fieldkit usb` or dd."""
    for tool in ("sfdisk", "mkfs.fat", "mcopy"):
        if not shutil.which(tool):
            sys.exit(f"make-stick --image needs {tool} ({'mtools' if tool == 'mcopy' else 'util-linux' if tool == 'sfdisk' else 'dosfstools'})")
    iso = source_image(a)
    out = os.path.abspath(a.image)
    folder = tempfile.mkdtemp(prefix="fieldkit-settings-")
    n = gather(a, folder)
    print(f"Your settings: {n} SSH key(s), {len(a.wifi)} Wi-Fi network(s)"
          + (", the lab connection" if os.path.isfile(os.path.join(folder, "homelab.toml")) else "") + ".")
    part_file = out + ".part"
    fat = out + ".fieldkit.fat"
    try:
        shutil.copyfile(iso, part_file)
        size = os.path.getsize(part_file)
        mib = 1 << 20
        # the partition starts 1 MiB-aligned after the whole medium (not just after its last
        # partition: an ISO may carry data past it), with a spare MiB after it
        first = ((size + mib - 1) // mib) * mib // 512
        sectors = SETTINGS_MIB * mib // 512
        with open(part_file, "r+b") as f:
            f.truncate(first * 512 + sectors * 512 + mib)
        pt = system.run(["blkid", "-p", "-o", "value", "-s", "PTTYPE", part_file], check=False).stdout.strip()
        if pt == "gpt":
            system.run(["sgdisk", "-e", part_file], check=False)
            system.run(["sgdisk", "-n", f"0:{first}:+{SETTINGS_MIB}M", "-t", "0:0700", "-c", "0:FIELDKIT", part_file])
        else:
            system.run(["sfdisk", "--append", part_file], input=f"{first},{sectors},c\n")
        last = json.loads(system.run(["sfdisk", "-J", part_file]).stdout)["partitiontable"]["partitions"][-1]
        start, sectors = int(last["start"]), int(last["size"])
        if os.path.exists(fat):
            os.unlink(fat)
        system.run(["mkfs.fat", "-F", "32", "-n", "FIELDKIT", "-C", fat, str(sectors * 512 // 1024)])
        system.run(["mcopy", "-i", fat, "-s", folder, "::/fieldkit"])
        with open(fat, "rb") as src, open(part_file, "r+b") as dst:
            dst.seek(start * 512)
            shutil.copyfileobj(src, dst, 4 * mib)
        os.replace(part_file, out)
    finally:
        for f in (fat, part_file):
            if os.path.exists(f):
                os.unlink(f)
        shutil.rmtree(folder, ignore_errors=True)
    print(f"Done: {out} is a Field Kit stick ({os.path.basename(iso)}, with your settings on its FIELDKIT "
          "partition). Write it to a drive with: bromigos fieldkit usb DEV --iso " + out)
    return 0


def make_stick(a, need_root, argv):
    if isinstance(getattr(a, "image", None), str) and a.image:
        return make_image(a)
    dev = a.device
    if os.geteuid() != 0 and dev and not a.settings_only:
        # the ISO, found as you (your Downloads), before sudo; the root half gets it as --iso
        argv = image.with_image(a, argv)
        if argv is None:
            return 1
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
    if os.path.realpath(iso) == os.path.realpath(dev):
        sys.exit(f"{dev} is the stick Field Kit is running from. Choose another drive.")
    if not a.yes:
        ans = input(f"Everything on {dev} will be replaced by Field Kit. Type the drive's name ({os.path.basename(dev)}) to go ahead: ")
        if ans.strip() != os.path.basename(dev):
            print("Nothing written.")
            return 1
    print(f"Writing {os.path.basename(iso)} to {dev}…")
    cmd = ["dd", f"if={iso}", f"of={dev}", "bs=4M", "conv=fsync", "oflag=direct", "status=progress"]
    if not os.path.isfile(iso):
        # this Field Kit stick's device: only as many bytes as its ISO holds (isosize)
        n = int(system.run(["isosize", iso], check=False).stdout.strip() or 0)
        if not n:
            sys.exit("make-stick: couldn't tell this stick's size")
        cmd += ["iflag=fullblock,count_bytes", f"count={n}"]
    rc = subprocess.call(cmd)
    if rc != 0:
        sys.exit("make-stick: writing the medium failed")
    part = add_partition(dev)
    write_settings(part, folder)
    print(f"Done: {dev} starts Field Kit, with your settings on {part} (FIELDKIT).")
    return 0
