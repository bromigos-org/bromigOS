//! `bromigos whats-new`: the release notes installed with bromigos-core.
//!
//! The notes are the manual's "What's new" page (`manual/src/whats-new.md`, written when a
//! release is prepared: docs/release.md), installed as `/usr/share/bromigos/whats-new.md`,
//! so they read offline. Each release is a section:
//!
//! ```text
//! ## 0.1.2
//! <!-- release: 0.1.2-rc1 -->
//! …
//! ```
//!
//! The heading is the version people know; the comment names the exact release (an rc
//! keeps its name when the same build is promoted to stable). The newest section is the
//! first. `bromigos update` says once that a new release came with it: the release told is
//! kept in `~/.local/state/bromigos/whats-new` (the comment's name).

use std::fs;
use std::path::PathBuf;

use crate::paths::Paths;

/// One release's notes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Release {
    /// The heading's version (`0.1.2`).
    pub version: String,
    /// The exact release (`0.1.2-rc1`, or `0.1.2`).
    pub id: String,
    /// The section's text after its heading and marker, Markdown.
    pub text: String,
}

/// `/usr/share/bromigos/whats-new.md` (BROMIGOS_SHARE_DIR moves it).
pub fn file(paths: &Paths) -> PathBuf {
    paths.share_dir.join("whats-new.md")
}

/// The release told last, as `bromigos update` and `bromigos whats-new` record it.
pub fn seen_file(paths: &Paths) -> PathBuf {
    paths.user_state_dir().join("whats-new")
}

/// The releases in a whats-new.md, newest first: each `## ` heading followed by a
/// `<!-- release: ID -->` line. Headings without the marker (the page's own) are text.
pub fn parse(md: &str) -> Vec<Release> {
    let lines: Vec<&str> = md.lines().collect();
    let mut starts = vec![];
    for (i, w) in lines.windows(2).enumerate() {
        if let (Some(v), Some(id)) = (w[0].strip_prefix("## "), marker(w[1])) {
            starts.push((i, v.trim().to_owned(), id));
        }
    }
    starts
        .iter()
        .enumerate()
        .map(|(n, (i, version, id))| {
            let end = starts.get(n + 1).map_or(lines.len(), |s| s.0);
            Release {
                version: version.clone(),
                id: id.clone(),
                text: lines[i + 2..end].join("\n").trim().to_owned(),
            }
        })
        .collect()
}

fn marker(line: &str) -> Option<String> {
    let id = line
        .trim()
        .strip_prefix("<!-- release:")?
        .strip_suffix("-->")?
        .trim();
    (!id.is_empty()).then(|| id.to_owned())
}

/// The installed releases, newest first (none when the file isn't there).
pub fn installed(paths: &Paths) -> Vec<Release> {
    fs::read_to_string(file(paths))
        .map(|t| parse(&t))
        .unwrap_or_default()
}

/// The release this user was told about last.
pub fn seen(paths: &Paths) -> Option<String> {
    fs::read_to_string(seen_file(paths))
        .ok()
        .map(|s| s.trim().to_owned())
        .filter(|s| !s.is_empty())
}

pub fn mark_seen(paths: &Paths, id: &str) -> std::io::Result<()> {
    let f = seen_file(paths);
    if let Some(d) = f.parent() {
        fs::create_dir_all(d)?;
    }
    fs::write(f, format!("{id}\n"))
}

/// After an update: the newest installed release when this user hasn't been told about it
/// yet (it's then recorded as told). None when there are no notes, or nothing new.
pub fn announce(paths: &Paths) -> Option<Release> {
    let newest = installed(paths).into_iter().next()?;
    if seen(paths).as_deref() == Some(newest.id.as_str()) {
        return None;
    }
    let _ = mark_seen(paths, &newest.id);
    Some(newest)
}

#[cfg(test)]
mod tests {
    use super::*;

    const MD: &str = "# What's new\n\nIntro.\n\n## Not a release\n\ntext\n\n\
<!-- releases: … -->\n\n## 0.1.3\n<!-- release: 0.1.3-rc2 -->\n\n*rc*\n\n### New\n\n- a\n\n\
## 0.1.2\n<!-- release: 0.1.2 -->\n\nOlder.\n";

    #[test]
    fn sections_newest_first() {
        let r = parse(MD);
        assert_eq!(r.len(), 2);
        assert_eq!((r[0].version.as_str(), r[0].id.as_str()), ("0.1.3", "0.1.3-rc2"));
        assert_eq!(r[0].text, "*rc*\n\n### New\n\n- a");
        assert_eq!((r[1].version.as_str(), r[1].text.as_str()), ("0.1.2", "Older."));
        assert!(parse("# What's new\n\nNothing yet.\n").is_empty());
    }

    #[test]
    fn announced_once() {
        let d = tempfile::tempdir().unwrap();
        let p = Paths::from_lookup(|k| match k {
            "HOME" => Some(d.path().into()),
            "BROMIGOS_SHARE_DIR" => Some(d.path().join("share")),
            _ => None,
        });
        assert_eq!(announce(&p), None, "no notes installed");
        fs::create_dir_all(&p.share_dir).unwrap();
        fs::write(file(&p), MD).unwrap();
        assert_eq!(announce(&p).map(|r| r.id), Some("0.1.3-rc2".into()));
        // told already: and an rc promoted to stable is the same file, so nothing new either
        assert_eq!(announce(&p), None);
        assert_eq!(seen(&p).as_deref(), Some("0.1.3-rc2"));
        // a release prepared as stable after its rcs is a new one
        fs::write(file(&p), MD.replace("0.1.3-rc2", "0.1.3")).unwrap();
        assert_eq!(announce(&p).map(|r| r.version), Some("0.1.3".into()));
    }
}
