//! Session discovery against a fake `$XDG_RUNTIME_DIR`, with real (test) processes
//! standing in for compositors.

use std::fs;
use std::os::unix::net::UnixListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::time::{Duration, SystemTime};

use bromigos_core::paths::Paths;
use bromigos_core::session::{self, discover};

/// A `sleep` standing in for a compositor; killed (by its own PID) on drop.
struct Proc(Child);

impl Proc {
    fn spawn(wayland_client: bool) -> Proc {
        let mut c = Command::new("sleep");
        c.arg("60");
        if wayland_client {
            c.env("WAYLAND_DISPLAY", "wayland-outer");
        } else {
            c.env_remove("WAYLAND_DISPLAY");
        }
        let child = c.spawn().unwrap();
        // spawn() returns once the child exists, before it has exec'd `sleep`: until
        // then /proc/<pid>/environ is still this test's own environment, so a check
        // could miss the WAYLAND_DISPLAY just set (CI, 2026-10-08). Wait for the exec.
        let cmdline = format!("/proc/{}/cmdline", child.id());
        for _ in 0..400 {
            if std::fs::read(&cmdline).is_ok_and(|b| b.starts_with(b"sleep\0")) {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
        Proc(child)
    }
    fn pid(&self) -> i32 {
        self.0.id() as i32
    }
}

impl Drop for Proc {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// A PID that is certainly gone: spawned, exited and reaped.
fn dead_pid() -> i32 {
    let mut c = Command::new("true").spawn().unwrap();
    let pid = c.id() as i32;
    c.wait().unwrap();
    pid
}

struct Rt {
    dir: tempfile::TempDir,
    sockets: Vec<UnixListener>,
}

impl Rt {
    fn new() -> Rt {
        let dir = tempfile::tempdir().unwrap();
        fs::create_dir(dir.path().join("hypr")).unwrap();
        Rt {
            dir,
            sockets: Vec::new(),
        }
    }
    fn paths(&self) -> Paths {
        let rt = self.dir.path().to_path_buf();
        Paths::from_lookup(move |k| match k {
            "XDG_RUNTIME_DIR" => Some(rt.clone()),
            "HOME" => Some(PathBuf::from("/nonexistent")),
            _ => None,
        })
    }
    fn socket(&mut self, wl: &str) {
        self.sockets
            .push(UnixListener::bind(self.dir.path().join(wl)).unwrap());
    }
    /// An instance dir with a lock file; `age` seconds old.
    fn instance(&self, sig: &str, lock: Option<&str>, age: u64) -> PathBuf {
        let d = self.dir.path().join("hypr").join(sig);
        fs::create_dir(&d).unwrap();
        if let Some(text) = lock {
            fs::write(d.join("hyprland.lock"), text).unwrap();
        }
        set_age(&d, age);
        d
    }
}

fn set_age(p: &Path, secs: u64) {
    let t = SystemTime::now() - Duration::from_secs(secs);
    fs::File::open(p).unwrap().set_modified(t).unwrap();
}

#[test]
fn real_session_beats_a_newer_nested_one() {
    let real = Proc::spawn(false);
    let nested = Proc::spawn(true);
    let mut rt = Rt::new();
    rt.socket("wayland-1");
    rt.socket("wayland-2");
    rt.instance("real", Some(&format!("{}\nwayland-1\n", real.pid())), 100);
    rt.instance(
        "nested",
        Some(&format!("{}\nwayland-2\n", nested.pid())),
        10,
    );
    let d = discover(&rt.paths());
    let s = d.session.unwrap();
    assert_eq!(s.signature, "real");
    assert_eq!(s.wayland_display, "wayland-1");
    assert_eq!(s.pid, real.pid());
    assert!(!s.nested);
    // both looked at, newest first
    assert_eq!(
        d.candidates
            .iter()
            .map(|c| c.signature.as_str())
            .collect::<Vec<_>>(),
        ["nested", "real"]
    );
    assert!(d.candidates[0].nested && d.candidates[0].usable());
}

#[test]
fn only_nested_falls_back_to_the_newest_running() {
    let a = Proc::spawn(true);
    let b = Proc::spawn(true);
    let mut rt = Rt::new();
    rt.socket("wayland-1");
    rt.socket("wayland-2");
    rt.instance("older", Some(&format!("{}\nwayland-1\n", a.pid())), 100);
    rt.instance("newer", Some(&format!("{}\nwayland-2\n", b.pid())), 10);
    let s = discover(&rt.paths()).session.unwrap();
    assert_eq!(s.signature, "newer");
    assert!(s.nested);
}

#[test]
fn newest_real_session_wins() {
    let a = Proc::spawn(false);
    let b = Proc::spawn(false);
    let mut rt = Rt::new();
    rt.socket("wayland-1");
    rt.socket("wayland-2");
    rt.instance("old", Some(&format!("{}\nwayland-1\n", a.pid())), 300);
    rt.instance("new", Some(&format!("{}\nwayland-2\n", b.pid())), 5);
    assert_eq!(discover(&rt.paths()).session.unwrap().signature, "new");
}

#[test]
fn shell_recovery_finds_desktop_but_preserves_explicit_and_remote_displays() {
    let desktop = Proc::spawn(false);
    let mut rt = Rt::new();
    rt.socket("wayland-desktop");
    rt.socket("wayland-explicit");
    rt.instance(
        "desktop",
        Some(&format!("{}\nwayland-desktop\n", desktop.pid())),
        1,
    );
    let recover = |env: &[(&str, &str)]| {
        session::shell_env(&rt.paths(), |key| {
            env.iter()
                .find(|(name, _)| *name == key)
                .map(|(_, value)| value.to_string())
        })
    };
    let expected = vec![
        ("WAYLAND_DISPLAY".into(), "wayland-desktop".into()),
        ("HYPRLAND_INSTANCE_SIGNATURE".into(), "desktop".into()),
        ("DISPLAY".into(), String::new()),
        ("XAUTHORITY".into(), String::new()),
    ];
    assert_eq!(recover(&[]), expected);
    assert_eq!(
        recover(&[("WAYLAND_DISPLAY", "wayland-gone"), ("DISPLAY", ":88")]),
        expected
    );
    assert!(recover(&[("WAYLAND_DISPLAY", "wayland-explicit")]).is_empty());
    assert!(recover(&[("DISPLAY", ":88")]).is_empty());
    for key in ["SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"] {
        assert!(recover(&[(key, "remote")]).is_empty());
    }
}

#[test]
fn shell_recovery_does_not_adopt_a_lone_nested_compositor() {
    let nested = Proc::spawn(true);
    let mut rt = Rt::new();
    rt.socket("wayland-test");
    rt.instance(
        "nested",
        Some(&format!("{}\nwayland-test\n", nested.pid())),
        1,
    );
    assert!(session::shell_env(&rt.paths(), |_| None).is_empty());
    assert!(session::shell_env(&Rt::new().paths(), |_| None).is_empty());
}

#[test]
fn stale_and_dead_instances_are_skipped() {
    let alive = Proc::spawn(false);
    let mut rt = Rt::new();
    rt.socket("wayland-1");
    // newest first: dead PID, then a live PID whose socket is gone, then junk
    rt.instance("dead", Some(&format!("{}\nwayland-1\n", dead_pid())), 1);
    rt.instance("stale", Some(&format!("{}\nwayland-9\n", alive.pid())), 2);
    rt.instance("no-lock", None, 3);
    rt.instance("one-line", Some(&format!("{}\n", alive.pid())), 4);
    rt.instance("garbage", Some("not-a-pid\nwayland-1\n"), 5);
    rt.instance("pid-zero", Some("0\nwayland-1\n"), 6);
    let d = discover(&rt.paths());
    assert_eq!(d.session, None);
    let by = |s: &str| d.candidates.iter().find(|c| c.signature == s).unwrap();
    assert!(!by("dead").running && by("dead").socket);
    assert!(by("stale").running && !by("stale").socket);
    assert!(by("one-line").wayland_display.is_none());
    assert!(by("garbage").pid.is_none());
    assert!(by("pid-zero").pid.is_none());
    assert!(d.candidates.iter().all(|c| c.signature != "no-lock"));

    // a live one older than all of them is still found
    rt.instance("live", Some(&format!("{}\nwayland-1\n", alive.pid())), 50);
    assert_eq!(discover(&rt.paths()).session.unwrap().signature, "live");
}

#[test]
fn no_hypr_dir_at_all() {
    let dir = tempfile::tempdir().unwrap();
    let rt = dir.path().to_path_buf();
    let p = Paths::from_lookup(move |k| (k == "XDG_RUNTIME_DIR").then(|| rt.clone()));
    let d = discover(&p);
    assert!(d.session.is_none() && d.candidates.is_empty());
}

#[test]
fn environ_lookup() {
    let p = Proc::spawn(true);
    // the child may not have exec'd yet; wait for its environ to show
    for _ in 0..100 {
        if session::environ_var(p.pid(), "WAYLAND_DISPLAY").is_some() {
            break;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(
        session::environ_var(p.pid(), "WAYLAND_DISPLAY").as_deref(),
        Some("wayland-outer")
    );
    assert!(session::pid_alive(p.pid()));
    assert!(!session::pid_alive(dead_pid()));
}
