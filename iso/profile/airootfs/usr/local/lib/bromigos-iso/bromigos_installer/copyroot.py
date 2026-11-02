#!/usr/bin/env python3
"""Installing by copying the live system (docs/iso.md, "How installing works").

The medium's live system is the system it installs, so the installer copies it onto the disk
instead of installing every package again from a second copy of them. The offline store then
holds only what the live system doesn't have (the NVIDIA driver, the kernel headers, the
compiler, an edition's own packages); its package databases still list everything, so pacman
resolves an install as before, and finds the copied packages installed already.

At build time, inside the image's chroot (both media's customize_airootfs.sh):

  copyroot.py prep-begin    /etc as the packages left it (before the live user and the live
                            session's settings): what the installed system's /etc starts from
  copyroot.py prep-finish   what's the medium's own (the profile's overlay: the live hooks,
                            autologin, the installer), which package files the image lacks
                            (they're kept in the store, to put back), and the store pruned of
                            every package the image has installed as it is

At install time:

  the archinstall plugin (archinstall_copy.py) calls install() at archinstall's first package
  step: the live image copied onto the new system's mounts, /etc from the baseline, the
  medium's own files taken away, root's account as a fresh system's, a new machine ID and
  pacman keyring, the kernels on /boot, and the packages whose files the image lacks put back
  from the store. archinstall then installs the rest (from the store), skipping what's there.

  copyroot.py prune --target /mnt --strapped FILE [--with PKG]…
                            after archinstall: what an install from packages would have had
                            explicitly (archinstall's package steps, recorded by the plugin,
                            and --with) stays; the live system's own packages (the rescue
                            tools, archiso's hooks, archinstall) go, with what they alone needed
  copyroot.py check --target /mnt [--repair]
                            pacman -Qk on the new system: every package's files are there
                            (--repair: a package with missing files is installed again from
                            the store when the store has it)
"""
import argparse
import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import sys

COPY_DIR = "usr/local/share/bromigos-iso/copy"          # in the image (relative to its root)
STORE = "var/lib/bromigos/repo"
LIVE_ROOT = "/run/archiso/airootfs"                    # the image itself, as archiso mounted it

# the image's own and the running system's, never copied (rsync's --exclude, anchored at the root):
# the kernel's file systems and mounts, the store, /etc (from the baseline instead), the live
# user's and root's homes (an install's are its own), /boot (the kernels are put there; it's
# FAT on UEFI, which takes no owners), archiso's version file
COPY_EXCLUDES = ["/dev/*", "/proc/*", "/sys/*", "/run/*", "/tmp/*", "/mnt/*", "/boot", "/etc",
                 "/home/*", "/root/*", "/" + STORE, "/version", "/var/spool/mail/live",
                 "/var/lib/AccountsService/users/live", "/var/lib/AccountsService/icons/live",
                 "/lost+found"]
# what the baseline of /etc leaves out: the pacman keyring (each system makes its own), the
# machine ID (each its own), pacman's leftovers
BASELINE_EXCLUDES = ["etc/pacman.d/gnupg", "etc/machine-id", "*.pacnew", "*.pacsave"]
# package files the image never has, whatever the profile: mkarchiso empties /boot (the
# kernels and the microcode go onto the medium), the copy leaves out the homes
MISSING_PREFIXES = ("boot/", "root/", "home/")
# the accounts: kept from the baseline (the system users' IDs are the copied files' owners),
# with root's shell and password as a fresh system's
ACCOUNTS = {"etc/passwd", "etc/group", "etc/shadow", "etc/gshadow"}
# package files mkarchiso changes after the packages are in (it adds the image's name to
# os-release): their package's own copy goes on the installed system
CHANGED_BY_BUILD = ["usr/lib/os-release"]
# kept in the store whatever the image has: the installer reads its files (pacman's stock
# mirrorlist for the installed system)
KEEP_IN_STORE = {"pacman-mirrorlist"}


def say(*a):
    print(*a, flush=True)


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


# ── pacman's local database ─────────────────────────────────────────────────────────────
def local_db(root):
    """{name: {"version", "arch", "files": [paths, dirs end in /], "reason"}} from ROOT's pacman."""
    base = os.path.join(root, "var/lib/pacman/local")
    out = {}
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return out
    for d in entries:
        desc = os.path.join(base, d, "desc")
        if not os.path.isfile(desc):
            continue
        fields = _sections(_read(desc))
        name = (fields.get("NAME") or [d.rsplit("-", 2)[0]])[0]
        files = []
        fp = os.path.join(base, d, "files")
        if os.path.isfile(fp):
            files = _sections(_read(fp)).get("FILES", [])
        out[name] = {"version": (fields.get("VERSION") or [""])[0], "arch": (fields.get("ARCH") or [""])[0],
                     "files": files, "dir": d}
    return out


def _sections(text):
    out, key = {}, None
    for line in text.split("\n"):
        m = re.fullmatch(r"%([A-Z0-9]+)%", line)
        if m:
            key = m.group(1)
            out[key] = []
        elif key and line:
            out[key].append(line)
    return out


def local_names(root):
    """The installed packages' names (from their database folders' names: name-version-release)."""
    try:
        return {d.rsplit("-", 2)[0] for d in os.listdir(os.path.join(root, "var/lib/pacman/local")) if d.count("-") >= 2}
    except OSError:
        return set()


# ── pacman.conf's NoExtract ─────────────────────────────────────────────────────────────
def noextract(conf_path):
    """NoExtract's patterns, in order, from a pacman.conf."""
    pats = []
    try:
        for line in _read(conf_path).split("\n"):
            line = line.split("#", 1)[0].strip()
            if line.startswith("NoExtract"):
                k, _, v = line.partition("=")
                if k.strip() == "NoExtract":
                    pats += v.split()
    except OSError:
        pass
    return pats


def noextracted(path, pats):
    """Whether pacman leaves PATH out (alpm's own rule: the last pattern that matches decides; ! keeps)."""
    for p in reversed(pats):
        neg = p.startswith("!")
        if fnmatch.fnmatchcase(path, p[1:] if neg else p):
            return not neg
    return False


# ── the store ───────────────────────────────────────────────────────────────────────────
def store_files(store):
    """{file name: full path} of every package file in the store."""
    out = {}
    for dirpath, _, files in os.walk(store):
        for f in files:
            if ".pkg.tar." in f and not f.endswith(".sig"):
                out[f] = os.path.join(dirpath, f)
    return out


def package_file(store_index, name, version, arch):
    for ext in ("zst", "xz", "gz"):
        f = store_index.get(f"{name}-{version}-{arch}.pkg.tar.{ext}")
        if f:
            return f
    return None


# ── build time: in the image's chroot ───────────────────────────────────────────────────
def prep_begin(root="/"):
    """/etc as the packages left it, before the customize script makes the live user and the
    live session's settings: the installed system's /etc starts from this."""
    d = os.path.join(root, COPY_DIR)
    os.makedirs(d, exist_ok=True)
    args = ["tar", "--xattrs", "--acls", "-cpf", os.path.join(d, "etc.tar"), "-C", root]
    args += [f"--exclude={x}" for x in BASELINE_EXCLUDES] + ["etc"]
    subprocess.run(args, check=True)
    say(f"copyroot: /etc's baseline: {os.path.getsize(os.path.join(d, 'etc.tar')) // 1024} KiB")


def read_overlay(path):
    """The profile's overlay as iso/build-in-container.sh listed it: (path, kind) with kind d for a folder."""
    out = []
    try:
        for line in _read(path).split("\n"):
            line = line.rstrip("\n")
            if not line:
                continue
            p, _, kind = line.partition("\t")
            out.append((p.strip("/"), kind or "f"))
    except OSError:
        pass
    return out


def classify_overlay(overlay, db):
    """What the installed system does with each of the overlay's paths: remove (a file of the
    medium's own), trees (a folder of its own, with all in it), pristine (a package's file the
    overlay replaced: the package's own goes back)."""
    owned_files, owned_dirs = set(), set()
    for meta in db.values():
        for f in meta["files"]:
            (owned_dirs if f.endswith("/") else owned_files).add(f.rstrip("/"))
    # every ancestor of an owned path holds something a package needs
    holds = set()
    for p in owned_files | owned_dirs:
        while "/" in p:
            p = p.rsplit("/", 1)[0]
            holds.add(p)
    skip = (STORE, "root", COPY_DIR)
    remove, trees, pristine = [], [], []
    for p, kind in sorted(overlay, key=lambda x: x[0]):
        if not p or any(p == s or p.startswith(s + "/") for s in skip):
            continue
        if any(p.startswith(t + "/") for t in trees):
            continue
        if kind == "d":
            if p in owned_dirs or p in holds:
                continue
            trees.append(p)
        elif p in owned_files:
            if p not in ACCOUNTS:
                pristine.append(p)
        else:
            remove.append(p)
    return remove, trees, pristine


def missing_packages(root, db, keep_pats):
    """The packages some of whose files the installed system wouldn't get from the image: left
    out of it by the build's NoExtract (and not left out of the installed system's), under /boot
    (mkarchiso empties it), or in the homes. They're kept in the store and installed again."""
    out = {}
    for name, meta in db.items():
        for f in meta["files"]:
            if f.endswith("/") or noextracted(f, keep_pats):
                continue
            if f.startswith(MISSING_PREFIXES) or not os.path.lexists(os.path.join(root, f)):
                out.setdefault(name, f)
                break
    return out


def owned_dirs_under(root, db, prefixes=MISSING_PREFIXES):
    """Package folders the copy doesn't bring (in /boot, the homes): (path, mode, uid, gid)."""
    out = {}
    for meta in db.values():
        for f in meta["files"]:
            if f.endswith("/") and f.startswith(prefixes):
                p = f.rstrip("/")
                try:
                    st = os.lstat(os.path.join(root, p))
                except OSError:
                    continue
                out[p] = [stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid]
    return [[p] + v for p, v in sorted(out.items())]


def prep_finish(root="/"):
    d = os.path.join(root, COPY_DIR)
    os.makedirs(d, exist_ok=True)
    db = local_db(root)
    overlay = read_overlay(os.path.join(d, "overlay.txt"))
    remove, trees, pristine = classify_overlay(overlay, db)
    owners = {}
    for name, meta in db.items():
        for f in meta["files"]:
            owners[f] = name
    store = os.path.join(root, STORE)
    index = store_files(store)
    # the packages' own copies of what the overlay and the build changed
    pdir = os.path.join(d, "pristine")
    saved = []
    for p in pristine + [x for x in CHANGED_BY_BUILD if x in owners]:
        meta = db[owners[p]]
        pkg = package_file(index, owners[p], meta["version"], meta["arch"])
        if not pkg:
            raise SystemExit(f"copyroot: {p} is {owners[p]}'s, whose package isn't in the store")
        os.makedirs(pdir, exist_ok=True)
        subprocess.run(["bsdtar", "-xpf", pkg, "-C", pdir, p], check=True)
        saved.append(p)
    keep_pats = noextract(os.path.join(root, "etc/pacman.conf"))
    repair = missing_packages(root, db, keep_pats)
    dirs = owned_dirs_under(root, db)
    # the store: every package the image has, as it has it, goes (its database entry stays)
    before = sum(os.path.getsize(f) for f in index.values())
    pruned, freed = [], 0
    for name, meta in db.items():
        if name in repair or name in KEEP_IN_STORE:
            continue
        pkg = package_file(index, name, meta["version"], meta["arch"])
        if not pkg:
            continue
        freed += os.path.getsize(pkg)
        os.remove(pkg)
        if os.path.exists(pkg + ".sig"):
            os.remove(pkg + ".sig")
        pruned.append(name)
    manifest = {"schema": 1, "remove": remove, "trees": trees, "pristine": saved, "repair": sorted(repair),
                "dirs": dirs, "live_packages": sorted(db), "noextract": keep_pats, "pruned": sorted(pruned)}
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    mib = 1 << 20
    say(f"copyroot: the medium's own: {len(remove)} files, {len(trees)} folders; {len(saved)} package files put back as they were")
    say(f"copyroot: kept in the store to install again ({len(repair)}): "
        + ", ".join(f"{n} ({f})" for n, f in sorted(repair.items())))
    say(f"copyroot: the store: {before // mib} MiB, less {freed // mib} MiB of {len(pruned)} packages the image has: "
        f"{(before - freed) // mib} MiB")


# ── install time ────────────────────────────────────────────────────────────────────────
def source_root():
    """The image as built (archiso's squashfs mount): nothing the live session changed."""
    if os.environ.get("BROMIGOS_ISO_LIVE_ROOT"):
        return os.environ["BROMIGOS_ISO_LIVE_ROOT"]
    if os.path.ismount(LIVE_ROOT) or os.path.isdir(os.path.join(LIVE_ROOT, "usr")):
        return LIVE_ROOT
    return "/"


_live = {}


def offline_has(name, store=None, src=None):
    """Whether the medium installs NAME with no network: its package file is in the store, or
    (a medium that installs by copying) the live image has it installed. The store's databases
    list both."""
    store = store or os.environ.get("BROMIGOS_ISO_REPO_DIR", "/" + STORE)
    pat = re.compile(re.escape(name) + r"-[^-]+-[^-]+-[^-]+\.pkg\.tar\.(zst|xz)$")
    for dirpath, _, files in os.walk(store):
        if any(pat.match(f) for f in files):
            return True
    src = src or source_root()
    if src not in _live:
        _live[src] = local_names(src) if available(src) else set()
    return name in _live[src]


def manifest(src=None):
    src = src or source_root()
    return json.loads(_read(os.path.join(src, COPY_DIR, "manifest.json")))


def available(src=None):
    """Whether this medium installs by copying (a build with the copy's manifest)."""
    return os.path.isfile(os.path.join(src or source_root(), COPY_DIR, "manifest.json"))


# the new system's own mounts whose insides are never looked through (a reinstall's kept home
# can be big): everything in them counts as there before the copy
OPAQUE = ("home", "srv", "boot", ".snapshots", "var/log", "var/cache/pacman/pkg", "var/lib/containers",
          "var/lib/rancher", "var/lib/bromigos/server")


class Existing(set):
    """The paths under TARGET before the copy (archinstall's mounts and first files), relative."""
    def __contains__(self, rel):
        return set.__contains__(self, rel) or any(rel.startswith(o + "/") for o in OPAQUE if set.__contains__(self, o))


def existing(target):
    out = Existing()
    for dirpath, dirs, files in os.walk(target):
        rel = os.path.relpath(dirpath, target)
        if rel != ".":
            out.add(rel)
            if rel in OPAQUE:
                dirs[:] = []
                continue
        for f in files + [x for x in dirs if os.path.islink(os.path.join(dirpath, x))]:
            out.add(os.path.normpath(os.path.join(rel, f)))
    return out


def rsync(src, target, progress=say):
    """The image onto the new system's mounts: owners, permissions, hard links, ACLs and
    capabilities as they are; nothing already there replaced (archinstall's files, a kept /home)."""
    args = ["rsync", "-aHAX", "--numeric-ids", "--ignore-existing", "--info=progress2", "--no-inc-recursive"]
    args += [f"--exclude={x}" for x in COPY_EXCLUDES] + [src.rstrip("/") + "/", target.rstrip("/") + "/"]
    say("+ " + " ".join(args))
    import tempfile
    with tempfile.TemporaryFile("w+") as errf:
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errf, text=True, bufsize=1)
        last, buf = -5, ""
        while True:
            ch = p.stdout.read(256)
            if not ch:
                break
            buf += ch
            parts = re.split(r"[\r\n]", buf)
            buf = parts.pop()
            for part in parts:
                m = re.search(r"\s(\d{1,3})%\s", part)
                if m and int(m.group(1)) >= last + 2:
                    last = int(m.group(1))
                    progress(f"Copying the live system: {last}%")
        rc = p.wait()
        errf.seek(0)
        err = errf.read()
    if err.strip():
        say("rsync: " + err.strip()[-2000:])
    if rc not in (0, 24):                     # 24: a file vanished while it was read (a live system's)
        raise RuntimeError(f"copying the live system failed (rsync {rc}): {err.strip()[-600:]}")
    progress("Copying the live system: 100%")


def _remove(target, rel, pre):
    """Remove TARGET/REL and what's in it, except what was there before the copy (a mount)."""
    if rel in pre:
        full = os.path.join(target, rel)
        if os.path.isdir(full) and not os.path.islink(full):
            for c in os.listdir(full):
                _remove(target, os.path.join(rel, c), pre)
        return
    if any(p.startswith(rel + "/") for p in set(pre)):
        for c in os.listdir(os.path.join(target, rel)):
            _remove(target, os.path.join(rel, c), pre)
        try:
            os.rmdir(os.path.join(target, rel))
        except OSError:
            pass
        return
    full = os.path.join(target, rel)
    if os.path.islink(full) or not os.path.isdir(full):
        if os.path.lexists(full):
            os.unlink(full)
    else:
        shutil.rmtree(full)


def accounts(target):
    """root's account as a fresh system's: bash, and no password until the installer sets one."""
    p = os.path.join(target, "etc/passwd")
    lines = _read(p).split("\n")
    for i, line in enumerate(lines):
        f = line.split(":")
        if len(f) == 7 and f[0] == "root":
            f[6] = "/usr/bin/bash"
            lines[i] = ":".join(f)
    open(p, "w").write("\n".join(lines))
    s = os.path.join(target, "etc/shadow")
    lines = _read(s).split("\n")
    for i, line in enumerate(lines):
        f = line.split(":")
        if len(f) >= 2 and f[0] == "root" and f[1] in ("", "!", "!*"):
            f[1] = "*"
            lines[i] = ":".join(f)
    mode = stat.S_IMODE(os.stat(s).st_mode)
    open(s, "w").write("\n".join(lines))
    os.chmod(s, mode)


def kernels_on_boot(target):
    """Each kernel's image on /boot as its package's hook puts it (mkinitcpio's install script)."""
    mods = os.path.join(target, "usr/lib/modules")
    done = []
    for k in sorted(os.listdir(mods)) if os.path.isdir(mods) else []:
        pb, img = os.path.join(mods, k, "pkgbase"), os.path.join(mods, k, "vmlinuz")
        if os.path.isfile(pb) and os.path.isfile(img):
            name = _read(pb).strip()
            dst = os.path.join(target, "boot", f"vmlinuz-{name}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(img, dst)
            try:
                os.chmod(dst, 0o644)
            except OSError:
                pass
            done.append(name)
    return done


def pacstrap(target, pkgs, needed=False):
    """pacstrap as archinstall runs it (the live system's pacman.conf: the medium's store)."""
    args = ["pacstrap", "-C", "/etc/pacman.conf", "-G", "-M", target] + list(pkgs) + ["--noconfirm"]
    if needed:
        args.append("--needed")
    say("+ " + " ".join(args))
    subprocess.run(args, check=True)


def install(target, src=None, run=subprocess.run):
    """The copy, at archinstall's first package step (the disk is laid out and mounted at TARGET)."""
    src = src or source_root()
    m = manifest(src)
    pre = existing(target)
    say(f"copyroot: copying the live system ({src}) onto {target}")
    rsync(src, target)
    # /etc: the packages' (the baseline), around what archinstall wrote already
    say("copyroot: /etc from the image's baseline")
    run(["tar", "--xattrs", "--acls", "--numeric-owner", "--skip-old-files", "-xpf",
         os.path.join(src, COPY_DIR, "etc.tar"), "-C", target], check=True)
    # the medium's own: the live hooks, autologin, the installer, the store's folder
    for rel in m["remove"] + m["trees"] + [COPY_DIR]:
        if os.path.lexists(os.path.join(target, rel)):
            _remove(target, rel, pre)
    for rel in m["pristine"]:
        if rel in pre:
            continue
        s, d = os.path.join(src, COPY_DIR, "pristine", rel), os.path.join(target, rel)
        if os.path.lexists(d):
            os.unlink(d)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d, follow_symlinks=False)
    for p, mode, uid, gid in m["dirs"]:
        d = os.path.join(target, p)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            try:
                os.chmod(d, mode)
                os.chown(d, uid, gid)
            except OSError:
                pass                         # /boot on FAT: no owners
    accounts(target)
    # each system its own machine ID and pacman keyring
    mid = os.path.join(target, "etc/machine-id")
    if os.path.lexists(mid):
        os.unlink(mid)
    run(["systemd-machine-id-setup", f"--root={target}"], check=True)
    gpg = os.path.join(target, "etc/pacman.d/gnupg")
    run(["pacman-key", "--gpgdir", gpg, "--init"], check=True, stdout=subprocess.DEVNULL)
    run(["pacman-key", "--gpgdir", gpg, "--populate"], check=True, stdout=subprocess.DEVNULL)
    # its agent goes, so nothing holds the new system's mounts
    run(["gpgconf", "--homedir", gpg, "--kill", "all"], check=False)
    say(f"copyroot: the kernels on /boot: {', '.join(kernels_on_boot(target)) or 'none'}")
    # the packages whose files the image doesn't have (the microcode on /boot, say), from the store
    have = local_names(target)
    again = [p for p in m["repair"] if p in have]
    if again:
        pacstrap(target, again)
    say("copyroot: the live system is on the disk; the rest comes from the store")


def chroot(target, *argv, check=True, capture=False):
    r = subprocess.run(["arch-chroot", target, *argv], text=True, capture_output=capture)
    if check and r.returncode != 0:
        if capture:
            say((r.stdout or "")[-2000:] + (r.stderr or "")[-2000:])
        raise RuntimeError(f"{' '.join(argv[:3])}… failed ({r.returncode}) in {target}")
    return r


def prune(target, explicit, keep_also=()):
    """What an install from packages has: the packages it installed explicitly and what they
    need. Everything else the copy brought (the live system's own) goes."""
    have = local_names(target)
    want = (set(explicit) | set(keep_also)) & have
    unknown = sorted((set(explicit) | set(keep_also)) - have)
    if unknown:
        say(f"copyroot: asked for but not installed (provided by another, or a group): {' '.join(unknown)}")
    chroot(target, "pacman", "-D", "--asdeps", *sorted(have), capture=True)
    chroot(target, "pacman", "-D", "--asexplicit", *sorted(want), capture=True)
    gone = []
    for _ in range(20):
        r = chroot(target, "pacman", "-Qttdq", check=False, capture=True)
        orphans = [x for x in r.stdout.split() if x]
        if not orphans:
            break
        chroot(target, "pacman", "-Rns", "--noconfirm", *orphans, capture=True)
        gone += orphans
    say(f"copyroot: {len(want)} packages installed explicitly; {len(gone)} of the live system's own removed: {' '.join(sorted(gone))}")
    return gone


def check(target, repair=False, src=None):
    """pacman -Qk on the new system; with REPAIR, a package missing files is installed again from
    the store when the store has it. Returns {package: [missing files]}."""
    def qk():
        r = subprocess.run(["pacman", "--root", target, "--dbpath", os.path.join(target, "var/lib/pacman"),
                            "--config", os.path.join(target, "etc/pacman.conf"), "-Qkq"],
                           capture_output=True, text=True)
        out = {}
        for line in r.stdout.splitlines():
            name, _, path = line.partition(" ")
            path = "/" + os.path.relpath(path, target) if path.startswith(target) else path
            out.setdefault(name, []).append(path)
        return out
    bad = qk()
    if bad and repair:
        index = store_files(os.path.join(src or source_root(), STORE))
        db = local_db(target)
        fix = [n for n in bad if n in db and package_file(index, n, db[n]["version"], db[n]["arch"])]
        if fix:
            pacstrap(target, fix)
            bad = qk()
    for name, paths in sorted(bad.items()):
        say(f"copyroot: pacman -Qk: {name} is missing {len(paths)} files ({', '.join(paths[:3])})")
    if not bad:
        say("copyroot: pacman -Qk: every package's files are there")
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prep-begin")
    sub.add_parser("prep-finish")
    p = sub.add_parser("prune")
    p.add_argument("--target", default="/mnt")
    p.add_argument("--strapped", required=True, help="archinstall's package steps, one package per line")
    p.add_argument("--with", dest="extras", action="append", default=[])
    c = sub.add_parser("check")
    c.add_argument("--target", default="/mnt")
    c.add_argument("--repair", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "prep-begin":
        prep_begin()
    elif a.cmd == "prep-finish":
        prep_finish()
    elif a.cmd == "prune":
        names = [x.strip() for x in open(a.strapped).read().split() if x.strip()]
        prune(a.target, names, a.extras)
    elif a.cmd == "check":
        return 1 if check(a.target, a.repair) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
