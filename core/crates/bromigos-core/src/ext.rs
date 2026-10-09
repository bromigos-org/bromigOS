//! Extensions (`bromigos ext`, docs/extensions.md): one installable unit for everything
//! bromigOS can be extended with — themes, the live layer's decks and shader layers,
//! widgets, VECTOR's tools, memory stores and skills, homelab adapters, commands and
//! theme-set hooks.
//!
//! An extension is a git repository (or a folder) with a manifest, `bromigos-ext.toml`,
//! at its root (a theme repository without one still installs, as a theme). Installed,
//! it is a checkout in `~/.local/share/bromigos/ext/src/<name>` pinned to a commit, and
//! each of its parts is a link in `~/.local/share/bromigos/ext/active/<seam>/`, the
//! folder that part's loader reads after the user's own. A ledger,
//! `~/.local/state/bromigos/ext/ledger.json`, records where each came from, the commit,
//! every file's sha256, the permissions it declared, how it was approved and when.
//! VECTOR's guard reads the ledger: a change to his plugin or homelab folders is his
//! sentinel's business unless it matches what `bromigos ext` recorded (holo/vector/guard.py).
//!
//! Borrowed from Omarchy 4's plugins (a manifest at the repository's root naming each
//! kind and its entry, `validate`, a starter to edit, a catalog to find them in), with
//! the differences bromigOS needs: commits pinned and hashed, permissions declared and
//! shown, VECTOR's guard in the loop, and nothing written into `~/.config/bromigos`
//! (often a public dotfiles repository).

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{self, Read, Write};
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::paths::Paths;
use crate::theme;

/// The manifest's file name, at the extension's root.
pub const MANIFEST: &str = "bromigos-ext.toml";
/// The extension API this bromigOS provides (`[requires] bromigos = ">=1.0, <2"`).
pub const API: &str = "1.0.0";
/// The catalog `bromigos ext search` reads when none is configured.
pub const DEFAULT_CATALOG: &str = "https://github.com/bromigos-org/extensions.git";
const LEDGER_SCHEMA: u32 = 1;
/// How long a catalog's copy is used before it's fetched again.
const CATALOG_TTL_SECS: u64 = 6 * 3600;
/// How long the guard honours an unfinished transaction's "either version" hashes.
pub const TXN_GRACE_SECS: i64 = 600;

#[derive(Debug, thiserror::Error)]
#[error("{0}")]
pub struct Error(pub String);

pub type Result<T> = std::result::Result<T, Error>;

fn err<T>(msg: impl Into<String>) -> Result<T> {
    Err(Error(msg.into()))
}

fn io_err(path: &Path) -> impl FnOnce(io::Error) -> Error + '_ {
    move |e| Error(format!("{}: {e}", path.display()))
}

// ------------------------------------------------------------------ kinds

/// What a part of an extension is, and so where it's linked.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Kind {
    Theme,
    LiveDeck,
    LiveLayer,
    Widget,
    VectorTool,
    VectorMemory,
    VectorSkill,
    HomelabAdapter,
    Command,
    Hook,
}

impl Kind {
    pub const ALL: [Kind; 10] = [
        Kind::Theme,
        Kind::LiveDeck,
        Kind::LiveLayer,
        Kind::Widget,
        Kind::VectorTool,
        Kind::VectorMemory,
        Kind::VectorSkill,
        Kind::HomelabAdapter,
        Kind::Command,
        Kind::Hook,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Theme => "theme",
            Kind::LiveDeck => "live-deck",
            Kind::LiveLayer => "live-layer",
            Kind::Widget => "widget",
            Kind::VectorTool => "vector-tool",
            Kind::VectorMemory => "vector-memory",
            Kind::VectorSkill => "vector-skill",
            Kind::HomelabAdapter => "homelab-adapter",
            Kind::Command => "command",
            Kind::Hook => "hook",
        }
    }

    pub fn parse(s: &str) -> Option<Kind> {
        Kind::ALL.into_iter().find(|k| k.as_str() == s)
    }

    /// What it is, for the permission summary.
    pub fn describe(self) -> &'static str {
        match self {
            Kind::Theme => "a theme (colours, backgrounds, a world: data)",
            Kind::LiveDeck => "a live-layer deck (Python, run by the live layer)",
            Kind::LiveLayer => "a shader layer over the background (GLSL, on the GPU)",
            Kind::Widget => "a desktop widget (Python, run by the widgets)",
            Kind::VectorTool => "VECTOR tools (Python, run inside VECTOR's calls)",
            Kind::VectorMemory => "a VECTOR memory store (Python, run inside VECTOR)",
            Kind::VectorSkill => "a VECTOR skill (instructions he loads on demand)",
            Kind::HomelabAdapter => "a homelab adapter (Python, run in VECTOR's homelab tools)",
            Kind::Command => "a bromigos command (a program you run)",
            Kind::Hook => "a theme-set hook (a program run at every theme change)",
        }
    }

    /// Runs code on this machine: Python, a program, a script. A theme is data, a shader
    /// layer runs on the GPU with no files and no network, a skill is text.
    pub fn runs_code(self) -> bool {
        !matches!(self, Kind::Theme | Kind::LiveLayer | Kind::VectorSkill)
    }

    /// Runs inside VECTOR's own calls: linked into the folders his guard watches.
    pub fn guarded(self) -> bool {
        matches!(
            self,
            Kind::VectorTool | Kind::VectorMemory | Kind::HomelabAdapter
        )
    }

    /// Gives VECTOR something: a tool, memory, a skill, an adapter his tools call.
    pub fn for_vector(self) -> bool {
        matches!(
            self,
            Kind::VectorTool | Kind::VectorMemory | Kind::VectorSkill | Kind::HomelabAdapter
        )
    }
}

impl std::fmt::Display for Kind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

// ------------------------------------------------------------------ the manifest

/// `bromigos-ext.toml`.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub extension: Meta,
    pub requires: Requires,
    #[serde(default)]
    pub provides: Vec<Part>,
    #[serde(default)]
    pub permissions: Permissions,
}

/// `[extension]`.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Meta {
    /// The id: lowercase letters, digits, `-` and `_`; the checkout's folder name.
    pub name: String,
    pub version: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub authors: Vec<String>,
    #[serde(default, alias = "license", skip_serializing_if = "Option::is_none")]
    pub licence: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub homepage: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tags: Vec<String>,
}

/// `[requires]`.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Requires {
    /// The extension API versions it works with, as a version range (`>=1.0, <2`).
    pub bromigos: String,
}

/// One `[[provides]]` entry.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Part {
    pub kind: Kind,
    /// Relative to the extension's root (`.` for a theme at the root).
    pub path: String,
    /// The name it's linked under (default: the file's stem, or the folder's name).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// A hook's event (`theme-set`, the default and only one so far).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub event: Option<String>,
}

/// `[permissions]`: what it reaches, declared by the author and shown before an install.
#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Permissions {
    /// `"none"` (the default), `"any"`, or the hosts it talks to.
    #[serde(default)]
    pub network: Network,
    /// Paths outside its own folder it reads or writes (`~/Music`, `$XDG_RUNTIME_DIR/x.sock`).
    #[serde(default)]
    pub filesystem: Vec<String>,
    /// VECTOR tool level: `read` (looks things up) or `desktop` (changes this desktop);
    /// never the terminal.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub vector: Option<String>,
    /// Whether it runs code (a deck, a widget, a VECTOR plugin, an adapter, a command, a hook).
    #[serde(default)]
    pub code: bool,
}

/// `network = "none" | "any" | ["host", …]`.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub enum Network {
    #[default]
    None,
    Any,
    Hosts(Vec<String>),
}

impl<'de> Deserialize<'de> for Network {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Repr {
            Word(String),
            Hosts(Vec<String>),
        }
        match Repr::deserialize(d)? {
            Repr::Word(w) => match w.as_str() {
                "none" => Ok(Network::None),
                "any" | "*" => Ok(Network::Any),
                _ => Err(serde::de::Error::custom(format!(
                    "network = {w:?}: \"none\", \"any\", or a list of hosts"
                ))),
            },
            Repr::Hosts(h) if h.is_empty() => Ok(Network::None),
            Repr::Hosts(h) if h.iter().any(|x| x == "*" || x == "any") => Ok(Network::Any),
            Repr::Hosts(h) => Ok(Network::Hosts(h)),
        }
    }
}

impl Serialize for Network {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        match self {
            Network::None => s.serialize_str("none"),
            Network::Any => s.serialize_str("any"),
            Network::Hosts(h) => h.serialize(s),
        }
    }
}

impl Permissions {
    /// One line per permission, for people.
    pub fn lines(&self) -> Vec<String> {
        let mut out = vec![];
        out.push(match &self.network {
            Network::None => "network: none".to_owned(),
            Network::Any => "network: ANY host".to_owned(),
            Network::Hosts(h) => format!("network: {}", h.join(", ")),
        });
        out.push(if self.filesystem.is_empty() {
            "files outside its folder: none".to_owned()
        } else {
            format!("files outside its folder: {}", self.filesystem.join(", "))
        });
        out.push(match self.vector.as_deref() {
            None => "VECTOR: nothing".to_owned(),
            Some("read") => "VECTOR: read-level tools (look things up)".to_owned(),
            Some("desktop") => "VECTOR: desktop-level tools (change this desktop)".to_owned(),
            Some(o) => format!("VECTOR: {o}"),
        });
        out.push(format!(
            "runs code: {}",
            if self.code { "YES" } else { "no" }
        ));
        out
    }

    /// What `new` grants that `self` didn't, one line each (empty when nothing grew).
    pub fn growth(&self, new: &Permissions) -> Vec<String> {
        let mut out = vec![];
        match (&self.network, &new.network) {
            (Network::Any, _) | (_, Network::None) => {}
            (_, Network::Any) => out.push("network: now ANY host".to_owned()),
            (old, Network::Hosts(h)) => {
                let had: BTreeSet<&String> = match old {
                    Network::Hosts(o) => o.iter().collect(),
                    _ => BTreeSet::new(),
                };
                let more: Vec<&str> = h
                    .iter()
                    .filter(|x| !had.contains(x))
                    .map(String::as_str)
                    .collect();
                if !more.is_empty() {
                    out.push(format!("network: now also {}", more.join(", ")));
                }
            }
        }
        let more: Vec<&str> = new
            .filesystem
            .iter()
            .filter(|p| !self.filesystem.contains(p))
            .map(String::as_str)
            .collect();
        if !more.is_empty() {
            out.push(format!("files: now also {}", more.join(", ")));
        }
        let rank = |v: Option<&str>| match v {
            Some("desktop") => 2,
            Some(_) => 1,
            None => 0,
        };
        if rank(new.vector.as_deref()) > rank(self.vector.as_deref()) {
            out.push(format!(
                "VECTOR: now {}-level tools",
                new.vector.as_deref().unwrap_or("")
            ));
        }
        if new.code && !self.code {
            out.push("runs code: now YES".to_owned());
        }
        out
    }
}

/// Reads a manifest.
pub fn parse_manifest(text: &str, path: &Path) -> Result<Manifest> {
    toml::from_str(text).map_err(|e| Error(format!("{}: {e}", path.display())))
}

/// The manifest a theme repository without one gets.
fn theme_manifest(name: &str) -> Manifest {
    Manifest {
        extension: Meta {
            name: name.to_owned(),
            version: "0".to_owned(),
            description: String::new(),
            authors: vec![],
            licence: None,
            homepage: None,
            tags: vec![],
        },
        requires: Requires {
            bromigos: ">=1.0".to_owned(),
        },
        provides: vec![Part {
            kind: Kind::Theme,
            path: ".".to_owned(),
            name: None,
            event: None,
        }],
        permissions: Permissions::default(),
    }
}

/// Whether this bromigOS's API is in `range`.
pub fn api_matches(range: &str) -> Result<bool> {
    let req = semver::VersionReq::parse(range.trim()).map_err(|e| {
        Error(format!(
            "[requires] bromigos = {range:?}: not a version range ({e}); e.g. \">=1.0, <2\""
        ))
    })?;
    Ok(req.matches(&semver::Version::parse(API).expect("API is a version")))
}

// ------------------------------------------------------------------ checking a tree

/// A relative path inside the extension: no root, no `..`, nothing empty.
fn safe_rel(p: &str) -> Result<PathBuf> {
    if p.is_empty() || p.contains('\0') || p.starts_with('-') {
        return err(format!(
            "path {p:?}: not a relative path inside the extension"
        ));
    }
    let mut out = PathBuf::new();
    for c in Path::new(p).components() {
        match c {
            Component::CurDir => {}
            Component::Normal(n) => out.push(n),
            _ => {
                return err(format!(
                    "path {p:?} leaves the extension (absolute, or ..): refused"
                ));
            }
        }
    }
    Ok(out)
}

/// The sha256 of a file, in hex.
pub fn sha256_file(p: &Path) -> io::Result<String> {
    let mut f = fs::File::open(p)?;
    let mut h = Sha256::new();
    let mut buf = vec![0u8; 1 << 16];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(hex(&h.finalize()))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// One hash for a set of file hashes (a theme or a skill folder).
fn tree_hash(files: &BTreeMap<String, String>, prefix: &str) -> String {
    let mut h = Sha256::new();
    for (k, v) in files {
        let inside = if prefix.is_empty() {
            Some(k.as_str())
        } else {
            k.strip_prefix(prefix).and_then(|r| r.strip_prefix('/'))
        };
        if let Some(rel) = inside {
            h.update(rel.as_bytes());
            h.update(b"\0");
            h.update(v.as_bytes());
            h.update(b"\n");
        }
    }
    hex(&h.finalize())
}

/// Every file under `root` (not `.git`) with its sha256, refusing what could reach
/// outside it: a symlink that resolves outside (or nowhere), a device, a socket or a fifo.
/// A symlink inside is recorded as `symlink:<target>`, not followed.
pub fn scan_tree(root: &Path) -> Result<BTreeMap<String, String>> {
    let canon_root = fs::canonicalize(root).map_err(io_err(root))?;
    let mut out = BTreeMap::new();
    let mut stack = vec![PathBuf::new()];
    while let Some(rel) = stack.pop() {
        let dir = root.join(&rel);
        let mut entries: Vec<_> = fs::read_dir(&dir)
            .map_err(io_err(&dir))?
            .collect::<io::Result<Vec<_>>>()
            .map_err(io_err(&dir))?;
        entries.sort_by_key(|e| e.file_name());
        for e in entries {
            let name = e.file_name();
            if rel.as_os_str().is_empty() && name == ".git" {
                continue;
            }
            // Python's bytecode, written next to a module when it's imported: not the
            // extension's (an extension that ships any is refused: `check`)
            if name == "__pycache__" || Path::new(&name).extension().is_some_and(|e| e == "pyc") {
                continue;
            }
            let r = rel.join(&name);
            let key = r.to_string_lossy().into_owned();
            let p = root.join(&r);
            let meta = fs::symlink_metadata(&p).map_err(io_err(&p))?;
            let ft = meta.file_type();
            if ft.is_symlink() {
                let target = fs::canonicalize(&p).map_err(|_| {
                    Error(format!("{key}: a symlink to nothing (dangling): refused"))
                })?;
                if !target.starts_with(&canon_root) {
                    return err(format!(
                        "{key}: a symlink out of the extension ({}): refused",
                        target.display()
                    ));
                }
                let to = fs::read_link(&p).map_err(io_err(&p))?;
                out.insert(key, format!("symlink:{}", to.display()));
            } else if ft.is_dir() {
                stack.push(r);
            } else if ft.is_file() {
                out.insert(key, sha256_file(&p).map_err(io_err(&p))?);
            } else {
                return err(format!(
                    "{key}: not a file or a folder (a device, socket or fifo): refused"
                ));
            }
        }
    }
    Ok(out)
}

/// The first `__pycache__` folder or `.pyc` file under `root` (not `.git`), if any.
fn compiled(root: &Path) -> Option<String> {
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in fs::read_dir(&d).into_iter().flatten().flatten() {
            let p = e.path();
            let name = e.file_name();
            if d == root && name == ".git" {
                continue;
            }
            let is_dir = e.file_type().is_ok_and(|t| t.is_dir());
            if name == "__pycache__" || p.extension().is_some_and(|x| x == "pyc") {
                return Some(
                    p.strip_prefix(root)
                        .unwrap_or(&p)
                        .to_string_lossy()
                        .into_owned(),
                );
            }
            if is_dir {
                stack.push(p);
            }
        }
    }
    None
}

/// One part, checked: the name it's linked under and its links (relative to `active/`).
#[derive(Debug, Clone, Serialize)]
pub struct CheckedPart {
    pub kind: Kind,
    pub name: String,
    pub path: String,
    /// (link under `active/`, target relative to the extension's root)
    pub links: Vec<(PathBuf, PathBuf)>,
}

/// A checked extension tree.
#[derive(Debug, Clone, Serialize)]
pub struct Checked {
    pub manifest: Manifest,
    /// The manifest was made up: a theme repository without one.
    pub synthesized: bool,
    pub parts: Vec<CheckedPart>,
    pub files: BTreeMap<String, String>,
    pub warnings: Vec<String>,
}

impl Checked {
    /// Nothing but themes: installs without a question.
    pub fn data_only(&self) -> bool {
        self.parts.iter().all(|p| p.kind == Kind::Theme)
    }
}

fn snake_ok(n: &str) -> bool {
    let b = n.as_bytes();
    (3..=40).contains(&b.len())
        && b[0].is_ascii_lowercase()
        && b.iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'_')
}

fn host_ok(h: &str) -> bool {
    let (host, port) = match h.rsplit_once(':') {
        Some((a, p)) => (a, Some(p)),
        None => (h, None),
    };
    if port.is_some_and(|p| p.is_empty() || p.len() > 5 || !p.bytes().all(|b| b.is_ascii_digit())) {
        return false;
    }
    let host = host.strip_prefix("*.").unwrap_or(host);
    !host.is_empty()
        && host.len() <= 253
        && host.split('.').all(|l| {
            !l.is_empty()
                && l.len() <= 63
                && !l.starts_with('-')
                && !l.ends_with('-')
                && l.bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        })
}

fn stem_of(p: &Path) -> String {
    p.file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default()
}

fn is_exec(p: &Path) -> bool {
    fs::metadata(p).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
}

/// Checks the extension at `root`: its manifest (or a theme without one, named
/// `fallback_name`), the API range, every part, the permissions against what the parts
/// do, and the whole tree for paths that leave it.
pub fn check(root: &Path, fallback_name: Option<&str>) -> Result<Checked> {
    let meta = fs::symlink_metadata(root).map_err(io_err(root))?;
    if !meta.is_dir() {
        return err(format!("{}: not a folder", root.display()));
    }
    let mpath = root.join(MANIFEST);
    let (manifest, synthesized) = match fs::symlink_metadata(&mpath) {
        Ok(m) if m.file_type().is_symlink() => {
            return err(format!("{MANIFEST} is a symlink: refused"));
        }
        Ok(_) => {
            let text = fs::read_to_string(&mpath).map_err(io_err(&mpath))?;
            (parse_manifest(&text, &mpath)?, false)
        }
        Err(_) if root.join("colors.toml").is_file() => {
            let name = fallback_name.ok_or_else(|| {
                Error("a theme without a manifest needs a name (--name)".to_owned())
            })?;
            (theme_manifest(name), true)
        }
        Err(_) => {
            return err(format!(
                "no {MANIFEST} at {} (and not a theme: no colors.toml); `bromigos ext new` makes one",
                root.display()
            ));
        }
    };
    let m = &manifest;
    let name = &m.extension.name;
    if !theme::valid_name(name) {
        return err(format!(
            "name {name:?}: lowercase letters, digits, - and _, starting with a letter or digit"
        ));
    }
    if m.extension.version.trim().is_empty() {
        return err("[extension] version is empty");
    }
    if !api_matches(&m.requires.bromigos)? {
        return err(format!(
            "{name} needs bromigOS extension API {}; this bromigOS has {API}",
            m.requires.bromigos
        ));
    }
    if m.provides.is_empty() {
        return err(format!("{name} provides nothing ([[provides]] entries)"));
    }
    if let Some(c) = compiled(root) {
        return err(format!(
            "{c}: compiled Python in an extension is refused (it could run instead of the source \
             people read): ship the .py files only"
        ));
    }
    let files = scan_tree(root)?;
    let mut warnings = vec![];
    let mut parts: Vec<CheckedPart> = vec![];
    for p in &m.provides {
        parts.push(check_part(root, name, p, &mut warnings)?);
    }
    // two parts linked at the same place
    let mut seen = BTreeSet::new();
    for p in &parts {
        for (l, _) in &p.links {
            if !seen.insert(l.clone()) {
                return err(format!("two parts are both linked as {}", l.display()));
            }
        }
    }
    // permissions against what the parts do
    let perms = &m.permissions;
    if let Network::Hosts(h) = &perms.network
        && let Some(bad) = h.iter().find(|h| !host_ok(h))
    {
        return err(format!(
            "[permissions] network: {bad:?} isn't a host name (host, *.domain, host:port)"
        ));
    }
    if let Some(v) = perms.vector.as_deref()
        && v != "read"
        && v != "desktop"
    {
        return err(format!(
            "[permissions] vector = {v:?}: \"read\" or \"desktop\"; an extension never gets VECTOR's terminal"
        ));
    }
    let coded: Vec<&str> = parts
        .iter()
        .filter(|p| p.kind.runs_code())
        .map(|p| p.kind.as_str())
        .collect();
    if !coded.is_empty() && !perms.code {
        return err(format!(
            "it runs code ({}) but [permissions] says code = false: declare code = true",
            coded.join(", ")
        ));
    }
    if coded.is_empty() && perms.code {
        warnings.push("[permissions] code = true, but no part runs code".to_owned());
    }
    let vec_tools = parts
        .iter()
        .any(|p| matches!(p.kind, Kind::VectorTool | Kind::VectorMemory));
    if vec_tools && perms.vector.is_none() {
        return err(
            "it gives VECTOR tools or memory: declare their level, [permissions] vector = \"read\" or \"desktop\"",
        );
    }
    if !parts.iter().any(|p| p.kind.for_vector()) && perms.vector.is_some() {
        warnings.push("[permissions] vector is set, but no part is for VECTOR".to_owned());
    }
    Ok(Checked {
        manifest,
        synthesized,
        parts,
        files,
        warnings,
    })
}

fn check_part(root: &Path, ext: &str, p: &Part, warnings: &mut Vec<String>) -> Result<CheckedPart> {
    let rel = safe_rel(&p.path)?;
    let abs = root.join(&rel);
    let what = format!("{} {:?}", p.kind, p.path);
    let meta = fs::symlink_metadata(&abs)
        .map_err(|_| Error(format!("{what}: no such file in the extension")))?;
    if meta.file_type().is_symlink() {
        return err(format!("{what}: a part can't be a symlink"));
    }
    let canon_root = fs::canonicalize(root).map_err(io_err(root))?;
    let canon = fs::canonicalize(&abs).map_err(io_err(&abs))?;
    if !canon.starts_with(&canon_root) {
        return err(format!("{what}: outside the extension: refused"));
    }
    if p.event.is_some() && p.kind != Kind::Hook {
        return err(format!("{what}: only a hook has an event"));
    }
    let file_with = |ext_: &str| -> Result<()> {
        if !meta.is_file() || abs.extension().and_then(|e| e.to_str()) != Some(ext_) {
            return err(format!("{what}: should be a .{ext_} file"));
        }
        Ok(())
    };
    let named = |default: String| p.name.clone().unwrap_or(default);
    let one = |link: String| vec![(PathBuf::from(link), rel.clone())];
    let (name, links) = match p.kind {
        Kind::Theme => {
            if !meta.is_dir() {
                return err(format!("{what}: a theme is a folder (with colors.toml)"));
            }
            let n = named(if rel.as_os_str().is_empty() {
                ext.to_owned()
            } else {
                stem_of(&rel)
            });
            if !theme::valid_name(&n) {
                return err(format!("{what}: theme name {n:?} isn't valid"));
            }
            // a theme loads under its own folder's name: check a copy named as installed
            theme::check_dir(&abs).map_err(|e| Error(format!("{what}: {e}")))?;
            let links = one(format!("themes/{n}"));
            (n, links)
        }
        Kind::LiveDeck => {
            file_with("py")?;
            let n = named(stem_of(&rel));
            if !theme::valid_name(&n) {
                return err(format!("{what}: deck name {n:?} isn't valid"));
            }
            let links = one(format!("live/decks/{n}.py"));
            (n, links)
        }
        Kind::LiveLayer => {
            file_with("frag")?;
            let n = named(stem_of(&rel));
            if !theme::valid_name(&n) {
                return err(format!("{what}: layer name {n:?} isn't valid"));
            }
            let mut links = one(format!("live/layers/{n}.frag"));
            let json = rel.with_extension("json");
            match fs::symlink_metadata(root.join(&json)) {
                Ok(m) if m.is_file() => links.push((format!("live/layers/{n}.json").into(), json)),
                _ => warnings.push(format!(
                    "{what}: no {} beside it: the layer starts with the defaults (off)",
                    json.display()
                )),
            }
            (n, links)
        }
        Kind::Widget => {
            file_with("py")?;
            let n = named(stem_of(&rel));
            if !snake_ok(&n) && !theme::valid_name(&n) {
                return err(format!("{what}: widget name {n:?} isn't valid"));
            }
            let links = one(format!("widgets/{n}.py"));
            (n, links)
        }
        Kind::VectorTool | Kind::VectorMemory => {
            file_with("py")?;
            let n = named(stem_of(&rel));
            if !snake_ok(&n) {
                return err(format!(
                    "{what}: VECTOR plugin name {n:?}: lower_snake_case, 3-40 characters"
                ));
            }
            let links = one(format!("vector/{n}.py"));
            (n, links)
        }
        Kind::VectorSkill => {
            let (n, link) = if meta.is_dir() {
                if !abs.join("SKILL.md").is_file() {
                    return err(format!("{what}: a skill folder needs a SKILL.md"));
                }
                let n = named(stem_of(&rel));
                let l = format!("skills/{n}");
                (n, l)
            } else {
                file_with("md")?;
                let n = named(stem_of(&rel));
                let l = format!("skills/{n}.md");
                (n, l)
            };
            let nb = n.as_bytes();
            if nb.is_empty()
                || nb.len() > 64
                || !(nb[0].is_ascii_lowercase() || nb[0].is_ascii_digit())
                || !nb
                    .iter()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-')
            {
                return err(format!(
                    "{what}: skill name {n:?}: lowercase letters, digits and -"
                ));
            }
            (n, vec![(PathBuf::from(link), rel.clone())])
        }
        Kind::HomelabAdapter => {
            file_with("py")?;
            let n = named(stem_of(&rel));
            if !snake_ok(&n) {
                return err(format!(
                    "{what}: adapter module name {n:?}: lower_snake_case, 3-40 characters"
                ));
            }
            let links = one(format!("homelab/{n}.py"));
            (n, links)
        }
        Kind::Command => {
            if !meta.is_file() {
                return err(format!("{what}: a command is a file"));
            }
            let n = named(
                rel.file_name()
                    .map(|s| s.to_string_lossy().into_owned())
                    .unwrap_or_default(),
            );
            if !crate::commands::is_command_name(&n) {
                return err(format!(
                    "{what}: a command is named bromigos-<group>[-<name>] (lowercase), not {n:?}"
                ));
            }
            if !is_exec(&abs) {
                return err(format!("{what}: not executable (chmod +x, and commit it)"));
            }
            if crate::commands::read_header(&abs).summary.is_none() {
                warnings.push(format!(
                    "{what}: no `# bromigos:summary=` line: the menu and `bromigos commands` show it bare"
                ));
            }
            let links = one(format!("bin/{n}"));
            (n, links)
        }
        Kind::Hook => {
            if !meta.is_file() {
                return err(format!("{what}: a hook is a file"));
            }
            let ev = p.event.as_deref().unwrap_or("theme-set");
            if ev != "theme-set" {
                return err(format!(
                    "{what}: event {ev:?}: the only event so far is theme-set"
                ));
            }
            if !is_exec(&abs) {
                return err(format!("{what}: not executable (chmod +x, and commit it)"));
            }
            let base = named(
                rel.file_name()
                    .map(|s| s.to_string_lossy().into_owned())
                    .unwrap_or_default(),
            );
            if base.is_empty() || base.starts_with('.') || base.contains('/') {
                return err(format!("{what}: bad hook name {base:?}"));
            }
            let links = one(format!("hooks/theme-set.d/{ext}--{base}"));
            (base, links)
        }
    };
    Ok(CheckedPart {
        kind: p.kind,
        name,
        path: p.path.clone(),
        links,
    })
}

// ------------------------------------------------------------------ the ledger

/// Where an installed extension came from.
#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
pub struct SourceRecord {
    /// `git`, or `copy` (a folder without git, copied).
    pub kind: String,
    /// The git URL, or the folder.
    pub url: String,
    /// The extension's folder inside the repository, when not its root.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    /// The branch, tag or commit asked for (the default branch's name otherwise).
    #[serde(default, rename = "ref", skip_serializing_if = "Option::is_none")]
    pub git_ref: Option<String>,
    /// `branch` (updates follow it), `tag` or `commit` (pinned), or `copy`.
    pub ref_kind: String,
    /// The catalog it was found in, by name.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub catalog: Option<String>,
}

impl SourceRecord {
    pub fn describe(&self) -> String {
        let mut s = self.url.clone();
        if let Some(p) = &self.path {
            s.push_str(&format!(" ({p})"));
        }
        match (self.ref_kind.as_str(), &self.git_ref) {
            ("copy", _) => s.push_str(" [copied]"),
            (k, Some(r)) => s.push_str(&format!(" @{r} [{k}]")),
            _ => {}
        }
        s
    }
}

/// A link a part got.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct LinkRecord {
    pub link: PathBuf,
    pub target: PathBuf,
    /// The target's sha256 (a folder's: one hash of its files' hashes).
    pub sha256: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct PartRecord {
    pub kind: Kind,
    pub name: String,
    pub path: String,
    pub links: Vec<LinkRecord>,
}

/// How an install or update was allowed.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct ApprovalRecord {
    /// `data-only` (themes: no question), `interactive` (a person said yes at a
    /// terminal), `answers` (a setup answers file approved it).
    pub how: String,
    pub when: String,
    #[serde(default)]
    pub detail: String,
}

/// One installed extension.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Entry {
    pub name: String,
    pub version: String,
    #[serde(default)]
    pub description: String,
    pub source: SourceRecord,
    #[serde(default)]
    pub commit: Option<String>,
    /// The checkout: `~/.local/share/bromigos/ext/src/<name>`.
    pub dir: PathBuf,
    /// The extension's folder: `dir`, or a folder in it.
    pub root: PathBuf,
    pub enabled: bool,
    pub installed: String,
    pub updated: String,
    pub approved: ApprovalRecord,
    pub permissions: Permissions,
    pub parts: Vec<PartRecord>,
    /// Every file under `root` and its sha256.
    pub files: BTreeMap<String, String>,
}

impl Entry {
    pub fn kinds(&self) -> Vec<Kind> {
        let s: BTreeSet<Kind> = self.parts.iter().map(|p| p.kind).collect();
        s.into_iter().collect()
    }

    pub fn data_only(&self) -> bool {
        self.parts.iter().all(|p| p.kind == Kind::Theme)
    }
}

/// An unfinished change: while it lasts, the guard accepts either version of a link.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Txn {
    pub op: String,
    pub name: String,
    pub started: String,
    pub started_unix: i64,
    pub accept: Vec<Accept>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Accept {
    pub link: PathBuf,
    /// None: the link may be missing.
    pub sha256: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Removed {
    pub name: String,
    pub url: String,
    #[serde(default)]
    pub commit: Option<String>,
    pub when: String,
}

/// `~/.local/state/bromigos/ext/ledger.json`.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Ledger {
    pub schema: u32,
    #[serde(default)]
    pub extensions: BTreeMap<String, Entry>,
    #[serde(default)]
    pub removed: Vec<Removed>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub txn: Option<Txn>,
}

impl Default for Ledger {
    fn default() -> Self {
        Ledger {
            schema: LEDGER_SCHEMA,
            extensions: BTreeMap::new(),
            removed: vec![],
            txn: None,
        }
    }
}

pub fn ledger_path(paths: &Paths) -> PathBuf {
    paths.ext_state_dir().join("ledger.json")
}

pub fn load_ledger(paths: &Paths) -> Result<Ledger> {
    let p = ledger_path(paths);
    match fs::read_to_string(&p) {
        Ok(t) => serde_json::from_str(&t).map_err(|e| {
            Error(format!(
                "{}: {e} (the ledger is unreadable: fix or move it)",
                p.display()
            ))
        }),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(Ledger::default()),
        Err(e) => Err(io_err(&p)(e)),
    }
}

fn write_atomic(p: &Path, bytes: &[u8]) -> Result<()> {
    let dir = p.parent().unwrap_or(Path::new("."));
    fs::create_dir_all(dir).map_err(io_err(dir))?;
    let tmp = dir.join(format!(
        ".{}.{}.tmp",
        p.file_name().and_then(|n| n.to_str()).unwrap_or("file"),
        std::process::id()
    ));
    let mut f = fs::File::create(&tmp).map_err(io_err(&tmp))?;
    f.write_all(bytes).map_err(io_err(&tmp))?;
    f.sync_all().map_err(io_err(&tmp))?;
    fs::rename(&tmp, p).map_err(io_err(p))?;
    if let Ok(d) = fs::File::open(dir) {
        let _ = d.sync_all();
    }
    Ok(())
}

fn save_ledger(paths: &Paths, l: &Ledger) -> Result<()> {
    let text = serde_json::to_string_pretty(l).map_err(|e| Error(e.to_string()))?;
    write_atomic(&ledger_path(paths), format!("{text}\n").as_bytes())
}

fn now() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

/// One `bromigos ext` at a time.
struct Lock(#[allow(dead_code)] fs::File);

fn lock(paths: &Paths) -> Result<Lock> {
    let dir = paths.ext_state_dir();
    fs::create_dir_all(&dir).map_err(io_err(&dir))?;
    let p = dir.join(".lock");
    let f = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(&p)
        .map_err(io_err(&p))?;
    rustix::fs::flock(&f, rustix::fs::FlockOperation::LockExclusive)
        .map_err(|e| Error(format!("{}: {e}", p.display())))?;
    Ok(Lock(f))
}

/// Appends to `~/.local/state/bromigos/ext/log.jsonl` and the journal.
fn log_event(paths: &Paths, op: &str, name: &str, detail: serde_json::Value) {
    let line = serde_json::json!({"when": now(), "op": op, "name": name, "detail": detail});
    let p = paths.ext_state_dir().join("log.jsonl");
    if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(&p) {
        let _ = writeln!(f, "{line}");
    }
    crate::log("bromigos-ext", &format!("{op} {name}: {detail}"));
}

// ------------------------------------------------------------------ sources

/// What `bromigos ext install` was given, resolved.
#[derive(Debug, Clone, PartialEq)]
pub struct Spec {
    pub source: SourceRecord,
    /// A local folder to copy (no git).
    pub copy_from: Option<PathBuf>,
}

/// `<git url|dir>[@ref]` -> (source, ref). The ref follows the last `@` after the
/// URL's host part (`git@host:org/repo.git@v1`, `https://host/x.git@main`,
/// `./dir@feature/x`).
pub fn split_ref(s: &str) -> (String, Option<String>) {
    // the host part ends at the first / after :// (a URL) or at the : of user@host:path
    let after_host = match s.find("://") {
        Some(i) => s[i + 3..].find('/').map(|j| i + 3 + j).unwrap_or(s.len()),
        None => s
            .find(':')
            .filter(|&c| {
                let head = &s[..c];
                !head.contains('/') && (head.contains('@') || head.contains('.'))
            })
            .unwrap_or(0),
    };
    match s[after_host..].rfind('@') {
        Some(j) if after_host + j + 1 < s.len() => {
            let at = after_host + j;
            (s[..at].to_owned(), Some(s[at + 1..].to_owned()))
        }
        _ => (s.to_owned(), None),
    }
}

fn url_ok(u: &str) -> bool {
    if u.starts_with('-') || u.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return false;
    }
    if let Some((scheme, _)) = u.split_once("://") {
        return matches!(scheme, "https" | "ssh" | "file");
    }
    // scp-like: user@host:path
    if let Some((head, _)) = u.split_once(':') {
        return head.contains('@') && !head.contains('/') && !head.contains("::");
    }
    false
}

fn ref_ok(r: &str) -> bool {
    !r.is_empty()
        && !r.starts_with('-')
        && !r.contains("..")
        && !r.ends_with('/')
        && r.bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-' | b'/' | b'+'))
}

/// Options for an install.
#[derive(Debug, Clone, Default)]
pub struct InstallOpts {
    /// `--ref`: a branch, tag or commit (overrides `@ref`).
    pub git_ref: Option<String>,
    /// `--path`: the extension's folder inside the repository.
    pub path: Option<String>,
    /// `--name`: a theme repository without a manifest gets this name.
    pub name: Option<String>,
    /// `--copy`: install a local folder as a copy even when it's a git repository
    /// (its working tree, uncommitted changes and all).
    pub copy: bool,
    /// `--adopt`: a theme of the user's with the same name, installed the old way, is
    /// moved aside (kept in ~/.local/state/bromigos/ext/adopted/).
    pub adopt: bool,
}

/// Resolves what the user typed: a catalog name, a git URL, a folder.
pub fn resolve(paths: &Paths, text: &str, opts: &InstallOpts) -> Result<Spec> {
    let (base, at_ref) = split_ref(text.trim());
    let git_ref = opts.git_ref.clone().or(at_ref);
    if let Some(r) = &git_ref
        && !ref_ok(r)
    {
        return err(format!("ref {r:?} isn't a branch, tag or commit name"));
    }
    if let Some(p) = &opts.path {
        safe_rel(p)?;
    }
    let local = Path::new(&base);
    let looks_local = base.starts_with('/') || base.starts_with('.') || base.starts_with('~');
    if looks_local || (local.is_dir() && !url_ok(&base)) {
        let expanded = if let Some(rest) = base.strip_prefix("~/") {
            paths.home.join(rest)
        } else {
            local.to_path_buf()
        };
        let dir = fs::canonicalize(&expanded)
            .map_err(|e| Error(format!("{}: {e}", expanded.display())))?;
        if !dir.is_dir() {
            return err(format!("{}: not a folder", dir.display()));
        }
        let is_git = dir.join(".git").exists()
            && git(Some(&dir), &["rev-parse", "--verify", "-q", "HEAD"]).is_ok();
        if is_git && !opts.copy {
            return Ok(Spec {
                source: SourceRecord {
                    kind: "git".into(),
                    url: dir.to_string_lossy().into_owned(),
                    path: opts.path.clone(),
                    git_ref,
                    ref_kind: String::new(),
                    catalog: None,
                },
                copy_from: None,
            });
        }
        if git_ref.is_some() {
            return err("a ref needs a git repository (this folder is copied)");
        }
        return Ok(Spec {
            source: SourceRecord {
                kind: "copy".into(),
                url: dir.to_string_lossy().into_owned(),
                path: opts.path.clone(),
                git_ref: None,
                ref_kind: "copy".into(),
                catalog: None,
            },
            copy_from: Some(dir),
        });
    }
    if url_ok(&base) {
        return Ok(Spec {
            source: SourceRecord {
                kind: "git".into(),
                url: base,
                path: opts.path.clone(),
                git_ref,
                ref_kind: String::new(),
                catalog: None,
            },
            copy_from: None,
        });
    }
    if base.contains("://") || base.contains(':') {
        return err(format!(
            "{base}: only https://, ssh://, file:// and git@host:path sources (or a folder)"
        ));
    }
    // a name: the catalogs
    if theme::valid_name(&base) {
        let hits = search(paths, None, None, false)?;
        if let Some(h) = hits.results.iter().find(|h| h.entry.name == base) {
            if h.entry.bundled {
                return err(format!(
                    "{base} ships with bromigOS: it's already here (bromigos theme set {base}, or see bromigos ext search {base})"
                ));
            }
            return Ok(Spec {
                source: SourceRecord {
                    kind: "git".into(),
                    url: h.entry.url.clone(),
                    path: opts.path.clone().or(h.entry.path.clone()),
                    git_ref: git_ref.or(h.entry.git_ref.clone()),
                    ref_kind: String::new(),
                    catalog: Some(h.catalog.clone()),
                },
                copy_from: None,
            });
        }
        return err(format!(
            "no extension named {base} in the catalogs{} (a git URL or a folder installs too)",
            if hits.errors.is_empty() {
                String::new()
            } else {
                format!(" ({})", hits.errors.join("; "))
            }
        ));
    }
    err(format!("{base}: not a git URL, a folder or a catalog name"))
}

/// A GitHub https URL's ssh form (`git@github.com:org/repo.git`): tried when https fails,
/// so a private repository reads with the user's ssh key (git never prompts here).
fn github_ssh(url: &str) -> Option<String> {
    let rest = url.strip_prefix("https://github.com/")?;
    let rest = rest.trim_end_matches('/');
    let rest = rest.strip_suffix(".git").unwrap_or(rest);
    (rest.split('/').count() == 2).then(|| format!("git@github.com:{rest}.git"))
}

/// Runs git with no prompts (a private repository fails instead of asking).
fn git(dir: Option<&Path>, args: &[&str]) -> Result<String> {
    let mut c = Command::new("git");
    if let Some(d) = dir {
        c.arg("-C").arg(d);
    }
    c.args([
        "-c",
        "advice.detachedHead=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "protocol.ext.allow=never",
    ])
    .args(args)
    .env("GIT_TERMINAL_PROMPT", "0")
    .env(
        "GIT_SSH_COMMAND",
        std::env::var("GIT_SSH_COMMAND").unwrap_or_else(|_| "ssh -o BatchMode=yes".into()),
    )
    .env_remove("GIT_DIR")
    .env_remove("GIT_WORK_TREE")
    .env_remove("GIT_INDEX_FILE")
    .stdin(Stdio::null())
    .stdout(Stdio::piped())
    .stderr(Stdio::piped());
    let out = c
        .output()
        .map_err(|e| Error(format!("git: {e} (is git installed?)")))?;
    if !out.status.success() {
        return err(format!(
            "git {}: {}",
            args.first().copied().unwrap_or(""),
            String::from_utf8_lossy(&out.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_owned())
}

/// A staged checkout, removed unless kept.
struct Stage {
    dir: PathBuf,
    keep: bool,
}

impl Drop for Stage {
    fn drop(&mut self) {
        if !self.keep {
            let _ = fs::remove_dir_all(&self.dir);
        }
    }
}

fn src_dir(paths: &Paths) -> PathBuf {
    paths.ext_dir().join("src")
}

fn new_stage(paths: &Paths) -> Result<Stage> {
    let src = src_dir(paths);
    fs::create_dir_all(&src).map_err(io_err(&src))?;
    let n = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.subsec_nanos())
        .unwrap_or(0);
    let dir = src.join(format!(".stage-{}-{n}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).map_err(io_err(&dir))?;
    Ok(Stage { dir, keep: false })
}

/// Copies a folder's files (not `.git`), symlinks as symlinks (checked later).
fn copy_tree(from: &Path, to: &Path) -> Result<()> {
    fs::create_dir_all(to).map_err(io_err(to))?;
    for e in fs::read_dir(from).map_err(io_err(from))? {
        let e = e.map_err(io_err(from))?;
        if e.file_name() == ".git" {
            continue;
        }
        let src = e.path();
        let dst = to.join(e.file_name());
        let meta = fs::symlink_metadata(&src).map_err(io_err(&src))?;
        if meta.file_type().is_symlink() {
            let t = fs::read_link(&src).map_err(io_err(&src))?;
            symlink(&t, &dst).map_err(io_err(&dst))?;
        } else if meta.is_dir() {
            copy_tree(&src, &dst)?;
        } else if meta.is_file() {
            fs::copy(&src, &dst).map_err(io_err(&src))?;
        }
    }
    Ok(())
}

/// Which ref to fetch: (refspec, kind, name).
fn which_ref(stage: &Path, want: Option<&str>) -> Result<(String, String, String)> {
    match want {
        None => {
            let out = git(Some(stage), &["ls-remote", "--symref", "origin", "HEAD"])?;
            let branch = out
                .lines()
                .find_map(|l| l.strip_prefix("ref: refs/heads/"))
                .and_then(|l| l.split_whitespace().next())
                .ok_or_else(|| Error("the repository has no default branch (empty?)".into()))?;
            Ok((
                format!("refs/heads/{branch}"),
                "branch".into(),
                branch.to_owned(),
            ))
        }
        Some(r) => {
            let out = git(
                Some(stage),
                &[
                    "ls-remote",
                    "origin",
                    &format!("refs/tags/{r}"),
                    &format!("refs/heads/{r}"),
                ],
            )?;
            if out.lines().any(|l| l.ends_with(&format!("refs/tags/{r}"))) {
                Ok((format!("refs/tags/{r}"), "tag".into(), r.to_owned()))
            } else if out.lines().any(|l| l.ends_with(&format!("refs/heads/{r}"))) {
                Ok((format!("refs/heads/{r}"), "branch".into(), r.to_owned()))
            } else if (7..=40).contains(&r.len()) && r.bytes().all(|b| b.is_ascii_hexdigit()) {
                Ok((r.to_owned(), "commit".into(), r.to_owned()))
            } else {
                err(format!("no branch or tag {r:?} in the repository"))
            }
        }
    }
}

/// Fetches the source into a new stage: (stage, commit, source with its ref settled).
fn fetch(paths: &Paths, spec: &Spec) -> Result<(Stage, Option<String>, SourceRecord)> {
    let stage = new_stage(paths)?;
    let mut src = spec.source.clone();
    if let Some(from) = &spec.copy_from {
        copy_tree(from, &stage.dir)?;
        return Ok((stage, None, src));
    }
    let d = Some(stage.dir.as_path());
    git(d, &["init", "-q"])?;
    git(d, &["remote", "add", "origin", &src.url])?;
    let (refspec, kind, name) = match which_ref(&stage.dir, src.git_ref.as_deref()) {
        Ok(r) => r,
        Err(e) => match github_ssh(&src.url) {
            Some(ssh) => {
                git(d, &["remote", "set-url", "origin", &ssh])?;
                which_ref(&stage.dir, src.git_ref.as_deref()).map_err(|_| e)?
            }
            None => return Err(e),
        },
    };
    let shallow = git(d, &["fetch", "-q", "--depth", "1", "origin", &refspec]);
    if shallow.is_err() {
        if kind != "commit" {
            shallow?;
        }
        // a short or unadvertised commit: fetch everything, then find it
        git(
            d,
            &[
                "fetch",
                "-q",
                "--tags",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
            ],
        )?;
        let full = git(
            d,
            &["rev-parse", "--verify", &format!("{refspec}^{{commit}}")],
        )
        .map_err(|_| Error(format!("no commit {refspec} in the repository")))?;
        git(d, &["checkout", "-q", "--detach", &full])?;
    } else {
        git(d, &["checkout", "-q", "--detach", "FETCH_HEAD^{commit}"])?;
    }
    let commit = git(d, &["rev-parse", "HEAD"])?;
    src.ref_kind = kind;
    src.git_ref = Some(if src.ref_kind == "commit" {
        commit.clone()
    } else {
        name
    });
    Ok((stage, Some(commit), src))
}

/// The extension's folder inside a checkout.
fn root_in(dir: &Path, sub: Option<&str>) -> Result<PathBuf> {
    Ok(match sub {
        Some(s) => dir.join(safe_rel(s)?),
        None => dir.to_path_buf(),
    })
}

// ------------------------------------------------------------------ collisions

/// Where each part's name is already taken outside the extensions: first-party and
/// the user's own folders (a loader's first folder wins, so a clash would hide it).
fn taken_elsewhere(paths: &Paths, p: &CheckedPart) -> Option<PathBuf> {
    let cfg = paths.user_config_dir();
    let n = &p.name;
    let candidates: Vec<PathBuf> = match p.kind {
        Kind::Theme => vec![paths.share_dir.join("themes").join(n)],
        Kind::LiveDeck => vec![
            cfg.join("plugins/live/decks").join(format!("{n}.py")),
            paths
                .config_home
                .join("bromigos-live/plugins")
                .join(format!("{n}.py")),
        ],
        Kind::LiveLayer => vec![
            cfg.join("plugins/live/layers").join(format!("{n}.frag")),
            paths
                .config_home
                .join("bromigos-live/layers")
                .join(format!("{n}.frag")),
        ],
        Kind::Widget => vec![
            PathBuf::from("/usr/lib/bromigos/widgets/plugins").join(format!("{n}.py")),
            cfg.join("plugins/widgets").join(format!("{n}.py")),
        ],
        Kind::VectorTool | Kind::VectorMemory => vec![
            cfg.join("plugins/vector").join(format!("{n}.py")),
            PathBuf::from("/usr/lib/bromigos/homelab/vector").join(format!("{n}.py")),
        ],
        Kind::VectorSkill => vec![
            cfg.join("skills").join(format!("{n}.md")),
            cfg.join("skills").join(n),
        ],
        Kind::HomelabAdapter => vec![cfg.join("plugins/homelab").join(format!("{n}.py"))],
        Kind::Command => vec![paths.lib_bin.join(n)],
        Kind::Hook => vec![],
    };
    candidates
        .into_iter()
        .find(|c| fs::symlink_metadata(c).is_ok())
}

/// A user theme folder that's a whole theme (not an overlay of a first-party one).
fn user_theme(paths: &Paths, name: &str) -> Option<PathBuf> {
    let d = paths.user_config_dir().join("themes").join(name);
    (d.join("colors.toml").is_file() && !paths.share_dir.join("themes").join(name).is_dir())
        .then_some(d)
}

/// Refuses what would clash; returns the user's same-named themes to move aside.
fn collisions(
    paths: &Paths,
    ledger: &Ledger,
    me: &str,
    parts: &[CheckedPart],
    adopt: bool,
) -> Result<Vec<(String, PathBuf)>> {
    let mut adopted = vec![];
    for p in parts {
        for (l, _) in &p.links {
            let link = paths.ext_dir().join("active").join(l);
            if let Some((other, _)) = ledger.extensions.iter().find(|(n, e)| {
                n.as_str() != me
                    && e.parts
                        .iter()
                        .any(|q| q.links.iter().any(|r| r.link == link))
            }) {
                return err(format!(
                    "{} {:?} clashes with extension {other}, which has one by that name",
                    p.kind, p.name
                ));
            }
            // there already: fine only when it's a link into this extension's own checkout
            // (its last version, or an install that didn't finish)
            if fs::symlink_metadata(&link).is_ok()
                && !fs::read_link(&link).is_ok_and(|t| t.starts_with(src_dir(paths).join(me)))
            {
                return err(format!(
                    "{} is already there and isn't this extension's: refused",
                    link.display()
                ));
            }
        }
        if let Some(t) = taken_elsewhere(paths, p) {
            return err(format!(
                "{} {:?} clashes with {} (that one would win; rename this part with name = \"…\")",
                p.kind,
                p.name,
                t.display()
            ));
        }
        if p.kind == Kind::Theme
            && let Some(d) = user_theme(paths, &p.name)
        {
            if !adopt {
                return err(format!(
                    "you have a theme named {} ({}): installed the old way, or yours. \
                     --adopt moves it aside (kept in {}) and installs this one",
                    p.name,
                    d.display(),
                    paths.ext_state_dir().join("adopted").display()
                ));
            }
            adopted.push((p.name.clone(), d));
        }
    }
    Ok(adopted)
}

// ------------------------------------------------------------------ plans, approval

/// What an install or update would do, shown before anything changes.
#[derive(Debug, Clone, Serialize)]
pub struct Plan {
    pub op: String,
    pub name: String,
    pub version: String,
    pub description: String,
    pub source: SourceRecord,
    pub commit: Option<String>,
    pub parts: Vec<CheckedPart>,
    pub permissions: Permissions,
    pub data_only: bool,
    pub warnings: Vec<String>,
    /// An update's changes.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub changes: Option<Changes>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct Changes {
    pub from_version: String,
    pub from_commit: Option<String>,
    pub added: Vec<String>,
    pub changed: Vec<String>,
    pub removed: Vec<String>,
    /// `git diff --stat`, when the old commit could be fetched.
    pub stat: Option<String>,
    /// What it may now do that it couldn't.
    pub new_permissions: Vec<String>,
    pub new_kinds: Vec<Kind>,
    /// Files of the installed copy changed by hand (they are replaced).
    pub local_edits: Vec<String>,
}

impl Plan {
    /// The plan, for a person deciding.
    pub fn describe(&self) -> String {
        let mut s = String::new();
        let verb = if self.op == "update" {
            "Update"
        } else {
            "Install"
        };
        s.push_str(&format!("{verb} {} {}", self.name, self.version));
        if !self.description.is_empty() {
            s.push_str(&format!(" — {}", self.description));
        }
        s.push('\n');
        s.push_str(&format!("  from    {}\n", self.source.describe()));
        if let Some(c) = &self.commit {
            s.push_str(&format!("  commit  {}\n", &c[..c.len().min(12)]));
        }
        s.push_str("  parts\n");
        for p in &self.parts {
            s.push_str(&format!(
                "    {:<16} {:<20} {}\n",
                p.kind.as_str(),
                p.name,
                p.kind.describe()
            ));
        }
        s.push_str("  permissions\n");
        for l in self.permissions.lines() {
            s.push_str(&format!("    {l}\n"));
        }
        if let Some(c) = &self.changes {
            s.push_str(&format!(
                "  changes from {} ({})\n",
                c.from_version,
                c.from_commit
                    .as_deref()
                    .map(|x| &x[..x.len().min(12)])
                    .unwrap_or("a copy")
            ));
            for (tag, list) in [("+", &c.added), ("~", &c.changed), ("-", &c.removed)] {
                for f in list.iter().take(40) {
                    s.push_str(&format!("    {tag} {f}\n"));
                }
                if list.len() > 40 {
                    s.push_str(&format!("    {tag} … and {} more\n", list.len() - 40));
                }
            }
            if let Some(st) = &c.stat {
                s.push_str("  git diff --stat\n");
                for l in st.lines() {
                    s.push_str(&format!("    {l}\n"));
                }
            }
            if !c.new_permissions.is_empty() || !c.new_kinds.is_empty() {
                s.push_str("  NEW PERMISSIONS\n");
                for l in &c.new_permissions {
                    s.push_str(&format!("    {l}\n"));
                }
                for k in &c.new_kinds {
                    s.push_str(&format!("    now also {}: {}\n", k, k.describe()));
                }
            }
            if !c.local_edits.is_empty() {
                s.push_str(&format!(
                    "  hand edits to the installed copy are replaced: {}\n",
                    c.local_edits.join(", ")
                ));
            }
        }
        for w in &self.warnings {
            s.push_str(&format!("  note: {w}\n"));
        }
        s
    }
}

/// How the person (or an answers file) allowed it.
#[derive(Debug, Clone, PartialEq)]
pub enum Approval {
    /// Themes only: no question.
    DataOnly,
    /// A person said yes at a terminal.
    Interactive,
    /// A setup answers file (its path or description).
    Answers(String),
}

impl Approval {
    fn record(&self) -> ApprovalRecord {
        let (how, detail) = match self {
            Approval::DataOnly => ("data-only", String::new()),
            Approval::Interactive => ("interactive", String::new()),
            Approval::Answers(d) => ("answers", d.clone()),
        };
        ApprovalRecord {
            how: how.into(),
            when: now(),
            detail,
        }
    }
}

// ------------------------------------------------------------------ links

fn active_dir(paths: &Paths) -> PathBuf {
    paths.ext_dir().join("active")
}

fn records(paths: &Paths, root: &Path, c: &Checked) -> Vec<PartRecord> {
    c.parts
        .iter()
        .map(|p| PartRecord {
            kind: p.kind,
            name: p.name.clone(),
            path: p.path.clone(),
            links: p
                .links
                .iter()
                .map(|(l, t)| {
                    let key = t.to_string_lossy().into_owned();
                    let sha = match c.files.get(&key) {
                        Some(h) => h.clone(),
                        None => tree_hash(&c.files, &key),
                    };
                    LinkRecord {
                        link: active_dir(paths).join(l),
                        target: root.join(t),
                        sha256: sha,
                    }
                })
                .collect(),
        })
        .collect()
}

/// Points `link` at `target`, replacing an old link atomically.
fn place_link(link: &Path, target: &Path) -> Result<()> {
    let dir = link.parent().unwrap_or(Path::new("/"));
    fs::create_dir_all(dir).map_err(io_err(dir))?;
    let tmp = dir.join(format!(
        ".{}.{}.link",
        link.file_name().and_then(|n| n.to_str()).unwrap_or("x"),
        std::process::id()
    ));
    let _ = fs::remove_file(&tmp);
    symlink(target, &tmp).map_err(io_err(&tmp))?;
    fs::rename(&tmp, link).map_err(io_err(link))
}

/// Removes `link` if it's a symlink into `dir`; never anything else.
fn drop_link(link: &Path, dir: &Path) {
    if let Ok(t) = fs::read_link(link)
        && t.starts_with(dir)
    {
        let _ = fs::remove_file(link);
    }
}

fn link_all(e: &Entry) -> Result<()> {
    for p in &e.parts {
        for l in &p.links {
            place_link(&l.link, &l.target)?;
        }
    }
    Ok(())
}

fn unlink_all(e: &Entry) {
    for p in &e.parts {
        for l in &p.links {
            drop_link(&l.link, &e.dir);
        }
    }
}

// ------------------------------------------------------------------ install

/// What an operation did.
#[derive(Debug, Clone, Serialize)]
pub struct Report {
    pub op: String,
    pub name: String,
    pub version: String,
    pub commit: Option<String>,
    pub detail: String,
    /// What to do next (a restart a part needs, how to use it).
    pub next: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub plan: Option<Plan>,
}

fn next_steps(e: &Entry) -> Vec<String> {
    let mut out = vec![];
    for p in &e.parts {
        let n = &p.name;
        match p.kind {
            Kind::Theme => out.push(format!("bromigos theme set {n}")),
            Kind::LiveDeck => out.push(format!("bromigos-live plugin {n}")),
            Kind::LiveLayer => out.push(format!(
                "the layer {n} draws over the background within seconds when its .json says \"enabled\": true"
            )),
            Kind::Widget => out.push(format!("the widget {n} appears within seconds")),
            Kind::VectorTool | Kind::VectorMemory | Kind::VectorSkill => {
                if !out.iter().any(|s| s.contains("restart vector")) {
                    out.push("VECTOR loads it at his next start: bromigos restart vector".into());
                }
            }
            Kind::HomelabAdapter => out.push(format!(
                "the adapter {n} loads with the homelab tools' next start (bromigos restart vector, bromigos restart widgets)"
            )),
            Kind::Command => {
                let cmd = n.strip_prefix("bromigos-").unwrap_or(n).replacen('-', " ", 1);
                out.push(format!("bromigos {cmd}"));
            }
            Kind::Hook => out.push(format!(
                "the hook {n} runs at the next bromigos theme set"
            )),
        }
    }
    out
}

/// Installs an extension. `confirm` is asked (with the plan) unless it's data only;
/// it returns how it was allowed, or None to decline.
pub fn install(
    paths: &Paths,
    text: &str,
    opts: &InstallOpts,
    confirm: &mut dyn FnMut(&Plan) -> Option<Approval>,
) -> Result<Report> {
    let spec = resolve(paths, text, opts)?;
    let _lock = lock(paths)?;
    let mut ledger = load_ledger(paths)?;
    let (mut stage, commit, source) = fetch(paths, &spec)?;
    let root = root_in(&stage.dir, source.path.as_deref())?;
    let fallback = match &opts.name {
        Some(n) => Some(n.clone()),
        None => theme::name_for(&source.url, None).ok(),
    };
    let mut c = check(&root, fallback.as_deref())?;
    if source.kind == "git"
        && Path::new(&source.url).is_dir()
        && git(Some(Path::new(&source.url)), &["status", "--porcelain"])
            .is_ok_and(|s| !s.is_empty())
    {
        c.warnings.push(format!(
            "{} has uncommitted changes: they aren't installed (commit them, or install with --copy)",
            source.url
        ));
    }
    let name = c.manifest.extension.name.clone();
    if let Some(e) = ledger.extensions.get(&name) {
        return err(format!(
            "{name} is already installed (from {}): bromigos ext update {name}, or remove it first",
            e.source.describe()
        ));
    }
    let adopted = collisions(paths, &ledger, &name, &c.parts, opts.adopt)?;
    let plan = Plan {
        op: "install".into(),
        name: name.clone(),
        version: c.manifest.extension.version.clone(),
        description: c.manifest.extension.description.clone(),
        source: source.clone(),
        commit: commit.clone(),
        parts: c.parts.clone(),
        permissions: c.manifest.permissions.clone(),
        data_only: c.data_only(),
        warnings: c.warnings.clone(),
        changes: None,
    };
    let approval = if plan.data_only {
        Approval::DataOnly
    } else {
        confirm(&plan).ok_or_else(|| Error(format!("{name}: not installed (declined)")))?
    };
    // into place
    let dir = src_dir(paths).join(&name);
    if fs::symlink_metadata(&dir).is_ok() {
        // left by an install that didn't finish (not in the ledger): ours to clear
        fs::remove_dir_all(&dir).map_err(io_err(&dir))?;
    }
    fs::rename(&stage.dir, &dir).map_err(io_err(&dir))?;
    stage.keep = true;
    let root = root_in(&dir, source.path.as_deref())?;
    let when = now();
    let entry = Entry {
        name: name.clone(),
        version: c.manifest.extension.version.clone(),
        description: c.manifest.extension.description.clone(),
        source,
        commit: commit.clone(),
        dir: dir.clone(),
        root: root.clone(),
        enabled: true,
        installed: when.clone(),
        updated: when,
        approved: approval.record(),
        permissions: c.manifest.permissions.clone(),
        parts: records(paths, &root, &c),
        files: c.files.clone(),
    };
    for (theme_name, d) in &adopted {
        let to = paths.ext_state_dir().join("adopted").join(format!(
            "{theme_name}-{}",
            chrono::Utc::now().format("%Y%m%dT%H%M%S")
        ));
        fs::create_dir_all(to.parent().unwrap_or(Path::new("/"))).map_err(io_err(&to))?;
        if fs::rename(d, &to).is_err() {
            copy_tree(d, &to)?;
            fs::remove_dir_all(d).map_err(io_err(d))?;
        }
    }
    // the ledger first: the guard accepts a link only once it's recorded
    ledger.extensions.insert(name.clone(), entry.clone());
    save_ledger(paths, &ledger)?;
    if let Err(e) = link_all(&entry) {
        unlink_all(&entry);
        ledger.extensions.remove(&name);
        let _ = save_ledger(paths, &ledger);
        let _ = fs::remove_dir_all(&dir);
        return Err(e);
    }
    log_event(
        paths,
        "install",
        &name,
        serde_json::json!({"source": entry.source, "commit": commit, "approved": entry.approved,
                           "permissions": entry.permissions, "kinds": entry.kinds()}),
    );
    Ok(Report {
        op: "install".into(),
        name: name.clone(),
        version: entry.version.clone(),
        commit,
        detail: format!(
            "installed {name} {} ({})",
            entry.version,
            entry
                .kinds()
                .iter()
                .map(|k| k.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        ),
        next: next_steps(&entry),
        plan: Some(plan),
    })
}

// ------------------------------------------------------------------ update

/// Options for an update.
#[derive(Debug, Clone, Default)]
pub struct UpdateOpts {
    /// Move to this branch, tag or commit.
    pub git_ref: Option<String>,
    /// Report what would change; change nothing.
    pub check_only: bool,
}

/// Files of the installed copy that differ from the ledger.
pub fn local_edits(e: &Entry) -> Vec<String> {
    match scan_tree(&e.root) {
        Ok(now) => {
            let keys: BTreeSet<&String> = now.keys().chain(e.files.keys()).collect();
            keys.into_iter()
                .filter(|k| now.get(*k) != e.files.get(*k))
                .cloned()
                .collect()
        }
        Err(x) => vec![format!("(unreadable: {x})")],
    }
}

fn exchange(a: &Path, b: &Path) -> io::Result<()> {
    rustix::fs::renameat_with(
        rustix::fs::CWD,
        a,
        rustix::fs::CWD,
        b,
        rustix::fs::RenameFlags::EXCHANGE,
    )
    .map_err(io::Error::from)
}

/// Updates one extension: fetches its branch (or `opts.git_ref`), shows what changed
/// and any new permissions, asks (unless it's data only and asks for nothing new),
/// then swaps the checkout in one step and relinks.
pub fn update(
    paths: &Paths,
    name: &str,
    opts: &UpdateOpts,
    confirm: &mut dyn FnMut(&Plan) -> Option<Approval>,
) -> Result<Report> {
    let _lock = lock(paths)?;
    let mut ledger = load_ledger(paths)?;
    let Some(old) = ledger.extensions.get(name).cloned() else {
        return err(format!("{name} isn't installed (bromigos ext list)"));
    };
    let edits = local_edits(&old);
    let pinned = matches!(old.source.ref_kind.as_str(), "tag" | "commit");
    if pinned && opts.git_ref.is_none() && edits.is_empty() {
        let mut detail = format!(
            "{name} is pinned to {} {}",
            old.source.ref_kind,
            old.source.git_ref.as_deref().unwrap_or("")
        );
        if old.source.ref_kind == "tag"
            && let Ok(tags) = newer_tags(&old)
            && !tags.is_empty()
        {
            detail.push_str(&format!("; newer tags: {}", tags.join(", ")));
        }
        detail.push_str(&format!(
            " (bromigos ext update {name} --ref <tag|branch|commit> moves it)"
        ));
        return Ok(Report {
            op: "pinned".into(),
            name: name.into(),
            version: old.version.clone(),
            commit: old.commit.clone(),
            detail,
            next: vec![],
            plan: None,
        });
    }
    let mut source = old.source.clone();
    if let Some(r) = &opts.git_ref {
        if source.kind != "git" {
            return err(format!("{name} was copied from a folder: it has no refs"));
        }
        if !ref_ok(r) {
            return err(format!("ref {r:?} isn't a branch, tag or commit name"));
        }
        source.git_ref = Some(r.clone());
    }
    let spec = Spec {
        copy_from: (source.kind == "copy").then(|| PathBuf::from(&source.url)),
        source: source.clone(),
    };
    let (mut stage, commit, source) = fetch(paths, &spec)?;
    let root = root_in(&stage.dir, source.path.as_deref())?;
    let c = check(&root, Some(name))?;
    if c.manifest.extension.name != name {
        return err(format!(
            "the new version calls itself {}: remove {name} and install that",
            c.manifest.extension.name
        ));
    }
    let same_commit = commit.is_some() && commit == old.commit;
    if same_commit && edits.is_empty() && c.files == old.files {
        return Ok(Report {
            op: "current".into(),
            name: name.into(),
            version: old.version.clone(),
            commit,
            detail: format!("{name} is up to date"),
            next: vec![],
            plan: None,
        });
    }
    if source.kind == "copy" && c.files == old.files && edits.is_empty() {
        return Ok(Report {
            op: "current".into(),
            name: name.into(),
            version: old.version.clone(),
            commit: None,
            detail: format!("{name} is up to date with {}", source.url),
            next: vec![],
            plan: None,
        });
    }
    let others = Ledger {
        extensions: ledger
            .extensions
            .iter()
            .filter(|(n, _)| n.as_str() != name)
            .map(|(n, e)| (n.clone(), e.clone()))
            .collect(),
        ..Ledger::default()
    };
    collisions(paths, &others, name, &c.parts, false)
        .map_err(|e| Error(format!("the new version: {e}")))?;
    let keys: BTreeSet<&String> = c.files.keys().chain(old.files.keys()).collect();
    let mut ch = Changes {
        from_version: old.version.clone(),
        from_commit: old.commit.clone(),
        local_edits: edits,
        ..Changes::default()
    };
    for k in keys {
        match (old.files.get(k), c.files.get(k)) {
            (None, Some(_)) => ch.added.push(k.clone()),
            (Some(_), None) => ch.removed.push(k.clone()),
            (Some(a), Some(b)) if a != b => ch.changed.push(k.clone()),
            _ => {}
        }
    }
    if let (Some(from), Some(to)) = (&old.commit, &commit)
        && from != to
    {
        let d = Some(stage.dir.as_path());
        if git(d, &["cat-file", "-e", &format!("{from}^{{commit}}")]).is_ok()
            || git(d, &["fetch", "-q", "--depth", "1", "origin", from]).is_ok()
        {
            let sub = source.path.clone().unwrap_or_else(|| ".".into());
            ch.stat = git(d, &["diff", "--stat", from, to, "--", &sub])
                .ok()
                .filter(|s| !s.is_empty());
        }
    }
    ch.new_permissions = old.permissions.growth(&c.manifest.permissions);
    let old_kinds: BTreeSet<Kind> = old.kinds().into_iter().collect();
    ch.new_kinds = c
        .parts
        .iter()
        .map(|p| p.kind)
        .filter(|k| !old_kinds.contains(k))
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let plan = Plan {
        op: "update".into(),
        name: name.into(),
        version: c.manifest.extension.version.clone(),
        description: c.manifest.extension.description.clone(),
        source: source.clone(),
        commit: commit.clone(),
        parts: c.parts.clone(),
        permissions: c.manifest.permissions.clone(),
        data_only: c.data_only() && old.data_only(),
        warnings: c.warnings.clone(),
        changes: Some(ch),
    };
    if opts.check_only {
        return Ok(Report {
            op: "available".into(),
            name: name.into(),
            version: plan.version.clone(),
            commit,
            detail: format!(
                "{name}: {} → {} available",
                old.version, c.manifest.extension.version
            ),
            next: vec![format!("bromigos ext update {name}")],
            plan: Some(plan),
        });
    }
    let approval = if plan.data_only {
        Approval::DataOnly
    } else {
        confirm(&plan).ok_or_else(|| Error(format!("{name}: not updated (declined)")))?
    };
    // the transaction: either version of every link is accepted until it's done
    let dir = old.dir.clone();
    let new_root = root_in(&dir, source.path.as_deref())?;
    let new_parts = records(paths, &new_root, &c);
    let mut accept = vec![];
    for p in old.parts.iter().chain(new_parts.iter()) {
        for l in &p.links {
            accept.push(Accept {
                link: l.link.clone(),
                sha256: Some(l.sha256.clone()),
            });
            accept.push(Accept {
                link: l.link.clone(),
                sha256: None,
            });
        }
    }
    ledger.txn = Some(Txn {
        op: "update".into(),
        name: name.into(),
        started: now(),
        started_unix: chrono::Utc::now().timestamp(),
        accept,
    });
    save_ledger(paths, &ledger)?;
    if exchange(&stage.dir, &dir).is_err() {
        // no RENAME_EXCHANGE here: two renames (the transaction covers the gap)
        let aside = dir.with_file_name(format!(".old-{name}-{}", std::process::id()));
        fs::rename(&dir, &aside).map_err(io_err(&dir))?;
        fs::rename(&stage.dir, &dir).map_err(io_err(&dir))?;
        stage.dir = aside;
    }
    // stage.dir now holds the old checkout (removed when `stage` drops)
    let new_links: BTreeSet<&PathBuf> = new_parts
        .iter()
        .flat_map(|p| p.links.iter().map(|l| &l.link))
        .collect();
    for p in &old.parts {
        for l in &p.links {
            if !new_links.contains(&l.link) {
                drop_link(&l.link, &dir);
            }
        }
    }
    let when = now();
    let entry = Entry {
        version: c.manifest.extension.version.clone(),
        description: c.manifest.extension.description.clone(),
        source: source.clone(),
        commit: commit.clone(),
        root: new_root,
        updated: when,
        approved: approval.record(),
        permissions: c.manifest.permissions.clone(),
        parts: new_parts,
        files: c.files.clone(),
        ..old.clone()
    };
    if entry.enabled {
        link_all(&entry)?;
    }
    ledger.extensions.insert(name.into(), entry.clone());
    ledger.txn = None;
    save_ledger(paths, &ledger)?;
    log_event(
        paths,
        "update",
        name,
        serde_json::json!({"from": old.commit, "to": commit, "source": entry.source,
                           "approved": entry.approved, "permissions": entry.permissions,
                           "new_permissions": plan.changes.as_ref().map(|c| c.new_permissions.clone())}),
    );
    Ok(Report {
        op: "update".into(),
        name: name.into(),
        version: entry.version.clone(),
        commit,
        detail: format!("updated {name}: {} → {}", old.version, entry.version),
        next: next_steps(&entry),
        plan: Some(plan),
    })
}

/// Tags newer than the one an extension is pinned to (by version order).
fn newer_tags(e: &Entry) -> Result<Vec<String>> {
    let cur = e.source.git_ref.clone().unwrap_or_default();
    let out =
        git(None, &["ls-remote", "--tags", "--refs", &e.source.url]).or_else(
            |err| match github_ssh(&e.source.url) {
                Some(ssh) => git(None, &["ls-remote", "--tags", "--refs", &ssh]),
                None => Err(err),
            },
        )?;
    let parse = |t: &str| semver::Version::parse(t.trim_start_matches('v')).ok();
    let Some(c) = parse(&cur) else {
        return Ok(vec![]);
    };
    let mut tags: Vec<(semver::Version, String)> = out
        .lines()
        .filter_map(|l| l.split("refs/tags/").nth(1))
        .filter_map(|t| parse(t).map(|v| (v, t.to_owned())))
        .filter(|(v, _)| *v > c)
        .collect();
    tags.sort();
    Ok(tags.into_iter().map(|(_, t)| t).collect())
}

// ------------------------------------------------------------------ remove, enable

/// The installed extension that provides theme `theme`, if one does.
pub fn theme_provider(paths: &Paths, theme_name: &str) -> Option<String> {
    let l = load_ledger(paths).ok()?;
    l.extensions
        .values()
        .find(|e| {
            e.parts
                .iter()
                .any(|p| p.kind == Kind::Theme && p.name == theme_name)
        })
        .map(|e| e.name.clone())
}

fn refuse_current_theme(paths: &Paths, e: &Entry, what: &str) -> Result<()> {
    let cur = theme::current(paths);
    if cur.set
        && e.parts
            .iter()
            .any(|p| p.kind == Kind::Theme && p.name == cur.name)
    {
        return err(format!(
            "{} provides the theme in force ({}): set another first (bromigos theme set …), then {what}",
            e.name, cur.name
        ));
    }
    Ok(())
}

/// Removes an extension: its links, its checkout, its ledger entry (kept in `removed`).
pub fn remove(paths: &Paths, name: &str) -> Result<Report> {
    let _lock = lock(paths)?;
    let mut ledger = load_ledger(paths)?;
    let Some(e) = ledger.extensions.get(name).cloned() else {
        return err(format!("{name} isn't installed (bromigos ext list)"));
    };
    refuse_current_theme(paths, &e, "remove it")?;
    // the ledger first: a link it no longer lists may go
    ledger.extensions.remove(name);
    ledger.removed.push(Removed {
        name: name.into(),
        url: e.source.url.clone(),
        commit: e.commit.clone(),
        when: now(),
    });
    save_ledger(paths, &ledger)?;
    unlink_all(&e);
    if e.dir.starts_with(src_dir(paths)) {
        let _ = fs::remove_dir_all(&e.dir);
    }
    log_event(
        paths,
        "remove",
        name,
        serde_json::json!({"source": e.source, "commit": e.commit}),
    );
    Ok(Report {
        op: "remove".into(),
        name: name.into(),
        version: e.version.clone(),
        commit: e.commit.clone(),
        detail: format!("removed {name}"),
        next: if e.parts.iter().any(|p| p.kind.for_vector()) {
            vec!["VECTOR drops it at his next start: bromigos restart vector".into()]
        } else {
            vec![]
        },
        plan: None,
    })
}

/// Enables or disables an extension (its links come or go; the checkout stays).
pub fn set_enabled(paths: &Paths, name: &str, on: bool) -> Result<Report> {
    let _lock = lock(paths)?;
    let mut ledger = load_ledger(paths)?;
    let Some(mut e) = ledger.extensions.get(name).cloned() else {
        return err(format!("{name} isn't installed (bromigos ext list)"));
    };
    let op = if on { "enable" } else { "disable" };
    if e.enabled == on {
        return Ok(Report {
            op: op.into(),
            name: name.into(),
            version: e.version.clone(),
            commit: e.commit.clone(),
            detail: format!("{name} is already {op}d"),
            next: vec![],
            plan: None,
        });
    }
    if on {
        let edits = local_edits(&e);
        if !edits.is_empty() {
            return err(format!(
                "{name}'s installed copy changed since it was installed ({}): \
                 bromigos ext update {name} restores it",
                edits.join(", ")
            ));
        }
        let others = Ledger {
            extensions: ledger
                .extensions
                .iter()
                .filter(|(n, x)| n.as_str() != name && x.enabled)
                .map(|(n, x)| (n.clone(), x.clone()))
                .collect(),
            ..Ledger::default()
        };
        let parts: Vec<CheckedPart> = e
            .parts
            .iter()
            .map(|p| CheckedPart {
                kind: p.kind,
                name: p.name.clone(),
                path: p.path.clone(),
                links: p
                    .links
                    .iter()
                    .filter_map(|l| {
                        l.link
                            .strip_prefix(active_dir(paths))
                            .ok()
                            .map(|r| (r.to_path_buf(), PathBuf::new()))
                    })
                    .collect(),
            })
            .collect();
        collisions(paths, &others, name, &parts, false)?;
    } else {
        refuse_current_theme(paths, &e, "disable it")?;
    }
    e.enabled = on;
    ledger.extensions.insert(name.into(), e.clone());
    save_ledger(paths, &ledger)?;
    if on {
        link_all(&e)?;
    } else {
        unlink_all(&e);
    }
    log_event(paths, op, name, serde_json::json!({}));
    Ok(Report {
        op: op.into(),
        name: name.into(),
        version: e.version.clone(),
        commit: e.commit.clone(),
        detail: format!("{op}d {name}"),
        next: if on { next_steps(&e) } else { vec![] },
        plan: None,
    })
}

// ------------------------------------------------------------------ list, info

/// One row of `bromigos ext list`.
#[derive(Debug, Clone, Serialize)]
pub struct Row {
    pub name: String,
    pub version: String,
    pub kinds: Vec<Kind>,
    pub enabled: bool,
    pub source: String,
    pub commit: Option<String>,
    /// `ok`, `disabled`, `links missing`, or `modified` (with `--verify`).
    pub status: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub problems: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Listing {
    pub extensions: Vec<Row>,
    /// The user's whole themes in ~/.config/bromigos/themes (theirs, or installed the
    /// old way, before extensions): `bromigos ext install <url> --adopt` brings one in.
    pub unmanaged_themes: Vec<String>,
    /// An update that didn't finish.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub unfinished: Option<String>,
}

fn row(e: &Entry, verify: bool) -> Row {
    let mut problems = vec![];
    if e.enabled {
        for p in &e.parts {
            for l in &p.links {
                if fs::read_link(&l.link).ok().as_deref() != Some(l.target.as_path()) {
                    problems.push(format!("missing link {}", l.link.display()));
                }
            }
        }
    }
    let edits = if verify { local_edits(e) } else { vec![] };
    let status = if !problems.is_empty() {
        "links missing"
    } else if !edits.is_empty() {
        "modified"
    } else if !e.enabled {
        "disabled"
    } else {
        "ok"
    };
    problems.extend(
        edits
            .into_iter()
            .map(|f| format!("changed since install: {f}")),
    );
    Row {
        name: e.name.clone(),
        version: e.version.clone(),
        kinds: e.kinds(),
        enabled: e.enabled,
        source: e.source.describe(),
        commit: e.commit.clone(),
        status: status.into(),
        problems,
    }
}

pub fn list(paths: &Paths, verify: bool) -> Result<Listing> {
    let ledger = load_ledger(paths)?;
    let user = paths.user_config_dir().join("themes");
    let mut unmanaged: Vec<String> = fs::read_dir(&user)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| e.file_name().into_string().ok())
        .filter(|n| theme::valid_name(n) && user_theme(paths, n).is_some())
        .collect();
    unmanaged.sort();
    Ok(Listing {
        extensions: ledger.extensions.values().map(|e| row(e, verify)).collect(),
        unmanaged_themes: unmanaged,
        unfinished: ledger
            .txn
            .as_ref()
            .map(|t| format!("{} {} (started {})", t.op, t.name, t.started)),
    })
}

/// `bromigos ext info`: an installed extension, or what one would install (fetched,
/// checked, nothing installed).
#[derive(Debug, Clone, Serialize)]
pub struct Info {
    pub installed: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub entry: Option<Entry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub row: Option<Row>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub plan: Option<Plan>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub manifest: Option<Manifest>,
}

pub fn info(paths: &Paths, what: &str, opts: &InstallOpts) -> Result<Info> {
    let ledger = load_ledger(paths)?;
    if let Some(e) = ledger.extensions.get(what) {
        let manifest = fs::read_to_string(e.root.join(MANIFEST))
            .ok()
            .and_then(|t| toml::from_str(&t).ok());
        return Ok(Info {
            installed: true,
            row: Some(row(e, true)),
            entry: Some(e.clone()),
            plan: None,
            manifest,
        });
    }
    let spec = resolve(paths, what, opts)?;
    let (stage, commit, source) = fetch(paths, &spec)?;
    let root = root_in(&stage.dir, source.path.as_deref())?;
    let fallback = opts
        .name
        .clone()
        .or_else(|| theme::name_for(&source.url, None).ok());
    let c = check(&root, fallback.as_deref())?;
    Ok(Info {
        installed: false,
        entry: None,
        row: None,
        plan: Some(Plan {
            op: "install".into(),
            name: c.manifest.extension.name.clone(),
            version: c.manifest.extension.version.clone(),
            description: c.manifest.extension.description.clone(),
            source,
            commit,
            data_only: c.data_only(),
            parts: c.parts.clone(),
            permissions: c.manifest.permissions.clone(),
            warnings: c.warnings.clone(),
            changes: None,
        }),
        manifest: Some(c.manifest),
    })
}

// ------------------------------------------------------------------ catalogs

/// One extension a catalog offers (`index.toml`'s `[[extension]]`).
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct CatalogEntry {
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub kinds: Vec<Kind>,
    pub url: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(default, rename = "ref", skip_serializing_if = "Option::is_none")]
    pub git_ref: Option<String>,
    /// A picture of it: a path in the catalog, or an https URL (in search results, the
    /// path is made absolute: the catalog's local copy).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub preview: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub authors: Vec<String>,
    #[serde(default, alias = "license", skip_serializing_if = "Option::is_none")]
    pub licence: Option<String>,
    /// Ships with bromigOS already (listed to be found; nothing to install).
    #[serde(default)]
    pub bundled: bool,
}

#[derive(Debug, Clone, Deserialize)]
struct Index {
    schema: u32,
    #[serde(default, rename = "extension")]
    extensions: Vec<CatalogEntry>,
}

/// Reads a catalog's `index.toml`.
pub fn parse_index(text: &str, path: &Path) -> Result<Vec<CatalogEntry>> {
    let i: Index = toml::from_str(text).map_err(|e| Error(format!("{}: {e}", path.display())))?;
    if i.schema != 1 {
        return err(format!(
            "{}: catalog schema {} (this bromigOS reads 1)",
            path.display(),
            i.schema
        ));
    }
    Ok(i.extensions)
}

/// One search result.
#[derive(Debug, Clone, Serialize)]
pub struct Hit {
    #[serde(flatten)]
    pub entry: CatalogEntry,
    /// The catalog it's from.
    pub catalog: String,
    /// Installed already (or shipped with bromigOS).
    pub installed: bool,
    /// The command that installs it.
    pub install: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Search {
    pub catalogs: Vec<String>,
    pub results: Vec<Hit>,
    pub errors: Vec<String>,
}

/// The catalogs: `$BROMIGOS_EXT_CATALOGS` (space-separated), else `catalogs = […]` in
/// `~/.config/bromigos/ext.toml`, else bromigOS's own.
pub fn catalogs(paths: &Paths) -> Vec<String> {
    if let Some(v) = std::env::var_os("BROMIGOS_EXT_CATALOGS") {
        let v = v.to_string_lossy();
        let list: Vec<String> = v.split_whitespace().map(str::to_owned).collect();
        if !list.is_empty() {
            return list;
        }
    }
    #[derive(Deserialize)]
    struct Conf {
        #[serde(default)]
        catalogs: Vec<String>,
    }
    let p = paths.user_config_dir().join("ext.toml");
    if let Ok(t) = fs::read_to_string(&p)
        && let Ok(c) = toml::from_str::<Conf>(&t)
        && !c.catalogs.is_empty()
    {
        return c.catalogs;
    }
    vec![DEFAULT_CATALOG.to_owned()]
}

/// A catalog's folder: a local one as it is, a git one cloned into the cache and
/// refreshed when older than six hours (or `refresh`). A stale copy is used when the
/// catalog can't be reached, with a note.
fn catalog_dir(
    paths: &Paths,
    url: &str,
    refresh: bool,
    notes: &mut Vec<String>,
) -> Result<PathBuf> {
    let local = Path::new(url);
    if !url.contains("://") && !url.contains('@') && local.is_dir() {
        return Ok(local.to_path_buf());
    }
    if !url_ok(url) {
        return err(format!("catalog {url}: not a git URL or a folder"));
    }
    let key = hex(&Sha256::digest(url.as_bytes()))[..16].to_owned();
    let dir = paths.cache_home.join("bromigos/ext/catalogs").join(key);
    let stamp = dir.join(".git/bromigos-fetched");
    let fresh = fs::metadata(&stamp)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.elapsed().ok())
        .is_some_and(|age| age.as_secs() < CATALOG_TTL_SECS);
    if fresh && !refresh {
        return Ok(dir);
    }
    let got = if dir.join(".git").is_dir() {
        git(
            Some(&dir),
            &["fetch", "-q", "--depth", "1", "origin", "HEAD"],
        )
        .and_then(|_| git(Some(&dir), &["reset", "-q", "--hard", "FETCH_HEAD"]))
    } else {
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.parent().unwrap_or(Path::new("/"))).map_err(io_err(&dir))?;
        let target = dir.to_string_lossy().into_owned();
        let clone = |u: &str| git(None, &["clone", "-q", "--depth", "1", "--", u, &target]);
        clone(url).or_else(|e| match github_ssh(url) {
            Some(ssh) => {
                let _ = fs::remove_dir_all(&dir);
                clone(&ssh)
            }
            None => Err(e),
        })
    };
    match got {
        Ok(_) => {
            let _ = fs::write(&stamp, now());
            Ok(dir)
        }
        Err(e) if dir.join("index.toml").is_file() => {
            notes.push(format!(
                "{url}: unreachable, using the copy from before ({e})"
            ));
            Ok(dir)
        }
        Err(e) => err(format!("{url}: unreachable ({e})")),
    }
}

/// `bromigos ext search`: every catalog's extensions matching `term` (name,
/// description, tags, kinds) and `kind`.
pub fn search(
    paths: &Paths,
    term: Option<&str>,
    kind: Option<Kind>,
    refresh: bool,
) -> Result<Search> {
    let cats = catalogs(paths);
    let ledger = load_ledger(paths).unwrap_or_default();
    let have_theme = |n: &str| {
        paths.share_dir.join("themes").join(n).is_dir()
            || paths.user_config_dir().join("themes").join(n).is_dir()
    };
    let mut results = vec![];
    let mut errors = vec![];
    let term = term.map(str::to_lowercase);
    for url in &cats {
        let dir = match catalog_dir(paths, url, refresh, &mut errors) {
            Ok(d) => d,
            Err(e) => {
                errors.push(e.0);
                continue;
            }
        };
        let ip = dir.join("index.toml");
        let entries = match fs::read_to_string(&ip)
            .map_err(io_err(&ip))
            .and_then(|t| parse_index(&t, &ip))
        {
            Ok(e) => e,
            Err(e) => {
                errors.push(e.0);
                continue;
            }
        };
        for e in entries {
            if let Some(k) = kind
                && !e.kinds.contains(&k)
            {
                continue;
            }
            if let Some(t) = &term {
                let hay = format!(
                    "{} {} {} {} {}",
                    e.name,
                    e.display_name.clone().unwrap_or_default(),
                    e.description,
                    e.tags.join(" "),
                    e.kinds
                        .iter()
                        .map(|k| k.as_str())
                        .collect::<Vec<_>>()
                        .join(" ")
                )
                .to_lowercase();
                if !hay.contains(t.as_str()) {
                    continue;
                }
            }
            let mut e = e;
            // a preview in the catalog becomes its local path; an https URL stays
            e.preview = e.preview.as_deref().and_then(|p| {
                if p.starts_with("https://") {
                    Some(p.to_owned())
                } else {
                    let rel = safe_rel(p).ok()?;
                    let f = dir.join(rel);
                    f.is_file().then(|| f.to_string_lossy().into_owned())
                }
            });
            let installed = ledger.extensions.contains_key(&e.name)
                || e.bundled
                || (e.kinds == [Kind::Theme] && have_theme(&e.name));
            results.push(Hit {
                install: vec![
                    "bromigos".into(),
                    "ext".into(),
                    "install".into(),
                    e.name.clone(),
                ],
                catalog: url.clone(),
                installed,
                entry: e,
            });
        }
    }
    results.sort_by(|a, b| a.entry.name.cmp(&b.entry.name));
    results.dedup_by(|a, b| a.entry.name == b.entry.name);
    Ok(Search {
        catalogs: cats,
        results,
        errors,
    })
}

// ------------------------------------------------------------------ starters

/// A starter's file: (path, text, executable).
type StarterFile = (&'static str, &'static str, bool);

macro_rules! starter {
    ($($path:literal $exec:literal),* $(,)?) => {
        &[$(($path, include_str!(concat!("../starters/", $path)), $exec)),*]
    };
}

/// Every kind's starter files (`core/crates/bromigos-core/starters/<kind>/`).
fn starter_files(kind: Kind) -> &'static [StarterFile] {
    match kind {
        Kind::Theme => starter!(
            "theme/bromigos-ext.toml" false, "theme/colors.toml" false,
            "theme/theme.toml" false, "theme/README.md" false,
        ),
        Kind::LiveDeck => starter!(
            "live-deck/bromigos-ext.toml" false, "live-deck/deck.py" false,
            "live-deck/README.md" false,
        ),
        Kind::LiveLayer => starter!(
            "live-layer/bromigos-ext.toml" false, "live-layer/layer.frag" false,
            "live-layer/layer.json" false, "live-layer/README.md" false,
        ),
        Kind::Widget => starter!(
            "widget/bromigos-ext.toml" false, "widget/widget.py" false,
            "widget/README.md" false,
        ),
        Kind::VectorTool => starter!(
            "vector-tool/bromigos-ext.toml" false, "vector-tool/tool.py" false,
            "vector-tool/README.md" false,
        ),
        Kind::VectorMemory => starter!(
            "vector-memory/bromigos-ext.toml" false, "vector-memory/memory.py" false,
            "vector-memory/README.md" false,
        ),
        Kind::VectorSkill => starter!(
            "vector-skill/bromigos-ext.toml" false, "vector-skill/skill.md" false,
            "vector-skill/README.md" false,
        ),
        Kind::HomelabAdapter => starter!(
            "homelab-adapter/bromigos-ext.toml" false, "homelab-adapter/adapter.py" false,
            "homelab-adapter/README.md" false,
        ),
        Kind::Command => starter!(
            "command/bromigos-ext.toml" false, "command/bromigos-hello" true,
            "command/README.md" false,
        ),
        Kind::Hook => starter!(
            "hook/bromigos-ext.toml" false, "hook/theme-set" true,
            "hook/README.md" false,
        ),
    }
}

/// The words a starter's placeholders become.
fn fill(text: &str, name: &str) -> String {
    let ident = name.replace('-', "_");
    let words: Vec<String> = name
        .split(['-', '_'])
        .filter(|w| !w.is_empty())
        .map(|w| {
            let mut c = w.chars();
            c.next()
                .map(|f| f.to_uppercase().collect::<String>() + c.as_str())
                .unwrap_or_default()
        })
        .collect();
    let title = words.join(" ");
    let camel = words.concat();
    let group = name.split(['-', '_']).next().unwrap_or(name);
    text.replace("__NAME__", name)
        .replace("__CAMEL__", &camel)
        .replace("__IDENT__", &ident)
        .replace("__TITLE__", &title)
        .replace("__UPPER__", &title.to_uppercase())
        .replace("__GROUP__", group)
        .replace("__API__", API)
}

/// `bromigos ext new <kind> <name>`: a working extension of that kind in `dir`
/// (default `./<name>`), ready to edit, `validate`, commit and install.
pub fn new_starter(kind: Kind, name: &str, dir: &Path) -> Result<Vec<PathBuf>> {
    if !theme::valid_name(name) {
        return err(format!(
            "name {name:?}: lowercase letters, digits, - and _, starting with a letter or digit"
        ));
    }
    if matches!(
        kind,
        Kind::VectorTool | Kind::VectorMemory | Kind::HomelabAdapter
    ) && !snake_ok(&name.replace('-', "_"))
    {
        return err(format!(
            "name {name:?}: 3-40 characters, starting with a letter (it becomes a Python module name)"
        ));
    }
    if kind == Kind::VectorTool && name.len() > 33 {
        return err(format!(
            "name {name:?}: at most 33 characters (its tool is <name>_uptime, 40 at most)"
        ));
    }
    if kind == Kind::Command && !crate::commands::is_command_name(&format!("bromigos-{name}")) {
        return err(format!(
            "name {name:?}: a command's name is lowercase words joined by - (bromigos-<name>)"
        ));
    }
    if fs::read_dir(dir).is_ok_and(|mut d| d.next().is_some()) {
        return err(format!("{}: exists and isn't empty", dir.display()));
    }
    let mut made = vec![];
    for (path, text, exec) in starter_files(kind) {
        let rel = path.split_once('/').map(|(_, r)| r).unwrap_or(path);
        let rel = if kind == Kind::Command && rel == "bromigos-hello" {
            format!("bromigos-{name}")
        } else {
            rel.to_owned()
        };
        let out = dir.join(&rel);
        if let Some(p) = out.parent() {
            fs::create_dir_all(p).map_err(io_err(p))?;
        }
        fs::write(&out, fill(text, name)).map_err(io_err(&out))?;
        if *exec {
            fs::set_permissions(&out, fs::Permissions::from_mode(0o755)).map_err(io_err(&out))?;
        }
        made.push(out);
    }
    Ok(made)
}

/// `bromigos theme new <name> --from <theme>`: an extension holding a copy of an
/// installed theme's files (its overlays merged), renamed, in `dir`.
pub fn new_theme_from(paths: &Paths, name: &str, from: &str, dir: &Path) -> Result<Vec<PathBuf>> {
    let loc = theme::Locations::new(paths);
    let srcs: Vec<PathBuf> = [&loc.system_themes, &loc.ext_themes, &loc.user_themes]
        .iter()
        .map(|d| d.join(from))
        .filter(|d| d.is_dir())
        .collect();
    if srcs.is_empty() {
        return err(format!("no theme {from:?} (bromigos theme list)"));
    }
    let made = new_starter(Kind::Theme, name, dir)?;
    for s in &srcs {
        copy_theme_files(s, dir)?;
    }
    // the manifest is the starter's; theme.toml keeps the source's look under a new name
    let tt = dir.join("theme.toml");
    let text = fs::read_to_string(&tt).unwrap_or_default();
    let mut doc: toml_edit::DocumentMut = text.parse().unwrap_or_default();
    let title = fill("__TITLE__", name);
    doc["name"] = toml_edit::value(title);
    let desc = doc
        .get("description")
        .and_then(|v| v.as_str())
        .map(|d| format!("{d} (from {from})"))
        .unwrap_or_else(|| format!("A theme made from {from}."));
    doc["description"] = toml_edit::value(desc);
    fs::write(&tt, doc.to_string()).map_err(io_err(&tt))?;
    Ok(made)
}

/// A theme folder's files (not dotfiles, not symlinks), over what's there.
fn copy_theme_files(from: &Path, to: &Path) -> Result<()> {
    fs::create_dir_all(to).map_err(io_err(to))?;
    for e in fs::read_dir(from).map_err(io_err(from))? {
        let e = e.map_err(io_err(from))?;
        let n = e.file_name();
        if n.to_string_lossy().starts_with('.') || n == MANIFEST || n == "README.md" {
            continue;
        }
        let src = e.path();
        let meta = fs::symlink_metadata(&src).map_err(io_err(&src))?;
        let dst = to.join(&n);
        if meta.file_type().is_symlink() {
            continue;
        } else if meta.is_dir() {
            copy_theme_files(&src, &dst)?;
        } else if meta.is_file() {
            fs::copy(&src, &dst).map_err(io_err(&src))?;
        }
    }
    Ok(())
}

// ------------------------------------------------------------------ migration

/// What `bromigos ext migrate` did with the themes installed before extensions.
#[derive(Debug, Clone, Serialize)]
pub struct Migration {
    /// Matched a catalog theme file for file: reinstalled as an extension (updatable),
    /// the old copy kept in ~/.local/state/bromigos/ext/adopted/.
    pub migrated: Vec<String>,
    /// Whole themes of the user's with no catalog match: left where they are.
    pub left: Vec<String>,
    pub errors: Vec<String>,
}

/// Themes installed by the old `bromigos theme install` (copied, no git) into
/// ~/.config/bromigos/themes: each one a catalog offers, with the same files, becomes
/// an extension (a checkout that updates); the rest are left as they are.
pub fn migrate(paths: &Paths, dry_run: bool) -> Result<Migration> {
    let listing = list(paths, false)?;
    let mut out = Migration {
        migrated: vec![],
        left: vec![],
        errors: vec![],
    };
    if listing.unmanaged_themes.is_empty() {
        return Ok(out);
    }
    let found = search(paths, None, Some(Kind::Theme), false)?;
    out.errors.extend(found.errors.clone());
    for t in listing.unmanaged_themes {
        let Some(hit) = found
            .results
            .iter()
            .find(|h| h.entry.name == t && !h.entry.bundled)
        else {
            out.left.push(t);
            continue;
        };
        let Some(mine) = user_theme(paths, &t) else {
            continue;
        };
        // compare files: the old install copied the theme's files (no dotfiles)
        let spec = Spec {
            source: SourceRecord {
                kind: "git".into(),
                url: hit.entry.url.clone(),
                path: hit.entry.path.clone(),
                git_ref: hit.entry.git_ref.clone(),
                ref_kind: String::new(),
                catalog: Some(hit.catalog.clone()),
            },
            copy_from: None,
        };
        let same = (|| -> Result<bool> {
            let (stage, _, src) = fetch(paths, &spec)?;
            let root = root_in(&stage.dir, src.path.as_deref())?;
            let theirs: BTreeMap<String, String> = scan_tree(&root)?
                .into_iter()
                .filter(|(k, _)| {
                    !k.split('/').any(|c| c.starts_with('.')) && k != MANIFEST && k != "README.md"
                })
                .collect();
            let ours: BTreeMap<String, String> = scan_tree(&mine)?
                .into_iter()
                .filter(|(k, _)| !k.split('/').any(|c| c.starts_with('.')))
                .collect();
            Ok(ours.iter().all(|(k, v)| theirs.get(k) == Some(v)) && !ours.is_empty())
        })();
        match same {
            Ok(true) if dry_run => out.migrated.push(t),
            Ok(true) => {
                let opts = InstallOpts {
                    adopt: true,
                    ..InstallOpts::default()
                };
                match install(paths, &t, &opts, &mut |_| None) {
                    Ok(_) => out.migrated.push(t),
                    Err(e) => out.errors.push(format!("{t}: {e}")),
                }
            }
            Ok(false) => out.left.push(t),
            Err(e) => out.errors.push(format!("{t}: {e}")),
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn refs_split_after_the_host() {
        assert_eq!(
            split_ref("git@github.com:org/repo.git@v1.2"),
            ("git@github.com:org/repo.git".into(), Some("v1.2".into()))
        );
        assert_eq!(
            split_ref("git@github.com:org/repo.git"),
            ("git@github.com:org/repo.git".into(), None)
        );
        assert_eq!(
            split_ref("https://github.com/org/repo@feature/x"),
            (
                "https://github.com/org/repo".into(),
                Some("feature/x".into())
            )
        );
        assert_eq!(
            split_ref("ssh://git@host/repo.git"),
            ("ssh://git@host/repo.git".into(), None)
        );
        assert_eq!(
            split_ref("./dir@main"),
            ("./dir".into(), Some("main".into()))
        );
        assert_eq!(split_ref("mire"), ("mire".into(), None));
        assert_eq!(split_ref("hello@v2"), ("hello".into(), Some("v2".into())));
    }

    #[test]
    fn only_safe_urls() {
        for ok in [
            "https://github.com/a/b.git",
            "ssh://git@host/x",
            "git@github.com:a/b",
            "file:///srv/x",
        ] {
            assert!(url_ok(ok), "{ok}");
        }
        for bad in [
            "-uhelp",
            "ext::sh -c touch% /tmp/x",
            "http://plain.example/x",
            "git://example/x",
            "fd::7",
            "a b",
        ] {
            assert!(!url_ok(bad), "{bad}");
        }
    }

    #[test]
    fn github_https_has_an_ssh_form() {
        assert_eq!(
            github_ssh("https://github.com/bromigos-org/extensions").as_deref(),
            Some("git@github.com:bromigos-org/extensions.git")
        );
        assert_eq!(
            github_ssh("https://github.com/a/b.git/").as_deref(),
            Some("git@github.com:a/b.git")
        );
        assert_eq!(github_ssh("https://gitlab.com/a/b"), None);
        assert_eq!(github_ssh("https://github.com/a"), None);
    }

    #[test]
    fn relative_paths_stay_inside() {
        assert_eq!(safe_rel("./a/b.py").unwrap(), PathBuf::from("a/b.py"));
        assert_eq!(safe_rel(".").unwrap(), PathBuf::new());
        for bad in ["../x", "a/../../x", "/etc/passwd", "", "-rf"] {
            assert!(safe_rel(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn api_ranges() {
        assert!(api_matches(">=1.0, <2").unwrap());
        assert!(api_matches("^1").unwrap());
        assert!(api_matches("*").unwrap());
        assert!(!api_matches(">=2").unwrap());
        assert!(api_matches("not a range").is_err());
    }

    #[test]
    fn network_forms() {
        #[derive(Deserialize)]
        struct W {
            n: Network,
        }
        let p = |s: &str| toml::from_str::<W>(s).map(|w| w.n);
        assert_eq!(p("n = \"none\"").unwrap(), Network::None);
        assert_eq!(p("n = \"any\"").unwrap(), Network::Any);
        assert_eq!(p("n = []").unwrap(), Network::None);
        assert_eq!(
            p("n = [\"api.example.com\"]").unwrap(),
            Network::Hosts(vec!["api.example.com".into()])
        );
        assert!(p("n = \"lots\"").is_err());
        assert!(host_ok("*.example.com"));
        assert!(host_ok("lab.local:8080"));
        assert!(!host_ok("http://x"));
        assert!(!host_ok("a..b"));
    }

    #[test]
    fn permission_growth() {
        let a = Permissions {
            network: Network::Hosts(vec!["a.com".into()]),
            vector: Some("read".into()),
            ..Default::default()
        };
        let b = Permissions {
            network: Network::Hosts(vec!["a.com".into(), "b.com".into()]),
            vector: Some("desktop".into()),
            code: true,
            ..Default::default()
        };
        let g = a.growth(&b);
        assert!(g.iter().any(|l| l.contains("b.com")), "{g:?}");
        assert!(g.iter().any(|l| l.contains("desktop")), "{g:?}");
        assert!(g.iter().any(|l| l.contains("runs code")), "{g:?}");
        assert!(b.growth(&a).is_empty());
    }

    #[test]
    fn every_kind_has_a_starter_that_checks() {
        for k in Kind::ALL {
            let d = tempfile::tempdir().unwrap();
            let dir = d.path().join("demo-ext");
            new_starter(k, "demo-ext", &dir).unwrap();
            let c = check(&dir, None).unwrap_or_else(|e| panic!("{k}: {e}"));
            assert_eq!(c.manifest.extension.name, "demo-ext");
            assert!(c.parts.iter().any(|p| p.kind == k), "{k}");
            assert_eq!(c.data_only(), k == Kind::Theme, "{k}");
            let text = fs::read_to_string(dir.join(MANIFEST)).unwrap();
            assert!(!text.contains("__"), "{k}: unfilled placeholder");
        }
    }
}
