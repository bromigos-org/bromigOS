//! Update channels: which build of bromigOS a machine follows.
//!
//! The repository publishes four channels (packaging/README.md "Channels"):
//!
//! | channel  | what                                                  | path in the bucket        |
//! |----------|-------------------------------------------------------|---------------------------|
//! | `stable` | tagged releases (`vX.Y.Z`)                            | `<repo>/stable/<arch>/`   |
//! | `rc`     | release candidates (`vX.Y.Z-rcN`)                     | `<repo>/rc/<arch>/`       |
//! | `edge`   | every push to main (the first layout: `<repo>/<arch>`) | `<repo>/<arch>/`          |
//! | `dev`    | your own build (`packaging/dev-repo.sh`), a local repo | `file://…/repo/<repo>/<arch>` |
//!
//! A machine's channel is whatever its `[bromigos]` `Server` line in `/etc/pacman.conf`
//! points at; `bromigos channel` reads it, `bromigos channel set <name>` rewrites that
//! line (and `SigLevel`: a dev repo is unsigned) with `sudo`, then `bromigos update`
//! follows it. The old channel's sync database goes with the old line: kept, a move to an
//! older channel failed ("signature is invalid": the old `bromigos.db` is newer than the new
//! channel's, so `pacman -Sy` asked "modified since?", kept it, and checked the new
//! channel's signature against it). Nothing else is stored, except the last remote base URL
//! (`~/.local/state/bromigos/channel.toml`) so that leaving `dev` finds its way back.
//!
//! Adapted from Omarchy's channels (stable, rc, edge, dev; `omarchy-channel-set`), for a
//! packaged system: there is no git checkout to switch, only a repository path.

use std::fmt;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde::Serialize;

use crate::paths::Paths;

/// The repository's name in pacman.conf (`[bromigos]`, `$repo`).
pub const REPO: &str = "bromigos";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Channel {
    Stable,
    Rc,
    Edge,
    Dev,
}

impl Channel {
    pub const ALL: [Channel; 4] = [Channel::Stable, Channel::Rc, Channel::Edge, Channel::Dev];

    pub fn as_str(self) -> &'static str {
        match self {
            Channel::Stable => "stable",
            Channel::Rc => "rc",
            Channel::Edge => "edge",
            Channel::Dev => "dev",
        }
    }

    pub fn parse(s: &str) -> Option<Channel> {
        match s.trim().to_ascii_lowercase().as_str() {
            "stable" => Some(Channel::Stable),
            "rc" => Some(Channel::Rc),
            "edge" => Some(Channel::Edge),
            "dev" => Some(Channel::Dev),
            _ => None,
        }
    }

    /// What the channel means, for `bromigos channel` and the manual.
    pub fn describe(self) -> &'static str {
        match self {
            Channel::Stable => "tagged releases; the default for new installs",
            Channel::Rc => "release candidates: what becomes the next stable",
            Channel::Edge => "every push to main, as soon as CI publishes it",
            Channel::Dev => "your own build, from a local repository (packaging/dev-repo.sh)",
        }
    }

    /// The `SigLevel` the channel's repository needs: a dev repository is unsigned.
    pub fn siglevel(self) -> &'static str {
        match self {
            Channel::Dev => "Optional",
            _ => "Required DatabaseOptional",
        }
    }
}

impl fmt::Display for Channel {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// pacman's `Server` line for a channel. `base` is the repository's base URL
/// (`https://host`), the way install.sh's `--repo` takes it; `dev_dir` the local
/// repository's directory (the one `packaging/dev-repo.sh` fills).
pub fn server(base: &str, channel: Channel, dev_dir: &Path) -> String {
    let base = base.trim_end_matches('/');
    match channel {
        Channel::Edge => format!("{base}/$repo/$arch"),
        Channel::Stable | Channel::Rc => format!("{base}/$repo/{}/$arch", channel.as_str()),
        Channel::Dev => format!("file://{}/$repo/$arch", dev_dir.display()),
    }
}

/// The channel a `Server` line points at, and (for the remote ones) its base URL.
pub fn of_server(server: &str) -> Option<(Channel, Option<String>)> {
    let s = server.trim().trim_end_matches('/');
    if s.starts_with("file://") {
        return Some((Channel::Dev, None));
    }
    for ch in [Channel::Stable, Channel::Rc] {
        let tail = format!("/$repo/{}/$arch", ch.as_str());
        if let Some(base) = s.strip_suffix(&tail) {
            return Some((ch, Some(base.to_owned())));
        }
    }
    s.strip_suffix("/$repo/$arch")
        .map(|base| (Channel::Edge, Some(base.to_owned())))
}

/// The `[bromigos]` section of a pacman.conf: its `Server` line and `SigLevel`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Section {
    pub server: String,
    pub siglevel: Option<String>,
}

/// Reads the `[bromigos]` section. None when pacman.conf has none (install.sh adds it).
pub fn section(conf: &str) -> Option<Section> {
    let mut inside = false;
    let mut server = None;
    let mut siglevel = None;
    for line in conf.lines() {
        let t = line.trim();
        if t.starts_with('[') && t.ends_with(']') {
            if inside {
                break;
            }
            inside = t == format!("[{REPO}]");
            continue;
        }
        if !inside || t.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = t.split_once('=') {
            match k.trim() {
                "Server" => server = Some(v.trim().to_owned()),
                "Include" if server.is_none() => {
                    if let Ok(mirrors) = fs::read_to_string(v.trim()) {
                        server = mirrors.lines().find_map(|line| {
                            let (key, value) = line.trim().split_once('=')?;
                            (key.trim() == "Server").then(|| value.trim().to_owned())
                        });
                    }
                }
                "SigLevel" => siglevel = Some(v.trim().to_owned()),
                _ => {}
            }
        }
    }
    server.map(|server| Section { server, siglevel })
}

/// pacman.conf with the `[bromigos]` section's `Server` and `SigLevel` lines replaced
/// (the rest byte for byte). None when there is no such section.
pub fn rewrite(conf: &str, server: &str, siglevel: &str) -> Option<String> {
    let has_sig = section(conf)?.siglevel.is_some();
    let mut out = String::with_capacity(conf.len() + 64);
    let mut inside = false;
    for line in conf.split_inclusive('\n') {
        let t = line.trim();
        if t.starts_with('[') && t.ends_with(']') {
            inside = t == format!("[{REPO}]");
            out.push_str(line);
            continue;
        }
        let key = (inside && !t.starts_with('#'))
            .then(|| t.split_once('=').map(|(k, _)| k.trim()))
            .flatten();
        match key {
            Some("Server" | "Include") => {
                out.push_str(&format!("Server = {server}\n"));
                if !has_sig {
                    out.push_str(&format!("SigLevel = {siglevel}\n"));
                }
            }
            Some("SigLevel") => out.push_str(&format!("SigLevel = {siglevel}\n")),
            _ => out.push_str(line),
        }
    }
    Some(out)
}

/// Where this machine's pacman.conf is (`BROMIGOS_PACMAN_CONF` for tests and dry runs).
pub fn conf_path() -> PathBuf {
    std::env::var_os("BROMIGOS_PACMAN_CONF")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/etc/pacman.conf"))
}

/// pacman's sync databases (`BROMIGOS_PACMAN_SYNC` for tests; else pacman.conf's
/// `DBPath`, as `pacman-conf` says, and `sync/` in it).
pub fn sync_dir() -> PathBuf {
    if let Some(d) = std::env::var_os("BROMIGOS_PACMAN_SYNC") {
        return PathBuf::from(d);
    }
    let db = Command::new("pacman-conf")
        .arg("DBPath")
        .stderr(std::process::Stdio::null())
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_owned())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "/var/lib/pacman/".to_owned());
    PathBuf::from(db).join("sync")
}

/// The `[bromigos]` repository's sync files in `sync`: its database and file list, and
/// their signatures (only those there).
pub fn sync_files(sync: &Path) -> Vec<PathBuf> {
    ["db", "db.sig", "files", "files.sig"]
        .iter()
        .map(|ext| sync.join(format!("{REPO}.{ext}")))
        .filter(|p| p.exists() || p.is_symlink())
        .collect()
}

/// The command that drops them (root's: pacman's directory).
pub fn forget_command(files: &[PathBuf]) -> Vec<String> {
    let mut a: Vec<String> = ["sudo", "rm", "-f", "--"]
        .iter()
        .map(|s| (*s).to_owned())
        .collect();
    a.extend(files.iter().map(|p| p.display().to_string()));
    a
}

/// Where a `dev` channel's local repository lives.
pub fn dev_dir(paths: &Paths) -> PathBuf {
    std::env::var_os("BROMIGOS_DEV_REPO")
        .map(PathBuf::from)
        .unwrap_or_else(|| paths.home.join(".local/share/bromigos/repo"))
}

/// What `bromigos channel` reports.
#[derive(Debug, Clone, Serialize)]
pub struct Current {
    pub channel: Option<Channel>,
    pub server: Option<String>,
    /// The remote repository's base URL, when known (not on dev, unless remembered).
    pub base: Option<String>,
    pub conf: PathBuf,
}

fn state_file(paths: &Paths) -> PathBuf {
    paths.state_home.join("bromigos/channel.toml")
}

/// The remote base URL remembered when the machine went to `dev`.
fn remembered_base(paths: &Paths) -> Option<String> {
    let s = fs::read_to_string(state_file(paths)).ok()?;
    s.lines()
        .find_map(|l| l.trim().strip_prefix("base = "))
        .map(|v| v.trim().trim_matches('"').to_owned())
        .filter(|v| !v.is_empty())
}

fn remember_base(paths: &Paths, base: &str) {
    let p = state_file(paths);
    if let Some(d) = p.parent() {
        let _ = fs::create_dir_all(d);
    }
    let _ = fs::write(
        &p,
        format!(
            "# the repository bromigos channel set edge|stable|rc goes back to\nbase = \"{base}\"\n"
        ),
    );
}

pub fn current(paths: &Paths) -> Current {
    let conf = conf_path();
    let text = fs::read_to_string(&conf).unwrap_or_default();
    let sec = section(&text);
    let (channel, base) = sec
        .as_ref()
        .and_then(|s| of_server(&s.server))
        .map(|(c, b)| (Some(c), b))
        .unwrap_or((None, None));
    Current {
        channel,
        base: base.or_else(|| remembered_base(paths)),
        server: sec.map(|s| s.server),
        conf,
    }
}

/// What `bromigos channel set` did.
#[derive(Debug, Clone, Serialize)]
pub struct Change {
    pub from: Option<Channel>,
    pub to: Channel,
    pub server: String,
    pub siglevel: String,
    pub conf: PathBuf,
    /// The new channel is older than the old one: `bromigos update --downgrade` lands it.
    pub downgrade: bool,
    /// The old channel's sync files, dropped with its Server line (the next `pacman -Sy`
    /// fetches the new channel's afresh).
    pub dropped: Vec<PathBuf>,
}

/// Rewrites pacman.conf for `channel` through `sudo install` (the user answers sudo on the
/// terminal). `base` overrides the remembered remote base URL; `dev_dir` the local repo.
pub fn set(
    paths: &Paths,
    channel: Channel,
    base: Option<&str>,
    dev_dir_override: Option<&Path>,
) -> Result<Change, String> {
    let cur = current(paths);
    let conf = cur.conf.clone();
    let text = fs::read_to_string(&conf).map_err(|e| format!("{}: {e}", conf.display()))?;
    let base = match (channel, base, cur.base.as_deref()) {
        (Channel::Dev, _, _) => String::new(),
        (_, Some(b), _) => b.to_owned(),
        (_, None, Some(b)) => b.to_owned(),
        (_, None, None) => {
            return Err(
                "the repository's base URL isn't known (the Server line is a file:// repo \
                 and nothing was remembered): give it with --repo URL"
                    .into(),
            );
        }
    };
    let dev = dev_dir_override
        .map(Path::to_path_buf)
        .unwrap_or_else(|| dev_dir(paths));
    let server = server(&base, channel, &dev);
    let siglevel = channel.siglevel();
    let moved = section(&text).is_some_and(|sec| sec.server != server);
    let new = rewrite(&text, &server, siglevel).ok_or_else(|| {
        format!(
            "{} has no [{REPO}] section (run install.sh)",
            conf.display()
        )
    })?;
    if new != text {
        let tmp = paths
            .runtime_dir
            .join(format!("bromigos-pacman.conf.{}", std::process::id()));
        {
            let mut f = fs::File::create(&tmp).map_err(|e| format!("{}: {e}", tmp.display()))?;
            f.write_all(new.as_bytes())
                .map_err(|e| format!("{}: {e}", tmp.display()))?;
        }
        let st = Command::new("sudo")
            .args(["install", "-m", "644", "-o", "root", "-g", "root"])
            .arg(&tmp)
            .arg(&conf)
            .status();
        let _ = fs::remove_file(&tmp);
        match st {
            Ok(s) if s.success() => {}
            Ok(s) => return Err(format!("sudo install exited {s}")),
            Err(e) => return Err(format!("sudo install: {e}")),
        }
    }
    let mut dropped = vec![];
    if moved {
        let old = sync_files(&sync_dir());
        if !old.is_empty() {
            let a = forget_command(&old);
            let st = Command::new(&a[0]).args(&a[1..]).status();
            match st {
                Ok(s) if s.success() => dropped = old,
                _ => {
                    return Err(format!(
                        "the Server line is the {channel} channel's now, but the old channel's \
                         database stays (`{}` failed): remove it, or the next update fails its \
                         signature",
                        a.join(" ")
                    ));
                }
            }
        }
    }
    if channel != Channel::Dev && !base.is_empty() {
        remember_base(paths, &base);
    } else if let Some(b) = cur.base.as_deref() {
        remember_base(paths, b);
    }
    let downgrade = matches!(
        (cur.channel, channel),
        (
            Some(Channel::Edge) | Some(Channel::Dev),
            Channel::Stable | Channel::Rc
        ) | (Some(Channel::Rc), Channel::Stable)
    );
    Ok(Change {
        from: cur.channel,
        to: channel,
        server,
        siglevel: siglevel.to_owned(),
        conf,
        downgrade,
        dropped,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const CONF: &str = "[options]\nColor\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n\n\
                        [bromigos]\nSigLevel = Required DatabaseOptional\nServer = https://pkgs.example/$repo/$arch\n";

    #[test]
    fn server_lines() {
        let dev = Path::new("/home/u/.local/share/bromigos/repo");
        assert_eq!(
            server("https://pkgs.example/", Channel::Edge, dev),
            "https://pkgs.example/$repo/$arch"
        );
        assert_eq!(
            server("https://pkgs.example", Channel::Stable, dev),
            "https://pkgs.example/$repo/stable/$arch"
        );
        assert_eq!(
            server("https://pkgs.example", Channel::Rc, dev),
            "https://pkgs.example/$repo/rc/$arch"
        );
        assert_eq!(
            server("https://pkgs.example", Channel::Dev, dev),
            "file:///home/u/.local/share/bromigos/repo/$repo/$arch"
        );
    }

    #[test]
    fn channel_of_a_server_line() {
        assert_eq!(
            of_server("https://pkgs.example/$repo/$arch"),
            Some((Channel::Edge, Some("https://pkgs.example".into())))
        );
        assert_eq!(
            of_server("https://pkgs.example/$repo/stable/$arch/"),
            Some((Channel::Stable, Some("https://pkgs.example".into())))
        );
        assert_eq!(
            of_server("https://pkgs.example/$repo/rc/$arch"),
            Some((Channel::Rc, Some("https://pkgs.example".into())))
        );
        assert_eq!(
            of_server("file:///tmp/repo/$repo/$arch"),
            Some((Channel::Dev, None))
        );
        assert_eq!(of_server("https://pkgs.example/other"), None);
        for c in Channel::ALL {
            let s = server("https://h", c, Path::new("/d"));
            assert_eq!(of_server(&s).unwrap().0, c, "{s}");
        }
    }

    #[test]
    fn reads_and_rewrites_the_section() {
        let s = section(CONF).unwrap();
        assert_eq!(s.server, "https://pkgs.example/$repo/$arch");
        assert_eq!(s.siglevel.as_deref(), Some("Required DatabaseOptional"));
        let new = rewrite(
            CONF,
            "https://pkgs.example/$repo/stable/$arch",
            "Required DatabaseOptional",
        )
        .unwrap();
        assert!(new.contains("Server = https://pkgs.example/$repo/stable/$arch\n"));
        assert!(
            new.starts_with("[options]\nColor\n\n[core]\n"),
            "the rest is untouched"
        );
        assert_eq!(new.matches("Server = ").count(), 1);
        let dev = rewrite(CONF, "file:///r/$repo/$arch", "Optional").unwrap();
        assert!(dev.contains("SigLevel = Optional\nServer = file:///r/$repo/$arch\n"));
        assert_eq!(section(&dev).unwrap().siglevel.as_deref(), Some("Optional"));
    }

    #[test]
    fn the_old_channels_sync_files() {
        let t = tempfile::tempdir().unwrap();
        for f in [
            "bromigos.db",
            "bromigos.db.sig",
            "bromigos.files",
            "core.db",
            "extra.db",
        ] {
            fs::write(t.path().join(f), "x").unwrap();
        }
        let got = sync_files(t.path());
        let names: Vec<_> = got
            .iter()
            .map(|p| p.file_name().unwrap().to_str().unwrap().to_owned())
            .collect();
        // only [bromigos]'s, never Arch's
        assert_eq!(
            names,
            vec!["bromigos.db", "bromigos.db.sig", "bromigos.files"]
        );
        let a = forget_command(&got);
        assert_eq!(&a[..4], &["sudo", "rm", "-f", "--"]);
        assert_eq!(a.len(), 7);
        assert!(a[4].ends_with("/bromigos.db"));
        assert!(sync_files(&t.path().join("none")).is_empty());
    }

    #[test]
    fn rewrite_adds_a_missing_siglevel_and_keeps_later_sections() {
        let conf = "[bromigos]\nServer = https://h/$repo/$arch\n\n[multilib]\nInclude = x\n";
        let new = rewrite(
            conf,
            "https://h/$repo/rc/$arch",
            "Required DatabaseOptional",
        )
        .unwrap();
        assert_eq!(
            new,
            "[bromigos]\nServer = https://h/$repo/rc/$arch\nSigLevel = Required DatabaseOptional\n\n[multilib]\nInclude = x\n"
        );
        assert!(rewrite("[core]\nInclude = x\n", "s", "l").is_none());
    }
}

#[cfg(test)]
mod mirrorlist_tests {
    use super::*;
    #[test]
    fn reads_include_and_switches_without_changing_the_packaged_mirrorlist() {
        let d = tempfile::tempdir().unwrap();
        let file = d.path().join("mirrors");
        let mirrors =
            "# Future mirrors go here\nServer = https://pkgs.example/$repo/stable/$arch\n";
        fs::write(&file, mirrors).unwrap();
        let conf = format!(
            "[core]\nInclude = /elsewhere\n[bromigos]\nInclude = {}\n",
            file.display()
        );
        let sec = section(&conf).unwrap();
        assert_eq!(of_server(&sec.server).unwrap().0, Channel::Stable);
        let updated = rewrite(
            &conf,
            "https://pkgs.example/$repo/$arch",
            "Required DatabaseOptional",
        )
        .unwrap();
        assert!(updated.contains("[core]\nInclude = /elsewhere"));
        assert!(updated.contains("Server = https://pkgs.example/$repo/$arch"));
        assert!(!updated.contains(&file.display().to_string()));
        assert_eq!(fs::read_to_string(file).unwrap(), mirrors);
    }
}
