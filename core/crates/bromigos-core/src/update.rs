//! `bromigos update` and `bromigos restart`.
//!
//! An update is, in order:
//! 1. the package transaction, `sudo pacman -Syu`, interactive (the user sees its prompts
//!    and answers sudo, a security key, a conflict question themselves);
//! 2. the pending migrations ([`crate::migrate`]); a failed one stops the update there;
//! 3. the theme in force rendered again, so a new theme file lands in `current/` (by the
//!    newly installed bromigos when the update replaced this one), and the theme
//!    switcher's out-of-date previews drawn again in the background, and the boot menu
//!    kept on it where bromigOS's GRUB theme is on ([`crate::boot`]);
//! 4. restarts: each running piece whose package was installed after the process started
//!    (pacman's install date) is restarted, or reloaded when only its config changed. What
//!    can't be restarted from here (Hyprland itself, the kernel) is reported instead.
//!
//! Step 4 compares the running processes with what's installed, not just what this update
//! changed, so `bromigos restart` (or the next `bromigos update`) also catches code left
//! running stale after a bare `pacman -Syu`.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::paths::Paths;
use crate::session;
use crate::theme;

// ------------------------------------------------------------------ packages

/// One installed package, from pacman's local database.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Installed {
    pub version: String,
    /// When it was installed or last upgraded (Unix seconds).
    pub installed: i64,
}

/// Every installed package: name -> version and install time, read from pacman's local
/// database (`/var/lib/pacman/local/<name>-<version>/desc`), no pacman run.
pub fn installed(paths: &Paths) -> BTreeMap<String, Installed> {
    fs::read_dir(&paths.pacman_local)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| parse_desc(&fs::read_to_string(e.path().join("desc")).ok()?))
        .collect()
}

/// `%NAME%`, `%VERSION%` and `%INSTALLDATE%` from a local db `desc` file.
pub fn parse_desc(desc: &str) -> Option<(String, Installed)> {
    let mut field: Option<&str> = None;
    let (mut name, mut version, mut date) = (None, None, None);
    for line in desc.lines() {
        if line.starts_with('%') && line.ends_with('%') {
            field = Some(line);
            continue;
        }
        if line.is_empty() {
            field = None;
            continue;
        }
        match field {
            Some("%NAME%") => name = Some(line.to_owned()),
            Some("%VERSION%") => version = Some(line.to_owned()),
            Some("%INSTALLDATE%") => date = line.parse::<i64>().ok(),
            _ => {}
        }
        field = None;
    }
    Some((
        name?,
        Installed {
            version: version?,
            installed: date.unwrap_or(0),
        },
    ))
}

/// A package whose version changed (or that came or went) between two snapshots.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Changed {
    pub name: String,
    pub from: Option<String>,
    pub to: Option<String>,
}

pub fn changes(
    before: &BTreeMap<String, Installed>,
    after: &BTreeMap<String, Installed>,
) -> Vec<Changed> {
    let names: BTreeSet<&String> = before.keys().chain(after.keys()).collect();
    names
        .into_iter()
        .filter_map(|n| {
            let (b, a) = (before.get(n), after.get(n));
            (b.map(|i| &i.version) != a.map(|i| &i.version)).then(|| Changed {
                name: n.clone(),
                from: b.map(|i| i.version.clone()),
                to: a.map(|i| i.version.clone()),
            })
        })
        .collect()
}

/// An upgrade waiting in the repos.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Available {
    pub name: String,
    pub from: String,
    pub to: String,
}

/// The upgrades waiting, from `checkupdates` (pacman-contrib: a fresh copy of the sync
/// databases, no root). None when it can't tell (not installed, or it failed).
pub fn available() -> Option<Vec<Available>> {
    let o = Command::new("checkupdates")
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .ok()?;
    match o.status.code() {
        Some(0) => Some(parse_checkupdates(&String::from_utf8_lossy(&o.stdout))),
        Some(2) => Some(Vec::new()), // nothing to update
        _ => None,
    }
}

/// `name old -> new` lines.
pub fn parse_checkupdates(text: &str) -> Vec<Available> {
    text.lines()
        .filter_map(|l| {
            let mut w = l.split_whitespace();
            let (name, from, arrow, to) = (w.next()?, w.next()?, w.next()?, w.next()?);
            (arrow == "->").then(|| Available {
                name: name.to_owned(),
                from: from.to_owned(),
                to: to.to_owned(),
            })
        })
        .collect()
}

/// Runs `sudo pacman -Syu` on this terminal (`-Syuu` with `downgrade`: after a move to an
/// older channel, packages newer than the channel's go back; `--noconfirm` with `yes`);
/// returns its exit code. With `skip_snap_pac` (the update made its own pre snapshot)
/// snap-pac's hooks skip this transaction (`SNAP_PAC_SKIP=y`, which sudo passes on for an
/// admin: SETENV comes with ALL).
pub fn pacman_upgrade(downgrade: bool, skip_snap_pac: bool, yes: bool) -> std::io::Result<i32> {
    let s = Command::new("sudo")
        .args(pacman_command(
            downgrade,
            skip_snap_pac,
            yes,
            &upgrade_overwrites(),
        ))
        .status()?;
    Ok(s.code().unwrap_or(1))
}

/// `sudo`'s arguments for the repositories' transaction.
pub fn pacman_command(
    downgrade: bool,
    skip_snap_pac: bool,
    yes: bool,
    overwrites: &[String],
) -> Vec<String> {
    let mut args = vec![];
    if skip_snap_pac {
        args.push("SNAP_PAC_SKIP=y".to_string());
    }
    args.push("pacman".to_string());
    args.push((if downgrade { "-Syuu" } else { "-Syu" }).to_string());
    if yes {
        args.push("--noconfirm".to_string());
    }
    args.extend(overwrites.iter().cloned());
    args
}

/// `--overwrite` for the theme files a hand install put in /usr/share before a package
/// shipped them (bromigos-settings: the SDDM theme, the icon and cursor themes), only
/// where they exist and no package owns them: an update replaces them instead of failing
/// on a file conflict (crate::install::PRE_PACKAGE_PATHS).
pub fn upgrade_overwrites() -> Vec<String> {
    let mut sys = crate::install::System;
    crate::install::overwrite_globs(&mut sys, |p| std::path::Path::new(p).exists())
        .into_iter()
        .flat_map(|g| ["--overwrite".to_string(), g])
        .collect()
}

// ------------------------------------------------------------------ the running pieces

/// The long-running pieces an update can leave stale.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Piece {
    Live,
    Widgets,
    Waybar,
    Dunst,
    Vector,
    Hyprland,
    /// swayosd-server: the volume/brightness/mute on-screen display
    Osd,
    /// hypridle: the idle policy (crate::idle renders its config)
    Idle,
}

impl Piece {
    pub const ALL: [Piece; 8] = [
        Piece::Live,
        Piece::Widgets,
        Piece::Waybar,
        Piece::Dunst,
        Piece::Vector,
        Piece::Hyprland,
        Piece::Osd,
        Piece::Idle,
    ];

    pub fn name(self) -> &'static str {
        match self {
            Piece::Live => "live",
            Piece::Widgets => "widgets",
            Piece::Waybar => "waybar",
            Piece::Dunst => "dunst",
            Piece::Vector => "vector",
            Piece::Hyprland => "hyprland",
            Piece::Osd => "osd",
            Piece::Idle => "idle",
        }
    }

    pub fn parse(s: &str) -> Option<Piece> {
        Piece::ALL.into_iter().find(|p| p.name() == s)
    }

    /// The package its code comes from.
    pub fn package(self) -> &'static str {
        match self {
            Piece::Live => "bromigos-live",
            Piece::Widgets => "bromigos-widgets",
            Piece::Waybar => "waybar",
            Piece::Dunst => "dunst",
            Piece::Vector => "bromigos-vector",
            Piece::Hyprland => "hyprland",
            Piece::Osd => "swayosd",
            Piece::Idle => "hypridle",
        }
    }

    /// It draws with the GPU, so a new process of it needs the graphics driver that's
    /// loaded now: the live layer, and VECTOR (his holograms, and his voice server's
    /// models). After a driver update, until the computer restarts, a new one would fall
    /// back to the CPU ([`crate::reboot`]).
    pub fn needs_gpu(self) -> bool {
        matches!(self, Piece::Live | Piece::Vector)
    }

    /// The package its default config comes from, when that's a different one.
    pub fn config_package(self) -> Option<&'static str> {
        match self {
            Piece::Waybar | Piece::Dunst | Piece::Hyprland | Piece::Osd => Some("bromigos-desktop"),
            _ => None,
        }
    }
}

/// A piece as it runs now.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Running {
    pub piece: Piece,
    pub pids: Vec<i32>,
    /// When its oldest process started (Unix seconds).
    pub started: Option<i64>,
}

fn boot_time(proc: &Path) -> Option<i64> {
    fs::read_to_string(proc.join("stat"))
        .ok()?
        .lines()
        .find_map(|l| l.strip_prefix("btime ")?.trim().parse().ok())
}

/// When a process started (Unix seconds): /proc/<pid>/stat's starttime, in clock ticks
/// since boot. Linux reports them in USER_HZ, which is 100 on every architecture.
fn proc_start(proc: &Path, pid: i32, btime: i64) -> Option<i64> {
    let stat = fs::read_to_string(proc.join(pid.to_string()).join("stat")).ok()?;
    let rest = stat.rsplit_once(") ")?.1;
    let ticks: i64 = rest.split_whitespace().nth(19)?.parse().ok()?;
    Some(btime + ticks / 100)
}

fn argv(proc: &Path, pid: i32) -> Vec<String> {
    fs::read(proc.join(pid.to_string()).join("cmdline"))
        .map(|raw| {
            raw.split(|b| *b == 0)
                .filter(|a| !a.is_empty())
                .map(|a| String::from_utf8_lossy(a).into_owned())
                .collect()
        })
        .unwrap_or_default()
}

fn base(s: &str) -> &str {
    s.rsplit('/').next().unwrap_or(s)
}

/// Whether a command line is one of the piece's processes (by its argument vector, never
/// a substring of the joined line, so a shell or editor that names it doesn't match).
pub fn is_piece(piece: Piece, argv: &[String]) -> bool {
    let a0 = argv.first().map(|s| base(s)).unwrap_or("");
    let py = a0.starts_with("python");
    let module = |m: &str| py && argv.windows(2).any(|w| w[0] == "-m" && w[1] == m);
    match piece {
        Piece::Live => module("live.app"),
        // the app, and his voice server: it runs in its own session to keep its models warm
        // across app restarts, so after an upgrade it would keep running the old code
        Piece::Vector => module("holo.app") || module("holo.voice_server"),
        Piece::Widgets => py && argv.get(1).is_some_and(|a| base(a) == "bromigos-widgets"),
        Piece::Waybar => a0 == "waybar",
        Piece::Dunst => a0 == "dunst",
        Piece::Hyprland => a0 == "Hyprland" || a0 == "hyprland",
        Piece::Osd => a0 == "swayosd-server",
        Piece::Idle => a0 == "hypridle",
    }
}

/// This user's live processes of each piece (zombies left out).
pub fn running(proc: &Path) -> Vec<Running> {
    let uid = rustix::process::getuid().as_raw();
    let me = std::process::id() as i32;
    let btime = boot_time(proc).unwrap_or(0);
    let pids: Vec<i32> = fs::read_dir(proc)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let pid: i32 = e.file_name().to_str()?.parse().ok()?;
            (pid != me && e.metadata().ok()?.uid() == uid).then_some(pid)
        })
        .filter(|pid| {
            fs::read_to_string(proc.join(pid.to_string()).join("stat")).is_ok_and(|s| {
                s.rsplit_once(") ")
                    .is_some_and(|(_, r)| !r.starts_with('Z'))
            })
        })
        .collect();
    let mut out = Vec::new();
    for piece in Piece::ALL {
        let mut mine: Vec<i32> = pids
            .iter()
            .copied()
            .filter(|&p| is_piece(piece, &argv(proc, p)))
            .collect();
        if mine.is_empty() {
            continue;
        }
        mine.sort_unstable();
        let started = mine
            .iter()
            .filter_map(|&p| proc_start(proc, p, btime))
            .min();
        out.push(Running {
            piece,
            pids: mine,
            started,
        });
    }
    out
}

// ------------------------------------------------------------------ the plan

/// What a piece needs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Need {
    /// Its code is newer than the process: stop it and start it again.
    Restart,
    /// Only its config is newer: tell it to read it again.
    Reload,
    /// Hyprland itself is newer: only logging out and in again runs it.
    Relogin,
    /// Only a restart of the computer runs it: a new kernel or graphics driver is
    /// installed, or the piece needs the GPU and is held back until then.
    Reboot,
    /// Installed but not running: a session service the login starts, added by an update
    /// (only the OSD: the others can be switched off on purpose, so they're never started).
    Start,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Plan {
    /// A piece's name, or "kernel".
    pub what: String,
    pub need: Need,
    pub why: String,
    pub pids: Vec<i32>,
}

/// What each running piece needs, given what's installed (and which packages this update
/// changed: a changed bromigos-desktop also reloads Hyprland's config, which it can't tell
/// from a process start). `pending`: a new kernel or graphics driver waits for a restart
/// of the computer; then the pieces that need the GPU are held back, not restarted.
pub fn plan(
    runs: &[Running],
    inst: &BTreeMap<String, Installed>,
    changed: &[String],
    pending: &crate::reboot::Pending,
) -> Vec<Plan> {
    let newer = |pkg: &str, started: Option<i64>| -> Option<&Installed> {
        let i = inst.get(pkg)?;
        (started.is_some_and(|s| i.installed > s)).then_some(i)
    };
    let mut out = Vec::new();
    for r in runs {
        let code = newer(r.piece.package(), r.started);
        let config = r.piece.config_package().and_then(|c| {
            newer(c, r.started)
                .map(|i| (c, i))
                .filter(|_| r.piece != Piece::Hyprland || changed.iter().any(|n| n == c))
        });
        let (need, why) = match (r.piece, code, config) {
            (Piece::Hyprland, Some(i), _) => (
                Need::Relogin,
                format!(
                    "hyprland {} is newer than the running compositor",
                    i.version
                ),
            ),
            (_, Some(i), _) => (
                Need::Restart,
                format!(
                    "{} {} is newer than the running process",
                    r.piece.package(),
                    i.version
                ),
            ),
            (_, None, Some((c, i))) => (
                Need::Reload,
                format!("its default config ({c} {}) is newer", i.version),
            ),
            _ => continue,
        };
        // started now, it would come up without the GPU (on the CPU's software renderer)
        let (need, why) = if r.piece.needs_gpu() && pending.any() {
            (
                Need::Reboot,
                format!(
                    "{why}, but {}: held back until the computer restarts",
                    pending.why()
                ),
            )
        } else {
            (need, why)
        };
        out.push(Plan {
            what: r.piece.name().to_owned(),
            need,
            why,
            pids: r.pids.clone(),
        });
    }
    if inst.contains_key(Piece::Osd.package()) && !runs.iter().any(|r| r.piece == Piece::Osd) {
        out.push(Plan {
            what: Piece::Osd.name().to_owned(),
            need: Need::Start,
            why: "installed, not running (the session starts it at login)".to_owned(),
            pids: vec![],
        });
    }
    if let Some(k) = &pending.kernel {
        out.push(Plan {
            what: "kernel".to_owned(),
            need: Need::Reboot,
            why: format!(
                "the running kernel's modules were replaced by a newer kernel ({} running, {} installed)",
                k.running,
                k.installed.join(", ")
            ),
            pids: vec![],
        });
    }
    if let Some(d) = &pending.driver {
        out.push(Plan {
            what: "driver".to_owned(),
            need: Need::Reboot,
            why: format!(
                "NVIDIA's driver {} is installed{}, but the kernel module running is {}",
                d.installed,
                d.package
                    .as_deref()
                    .map(|p| format!(" ({p})"))
                    .unwrap_or_default(),
                d.running
            ),
            pids: vec![],
        });
    }
    out
}

/// What waits for a restart of the computer here ([`crate::reboot::here`]).
pub fn pending(paths: &Paths) -> crate::reboot::Pending {
    crate::reboot::here(&installed(paths))
}

// ------------------------------------------------------------------ doing it

#[derive(Debug, Clone, Serialize)]
pub struct Done {
    pub what: String,
    /// `restarted`, `reloaded`, or what the user has to do.
    pub action: String,
    pub ok: bool,
    pub detail: Option<String>,
}

/// Runs `cmd` and returns what it printed. Its output goes to unlinked temporary files, not
/// pipes: a restart script (bromigos-live restart, bromigos-holo restart) starts a daemon
/// that inherits the command's stdout, and waiting for a pipe's end would then wait for
/// the daemon to exit. A file has no such end; only the command's own exit is waited for.
fn run_quiet(cmd: &mut Command) -> Result<String, String> {
    use std::io::{Read, Seek, SeekFrom};
    let capture = || -> std::io::Result<std::fs::File> {
        let dir = std::env::temp_dir();
        for n in 0..100u32 {
            let p = dir.join(format!("bromigos-update-{}-{n}", std::process::id()));
            if let Ok(f) = std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(&p)
            {
                let _ = std::fs::remove_file(&p); // unlinked: gone when the last holder closes it
                return Ok(f);
            }
        }
        Err(std::io::Error::other("no temporary file"))
    };
    let (mut out_f, mut err_f) = match (capture(), capture()) {
        (Ok(a), Ok(b)) => (a, b),
        (Err(e), _) | (_, Err(e)) => return Err(e.to_string()),
    };
    let status = cmd
        .stdin(Stdio::null())
        .stdout(Stdio::from(out_f.try_clone().map_err(|e| e.to_string())?))
        .stderr(Stdio::from(err_f.try_clone().map_err(|e| e.to_string())?))
        .status()
        .map_err(|e| e.to_string())?;
    let read = |f: &mut std::fs::File| {
        let mut s = String::new();
        let _ = f.seek(SeekFrom::Start(0));
        let _ = f.read_to_string(&mut s);
        s.trim().to_owned()
    };
    let (out, err) = (read(&mut out_f), read(&mut err_f));
    if status.success() {
        Ok(out)
    } else {
        Err(if err.is_empty() { out } else { err })
    }
}

pub(crate) fn session_env(paths: &Paths) -> Vec<(String, String)> {
    session::discover(paths)
        .session
        .map(|s| {
            s.env()
                .iter()
                .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
                .collect()
        })
        .unwrap_or_default()
}

/// SIGTERM to each, then waits up to 3 s for them to go.
pub(crate) fn stop(pids: &[i32]) -> Result<(), String> {
    use rustix::process::{Pid, Signal, kill_process};
    for &p in pids {
        if let Some(pid) = Pid::from_raw(p) {
            let _ = kill_process(pid, Signal::TERM);
        }
    }
    let deadline = Instant::now() + Duration::from_secs(3);
    while Instant::now() < deadline {
        if pids.iter().all(|p| !session::pid_alive(*p)) {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err(format!("still running after 3 s: {pids:?}"))
}

/// Starts `prog` in its own session (setsid), detached from this terminal, with the live
/// session's display. It gets no pipes of ours: a daemon that inherits a captured stdout
/// keeps it open for its whole life, and waiting for that pipe's end hung `bromigos update`
/// after it restarted the widgets. Each daemon keeps its own log; only setsid's exit is
/// waited for (`-f` forks and returns at once).
pub(crate) fn spawn(env: &[(String, String)], prog: &str) -> Result<String, String> {
    spawn_args(env, prog, &[])
}

/// `spawn` with arguments.
pub(crate) fn spawn_args(
    env: &[(String, String)],
    prog: &str,
    args: &[&str],
) -> Result<String, String> {
    match Command::new("setsid")
        .arg("-f")
        .arg(prog)
        .args(args)
        .envs(env.iter().map(|(k, v)| (k.as_str(), v.as_str())))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
    {
        Ok(s) if s.success() => Ok(String::new()),
        Ok(s) => Err(format!("setsid -f {prog}: {s}")),
        Err(e) => Err(format!("setsid -f {prog}: {e}")),
    }
}

/// Starts `cmd` through the compositor (`hl.dsp.exec_cmd`, via bromigos-dispatch), as
/// Hyprland's autostart does; `setsid -f` when there's no compositor to ask.
pub(crate) fn start_in_compositor(
    paths: &Paths,
    env: &[(String, String)],
    cmd: &str,
) -> Result<String, String> {
    let lua = format!("hl.dsp.exec_cmd({cmd:?})");
    let dispatch = paths.lib_bin.join("bromigos-dispatch");
    if !env.is_empty() && dispatch.exists() {
        let r = run_quiet(
            Command::new(&dispatch)
                .args([lua.as_str(), "exec", cmd])
                .envs(env.iter().map(|(k, v)| (k.as_str(), v.as_str()))),
        );
        if r.is_ok() {
            return r;
        }
    }
    spawn(env, cmd)
}

/// Carries out a plan. Restart and reload are done; relogin and reboot are reported.
pub fn execute(paths: &Paths, plans: &[Plan]) -> Vec<Done> {
    let env = session_env(paths);
    let envs = || env.iter().map(|(k, v)| (k.as_str(), v.as_str()));
    plans
        .iter()
        .map(|p| {
            let piece = Piece::parse(&p.what);
            let (action, r): (&str, Result<String, String>) = match (piece, p.need) {
                (Some(Piece::Live), Need::Restart) => (
                    "restarted",
                    run_quiet(Command::new(&paths.live_bin).arg("restart").envs(envs())),
                ),
                (Some(Piece::Vector), Need::Restart) => (
                    "restarted",
                    // the voice server too (bromigos-holo restart leaves it up); the app
                    // starts a fresh one on the new code the next time he speaks
                    stop(&p.pids).and_then(|_| {
                        run_quiet(Command::new(&paths.holo_bin).arg("restart").envs(envs()))
                    }),
                ),
                (Some(Piece::Widgets), Need::Restart) => (
                    "restarted",
                    stop(&p.pids).and_then(|_| spawn(&env, "bromigos-widgets")),
                ),
                (Some(Piece::Waybar), Need::Restart) => (
                    "restarted",
                    stop(&p.pids).and_then(|_| spawn(&env, "waybar")),
                ),
                (Some(Piece::Dunst), Need::Restart) => (
                    "restarted",
                    stop(&p.pids).and_then(|_| spawn(&env, "dunst")),
                ),
                // a restart, not SIGUSR2: waybar 0.15's mpris module crashes on an in-place reload
                // (a Glib::Dispatcher torn down by the reload gets a playerctl signal: SIGSEGV)
                (Some(Piece::Waybar), Need::Reload) => (
                    "restarted",
                    stop(&p.pids).and_then(|_| spawn(&env, "waybar")),
                ),
                (Some(Piece::Dunst), Need::Reload) => (
                    "reloaded",
                    run_quiet(Command::new("dunstctl").arg("reload").envs(envs())),
                ),
                (Some(Piece::Hyprland), Need::Reload) => (
                    "reloaded",
                    run_quiet(Command::new("hyprctl").arg("reload").envs(envs())),
                ),
                // hypridle reads its config only at start: the policy rendered again (a newer
                // template, or idle.toml changed), then a new one started inside the
                // compositor (Hyprland's exec), so logind sees it in the graphical session
                // and its lock signal reaches it (a setsid'd one from a terminal wouldn't)
                (Some(Piece::Idle), Need::Restart | Need::Reload) => (
                    "restarted",
                    crate::idle::render_file(paths)
                        .and_then(|_| stop(&p.pids))
                        .and_then(|_| start_in_compositor(paths, &env, "hypridle")),
                ),
                (Some(Piece::Osd), need) => {
                    // its style is read at start, so a reload is a restart too
                    let css = paths.user_state_dir().join("theme/current/swayosd.css");
                    let css = css.to_string_lossy().into_owned();
                    let go = || spawn_args(&env, "swayosd-server", &["--style", &css]);
                    match need {
                        Need::Start => ("started", go()),
                        _ => ("restarted", stop(&p.pids).and_then(|_| go())),
                    }
                }
                (_, Need::Relogin) => ("log out and back in to run it", Ok(String::new())),
                // a piece held back: it keeps running on the libraries it loaded
                (Some(_), Need::Reboot) => (
                    "held back: restart the computer to run it",
                    Ok(String::new()),
                ),
                (_, Need::Reboot) => ("reboot to run it", Ok(String::new())),
                _ => ("nothing to do", Ok(String::new())),
            };
            let ok = r.is_ok();
            Done {
                what: p.what.clone(),
                action: action.to_owned(),
                ok,
                detail: match r {
                    Ok(s) if s.is_empty() => None,
                    Ok(s) | Err(s) => Some(s.lines().last().unwrap_or_default().to_owned()),
                },
            }
        })
        .collect()
}

/// The restarts the running pieces need now (no package step): what `bromigos restart`
/// and an update's step 4 do. `only`: just these pieces, restarted whether stale or not.
pub fn restart_plan(paths: &Paths, only: &[Piece], changed: &[String]) -> Vec<Plan> {
    let runs = running(Path::new("/proc"));
    if only.is_empty() {
        let inst = installed(paths);
        let pending = crate::reboot::here(&inst);
        let mut p = plan(&runs, &inst, changed, &pending);
        // hypridle's config is a file of the user's and a rendered one, not a package's
        p.extend(crate::idle::stale(paths, &runs, &p));
        return p;
    }
    runs.iter()
        .filter(|r| only.contains(&r.piece) && r.piece != Piece::Hyprland)
        .map(|r| Plan {
            what: r.piece.name().to_owned(),
            need: Need::Restart,
            why: "asked for".to_owned(),
            pids: r.pids.clone(),
        })
        .chain(only.iter().filter(|p| **p == Piece::Hyprland).map(|_| {
            Plan {
                what: "hyprland".to_owned(),
                need: Need::Reload,
                why: "asked for (its config; the compositor itself restarts only with a new login)"
                    .to_owned(),
                pids: vec![],
            }
        }))
        .collect()
}

// ------------------------------------------------------------------ the package step

/// What the package step does, in order, and what decides it.
#[derive(Debug, Clone)]
pub struct PackageOpts {
    /// `pacman -Syuu`: after a move to an older channel.
    pub downgrade: bool,
    /// `--yes`: pacman takes its defaults (and the AUR step, planned with it, its own).
    pub yes: bool,
    /// snap-pac's hooks are installed: a transaction inside the update's own pair skips them.
    pub snap_pac: bool,
    /// How this machine snapshots (`snapshot: none (…)` when it doesn't).
    pub snapshots: String,
    /// The AUR step ([`crate::aur::plan`]).
    pub aur: crate::aur::Plan,
}

/// The package step's effects on the machine (the system's in `bromigos update`, a
/// recording stand-in in the tests), so the order is the step's, not its caller's.
pub trait PackageIo {
    /// pacman's local database (the packages installed now).
    fn installed(&mut self) -> BTreeMap<String, Installed>;
    /// The pre snapshot (None: no snapshots here).
    fn snapshot_before(&mut self) -> Result<Option<crate::snapshot::Marker>, String>;
    /// `sudo pacman -Syu`: its exit code.
    fn pacman(&mut self, downgrade: bool, skip_snap_pac: bool, yes: bool) -> std::io::Result<i32>;
    /// The AUR updates waiting (`paru -Qua`).
    fn aur_pending(&mut self, helper: crate::aur::Helper) -> Result<Vec<Available>, String>;
    /// The AUR step's command: its exit code.
    fn aur(&mut self, step: &crate::aur::Step) -> std::io::Result<i32>;
    /// The post snapshot: the pair (None: no snapshots here).
    fn snapshot_after(
        &mut self,
        marker: &crate::snapshot::Marker,
    ) -> Result<Option<crate::snapshot::Pair>, String>;
    /// Deletes a pair around nothing.
    fn discard(&mut self, pair: crate::snapshot::Pair) -> Result<(), String>;
    /// A line for whoever watches (`== packages: …`).
    fn say(&mut self, line: &str);
}

/// What the package step did.
#[derive(Debug, Clone, Default)]
pub struct Packages {
    /// The packages before it.
    pub before: BTreeMap<String, Installed>,
    /// pacman's exit code.
    pub pacman: Option<i32>,
    /// The AUR step (None: pacman failed, so it didn't run).
    pub aur: Option<crate::aur::Outcome>,
    /// The pair around the whole step, the AUR's transactions included.
    pub pair: Option<crate::snapshot::Pair>,
    /// What went wrong with the snapshots (the update goes on without them).
    pub warnings: Vec<String>,
}

impl Packages {
    /// The update goes on to the migrations, the theme and the restarts: the repositories'
    /// transaction didn't fail. The AUR step's failure doesn't stop it.
    pub fn goes_on(&self) -> bool {
        self.pacman.is_none_or(|c| c == 0)
    }
}

/// The package step, in order: the pre snapshot; the repositories' transaction (`sudo
/// pacman -Syu`); the AUR step (after the repositories, only when their transaction
/// succeeded; [`crate::aur`]), inside the same pair, snap-pac skipping its transactions too;
/// the post snapshot; the pair deleted again when nothing changed. Err: the pre snapshot
/// failed (nothing ran).
pub fn packages(io: &mut dyn PackageIo, o: &PackageOpts) -> Result<Packages, String> {
    let mut out = Packages {
        before: io.installed(),
        ..Default::default()
    };
    let marker = io.snapshot_before()?;
    let own = marker.as_ref().is_some_and(|m| m.own_pre.is_some());
    let skip_snap_pac = own && o.snap_pac;
    match &marker {
        Some(m) if m.own_pre.is_some() => io.say(&format!(
            "== snapshot: pre {} (snapper{})",
            m.own_pre.unwrap_or_default(),
            if o.snap_pac {
                "; snap-pac skips this update's transactions"
            } else {
                ""
            }
        )),
        Some(_) => io.say("== snapshot: the transaction's own"),
        None => io.say(&format!("== snapshot: none ({})", o.snapshots)),
    }
    io.say(&format!(
        "== packages: sudo pacman {}{}",
        if o.downgrade { "-Syuu" } else { "-Syu" },
        if o.yes { " --noconfirm" } else { "" }
    ));
    let code = match io.pacman(o.downgrade, skip_snap_pac, o.yes) {
        Ok(c) => c,
        Err(e) => {
            out.warnings.push(format!("sudo pacman: {e}"));
            1
        }
    };
    out.pacman = Some(code);
    if code == 0 {
        out.aur = Some(match &o.aur {
            // said once, in the update's summary
            crate::aur::Plan::Skip { why } => crate::aur::Outcome::skipped(why.clone()),
            crate::aur::Plan::Run { helper, unattended } => {
                let step = crate::aur::step(*helper, *unattended, skip_snap_pac);
                let due = io.aur_pending(*helper);
                if due.as_ref().is_ok_and(|d| d.is_empty()) {
                    io.say("== AUR: up to date");
                    crate::aur::Outcome::up_to_date(*helper)
                } else {
                    io.say(&format!(
                        "== AUR: {}{}",
                        step.line(),
                        if *unattended {
                            " (--yes: no review)"
                        } else {
                            ""
                        }
                    ));
                    let before = io.installed();
                    let code = match io.aur(&step) {
                        Ok(c) => c,
                        Err(e) => {
                            out.warnings.push(format!("{}: {e}", helper.bin()));
                            127
                        }
                    };
                    let after = io.installed();
                    crate::aur::outcome(*helper, &step, due, code, &before, &after)
                }
            }
        });
    }
    if let Some(m) = &marker {
        match io.snapshot_after(m) {
            Ok(p) => out.pair = p,
            Err(e) => out.warnings.push(format!("snapshot: {e}")),
        }
    }
    // a pair around nothing (no package changed, or pacman stopped) isn't an update: the
    // boot menu's snapshot list keeps updates only
    if let Some(p) = out.pair.filter(|_| own)
        && changes(&out.before, &io.installed()).is_empty()
    {
        match io.discard(p) {
            Ok(()) => out.pair = None,
            Err(e) => out.warnings.push(format!("snapshot: {e}")),
        }
    }
    Ok(out)
}

/// The machine's side of [`packages`].
pub struct SystemIo<'a> {
    pub paths: &'a Paths,
    pub env: &'a crate::snapshot::Env,
    /// Print the progress lines (not with `--json`).
    pub print: bool,
    /// Where the helper's own output goes: our stderr with `--json`, so the document on
    /// stdout stays whole.
    pub helper_to_stderr: bool,
}

impl PackageIo for SystemIo<'_> {
    fn installed(&mut self) -> BTreeMap<String, Installed> {
        installed(self.paths)
    }
    fn snapshot_before(&mut self) -> Result<Option<crate::snapshot::Marker>, String> {
        crate::snapshot::before(self.env, &mut crate::install::System)
    }
    fn pacman(&mut self, downgrade: bool, skip_snap_pac: bool, yes: bool) -> std::io::Result<i32> {
        pacman_upgrade(downgrade, skip_snap_pac, yes)
    }
    fn aur_pending(&mut self, helper: crate::aur::Helper) -> Result<Vec<Available>, String> {
        crate::aur::pending(&mut crate::install::System, helper)
    }
    fn aur(&mut self, step: &crate::aur::Step) -> std::io::Result<i32> {
        let mut c = Command::new(&step.argv[0]);
        c.args(&step.argv[1..])
            .envs(step.env.iter().map(|(k, v)| (k.as_str(), v.as_str())));
        if self.helper_to_stderr {
            c.stdout(std::io::stderr());
        }
        Ok(c.status()?.code().unwrap_or(1))
    }
    fn snapshot_after(
        &mut self,
        marker: &crate::snapshot::Marker,
    ) -> Result<Option<crate::snapshot::Pair>, String> {
        crate::snapshot::after(self.env, &mut crate::install::System, marker)
    }
    fn discard(&mut self, pair: crate::snapshot::Pair) -> Result<(), String> {
        crate::snapshot::discard(&mut crate::install::System, pair)
    }
    fn say(&mut self, line: &str) {
        if self.print {
            println!("{line}");
        }
    }
}

// ------------------------------------------------------------------ the whole update

/// What `bromigos update` did (its `--json` document; schema in core/README.md).
#[derive(Debug, Clone, Serialize)]
pub struct Report {
    /// pacman's exit code (None: the package step was skipped).
    pub pacman: Option<i32>,
    /// The AUR step (None: the package step was skipped, or pacman failed before it).
    pub aur: Option<crate::aur::Outcome>,
    pub packages: Vec<Changed>,
    pub migrations: Vec<crate::migrate::Ran>,
    pub migrations_ok: bool,
    /// The theme rendered again (None: no theme set, or it was skipped after a failure).
    pub theme: Option<String>,
    pub theme_error: Option<String>,
    /// The switcher's previews started in the background (None: no renderer here).
    pub previews: Option<String>,
    /// The boot menu brought to the theme (None: the update stopped before it).
    pub boot: Option<crate::boot::Outcome>,
    pub restarts: Vec<Done>,
    /// The pre/post snapshot pair around the package step (None: no snapshots here, or
    /// the package step was skipped).
    pub snapshot: Option<crate::snapshot::Pair>,
    /// The channel the packages came from.
    pub channel: Option<String>,
    /// A new kernel or graphics driver waits for the computer to restart (None: nothing
    /// does): what, what was held back until then, and the update's last line.
    pub reboot: Option<RebootNotice>,
}

/// What an update says when the computer must restart ([`crate::reboot`]).
#[derive(Debug, Clone, Serialize)]
pub struct RebootNotice {
    pub driver: Option<crate::reboot::Driver>,
    pub kernel: Option<crate::reboot::Kernel>,
    /// What wasn't restarted or started because it needs the GPU: `live`, `vector`,
    /// `previews` (the theme switcher's).
    pub held: Vec<String>,
    /// The update's last line, and the desktop notification's text.
    pub message: String,
    /// The desktop notification went out.
    pub notified: bool,
}

/// The one desktop notification an update sends when the computer must restart.
fn notify_restart(paths: &Paths, message: &str) -> bool {
    Command::new("notify-send")
        .args([
            "-a",
            "bromigos",
            "-u",
            "normal",
            "-i",
            "system-reboot",
            "Restart to finish the update",
            message,
        ])
        .envs(session_env(paths))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|s| s.success())
}

/// What a pending restart of the computer held back, and the notice for it.
pub fn reboot_notice(
    pending: &crate::reboot::Pending,
    plans: &[Plan],
    previews_held: bool,
    background_running: bool,
) -> Option<RebootNotice> {
    let message = pending.message(background_running)?;
    let mut held: Vec<String> = plans
        .iter()
        .filter(|p| p.need == Need::Reboot && Piece::parse(&p.what).is_some())
        .map(|p| p.what.clone())
        .collect();
    if previews_held {
        held.push("previews".to_owned());
    }
    Some(RebootNotice {
        driver: pending.driver.clone(),
        kernel: pending.kernel.clone(),
        held,
        message,
        notified: false,
    })
}

/// Steps 2-4 of an update, after the package step (whose before/after package lists are
/// given, the AUR step's outcome, and the snapshot pair around both). A package step that
/// ran is recorded in `updates.jsonl` with its pair, for `bromigos update --rollback`; the
/// AUR's changes are among its packages.
pub fn finish(
    paths: &Paths,
    pacman: Option<i32>,
    aur: Option<crate::aur::Outcome>,
    before: &BTreeMap<String, Installed>,
    snapshot: Option<crate::snapshot::Pair>,
) -> Report {
    let after = installed(paths);
    let packages = changes(before, &after);
    let channel = crate::channel::current(paths)
        .channel
        .map(|c| c.to_string());
    if pacman == Some(0) {
        let _ = crate::snapshot::record(
            paths,
            &crate::snapshot::Record {
                at: chrono::Local::now().to_rfc3339(),
                channel: channel.clone(),
                snapshot,
                packages: packages
                    .iter()
                    .map(|c| {
                        format!(
                            "{} {} -> {}",
                            c.name,
                            c.from.as_deref().unwrap_or("(new)"),
                            c.to.as_deref().unwrap_or("(removed)")
                        )
                    })
                    .collect(),
                rolled_back: false,
                root: None,
            },
        );
    }
    let env = session_env(paths);
    let (migrations, migrations_ok) = crate::migrate::run_pending(paths, &env);
    let mut report = Report {
        pacman,
        aur,
        packages,
        migrations,
        migrations_ok,
        theme: None,
        theme_error: None,
        previews: None,
        boot: None,
        restarts: vec![],
        snapshot,
        channel,
        reboot: None,
    };
    if !migrations_ok {
        return report;
    }
    let cur = theme::current(paths);
    if cur.set {
        match render_theme(paths, &cur.name) {
            Ok(()) => report.theme = Some(cur.name),
            Err(e) => report.theme_error = Some(e),
        }
    }
    // a new kernel or graphics driver waits for a restart of the computer: what needs the
    // GPU isn't started again until then (it would draw on the CPU instead)
    let pending = pending(paths);
    // a theme, a template or the bar may have changed: the switcher's previews that are
    // out of date now are drawn again, in the background (after the restart, when the
    // driver changed: the renderer would find no GPU)
    let previews_held = pending.any() && crate::previews::renderer().is_some();
    if !pending.any() {
        report.previews = crate::previews::render_in_background(&[], None);
    }
    // the boot menu on the theme in force, where it's on (sudo asks here, on the terminal,
    // like the update's other root steps; usually it still remembers pacman's)
    report.boot = Some(crate::boot::sync(
        paths,
        &mut crate::install::System,
        &crate::snapshot::RootFs,
        crate::boot::Enable::Keep,
        true,
        false,
    ));
    let changed: Vec<String> = report.packages.iter().map(|c| c.name.clone()).collect();
    let plans = restart_plan(paths, &[], &changed);
    report.restarts = execute(paths, &plans);
    let background = running(Path::new("/proc"))
        .iter()
        .any(|r| r.piece == Piece::Live);
    report.reboot = reboot_notice(&pending, &plans, previews_held, background).map(|mut n| {
        n.notified = notify_restart(paths, &n.message);
        n
    });
    report
}

/// The theme in force rendered again by the bromigos that is installed now. When this
/// update replaced the running program, this process still has the old code, and the
/// new templates may expect what only the new renderer gives them (bromigOS 0.1.1's
/// renderer had no `a11y` for the templates of 0.1.2). The installed `bromigos theme set
/// --no-reload` renders it then; the restarts after this step do the reloading.
fn render_theme(paths: &Paths, name: &str) -> Result<(), String> {
    let Some(exe) = fs::read_link("/proc/self/exe")
        .ok()
        .and_then(|l| replaced_program(&l))
    else {
        return theme::set(paths, name)
            .map(|_| ())
            .map_err(|e| e.to_string());
    };
    let out = Command::new(&exe)
        .args(["theme", "set", name, "--no-reload"])
        .stdin(Stdio::null())
        .output()
        .map_err(|e| format!("{}: {e}", exe.display()))?;
    if out.status.success() {
        return Ok(());
    }
    let err = String::from_utf8_lossy(&out.stderr);
    let last = err
        .lines()
        .rev()
        .find(|l| !l.trim().is_empty())
        .unwrap_or("");
    Err(last
        .strip_prefix("bromigos theme: ")
        .unwrap_or(last)
        .to_owned())
}

/// The running program's path when its file was replaced (Linux links `/proc/self/exe`
/// to "PATH (deleted)" once pacman puts a new file at PATH) and a program is there now.
fn replaced_program(link: &Path) -> Option<std::path::PathBuf> {
    let path = Path::new(link.to_str()?.strip_suffix(" (deleted)")?);
    path.is_file().then(|| path.to_path_buf())
}

/// What an update would do now (`bromigos update --check`).
#[derive(Debug, Clone, Serialize)]
pub struct Check {
    /// None: can't tell (install pacman-contrib for checkupdates).
    pub packages: Option<Vec<Available>>,
    pub migrations: Vec<String>,
    pub restarts: Vec<Plan>,
    /// The channel followed (None: no [bromigos] repository, or an unknown Server line).
    pub channel: Option<crate::channel::Channel>,
    /// How updates are snapshotted here, and whether the boot menu can boot them.
    pub snapshots: crate::snapshot::Env,
    /// Recorded updates with a snapshot pair that could be rolled back, newest first.
    pub rollbacks: Vec<crate::snapshot::Record>,
    /// The boot menu: GRUB's theme, on or off, current or not (crate::boot).
    pub boot: String,
    /// The AUR: the helper, whether the update uses it, the AUR updates waiting.
    pub aur: AurCheck,
}

/// The AUR in `bromigos update --check`.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct AurCheck {
    /// The setting (`~/.config/bromigos/aur.toml`).
    pub enabled: bool,
    /// The helper here.
    pub found: crate::aur::Found,
    /// The AUR updates waiting (None: not asked, or the helper couldn't tell: `note`).
    pub packages: Option<Vec<Available>>,
    /// Why they weren't asked for, or why the helper couldn't tell.
    pub note: Option<String>,
}

/// The AUR's part of `--check`: `paru -Qua` when the update would run its AUR step.
pub fn aur_check(
    enabled: bool,
    no_aur: bool,
    found: crate::aur::Found,
    pending: impl FnOnce(crate::aur::Helper) -> Result<Vec<Available>, String>,
) -> AurCheck {
    let note = if no_aur {
        Some("left alone (--no-aur)".to_string())
    } else if !enabled {
        Some("left alone: the AUR is off here (bromigos aur on)".to_string())
    } else if found.helper.is_none() {
        Some("no AUR helper here (bromigos aur on installs bromigOS's paru)".to_string())
    } else {
        None
    };
    let (packages, note) = match (note, found.helper) {
        (None, Some(h)) => match pending(h) {
            Ok(p) => (Some(p), None),
            Err(e) => (None, Some(format!("can't tell ({e})"))),
        },
        (n, _) => (None, n),
    };
    AurCheck {
        enabled,
        found,
        packages,
        note,
    }
}

/// `--check`'s lines for the AUR.
pub fn aur_check_lines(c: &AurCheck) -> Vec<String> {
    let head = match c.found.helper {
        Some(_) => format!("AUR ({}):", c.found.describe()),
        None => "AUR:".to_string(),
    };
    match (&c.packages, &c.note) {
        (Some(p), _) if p.is_empty() => vec![format!("{head} up to date")],
        (Some(p), _) => {
            let mut v = vec![format!(
                "{head} {} waiting (bromigos update builds them after the repositories', \
                 inside its snapshot pair)",
                p.len()
            )];
            v.extend(
                p.iter()
                    .map(|a| format!("  {:<28} {} -> {}", a.name, a.from, a.to)),
            );
            v
        }
        (None, Some(n)) => vec![format!("{head} {n}")],
        (None, None) => vec![format!("{head} can't tell")],
    }
}

pub fn check(paths: &Paths, no_aur: bool) -> Check {
    let mut sys = crate::install::System;
    let snapshots = crate::snapshot::detect(&mut sys, &crate::snapshot::RootFs);
    let mut rollbacks: Vec<_> = crate::snapshot::records(paths)
        .into_iter()
        .filter(|r| !r.rolled_back && r.snapshot.is_some())
        .collect();
    rollbacks.reverse();
    rollbacks.truncate(5);
    Check {
        packages: available(),
        migrations: crate::migrate::pending(paths)
            .into_iter()
            .map(|m| m.id)
            .collect(),
        restarts: restart_plan(paths, &[], &[]),
        channel: crate::channel::current(paths).channel,
        snapshots,
        rollbacks,
        boot: crate::boot::status(paths, &mut sys, &crate::snapshot::RootFs).summary(),
        aur: aur_check(
            crate::aur::enabled(paths),
            no_aur,
            crate::aur::found(&mut sys),
            |h| crate::aur::pending(&mut crate::install::System, h),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_replaced_program_is_found_by_its_deleted_link() {
        let dir = tempfile::tempdir().unwrap();
        let exe = dir.path().join("bromigos");
        fs::write(&exe, "new").unwrap();
        let link = format!("{} (deleted)", exe.display());
        assert_eq!(replaced_program(Path::new(&link)), Some(exe.clone()));
        // still the running file: not replaced
        assert_eq!(replaced_program(&exe), None);
        // replaced by nothing (removed): nothing to run
        let gone = format!("{} (deleted)", dir.path().join("gone").display());
        assert_eq!(replaced_program(Path::new(&gone)), None);
    }

    fn inst(v: &str, t: i64) -> Installed {
        Installed {
            version: v.to_owned(),
            installed: t,
        }
    }

    #[test]
    fn desc_file() {
        let d = "%NAME%\nbromigos-live\n\n%VERSION%\n0.1.0.r5.gcb25658-1\n\n%BASE%\nbromigos-live\n\n\
                 %INSTALLDATE%\n1791489000\n\n%SIZE%\n123\n";
        assert_eq!(
            parse_desc(d),
            Some((
                "bromigos-live".into(),
                inst("0.1.0.r5.gcb25658-1", 1791489000)
            ))
        );
        assert_eq!(parse_desc("%NAME%\nx\n"), None, "no version");
    }

    #[test]
    fn changed_packages() {
        let b = BTreeMap::from([("a".into(), inst("1", 1)), ("b".into(), inst("1", 1))]);
        let a = BTreeMap::from([("a".into(), inst("2", 5)), ("c".into(), inst("1", 5))]);
        let c = changes(&b, &a);
        assert_eq!(c.len(), 3);
        assert_eq!(
            c[0],
            Changed {
                name: "a".into(),
                from: Some("1".into()),
                to: Some("2".into())
            }
        );
        assert_eq!(c[1].to, None);
        assert_eq!(c[2].from, None);
    }

    #[test]
    fn checkupdates_lines() {
        let u = parse_checkupdates("waybar 0.15.0-3 -> 0.15.1-1\nnoise\n");
        assert_eq!(
            u,
            vec![Available {
                name: "waybar".into(),
                from: "0.15.0-3".into(),
                to: "0.15.1-1".into()
            }]
        );
    }

    fn v(s: &[&str]) -> Vec<String> {
        s.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn piece_command_lines() {
        assert!(is_piece(
            Piece::Live,
            &v(&["/usr/bin/python3", "-m", "live.app"])
        ));
        assert!(!is_piece(
            Piece::Live,
            &v(&["zsh", "-c", "python3 -m live.app"])
        ));
        assert!(is_piece(
            Piece::Widgets,
            &v(&["python3", "/usr/bin/bromigos-widgets"])
        ));
        assert!(is_piece(
            Piece::Widgets,
            &v(&[
                "/usr/bin/python3",
                "/home/u/.config/bromigos/widgets/bromigos-widgets",
                "notes"
            ])
        ));
        assert!(!is_piece(Piece::Widgets, &v(&["vim", "bromigos-widgets"])));
        assert!(is_piece(Piece::Waybar, &v(&["waybar"])));
        assert!(is_piece(Piece::Vector, &v(&["python", "-m", "holo.app"])));
        assert!(is_piece(
            Piece::Vector,
            &v(&["/venv-tts/bin/python", "-m", "holo.voice_server"])
        ));
        assert!(is_piece(Piece::Hyprland, &v(&["/usr/bin/Hyprland"])));
    }

    #[test]
    fn stale_code_restarts_new_config_reloads() {
        let i = BTreeMap::from([
            ("bromigos-live".into(), inst("2", 200)),
            ("bromigos-widgets".into(), inst("1", 50)),
            ("waybar".into(), inst("1", 50)),
            ("bromigos-desktop".into(), inst("3", 200)),
            ("dunst".into(), inst("2", 300)),
            ("hyprland".into(), inst("1", 50)),
        ]);
        let r = |piece, started| Running {
            piece,
            pids: vec![1],
            started: Some(started),
        };
        let runs = vec![
            r(Piece::Live, 100),     // older than its package: restart
            r(Piece::Widgets, 100),  // newer than its package: fine
            r(Piece::Waybar, 100),   // binary fine, config newer: reload
            r(Piece::Dunst, 100),    // binary newer: restart (beats the reload)
            r(Piece::Hyprland, 100), // desktop newer, but not changed by this update: nothing
        ];
        let none = crate::reboot::Pending::default();
        let new_kernel = crate::reboot::Pending {
            driver: None,
            kernel: Some(crate::reboot::Kernel {
                running: "7.2.9-arch1-1".into(),
                installed: vec!["7.2.10-arch1-1".into()],
            }),
        };
        let p = plan(&runs, &i, &[], &none);
        let got: Vec<_> = p.iter().map(|p| (p.what.as_str(), p.need)).collect();
        assert_eq!(
            got,
            vec![
                ("live", Need::Restart),
                ("waybar", Need::Reload),
                ("dunst", Need::Restart)
            ]
        );
        // the update changed bromigos-desktop: Hyprland reloads its config too
        let p = plan(&runs, &i, &["bromigos-desktop".into()], &new_kernel);
        assert!(
            p.iter()
                .any(|p| p.what == "hyprland" && p.need == Need::Reload)
        );
        assert!(
            p.iter()
                .any(|p| p.what == "kernel" && p.need == Need::Reboot)
        );
        // the OSD: installed and not running is started; running, nothing to do
        let mut io = i.clone();
        io.insert("swayosd".into(), inst("0.3", 50));
        let p = plan(&runs, &io, &[], &none);
        assert!(p.iter().any(|p| p.what == "osd" && p.need == Need::Start));
        let mut ro = runs.clone();
        ro.push(r(Piece::Osd, 400)); // started after its package and its config
        assert!(!plan(&ro, &io, &[], &none).iter().any(|p| p.what == "osd"));
        assert!(is_piece(
            Piece::Osd,
            &["/usr/bin/swayosd-server".into(), "--style".into()]
        ));
        // a newer compositor can't be restarted from inside it
        let i2 = BTreeMap::from([("hyprland".into(), inst("2", 500))]);
        let p = plan(&[r(Piece::Hyprland, 100)], &i2, &[], &none);
        assert_eq!(p[0].need, Need::Relogin);
    }

    /// The update of 2026-10-09: nvidia-utils 615.71.09 -> 615.78.08 with the old module
    /// still loaded. Restarted then, the live layer drew on the CPU (llvmpipe, ~1,180%).
    #[test]
    fn a_new_driver_holds_back_what_needs_the_gpu() {
        use crate::reboot::{Driver, Pending};
        let i = BTreeMap::from([
            ("bromigos-live".into(), inst("2", 200)),
            ("bromigos-vector".into(), inst("2", 200)),
            ("bromigos-widgets".into(), inst("2", 200)),
            ("waybar".into(), inst("2", 200)),
            ("bromigos-desktop".into(), inst("2", 200)),
            ("dunst".into(), inst("1", 50)),
            ("nvidia-utils".into(), inst("615.78.08-1", 200)),
        ]);
        let r = |piece| Running {
            piece,
            pids: vec![1],
            started: Some(100),
        };
        let runs = vec![
            r(Piece::Live),
            r(Piece::Vector),
            r(Piece::Widgets),
            r(Piece::Waybar),
            r(Piece::Dunst),
        ];
        let driver = Pending {
            driver: Some(Driver {
                running: "615.71.09".into(),
                installed: "615.78.08".into(),
                package: Some("nvidia-utils 615.78.08-1".into()),
            }),
            kernel: None,
        };
        let got = |p: &[Plan]| -> Vec<(String, Need)> {
            p.iter().map(|p| (p.what.clone(), p.need)).collect()
        };
        // the driver changed: the GPU's pieces wait for the restart, the others restart now
        let p = plan(&runs, &i, &["nvidia-utils".into()], &driver);
        assert_eq!(
            got(&p),
            vec![
                ("live".to_string(), Need::Reboot),
                ("vector".to_string(), Need::Reboot),
                ("widgets".to_string(), Need::Restart),
                ("waybar".to_string(), Need::Restart),
                ("dunst".to_string(), Need::Reload),
                ("driver".to_string(), Need::Reboot),
            ]
        );
        assert!(
            p[0].why.contains("615.78.08 installed, 615.71.09 running"),
            "{}",
            p[0].why
        );
        assert!(p[0].why.ends_with("held back until the computer restarts"));
        assert_eq!(
            p[5].why,
            "NVIDIA's driver 615.78.08 is installed (nvidia-utils 615.78.08-1), \
             but the kernel module running is 615.71.09"
        );
        // the same update after the restart (or with a matching driver): everything restarts
        let p = plan(&runs, &i, &["nvidia-utils".into()], &Pending::default());
        assert_eq!(
            got(&p),
            vec![
                ("live".to_string(), Need::Restart),
                ("vector".to_string(), Need::Restart),
                ("widgets".to_string(), Need::Restart),
                ("waybar".to_string(), Need::Restart),
                ("dunst".to_string(), Need::Reload),
            ]
        );
        // what the update says, and what it held
        let p = plan(&runs, &i, &[], &driver);
        let n = reboot_notice(&driver, &p, true, false).unwrap();
        assert_eq!(n.held, vec!["live", "vector", "previews"]);
        assert_eq!(
            n.message,
            "The graphics driver was updated: restart the computer to use it. \
             Until then, the animated background stays off."
        );
        assert!(reboot_notice(&Pending::default(), &p, false, true).is_none());
        // a held piece is reported, not run, and isn't a failure
        let d = execute(&Paths::from_env(), &p[..1]);
        assert_eq!(d[0].action, "held back: restart the computer to run it");
        assert!(d[0].ok);
    }

    // ------------------------------------------------------------------ the package step

    use crate::aur::{Helper, Plan as AurPlan};
    use crate::snapshot::{Marker, Pair};

    /// Records what the package step does, in order, and changes its package list as the
    /// transactions would.
    struct Fake {
        log: Vec<String>,
        said: Vec<String>,
        pkgs: BTreeMap<String, Installed>,
        snapshots: bool,
        pacman_code: i32,
        pacman_sets: Vec<(&'static str, &'static str)>,
        due: Result<Vec<Available>, String>,
        aur_code: i32,
        aur_sets: Vec<(&'static str, &'static str)>,
    }

    impl Fake {
        fn new() -> Fake {
            Fake {
                log: vec![],
                said: vec![],
                pkgs: BTreeMap::from([
                    ("waybar".to_string(), inst("0.15.0-1", 1)),
                    ("cowsay".to_string(), inst("3.7.0-1", 1)),
                    ("broken".to_string(), inst("1-1", 1)),
                ]),
                snapshots: true,
                pacman_code: 0,
                pacman_sets: vec![("waybar", "0.15.1-1")],
                due: Ok(vec![Available {
                    name: "cowsay".into(),
                    from: "3.7.0-1".into(),
                    to: "3.8.4-1".into(),
                }]),
                aur_code: 0,
                aur_sets: vec![("cowsay", "3.8.4-1")],
            }
        }
        fn set(&mut self, sets: &[(&str, &str)]) {
            for (n, v) in sets {
                self.pkgs.insert(n.to_string(), inst(v, 2));
            }
        }
    }

    impl PackageIo for Fake {
        fn installed(&mut self) -> BTreeMap<String, Installed> {
            self.pkgs.clone()
        }
        fn snapshot_before(&mut self) -> Result<Option<Marker>, String> {
            if !self.snapshots {
                return Ok(None);
            }
            self.log.push("snapper pre".into());
            Ok(Some(Marker {
                last: 10,
                own_pre: Some(11),
            }))
        }
        fn pacman(&mut self, downgrade: bool, skip: bool, yes: bool) -> std::io::Result<i32> {
            self.log.push(format!(
                "sudo {}",
                pacman_command(downgrade, skip, yes, &[]).join(" ")
            ));
            let sets = self.pacman_sets.clone();
            self.set(&sets);
            Ok(self.pacman_code)
        }
        fn aur_pending(&mut self, helper: Helper) -> Result<Vec<Available>, String> {
            self.log.push(format!("{} -Qua", helper.bin()));
            self.due.clone()
        }
        fn aur(&mut self, step: &crate::aur::Step) -> std::io::Result<i32> {
            self.log.push(step.line());
            let sets = self.aur_sets.clone();
            self.set(&sets);
            Ok(self.aur_code)
        }
        fn snapshot_after(&mut self, m: &Marker) -> Result<Option<Pair>, String> {
            self.log.push("snapper post".into());
            Ok(m.own_pre.map(|pre| Pair { pre, post: pre + 1 }))
        }
        fn discard(&mut self, p: Pair) -> Result<(), String> {
            self.log
                .push(format!("snapper delete {} {}", p.pre, p.post));
            Ok(())
        }
        fn say(&mut self, line: &str) {
            self.said.push(line.into());
        }
    }

    fn opts(aur: AurPlan) -> PackageOpts {
        PackageOpts {
            downgrade: false,
            yes: false,
            snap_pac: true,
            snapshots: "test".into(),
            aur,
        }
    }

    fn paru(unattended: bool) -> AurPlan {
        AurPlan::Run {
            helper: Helper::Paru,
            unattended,
        }
    }

    #[test]
    fn the_aur_step_runs_after_the_repositories_inside_the_pair() {
        let mut f = Fake::new();
        let r = packages(&mut f, &opts(paru(false))).unwrap();
        assert_eq!(
            f.log,
            vec![
                "snapper pre",
                "sudo SNAP_PAC_SKIP=y pacman -Syu",
                "paru -Qua",
                "SNAP_PAC_SKIP=y paru -Sua --sudoflags --preserve-env=SNAP_PAC_SKIP",
                "snapper post",
            ]
        );
        assert_eq!(r.pair, Some(Pair { pre: 11, post: 12 }));
        assert!(r.goes_on());
        let a = r.aur.unwrap();
        assert_eq!(a.status, "done");
        assert_eq!(
            a.changed.len(),
            1,
            "the AUR step's own changes: {:?}",
            a.changed
        );
        // the update's record has both
        assert_eq!(changes(&r.before, &f.pkgs).len(), 2);
        assert!(
            f.said
                .iter()
                .any(|l| l.starts_with("== AUR: SNAP_PAC_SKIP=y paru -Sua"))
        );
        // --yes: pacman and paru take their defaults, paru without its review
        let mut f = Fake::new();
        let mut o = opts(paru(true));
        o.yes = true;
        packages(&mut f, &o).unwrap();
        assert_eq!(f.log[1], "sudo SNAP_PAC_SKIP=y pacman -Syu --noconfirm");
        assert!(
            f.log[3].ends_with("--noconfirm --skipreview"),
            "{}",
            f.log[3]
        );
    }

    #[test]
    fn no_aur_leaves_it_out_and_a_pair_around_nothing_goes() {
        let mut f = Fake::new();
        f.pacman_sets.clear();
        let r = packages(
            &mut f,
            &opts(AurPlan::Skip {
                why: "--no-aur".into(),
            }),
        )
        .unwrap();
        assert_eq!(
            f.log,
            vec![
                "snapper pre",
                "sudo SNAP_PAC_SKIP=y pacman -Syu",
                "snapper post",
                "snapper delete 11 12",
            ]
        );
        assert_eq!(r.pair, None);
        let a = r.aur.unwrap();
        assert_eq!((a.status, a.detail.as_str()), ("skipped", "--no-aur"));
        assert!(
            !f.said.iter().any(|l| l.starts_with("== AUR")),
            "the summary says it"
        );
    }

    #[test]
    fn an_aur_update_alone_keeps_the_pair() {
        let mut f = Fake::new();
        f.pacman_sets.clear();
        let r = packages(&mut f, &opts(paru(false))).unwrap();
        assert_eq!(r.pair, Some(Pair { pre: 11, post: 12 }));
        assert!(!f.log.iter().any(|l| l.starts_with("snapper delete")));
    }

    #[test]
    fn nothing_due_runs_no_helper() {
        let mut f = Fake::new();
        f.due = Ok(vec![]);
        let r = packages(&mut f, &opts(paru(false))).unwrap();
        assert!(!f.log.iter().any(|l| l.contains("-Sua")), "{:?}", f.log);
        assert_eq!(r.aur.unwrap().status, "none");
    }

    #[test]
    fn a_failing_aur_step_is_reported_and_the_update_goes_on() {
        let mut f = Fake::new();
        f.due = Ok(vec![
            Available {
                name: "cowsay".into(),
                from: "3.7.0-1".into(),
                to: "3.8.4-1".into(),
            },
            Available {
                name: "broken".into(),
                from: "1-1".into(),
                to: "2-1".into(),
            },
        ]);
        f.aur_code = 1; // paru: "packages failed to build: broken-2-1"
        let r = packages(&mut f, &opts(paru(false))).unwrap();
        assert!(
            r.goes_on(),
            "migrations, the theme and the restarts still run"
        );
        assert_eq!(r.pacman, Some(0));
        assert_eq!(r.pair, Some(Pair { pre: 11, post: 12 }));
        let a = r.aur.unwrap();
        assert!(a.failed());
        assert_eq!(a.not_updated, vec!["broken"]);
        assert!(a.retry.unwrap().contains("paru -S broken"));
        assert_eq!(a.changed.len(), 1, "cowsay was built: {:?}", a.changed);
        // the repositories' transaction failing stops it, and the AUR step never runs
        let mut f = Fake::new();
        f.pacman_code = 1;
        let r = packages(&mut f, &opts(paru(false))).unwrap();
        assert!(!r.goes_on());
        assert!(r.aur.is_none());
        assert!(!f.log.iter().any(|l| l.contains("paru")), "{:?}", f.log);
        assert_eq!(f.log.last().unwrap(), "snapper post");
    }

    #[test]
    fn without_snapshots_snap_pac_is_left_to_its_job() {
        let mut f = Fake::new();
        f.snapshots = false;
        let r = packages(&mut f, &opts(paru(false))).unwrap();
        assert_eq!(f.log, vec!["sudo pacman -Syu", "paru -Qua", "paru -Sua"]);
        assert_eq!(r.pair, None);
        assert!(f.said[0].starts_with("== snapshot: none"));
    }

    fn found(helper: Option<Helper>) -> crate::aur::Found {
        crate::aur::Found {
            helper,
            version: helper.map(|_| "2.1.0".to_string()),
            bromigos_build: false,
            paru_provided: helper.is_some(),
            also: None,
        }
    }

    #[test]
    fn check_lists_the_aur_updates_waiting() {
        let c = aur_check(true, false, found(Some(Helper::Paru)), |h| {
            assert_eq!(h, Helper::Paru);
            crate::aur::parse_pending(h, 0, "cowsay 3.7.0-1 -> 3.8.4-1\n")
        });
        assert_eq!(
            aur_check_lines(&c),
            vec![
                "AUR (paru 2.1.0 (yours)): 1 waiting (bromigos update builds them after the \
                 repositories', inside its snapshot pair)"
                    .to_string(),
                format!("  {:<28} 3.7.0-1 -> 3.8.4-1", "cowsay"),
            ]
        );
        let c = aur_check(true, false, found(Some(Helper::Paru)), |_| Ok(vec![]));
        assert_eq!(
            aur_check_lines(&c),
            vec!["AUR (paru 2.1.0 (yours)): up to date"]
        );
        let c = aur_check(true, false, found(Some(Helper::Paru)), |_| {
            Err("paru -Qua: error: Connection refused".into())
        });
        assert!(aur_check_lines(&c)[0].contains("can't tell (paru -Qua: error"));
        // not asked: --no-aur, the setting off, no helper
        let never = |_| -> Result<Vec<Available>, String> { panic!("asked") };
        let c = aur_check(true, true, found(Some(Helper::Paru)), never);
        assert_eq!(
            aur_check_lines(&c),
            vec!["AUR (paru 2.1.0 (yours)): left alone (--no-aur)"]
        );
        let c = aur_check(false, false, found(Some(Helper::Paru)), never);
        assert!(aur_check_lines(&c)[0].contains("the AUR is off here"));
        let c = aur_check(true, false, found(None), never);
        assert_eq!(
            aur_check_lines(&c),
            vec!["AUR: no AUR helper here (bromigos aur on installs bromigOS's paru)"]
        );
    }

    #[test]
    fn this_machine_is_readable() {
        // whatever runs here: the scan must not fail or include this test process
        let me = std::process::id() as i32;
        for r in running(Path::new("/proc")) {
            assert!(!r.pids.contains(&me));
        }
    }

    #[test]
    fn a_daemon_holding_our_output_does_not_hang_run_quiet() {
        // what hung `bromigos update`: the command exits, but a process it started keeps
        // its stdout open; run_quiet must return when the command does, with its output
        let t = Instant::now();
        let out =
            run_quiet(Command::new("sh").args(["-c", "echo started; sleep 30 & echo $! >&2"]))
                .expect("sh ran");
        assert!(
            t.elapsed() < Duration::from_secs(5),
            "waited for the background process"
        );
        assert_eq!(out, "started");
    }

    #[test]
    fn spawn_returns_without_waiting_for_the_daemon() {
        let t = Instant::now();
        spawn(&[], "true").expect("setsid -f true");
        assert!(t.elapsed() < Duration::from_secs(5));
    }
}
