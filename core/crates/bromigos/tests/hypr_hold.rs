//! `bromigos session hold` and `release` end to end (core/src/hypr_hold.rs), as a user (the
//! caller's own compositors), in a sandbox: a temp runtime dir with stand-in compositors
//! (a script named Hyprland, so its process is called that, with an instance directory and
//! lock) and a stand-in hyprctl and `Hyprland --verify-config` on PATH. Nothing here can
//! reach a real Hyprland: every call carries the sandbox's runtime dir and signatures.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::time::{Duration, Instant};

use serde_json::Value;

/// Held while a script is written and while a child is spawned: a script written while
/// another test thread forks can stay open for writing in that child for a moment, and
/// exec then fails with ETXTBSY (as tests/cli.rs).
static FORK: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn fork_guard() -> std::sync::MutexGuard<'static, ()> {
    FORK.lock().unwrap_or_else(|e| e.into_inner())
}

const HYPRCTL: &str = r#"#!/bin/sh
# the stand-in hyprctl: state per instance in $XDG_RUNTIME_DIR/hypr/$SIG/
d="$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE"
[ -d "$d" ] && [ ! -e "$d/dead" ] || { echo "no instance" >&2; exit 1; }
echo "$*" >> "$d/calls"
off=$(cat "$d/off" 2>/dev/null || echo false)
case "$1" in
  getoption) echo "{\"option\": \"misc:disable_autoreload\", \"bool\": $off, \"set\": true }" ;;
  eval) case "$2" in *"disable_autoreload = true"*) echo true > "$d/off" ;; *"disable_autoreload = false"*) echo false > "$d/off" ;; esac; echo ok ;;
  reload) cat "$d/config-off" 2>/dev/null > "$d/off" || echo false > "$d/off"; echo x >> "$d/reloads"; echo ok ;;
  configerrors) if [ -f "$d/errors" ]; then printf '["%s"]\n' "$(cat "$d/errors")"; else echo '[""]'; fi ;;
  *) echo ok ;;
esac
"#;

/// The compositor (no arguments but -c: runs until killed) and its verify-config.
const HYPRLAND: &str = r#"#!/bin/sh
if [ "$1" = --verify-config ]; then
  echo "$*" >> "$VERIFY_LOG"
  [ "$2" = -c ] && grep -q BROKEN "$3" && { echo "error: line 3: attempt to call a nil value (field 'vmtest')"; exit 1; }
  echo "config ok"; exit 0
fi
while :; do sleep 1; done
"#;

struct Sandbox {
    dir: tempfile::TempDir,
    comps: Vec<Child>,
}

impl Drop for Sandbox {
    fn drop(&mut self) {
        for c in &mut self.comps {
            let _ = c.kill();
            let _ = c.wait();
        }
    }
}

impl Sandbox {
    fn new() -> Sandbox {
        let s = Sandbox {
            dir: tempfile::tempdir().unwrap(),
            comps: Vec::new(),
        };
        for d in ["run/hypr", "bin", "home/.config/hypr", "comp"] {
            fs::create_dir_all(s.p(d)).unwrap();
        }
        s.exe("bin/hyprctl", HYPRCTL);
        s.exe("bin/Hyprland", HYPRLAND);
        s.exe("comp/Hyprland", HYPRLAND);
        fs::write(s.p("home/.config/hypr/hyprland.lua"), "-- fine\n").unwrap();
        s
    }
    fn p(&self, rel: &str) -> PathBuf {
        self.dir.path().join(rel)
    }
    fn exe(&self, rel: &str, body: &str) {
        let _g = fork_guard();
        fs::write(self.p(rel), body).unwrap();
        fs::set_permissions(self.p(rel), fs::Permissions::from_mode(0o755)).unwrap();
    }
    fn path_var(&self) -> String {
        format!("{}:/usr/bin:/bin", self.p("bin").display())
    }
    /// A stand-in compositor with its instance directory; `config`: its -c.
    fn compositor(&mut self, sig: &str, config: Option<&Path>) -> i32 {
        let mut c = Command::new(self.p("comp/Hyprland"));
        if let Some(cfg) = config {
            c.arg("-c").arg(cfg);
        }
        let _g = fork_guard();
        let child = c
            .env_clear()
            .env("HOME", self.p("home"))
            .env("PATH", self.path_var())
            .env("VERIFY_LOG", self.p("verify.log"))
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let pid = child.id() as i32;
        self.comps.push(child);
        let d = self.inst(sig);
        fs::create_dir_all(&d).unwrap();
        fs::write(d.join("hyprland.lock"), format!("{pid}\nwayland-9\n")).unwrap();
        fs::write(d.join(".socket.sock"), "").unwrap();
        // its process is named Hyprland once the script runs
        let t0 = Instant::now();
        while fs::read_to_string(format!("/proc/{pid}/comm"))
            .unwrap_or_default()
            .trim()
            != "Hyprland"
        {
            assert!(
                t0.elapsed() < Duration::from_secs(5),
                "the stand-in compositor didn't start"
            );
            std::thread::sleep(Duration::from_millis(20));
        }
        pid
    }
    fn inst(&self, sig: &str) -> PathBuf {
        self.p("run/hypr").join(sig)
    }
    fn off(&self, sig: &str) -> String {
        fs::read_to_string(self.inst(sig).join("off"))
            .unwrap_or_else(|_| "false".into())
            .trim()
            .to_owned()
    }
    fn reloads(&self, sig: &str) -> usize {
        fs::read_to_string(self.inst(sig).join("reloads"))
            .unwrap_or_default()
            .lines()
            .count()
    }
    /// The holds recorded (the lock file beside them isn't one).
    fn records(&self) -> Vec<PathBuf> {
        fs::read_dir(self.p("run/bromigos-hypr-hold"))
            .map(|rd| {
                rd.flatten()
                    .map(|e| e.path())
                    .filter(|p| p.extension().is_some_and(|x| x == "json"))
                    .collect()
            })
            .unwrap_or_default()
    }
    fn cmd(&self, args: &[&str]) -> Command {
        let mut c = Command::new(env!("CARGO_BIN_EXE_bromigos"));
        c.args(args)
            .env_clear()
            .env("HOME", self.p("home"))
            .env("XDG_RUNTIME_DIR", self.p("run"))
            .env("PATH", self.path_var())
            .stdin(Stdio::null());
        c
    }
    fn run(&self, args: &[&str]) -> Output {
        let child = {
            let _g = fork_guard();
            self.cmd(args)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .unwrap()
        };
        child.wait_with_output().unwrap()
    }
    fn json(&self, args: &[&str]) -> Value {
        let o = self.run(args);
        serde_json::from_slice(&o.stdout).unwrap_or_else(|e| {
            panic!(
                "{e}: {} {}",
                String::from_utf8_lossy(&o.stdout),
                String::from_utf8_lossy(&o.stderr)
            )
        })
    }
}

fn text(o: &Output) -> String {
    format!(
        "{}{}",
        String::from_utf8_lossy(&o.stdout),
        String::from_utf8_lossy(&o.stderr)
    )
}

#[test]
fn hold_then_release_reloads_once_and_puts_auto_reload_back() {
    let mut s = Sandbox::new();
    let cfg = s.p("home/.config/hypr/hyprland.lua");
    let pid = s.compositor("aaa_1_1", Some(&cfg));
    let v = s.json(&["session", "hold", "--json"]);
    let held = v["held"].as_array().unwrap();
    assert_eq!(held.len(), 1, "{v}");
    assert_eq!(held[0]["pid"], pid);
    assert_eq!(held[0]["ok"], true);
    assert_eq!(held[0]["was_off"], false);
    assert_eq!(s.off("aaa_1_1"), "true", "auto-reload off while held");
    assert_eq!(s.records().len(), 1);
    assert_eq!(s.reloads("aaa_1_1"), 0);

    // the files change; then the release: verified with the compositor's own -c, one reload
    let o = s.run(&["session", "release"]);
    assert!(o.status.success(), "{}", text(&o));
    assert!(
        text(&o).contains("config ok, reloaded once; auto-reload back on"),
        "{}",
        text(&o)
    );
    assert_eq!(s.reloads("aaa_1_1"), 1);
    assert_eq!(s.off("aaa_1_1"), "false");
    assert!(s.records().is_empty());
    let verify = fs::read_to_string(s.p("verify.log")).unwrap();
    assert_eq!(
        verify.trim(),
        format!("--verify-config -c {}", cfg.display())
    );
    // nothing held now: release does nothing (and says so)
    let o = s.run(&["session", "release"]);
    assert!(text(&o).contains("nothing held"));
    assert_eq!(s.reloads("aaa_1_1"), 1);
}

#[test]
fn a_config_that_doesnt_verify_isnt_reloaded() {
    let mut s = Sandbox::new();
    s.compositor("bbb_1_1", None); // its config by Hyprland's lookup: HOME/.config/hypr
    assert!(s.run(&["session", "hold"]).status.success());
    fs::write(s.p("home/.config/hypr/hyprland.lua"), "-- BROKEN\n").unwrap();
    let o = s.run(&["session", "release"]);
    assert_eq!(o.status.code(), Some(1), "{}", text(&o));
    assert!(
        text(&o).contains("doesn't verify, so it isn't reloaded"),
        "{}",
        text(&o)
    );
    assert!(text(&o).contains("nil value"), "{}", text(&o));
    assert_eq!(
        s.reloads("bbb_1_1"),
        0,
        "Hyprland keeps running what it ran"
    );
    assert_eq!(s.off("bbb_1_1"), "false", "auto-reload is back on anyway");
    // under pacman the hook never fails the transaction
    assert!(s.run(&["session", "hold"]).status.success());
    let o = s.run(&["session", "release", "--pacman"]);
    assert_eq!(o.status.code(), Some(0), "{}", text(&o));
}

#[test]
fn the_users_own_auto_reload_off_stays_off() {
    let mut s = Sandbox::new();
    s.compositor("ccc_1_1", None);
    fs::write(s.inst("ccc_1_1").join("off"), "true\n").unwrap();
    fs::write(s.inst("ccc_1_1").join("config-off"), "true\n").unwrap();
    let v = s.json(&["session", "hold", "--json"]);
    assert_eq!(v["held"][0]["was_off"], true);
    // a second hold before the release keeps the first one's value
    let v = s.json(&["session", "hold", "--json"]);
    assert_eq!(v["held"][0]["was_off"], true);
    let o = s.run(&["session", "release"]);
    assert!(
        text(&o).contains("auto-reload stays off (yours)"),
        "{}",
        text(&o)
    );
    assert_eq!(s.off("ccc_1_1"), "true");
}

#[test]
fn every_compositor_and_only_live_ones() {
    let mut s = Sandbox::new();
    s.compositor("ddd_1_1", None);
    s.compositor("ddd_2_2", None);
    // a lock naming a dead process, and one naming a process that isn't Hyprland
    let dead = s.inst("ddd_dead");
    fs::create_dir_all(&dead).unwrap();
    fs::write(dead.join("hyprland.lock"), "999999999\nwayland-8\n").unwrap();
    fs::write(dead.join(".socket.sock"), "").unwrap();
    let other = s.inst("ddd_other");
    fs::create_dir_all(&other).unwrap();
    fs::write(
        other.join("hyprland.lock"),
        format!("{}\nwayland-7\n", std::process::id()),
    )
    .unwrap();
    fs::write(other.join(".socket.sock"), "").unwrap();
    let v = s.json(&["session", "hold", "--json"]);
    let mut sigs: Vec<&str> = v["held"]
        .as_array()
        .unwrap()
        .iter()
        .map(|h| h["signature"].as_str().unwrap())
        .collect();
    sigs.sort();
    assert_eq!(sigs, ["ddd_1_1", "ddd_2_2"], "{v}");
    assert!(
        !other.join("calls").exists(),
        "nothing was asked of a process that isn't Hyprland"
    );
    // one compositor goes away while held: its record goes, the other is released
    let gone = s.comps.remove(0);
    let mut gone = gone;
    gone.kill().unwrap();
    gone.wait().unwrap();
    let v = s.json(&["session", "release", "--json"]);
    let rel = v["released"].as_array().unwrap();
    assert_eq!(rel.len(), 1, "{v}");
    assert_eq!(rel[0]["signature"], "ddd_2_2");
    assert!(
        s.records().is_empty(),
        "the gone compositor's record is dropped too"
    );
}

#[test]
fn under_pacman_release_reloads_what_wasnt_held_and_is_quiet_without_any() {
    let mut s = Sandbox::new();
    let o = s.run(&["session", "hold", "--pacman"]);
    assert!(o.status.success());
    assert_eq!(text(&o), "", "nothing to say when no Hyprland runs");
    let o = s.run(&["session", "release", "--pacman"]);
    assert_eq!(text(&o), "");
    s.compositor("eee_1_1", None);
    let o = s.run(&["session", "release"]);
    assert!(text(&o).contains("nothing held"));
    assert_eq!(s.reloads("eee_1_1"), 0);
    // the hook: it started mid-transaction, or the hold hook wasn't installed yet
    let o = s.run(&["session", "release", "--pacman"]);
    assert!(
        text(&o).contains("config ok, reloaded once"),
        "{}",
        text(&o)
    );
    assert_eq!(s.reloads("eee_1_1"), 1);
}

#[test]
fn a_transaction_that_dies_after_the_hold_is_released_by_the_watcher() {
    let mut s = Sandbox::new();
    s.compositor("fff_1_1", None);
    // pacman stands in as a shell that runs the hook and exits without the release hook
    let bromigos = env!("CARGO_BIN_EXE_bromigos");
    let mut sh = Command::new("/bin/sh");
    sh.arg("-c")
        .arg(format!(
            "'{bromigos}' session hold --pacman --json > '{}'; exit 0",
            s.p("hold.json").display()
        ))
        .env_clear()
        .env("HOME", s.p("home"))
        .env("XDG_RUNTIME_DIR", s.p("run"))
        .env("PATH", s.path_var());
    let st = {
        let _g = fork_guard();
        sh.spawn().unwrap()
    }
    .wait()
    .unwrap();
    assert!(st.success());
    let v: Value = serde_json::from_str(&fs::read_to_string(s.p("hold.json")).unwrap()).unwrap();
    assert_eq!(v["held"][0]["ok"], true, "{v}");
    assert!(v["watcher"]["after"].as_i64().is_some(), "{v}");
    // the "pacman" exited: the watcher releases within a moment
    let t0 = Instant::now();
    while !(s.records().is_empty() && s.reloads("fff_1_1") == 1) {
        assert!(
            t0.elapsed() < Duration::from_secs(10),
            "the watcher didn't release: {:?}",
            s.records()
        );
        std::thread::sleep(Duration::from_millis(50));
    }
    assert_eq!(s.off("fff_1_1"), "false");
}

#[test]
fn release_after_waits_for_the_process() {
    let mut s = Sandbox::new();
    s.compositor("ggg_1_1", None);
    assert!(s.run(&["session", "hold"]).status.success());
    let mut waiter = {
        let _g = fork_guard();
        Command::new("/bin/sleep").arg("1").spawn().unwrap()
    };
    let pid = waiter.id();
    let stat = fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
    let start = stat[stat.rfind(')').unwrap() + 2..]
        .split_whitespace()
        .nth(19)
        .unwrap()
        .to_owned();
    let t0 = Instant::now();
    let reaper = std::thread::spawn(move || waiter.wait());
    let o = s.run(&["session", "release", "--after", &format!("{pid}:{start}")]);
    assert!(
        t0.elapsed() >= Duration::from_millis(700),
        "it waited for the process"
    );
    assert!(o.status.success(), "{}", text(&o));
    assert_eq!(s.reloads("ggg_1_1"), 1);
    assert!(s.records().is_empty());
    reaper.join().unwrap().unwrap();
}
