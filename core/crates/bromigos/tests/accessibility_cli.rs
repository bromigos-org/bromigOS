//! `bromigos accessibility` (and `a11y`, and `bromigos setup accessibility`) end to end, in
//! a temp HOME and runtime dir with the repository as the share dir. No session is found
//! there, so nothing is ever signalled or restarted (that's the command's own rule, tested
//! here too); the sandbox has no Hyprland, waybar or gsettings.

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

fn palette(home: &Path) -> Value {
    let p = home.join(".local/state/bromigos/theme/current/palette.json");
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

#[test]
fn status_shows_the_defaults_until_set() {
    let d = tempfile::tempdir().unwrap();
    let doc = json(&run(d.path(), &["accessibility", "--json"]));
    assert_eq!(doc["schema"], 1);
    assert_eq!(doc["accessibility"]["motion"], "full");
    assert_eq!(doc["accessibility"]["contrast"], "normal");
    assert_eq!(doc["accessibility"]["exists"], false);
    assert_eq!(doc["theme"], "wick");
    assert_eq!(doc["contrast"]["mode"], "normal");
    // `a11y` is the same command
    let doc2 = json(&run(d.path(), &["a11y", "status", "--json"]));
    assert_eq!(doc2["accessibility"], doc["accessibility"]);
    let o = run(d.path(), &["accessibility"]);
    assert!(o.status.success());
    assert!(String::from_utf8_lossy(&o.stdout).contains("motion    full"));
}

#[test]
fn motion_and_contrast_write_the_file_and_render_the_theme() {
    let d = tempfile::tempdir().unwrap();
    let home = d.path();
    // no session in the sandbox: the theme renders, nothing is told (no --no-reload needed)
    let o = run(home, &["accessibility", "motion", "reduced", "--json"]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let doc = json(&o);
    assert_eq!(doc["ok"], true);
    assert_eq!(doc["accessibility"]["motion"], "reduced");
    assert_eq!(doc["theme"]["motion"], "reduced");
    let r = doc["reloads"].as_array().unwrap();
    assert_eq!(r.len(), 1, "{r:?}");
    assert_eq!(r[0]["app"], "desktop");
    assert!(
        r[0]["detail"]
            .as_str()
            .unwrap()
            .contains("no running session")
    );
    assert_eq!(palette(home)["motion"], "reduced");
    let hl = std::fs::read_to_string(home.join(".local/state/bromigos/theme/current/hyprland.lua"))
        .unwrap();
    assert!(hl.contains("motion   = \"reduced\""));

    let doc = json(&run(
        home,
        &["a11y", "contrast", "high", "--no-reload", "--json"],
    ));
    assert_eq!(doc["accessibility"]["contrast"], "high");
    assert_eq!(
        doc["accessibility"]["motion"], "reduced",
        "the other key kept"
    );
    assert_eq!(doc["theme"]["contrast"]["mode"], "high");
    assert_eq!(doc["theme"]["contrast"]["ok"], true);
    assert_eq!(doc["reloads"], serde_json::json!([]));
    let p = palette(home);
    assert_eq!(p["contrast"]["mode"], "high");
    assert_eq!(p["contrast"]["ok"], true);

    // theme set renders with them too, and says so
    let doc = json(&run(
        home,
        &["theme", "set", "mire", "--no-reload", "--json"],
    ));
    assert_eq!(doc["contrast"]["mode"], "high");
    assert_eq!(doc["motion"], "reduced");
    let text = run(home, &["theme", "set", "--no-reload"]);
    assert!(String::from_utf8_lossy(&text.stdout).contains("accessibility: contrast high"));

    let file = std::fs::read_to_string(home.join(".config/bromigos/accessibility.toml")).unwrap();
    assert!(file.starts_with("# Accessibility"));
    assert!(file.contains("motion = \"reduced\"") && file.contains("contrast = \"high\""));

    // back to normal: the theme's own colours
    json(&run(
        home,
        &[
            "accessibility",
            "contrast",
            "normal",
            "--no-reload",
            "--json",
        ],
    ));
    assert_eq!(palette(home)["contrast"]["mode"], "normal");
}

#[test]
fn bad_levels_are_refused() {
    let d = tempfile::tempdir().unwrap();
    let o = run(d.path(), &["accessibility", "motion", "sideways"]);
    assert_eq!(o.status.code(), Some(2));
    assert!(
        !d.path()
            .join(".config/bromigos/accessibility.toml")
            .exists()
    );
}

#[test]
fn check_measures_every_repository_theme() {
    let d = tempfile::tempdir().unwrap();
    for name in [
        "wick", "mire", "tidewell", "rime", "sunder", "cinder", "lowtown", "highwind", "deepvein",
        "wick-tidewell", "wick-mire",
    ] {
        let o = run(d.path(), &["accessibility", "check", name, "--json"]);
        assert!(
            o.status.success(),
            "{name}: {}",
            String::from_utf8_lossy(&o.stdout)
        );
        let doc = json(&o);
        assert_eq!(doc["high"]["ok"], true, "{name}");
        assert_eq!(doc["normal"]["mode"], "normal");
        assert!(doc["high"]["checks"].as_array().unwrap().len() > 40);
    }
    let o = run(d.path(), &["accessibility", "check", "nope"]);
    assert_eq!(o.status.code(), Some(1));
}

#[test]
fn setup_takes_an_accessibility_section() {
    let d = tempfile::tempdir().unwrap();
    let home = d.path();
    let o = run(
        home,
        &[
            "setup",
            "accessibility",
            "--motion",
            "still",
            "--contrast",
            "high",
            "--json",
        ],
    );
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let doc = json(&o);
    let s = &doc["setup"][0];
    assert_eq!(s["section"], "accessibility");
    assert_eq!(s["ok"], true);
    let p = palette(home);
    assert_eq!(
        (p["motion"].as_str(), p["contrast"]["mode"].as_str()),
        (Some("still"), Some("high"))
    );

    let answers = home.join("a.toml");
    std::fs::write(&answers, "[accessibility]\nmotion = \"full\"\n").unwrap();
    let doc = json(&run(
        home,
        &[
            "setup",
            "accessibility",
            "--answers",
            answers.to_str().unwrap(),
            "--json",
        ],
    ));
    assert_eq!(doc["setup"][0]["ok"], true);
    let st = json(&run(home, &["accessibility", "--json"]));
    assert_eq!(st["accessibility"]["motion"], "full");
    assert_eq!(st["accessibility"]["contrast"], "high", "left out: kept");
}
