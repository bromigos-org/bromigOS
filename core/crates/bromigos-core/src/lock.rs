//! The lock launcher: lock the screen, and keep it locked if the locker crashes.
//!
//! Runs a screen locker (`gtklock`, falling back to `hyprlock`; `$BROMIGOS_LOCKER`
//! overrides the list). Exit 0 means the user unlocked it with their password: done.
//! Anything else (a crash, a kill) means the session is still locked with no lock
//! screen on it, so the locker is started again at once; Hyprland's
//! `misc.allow_session_lock_restore` lets the new one take over. A locker that fails
//! twice in a row within 3 s of starting (missing, broken config) gives way to the next
//! in the list. After 30 tries it gives up.
//!
//! This never unlocks anything and never signals a locker (SIGUSR1 unlocks hyprlock,
//! and signalling hyprlock has crashed it). One instance at a time: a second call while
//! one runs is a no-op. The lock file's descriptor is inherited by the locker, as in
//! the shell version, so a locker that outlives this process still counts.

use std::fs::{File, OpenOptions, TryLockError};
use std::io;
use std::os::unix::process::ExitStatusExt;
use std::path::PathBuf;
use std::process::Command;
use std::time::{Duration, Instant};

/// The lockers tried when `$BROMIGOS_LOCKER` is unset or empty.
pub const DEFAULT_LOCKERS: &[&str] = &["gtklock", "hyprlock"];

/// How the launcher runs.
pub struct LockConfig<'a> {
    /// Locker commands (no arguments), in order of preference.
    pub lockers: Vec<String>,
    /// The single-instance lock file.
    pub flock_path: PathBuf,
    /// Locker starts before giving up.
    pub tries: u32,
    /// A run shorter than this counts as a failure to start.
    pub quick: Duration,
    /// The pause before restarting a locker that exited.
    pub restart_delay: Duration,
    /// Where messages go (the CLI sends them to `logger -t bromigos-lock`).
    pub log: Box<dyn FnMut(&str) + 'a>,
}

impl<'a> LockConfig<'a> {
    /// The shell version's settings: 30 tries, 3 s, 0.5 s.
    pub fn new(lockers: Vec<String>, flock_path: PathBuf, log: Box<dyn FnMut(&str) + 'a>) -> Self {
        LockConfig {
            lockers,
            flock_path,
            tries: 30,
            quick: Duration::from_secs(3),
            restart_delay: Duration::from_millis(500),
            log,
        }
    }
}

/// The locker list from `$BROMIGOS_LOCKER` (whitespace-separated; unset or blank
/// means the default).
pub fn lockers_from(var: Option<&str>) -> Vec<String> {
    let words: Vec<String> = var
        .unwrap_or_default()
        .split_whitespace()
        .map(str::to_owned)
        .collect();
    if words.is_empty() {
        DEFAULT_LOCKERS.iter().map(|s| s.to_string()).collect()
    } else {
        words
    }
}

/// How a launcher run ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    /// A locker exited 0: the user unlocked.
    Unlocked,
    /// Another launcher holds the lock; nothing was started.
    AlreadyRunning,
    /// No locker stayed up.
    GaveUp,
}

impl Outcome {
    /// The process exit code (0, 0, 1 as in the shell version).
    pub fn exit_code(self) -> i32 {
        match self {
            Outcome::Unlocked | Outcome::AlreadyRunning => 0,
            Outcome::GaveUp => 1,
        }
    }
}

/// Takes the single-instance lock; `None` when another launcher holds it. The
/// descriptor is made inheritable so the locker holds the lock too.
fn take_lock(path: &PathBuf) -> io::Result<Option<File>> {
    let f = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(path)?;
    match f.try_lock() {
        Ok(()) => {}
        Err(TryLockError::WouldBlock) => return Ok(None),
        Err(TryLockError::Error(e)) => return Err(e),
    }
    rustix::io::fcntl_setfd(&f, rustix::io::FdFlags::empty())?;
    Ok(Some(f))
}

/// Runs one locker to completion; its exit code as the shell reports it (127 when it
/// cannot be started, 128+N when killed by signal N).
fn run_locker(locker: &str) -> i32 {
    match Command::new(locker).status() {
        Ok(st) => st
            .code()
            .or_else(|| st.signal().map(|s| 128 + s))
            .unwrap_or(1),
        Err(e) if e.kind() == io::ErrorKind::PermissionDenied => 126,
        Err(_) => 127,
    }
}

/// The launcher loop. Messages go to `cfg.log`; it never returns an error, because
/// a failure to lock must still try to lock.
pub fn run(mut cfg: LockConfig<'_>) -> Outcome {
    // Without a lock file (an unwritable runtime dir) the screen still gets locked:
    // only the single-instance guard is lost.
    let _lock = match take_lock(&cfg.flock_path) {
        Ok(Some(f)) => Some(f),
        Ok(None) => return Outcome::AlreadyRunning,
        Err(e) => {
            (cfg.log)(&format!(
                "can't take {}: {e}; locking without the single-instance guard",
                cfg.flock_path.display()
            ));
            None
        }
    };
    if cfg.lockers.is_empty() {
        cfg.lockers = lockers_from(None);
    }
    let mut i = 0;
    let mut quick = 0;
    for attempt in 1..=cfg.tries {
        let locker = cfg.lockers[i].clone();
        let started = Instant::now();
        let rc = run_locker(&locker);
        if rc == 0 {
            return Outcome::Unlocked;
        }
        if started.elapsed() < cfg.quick {
            quick += 1;
        } else {
            quick = 0;
        }
        if quick >= 2 && i + 1 < cfg.lockers.len() {
            (cfg.log)(&format!(
                "{locker} won't start (exit {rc}); falling back to {}",
                cfg.lockers[i + 1]
            ));
            i += 1;
            quick = 0;
            continue;
        }
        (cfg.log)(&format!(
            "{locker} exited {rc} while locked (try {attempt}); starting it again"
        ));
        std::thread::sleep(cfg.restart_delay);
    }
    (cfg.log)(&format!(
        "no locker stays up; giving up after {} tries",
        cfg.tries
    ));
    Outcome::GaveUp
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    use std::path::Path;
    use std::sync::Mutex;

    /// Serializes these tests: a script written while another thread forks can be
    /// held open for writing in the child for a moment, and exec then fails with
    /// ETXTBSY ("text file busy").
    static SERIAL: Mutex<()> = Mutex::new(());

    /// A fake locker: appends its name to `runs`, then runs `body`.
    fn fake(dir: &Path, name: &str, body: &str) -> String {
        let _serial = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
        let p = dir.join(name);
        let runs = dir.join("runs");
        fs::write(
            &p,
            format!("#!/bin/sh\necho {name} >> '{}'\n{body}\n", runs.display()),
        )
        .unwrap();
        fs::set_permissions(&p, fs::Permissions::from_mode(0o755)).unwrap();
        p.display().to_string()
    }

    fn runs(dir: &Path) -> Vec<String> {
        fs::read_to_string(dir.join("runs"))
            .unwrap_or_default()
            .lines()
            .map(str::to_owned)
            .collect()
    }

    fn go(dir: &Path, lockers: Vec<String>, tries: u32) -> (Outcome, Vec<String>) {
        let _serial = SERIAL.lock().unwrap_or_else(|e| e.into_inner());
        let log = RefCell::new(Vec::new());
        let mut cfg = LockConfig::new(
            lockers,
            dir.join("bromigos-lock.flock"),
            Box::new(|m: &str| log.borrow_mut().push(m.to_owned())),
        );
        cfg.tries = tries;
        cfg.restart_delay = Duration::from_millis(10);
        let out = run(cfg);
        (out, log.into_inner())
    }

    #[test]
    fn exit_zero_stops() {
        let d = tempfile::tempdir().unwrap();
        let a = fake(d.path(), "a", "exit 0");
        let b = fake(d.path(), "b", "exit 0");
        let (out, log) = go(d.path(), vec![a, b], 30);
        assert_eq!(out, Outcome::Unlocked);
        assert_eq!(runs(d.path()), ["a"]);
        assert!(log.is_empty());
    }

    #[test]
    fn crash_then_restart_same_locker() {
        let d = tempfile::tempdir().unwrap();
        let marker = d.path().join("crashed");
        // first run: killed by a signal (a crash); second: unlocked
        let a = fake(
            d.path(),
            "a",
            &format!(
                "if [ -e '{m}' ]; then exit 0; fi; touch '{m}'; kill -SEGV $$",
                m = marker.display()
            ),
        );
        let b = fake(d.path(), "b", "exit 0");
        let (out, log) = go(d.path(), vec![a, b], 30);
        assert_eq!(out, Outcome::Unlocked);
        assert_eq!(runs(d.path()), ["a", "a"]);
        assert_eq!(log.len(), 1);
        assert!(log[0].ends_with("exited 139 while locked (try 1); starting it again"));
    }

    #[test]
    fn missing_at_start_falls_back() {
        let d = tempfile::tempdir().unwrap();
        let missing = d.path().join("no-such-locker").display().to_string();
        let b = fake(d.path(), "b", "exit 0");
        let (out, log) = go(d.path(), vec![missing.clone(), b.clone()], 30);
        assert_eq!(out, Outcome::Unlocked);
        assert_eq!(runs(d.path()), ["b"]);
        assert_eq!(
            log,
            [
                format!("{missing} exited 127 while locked (try 1); starting it again"),
                format!("{missing} won't start (exit 127); falling back to {b}"),
            ]
        );
    }

    #[test]
    fn broken_at_start_falls_back() {
        let d = tempfile::tempdir().unwrap();
        let a = fake(d.path(), "a", "exit 1");
        let b = fake(d.path(), "b", "exit 0");
        let (out, _) = go(d.path(), vec![a, b], 30);
        assert_eq!(out, Outcome::Unlocked);
        assert_eq!(runs(d.path()), ["a", "a", "b"]);
    }

    #[test]
    fn last_locker_is_retried_then_gives_up() {
        let d = tempfile::tempdir().unwrap();
        let a = fake(d.path(), "a", "exit 1");
        let (out, log) = go(d.path(), vec![a], 5);
        assert_eq!(out, Outcome::GaveUp);
        assert_eq!(runs(d.path()).len(), 5);
        assert_eq!(
            log.last().unwrap(),
            "no locker stays up; giving up after 5 tries"
        );
    }

    #[test]
    fn second_instance_is_a_no_op() {
        let d = tempfile::tempdir().unwrap();
        let held = take_lock(&d.path().join("bromigos-lock.flock"))
            .unwrap()
            .unwrap();
        let a = fake(d.path(), "a", "exit 0");
        let (out, log) = go(d.path(), vec![a], 30);
        assert_eq!(out, Outcome::AlreadyRunning);
        assert!(runs(d.path()).is_empty());
        assert!(log.is_empty());
        drop(held);
    }

    #[test]
    fn locker_list_from_env() {
        assert_eq!(lockers_from(None), ["gtklock", "hyprlock"]);
        assert_eq!(lockers_from(Some("  ")), ["gtklock", "hyprlock"]);
        assert_eq!(
            lockers_from(Some("hyprlock  gtklock")),
            ["hyprlock", "gtklock"]
        );
    }
}
