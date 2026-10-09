//! Hyprland's auto-reload held off while a package transaction replaces its config
//! (`bromigos session hold` and `release`; bromigos-core's pacman hooks run them).
//!
//! Hyprland reloads by itself when a file its config loaded changes. pacman replaces
//! bromigos-desktop's defaults (`/usr/share/bromigos/default/hypr/`) one file at a time, so
//! a running Hyprland with auto-reload on can reload a half-written set: a new `binds.lua`
//! with the old `keys.lua`, a Lua error, no binds, and Hyprland's emergency mode.
//!
//! - `hold` (the PreTransaction hook, before the first file): every running Hyprland (as
//!   root, every user's: each `/run/user/<uid>/hypr/<signature>`, reached through its
//!   instance signature with hyprctl run as that user) gets `misc.disable_autoreload` on.
//!   What it was is recorded (`/run/bromigos/hypr-hold/`, or `$XDG_RUNTIME_DIR/
//!   bromigos-hypr-hold/` for a user's own), keyed by the compositor's PID and start time.
//! - `release` (the PostTransaction hook, after every package's files are in place): each
//!   compositor's config is verified (`Hyprland --verify-config`, as its user, in its own
//!   environment and with its own `-c`), reloaded once when it verifies, and auto-reload is
//!   put back as it was. A config that doesn't verify isn't reloaded (Hyprland keeps
//!   running what it ran) and is reported. Under pacman, a compositor that wasn't held (it
//!   started mid-transaction, or the hook wasn't installed yet) gets the verified reload too.
//! - A transaction that fails after `hold` never runs its PostTransaction hooks: under
//!   pacman, `hold` leaves a detached watcher that waits for pacman to exit and then
//!   releases whatever is still held.

use std::ffi::OsString;
use std::fs;
use std::io::Read;
use std::os::unix::ffi::OsStringExt;
use std::os::unix::fs::{DirBuilderExt, MetadataExt};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::paths::Paths;
use crate::session;

/// The PATH hyprctl and Hyprland get when root runs them for a user.
const SAFE_PATH: &str = "/usr/local/sbin:/usr/local/bin:/usr/bin";

/// Whose compositors: every user's (root, the hooks) or the caller's own.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Scope {
    /// Every `<run_user>/<uid>` runtime dir (`/run/user`); records in `records`.
    Everyone { run_user: PathBuf, records: PathBuf },
    /// One runtime dir, the caller's.
    Me { runtime_dir: PathBuf },
}

impl Scope {
    /// Root: everyone's (`/run/user`, records in `/run/bromigos/hypr-hold`); anyone else:
    /// their own (`$XDG_RUNTIME_DIR`).
    pub fn for_caller(paths: &Paths) -> Scope {
        if rustix::process::geteuid().is_root() {
            Scope::Everyone {
                run_user: PathBuf::from("/run/user"),
                records: PathBuf::from("/run/bromigos/hypr-hold"),
            }
        } else {
            Scope::Me {
                runtime_dir: paths.runtime_dir.clone(),
            }
        }
    }

    fn records(&self) -> PathBuf {
        match self {
            Scope::Everyone { records, .. } => records.clone(),
            Scope::Me { runtime_dir } => runtime_dir.join("bromigos-hypr-hold"),
        }
    }

    /// (owner's uid, runtime dir) for each runtime dir in scope.
    fn runtime_dirs(&self) -> Vec<(Option<u32>, PathBuf)> {
        match self {
            Scope::Everyone { run_user, .. } => user_runtime_dirs(run_user)
                .into_iter()
                .map(|(u, p)| (Some(u), p))
                .collect(),
            Scope::Me { runtime_dir } => vec![(None, runtime_dir.clone())],
        }
    }
}

/// `<run_user>/<uid>` directories: numeric names, owned by that uid.
pub fn user_runtime_dirs(run_user: &Path) -> Vec<(u32, PathBuf)> {
    let mut out: Vec<(u32, PathBuf)> = fs::read_dir(run_user)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let uid = e.file_name().to_str()?.parse::<u32>().ok()?;
            let md = fs::symlink_metadata(e.path()).ok()?;
            (md.is_dir() && md.uid() == uid).then(|| (uid, e.path()))
        })
        .collect();
    out.sort();
    out
}

/// One running Hyprland, and how to reach it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Compositor {
    pub user: String,
    pub uid: u32,
    #[serde(skip)]
    pub gid: u32,
    pub signature: String,
    pub pid: i32,
    /// Its start time (field 22 of /proc/PID/stat): a PID given to another process since
    /// is never taken for it.
    pub start: u64,
    #[serde(skip)]
    pub runtime_dir: PathBuf,
}

/// What hold or release did to one compositor.
#[derive(Debug, Clone, Serialize)]
pub struct Outcome {
    pub user: String,
    pub uid: u32,
    pub signature: String,
    pub pid: i32,
    /// `held`, `reloaded`, `not reloaded`, `released`, `gone`.
    pub action: String,
    pub ok: bool,
    /// Auto-reload was off before the hold (the user's own setting), when known.
    pub was_off: Option<bool>,
    pub detail: String,
}

impl Outcome {
    fn new(c: &Compositor, action: &str, ok: bool, was_off: Option<bool>, detail: String) -> Self {
        Outcome {
            user: c.user.clone(),
            uid: c.uid,
            signature: c.signature.clone(),
            pid: c.pid,
            action: action.to_owned(),
            ok,
            was_off,
            detail,
        }
    }

    /// One line for pacman's output.
    pub fn line(&self) -> String {
        let sig: String = self.signature.chars().take(8).collect();
        format!(
            "bromigOS: Hyprland of {} ({sig}…): {}",
            self.user, self.detail
        )
    }
}

/// A hold, remembered until its release.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct Record {
    uid: u32,
    signature: String,
    pid: i32,
    start: u64,
    was_off: bool,
}

impl Record {
    fn of(&self, c: &Compositor) -> bool {
        self.uid == c.uid
            && self.signature == c.signature
            && self.pid == c.pid
            && self.start == c.start
    }
    fn file(&self) -> String {
        record_file(self.uid, &self.signature)
    }
}

fn record_file(uid: u32, signature: &str) -> String {
    let safe: String = signature
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '_' || ch == '-' {
                ch
            } else {
                '_'
            }
        })
        .collect();
    format!("{uid}-{safe}.json")
}

/// A process's start time, real uid and gid, and name, from /proc.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcInfo {
    pub start: u64,
    pub uid: u32,
    pub gid: u32,
    pub comm: String,
}

pub fn proc_info(pid: i32) -> Option<ProcInfo> {
    let stat = fs::read(format!("/proc/{pid}/stat")).ok()?;
    let start = start_from_stat(&stat)?;
    let status = fs::read_to_string(format!("/proc/{pid}/status")).ok()?;
    let id = |key: &str| -> Option<u32> {
        status
            .lines()
            .find_map(|l| l.strip_prefix(key))?
            .split_whitespace()
            .next()?
            .parse()
            .ok()
    };
    let comm = fs::read_to_string(format!("/proc/{pid}/comm")).ok()?;
    Some(ProcInfo {
        start,
        uid: id("Uid:")?,
        gid: id("Gid:")?,
        comm: comm.trim().to_owned(),
    })
}

/// Field 22 of /proc/PID/stat (the name in field 2 may hold spaces and parentheses).
pub fn start_from_stat(stat: &[u8]) -> Option<u64> {
    let close = stat.iter().rposition(|b| *b == b')')?;
    let rest = std::str::from_utf8(stat.get(close + 2..)?).ok()?;
    rest.split_whitespace().nth(19)?.parse().ok()
}

/// The process is still the one recorded, and running (a zombie has exited).
pub fn same_process(pid: i32, start: u64) -> bool {
    let Ok(stat) = fs::read(format!("/proc/{pid}/stat")) else {
        return false;
    };
    let state = stat
        .iter()
        .rposition(|b| *b == b')')
        .and_then(|i| stat.get(i + 2))
        .copied();
    !matches!(state, Some(b'Z' | b'X')) && start_from_stat(&stat) == Some(start)
}

fn user_name(uid: u32) -> String {
    fs::read_to_string("/etc/passwd")
        .ok()
        .and_then(|p| {
            p.lines().find_map(|l| {
                let mut f = l.split(':');
                let name = f.next()?;
                (f.nth(1)?.parse::<u32>().ok()? == uid).then(|| name.to_owned())
            })
        })
        .unwrap_or_else(|| uid.to_string())
}

/// Every running Hyprland in scope: an instance directory whose lock names a live
/// process called Hyprland, owned by the runtime dir's user, with its control socket.
pub fn compositors(scope: &Scope) -> Vec<Compositor> {
    let mut out = Vec::new();
    for (owner, runtime) in scope.runtime_dirs() {
        for dir in session::instance_dirs(&runtime.join("hypr")) {
            let Some((Some(pid), _)) = session::read_lock(&dir) else {
                continue;
            };
            let Some(info) = proc_info(pid) else {
                continue;
            };
            if !info.comm.eq_ignore_ascii_case("hyprland")
                || owner.is_some_and(|u| u != info.uid)
                || !dir.join(".socket.sock").exists()
            {
                continue;
            }
            let Some(signature) = dir.file_name().map(|n| n.to_string_lossy().into_owned()) else {
                continue;
            };
            out.push(Compositor {
                user: user_name(info.uid),
                uid: info.uid,
                gid: info.gid,
                signature,
                pid,
                start: info.start,
                runtime_dir: runtime.clone(),
            });
        }
    }
    out
}

// ------------------------------------------------------------------ talking to it

/// `prog` as the compositor's user (root drops to it; anyone else runs as themselves).
fn as_user(c: &Compositor, prog: &str) -> Command {
    let mut cmd = Command::new(prog);
    if rustix::process::geteuid().is_root() {
        cmd.env_clear().env("PATH", SAFE_PATH);
        if c.uid != 0 {
            cmd.uid(c.uid).gid(c.gid);
        }
    }
    cmd
}

/// Runs `cmd` with a deadline: (success, stdout, stderr), or what went wrong.
fn run(mut cmd: Command, limit: Duration) -> Result<(bool, String, String), String> {
    let mut child = cmd
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("{}: {e}", cmd.get_program().to_string_lossy()))?;
    let reader = |r: Option<Box<dyn Read + Send>>| {
        std::thread::spawn(move || {
            let mut s = Vec::new();
            if let Some(mut r) = r {
                let _ = r.read_to_end(&mut s);
            }
            String::from_utf8_lossy(&s).into_owned()
        })
    };
    let out = reader(
        child
            .stdout
            .take()
            .map(|r| Box::new(r) as Box<dyn Read + Send>),
    );
    let err = reader(
        child
            .stderr
            .take()
            .map(|r| Box::new(r) as Box<dyn Read + Send>),
    );
    let deadline = Instant::now() + limit;
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break st,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(20)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!(
                    "{} didn't answer in {} s",
                    cmd.get_program().to_string_lossy(),
                    limit.as_secs()
                ));
            }
        }
    };
    Ok((
        status.success(),
        out.join().unwrap_or_default(),
        err.join().unwrap_or_default(),
    ))
}

fn hyprctl(c: &Compositor, args: &[&str]) -> Result<String, String> {
    let mut cmd = as_user(c, "hyprctl");
    cmd.env("XDG_RUNTIME_DIR", &c.runtime_dir)
        .env("HYPRLAND_INSTANCE_SIGNATURE", &c.signature)
        .args(args);
    match run(cmd, Duration::from_secs(5))? {
        (true, out, _) => Ok(out.trim().to_owned()),
        (false, out, err) => Err(format!(
            "hyprctl {}: {}",
            args[0],
            last_lines(&format!("{out}{err}"), 2)
        )),
    }
}

/// `misc.disable_autoreload` now (None: hyprctl didn't answer).
fn autoreload_off(c: &Compositor) -> Option<bool> {
    let out = hyprctl(c, &["getoption", "misc:disable_autoreload", "-j"]).ok()?;
    let v: Value = serde_json::from_str(&out).ok()?;
    v.get("bool")
        .and_then(Value::as_bool)
        .or_else(|| v.get("int").and_then(Value::as_i64).map(|i| i != 0))
}

/// Sets it and reads it back: `hl.config` (a Lua config), else the keyword (hyprlang).
fn set_autoreload_off(c: &Compositor, off: bool) -> bool {
    for _ in 0..3 {
        let _ = hyprctl(
            c,
            &[
                "eval",
                &format!("hl.config({{ misc = {{ disable_autoreload = {off} }} }})"),
            ],
        );
        if autoreload_off(c) == Some(off) {
            return true;
        }
        let _ = hyprctl(
            c,
            &[
                "keyword",
                "misc:disable_autoreload",
                if off { "1" } else { "0" },
            ],
        );
        if autoreload_off(c) == Some(off) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    false
}

/// The compositor's environment at its start (/proc/PID/environ).
fn environ(pid: i32) -> Vec<(OsString, OsString)> {
    fs::read(format!("/proc/{pid}/environ"))
        .unwrap_or_default()
        .split(|b| *b == 0)
        .filter_map(|kv| {
            let eq = kv.iter().position(|b| *b == b'=')?;
            Some((
                OsString::from_vec(kv[..eq].to_vec()),
                OsString::from_vec(kv[eq + 1..].to_vec()),
            ))
        })
        .collect()
}

fn cmdline(pid: i32) -> Vec<OsString> {
    fs::read(format!("/proc/{pid}/cmdline"))
        .unwrap_or_default()
        .split(|b| *b == 0)
        .filter(|a| !a.is_empty())
        .map(|a| OsString::from_vec(a.to_vec()))
        .collect()
}

/// The config the compositor runs: its `-c`/`--config`, else Hyprland's own lookup
/// (`$XDG_CONFIG_HOME/hypr/hyprland.lua`, then `hyprland.conf`) in its environment.
pub fn config_path(
    argv: &[OsString],
    env: &[(OsString, OsString)],
    home: &Path,
) -> Option<PathBuf> {
    let mut it = argv.iter().skip(1);
    while let Some(a) = it.next() {
        if a == "-c" || a == "--config" {
            return it.next().map(PathBuf::from);
        }
        if let Some(v) = a.to_str().and_then(|s| s.strip_prefix("--config=")) {
            return Some(PathBuf::from(v));
        }
    }
    let get = |k: &str| {
        env.iter()
            .find(|(n, _)| n == k)
            .map(|(_, v)| PathBuf::from(v))
    };
    let home = get("HOME").unwrap_or_else(|| home.to_path_buf());
    let config = get("XDG_CONFIG_HOME")
        .filter(|p| p.is_absolute())
        .unwrap_or_else(|| home.join(".config"));
    ["hyprland.lua", "hyprland.conf"]
        .iter()
        .map(|f| config.join("hypr").join(f))
        .find(|p| p.exists())
}

fn passwd_home(uid: u32) -> PathBuf {
    fs::read_to_string("/etc/passwd")
        .ok()
        .and_then(|p| {
            p.lines().find_map(|l| {
                let f: Vec<&str> = l.split(':').collect();
                (f.len() > 5 && f[2].parse::<u32>().ok()? == uid).then(|| PathBuf::from(f[5]))
            })
        })
        .unwrap_or_else(|| PathBuf::from("/"))
}

/// `Hyprland --verify-config` on the compositor's config, as its user, in its environment.
fn verify(c: &Compositor) -> Result<(), String> {
    let env = environ(c.pid);
    let config = config_path(&cmdline(c.pid), &env, &passwd_home(c.uid));
    let mut cmd = as_user(c, "Hyprland");
    if !env.is_empty() {
        cmd.env_clear().envs(env);
        if !cmd
            .get_envs()
            .any(|(k, _)| k == std::ffi::OsStr::new("PATH"))
        {
            cmd.env("PATH", SAFE_PATH);
        }
    }
    // verify-config reaches no compositor, and nothing here should
    cmd.env_remove("WAYLAND_DISPLAY")
        .env_remove("HYPRLAND_INSTANCE_SIGNATURE")
        .arg("--verify-config");
    if let Some(p) = &config {
        cmd.arg("-c").arg(p);
    }
    let (ok, out, err) = run(cmd, Duration::from_secs(60))?;
    let all = format!("{out}{err}");
    if ok && all.contains("config ok") {
        Ok(())
    } else {
        Err(last_lines(&all, 3))
    }
}

/// `hyprctl reload`, then the config errors it reports (none: an empty list).
fn reload(c: &Compositor) -> Result<Vec<String>, String> {
    hyprctl(c, &["reload"])?;
    let raw = hyprctl(c, &["configerrors", "-j"]).unwrap_or_default();
    let errs = serde_json::from_str::<Vec<String>>(&raw)
        .unwrap_or_else(|_| vec![raw.clone()])
        .into_iter()
        .map(|e| e.trim().to_owned())
        .filter(|e| !e.is_empty())
        .collect();
    Ok(errs)
}

fn last_lines(s: &str, n: usize) -> String {
    let lines: Vec<&str> = s.lines().map(str::trim).filter(|l| !l.is_empty()).collect();
    let tail = &lines[lines.len().saturating_sub(n)..];
    if tail.is_empty() {
        "no output".to_owned()
    } else {
        tail.join(" | ")
    }
}

// ------------------------------------------------------------------ records

fn records(scope: &Scope) -> Vec<Record> {
    fs::read_dir(scope.records())
        .into_iter()
        .flatten()
        .flatten()
        .filter(|e| e.path().extension().is_some_and(|x| x == "json"))
        .filter_map(|e| serde_json::from_slice(&fs::read(e.path()).ok()?).ok())
        .collect()
}

fn save_record(scope: &Scope, r: &Record) -> std::io::Result<()> {
    let dir = scope.records();
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)?;
    let tmp = dir.join(format!(".{}.tmp", r.file()));
    fs::write(&tmp, serde_json::to_vec(r).map_err(std::io::Error::other)?)?;
    fs::rename(tmp, dir.join(r.file()))
}

fn drop_record(scope: &Scope, r: &Record) {
    let _ = fs::remove_file(scope.records().join(r.file()));
}

/// Hold, release and the watcher one at a time: an exclusive lock on the records' `.lock`
/// (released when the returned file closes). A release pacman's death left running and the
/// watcher it woke never act at once.
fn serial(scope: &Scope) -> Option<fs::File> {
    let dir = scope.records();
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .ok()?;
    let f = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(dir.join(".lock"))
        .ok()?;
    rustix::fs::flock(&f, rustix::fs::FlockOperation::LockExclusive).ok()?;
    Some(f)
}

/// Whether anything is held now (records of compositors still running).
pub fn held(scope: &Scope) -> bool {
    records(scope).iter().any(|r| same_process(r.pid, r.start))
}

// ------------------------------------------------------------------ hold, release

/// Auto-reload off in every running Hyprland in scope, what it was recorded.
pub fn hold(scope: &Scope) -> Vec<Outcome> {
    let _serial = serial(scope);
    let recs = records(scope);
    for r in &recs {
        if !same_process(r.pid, r.start) {
            drop_record(scope, r); // its compositor is gone
        }
    }
    compositors(scope)
        .into_iter()
        .map(|c| {
            // held already (a hold before this one's release): keep the first one's value,
            // never record our own hold as the user's setting
            let before = recs.iter().find(|r| r.of(&c)).map(|r| r.was_off);
            let was_off = match before.or_else(|| autoreload_off(&c)) {
                Some(v) => v,
                None => {
                    return Outcome::new(
                        &c,
                        "held",
                        false,
                        None,
                        "hyprctl didn't answer; not held".to_owned(),
                    );
                }
            };
            if !set_autoreload_off(&c, true) {
                return Outcome::new(
                    &c,
                    "held",
                    false,
                    Some(was_off),
                    "couldn't turn auto-reload off".to_owned(),
                );
            }
            let rec = Record {
                uid: c.uid,
                signature: c.signature.clone(),
                pid: c.pid,
                start: c.start,
                was_off,
            };
            match save_record(scope, &rec) {
                Ok(()) => Outcome::new(
                    &c,
                    "held",
                    true,
                    Some(was_off),
                    "auto-reload held off while the files change".to_owned(),
                ),
                Err(e) => {
                    // unrecorded, it would stay off: put it back
                    set_autoreload_off(&c, was_off);
                    Outcome::new(
                        &c,
                        "held",
                        false,
                        Some(was_off),
                        format!("couldn't record the hold: {e}"),
                    )
                }
            }
        })
        .collect()
}

/// Each held compositor (and with `unheld`, every running one): its config verified,
/// reloaded once when it verifies, auto-reload back as it was.
pub fn release(scope: &Scope, unheld: bool) -> Vec<Outcome> {
    let _serial = serial(scope);
    let recs = records(scope);
    let mut out = Vec::new();
    for c in compositors(scope) {
        let rec = recs.iter().find(|r| r.of(&c));
        if rec.is_none() && !unheld {
            continue;
        }
        let was_off = rec.map(|r| r.was_off);
        let back = |c: &Compositor| match was_off {
            Some(off) if set_autoreload_off(c, off) => {
                if off {
                    "; auto-reload stays off (yours)"
                } else {
                    "; auto-reload back on"
                }
            }
            Some(_) => "; auto-reload couldn't be put back (hyprctl reload restores the config's)",
            None => "",
        };
        let o = match verify(&c) {
            Ok(()) => match reload(&c) {
                Ok(errs) if errs.is_empty() => {
                    let b = back(&c);
                    Outcome::new(
                        &c,
                        "reloaded",
                        true,
                        was_off,
                        format!("config ok, reloaded once{b}"),
                    )
                }
                Ok(errs) => {
                    let b = back(&c);
                    Outcome::new(
                        &c,
                        "reloaded",
                        false,
                        was_off,
                        format!("reloaded once; Hyprland reports: {}{b}", errs[0]),
                    )
                }
                Err(e) => {
                    let b = back(&c);
                    Outcome::new(&c, "not reloaded", false, was_off, format!("{e}{b}"))
                }
            },
            Err(why) => {
                let b = back(&c);
                Outcome::new(
                    &c,
                    "not reloaded",
                    false,
                    was_off,
                    format!(
                        "the config doesn't verify, so it isn't reloaded ({why}){b}; \
                         fix it, then hyprctl reload"
                    ),
                )
            }
        };
        if let Some(r) = rec {
            drop_record(scope, r);
        }
        out.push(o);
    }
    for r in &recs {
        if !same_process(r.pid, r.start) {
            drop_record(scope, r);
        }
    }
    out
}

/// A process to wait for: its PID and start time.
pub type Pid = (i32, u64);

/// Under pacman, before anything is held: a detached `bromigos session release --after
/// PACMAN,HOLD` (each `PID:START`) that waits for pacman (this process's parent) and this
/// hold to exit, then releases whatever is still held (pacman runs no PostTransaction hook
/// when the transaction fails, or when it's killed). `Ok(None)`: pacman is gone already,
/// so nothing should be held. Its stdio is /dev/null: pacman reads a hook's output to its
/// end, so the watcher must hold none of it.
pub fn spawn_watcher() -> Result<Option<[Pid; 2]>, String> {
    let ppid = rustix::process::getppid()
        .map(|p| p.as_raw_nonzero().get())
        .ok_or("no parent")?;
    // reparented to init: pacman died before this hook asked
    let Some(pacman) = proc_info(ppid)
        .filter(|_| ppid != 1)
        .map(|i| (ppid, i.start))
    else {
        return Ok(None);
    };
    let me = std::process::id() as i32;
    let hold = (me, proc_info(me).map(|i| i.start).ok_or("no /proc")?);
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let mut cmd = Command::new(exe);
    cmd.args([
        "session",
        "release",
        "--after",
        &format!("{}:{},{}:{}", pacman.0, pacman.1, hold.0, hold.1),
    ])
    .stdin(Stdio::null())
    .stdout(Stdio::null())
    .stderr(Stdio::null());
    // its own session: pacman's terminal and its Ctrl-C don't reach it
    // SAFETY: setsid is async-signal-safe
    unsafe {
        cmd.pre_exec(|| {
            let _ = rustix::process::setsid();
            Ok(())
        });
    }
    cmd.spawn().map_err(|e| e.to_string())?;
    Ok(Some([pacman, hold]))
}

/// `PID:START[,PID:START…]`.
pub fn parse_after(spec: &str) -> Option<Vec<Pid>> {
    spec.split(',')
        .map(|one| {
            let (p, s) = one.split_once(':')?;
            Some((p.trim().parse().ok()?, s.trim().parse().ok()?))
        })
        .collect()
}

/// The watcher: waits until every one of `after` is gone, then releases what is still held
/// (the release hook never ran, or was cut short). Logged to the journal.
pub fn watch_then_release(scope: &Scope, after: &[Pid]) -> Vec<Outcome> {
    while after.iter().any(|(pid, start)| same_process(*pid, *start)) {
        std::thread::sleep(Duration::from_millis(200));
    }
    if !held(scope) {
        return Vec::new();
    }
    let out = release(scope, false);
    for o in &out {
        crate::log(
            "bromigos-hypr-hold",
            &format!(
                "the transaction ended without its release hook: {}",
                o.line()
            ),
        );
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stat_start_time_past_an_odd_name() {
        let mut stat =
            b"1234 (we(i)rd ) name) S 1 1234 1234 0 -1 4194560 100 0 0 0 1 2 0 0 20 0 1 0 "
                .to_vec();
        stat.extend_from_slice(
            b"987654 12345678 300 18446744073709551615 1 1 0 0 0 0 0 0 0 0 0 0 17 3 0 0\n",
        );
        assert_eq!(start_from_stat(&stat), Some(987654));
        assert_eq!(start_from_stat(b"1 (x) S"), None);
        let me = std::process::id() as i32;
        let info = proc_info(me).unwrap();
        assert!(same_process(me, info.start));
        assert!(!same_process(me, info.start + 1));
    }

    #[test]
    fn user_runtime_dirs_are_numeric_and_their_owners() {
        let t = tempfile::tempdir().unwrap();
        let me = rustix::process::getuid().as_raw();
        fs::create_dir(t.path().join(me.to_string())).unwrap();
        fs::create_dir(t.path().join("notanumber")).unwrap();
        fs::create_dir(t.path().join((me + 1).to_string())).unwrap(); // owned by us, named for another
        fs::write(t.path().join("4242"), "").unwrap();
        assert_eq!(
            user_runtime_dirs(t.path()),
            vec![(me, t.path().join(me.to_string()))]
        );
    }

    #[test]
    fn config_path_follows_the_compositor() {
        let t = tempfile::tempdir().unwrap();
        let argv = |a: &[&str]| a.iter().map(OsString::from).collect::<Vec<_>>();
        let env = |kv: &[(&str, &Path)]| {
            kv.iter()
                .map(|(k, v)| (OsString::from(k), v.as_os_str().to_owned()))
                .collect::<Vec<_>>()
        };
        assert_eq!(
            config_path(&argv(&["Hyprland", "-c", "/x/h.lua"]), &[], t.path()),
            Some(PathBuf::from("/x/h.lua"))
        );
        assert_eq!(
            config_path(&argv(&["Hyprland", "--config=/y.lua"]), &[], t.path()),
            Some(PathBuf::from("/y.lua"))
        );
        // its own lookup: XDG_CONFIG_HOME, Lua first
        let cfg = t.path().join("cfg");
        fs::create_dir_all(cfg.join("hypr")).unwrap();
        assert_eq!(
            config_path(
                &argv(&["Hyprland"]),
                &env(&[("XDG_CONFIG_HOME", &cfg)]),
                t.path()
            ),
            None
        );
        fs::write(cfg.join("hypr/hyprland.conf"), "").unwrap();
        assert_eq!(
            config_path(
                &argv(&["Hyprland"]),
                &env(&[("XDG_CONFIG_HOME", &cfg)]),
                t.path()
            ),
            Some(cfg.join("hypr/hyprland.conf"))
        );
        fs::write(cfg.join("hypr/hyprland.lua"), "").unwrap();
        assert_eq!(
            config_path(
                &argv(&["Hyprland", "--watchdog-fd", "4"]),
                &env(&[("XDG_CONFIG_HOME", &cfg)]),
                t.path()
            ),
            Some(cfg.join("hypr/hyprland.lua"))
        );
        // HOME's .config without XDG_CONFIG_HOME
        let home = t.path().join("home");
        fs::create_dir_all(home.join(".config/hypr")).unwrap();
        fs::write(home.join(".config/hypr/hyprland.lua"), "").unwrap();
        assert_eq!(
            config_path(&argv(&["Hyprland"]), &env(&[("HOME", &home)]), t.path()),
            Some(home.join(".config/hypr/hyprland.lua"))
        );
    }

    #[test]
    fn after_specs() {
        assert_eq!(parse_after("12:34"), Some(vec![(12, 34)]));
        assert_eq!(parse_after("12:34,56:78"), Some(vec![(12, 34), (56, 78)]));
        assert_eq!(parse_after("12"), None);
        assert_eq!(parse_after("12:x"), None);
    }

    #[test]
    fn record_files_are_plain_names() {
        assert_eq!(record_file(1000, "abc_123_456"), "1000-abc_123_456.json");
        assert_eq!(record_file(1000, "../x"), "1000-___x.json");
    }
}
