//! Migrations: scripts that bring an existing install forward on update (as Omarchy's).
//!
//! Each is `/usr/share/bromigos/migrations/<id>.sh`, where the id is a timestamp and a slug
//! (`20261008120000-desktop-user-configs`). `bromigos update` runs the pending ones once per
//! user, in id order, with bash, after the package upgrade. A done one is recorded as
//! `~/.local/state/bromigos/migrations/<id>` (holding when it finished); everything a
//! migration prints is appended to `~/.local/state/bromigos/migrations/log`.
//!
//! A migration is idempotent (it may run again after a failure) and exits:
//! - 0 when it's done (recorded; never runs again),
//! - 75 (`EX_TEMPFAIL`) when it can't apply yet, e.g. its package isn't installed: not
//!   recorded, so a later update runs it again,
//! - anything else when it failed: `bromigos update` stops there and reports it; the
//!   migrations after it don't run, and it isn't recorded.
//!
//! It gets `BROMIGOS_MIGRATION` (its id), `BROMIGOS_CHANNEL` (stable, rc, edge, dev or
//! unknown: a migration may act differently on a dev checkout), `BROMIGOS_SHARE_DIR`, and `HOME`,
//! `XDG_CONFIG_HOME`, `XDG_STATE_HOME` always set (the defaults filled in).

use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde::Serialize;

use crate::paths::Paths;

/// The exit code that means "not yet: run me on a later update".
pub const DEFERRED: i32 = 75;

/// One migration script.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Migration {
    pub id: String,
    pub path: PathBuf,
}

/// What running one did.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Outcome {
    Done,
    Deferred,
    Failed,
}

#[derive(Debug, Clone, Serialize)]
pub struct Ran {
    pub id: String,
    pub outcome: Outcome,
    /// The exit code (None: killed by a signal, or bash couldn't start).
    pub code: Option<i32>,
    /// Its last lines of output (all of it is in the log).
    pub tail: String,
}

/// An id is a 14-digit timestamp, a dash and a lowercase slug.
pub fn valid_id(id: &str) -> bool {
    let (ts, slug) = match id.split_once('-') {
        Some(p) => p,
        None => return false,
    };
    ts.len() == 14
        && ts.bytes().all(|b| b.is_ascii_digit())
        && !slug.is_empty()
        && slug
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

/// Every migration shipped, in id order (files that aren't `<valid id>.sh` are ignored).
pub fn all(paths: &Paths) -> Vec<Migration> {
    let mut out: Vec<Migration> = fs::read_dir(paths.migrations_dir())
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let path = e.path();
            let id = path.file_name()?.to_str()?.strip_suffix(".sh")?.to_owned();
            (valid_id(&id) && path.is_file()).then_some(Migration { id, path })
        })
        .collect();
    out.sort_by(|a, b| a.id.cmp(&b.id));
    out
}

pub fn is_done(paths: &Paths, id: &str) -> bool {
    paths.migrations_state_dir().join(id).is_file()
}

/// The ones not done yet, in order.
pub fn pending(paths: &Paths) -> Vec<Migration> {
    all(paths)
        .into_iter()
        .filter(|m| !is_done(paths, &m.id))
        .collect()
}

fn now() -> String {
    chrono::Local::now()
        .format("%Y-%m-%dT%H:%M:%S%:z")
        .to_string()
}

/// Runs one migration and records it when it's done. `env` is added to its environment
/// (the live session's, so a migration can reach Hyprland or the bar).
pub fn run(paths: &Paths, m: &Migration, env: &[(String, String)]) -> Ran {
    let state = paths.migrations_state_dir();
    let _ = fs::create_dir_all(&state);
    let out = Command::new("bash")
        .arg(&m.path)
        .envs(env.iter().map(|(k, v)| (k.as_str(), v.as_str())))
        .env("BROMIGOS_MIGRATION", &m.id)
        .env(
            "BROMIGOS_CHANNEL",
            crate::channel::current(paths)
                .channel
                .map_or("unknown".to_owned(), |c| c.to_string()),
        )
        .env("BROMIGOS_SHARE_DIR", &paths.share_dir)
        .env("HOME", &paths.home)
        .env("XDG_CONFIG_HOME", &paths.config_home)
        .env("XDG_STATE_HOME", &paths.state_home)
        .stdin(Stdio::null())
        .output();
    let (code, text) = match out {
        Ok(o) => {
            let mut t = String::from_utf8_lossy(&o.stdout).into_owned();
            t.push_str(&String::from_utf8_lossy(&o.stderr));
            (o.status.code(), t)
        }
        Err(e) => (None, format!("bash: {e}\n")),
    };
    let outcome = match code {
        Some(0) => Outcome::Done,
        Some(DEFERRED) => Outcome::Deferred,
        _ => Outcome::Failed,
    };
    let when = now();
    if let Ok(mut log) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(state.join("log"))
    {
        let _ = writeln!(
            log,
            "== {} {} {:?} (exit {})\n{}",
            m.id,
            when,
            outcome,
            code.map_or("signal".to_owned(), |c| c.to_string()),
            text.trim_end()
        );
    }
    if outcome == Outcome::Done {
        let _ = fs::write(state.join(&m.id), format!("{when}\n"));
    }
    let lines: Vec<&str> = text.trim_end().lines().collect();
    let tail = lines[lines.len().saturating_sub(8)..].join("\n");
    Ran {
        id: m.id.clone(),
        outcome,
        code,
        tail,
    }
}

/// Runs every pending migration in order and stops at the first failure.
/// Returns what ran and whether all of it succeeded (deferred ones count as success).
pub fn run_pending(paths: &Paths, env: &[(String, String)]) -> (Vec<Ran>, bool) {
    let mut ran = Vec::new();
    for m in pending(paths) {
        let r = run(paths, &m, env);
        let failed = r.outcome == Outcome::Failed;
        ran.push(r);
        if failed {
            return (ran, false);
        }
    }
    (ran, true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::path::Path;

    fn paths(root: &Path) -> Paths {
        let m: HashMap<&str, PathBuf> = HashMap::from([
            ("HOME", root.join("home")),
            ("XDG_RUNTIME_DIR", root.join("run")),
            ("BROMIGOS_SHARE_DIR", root.join("share")),
        ]);
        Paths::from_lookup(|k| m.get(k).cloned())
    }

    fn script(p: &Paths, id: &str, body: &str) {
        fs::create_dir_all(p.migrations_dir()).unwrap();
        fs::write(p.migrations_dir().join(format!("{id}.sh")), body).unwrap();
    }

    #[test]
    fn ids() {
        assert!(valid_id("20261008120000-desktop-user-configs"));
        assert!(!valid_id("2026100812000-short"));
        assert!(!valid_id("20261008120000-"));
        assert!(!valid_id("20261008120000-Upper"));
        assert!(!valid_id("notes"));
    }

    #[test]
    fn order_record_defer_and_stop() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        script(
            &p,
            "20260101000002-second",
            "echo two; touch \"$HOME/two\"\n",
        );
        script(&p, "20260101000001-first", "echo one $BROMIGOS_MIGRATION\n");
        script(&p, "20260101000003-later", "echo not yet; exit 75\n");
        script(&p, "20260101000004-broken", "echo boom >&2; exit 3\n");
        script(&p, "20260101000005-after", "touch \"$HOME/after\"\n");
        fs::write(p.migrations_dir().join("README"), "not a migration").unwrap();
        fs::create_dir_all(&p.home).unwrap();

        let ids: Vec<_> = all(&p).into_iter().map(|m| m.id).collect();
        assert_eq!(ids.len(), 5);
        assert_eq!(ids[0], "20260101000001-first");

        let (ran, ok) = run_pending(&p, &[]);
        assert!(!ok);
        let got: Vec<_> = ran.iter().map(|r| (r.id.as_str(), r.outcome)).collect();
        assert_eq!(
            got,
            vec![
                ("20260101000001-first", Outcome::Done),
                ("20260101000002-second", Outcome::Done),
                ("20260101000003-later", Outcome::Deferred),
                ("20260101000004-broken", Outcome::Failed),
            ]
        );
        assert_eq!(ran[0].tail, "one 20260101000001-first");
        assert_eq!(ran[3].code, Some(3));
        assert!(ran[3].tail.contains("boom"));
        assert!(p.home.join("two").exists());
        assert!(
            !p.home.join("after").exists(),
            "nothing runs after a failure"
        );
        assert!(is_done(&p, "20260101000001-first"));
        assert!(
            !is_done(&p, "20260101000003-later"),
            "a deferred one isn't recorded"
        );
        assert!(!is_done(&p, "20260101000004-broken"));
        let log = fs::read_to_string(p.migrations_state_dir().join("log")).unwrap();
        assert!(log.contains("== 20260101000004-broken") && log.contains("boom"));

        // next update: the done ones are skipped, the deferred and failed ones run again
        let left: Vec<_> = pending(&p).into_iter().map(|m| m.id).collect();
        assert_eq!(
            left,
            vec![
                "20260101000003-later",
                "20260101000004-broken",
                "20260101000005-after"
            ]
        );
    }
}
