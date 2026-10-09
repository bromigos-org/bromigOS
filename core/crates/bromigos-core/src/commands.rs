//! The command router: `bromigos <group> <name> [args…]` reaches any executable
//! `bromigos-<group>-<name>` (or `bromigos-<group>` for the group's root) in
//! `/usr/lib/bromigos/bin` or on `PATH`, the way git and cargo find their plugins.
//! Built-in commands always come first.
//!
//! Each external command may describe itself in its first comment block (after an
//! optional `#!` line, within the first 80 lines):
//!
//! ```sh
//! #!/bin/sh
//! # bromigos:summary=Toggle the night light
//! # bromigos:args=[on|off]
//! # bromigos:examples=bromigos toggle nightlight on
//! # bromigos:hidden=true
//! ```
//!
//! Unknown or malformed `bromigos:` keys are ignored; `examples` may repeat.

use std::collections::HashMap;
use std::ffi::{OsStr, OsString};
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::paths::Paths;

/// Lines read when looking for the header.
pub const HEADER_LINES: usize = 80;
const HEADER_BYTES: u64 = 64 * 1024;

/// What an external command says about itself.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Header {
    pub summary: Option<String>,
    pub args: Option<String>,
    pub examples: Vec<String>,
    pub hidden: bool,
}

/// Reads the header of an executable (empty for binaries and unreadable files).
pub fn read_header(path: &Path) -> Header {
    match fs::File::open(path) {
        Ok(f) => parse_header(BufReader::new(f.take(HEADER_BYTES))),
        Err(_) => Header::default(),
    }
}

/// Parses the first comment block.
pub fn parse_header(mut r: impl BufRead) -> Header {
    let mut h = Header::default();
    let mut started = false;
    let mut buf = Vec::new();
    for n in 0..HEADER_LINES {
        buf.clear();
        match r.read_until(b'\n', &mut buf) {
            Ok(0) | Err(_) => break,
            Ok(_) => {}
        }
        if buf.contains(&0) {
            return Header::default(); // a binary
        }
        let line = String::from_utf8_lossy(&buf);
        let line = line.trim();
        if n == 0 && line.starts_with("#!") {
            continue;
        }
        if !started && line.is_empty() {
            continue;
        }
        let Some(comment) = line.strip_prefix('#') else {
            break; // the block ended
        };
        started = true;
        let comment = comment.trim_start_matches('#').trim();
        let Some(kv) = comment.strip_prefix("bromigos:") else {
            continue;
        };
        let Some((key, value)) = kv.split_once('=') else {
            continue;
        };
        let value = value.trim();
        match key.trim() {
            "summary" if !value.is_empty() => h.summary = Some(value.to_owned()),
            "args" if !value.is_empty() => h.args = Some(value.to_owned()),
            "examples" if !value.is_empty() => h.examples.push(value.to_owned()),
            "hidden" => h.hidden = value.eq_ignore_ascii_case("true"),
            _ => {}
        }
    }
    h
}

/// Where external commands are looked for: `/usr/lib/bromigos/bin`, then installed
/// extensions' (`~/.local/share/bromigos/ext/active/bin`, `bromigos ext`), then `PATH`.
/// Duplicates and relative entries are dropped.
pub fn search_dirs(paths: &Paths, path_var: Option<&OsStr>) -> Vec<PathBuf> {
    let mut seen = Vec::new();
    let path_dirs = path_var.map(|p| std::env::split_paths(p).collect::<Vec<_>>());
    for d in [paths.lib_bin.clone(), paths.ext_active("bin")]
        .into_iter()
        .chain(path_dirs.into_iter().flatten())
    {
        if d.is_absolute() && !seen.contains(&d) {
            seen.push(d);
        }
    }
    seen
}

/// Whether `file` is a valid command file name (`bromigos-<group>[-<name>]`).
pub fn is_command_name(file: &str) -> bool {
    command_parts(file).is_some()
}

/// A valid command file name: `bromigos-` then lowercase words joined by `-`.
fn command_parts(file: &str) -> Option<(&str, Option<&str>)> {
    let rest = file.strip_prefix("bromigos-")?;
    let ok = !rest.is_empty()
        && !rest.starts_with('-')
        && !rest.ends_with('-')
        && !rest.contains("--")
        && rest
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-');
    if !ok {
        return None;
    }
    Some(match rest.split_once('-') {
        Some((g, n)) => (g, Some(n)),
        None => (rest, None),
    })
}

fn is_executable(p: &Path) -> bool {
    fs::metadata(p).is_ok_and(|m| m.is_file())
        && rustix::fs::access(p, rustix::fs::Access::EXEC_OK).is_ok()
}

/// The first `name` (e.g. `bromigos-toggle-x`) found in `dirs`.
pub fn find(dirs: &[PathBuf], name: &str) -> Option<PathBuf> {
    command_parts(name)?;
    dirs.iter().map(|d| d.join(name)).find(|p| is_executable(p))
}

/// One discovered external command.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct External {
    /// The file name, e.g. `bromigos-toggle-nightlight`.
    pub command: String,
    pub group: String,
    /// `None` for a group's root (`bromigos-update`).
    pub name: Option<String>,
    /// How to call it, e.g. `bromigos toggle nightlight`.
    pub route: String,
    pub path: PathBuf,
    #[serde(flatten)]
    pub header: Header,
}

/// An external command hidden behind another file of the same name earlier in the
/// search path.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Shadowed {
    pub command: String,
    pub path: PathBuf,
    pub by: PathBuf,
}

/// Every external command in `dirs`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Scan {
    /// The winners, sorted by group then name (root first).
    pub commands: Vec<External>,
    pub shadowed: Vec<Shadowed>,
}

/// Lists the external commands in `dirs` (first found wins, as `find` does).
pub fn scan(dirs: &[PathBuf]) -> Scan {
    let mut out = Scan::default();
    let mut by_name: HashMap<String, PathBuf> = HashMap::new();
    for dir in dirs {
        let Ok(rd) = fs::read_dir(dir) else { continue };
        let mut files: Vec<(String, PathBuf)> = rd
            .filter_map(Result::ok)
            .filter_map(|e| Some((e.file_name().into_string().ok()?, e.path())))
            .filter(|(n, p)| command_parts(n).is_some() && is_executable(p))
            .collect();
        files.sort();
        for (file, path) in files {
            if let Some(first) = by_name.get(&file) {
                out.shadowed.push(Shadowed {
                    command: file,
                    path,
                    by: first.clone(),
                });
                continue;
            }
            let (group, name) = command_parts(&file).expect("filtered above");
            let route = match name {
                Some(n) => format!("bromigos {group} {n}"),
                None => format!("bromigos {group}"),
            };
            out.commands.push(External {
                group: group.to_owned(),
                name: name.map(str::to_owned),
                route,
                header: read_header(&path),
                command: file.clone(),
                path: path.clone(),
            });
            by_name.insert(file, path);
        }
    }
    out.commands
        .sort_by(|a, b| (&a.group, &a.name).cmp(&(&b.group, &b.name)));
    out
}

/// Which second words a built-in command owns.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verbs {
    /// Every following word (pass-through commands such as `live`).
    All,
    /// Only these; any other word may route to `bromigos-<group>-<word>`.
    Only(&'static [&'static str]),
}

/// A built-in command, as the router sees it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Builtin {
    pub name: &'static str,
    pub verbs: Verbs,
    /// The executable a pass-through built-in runs (it is no collision when the
    /// external command is that same file).
    pub target: Option<PathBuf>,
}

/// Where a command line goes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Route {
    /// Parse it as a built-in (or let the parser report it).
    Builtin,
    /// Exec `path` with `args`.
    External {
        command: String,
        path: PathBuf,
        args: Vec<OsString>,
    },
    /// No built-in and no external command matches.
    Unknown(String),
}

fn word(a: Option<&OsString>) -> Option<&str> {
    a.and_then(|s| s.to_str()).filter(|s| !s.starts_with('-'))
}

/// Routes `argv` (without the program name). Built-ins first; then
/// `bromigos-<group>-<name>` with the rest as arguments; then `bromigos-<group>`
/// with everything after the group.
pub fn route(
    argv: &[OsString],
    builtins: &[Builtin],
    find: impl Fn(&str) -> Option<PathBuf>,
) -> Route {
    let Some(group) = word(argv.first()) else {
        return Route::Builtin; // nothing, or a flag such as --help
    };
    let second = word(argv.get(1));
    let ext = |name: String, skip: usize| {
        find(&name).map(|path| Route::External {
            command: name,
            path,
            args: argv[skip..].to_vec(),
        })
    };
    if let Some(b) = builtins.iter().find(|b| b.name == group) {
        return match (b.verbs, second) {
            (Verbs::Only(verbs), Some(s)) if !verbs.contains(&s) => {
                ext(format!("bromigos-{group}-{s}"), 2).unwrap_or(Route::Builtin)
            }
            _ => Route::Builtin,
        };
    }
    second
        .and_then(|s| ext(format!("bromigos-{group}-{s}"), 2))
        .or_else(|| ext(format!("bromigos-{group}"), 1))
        .unwrap_or_else(|| Route::Unknown(group.to_owned()))
}

/// A problem `bromigos commands --check` reports.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Issue {
    /// `no-summary`, `shadowed` (a same-named file earlier in the search path wins) or
    /// `builtin` (a built-in owns the route).
    pub kind: &'static str,
    pub command: String,
    pub path: PathBuf,
    pub detail: String,
}

/// Lints the scan: commands with no summary, and route collisions.
pub fn check(scan: &Scan, builtins: &[Builtin]) -> Vec<Issue> {
    let mut issues = Vec::new();
    for c in &scan.commands {
        if c.header.summary.is_none() {
            issues.push(Issue {
                kind: "no-summary",
                command: c.command.clone(),
                path: c.path.clone(),
                detail: "no `# bromigos:summary=` line in its first comment block".into(),
            });
        }
        let Some(b) = builtins.iter().find(|b| b.name == c.group) else {
            continue;
        };
        let same_file = b.target.as_ref().is_some_and(|t| {
            matches!((fs::canonicalize(t), fs::canonicalize(&c.path)), (Ok(a), Ok(b)) if a == b)
        });
        let owned = match (&c.name, b.verbs) {
            (None, _) | (Some(_), Verbs::All) => true,
            (Some(n), Verbs::Only(v)) => v.contains(&n.as_str()),
        };
        if owned && !same_file {
            issues.push(Issue {
                kind: "builtin",
                command: c.command.clone(),
                path: c.path.clone(),
                detail: format!(
                    "`{}` is the built-in `bromigos {}`; this never runs",
                    c.route, b.name
                ),
            });
        }
    }
    for s in &scan.shadowed {
        issues.push(Issue {
            kind: "shadowed",
            command: s.command.clone(),
            path: s.path.clone(),
            detail: format!("{} comes first in the search path", s.by.display()),
        });
    }
    issues
}

#[cfg(test)]
mod tests {
    use super::*;

    fn h(text: &str) -> Header {
        parse_header(text.as_bytes())
    }

    #[test]
    fn header_block() {
        let x = h(
            "#!/bin/sh\n# bromigos:summary=Do a thing\n#bromigos:args=[on|off]\n# bromigos:examples=bromigos x y on\n# bromigos:examples=bromigos x y off\n# plain comment\n# bromigos:hidden=true\necho hi\n# bromigos:summary=too late\n",
        );
        assert_eq!(x.summary.as_deref(), Some("Do a thing"));
        assert_eq!(x.args.as_deref(), Some("[on|off]"));
        assert_eq!(x.examples, ["bromigos x y on", "bromigos x y off"]);
        assert!(x.hidden);
    }

    #[test]
    fn header_only_first_block_and_malformed_keys() {
        let x = h(
            "#!/usr/bin/env python3\n\n# intro\n# bromigos:summary\n# bromigos:colour=red\n# bromigos:summary=\n# bromigos:hidden=yes\nimport os\n# bromigos:summary=no\n",
        );
        assert_eq!(x, Header::default());
        // a block after code is not the header
        assert_eq!(h("set -e\n# bromigos:summary=x\n"), Header::default());
        // nor a block past line 80
        let late = format!("{}# bromigos:summary=x\n", "#\n".repeat(80));
        assert_eq!(h(&late), Header::default());
        assert_eq!(h("\x7fELF\0\0# bromigos:summary=x\n"), Header::default());
    }

    #[test]
    fn parts() {
        assert_eq!(command_parts("bromigos-update"), Some(("update", None)));
        assert_eq!(
            command_parts("bromigos-toggle-night-light"),
            Some(("toggle", Some("night-light")))
        );
        for bad in [
            "bromigos",
            "bromigos-",
            "bromigos--x",
            "bromigos-x-",
            "bromigos-X",
            "bromigos-a.py",
            "other-x",
        ] {
            assert_eq!(command_parts(bad), None, "{bad}");
        }
    }

    const BUILTINS: &[Builtin] = &[
        Builtin {
            name: "anim",
            verbs: Verbs::Only(&["on", "off", "reset"]),
            target: None,
        },
        Builtin {
            name: "live",
            verbs: Verbs::All,
            target: None,
        },
        Builtin {
            name: "lock",
            verbs: Verbs::Only(&[]),
            target: None,
        },
    ];

    fn argv(s: &str) -> Vec<OsString> {
        s.split_whitespace().map(OsString::from).collect()
    }

    fn r(s: &str, have: &[&str]) -> Route {
        route(&argv(s), BUILTINS, |n| {
            have.contains(&n).then(|| PathBuf::from(format!("/x/{n}")))
        })
    }

    #[test]
    fn routing() {
        let ext = |c: &str, a: &str| Route::External {
            command: c.into(),
            path: PathBuf::from(format!("/x/{c}")),
            args: argv(a),
        };
        assert_eq!(r("", &[]), Route::Builtin);
        assert_eq!(r("--help", &[]), Route::Builtin);
        // built-in verbs win; other words may route out
        assert_eq!(r("anim on rain", &["bromigos-anim-on"]), Route::Builtin);
        assert_eq!(
            r("anim fade 3", &["bromigos-anim-fade"]),
            ext("bromigos-anim-fade", "3")
        );
        assert_eq!(r("anim fade", &[]), Route::Builtin);
        assert_eq!(r("live foo", &["bromigos-live-foo"]), Route::Builtin);
        assert_eq!(
            r("lock screen now", &["bromigos-lock-screen"]),
            ext("bromigos-lock-screen", "now")
        );
        // groups: the named command, else the group's root with the rest
        assert_eq!(
            r(
                "toggle nightlight on",
                &["bromigos-toggle-nightlight", "bromigos-toggle"]
            ),
            ext("bromigos-toggle-nightlight", "on")
        );
        assert_eq!(
            r("update --yes", &["bromigos-update"]),
            ext("bromigos-update", "--yes")
        );
        assert_eq!(
            r("update now", &["bromigos-update"]),
            ext("bromigos-update", "now")
        );
        assert_eq!(r("nope x", &[]), Route::Unknown("nope".into()));
    }
}
