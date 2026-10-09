//! The private overlay at login: bromigos-core's user units (packaging/bromigos-core's
//! bromigos-private.service and .path) run `bromigos-private decrypt --quiet` when a
//! session starts and when the encrypted file changes. Here: the units name the script and
//! the file it reads, and the script does nothing, quietly, without the age key.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn unit(name: &str) -> String {
    fs::read_to_string(repo().join("packaging/bromigos-core").join(name)).unwrap()
}

/// `key=value` lines of a unit file, in order.
fn settings(text: &str) -> Vec<(String, String)> {
    text.lines()
        .filter(|l| !l.starts_with('#'))
        .filter_map(|l| l.split_once('='))
        .map(|(k, v)| (k.trim().to_owned(), v.trim().to_owned()))
        .collect()
}

#[test]
fn the_units_run_decrypt_on_the_overlays_file() {
    let script = fs::read_to_string(repo().join("bin/bromigos-private")).unwrap();
    // the file the script decrypts: ~/.config/bromigos/private.sops.yaml
    assert!(script.contains(r#"SRC = os.path.join(BASE, "private.sops.yaml")"#));
    assert!(script.contains(r#"BASE = os.path.join(HOME, ".config/bromigos")"#));
    let file = "%h/.config/bromigos/private.sops.yaml".to_owned();

    let service = settings(&unit("bromigos-private.service"));
    let get = |s: &[(String, String)], k: &str| {
        s.iter()
            .filter(|(key, _)| key == k)
            .map(|(_, v)| v.clone())
            .collect::<Vec<_>>()
    };
    assert_eq!(
        get(&service, "ExecStart"),
        ["/usr/lib/bromigos/bin/bromigos-private decrypt --quiet"]
    );
    assert_eq!(get(&service, "ConditionPathExists"), [file.clone()]);
    assert_eq!(get(&service, "Type"), ["oneshot"]);
    assert_eq!(get(&service, "WantedBy"), ["default.target"]);

    let path = settings(&unit("bromigos-private.path"));
    assert_eq!(get(&path, "PathChanged"), [file]);
    assert_eq!(get(&path, "Unit"), ["bromigos-private.service"]);

    // bromigos-core installs the script where ExecStart looks, and both units enabled
    let pkgbuild = fs::read_to_string(repo().join("packaging/bromigos-core/PKGBUILD")).unwrap();
    assert!(pkgbuild.contains(r#""$pkgdir/usr/lib/bromigos/bin/" "$_root"/bin/bromigos-private"#));
    assert!(pkgbuild.contains("for u in bromigos-private.service bromigos-private.path; do"));
    assert!(
        pkgbuild
            .contains(r#"ln -s "../$u" "$pkgdir/usr/lib/systemd/user/default.target.wants/$u""#)
    );
}

#[test]
fn without_the_age_key_decrypt_does_nothing_quietly() {
    let home = tempfile::tempdir().unwrap();
    let cfg = home.path().join(".config/bromigos");
    fs::create_dir_all(&cfg).unwrap();
    // the encrypted file is there (the unit's condition holds), the key isn't
    fs::write(cfg.join("private.sops.yaml"), "env: ENC[…]\n").unwrap();
    let out = Command::new("python3")
        .arg(repo().join("bin/bromigos-private"))
        .args(["decrypt", "--quiet"])
        .env_clear()
        .env("HOME", home.path())
        .env("PATH", "/usr/bin:/bin")
        .output()
        .unwrap();
    assert!(out.status.success(), "{out:?}");
    assert!(out.stdout.is_empty() && out.stderr.is_empty(), "{out:?}");
    assert!(!cfg.join("private").exists());
}
