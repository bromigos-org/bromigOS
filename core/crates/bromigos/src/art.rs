//! `bromigos art plan|run|status|mark|make`: a world's art pipeline, and one-off
//! jobs through create.toml's providers (bromigos-art; docs/art.md).

use std::path::PathBuf;

use anyhow::{Context, Result};
use bromigos_art::{self as art, Error, RunOptions, State, World, log};
use bromigos_core::paths::Paths;
use bromigos_core::theme::Locations;
use clap::Subcommand;
use serde_json::{Value, json};

use crate::SCHEMA;

/// Exit status when `--max-credits` refuses a run.
const REFUSED: i32 = 3;

#[derive(clap::Args)]
pub struct ArtArgs {
    /// Print the JSON document (schema in core/README.md)
    #[arg(long, global = true)]
    json: bool,
    /// The world's theme directory (default: themes/WORLD/ in the checkout you're in,
    /// then ~/.config/bromigos/themes/WORLD/, then the system's)
    #[arg(long, global = true, value_name = "DIR")]
    dir: Option<PathBuf>,
    #[command(subcommand)]
    verb: ArtVerb,
}

#[derive(Subcommand)]
enum ArtVerb {
    /// What a run would make and the exact credits, from nolgia's live catalog
    Plan {
        world: String,
        /// Only these assets (and the inputs they need that aren't produced)
        assets: Vec<String>,
        /// Make the named assets again even if they're done
        #[arg(long)]
        force: bool,
    },
    /// Make what isn't produced (or ASSET…) through nolgia, and log each job
    Run {
        world: String,
        assets: Vec<String>,
        #[arg(long)]
        force: bool,
        /// Refuse to start when the plan costs more (exit 3), and stop before a job
        /// that would take the run past it. No cap by default.
        #[arg(long, value_name = "CREDITS")]
        max_credits: Option<u64>,
    },
    /// What's produced, missing, stale or new, and which backends answer (nolgia's
    /// credentials, the homelab ComfyUI)
    Status { world: String },
    /// Make one thing through create.toml's providers, outside any world (VECTOR's
    /// hologram builder and gen3d.py call this). CAPABILITY: image.generate,
    /// image.edit, image.cutout, image.upscale, video.loop, video.upscale,
    /// model3d.generate
    Make {
        capability: String,
        /// The prompt (image.generate, image.edit, video.loop; optional otherwise)
        #[arg(long)]
        prompt: Option<String>,
        /// An input image (the image to edit, cut out, upscale or model; the start frame;
        /// references for image.generate), or the clip to upscale; repeat for more
        #[arg(long = "input", value_name = "FILE")]
        inputs: Vec<PathBuf>,
        /// An edit's mask (transparent = may change)
        #[arg(long, value_name = "FILE")]
        mask: Option<PathBuf>,
        /// Use only this provider (comfyui:<name> or nolgia)
        #[arg(long, value_name = "ID")]
        provider: Option<String>,
        /// The workflow (ComfyUI) or model id (nolgia); needs --provider
        #[arg(long)]
        model: Option<String>,
        /// W:H for a new image or video
        #[arg(long)]
        aspect: Option<String>,
        /// A video's length in seconds (default 5)
        #[arg(long)]
        duration: Option<u32>,
        /// A video's resolution tier (nolgia's quality; a ComfyUI workflow's sizes, e.g.
        /// 720p or 480p)
        #[arg(long)]
        resolution: Option<String>,
        /// video.loop: make the world's loop from the raw clip with theme/tools/glow-loop.py
        /// (crop to the creature, cut at the wrap, matte): luma (glow on black, drawn
        /// additive), stacked (colour over its matte) or mask (also OUT-mask.png, a soft
        /// oval edge); the raw clip is kept as OUT-raw.mp4
        #[arg(long, value_name = "MODE")]
        alpha: Option<String>,
        /// An argument for glow-loop.py with --alpha (repeat), e.g. --post=--width=960
        #[arg(long = "post", value_name = "ARG", allow_hyphen_values = true)]
        post: Vec<String>,
        /// Where to write the result (.png, .mp4, .glb)
        #[arg(long, value_name = "FILE")]
        out: PathBuf,
        /// Skip a provider whose job would cost more
        #[arg(long, value_name = "CREDITS")]
        max_credits: Option<u64>,
        /// A provider option, KEY=VALUE (VALUE as JSON when it parses, else text),
        /// e.g. texture=true for a textured nolgia mesh, scale=2 for an upscale; repeat
        /// for more
        #[arg(long = "extra", value_name = "KEY=VALUE")]
        extra: Vec<String>,
    },
    /// Record an asset made outside `art run` as produced with its current recipe
    Mark {
        world: String,
        asset: String,
        /// The nolgia job that made it
        #[arg(long)]
        job: Option<String>,
        /// The credits it cost
        #[arg(long)]
        credits: Option<u64>,
        /// When it was made (RFC 3339; default now)
        #[arg(long)]
        at: Option<String>,
        #[arg(long)]
        seconds: Option<u64>,
        /// What made it
        #[arg(long, default_value = "bromigos art mark")]
        by: String,
    },
}

fn load(paths: &Paths, dir: Option<&PathBuf>, world: &str) -> Result<World> {
    let loc = Locations::new(paths);
    let cwd = std::env::current_dir().context("the current directory")?;
    let d = art::find_world(
        world,
        dir.map(|d| d.as_path()),
        &cwd,
        &loc.user_themes,
        &loc.system_themes,
    )?;
    Ok(World::load(world, &d)?)
}

fn runtime() -> Result<nolgia::tokio::runtime::Runtime> {
    Ok(nolgia::tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?)
}

pub fn art_cmd(paths: &Paths, a: ArtArgs) -> Result<i32> {
    match a.verb {
        ArtVerb::Status { world } => status(paths, a.dir.as_ref(), &world, a.json),
        ArtVerb::Plan {
            world,
            assets,
            force,
        } => plan_or_run(
            paths,
            a.dir.as_ref(),
            &world,
            &assets,
            force,
            None,
            false,
            a.json,
        ),
        ArtVerb::Run {
            world,
            assets,
            force,
            max_credits,
        } => plan_or_run(
            paths,
            a.dir.as_ref(),
            &world,
            &assets,
            force,
            max_credits,
            true,
            a.json,
        ),
        ArtVerb::Make {
            capability,
            prompt,
            inputs,
            mask,
            provider,
            model,
            aspect,
            duration,
            resolution,
            alpha,
            post,
            out,
            max_credits,
            extra,
        } => crate::art_make::make(
            paths,
            crate::art_make::Request {
                capability,
                prompt,
                inputs,
                mask,
                provider,
                model,
                aspect,
                duration,
                resolution,
                alpha,
                post,
                out,
                max_credits,
                extra,
            },
            a.json,
        ),
        ArtVerb::Mark {
            world,
            asset,
            job,
            credits,
            at,
            seconds,
            by,
        } => {
            let w = load(paths, a.dir.as_ref(), &world)?;
            let rec = art::mark(&w, &asset, job, credits, at, seconds, &by)?;
            if a.json {
                println!("{}", json!({"schema": SCHEMA, "record": rec}));
            } else {
                println!("{world}/{asset}: marked produced ({})", rec.spec);
            }
            Ok(0)
        }
    }
}

fn status(paths: &Paths, dir: Option<&PathBuf>, world: &str, as_json: bool) -> Result<i32> {
    let w = load(paths, dir, world)?;
    let recs = log::read(&w.log_path())?;
    let st = art::status(&w, &recs);
    let spent = log::spent(&recs);
    let jobs = recs
        .iter()
        .filter_map(|r| r.job.as_deref())
        .collect::<std::collections::BTreeSet<_>>()
        .len();
    let backends = backends();
    if as_json {
        let assets: Vec<Value> = w
            .assets
            .iter()
            .zip(&st)
            .map(|(a, s)| {
                let p = s.produced.as_ref();
                json!({
                    "id": a.id,
                    "kind": a.kind.as_str(),
                    "model": a.model,
                    "version": a.version,
                    "state": s.state,
                    "reason": s.reason,
                    "spec": a.spec,
                    "outputs": a.outs,
                    "needs": a.needs(),
                    "produced": p.map(|r| json!({
                        "t": r.t, "status": r.status, "spec": r.spec, "job": r.job,
                        "credits": r.credits, "by": r.by,
                    })),
                    "pending_job": s.pending_job,
                })
            })
            .collect();
        println!(
            "{}",
            json!({
                "schema": SCHEMA, "world": w.name, "dir": w.dir, "spent": spent, "jobs": jobs,
                "assets": assets, "backends": backends,
            })
        );
        return Ok(0);
    }
    println!(
        "{} ({}): {spent} credits spent over {jobs} jobs",
        w.name,
        w.dir.display()
    );
    for (name, b) in backends.as_object().into_iter().flatten() {
        println!("  backend {name}: {}", b["status"].as_str().unwrap_or("?"));
    }
    let width = w.assets.iter().map(|a| a.id.len()).max().unwrap_or(0);
    for (a, s) in w.assets.iter().zip(&st) {
        let mut line = format!(
            "  {:width$}  {:7}  {:7}  {}",
            a.id,
            s.state.as_str(),
            a.kind.as_str(),
            a.model.as_deref().unwrap_or("-")
        );
        if let Some(r) = &s.reason {
            line.push_str(&format!("  ({r})"));
        }
        println!("{line}");
    }
    Ok(0)
}

/// Whether each backend could take a job: nolgia's credentials (found, not
/// used: no network), the homelab ComfyUI (a 4 s probe of its /system_stats).
/// Never prints an address or a token.
fn backends() -> Value {
    let nolgia = match art::auth::source() {
        Some(s) => json!({"ok": true, "status": format!("credentials from {}", s.describe())}),
        None => {
            json!({"ok": false, "status": "no credentials (NOLGIA_API_KEY or `nolgia auth login`)"})
        }
    };
    let cfg = art::create::Config::load();
    let mut names = cfg.as_ref().map(|c| c.comfyui_names()).unwrap_or_default();
    if !names.iter().any(|n| n == "homelab") {
        names.push("homelab".into()); // the older settings (BROMIGOS_COMFYUI_URL) still count
    }
    let mut comfyui = serde_json::Map::new();
    for name in names {
        let endpoint = match &cfg {
            Ok(c) => c.comfyui_endpoint(&name),
            Err(_) => art::comfy::endpoint(),
        };
        let v = match endpoint {
            Err(_) => json!({"ok": false, "status": "not configured"}),
            Ok(url) => {
                let probe = runtime().map_err(|e| e.to_string()).and_then(|rt| {
                    let http = art::comfy::client().map_err(|e| e.to_string())?;
                    rt.block_on(art::comfy::probe(&http, &url))
                        .map_err(|e| e.to_string())
                });
                match probe {
                    Ok((version, free)) => {
                        json!({"ok": true, "version": version, "vram_free_gib": free,
                        "status": format!("up: ComfyUI {version}, {free:.1} GiB VRAM free")})
                    }
                    Err(e) => json!({"ok": false, "status": format!("unreachable: {e}")}),
                }
            }
        };
        comfyui.insert(format!("comfyui:{name}"), v);
    }
    let homelab = comfyui
        .get("comfyui:homelab")
        .cloned()
        .unwrap_or_else(|| json!({"ok": false, "status": "not configured"}));
    let create = match &cfg {
        Ok(c) => json!({"ok": true, "files": c.files}),
        Err(e) => json!({"ok": false, "status": e.to_string()}),
    };
    json!({"nolgia": nolgia, "homelab": homelab, "comfyui": comfyui, "create": create})
}

#[allow(clippy::too_many_arguments)]
fn plan_or_run(
    paths: &Paths,
    dir: Option<&PathBuf>,
    world: &str,
    targets: &[String],
    force: bool,
    max_credits: Option<u64>,
    go: bool,
    as_json: bool,
) -> Result<i32> {
    let w = load(paths, dir, world)?;
    let recs = log::read(&w.log_path())?;
    let st = art::status(&w, &recs);
    let sel = art::state::select(&w, &st, targets, force)?;
    // nolgia only when something selected goes to it (ComfyUI and local steps don't)
    let cfg = art::create::Config::load()?;
    let remote = sel.run.iter().any(|id| {
        w.get(id)
            .is_some_and(|a| matches!(art::run::route(a, &cfg), Ok(art::run::Route::Nolgia(_))))
    });
    let rt = runtime()?;
    let (client, auth) = if remote {
        let (c, s) = art::auth::client()?;
        (Some(c), Some(s.describe()))
    } else {
        (None, None)
    };
    let catalog = match &client {
        Some(c) => rt.block_on(art::run::catalog(c))?,
        None => Vec::new(),
    };
    let plan = art::plan(&w, &st, targets, force, &catalog)?;
    let within = max_credits.is_none_or(|m| plan.credits <= m);
    if !go || !plan.ok() || !within {
        if as_json {
            let mut doc = serde_json::to_value(&plan)?;
            doc["schema"] = json!(SCHEMA);
            doc["ok"] = json!(plan.ok());
            doc["max_credits"] = json!(max_credits);
            doc["within_limit"] = json!(within);
            doc["auth"] = json!(auth);
            println!("{doc}");
        } else {
            print_plan(&plan, max_credits);
        }
        if !plan.ok() {
            return Ok(1);
        }
        if !within {
            eprintln!(
                "bromigos art: refused: {} credits is over --max-credits {}",
                plan.credits,
                max_credits.unwrap_or(0)
            );
            return Ok(REFUSED);
        }
        return Ok(0);
    }
    if !as_json {
        print_plan(&plan, max_credits);
    }
    // Only local steps selected: a client that is never called.
    let client = match client {
        Some(c) => c,
        None => nolgia::Client::new("local-steps-only")?,
    };
    finish_run(&rt, client, &w, &plan, &recs, paths, max_credits, as_json)
}

#[allow(clippy::too_many_arguments)]
fn finish_run(
    rt: &nolgia::tokio::runtime::Runtime,
    client: nolgia::Client,
    w: &World,
    plan: &art::Plan,
    recs: &[log::Record],
    paths: &Paths,
    max_credits: Option<u64>,
    as_json: bool,
) -> Result<i32> {
    let opts = RunOptions {
        max_credits,
        spend_ledger: Some(paths.user_state_dir().join("nolgia-spend.jsonl")),
        wait: None,
    };
    let say = |s: &str| eprintln!("  {s}");
    let report = match rt.block_on(art::run(&client, w, plan, recs, &opts, &say)) {
        Ok(r) => r,
        Err(Error::OverBudget { planned, max }) => {
            eprintln!("bromigos art: refused: {planned} credits is over --max-credits {max}");
            return Ok(REFUSED);
        }
        Err(e) => return Err(e.into()),
    };
    if as_json {
        let mut doc = serde_json::to_value(&report)?;
        doc["schema"] = json!(SCHEMA);
        doc["max_credits"] = json!(max_credits);
        println!("{doc}");
    } else {
        for r in &report.ran {
            let credits = r.credits.map_or("?".into(), |c| c.to_string());
            match &r.error {
                None => println!("{}: {} ({credits} credits, {}s)", r.id, r.status, r.seconds),
                Some(e) => println!("{}: {} ({credits} credits): {e}", r.id, r.status),
            }
        }
        println!(
            "{}: spent {} credits (planned {})",
            report.world, report.spent, report.planned
        );
    }
    let over = report.ran.iter().any(|r| {
        r.error
            .as_deref()
            .is_some_and(|e| e.contains("--max-credits"))
    });
    Ok(if report.ok {
        0
    } else if over {
        REFUSED
    } else {
        1
    })
}

fn print_plan(plan: &art::Plan, max_credits: Option<u64>) {
    if plan.assets.is_empty() {
        println!(
            "{}: nothing to make ({} up to date)",
            plan.world,
            plan.skipped.len()
        );
        return;
    }
    println!(
        "{}: {} to make, {} credits{}",
        plan.world,
        plan.assets.len(),
        plan.credits,
        max_credits.map_or(String::new(), |m| format!(" (max {m})"))
    );
    let width = plan.assets.iter().map(|a| a.id.len()).max().unwrap_or(0);
    for a in &plan.assets {
        let state = match a.state {
            State::Pending => "pending",
            s => s.as_str(),
        };
        let detail = match (&a.error, &a.basis) {
            (Some(e), _) => format!("ERROR: {e}"),
            (None, Some(b)) => b.clone(),
            (None, None) => String::new(),
        };
        println!(
            "  {:width$}  {:7}  {:7}  {:24}  {:>5}  {detail}",
            a.id,
            state,
            a.kind,
            a.model.as_deref().unwrap_or("-"),
            a.credits
        );
    }
    if !plan.skipped.is_empty() {
        println!("  up to date: {}", plan.skipped.join(", "));
    }
}
