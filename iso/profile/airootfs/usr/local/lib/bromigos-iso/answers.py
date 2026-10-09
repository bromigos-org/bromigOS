#!/usr/bin/env python3
"""archinstall's files for bromigos-iso-install: its configuration (the medium's
archinstall.json plus the disk and the choices) and its credentials.

  answers.py --disk /dev/sda --user NAME --password PW [--hostname H] [--no-encrypt]
             [--passphrase PP] [--keymap us] [--timezone UTC] [--locale en_US]
             [--firmware uefi|bios] [--ssh] --out DIR

The disk: a 1 GiB FAT32 /boot, unencrypted (the kernels and GRUB; the ESP on UEFI), and
the rest. The table is archinstall's choice: GPT on UEFI, MBR on BIOS (GRUB's core image
goes in the gap after the MBR, so no BIOS boot partition). The rest is btrfs,
on LUKS2 unless --no-encrypt (the passphrase is asked at boot; it defaults to the user's
password), with the subvolumes archinstall lays out (@ for /, @home, @log, @pkg,
@.snapshots). snapper's configurations of / and /home are bromigos-iso-install's, after
archinstall (no btrfs_options here: archinstall 4.5 can't make them on this layout, see
there); grub-btrfs and its daemon put the snapshots in GRUB's menu.
"""
import argparse
import json
import os
import subprocess
import uuid

TEMPLATE = "/usr/local/share/bromigos-iso/archinstall.json"


def size(unit, value):
    return {"sector_size": {"unit": "B", "value": 512}, "unit": unit, "value": value}


def part(start_mib, size_unit, size_value, fs, mountpoint, flags, btrfs=()):
    return {"btrfs": list(btrfs), "dev_path": None, "flags": flags, "fs_type": fs,
            "mount_options": [], "mountpoint": mountpoint, "obj_id": str(uuid.uuid4()),
            "size": size(size_unit, size_value), "start": size("MiB", start_mib),
            "status": "create", "type": "primary"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=TEMPLATE)
    ap.add_argument("--disk", required=True)
    ap.add_argument("--firmware", choices=["uefi", "bios"], default="uefi" if os.path.isdir("/sys/firmware/efi") else "bios")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--hostname", default="bromigos")
    ap.add_argument("--no-encrypt", action="store_true")
    ap.add_argument("--passphrase", default=None, help="the disk's passphrase (default: the password)")
    ap.add_argument("--keymap", default="us")
    ap.add_argument("--timezone", default="UTC")
    ap.add_argument("--locale", default="en_US")
    ap.add_argument("--ssh", action="store_true", help="sshd enabled on the installed system")
    ap.add_argument("--root-gib", type=int, default=None, help="the root's size (default: the disk's, less the boot partition)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    cfg = json.load(open(a.template))
    cfg.pop("_comment", None)
    subvols = [{"name": "@", "mountpoint": "/"}, {"name": "@home", "mountpoint": "/home"},
               {"name": "@log", "mountpoint": "/var/log"}, {"name": "@pkg", "mountpoint": "/var/cache/pacman/pkg"},
               {"name": "@.snapshots", "mountpoint": "/.snapshots"}]
    root_gib = a.root_gib
    if root_gib is None:                       # the whole disk, less /boot and a margin for GPT's tables
        name = os.path.basename(os.path.realpath(a.disk))
        try:
            sectors = int(open(f"/sys/class/block/{name}/size").read())
            root_gib = sectors * 512 // (1024 ** 3) - 2
        except OSError:
            raise SystemExit(f"answers.py: {a.disk}: no size in /sys; give --root-gib")
    if root_gib < 8:
        raise SystemExit(f"answers.py: {a.disk} is too small ({root_gib} GiB for the root)")
    parts, at = [], 1
    parts.append(part(at, "GiB", 1, "fat32", "/boot", ["boot"] + (["esp"] if a.firmware == "uefi" else []))); at += 1024
    root = part(at, "GiB", root_gib, "btrfs", None, [], subvols)
    parts.append(root)
    cfg["disk_config"] = {
        "config_type": "default_layout",
        "device_modifications": [{"device": a.disk, "wipe": True, "partitions": parts}],
    }
    if not a.no_encrypt:                       # inside disk_config (the top-level key is archinstall's deprecated form)
        cfg["disk_config"]["disk_encryption"] = {"encryption_type": "luks", "partitions": [root["obj_id"]], "lvm_volumes": []}
    cfg["hostname"] = a.hostname
    cfg["timezone"] = a.timezone
    cfg["locale_config"] = {"kb_layout": a.keymap, "sys_enc": "UTF-8", "sys_lang": a.locale}
    if a.ssh:
        cfg["services"] = sorted(set(cfg.get("services", [])) | {"sshd"})
        cfg["packages"] = sorted(set(cfg.get("packages", [])) | {"openssh"})

    def enc(pw):
        return subprocess.run(["openssl", "passwd", "-6", pw], capture_output=True, text=True, check=True).stdout.strip()
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
