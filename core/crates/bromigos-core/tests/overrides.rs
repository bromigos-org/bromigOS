//! The animation switches on disk: round trip, reset, and the move from the old
//! location.

use std::fs;
use std::path::{Path, PathBuf};

use bromigos_core::config::{self, Overrides};
use bromigos_core::paths::Paths;

fn paths(home: &Path) -> Paths {
    let home = home.to_path_buf();
    Paths::from_lookup(move |k| match k {
        "HOME" => Some(home.clone()),
        "XDG_RUNTIME_DIR" => Some(home.join("run")),
        "BROMIGOS_SHARE_DIR" => Some(home.join("share")),
        _ => None,
    })
}

fn write(p: &PathBuf, text: &str) {
    fs::create_dir_all(p.parent().unwrap()).unwrap();
    fs::write(p, text).unwrap();
}

#[test]
fn round_trip_keeps_comments_and_reset_removes_keys() {
    let d = tempfile::tempdir().unwrap();
    let p = paths(d.path());
    write(
        &p.live_overrides,
        "# my switches\n\n[space]\n# ships off at night\ntraffic = false  # noisy\n\n[general]\nfps = 12\n",
    );
    let mut ov = Overrides::load(&p).unwrap();
    assert_eq!(ov.source.as_deref(), Some(p.live_overrides.as_path()));
    ov.set("rain", "enabled", false).unwrap();
    ov.set("space", "traffic", true).unwrap();
    ov.save(&p).unwrap();
    let text = fs::read_to_string(&p.live_overrides).unwrap();
    assert_eq!(
        text,
        "# my switches\n\n[space]\n# ships off at night\ntraffic = true  # noisy\n\n[general]\nfps = 12\n\n[rain]\nenabled = false\n"
    );

    let mut ov = Overrides::load(&p).unwrap();
    ov.remove("space", "traffic");
    ov.remove("rain", "enabled");
    ov.save(&p).unwrap();
    assert_eq!(
        fs::read_to_string(&p.live_overrides).unwrap(),
        "# my switches\n\n[general]\nfps = 12\n"
    );
}

#[test]
fn legacy_file_is_read_then_moved_on_write() {
    let d = tempfile::tempdir().unwrap();
    let p = paths(d.path());
    write(
        &p.live_overrides_legacy,
        "# Old header (bromigos anim …). Safe to delete.\n\n[rain]\nenabled = false\n",
    );
    let mut ov = Overrides::load(&p).unwrap();
    assert_eq!(
        ov.source.as_deref(),
        Some(p.live_overrides_legacy.as_path())
    );
    assert!(ov.contains("rain", "enabled"));
    assert!(!p.live_overrides.exists());

    ov.set("sounds", "enabled", false).unwrap();
    ov.save(&p).unwrap();
    assert!(!p.live_overrides_legacy.exists(), "nothing left behind");
    assert_eq!(
        fs::read_to_string(&p.live_overrides).unwrap(),
        "# Old header (bromigos anim …). Safe to delete.\n\n[rain]\nenabled = false\n\n[sounds]\nenabled = false\n"
    );
    let tmp = p.live_overrides.with_extension("toml.tmp");
    assert!(!tmp.exists());
}

#[test]
fn new_location_wins_over_legacy() {
    let d = tempfile::tempdir().unwrap();
    let p = paths(d.path());
    write(&p.live_overrides_legacy, "[rain]\nenabled = false\n");
    write(&p.live_overrides, "# mine\n[rain]\nenabled = true\n");
    let ov = Overrides::load(&p).unwrap();
    assert_eq!(
        config::lookup(&ov.table(), "rain", "enabled"),
        Some(&toml::Value::Boolean(true))
    );
}

#[test]
fn merged_over_the_live_config() {
    let d = tempfile::tempdir().unwrap();
    let p = paths(d.path());
    // only the packaged default exists
    write(
        &p.live_config_default(),
        "[rain]\nenabled = true\nbursts = false\n[space]\nstars = true\n",
    );
    write(&p.live_overrides, "[rain]\nenabled = false\n");
    let (merged, _) = config::load_merged(&p).unwrap();
    assert_eq!(
        config::lookup(&merged, "rain", "enabled"),
        Some(&toml::Value::Boolean(false))
    );
    assert_eq!(
        config::lookup(&merged, "rain", "bursts"),
        Some(&toml::Value::Boolean(false))
    );
    // the user's live config, when present, comes before the packaged default
    write(&p.live_config, "[space]\nstars = false\n");
    let (merged, _) = config::load_merged(&p).unwrap();
    assert_eq!(
        config::lookup(&merged, "space", "stars"),
        Some(&toml::Value::Boolean(false))
    );
    assert_eq!(config::lookup(&merged, "rain", "bursts"), None);
}

#[test]
fn broken_file_is_not_overwritten() {
    let d = tempfile::tempdir().unwrap();
    let p = paths(d.path());
    write(&p.live_overrides, "[rain\nenabled = false\n");
    assert!(Overrides::load(&p).is_err());
    assert_eq!(
        fs::read_to_string(&p.live_overrides).unwrap(),
        "[rain\nenabled = false\n"
    );
}
