//! `bromigos art make <capability>`: one job through create.toml's providers,
//! outside any world (docs/art.md, "Creation providers"). VECTOR's hologram
//! builder and `gen3d.py` call it with `--json`.
//!
//! Each provider is tried in turn as a one-asset world in a scratch directory,
//! through the same plan and run as `bromigos art run` (the same checks, the same
//! credit accounting, the same log). A provider that isn't configured, can't
//! price the job, costs more than `--max-credits` or `[nolgia]
//! max_credits_per_job`, or (a ComfyUI) doesn't answer, hands over to the next.
//! A job that started and failed stops there: nothing falls through to a paid
//! provider after a job ran.

use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{Context, Result, bail};
use bromigos_art::create::{Candidate, Capability, Config, Provider};
use bromigos_art::{self as art, RunOptions, World, log};
use bromigos_core::paths::Paths;
use serde_json::{Value, json};
use toml::Table;

use crate::SCHEMA;

pub struct Request {
    pub capability: String,
    pub prompt: Option<String>,
    pub inputs: Vec<PathBuf>,
    pub mask: Option<PathBuf>,
    pub provider: Option<String>,
    pub model: Option<String>,
    pub aspect: Option<String>,
    pub duration: Option<u32>,
    /// A video's resolution tier.
    pub resolution: Option<String>,
    /// video.loop: the world loop's alpha (luma, stacked, mask), made by glow-loop.py.
    pub alpha: Option<String>,
    /// glow-loop.py's own arguments.
    pub post: Vec<String>,
    pub out: PathBuf,
    pub max_credits: Option<u64>,
    pub extra: Vec<String>,
}

fn runtime() -> Result<nolgia::tokio::runtime::Runtime> {
    Ok(nolgia::tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?)
}

/// The providers to try: `--provider` alone (with `--model`, or the
/// capability's models for that kind of provider, in preference order), else
/// create.toml's list.
fn candidates(cfg: &Config, cap: Capability, r: &Request) -> Result<Vec<Candidate>> {
    match (&r.provider, &r.model) {
        (None, Some(_)) => bail!("--model needs --provider (which provider runs it?)"),
        (Some(p), Some(m)) => Ok(vec![Candidate {
            provider: Provider::parse(p)?,
            model: m.clone(),
        }]),
        (Some(p), None) => {
            let provider = Provider::parse(p)?;
            // the first provider of that kind's models (create.toml may list several)
            let all: Vec<Candidate> = cfg
                .candidates(cap)?
                .into_iter()
                .chain(fallback_models(cfg, cap)?)
                .filter(|c| same_kind(&c.provider, &provider))
                .collect();
            let first = all.first().map(|c| c.provider.clone()).with_context(|| {
                format!("create.toml has no model for {cap} on {p}; pass --model")
            })?;
            let mut models: Vec<String> = Vec::new();
            for c in all.into_iter().filter(|c| c.provider == first) {
                if !models.contains(&c.model) {
                    models.push(c.model);
                }
            }
            Ok(models
                .into_iter()
                .map(|model| Candidate {
                    provider: provider.clone(),
                    model,
                })
                .collect())
        }
        (None, None) => Ok(cfg.candidates(cap)?),
    }
}

/// The capability's models for each kind of provider, whether or not that
/// provider is in its list (for `--provider` without `--model`).
fn fallback_models(cfg: &Config, cap: Capability) -> Result<Vec<Candidate>> {
    let mut v = Vec::new();
    for name in cfg
        .comfyui_names()
        .into_iter()
        .chain(["homelab".to_string()])
    {
        let probe = Config::from_toml(&format!(
            "[comfyui.{name}]\nendpoint = \"-\"\n[{cap}]\nproviders = [\"comfyui:{name}\", \"nolgia\"]\n"
        ))?;
        v.extend(probe.candidates(cap)?);
    }
    Ok(v)
}

fn same_kind(a: &Provider, b: &Provider) -> bool {
    matches!(
        (a, b),
        (Provider::Comfyui(_), Provider::Comfyui(_)) | (Provider::Nolgia, Provider::Nolgia)
    )
}

/// A one-asset world for `c`: the inputs copied in, `art.toml` written.
fn scratch(r: &Request, cap: Capability, c: &Candidate, ext: &str) -> Result<PathBuf> {
    let dir = std::env::temp_dir().join(format!(
        "bromigos-art-make-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    ));
    std::fs::create_dir_all(dir.join("in")).with_context(|| dir.display().to_string())?;
    let copy = |src: &Path, i: usize| -> Result<String> {
        let name = format!(
            "in/{i}-{}",
            src.file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_else(|| "input".into())
        );
        std::fs::copy(src, dir.join(&name)).with_context(|| src.display().to_string())?;
        Ok(name)
    };
    let mut ins = Vec::new();
    for (i, p) in r.inputs.iter().enumerate() {
        ins.push(copy(p, i)?);
    }
    let mask = r.mask.as_deref().map(|m| copy(m, 99)).transpose()?;
    let mut a = Table::new();
    a.insert("id".into(), "make".into());
    a.insert("kind".into(), cap.kind().as_str().into());
    a.insert("provider".into(), c.provider.id().into());
    a.insert("model".into(), c.model.clone().into());
    if let Some(p) = &r.prompt {
        a.insert("prompt".into(), p.clone().into());
    }
    match cap {
        Capability::ImageGenerate => {
            if !ins.is_empty() {
                a.insert("inputs".into(), ins.clone().into());
            }
        }
        Capability::ImageEdit
        | Capability::ImageCutout
        | Capability::Model3dGenerate
        | Capability::ImageUpscale
        | Capability::VideoUpscale => {
            let first = ins
                .first()
                .with_context(|| format!("{cap} needs --input"))?;
            if ins.len() > 1 {
                bail!("{cap} takes one --input");
            }
            a.insert("input".into(), first.clone().into());
        }
        Capability::VideoLoop => {
            let first = ins
                .first()
                .context("video.loop needs --input (the start frame)")?;
            a.insert("start".into(), first.clone().into());
            a.insert("loop".into(), true.into());
            a.insert("duration".into(), i64::from(r.duration.unwrap_or(5)).into());
            if let Some(res) = &r.resolution {
                a.insert("resolution".into(), res.clone().into());
            }
        }
    }
    if let Some(m) = mask {
        a.insert("mask".into(), m.into());
    }
    if let Some(asp) = &r.aspect {
        a.insert("aspect".into(), asp.clone().into());
    }
    if !r.extra.is_empty() {
        let mut ex = Table::new();
        for kv in &r.extra {
            let (k, v) = kv
                .split_once('=')
                .with_context(|| format!("--extra {kv:?}: expected KEY=VALUE"))?;
            let v: toml::Value = match serde_json::from_str::<Value>(v) {
                Ok(Value::Bool(b)) => b.into(),
                Ok(Value::Number(n)) if n.is_i64() => n.as_i64().unwrap_or(0).into(),
                Ok(Value::Number(n)) => n.as_f64().unwrap_or(0.0).into(),
                _ => v.to_string().into(),
            };
            ex.insert(k.to_string(), v);
        }
        a.insert("extra".into(), toml::Value::Table(ex));
    }
    a.insert("out".into(), format!("out.{ext}").into());
    let mut doc = Table::new();
    doc.insert("format".into(), 1.into());
    doc.insert(
        "assets".into(),
        toml::Value::Array(vec![toml::Value::Table(a)]),
    );
    std::fs::write(dir.join("art.toml"), toml::to_string(&doc)?)?;
    Ok(dir)
}

pub fn make(paths: &Paths, r: Request, as_json: bool) -> Result<i32> {
    let cap = Capability::parse(&r.capability).with_context(|| {
        format!(
            "{}: not a capability ({})",
            r.capability,
            Capability::ALL.map(|c| c.as_str()).join(", ")
        )
    })?;
    let ext = r
        .out
        .extension()
        .map(|e| e.to_string_lossy().to_ascii_lowercase())
        .with_context(|| format!("--out {}: needs an extension", r.out.display()))?;
    if r.alpha.is_some() && cap != Capability::VideoLoop {
        bail!("--alpha is for video.loop");
    }
    if let Some(a) = &r.alpha
        && !["luma", "stacked", "mask"].contains(&a.as_str())
    {
        bail!("--alpha {a}: luma, stacked or mask");
    }
    if r.alpha.is_some() && ext != "mp4" {
        bail!("--alpha writes an MP4: --out must end in .mp4");
    }
    let cfg = Config::load()?;
    let cands = candidates(&cfg, cap, &r)?;
    if cands.is_empty() {
        bail!("no provider for {cap}: create.toml lists none that is configured (docs/art.md)");
    }
    let rt = runtime()?;
    let say = |m: &str| {
        if !as_json {
            eprintln!("{m}");
        }
    };
    let mut skipped: Vec<Value> = Vec::new();
    let started = Instant::now();
    for c in &cands {
        let id = c.provider.id();
        // a ComfyUI that isn't configured or doesn't answer: the next provider
        if let Provider::Comfyui(name) = &c.provider {
            let up = cfg.comfyui_endpoint(name).and_then(|url| {
                let http = art::comfy::client()?;
                rt.block_on(art::comfy::probe(&http, &url))
                    .map(|_| (http, url))
            });
            let (http, url) = match up {
                Ok(x) => x,
                Err(e) => {
                    say(&format!("{id}: {e}; trying the next provider"));
                    skipped.push(json!({"provider": id, "why": e.to_string()}));
                    continue;
                }
            };
            // a workflow (of a preference list) the instance lacks files or nodes for, or
            // whose measured peak is more than its card has: the next one
            if let Ok(wf) = art::comfy::workflow(&c.model)
                && let Ok(m) = rt.block_on(art::comfy::missing(&http, &url, &wf))
                && (!m.ready() || !m.fits(&wf))
            {
                let why = m.describe(&wf);
                say(&format!("{id}: {why}; trying the next"));
                skipped.push(json!({"provider": id, "model": c.model, "why": why}));
                continue;
            }
        }
        let dir = scratch(&r, cap, c, &ext)?;
        let result = (|| -> Result<Option<Value>> {
            let w = World::load("make", &dir)?;
            let recs = log::read(&w.log_path())?;
            let st = art::status(&w, &recs);
            let (client, catalog) = if c.provider == Provider::Nolgia {
                let (cl, _) = art::auth::client()?;
                let cat = rt.block_on(art::run::catalog(&cl))?;
                (cl, cat)
            } else {
                (nolgia::Client::new("comfyui-only")?, Vec::new())
            };
            let plan = art::plan(&w, &st, &[], true, &catalog)?;
            if let Some(e) = plan.assets.iter().find_map(|a| a.error.clone()) {
                skipped.push(json!({"provider": id, "why": e}));
                return Ok(None);
            }
            let cap_credits = r.max_credits.or(if c.provider == Provider::Nolgia {
                cfg.nolgia_max_credits()
            } else {
                None
            });
            if let Some(max) = cap_credits
                && plan.credits > max
            {
                skipped.push(json!({"provider": id, "why": format!("{} credits is over the limit {max}", plan.credits)}));
                return Ok(None);
            }
            let opts = RunOptions {
                max_credits: cap_credits,
                spend_ledger: Some(paths.user_state_dir().join("nolgia-spend.jsonl")),
                ..Default::default()
            };
            let report = rt.block_on(art::run(&client, &w, &plan, &recs, &opts, &say))?;
            if !report.ok {
                let e = report
                    .ran
                    .iter()
                    .find_map(|x| x.error.clone())
                    .unwrap_or_else(|| "failed".into());
                bail!("{id}: {e}");
            }
            let made = dir.join(format!("out.{ext}"));
            if let Some(parent) = r.out.parent().filter(|p| !p.as_os_str().is_empty()) {
                std::fs::create_dir_all(parent)?;
            }
            match &r.alpha {
                Some(alpha) => post_loop(&made, &r.out, alpha, &r.post, &say)?,
                None => {
                    std::fs::copy(&made, &r.out).with_context(|| r.out.display().to_string())?;
                }
            }
            let rec = log::read(&w.log_path())?
                .into_iter()
                .rev()
                .find(|x| x.status == "succeeded");
            Ok(Some(json!({
                "capability": cap.as_str(),
                // where it ran: homelab, local or cloud (targets.toml; null: another named ComfyUI)
                "target": art::targets::Target::of_provider(&id).map(|t| t.as_str()),
                "provider": id,
                "model": c.model,
                "out": r.out,
                "credits": report.spent,
                "licence": rec.as_ref().and_then(|x| x.license.clone())
                    .unwrap_or_else(|| if c.provider == Provider::Nolgia { "nolgia (its terms)".into() } else { "unknown".into() }),
                "job": rec.as_ref().and_then(|x| x.job.clone()),
                "seconds": started.elapsed().as_secs(),
            })))
        })();
        let _ = std::fs::remove_dir_all(&dir);
        match result {
            Ok(Some(made)) => {
                let line = json!({"t": log::now(), "by": "bromigos art make", "skipped": skipped, "made": made});
                let logp = paths.user_state_dir().join("art/make.log.jsonl");
                if let Some(d) = logp.parent() {
                    let _ = std::fs::create_dir_all(d);
                }
                if let Err(e) = log::append_line(&logp, &line.to_string()) {
                    say(&format!("make log {}: {e}", logp.display()));
                }
                if as_json {
                    let mut doc = made.clone();
                    doc["schema"] = json!(SCHEMA);
                    doc["skipped"] = json!(skipped);
                    println!("{doc}");
                } else {
                    println!(
                        "{}: {} via {}{} ({}), {} credits, {} s -> {}",
                        cap,
                        c.model,
                        id,
                        made["target"]
                            .as_str()
                            .map(|t| format!(" [{t}]"))
                            .unwrap_or_default(),
                        made["licence"].as_str().unwrap_or(""),
                        made["credits"],
                        made["seconds"],
                        r.out.display()
                    );
                }
                return Ok(0);
            }
            Ok(None) => {
                say(&format!(
                    "{id}: {}; trying the next provider",
                    skipped
                        .last()
                        .map(|s| s["why"].to_string())
                        .unwrap_or_default()
                ));
                continue;
            }
            Err(e) => return Err(e),
        }
    }
    if as_json {
        println!(
            "{}",
            json!({"schema": SCHEMA, "ok": false, "capability": cap.as_str(), "skipped": skipped})
        );
    }
    bail!(
        "no provider could make {cap}: {}",
        skipped
            .iter()
            .map(|s| format!(
                "{} ({})",
                s["provider"].as_str().unwrap_or("?"),
                s["why"].as_str().unwrap_or("")
            ))
            .collect::<Vec<_>>()
            .join("; ")
    )
}

/// theme/tools/glow-loop.py: `$BROMIGOS_GLOW_LOOP`, the packaged copy, or a checkout's
/// (above this binary or the current directory).
fn glow_loop() -> Result<PathBuf> {
    if let Some(p) = std::env::var_os("BROMIGOS_GLOW_LOOP") {
        return Ok(PathBuf::from(p));
    }
    let share = std::env::var_os("BROMIGOS_SHARE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/usr/share/bromigos"))
        .join("tools/glow-loop.py");
    let rel = Path::new("theme/tools/glow-loop.py");
    let exe = std::env::current_exe().ok();
    let cwd = std::env::current_dir().ok();
    std::iter::once(share)
        .chain(
            exe.iter()
                .chain(cwd.iter())
                .flat_map(|d| d.ancestors().map(|a| a.join(rel)).collect::<Vec<_>>()),
        )
        .find(|p| p.is_file())
        .context("glow-loop.py isn't installed (bromigos-core) and no checkout is near; set BROMIGOS_GLOW_LOOP")
}

/// A world's loop from a raw clip, through glow-loop.py (docs/art.md): cropped to the
/// creature, cut at the wrap, matted for `alpha` (luma, stacked, or mask: a soft oval
/// OUT-mask.png beside it). The raw clip is kept beside it as OUT-raw.mp4.
fn post_loop(
    raw: &Path,
    out: &Path,
    alpha: &str,
    post: &[String],
    say: &dyn Fn(&str),
) -> Result<()> {
    let keep = out.with_file_name(format!(
        "{}-raw.mp4",
        out.file_stem()
            .map(|s| s.to_string_lossy())
            .unwrap_or_default()
    ));
    std::fs::copy(raw, &keep).with_context(|| keep.display().to_string())?;
    let tool = glow_loop()?;
    let mut argv: Vec<String> = vec![keep.display().to_string(), out.display().to_string()];
    let has = |flag: &str| {
        post.iter()
            .any(|a| a == flag || a.starts_with(&format!("{flag}=")))
    };
    match alpha {
        "stacked" if !has("--stacked") => {
            argv.extend(["--stacked", "0.03", "0.15"].map(String::from))
        }
        "mask" if !has("--mask") => argv.push("--mask".into()),
        _ => {}
    }
    argv.extend(post.iter().cloned());
    say(&format!("glow-loop.py {}", argv[2..].join(" ")));
    let st = std::process::Command::new("python3")
        .arg(&tool)
        .args(&argv)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .status()
        .with_context(|| format!("python3 {}", tool.display()))?;
    if !st.success() {
        bail!(
            "glow-loop.py failed ({st}); the raw clip is {}",
            keep.display()
        );
    }
    Ok(())
}
