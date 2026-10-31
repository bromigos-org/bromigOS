"""Field Kit's repairs that change an install (docs/fieldkit.md). Each one keeps what it
changes in a backup first (system.Backup), says what it did in plain words, and needs no
network.

  snapshots(t) / rollback(t, n)   snapper's snapshots, and starting from one as the system
  repair_grub(t)                  GRUB put back on the disk and its menu made again
  boot_options(t) / set_boot_options(t, words)   the kernel's parameters in /etc/default/grub
  disk_report() / scrub(t)        the drives' health and btrfs's own checks, read-only
  backup_home(t, dest)            the people's files to a USB drive (rsync)
"""

import glob
import os
import re
import shlex
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from . import diagnose, system


# ------------------------------------------------------------------ snapshots and rollback

@dataclass
class Snapshot:
    number: int
    date: str
    kind: str
    description: str

    def title(self):
        what = self.description or {"pre": "before a change", "post": "after a change", "single": "timeline"}.get(self.kind, self.kind)
        return f"{self.date} · {what} ({self.number})"


def snapshots(target):
    """snapper's snapshots of / on the install, newest first (read from btrfs's top level, so
    it works when the install doesn't boot)."""
    base = os.path.join(target.top, "@.snapshots") if target.top else target.path("/.snapshots")
    out = []
    for info in glob.glob(os.path.join(base, "*", "info.xml")):
        try:
            x = ET.parse(info).getroot()
            n = int(x.findtext("num"))
            out.append(Snapshot(n, (x.findtext("date") or "")[:16], x.findtext("type") or "",
                                (x.findtext("description") or "").strip()))
        except (ET.ParseError, ValueError, TypeError, OSError):
            continue
        if not os.path.isdir(os.path.join(os.path.dirname(info), "snapshot")):
            out.pop()
    return sorted(out, key=lambda s: s.number, reverse=True)


def rollback(target, number):
    """The install starts from snapshot NUMBER from now on, the way `bromigos update --rollback`
    does it: the current root (@) is kept as @.before-rollback-<when>, a writable copy of the
    snapshot becomes @. Then the kernel in /boot is made to match the snapshot's modules
    (/boot isn't in snapshots). Returns what happened, in words."""
    if not target.top or target.is_live_root:
        raise system.Failed("Roll back from Field Kit with the install mounted (Mount my bromigOS install).")
    top = target.top
    src = os.path.join(top, "@.snapshots", str(number), "snapshot")
    if not os.path.isdir(src):
        raise system.Failed(f"There's no snapshot {number}.")
    if not os.path.isdir(os.path.join(top, "@")):
        raise system.Failed("This install's root isn't the @ subvolume: Field Kit can't roll it back by itself.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    kept = f"@.before-rollback-{stamp}"
    boot_kernels = {base: kernel_version(os.path.join(target.root, "boot", f"vmlinuz-{base}"))
                    for base in diagnose.kernels(target).values()}
    # the install's own mounts go first: @ is renamed under them
    system.run(["umount", "-R", target.root], check=False)
    os.rename(os.path.join(top, "@"), os.path.join(top, kept))
    r = system.run(["btrfs", "subvolume", "snapshot", src, os.path.join(top, "@")], check=False)
    if r.returncode != 0:
        os.rename(os.path.join(top, kept), os.path.join(top, "@"))
        raise system.Failed("The snapshot couldn't be copied: " + (r.stderr.strip() or "?") + ". Nothing changed.")
    # a snapshot taken while pacman ran holds its lock (docs/iso.md, the rollback test)
    lock = os.path.join(top, "@", "var/lib/pacman/db.lck")
    if os.path.exists(lock):
        os.unlink(lock)
    system.run(["mount", "-o", "subvol=@", target.mapper or target.device, target.root])
    system.run(["mount", "-a", "--fstab", target.path("/etc/fstab"), "--target-prefix", target.root], check=False)
    words = [f"The install now starts as it was at snapshot {number}. The way it was a minute ago is kept beside it, "
             f"as {kept}, so this can be undone; delete it once you're happy with the result."]
    words.append(match_kernel(target, boot_kernels))
    return " ".join(w for w in words if w)


def kernel_version(path):
    """The version string inside a bzImage (its header points at it), or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(0x210)
            if head[0x202:0x206] != b"HdrS":
                return None
            off = int.from_bytes(head[0x20E:0x210], "little") + 0x200
            f.seek(off)
            return f.read(256).split(b"\0", 1)[0].split(b" ", 1)[0].decode(errors="replace")
    except OSError:
        return None


def match_kernel(target, boot_kernels):
    """After a rollback: each kernel in /boot must be the one whose modules the restored system
    has, or it can't load drivers (even the one /boot itself needs). Copies the snapshot's own
    kernel to /boot and builds the startup files in that case."""
    have = diagnose.kernels(target)                    # {version: base} in the restored root
    fixed = []
    for base, booted in boot_kernels.items():
        want = next((v for v, b in have.items() if b == base), None)
        if not want or want == booted:
            continue
        src = target.path(f"/usr/lib/modules/{want}/vmlinuz")
        if os.path.isfile(src):
            b = system.Backup(target, "rollback-kernel")
            b.keep(f"/boot/vmlinuz-{base}")
            target.chroot(["cp", f"/usr/lib/modules/{want}/vmlinuz", f"/boot/vmlinuz-{base}"])
            fixed.append(f"{base} {booted or '?'} → {want}")
    if not fixed:
        return "The kernel in /boot already matches."
    return "The kernel in /boot was changed to match (" + ", ".join(fixed) + "). " + diagnose.rebuild_initramfs(target)


# ------------------------------------------------------------------ the boot menu

def firmware():
    return "uefi" if os.path.isdir("/sys/firmware/efi") else "bios"


def boot_disk(target):
    """The disk holding /boot (for a BIOS install's GRUB)."""
    r = system.run(["findmnt", "-no", "SOURCE", "--target", target.path("/boot")], check=False)
    src = r.stdout.strip()
    r = system.run(["lsblk", "-no", "PKNAME", src], check=False)
    name = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    return f"/dev/{name}" if name else None


def repair_grub(target):
    """GRUB reinstalled from the install's own package, where it was (the removable path when
    that's how it was installed), then grub.cfg made again and checked."""
    words = []
    if not os.path.isfile(target.path("/usr/bin/grub-install")):
        raise system.Failed("This install hasn't got GRUB (another boot loader starts it): nothing done.")
    b = system.Backup(target, "boot-menu")
    b.keep("/boot/grub/grub.cfg")
    if firmware() == "uefi":
        args = ["grub-install", "--target=x86_64-efi", "--efi-directory=/boot"]
        removable = os.path.isfile(target.path("/boot/EFI/BOOT/BOOTX64.EFI"))
        # the folders other loaders own aren't GRUB's: the removable path's, Field Kit's own UKI,
        # Windows', systemd-boot's, Linux distributions' shims
        others = {"BOOT", "BROMIGOS-FIELDKIT", "MICROSOFT", "SYSTEMD", "LINUX", "LIMINE"}
        ids = [os.path.basename(d) for d in glob.glob(target.path("/boot/EFI/*"))
               if os.path.basename(d).upper() not in others
               and glob.glob(os.path.join(d, "grub*.efi"))]
        if ids:
            args.append(f"--bootloader-id={ids[0]}")
        else:
            # where archinstall puts it, and where any firmware looks: the removable path
            args.append("--removable")
    else:
        disk = boot_disk(target)
        if not disk:
            raise system.Failed("Couldn't tell which disk starts this install.")
        args = ["grub-install", "--target=i386-pc", disk]
    r = target.chroot(args, check=False, timeout=300)
    if r.returncode != 0:
        raise system.Failed("grub-install: " + " / ".join((r.stdout + r.stderr).strip().splitlines()[-2:]))
    words.append("GRUB is back on the disk.")
    words.append(make_grub_cfg(target))
    return f"{' '.join(words)} (The old menu is in {b.where()}.)"


def make_grub_cfg(target):
    """grub.cfg made again, aside, checked, then swapped in (as bromigos-boot-theme does)."""
    r = target.chroot(["grub-mkconfig", "-o", "/boot/grub/grub.cfg.fieldkit-new"], check=False, timeout=300)
    if r.returncode != 0:
        raise system.Failed("grub-mkconfig: " + " / ".join((r.stdout + r.stderr).strip().splitlines()[-2:]))
    r = target.chroot(["grub-script-check", "/boot/grub/grub.cfg.fieldkit-new"], check=False)
    if r.returncode != 0:
        os.unlink(target.path("/boot/grub/grub.cfg.fieldkit-new"))
        raise system.Failed("The new boot menu didn't pass GRUB's check; the old one is left as it was.")
    os.replace(target.path("/boot/grub/grub.cfg.fieldkit-new"), target.path("/boot/grub/grub.cfg"))
    os.sync()
    return "The boot menu was made again."


# the presets the boot options editor offers: (word, label, hint)
PRESETS = [
    ("quiet", "Quiet start", "fewer messages while it starts"),
    ("splash", "Splash", "the bromigOS emblem while it starts"),
    ("nomodeset", "Safe graphics", "the basic display only, no graphics driver"),
    ("systemd.unit=multi-user.target", "Always text mode", "a login prompt, no desktop, every boot"),
    ("module_blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm,nouveau", "No NVIDIA driver", "start on another card or the basic display"),
    ("module_blacklist=amdgpu,radeon", "No AMD driver", "start on another card or the basic display"),
    ("module_blacklist=i915,xe", "No Intel driver", "start on another card or the basic display"),
    ("nvidia_drm.modeset=1", "NVIDIA early display", "NVIDIA's driver takes the screen from the start"),
    ("loglevel=7", "Every kernel message", "for finding a problem; noisy"),
]


def boot_options(target):
    """GRUB_CMDLINE_LINUX_DEFAULT's words in the install's /etc/default/grub (the last such line
    wins, as grub-mkconfig reads it; bromigOS's own block doesn't set it)."""
    text = _default_grub(target)
    val = None
    for m in re.finditer(r"^\s*GRUB_CMDLINE_LINUX_DEFAULT=(.*)$", text, re.M):
        val = m.group(1)
    if val is None:
        return []
    try:
        return shlex.split(val)[0].split() if shlex.split(val) else []
    except ValueError:
        return val.strip("\"'").split()


def _default_grub(target):
    try:
        return system.read(target.path("/etc/default/grub"))
    except OSError:
        raise system.Failed("This install has no /etc/default/grub (GRUB doesn't start it).") from None


def set_boot_options(target, words):
    """GRUB_CMDLINE_LINUX_DEFAULT set to WORDS (its last line rewritten; the file kept first),
    then the boot menu made again. Takes effect at the next start."""
    text = _default_grub(target)
    new = 'GRUB_CMDLINE_LINUX_DEFAULT="' + " ".join(words).replace('"', "") + '"'
    lines = text.splitlines(keepends=True)
    idx = [i for i, line in enumerate(lines) if re.match(r"^\s*GRUB_CMDLINE_LINUX_DEFAULT=", line)]
    if idx:
        lines[idx[-1]] = new + "\n"
    else:
        lines.append(new + "\n")
    b = system.Backup(target, "boot-options")
    b.write("/etc/default/grub", "".join(lines))
    try:
        msg = make_grub_cfg(target)
    except system.Failed:
        # put it back: never leave a config grub-mkconfig refuses
        b.write("/etc/default/grub", text)
        raise
    return f"Saved: {' '.join(words) or '(none)'}. {msg} The old file is in {b.where()}."


# ------------------------------------------------------------------ disks

def disks():
    return [p for p in system.block_devices() if getattr(p, "type", "") == "disk" and not p.path.startswith(("/dev/loop", "/dev/zram", "/dev/sr"))]


def disk_report(dev):
    """A drive's health from its own records (SMART), in plain words first, then the details."""
    r = system.run(["smartctl", "-H", "-A", "-i", dev], check=False, timeout=60)
    text = r.stdout
    if "PASSED" in text or "OK" in re.findall(r"SMART Health Status:\s*(\w+)", text):
        verdict = f"{dev}: the drive says it's healthy."
    elif "FAILED" in text:
        verdict = f"{dev}: the drive says it's FAILING. Copy your files off it now (Back up my files)."
    elif r.returncode & 0b10:
        verdict = f"{dev}: this drive doesn't report its health (common for USB adapters and virtual disks)."
    else:
        verdict = f"{dev}: no clear answer from the drive."
    worry = []
    for key in ("Reallocated_Sector_Ct", "Current_Pending_Sector", "Offline_Uncorrectable", "Media and Data Integrity Errors",
                "Percentage Used", "Critical Warning"):
        m = re.search(rf"{re.escape(key)}.*?(\d+)\s*%?\s*$", text, re.M)
        if m and int(m.group(1)) > 0 and not (key == "Percentage Used" and int(m.group(1)) < 80):
            worry.append(f"{key}: {m.group(1)}")
    if worry:
        verdict += " Worth watching: " + ", ".join(worry) + "."
    return verdict, text


def scrub(target):
    """btrfs's scrub, read-only (-r): reads every block and checks its checksum, repairs nothing."""
    if not target.top and not target.is_live_root:
        raise system.Failed("Mount the install first.")
    where = target.top or "/"
    r = system.run(["btrfs", "scrub", "start", "-B", "-r", where], check=False, timeout=None)
    text = (r.stdout + r.stderr).strip()
    errs = re.search(r"Error summary:\s*(.*)", text)
    if r.returncode == 0 and errs and "no errors found" in errs.group(1):
        return "Every block read back as written: no errors.", text
    if r.returncode == 0:
        return "The check finished: " + (errs.group(1) if errs else "see the details."), text
    return "The check found problems: " + (errs.group(1) if errs else "see the details.") + \
        " Copy your files off first (Back up my files), then ask before repairing.", text


# ------------------------------------------------------------------ backups to a USB drive

def backup_argv(target, dest):
    """rsync of every person's home folder to DEST/bromigos-backup-<host>-<date>/: files,
    permissions, links and times kept; nothing deleted on the drive."""
    folder = os.path.join(dest, f"bromigos-backup-{target.hostname()}-{time.strftime('%Y%m%d-%H%M')}")
    homes = [target.path(h) for _, h in target.users() if os.path.isdir(target.path(h))]
    if not homes:
        raise system.Failed("There are no home folders on this install to back up.")
    return ["rsync", "-aHX", "--info=progress2", "--no-inc-recursive", *homes, folder + "/"], folder


# ---------------------------------------------------------------- what each repair runs (dry runs)

def plan(target, action, *args):
    """{commands, touches} for a repair, as a person would type them, without running it:
    `fieldkit … --dry-run`, the screens' "show commands" (c). {root} is the install's root."""
    if action == "rollback":
        n = int(args[0])
        return {"commands": [
            "umount -R {root}",
            "mv {top}/@ {top}/@.before-rollback-<when>",
            f"btrfs subvolume snapshot {{top}}/@.snapshots/{n}/snapshot {{top}}/@",
            "rm -f {top}/@/var/lib/pacman/db.lck",
            "mount -o subvol=@ <the install's device> {root}",
            "mount -a --fstab {root}/etc/fstab --target-prefix {root}",
            "# if /boot's kernel doesn't match the snapshot's modules:",
            "cp {root}/usr/lib/modules/<version>/vmlinuz {root}/boot/vmlinuz-linux",
            "arch-chroot {root} mkinitcpio -P"],
            "touches": ["the @ subvolume (kept as @.before-rollback-<when>)", "/boot/vmlinuz-*", "/boot/initramfs-*.img"]}
    if action == "grub-repair":
        if firmware() == "uefi":
            cmd = "arch-chroot {root} grub-install --target=x86_64-efi --efi-directory=/boot --removable (or --bootloader-id=<its folder>)"
        else:
            cmd = f"arch-chroot {{root}} grub-install --target=i386-pc {boot_disk(target) or '<the boot disk>'}"
        return {"commands": [cmd, "arch-chroot {root} grub-mkconfig -o /boot/grub/grub.cfg.fieldkit-new",
                             "arch-chroot {root} grub-script-check /boot/grub/grub.cfg.fieldkit-new",
                             "mv {root}/boot/grub/grub.cfg.fieldkit-new {root}/boot/grub/grub.cfg"],
                "touches": ["/boot/EFI/BOOT/BOOTX64.EFI or /boot/EFI/<id>/grubx64.efi" if firmware() == "uefi" else "the boot disk's MBR and gap",
                            "/boot/grub/", "the firmware's boot entries (efibootmgr)" if firmware() == "uefi" else ""]}
    if action == "boot-options":
        words = " ".join(args)
        return {"commands": ["cp -a {root}/etc/default/grub {root}/var/lib/bromigos/fieldkit-backups/<when>-boot-options/etc/default/grub",
                             f"sed -i 's|^GRUB_CMDLINE_LINUX_DEFAULT=.*|GRUB_CMDLINE_LINUX_DEFAULT=\"{words}\"|' {{root}}/etc/default/grub",
                             "arch-chroot {root} grub-mkconfig -o /boot/grub/grub.cfg.fieldkit-new",
                             "arch-chroot {root} grub-script-check /boot/grub/grub.cfg.fieldkit-new",
                             "mv {root}/boot/grub/grub.cfg.fieldkit-new {root}/boot/grub/grub.cfg"],
                "touches": ["/etc/default/grub", "/boot/grub/grub.cfg"]}
    if action == "scrub":
        return {"commands": ["btrfs scrub start -B -r {top}"], "touches": ["nothing (read-only)"]}
    if action == "backup":
        dev = args[0]
        return {"commands": [f"mount {dev} /run/bromigos-fieldkit/usb",
                             "rsync -aHX --info=progress2 {root}/home/<each person> /run/bromigos-fieldkit/usb/bromigos-backup-<host>-<when>/",
                             "sync"], "touches": [f"{dev} (adds a folder, deletes nothing)"]}
    if action == "mount":
        dev = args[0]
        return {"commands": [f"cryptsetup open --type luks {dev} bromigos-root   # asks the passphrase",
                             "mount -o subvolid=5 /dev/mapper/bromigos-root {top}",
                             "mount -o subvol=@ /dev/mapper/bromigos-root {root}",
                             "mount -a --fstab {root}/etc/fstab --target-prefix {root}"],
                "touches": [f"{dev} (unlocked, read and written only by the repairs you choose)"]}
    if action == "unmount":
        return {"commands": ["umount -R {root}", "umount {top}", "cryptsetup close bromigos-root"], "touches": []}
    raise ValueError(f"no plan for {action}")
