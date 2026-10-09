//! The theme switcher's previews: each theme drawn offscreen as a miniature screenshot of
//! the desktop wearing it, by `bromigos-theme-previews` (package bromigos-desktop;
//! docs/theming.md, "The previews"). They're started here in the background whenever a
//! theme may have changed: after `bromigos update`, `bromigos ext install`/`update` of a
//! theme, and `bromigos theme new`. The renderer only draws what is missing or out of
//! date, waits its turn behind a run already going, and never touches the desktop.

use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// The renderer's command.
pub const COMMAND: &str = "bromigos-theme-previews";

/// `bromigos-theme-previews` on PATH (None without bromigos-desktop, or when
/// `BROMIGOS_NO_PREVIEWS` is set: tests, a headless box that never shows the switcher).
pub fn renderer() -> Option<PathBuf> {
    if std::env::var_os("BROMIGOS_NO_PREVIEWS").is_some_and(|v| !v.is_empty()) {
        return None;
    }
    find_on(std::env::var_os("PATH").as_deref())
}

fn find_on(path: Option<&OsStr>) -> Option<PathBuf> {
    std::env::split_paths(path?)
        .map(|d| d.join(COMMAND))
        .find(|p| p.is_file())
}

/// The arguments for a background run: `names` (none: every installed theme), or one
/// theme from a directory that isn't installed (`bromigos theme new`'s).
pub fn args(names: &[String], dir: Option<&Path>) -> Vec<String> {
    let mut a = vec!["--quiet".to_owned()];
    match dir {
        Some(d) => {
            a.push("--dir".into());
            a.push(d.display().to_string());
        }
        None => a.extend(names.iter().cloned()),
    }
    a
}

/// Starts the renderer detached (its own session, niced, no pipes of ours: it outlives
/// this command). Returns what was started, for the command's output, or None when
/// there's no renderer here or it couldn't start.
pub fn render_in_background(names: &[String], dir: Option<&Path>) -> Option<String> {
    let exe = renderer()?;
    let a = args(names, dir);
    let ok = Command::new("setsid")
        .arg("-f")
        .args(["nice", "-n", "10"])
        .arg(&exe)
        .args(&a)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|s| s.success());
    ok.then(|| {
        let what = match (dir, names) {
            (Some(d), _) => format!("the theme in {}", d.display()),
            (None, []) => "any theme whose preview is missing or out of date".to_owned(),
            (None, n) => n.join(", "),
        };
        format!("drawing the switcher's previews in the background: {what} (bromigos theme previews --list)")
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn args_name_themes_or_a_directory() {
        assert_eq!(args(&[], None), vec!["--quiet"]);
        assert_eq!(
            args(&["mire".into(), "wick".into()], None),
            vec!["--quiet", "mire", "wick"]
        );
        assert_eq!(
            args(&["ignored".into()], Some(Path::new("/tmp/my-theme"))),
            vec!["--quiet", "--dir", "/tmp/my-theme"]
        );
    }

    #[test]
    fn the_renderer_is_found_on_path_only() {
        let d = tempfile::tempdir().unwrap();
        assert_eq!(find_on(Some(d.path().as_os_str())), None);
        let exe = d.path().join(COMMAND);
        std::fs::write(&exe, "#!/bin/sh\n").unwrap();
        std::fs::set_permissions(&exe, std::fs::Permissions::from_mode(0o755)).unwrap();
        let path = std::env::join_paths([Path::new("/nonexistent"), d.path()]).unwrap();
        assert_eq!(find_on(Some(&path)), Some(exe));
        assert_eq!(find_on(None), None);
    }
}
