"""What went wrong, in plain words, and what Field Kit can do about it (docs/fieldkit.md).

  last_boot(target)      "What went wrong on the last boot?": the install's own journal for
                         its latest boot (Field Kit's own boot is never in it), failed units,
                         errors, a crash, and whether it shut down cleanly
  black_screen(target)   "Fix a black screen / blinking cursor at startup": the known causes,
                         each a Finding with a fix that backs up what it changes

Each check reads the install's files (mounted, or "/" on a running system); fixes go through
system.Backup. Nothing here needs a network.
"""

import glob
import os
import re
from dataclasses import dataclass, field

from . import system

# commands show the install's root as {ROOT}; engine.plan_text() fills it in
ROOT = "{root}"
GPU_MODULES = ("nvidia", "nvidia_drm", "nvidia_modeset", "nvidia_uvm", "amdgpu", "radeon", "i915", "xe", "nouveau")
# package names people put in MODULES=() by mistake, and the module each one means
PACKAGE_NOT_MODULE = {
    "nvidia-open": "nvidia", "nvidia-open-dkms": "nvidia", "nvidia-dkms": "nvidia", "nvidia-utils": "nvidia",
    "nvidia-lts": "nvidia", "nvidia-580xx-dkms": "nvidia", "xf86-video-amdgpu": "amdgpu", "vulkan-radeon": "amdgpu",
    "vulkan-intel": "i915", "intel-media-driver": "i915", "mesa": None,
}
DRM_PIN = re.compile(r"(/dev/dri/(?:by-path/pci-[0-9a-f:.]+-card|card\d+)|pci-[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.\d)")


@dataclass
class Finding:
    title: str                       # one line, plain
    detail: str = ""                 # what it means, what's wrong
    fix_label: str = ""              # the button: "Move it out (kept in a backup)"
    fix: object = None               # fix(target) -> str, the outcome in words
    ok: bool = False                 # a check that passed (shown dimmer)
    lines: list = field(default_factory=list)
    commands: list = field(default_factory=list)   # what the fix runs, as a person would type it
    touches: list = field(default_factory=list)    # the files, units and devices it changes


# ------------------------------------------------------------------ the journal

def journal_args(target):
    """journalctl's arguments for the install's latest boot: its journal folder when mounted
    (the latest boot there is the one that went wrong), the boot before this one when it's
    the running system."""
    if target.is_live_root:
        return ["journalctl", "--no-pager", "-b", "-1"]
    return ["journalctl", "--no-pager", "-D", target.path("/var/log/journal"), "-b", "0"]


def journal(target, *extra):
    r = system.run(journal_args(target) + list(extra), check=False, timeout=60)
    return r.stdout.splitlines() if r.returncode == 0 else []


def first_line(target):
    """The boot's first journal line (journalctl has no "first N"; read one line and stop)."""
    import subprocess
    try:
        p = subprocess.Popen(journal_args(target) + ["-o", "short-iso"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except FileNotFoundError:
        return []
    line = p.stdout.readline().strip()
    p.kill()
    p.wait()
    return [line] if line and not line.startswith("--") else []


def last_boot(target):
    """The install's latest boot in a few plain findings."""
    out = []
    jdir = target.path("/var/log/journal")
    if not target.is_live_root and not os.path.isdir(jdir):
        return [Finding("There's no saved log on this install.",
                        "Its journal isn't kept on disk (/var/log/journal is missing), so the last boot left no record.")]
    head = first_line(target)
    if not head:
        return [Finding("No record of its last boot.",
                        "The journal is there but holds no boot that Field Kit can read (it may be damaged).")]
    first = head[0][:19]
    tail = journal(target, "-o", "short-iso", "-n", "1")
    last = tail[0][:19] if tail else "?"
    out.append(Finding(f"Its last boot: {first.replace('T', ' ')} to {last.replace('T', ' ')}", ok=True))
    failed = sorted({m.group(1) for line in journal(target, "-o", "cat", "-u", "init.scope", "--grep", "Failed with result|Failed to start")
                     for m in [re.search(r"([\w@.-]+\.(?:service|mount|socket|target|timer))", line)] if m})
    if failed:
        out.append(Finding(f"{len(failed)} part(s) of the system failed to start",
                           "These didn't start: " + ", ".join(failed[:12]) + (" …" if len(failed) > 12 else "")
                           + ". Field Kit's black screen check looks at the ones that stop the desktop.",
                           lines=failed))
    else:
        out.append(Finding("Every part of the system started", ok=True))
    errs = journal(target, "-p", "err", "-o", "cat", "-n", "400")
    gpu = [line for line in errs if re.search(r"nvidia|amdgpu|i915|\bxe\b|nouveau|drm|NVRM", line, re.I)]
    if gpu:
        out.append(Finding("The graphics driver reported errors",
                           "The last ones:\n  " + "\n  ".join(gpu[-5:]), lines=gpu))
    crash = [line for line in errs if re.search(r"segfault|core dumped|Kernel panic|BUG:|Oops", line)]
    if crash:
        out.append(Finding("Something crashed", "The last ones:\n  " + "\n  ".join(crash[-5:]), lines=crash))
    dm = journal(target, "-o", "cat", "-u", "sddm.service", "-n", "30")
    if any(re.search(r"failed|error|could not|cannot", line, re.I) for line in dm):
        out.append(Finding("The login screen (SDDM) had trouble",
                           "Its last lines:\n  " + "\n  ".join(dm[-6:]), lines=dm))
    clean = journal(target, "-o", "cat", "-n", "300")
    if clean and not any(re.search(r"Reached target .*(Power-Off|Power Off|Reboot|Shutdown|Halt|Kexec)|Shutting down|"
                                   r"systemd-shutdown|Journal stopped|Received SIGTERM from PID 1", line) for line in clean):
        out.append(Finding("It didn't shut down cleanly",
                           "The record stops without a shutdown: it froze, lost power, or was switched off while stuck."))
    if errs and not gpu and not crash:
        out.append(Finding(f"{len(errs)} error message(s) were logged",
                           "The last ones:\n  " + "\n  ".join(errs[-5:]), lines=errs))
    return out


# ------------------------------------------------------------------ the black screen's causes

def sddm_dropins(target):
    """/etc/sddm.conf.d: SDDM reads EVERY file in it, whatever its name. A file renamed to
    .disabled or .bak still counts; the only way to disable one is to move it out."""
    out = []
    d = target.path("/etc/sddm.conf.d")
    for path in sorted(glob.glob(os.path.join(d, "*"))):
        name = os.path.basename(path)
        try:
            text = system.read(path, errors="replace")
        except OSError:
            continue
        rel = "/etc/sddm.conf.d/" + name
        risky = re.findall(r"^\s*(CompositorCommand|DisplayServer|GreeterEnvironment|ServerArguments|"
                           r"[A-Z_]*DRM_DEVICES?|Current|EnableHiDPI)\s*=\s*(.*)$", text, re.M)
        renamed = not name.endswith(".conf")
        if not renamed and not risky:
            continue
        why = []
        if renamed:
            why.append(f"It's named {name}, which looks switched off, but SDDM reads every file in that "
                       "folder whatever its name, so it still applies.")
        for k, v in risky:
            why.append(f"It sets {k}={v.strip()}.")
        out.append(Finding(f"A login screen setting left in {rel}", " ".join(why),
                           fix_label="Move it out (kept in a backup)", fix=_move_out(rel),
                           commands=[f"mkdir -p {ROOT}/var/lib/bromigos/fieldkit-backups/<when>-sddm-dropin/etc/sddm.conf.d",
                                     f"mv {ROOT}{rel} {ROOT}/var/lib/bromigos/fieldkit-backups/<when>-sddm-dropin{rel}"],
                           touches=[rel]))
    if not out:
        out.append(Finding("No leftover login screen settings", ok=True))
    return out


def _move_out(rel):
    def fix(target):
        b = system.Backup(target, "sddm-dropin")
        b.move_out(rel)
        return f"Moved {rel} out. It's in {b.where()} if you want it back."
    return fix


def connected_cards():
    """{pci address: [connected connectors]} for this machine's graphics cards, from /sys."""
    cards = {}
    for status in glob.glob(os.environ.get("BROMIGOS_SYSFS", "/sys") + "/class/drm/card*-*/status"):
        conn = os.path.dirname(status)
        card = os.path.basename(conn).split("-", 1)[0]
        try:
            pci = os.path.basename(os.path.realpath(os.path.join(os.path.dirname(conn), card, "device")))
            on = system.read(status).strip() == "connected"
        except OSError:
            continue
        cards.setdefault(pci, [])
        if on:
            cards[pci].append(os.path.basename(conn).split("-", 1)[1])
    return cards


def card_pci(pin):
    """The PCI address a pin names (a by-path link or a pci- string); None for /dev/dri/cardN,
    whose number can change between boots."""
    m = re.search(r"pci-([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.\d)", pin)
    return m.group(1) if m else None


def gpu_pins(target):
    """Graphics cards pinned for the desktop or the login screen (the user's Hyprland env, the
    login screen's settings), checked against the cards that have a monitor connected now."""
    cards = connected_cards()
    with_screen = {pci for pci, conns in cards.items() if conns}
    files = []
    for _, home in target.users():
        files += glob.glob(target.path(os.path.join(home, ".local/state/bromigos/hw/hyprland.lua")))
        files += glob.glob(target.path(os.path.join(home, ".config/hypr/*.lua")))
        files += glob.glob(target.path(os.path.join(home, ".config/hypr/*.conf")))
        files += glob.glob(target.path(os.path.join(home, ".config/environment.d/*.conf")))
    files += glob.glob(target.path("/etc/sddm.conf.d/*")) + glob.glob(target.path("/etc/environment"))
    out = []
    for path in files:
        try:
            text = system.read(path, errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if line.lstrip().startswith(("--", "#")) or not re.search(r"DRM_DEVICES?|DRI_PRIME|card", line):
                continue
            pins = DRM_PIN.findall(line)
            if not pins:
                continue
            first = card_pci(pins[0])
            rel = "/" + os.path.relpath(path, target.root) if not target.is_live_root else path
            if first and cards and first not in with_screen:
                out.append(Finding(f"The desktop is pinned to a graphics card with no monitor ({first})",
                                   f"{rel} says to use {pins[0]} first, but no monitor is connected to that card now"
                                   + (f"; one is on {', '.join(sorted(with_screen))}." if with_screen else ".")
                                   + " The desktop then starts on a screen you can't see.",
                                   fix_label="Take the pin out (kept in a backup)",
                                   fix=_unpin(rel, line),
                                   commands=[f"cp -a {ROOT}{rel} {ROOT}/var/lib/bromigos/fieldkit-backups/<when>-gpu-pin{rel}",
                                             f"comment out in {ROOT}{rel}: {line.strip()}"],
                                   touches=[rel]))
            elif not first and pins[0].startswith("/dev/dri/card"):
                out.append(Finding(f"The desktop is pinned to {pins[0]} by number",
                                   f"{rel} names {pins[0]}. Card numbers can change from one boot to the next, "
                                   "so this can pick a card with no monitor.",
                                   fix_label="Take the pin out (kept in a backup)", fix=_unpin(rel, line),
                                   commands=[f"cp -a {ROOT}{rel} {ROOT}/var/lib/bromigos/fieldkit-backups/<when>-gpu-pin{rel}",
                                             f"comment out in {ROOT}{rel}: {line.strip()}"],
                                   touches=[rel]))
    if not out:
        out.append(Finding("No graphics card pins point away from your monitor", ok=True))
    return out


def _unpin(rel, line):
    def fix(target):
        path = target.path(rel)
        text = system.read(path)
        if line not in text:
            return f"{rel} changed since the check; nothing done."
        b = system.Backup(target, "gpu-pin")
        comment = "--" if rel.endswith(".lua") else "#"
        b.write(rel, text.replace(line, f"{comment} (Field Kit took this out: no monitor on that card) {line.strip()}", 1))
        return f"Took the pin out of {rel}. The old file is in {b.where()}. bromigOS picks the card with the monitor at the next login."
    return fix


def kernels(target):
    """The install's kernels: {version: package base} from /usr/lib/modules/*/pkgbase."""
    out = {}
    for d in glob.glob(target.path("/usr/lib/modules/*")):
        try:
            out[os.path.basename(d)] = system.read(os.path.join(d, "pkgbase")).strip()
        except OSError:
            pass
    return out


def module_exists(target, kver, name):
    """Whether the install has a module by that name for that kernel (modules.dep and
    modules.builtin, - and _ alike)."""
    base = target.path(f"/usr/lib/modules/{kver}")
    want = name.replace("-", "_")
    for listing in ("modules.dep", "modules.builtin"):
        try:
            with open(os.path.join(base, listing)) as f:
                for line in f:
                    mod = os.path.basename(line.split(":", 1)[0].strip())
                    mod = re.sub(r"\.ko(\.(xz|zst|gz))?$", "", mod).replace("-", "_")
                    if mod == want:
                        return True
        except OSError:
            continue
    return False


def mkinitcpio_conf_files(target):
    files = ["/etc/mkinitcpio.conf"] + sorted("/" + os.path.relpath(p, target.root) if not target.is_live_root else p
                                              for p in glob.glob(target.path("/etc/mkinitcpio.conf.d/*.conf")))
    return [f for f in files if os.path.isfile(target.path(f))]


def mkinitcpio(target):
    """MODULES=() naming a package instead of a module (nvidia-open for nvidia), or a module
    the install hasn't got for its kernel: the startup files can't be built then."""
    out = []
    ks = kernels(target)
    for rel in mkinitcpio_conf_files(target):
        text = system.read(target.path(rel))
        m = re.search(r"^\s*MODULES=\(([^)]*)\)", text, re.M)
        if not m:
            continue
        mods = m.group(1).split()
        bad = {}
        for mod in mods:
            name = mod.strip("'\"")
            if name in PACKAGE_NOT_MODULE:
                bad[mod] = PACKAGE_NOT_MODULE[name]
            elif ks and not any(module_exists(target, k, name) for k in ks):
                bad[mod] = None
        if not bad:
            continue
        fixed = [bad.get(x, x) if x in bad else x for x in mods]
        fixed = [x for x in dict.fromkeys(x for x in fixed if x)]
        words = []
        for k, v in bad.items():
            words.append(f"{k} is a package, not a module" + (f" (the module is {v})" if v else "") if k.strip("'\"") in PACKAGE_NOT_MODULE
                         else f"{k} isn't a module this install's kernel has")
        new_line = f"MODULES=({' '.join(fixed)})"
        out.append(Finding(f"The startup files' module list is wrong ({rel})",
                           "; ".join(words) + f". So the startup files (initramfs) can't be built and the "
                           f"graphics driver doesn't load early. It should read: {new_line}",
                           fix_label="Correct it and rebuild the startup files",
                           fix=_fix_modules(rel, m.group(0), new_line),
                           commands=[f"cp -a {ROOT}{rel} {ROOT}/var/lib/bromigos/fieldkit-backups/<when>-mkinitcpio{rel}",
                                     f"sed -i 's|^{m.group(0)}|{new_line}|' {ROOT}{rel}",
                                     f"arch-chroot {ROOT} mkinitcpio -P"],
                           touches=[rel, "/boot/initramfs-*.img"]))
    if not out:
        out.append(Finding("The startup files' module list is right", ok=True))
    return out


def _fix_modules(rel, old, new):
    def fix(target):
        text = system.read(target.path(rel))
        if old not in text:
            return f"{rel} changed since the check; nothing done."
        b = system.Backup(target, "mkinitcpio")
        b.write(rel, text.replace(old, new, 1))
        b.keep("/boot")
        msg = rebuild_initramfs(target)
        return f"Corrected {rel} (the old one is in {b.where()}). {msg}"
    return fix


def rebuild_initramfs(target):
    r = target.chroot(["mkinitcpio", "-P"], check=False, timeout=900)
    if r.returncode == 0:
        return "The startup files were built again."
    tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
    return "Building the startup files failed: " + " / ".join(tail)


def initramfs(target):
    """Each kernel in /boot has its startup file, newer than the kernel, and building them works."""
    out = []
    for kver, base in kernels(target).items():
        img = target.path(f"/boot/initramfs-{base}.img")
        kern = target.path(f"/boot/vmlinuz-{base}")
        if os.path.isfile(kern) and not os.path.isfile(img):
            out.append(Finding(f"The startup file for {base} is missing",
                               f"/boot has the kernel but not initramfs-{base}.img, so it can't start.",
                               fix_label="Build the startup files", fix=lambda t: rebuild_initramfs(t),
                               commands=[f"arch-chroot {ROOT} mkinitcpio -P"], touches=[f"/boot/initramfs-{base}.img"]))
        elif os.path.isfile(kern) and os.path.getmtime(img) + 1 < os.path.getmtime(kern):
            out.append(Finding(f"The startup file for {base} is older than its kernel",
                               "An update changed the kernel but building its startup file didn't finish.",
                               fix_label="Build the startup files", fix=lambda t: rebuild_initramfs(t),
                               commands=[f"arch-chroot {ROOT} mkinitcpio -P"], touches=[f"/boot/initramfs-{base}.img"]))
    if not out:
        out.append(Finding("The startup files are there for every kernel", ok=True))
    return out


def installed_packages(target):
    r = system.run(["pacman", "--root", target.root, "-Q"], check=False)
    return dict(line.split(" ", 1) for line in r.stdout.splitlines() if " " in line)


def drivers(target):
    """NVIDIA's driver built for the kernel that's installed: the prebuilt one matching, or DKMS
    having built its modules for each kernel."""
    out = []
    pkgs = installed_packages(target)
    nv = [p for p in pkgs if p.startswith("nvidia") and (p.endswith("-dkms") or p in ("nvidia", "nvidia-open", "nvidia-lts", "nvidia-open-lts"))]
    if not nv:
        return [Finding("No NVIDIA driver to check", ok=True)]
    for kver, base in kernels(target).items():
        if not module_exists(target, kver, "nvidia"):
            dkms = any(p.endswith("-dkms") for p in nv)
            out.append(Finding(f"The NVIDIA driver isn't built for the kernel {kver}",
                               f"{', '.join(nv)} is installed, but kernel {kver} ({base}) has no nvidia module. "
                               + ("DKMS didn't finish building it after an update." if dkms else
                                  "The prebuilt driver is for a different kernel version than the one installed."),
                               fix_label="Build it now (DKMS)" if dkms else "",
                               fix=(lambda t, k=kver: _dkms(t, k)) if dkms else None,
                               commands=[f"arch-chroot {ROOT} dkms autoinstall -k {kver}", f"arch-chroot {ROOT} mkinitcpio -P"] if dkms else [],
                               touches=[f"/usr/lib/modules/{kver}/updates/dkms", "/boot/initramfs-*.img"] if dkms else []))
    if not out:
        out.append(Finding("The NVIDIA driver is built for every kernel", ok=True))
    return out


def _dkms(target, kver):
    r = target.chroot(["dkms", "autoinstall", "-k", kver], check=False, timeout=1800)
    if r.returncode != 0:
        return "DKMS couldn't build it: " + " / ".join((r.stdout + r.stderr).strip().splitlines()[-3:])
    return f"Built for {kver}. " + rebuild_initramfs(target)


def display_manager(target):
    """The login screen is set to start, and the machine starts to the desktop. An install
    without a desktop (bromigOS Server) has neither, on purpose."""
    if not os.path.exists(target.path("/usr/bin/sddm")):
        return [Finding("No desktop on this install (bromigOS Server, or a text-only system)", ok=True)]
    out = []
    dm = target.path("/etc/systemd/system/display-manager.service")
    if not os.path.lexists(dm):
        out.append(Finding("No login screen is set to start",
                           "display-manager.service isn't enabled, so the machine stops at a text console.",
                           fix_label="Turn the login screen on", fix=lambda t: _enable(t, "sddm.service"),
                           commands=[f"arch-chroot {ROOT} systemctl enable sddm.service"],
                           touches=["/etc/systemd/system/display-manager.service"]))
    else:
        out.append(Finding(f"The login screen starts: {os.path.basename(os.path.realpath(dm))}", ok=True))
    default = target.path("/etc/systemd/system/default.target")
    if os.path.lexists(default) and os.path.basename(os.readlink(default)) == "multi-user.target":
        out.append(Finding("It's set to start without the desktop",
                           "default.target is multi-user.target: text mode at every boot.",
                           fix_label="Start to the desktop again", fix=lambda t: _enable(t, None, "graphical.target"),
                           commands=[f"arch-chroot {ROOT} systemctl set-default graphical.target"],
                           touches=["/etc/systemd/system/default.target"]))
    return out


def _enable(target, unit=None, default=None):
    if unit:
        target.chroot(["systemctl", "enable", unit])
        return f"{unit} will start at the next boot."
    target.chroot(["systemctl", "set-default", default])
    return f"It starts to {default} again."


def black_screen(target):
    """Every check the black screen repair makes, in the order a person would look."""
    out = []
    out += display_manager(target)
    out += sddm_dropins(target)
    out += gpu_pins(target)
    out += mkinitcpio(target)
    out += initramfs(target)
    out += drivers(target)
    return out
