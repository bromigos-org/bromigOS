#!/usr/bin/env python3
"""Reinstall bromigOS and keep your files (docs/iso.md, "Reinstalling"): a fresh system on
the same disk, the home folder untouched, the old system kept as a snapshot. Run as root by
bromigos-iso-install for mode = "reinstall":

  reinstall.py prepare --answers FILE   unlock the root (LUKS: the passphrase in the answers),
                                        keep the old root (@ becomes @old-root-DATE, read-only)
                                        and its snapshots, make a fresh @ and @.snapshots, move
                                        the old kernels aside on /boot, mount it all at /mnt for
                                        archinstall (its pre-mounted layout); writes what it
                                        found to /run/bromigos-iso/reinstall.json
  reinstall.py finish --answers FILE    in the new system: the old system's people again, with
                                        their user IDs, groups and passwords (yours with the new
                                        password)
  reinstall.py boot --answers FILE      unlocking at start (LUKS), and GRUB
  reinstall.py undo --answers FILE      the install stopped before the new system could start:
                                        the old system back as @ (from @old-root-DATE), its
                                        snapshots and kernels back, so the computer starts as
                                        it did before
  reinstall.py tidy --answers FILE      the new system starts: the old kernels' copy goes
Prints ::stage lines; a problem is one ::error line in plain words.
"""
import json
import os
import subprocess
import sys
import time


def _read(path):
    with open(path) as f:
        return f.read()

STATE = "/run/bromigos-iso/reinstall.json"
TOP = "/run/bromigos-iso/top"
TARGET = "/mnt"
STASH = ".bromigos-old-kernels"       # on /boot, while a reinstall runs
SUBVOLS = [("@home", "home"), ("@log", "var/log"), ("@pkg", "var/cache/pacman/pkg"), ("@.snapshots", ".snapshots"),
           # the data a reinstall keeps, as it keeps /home (made empty if the old system had none)
           ("@containers", "var/lib/containers"), ("@k3s", "var/lib/rancher"), ("@srv", "srv"),
           ("@bromigos-state", "var/lib/bromigos/server")]


def sh(*argv, input=None, check=True):
    print("+ " + " ".join(argv), flush=True)
    r = subprocess.run(argv, input=input, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.rstrip(), flush=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{argv[0]}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def fail(words):
    print(f"::error {words}", flush=True)
    return 1


def prepare(a):
    import bromigos_installer.disks as disks
    disk = a["disk"]
    doc = disks.probe()
    d = next((x for x in doc["disks"] if x["path"] == disk), None)
    b = (d or {}).get("bromigos")
    if not b:
        return fail("There's no bromigOS on that disk any more. Nothing was changed.")
    print("::stage 4 Opening your bromigOS", flush=True)
    dev = b["root"]
    luks_uuid = None
    if b["encrypted"]:
        luks_uuid = sh("blkid", "-s", "UUID", "-o", "value", dev).stdout.strip()
        pp = a.get("old_passphrase") or a.get("passphrase") or a.get("password")
        if subprocess.run(["cryptsetup", "open", "--test-passphrase", dev], input=pp, text=True,
                          capture_output=True).returncode != 0:
            return fail("The passphrase doesn't unlock the disk. Go back and type the passphrase you use at start. "
                        "Nothing was changed.")
        if not os.path.exists("/dev/mapper/root"):
            sh("cryptsetup", "open", dev, "root", "--key-file=-", input=pp)
        dev = "/dev/mapper/root"
    os.makedirs(TOP, exist_ok=True)
    sh("mount", "-o", "subvolid=5", dev, TOP)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    names = os.listdir(TOP)
    if "@" not in names or "@home" not in names:
        sh("umount", TOP)
        return fail("The disk's bromigOS isn't laid out the usual way (no @ and @home), so it can't be reinstalled "
                    "keeping your files. Nothing was changed. Copy your files off it, then choose Erase the whole disk.")
    print(f"::stage 6 Keeping the old system as a snapshot (@old-root-{stamp})", flush=True)
    sh("btrfs", "subvolume", "snapshot", "-r", f"{TOP}/@", f"{TOP}/@old-root-{stamp}")
    old = "/run/bromigos-iso/old-root"
    state = {"stamp": stamp, "encrypted": b["encrypted"], "luks_uuid": luks_uuid, "root": b["root"], "boot": b["boot"],
             "esp": b.get("esp"), "boot_is_esp": b.get("boot_is_esp"), "old_root": old, "disk": disk, "dev": dev,
             "had_snapshots": "@.snapshots" in names}
    with open(STATE, "w") as f:            # from here on, `undo` can put everything back
        json.dump(state, f)
    if "@.snapshots" in names:
        os.rename(f"{TOP}/@.snapshots", f"{TOP}/@old-snapshots-{stamp}")
    sh("btrfs", "subvolume", "delete", "--recursive", f"{TOP}/@")
    sh("btrfs", "subvolume", "create", f"{TOP}/@")
    sh("btrfs", "subvolume", "create", f"{TOP}/@.snapshots")
    fresh = []
    for sv in ("@log", "@pkg", "@containers", "@k3s", "@srv", "@bromigos-state"):
        if sv not in names:
            sh("btrfs", "subvolume", "create", f"{TOP}/{sv}")
            fresh.append(sv)
    sh("mount", "-o", "subvol=@", dev, TARGET)
    for sv, where in SUBVOLS:
        os.makedirs(f"{TARGET}/{where}", exist_ok=True)
        sh("mount", "-o", f"subvol={sv}", dev, f"{TARGET}/{where}")
    os.makedirs(f"{TARGET}/boot", exist_ok=True)
    sh("mount", b["boot"], f"{TARGET}/boot")
    # the old kernels move aside (`undo` puts them back, `tidy` removes them); Field Kit's
    # image and anything else stays
    stash = f"{TARGET}/boot/{STASH}"
    os.makedirs(stash, exist_ok=True)
    for f in os.listdir(f"{TARGET}/boot"):
        if f.startswith(("vmlinuz-", "initramfs-", "intel-ucode", "amd-ucode")):
            os.rename(f"{TARGET}/boot/{f}", f"{stash}/{f}")
    if b.get("esp") and not b.get("boot_is_esp"):
        os.makedirs(f"{TARGET}/boot/efi", exist_ok=True)
        sh("mount", b["esp"], f"{TARGET}/boot/efi")
    os.makedirs(old, exist_ok=True)
    sh("mount", "-o", f"ro,subvol=@old-root-{stamp}", dev, old)
    # a system from before the data subvolumes kept containers, k3s and /srv inside its root:
    # their data comes along into the new subvolumes (reflinked: instant, no extra space)
    for sv, where in SUBVOLS:
        src = f"{old}/{where}"
        if sv in fresh and os.path.isdir(src) and os.listdir(src):
            print(f"::stage 8 Bringing {('/' + where)} along", flush=True)
            sh("cp", "-a", "--reflink=auto", f"{src}/.", f"{TARGET}/{where}/")
    print("::stage 9 Your files are safe; the new system goes in beside them", flush=True)
    return 0


def chroot(*argv, input=None, check=True):
    return sh("arch-chroot", TARGET, *argv, input=input, check=check)


def finish(a):
    st = json.loads(_read(STATE))
    old = st["old_root"]
    me = a["user"]
    print("::stage 80 Bringing back the people who use this computer", flush=True)
    shadow = {}
    try:
        for line in open(f"{old}/etc/shadow"):
            f = line.split(":")
            shadow[f[0]] = line.rstrip("\n")
    except OSError:
        pass
    groups_of = {}
    try:
        for line in open(f"{old}/etc/group"):
            f = line.rstrip("\n").split(":")
            for u in filter(None, f[3].split(",")) if len(f) > 3 else []:
                groups_of.setdefault(u, []).append(f[0])
    except OSError:
        pass
    new_groups = {line.split(":")[0] for line in open(f"{TARGET}/etc/group")}
    for line in open(f"{old}/etc/passwd"):
        f = line.rstrip("\n").split(":")
        if len(f) < 7 or not f[2].isdigit() or not 1000 <= int(f[2]) < 60000:
            continue
        name, uid, gid, gecos, home, shell = f[0], int(f[2]), int(f[3]), f[4], f[5], f[6]
        exists = subprocess.run(["arch-chroot", TARGET, "id", "-u", name], capture_output=True, text=True)
        if exists.returncode == 0:
            if int(exists.stdout.strip()) != uid:          # you, made afresh: your old number back
                chroot("usermod", "-u", str(uid), name, check=False)
                chroot("groupmod", "-g", str(gid), name, check=False)
            continue
        if subprocess.run(["arch-chroot", TARGET, "getent", "group", str(gid)], capture_output=True).returncode != 0:
            chroot("groupadd", "-g", str(gid), name, check=False)
        chroot("useradd", "-M", "-u", str(uid), "-g", str(gid), "-d", home, "-s", shell if os.path.exists(f"{TARGET}{shell}") else "/bin/bash",
               "-c", gecos, name, check=False)
        keep = [g for g in groups_of.get(name, []) if g in new_groups]
        if keep:
            chroot("usermod", "-aG", ",".join(keep), name, check=False)
        if name in shadow and name != me:                 # their own password, as it was
            chroot("chpasswd", "-e", input=":".join(shadow[name].split(":")[:2]) + "\n", check=False)
        print(f"kept {name} (user ID {uid})", flush=True)
    # /home's snapshots stay where they were: snapper's configuration for them comes back too
    if os.path.isfile(f"{old}/etc/snapper/configs/home") and os.path.isdir(f"{TARGET}/home/.snapshots"):
        os.makedirs(f"{TARGET}/etc/snapper/configs", exist_ok=True)
        open(f"{TARGET}/etc/snapper/configs/home", "w").write(open(f"{old}/etc/snapper/configs/home").read())
        conf = f"{TARGET}/etc/conf.d/snapper"
        s = open(conf).read() if os.path.exists(conf) else 'SNAPPER_CONFIGS=""\n'
        import re
        m = re.search(r'^SNAPPER_CONFIGS="([^"]*)"', s, re.M)
        names = (m.group(1).split() if m else [])
        if "home" not in names:
            names.append("home")
            s = re.sub(r'^SNAPPER_CONFIGS="[^"]*"', f'SNAPPER_CONFIGS="{" ".join(names)}"', s, flags=re.M) if m else s + f'SNAPPER_CONFIGS="{" ".join(names)}"\n'
            open(conf, "w").write(s)
    return 0


def boot_loader(a):
    """Unlocking at start (LUKS) and GRUB, as archinstall would have (it isn't told about a
    pre-mounted root's encryption, nor asked for a boot loader)."""
    st = json.loads(_read(STATE))
    if st["encrypted"]:
        for conf in [f"{TARGET}/etc/mkinitcpio.conf"] + [f"{TARGET}/etc/mkinitcpio.conf.d/{x}" for x in
                                                        os.listdir(f"{TARGET}/etc/mkinitcpio.conf.d")]:
            if not os.path.isfile(conf):
                continue
            s = open(conf).read()
            import re
            s2 = re.sub(r"^(HOOKS=\([^)]*?)\b(filesystems)\b", lambda m: m.group(1) + ("" if "encrypt" in m.group(1) else "encrypt ") + m.group(2),
                        s, flags=re.M)
            if s2 != s:
                open(conf, "w").write(s2)
        g = open(f"{TARGET}/etc/default/grub").read()
        import re
        param = f"cryptdevice=UUID={st['luks_uuid']}:root root=/dev/mapper/root"
        if "cryptdevice=" not in g:
            g = re.sub(r'^GRUB_CMDLINE_LINUX="([^"]*)"', lambda m: f'GRUB_CMDLINE_LINUX="{(m.group(1) + " " + param).strip()}"', g, flags=re.M)
            open(f"{TARGET}/etc/default/grub", "w").write(g)
        chroot("mkinitcpio", "-P")
    if os.path.isdir("/sys/firmware/efi"):
        efi = "/boot" if st.get("boot_is_esp") else "/boot/efi"
        args = ["grub-install", "--target=x86_64-efi", f"--efi-directory={efi}", "--bootloader-id=GRUB"]
        if st.get("boot_is_esp"):
            args.append("--removable")                    # as the first install (its own disk)
        chroot(*args)
    else:
        chroot("grub-install", "--target=i386-pc", "--recheck", st["disk"])
    chroot("grub-mkconfig", "-o", "/boot/grub/grub.cfg")
    return 0


def undo(a):
    """The install stopped before the new system could start: the old one back, as it was."""
    try:
        st = json.loads(_read(STATE))
    except (OSError, ValueError):
        return 0                                   # prepare stopped before it changed anything
    stamp, dev = st["stamp"], st["dev"]
    print("::stage 0 Putting your old bromigOS back", flush=True)
    sh("umount", "-R", TARGET, check=False)
    sh("umount", st["old_root"], check=False)
    if not os.path.ismount(TOP):
        os.makedirs(TOP, exist_ok=True)
        sh("mount", "-o", "subvolid=5", dev, TOP)
    if not os.path.isdir(f"{TOP}/@old-root-{stamp}"):
        return fail("The old system's snapshot isn't there, so it can't be put back. Your home folder wasn't touched.")
    if os.path.isdir(f"{TOP}/@"):
        sh("btrfs", "subvolume", "delete", "--recursive", f"{TOP}/@")
    sh("btrfs", "subvolume", "snapshot", f"{TOP}/@old-root-{stamp}", f"{TOP}/@")
    if os.path.isdir(f"{TOP}/@old-snapshots-{stamp}"):
        if os.path.isdir(f"{TOP}/@.snapshots"):
            sh("btrfs", "subvolume", "delete", "--recursive", f"{TOP}/@.snapshots")
        os.rename(f"{TOP}/@old-snapshots-{stamp}", f"{TOP}/@.snapshots")
    # the restored @ is a new subvolume: an fstab line that names the old one by its ID
    # would no longer find it; by name (subvol=/@) it does
    fstab = f"{TOP}/@/etc/fstab"
    if os.path.isfile(fstab):
        import re
        s = _read(fstab)
        s2 = re.sub(r",?subvolid=\d+", "", s)
        if s2 != s:
            with open(fstab, "w") as f:
                f.write(s2)
    sh("btrfs", "subvolume", "delete", f"{TOP}/@old-root-{stamp}", check=False)
    sh("umount", TOP, check=False)
    boot = "/run/bromigos-iso/boot"
    os.makedirs(boot, exist_ok=True)
    sh("mount", st["boot"], boot)
    for f in os.listdir(boot):                     # whatever the new system put there first
        if f.startswith(("vmlinuz-", "initramfs-", "intel-ucode", "amd-ucode")):
            os.remove(f"{boot}/{f}")
    if os.path.isdir(f"{boot}/{STASH}"):
        for f in os.listdir(f"{boot}/{STASH}"):
            os.rename(f"{boot}/{STASH}/{f}", f"{boot}/{f}")
        os.rmdir(f"{boot}/{STASH}")
    sh("umount", boot, check=False)
    os.remove(STATE)
    print("Your old bromigOS is back as it was, and your files weren't touched.", flush=True)
    return 0


def tidy(a):
    """The new system starts: the old kernels' copy goes."""
    import shutil
    shutil.rmtree(f"{TARGET}/boot/{STASH}", ignore_errors=True)
    return 0


def main(argv):
    if len(argv) < 3 or argv[1] != "--answers":
        print(__doc__.strip())
        return 2
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    a = json.loads(_read(argv[2]))
    try:
        return {"prepare": prepare, "finish": finish, "boot": boot_loader, "undo": undo, "tidy": tidy}[argv[0]](a)
    except RuntimeError as e:
        return fail(f"Reinstalling stopped: {e}. Your home folder wasn't touched.")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
