//! A snapshot around every `bromigos update`, and undoing one.
//!
//! On a btrfs root with snapper, every update is bracketed by a *pre* and a *post*
//! snapshot of `/`. `bromigos update` makes the pair itself (`snapper create -t pre/post`,
//! described "bromigos update", which is how GRUB's snapshot list names it: docs/boot.md),
//! and tells Arch's `snap-pac`, which brackets every other pacman transaction, to skip this
//! one (`SNAP_PAC_SKIP`). A pair around nothing (no package changed) is deleted again. The
//! pair's numbers go into `~/.local/state/bromigos/updates.jsonl` with the packages that
//! changed.
//!
//! `bromigos update --rollback [PRE]` undoes an update in place: `snapper undochange
//! PRE..POST` puts every file `/` had before the update back (pacman's database included),
//! after showing what that touches and asking. It works on any btrfs layout (no default-
//! subvolume swap), so the running system keeps going; a reboot follows when the kernel
//! was part of it. Booting *around* a bad update (the system doesn't come up at all) is the
//! boot loader's job: grub-btrfs lists the snapshots in GRUB's menu, limine-snapper-sync
//! in limine's; `bromigos rollback setup` installs whichever applies (docs/update.md has
//! the matrix). Not btrfs, or no snapper: the update says so and goes on without.
//!
//! The update reads snapper's list as the user, so the `root` configuration allows the
//! group `wheel` (`ALLOW_GROUPS`, with `SYNC_ACL` for `/.snapshots`): `bromigos rollback
//! setup` sets that on a configuration it makes, and `bromigos rollback allow` on one that
//! exists. In an install chroot (no system bus) snapper runs with `--no-dbus`, so the ISO's
//! installer sets up rollback with the same `bromigos rollback setup`.
//!
//! Adapted from Omarchy (a snapshot before each update, rollback from the boot menu),
//! for a packaged system that may run on any file system.

use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::install::Runner;
use crate::paths::Paths;

/// snapper's configuration for `/`.
pub const CONFIG: &str = "root";

/// The group the `root` configuration lets list its snapshots: the admins (archinstall's
/// users are in it; it's sudo's group on Arch).
pub const ALLOW_GROUP: &str = "wheel";

/// grub-btrfs's initramfs hook: a snapshot booted from GRUB's menu is read-only, and the
/// hook lays a writable overlay (in memory) on it, so the system comes up.
pub const OVERLAY_HOOK: &str = "grub-btrfs-overlayfs";

/// systemd's Boot Loader Interface variable: which loader booted this machine (systemd-boot
/// sets it, and GRUB's `bli` module, which grub-mkconfig loads on UEFI). Every user may read
/// it, unlike a `/boot` that archinstall mounts 0700.
pub const LOADER_INFO: &str =
    "/sys/firmware/efi/efivars/LoaderInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f";

/// The system bus. Missing in an install chroot: snapper can't reach snapperd there.
pub const SYSTEM_BUS: &str = "/run/dbus/system_bus_socket";

// ------------------------------------------------------------------ the file system

/// What `detect` and `setup_plan` read of the file system: the real one ([`RootFs`]), or a
/// stand-in in tests.
pub trait Files {
    /// Whether `path` exists and can be seen (a file under a directory the user may not
    /// search, such as a `/boot` mounted 0700, can't).
    fn exists(&self, path: &str) -> bool;
    /// Its contents (invalid UTF-8 replaced), None when it's missing or unreadable.
    fn read(&self, path: &str) -> Option<String>;
    /// The names in a directory, sorted; none when it's missing or unreadable.
    fn list(&self, dir: &str) -> Vec<String>;
}

/// The root file system. `BROMIGOS_FS_ROOT` (tests, a dry run against another root) moves
/// `/` elsewhere.
pub struct RootFs;

impl RootFs {
    fn path(path: &str) -> PathBuf {
        std::env::var_os("BROMIGOS_FS_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("/"))
            .join(path.trim_start_matches('/'))
    }
}

impl Files for RootFs {
    fn exists(&self, path: &str) -> bool {
        Self::path(path).exists()
    }
    fn read(&self, path: &str) -> Option<String> {
        fs::read(Self::path(path))
            .ok()
            .map(|b| String::from_utf8_lossy(&b).into_owned())
    }
    fn list(&self, dir: &str) -> Vec<String> {
        let mut names: Vec<String> = fs::read_dir(Self::path(dir))
            .into_iter()
            .flatten()
            .flatten()
            .filter_map(|e| e.file_name().into_string().ok())
            .collect();
        names.sort();
        names
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum Bootloader {
    Grub,
    Limine,
    SystemdBoot,
    Unknown,
}

/// What this machine can do (`detect`).
#[derive(Debug, Clone, Serialize)]
pub struct Env {
    /// The root file system's type (`btrfs`, `ext4`, …).
    pub fs: String,
    pub btrfs: bool,
    /// snapper is installed.
    pub snapper: bool,
    /// snapper has a configuration for `/` (CONFIG).
    pub config: bool,
    /// snap-pac's hooks bracket every pacman transaction.
    pub snap_pac: bool,
    pub bootloader: Bootloader,
    /// Snapshots can be booted from the boot loader's menu (grub-btrfs, limine-snapper-sync).
    pub boot_menu: bool,
    /// `/boot` is its own file system (a rollback of `/` leaves the kernel image there).
    pub boot_separate: bool,
    /// GRUB: the initramfs's HOOKS have grub-btrfs-overlayfs, so a snapshot booted from the
    /// menu comes up writable (in memory). False elsewhere.
    pub boot_overlay: bool,
    /// GRUB without the hook: `rollback setup` can add it (mkinitcpio's HOOKS, one line, not a
    /// systemd initramfs, which runs no such hook).
    pub overlay_fixable: bool,
    /// This user may list root's snapshots (snapper's ALLOW_USERS, ALLOW_GROUPS): the update
    /// reads snap-pac's pair as the user to record it for `--rollback`.
    pub readable: bool,
    /// Not the booted system (an install chroot), or no system bus: snapper runs with
    /// `--no-dbus` (as root), systemctl reads the units' files, and services are enabled,
    /// not started. arch-chroot binds the live system's /run in, so a bus there is the live
    /// system's, never this root's.
    pub offline: bool,
    /// This boot is a snapshot chosen from the boot menu (`--rollback` makes it the root).
    pub booted: Option<Booted>,
}

impl Env {
    /// Updates are bracketed by snapshots.
    pub fn snapshots(&self) -> bool {
        self.btrfs && self.snapper && self.config
    }

    /// Updates are snapshotted but can't be recorded for `--rollback` (the user may not
    /// list the snapshots).
    pub fn unrecorded(&self) -> bool {
        self.snapshots() && !self.readable && !self.offline
    }

    /// Something `bromigos rollback setup` would do here.
    pub fn needs_setup(&self) -> bool {
        self.btrfs
            && (!self.snapshots()
                || !self.boot_menu && self.bootloader != Bootloader::SystemdBoot
                || self.bootloader == Bootloader::Grub
                    && !self.boot_overlay
                    && self.overlay_fixable
                || self.unrecorded())
    }

    /// One line for `bromigos update --check` and `bromigos rollback status`.
    pub fn summary(&self) -> String {
        if let Some(b) = &self.booted {
            return format!(
                "this boot is snapshot {} from the boot menu: bromigos update --rollback makes \
                 it the root",
                b.number
            );
        }
        if !self.btrfs {
            return format!("none: / is {} (snapshots need btrfs)", self.fs);
        }
        if !self.snapper || !self.config {
            return "none: btrfs, but snapper has no configuration for / (bromigos rollback setup)"
                .into();
        }
        let how = if self.snap_pac {
            "bromigos update's own pre/post pair (snap-pac's around any other pacman run)"
        } else {
            "bromigos update's own pre/post pair"
        };
        let boot = match (self.bootloader, self.boot_menu) {
            (Bootloader::Grub, true) if self.boot_overlay => {
                "boot menu: GRUB lists them (grub-btrfs)".to_owned()
            }
            (Bootloader::Grub, true) if self.overlay_fixable => "boot menu: GRUB lists them \
                (grub-btrfs), but one booted from it is read-only (no grub-btrfs-overlayfs hook: \
                bromigos rollback setup)"
                .to_owned(),
            (Bootloader::Grub, true) => "boot menu: GRUB lists them (grub-btrfs); one booted from \
                it comes up read-only (this initramfs takes no grub-btrfs-overlayfs: bromigos \
                rollback setup --dry-run says why)"
                .to_owned(),
            (Bootloader::Grub, false) => {
                "boot menu: not yet (grub-btrfs; bromigos rollback setup)".to_owned()
            }
            (Bootloader::Limine, true) => {
                "boot menu: limine lists them (limine-snapper-sync)".to_owned()
            }
            (Bootloader::Limine, false) => {
                "boot menu: not yet (limine-snapper-sync; bromigos rollback setup)".to_owned()
            }
            (Bootloader::SystemdBoot, _) => {
                "boot menu: none (systemd-boot has no snapshot entries)".to_owned()
            }
            (Bootloader::Unknown, _) => "boot menu: unknown boot loader".to_owned(),
        };
        let rec = if self.unrecorded() {
            "; updates aren't recorded for --rollback: you may not list root's snapshots \
             (bromigos rollback allow)"
        } else {
            ""
        };
        format!("{how}; {boot}{rec}")
    }
}

fn installed(runner: &mut dyn Runner, pkg: &str) -> bool {
    runner.query(&["pacman", "-Qq", pkg]).0 == 0
}

/// The boot loader: what `/boot` shows, when it can be read; else which loader booted the
/// machine (UEFI's LoaderInfo; not in a chroot, where it's the live medium's); else GRUB's
/// own files outside `/boot`, `/etc/default/grub` and the grub package. archinstall mounts
/// `/boot` 0700, so as the user nothing in it shows.
pub fn bootloader(runner: &mut dyn Runner, files: &dyn Files, offline: bool) -> Bootloader {
    if files.exists("/boot/grub/grub.cfg") {
        return Bootloader::Grub;
    }
    if files.exists("/boot/limine.conf")
        || files.exists("/boot/limine/limine.conf")
        || files.exists("/boot/EFI/limine/limine.conf")
        || installed(runner, "limine")
    {
        return Bootloader::Limine;
    }
    if files.exists("/boot/loader/loader.conf") || files.exists("/efi/loader/loader.conf") {
        return Bootloader::SystemdBoot;
    }
    if let Some(info) = files.read(LOADER_INFO).filter(|_| !offline) {
        // 4 bytes of attributes, then UTF-16LE: the name's letters with NULs between them
        let name = info
            .chars()
            .filter(|c| c.is_ascii_graphic() || *c == ' ')
            .collect::<String>()
            .to_ascii_lowercase();
        if name.contains("grub") {
            return Bootloader::Grub;
        }
        if name.contains("systemd-boot") {
            return Bootloader::SystemdBoot;
        }
        if name.contains("limine") {
            return Bootloader::Limine;
        }
    }
    if files.exists("/etc/default/grub") && installed(runner, "grub") {
        return Bootloader::Grub;
    }
    Bootloader::Unknown
}

/// The mount this process sees as `/` in a mountinfo (the last one there: mounts stack).
fn root_mount(mountinfo: &str) -> Option<String> {
    mountinfo.lines().rev().find_map(|l| {
        let f: Vec<&str> = l.split_whitespace().collect();
        (f.get(4) == Some(&"/")).then(|| f[0].to_owned())
    })
}

/// Chrooted into another root than the booted system's (an install chroot): the mount this
/// process sees as `/` isn't PID 1's. Any user may read both (no /proc/1/root, which needs
/// root), so it holds under `sudo -u`.
pub fn chrooted(files: &dyn Files) -> bool {
    match (
        files
            .read("/proc/self/mountinfo")
            .as_deref()
            .and_then(root_mount),
        files
            .read("/proc/1/mountinfo")
            .as_deref()
            .and_then(root_mount),
    ) {
        (Some(me), Some(init)) => me != init,
        _ => false,
    }
}

/// Whether a unit is enabled: systemd's answer, or offline its files' (`--root=/`: in a
/// chroot systemctl would ask the live system's systemd).
fn enabled(runner: &mut dyn Runner, offline: bool, unit: &str) -> bool {
    let args: &[&str] = if offline {
        &["systemctl", "--root=/", "is-enabled", unit]
    } else {
        &["systemctl", "is-enabled", unit]
    };
    runner.query(args).1.trim() == "enabled"
}

/// snapper's configurations as its files say (no snapperd needed): `SNAPPER_CONFIGS` in
/// `/etc/conf.d/snapper` names CONFIG and its file is there.
fn configured(files: &dyn Files) -> bool {
    files.exists(&format!("/etc/snapper/configs/{CONFIG}"))
        && files.read("/etc/conf.d/snapper").is_some_and(|t| {
            t.lines().any(|l| {
                l.trim_start()
                    .strip_prefix("SNAPPER_CONFIGS=")
                    .is_some_and(|v| {
                        v.trim()
                            .trim_matches('"')
                            .split_whitespace()
                            .any(|c| c == CONFIG)
                    })
            })
        })
}

/// Looks at the machine. `files` answers for paths, so tests can stand in for `/`.
pub fn detect(runner: &mut dyn Runner, files: &dyn Files) -> Env {
    let fs = runner
        .query(&["findmnt", "-no", "FSTYPE", "/"])
        .1
        .trim()
        .to_owned();
    let btrfs = fs == "btrfs";
    let chroot = chrooted(files);
    let offline = chroot || !files.exists(SYSTEM_BUS);
    let snapper = runner.query(&["snapper", "--version"]).0 == 0;
    let config = snapper && {
        let (code, out) = if chroot {
            // the bus here is the live system's: its snapperd mustn't be asked; the files say
            (1, String::new())
        } else {
            runner.query(&[
                "snapper",
                "--no-headers",
                "--csvout",
                "list-configs",
                "--columns",
                "config",
            ])
        };
        if code == 0 {
            out.lines().any(|l| l.trim() == CONFIG)
        } else {
            configured(files)
        }
    };
    let readable = config
        && !offline
        && runner
            .query(&[
                "snapper",
                "-c",
                CONFIG,
                "--no-headers",
                "--csvout",
                "list",
                "--columns",
                "number",
            ])
            .0
            == 0;
    let snap_pac = files.exists("/usr/share/libalpm/hooks/05-snap-pac-pre.hook");
    let bootloader = bootloader(runner, files, offline);
    let boot_menu = match bootloader {
        Bootloader::Grub => {
            installed(runner, "grub-btrfs") && enabled(runner, offline, "grub-btrfsd.service")
        }
        Bootloader::Limine => installed(runner, "limine-snapper-sync"),
        _ => false,
    };
    let (boot_overlay, overlay_fixable) = match bootloader {
        Bootloader::Grub => match overlay(files) {
            Overlay::Present => (true, false),
            Overlay::Add { files, .. } => (false, !files.is_empty()),
            Overlay::Cannot(_) => (false, false),
        },
        _ => (false, false),
    };
    let boot_separate = !runner
        .query(&["findmnt", "-no", "TARGET", "/boot"])
        .1
        .trim()
        .is_empty();
    Env {
        fs,
        btrfs,
        snapper,
        config,
        snap_pac,
        bootloader,
        boot_menu,
        boot_separate,
        boot_overlay,
        overlay_fixable,
        readable,
        offline,
        booted: booted(files),
    }
}

// ------------------------------------------------------------------ mkinitcpio's HOOKS

/// A file that sets mkinitcpio's HOOKS.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HooksFile {
    pub path: String,
    /// What its last `HOOKS=(…)` names (None: it only adds, `HOOKS+=(…)`).
    pub hooks: Option<Vec<String>>,
    /// That assignment is on one line (what the edit rewrites).
    pub one_line: bool,
    /// Its `HOOKS+=(…)`, after the assignment.
    pub added: Vec<String>,
}

fn words(list: &str) -> Vec<String> {
    list.split_whitespace()
        .map(|w| w.trim_matches(|c| c == '"' || c == '\'').to_owned())
        .filter(|w| !w.is_empty())
        .collect()
}

/// Parses one file's HOOKS: its last `HOOKS=(…)` (one or more lines) and any `HOOKS+=(…)`
/// after it. None when it sets none. Commented lines are skipped.
pub fn parse_hooks(path: &str, text: &str) -> Option<HooksFile> {
    let lines: Vec<&str> = text.lines().collect();
    let mut found: Option<HooksFile> = None;
    let mut i = 0;
    while i < lines.len() {
        let l = lines[i];
        let (append, rest) = if let Some(r) = l.strip_prefix("HOOKS+=(") {
            (true, r)
        } else if let Some(r) = l.strip_prefix("HOOKS=(") {
            (false, r)
        } else {
            i += 1;
            continue;
        };
        let mut body = String::new();
        let mut one_line = true;
        let mut rest = rest.to_owned();
        loop {
            if let Some((inside, _)) = rest.split_once(')') {
                body.push_str(inside);
                break;
            }
            body.push_str(&rest);
            body.push(' ');
            one_line = false;
            i += 1;
            match lines.get(i) {
                Some(next) => rest = next.split('#').next().unwrap_or("").to_owned(),
                None => break,
            }
        }
        if append {
            if let Some(f) = found.as_mut() {
                f.added.extend(words(&body));
            } else {
                found = Some(HooksFile {
                    path: path.to_owned(),
                    hooks: None,
                    one_line: false,
                    added: words(&body),
                });
            }
        } else {
            found = Some(HooksFile {
                path: path.to_owned(),
                hooks: Some(words(&body)),
                one_line,
                added: vec![],
            });
        }
        i += 1;
    }
    found
}

/// Every file that sets HOOKS, in mkinitcpio's reading order: `/etc/mkinitcpio.conf`, then
/// the drop-ins (`/etc/mkinitcpio.conf.d/*.conf`, by name).
pub fn hooks_files(files: &dyn Files) -> Vec<HooksFile> {
    let mut paths = vec!["/etc/mkinitcpio.conf".to_owned()];
    paths.extend(
        files
            .list("/etc/mkinitcpio.conf.d")
            .into_iter()
            .filter(|n| n.ends_with(".conf"))
            .map(|n| format!("/etc/mkinitcpio.conf.d/{n}")),
    );
    paths
        .iter()
        .filter_map(|p| parse_hooks(p, &files.read(p)?))
        .collect()
}

/// The hooks in force: the last plain assignment, plus what `+=` added after it.
pub fn hooks_in_force(hf: &[HooksFile]) -> Vec<String> {
    let mut out: Vec<String> = vec![];
    for f in hf {
        if let Some(h) = &f.hooks {
            out = h.clone();
        }
        out.extend(f.added.iter().cloned());
    }
    out
}

/// The edit that puts `hook` last in a file's one-line `HOOKS=(…)` (grub-btrfs's README:
/// "at the end of the line HOOKS").
pub fn add_hook_command(path: &str, hook: &str) -> Vec<String> {
    argv(&[
        "sudo",
        "sed",
        "-i",
        "-E",
        &format!(r"s/^(HOOKS=\([^)]*[^ )]) *\)/\1 {hook})/"),
        path,
    ])
}

// ------------------------------------------------------------------ snapper's list

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Pre,
    Post,
    Single,
}

/// One snapshot, from `snapper --csvout list`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Snap {
    pub number: u64,
    pub kind: Kind,
    /// A post snapshot's pre.
    pub pre: Option<u64>,
    pub date: String,
    pub description: String,
}

/// Parses `snapper --no-headers --csvout list --columns number,type,pre-number,date,description`.
pub fn parse_list(csv: &str) -> Vec<Snap> {
    csv.lines()
        .filter_map(|l| {
            let mut f = l.splitn(5, ',');
            let number: u64 = f.next()?.trim().parse().ok()?;
            let kind = match f.next()?.trim() {
                "pre" => Kind::Pre,
                "post" => Kind::Post,
                _ => Kind::Single,
            };
            let pre = f.next()?.trim().parse().ok();
            let date = f.next().unwrap_or("").trim().to_owned();
            let description = f.next().unwrap_or("").trim().trim_matches('"').to_owned();
            Some(Snap {
                number,
                kind,
                pre,
                date,
                description,
            })
        })
        .collect()
}

pub fn list(runner: &mut dyn Runner) -> Vec<Snap> {
    let (code, out) = runner.query(&[
        "snapper",
        "-c",
        CONFIG,
        "--no-headers",
        "--csvout",
        "list",
        "--columns",
        "number,type,pre-number,date,description",
    ]);
    if code != 0 {
        return vec![];
    }
    parse_list(&out)
}

/// A pre/post pair around one update.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Pair {
    pub pre: u64,
    pub post: u64,
}

/// The pre/post pairs made after snapshot `after` (snap-pac's, around the transaction),
/// oldest first.
pub fn pairs_after(snaps: &[Snap], after: u64) -> Vec<Pair> {
    let mut out: Vec<Pair> = snaps
        .iter()
        .filter(|s| s.kind == Kind::Post && s.number > after)
        .filter_map(|s| {
            s.pre.filter(|p| *p > after).map(|pre| Pair {
                pre,
                post: s.number,
            })
        })
        .collect();
    out.sort_by_key(|p| p.pre);
    out
}

/// What was noted before the package step.
#[derive(Debug, Clone, Serialize)]
pub struct Marker {
    /// The newest snapshot number before the update.
    pub last: u64,
    /// The pre snapshot `bromigos update` made itself (no snap-pac).
    pub own_pre: Option<u64>,
}

/// Before `pacman`: notes the newest snapshot and makes the pre snapshot (`sudo snapper
/// create`, on the terminal), described "bromigos update" (snap-pac skips the transaction:
/// [`crate::update::pacman_upgrade`]). None when the machine takes no snapshots.
pub fn before(env: &Env, runner: &mut dyn Runner) -> Result<Option<Marker>, String> {
    if !env.snapshots() {
        return Ok(None);
    }
    let last = list(runner).iter().map(|s| s.number).max().unwrap_or(0);
    let (code, out) = runner
        .run(
            &argv(&[
                "sudo",
                "snapper",
                "-c",
                CONFIG,
                "create",
                "-t",
                "pre",
                "-p",
                "-c",
                "number",
                "-d",
                "bromigos update",
            ]),
            false,
        )
        .map_err(|e| e.to_string())?;
    if code != 0 {
        return Err(format!(
            "snapper create (pre) exited {code}: {}",
            out.trim()
        ));
    }
    let n = out
        .trim()
        .parse()
        .map_err(|_| format!("snapper create printed no number: {}", out.trim()))?;
    Ok(Some(Marker {
        last,
        own_pre: Some(n),
    }))
}

/// After `pacman`: the pair around it (snap-pac's newest, or our own post snapshot).
pub fn after(env: &Env, runner: &mut dyn Runner, marker: &Marker) -> Result<Option<Pair>, String> {
    if let Some(pre) = marker.own_pre {
        let (code, out) = runner
            .run(
                &argv(&[
                    "sudo",
                    "snapper",
                    "-c",
                    CONFIG,
                    "create",
                    "-t",
                    "post",
                    "--pre-number",
                    &pre.to_string(),
                    "-p",
                    "-c",
                    "number",
                    "-d",
                    "bromigos update",
                ]),
                false,
            )
            .map_err(|e| e.to_string())?;
        if code != 0 {
            return Err(format!(
                "snapper create (post) exited {code}: {}",
                out.trim()
            ));
        }
        let post = out
            .trim()
            .parse()
            .map_err(|_| format!("snapper create printed no number: {}", out.trim()))?;
        return Ok(Some(Pair { pre, post }));
    }
    let _ = env;
    Ok(pairs_after(&list(runner), marker.last).last().copied())
}

/// A pair around nothing (pacman changed no package): deleted, so the boot menu's snapshot
/// list holds updates only. Right after the post snapshot snapperd compares the pair in the
/// background (BACKGROUND_COMPARISON, on by default) and refuses a delete meanwhile ("Config
/// is in use."): the delete is tried again for up to 10 s.
pub fn discard(runner: &mut dyn Runner, pair: Pair) -> Result<(), String> {
    discard_waiting(runner, pair, std::time::Duration::from_millis(500), 20)
}

pub(crate) fn discard_waiting(
    runner: &mut dyn Runner,
    pair: Pair,
    pause: std::time::Duration,
    tries: u32,
) -> Result<(), String> {
    let a = argv(&[
        "sudo",
        "snapper",
        "-c",
        CONFIG,
        "delete",
        &pair.pre.to_string(),
        &pair.post.to_string(),
    ]);
    for n in 1..=tries {
        let (code, out) = runner.run(&a, false).map_err(|e| e.to_string())?;
        if code == 0 {
            return Ok(());
        }
        if n == tries || !out.contains("in use") {
            return Err(format!("snapper delete exited {code}: {}", out.trim()));
        }
        std::thread::sleep(pause);
    }
    Ok(())
}

fn argv(a: &[&str]) -> Vec<String> {
    a.iter().map(|s| (*s).to_owned()).collect()
}

// ------------------------------------------------------------------ the update log

/// One update, in `updates.jsonl`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Record {
    pub at: String,
    pub channel: Option<String>,
    pub snapshot: Option<Pair>,
    /// `name old -> new` per changed package.
    pub packages: Vec<String>,
    #[serde(default)]
    pub rolled_back: bool,
    /// A rollback from a snapshot booted from the boot menu: the snapshot it made the root
    /// (`snapshot` is then the update it undid, if one was recorded).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub root: Option<u64>,
}

pub fn log_path(paths: &Paths) -> PathBuf {
    paths.state_home.join("bromigos/updates.jsonl")
}

pub fn record(paths: &Paths, rec: &Record) -> std::io::Result<()> {
    let p = log_path(paths);
    if let Some(d) = p.parent() {
        fs::create_dir_all(d)?;
    }
    let mut f = fs::OpenOptions::new().append(true).create(true).open(p)?;
    writeln!(
        f,
        "{}",
        serde_json::to_string(rec).map_err(std::io::Error::other)?
    )
}

/// Every recorded update, oldest first, with rollbacks applied (a later line with the
/// same pre snapshot and `rolled_back` marks the earlier one).
pub fn records(paths: &Paths) -> Vec<Record> {
    let text = fs::read_to_string(log_path(paths)).unwrap_or_default();
    parse_records(&text)
}

pub fn parse_records(text: &str) -> Vec<Record> {
    let mut out: Vec<Record> = vec![];
    for line in text.lines() {
        let Ok(r) = serde_json::from_str::<Record>(line) else {
            continue;
        };
        if r.rolled_back {
            if let Some(p) = r.snapshot {
                for o in out.iter_mut() {
                    if o.snapshot == Some(p) {
                        o.rolled_back = true;
                    }
                }
            }
            continue;
        }
        out.push(r);
    }
    out
}

// ------------------------------------------------------------------ rollback

/// The update a rollback would undo, and what that touches.
#[derive(Debug, Clone, Serialize)]
pub struct Target {
    pub record: Record,
    pub pair: Pair,
    /// `snapper status`: files changed, created, deleted between the two snapshots.
    pub changed: usize,
    pub created: usize,
    pub deleted: usize,
}

/// Picks the update to undo: the newest recorded one with a snapshot pair that still
/// exists and wasn't rolled back, or the one whose pre snapshot is `pre`.
pub fn target(paths: &Paths, runner: &mut dyn Runner, pre: Option<u64>) -> Result<Target, String> {
    let recs = records(paths);
    let snaps = list(runner);
    let have = |n: u64| snaps.iter().any(|s| s.number == n);
    let rec = match pre {
        Some(p) => recs
            .iter()
            .rev()
            .find(|r| r.snapshot.is_some_and(|s| s.pre == p))
            .cloned()
            .ok_or_else(|| {
                format!(
                    "no recorded update has pre snapshot {p} (bromigos update --check lists them)"
                )
            })?,
        None => recs
            .iter()
            .rev()
            .find(|r| !r.rolled_back && r.snapshot.is_some())
            .cloned()
            .ok_or_else(|| {
                "no update with a snapshot pair is recorded (updates.jsonl)".to_owned()
            })?,
    };
    let pair = rec.snapshot.ok_or("that update has no snapshot pair")?;
    if rec.rolled_back {
        return Err(format!(
            "the update with snapshots {}..{} was already rolled back",
            pair.pre, pair.post
        ));
    }
    if !have(pair.pre) || !have(pair.post) {
        return Err(format!(
            "snapshots {}..{} are gone (snapper's cleanup); nothing to roll back to",
            pair.pre, pair.post
        ));
    }
    let (code, out) = runner.query(&[
        "snapper",
        "-c",
        CONFIG,
        "status",
        &format!("{}..{}", pair.pre, pair.post),
    ]);
    if code != 0 {
        return Err(
            "snapper status failed (is snapper allowed for your user? sudo snapper status …)"
                .into(),
        );
    }
    let (changed, created, deleted) = count_status(&out);
    Ok(Target {
        record: rec,
        pair,
        changed,
        created,
        deleted,
    })
}

/// Counts `snapper status` lines by their first column: c (changed), + (created), - (deleted).
pub fn count_status(out: &str) -> (usize, usize, usize) {
    let mut c = (0, 0, 0);
    for l in out.lines() {
        match l.chars().next() {
            Some('c') => c.0 += 1,
            Some('+') => c.1 += 1,
            Some('-') => c.2 += 1,
            _ => {}
        }
    }
    c
}

/// What `bromigos update --rollback` did.
#[derive(Debug, Clone, Serialize)]
pub struct Rollback {
    pub pair: Pair,
    pub packages: Vec<String>,
    /// What to do next (reboot; `/boot` on its own file system).
    pub notes: Vec<String>,
}

/// Runs `sudo snapper undochange PRE..POST` (on the terminal: sudo asks) and records it.
pub fn undo(
    paths: &Paths,
    env: &Env,
    runner: &mut dyn Runner,
    t: &Target,
) -> Result<Rollback, String> {
    let range = format!("{}..{}", t.pair.pre, t.pair.post);
    let (code, out) = runner
        .run(
            &argv(&["sudo", "snapper", "-c", CONFIG, "undochange", &range]),
            true,
        )
        .map_err(|e| e.to_string())?;
    if code != 0 {
        return Err(format!("snapper undochange exited {code} {}", out.trim()));
    }
    let _ = record(
        paths,
        &Record {
            at: chrono::Local::now().to_rfc3339(),
            channel: t.record.channel.clone(),
            snapshot: Some(t.pair),
            packages: vec![],
            rolled_back: true,
            root: None,
        },
    );
    let kernel = t.record.packages.iter().any(|p| {
        let name = p.split(' ').next().unwrap_or("");
        name == "linux" || name.starts_with("linux-") && !name.starts_with("linux-firmware")
    });
    let mut notes = vec![];
    if kernel {
        if env.boot_separate {
            notes.push(
                "/boot is its own file system, so the kernel image there wasn't reverted: run \
                 `sudo pacman -S linux` (pacman's cache has the version now installed), then reboot"
                    .into(),
            );
        } else {
            notes.push("the kernel was part of that update: reboot".into());
        }
    } else {
        notes.push("the running programs are newer than what's installed now: `bromigos restart`, or reboot".into());
    }
    Ok(Rollback {
        pair: t.pair,
        packages: t.record.packages.clone(),
        notes,
    })
}

// ------------------------------------------------------------------ booted from a snapshot

/// Where a rollback from a booted snapshot mounts the btrfs file system's top level.
pub const TOP: &str = "/run/bromigos-rollback";

/// A snapshot booted from the boot menu. grub-btrfs names it on the kernel line
/// (`rootflags=…,subvol=@.snapshots/3/snapshot`), and `/` is then grub-btrfs-overlayfs's
/// overlay on it (writable, in memory), or the read-only snapshot itself.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Booted {
    /// snapper's number for it.
    pub number: u64,
    /// Its subvolume, from the file system's top level: `@.snapshots/3/snapshot`.
    pub subvol: String,
    /// The file system, as the kernel line's `root=` names it (`UUID=…`, `/dev/mapper/root`).
    pub device: String,
}

/// The snapshot a kernel line boots, if it boots one: its root subvolume is a snapper
/// snapshot (`…/<number>/snapshot`).
pub fn booted_from(cmdline: &str) -> Option<Booted> {
    let (mut device, mut subvol) = (None, None);
    for w in cmdline.split_whitespace() {
        if let Some(v) = w.strip_prefix("root=") {
            device = Some(v.trim_matches('"').to_owned());
        }
        if let Some(v) = w.strip_prefix("rootflags=") {
            for o in v.trim_matches('"').split(',') {
                if let Some(sv) = o.strip_prefix("subvol=") {
                    subvol = Some(sv.trim_matches('"').trim_start_matches('/').to_owned());
                }
            }
        }
    }
    let subvol = subvol?;
    let mut parts = subvol.rsplit('/');
    if parts.next()? != "snapshot" {
        return None;
    }
    let number = parts.next()?.parse().ok()?;
    Some(Booted {
        number,
        subvol,
        device: device.filter(|d| !d.is_empty())?,
    })
}

/// The root mount's file system type and options, from a mountinfo.
fn root_fs(mountinfo: &str) -> Option<(String, Vec<String>)> {
    mountinfo.lines().rev().find_map(|l| {
        let f: Vec<&str> = l.split_whitespace().collect();
        if f.get(4) != Some(&"/") {
            return None;
        }
        let dash = f.iter().position(|w| *w == "-")?;
        let opts = f.get(5)?.split(',').map(str::to_owned).collect();
        Some((f.get(dash + 1)?.to_string(), opts))
    })
}

/// This boot is a snapshot from the boot menu: the kernel line names a snapshot, and `/` is
/// an overlay (grub-btrfs-overlayfs) or a read-only btrfs. A system whose normal root is
/// itself a snapshot (btrfs's default subvolume, mounted writable) isn't one.
pub fn booted(files: &dyn Files) -> Option<Booted> {
    let b = booted_from(&files.read("/proc/cmdline")?)?;
    let (fs, opts) = root_fs(&files.read("/proc/self/mountinfo")?)?;
    (fs == "overlay" || fs == "btrfs" && opts.iter().any(|o| o == "ro")).then_some(b)
}

/// How `/etc/fstab` mounts `/`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum RootLayout {
    /// By the subvolume's name (`subvol=/@`): archinstall's, the Arch wiki's, the ISO's.
    Named(String),
    /// btrfs's default subvolume (no `subvol=`).
    Default,
    /// Anything else, with why it doesn't do.
    Other(String),
}

pub fn root_layout(fstab: &str) -> RootLayout {
    for l in fstab.lines() {
        let f: Vec<&str> = l.split_whitespace().collect();
        if f.first().is_none_or(|w| w.starts_with('#')) || f.get(1) != Some(&"/") {
            continue;
        }
        if f.get(2) != Some(&"btrfs") {
            return RootLayout::Other(format!(
                "/etc/fstab mounts / as {}, not btrfs",
                f.get(2).unwrap_or(&"?")
            ));
        }
        let opts: Vec<&str> = f.get(3).map(|o| o.split(',').collect()).unwrap_or_default();
        if let Some(sv) = opts.iter().find_map(|o| o.strip_prefix("subvol=")) {
            let sv = sv.trim_matches('"').trim_matches('/');
            return if sv.is_empty() {
                RootLayout::Default
            } else {
                RootLayout::Named(sv.to_owned())
            };
        }
        if opts.iter().any(|o| o.starts_with("subvolid=")) {
            return RootLayout::Other(
                "/etc/fstab mounts / by subvolume id (subvolid=), which a new subvolume can't keep"
                    .into(),
            );
        }
        return RootLayout::Default;
    }
    RootLayout::Other("/etc/fstab has no line for /".into())
}

/// The modules mounting `/boot` takes (its file system, and for FAT its code page and
/// character set), from `/etc/fstab`. None when `/boot` isn't a file system of its own.
pub fn boot_modules(fstab: &str) -> Option<Vec<String>> {
    fstab.lines().find_map(|l| {
        let f: Vec<&str> = l.split_whitespace().collect();
        if f.first().is_none_or(|w| w.starts_with('#')) || f.get(1) != Some(&"/boot") {
            return None;
        }
        let fs = (*f.get(2)?).to_owned();
        let mut mods = vec![fs.clone()];
        if fs == "vfat" {
            for o in f.get(3).map(|o| o.split(',').collect::<Vec<_>>()).unwrap_or_default() {
                if let Some(cp) = o.strip_prefix("codepage=") {
                    mods.push(format!("nls_cp{cp}"));
                }
                if let Some(cs) = o.strip_prefix("iocharset=") {
                    mods.push(format!("nls_{}", cs.replace('-', "_")));
                }
            }
        }
        Some(mods)
    })
}

/// A kernel the snapshot has (`/usr/lib/modules/<release>/vmlinuz`, and its `pkgbase`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Kernel {
    pub pkgbase: String,
    pub release: String,
}

/// The snapshot's kernels, when `/boot` boots another one: the running kernel (the one
/// `/boot` has, which GRUB booted the snapshot with) has no modules in the snapshot. That
/// happens when `/boot` is its own file system and the update replaced the kernel.
pub fn kernels_to_restore(files: &dyn Files, running: &str) -> Vec<Kernel> {
    if running.is_empty() || files.exists(&format!("/usr/lib/modules/{running}")) {
        return vec![];
    }
    files
        .list("/usr/lib/modules")
        .into_iter()
        .filter(|r| files.exists(&format!("/usr/lib/modules/{r}/vmlinuz")))
        .filter_map(|r| {
            let base = files.read(&format!("/usr/lib/modules/{r}/pkgbase"))?;
            Some(Kernel {
                pkgbase: base.trim().to_owned(),
                release: r,
            })
        })
        .filter(|k| !k.pkgbase.is_empty())
        .collect()
}

/// snapper's date and description for a snapshot (its `info.xml`, which `wheel` may read).
pub fn snapshot_info(files: &dyn Files, number: u64) -> (Option<String>, Option<String>) {
    let Some(x) = files.read(&format!("/.snapshots/{number}/info.xml")) else {
        return (None, None);
    };
    let tag = |t: &str| {
        let a = x.find(&format!("<{t}>"))? + t.len() + 2;
        let b = x[a..].find(&format!("</{t}>"))? + a;
        Some(x[a..b].trim().to_owned()).filter(|v| !v.is_empty())
    };
    (tag("date"), tag("description"))
}

/// One step of making a booted snapshot the root.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum Step {
    Mount,
    MoveAside,
    Copy,
    /// pacman's lock, left in a snapshot taken during a transaction (snap-pac's are).
    Unlock,
    Unmount,
    Kernel,
}

/// What `bromigos update --rollback` does from a booted snapshot: the root subvolume
/// (`@`) is kept under another name, and a writable copy of the snapshot takes its name,
/// so the next normal boot comes up on it. Nothing in `/etc/fstab` or GRUB changes.
#[derive(Debug, Clone, Serialize)]
pub struct MakeRoot {
    pub booted: Booted,
    /// The root subvolume `/etc/fstab` mounts (`@`).
    pub root: String,
    /// What the replaced root is kept as: `@.before-rollback-<when>`.
    pub kept: String,
    /// snapper's date (UTC) and description of the snapshot.
    pub date: Option<String>,
    pub description: Option<String>,
    /// The kernel running now; `kernels` is set when the snapshot has another.
    pub running_kernel: String,
    /// The snapshot's kernels, put back into `/boot` (its image, then its initramfs).
    pub kernels: Vec<Kernel>,
    /// Recorded updates made at or after the snapshot: undone by this.
    pub undoes: Vec<Record>,
    pub steps: Vec<(Step, Vec<String>)>,
    /// Said before the question.
    pub notes: Vec<String>,
}

/// Plans making the booted snapshot the root. `stamp` names the kept root
/// (`@.before-rollback-<stamp>`). Refuses, saying what to do instead, on a layout it
/// can't do it on.
pub fn make_root_plan(
    paths: &Paths,
    runner: &mut dyn Runner,
    files: &dyn Files,
    booted: &Booted,
    stamp: &str,
) -> Result<MakeRoot, String> {
    let by_hand = "docs/update.md, \"When the machine won't boot\", has the steps by hand";
    let fstab = files.read("/etc/fstab").unwrap_or_default();
    let root = match root_layout(&fstab) {
        RootLayout::Named(r) => r,
        RootLayout::Default => {
            return Err(format!(
                "this machine boots btrfs's default subvolume (no subvol= for / in /etc/fstab), \
                 so making snapshot {} the root means changing the default: from this \
                 snapshot, `sudo btrfs subvolume snapshot` it to a new subvolume and \
                 `sudo btrfs subvolume set-default` that one, then reboot ({by_hand})",
                booted.number
            ));
        }
        RootLayout::Other(why) => {
            return Err(format!(
                "{why}: bromigos can't make snapshot {} the root here ({by_hand})",
                booted.number
            ));
        }
    };
    if root == booted.subvol {
        return Err(format!(
            "this boot is the root subvolume {root} itself, not a snapshot"
        ));
    }
    // the root subvolume must be idle: in a snapshot boot nothing mounts it
    if let Some(at) = files.read("/proc/self/mountinfo").and_then(|mi| {
        mi.lines().find_map(|l| {
            let f: Vec<&str> = l.split_whitespace().collect();
            let fs = f.iter().position(|w| *w == "-").and_then(|d| f.get(d + 1));
            (fs == Some(&"btrfs") && f.get(3) == Some(&format!("/{root}").as_str()))
                .then(|| f.get(4).unwrap_or(&"?").to_string())
        })
    }) {
        return Err(format!(
            "{root} is mounted (at {at}), so it's in use: reboot into the snapshot from the \
             boot menu first"
        ));
    }
    let kept = format!("{root}.before-rollback-{stamp}");
    let top = |p: &str| format!("{TOP}/{p}");
    let mut steps = vec![
        (Step::Mount, argv(&["sudo", "mkdir", "-p", TOP])),
        (
            Step::Mount,
            argv(&["sudo", "mount", "-o", "subvolid=5", &booted.device, TOP]),
        ),
        (
            Step::MoveAside,
            argv(&["sudo", "mv", "-T", &top(&root), &top(&kept)]),
        ),
        (
            Step::Copy,
            argv(&[
                "sudo",
                "btrfs",
                "subvolume",
                "snapshot",
                &top(&booted.subvol),
                &top(&root),
            ]),
        ),
        (
            Step::Unlock,
            argv(&["sudo", "rm", "-f", &top(&format!("{root}/var/lib/pacman/db.lck"))]),
        ),
        (Step::Unmount, argv(&["sudo", "umount", TOP])),
        (Step::Unmount, argv(&["sudo", "rmdir", TOP])),
    ];
    let running_kernel = runner.query(&["uname", "-r"]).1.trim().to_owned();
    let mut notes = vec![];
    let mut kernels = vec![];
    let mut kernel_steps = vec![];
    let restore = kernels_to_restore(files, &running_kernel);
    if !restore.is_empty() {
        // /boot's file system needs modules the snapshot hasn't for this kernel (so that boot
        // stopped in emergency mode, /boot unmounted): the replaced root has them
        let mounted = files
            .read("/proc/self/mountinfo")
            .is_some_and(|mi| mi.lines().any(|l| l.split_whitespace().nth(4) == Some("/boot")));
        match (mounted, boot_modules(&fstab)) {
            (true, _) => {}
            (false, Some(mods)) => {
                let mut a = vec!["sudo", "modprobe", "-d"];
                let dir = top(&kept);
                a.push(&dir);
                a.push("-a");
                a.extend(mods.iter().map(String::as_str));
                kernel_steps.push((Step::Kernel, argv(&a)));
                kernel_steps.push((Step::Kernel, argv(&["sudo", "mount", "/boot"])));
            }
            (false, None) => notes.push(format!(
                "/boot's kernel ({running_kernel}) isn't this snapshot's, and /etc/fstab has no \
                 /boot to put its kernel into: check the boot loader's kernel before you reboot"
            )),
        }
    }
    for k in restore {
        let preset = format!("/etc/mkinitcpio.d/{}.preset", k.pkgbase);
        if !files.exists(&preset) || !notes.is_empty() {
            notes.push(format!(
                "/boot's kernel ({running_kernel}) isn't this snapshot's ({} {}), and there's \
                 no {preset} to rebuild its initramfs with: put the snapshot's kernel into \
                 /boot yourself before you reboot",
                k.pkgbase, k.release
            ));
            continue;
        }
        kernel_steps.push((
            Step::Kernel,
            argv(&[
                "sudo",
                "install",
                "-m",
                "0644",
                &format!("/usr/lib/modules/{}/vmlinuz", k.release),
                &format!("/boot/vmlinuz-{}", k.pkgbase),
            ]),
        ));
        kernel_steps.push((Step::Kernel, argv(&["sudo", "mkinitcpio", "-p", &k.pkgbase])));
        kernels.push(k);
    }
    if kernels.is_empty() {
        kernel_steps.clear();
    }
    // the kernel before the top level is unmounted (modprobe reads the replaced root)
    let at = steps
        .iter()
        .position(|(s, _)| *s == Step::Unmount)
        .unwrap_or(steps.len());
    steps.splice(at..at, kernel_steps);
    let undoes = records(paths)
        .into_iter()
        .filter(|r| !r.rolled_back && r.snapshot.is_some_and(|p| p.pre >= booted.number))
        .collect();
    let (date, description) = snapshot_info(files, booted.number);
    Ok(MakeRoot {
        booted: booted.clone(),
        root,
        kept,
        date,
        description,
        running_kernel,
        kernels,
        undoes,
        steps,
        notes,
    })
}

/// Now, for the kept root's name: `20261009-183012`.
pub fn stamp() -> String {
    chrono::Local::now().format("%Y%m%d-%H%M%S").to_string()
}

/// What making a booted snapshot the root did.
#[derive(Debug, Clone, Serialize)]
pub struct MadeRoot {
    pub snapshot: u64,
    pub root: String,
    pub kept: String,
    pub kernels: Vec<Kernel>,
    /// What to do next: reboot, and deleting the kept root later.
    pub notes: Vec<String>,
}

/// Runs the plan's steps (sudo asks on the terminal). A step that fails before the copy is
/// in place puts the root back under its name; the top level is always unmounted.
pub fn make_root(
    paths: &Paths,
    runner: &mut dyn Runner,
    plan: &MakeRoot,
) -> Result<MadeRoot, String> {
    let top = |p: &str| format!("{TOP}/{p}");
    let (mut mounted, mut moved, mut later) = (false, false, vec![]);
    for (step, cmd) in &plan.steps {
        let (code, out) = runner.run(cmd, true).map_err(|e| e.to_string())?;
        if code == 0 {
            match step {
                Step::Mount if cmd.get(1).is_some_and(|c| c == "mount") => mounted = true,
                Step::MoveAside => moved = true,
                _ => {}
            }
            continue;
        }
        let why = format!("`{}` exited {code} {}", cmd.join(" "), out.trim());
        match step {
            // the copy is the root now: an unmount that fails is the reboot's to finish
            Step::Unmount => {
                later.push(format!("{why} (the reboot unmounts it)"));
                continue;
            }
            Step::Unlock => {
                later.push(format!(
                    "{why}: if pacman says \"unable to lock database\" after the reboot, \
                     remove /var/lib/pacman/db.lck (no pacman is running then)"
                ));
                continue;
            }
            Step::Kernel => {
                // the rest as commands to type (the top level stays mounted for them)
                let rest: Vec<String> = plan
                    .steps
                    .iter()
                    .skip_while(|(_, c)| c != cmd)
                    .map(|(_, c)| c.join(" "))
                    .collect();
                return Err(format!(
                    "snapshot {} is the root now, but putting its kernel back into /boot \
                     failed: {why}. Before you reboot, finish that by hand: {}",
                    plan.booted.number,
                    rest.join("; ")
                ));
            }
            Step::Mount | Step::MoveAside | Step::Copy => {}
        }
        let mut put_back = String::new();
        if moved {
            let back = argv(&["sudo", "mv", "-T", &top(&plan.kept), &top(&plan.root)]);
            put_back = match runner.run(&back, true) {
                Ok((0, _)) => format!("; {} is back as it was", plan.root),
                _ => format!(
                    "; putting {} back failed too: it's {} on the file system's top level",
                    plan.root, plan.kept
                ),
            };
        }
        if mounted {
            let _ = runner.run(&argv(&["sudo", "umount", TOP]), true);
        }
        return Err(format!("{why}{put_back}"));
    }
    let now = chrono::Local::now().to_rfc3339();
    let mut lines: Vec<Record> = plan
        .undoes
        .iter()
        .map(|r| Record {
            at: now.clone(),
            channel: r.channel.clone(),
            snapshot: r.snapshot,
            packages: vec![],
            rolled_back: true,
            root: Some(plan.booted.number),
        })
        .collect();
    if lines.is_empty() {
        lines.push(Record {
            at: now,
            channel: None,
            snapshot: None,
            packages: vec![],
            rolled_back: true,
            root: Some(plan.booted.number),
        });
    }
    for l in &lines {
        let _ = record(paths, l);
    }
    let mut notes = vec![format!(
        "reboot: the next normal boot comes up on snapshot {} (choose the first entry, not \
         the snapshot again)",
        plan.booted.number
    )];
    notes.extend(later);
    notes.push(format!(
        "the replaced root is kept as {}. Once everything works, delete it: \
         sudo mount -o subvolid=5 {} /mnt && sudo btrfs subvolume delete -R /mnt/{} && \
         sudo umount /mnt",
        plan.kept, plan.booted.device, plan.kept
    ));
    Ok(MadeRoot {
        snapshot: plan.booted.number,
        root: plan.root.clone(),
        kept: plan.kept.clone(),
        kernels: plan.kernels.clone(),
        notes,
    })
}

// ------------------------------------------------------------------ who may list

/// Who runs this, for snapper's permissions: the user (the one behind sudo when run as
/// root; None for root itself) and their groups.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Who {
    pub user: Option<String>,
    pub groups: Vec<String>,
}

pub fn who(runner: &mut dyn Runner) -> Who {
    let user = if rustix::process::geteuid().is_root() {
        std::env::var("SUDO_USER").ok()
    } else {
        Some(runner.query(&["id", "-un"]).1.trim().to_owned())
    }
    .filter(|u| !u.is_empty() && u != "root");
    let groups = match &user {
        Some(u) => runner
            .query(&["id", "-Gn", u])
            .1
            .split_whitespace()
            .map(str::to_owned)
            .collect(),
        None => vec![],
    };
    Who { user, groups }
}

/// snapper as root: `sudo snapper`, with `--no-dbus` where there's no system bus.
fn snapper_cmd(env: &Env, args: &[&str]) -> Vec<String> {
    let mut a = argv(&["sudo", "snapper"]);
    if env.offline {
        a.push("--no-dbus".into());
    }
    a.extend(args.iter().map(|s| (*s).to_owned()));
    a
}

/// `snapper --csvout get-config --columns key,value`: key -> value (the header skipped).
pub fn parse_config(csv: &str) -> BTreeMap<String, String> {
    csv.lines()
        .filter_map(|l| {
            let (k, v) = l.split_once(',')?;
            let k = k.trim();
            (!k.is_empty() && k != "key")
                .then(|| (k.to_owned(), v.trim().trim_matches('"').to_owned()))
        })
        .collect()
}

/// The `set-config` pairs that let wheel, and `who`, list root's snapshots, given the
/// configuration's current values: wheel added to ALLOW_GROUPS (the groups there stay), the
/// user added to ALLOW_USERS when no allowed group has them, SYNC_ACL=yes (so `/.snapshots`
/// lets them in). Nothing when it already does.
pub fn access_pairs(cur: &BTreeMap<String, String>, who: &Who) -> Vec<(String, String)> {
    let list = |k: &str| -> Vec<String> {
        cur.get(k)
            .map(|v| v.split_whitespace().map(str::to_owned).collect())
            .unwrap_or_default()
    };
    let mut out = vec![];
    let mut groups = list("ALLOW_GROUPS");
    if !groups.iter().any(|g| g == ALLOW_GROUP) {
        groups.push(ALLOW_GROUP.to_owned());
        out.push(("ALLOW_GROUPS".to_owned(), groups.join(" ")));
    }
    if let Some(u) = &who.user {
        let mut users = list("ALLOW_USERS");
        let by_group = who.groups.iter().any(|g| groups.contains(g));
        if !by_group && !users.contains(u) {
            users.push(u.clone());
            out.push(("ALLOW_USERS".to_owned(), users.join(" ")));
        }
    }
    if cur.get("SYNC_ACL").map(|v| v.as_str()) != Some("yes") {
        out.push(("SYNC_ACL".to_owned(), "yes".to_owned()));
    }
    out
}

fn set_config(env: &Env, pairs: &[(String, String)]) -> Vec<String> {
    let mut a = snapper_cmd(env, &["-c", CONFIG, "set-config"]);
    a.extend(pairs.iter().map(|(k, v)| format!("{k}={v}")));
    a
}

/// `bromigos rollback allow`: lets wheel (and `who`) list root's snapshots, on a
/// configuration that exists. Reads it as root (`sudo snapper get-config`; sudo asks on the
/// terminal, as the update's other root steps), then sets what's missing of
/// [`access_pairs`]. Returns the `set-config` command it ran, None when nothing was missing.
pub fn allow(env: &Env, runner: &mut dyn Runner, who: &Who) -> Result<Option<Vec<String>>, String> {
    if !env.config {
        return Err(
            "snapper has no configuration for / yet (bromigos rollback setup makes one, wheel allowed)"
                .into(),
        );
    }
    let get = snapper_cmd(
        env,
        &[
            "-c",
            CONFIG,
            "--csvout",
            "get-config",
            "--columns",
            "key,value",
        ],
    );
    let (code, out) = runner.run(&get, false).map_err(|e| e.to_string())?;
    if code != 0 {
        return Err(format!(
            "`{}` exited {code}: {}",
            get.join(" "),
            out.trim().lines().last().unwrap_or("")
        ));
    }
    let pairs = access_pairs(&parse_config(&out), who);
    if pairs.is_empty() {
        return Ok(None);
    }
    let set = set_config(env, &pairs);
    let (code, out) = runner.run(&set, false).map_err(|e| e.to_string())?;
    if code != 0 {
        return Err(format!(
            "`{}` exited {code}: {}",
            set.join(" "),
            out.trim().lines().last().unwrap_or("")
        ));
    }
    Ok(Some(set))
}

// ------------------------------------------------------------------ setup

/// What `bromigos rollback setup` would run on this machine, and what it can only say.
#[derive(Debug, Clone, Serialize)]
pub struct Setup {
    pub commands: Vec<Vec<String>>,
    /// Then [`allow`]: a configuration that exists doesn't let this user list it.
    pub allow: bool,
    pub notes: Vec<String>,
}

impl Setup {
    /// pacman doesn't stop to ask (unattended: `--yes`).
    pub fn noconfirm(&mut self) {
        for c in &mut self.commands {
            if c.iter().any(|w| w == "pacman") && !c.iter().any(|w| w == "--noconfirm") {
                c.push("--noconfirm".into());
            }
        }
    }
}

/// `findmnt -no SOURCE` of a btrfs subvolume, `/dev/mapper/root[/@.snapshots]`: the device
/// and the subvolume.
pub fn parse_source(source: &str) -> Option<(String, String)> {
    let (dev, rest) = source.trim().split_once('[')?;
    let sub = rest.strip_suffix(']')?;
    (!dev.is_empty() && !sub.is_empty()).then(|| (dev.to_owned(), sub.to_owned()))
}

/// The commands that make snapshots and the boot menu work here: snap-pac on a snapper
/// root; snapper's `root` configuration, with wheel allowed to list it; grub-btrfs (and
/// its daemon, and its overlay hook in the initramfs) on GRUB; limine-snapper-sync on
/// limine, when a repository has it. Anything missing that a command can't fix is a note.
/// In an install chroot (`env.offline`) snapper runs with `--no-dbus` and services are only
/// enabled.
pub fn setup_plan(env: &Env, runner: &mut dyn Runner, files: &dyn Files, who: &Who) -> Setup {
    let mut commands = vec![];
    let mut notes = vec![];
    if !env.btrfs {
        notes.push(format!(
            "/ is {}: snapshots need btrfs (nothing to set up)",
            env.fs
        ));
        return Setup {
            commands,
            allow: false,
            notes,
        };
    }
    let available = |r: &mut dyn Runner, p: &str| r.query(&["pacman", "-Si", p]).0 == 0;
    let mut need = vec![];
    if !env.snapper {
        need.push("snapper");
    }
    if !env.snap_pac {
        need.push("snap-pac");
    }
    let grub_btrfs = env.bootloader == Bootloader::Grub && installed(runner, "grub-btrfs");
    match env.bootloader {
        Bootloader::Grub if !grub_btrfs => need.push("grub-btrfs"),
        Bootloader::Limine if !installed(runner, "limine-snapper-sync") => {
            if available(runner, "limine-snapper-sync") {
                need.push("limine-snapper-sync");
            } else {
                notes.push(
                    "limine boots snapshots with limine-snapper-sync, which no repository here has yet \
                     (AUR); `bromigos update --rollback` still works"
                        .into(),
                );
            }
        }
        Bootloader::SystemdBoot => notes.push(
            "systemd-boot has no snapshot entries: rollback is `bromigos update --rollback` only"
                .into(),
        ),
        Bootloader::Unknown => {
            notes.push("the boot loader wasn't recognised: no boot-menu rollback set up".into())
        }
        _ => {}
    }
    if !need.is_empty() {
        let mut a = argv(&["sudo", "pacman", "-S", "--needed"]);
        a.extend(need.iter().map(|s| (*s).to_owned()));
        commands.push(a);
    }
    let mut allow = false;
    if !env.config {
        let create = snapper_cmd(env, &["-c", CONFIG, "create-config", "/"]);
        let mounted = runner
            .query(&["findmnt", "-no", "SOURCE", "/.snapshots"])
            .1
            .trim()
            .to_owned();
        let made = if !mounted.is_empty() {
            // a subvolume of its own on /.snapshots (the Arch wiki's layout, archinstall's
            // @.snapshots: rolling @ back leaves the snapshots alone). snapper wants to make
            // .snapshots itself, so it comes off, snapper makes its config and a nested
            // .snapshots, that one goes, and the subvolume goes back on
            match parse_source(&mounted) {
                Some((dev, sub)) => {
                    commands.push(argv(&["sudo", "umount", "/.snapshots"]));
                    commands.push(argv(&["sudo", "rmdir", "/.snapshots"]));
                    commands.push(create);
                    commands.push(argv(&[
                        "sudo",
                        "btrfs",
                        "subvolume",
                        "delete",
                        "/.snapshots",
                    ]));
                    commands.push(argv(&["sudo", "mkdir", "/.snapshots"]));
                    commands.push(argv(&[
                        "sudo",
                        "mount",
                        "-o",
                        &format!("subvol={sub}"),
                        &dev,
                        "/.snapshots",
                    ]));
                    commands.push(argv(&["sudo", "chmod", "750", "/.snapshots"]));
                    true
                }
                None => {
                    notes.push(format!(
                        "/.snapshots is mounted ({mounted}) but not as a btrfs subvolume: \
                         snapper's `root` configuration is left to you (docs/update.md)"
                    ));
                    false
                }
            }
        } else if files.exists("/.snapshots") {
            notes.push(
                "/.snapshots exists but snapper has no `root` configuration: see docs/update.md"
                    .into(),
            );
            false
        } else {
            commands.push(create);
            true
        };
        if made {
            // a new configuration's ALLOW_GROUPS, ALLOW_USERS are empty and SYNC_ACL is no
            commands.push(set_config(env, &access_pairs(&BTreeMap::new(), who)));
        }
    } else if !env.readable {
        allow = true;
    }
    if env.bootloader == Bootloader::Grub {
        if !enabled(runner, env.offline, "grub-btrfsd.service") {
            commands.push(if env.offline {
                argv(&["sudo", "systemctl", "enable", "grub-btrfsd.service"])
            } else {
                argv(&[
                    "sudo",
                    "systemctl",
                    "enable",
                    "--now",
                    "grub-btrfsd.service",
                ])
            });
        }
        overlay_plan(files, &mut commands, &mut notes);
        if !env.boot_menu {
            commands.push(argv(&[
                "sudo",
                "grub-mkconfig",
                "-o",
                "/boot/grub/grub.cfg",
            ]));
        }
    }
    if env.bootloader == Bootloader::Limine
        && !env.boot_menu
        && installed(runner, "limine-snapper-sync")
    {
        commands.push(argv(&[
            "sudo",
            "systemctl",
            "enable",
            "--now",
            "limine-snapper-sync.service",
        ]));
    }
    Setup {
        commands,
        allow,
        notes,
    }
}

/// Where grub-btrfs's overlay hook stands in the initramfs's HOOKS.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Overlay {
    /// In the hooks in force.
    Present,
    /// Missing: the files whose one-line HOOKS setup can put it in, and notes for the rest
    /// (HOOKS over several lines).
    Add {
        files: Vec<String>,
        notes: Vec<String>,
    },
    /// Missing, and setup can't add it (why).
    Cannot(String),
}

pub fn overlay(files: &dyn Files) -> Overlay {
    let hf = hooks_files(files);
    if hf.is_empty() {
        return Overlay::Cannot(format!(
            "no mkinitcpio HOOKS here: a snapshot booted from GRUB comes up read-only unless the \
             initramfs has {OVERLAY_HOOK} (or dracut's rd.live.overlay.overlayfs=1)"
        ));
    }
    let in_force = hooks_in_force(&hf);
    if in_force.iter().any(|h| h == OVERLAY_HOOK) {
        return Overlay::Present;
    }
    if in_force.iter().any(|h| h == "systemd") && !in_force.iter().any(|h| h == "udev") {
        return Overlay::Cannot(format!(
            "the initramfs is systemd's, which runs no {OVERLAY_HOOK} hook: a snapshot booted \
             from GRUB comes up read-only (log in on a console, then bromigos update --rollback)"
        ));
    }
    let mut add = vec![];
    let mut notes = vec![];
    for f in &hf {
        let Some(hooks) = &f.hooks else { continue };
        if hooks.iter().chain(&f.added).any(|h| h == OVERLAY_HOOK) {
            continue;
        }
        if f.one_line {
            add.push(f.path.clone());
        } else {
            notes.push(format!(
                "{}: HOOKS spans several lines; add {OVERLAY_HOOK} at its end, then sudo mkinitcpio -P",
                f.path
            ));
        }
    }
    Overlay::Add { files: add, notes }
}

/// grub-btrfs's overlay hook, last in every file's HOOKS that lacks it, then the initramfs
/// made again (`mkinitcpio -P`). Not with a systemd initramfs (the hook is busybox's).
fn overlay_plan(files: &dyn Files, commands: &mut Vec<Vec<String>>, notes: &mut Vec<String>) {
    match overlay(files) {
        Overlay::Present => {}
        Overlay::Cannot(why) => notes.push(why),
        Overlay::Add { files, notes: n } => {
            notes.extend(n);
            for f in &files {
                commands.push(add_hook_command(f, OVERLAY_HOOK));
            }
            if !files.is_empty() {
                commands.push(argv(&["sudo", "mkinitcpio", "-P"]));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_pair_snapperd_is_still_comparing_is_deleted_once_it_is_done() {
        struct Busy(u32, Vec<String>);
        impl Runner for Busy {
            fn run(&mut self, argv: &[String], _: bool) -> std::io::Result<(i32, String)> {
                self.1.push(argv.join(" "));
                if self.0 > 0 {
                    self.0 -= 1;
                    return Ok((1, "Config is in use.\n".into()));
                }
                Ok((0, String::new()))
            }
        }
        let pair = Pair { pre: 21, post: 22 };
        let zero = std::time::Duration::ZERO;
        let mut r = Busy(2, vec![]);
        assert_eq!(discard_waiting(&mut r, pair, zero, 20), Ok(()));
        assert_eq!(r.1.len(), 3);
        assert_eq!(r.1[0], "sudo snapper -c root delete 21 22");
        let mut r = Busy(50, vec![]);
        assert!(
            discard_waiting(&mut r, pair, zero, 5)
                .unwrap_err()
                .contains("in use")
        );
        assert_eq!(r.1.len(), 5);
        // any other failure isn't waited out
        struct No(u32);
        impl Runner for No {
            fn run(&mut self, _: &[String], _: bool) -> std::io::Result<(i32, String)> {
                self.0 += 1;
                Ok((1, "Snapshot '22' not found.".into()))
            }
        }
        let mut r = No(0);
        assert!(discard_waiting(&mut r, pair, zero, 20).is_err());
        assert_eq!(r.0, 1);
    }

    #[test]
    fn parses_snapper_csv() {
        let csv = "149,pre,,Thu 08 Oct 2026 07:23:39 PM PDT,pacman -Syu\n\
                   150,post,149,Thu 08 Oct 2026 07:23:39 PM PDT,bromigos-settings\n\
                   151,single,,Fri 09 Oct 2026,\"hourly, timeline\"\n\
                   junk line\n";
        let s = parse_list(csv);
        assert_eq!(s.len(), 3);
        assert_eq!(s[0].number, 149);
        assert_eq!(s[0].kind, Kind::Pre);
        assert_eq!(s[1].pre, Some(149));
        assert_eq!(s[1].description, "bromigos-settings");
        assert_eq!(s[2].kind, Kind::Single);
        assert_eq!(s[2].description, "hourly, timeline");
    }

    #[test]
    fn the_pair_after_a_marker() {
        let s = parse_list(
            "10,pre,,d,x\n11,post,10,d,x\n12,pre,,d,y\n13,post,12,d,y\n14,single,,d,z\n",
        );
        assert_eq!(pairs_after(&s, 11), vec![Pair { pre: 12, post: 13 }]);
        assert_eq!(pairs_after(&s, 13), vec![]);
        assert_eq!(pairs_after(&s, 9).len(), 2);
    }

    #[test]
    fn records_apply_rollbacks() {
        let text = concat!(
            r#"{"at":"a","channel":"edge","snapshot":{"pre":10,"post":11},"packages":["x 1 -> 2"]}"#,
            "\n",
            r#"{"at":"b","channel":"edge","snapshot":{"pre":12,"post":13},"packages":["y 1 -> 2"]}"#,
            "\n",
            r#"{"at":"c","channel":"edge","snapshot":{"pre":12,"post":13},"packages":[],"rolled_back":true}"#,
            "\nnot json\n",
        );
        let r = parse_records(text);
        assert_eq!(r.len(), 2);
        assert!(!r[0].rolled_back);
        assert!(r[1].rolled_back);
    }

    #[test]
    fn counts_status() {
        assert_eq!(
            count_status("c..... /etc/a\n+..... /usr/b\n-..... /usr/c\nc..... /d\n"),
            (2, 1, 1)
        );
    }

    // ---------------------------------------------------------- fakes

    /// A file system of given files (path -> contents); a directory lists the files in it.
    #[derive(Default)]
    struct FakeFs(BTreeMap<String, String>);

    impl FakeFs {
        fn with(mut self, path: &str, text: &str) -> Self {
            self.0.insert(path.to_owned(), text.to_owned());
            self
        }
        fn without(mut self, path: &str) -> Self {
            self.0.remove(path);
            self
        }
    }

    impl Files for FakeFs {
        fn exists(&self, path: &str) -> bool {
            self.0.contains_key(path)
        }
        fn read(&self, path: &str) -> Option<String> {
            self.0.get(path).cloned()
        }
        fn list(&self, dir: &str) -> Vec<String> {
            let pre = format!("{}/", dir.trim_end_matches('/'));
            self.0
                .keys()
                .filter_map(|k| k.strip_prefix(&pre))
                .filter(|n| !n.contains('/'))
                .map(str::to_owned)
                .collect()
        }
    }

    /// Answers queries by their command line (anything else: exit 1, nothing printed) and
    /// records what it's asked to run, answering those from `runs`.
    #[derive(Default)]
    struct FakeRun {
        answers: BTreeMap<String, (i32, String)>,
        runs: BTreeMap<String, (i32, String)>,
        ran: Vec<String>,
    }

    impl FakeRun {
        fn answer(mut self, cmd: &str, code: i32, out: &str) -> Self {
            self.answers.insert(cmd.to_owned(), (code, out.to_owned()));
            self
        }
        fn on_run(mut self, cmd: &str, code: i32, out: &str) -> Self {
            self.runs.insert(cmd.to_owned(), (code, out.to_owned()));
            self
        }
    }

    impl Runner for FakeRun {
        fn run(&mut self, argv: &[String], _interactive: bool) -> std::io::Result<(i32, String)> {
            let line = argv.join(" ");
            self.ran.push(line.clone());
            Ok(self.runs.get(&line).cloned().unwrap_or((0, String::new())))
        }
        fn query(&mut self, argv: &[&str]) -> (i32, String) {
            self.answers
                .get(&argv.join(" "))
                .cloned()
                .unwrap_or((1, String::new()))
        }
    }

    const LIST_CONFIGS: &str = "snapper --no-headers --csvout list-configs --columns config";
    const LIST_ROOT: &str = "snapper -c root --no-headers --csvout list --columns number";
    const GRUBD: &str = "systemctl is-enabled grub-btrfsd.service";
    const GRUBD_FILES: &str = "systemctl --root=/ is-enabled grub-btrfsd.service";

    /// EFI's LoaderInfo as efivarfs gives it: 4 bytes of attributes, then UTF-16LE.
    fn loader_info(name: &str) -> String {
        let mut b = vec![6u8, 0, 0, 0];
        for u in name.encode_utf16().chain([0]) {
            b.extend(u.to_le_bytes());
        }
        String::from_utf8_lossy(&b).into_owned()
    }

    fn lines(cmds: &[Vec<String>]) -> Vec<String> {
        cmds.iter().map(|c| c.join(" ")).collect()
    }

    fn tester() -> Who {
        Who {
            user: Some("tester".into()),
            groups: vec!["tester".into(), "wheel".into()],
        }
    }

    // ---------------------------------------------------------- the boot loader

    #[test]
    fn grub_is_found_without_reading_boot() {
        // archinstall's /boot is 0700: as the user grub.cfg can't be seen, but GRUB's file
        // in /etc and its package can (gap: "unknown boot loader" while root saw GRUB)
        let fs = FakeFs::default().with("/etc/default/grub", "GRUB_TIMEOUT=5\n");
        let mut r = FakeRun::default().answer("pacman -Qq grub", 0, "grub\n");
        assert_eq!(bootloader(&mut r, &fs, false), Bootloader::Grub);
        // the file alone (a package removed, its config kept) isn't GRUB
        let mut r = FakeRun::default();
        assert_eq!(bootloader(&mut r, &fs, false), Bootloader::Unknown);
        // nothing at all
        assert_eq!(
            bootloader(&mut FakeRun::default(), &FakeFs::default(), false),
            Bootloader::Unknown
        );
        // a readable /boot still answers first
        let fs = FakeFs::default().with("/boot/grub/grub.cfg", "");
        assert_eq!(
            bootloader(&mut FakeRun::default(), &fs, false),
            Bootloader::Grub
        );
    }

    #[test]
    fn the_firmware_says_which_loader_booted() {
        let grub = FakeFs::default().with(LOADER_INFO, &loader_info("GRUB 2.12"));
        assert_eq!(
            bootloader(&mut FakeRun::default(), &grub, false),
            Bootloader::Grub
        );
        // systemd-boot booted it, though GRUB's package and file are installed
        let sdb = FakeFs::default()
            .with(LOADER_INFO, &loader_info("systemd-boot 258.1-1-arch"))
            .with("/etc/default/grub", "");
        let mut r = FakeRun::default().answer("pacman -Qq grub", 0, "grub\n");
        assert_eq!(bootloader(&mut r, &sdb, false), Bootloader::SystemdBoot);
        // in the ISO's chroot the variable is the live medium's (systemd-boot on UEFI): the
        // new system's GRUB files answer
        let mut r = FakeRun::default().answer("pacman -Qq grub", 0, "grub\n");
        assert_eq!(bootloader(&mut r, &sdb, true), Bootloader::Grub);
        // a name it doesn't know: the files
        let other = FakeFs::default().with(LOADER_INFO, &loader_info("rEFInd 0.14"));
        assert_eq!(
            bootloader(&mut FakeRun::default(), &other, false),
            Bootloader::Unknown
        );
    }

    /// An installed system from the ISO, as its user sees it: /boot unreadable, snapper with
    /// its configuration, snap-pac, grub-btrfs and its daemon, the overlay hook.
    fn installed_fs() -> FakeFs {
        FakeFs::default()
            .with(SYSTEM_BUS, "")
            .with("/etc/default/grub", "")
            .with("/usr/share/libalpm/hooks/05-snap-pac-pre.hook", "")
            .with(
                "/etc/mkinitcpio.conf",
                "# HOOKS=(base udev)\nMODULES=()\nHOOKS=(base udev plymouth autodetect microcode modconf kms keyboard keymap consolefont block encrypt filesystems fsck grub-btrfs-overlayfs)\n",
            )
    }

    fn installed_run() -> FakeRun {
        FakeRun::default()
            .answer("findmnt -no FSTYPE /", 0, "btrfs\n")
            .answer("findmnt -no TARGET /boot", 0, "/boot\n")
            .answer("snapper --version", 0, "snapper 0.13.2\n")
            .answer(LIST_CONFIGS, 0, "home\nroot\n")
            .answer("pacman -Qq grub", 0, "grub\n")
            .answer("pacman -Qq grub-btrfs", 0, "grub-btrfs\n")
            .answer(GRUBD, 0, "enabled\n")
    }

    #[test]
    fn detects_an_installed_system_as_its_user() {
        let mut r = installed_run().answer(LIST_ROOT, 0, "1\n2\n");
        let e = detect(&mut r, &installed_fs());
        assert!(e.snapshots() && e.snap_pac && e.boot_menu && e.boot_separate);
        assert_eq!(e.bootloader, Bootloader::Grub);
        assert!(e.boot_overlay && e.readable && !e.offline);
        assert_eq!(
            e.summary(),
            "bromigos update's own pre/post pair (snap-pac's around any other pacman run); boot menu: GRUB lists them (grub-btrfs)"
        );
        assert!(!e.needs_setup());
        // snapper answers "No permissions." to the user: updates aren't recorded, and it says so
        let mut r = installed_run().answer(LIST_ROOT, 1, "");
        let e = detect(&mut r, &installed_fs());
        assert!(e.unrecorded() && e.needs_setup());
        assert!(
            e.summary().contains("bromigos rollback allow"),
            "{}",
            e.summary()
        );
        // no overlay hook: a snapshot booted from GRUB is read-only, and setup has work
        let fs = installed_fs().with("/etc/mkinitcpio.conf", "HOOKS=(base udev filesystems)\n");
        let mut r = installed_run().answer(LIST_ROOT, 0, "1\n");
        let e = detect(&mut r, &fs);
        assert!(!e.boot_overlay && e.needs_setup());
        assert!(e.summary().contains("read-only"), "{}", e.summary());
    }

    #[test]
    fn in_a_chroot_the_files_say_what_snapperd_cant() {
        // no system bus: snapper's D-Bus calls fail, its files have the configuration
        let fs = FakeFs::default()
            .with("/etc/snapper/configs/root", "SUBVOLUME=\"/\"\n")
            .with("/etc/conf.d/snapper", "SNAPPER_CONFIGS=\"root home\"\n");
        let mut r = FakeRun::default()
            .answer("findmnt -no FSTYPE /", 0, "btrfs\n")
            .answer("snapper --version", 0, "snapper 0.13.2\n")
            .answer(LIST_CONFIGS, 1, "");
        let e = detect(&mut r, &fs);
        assert!(e.offline && e.config && !e.readable);
        assert!(!e.unrecorded(), "a chroot can't tell; it doesn't claim it");
        // SNAPPER_CONFIGS without root: none
        let fs = fs.with("/etc/conf.d/snapper", "SNAPPER_CONFIGS=\"home\"\n");
        let mut r = FakeRun::default()
            .answer("findmnt -no FSTYPE /", 0, "btrfs\n")
            .answer("snapper --version", 0, "")
            .answer(LIST_CONFIGS, 1, "");
        assert!(!detect(&mut r, &fs).config);
    }

    // ---------------------------------------------------------- who may list

    #[test]
    fn access_adds_what_is_missing_and_keeps_the_rest() {
        let cur = |pairs: &[(&str, &str)]| -> BTreeMap<String, String> {
            pairs
                .iter()
                .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
                .collect()
        };
        let p = |v: Vec<(String, String)>| -> Vec<String> {
            v.into_iter().map(|(k, v)| format!("{k}={v}")).collect()
        };
        // a configuration snapper just made: wheel and the ACL
        assert_eq!(
            p(access_pairs(&BTreeMap::new(), &tester())),
            vec!["ALLOW_GROUPS=wheel", "SYNC_ACL=yes"]
        );
        // a user outside wheel is named too
        let outsider = Who {
            user: Some("ann".into()),
            groups: vec!["ann".into(), "users".into()],
        };
        assert_eq!(
            p(access_pairs(&BTreeMap::new(), &outsider)),
            vec!["ALLOW_GROUPS=wheel", "ALLOW_USERS=ann", "SYNC_ACL=yes"]
        );
        // groups and users already there stay
        let c = cur(&[
            ("ALLOW_GROUPS", "admins"),
            ("ALLOW_USERS", "bob"),
            ("SYNC_ACL", "no"),
        ]);
        assert_eq!(
            p(access_pairs(&c, &outsider)),
            vec![
                "ALLOW_GROUPS=admins wheel",
                "ALLOW_USERS=bob ann",
                "SYNC_ACL=yes"
            ]
        );
        // the operator's machine (ALLOW_USERS=him, SYNC_ACL=yes): only wheel is new
        let c = cur(&[
            ("ALLOW_GROUPS", ""),
            ("ALLOW_USERS", "operator1"),
            ("SYNC_ACL", "yes"),
        ]);
        let him = Who {
            user: Some("operator1".into()),
            groups: vec!["operator1".into(), "wheel".into()],
        };
        assert_eq!(p(access_pairs(&c, &him)), vec!["ALLOW_GROUPS=wheel"]);
        // the ISO's (wheel, SYNC_ACL): nothing to change
        let c = cur(&[("ALLOW_GROUPS", "wheel"), ("SYNC_ACL", "yes")]);
        assert!(access_pairs(&c, &tester()).is_empty());
        // root itself: just wheel and the ACL
        assert_eq!(
            p(access_pairs(&BTreeMap::new(), &Who::default())),
            vec!["ALLOW_GROUPS=wheel", "SYNC_ACL=yes"]
        );
    }

    #[test]
    fn parses_get_config() {
        let c = parse_config(
            "key,value\nALLOW_GROUPS,\nALLOW_USERS,operator1\nSUBVOLUME,/\nSYNC_ACL,yes\n",
        );
        assert_eq!(c.get("ALLOW_GROUPS").map(String::as_str), Some(""));
        assert_eq!(c.get("ALLOW_USERS").map(String::as_str), Some("operator1"));
        assert_eq!(c.get("SYNC_ACL").map(String::as_str), Some("yes"));
        assert!(!c.contains_key("key"));
    }

    fn env_of(r: &mut FakeRun, fs: &FakeFs) -> Env {
        detect(r, fs)
    }

    #[test]
    fn allow_reads_as_root_then_sets_whats_missing() {
        const GET: &str = "sudo snapper -c root --csvout get-config --columns key,value";
        let e = env_of(
            &mut installed_run().answer(LIST_ROOT, 1, ""),
            &installed_fs(),
        );
        let mut r = FakeRun::default().on_run(
            GET,
            0,
            "key,value\nALLOW_GROUPS,\nALLOW_USERS,\nSYNC_ACL,no\n",
        );
        let set = allow(&e, &mut r, &tester()).unwrap().unwrap();
        assert_eq!(
            set.join(" "),
            "sudo snapper -c root set-config ALLOW_GROUPS=wheel SYNC_ACL=yes"
        );
        assert_eq!(r.ran, vec![GET.to_owned(), set.join(" ")]);
        // a value with spaces is one argument (snapper takes one key=value per argument)
        let mut r = FakeRun::default().on_run(GET, 0, "ALLOW_GROUPS,admins\nSYNC_ACL,yes\n");
        let set = allow(&e, &mut r, &tester()).unwrap().unwrap();
        assert_eq!(set.last().unwrap(), "ALLOW_GROUPS=admins wheel");
        // nothing missing: nothing set
        let mut r = FakeRun::default().on_run(GET, 0, "ALLOW_GROUPS,wheel\nSYNC_ACL,yes\n");
        assert_eq!(allow(&e, &mut r, &tester()).unwrap(), None);
        assert_eq!(r.ran.len(), 1);
        // sudo refused (no terminal, no password): an error, nothing set
        let mut r =
            FakeRun::default().on_run(GET, 1, "sudo: a terminal is required to read the password");
        let err = allow(&e, &mut r, &tester()).unwrap_err();
        assert!(err.contains("a terminal is required"), "{err}");
        assert_eq!(r.ran.len(), 1);
        // in a chroot: --no-dbus
        let mut off = e.clone();
        off.offline = true;
        let mut r = FakeRun::default().on_run(
            "sudo snapper --no-dbus -c root --csvout get-config --columns key,value",
            0,
            "SYNC_ACL,no\n",
        );
        let set = allow(&off, &mut r, &tester()).unwrap().unwrap();
        assert!(
            set.join(" ")
                .starts_with("sudo snapper --no-dbus -c root set-config")
        );
        // no configuration: an error that says what makes one
        let mut none = e.clone();
        none.config = false;
        assert!(
            allow(&none, &mut FakeRun::default(), &tester())
                .unwrap_err()
                .contains("rollback setup")
        );
    }

    // ---------------------------------------------------------- setup

    #[test]
    fn setup_on_a_fresh_grub_machine() {
        // install.sh's case: btrfs, GRUB, nothing of snapper yet
        let fs = FakeFs::default()
            .with(SYSTEM_BUS, "")
            .with("/etc/default/grub", "")
            .with(
                "/etc/mkinitcpio.conf",
                "HOOKS=(base udev autodetect modconf block filesystems keyboard fsck)\n",
            );
        let mut r = FakeRun::default()
            .answer("findmnt -no FSTYPE /", 0, "btrfs\n")
            .answer("pacman -Qq grub", 0, "grub\n");
        let e = detect(&mut r, &fs);
        assert_eq!(e.bootloader, Bootloader::Grub);
        let mut plan = setup_plan(&e, &mut r, &fs, &tester());
        plan.noconfirm();
        assert!(!plan.allow);
        assert_eq!(
            lines(&plan.commands),
            vec![
                "sudo pacman -S --needed snapper snap-pac grub-btrfs --noconfirm",
                "sudo snapper -c root create-config /",
                "sudo snapper -c root set-config ALLOW_GROUPS=wheel SYNC_ACL=yes",
                "sudo systemctl enable --now grub-btrfsd.service",
                r"sudo sed -i -E s/^(HOOKS=\([^)]*[^ )]) *\)/\1 grub-btrfs-overlayfs)/ /etc/mkinitcpio.conf",
                "sudo mkinitcpio -P",
                "sudo grub-mkconfig -o /boot/grub/grub.cfg",
            ]
        );
        assert!(plan.notes.is_empty(), "{:?}", plan.notes);
    }

    #[test]
    fn setup_on_the_arch_cloud_image() {
        // install.sh on Arch's cloud image: btrfs, GRUB, a systemd initramfs, and a user
        // outside wheel (cloud-init's): the user goes in ALLOW_USERS, the hook can't go in
        let fs = FakeFs::default()
            .with(SYSTEM_BUS, "")
            .with("/boot/grub/grub.cfg", "")
            .with("/etc/default/grub", "")
            .with(
                "/etc/mkinitcpio.conf",
                "HOOKS=(base systemd autodetect microcode modconf kms keyboard sd-vconsole block filesystems fsck)\n",
            );
        let mut r = FakeRun::default()
            .answer("findmnt -no FSTYPE /", 0, "btrfs\n")
            .answer("pacman -Qq grub", 0, "grub\n");
        let cloud = Who {
            user: Some("tester".into()),
            groups: vec!["tester".into()],
        };
        let e = detect(&mut r, &fs);
        assert!(!e.boot_overlay && !e.overlay_fixable);
        let plan = setup_plan(&e, &mut r, &fs, &cloud);
        let c = lines(&plan.commands);
        assert!(c.contains(&"sudo snapper -c root set-config ALLOW_GROUPS=wheel ALLOW_USERS=tester SYNC_ACL=yes".to_owned()), "{c:?}");
        assert!(
            !c.iter()
                .any(|l| l.contains("mkinitcpio") || l.contains(" sed ")),
            "{c:?}"
        );
        assert!(
            plan.notes.iter().any(|n| n.contains("systemd's")),
            "{:?}",
            plan.notes
        );
        // once set up: nothing left (the hook isn't setup's to add), and the summary says why
        let mut r = FakeRun::default()
            .answer("findmnt -no FSTYPE /", 0, "btrfs\n")
            .answer("snapper --version", 0, "")
            .answer(LIST_CONFIGS, 0, "root\n")
            .answer(LIST_ROOT, 0, "1\n")
            .answer("pacman -Qq grub", 0, "grub\n")
            .answer("pacman -Qq grub-btrfs", 0, "grub-btrfs\n")
            .answer(GRUBD, 0, "enabled\n");
        let fs = fs.with("/usr/share/libalpm/hooks/05-snap-pac-pre.hook", "");
        let e = detect(&mut r, &fs);
        assert!(!e.needs_setup(), "{e:?}");
        assert!(
            e.summary()
                .contains("GRUB lists them (grub-btrfs); one booted from it comes up read-only")
        );
    }

    /// /proc/self/mountinfo in arch-chroot's /mnt (its own root mount, 77) and PID 1's (the
    /// live system's, 31).
    const CHROOT_SELF: &str = "77 31 0:51 /@ / rw,relatime shared:40 - btrfs /dev/mapper/root rw,subvol=/@\n\
                               78 77 0:51 /@.snapshots /.snapshots rw shared:41 - btrfs /dev/mapper/root rw,subvol=/@.snapshots\n";
    const LIVE_INIT: &str = "22 1 0:20 / / rw shared:1 - overlay airootfs rw\n\
                             31 22 0:30 / /run/archiso/bootmnt ro - iso9660 /dev/sr0 ro\n";

    #[test]
    fn a_chroot_is_seen_with_the_live_systems_bus_in_it() {
        // arch-chroot binds the live system's /run in: the bus socket is there, but it isn't
        // this root's; the mounts say so
        let fs = FakeFs::default()
            .with(SYSTEM_BUS, "")
            .with("/proc/self/mountinfo", CHROOT_SELF)
            .with("/proc/1/mountinfo", LIVE_INIT);
        assert!(chrooted(&fs));
        let mut r = FakeRun::default().answer("findmnt -no FSTYPE /", 0, "btrfs\n");
        assert!(detect(&mut r, &fs).offline);
        // the booted system: the same root mount as PID 1's
        let booted = "31 1 0:28 /@ / rw shared:1 - btrfs /dev/nvme0n1p2 rw,subvol=/@\n";
        let fs = FakeFs::default()
            .with(SYSTEM_BUS, "")
            .with("/proc/self/mountinfo", booted)
            .with("/proc/1/mountinfo", booted);
        assert!(!chrooted(&fs));
        assert!(!detect(&mut r, &fs).offline);
        // nothing to read: not a chroot
        assert!(!chrooted(&FakeFs::default()));
    }

    #[test]
    fn setup_in_the_isos_chroot() {
        // archinstall's system in arch-chroot, as the installer's user: the live system's
        // /run (its bus, which must not be asked) and UEFI variables (its systemd-boot), @.snapshots
        // mounted on /.snapshots, grub-btrfs and its daemon (archinstall's), Plymouth's hook
        let fs = FakeFs::default()
            .with(SYSTEM_BUS, "")
            .with("/proc/self/mountinfo", CHROOT_SELF)
            .with("/proc/1/mountinfo", LIVE_INIT)
            .with(LOADER_INFO, &loader_info("systemd-boot 258"))
            .with("/etc/default/grub", "")
            .with("/.snapshots", "")
            .with("/usr/share/libalpm/hooks/05-snap-pac-pre.hook", "")
            .with("/etc/mkinitcpio.conf", "HOOKS=(base udev plymouth autodetect microcode modconf kms keyboard keymap consolefont block encrypt filesystems fsck)\n");
        let mut r = FakeRun::default()
            .answer("findmnt -no FSTYPE /", 0, "btrfs\n")
            .answer(
                "findmnt -no SOURCE /.snapshots",
                0,
                "/dev/mapper/root[/@.snapshots]\n",
            )
            .answer("snapper --version", 0, "snapper 0.13.2\n")
            // the live system's snapperd and systemd would answer: they mustn't be asked
            .answer(LIST_CONFIGS, 0, "")
            .answer(GRUBD, 0, "disabled\n")
            .answer("pacman -Qq grub", 0, "grub\n")
            .answer("pacman -Qq grub-btrfs", 0, "grub-btrfs\n")
            .answer(GRUBD_FILES, 0, "enabled\n");
        let e = detect(&mut r, &fs);
        assert_eq!(
            e.bootloader,
            Bootloader::Grub,
            "not the live medium's systemd-boot"
        );
        assert!(e.offline && !e.config && e.boot_menu && !e.boot_overlay);
        let plan = setup_plan(&e, &mut r, &fs, &tester());
        assert_eq!(
            lines(&plan.commands),
            vec![
                "sudo umount /.snapshots",
                "sudo rmdir /.snapshots",
                "sudo snapper --no-dbus -c root create-config /",
                "sudo btrfs subvolume delete /.snapshots",
                "sudo mkdir /.snapshots",
                "sudo mount -o subvol=/@.snapshots /dev/mapper/root /.snapshots",
                "sudo chmod 750 /.snapshots",
                "sudo snapper --no-dbus -c root set-config ALLOW_GROUPS=wheel SYNC_ACL=yes",
                r"sudo sed -i -E s/^(HOOKS=\([^)]*[^ )]) *\)/\1 grub-btrfs-overlayfs)/ /etc/mkinitcpio.conf",
                "sudo mkinitcpio -P",
            ]
        );
        assert!(!plan.allow);
        // the daemon not enabled yet: enabled only (nothing starts in a chroot)
        let mut r2 = FakeRun::default()
            .answer("findmnt -no FSTYPE /", 0, "btrfs\n")
            .answer("snapper --version", 0, "")
            .answer(LIST_CONFIGS, 1, "")
            .answer("pacman -Qq grub", 0, "grub\n")
            .answer("pacman -Qq grub-btrfs", 0, "grub-btrfs\n");
        let e2 = detect(&mut r2, &fs);
        let plan = setup_plan(&e2, &mut r2, &fs, &tester());
        assert!(
            lines(&plan.commands).contains(&"sudo systemctl enable grub-btrfsd.service".to_owned())
        );
        // the same on the running system once set up: nothing to do
        let fs = installed_fs();
        let mut r = installed_run().answer(LIST_ROOT, 0, "1\n");
        let e = detect(&mut r, &fs);
        let plan = setup_plan(&e, &mut r, &fs, &tester());
        assert!(
            plan.commands.is_empty() && !plan.allow && plan.notes.is_empty(),
            "{plan:?}"
        );
        // … unless the user may not list the snapshots: allow
        let mut r = installed_run().answer(LIST_ROOT, 1, "");
        let e = detect(&mut r, &fs);
        let plan = setup_plan(&e, &mut r, &fs, &tester());
        assert!(plan.commands.is_empty() && plan.allow);
    }

    #[test]
    fn setup_leaves_other_snapshot_layouts_alone() {
        // a /.snapshots that isn't a mounted subvolume: a note, no configuration made
        let fs = FakeFs::default()
            .with(SYSTEM_BUS, "")
            .with("/.snapshots", "");
        let mut r = FakeRun::default()
            .answer("findmnt -no FSTYPE /", 0, "btrfs\n")
            .answer("snapper --version", 0, "");
        let e = detect(&mut r, &fs);
        let plan = setup_plan(&e, &mut r, &fs, &tester());
        assert!(
            !lines(&plan.commands)
                .iter()
                .any(|c| c.contains("create-config") || c.contains("set-config"))
        );
        assert!(plan.notes.iter().any(|n| n.contains("/.snapshots exists")));
        // ext4: nothing
        let mut r = FakeRun::default().answer("findmnt -no FSTYPE /", 0, "ext4\n");
        let e = detect(&mut r, &FakeFs::default());
        let plan = setup_plan(&e, &mut r, &FakeFs::default(), &tester());
        assert!(plan.commands.is_empty() && plan.notes[0].contains("snapshots need btrfs"));
    }

    // ---------------------------------------------------------- the overlay hook

    #[test]
    fn parses_hooks() {
        let f = parse_hooks(
            "/etc/mkinitcpio.conf",
            "#HOOKS=(base)\n#    HOOKS=(base udev)\nMODULES=()\nHOOKS=(base udev autodetect) # mine\n",
        )
        .unwrap();
        assert_eq!(
            f.hooks.as_deref(),
            Some(&["base".to_owned(), "udev".into(), "autodetect".into()][..])
        );
        assert!(f.one_line);
        let f = parse_hooks(
            "x",
            "HOOKS=(base\n  udev # the devices\n  filesystems)\nHOOKS+=(fsck)\n",
        )
        .unwrap();
        assert_eq!(f.hooks.as_ref().unwrap().len(), 3);
        assert!(!f.one_line);
        assert_eq!(f.added, vec!["fsck"]);
        assert!(parse_hooks("x", "MODULES=(btrfs)\n").is_none());
        // a drop-in sets HOOKS after the main file: its own are in force
        let main = parse_hooks(
            "/etc/mkinitcpio.conf",
            "HOOKS=(base udev grub-btrfs-overlayfs)\n",
        )
        .unwrap();
        let drop = parse_hooks("/etc/mkinitcpio.conf.d/x.conf", "HOOKS=(base systemd)\n").unwrap();
        assert_eq!(
            hooks_in_force(&[main.clone(), drop]),
            vec!["base", "systemd"]
        );
        let add = parse_hooks("/etc/mkinitcpio.conf.d/y.conf", "HOOKS+=(extra)\n").unwrap();
        assert!(add.hooks.is_none());
        assert_eq!(
            hooks_in_force(&[main, add]),
            vec!["base", "udev", "grub-btrfs-overlayfs", "extra"]
        );
    }

    #[test]
    fn the_hook_edit_puts_it_last() {
        let t = tempfile::tempdir().unwrap();
        let conf = t.path().join("mkinitcpio.conf");
        let text = "# HOOKS=(base udev)\nMODULES=()\nHOOKS=(base udev plymouth block encrypt filesystems fsck)\nCOMPRESSION=\"zstd\"\n";
        fs::write(&conf, text).unwrap();
        let a = add_hook_command(conf.to_str().unwrap(), OVERLAY_HOOK);
        assert_eq!(&a[..2], &["sudo", "sed"]);
        // run the edit itself (without sudo: the file is ours)
        let st = std::process::Command::new(&a[1])
            .args(&a[2..])
            .status()
            .unwrap();
        assert!(st.success());
        let got = fs::read_to_string(&conf).unwrap();
        assert_eq!(
            got,
            "# HOOKS=(base udev)\nMODULES=()\nHOOKS=(base udev plymouth block encrypt filesystems fsck grub-btrfs-overlayfs)\nCOMPRESSION=\"zstd\"\n"
        );
        let f = parse_hooks("x", &got).unwrap();
        assert_eq!(
            f.hooks.unwrap().last().map(String::as_str),
            Some(OVERLAY_HOOK)
        );
    }

    #[test]
    fn overlay_hook_plans() {
        let plan_of = |fs: &FakeFs| {
            let mut cmds = vec![];
            let mut notes = vec![];
            overlay_plan(fs, &mut cmds, &mut notes);
            (lines(&cmds), notes)
        };
        // there already: nothing
        let fs = FakeFs::default().with(
            "/etc/mkinitcpio.conf",
            "HOOKS=(base udev fsck grub-btrfs-overlayfs)\n",
        );
        assert_eq!(plan_of(&fs), (vec![], vec![]));
        // every file that sets HOOKS without it is edited, then the images are made again
        let fs = FakeFs::default()
            .with("/etc/mkinitcpio.conf", "HOOKS=(base udev fsck)\n")
            .with(
                "/etc/mkinitcpio.conf.d/10-mine.conf",
                "HOOKS=(base udev plymouth fsck)\n",
            )
            .with("/etc/mkinitcpio.conf.d/20-more.conf", "HOOKS+=(extra)\n")
            .with("/etc/mkinitcpio.conf.d/readme.txt", "HOOKS=(no)\n");
        let (c, n) = plan_of(&fs);
        assert_eq!(c.len(), 3, "{c:?}");
        assert!(c[0].ends_with(" /etc/mkinitcpio.conf") && c[1].ends_with("/10-mine.conf"));
        assert_eq!(c[2], "sudo mkinitcpio -P");
        assert!(n.is_empty());
        // a systemd initramfs runs no busybox hook: a note
        let fs = FakeFs::default().with(
            "/etc/mkinitcpio.conf",
            "HOOKS=(base systemd autodetect sd-encrypt filesystems)\n",
        );
        let (c, n) = plan_of(&fs);
        assert!(c.is_empty() && n[0].contains("systemd"));
        // HOOKS over several lines: by hand
        let fs = FakeFs::default().with("/etc/mkinitcpio.conf", "HOOKS=(base\n udev\n fsck)\n");
        let (c, n) = plan_of(&fs);
        assert!(c.is_empty() && n[0].contains("spans several lines"));
        // no mkinitcpio at all: a note
        let (c, n) = plan_of(&FakeFs::default());
        assert!(c.is_empty() && n[0].contains("no mkinitcpio HOOKS"));
    }

    #[test]
    fn subvolume_sources() {
        assert_eq!(
            parse_source("/dev/mapper/root[/@.snapshots]\n"),
            Some(("/dev/mapper/root".into(), "/@.snapshots".into()))
        );
        assert_eq!(parse_source("/dev/vda2"), None);
        assert_eq!(parse_source("[/@x]"), None);
    }

    #[test]
    fn summaries() {
        let mut e = Env {
            fs: "ext4".into(),
            btrfs: false,
            snapper: false,
            config: false,
            snap_pac: false,
            bootloader: Bootloader::Grub,
            boot_menu: false,
            boot_separate: false,
            boot_overlay: false,
            overlay_fixable: true,
            readable: true,
            offline: false,
            booted: None,
        };
        assert!(e.summary().starts_with("none: / is ext4"));
        assert!(!e.needs_setup(), "not btrfs: nothing to set up");
        e.fs = "btrfs".into();
        e.btrfs = true;
        e.snapper = true;
        e.config = true;
        e.snap_pac = true;
        assert!(e.summary().contains("snap-pac") && e.summary().contains("not yet (grub-btrfs"));
        e.boot_menu = true;
        e.boot_overlay = true;
        assert!(e.summary().contains("GRUB lists them"));
        assert!(!e.needs_setup());
        // a systemd initramfs: the hook can't go in, so setup has nothing to do, and it says why
        e.boot_overlay = false;
        e.overlay_fixable = false;
        assert!(!e.needs_setup());
        assert!(
            e.summary().contains("comes up read-only"),
            "{}",
            e.summary()
        );
        e.overlay_fixable = true;
        assert!(e.needs_setup() && e.summary().contains("no grub-btrfs-overlayfs hook"));
        e.bootloader = Bootloader::SystemdBoot;
        e.boot_menu = false;
        assert!(!e.needs_setup(), "systemd-boot: nothing a setup could add");
    }

    // ---------------------------------------------------------- booted from a snapshot

    /// The ISO's machine booted from GRUB's snapshot 3, as the VM showed it (BIOS, plain
    /// btrfs; 2026-10-09): grub-btrfs-overlayfs's overlay over the snapshot, /.snapshots and
    /// /boot mounted as usual.
    const SNAP_CMDLINE: &str = "BOOT_IMAGE=/vmlinuz-linux root=UUID=40f82c71-4a33-40c8-b6ff-55a463706c47 zswap.enabled=0 rootfstype=btrfs loglevel=3 quiet splash rootflags=rw,relatime,discard=async,space_cache=v2,subvol=@.snapshots/3/snapshot\n";
    const NORMAL_CMDLINE: &str = "BOOT_IMAGE=/vmlinuz-linux root=UUID=40f82c71-4a33-40c8-b6ff-55a463706c47 rw rootflags=subvol=@ zswap.enabled=0 rootfstype=btrfs loglevel=3 quiet splash\n";
    const SNAP_MOUNTINFO: &str = "29 35 0:26 / /run rw,nosuid,nodev,relatime shared:11 - tmpfs run rw,mode=755\n\
        35 2 0:33 / / rw,relatime shared:1 - overlay rootfs rw,lowerdir=/tmp.Ai9Lzg,upperdir=/tmp.LfAYUZ/upper,workdir=/tmp.LfAYUZ/work,uuid=on\n\
        67 35 0:28 /@.snapshots /.snapshots rw,relatime shared:109 - btrfs /dev/vda2 rw,discard=async,space_cache=v2,subvolid=257,subvol=/@.snapshots\n\
        68 35 0:28 /@home /home rw,relatime shared:110 - btrfs /dev/vda2 rw,discard=async,space_cache=v2,subvolid=258,subvol=/@home\n\
        167 35 254:1 / /boot rw,relatime shared:125 - vfat /dev/vda1 rw,fmask=0022\n";
    const NORMAL_MOUNTINFO: &str = "35 2 0:28 /@ / rw,relatime shared:1 - btrfs /dev/vda2 rw,discard=async,space_cache=v2,subvolid=256,subvol=/@\n\
        67 35 0:28 /@.snapshots /.snapshots rw,relatime shared:109 - btrfs /dev/vda2 rw,subvolid=257,subvol=/@.snapshots\n";
    const ISO_FSTAB: &str = "# /dev/vda2\n\
        UUID=40f82c71-4a33-40c8-b6ff-55a463706c47\t/         \tbtrfs     \trw,relatime,discard=async,space_cache=v2,subvol=/@\t0 0\n\n\
        UUID=40f82c71-4a33-40c8-b6ff-55a463706c47\t/.snapshots\tbtrfs     \trw,relatime,discard=async,space_cache=v2,subvol=/@.snapshots\t0 0\n\
        UUID=3E84-6E90      \t/boot     \tvfat      \trw,relatime,fmask=0022,dmask=0022,codepage=437,iocharset=ascii,shortname=mixed,utf8,errors=remount-ro\t0 2\n";
    const INFO_3: &str = "<?xml version=\"1.0\"?>\n<snapshot>\n  <type>pre</type>\n  <num>3</num>\n  <date>2026-10-09 18:19:27</date>\n  <description>pacman -Syu</description>\n  <cleanup>number</cleanup>\n</snapshot>\n";

    fn snapshot_boot() -> FakeFs {
        FakeFs::default()
            .with("/proc/cmdline", SNAP_CMDLINE)
            .with("/proc/self/mountinfo", SNAP_MOUNTINFO)
            .with("/etc/fstab", ISO_FSTAB)
            .with("/.snapshots/3/info.xml", INFO_3)
            .with("/usr/lib/modules/7.2.9-arch1-1", "")
            .with("/usr/lib/modules/7.2.9-arch1-1/vmlinuz", "")
            .with("/usr/lib/modules/7.2.9-arch1-1/pkgbase", "linux\n")
            .with("/etc/mkinitcpio.d/linux.preset", "")
    }

    fn state_with(lines: &str) -> (tempfile::TempDir, Paths) {
        let t = tempfile::tempdir().unwrap();
        let state = t.path().join("state");
        fs::create_dir_all(state.join("bromigos")).unwrap();
        fs::write(state.join("bromigos/updates.jsonl"), lines).unwrap();
        let p = Paths::from_lookup(|k| match k {
            "HOME" => Some(t.path().to_path_buf()),
            "XDG_STATE_HOME" => Some(state.clone()),
            _ => None,
        });
        (t, p)
    }

    const TWO_UPDATES: &str = "{\"at\":\"2026-10-09T06:07:37+00:00\",\"channel\":\"stable\",\"snapshot\":{\"pre\":1,\"post\":2},\"packages\":[\"bromigos-core a -> b\"],\"rolled_back\":false}\n\
        {\"at\":\"2026-10-09T18:19:30+00:00\",\"channel\":\"edge\",\"snapshot\":{\"pre\":3,\"post\":4},\"packages\":[\"bromigos-core b -> c\"],\"rolled_back\":false}\n";

    #[test]
    fn the_kernel_line_names_the_booted_snapshot() {
        let b = booted_from(SNAP_CMDLINE).unwrap();
        assert_eq!(b.number, 3);
        assert_eq!(b.subvol, "@.snapshots/3/snapshot");
        assert_eq!(b.device, "UUID=40f82c71-4a33-40c8-b6ff-55a463706c47");
        // the normal root, and other layouts' snapshot paths
        assert_eq!(booted_from(NORMAL_CMDLINE), None);
        let b = booted_from("root=/dev/mapper/root rootflags=subvol=\"/@/.snapshots/12/snapshot\"").unwrap();
        assert_eq!((b.number, b.subvol.as_str()), (12, "@/.snapshots/12/snapshot"));
        assert_eq!(booted_from("rootflags=subvol=@.snapshots/3/snapshot"), None, "no root=");
        assert_eq!(booted_from("root=/dev/vda2 rootflags=subvol=@.snapshots/x/snapshot"), None);
    }

    #[test]
    fn a_snapshot_boot_is_an_overlay_or_read_only() {
        assert_eq!(booted(&snapshot_boot()).map(|b| b.number), Some(3));
        // the read-only snapshot itself (a systemd initramfs: no overlay hook)
        let ro = snapshot_boot().with(
            "/proc/self/mountinfo",
            "35 2 0:28 /@.snapshots/3/snapshot / ro,relatime shared:1 - btrfs /dev/vda2 ro,subvolid=265,subvol=/@.snapshots/3/snapshot\n",
        );
        assert_eq!(booted(&ro).map(|b| b.number), Some(3));
        // a root that is a snapshot, mounted writable (btrfs's default subvolume layout):
        // the normal system, where --rollback undoes in place
        let rw = snapshot_boot().with(
            "/proc/self/mountinfo",
            "35 2 0:28 /@/.snapshots/1/snapshot / rw,relatime shared:1 - btrfs /dev/vda2 rw,subvolid=265,subvol=/@/.snapshots/1/snapshot\n",
        );
        assert_eq!(booted(&rw), None);
        let normal = snapshot_boot()
            .with("/proc/cmdline", NORMAL_CMDLINE)
            .with("/proc/self/mountinfo", NORMAL_MOUNTINFO);
        assert_eq!(booted(&normal), None);
    }

    #[test]
    fn fstab_says_how_the_root_is_mounted() {
        assert_eq!(root_layout(ISO_FSTAB), RootLayout::Named("@".into()));
        assert_eq!(
            root_layout("UUID=x / btrfs rw,subvol=@root 0 0\n"),
            RootLayout::Named("@root".into())
        );
        assert_eq!(root_layout("UUID=x / btrfs rw,relatime 0 0\n"), RootLayout::Default);
        assert!(matches!(
            root_layout("UUID=x / btrfs rw,subvolid=256 0 0\n"),
            RootLayout::Other(w) if w.contains("subvolid")
        ));
        assert!(matches!(root_layout("UUID=x / ext4 rw 0 1\n"), RootLayout::Other(_)));
        assert!(matches!(root_layout("# UUID=x / btrfs rw,subvol=@ 0 0\n"), RootLayout::Other(_)));
        assert_eq!(
            boot_modules(ISO_FSTAB),
            Some(vec!["vfat".into(), "nls_cp437".into(), "nls_ascii".into()])
        );
        assert_eq!(boot_modules("UUID=x /boot ext4 rw 0 2\n"), Some(vec!["ext4".into()]));
        assert_eq!(boot_modules("UUID=x / btrfs rw 0 0\n"), None);
    }

    #[test]
    fn a_kernel_goes_back_only_when_boot_runs_another() {
        let fs = snapshot_boot();
        assert!(kernels_to_restore(&fs, "7.2.9-arch1-1").is_empty());
        assert_eq!(
            kernels_to_restore(&fs, "7.2.10-arch1-1"),
            vec![Kernel { pkgbase: "linux".into(), release: "7.2.9-arch1-1".into() }]
        );
    }

    #[test]
    fn making_the_booted_snapshot_the_root() {
        let (_t, paths) = state_with(TWO_UPDATES);
        let fs = snapshot_boot();
        let b = booted(&fs).unwrap();
        let mut r = FakeRun::default().answer("uname -r", 0, "7.2.9-arch1-1\n");
        let plan = make_root_plan(&paths, &mut r, &fs, &b, "20261009-183012").unwrap();
        assert_eq!(plan.root, "@");
        assert_eq!(plan.kept, "@.before-rollback-20261009-183012");
        assert_eq!(plan.date.as_deref(), Some("2026-10-09 18:19:27"));
        assert_eq!(plan.description.as_deref(), Some("pacman -Syu"));
        assert!(plan.kernels.is_empty());
        // the update made at the snapshot (pre 3) is undone; the one before it isn't
        assert_eq!(plan.undoes.len(), 1);
        assert_eq!(plan.undoes[0].snapshot, Some(Pair { pre: 3, post: 4 }));
        let cmds: Vec<String> = plan.steps.iter().map(|(_, c)| c.join(" ")).collect();
        assert_eq!(
            cmds,
            [
                "sudo mkdir -p /run/bromigos-rollback",
                "sudo mount -o subvolid=5 UUID=40f82c71-4a33-40c8-b6ff-55a463706c47 /run/bromigos-rollback",
                "sudo mv -T /run/bromigos-rollback/@ /run/bromigos-rollback/@.before-rollback-20261009-183012",
                "sudo btrfs subvolume snapshot /run/bromigos-rollback/@.snapshots/3/snapshot /run/bromigos-rollback/@",
                // snap-pac's pre snapshot is taken inside pacman's transaction: its lock
                // came along (the VM's first boot after this said "unable to lock database")
                "sudo rm -f /run/bromigos-rollback/@/var/lib/pacman/db.lck",
                "sudo umount /run/bromigos-rollback",
                "sudo rmdir /run/bromigos-rollback",
            ]
        );
        let done = make_root(&paths, &mut r, &plan).unwrap();
        assert_eq!(r.ran, cmds);
        assert!(done.notes[0].starts_with("reboot"));
        assert!(done.notes[1].contains("btrfs subvolume delete -R /mnt/@.before-rollback-20261009-183012"));
        // recorded: the update after the snapshot is rolled back, so --check stops offering it
        let recs = records(&paths);
        assert!(recs[1].rolled_back && !recs[0].rolled_back);
        let text = fs::read_to_string(log_path(&paths)).unwrap();
        assert!(text.lines().last().unwrap().contains("\"root\":3"), "{text}");
    }

    #[test]
    fn the_snapshots_kernel_goes_back_into_boot() {
        let (_t, paths) = state_with("");
        let fs = snapshot_boot();
        let b = booted(&fs).unwrap();
        // GRUB booted /boot's newer kernel; the snapshot has 7.2.9's modules only
        let mut r = FakeRun::default().answer("uname -r", 0, "7.2.10-arch1-1\n");
        let plan = make_root_plan(&paths, &mut r, &fs, &b, "s").unwrap();
        assert!(plan.undoes.is_empty());
        let cmds: Vec<String> = plan.steps.iter().map(|(_, c)| c.join(" ")).collect();
        // before the top level is unmounted; /boot is mounted, so straight in
        assert_eq!(
            &cmds[5..],
            [
                "sudo install -m 0644 /usr/lib/modules/7.2.9-arch1-1/vmlinuz /boot/vmlinuz-linux",
                "sudo mkinitcpio -p linux",
                "sudo umount /run/bromigos-rollback",
                "sudo rmdir /run/bromigos-rollback",
            ]
        );
        // that boot couldn't mount /boot (the VM's: emergency mode, boot.mount failed, as
        // vfat's module for /boot's kernel isn't in the snapshot): the replaced root lends
        // the modules, then /boot mounts
        let unmounted = snapshot_boot().with(
            "/proc/self/mountinfo",
            &SNAP_MOUNTINFO.replace("167 35 254:1 / /boot rw,relatime shared:125 - vfat /dev/vda1 rw,fmask=0022\n", ""),
        );
        let plan = make_root_plan(&paths, &mut r, &unmounted, &b, "s").unwrap();
        let cmds: Vec<String> = plan.steps.iter().map(|(_, c)| c.join(" ")).collect();
        assert_eq!(
            &cmds[5..7],
            [
                "sudo modprobe -d /run/bromigos-rollback/@.before-rollback-s -a vfat nls_cp437 nls_ascii",
                "sudo mount /boot",
            ]
        );
        // a failure there leaves the rest to type, the top level still mounted for it
        let mut r2 = FakeRun::default().on_run(&cmds[5], 1, "modprobe: FATAL: Module vfat not found");
        let e = make_root(&paths, &mut r2, &plan).unwrap_err();
        assert!(e.contains("is the root now") && e.contains("sudo mount /boot; sudo install"), "{e}");
        assert!(!r2.ran.iter().any(|c| c.contains("umount")), "{:?}", r2.ran);
        // no preset to rebuild with: said, not done
        let fs = snapshot_boot().without("/etc/mkinitcpio.d/linux.preset");
        let plan = make_root_plan(&paths, &mut r, &fs, &b, "s").unwrap();
        assert_eq!(plan.steps.len(), 7);
        assert!(plan.notes[0].contains("put the snapshot's kernel into /boot"), "{:?}", plan.notes);
        // nothing recorded before: one line says what became the root
        make_root(&paths, &mut r, &plan).unwrap();
        let text = fs::read_to_string(log_path(&paths)).unwrap();
        assert_eq!(text.lines().count(), 1);
        assert!(text.contains("\"root\":3") && text.contains("\"snapshot\":null"), "{text}");
    }

    #[test]
    fn a_failed_copy_puts_the_root_back() {
        let (_t, paths) = state_with(TWO_UPDATES);
        let fs = snapshot_boot();
        let b = booted(&fs).unwrap();
        let mut r = FakeRun::default().answer("uname -r", 0, "7.2.9-arch1-1\n").on_run(
            "sudo btrfs subvolume snapshot /run/bromigos-rollback/@.snapshots/3/snapshot /run/bromigos-rollback/@",
            1,
            "ERROR: no space left",
        );
        let plan = make_root_plan(&paths, &mut r, &fs, &b, "s").unwrap();
        let e = make_root(&paths, &mut r, &plan).unwrap_err();
        assert!(e.contains("no space left") && e.contains("@ is back as it was"), "{e}");
        assert_eq!(
            &r.ran[4..],
            [
                "sudo mv -T /run/bromigos-rollback/@.before-rollback-s /run/bromigos-rollback/@",
                "sudo umount /run/bromigos-rollback",
            ]
        );
        assert!(!records(&paths)[1].rolled_back, "nothing recorded");
        // a failed mount changes nothing, and unmounts nothing
        let mut r = FakeRun::default().answer("uname -r", 0, "7.2.9-arch1-1\n").on_run(
            "sudo mount -o subvolid=5 UUID=40f82c71-4a33-40c8-b6ff-55a463706c47 /run/bromigos-rollback",
            32,
            "",
        );
        assert!(make_root(&paths, &mut r, &plan).is_err());
        assert_eq!(r.ran.len(), 2);
        // an unmount that fails is the reboot's: the rollback stands
        let mut r = FakeRun::default().on_run("sudo umount /run/bromigos-rollback", 32, "target is busy");
        let done = make_root(&paths, &mut r, &plan).unwrap();
        assert!(done.notes.iter().any(|n| n.contains("target is busy")));
    }

    #[test]
    fn layouts_it_cant_change_are_refused_with_what_to_do() {
        let (_t, paths) = state_with("");
        let b = booted(&snapshot_boot()).unwrap();
        let mut r = FakeRun::default();
        let fs = snapshot_boot().with("/etc/fstab", "UUID=x / btrfs rw,relatime 0 0\n");
        let e = make_root_plan(&paths, &mut r, &fs, &b, "s").unwrap_err();
        assert!(e.contains("default subvolume") && e.contains("set-default"), "{e}");
        let fs = snapshot_boot().with("/etc/fstab", "UUID=x / btrfs rw,subvolid=256 0 0\n");
        let e = make_root_plan(&paths, &mut r, &fs, &b, "s").unwrap_err();
        assert!(e.contains("subvolid") && e.contains("docs/update.md"), "{e}");
        // the root subvolume in use: not a snapshot boot after all
        let fs = snapshot_boot().with(
            "/proc/self/mountinfo",
            &format!("{SNAP_MOUNTINFO}90 35 0:28 /@ /mnt rw - btrfs /dev/vda2 rw,subvol=/@\n"),
        );
        let e = make_root_plan(&paths, &mut r, &fs, &b, "s").unwrap_err();
        assert!(e.contains("@ is mounted (at /mnt)"), "{e}");
    }

    #[test]
    fn a_snapshot_boot_says_so() {
        let mut r = FakeRun::default().answer("findmnt -no FSTYPE /", 0, "overlay\n");
        let e = env_of(&mut r, &snapshot_boot());
        assert_eq!(e.booted.as_ref().map(|b| b.number), Some(3));
        assert!(e.summary().contains("snapshot 3 from the boot menu"), "{}", e.summary());
        assert!(!e.needs_setup());
    }
}
