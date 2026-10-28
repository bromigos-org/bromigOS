//! The idle policy as data (docs/idle.md): when the screensaver starts, the screen locks,
//! the displays go off and the machine suspends; whether sleep locks first; when the
//! worlds' creatures doze.
//!
//! Three homes, as everywhere: the packaged defaults (`/usr/share/bromigos/default/idle.toml`,
//! built in too), the user's `~/.config/bromigos/idle.toml` (a key there wins over the
//! default, key by key), and the generated hypridle config,
//! `~/.local/state/bromigos/idle/hypridle.conf`, rendered from the template
//! (`/usr/share/bromigos/idle/hypridle.conf.tpl`, minijinja, as the theme's templates) and
//! sourced by the user's `~/.config/hypr/hypridle.conf`, which can still add listeners of
//! its own.
//!
//! `bromigos idle set|preset|undo` edit the user's file (`toml_edit`: comments and keys this
//! doesn't know are kept), render, and restart this session's hypridle through `bromigos
//! restart`'s machinery ([`crate::update::Piece::Idle`]). The order of the timers is
//! checked (the screensaver before the lock, …) and odd combinations are warned about,
//! never refused. Stay awake is a timer, not a setting: a logind idle inhibitor
//! (`systemd-inhibit --what=idle`), which hypridle honours.

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use minijinja::{AutoEscape, Environment, UndefinedBehavior};
use serde::{Deserialize, Serialize};

use crate::paths::Paths;

/// The packaged defaults, built in (the file in `/usr/share/bromigos/default/` wins).
pub const DEFAULT_TOML: &str = include_str!("../idle/idle.toml");
/// The hypridle template, built in (the file in `/usr/share/bromigos/idle/` wins).
pub const TEMPLATE: &str = include_str!("../idle/hypridle.conf.tpl");

/// A new `idle.toml` starts with this.
pub const HEADER: &str = "# Your idle policy (docs/idle.md): any key here wins over bromigOS's defaults in\n\
# /usr/share/bromigos/default/idle.toml. Settings › Idle & lock and `bromigos idle` write it.";

/// What the thin `~/.config/hypr/hypridle.conf` says above its source line.
pub const HOOK_COMMENT: &str = "# Your idle policy: bromigOS's, from ~/.config/bromigos/idle.toml (Settings › Idle & lock,\n\
# `bromigos idle`), rendered into the file below; then any listeners of yours.";

/// The comment the thin file had before the policy became data (it named the timers).
const OLD_HOOK_COMMENT: &str = "# Your idle policy: bromigOS's (lock at 10 min, displays off at 15), then any listeners of yours.";

/// The limits a timer's minutes and the creatures' seconds must keep to.
pub const MINUTES: (u32, u32) = (1, 1440);
pub const ACTIVITY_SECONDS: (u32, u32) = (10, 3600);

// ------------------------------------------------------------------ the policy

/// One idle timer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Timer {
    pub enabled: bool,
    pub minutes: u32,
}

/// The worlds' keeper and creatures dozing.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Activity {
    pub enabled: bool,
    pub seconds: u32,
}

/// The whole policy, every key resolved.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Policy {
    pub screensaver: Timer,
    pub lock: Timer,
    pub displays: Timer,
    pub suspend: Timer,
    pub lock_before_sleep: bool,
    pub activity: Activity,
}

/// The four timers, in their natural order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Which {
    Screensaver,
    Lock,
    Displays,
    Suspend,
}

impl Which {
    pub const ALL: [Which; 4] = [
        Which::Screensaver,
        Which::Lock,
        Which::Displays,
        Which::Suspend,
    ];

    pub fn section(self) -> &'static str {
        match self {
            Which::Screensaver => "screensaver",
            Which::Lock => "lock",
            Which::Displays => "displays",
            Which::Suspend => "suspend",
        }
    }

    pub fn parse(s: &str) -> Option<Which> {
        match s {
            "screensaver" | "saver" => Some(Which::Screensaver),
            "lock" => Some(Which::Lock),
            "displays" | "display" | "displays-off" | "displays_off" | "dpms" => {
                Some(Which::Displays)
            }
            "suspend" | "sleep-after" => Some(Which::Suspend),
            _ => None,
        }
    }
}

impl Policy {
    pub fn timer(&self, w: Which) -> Timer {
        match w {
            Which::Screensaver => self.screensaver,
            Which::Lock => self.lock,
            Which::Displays => self.displays,
            Which::Suspend => self.suspend,
        }
    }

    pub fn timer_mut(&mut self, w: Which) -> &mut Timer {
        match w {
            Which::Screensaver => &mut self.screensaver,
            Which::Lock => &mut self.lock,
            Which::Displays => &mut self.displays,
            Which::Suspend => &mut self.suspend,
        }
    }

    /// Sets one key (a [`KEYS`] name) to a checked value.
    fn put(&mut self, key: &str, v: &Value) {
        match (key, v) {
            ("sleep.lock_before", Value::Bool(b)) => self.lock_before_sleep = *b,
            ("activity.enabled", Value::Bool(b)) => self.activity.enabled = *b,
            ("activity.seconds", Value::Int(n)) => self.activity.seconds = *n,
            (k, v) => {
                let (sec, field) = k.split_once('.').unwrap_or((k, ""));
                if let Some(w) = Which::parse(sec) {
                    match (field, v) {
                        ("enabled", Value::Bool(b)) => self.timer_mut(w).enabled = *b,
                        ("minutes", Value::Int(n)) => self.timer_mut(w).minutes = *n,
                        _ => {}
                    }
                }
            }
        }
    }

    fn get(&self, key: &str) -> Value {
        match key {
            "sleep.lock_before" => Value::Bool(self.lock_before_sleep),
            "activity.enabled" => Value::Bool(self.activity.enabled),
            "activity.seconds" => Value::Int(self.activity.seconds),
            k => {
                let (sec, field) = k.split_once('.').unwrap_or((k, ""));
                let t = Which::parse(sec).map(|w| self.timer(w));
                match (t, field) {
                    (Some(t), "enabled") => Value::Bool(t.enabled),
                    (Some(t), _) => Value::Int(t.minutes),
                    (None, _) => Value::Bool(false),
                }
            }
        }
    }
}

/// A key's value, checked.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Value {
    Bool(bool),
    Int(u32),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Kind {
    Bool,
    Minutes,
    Seconds,
}

/// Every key of `idle.toml`, `section.key`, with its kind.
const KEYS: &[(&str, Kind)] = &[
    ("screensaver.enabled", Kind::Bool),
    ("screensaver.minutes", Kind::Minutes),
    ("lock.enabled", Kind::Bool),
    ("lock.minutes", Kind::Minutes),
    ("displays.enabled", Kind::Bool),
    ("displays.minutes", Kind::Minutes),
    ("suspend.enabled", Kind::Bool),
    ("suspend.minutes", Kind::Minutes),
    ("sleep.lock_before", Kind::Bool),
    ("activity.enabled", Kind::Bool),
    ("activity.seconds", Kind::Seconds),
];

/// The keys, `section.key`.
pub fn keys() -> Vec<&'static str> {
    KEYS.iter().map(|(k, _)| *k).collect()
}

fn kind(key: &str) -> Option<Kind> {
    KEYS.iter().find(|(k, _)| *k == key).map(|(_, t)| *t)
}

fn check_range(kind: Kind, n: i64) -> Result<u32, String> {
    let (lo, hi, unit) = match kind {
        Kind::Minutes => (MINUTES.0, MINUTES.1, "minutes"),
        Kind::Seconds => (ACTIVITY_SECONDS.0, ACTIVITY_SECONDS.1, "seconds"),
        Kind::Bool => return Err("not a number".into()),
    };
    if n < lo as i64 || n > hi as i64 {
        return Err(format!("{n} {unit} is out of range ({lo} to {hi})"));
    }
    Ok(n as u32)
}

/// A TOML value as this key's kind.
fn from_toml(key: &str, v: &toml_edit::Item) -> Result<Value, String> {
    let k = kind(key).ok_or_else(|| format!("unknown key {key}"))?;
    match k {
        Kind::Bool => v
            .as_bool()
            .map(Value::Bool)
            .ok_or_else(|| format!("{key} must be true or false")),
        _ => {
            let n = v
                .as_integer()
                .ok_or_else(|| format!("{key} must be a whole number"))?;
            check_range(k, n).map(Value::Int)
        }
    }
}

// ------------------------------------------------------------------ files

/// The user's file: `~/.config/bromigos/idle.toml`.
pub fn user_file(paths: &Paths) -> PathBuf {
    paths.user_config_dir().join("idle.toml")
}

/// The packaged defaults: `/usr/share/bromigos/default/idle.toml`.
pub fn default_file(paths: &Paths) -> PathBuf {
    paths.defaults_dir().join("idle.toml")
}

/// The packaged template: `/usr/share/bromigos/idle/hypridle.conf.tpl`.
pub fn template_file(paths: &Paths) -> PathBuf {
    paths.share_dir.join("idle/hypridle.conf.tpl")
}

/// Generated state: `~/.local/state/bromigos/idle`.
pub fn state_dir(paths: &Paths) -> PathBuf {
    paths.user_state_dir().join("idle")
}

/// The rendered hypridle config: `~/.local/state/bromigos/idle/hypridle.conf`.
pub fn rendered_file(paths: &Paths) -> PathBuf {
    state_dir(paths).join("hypridle.conf")
}

/// The user's hypridle config, which sources the rendered one: `~/.config/hypr/hypridle.conf`.
pub fn hypr_file(paths: &Paths) -> PathBuf {
    paths.config_home.join("hypr/hypridle.conf")
}

/// The packaged hypridle config users sourced before the policy became data.
pub fn packaged_conf(paths: &Paths) -> PathBuf {
    paths.defaults_dir().join("hypr/hypridle.conf")
}

/// The file before the last change (`bromigos idle undo` puts it back).
fn undo_file(paths: &Paths) -> PathBuf {
    state_dir(paths).join("undo.toml")
}

/// Present when there was no user file before the last change.
fn undo_absent(paths: &Paths) -> PathBuf {
    state_dir(paths).join("undo.none")
}

/// Stay awake's record: `$XDG_RUNTIME_DIR/bromigos-idle-awake.json` (gone at logout, as
/// the inhibitor is).
pub fn awake_file(paths: &Paths) -> PathBuf {
    paths.runtime_dir.join("bromigos-idle-awake.json")
}

/// Writes atomically, through a symlink to the file it points at (a dotfiles link stays a
/// link), keeping an existing file's mode.
pub fn write_atomic(path: &Path, text: &str) -> io::Result<()> {
    let target = match fs::symlink_metadata(path) {
        Ok(m) if m.file_type().is_symlink() => fs::canonicalize(path)?,
        _ => path.to_path_buf(),
    };
    if let Some(d) = target.parent() {
        fs::create_dir_all(d)?;
    }
    let mode = fs::metadata(&target).ok().map(|m| m.permissions().mode());
    let name = target
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    let tmp = target.with_file_name(format!(".{name}.tmp-{}", std::process::id()));
    fs::write(&tmp, text)?;
    if let Some(m) = mode {
        let _ = fs::set_permissions(&tmp, fs::Permissions::from_mode(m));
    }
    fs::rename(&tmp, &target).inspect_err(|_| {
        let _ = fs::remove_file(&tmp);
    })
}

// ------------------------------------------------------------------ loading

/// Something worth saying about the policy: `warn` (likely not what was meant) or `note`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Warning {
    pub level: &'static str,
    /// The key it's about (`lock.minutes`), when it's about one.
    pub key: Option<String>,
    pub text: String,
}

fn warn(key: &str, text: impl Into<String>) -> Warning {
    Warning {
        level: "warn",
        key: (!key.is_empty()).then(|| key.to_owned()),
        text: text.into(),
    }
}

fn note(key: &str, text: impl Into<String>) -> Warning {
    Warning {
        level: "note",
        key: (!key.is_empty()).then(|| key.to_owned()),
        text: text.into(),
    }
}

/// The policy a document gives over `base`, the keys it sets, and what was wrong in it
/// (a bad value is reported and the base's kept).
fn overlay(
    base: Policy,
    doc: &toml_edit::DocumentMut,
    file: &str,
) -> (Policy, Vec<String>, Vec<Warning>) {
    let mut p = base;
    let mut set = Vec::new();
    let mut problems = Vec::new();
    for (key, _) in KEYS {
        let (sec, k) = key.split_once('.').unwrap_or((key, ""));
        let Some(item) = doc
            .get(sec)
            .and_then(|t| t.as_table_like())
            .and_then(|t| t.get(k))
        else {
            continue;
        };
        match from_toml(key, item) {
            Ok(v) => {
                p.put(key, &v);
                set.push((*key).to_owned());
            }
            Err(e) => problems.push(warn(
                key,
                format!("{file}: {e}; using {}", show(&base.get(key))),
            )),
        }
    }
    (p, set, problems)
}

fn show(v: &Value) -> String {
    match v {
        Value::Bool(b) => b.to_string(),
        Value::Int(n) => n.to_string(),
    }
}

/// Parses the built-in defaults (they're tested to be complete and valid).
pub fn builtin_defaults() -> Policy {
    let doc: toml_edit::DocumentMut = DEFAULT_TOML.parse().expect("built-in idle.toml parses");
    let zero = Policy {
        screensaver: Timer {
            enabled: false,
            minutes: 1,
        },
        lock: Timer {
            enabled: false,
            minutes: 1,
        },
        displays: Timer {
            enabled: false,
            minutes: 1,
        },
        suspend: Timer {
            enabled: false,
            minutes: 1,
        },
        lock_before_sleep: false,
        activity: Activity {
            enabled: false,
            seconds: 10,
        },
    };
    overlay(zero, &doc, "idle.toml").0
}

/// The packaged defaults: the file in `/usr/share/bromigos/default/` over the built-in ones.
pub fn defaults(paths: &Paths) -> (Policy, Vec<Warning>) {
    let base = builtin_defaults();
    let path = default_file(paths);
    match fs::read_to_string(&path) {
        Ok(text) => match text.parse::<toml_edit::DocumentMut>() {
            Ok(doc) => {
                let (p, _, w) = overlay(base, &doc, &path.display().to_string());
                (p, w)
            }
            Err(e) => (base, vec![warn("", format!("{}: {e}", path.display()))]),
        },
        Err(_) => (base, vec![]),
    }
}

/// The user's file as it is (empty when there's none), and whether it exists.
fn read_user(paths: &Paths) -> io::Result<(String, bool)> {
    match fs::read_to_string(user_file(paths)) {
        Ok(t) => Ok((t, true)),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok((String::new(), false)),
        Err(e) => Err(e),
    }
}

/// The policy in force: the defaults with the user's keys over them.
#[derive(Debug, Clone, Serialize)]
pub struct Loaded {
    pub policy: Policy,
    pub defaults: Policy,
    /// The keys the user's file sets.
    pub set: Vec<String>,
    pub exists: bool,
    /// Problems reading the files (a bad value: the default is used).
    pub problems: Vec<Warning>,
}

pub fn load(paths: &Paths) -> Loaded {
    let (defaults, mut problems) = defaults(paths);
    let file = user_file(paths);
    let (text, exists) = match read_user(paths) {
        Ok(x) => x,
        Err(e) => {
            problems.push(warn("", format!("{}: {e}", file.display())));
            (String::new(), false)
        }
    };
    match text.parse::<toml_edit::DocumentMut>() {
        Ok(doc) => {
            let (policy, set, w) = overlay(defaults, &doc, &file.display().to_string());
            problems.extend(w);
            Loaded {
                policy,
                defaults,
                set,
                exists,
                problems,
            }
        }
        Err(e) => {
            problems.push(warn(
                "",
                format!("{}: {e}; using the defaults", file.display()),
            ));
            Loaded {
                policy: defaults,
                defaults,
                set: vec![],
                exists,
                problems,
            }
        }
    }
}

// ------------------------------------------------------------------ editing

/// One change asked for, checked: `section.key` and its value.
pub type Change = (String, Value);

fn parse_bool(s: &str) -> Option<bool> {
    match s.to_ascii_lowercase().as_str() {
        "on" | "true" | "yes" | "enable" | "enabled" => Some(true),
        "off" | "false" | "no" | "disable" | "disabled" | "never" => Some(false),
        _ => None,
    }
}

/// A duration in seconds: `90`, `90s`, `8m`, `1h`, `1h30m` (a bare number is in `bare`
/// seconds: 60 for minutes, 1 for seconds).
pub fn parse_duration(s: &str, bare: u64) -> Option<u64> {
    let s = s.trim().to_ascii_lowercase();
    if s.is_empty() {
        return None;
    }
    if let Ok(n) = s.parse::<u64>() {
        return Some(n * bare);
    }
    let (mut total, mut num) = (0u64, String::new());
    for c in s.chars() {
        if c.is_ascii_digit() {
            num.push(c);
            continue;
        }
        let n: u64 = num.parse().ok()?;
        num.clear();
        total += match c {
            'h' => n * 3600,
            'm' => n * 60,
            's' => n,
            _ => return None,
        };
    }
    if !num.is_empty() {
        return None;
    }
    Some(total)
}

fn minutes_of(s: &str) -> Result<u32, String> {
    let secs = parse_duration(s, 60).ok_or_else(|| format!("{s:?}: minutes, like 8, 90m or 1h"))?;
    if secs % 60 != 0 {
        return Err(format!("{s:?}: whole minutes only"));
    }
    check_range(Kind::Minutes, (secs / 60) as i64)
}

fn seconds_of(s: &str) -> Result<u32, String> {
    let secs = parse_duration(s, 1).ok_or_else(|| format!("{s:?}: seconds, like 90, 90s or 2m"))?;
    check_range(Kind::Seconds, secs as i64)
}

/// What `bromigos idle set KEY VALUE` means, as changes:
/// - `screensaver|lock|displays|suspend on|off|MINUTES` (a time also switches it on);
/// - `activity on|off|SECONDS`, `lock-before-sleep on|off`;
/// - any `section.key` of idle.toml with its value.
pub fn parse_set(key: &str, value: &str) -> Result<Vec<Change>, String> {
    let key = key.trim().to_ascii_lowercase();
    let value = value.trim();
    let one = |k: &str, v: Value| Ok(vec![(k.to_owned(), v)]);
    if let Some(w) = Which::parse(&key) {
        let sec = w.section();
        if let Some(b) = parse_bool(value) {
            return one(&format!("{sec}.enabled"), Value::Bool(b));
        }
        let m = minutes_of(value)?;
        return Ok(vec![
            (format!("{sec}.minutes"), Value::Int(m)),
            (format!("{sec}.enabled"), Value::Bool(true)),
        ]);
    }
    match key.as_str() {
        "activity" | "doze" => {
            if let Some(b) = parse_bool(value) {
                return one("activity.enabled", Value::Bool(b));
            }
            let s = seconds_of(value)?;
            return Ok(vec![
                ("activity.seconds".into(), Value::Int(s)),
                ("activity.enabled".into(), Value::Bool(true)),
            ]);
        }
        "lock-before-sleep" | "lock_before_sleep" | "sleep" => {
            let b = parse_bool(value).ok_or_else(|| format!("{value:?}: on or off"))?;
            return one("sleep.lock_before", Value::Bool(b));
        }
        _ => {}
    }
    let k = kind(&key).ok_or_else(|| {
        format!(
            "unknown key {key:?} (screensaver, lock, displays, suspend, activity, lock-before-sleep, or one of {})",
            keys().join(", ")
        )
    })?;
    let v = match k {
        Kind::Bool => {
            Value::Bool(parse_bool(value).ok_or_else(|| format!("{value:?}: on or off"))?)
        }
        Kind::Minutes => Value::Int(minutes_of(value)?),
        Kind::Seconds => Value::Int(seconds_of(value)?),
    };
    one(&key, v)
}

/// The user's text with these changes made (comments, order and other keys kept; a
/// changed value keeps its trailing comment). `None` for a value removes the key, and a
/// table left empty goes.
pub fn edit(text: &str, changes: &[(String, Option<Value>)]) -> Result<String, String> {
    let mut doc: toml_edit::DocumentMut = text.parse().map_err(|e| format!("idle.toml: {e}"))?;
    for (key, v) in changes {
        let (sec, k) = key
            .split_once('.')
            .ok_or_else(|| format!("bad key {key}"))?;
        match v {
            Some(v) => {
                if !doc.contains_key(sec) {
                    doc.insert(sec, toml_edit::Item::Table(toml_edit::Table::new()));
                }
                let t = doc[sec]
                    .as_table_like_mut()
                    .ok_or_else(|| format!("idle.toml: {sec} isn't a table"))?;
                let decor = t
                    .get(k)
                    .and_then(|i| i.as_value())
                    .map(|v| v.decor().clone());
                let mut new = match v {
                    Value::Bool(b) => toml_edit::Value::from(*b),
                    Value::Int(n) => toml_edit::Value::from(*n as i64),
                };
                if let Some(d) = decor {
                    *new.decor_mut() = d;
                }
                t.insert(k, toml_edit::Item::Value(new));
            }
            None => {
                let empty = match doc.get_mut(sec).and_then(|i| i.as_table_like_mut()) {
                    Some(t) => {
                        t.remove(k);
                        t.is_empty()
                    }
                    None => false,
                };
                if empty {
                    doc.remove(sec);
                }
            }
        }
    }
    // the file's opening comment rides on its first table: keep it when that table goes
    let lead: String = text
        .lines()
        .take_while(|l| l.trim().is_empty() || l.trim_start().starts_with('#'))
        .map(|l| format!("{l}\n"))
        .collect();
    let lead = lead.trim_end();
    let out = doc.to_string();
    let body = out.trim_start_matches('\n');
    Ok(if !lead.is_empty() && !body.starts_with(lead) {
        format!("{lead}\n\n{body}").trim_end().to_owned() + "\n"
    } else if body.trim_start().starts_with('#') {
        body.to_owned()
    } else {
        format!("{HEADER}\n\n{body}")
    })
}

/// The presets: what each sets (the timers' minutes stay as they are).
pub const PRESETS: &[(&str, &str)] = &[
    (
        "default",
        "bromigOS's defaults: your idle.toml's timers removed",
    ),
    (
        "screensaver-only",
        "the screensaver at its time, and nothing locks, dims or sleeps; any input ends it",
    ),
    (
        "presentation",
        "nothing idles: no screensaver, no lock, the displays stay on, no suspend, the creatures stay awake",
    ),
];

/// A preset's changes to the user's file.
pub fn preset_changes(name: &str) -> Option<Vec<(String, Option<Value>)>> {
    let on = |k: &str, b: bool| (k.to_owned(), Some(Value::Bool(b)));
    match name {
        "default" | "defaults" => Some(
            KEYS.iter()
                .filter(|(k, _)| *k != "sleep.lock_before")
                .map(|(k, _)| ((*k).to_owned(), None))
                .collect(),
        ),
        "screensaver-only" | "screensaver" | "saver" => Some(vec![
            on("screensaver.enabled", true),
            on("lock.enabled", false),
            on("displays.enabled", false),
            on("suspend.enabled", false),
        ]),
        "presentation" | "none" => Some(vec![
            on("screensaver.enabled", false),
            on("lock.enabled", false),
            on("displays.enabled", false),
            on("suspend.enabled", false),
            on("activity.enabled", false),
        ]),
        _ => None,
    }
}

/// The preset this policy is, if any (`default`: the defaults' timers, switches and times).
pub fn preset_of(p: &Policy, defaults: &Policy) -> Option<&'static str> {
    let same_but_sleep = |a: &Policy, b: &Policy| {
        let mut a = *a;
        a.lock_before_sleep = b.lock_before_sleep;
        a == *b
    };
    if same_but_sleep(p, defaults) {
        return Some("default");
    }
    let off = |t: Timer| !t.enabled;
    if !p.screensaver.enabled
        && off(p.lock)
        && off(p.displays)
        && off(p.suspend)
        && !p.activity.enabled
    {
        return Some("presentation");
    }
    if p.screensaver.enabled && off(p.lock) && off(p.displays) && off(p.suspend) {
        return Some("screensaver-only");
    }
    None
}

/// True when nothing locks on idle and the screensaver still runs: the bar's eye.
pub fn screensaver_only(p: &Policy) -> bool {
    p.screensaver.enabled && !p.lock.enabled && !p.suspend.enabled
}

// ------------------------------------------------------------------ checking

fn m(n: u32) -> String {
    if n.is_multiple_of(60) && n >= 60 {
        let h = n / 60;
        format!("{h} h")
    } else if n > 60 {
        format!("{} h {} min", n / 60, n % 60)
    } else {
        format!("{n} min")
    }
}

/// The order and the odd combinations: warnings and notes, never refusals.
pub fn check(p: &Policy) -> Vec<Warning> {
    let mut out = Vec::new();
    let (s, l, d, z) = (p.screensaver, p.lock, p.displays, p.suspend);
    if s.enabled && l.enabled && s.minutes >= l.minutes {
        out.push(warn(
            "screensaver.minutes",
            format!(
                "The screensaver ({}) doesn't come before the lock ({}): the lock covers it, so it never shows. Start it before {}.",
                m(s.minutes), m(l.minutes), m(l.minutes)
            ),
        ));
    }
    if s.enabled && d.enabled && d.minutes <= s.minutes {
        out.push(warn(
            "displays.minutes",
            format!(
                "The displays go off ({}) before the screensaver starts ({}): it would run on dark screens.",
                m(d.minutes), m(s.minutes)
            ),
        ));
    }
    if l.enabled && d.enabled && d.minutes < l.minutes {
        out.push(note(
            "displays.minutes",
            format!(
                "The displays go off ({}) before the lock ({}): until then a key wakes them unlocked.",
                m(d.minutes), m(l.minutes)
            ),
        ));
    }
    if z.enabled {
        if s.enabled && z.minutes <= s.minutes {
            out.push(warn(
                "suspend.minutes",
                format!(
                    "It suspends ({}) before the screensaver starts ({}).",
                    m(z.minutes),
                    m(s.minutes)
                ),
            ));
        }
        if d.enabled && z.minutes <= d.minutes {
            out.push(note(
                "suspend.minutes",
                format!(
                    "It suspends ({}) before the displays would go off ({}), so that timer never fires.",
                    m(z.minutes), m(d.minutes)
                ),
            ));
        }
        if !p.lock_before_sleep && (!l.enabled || z.minutes <= l.minutes) {
            out.push(warn(
                "suspend.enabled",
                format!(
                    "It suspends at {} without locking first: whoever wakes it gets your desktop. Turn on locking before sleep.",
                    m(z.minutes)
                ),
            ));
        }
    }
    if !p.lock_before_sleep && !(z.enabled && (!l.enabled || z.minutes <= l.minutes)) {
        out.push(warn(
            "sleep.lock_before",
            "Sleep doesn't lock first: whoever wakes the machine (lid, power menu, a suspend) gets your desktop.",
        ));
    }
    if !l.enabled {
        out.push(note(
            "lock.enabled",
            "Nothing locks on idle: anyone at this machine gets your desktop. SUPER+L still locks.",
        ));
    }
    if p.activity.enabled && s.enabled && p.activity.seconds >= s.minutes * 60 {
        out.push(note(
            "activity.seconds",
            format!(
                "The creatures doze ({} s) only after the screensaver starts ({}).",
                p.activity.seconds,
                m(s.minutes)
            ),
        ));
    }
    out
}

/// The policy in plain words: "Screensaver at 8 min, then nothing locks; …".
pub fn summary(p: &Policy) -> String {
    let mut events: Vec<(u32, Which)> = Which::ALL
        .iter()
        .filter(|w| p.timer(**w).enabled)
        .map(|w| (p.timer(*w).minutes, *w))
        .collect();
    events.sort();
    if events.is_empty() {
        let mut s = "Nothing idles: no screensaver, no lock, the displays stay on, never suspends"
            .to_owned();
        if !p.activity.enabled {
            s.push_str(", the creatures stay awake");
        }
        return s + ".";
    }
    let first = |w: Which| match w {
        Which::Screensaver => "Screensaver",
        Which::Lock => "Lock",
        Which::Displays => "Displays off",
        Which::Suspend => "Suspend",
    };
    let later = |w: Which| match w {
        Which::Screensaver => "the screensaver",
        Which::Lock => "the lock",
        Which::Displays => "displays off",
        Which::Suspend => "suspend",
    };
    let mut s = format!("{} at {}", first(events[0].1), m(events[0].0));
    for (min, w) in &events[1..] {
        s.push_str(&format!(", then {} at {}", later(*w), m(*min)));
    }
    let mut tail = Vec::new();
    if !p.lock.enabled {
        tail.push("nothing locks");
    }
    if !p.displays.enabled {
        tail.push("the displays stay on");
    }
    if !p.suspend.enabled {
        tail.push("never suspends");
    }
    if !tail.is_empty() {
        let t = tail.join("; ");
        if p.lock.enabled {
            let mut c = t.chars();
            let cap: String = c
                .next()
                .map(|f| f.to_uppercase().chain(c).collect())
                .unwrap_or_default();
            s.push_str(". ");
            s.push_str(&cap);
        } else {
            s.push_str(", then ");
            s.push_str(&t);
        }
    }
    s.push('.');
    if !p.lock_before_sleep {
        s.push_str(" Sleep doesn't lock first.");
    }
    s
}

// ------------------------------------------------------------------ rendering

fn timer_ctx(t: Timer) -> minijinja::Value {
    minijinja::Value::from_serialize(BTreeMap::from([
        ("enabled", minijinja::Value::from(t.enabled)),
        ("minutes", minijinja::Value::from(t.minutes)),
        ("seconds", minijinja::Value::from(t.minutes * 60)),
    ]))
}

/// The template's context: each timer (`enabled`, `minutes`, `seconds`), `activity`
/// (`enabled`, `seconds`), `lock_before_sleep`, `summary` and `dispatch` (the Hyprland
/// dispatcher tool's path).
fn context(p: &Policy, dispatch: &str) -> minijinja::Value {
    let mut ctx: BTreeMap<&str, minijinja::Value> = BTreeMap::new();
    for w in Which::ALL {
        ctx.insert(w.section(), timer_ctx(p.timer(w)));
    }
    ctx.insert(
        "activity",
        minijinja::Value::from_serialize(BTreeMap::from([
            ("enabled", minijinja::Value::from(p.activity.enabled)),
            ("seconds", minijinja::Value::from(p.activity.seconds)),
        ])),
    );
    ctx.insert(
        "lock_before_sleep",
        minijinja::Value::from(p.lock_before_sleep),
    );
    ctx.insert("summary", minijinja::Value::from(summary(p)));
    ctx.insert("dispatch", minijinja::Value::from(dispatch));
    minijinja::Value::from_serialize(&ctx)
}

/// Renders a template with the policy (strict: an unknown name is an error).
pub fn render_with(template: &str, p: &Policy, dispatch: &str) -> Result<String, String> {
    let mut env = Environment::new();
    env.set_undefined_behavior(UndefinedBehavior::Strict);
    env.set_keep_trailing_newline(true);
    env.set_auto_escape_callback(|_| AutoEscape::None);
    let mut out = env
        .render_named_str("hypridle.conf.tpl", template, context(p, dispatch))
        .map_err(|e| format!("hypridle.conf.tpl: {e:#}"))?;
    if !out.ends_with('\n') {
        out.push('\n');
    }
    Ok(out)
}

/// The template in force: the packaged file, else the built-in one.
pub fn template(paths: &Paths) -> String {
    fs::read_to_string(template_file(paths)).unwrap_or_else(|_| TEMPLATE.to_owned())
}

/// The dispatcher tool hypridle calls for the displays (`/usr/lib/bromigos/bin/bromigos-dispatch`).
pub fn dispatch(paths: &Paths) -> String {
    paths
        .lib_bin
        .join("bromigos-dispatch")
        .to_string_lossy()
        .into_owned()
}

/// The hypridle config for the policy in force.
pub fn render(paths: &Paths, p: &Policy) -> Result<String, String> {
    render_with(&template(paths), p, &dispatch(paths))
}

/// Renders the policy in force into the state file, written only when it changed.
/// Returns whether it was written.
pub fn render_file(paths: &Paths) -> Result<bool, String> {
    let text = render(paths, &load(paths).policy)?;
    let path = rendered_file(paths);
    if fs::read_to_string(&path).is_ok_and(|t| t == text) {
        return Ok(false);
    }
    write_atomic(&path, &text).map_err(|e| format!("{}: {e}", path.display()))?;
    Ok(true)
}

// ------------------------------------------------------------------ the user's hypridle.conf

/// How `~/.config/hypr/hypridle.conf` takes the policy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum Hook {
    /// It sources the rendered policy: settings reach hypridle.
    Rendered,
    /// It still sources the packaged hypridle.conf (before the policy was data).
    Packaged,
    /// It sources neither: the user's own idle setup.
    Other,
    /// There's no such file.
    Missing,
}

fn source_lines(text: &str) -> Vec<(usize, String)> {
    text.lines()
        .enumerate()
        .filter_map(|(i, l)| {
            let l = l.trim();
            let rest = l.strip_prefix("source")?.trim_start().strip_prefix('=')?;
            let v = rest.split(" #").next().unwrap_or(rest).trim();
            Some((i, v.to_owned()))
        })
        .collect()
}

fn expand(paths: &Paths, v: &str) -> PathBuf {
    let v = v.trim();
    if let Some(r) = v.strip_prefix("~/") {
        return paths.home.join(r);
    }
    for var in ["$HOME/", "${HOME}/"] {
        if let Some(r) = v.strip_prefix(var) {
            return paths.home.join(r);
        }
    }
    for var in ["$XDG_STATE_HOME/", "${XDG_STATE_HOME}/"] {
        if let Some(r) = v.strip_prefix(var) {
            return paths.state_home.join(r);
        }
    }
    PathBuf::from(v)
}

/// What a hypridle.conf's text sources.
pub fn hook_of(paths: &Paths, text: &str) -> Hook {
    let rendered = rendered_file(paths);
    let packaged = packaged_conf(paths);
    let mut seen = Hook::Other;
    for (_, v) in source_lines(text) {
        let p = expand(paths, &v);
        if p == rendered {
            return Hook::Rendered;
        }
        if p == packaged || p == Path::new("/usr/share/bromigos/default/hypr/hypridle.conf") {
            seen = Hook::Packaged;
        }
    }
    seen
}

/// The state of the user's hypridle.conf.
pub fn hooked(paths: &Paths) -> Hook {
    match fs::read_to_string(hypr_file(paths)) {
        Ok(t) => hook_of(paths, &t),
        Err(_) => Hook::Missing,
    }
}

/// The source line for the rendered policy: `~/…` when the state home is the usual one,
/// so a file kept in dotfiles works for any user.
pub fn source_line(paths: &Paths) -> String {
    let r = rendered_file(paths);
    match r.strip_prefix(&paths.home) {
        Ok(rel) if paths.state_home == paths.home.join(".local/state") => {
            format!("source = ~/{}", rel.display())
        }
        _ => format!("source = {}", r.display()),
    }
}

/// The thin hypridle.conf a user starts from.
pub fn thin_file(paths: &Paths) -> String {
    format!("{HOOK_COMMENT}\n{}\n", source_line(paths))
}

/// A hypridle.conf's text moved to the rendered policy: the packaged source line becomes
/// the rendered one, the old seeded comment the new one; everything else (the user's own
/// listeners) is kept as it is.
pub fn rehook(paths: &Paths, text: &str) -> String {
    let packaged: Vec<usize> = source_lines(text)
        .into_iter()
        .filter(|(_, v)| {
            let p = expand(paths, v);
            p == packaged_conf(paths)
                || p == Path::new("/usr/share/bromigos/default/hypr/hypridle.conf")
        })
        .map(|(i, _)| i)
        .collect();
    let mut out = String::new();
    let mut done = false;
    for (i, line) in text.lines().enumerate() {
        if line.trim() == OLD_HOOK_COMMENT {
            out.push_str(HOOK_COMMENT);
        } else if packaged.contains(&i) {
            if done {
                continue;
            }
            let indent: String = line.chars().take_while(|c| c.is_whitespace()).collect();
            out.push_str(&indent);
            out.push_str(&source_line(paths));
            done = true;
        } else {
            out.push_str(line);
        }
        out.push('\n');
    }
    out
}

/// What `bromigos idle hook` did.
#[derive(Debug, Clone, Serialize)]
pub struct Hooked {
    pub file: PathBuf,
    /// `made`, `moved`, `kept`, `yours`.
    pub outcome: &'static str,
    /// The file as it was, when it was changed.
    pub backup: Option<PathBuf>,
    pub detail: String,
}

/// Points the user's hypridle.conf at the rendered policy (what the update's migration
/// runs): made where there's none, the packaged source line replaced (the file kept in a
/// backup first, written through a symlink), left alone when it's already there or is the
/// user's own setup. Renders the policy first, so the file it sources exists.
pub fn hook(paths: &Paths) -> Result<Hooked, String> {
    render_file(paths)?;
    let file = hypr_file(paths);
    let text = match fs::read_to_string(&file) {
        Ok(t) => Some(t),
        Err(e) if e.kind() == io::ErrorKind::NotFound && fs::symlink_metadata(&file).is_err() => {
            None
        }
        Err(e) => return Err(format!("{}: {e}", file.display())),
    };
    let Some(text) = text else {
        write_atomic(&file, &thin_file(paths)).map_err(|e| format!("{}: {e}", file.display()))?;
        return Ok(Hooked {
            file,
            outcome: "made",
            backup: None,
            detail: "it sources the rendered policy".into(),
        });
    };
    match hook_of(paths, &text) {
        Hook::Rendered | Hook::Missing => Ok(Hooked {
            file,
            outcome: "kept",
            backup: None,
            detail: "it already sources the rendered policy".into(),
        }),
        Hook::Other => Ok(Hooked {
            file,
            outcome: "yours",
            backup: None,
            detail: format!(
                "it doesn't source bromigOS's policy, so Settings and `bromigos idle` don't reach it; to use them, add: {}",
                source_line(paths)
            ),
        }),
        Hook::Packaged => {
            let backup = state_dir(paths).join("hypridle.conf.before-policy");
            if !backup.exists() {
                fs::create_dir_all(state_dir(paths)).map_err(|e| e.to_string())?;
                fs::write(&backup, &text).map_err(|e| format!("{}: {e}", backup.display()))?;
            }
            write_atomic(&file, &rehook(paths, &text))
                .map_err(|e| format!("{}: {e}", file.display()))?;
            Ok(Hooked {
                file,
                outcome: "moved",
                backup: Some(backup),
                detail: "it sources the rendered policy now; your own lines are kept".into(),
            })
        }
    }
}

// ------------------------------------------------------------------ saving, undo

/// Writes the user's file, keeping what it was for `undo`.
pub fn save(paths: &Paths, text: &str) -> Result<(), String> {
    let (old, existed) = read_user(paths).map_err(|e| e.to_string())?;
    let dir = state_dir(paths);
    fs::create_dir_all(&dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    if existed {
        write_atomic(&undo_file(paths), &old).map_err(|e| e.to_string())?;
        let _ = fs::remove_file(undo_absent(paths));
    } else {
        let _ = fs::remove_file(undo_file(paths));
        fs::write(undo_absent(paths), "").map_err(|e| e.to_string())?;
    }
    let f = user_file(paths);
    write_atomic(&f, text).map_err(|e| format!("{}: {e}", f.display()))
}

/// Puts the file back as it was before the last change (and keeps the current one, so a
/// second undo redoes). Err when there's nothing to undo.
pub fn undo(paths: &Paths) -> Result<(), String> {
    let back = if undo_absent(paths).exists() {
        None
    } else {
        match fs::read_to_string(undo_file(paths)) {
            Ok(t) => Some(t),
            Err(_) => return Err("nothing to undo".into()),
        }
    };
    let (cur, existed) = read_user(paths).map_err(|e| e.to_string())?;
    if existed {
        write_atomic(&undo_file(paths), &cur).map_err(|e| e.to_string())?;
        let _ = fs::remove_file(undo_absent(paths));
    } else {
        let _ = fs::remove_file(undo_file(paths));
        fs::write(undo_absent(paths), "").map_err(|e| e.to_string())?;
    }
    let f = user_file(paths);
    match back {
        Some(t) => write_atomic(&f, &t).map_err(|e| format!("{}: {e}", f.display())),
        None => match fs::remove_file(&f) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(format!("{}: {e}", f.display())),
        },
    }
}

/// Applies changes to the user's file: checked, written (with an undo point), rendered.
pub fn change(paths: &Paths, changes: &[(String, Option<Value>)]) -> Result<(), String> {
    let (text, _) = read_user(paths).map_err(|e| e.to_string())?;
    let new = edit(&text, changes)?;
    if new == text {
        return Ok(());
    }
    save(paths, &new)
}

// ------------------------------------------------------------------ hypridle

/// This user's hypridle processes.
pub fn hypridle_pids() -> Vec<i32> {
    crate::update::running(Path::new("/proc"))
        .into_iter()
        .filter(|r| r.piece == crate::update::Piece::Idle)
        .flat_map(|r| r.pids)
        .collect()
}

/// The hypridle of the session these paths find (its Wayland display), never another
/// session's or a test's: what `bromigos idle` restarts.
pub fn session_hypridle(paths: &Paths) -> Vec<i32> {
    let Some(s) = crate::session::discover(paths).session else {
        return vec![];
    };
    hypridle_pids()
        .into_iter()
        .filter(|p| {
            crate::session::environ_var(*p, "WAYLAND_DISPLAY").as_deref()
                == Some(s.wayland_display.as_str())
        })
        .collect()
}

/// Renders, then restarts this session's hypridle through the restart machinery (it reads
/// its config only at start). Nothing to restart when it isn't running.
pub fn apply(paths: &Paths) -> Result<Applied, String> {
    let rendered = render_file(paths)?;
    let pids = session_hypridle(paths);
    let restarts = if pids.is_empty() {
        vec![]
    } else {
        let done = crate::update::execute(
            paths,
            &[crate::update::Plan {
                what: crate::update::Piece::Idle.name().to_owned(),
                need: crate::update::Need::Restart,
                why: "the idle policy changed".to_owned(),
                pids,
                unit: None,
                package: None,
            }],
        );
        // the compositor starts the new one a moment later: wait for it (2 s at most), so
        // what's said next (status, the bar) sees it running
        if done.iter().all(|d| d.ok) {
            for _ in 0..20 {
                if !session_hypridle(paths).is_empty() {
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
        }
        done
    };
    refresh_bar();
    Ok(Applied { rendered, restarts })
}

/// When the running hypridle reads an older policy than there is now: the policy renders
/// differently from the file (a newer template, or idle.toml edited by hand), or a file it
/// reads changed after it started. A reload for `bromigos restart` and an update's restarts.
pub fn stale(
    paths: &Paths,
    runs: &[crate::update::Running],
    planned: &[crate::update::Plan],
) -> Option<crate::update::Plan> {
    use crate::update::{Need, Piece, Plan};
    let r = runs.iter().find(|r| r.piece == Piece::Idle)?;
    if planned.iter().any(|p| p.what == Piece::Idle.name()) {
        return None;
    }
    // only this session's hypridle reads these files (never another session's, or the
    // desktop's from a test's sandbox)
    let mine = session_hypridle(paths);
    let pids: Vec<i32> = r
        .pids
        .iter()
        .copied()
        .filter(|p| mine.contains(p))
        .collect();
    if pids.is_empty() {
        return None;
    }
    let mtime = |p: &Path| {
        fs::metadata(fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf()))
            .ok()
            .and_then(|m| m.modified().ok())
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_secs() as i64)
    };
    let hooked = hooked(paths) == Hook::Rendered;
    // a process's start is known to the second only (boot time is whole seconds), so a
    // file written in the second before the restart isn't "newer"
    let newer = |p: &Path| {
        r.started
            .is_some_and(|s| mtime(p).is_some_and(|m| m > s + 1))
    };
    let why = if hooked
        && render(paths, &load(paths).policy).is_ok_and(|t| {
            fs::read_to_string(rendered_file(paths)).ok().as_deref() != Some(t.as_str())
        }) {
        "its policy renders differently now (idle.toml or a newer template)"
    } else if newer(&hypr_file(paths)) || (hooked && newer(&rendered_file(paths))) {
        "its config changed after it started"
    } else {
        return None;
    };
    Some(Plan {
        what: Piece::Idle.name().to_owned(),
        need: Need::Reload,
        why: why.to_owned(),
        pids,
        unit: None,
        package: None,
    })
}

/// What `apply` did.
#[derive(Debug, Clone, Serialize)]
pub struct Applied {
    /// The rendered file changed.
    pub rendered: bool,
    pub restarts: Vec<crate::update::Done>,
}

/// The bar's idle module reads the state again now (its signal), not at its next interval.
pub fn refresh_bar() {
    let _ = Command::new("pkill")
        .args([&format!("-RTMIN+{BAR_SIGNAL}"), "-x", "waybar"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

/// The waybar signal the idle module refreshes on (`"signal": 10`).
pub const BAR_SIGNAL: u32 = 10;

/// Starts hypridle now, in this session, through the compositor (as a restart does), unless
/// it already runs there. Ok(false): it was running.
pub fn start_detached(paths: &Paths) -> Result<bool, String> {
    render_file(paths)?;
    if !session_hypridle(paths).is_empty() {
        return Ok(false);
    }
    let env = crate::update::session_env(paths);
    if env.is_empty() {
        return Err("no running Hyprland session".into());
    }
    crate::update::start_in_compositor(paths, &env, "hypridle")?;
    refresh_bar();
    Ok(true)
}

/// Starts hypridle for the login (Hyprland's autostart): renders the policy, then becomes
/// hypridle. Returns only on failure.
pub fn exec_hypridle(paths: &Paths) -> io::Error {
    if let Err(e) = render_file(paths) {
        crate::log("bromigos-idle", &format!("render: {e}"));
    }
    Command::new("hypridle").arg0("hypridle").exec()
}

// ------------------------------------------------------------------ stay awake

/// Stay awake: a logind idle inhibitor, `systemd-inhibit --what=idle … sleep N`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Awake {
    pub on: bool,
    /// systemd-inhibit's PID (its process group: the sleep under it goes with it).
    pub pid: Option<i32>,
    pub started: Option<i64>,
    /// When it ends (Unix seconds); None while on: until turned off.
    pub until: Option<i64>,
    /// `until` as local time (RFC 3339).
    pub until_local: Option<String>,
    pub remaining_s: Option<i64>,
}

impl Awake {
    fn off() -> Self {
        Awake {
            on: false,
            pid: None,
            started: None,
            until: None,
            until_local: None,
            remaining_s: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct AwakeRecord {
    pid: i32,
    started: i64,
    until: Option<i64>,
}

const WHO: &str = "bromigOS";

fn now() -> i64 {
    chrono::Local::now().timestamp()
}

fn local(t: i64) -> Option<chrono::DateTime<chrono::Local>> {
    chrono::DateTime::from_timestamp(t, 0).map(|d| d.with_timezone(&chrono::Local))
}

/// Whether `pid` is our inhibitor (not a reused PID).
fn is_ours(pid: i32) -> bool {
    let Ok(raw) = fs::read(format!("/proc/{pid}/cmdline")) else {
        return false;
    };
    let argv: Vec<String> = raw
        .split(|b| *b == 0)
        .filter(|a| !a.is_empty())
        .map(|a| String::from_utf8_lossy(a).into_owned())
        .collect();
    argv.first().is_some_and(|a| a.ends_with("systemd-inhibit"))
        && argv.iter().any(|a| a == &format!("--who={WHO}"))
}

/// Stay awake as it is now.
pub fn awake(paths: &Paths) -> Awake {
    let rec: Option<AwakeRecord> = fs::read_to_string(awake_file(paths))
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok());
    let Some(r) = rec else {
        return Awake::off();
    };
    if !is_ours(r.pid) || r.until.is_some_and(|u| u <= now()) {
        let _ = fs::remove_file(awake_file(paths));
        return Awake::off();
    }
    Awake {
        on: true,
        pid: Some(r.pid),
        started: Some(r.started),
        until: r.until,
        until_local: r.until.and_then(local).map(|d| d.to_rfc3339()),
        remaining_s: r.until.map(|u| (u - now()).max(0)),
    }
}

/// Ends stay awake (its process group: systemd-inhibit and the sleep under it).
pub fn awake_off(paths: &Paths) -> Awake {
    if let Some(pid) = awake(paths).pid
        && let Some(p) = rustix::process::Pid::from_raw(pid)
    {
        let _ = rustix::process::kill_process_group(p, rustix::process::Signal::TERM);
    }
    let _ = fs::remove_file(awake_file(paths));
    refresh_bar();
    Awake::off()
}

/// Stays awake for `secs` (None: until turned off), replacing any earlier one.
pub fn awake_on(paths: &Paths, secs: Option<u64>) -> Result<Awake, String> {
    awake_off(paths);
    let started = now();
    let until = secs.map(|s| started + s as i64);
    let why = match until.and_then(local) {
        Some(t) => format!(
            "Stay awake until {} (bromigos idle stay-awake)",
            t.format("%H:%M")
        ),
        None => "Stay awake until turned off (bromigos idle stay-awake off)".to_owned(),
    };
    let sleep = secs
        .map(|s| s.to_string())
        .unwrap_or_else(|| "infinity".into());
    let child = Command::new("systemd-inhibit")
        .args([
            "--what=idle",
            &format!("--who={WHO}"),
            &format!("--why={why}"),
            "--mode=block",
            "sleep",
            &sleep,
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .process_group(0)
        .spawn()
        .map_err(|e| format!("systemd-inhibit: {e}"))?;
    let pid = child.id() as i32;
    // it must hold the inhibitor, not fail at once (no logind, refused)
    std::thread::sleep(std::time::Duration::from_millis(300));
    let mut child = child;
    if let Ok(Some(st)) = child.try_wait() {
        return Err(format!("systemd-inhibit exited at once ({st}): no logind?"));
    }
    std::mem::forget(child);
    let rec = AwakeRecord {
        pid,
        started,
        until,
    };
    write_atomic(
        &awake_file(paths),
        &serde_json::to_string(&rec).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())?;
    refresh_bar();
    Ok(awake(paths))
}

/// `1h`, `2h`, `30m`, `90` (minutes), `until-off`/`on`: seconds, or None for until off.
pub fn parse_awake(s: &str) -> Result<Option<u64>, String> {
    match s.trim().to_ascii_lowercase().as_str() {
        "on" | "until-off" | "until_off" | "untiloff" | "forever" | "always" => Ok(None),
        v => {
            let secs = parse_duration(v, 60)
                .ok_or_else(|| format!("{s:?}: a time (1h, 2h, 30m, 90) or until-off"))?;
            if !(60..=7 * 24 * 3600).contains(&secs) {
                return Err(format!("{s:?}: from 1 minute to 7 days"));
            }
            Ok(Some(secs))
        }
    }
}

/// Someone else keeping the machine awake (a logind idle inhibitor: a video player, a
/// download), as `systemd-inhibit --list` shows it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Inhibitor {
    pub who: String,
    pub why: String,
    pub mode: String,
    pub pid: u32,
}

/// The idle inhibitors from `busctl --json=short call … ListInhibitors`' output, but ours.
pub fn parse_inhibitors(json: &str, ours: Option<i32>) -> Vec<Inhibitor> {
    let Ok(v) = serde_json::from_str::<serde_json::Value>(json) else {
        return vec![];
    };
    v["data"][0]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|row| {
            let r = row.as_array()?;
            let what = r.first()?.as_str()?;
            if !what.split(':').any(|w| w == "idle") {
                return None;
            }
            let pid = r.get(5)?.as_u64()? as u32;
            if ours.is_some_and(|o| o as u32 == pid) {
                return None;
            }
            Some(Inhibitor {
                who: r.get(1)?.as_str()?.to_owned(),
                why: r.get(2)?.as_str()?.to_owned(),
                mode: r.get(3)?.as_str()?.to_owned(),
                pid,
            })
        })
        .collect()
}

/// The other idle inhibitors logind holds now (empty when it can't be asked).
pub fn inhibitors(ours: Option<i32>) -> Vec<Inhibitor> {
    let out = Command::new("busctl")
        .args([
            "--system",
            "--json=short",
            "call",
            "org.freedesktop.login1",
            "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager",
            "ListInhibitors",
        ])
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output();
    match out {
        Ok(o) if o.status.success() => parse_inhibitors(&String::from_utf8_lossy(&o.stdout), ours),
        _ => vec![],
    }
}

// ------------------------------------------------------------------ status

/// hypridle as it runs.
#[derive(Debug, Clone, Serialize)]
pub struct Daemon {
    pub running: bool,
    pub pids: Vec<i32>,
}

/// `bromigos idle status --json` (schema in core/README.md).
#[derive(Debug, Clone, Serialize)]
pub struct Status {
    pub file: PathBuf,
    pub exists: bool,
    pub policy: Policy,
    pub defaults: Policy,
    /// The keys the user's file sets (the rest are the defaults).
    pub set: Vec<String>,
    pub preset: Option<&'static str>,
    pub screensaver_only: bool,
    pub summary: String,
    pub warnings: Vec<Warning>,
    pub stay_awake: Awake,
    pub inhibitors: Vec<Inhibitor>,
    pub rendered: PathBuf,
    /// The rendered file matches the policy now.
    pub rendered_current: bool,
    pub hook: Hook,
    pub hypridle: Daemon,
}

/// Whether the live layer's screensaver animation is on (`bromigos anim`): unknown counts as on.
fn screensaver_anim_on(paths: &Paths) -> bool {
    crate::config::load_merged(paths)
        .ok()
        .and_then(|(t, _)| {
            crate::config::lookup(&t, "screensaver", "enabled").map(crate::config::truthy)
        })
        .unwrap_or(true)
}

pub fn status(paths: &Paths) -> Status {
    let l = load(paths);
    let p = l.policy;
    let mut warnings = l.problems.clone();
    warnings.extend(check(&p));
    if p.screensaver.enabled && !screensaver_anim_on(paths) {
        warnings.push(warn(
            "screensaver.enabled",
            "The screensaver animation is switched off (bromigos anim on screensaver), so nothing shows at its time.",
        ));
    }
    let hook = hooked(paths);
    match hook {
        Hook::Packaged => warnings.push(warn(
            "",
            format!(
                "{} still sources the packaged policy, so these settings don't reach hypridle: `bromigos idle hook` (or `bromigos update`) moves it.",
                hypr_file(paths).display()
            ),
        )),
        Hook::Other => warnings.push(warn(
            "",
            format!(
                "{} doesn't source bromigOS's policy, so these settings don't reach hypridle. Add: {}",
                hypr_file(paths).display(),
                source_line(paths)
            ),
        )),
        Hook::Missing => warnings.push(warn(
            "",
            format!("There's no {}: `bromigos idle hook` makes it.", hypr_file(paths).display()),
        )),
        Hook::Rendered => {}
    }
    let pids = hypridle_pids();
    if pids.is_empty() {
        warnings.push(warn(
            "",
            "hypridle isn't running, so nothing idles: it starts at login (`bromigos idle start --detach` starts it now).",
        ));
    }
    let stay = awake(paths);
    let rendered_current = render(paths, &p)
        .ok()
        .is_some_and(|t| fs::read_to_string(rendered_file(paths)).is_ok_and(|f| f == t));
    Status {
        file: user_file(paths),
        exists: l.exists,
        policy: p,
        defaults: l.defaults,
        set: l.set,
        preset: preset_of(&p, &l.defaults),
        screensaver_only: screensaver_only(&p),
        summary: summary(&p),
        warnings,
        inhibitors: inhibitors(stay.pid),
        stay_awake: stay,
        rendered: rendered_file(paths),
        rendered_current,
        hook,
        hypridle: Daemon {
            running: !pids.is_empty(),
            pids,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn defaults_() -> Policy {
        builtin_defaults()
    }

    fn paths(root: &Path) -> Paths {
        let r = root.to_path_buf();
        Paths::from_lookup(move |k| match k {
            "HOME" => Some(r.join("home")),
            "XDG_RUNTIME_DIR" => Some(r.join("run")),
            "BROMIGOS_SHARE_DIR" => Some(r.join("share")),
            "BROMIGOS_LIB_BIN" => Some(PathBuf::from("/usr/lib/bromigos/bin")),
            _ => None,
        })
    }

    #[test]
    fn the_built_in_defaults_are_the_old_policy() {
        let d = defaults_();
        assert_eq!(
            d.screensaver,
            Timer {
                enabled: true,
                minutes: 8
            }
        );
        assert_eq!(
            d.lock,
            Timer {
                enabled: true,
                minutes: 10
            }
        );
        assert_eq!(
            d.displays,
            Timer {
                enabled: true,
                minutes: 15
            }
        );
        assert_eq!(
            d.suspend,
            Timer {
                enabled: false,
                minutes: 60
            }
        );
        assert!(d.lock_before_sleep);
        assert_eq!(
            d.activity,
            Activity {
                enabled: true,
                seconds: 90
            }
        );
        // every key is in the file, so no default is a zero
        let doc: toml_edit::DocumentMut = DEFAULT_TOML.parse().unwrap();
        let (_, set, w) = overlay(d, &doc, "x");
        assert_eq!(set.len(), KEYS.len());
        assert!(w.is_empty());
        assert!(
            check(&d).is_empty(),
            "the defaults raise nothing: {:?}",
            check(&d)
        );
    }

    #[test]
    fn the_users_keys_win_and_bad_ones_fall_back() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        fs::create_dir_all(p.user_config_dir()).unwrap();
        fs::write(
            user_file(&p),
            "[lock]\nenabled = false\n[screensaver]\nminutes = \"ten\"\n[displays]\nminutes = 0\n",
        )
        .unwrap();
        let l = load(&p);
        assert!(!l.policy.lock.enabled);
        assert_eq!(l.policy.lock.minutes, 10);
        assert_eq!(
            l.policy.screensaver.minutes, 8,
            "a bad value keeps the default"
        );
        assert_eq!(
            l.policy.displays.minutes, 15,
            "out of range keeps the default"
        );
        assert_eq!(l.set, vec!["lock.enabled"]);
        assert_eq!(l.problems.len(), 2);
        assert!(l.problems[0].text.contains("whole number"));
        // a packaged defaults file wins over the built-in ones
        fs::create_dir_all(p.defaults_dir()).unwrap();
        fs::write(default_file(&p), "[screensaver]\nminutes = 5\n").unwrap();
        assert_eq!(load(&p).policy.screensaver.minutes, 5);
    }

    #[test]
    fn set_words() {
        assert_eq!(
            parse_set("lock", "off").unwrap(),
            vec![("lock.enabled".into(), Value::Bool(false))]
        );
        assert_eq!(
            parse_set("screensaver", "5").unwrap(),
            vec![
                ("screensaver.minutes".into(), Value::Int(5)),
                ("screensaver.enabled".into(), Value::Bool(true))
            ]
        );
        assert_eq!(
            parse_set("displays", "1h").unwrap()[0],
            ("displays.minutes".into(), Value::Int(60))
        );
        assert_eq!(
            parse_set("dpms", "1h30m").unwrap()[0],
            ("displays.minutes".into(), Value::Int(90))
        );
        assert_eq!(
            parse_set("activity", "2m").unwrap()[0],
            ("activity.seconds".into(), Value::Int(120))
        );
        assert_eq!(
            parse_set("activity", "off").unwrap()[0],
            ("activity.enabled".into(), Value::Bool(false))
        );
        assert_eq!(
            parse_set("lock-before-sleep", "off").unwrap(),
            vec![("sleep.lock_before".into(), Value::Bool(false))]
        );
        assert_eq!(
            parse_set("suspend.minutes", "45").unwrap(),
            vec![("suspend.minutes".into(), Value::Int(45))]
        );
        assert_eq!(
            parse_set("suspend.enabled", "yes").unwrap()[0].1,
            Value::Bool(true)
        );
        // refused: out of range, nonsense, unknown
        assert!(parse_set("lock", "0").unwrap_err().contains("out of range"));
        assert!(parse_set("lock", "2000").is_err());
        assert!(
            parse_set("lock", "90s")
                .unwrap_err()
                .contains("whole minutes")
        );
        assert!(parse_set("activity", "5").is_err());
        assert!(parse_set("lock", "soon").is_err());
        assert!(
            parse_set("brightness", "5")
                .unwrap_err()
                .contains("unknown key")
        );
        assert!(parse_set("lock-before-sleep", "5").is_err());
    }

    #[test]
    fn edits_keep_comments_and_drop_empty_tables() {
        let mine =
            "# mine\n[lock]\nenabled = true   # I like it locked\nminutes = 12\n\n[other]\nx = 1\n";
        let out = edit(mine, &[("lock.enabled".into(), Some(Value::Bool(false)))]).unwrap();
        assert!(
            out.contains("enabled = false   # I like it locked"),
            "{out}"
        );
        assert!(
            out.contains("[other]\nx = 1"),
            "keys it doesn't know are kept"
        );
        let out = edit(&out, &preset_changes("default").unwrap()).unwrap();
        assert!(!out.contains("[lock]"), "{out}");
        assert!(out.starts_with("# mine"));
        // a new file gets the header
        let out = edit("", &[("screensaver.minutes".into(), Some(Value::Int(4)))]).unwrap();
        assert!(out.starts_with(HEADER), "{out}");
        assert!(out.contains("[screensaver]\nminutes = 4"));
        // and the default preset leaves the header alone in an otherwise empty file
        let out = edit(&out, &preset_changes("default").unwrap()).unwrap();
        assert_eq!(out.trim(), HEADER);
    }

    fn rules(text: &str) -> Vec<String> {
        text.lines()
            .map(|l| l.split(" #").next().unwrap_or(l).trim().to_owned())
            .filter(|l| !l.is_empty() && !l.starts_with('#'))
            .collect()
    }

    #[test]
    fn renders_the_default_policy_as_shipped() {
        let d = defaults_();
        let out = render_with(TEMPLATE, &d, "/usr/lib/bromigos/bin/bromigos-dispatch").unwrap();
        // the packaged hypridle.conf (bromigos-desktop) is this policy, for files that still source it
        let shipped = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../../desktop/hypr/hypridle.conf"
        );
        if let Ok(s) = fs::read_to_string(shipped) {
            assert_eq!(
                rules(&s),
                rules(&out),
                "desktop/hypr/hypridle.conf drifted from the template's defaults"
            );
        }
        for t in [
            "timeout = 480",
            "timeout = 600",
            "timeout = 900",
            "timeout = 90",
        ] {
            assert!(out.contains(t), "{t} in {out}");
        }
        assert!(out.contains("lock_cmd = bromigos lock-run"));
        assert!(out.contains("before_sleep_cmd = loginctl lock-session"));
        assert!(!out.contains("systemctl suspend"));
        assert!(out.contains("# Screensaver at 8 min, then the lock at 10 min, then displays off at 15 min. Never suspends."));
    }

    #[test]
    fn renders_screensaver_only_and_presentation() {
        let mut p = defaults_();
        for (k, v) in preset_changes("screensaver-only").unwrap() {
            p.put(&k, &v.unwrap());
        }
        let out = render_with(TEMPLATE, &p, "D").unwrap();
        assert!(out.contains("on-timeout = bromigos-live ctl screensaver open"));
        assert!(out.contains("on-resume = bromigos-live screensaver-off"));
        assert!(
            !out.contains("on-timeout = loginctl lock-session"),
            "nothing locks on idle"
        );
        assert!(!out.contains("dpms off"));
        assert!(
            out.contains("lock_cmd = bromigos lock-run"),
            "SUPER+L still locks"
        );
        assert!(out.contains("before_sleep_cmd"), "sleep still locks first");
        assert_eq!(
            summary(&p),
            "Screensaver at 8 min, then nothing locks; the displays stay on; never suspends."
        );
        assert_eq!(preset_of(&p, &defaults_()), Some("screensaver-only"));
        assert!(screensaver_only(&p));

        let mut q = defaults_();
        for (k, v) in preset_changes("presentation").unwrap() {
            q.put(&k, &v.unwrap());
        }
        let out = render_with(TEMPLATE, &q, "D").unwrap();
        assert!(!out.contains("listener"), "{out}");
        assert!(out.contains("lock_cmd"));
        assert_eq!(preset_of(&q, &defaults_()), Some("presentation"));
        assert!(summary(&q).starts_with("Nothing idles"));

        let mut z = defaults_();
        z.suspend = Timer {
            enabled: true,
            minutes: 30,
        };
        z.lock_before_sleep = false;
        let out = render_with(TEMPLATE, &z, "D").unwrap();
        assert!(out.contains("timeout = 1800\n    on-timeout = systemctl suspend"));
        assert!(!out.contains("before_sleep_cmd"));
        assert_eq!(preset_of(&z, &defaults_()), None);
        assert!(
            summary(&z).ends_with("Sleep doesn't lock first."),
            "{}",
            summary(&z)
        );
        // an unknown name in a template is an error, not an empty string
        assert!(render_with("{{ nope }}", &z, "D").is_err());
    }

    #[test]
    fn odd_orders_are_warned_never_refused() {
        let level = |p: &Policy, key: &str| {
            check(p)
                .into_iter()
                .find(|w| w.key.as_deref() == Some(key))
                .map(|w| w.level)
        };
        let mut p = defaults_();
        p.screensaver.minutes = 12;
        assert_eq!(level(&p, "screensaver.minutes"), Some("warn"));
        let mut p = defaults_();
        p.displays.minutes = 5;
        assert_eq!(
            level(&p, "displays.minutes"),
            Some("warn"),
            "dark before the screensaver"
        );
        let mut p = defaults_();
        p.displays.minutes = 9;
        assert_eq!(
            level(&p, "displays.minutes"),
            Some("note"),
            "dark before the lock"
        );
        let mut p = defaults_();
        p.suspend = Timer {
            enabled: true,
            minutes: 5,
        };
        assert_eq!(level(&p, "suspend.minutes"), Some("warn"));
        p.lock_before_sleep = false;
        assert_eq!(level(&p, "suspend.enabled"), Some("warn"));
        assert_eq!(
            level(&p, "sleep.lock_before"),
            None,
            "said once, on the suspend"
        );
        let mut p = defaults_();
        p.lock_before_sleep = false;
        assert_eq!(level(&p, "sleep.lock_before"), Some("warn"));
        let mut p = defaults_();
        p.lock.enabled = false;
        assert_eq!(level(&p, "lock.enabled"), Some("note"));
        // a later suspend with the lock before it: fine
        let mut p = defaults_();
        p.suspend = Timer {
            enabled: true,
            minutes: 60,
        };
        assert!(check(&p).is_empty(), "{:?}", check(&p));
    }

    #[test]
    fn summaries() {
        let mut p = defaults_();
        assert_eq!(
            summary(&p),
            "Screensaver at 8 min, then the lock at 10 min, then displays off at 15 min. Never suspends."
        );
        p.suspend = Timer {
            enabled: true,
            minutes: 90,
        };
        assert_eq!(
            summary(&p),
            "Screensaver at 8 min, then the lock at 10 min, then displays off at 15 min, then suspend at 1 h 30 min."
        );
        p.screensaver.enabled = false;
        p.displays.enabled = false;
        p.suspend.minutes = 120;
        assert_eq!(
            summary(&p),
            "Lock at 10 min, then suspend at 2 h. The displays stay on."
        );
    }

    #[test]
    fn hook_moves_the_packaged_source_and_keeps_the_rest() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        let mine = format!(
            "{OLD_HOOK_COMMENT}\nsource = /usr/share/bromigos/default/hypr/hypridle.conf\n\nlistener {{\n    timeout = 30\n    on-timeout = notify-send hi\n}}\n"
        );
        assert_eq!(hook_of(&p, &mine), Hook::Packaged);
        let out = rehook(&p, &mine);
        assert!(out.starts_with(HOOK_COMMENT), "{out}");
        assert!(out.contains("source = ~/.local/state/bromigos/idle/hypridle.conf\n"));
        assert!(out.contains("on-timeout = notify-send hi"));
        assert_eq!(hook_of(&p, &out), Hook::Rendered);
        assert_eq!(rehook(&p, &out), out, "idempotent");
        // on disk, through a dotfiles symlink: the link stays, its target changes, a backup is kept
        let dot = t.path().join("dotfiles/hypridle.conf");
        fs::create_dir_all(dot.parent().unwrap()).unwrap();
        fs::write(&dot, &mine).unwrap();
        let f = hypr_file(&p);
        fs::create_dir_all(f.parent().unwrap()).unwrap();
        std::os::unix::fs::symlink(&dot, &f).unwrap();
        let h = hook(&p).unwrap();
        assert_eq!(h.outcome, "moved");
        assert!(fs::symlink_metadata(&f).unwrap().file_type().is_symlink());
        assert_eq!(
            hook_of(&p, &fs::read_to_string(&dot).unwrap()),
            Hook::Rendered
        );
        assert_eq!(fs::read_to_string(h.backup.unwrap()).unwrap(), mine);
        assert!(
            rendered_file(&p).is_file(),
            "the file it sources is rendered"
        );
        assert_eq!(hook(&p).unwrap().outcome, "kept");
        // the user's own setup is reported, not changed
        fs::write(&dot, "listener {\n timeout = 5\n on-timeout = x\n}\n").unwrap();
        assert_eq!(hook(&p).unwrap().outcome, "yours");
        // none: made
        fs::remove_file(&f).unwrap();
        assert_eq!(hook(&p).unwrap().outcome, "made");
        assert_eq!(fs::read_to_string(&f).unwrap(), thin_file(&p));
        assert_eq!(hooked(&p), Hook::Rendered);
        // the seeded thin file (desktop/user/hypr/hypridle.conf) is this one
        let seed = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../../desktop/user/hypr/hypridle.conf"
        );
        if let Ok(s) = fs::read_to_string(seed) {
            assert_eq!(
                hook_of(&p, &s),
                Hook::Rendered,
                "the seed sources the rendered policy"
            );
        }
    }

    #[test]
    fn source_paths_expand() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        let abs = format!("source = {}", rendered_file(&p).display());
        assert_eq!(hook_of(&p, &abs), Hook::Rendered);
        assert_eq!(
            hook_of(
                &p,
                "source = $HOME/.local/state/bromigos/idle/hypridle.conf"
            ),
            Hook::Rendered
        );
        assert_eq!(
            hook_of(&p, "# source = ~/.local/state/bromigos/idle/hypridle.conf"),
            Hook::Other
        );
        assert_eq!(
            hook_of(
                &p,
                "source=~/.local/state/bromigos/idle/hypridle.conf # mine"
            ),
            Hook::Rendered
        );
    }

    #[test]
    fn change_render_and_undo_round_trip() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        assert!(undo(&p).is_err(), "nothing to undo yet");
        change(&p, &[("lock.enabled".into(), Some(Value::Bool(false)))]).unwrap();
        assert!(!load(&p).policy.lock.enabled);
        assert!(render_file(&p).unwrap());
        assert!(!render_file(&p).unwrap(), "unchanged: not written again");
        let r = fs::read_to_string(rendered_file(&p)).unwrap();
        assert!(!r.contains("on-timeout = loginctl lock-session"));
        change(&p, &[("screensaver.minutes".into(), Some(Value::Int(3)))]).unwrap();
        undo(&p).unwrap();
        let l = load(&p);
        assert_eq!(l.policy.screensaver.minutes, 8);
        assert!(!l.policy.lock.enabled, "one step back");
        undo(&p).unwrap();
        assert_eq!(load(&p).policy.screensaver.minutes, 3, "undo twice redoes");
        // back to no file at all
        let t2 = tempfile::tempdir().unwrap();
        let p2 = paths(t2.path());
        change(&p2, &[("lock.minutes".into(), Some(Value::Int(20)))]).unwrap();
        undo(&p2).unwrap();
        assert!(!user_file(&p2).exists());
        assert_eq!(load(&p2).policy, defaults_());
    }

    #[test]
    fn durations() {
        assert_eq!(parse_awake("1h").unwrap(), Some(3600));
        assert_eq!(parse_awake("2h").unwrap(), Some(7200));
        assert_eq!(parse_awake("90").unwrap(), Some(5400));
        assert_eq!(parse_awake("1h30m").unwrap(), Some(5400));
        assert_eq!(parse_awake("until-off").unwrap(), None);
        assert_eq!(parse_awake("on").unwrap(), None);
        assert!(parse_awake("30s").is_err());
        assert!(parse_awake("later").is_err());
        assert_eq!(parse_duration("2m", 1), Some(120));
        assert_eq!(parse_duration("m", 1), None);
        assert_eq!(parse_duration("5x", 1), None);
    }

    #[test]
    fn inhibitors_from_logind() {
        let j = r#"{"type":"a(ssssuu)","data":[[["sleep","NetworkManager","NetworkManager needs to turn off networks","delay",0,889],["idle:sleep","firefox","Playing video","block",1000,4242],["idle","bromigOS","Stay awake","block",1000,77]]]}"#;
        let i = parse_inhibitors(j, Some(77));
        assert_eq!(
            i,
            vec![Inhibitor {
                who: "firefox".into(),
                why: "Playing video".into(),
                mode: "block".into(),
                pid: 4242
            }]
        );
        assert!(parse_inhibitors("nope", None).is_empty());
    }

    #[test]
    fn stay_awake_is_off_without_a_live_inhibitor() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        assert!(!awake(&p).on);
        fs::create_dir_all(&p.runtime_dir).unwrap();
        // a record whose PID isn't ours (this test process) reads as off, and is removed
        let rec = AwakeRecord {
            pid: std::process::id() as i32,
            started: 1,
            until: None,
        };
        fs::write(awake_file(&p), serde_json::to_string(&rec).unwrap()).unwrap();
        assert!(!awake(&p).on);
        assert!(!awake_file(&p).exists());
    }
}
