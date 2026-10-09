//! What's produced, what's stale, and what a run would do.

use serde::Serialize;

use crate::Error;
use crate::log::Record;
use crate::spec::{World, file_sha256};

/// Where an asset stands.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum State {
    /// Produced with this spec, and every output is here.
    Done,
    /// Produced with this spec, but an output isn't on this machine.
    Missing,
    /// Produced, but the spec, a file input or an input asset changed since.
    Stale,
    /// Submitted with this spec and not finished: a run waits for that job
    /// instead of paying again.
    Pending,
    /// Never produced.
    New,
}

impl State {
    pub fn as_str(self) -> &'static str {
        match self {
            State::Done => "done",
            State::Missing => "missing",
            State::Stale => "stale",
            State::Pending => "pending",
            State::New => "new",
        }
    }
}

/// One asset's state, with the record that produced it.
#[derive(Debug, Clone, Serialize)]
pub struct Status {
    pub id: String,
    pub state: State,
    /// Why it is stale or missing, or which job it waits for.
    pub reason: Option<String>,
    /// The latest record that produced it (any spec).
    pub produced: Option<Record>,
    /// The job a pending asset waits for.
    pub pending_job: Option<String>,
    /// Its index in the log, to tell which of two assets was produced later.
    #[serde(skip)]
    produced_at: Option<usize>,
}

/// The state of every asset, in the world's order.
pub fn status(world: &World, records: &[Record]) -> Vec<Status> {
    let mut out: Vec<Status> = Vec::new();
    for a in &world.assets {
        let mine: Vec<(usize, &Record)> = records
            .iter()
            .enumerate()
            .filter(|(_, r)| r.asset == a.id)
            .collect();
        let produced = mine.iter().rev().find(|(_, r)| r.produced()).copied();
        let last = mine.last().map(|(_, r)| *r);
        let pending = last.filter(|r| {
            (r.status == "submitted" || r.status == "timeout")
                && r.spec == a.spec
                && r.job.is_some()
        });
        let (state, reason) = if let Some(p) = pending {
            (
                State::Pending,
                Some(format!(
                    "job {} not finished",
                    p.job.as_deref().unwrap_or("")
                )),
            )
        } else {
            match produced {
                None => (State::New, None),
                Some((_, r)) if r.spec != a.spec => (State::Stale, Some("the spec changed".into())),
                Some((i, r)) => {
                    let changed_file = r.inputs.iter().find(|(path, sha)| {
                        let p = world.dir.join(path);
                        p.exists() && file_sha256(&p).is_ok_and(|now| &now != *sha)
                    });
                    let newer_input = a.needs().into_iter().find(|n| {
                        out.iter()
                            .find(|s| s.id == *n)
                            .and_then(|s| s.produced_at)
                            .is_some_and(|j| j > i)
                    });
                    let absent: Vec<&String> = a
                        .outs
                        .iter()
                        .filter(|o| !world.dir.join(o).exists())
                        .collect();
                    if let Some((path, _)) = changed_file {
                        (State::Stale, Some(format!("{path} changed")))
                    } else if let Some(n) = newer_input {
                        (State::Stale, Some(format!("@{n} was made again since")))
                    } else if !absent.is_empty() {
                        let names: Vec<&str> = absent.iter().map(|s| s.as_str()).collect();
                        (
                            State::Missing,
                            Some(format!("not here: {}", names.join(", "))),
                        )
                    } else {
                        (State::Done, None)
                    }
                }
            }
        };
        out.push(Status {
            id: a.id.clone(),
            state,
            reason,
            produced: produced.map(|(_, r)| r.clone()),
            pending_job: pending.and_then(|r| r.job.clone()),
            produced_at: produced.map(|(i, _)| i),
        });
    }
    out
}

/// What a run does: the assets to make, in order, and those left alone.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Selection {
    pub run: Vec<String>,
    pub skipped: Vec<String>,
}

/// Picks what to run. With no `targets`: every new, stale or pending asset.
/// With targets: those (a done one only with `force`). Either way, an input
/// asset that isn't done (missing here, stale, new) is made first.
pub fn select(
    world: &World,
    statuses: &[Status],
    targets: &[String],
    force: bool,
) -> Result<Selection, Error> {
    for t in targets {
        if world.get(t).is_none() {
            let ids: Vec<&str> = world.assets.iter().map(|a| a.id.as_str()).collect();
            return Err(Error::Spec(format!(
                "{}: no asset {t:?} (has {})",
                world.name,
                ids.join(", ")
            )));
        }
    }
    let state = |id: &str| {
        statuses
            .iter()
            .find(|s| s.id == id)
            .map_or(State::New, |s| s.state)
    };
    let mut chosen: Vec<String> = if targets.is_empty() {
        statuses
            .iter()
            .filter(|s| matches!(s.state, State::New | State::Stale | State::Pending))
            .map(|s| s.id.clone())
            .collect()
    } else {
        targets
            .iter()
            .filter(|t| force || state(t) != State::Done)
            .cloned()
            .collect()
    };
    let mut i = 0;
    while i < chosen.len() {
        let needs: Vec<String> = world
            .get(&chosen[i])
            .map(|a| a.needs().into_iter().map(String::from).collect())
            .unwrap_or_default();
        for n in needs {
            if state(&n) != State::Done && !chosen.contains(&n) {
                chosen.push(n);
            }
        }
        i += 1;
    }
    let run: Vec<String> = world
        .assets
        .iter()
        .filter(|a| chosen.contains(&a.id))
        .map(|a| a.id.clone())
        .collect();
    let skipped = world
        .assets
        .iter()
        .filter(|a| !chosen.contains(&a.id) && (targets.is_empty() || targets.contains(&a.id)))
        .map(|a| a.id.clone())
        .collect();
    Ok(Selection { run, skipped })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::log::LOG_SCHEMA;
    use std::collections::BTreeMap;

    const TOML: &str = r#"
format = 1
[[assets]]
id = "comp"
kind = "image"
model = "m"
prompt = "p"
inputs = ["refs/den.jpg"]
out = "art/comp.png"
[[assets]]
id = "fix"
kind = "edit"
model = "m"
prompt = "q"
input = "@comp"
out = "art/fix.png"
[[assets]]
id = "split"
kind = "command"
run = ["true"]
inputs = ["@fix"]
outs = ["backgrounds/layers/00-sky.webp"]
"#;

    fn setup() -> (tempfile::TempDir, World) {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("art.toml"), TOML).unwrap();
        for f in [
            "refs/den.jpg",
            "art/comp.png",
            "art/fix.png",
            "backgrounds/layers/00-sky.webp",
        ] {
            let p = dir.path().join(f);
            std::fs::create_dir_all(p.parent().unwrap()).unwrap();
            std::fs::write(p, f).unwrap();
        }
        let w = World::load("w", dir.path()).unwrap();
        (dir, w)
    }

    fn rec(w: &World, id: &str, status: &str) -> Record {
        let a = w.get(id).unwrap();
        let mut inputs = BTreeMap::new();
        for f in a.files() {
            inputs.insert(f.to_owned(), file_sha256(&w.dir.join(f)).unwrap());
        }
        Record {
            schema: LOG_SCHEMA,
            t: "t".into(),
            world: "w".into(),
            asset: id.into(),
            version: a.version,
            kind: a.kind.to_string(),
            spec: a.spec.clone(),
            status: status.into(),
            model: a.model.clone(),
            prompt_sha256: None,
            credits: Some(8),
            planned: Some(8),
            job: Some(format!("job-{id}")),
            outputs: a.outs.clone(),
            inputs,
            seconds: None,
            error: None,
            by: "test".into(),
            backend: None,
            license: None,
        }
    }

    fn states(w: &World, rs: &[Record]) -> Vec<(String, State)> {
        status(w, rs).into_iter().map(|s| (s.id, s.state)).collect()
    }

    fn ids(v: &[&str]) -> Vec<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn unchanged_produced_assets_are_skipped() {
        let (_d, w) = setup();
        let rs: Vec<Record> = ["comp", "fix", "split"]
            .iter()
            .map(|i| rec(&w, i, "succeeded"))
            .collect();
        assert!(states(&w, &rs).iter().all(|(_, s)| *s == State::Done));
        let sel = select(&w, &status(&w, &rs), &[], false).unwrap();
        assert!(sel.run.is_empty());
        assert_eq!(sel.skipped, ids(&["comp", "fix", "split"]));
        // Named but done: skipped unless forced.
        let st = status(&w, &rs);
        assert!(
            select(&w, &st, &ids(&["fix"]), false)
                .unwrap()
                .run
                .is_empty()
        );
        assert_eq!(
            select(&w, &st, &ids(&["fix"]), true).unwrap().run,
            ids(&["fix"])
        );
    }

    #[test]
    fn a_new_world_runs_everything_in_order() {
        let (_d, w) = setup();
        let sel = select(&w, &status(&w, &[]), &[], false).unwrap();
        assert_eq!(sel.run, ids(&["comp", "fix", "split"]));
        // Asking for the last one brings what it reads.
        let sel = select(&w, &status(&w, &[]), &ids(&["split"]), false).unwrap();
        assert_eq!(sel.run, ids(&["comp", "fix", "split"]));
    }

    #[test]
    fn a_changed_spec_makes_it_and_what_reads_it_stale() {
        let (d, w) = setup();
        let rs: Vec<Record> = ["comp", "fix", "split"]
            .iter()
            .map(|i| rec(&w, i, "succeeded"))
            .collect();
        std::fs::write(
            d.path().join("art.toml"),
            TOML.replace("prompt = \"p\"", "prompt = \"p2\""),
        )
        .unwrap();
        let w2 = World::load("w", d.path()).unwrap();
        let st = states(&w2, &rs);
        assert_eq!(
            st,
            vec![
                ("comp".into(), State::Stale),
                ("fix".into(), State::Stale),
                ("split".into(), State::Stale)
            ]
        );
    }

    #[test]
    fn a_changed_file_input_makes_it_stale() {
        let (d, w) = setup();
        let rs: Vec<Record> = ["comp", "fix", "split"]
            .iter()
            .map(|i| rec(&w, i, "succeeded"))
            .collect();
        std::fs::write(d.path().join("refs/den.jpg"), "repainted").unwrap();
        let s = status(&w, &rs);
        assert_eq!(s[0].state, State::Stale);
        assert_eq!(s[0].reason.as_deref(), Some("refs/den.jpg changed"));
    }

    #[test]
    fn an_input_made_again_makes_its_readers_stale() {
        let (_d, w) = setup();
        let mut rs: Vec<Record> = ["comp", "fix", "split"]
            .iter()
            .map(|i| rec(&w, i, "succeeded"))
            .collect();
        rs.push(rec(&w, "comp", "succeeded")); // forced re-run
        let st = states(&w, &rs);
        assert_eq!(st[0].1, State::Done);
        assert_eq!(st[1].1, State::Stale);
        assert_eq!(st[2].1, State::Done); // fix itself wasn't made again yet
    }

    #[test]
    fn missing_outputs_are_only_made_when_something_needs_them() {
        let (d, w) = setup();
        let rs: Vec<Record> = ["comp", "fix", "split"]
            .iter()
            .map(|i| rec(&w, i, "succeeded"))
            .collect();
        std::fs::remove_file(d.path().join("art/comp.png")).unwrap();
        let st = status(&w, &rs);
        assert_eq!(st[0].state, State::Missing);
        assert!(select(&w, &st, &[], false).unwrap().run.is_empty());
        assert_eq!(
            select(&w, &st, &ids(&["fix"]), true).unwrap().run,
            ids(&["comp", "fix"])
        );
    }

    #[test]
    fn a_submitted_job_is_waited_for_not_paid_again() {
        let (_d, w) = setup();
        let rs = vec![rec(&w, "comp", "submitted")];
        let st = status(&w, &rs);
        assert_eq!(st[0].state, State::Pending);
        assert_eq!(st[0].pending_job.as_deref(), Some("job-comp"));
        let mut done = rs.clone();
        done.push(rec(&w, "comp", "succeeded"));
        assert_eq!(status(&w, &done)[0].state, State::Done);
    }

    #[test]
    fn unknown_targets_are_refused() {
        let (_d, w) = setup();
        let err = select(&w, &status(&w, &[]), &ids(&["nope"]), false).unwrap_err();
        assert!(err.to_string().contains("no asset \"nope\""));
    }
}
