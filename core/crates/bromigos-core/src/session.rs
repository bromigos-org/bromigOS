//! Finding the live Hyprland session.
//!
//! Every Hyprland that starts, a nested test copy included, exports its own display to
//! systemd's and D-Bus's activation environment. When the copy exits the stale value
//! stays, and anything started on demand afterwards (xdg-desktop-portal-hyprland, when
//! an app asks to share the screen) cannot reach a compositor. Each instance directory
//! in `$XDG_RUNTIME_DIR/hypr` holds `hyprland.lock`: its PID on line 1, its Wayland
//! socket on line 2. The real session is the running instance whose process is not
//! itself a Wayland client (a nested copy has `WAYLAND_DISPLAY` in its environment);
//! with none of those, the newest running one.

use std::ffi::OsStr;
use std::fs;
use std::io;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::time::SystemTime;

use serde::Serialize;

use crate::paths::Paths;

/// The live session: the values to put in `WAYLAND_DISPLAY` and
/// `HYPRLAND_INSTANCE_SIGNATURE`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Session {
    /// The instance directory's name (`HYPRLAND_INSTANCE_SIGNATURE`).
    pub signature: String,
    /// The Wayland socket's name (`WAYLAND_DISPLAY`).
    pub wayland_display: String,
    /// The compositor's PID.
    pub pid: i32,
    /// True when no running instance was a top-level compositor and this one (the
    /// newest running) is itself a Wayland client, i.e. nested.
    pub nested: bool,
}

impl Session {
    /// The two variables, in the order the shell version exported them.
    pub fn env(&self) -> [(&'static str, &str); 2] {
        [
            ("WAYLAND_DISPLAY", &self.wayland_display),
            ("HYPRLAND_INSTANCE_SIGNATURE", &self.signature),
        ]
    }
}

/// Environment to recover in a local persistent shell. This is read-only: it never
/// imports into systemd, contacts the compositor, or changes a running process.
/// Respect SSH, an explicitly selected X display, and any usable Wayland socket,
/// including a nested compositor. Never fall back to a nested test session.
pub fn shell_env(paths: &Paths, get: impl Fn(&str) -> Option<String>) -> Vec<(String, String)> {
    let present = |key: &str| get(key).filter(|value| !value.is_empty());
    if present("SSH_CONNECTION").is_some()
        || present("SSH_CLIENT").is_some()
        || present("SSH_TTY").is_some()
    {
        return Vec::new();
    }
    let wayland = present("WAYLAND_DISPLAY");
    if wayland
        .as_deref()
        .is_some_and(|name| is_socket(&paths.in_runtime(name)))
        || (wayland.is_none() && present("DISPLAY").is_some())
    {
        return Vec::new();
    }
    let Some(session) = discover(paths).session.filter(|session| !session.nested) else {
        return Vec::new();
    };
    let mut env: Vec<_> = session
        .env()
        .into_iter()
        .map(|(key, value)| (key.to_owned(), value.to_owned()))
        .collect();
    // Drop the old session's X display/auth path if the new one has none.
    env.push(("DISPLAY".to_owned(), String::new()));
    env.push(("XAUTHORITY".to_owned(), String::new()));
    for (key, value) in xwayland_env(Path::new("/proc"), session.pid) {
        if let Some(entry) = env.iter_mut().find(|(name, _)| *name == key) {
            entry.1 = value;
        }
    }
    // The line-oriented shell reader never evaluates these values. Reject line
    // breaks as well so a malformed lock file cannot add another assignment.
    env.retain(|(_, value)| !value.contains(['\n', '\r']));
    env
}

/// Xwayland is a child of the selected compositor. Read its own display argument
/// rather than guessing :0 or copying another session's activation environment.
fn xwayland_env(proc: &Path, compositor: i32) -> Vec<(String, String)> {
    let children = proc.join(format!("{compositor}/task/{compositor}/children"));
    let Ok(children) = fs::read_to_string(children) else {
        return Vec::new();
    };
    for pid in children
        .split_whitespace()
        .filter_map(|p| p.parse::<u32>().ok())
    {
        let Ok(raw) = fs::read(proc.join(pid.to_string()).join("cmdline")) else {
            continue;
        };
        let argv: Vec<_> = raw.split(|b| *b == 0).filter(|b| !b.is_empty()).collect();
        if argv
            .first()
            .and_then(|arg| arg.rsplit(|b| *b == b'/').next())
            != Some(&b"Xwayland"[..])
        {
            continue;
        }
        let display = argv.iter().skip(1).find_map(|arg| {
            let value = std::str::from_utf8(arg).ok()?;
            let number = value.strip_prefix(':')?;
            (!number.is_empty() && number.bytes().all(|b| b.is_ascii_digit())).then_some(value)
        });
        let Some(display) = display else { continue };
        let mut env = vec![("DISPLAY".to_owned(), display.to_owned())];
        if let Some(auth) = argv.windows(2).find_map(|pair| {
            (pair[0] == b"-auth")
                .then(|| std::str::from_utf8(pair[1]).ok())
                .flatten()
        }) && Path::new(auth).is_absolute()
            && !auth.contains(['\n', '\r'])
        {
            env.push(("XAUTHORITY".to_owned(), auth.to_owned()));
        }
        return env;
    }
    Vec::new()
}

/// One instance directory under `$XDG_RUNTIME_DIR/hypr`, newest first.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Candidate {
    pub signature: String,
    /// Line 1 of `hyprland.lock`, when it is a positive integer.
    pub pid: Option<i32>,
    /// Line 2 of `hyprland.lock`.
    pub wayland_display: Option<String>,
    /// The PID is alive (`kill -0` succeeds).
    pub running: bool,
    /// `$XDG_RUNTIME_DIR/<wayland_display>` is a socket.
    pub socket: bool,
    /// The process has `WAYLAND_DISPLAY` in its environment (a nested compositor).
    /// An unreadable environment counts as not nested, as in the shell version.
    pub nested: bool,
}

impl Candidate {
    /// Running, with its Wayland socket present: a session that can be used.
    pub fn usable(&self) -> bool {
        self.running && self.socket && self.pid.is_some() && self.wayland_display.is_some()
    }
}

/// The result of a scan: the pick, plus every instance directory that was looked at.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Discovery {
    pub session: Option<Session>,
    pub candidates: Vec<Candidate>,
    pub runtime_dir: PathBuf,
}

/// Scans `$XDG_RUNTIME_DIR/hypr/*/hyprland.lock` and picks the live session.
pub fn discover(paths: &Paths) -> Discovery {
    let candidates: Vec<Candidate> = instance_dirs(&paths.hypr_dir())
        .into_iter()
        .filter_map(|dir| candidate(paths, &dir))
        .collect();
    let pick = candidates
        .iter()
        .find(|c| c.usable() && !c.nested)
        .or_else(|| candidates.iter().find(|c| c.usable()));
    let session = pick.map(|c| Session {
        signature: c.signature.clone(),
        wayland_display: c.wayland_display.clone().unwrap_or_default(),
        pid: c.pid.unwrap_or_default(),
        nested: c.nested,
    });
    Discovery {
        session,
        candidates,
        runtime_dir: paths.runtime_dir.clone(),
    }
}

/// Instance directories, newest modification time first (ties by name), as `ls -td
/// hypr/*/` lists them. Hidden entries are skipped like the glob skips them.
pub(crate) fn instance_dirs(hypr: &Path) -> Vec<PathBuf> {
    let Ok(rd) = fs::read_dir(hypr) else {
        return Vec::new();
    };
    let mut dirs: Vec<(SystemTime, PathBuf)> = rd
        .filter_map(Result::ok)
        .filter(|e| !e.file_name().as_encoded_bytes().starts_with(b"."))
        .filter_map(|e| {
            let path = e.path();
            let md = fs::metadata(&path).ok()?; // follows symlinks, like the glob's `*/`
            md.is_dir()
                .then(|| (md.modified().unwrap_or(SystemTime::UNIX_EPOCH), path))
        })
        .collect();
    dirs.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    dirs.into_iter().map(|(_, p)| p).collect()
}

/// An instance directory's `hyprland.lock`: its PID (line 1, when a positive integer) and
/// its Wayland socket (line 2); `None` when the file is missing or unreadable.
pub(crate) fn read_lock(dir: &Path) -> Option<(Option<i32>, Option<String>)> {
    let text = fs::read_to_string(dir.join("hyprland.lock")).ok()?;
    let mut lines = text.lines().map(str::trim);
    let pid = lines
        .next()
        .and_then(|l| l.parse::<i32>().ok())
        .filter(|p| *p > 0);
    let wayland_display = lines.next().filter(|l| !l.is_empty()).map(str::to_owned);
    Some((pid, wayland_display))
}

fn candidate(paths: &Paths, dir: &Path) -> Option<Candidate> {
    let signature = dir.file_name()?.to_string_lossy().into_owned();
    // an unreadable or missing lock file: not a candidate at all
    let (pid, wayland_display) = read_lock(dir)?;
    let running = pid.is_some_and(pid_alive);
    let socket = wayland_display
        .as_deref()
        .is_some_and(|wl| is_socket(&paths.in_runtime(wl)));
    let nested = running && pid.is_some_and(|p| environ_has(p, "WAYLAND_DISPLAY"));
    Some(Candidate {
        signature,
        pid,
        wayland_display,
        running,
        socket,
        nested,
    })
}

fn is_socket(p: &Path) -> bool {
    fs::metadata(p).is_ok_and(|m| m.file_type().is_socket())
}

/// `kill -0 <pid>`: the process exists and we may signal it.
pub fn pid_alive(pid: i32) -> bool {
    rustix::process::Pid::from_raw(pid)
        .is_some_and(|p| rustix::process::test_kill_process(p).is_ok())
}

/// One variable from `/proc/<pid>/environ`; `None` when unset or unreadable.
pub fn environ_var(pid: i32, key: &str) -> Option<String> {
    let raw = fs::read(format!("/proc/{pid}/environ")).ok()?;
    let prefix = [key.as_bytes(), b"="].concat();
    raw.split(|b| *b == 0)
        .find_map(|kv| kv.strip_prefix(prefix.as_slice()))
        .map(|v| String::from_utf8_lossy(v).into_owned())
}

fn environ_has(pid: i32, key: &str) -> bool {
    environ_var(pid, key).is_some()
}

/// `dbus-update-activation-environment --systemd WAYLAND_DISPLAY
/// HYPRLAND_INSTANCE_SIGNATURE`, with the session's values.
pub fn import(session: &Session) -> io::Result<ExitStatus> {
    Command::new("dbus-update-activation-environment")
        .args([
            "--systemd",
            "WAYLAND_DISPLAY",
            "HYPRLAND_INSTANCE_SIGNATURE",
        ])
        .envs(session.env())
        .status()
}

/// Replaces this process with `cmd`, the session's values in its environment (or the
/// environment unchanged when there is no session). Returns only on failure.
pub fn exec<S: AsRef<OsStr>>(session: Option<&Session>, cmd: &[S]) -> io::Error {
    let Some((prog, args)) = cmd.split_first() else {
        return io::Error::new(io::ErrorKind::InvalidInput, "no command to exec");
    };
    let mut c = Command::new(prog);
    c.args(args);
    if let Some(s) = session {
        c.envs(s.env());
    }
    c.exec()
}

/// What `adopt` found and did about VECTOR's daemon.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Adopt {
    /// VECTOR's daemon (`python -m holo.app`), when one is running.
    pub vector_pid: Option<i32>,
    /// The `HYPRLAND_INSTANCE_SIGNATURE` in its environment.
    pub vector_signature: Option<String>,
    /// It belonged to another session and was stopped.
    pub stopped: bool,
}

/// At login: stop VECTOR's daemon if it belongs to another session (it starts again
/// on demand, in this one). `bromigos-holo stop now` first; `kill <pid>` if that fails.
pub fn adopt(paths: &Paths, session: &Session) -> Adopt {
    let Some(pid) = find_vector_daemon(Path::new("/proc")) else {
        return Adopt {
            vector_pid: None,
            vector_signature: None,
            stopped: false,
        };
    };
    let theirs = environ_var(pid, "HYPRLAND_INSTANCE_SIGNATURE");
    let stopped = theirs.as_deref() != Some(session.signature.as_str());
    if stopped {
        crate::log(
            "bromigos-session",
            &format!("VECTOR's daemon ({pid}) belongs to another session; stopping it"),
        );
        let ok = Command::new(&paths.holo_bin)
            .args(["stop", "now"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|s| s.success());
        if !ok && let Some(p) = rustix::process::Pid::from_raw(pid) {
            let _ = rustix::process::kill_process(p, rustix::process::Signal::TERM);
        }
    }
    Adopt {
        vector_pid: Some(pid),
        vector_signature: theirs,
        stopped,
    }
}

/// The lowest PID whose command line is `python… -m holo.app …`. Matches the argument
/// vector, not a substring of the joined command line, so a shell or editor that merely
/// mentions `holo.app` never matches.
pub fn find_vector_daemon(proc: &Path) -> Option<i32> {
    let me = std::process::id() as i32;
    let mut pids: Vec<i32> = fs::read_dir(proc)
        .ok()?
        .filter_map(Result::ok)
        .filter_map(|e| e.file_name().to_str()?.parse::<i32>().ok())
        .filter(|p| *p != me)
        .collect();
    pids.sort_unstable();
    pids.into_iter().find(|pid| {
        fs::read(proc.join(pid.to_string()).join("cmdline"))
            .is_ok_and(|raw| is_vector_cmdline(&raw))
    })
}

fn is_vector_cmdline(raw: &[u8]) -> bool {
    let argv: Vec<&[u8]> = raw.split(|b| *b == 0).filter(|a| !a.is_empty()).collect();
    let Some(argv0) = argv.first() else {
        return false;
    };
    let base = argv0.rsplit(|b| *b == b'/').next().unwrap_or(argv0);
    base.starts_with(b"python") && argv.windows(2).any(|w| w == [&b"-m"[..], b"holo.app"])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xwayland_display_belongs_to_the_selected_compositor() {
        let proc = tempfile::tempdir().unwrap();
        fs::create_dir_all(proc.path().join("12/task/12")).unwrap();
        fs::write(proc.path().join("12/task/12/children"), "30 31 32").unwrap();
        for (pid, argv) in [
            ("30", &b"sh\0-c\0Xwayland :98\0"[..]),
            (
                "31",
                &b"/usr/bin/Xwayland\0:7\0-rootless\0-auth\0/tmp/auth file\0"[..],
            ),
            ("32", &b"Xwayland\0:9\0"[..]),
        ] {
            fs::create_dir(proc.path().join(pid)).unwrap();
            fs::write(proc.path().join(pid).join("cmdline"), argv).unwrap();
        }
        assert_eq!(
            xwayland_env(proc.path(), 12),
            vec![
                ("DISPLAY".into(), ":7".into()),
                ("XAUTHORITY".into(), "/tmp/auth file".into()),
            ]
        );
        assert!(xwayland_env(proc.path(), 13).is_empty());
        fs::write(proc.path().join("31/cmdline"), b"Xwayland\0:bad\0").unwrap();
        assert_eq!(
            xwayland_env(proc.path(), 12),
            vec![("DISPLAY".into(), ":9".into())]
        );
    }

    #[test]
    fn vector_cmdline() {
        assert!(is_vector_cmdline(b"/usr/bin/python3\0-m\0holo.app\0"));
        assert!(is_vector_cmdline(b"/x/venv/bin/python\0-m\0holo.app\0"));
        assert!(!is_vector_cmdline(b"bash\0-c\0python -m holo.app\0"));
        assert!(!is_vector_cmdline(b"/usr/bin/python3\0-m\0live.app\0"));
        assert!(!is_vector_cmdline(b""));
    }
}
