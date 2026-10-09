//! `bromigos art` end to end, offline: a world whose plan holds only local steps
//! needs no credentials and no network. (The nolgia path is tested against a mock
//! API in bromigos-art's tests.)

use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use serde_json::Value;

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn run(home: &Path, cwd: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_bromigos"))
        .args(args)
        .current_dir(cwd)
        .env_clear()
        .env("HOME", home)
        .env("XDG_RUNTIME_DIR", home.join("run"))
        .env("BROMIGOS_SHARE_DIR", home.join("share"))
        .env("PATH", "/usr/bin:/bin")
        // Never the real account: nothing here may reach nolgia.
        .env("NOLGIA_BIN", "/nonexistent")
        .env("NOLGIA_BASE_URL", "http://127.0.0.1:9")
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

const ART: &str = r#"
format = 1

[[assets]]
id = "comp"
kind = "image"
model = "gpt-image-2.5-flare"
prompt = "a bayou"
out = "art/comp.png"

[[assets]]
id = "layers"
kind = "command"
run = ["cp", "{in}", "{out}"]
inputs = ["@comp"]
outs = ["backgrounds/layers/00-sky.png"]
"#;

#[test]
fn status_mark_plan_run_offline() {
    let d = tempfile::tempdir().unwrap();
    let home = d.path();
    // A checkout: themes/w/ found from a directory below it.
    let theme = home.join("src/themes/w");
    std::fs::create_dir_all(theme.join("art")).unwrap();
    std::fs::create_dir_all(home.join("src/deep/er")).unwrap();
    std::fs::write(theme.join("art.toml"), ART).unwrap();
    let cwd = home.join("src/deep/er");

    let st = json(&run(home, &cwd, &["art", "status", "w", "--json"]));
    assert_eq!(st["schema"], 1);
    assert_eq!(st["world"], "w");
    assert_eq!(st["spent"], 0);
    let states: Vec<&str> = st["assets"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["state"].as_str().unwrap())
        .collect();
    assert_eq!(states, ["new", "new"]);
    assert_eq!(st["assets"][1]["needs"], serde_json::json!(["comp"]));

    // The comp was painted elsewhere: mark it, with what it cost.
    let o = run(home, &cwd, &["art", "mark", "w", "comp", "--json"]);
    assert!(!o.status.success(), "marked without its output");
    std::fs::write(theme.join("art/comp.png"), "png").unwrap();
    let m = json(&run(
        home,
        &cwd,
        &[
            "art",
            "mark",
            "w",
            "comp",
            "--credits",
            "8",
            "--job",
            "j1",
            "--json",
        ],
    ));
    assert_eq!(m["record"]["status"], "marked");
    assert_eq!(m["record"]["credits"], 8);

    // Only a local step is left: planned and run without credentials.
    let p = json(&run(home, &cwd, &["art", "plan", "w", "--json"]));
    assert_eq!(p["ok"], true);
    assert_eq!(p["credits"], 0);
    assert_eq!(p["auth"], Value::Null);
    assert_eq!(p["assets"][0]["id"], "layers");
    assert_eq!(p["skipped"], serde_json::json!(["comp"]));
    let o = run(home, &cwd, &["art", "run", "w", "--json"]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let r = json(&o);
    assert_eq!(r["ok"], true);
    assert_eq!(r["spent"], 0);
    assert_eq!(r["ran"][0]["status"], "succeeded");
    assert_eq!(
        std::fs::read_to_string(theme.join("backgrounds/layers/00-sky.png")).unwrap(),
        "png"
    );

    let st = json(&run(home, &cwd, &["art", "status", "w", "--json"]));
    assert_eq!(st["spent"], 8);
    assert!(
        st["assets"]
            .as_array()
            .unwrap()
            .iter()
            .all(|a| a["state"] == "done")
    );
    let text = run(home, &cwd, &["art", "plan", "w"]);
    assert!(String::from_utf8_lossy(&text.stdout).contains("nothing to make"));

    // Asking for the comp again needs nolgia: no credentials here, so it fails
    // cleanly and spends nothing.
    let o = run(home, &cwd, &["art", "run", "w", "comp", "--force"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&o.stderr).contains("nolgia auth login"));
}

#[test]
fn unknown_worlds_and_assets_are_errors() {
    let d = tempfile::tempdir().unwrap();
    let o = run(d.path(), d.path(), &["art", "status", "nowhere"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&o.stderr).contains("no art.toml for \"nowhere\""));
}

#[test]
fn the_repository_worlds_parse_and_are_made() {
    // Every first-party art.toml loads, and its log knows every asset (the
    // sources under art/ aren't in git, so they may be missing here).
    let home = tempfile::tempdir().unwrap();
    for world in ["mire", "tidewell"] {
        let dir = repo().join("themes").join(world);
        if !dir.join("art.toml").exists() {
            continue;
        }
        let o = run(
            home.path(),
            home.path(),
            &[
                "art",
                "status",
                world,
                "--dir",
                dir.to_str().unwrap(),
                "--json",
            ],
        );
        let st = json(&o);
        for a in st["assets"].as_array().unwrap() {
            let s = a["state"].as_str().unwrap();
            assert!(
                s == "done" || s == "missing",
                "{world}/{}: {s} ({})",
                a["id"],
                a["reason"]
            );
        }
    }
}
