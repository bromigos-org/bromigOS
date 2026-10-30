#!/usr/bin/env python3
"""archinstall's files for bromigos-iso-install: its configuration (the medium's
archinstall.json plus the disk and the choices) and its credentials.

  answers.py --disk /dev/sda --user NAME --password PW [--hostname H] [--no-encrypt]
             [--passphrase PP] [--keymap us] [--timezone UTC] [--locale en_US]
             [--firmware uefi|bios] [--ssh] [--alongside [--esp DEV]] [--edition FILE]
             [--online] --out DIR
  answers.py --answers FILE --out DIR       the installers' answers (bromigos_installer:
                                            the same choices, as JSON)

Erase (the default): the disk is wiped. A 2 GiB FAT32 /boot, unencrypted (the kernels and
GRUB; the ESP on UEFI), and the rest. The table is archinstall's choice: GPT on UEFI, MBR
on BIOS (GRUB's core image goes in the gap after the MBR, so no BIOS boot partition).

--alongside: nothing on the disk is touched. The largest free stretch (bromigos-iso-install
made it first, shrinking the other system when asked) gets a 2 GiB ext4 /boot and the
rest; on UEFI the disk's own EFI system partition (Windows', --esp, or the first one) is
mounted at /boot/efi, unformatted, for GRUB's EFI files beside Windows' boot manager.

The rest is btrfs, on LUKS2 unless --no-encrypt (the passphrase is asked at boot; it
defaults to the user's password), with the subvolumes archinstall lays out (@ for /,
@home, @log, @pkg, @.snapshots). snapper's configurations of / and /home are
bromigos-iso-install's, after archinstall; grub-btrfs and its daemon put the snapshots in
GRUB's menu.

--edition FILE: an edition (Field Kit's: editions/*.json) whose packages and services
replace the desktop's; the boot, disk and snapshot pieces (REQUIRED) are always added.
--online: the packages come from Arch's mirrors (and bromigOS's repository, in the live
system's pacman.conf), for an edition the medium doesn't carry.
"""
import argparse
import json
import os
import subprocess
import uuid


def _read(path):
    with open(path) as f:
        return f.read()

TEMPLATE = "/usr/local/share/bromigos-iso/archinstall.json"
MiB, GiB = 1024 ** 2, 1024 ** 3
BOOT_GIB = 2                   # the kernels, GRUB, and Field Kit's repair image (its boot entry)
# what every install needs to boot, unlock, snapshot and update, whatever the edition
REQUIRED = ["amd-ucode", "intel-ucode", "linux-firmware", "btrfs-progs", "cryptsetup", "efibootmgr", "grub",
            "grub-btrfs", "inotify-tools", "snapper", "snap-pac", "sudo", "networkmanager", "bromigos-keyring",
            "os-prober", "ntfs-3g", "nano", "vim", "git"]
REQUIRED_SERVICES = ["NetworkManager", "snapper-timeline.timer", "snapper-cleanup.timer", "grub-btrfsd"]
ONLINE_MIRROR = "https://geo.mirror.pkgbuild.com/$repo/os/$arch"
# the boot menu's own entries and Field Kit on /boot (bromigos-boot's pacman hook copies it
# there when it fits: /boot is 2 GiB for it), and Secure Boot's signing (bromigos-secureboot:
# bromigos-iso-install sets it up), when the medium carries them
OPTIONAL = ["bromigos-boot", "bromigos-fieldkit", "bromigos-secureboot"]
OFFLINE_REPO = os.environ.get("BROMIGOS_ISO_REPO_DIR", "/var/lib/bromigos/repo")


def in_store(name):
    import glob
    import re
    pat = re.compile(re.escape(name) + r"-[^-]+-[^-]+-[^-]+\.pkg\.tar\.(zst|xz)$")
    return any(pat.match(os.path.basename(f)) for f in glob.glob(os.path.join(OFFLINE_REPO, "**", "*.pkg.tar.*"), recursive=True))


def size(unit, value):
    return {"sector_size": {"unit": "B", "value": 512}, "unit": unit, "value": value}


def part(start_mib, size_unit, size_value, fs, mountpoint, flags, btrfs=(), status="create", dev_path=None):
    return {"btrfs": list(btrfs), "dev_path": dev_path, "flags": flags, "fs_type": fs,
            "mount_options": [], "mountpoint": mountpoint, "obj_id": str(uuid.uuid4()),
            "size": size(size_unit, size_value), "start": size("MiB", start_mib),
            "status": status, "type": "primary"}


SUBVOLS = [{"name": "@", "mountpoint": "/"}, {"name": "@home", "mountpoint": "/home"},
           {"name": "@log", "mountpoint": "/var/log"}, {"name": "@pkg", "mountpoint": "/var/cache/pacman/pkg"},
           {"name": "@.snapshots", "mountpoint": "/.snapshots"}]


def sfdisk_json(disk):
    r = subprocess.run(["sfdisk", "--json", disk], capture_output=True, text=True)
    return json.loads(r.stdout)["partitiontable"] if r.returncode == 0 and r.stdout.strip() else None


def largest_free(table, disk_bytes):
    """The largest unallocated stretch, in MiB: (start, size)."""
    ss = int(table.get("sectorsize", 512))
    first = max(int(table.get("firstlba", 2048)), MiB // ss)
    last = int(table.get("lastlba", disk_bytes // ss - 1))
    used = sorted((int(p["start"]), int(p["start"]) + int(p["size"])) for p in table.get("partitions", []))
    best, cur = (0, 0), first
    for s, e in used + [(last + 1, last + 1)]:
        if s > cur:
            a = -(-cur * ss // MiB)
            b = (s * ss) // MiB
            if b - a > best[1]:
                best = (a, b - a)
        cur = max(cur, e)
    return best


def erase_layout(a, disk_bytes):
    root_gib = a.root_gib
    if root_gib is None:                       # the whole disk, less /boot and a margin for GPT's tables
        root_gib = disk_bytes // GiB - BOOT_GIB - 1
    if root_gib < 8:
        raise SystemExit(f"answers.py: {a.disk} is too small ({root_gib} GiB for the root)")
    parts = [part(1, "GiB", BOOT_GIB, "fat32", "/boot", ["boot"] + (["esp"] if a.firmware == "uefi" else []))]
    root = part(1 + BOOT_GIB * 1024, "GiB", root_gib, "btrfs", None, [], SUBVOLS)
    parts.append(root)
    return {"device": a.disk, "wipe": True, "partitions": parts}, root


def alongside_layout(a, disk_bytes, table=None):
    table = table or sfdisk_json(a.disk)
    if table is None:
        raise SystemExit(f"answers.py: {a.disk} has no partition table to install beside")
    start, length = largest_free(table, disk_bytes)
    length -= 1                                # a MiB of slack at the end (GPT's backup table)
    if length < 20 * 1024 - 64:
        raise SystemExit(f"answers.py: {a.disk} has {length} MiB free; bromigOS needs 20 GiB")
    parts = []
    if a.firmware == "uefi":
        ss = int(table.get("sectorsize", 512))
        esps = [p for p in table["partitions"] if p.get("type", "").upper() == "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"]
        esp = next((p for p in esps if p["node"] == a.esp), esps[0] if esps else None)
        if esp is None:
            raise SystemExit(f"answers.py: {a.disk} has no EFI system partition")
        parts.append(part(int(esp["start"]) * ss // MiB, "MiB", int(esp["size"]) * ss // MiB, "fat32", "/boot/efi",
                          ["esp"], status="existing", dev_path=esp["node"]))
    # /boot: the boot flag is how archinstall finds it (on GPT parted makes that an ESP's
    # type; bromigos-iso-install sets it back to a plain Linux partition after archinstall)
    parts.append(part(start, "MiB", BOOT_GIB * 1024, "ext4", "/boot", ["boot"]))
    root = part(start + BOOT_GIB * 1024, "MiB", length - BOOT_GIB * 1024, "btrfs", None, [], SUBVOLS)
    parts.append(root)
    return {"device": a.disk, "wipe": False, "partitions": parts}, root


def from_answers(path):
    """The installers' answers (bromigos_installer.common.backend_answers) as argv."""
    d = json.loads(_read(path))
    argv = ["--disk", d["disk"], "--user", d["user"], "--password", d["password"],
            "--hostname", d.get("hostname") or "bromigos", "--keymap", d.get("keymap") or "us",
            "--timezone", d.get("timezone") or "UTC", "--locale", d.get("locale") or "en_US"]
    if not d.get("encrypt", True):
        argv.append("--no-encrypt")
    if d.get("passphrase"):
        argv += ["--passphrase", d["passphrase"]]
    if d.get("mode") == "reinstall":
        argv.append("--reinstall")
    if d.get("mode") == "alongside":
        argv.append("--alongside")
        if d.get("esp"):
            argv += ["--esp", d["esp"]]
    if d.get("edition_file"):
        argv += ["--edition", d["edition_file"]]
    if d.get("ssh"):
        argv.append("--ssh")
    adv = d.get("advanced") or {}
    if adv.get("fs") in ("btrfs", "ext4"):
        argv += ["--fs", adv["fs"]]
    if adv.get("kernel") in ("linux", "linux-lts", "linux-zen"):
        argv += ["--kernel", adv["kernel"]]
    if adv.get("zram") is False:
        argv.append("--no-zram")
    if d.get("online"):
        argv.append("--online")
    return argv


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", default=None, help="the installers' answers (JSON)")
    ap.add_argument("--template", default=TEMPLATE)
    ap.add_argument("--disk")
    ap.add_argument("--firmware", choices=["uefi", "bios"], default="uefi" if os.path.isdir("/sys/firmware/efi") else "bios")
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--hostname", default="bromigos")
    ap.add_argument("--no-encrypt", action="store_true")
    ap.add_argument("--passphrase", default=None, help="the disk's passphrase (default: the password)")
    ap.add_argument("--keymap", default="us")
    ap.add_argument("--timezone", default="UTC")
    ap.add_argument("--locale", default="en_US")
    ap.add_argument("--ssh", action="store_true", help="sshd enabled on the installed system")
    ap.add_argument("--root-gib", type=int, default=None, help="the root's size (default: the disk's, less the boot partition)")
    ap.add_argument("--alongside", action="store_true", help="keep what's on the disk; use its largest free stretch")
    ap.add_argument("--esp", default=None, help="--alongside on UEFI: the EFI system partition to share")
    ap.add_argument("--reinstall", action="store_true", help="the root bromigos_installer/reinstall.py mounted at /mnt")
    ap.add_argument("--edition", default=None, help="an edition file: its packages and services")
    ap.add_argument("--online", action="store_true", help="packages from the internet, not the medium")
    ap.add_argument("--fs", choices=["btrfs", "ext4"], default="btrfs",
                    help="the root's file system: btrfs (snapshots, rollback; the default) or ext4 (none)")
    ap.add_argument("--kernel", choices=["linux", "linux-lts", "linux-zen"], default="linux")
    ap.add_argument("--no-zram", action="store_true", help="no compressed swap in memory (zram)")
    ap.add_argument("--sfdisk-json", default=None, help=argparse.SUPPRESS)       # tests: the disk's table
    ap.add_argument("--disk-bytes", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.answers:
        a = ap.parse_args(from_answers(a.answers) + ["--out", a.out, "--template", a.template, "--firmware", a.firmware])
    if not (a.disk and a.user and a.password):
        ap.error("--disk, --user and --password (or --answers)")

    cfg = json.loads(_read(a.template))
    cfg.pop("_comment", None)
    disk_bytes = a.disk_bytes
    if disk_bytes is None:
        name = os.path.basename(os.path.realpath(a.disk))
        try:
            disk_bytes = int(open(f"/sys/class/block/{name}/size").read()) * 512
        except OSError:
            if a.root_gib is None or a.alongside:
                raise SystemExit(f"answers.py: {a.disk}: no size in /sys; give --root-gib")
            disk_bytes = 0
    if a.reinstall:
        # reinstall.py prepare mounted the new root (and the kept home) at /mnt; it unlocks the
        # disk and puts GRUB on (archinstall isn't told of the encryption: it's already there)
        mod, root = None, None
        a.no_encrypt = True
    elif a.alongside:
        table = json.loads(_read(a.sfdisk_json))["partitiontable"] if a.sfdisk_json else None
        mod, root = alongside_layout(a, disk_bytes, table)
    else:
        mod, root = erase_layout(a, disk_bytes)
    if a.reinstall:
        cfg["disk_config"] = {"config_type": "pre_mounted_config", "mountpoint": "/mnt"}
        cfg.pop("bootloader", None)
        cfg["bootloader_config"] = {"bootloader": "No bootloader", "uki": False, "removable": False}
    else:
        cfg["disk_config"] = {"config_type": "default_layout", "device_modifications": [mod]}
    if a.alongside:
        # GRUB in its own folder on the shared ESP (EFI/GRUB) with a firmware boot entry, not
        # at the removable path (EFI/BOOT/BOOTX64.EFI), which is Windows' fallback loader
        cfg.pop("bootloader", None)
        cfg["bootloader_config"] = {"bootloader": "Grub", "uki": False, "removable": False}
    if not a.no_encrypt:                       # inside disk_config (the top-level key is archinstall's deprecated form)
        cfg["disk_config"]["disk_encryption"] = {"encryption_type": "luks", "partitions": [root["obj_id"]], "lvm_volumes": []}
    if a.fs == "ext4":               # no subvolumes, no snapshots: the root is one ext4 file system
        if root is not None:
            root["fs_type"], root["btrfs"], root["mountpoint"] = "ext4", [], "/"
        cfg["services"] = [x for x in cfg.get("services", []) if x != "grub-btrfsd"]
    cfg["kernels"] = [a.kernel]
    cfg["swap"] = {"enabled": not a.no_zram, "algorithm": "zstd"}
    cfg["hostname"] = a.hostname
    cfg["timezone"] = a.timezone
    cfg["locale_config"] = {"kb_layout": a.keymap, "sys_enc": "UTF-8", "sys_lang": a.locale}
    if a.edition:
        ed = json.loads(_read(a.edition))
        cfg["packages"] = sorted(set(REQUIRED) | set(ed.get("packages", [])))
        cfg["services"] = sorted(set(REQUIRED_SERVICES) | set(ed.get("services", [])))
    else:
        cfg["packages"] = sorted(set(cfg.get("packages", [])) | {"os-prober", "ntfs-3g"})
    extra = [p for p in OPTIONAL if a.online or in_store(p)]
    cfg["packages"] = sorted(set(cfg["packages"]) | set(extra))
    if a.ssh:
        cfg["services"] = sorted(set(cfg.get("services", [])) | {"sshd"})
        cfg["packages"] = sorted(set(cfg.get("packages", [])) | {"openssh"})
    if a.online:
        cfg["offline"] = False
        cfg["no_pkg_lookups"] = False
        cfg["mirror_config"] = {"custom_servers": [{"url": ONLINE_MIRROR}], "mirror_regions": {},
                                "optional_repositories": []}

    def enc(pw):
        return subprocess.run(["openssl", "passwd", "-6", "-stdin"], input=pw, capture_output=True, text=True, check=True).stdout.strip()
    creds = {"users": [{"username": a.user, "enc_password": enc(a.password), "sudo": True}],
             "root_enc_password": enc(a.password)}
    if not a.no_encrypt:
        creds["encryption_password"] = a.passphrase if a.passphrase is not None else a.password

    os.makedirs(a.out, mode=0o700, exist_ok=True)
    json.dump(cfg, open(os.path.join(a.out, "config.json"), "w"), indent=2)
    with open(os.path.join(a.out, "creds.json"), "w", opener=lambda p, f: os.open(p, f, 0o600)) as f:
        json.dump(creds, f, indent=2)
    print(os.path.join(a.out, "config.json"), os.path.join(a.out, "creds.json"))


if __name__ == "__main__":
    main()
