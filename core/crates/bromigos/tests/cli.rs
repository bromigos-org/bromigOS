//! The `bromigos` binary end to end, in a sandbox: a temp HOME, runtime dir and PATH
//! holding fake scripts. Nothing here touches the real session, the real overrides
//! file or a real locker.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output};
use std::sync::Mutex;

use serde_json::Value;

/// Held while a script is written and while a child is spawned: a script written
/// while another test thread forks can stay open for writing in that child for a
/// moment, and exec then fails with ETXTBSY ("text file busy").
static FORK: Mutex<()> = Mutex::new(());

fn fork_guard() -> std::sync::MutexGuard<'static, ()> {
    FORK.lock().unwrap_or_else(|e| e.into_inner())
}

fn spawn(c: &mut Command) -> Child {
    let _g = fork_guard();
    c.stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap()
}

fn output(mut c: Command) -> Output {
    spawn(&mut c).wait_with_output().unwrap()
}

struct Sandbox {
    dir: tempfile::TempDir,
}

impl Sandbox {
    fn new() -> Sandbox {
        let s = Sandbox {
            dir: tempfile::tempdir().unwrap(),
        };
        for d in ["home", "run", "bin", "lib", "bin2", "sync"] {
            fs::create_dir(s.p(d)).unwrap();
        }
        s
    }
    fn p(&self, rel: &str) -> PathBuf {
        self.dir.path().join(rel)
    }
    /// An executable script in `dir`.
    fn script(&self, dir: &str, name: &str, body: &str) -> PathBuf {
        let p = self.p(dir).join(name);
        let _g = fork_guard();
        fs::write(&p, body).unwrap();
        fs::set_permissions(&p, fs::Permissions::from_mode(0o755)).unwrap();
        p
    }
    fn cmd(&self, args: &[&str]) -> Command {
        let mut c = Command::new(env!("CARGO_BIN_EXE_bromigos"));
        c.args(args)
            .env_clear()
            .env("HOME", self.p("home"))
            .env("BROMIGOS_FS_ROOT", self.p("home"))
            // pacman's sync databases: the sandbox's, never the machine's (a channel switch
            // removes [bromigos]'s)
            .env("BROMIGOS_PACMAN_SYNC", self.p("sync"))
            .env("XDG_RUNTIME_DIR", self.p("run"))
            .env("BROMIGOS_LIB_BIN", self.p("lib"))
            .env("BROMIGOS_SHARE_DIR", self.p("share"))
            // never the switcher's preview renderer (a PATH below may have /usr/bin)
            .env("BROMIGOS_NO_PREVIEWS", "1")
            .env(
                "PATH",
                format!("{}:{}", self.p("bin").display(), self.p("bin2").display()),
            );
        c
    }
    fn run(&self, args: &[&str]) -> Output {
        output(self.cmd(args))
    }
}

fn stdout(o: &Output) -> String {
    String::from_utf8_lossy(&o.stdout).into_owned()
}
fn stderr(o: &Output) -> String {
    String::from_utf8_lossy(&o.stderr).into_owned()
}

// ------------------------------------------------------------------ router

#[test]
fn routes_to_external_commands() {
    let s = Sandbox::new();
    s.script(
        "bin",
        "bromigos-toggle-nightlight",
        "#!/bin/sh\n# bromigos:summary=Night light on or off\n# bromigos:args=[on|off]\necho \"nightlight:$*\"\n",
    );
    s.script(
        "bin",
        "bromigos-setup",
        "#!/bin/sh\n# bromigos:summary=Setup\necho \"setup:$*\"\n",
    );
    s.script(
        "lib",
        "bromigos-toggle-wifi",
        "#!/bin/sh\necho \"lib wifi:$*\"\n",
    );
    s.script(
        "bin",
        "bromigos-toggle-wifi",
        "#!/bin/sh\necho \"path wifi:$*\"\n",
    );
    s.script("bin", "bromigos-anim-fade", "#!/bin/sh\necho \"fade:$*\"\n");

    let o = s.run(&["toggle", "nightlight", "on", "--now"]);
    assert_eq!(stdout(&o), "nightlight:on --now\n");
    assert_eq!(stdout(&s.run(&["setup", "now"])), "setup:now\n");
    assert_eq!(stdout(&s.run(&["setup"])), "setup:\n");
    // /usr/lib/bromigos/bin comes before PATH
    assert_eq!(stdout(&s.run(&["toggle", "wifi"])), "lib wifi:\n");
    // a built-in group's other words may route out; its own verbs never do
    assert_eq!(stdout(&s.run(&["anim", "fade", "2"])), "fade:2\n");
    // unknown
    let o = s.run(&["toggle", "nothing"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(stderr(&o).contains("unknown command: toggle"));
}

#[test]
fn exit_codes_pass_through() {
    let s = Sandbox::new();
    s.script("bin", "bromigos-fail", "#!/bin/sh\nexit 7\n");
    assert_eq!(s.run(&["fail"]).status.code(), Some(7));
}

#[test]
fn commands_lists_and_checks() {
    let s = Sandbox::new();
    s.script(
        "bin",
        "bromigos-toggle-nightlight",
        "#!/bin/sh\n# bromigos:summary=Night light\n# bromigos:args=[on|off]\n# bromigos:examples=bromigos toggle nightlight on\n",
    );
    s.script(
        "bin",
        "bromigos-setup-secret",
        "#!/bin/sh\n# bromigos:summary=Hidden one\n# bromigos:hidden=true\n",
    );
    s.script("bin", "bromigos-hw-razer", "#!/bin/sh\necho no header\n");
    s.script(
        "bin2",
        "bromigos-toggle-nightlight",
        "#!/bin/sh\n# bromigos:summary=Shadowed\n",
    );
    s.script(
        "bin",
        "bromigos-anim-on",
        "#!/bin/sh\n# bromigos:summary=Never runs\n",
    );
    s.script(
        "bin",
        "bromigos-status",
        "#!/bin/sh\n# bromigos:summary=Never runs either\n",
    );
    fs::write(s.p("bin").join("bromigos-not-executable"), "#!/bin/sh\n").unwrap();
    s.script("bin", "bromigos-Bad.py", "#!/bin/sh\n");

    let o = s.run(&["commands"]);
    let out = stdout(&o);
    assert!(out.contains("bromigos toggle nightlight [on|off]"), "{out}");
    assert!(out.contains("Night light"));
    assert!(out.contains("bromigos hw razer") && out.contains("(no summary)"));
    assert!(!out.contains("secret"), "hidden by default");
    assert!(!out.contains("not-executable") && !out.contains("Bad"));
    assert!(stdout(&s.run(&["commands", "--all"])).contains("bromigos setup secret"));

    let j: Value = serde_json::from_slice(&s.run(&["commands", "--json"]).stdout).unwrap();
    assert_eq!(j["schema"], 1);
    assert!(
        j["groups"]
            .as_array()
            .unwrap()
            .iter()
            .any(|g| g == "toggle")
    );
    assert!(
        j["builtins"]
            .as_array()
            .unwrap()
            .iter()
            .any(|b| b["name"] == "lock-run")
    );
    let c = j["commands"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["command"] == "bromigos-toggle-nightlight")
        .unwrap();
    assert_eq!(c["group"], "toggle");
    assert_eq!(c["name"], "nightlight");
    assert_eq!(c["route"], "bromigos toggle nightlight");
    assert_eq!(c["summary"], "Night light");
    assert_eq!(c["examples"][0], "bromigos toggle nightlight on");
    assert_eq!(c["hidden"], false);

    let o = s.run(&["commands", "--check", "--json"]);
    assert_eq!(o.status.code(), Some(1));
    let j: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(j["ok"], false);
    let has = |kind: &str, cmd: &str| {
        j["issues"]
            .as_array()
            .unwrap()
            .iter()
            .any(|i| i["kind"] == kind && i["command"] == cmd)
    };
    assert!(has("no-summary", "bromigos-hw-razer"));
    assert!(has("shadowed", "bromigos-toggle-nightlight"));
    assert!(has("builtin", "bromigos-anim-on"));
    assert!(has("builtin", "bromigos-status"));
    assert!(!has("no-summary", "bromigos-toggle-nightlight"));
}

#[test]
fn commands_check_clean() {
    let s = Sandbox::new();
    s.script(
        "bin",
        "bromigos-toggle-x",
        "#!/bin/sh\n# bromigos:summary=X\n",
    );
    let o = s.run(&["commands", "--check"]);
    assert_eq!(o.status.code(), Some(0));
    assert_eq!(stdout(&o), "ok: 1 external commands\n");
}

// ------------------------------------------------------------------ anim

#[test]
fn anim_switches_write_the_overrides_file() {
    let s = Sandbox::new();
    let ov = s.p("home/.config/bromigos/live/overrides.toml");
    let legacy = s.p("home/.local/state/bromigos-live/overrides.toml");
    fs::create_dir_all(legacy.parent().unwrap()).unwrap();
    fs::write(&legacy, "# old header\n\n[space]\nstars = false\n").unwrap();

    // read from the old location
    let j: Value = serde_json::from_slice(&s.run(&["anim", "--json"]).stdout).unwrap();
    let stars = j["animations"]
        .as_array()
        .unwrap()
        .iter()
        .find(|a| a["name"] == "stars")
        .unwrap();
    assert_eq!(stars["on"], false);
    assert_eq!(stars["overridden"], true);
    assert_eq!(stars["keys"][0]["section"], "space");

    let o = s.run(&["anim", "off", "rain", "ships"]);
    assert_eq!(
        stdout(&o),
        "off: rain, ships (applies within a few seconds)\n"
    );
    assert!(!legacy.exists(), "moved, nothing left behind");
    assert_eq!(
        fs::read_to_string(&ov).unwrap(),
        "# old header\n\n[space]\nstars = false\ntraffic = false\n\n[rain]\nenabled = false\n"
    );
    let list = stdout(&s.run(&["anim"]));
    assert!(list.contains("  rain         OFF * glyph rain"), "{list}");
    assert!(list.contains("  den          on    the den's"), "{list}");

    let o = s.run(&["anim", "on", "intercept"]);
    assert_eq!(stdout(&o), "on: intercept (applies within a few seconds)\n");
    assert!(
        fs::read_to_string(&ov)
            .unwrap()
            .contains("[events]\nintercept_on_login = true\nintercept_on_unlock = true\n")
    );

    assert_eq!(
        stdout(&s.run(&["anim", "reset", "rain"])),
        "back to the defaults: rain\n"
    );
    assert!(!fs::read_to_string(&ov).unwrap().contains("[rain]"));
    assert_eq!(stdout(&s.run(&["anim", "reset"])), "back to the defaults\n");
    assert_eq!(fs::read_to_string(&ov).unwrap(), "# old header\n");

    let j: Value =
        serde_json::from_slice(&s.run(&["anim", "off", "all", "--json"]).stdout).unwrap();
    assert!(
        j["animations"]
            .as_array()
            .unwrap()
            .iter()
            .all(|a| a["on"] == false && a["overridden"] == true)
    );
}

#[test]
fn anim_rejects_unknown_names() {
    let s = Sandbox::new();
    let o = s.run(&["anim", "off", "rain", "snow"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(stderr(&o).starts_with("unknown: snow. Known: den, streaks,"));
    let o = s.run(&["anim", "on"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(stderr(&o).contains("name an animation (or 'all')"));
    assert!(!s.p("home/.config/bromigos/live/overrides.toml").exists());
}

// ------------------------------------------------------------------ profile

fn profile_doc(s: &Sandbox, args: &[&str]) -> Value {
    let o = s.run(args);
    assert_eq!(o.status.code(), Some(0), "{}", stderr(&o));
    serde_json::from_slice(&o.stdout).unwrap()
}

#[test]
fn profile_show_set_and_lists() {
    let s = Sandbox::new();
    let file = s.p("home/.config/bromigos/profile.toml");

    // no file yet: an empty profile, nothing written
    let j = profile_doc(&s, &["profile", "--json"]);
    assert_eq!(j["schema"], 1);
    assert_eq!(j["exists"], false);
    assert_eq!(j["path"], file.to_str().unwrap());
    assert_eq!(j["addressed_as"], Value::Null);
    assert_eq!(
        j["you"],
        serde_json::json!({"name": null, "full_name": null, "aliases": [], "address": [], "pronouns": null})
    );
    assert!(!file.exists());

    assert_eq!(
        stdout(&s.run(&["profile", "set", "name", "Sam"])),
        "name: Sam\n"
    );
    // the name is the default form of address
    assert_eq!(
        profile_doc(&s, &["profile", "show", "--json"])["addressed_as"],
        "Sam"
    );
    s.run(&["profile", "set", "full_name", "Sam Example"]);
    s.run(&["profile", "set", "pronouns", "they/them"]);
    assert_eq!(
        stdout(&s.run(&["profile", "address", "add", "Captain", "Sam"])),
        "address: Captain, Sam\n"
    );
    s.run(&["profile", "alias", "add", "--", "sammy", "-s-"]);
    let j = profile_doc(&s, &["profile", "address", "add", "captain", "--json"]);
    assert_eq!(j["exists"], true);
    assert_eq!(j["addressed_as"], "Captain");
    assert_eq!(j["you"]["address"], serde_json::json!(["Captain", "Sam"]));
    assert_eq!(j["you"]["aliases"], serde_json::json!(["sammy", "-s-"]));
    assert_eq!(j["you"]["full_name"], "Sam Example");
    assert_eq!(j["you"]["pronouns"], "they/them");

    let text = fs::read_to_string(&file).unwrap();
    assert!(text.starts_with("# Your bromigOS profile"), "{text}");

    // comments and unknown keys survive edits
    fs::write(
        &file,
        text.replace("[you]\n", "[you]\n# mine\ncolour = \"blue\"\n"),
    )
    .unwrap();
    s.run(&["profile", "address", "set", "Boss"]);
    s.run(&["profile", "alias", "remove", "SAMMY"]);
    let text = fs::read_to_string(&file).unwrap();
    assert!(text.contains("# mine\ncolour = \"blue\"\n"), "{text}");
    assert!(text.contains("address = [\"Boss\"]"), "{text}");
    assert!(text.contains("aliases = [\"-s-\"]"), "{text}");

    assert_eq!(
        stdout(&s.run(&["profile", "alias", "remove", "nobody"])),
        "aliases: -s- (nothing matched)\n"
    );
    assert_eq!(
        stdout(&s.run(&["profile", "set", "pronouns", ""])),
        "pronouns: cleared\n"
    );
    let shown = stdout(&s.run(&["profile"]));
    assert!(
        shown.starts_with("name       Sam\nfull_name  Sam Example\n"),
        "{shown}"
    );
    assert!(shown.contains("pronouns   -\n"), "{shown}");
}

#[test]
fn profile_rejects_bad_values() {
    let s = Sandbox::new();
    let o = s.run(&["profile", "set", "name", "two\nlines"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(stderr(&o).contains("one line"), "{}", stderr(&o));
    let o = s.run(&["profile", "set", "colour", "blue"]);
    assert_eq!(o.status.code(), Some(2));
    let long = "x".repeat(81);
    let o = s.run(&["profile", "alias", "add", &long]);
    assert_eq!(o.status.code(), Some(1));
    assert!(!s.p("home/.config/bromigos/profile.toml").exists());
}

// ------------------------------------------------------------------ session

#[test]
fn shell_environment_is_read_only_and_empty_without_a_desktop() {
    use std::os::unix::net::UnixListener;
    let s = Sandbox::new();
    s.script(
        "bin",
        "dbus-update-activation-environment",
        "#!/bin/sh\necho unexpected-import\n",
    );
    let empty = s.run(&["session", "shell-env", "--json"]);
    assert!(empty.status.success());
    assert!(stderr(&empty).is_empty());
    assert_eq!(
        serde_json::from_str::<Value>(&stdout(&empty)).unwrap()["env"],
        serde_json::json!({})
    );
    let mut compositor = spawn(Command::new("/bin/sleep").arg("60").env_clear());
    let dir = s.p("run/hypr/test-desktop");
    fs::create_dir_all(&dir).unwrap();
    fs::write(
        dir.join("hyprland.lock"),
        format!("{}\nwayland-test\n", compositor.id()),
    )
    .unwrap();
    let _socket = UnixListener::bind(s.p("run/wayland-test")).unwrap();
    let result = s.run(&["session", "shell-env", "--json"]);
    let _ = compositor.kill();
    let _ = compositor.wait();
    assert!(result.status.success(), "{}", stderr(&result));
    assert!(stderr(&result).is_empty());
    let doc: Value = serde_json::from_str(&stdout(&result)).unwrap();
    assert_eq!(doc["env"]["WAYLAND_DISPLAY"], "wayland-test");
    assert_eq!(doc["env"]["HYPRLAND_INSTANCE_SIGNATURE"], "test-desktop");
    assert_eq!(doc["env"]["DISPLAY"], "");
}

#[test]
fn session_without_hyprland() {
    let s = Sandbox::new();
    let o = s.run(&["session", "--json"]);
    assert_eq!(o.status.code(), Some(1));
    let j: Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(j["found"], false);
    assert_eq!(j["schema"], 1);
    assert!(j["env"].as_object().unwrap().is_empty());
    // exec still runs the command
    s.script("bin", "hello", "#!/bin/sh\necho \"hi $WAYLAND_DISPLAY\"\n");
    let o = s.run(&["session", "exec", "hello"]);
    assert_eq!(stdout(&o), "hi \n");
}

// ------------------------------------------------------------------ lock-run

/// Fake lockers plus a fake `logger` (records instead of writing to the journal).
fn lock_sandbox() -> Sandbox {
    let s = Sandbox::new();
    let log = s.p("log");
    s.script(
        "bin",
        "logger",
        &format!("#!/bin/sh\necho \"$*\" >> '{}'\n", log.display()),
    );
    s
}

fn locker(s: &Sandbox, name: &str, body: &str) {
    let runs = s.p("runs");
    s.script(
        "bin",
        name,
        &format!("#!/bin/sh\necho {name} >> '{}'\n{body}\n", runs.display()),
    );
}

fn lock_run(s: &Sandbox, lockers: &str) -> Output {
    let mut c = s.cmd(&["lock-run"]);
    c.env("BROMIGOS_LOCKER", lockers);
    output(c)
}

fn lines(p: &Path) -> Vec<String> {
    fs::read_to_string(p)
        .unwrap_or_default()
        .lines()
        .map(str::to_owned)
        .collect()
}

#[test]
fn lock_run_restarts_a_crashed_locker() {
    let s = lock_sandbox();
    let marker = s.p("crashed");
    locker(
        &s,
        "fakelock",
        &format!(
            "if [ -e '{m}' ]; then exit 0; fi; : > '{m}'; kill -KILL $$",
            m = marker.display()
        ),
    );
    locker(&s, "otherlock", "exit 0");
    let o = lock_run(&s, "fakelock otherlock");
    assert_eq!(o.status.code(), Some(0));
    assert_eq!(lines(&s.p("runs")), ["fakelock", "fakelock"]);
    assert_eq!(
        lines(&s.p("log")),
        ["-t bromigos-lock -- fakelock exited 137 while locked (try 1); starting it again"]
    );
}

#[test]
fn lock_run_falls_back_when_missing_or_broken() {
    let s = lock_sandbox();
    locker(&s, "broken", "exit 1");
    locker(&s, "good", "exit 0");
    let o = lock_run(&s, "missing broken good");
    assert_eq!(o.status.code(), Some(0));
    assert_eq!(lines(&s.p("runs")), ["broken", "broken", "good"]);
    let log = lines(&s.p("log"));
    assert!(log[1].ends_with("missing won't start (exit 127); falling back to broken"));
    assert!(log[3].ends_with("broken won't start (exit 1); falling back to good"));
}

#[test]
fn lock_run_second_instance_is_a_no_op() {
    let s = lock_sandbox();
    locker(&s, "good", "exit 0");
    let flock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(s.p("run/bromigos-lock.flock"))
        .unwrap();
    flock.try_lock().unwrap();
    let o = lock_run(&s, "good");
    assert_eq!(o.status.code(), Some(0));
    assert!(lines(&s.p("runs")).is_empty());
    flock.unlock().unwrap();
    let o = lock_run(&s, "good");
    assert_eq!(o.status.code(), Some(0));
    assert_eq!(lines(&s.p("runs")), ["good"]);
}

#[test]
fn lock_run_lock_is_held_while_the_locker_runs() {
    let s = lock_sandbox();
    let ready = s.p("ready");
    let release = s.p("release");
    // the first locker waits until the test says so (the sandbox PATH has no
    // coreutils, hence the absolute sleep)
    locker(
        &s,
        "slow",
        &format!(
            ": > '{r}'; while [ ! -e '{x}' ]; do /usr/bin/sleep 0.05; done; exit 0",
            r = ready.display(),
            x = release.display()
        ),
    );
    let mut c = s.cmd(&["lock-run"]);
    c.env("BROMIGOS_LOCKER", "slow");
    let mut first = spawn(&mut c);
    for _ in 0..500 {
        if ready.exists() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    assert!(ready.exists());
    let o = lock_run(&s, "slow");
    assert_eq!(o.status.code(), Some(0));
    assert_eq!(
        lines(&s.p("runs")),
        ["slow"],
        "the second call started nothing"
    );
    fs::write(&release, "").unwrap();
    assert_eq!(first.wait().unwrap().code(), Some(0));
}

// ------------------------------------------------------------------ update, restart

#[test]
fn update_check_then_migrations() {
    let s = Sandbox::new();
    fs::create_dir_all(s.p("share/migrations")).unwrap();
    fs::create_dir(s.p("pacman")).unwrap();
    s.script(
        "share/migrations",
        "20260101000000-hello.sh",
        "echo hi > \"$HOME/hello\"; echo said hi\n",
    );
    // --check: the pending migration; no checkupdates on this PATH, so packages unknown
    let mut c = s.cmd(&["update", "--check", "--json"]);
    c.env("BROMIGOS_PACMAN_LOCAL", s.p("pacman"));
    let o = output(c);
    assert!(o.status.success(), "{}", stderr(&o));
    let doc: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(
        doc["check"]["migrations"],
        serde_json::json!(["20260101000000-hello"])
    );
    assert!(doc["check"]["packages"].is_null());
    // --no-packages: runs it (bash from /usr/bin), records it, and a second run has none
    let run = || {
        let mut c = s.cmd(&["update", "--no-packages", "--json"]);
        c.env("BROMIGOS_PACMAN_LOCAL", s.p("pacman"))
            .env("PATH", format!("{}:/usr/bin", s.p("bin").display()));
        let o = output(c);
        assert!(o.status.success(), "{}", stderr(&o));
        serde_json::from_slice::<serde_json::Value>(&o.stdout).unwrap()
    };
    let r = run();
    assert_eq!(r["report"]["migrations"][0]["outcome"], "done");
    assert_eq!(r["report"]["migrations"][0]["tail"], "said hi");
    assert_eq!(fs::read_to_string(s.p("home/hello")).unwrap(), "hi\n");
    assert!(
        s.p("home/.local/state/bromigos/migrations/20260101000000-hello")
            .is_file()
    );
    assert_eq!(run()["report"]["migrations"], serde_json::json!([]));
}

const WHATS_NEW: &str = "# What's new\n\nIntro.\n\n<!-- releases: … -->\n\n## 0.1.3\n\
<!-- release: 0.1.3-rc1 -->\n\n*rc*\n\n### New\n\n- the newest\n\n## 0.1.2\n<!-- release: 0.1.2 -->\n\n- older\n";

#[test]
fn whats_new_reads_the_installed_notes() {
    let s = Sandbox::new();
    let o = s.run(&["whats-new"]);
    assert_eq!(o.status.code(), Some(1), "no notes installed");
    assert!(stderr(&o).contains("no release notes installed"));
    fs::create_dir_all(s.p("share")).unwrap();
    fs::write(s.p("share/whats-new.md"), WHATS_NEW).unwrap();
    let o = s.run(&["whats-new"]);
    assert!(o.status.success(), "{}", stderr(&o));
    let out = stdout(&o);
    assert!(out.starts_with("bromigOS 0.1.3\n\n*rc*"), "{out}");
    assert!(out.contains("- the newest") && !out.contains("- older") && out.contains("--all"));
    assert!(!out.contains("<!--"), "the marker isn't shown");
    let all = stdout(&s.run(&["whats-new", "--all"]));
    assert!(all.contains("bromigOS 0.1.3") && all.contains("bromigOS 0.1.2\n\n- older"));
    assert!(stdout(&s.run(&["whats-new", "v0.1.2"])).contains("- older"));
    let o = s.run(&["whats-new", "9.9.9"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(stderr(&o).contains("installed: 0.1.3, 0.1.2"));
    // reading them counts as told: the next update doesn't say it again
    assert_eq!(
        fs::read_to_string(s.p("home/.local/state/bromigos/whats-new")).unwrap(),
        "0.1.3-rc1\n"
    );
}

#[test]
fn update_says_once_that_a_new_release_came() {
    let s = Sandbox::new();
    fs::create_dir_all(s.p("share")).unwrap();
    fs::create_dir(s.p("pacman")).unwrap();
    fs::write(s.p("share/whats-new.md"), WHATS_NEW).unwrap();
    let update = || {
        let mut c = s.cmd(&["update", "--no-packages"]);
        c.env("BROMIGOS_PACMAN_LOCAL", s.p("pacman"))
            .env("PATH", format!("{}:/usr/bin", s.p("bin").display()));
        let o = output(c);
        assert!(o.status.success(), "{}", stderr(&o));
        stdout(&o)
    };
    assert!(
        update().contains("== what's new: bromigOS 0.1.3 (bromigos whats-new)"),
        "the first update after the release"
    );
    assert!(!update().contains("what's new"), "said once");
}

/// A driver update waiting for the restart (2026-10-09: nvidia-utils 615.78.08 installed,
/// the 615.71.09 module loaded), faked with BROMIGOS_GPU_ROOT: the update says so last, in
/// its JSON too, and sends one desktop notification.
#[test]
fn update_says_when_the_graphics_driver_waits_for_a_restart() {
    let s = Sandbox::new();
    fs::create_dir(s.p("pacman")).unwrap();
    let gpu = s.p("gpu");
    fs::create_dir_all(gpu.join("sys/module/nvidia")).unwrap();
    fs::create_dir_all(gpu.join("usr/lib")).unwrap();
    fs::write(gpu.join("sys/module/nvidia/version"), "615.71.09\n").unwrap();
    fs::write(gpu.join("usr/lib/libEGL_nvidia.so.615.78.08"), "").unwrap();
    s.script(
        "bin",
        "notify-send",
        "#!/bin/sh\nprintf '%s|' \"$@\" >> \"$HOME/notified\"; echo >> \"$HOME/notified\"\n",
    );
    let update = |json: bool| {
        let mut c = s.cmd(if json {
            &["update", "--no-packages", "--json"][..]
        } else {
            &["update", "--no-packages"][..]
        });
        c.env("BROMIGOS_PACMAN_LOCAL", s.p("pacman"))
            .env("BROMIGOS_GPU_ROOT", &gpu)
            .env("PATH", format!("{}:/usr/bin", s.p("bin").display()));
        let o = output(c);
        assert!(o.status.success(), "{}", stderr(&o));
        stdout(&o)
    };
    let out = update(false);
    let last = out.trim_end().lines().last().unwrap();
    assert!(
        last.starts_with("The graphics driver was updated: restart the computer to use it. Until then, the animated background "),
        "{out}"
    );
    assert!(out.contains("driver    reboot to run it"), "{out}");
    let doc: Value = serde_json::from_str(&update(true)).unwrap();
    let r = &doc["report"]["reboot"];
    assert_eq!(r["driver"]["running"], "615.71.09");
    assert_eq!(r["driver"]["installed"], "615.78.08");
    assert!(r["kernel"].is_null());
    assert_eq!(r["notified"], true);
    assert!(
        r["message"]
            .as_str()
            .unwrap()
            .starts_with("The graphics driver was updated")
    );
    // one notification an update
    let sent = fs::read_to_string(s.p("home/notified")).unwrap();
    assert_eq!(sent.lines().count(), 2, "{sent}");
    assert!(sent.contains("Restart to finish the update|The graphics driver was updated"));
    // the driver back in step: nothing said
    fs::write(gpu.join("sys/module/nvidia/version"), "615.78.08\n").unwrap();
    let doc: Value = serde_json::from_str(&update(true)).unwrap();
    assert!(doc["report"]["reboot"].is_null());
    assert!(!update(false).contains("restart the computer"));
}

#[test]
fn restart_names_pieces() {
    let s = Sandbox::new();
    let o = s.run(&["restart", "bogus"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(stderr(&o).contains("unknown: bogus"));
    let o = s.run(&["restart", "--check", "--json"]);
    assert!(o.status.success(), "{}", stderr(&o));
}

// ------------------------------------------------------------------ channels and rollback

/// A pacman.conf in the sandbox, and a `sudo` that copies `install`'s file (no root here).
fn channel_sandbox(server: &str) -> (Sandbox, PathBuf) {
    let s = Sandbox::new();
    let conf = s.p("home").join("pacman.conf");
    fs::write(
        &conf,
        format!("[options]\nColor\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n\n[bromigos]\nSigLevel = Required DatabaseOptional\nServer = {server}\n"),
    )
    .unwrap();
    s.script(
        "bin",
        "sudo",
        "#!/bin/sh\nif [ \"$1\" = install ]; then shift; while [ $# -gt 2 ]; do shift; done; /bin/cp \"$1\" \"$2\"; exit $?; fi\nif [ \"$1\" = rm ]; then shift; exec /bin/rm \"$@\"; fi\nexec \"$@\"\n",
    );
    (s, conf)
}

#[test]
fn channel_shows_and_switches() {
    let (s, conf) = channel_sandbox("https://pkgs.example/$repo/$arch");
    let mut c = s.cmd(&["channel", "--json"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let v: Value = serde_json::from_str(&stdout(&output(c))).unwrap();
    assert_eq!(v["channel"]["channel"], "edge");
    assert_eq!(v["channel"]["base"], "https://pkgs.example");

    let mut c = s.cmd(&["channel", "stable", "--json"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let o = output(c);
    assert!(o.status.success(), "{}", stderr(&o));
    let v: Value = serde_json::from_str(&stdout(&o)).unwrap();
    assert_eq!(v["channel"]["to"], "stable");
    assert_eq!(v["channel"]["downgrade"], true);
    let text = fs::read_to_string(&conf).unwrap();
    assert!(
        text.contains("Server = https://pkgs.example/$repo/stable/$arch\n"),
        "{text}"
    );
    assert!(
        text.starts_with("[options]\nColor\n"),
        "the rest is untouched"
    );

    // dev: a local repo, unsigned; and back to edge from the remembered base
    let mut c = s.cmd(&["channel", "dev", "--dev-dir", "/tmp/myrepo"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    assert!(output(c).status.success());
    let text = fs::read_to_string(&conf).unwrap();
    assert!(
        text.contains("SigLevel = Optional\nServer = file:///tmp/myrepo/$repo/$arch\n"),
        "{text}"
    );
    let mut c = s.cmd(&["channel", "edge"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let o = output(c);
    assert!(o.status.success(), "{}", stderr(&o));
    let text = fs::read_to_string(&conf).unwrap();
    assert!(
        text.contains(
            "SigLevel = Required DatabaseOptional\nServer = https://pkgs.example/$repo/$arch\n"
        ),
        "{text}"
    );

    let mut c = s.cmd(&["channel", "nightly"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let o = output(c);
    assert!(!o.status.success());
    assert!(stderr(&o).contains("no such channel"));
}

/// A move to an older channel that lacks a bromigOS package installed here (bromigos-boot
/// before the release that has it) waits, plainly, and is remembered; once the channel has
/// it, the move goes through and is forgotten.
#[test]
fn a_channel_that_lacks_a_package_waits_and_says_so() {
    let (s, conf) = channel_sandbox("https://pkgs.example/$repo/$arch");
    let listing = s.p("home").join("listing");
    fs::write(
        &listing,
        "bromigos-core-0.1.3-1/\nbromigos-settings-0.1.3-1/\n",
    )
    .unwrap();
    s.script(
        "bin",
        "curl",
        "#!/bin/sh\nwhile [ $# -gt 0 ]; do [ \"$1\" = -o ] && : > \"$2\"; shift; done\nexit 0\n",
    );
    s.script(
        "bin",
        "bsdtar",
        &format!("#!/bin/sh\nexec /bin/cat {}\n", listing.display()),
    );
    s.script("bin", "pacman", "#!/bin/sh\ncase \"$1\" in -Qq|-Slq) printf 'bromigos-core\\nbromigos-boot\\nbromigos-settings\\n' ;; esac\n");
    let mut c = s.cmd(&["channel", "stable", "--json"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let o = output(c);
    assert!(o.status.success(), "{}", stderr(&o));
    let v: Value = serde_json::from_str(&stdout(&o)).unwrap();
    let words = v["waiting"]["words"].as_str().unwrap();
    assert!(
        words.starts_with("Stable will be available after the next bromigOS release"),
        "{words}"
    );
    assert_eq!(v["waiting"]["lacks"][0], "bromigos-boot");
    assert!(
        fs::read_to_string(&conf)
            .unwrap()
            .contains("Server = https://pkgs.example/$repo/$arch\n"),
        "still edge"
    );
    let mut c = s.cmd(&["channel", "--json"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let v: Value = serde_json::from_str(&stdout(&output(c))).unwrap();
    assert_eq!(v["wanted"], "stable");
    // the next release has it: the move goes through, and nothing is waited for any more
    fs::write(
        &listing,
        "bromigos-core-0.1.4-1/\nbromigos-boot-0.1.4-1/\nbromigos-settings-0.1.4-1/\n",
    )
    .unwrap();
    let mut c = s.cmd(&["channel", "stable", "--json"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let o = output(c);
    assert!(o.status.success(), "{}", stderr(&o));
    assert!(
        fs::read_to_string(&conf)
            .unwrap()
            .contains("/$repo/stable/$arch\n")
    );
    let mut c = s.cmd(&["channel", "--json"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let v: Value = serde_json::from_str(&stdout(&output(c))).unwrap();
    assert!(v["wanted"].is_null(), "{v}");
}

#[test]
fn a_channel_switch_drops_the_old_channels_database() {
    // edge's bromigos.db is newer than stable's: kept, `pacman -Sy` asks "modified since?",
    // keeps it and checks stable's signature against it ("signature is invalid")
    let (s, conf) = channel_sandbox("https://pkgs.example/$repo/$arch");
    let sync = s.p("sync");
    for f in [
        "bromigos.db",
        "bromigos.db.sig",
        "bromigos.files",
        "core.db",
        "extra.db",
    ] {
        fs::write(sync.join(f), "x").unwrap();
    }
    let mut c = s.cmd(&["channel", "stable", "--json"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let o = output(c);
    assert!(o.status.success(), "{}", stderr(&o));
    let v: Value = serde_json::from_str(&stdout(&o)).unwrap();
    assert_eq!(v["channel"]["dropped"].as_array().unwrap().len(), 3);
    for f in ["bromigos.db", "bromigos.db.sig", "bromigos.files"] {
        assert!(!sync.join(f).exists(), "{f} stayed");
    }
    assert!(
        sync.join("core.db").exists() && sync.join("extra.db").exists(),
        "Arch's stay"
    );
    // the same channel again: the Server line doesn't change, the database (stable's now) stays
    fs::write(sync.join("bromigos.db"), "stable").unwrap();
    let mut c = s.cmd(&["channel", "stable"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let o = output(c);
    assert!(o.status.success(), "{}", stderr(&o));
    assert!(!stdout(&o).contains("database dropped"));
    assert!(sync.join("bromigos.db").exists());
    // and back to edge: dropped again, and said so
    let mut c = s.cmd(&["channel", "edge"]);
    c.env("BROMIGOS_PACMAN_CONF", &conf);
    let o = output(c);
    assert!(
        stdout(&o).contains("the old channel's database dropped"),
        "{}",
        stdout(&o)
    );
    assert!(!sync.join("bromigos.db").exists());
}

/// Fakes for a btrfs root with snapper and snap-pac, GRUB without grub-btrfs.
fn snapshot_fakes(s: &Sandbox) -> PathBuf {
    let calls = s.p("home").join("calls");
    s.script(
        "bin",
        "findmnt",
        "#!/bin/sh\ncase \"$*\" in *FSTYPE*) echo btrfs;; esac\n",
    );
    s.script("bin", "pacman", "#!/bin/sh\nexit 1\n");
    s.script("bin", "systemctl", "#!/bin/sh\necho disabled\n");
    s.script(
        "bin",
        "snapper",
        &format!(
            "#!/bin/sh\necho \"snapper $*\" >> {calls}\ncase \"$*\" in\n  *--version*) exit 0;;\n  *list-configs*) echo root;;\n  *\" list \"*) printf '10,pre,,d1,pacman -Syu\\n11,post,10,d1,bromigos-core\\n12,pre,,d2,pacman -Syu\\n13,post,12,d2,bromigos-live\\n';;\n  *status*) printf 'c..... /usr/lib/x\\n+..... /usr/lib/y\\nc..... /var/lib/pacman/local/z\\n';;\n  *undochange*) exit 0;;\nesac\n",
            calls = calls.display()
        ),
    );
    s.script("bin", "sudo", "#!/bin/sh\nexec \"$@\"\n");
    calls
}

#[test]
fn rollback_undoes_the_recorded_update() {
    let s = Sandbox::new();
    let calls = snapshot_fakes(&s);
    let state = s.p("home").join(".local/state/bromigos");
    fs::create_dir_all(&state).unwrap();
    fs::write(
        state.join("updates.jsonl"),
        concat!(
            r#"{"at":"2026-10-08T19:00:00-07:00","channel":"edge","snapshot":{"pre":10,"post":11},"packages":["bromigos-core 1 -> 2"]}"#,
            "\n",
            r#"{"at":"2026-10-08T20:00:00-07:00","channel":"edge","snapshot":{"pre":12,"post":13},"packages":["bromigos-live 1 -> 2","linux 7.2.8 -> 7.2.9"]}"#,
            "\n"
        ),
    )
    .unwrap();
    // status lists both, newest first, with the machine's snapshot setup
    let o = s.run(&["rollback", "status", "--json"]);
    assert!(o.status.success(), "{}", stderr(&o));
    let v: Value = serde_json::from_str(&stdout(&o)).unwrap();
    assert_eq!(v["snapshots"]["btrfs"], true);
    assert_eq!(v["snapshots"]["snap_pac"], false);
    assert_eq!(v["snapshots"]["bootloader"], "unknown");
    assert_eq!(v["rollbacks"][0]["snapshot"]["pre"], 12);
    assert_eq!(v["rollbacks"][1]["snapshot"]["pre"], 10);

    // the newest update is undone: snapper undochange 12..13, and it's recorded
    let o = s.run(&["update", "--rollback", "--yes", "--json"]);
    assert!(o.status.success(), "{}", stderr(&o));
    let v: Value = serde_json::from_str(&stdout(&o)).unwrap();
    assert_eq!(v["rollback"]["pair"]["pre"], 12);
    assert_eq!(v["rollback"]["pair"]["post"], 13);
    assert!(
        v["rollback"]["notes"][0]
            .as_str()
            .unwrap()
            .contains("reboot")
    );
    let log = fs::read_to_string(&calls).unwrap();
    assert!(log.contains("snapper -c root undochange 12..13"), "{log}");
    assert!(!log.contains("undochange 10..11"));
    let recorded = fs::read_to_string(state.join("updates.jsonl")).unwrap();
    assert!(
        recorded
            .lines()
            .last()
            .unwrap()
            .contains("\"rolled_back\":true")
    );

    // now only the older one is left, and it can be named by its pre snapshot
    let o = s.run(&["rollback", "status", "--json"]);
    let v: Value = serde_json::from_str(&stdout(&o)).unwrap();
    assert_eq!(v["rollbacks"].as_array().unwrap().len(), 1);
    let o = s.run(&["update", "--rollback", "10", "--yes", "--json"]);
    assert!(o.status.success(), "{}", stderr(&o));
    assert!(
        fs::read_to_string(&calls)
            .unwrap()
            .contains("undochange 10..11")
    );
    // and nothing is left to undo
    let o = s.run(&["update", "--rollback", "--yes"]);
    assert!(!o.status.success());
    assert!(
        stderr(&o).contains("no update with a snapshot pair"),
        "{}",
        stderr(&o)
    );
}

#[test]
fn rollback_setup_plans_the_boot_menu() {
    let s = Sandbox::new();
    snapshot_fakes(&s);
    // GRUB without grub-btrfs: the plan installs snap-pac and grub-btrfs, enables the daemon
    s.script(
        "bin",
        "findmnt",
        "#!/bin/sh\ncase \"$*\" in *FSTYPE*) echo btrfs;; esac\n",
    );
    s.script("bin", "test-exists", "#!/bin/sh\n");
    let o = s.run(&["rollback", "setup", "--dry-run"]);
    assert!(o.status.success(), "{}", stderr(&o));
    let out = stdout(&o);
    assert!(
        out.contains("would run: sudo pacman -S --needed snap-pac"),
        "{out}"
    );
    // the sandbox has no /boot/grub/grub.cfg: the boot loader is unknown, said as a note
    assert!(
        out.contains("note: the boot loader wasn't recognised"),
        "{out}"
    );
    // an ext4 root: nothing to set up
    s.script(
        "bin",
        "findmnt",
        "#!/bin/sh\ncase \"$*\" in *FSTYPE*) echo ext4;; esac\n",
    );
    let o = s.run(&["rollback", "setup", "--dry-run"]);
    assert!(
        stdout(&o).contains("snapshots need btrfs"),
        "{}",
        stdout(&o)
    );
}

/// A GRUB machine as its user sees it with archinstall's /boot (0700): no grub.cfg in
/// sight, GRUB's file in /etc and its package; grub-btrfs and its daemon, snapper's root
/// configuration, which answers this user "No permissions." until `allow` ran.
fn grub_user_fakes(s: &Sandbox) -> PathBuf {
    let calls = s.p("home").join("calls");
    let root = s.p("home");
    fs::create_dir_all(root.join("etc/default")).unwrap();
    fs::write(root.join("etc/default/grub"), "GRUB_TIMEOUT=5\n").unwrap();
    fs::create_dir_all(root.join("usr/share/libalpm/hooks")).unwrap();
    fs::write(
        root.join("usr/share/libalpm/hooks/05-snap-pac-pre.hook"),
        "",
    )
    .unwrap();
    fs::create_dir_all(root.join("run/dbus")).unwrap();
    fs::write(root.join("run/dbus/system_bus_socket"), "").unwrap();
    fs::write(
        root.join("etc/mkinitcpio.conf"),
        "HOOKS=(base udev autodetect block filesystems fsck grub-btrfs-overlayfs)\n",
    )
    .unwrap();
    s.script(
        "bin",
        "findmnt",
        "#!/bin/sh\ncase \"$*\" in *FSTYPE*) echo btrfs;; esac\n",
    );
    s.script(
        "bin",
        "pacman",
        "#!/bin/sh\ncase \"$*\" in \"-Qq grub\"|\"-Qq grub-btrfs\") exit 0;; esac\nexit 1\n",
    );
    s.script("bin", "systemctl", "#!/bin/sh\necho enabled\n");
    s.script(
        "bin",
        "id",
        "#!/bin/sh\ncase \"$1\" in -un) echo tester;; -Gn) echo tester wheel;; esac\n",
    );
    let allowed = s.p("home").join("allowed");
    s.script(
        "bin",
        "snapper",
        &format!(
            "#!/bin/sh\necho \"snapper $*\" >> {calls}\ncase \"$*\" in\n  *--version*) exit 0;;\n  *list-configs*) echo root;;\n  *get-config*) if [ -e {allowed} ]; then printf 'key,value\\nALLOW_GROUPS,wheel\\nSYNC_ACL,yes\\n'; else printf 'key,value\\nALLOW_GROUPS,\\nALLOW_USERS,\\nSYNC_ACL,no\\n'; fi;;\n  *set-config*) : > {allowed};;\n  *\" list \"*) [ -e {allowed} ] || {{ echo 'No permissions.' >&2; exit 1; }};;\nesac\n",
            calls = calls.display(),
            allowed = allowed.display()
        ),
    );
    s.script("bin", "sudo", "#!/bin/sh\nexec \"$@\"\n");
    calls
}

#[test]
fn grub_is_seen_by_the_user_and_allow_lets_them_list() {
    let s = Sandbox::new();
    let calls = grub_user_fakes(&s);
    // GRUB without /boot (gap: "unknown boot loader" as the user); the update can't be
    // recorded yet, and status says how to fix it
    let o = s.run(&["rollback", "status"]);
    assert!(o.status.success(), "{}", stderr(&o));
    let out = stdout(&o);
    assert!(out.contains("GRUB lists them (grub-btrfs)"), "{out}");
    assert!(out.contains("bromigos rollback allow"), "{out}");
    assert!(out.contains("setup: bromigos rollback setup"), "{out}");
    let o = s.run(&["rollback", "status", "--json"]);
    let v: Value = serde_json::from_str(&stdout(&o)).unwrap();
    assert_eq!(v["snapshots"]["bootloader"], "grub");
    assert_eq!(v["snapshots"]["readable"], false);
    assert_eq!(v["snapshots"]["boot_overlay"], true);

    // setup's plan: just allow
    let o = s.run(&["rollback", "setup", "--dry-run"]);
    assert!(o.status.success(), "{}", stderr(&o));
    assert!(
        stdout(&o).contains("would run: bromigos rollback allow"),
        "{}",
        stdout(&o)
    );

    // allow: reads the configuration as root, sets what's missing
    let o = s.run(&["rollback", "allow"]);
    assert!(o.status.success(), "{}", stderr(&o));
    assert!(
        stdout(&o).contains("+ sudo snapper -c root set-config ALLOW_GROUPS=wheel SYNC_ACL=yes"),
        "{}",
        stdout(&o)
    );
    let log = fs::read_to_string(&calls).unwrap();
    assert!(
        log.contains("snapper -c root --csvout get-config --columns key,value"),
        "{log}"
    );
    // and now the user lists them: recorded, nothing left to set up
    let o = s.run(&["rollback", "status"]);
    let out = stdout(&o);
    assert!(!out.contains("rollback allow"), "{out}");
    assert!(!out.contains("setup: bromigos rollback setup"), "{out}");
    let o = s.run(&["rollback", "allow"]);
    assert!(stdout(&o).contains("nothing to change"), "{}", stdout(&o));
    let o = s.run(&["rollback", "setup"]);
    assert!(stdout(&o).contains("nothing to do"), "{}", stdout(&o));
}

// -------------------------------------------------------------------------- hw

/// A hybrid laptop as files under the sandbox's root (BROMIGOS_FS_ROOT): Intel UHD 630 on
/// the panel and a GTX 1650 Mobile beside it, a battery, a lid, a touchpad; fake pacman
/// (nothing installed), systemctl (nothing enabled) and sudo (records, runs nothing).
fn hw_laptop(s: &Sandbox) -> PathBuf {
    let root = s.p("home");
    let put = |rel: &str, text: &str| {
        let p = root.join(rel);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, text).unwrap();
    };
    for (slot, id, drv, card, conns) in [
        (
            "0000:00:02.0",
            "8086:3E9B",
            "i915",
            "card0",
            &["eDP-1", "DP-1"][..],
        ),
        ("0000:01:00.0", "10DE:1F91", "nouveau", "card1", &[][..]),
    ] {
        let ue = format!("DRIVER={drv}\nPCI_CLASS=30000\nPCI_ID={id}\nPCI_SLOT_NAME={slot}\n");
        put(&format!("sys/bus/pci/devices/{slot}/uevent"), &ue);
        put(&format!("sys/class/drm/{card}/device/uevent"), &ue);
        for c in conns {
            fs::create_dir_all(root.join(format!("sys/class/drm/{card}-{c}"))).unwrap();
        }
    }
    put("sys/class/dmi/id/chassis_type", "10\n");
    put("sys/class/dmi/id/sys_vendor", "Dell Inc.\n");
    put("sys/class/dmi/id/product_name", "XPS 15 7590\n");
    put("sys/class/power_supply/BAT0/type", "Battery\n");
    put("sys/class/power_supply/BAT0/capacity", "64\n");
    put("sys/class/power_supply/BAT0/status", "Discharging\n");
    fs::create_dir_all(root.join("proc/acpi/button/lid/LID0")).unwrap();
    fs::create_dir_all(root.join("sys/class/backlight/intel_backlight")).unwrap();
    put(
        "proc/bus/input/devices",
        "I: Bus=0018\nN: Name=\"SYNA2393:00 06CB:7E7E Touchpad\"\nB: PROP=5\nB: EV=1b\nB: KEY=e520 10000 0 0 0 0\nB: ABS=2e0800000000003\n",
    );
    put("usr/lib/modules/7.2.9-arch1-1/pkgbase", "linux\n");
    put(
        "etc/mkinitcpio.conf",
        "MODULES=()\nHOOKS=(base udev autodetect modconf kms block filesystems fsck)\n",
    );
    put("etc/pacman.conf", "[options]\n[core]\n[extra]\n");
    put("proc/cmdline", "root=UUID=x rw quiet\n");
    let calls = s.p("calls");
    // pacman -T: everything asked is missing (and NVIDIA-MODULE); -Qq: nothing installed
    s.script(
        "bin",
        "pacman",
        "#!/bin/sh\nif [ \"$1\" = -T ]; then shift; for p; do echo \"$p\"; done; exit 127; fi\nexit 1\n",
    );
    s.script("bin", "systemctl", "#!/bin/sh\necho disabled\nexit 1\n");
    s.script("bin", "systemd-detect-virt", "#!/bin/sh\nexit 1\n");
    s.script(
        "bin",
        "sudo",
        &format!("#!/bin/sh\necho \"sudo $*\" >> {}\n", calls.display()),
    );
    calls
}

#[test]
fn hw_reports_a_hybrid_laptop_and_its_plan() {
    let s = Sandbox::new();
    hw_laptop(&s);
    let o = s.run(&["hw", "--json"]);
    assert!(o.status.success(), "{}", stderr(&o));
    let v: Value = serde_json::from_str(&stdout(&o)).unwrap();
    assert_eq!(v["schema"], 1);
    let d = &v["detection"];
    assert_eq!(d["machine"]["kind"], "laptop");
    assert_eq!(d["machine"]["laptop"], true);
    assert_eq!(d["gpus"][0]["stack"], "intel");
    assert_eq!(d["gpus"][0]["panel"], true);
    assert_eq!(d["gpus"][1]["stack"], "nvidia-open");
    assert_eq!(d["hybrid"]["integrated"], "0000:00:02.0");
    let p = &v["plan"];
    let install: Vec<&str> = p["install"]
        .as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_str().unwrap())
        .collect();
    for want in [
        "nvidia-open",
        "nvidia-utils",
        "intel-media-driver",
        "nvidia-prime",
        "brightnessctl",
        "power-profiles-daemon",
    ] {
        assert!(install.contains(&want), "{want} not in {install:?}");
    }
    assert_eq!(p["enable"][0], "power-profiles-daemon.service");
    assert_eq!(p["initramfs"], true);
    assert_eq!(p["want"]["env"][0]["name"], "AQ_DRM_DEVICES");

    let o = s.run(&["hw"]);
    let out = stdout(&o);
    assert!(
        out.contains("This machine: a laptop (chassis type 10), Dell Inc. XPS 15 7590"),
        "{out}"
    );
    assert!(
        out.contains("Hybrid the desktop renders on 0000:00:02.0"),
        "{out}"
    );
    assert!(
        out.contains("write     /etc/mkinitcpio.conf.d/bromigos-nvidia.conf"),
        "{out}"
    );
    assert!(
        out.contains("touchpad SYNA2393:00 06CB:7E7E Touchpad"),
        "{out}"
    );
}

#[test]
fn hw_setup_dry_runs_and_user_only_writes_only_the_users_file() {
    let s = Sandbox::new();
    let calls = hw_laptop(&s);
    let state = s.p("home/.local/state/bromigos/hw/hyprland.lua");
    let o = s.run(&["hw", "setup", "--dry-run"]);
    assert!(o.status.success(), "{}", stderr(&o));
    let out = stdout(&o);
    assert!(out.contains("It would run:"), "{out}");
    assert!(out.contains("$ sudo pacman -S --needed mesa vulkan-intel intel-media-driver linux-firmware-intel nvidia-open"), "{out}");
    assert!(out.contains("$ sudo mkinitcpio -P"), "{out}");
    assert!(!calls.exists(), "a dry run runs nothing");
    assert!(!state.exists(), "a dry run writes nothing");

    let o = s.run(&["hw", "setup", "--user-only"]);
    assert!(o.status.success(), "{} {}", stdout(&o), stderr(&o));
    assert!(!calls.exists(), "--user-only: no sudo");
    let lua = fs::read_to_string(&state).unwrap();
    assert!(
        lua.contains("\"AQ_DRM_DEVICES\", \"/dev/dri/bromigos-igpu:/dev/dri/bromigos-dgpu\""),
        "{lua}"
    );

    // the whole of it, with a sudo that only records: in order, then the user's file
    let o = s.run(&["hw", "setup", "--yes"]);
    assert!(o.status.success(), "{} {}", stdout(&o), stderr(&o));
    let log = fs::read_to_string(&calls).unwrap();
    let lines: Vec<&str> = log.lines().collect();
    assert!(
        lines[0].starts_with(
            "sudo pacman -S --needed --noconfirm mesa vulkan-intel intel-media-driver"
        ),
        "{log}"
    );
    assert!(
        lines
            .iter()
            .any(|l| l.ends_with("/etc/udev/rules.d/61-bromigos-gpu.rules")),
        "{log}"
    );
    assert!(lines.contains(&"sudo mkinitcpio -P"), "{log}");
    assert_eq!(
        *lines.last().unwrap(),
        "sudo systemctl enable power-profiles-daemon.service"
    );
}

#[test]
fn hw_routes_and_is_listed() {
    let s = Sandbox::new();
    let o = s.run(&["commands", "--json"]);
    let v: Value = serde_json::from_str(&stdout(&o)).unwrap();
    assert!(
        v["builtins"]
            .as_array()
            .unwrap()
            .iter()
            .any(|b| b["name"] == "hw")
    );
    // a word hw doesn't own goes to the router
    s.script(
        "bin",
        "bromigos-hw-keyboard",
        "#!/bin/sh\necho keyboard \"$@\"\n",
    );
    let o = s.run(&["hw", "keyboard", "x"]);
    assert_eq!(stdout(&o), "keyboard x\n");
}

// ------------------------------------------------------------------ idle

fn idle_doc(s: &Sandbox, args: &[&str]) -> Value {
    let o = s.run(args);
    assert!(o.status.success(), "{args:?}: {}", stderr(&o));
    serde_json::from_str(&stdout(&o)).unwrap()
}

#[test]
fn idle_presets_set_render_and_undo() {
    let s = Sandbox::new();
    // the defaults: the old policy; nothing of the user's yet
    let v = idle_doc(&s, &["idle", "--json"]);
    assert_eq!(v["schema"], 1);
    assert_eq!(v["exists"], false);
    assert_eq!(v["preset"], "default");
    assert_eq!(v["policy"]["lock"]["minutes"], 10);
    assert_eq!(v["hook"], "missing");
    // screensaver only: nothing locks, the file and the rendered config say so; no session
    // here, so nothing is restarted
    let v = idle_doc(&s, &["idle", "preset", "screensaver-only", "--json"]);
    assert_eq!(v["preset"], "screensaver-only");
    assert_eq!(v["screensaver_only"], true);
    assert_eq!(v["policy"]["lock"]["enabled"], false);
    assert_eq!(
        v["summary"],
        "Screensaver at 8 min, then nothing locks; the displays stay on; never suspends."
    );
    assert_eq!(v["applied"]["restarts"].as_array().unwrap().len(), 0);
    let toml = fs::read_to_string(s.p("home/.config/bromigos/idle.toml")).unwrap();
    assert!(toml.contains("[lock]\nenabled = false"), "{toml}");
    let conf = fs::read_to_string(s.p("home/.local/state/bromigos/idle/hypridle.conf")).unwrap();
    assert!(conf.contains("bromigos-live ctl screensaver open"));
    assert!(!conf.contains("on-timeout = loginctl lock-session"));
    assert!(conf.contains("lock_cmd = bromigos lock-run"));
    // a time switches a timer on; an odd order is warned, not refused
    let v = idle_doc(&s, &["idle", "set", "lock", "5", "--json"]);
    assert_eq!(v["policy"]["lock"]["enabled"], true);
    assert!(
        v["warnings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|w| w["key"] == "screensaver.minutes"),
        "{v}"
    );
    // undo: one step back
    let v = idle_doc(&s, &["idle", "undo", "--json"]);
    assert_eq!(v["preset"], "screensaver-only");
    // refused: a bad value, nothing written
    let before = fs::read_to_string(s.p("home/.config/bromigos/idle.toml")).unwrap();
    let o = s.run(&["idle", "set", "lock", "0"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(stderr(&o).contains("out of range"), "{}", stderr(&o));
    assert_eq!(
        fs::read_to_string(s.p("home/.config/bromigos/idle.toml")).unwrap(),
        before
    );
    let o = s.run(&["idle", "preset", "nap"]);
    assert_eq!(o.status.code(), Some(1));
    // back to the defaults
    let v = idle_doc(&s, &["idle", "preset", "default", "--json"]);
    assert_eq!(v["preset"], "default");
    // render prints the config without writing anything
    let o = s.run(&["idle", "render", "--defaults"]);
    assert!(stdout(&o).contains("timeout = 600"));
    // stay awake is off without a live inhibitor (none is started here)
    let v = idle_doc(&s, &["idle", "off", "--json"]);
    assert_eq!(v["stay_awake"]["on"], false);
    assert!(s.run(&["idle", "stay-awake", "soon"]).status.code() == Some(1));
}

#[test]
fn idle_hook_moves_the_users_hypridle_conf() {
    let s = Sandbox::new();
    let f = s.p("home/.config/hypr/hypridle.conf");
    fs::create_dir_all(f.parent().unwrap()).unwrap();
    fs::write(
        &f,
        "source = /usr/share/bromigos/default/hypr/hypridle.conf\nlisteners = mine\nlistener {\n    timeout = 30\n    on-timeout = notify-send hi\n}\n",
    )
    .unwrap();
    let o = s.run(&["idle", "hook"]);
    assert!(o.status.success(), "{}", stderr(&o));
    assert!(stdout(&o).starts_with("moved "), "{}", stdout(&o));
    let t = fs::read_to_string(&f).unwrap();
    assert!(
        t.starts_with("source = ~/.local/state/bromigos/idle/hypridle.conf\n"),
        "{t}"
    );
    assert!(t.contains("on-timeout = notify-send hi"));
    assert!(
        s.p("home/.local/state/bromigos/idle/hypridle.conf")
            .is_file()
    );
    assert!(stdout(&s.run(&["idle", "hook"])).starts_with("kept "));
    let v = idle_doc(&s, &["idle", "--json"]);
    assert_eq!(v["hook"], "rendered");
    // the migration runs the same
    let m = fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../migrations/20261009210000-idle-policy.sh"
    ))
    .unwrap();
    assert!(m.contains("bromigos idle hook"));
}

#[test]
fn restart_knows_idle() {
    let s = Sandbox::new();
    let o = s.run(&["restart", "idle", "--check", "--json"]);
    assert!(o.status.success(), "{}", stderr(&o));
}

/// The public repository's address migration: a [bromigos] Server line that is exactly the
/// r2.dev address moves to pkgs.bromigos.org (the channel's path kept), with a backup; any
/// other line, and a second run, change nothing. `sudo` is a stand-in that runs the command
/// as the user (without install's root ownership).
#[test]
fn migration_moves_the_r2dev_address() {
    let s = Sandbox::new();
    let script = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../migrations/20261010080000-public-repo-address.sh"
    );
    s.script(
        "bin",
        "sudo",
        "#!/bin/bash\na=(); while (($#)); do case $1 in -o|-g) shift 2 ;; *) a+=(\"$1\"); shift ;; esac; done; exec \"${a[@]}\"\n",
    );
    let r2 = "https://pub-725f58eecf5c43748779ba6473eb9720.r2.dev";
    let conf = format!(
        "[options]\nSigLevel = Required\n\n[mine]\nServer = {r2}/$repo/stable/$arch\n\n\
         [bromigos]\nSigLevel = Required DatabaseOptional\nServer = {r2}/$repo/stable/$arch\n"
    );
    fs::write(s.p("pacman.conf"), &conf).unwrap();
    fs::create_dir_all(s.p("home/.local/state/bromigos")).unwrap();
    fs::write(
        s.p("home/.local/state/bromigos/channel.toml"),
        format!("# x\nbase = \"{r2}\"\n"),
    )
    .unwrap();
    let run = |conf: &Path| {
        let mut c = Command::new("bash");
        c.arg(script)
            .env("PATH", format!("{}:/usr/bin:/bin", s.p("bin").display()))
            .env("HOME", s.p("home"))
            .env("XDG_STATE_HOME", s.p("home/.local/state"))
            .env("BROMIGOS_PACMAN_CONF", conf);
        output(c)
    };
    let o = run(&s.p("pacman.conf"));
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let new = fs::read_to_string(s.p("pacman.conf")).unwrap();
    assert!(new.ends_with("[bromigos]\nSigLevel = Required DatabaseOptional\nServer = https://pkgs.bromigos.org/$repo/stable/$arch\n"), "{new}");
    assert!(
        new.contains(&format!("[mine]\nServer = {r2}/$repo/stable/$arch\n")),
        "another section's line stays"
    );
    assert_eq!(
        fs::read_to_string(s.p("pacman.conf.bromigos-r2dev")).unwrap(),
        conf,
        "the backup"
    );
    assert!(
        fs::read_to_string(s.p("home/.local/state/bromigos/channel.toml"))
            .unwrap()
            .contains("base = \"https://pkgs.bromigos.org\"")
    );
    // again: nothing to do
    let o = run(&s.p("pacman.conf"));
    assert!(o.status.success());
    assert_eq!(fs::read_to_string(s.p("pacman.conf")).unwrap(), new);
    // edge's path moves too; a line that isn't exactly the address doesn't
    fs::write(
        s.p("edge.conf"),
        format!("[bromigos]\nServer = {r2}/$repo/$arch\n"),
    )
    .unwrap();
    assert!(run(&s.p("edge.conf")).status.success());
    assert_eq!(
        fs::read_to_string(s.p("edge.conf")).unwrap(),
        "[bromigos]\nServer = https://pkgs.bromigos.org/$repo/$arch\n"
    );
    let near = format!("[bromigos]\nServer = {r2}/$repo/stable/$arch/\n");
    fs::write(s.p("near.conf"), &near).unwrap();
    assert!(run(&s.p("near.conf")).status.success());
    assert_eq!(fs::read_to_string(s.p("near.conf")).unwrap(), near);
    assert!(!s.p("near.conf.bromigos-r2dev").exists());
}
