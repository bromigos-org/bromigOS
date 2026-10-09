//! `themes/<world>/art.log.jsonl`: one JSON object per line, appended, one per
//! event of a job (submitted, then succeeded, failed or timeout) and one per
//! asset marked as produced by hand. It never holds a URL or a token: errors are
//! scrubbed of URLs before they are written, and the prompt is only its hash.

use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::Error;

/// The record format; bumped only on incompatible changes.
pub const LOG_SCHEMA: u32 = 1;

/// One line of the log.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Record {
    pub schema: u32,
    /// Local time with its offset, to the second.
    pub t: String,
    pub world: String,
    pub asset: String,
    pub version: u32,
    pub kind: String,
    /// The asset's spec when this happened (see `World::parse`).
    pub spec: String,
    /// `submitted`, `succeeded`, `failed`, `timeout` or `marked`.
    pub status: String,
    pub model: Option<String>,
    pub prompt_sha256: Option<String>,
    /// Credits charged for the job (the server's quote it was submitted with);
    /// 0 when a failed job was refunded, `null` when unknown.
    pub credits: Option<u64>,
    /// What `art plan` priced it at from the catalog.
    pub planned: Option<u64>,
    /// The nolgia job id.
    pub job: Option<String>,
    /// Output paths, relative to the theme directory.
    #[serde(default)]
    pub outputs: Vec<String>,
    /// The SHA-256 of each file input, by path.
    #[serde(default)]
    pub inputs: BTreeMap<String, String>,
    pub seconds: Option<u64>,
    pub error: Option<String>,
    /// What wrote it: `bromigos art run`, `bromigos art mark`, …
    pub by: String,
    /// Where it was made when not nolgia: `homelab-comfyui`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub backend: Option<String>,
    /// The licence of the weights that made it, when it is not nolgia's terms
    /// (the asset audit reads it).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub license: Option<String>,
}

impl Record {
    /// Whether this record says the asset was produced.
    pub fn produced(&self) -> bool {
        self.status == "succeeded" || self.status == "marked"
    }
}

/// Every record in the log (none when it doesn't exist). A line that doesn't
/// parse is an error naming the line: the log is append-only and machine-written.
pub fn read(path: &Path) -> Result<Vec<Record>, Error> {
    let text = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => return Err(Error::io(path, e)),
    };
    text.lines()
        .enumerate()
        .filter(|(_, l)| !l.trim().is_empty())
        .map(|(i, l)| {
            serde_json::from_str(l)
                .map_err(|e| Error::Spec(format!("{}:{}: {e}", path.display(), i + 1)))
        })
        .collect()
}

/// Appends one record as a line.
pub fn append(path: &Path, rec: &Record) -> Result<(), Error> {
    let line = serde_json::to_string(rec).map_err(|e| Error::Spec(e.to_string()))?;
    debug_assert!(!line.contains("://"), "a URL reached the art log");
    append_line(path, &line)
}

pub fn append_line(path: &Path, line: &str) -> Result<(), Error> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| Error::io(dir, e))?;
    }
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|e| Error::io(path, e))?;
    f.write_all(format!("{line}\n").as_bytes())
        .map_err(|e| Error::io(path, e))
}

/// Credits spent: each job counted once, at its latest record; marked assets
/// count what they were marked with.
pub fn spent(records: &[Record]) -> u64 {
    let mut by_job: BTreeMap<String, u64> = BTreeMap::new();
    let mut unjobbed = 0;
    for r in records {
        match &r.job {
            Some(j) => {
                by_job.insert(j.clone(), r.credits.unwrap_or(0));
            }
            None => unjobbed += r.credits.unwrap_or(0),
        }
    }
    by_job.values().sum::<u64>() + unjobbed
}

/// `s` with every URL replaced by `<url>`: signed URLs carry credentials in
/// their query string, and errors from HTTP clients quote them.
pub fn scrub(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(i) = ["http://", "https://"]
        .iter()
        .filter_map(|p| rest.find(p))
        .min()
    {
        out.push_str(&rest[..i]);
        out.push_str("<url>");
        let tail = &rest[i..];
        let end = tail
            .find(|c: char| c.is_whitespace() || matches!(c, ')' | '"' | '\'' | '>' | ']'))
            .unwrap_or(tail.len());
        rest = &tail[end..];
    }
    out.push_str(rest);
    out
}

/// Now, as the log writes it: `2026-10-08T02:19:52-07:00`.
pub fn now() -> String {
    chrono::Local::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, false)
}

#[cfg(test)]
mod tests {
    use super::*;

    pub fn record(asset: &str, status: &str, job: Option<&str>, credits: Option<u64>) -> Record {
        Record {
            schema: LOG_SCHEMA,
            t: "2026-10-08T02:19:52-07:00".into(),
            world: "mire".into(),
            asset: asset.into(),
            version: 1,
            kind: "image".into(),
            spec: "sha256:00".into(),
            status: status.into(),
            model: Some("gpt-image-2.5-flare".into()),
            prompt_sha256: Some("ab".into()),
            credits,
            planned: credits,
            job: job.map(Into::into),
            outputs: vec!["art/x.png".into()],
            inputs: BTreeMap::new(),
            seconds: Some(3),
            error: None,
            by: "test".into(),
            backend: None,
            license: None,
        }
    }

    #[test]
    fn records_round_trip_one_per_line() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("art.log.jsonl");
        assert!(read(&p).unwrap().is_empty());
        let a = record("comp", "submitted", Some("j1"), Some(8));
        let b = record("comp", "succeeded", Some("j1"), Some(8));
        append(&p, &a).unwrap();
        append(&p, &b).unwrap();
        let text = std::fs::read_to_string(&p).unwrap();
        assert_eq!(text.lines().count(), 2);
        let first: serde_json::Value = serde_json::from_str(text.lines().next().unwrap()).unwrap();
        // The documented fields, always present (null when absent).
        for k in [
            "schema",
            "t",
            "world",
            "asset",
            "version",
            "kind",
            "spec",
            "status",
            "model",
            "prompt_sha256",
            "credits",
            "planned",
            "job",
            "outputs",
            "inputs",
            "seconds",
            "error",
            "by",
        ] {
            assert!(first.get(k).is_some(), "missing {k}");
        }
        assert_eq!(read(&p).unwrap(), vec![a, b]);
    }

    #[test]
    fn spend_counts_each_job_once_at_its_latest_record() {
        let rs = vec![
            record("a", "submitted", Some("j1"), Some(8)),
            record("a", "succeeded", Some("j1"), Some(8)),
            record("b", "submitted", Some("j2"), Some(56)),
            record("b", "failed", Some("j2"), Some(0)), // refunded
            record("c", "marked", None, Some(3)),
        ];
        assert_eq!(spent(&rs), 8 + 3);
    }

    #[test]
    fn urls_are_scrubbed() {
        assert_eq!(
            scrub("error sending request for url (https://s.example/a.png?X-Sig=abc&t=1): reset"),
            "error sending request for url (<url>): reset"
        );
        assert_eq!(scrub("a http://x/y b https://z"), "a <url> b <url>");
        assert_eq!(scrub("no links"), "no links");
    }

    #[test]
    fn a_broken_line_is_named() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("l.jsonl");
        std::fs::write(&p, "{}\n").unwrap();
        assert!(read(&p).unwrap_err().to_string().contains(":1:"));
    }
}
