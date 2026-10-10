//! `bromigos theme` end to end, in a temp HOME with the repository as the share dir.
//! Always `--no-reload`: a test must never signal the real waybar, kitty or Hyprland.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use serde_json::Value;

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn run(home: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_bromigos"))
        .args(args)
        .env_clear()
        .env("HOME", home)
        .env("XDG_RUNTIME_DIR", home.join("run"))
        .env("BROMIGOS_SHARE_DIR", repo())
        .env("BROMIGOS_LIB_BIN", home.join("lib"))
        .env("PATH", home.join("bin"))
        .output()
        .unwrap()
}

fn json(o: &Output) -> Value {
    serde_json::from_slice(&o.stdout).unwrap_or_else(|e| {
        panic!(
            "{e}: {}{}",
            String::from_utf8_lossy(&o.stdout),
            String::from_utf8_lossy(&o.stderr)
        )
    })
}

#[test]
fn list_current_set() {
    let d = tempfile::tempdir().unwrap();
    let home = d.path();

    let cur = json(&run(home, &["theme", "current", "--json"]));
    assert_eq!(cur["schema"], 1);
    assert_eq!(cur["name"], "wick");
    assert_eq!(cur["set"], false);
    assert_eq!(cur["default"], "wick");

    let list = json(&run(home, &["theme", "list", "--json"]));
    let names: Vec<&str> = list["themes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["name"].as_str().unwrap())
        .collect();
    assert!(names.contains(&"wick"));
    assert_eq!(list["current"], "wick");

    // no name: the current (here the default) theme
    let o = run(home, &["theme", "set", "--no-reload", "--json"]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let set = json(&o);
    assert_eq!(set["name"], "wick");
    assert_eq!(set["display_name"], "Wick");
    assert_eq!(set["reloads"], serde_json::json!([]));
    let dir = home.join(".local/state/bromigos/theme/current");
    assert_eq!(set["dir"], dir.to_str().unwrap());
    for f in [
        "waybar.css",
        "rofi.rasi",
        "kitty.conf",
        "hyprland.lua",
        "name",
    ] {
        assert!(dir.join(f).is_file(), "{f}");
    }

    let cur = json(&run(home, &["theme", "current", "--json"]));
    assert_eq!(cur["set"], true);
    let o = run(home, &["theme", "current"]);
    assert_eq!(String::from_utf8_lossy(&o.stdout), "wick\n");
}

#[test]
fn unknown_theme_exits_1_and_writes_nothing() {
    let d = tempfile::tempdir().unwrap();
    let o = run(d.path(), &["theme", "set", "nope", "--no-reload"]);
    assert_eq!(o.status.code(), Some(1));
    let err = String::from_utf8_lossy(&o.stderr);
    assert!(
        err.contains("unknown theme: nope") && err.contains("wick"),
        "{err}"
    );
    assert!(
        !d.path()
            .join(".local/state/bromigos/theme/current")
            .exists()
    );
}

#[test]
fn other_theme_words_go_to_the_router() {
    let d = tempfile::tempdir().unwrap();
    let o = run(d.path(), &["theme", "frobnicate"]);
    // no bromigos-theme-frobnicate anywhere: the router's "unknown command"
    assert_eq!(
        o.status.code(),
        Some(2),
        "{}",
        String::from_utf8_lossy(&o.stderr)
    );
}

/// Every shipped palette must produce the reviewed mehshell colours.
#[test]
fn mehshell_golden_for_each_theme() {
    let d = tempfile::tempdir().unwrap();
    for name in ["wick", "rime", "sunder", "cinder", "lowtown", "highwind", "deepvein", "tidewell", "mire"] {
        let o = run(d.path(), &["theme", "set", name, "--no-reload"]);
        assert!(o.status.success(), "{name}: {}", String::from_utf8_lossy(&o.stderr));
        let palette = d.path().join(".local/state/bromigos/theme/current/palette.json");
        let config = d.path().join("mehshell-config");
        let _ = std::fs::remove_file(&config);
        let generated = Command::new("python")
            .arg(repo().join("live/tools/make-mehshell.py"))
            .arg(palette).arg(&config)
            .env("HOME", d.path()).env("XDG_CACHE_HOME", d.path().join("cache"))
            .output().unwrap();
        assert!(generated.status.success(), "{}", String::from_utf8_lossy(&generated.stderr));
        let actual = std::fs::read_to_string(config).unwrap();
        let golden = std::fs::read_to_string(repo().join(format!("live/tests/golden/mehshell/{name}.config"))).unwrap();
        assert!(actual.ends_with(&golden), "{name} colours changed: review the golden file");
    }
}
