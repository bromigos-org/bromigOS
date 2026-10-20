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

/// Every theme in the repository renders Zettlr's colours (theme/templates/zettlr.css.tpl).
/// A theme with a golden file must match it (desktop/tests/golden/zettlr/<name>.css; after
/// a reviewed change, write the new render there). One without, such as a newly added
/// variant, must still carry its own palette and mode.
#[test]
fn zettlr_golden_for_each_theme() {
    let d = tempfile::tempdir().unwrap();
    let goldens = repo().join("desktop/tests/golden/zettlr");
    let mut names: Vec<String> = std::fs::read_dir(repo().join("themes"))
        .unwrap()
        .filter_map(|e| e.ok())
        .filter(|e| e.path().join("colors.toml").is_file())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .collect();
    names.sort();
    assert!(names.iter().any(|n| n == "wick") && names.iter().any(|n| n == "tidewell"));
    let mut checked = 0;
    for name in &names {
        let o = run(d.path(), &["theme", "set", name, "--no-reload"]);
        assert!(o.status.success(), "{name}: {}", String::from_utf8_lossy(&o.stderr));
        let current = d.path().join(".local/state/bromigos/theme/current");
        let css = std::fs::read_to_string(current.join("zettlr.css")).unwrap();
        let palette: Value =
            serde_json::from_str(&std::fs::read_to_string(current.join("palette.json")).unwrap()).unwrap();
        let mode = palette["mode"].as_str().unwrap();
        assert!(css.contains(&format!("color-scheme: {mode} !important;")), "{name}");
        for role in ["background", "panel", "primary", "text"] {
            let c = palette["colors"][role].as_str().unwrap();
            assert!(css.contains(&format!("--bromigos-{role}: {c};")), "{name}: {role}");
        }
        assert!(css.contains("\"Geist Mono\""), "{name}: the font");
        if let Ok(golden) = std::fs::read_to_string(goldens.join(format!("{name}.css"))) {
            assert_eq!(css, golden, "{name}: Zettlr's colours changed: review the golden file");
            checked += 1;
        }
    }
    assert!(checked >= 9, "only {checked} goldens");
}

/// The hook's merge, end to end in a throwaway home: a user's own custom.css keeps every
/// rule of theirs, the bromigOS block holds the rendered colours and is replaced, not
/// added, on the next switch; config.json's darkMode is the only key that changes.
#[test]
fn zettlr_hook_keeps_the_users_css_and_settings() {
    let d = tempfile::tempdir().unwrap();
    let zdir = d.path().join(".config/Zettlr");
    std::fs::create_dir_all(&zdir).unwrap();
    let mine = "@import url(\"fonts.css\");\n\n/* mine */\n.cm-editor { font-size: 20px; }\n";
    std::fs::write(zdir.join("custom.css"), mine).unwrap();
    let config = "{\n  \"version\": \"4.8.0\",\n  \"darkMode\": false,\n  \"autoDarkMode\": \"off\",\n  \"display\": {\n    \"theme\": \"bordeaux\"\n  }\n}";
    std::fs::write(zdir.join("config.json"), config).unwrap();
    let current = d.path().join(".local/state/bromigos/theme/current");
    for name in ["tidewell", "wick"] {
        let o = run(d.path(), &["theme", "set", name, "--no-reload"]);
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        let hook = Command::new("python3")
            .arg(repo().join("desktop/lib/bromigos_zettlr.py"))
            .arg(&current)
            .arg(&zdir)
            .env("BROMIGOS_ZETTLR_RUNNING", "0")
            .output()
            .unwrap();
        assert!(hook.status.success(), "{}", String::from_utf8_lossy(&hook.stderr));
    }
    let css = std::fs::read_to_string(zdir.join("custom.css")).unwrap();
    let rendered = std::fs::read_to_string(current.join("zettlr.css")).unwrap();
    assert!(css.starts_with("@import url(\"fonts.css\");\n/* >>> bromigOS theme"), "{css}");
    assert!(css.ends_with("/* <<< bromigOS theme */\n\n/* mine */\n.cm-editor { font-size: 20px; }\n"), "{css}");
    assert!(css.contains(rendered.trim()));
    assert_eq!(css.matches(">>> bromigOS theme").count(), 1);
    assert!(!css.contains("theme \"tidewell\""));
    let after = std::fs::read_to_string(zdir.join("config.json")).unwrap();
    assert_eq!(after, config.replace("\"darkMode\": false", "\"darkMode\": true"));
}
