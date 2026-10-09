//! `art plan` and `art run`: price the selection from the live catalog, then
//! submit each asset through the SDK, wait, download and log it.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use nolgia::types::Model;
use nolgia::{Client, Generation, SubmitOptions, Typed, UploadOptions, WaitOptions};
use serde::Serialize;
use serde_json::{Value, json};

use crate::Error;
use crate::comfy;
use crate::log::{self, LOG_SCHEMA, Record};
use crate::price::{self, Price};
use crate::spec::{Asset, Input, Kind, World, file_sha256};
use crate::state::{self, State, Status};

/// Where an asset is made.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Route {
    /// A local command.
    Command,
    /// nolgia, with this model.
    Nolgia(String),
    /// A ComfyUI instance (`[comfyui.<instance>]` in create.toml), running this workflow.
    Comfy { instance: String, workflow: String },
}

impl Route {
    /// The provider id (`comfyui:<name>`, `nolgia`, `local`).
    pub fn provider(&self) -> String {
        match self {
            Route::Command => "local".into(),
            Route::Nolgia(_) => "nolgia".into(),
            Route::Comfy { instance, .. } => format!("comfyui:{instance}"),
        }
    }

    pub fn model(&self) -> Option<&str> {
        match self {
            Route::Command => None,
            Route::Nolgia(m) => Some(m),
            Route::Comfy { workflow, .. } => Some(workflow),
        }
    }
}

/// Where `a` is made: its pinned provider, its `homelab:` model, its nolgia
/// model, or else the first provider create.toml (or targets.toml) gives its kind
/// that is configured and there (a ComfyUI whose endpoint resolves and answers a
/// TCP connect; nolgia, if enabled).
pub fn route(a: &Asset, cfg: &crate::create::Config) -> Result<Route, String> {
    use crate::create::{Capability, Provider};
    if a.kind == Kind::Command {
        return Ok(Route::Command);
    }
    if let Some(p) = &a.provider {
        let model = a.model.clone().ok_or("a pinned provider needs a model")?;
        return match Provider::parse(p).map_err(|e| e.to_string())? {
            Provider::Comfyui(instance) => Ok(Route::Comfy {
                instance,
                workflow: model
                    .strip_prefix(comfy::PREFIX)
                    .unwrap_or(&model)
                    .to_owned(),
            }),
            Provider::Nolgia => Ok(Route::Nolgia(model)),
            Provider::None => Err("provider = \"none\"".into()),
        };
    }
    if let Some(m) = &a.model {
        return Ok(match m.strip_prefix(comfy::PREFIX) {
            Some(w) => Route::Comfy {
                instance: "homelab".into(),
                workflow: w.to_owned(),
            },
            None => Route::Nolgia(m.clone()),
        });
    }
    let cap = Capability::for_asset(a).ok_or("a command has no provider")?;
    let cands = cfg.candidates(cap).map_err(|e| e.to_string())?;
    for c in &cands {
        match &c.provider {
            Provider::Nolgia => return Ok(Route::Nolgia(c.model.clone())),
            Provider::Comfyui(n)
                if cfg
                    .comfyui_endpoint(n)
                    .is_ok_and(|u| crate::comfy::reachable(&u)) =>
            {
                return Ok(Route::Comfy {
                    instance: n.clone(),
                    workflow: c.model.clone(),
                });
            }
            _ => {}
        }
    }
    Err(format!(
        "no provider for {cap}: create.toml lists {} (see docs/art.md, \"Creation providers\")",
        if cands.is_empty() {
            "none that is configured".to_string()
        } else {
            cands
                .iter()
                .map(|c| c.provider.id())
                .collect::<Vec<_>>()
                .join(", ")
        }
    ))
}

/// `a` with the model its route runs (an unpinned asset gets create.toml's).
pub fn routed(a: &Asset, r: &Route) -> Asset {
    let mut b = a.clone();
    if let Some(m) = r.model() {
        b.model = Some(match r {
            Route::Comfy { .. } => format!("{}{m}", comfy::PREFIX),
            _ => m.to_owned(),
        });
    }
    b
}

/// One asset a run would make.
#[derive(Debug, Clone, Serialize)]
pub struct Planned {
    pub id: String,
    pub kind: String,
    pub model: Option<String>,
    /// Who makes it: `nolgia`, `comfyui:<name>`, `local`.
    pub provider: Option<String>,
    pub state: State,
    pub reason: Option<String>,
    /// What it costs now: 0 for a command, or for a pending job (already paid).
    pub credits: u64,
    pub basis: Option<String>,
    /// Why it can't run (the catalog refuses it, an input is missing): the
    /// whole plan is refused while any asset has one.
    pub error: Option<String>,
    pub needs: Vec<String>,
    pub outputs: Vec<String>,
    pub job: Option<String>,
}

/// What a run would do, and what it costs.
#[derive(Debug, Clone, Serialize)]
pub struct Plan {
    pub world: String,
    pub dir: PathBuf,
    pub assets: Vec<Planned>,
    pub skipped: Vec<String>,
    pub credits: u64,
}

impl Plan {
    pub fn ok(&self) -> bool {
        self.assets.iter().all(|a| a.error.is_none())
    }
}

/// The live catalog, through the SDK (`GET /models`).
pub async fn catalog(client: &Client) -> Result<Vec<Model>, Error> {
    Ok(client.list_models().send().typed().await?.models)
}

/// Selects what to run and prices it. `catalog` is only needed when something
/// remote is selected; pass `None` to price nothing (status only).
pub fn plan(
    world: &World,
    statuses: &[Status],
    targets: &[String],
    force: bool,
    catalog: &[Model],
) -> Result<Plan, Error> {
    let sel = state::select(world, statuses, targets, force)?;
    let cfg = crate::create::Config::load()?;
    let mut assets = Vec::new();
    for id in &sel.run {
        let a = world.get(id).expect("selected from the world");
        let st = statuses
            .iter()
            .find(|s| &s.id == id)
            .expect("status of every asset");
        let state = if force && st.state == State::Done {
            State::Stale
        } else {
            st.state
        };
        let r = route(a, &cfg);
        let a = &match &r {
            Ok(r) => routed(a, r),
            Err(_) => a.clone(),
        };
        let mut p = Planned {
            id: a.id.clone(),
            kind: a.kind.to_string(),
            model: r.as_ref().ok().and_then(|r| r.model().map(String::from)),
            provider: r.as_ref().ok().map(Route::provider),
            state,
            reason: if force && st.state == State::Done {
                Some("forced".into())
            } else {
                st.reason.clone()
            },
            credits: 0,
            basis: None,
            error: None,
            needs: a.needs().into_iter().map(String::from).collect(),
            outputs: a.outs.clone(),
            job: st.pending_job.clone(),
        };
        if let Err(e) = &r {
            p.error = Some(e.clone());
        } else if let Some(f) = a.files().into_iter().find(|f| !world.dir.join(f).exists()) {
            p.error = Some(format!("input {f} is not in {}", world.dir.display()));
        } else if state == State::Pending {
            p.basis = Some("already submitted".into());
        } else if comfy::is_homelab(a.model.as_deref()) {
            match comfy::check(a) {
                Ok(_) => {
                    p.basis = Some(format!(
                        "{}: no credits",
                        p.provider.as_deref().unwrap_or("comfyui")
                    ))
                }
                Err(e) => p.error = Some(e),
            }
        } else if let Some(m) = &a.model {
            match catalog.iter().find(|c| &c.id == m) {
                None => p.error = Some(format!("{m} is not in nolgia's catalog")),
                Some(model) => match price::price(a, model) {
                    Ok(Price { credits, basis }) => {
                        p.credits = credits;
                        p.basis = Some(basis);
                    }
                    Err(e) => p.error = Some(e),
                },
            }
        } else {
            p.basis = Some("local command".into());
        }
        assets.push(p);
    }
    let credits = assets.iter().map(|a| a.credits).sum();
    Ok(Plan {
        world: world.name.clone(),
        dir: world.dir.clone(),
        assets,
        skipped: sel.skipped,
        credits,
    })
}

/// How a run behaves.
#[derive(Debug, Clone, Default)]
pub struct RunOptions {
    /// Refuse to start when the plan costs more; stop before a submit that
    /// would take the run past it. None: no cap.
    pub max_credits: Option<u64>,
    /// Also append each finished job to this spend ledger (JSONL).
    pub spend_ledger: Option<PathBuf>,
    /// The longest wait for one job. Default 30 min for images, 60 for video.
    pub wait: Option<Duration>,
}

/// What happened to one asset.
#[derive(Debug, Clone, Serialize)]
pub struct Ran {
    pub id: String,
    pub status: String,
    pub job: Option<String>,
    pub credits: Option<u64>,
    pub planned: u64,
    pub outputs: Vec<String>,
    pub seconds: u64,
    pub error: Option<String>,
}

/// What a run did.
#[derive(Debug, Clone, Serialize)]
pub struct Report {
    pub world: String,
    pub planned: u64,
    /// Credits this run was charged (refunds excluded).
    pub spent: u64,
    pub ran: Vec<Ran>,
    pub skipped: Vec<String>,
    pub ok: bool,
}

/// Runs a plan. Stops at the first asset that fails (what reads it can't run).
pub async fn run(
    client: &Client,
    world: &World,
    plan: &Plan,
    records: &[Record],
    opts: &RunOptions,
    say: &dyn Fn(&str),
) -> Result<Report, Error> {
    if !plan.ok() {
        return Err(Error::Spec(
            "the plan has errors; see `bromigos art plan`".into(),
        ));
    }
    if let Some(max) = opts.max_credits
        && plan.credits > max
    {
        return Err(Error::OverBudget {
            planned: plan.credits,
            max,
        });
    }
    let mut report = Report {
        world: world.name.clone(),
        planned: plan.credits,
        spent: 0,
        ran: Vec::new(),
        skipped: plan.skipped.clone(),
        ok: true,
    };
    let mut uploads: HashMap<String, nolgia::types::Asset> = HashMap::new();
    let cfg = crate::create::Config::load()?;
    for p in &plan.assets {
        let a = world.get(&p.id).expect("planned from the world");
        let rt = route(a, &cfg).map_err(Error::Spec)?;
        let a = &routed(a, &rt);
        let started = Instant::now();
        let mut ran = Ran {
            id: a.id.clone(),
            status: "succeeded".into(),
            job: None,
            credits: None,
            planned: p.credits,
            outputs: a.outs.clone(),
            seconds: 0,
            error: None,
        };
        let r = if a.kind == Kind::Command {
            say(&format!("{}: running {}", a.id, a.run.join(" ")));
            run_command(world, a).map(|_| Some(0))
        } else if let Route::Comfy { instance, .. } = &rt {
            homelab(
                world, a, &cfg, instance, p.credits, opts, say, started, &mut ran,
            )
            .await
        } else {
            let ctx = Job {
                client,
                world,
                asset: a,
                planned: p.credits,
                opts,
                spent_before: report.spent,
                say,
                started,
            };
            match &p.job {
                Some(job) if p.state == State::Pending => {
                    let paid = records
                        .iter()
                        .rev()
                        .find(|r| r.job.as_deref() == Some(job))
                        .and_then(|r| r.credits);
                    ran.job = Some(job.clone());
                    ctx.resume(job, paid, &mut ran).await
                }
                _ => ctx.submit(&mut uploads, &mut ran).await,
            }
        };
        ran.seconds = started.elapsed().as_secs();
        match r {
            Ok(credits) => {
                ran.credits = credits;
                if a.kind == Kind::Command {
                    log::append(
                        &world.log_path(),
                        &record(world, a, "succeeded", &ran, &Default::default()),
                    )?;
                }
            }
            Err(e) => {
                ran.status = if ran.status == "succeeded" {
                    "failed".into()
                } else {
                    ran.status
                };
                ran.error = Some(log::scrub(&e.to_string()));
                if matches!(rt, Route::Comfy { .. }) {
                    let mut rec = record(world, a, "failed", &ran, &Default::default());
                    rec.backend = Some(rt.provider());
                    log::append(&world.log_path(), &rec)?;
                }
                if a.kind == Kind::Command {
                    log::append(
                        &world.log_path(),
                        &record(world, a, "failed", &ran, &Default::default()),
                    )?;
                }
                report.ok = false;
            }
        }
        report.spent += if p.state == State::Pending {
            0
        } else {
            ran.credits.unwrap_or(0)
        };
        let stop = !report.ok;
        report.ran.push(ran);
        if stop {
            break;
        }
    }
    Ok(report)
}

/// A record for `a` from what happened.
fn record(
    world: &World,
    a: &Asset,
    status: &str,
    ran: &Ran,
    inputs: &BTreeMap<String, String>,
) -> Record {
    Record {
        schema: LOG_SCHEMA,
        t: log::now(),
        world: world.name.clone(),
        asset: a.id.clone(),
        version: a.version,
        kind: a.kind.to_string(),
        spec: a.spec.clone(),
        status: status.into(),
        model: a.model.clone(),
        prompt_sha256: a.prompt_sha256(),
        credits: ran.credits,
        planned: Some(ran.planned),
        job: ran.job.clone(),
        outputs: if status == "succeeded" {
            a.outs.clone()
        } else {
            Vec::new()
        },
        inputs: inputs.clone(),
        seconds: Some(ran.seconds),
        error: ran.error.as_deref().map(log::scrub),
        by: "bromigos art run".into(),
        backend: None,
        license: None,
    }
}

/// Makes `a` on the homelab ComfyUI: no credits, logged with the backend and
/// the weights' licence.
#[allow(clippy::too_many_arguments)]
async fn homelab(
    world: &World,
    a: &Asset,
    cfg: &crate::create::Config,
    instance: &str,
    planned: u64,
    opts: &RunOptions,
    say: &dyn Fn(&str),
    started: Instant,
    ran: &mut Ran,
) -> Result<Option<u64>, Error> {
    let model = comfy::check(a).map_err(Error::Spec)?;
    let url = cfg.comfyui_endpoint(instance)?;
    let http = comfy::client()?;
    let mut shas: BTreeMap<String, String> = BTreeMap::new();
    let mut inputs = Vec::new();
    // a video's end frame, when it isn't its start frame, goes up after it
    let end = a.end.iter().filter(|e| a.inputs.first() != Some(*e));
    for i in a.inputs.iter().chain(end) {
        let path = input_path(world, i)?;
        if let Input::File(f) = i {
            shas.insert(
                f.clone(),
                file_sha256(&path).map_err(|e| Error::io(&path, e))?,
            );
        }
        inputs.push(path);
    }
    let mask = match &a.mask {
        Some(i) => {
            let path = input_path(world, i)?;
            if let Input::File(f) = i {
                shas.insert(
                    f.clone(),
                    file_sha256(&path).map_err(|e| Error::io(&path, e))?,
                );
            }
            Some(path)
        }
        None => None,
    };
    let out = world.dir.join(&a.outs[0]);
    let wait = opts.wait.unwrap_or(Duration::from_secs(
        cfg.comfyui_timeout(instance).unwrap_or(30 * 60),
    ));
    let id = comfy::make(&http, &url, a, &inputs, mask.as_deref(), &out, wait, say).await?;
    say(&format!("{}: wrote {}", a.id, a.outs[0]));
    ran.job = Some(id);
    ran.credits = Some(0);
    ran.planned = planned;
    ran.seconds = started.elapsed().as_secs();
    let mut rec = record(world, a, "succeeded", ran, &shas);
    rec.backend = Some(format!("comfyui:{instance}"));
    rec.license = Some(model.license.clone());
    log::append(&world.log_path(), &rec)?;
    Ok(Some(0))
}

/// The path of an input on disk: a file in the theme, or an asset's (first)
/// output.
fn input_path(world: &World, i: &Input) -> Result<PathBuf, Error> {
    let p = match i {
        Input::File(f) => world.dir.join(f),
        Input::Asset(id) => {
            let a = world
                .get(id)
                .ok_or_else(|| Error::Spec(format!("no asset {id}")))?;
            world.dir.join(&a.outs[0])
        }
    };
    if !p.exists() {
        return Err(Error::Spec(format!(
            "input {i} ({}) is not there",
            p.display()
        )));
    }
    Ok(p)
}

/// `{dir}` the theme directory, `{in}`/`{out}` the first input/output,
/// `{ins}`/`{outs}` (a whole argument) every one of them; paths absolute.
fn run_command(world: &World, a: &Asset) -> Result<(), Error> {
    let ins: Vec<String> = a
        .inputs
        .iter()
        .map(|i| input_path(world, i).map(|p| p.display().to_string()))
        .collect::<Result<_, _>>()?;
    let outs: Vec<String> = a
        .outs
        .iter()
        .map(|o| world.dir.join(o).display().to_string())
        .collect();
    for o in &a.outs {
        if let Some(d) = world.dir.join(o).parent() {
            std::fs::create_dir_all(d).map_err(|e| Error::io(d, e))?;
        }
    }
    let dir = world.dir.display().to_string();
    let mut argv: Vec<String> = Vec::new();
    for arg in &a.run {
        match arg.as_str() {
            "{ins}" => argv.extend(ins.iter().cloned()),
            "{outs}" => argv.extend(outs.iter().cloned()),
            _ => argv.push(
                arg.replace("{dir}", &dir)
                    .replace("{in}", ins.first().map_or("", String::as_str))
                    .replace("{out}", outs.first().map_or("", String::as_str)),
            ),
        }
    }
    let status = std::process::Command::new(&argv[0])
        .args(&argv[1..])
        .current_dir(&world.dir)
        .stdin(std::process::Stdio::null())
        .status()
        .map_err(|e| Error::Spec(format!("{}: {e}", argv[0])))?;
    if !status.success() {
        return Err(Error::Spec(format!("{} exited with {status}", argv[0])));
    }
    if let Some(o) = a.outs.iter().find(|o| !world.dir.join(o).exists()) {
        return Err(Error::Spec(format!("{} did not write {o}", argv[0])));
    }
    Ok(())
}

struct Job<'a> {
    client: &'a Client,
    world: &'a World,
    asset: &'a Asset,
    planned: u64,
    opts: &'a RunOptions,
    spent_before: u64,
    say: &'a dyn Fn(&str),
    started: Instant,
}

impl Job<'_> {
    fn wait_options(&self) -> WaitOptions {
        let clip = self.asset.kind == Kind::Upscale
            && self
                .asset
                .outs
                .first()
                .is_some_and(|o| o.to_ascii_lowercase().ends_with(".mp4"));
        let default = if self.asset.kind == Kind::Video || clip {
            60
        } else {
            30
        };
        WaitOptions::default().timeout(self.opts.wait.unwrap_or(Duration::from_secs(default * 60)))
    }

    /// Uploads (once per run per content), quotes, submits, waits, downloads.
    async fn submit(
        &self,
        uploads: &mut HashMap<String, nolgia::types::Asset>,
        ran: &mut Ran,
    ) -> Result<Option<u64>, Error> {
        let (a, world) = (self.asset, self.world);
        let mut shas: BTreeMap<String, String> = BTreeMap::new();
        let mut uploaded: HashMap<String, nolgia::types::Asset> = HashMap::new();
        for i in a.inputs.iter().chain(&a.mask).chain(&a.end) {
            let path = input_path(world, i)?;
            let sha = file_sha256(&path).map_err(|e| Error::io(&path, e))?;
            if let Input::File(f) = i {
                shas.insert(f.clone(), sha.clone());
            }
            if !uploads.contains_key(&sha) {
                (self.say)(&format!("{}: uploading {i}", a.id));
                let up = self
                    .client
                    .upload_file(&path, UploadOptions::default().tag("bromigos-art"))
                    .await?;
                uploads.insert(sha.clone(), up);
            }
            uploaded.insert(i.to_string(), uploads[&sha].clone());
        }
        let body = request_body(a, &uploaded);
        let endpoint = match a.kind {
            Kind::Video => "/generate/video",
            Kind::Model3d => "/generate/3d",
            _ => "/generate/image",
        };
        let generation = Generation::json(endpoint, body.clone())?;
        let quote = self.client.quote(generation.clone()).await?;
        let credits = u64::try_from(quote.credits).unwrap_or(0);
        if credits != self.planned {
            (self.say)(&format!(
                "{}: nolgia quotes {credits} credits (the catalog said {})",
                a.id, self.planned
            ));
        }
        if !quote.sufficient_credits {
            return Err(Error::Api(format!(
                "not enough credits for {} ({credits} needed{})",
                a.id,
                quote
                    .balance_credits
                    .map_or(String::new(), |b| format!(", {b} left"))
            )));
        }
        if let Some(max) = self.opts.max_credits
            && self.spent_before + credits > max
        {
            return Err(Error::OverBudget {
                planned: self.spent_before + credits,
                max,
            });
        }
        let mut body = body;
        body["confirmation_token"] = json!(quote.confirmation_token);
        let generation = Generation::json(endpoint, body)?;
        // A fresh key: this is a deliberate generation, even of a recipe that
        // ran before; the SDK's own retries reuse it, so they never pay twice.
        let key = format!("bromigos-art-{}", nolgia::Uuid::new_v4());
        let handle = self
            .client
            .submit_with(generation, SubmitOptions::default().idempotency_key(key))
            .await?;
        let job = handle.id().to_string();
        ran.job = Some(job.clone());
        ran.credits = Some(credits);
        ran.seconds = self.started.elapsed().as_secs();
        (self.say)(&format!(
            "{}: submitted job {job} ({credits} credits)",
            a.id
        ));
        log::append(
            &world.log_path(),
            &record(world, a, "submitted", ran, &shas),
        )?;
        self.finish(
            handle.result_with(self.wait_options()).await,
            Some(credits),
            ran,
            &shas,
        )
        .await
    }

    /// Waits for a job submitted by an earlier run.
    async fn resume(
        &self,
        job: &str,
        paid: Option<u64>,
        ran: &mut Ran,
    ) -> Result<Option<u64>, Error> {
        let id: nolgia::Uuid = job
            .parse()
            .map_err(|_| Error::Spec(format!("job id {job:?} in the log is not a UUID")))?;
        (self.say)(&format!(
            "{}: waiting for job {job}, submitted earlier",
            self.asset.id
        ));
        let handle = self.client.job(id).await?;
        let shas = self.file_shas();
        self.finish(
            handle.result_with(self.wait_options()).await,
            paid,
            ran,
            &shas,
        )
        .await
    }

    fn file_shas(&self) -> BTreeMap<String, String> {
        self.asset
            .files()
            .into_iter()
            .filter_map(|f| {
                file_sha256(&self.world.dir.join(f))
                    .ok()
                    .map(|s| (f.to_owned(), s))
            })
            .collect()
    }

    async fn finish(
        &self,
        result: nolgia::Result<nolgia::GenerationResult>,
        credits: Option<u64>,
        ran: &mut Ran,
        shas: &BTreeMap<String, String>,
    ) -> Result<Option<u64>, Error> {
        let (a, world) = (self.asset, self.world);
        let done = match result {
            Ok(done) => done,
            Err(nolgia::Error::Job(failed)) => {
                let charged = match failed.credits_refunded {
                    Some(true) => Some(0),
                    Some(false) => credits,
                    None => None,
                };
                ran.status = "failed".into();
                ran.credits = charged;
                ran.error = Some(format!("{} ({:?})", failed.message, failed.code));
                ran.seconds = self.started.elapsed().as_secs();
                log::append(&world.log_path(), &record(world, a, "failed", ran, shas))?;
                self.ledger(ran);
                return Err(Error::Api(format!(
                    "job {} failed: {}{}",
                    failed.job_id,
                    failed.message,
                    match failed.credits_refunded {
                        Some(true) => ", credits refunded",
                        Some(false) => ", credits charged",
                        None => ", refund unknown",
                    }
                )));
            }
            Err(nolgia::Error::Timeout { job_id }) => {
                ran.status = "timeout".into();
                ran.credits = credits;
                ran.seconds = self.started.elapsed().as_secs();
                log::append(&world.log_path(), &record(world, a, "timeout", ran, shas))?;
                return Err(Error::Api(format!(
                    "job {} is still running; `bromigos art run {} {}` waits for it again",
                    job_id.map(|j| j.to_string()).unwrap_or_default(),
                    world.name,
                    a.id
                )));
            }
            Err(e) => return Err(e.into()),
        };
        if done.media.len() < a.outs.len() {
            return Err(Error::Api(format!(
                "job {} made {} file(s), {} expected",
                done.job.id,
                done.media.len(),
                a.outs.len()
            )));
        }
        for (m, out) in done.media.iter().zip(&a.outs) {
            let path = world.dir.join(out);
            if let Some(d) = path.parent() {
                std::fs::create_dir_all(d).map_err(|e| Error::io(d, e))?;
            }
            self.client.download(&m.url, &path).await?;
            (self.say)(&format!("{}: wrote {out}", a.id));
        }
        ran.credits = credits;
        ran.seconds = self.started.elapsed().as_secs();
        log::append(&world.log_path(), &record(world, a, "succeeded", ran, shas))?;
        self.ledger(ran);
        Ok(credits)
    }

    /// The desktop's nolgia spend ledger, in the format its other writers use.
    fn ledger(&self, ran: &Ran) {
        let Some(path) = &self.opts.spend_ledger else {
            return;
        };
        let a = self.asset;
        let line = json!({
            "t": log::now(),
            "kind": match a.kind { Kind::Video => "video", Kind::Model3d => "3d", Kind::Upscale => "upscale", _ => "image" },
            "model": a.model,
            "job": ran.job,
            "estimate": ran.planned as f64,
            "credits": ran.credits.unwrap_or(0),
            "out": format!("{}/{}", self.world.name, a.outs.first().map_or("", String::as_str)),
            "seconds": ran.seconds,
            "by": format!("bromigos art run {} {}", self.world.name, a.id),
        });
        if let Err(e) = log::append_line(path, &line.to_string()) {
            (self.say)(&format!("spend ledger {}: {e}", path.display()));
        }
    }
}

/// The JSON body for an asset, its inputs already uploaded (by `Input` text).
pub fn request_body(a: &Asset, up: &HashMap<String, nolgia::types::Asset>) -> Value {
    let id = |i: &Input| up.get(&i.to_string()).map(|x| x.id);
    let mut b = serde_json::Map::new();
    b.insert("model".into(), json!(a.model));
    if let Some(p) = &a.prompt {
        b.insert("prompt".into(), json!(p));
    }
    let mut put = |k: &str, v: Value| {
        if !v.is_null() {
            b.insert(k.into(), v);
        }
    };
    match a.kind {
        Kind::Image | Kind::Edit | Kind::Cutout => {
            let refs: Vec<_> = a.inputs.iter().filter_map(id).collect();
            if !refs.is_empty() {
                put("reference_asset_ids", json!(refs));
            }
            put("mask_asset_id", json!(a.mask.as_ref().and_then(id)));
            put("aspect_ratio", json!(a.aspect));
            put("quality", json!(a.quality));
            put("render_quality", json!(a.render_quality));
            put("aura", json!(a.aura));
            if a.images > 1 {
                put("num_images", json!(a.images));
            }
        }
        Kind::Video => {
            let start = a.inputs.first().and_then(|i| up.get(&i.to_string()));
            put("image_url", json!(start.map(|s| s.signed_url.clone())));
            put("end_image_asset_id", json!(a.end.as_ref().and_then(id)));
            put("duration_seconds", json!(a.duration));
            put("quality", json!(a.resolution));
            put("aspect_ratio", json!(a.aspect));
            put("generate_audio", json!(a.audio));
        }
        Kind::Model3d => {
            // the concept image; `extra.texture = true` for a textured mesh where the
            // model offers one (holograms keep geometry only)
            let refs: Vec<_> = a.inputs.iter().filter_map(id).collect();
            put("image_asset_ids", json!(refs));
            put("tags", json!(["bromigos", "holo"]));
            // no paid texture pass unless asked (`extra.texture = true`): holograms keep
            // geometry only; trellis takes no texture switch (it always textures)
            if !a.extra.contains_key("texture") && a.model.as_deref() != Some("trellis") {
                put("texture", json!(false));
            }
        }
        // a ComfyUI's only (price.rs refuses it on nolgia)
        Kind::Upscale | Kind::Command => {}
    }
    for (k, v) in &a.extra {
        b.insert(k.clone(), v.clone());
    }
    Value::Object(b)
}

/// Records an asset produced outside `art run` (by hand, or by an older tool)
/// as produced with its current spec. Every output must exist.
pub fn mark(
    world: &World,
    id: &str,
    job: Option<String>,
    credits: Option<u64>,
    at: Option<String>,
    seconds: Option<u64>,
    by: &str,
) -> Result<Record, Error> {
    let a = world
        .get(id)
        .ok_or_else(|| Error::Spec(format!("{}: no asset {id:?}", world.name)))?;
    if let Some(o) = a.outs.iter().find(|o| !world.dir.join(o).exists()) {
        return Err(Error::Spec(format!("{id}: {o} is not there to mark")));
    }
    let inputs = a
        .files()
        .into_iter()
        .filter_map(|f| {
            file_sha256(&world.dir.join(f))
                .ok()
                .map(|s| (f.to_owned(), s))
        })
        .collect();
    let rec = Record {
        schema: LOG_SCHEMA,
        t: at.unwrap_or_else(log::now),
        world: world.name.clone(),
        asset: a.id.clone(),
        version: a.version,
        kind: a.kind.to_string(),
        spec: a.spec.clone(),
        status: "marked".into(),
        model: a.model.clone(),
        prompt_sha256: a.prompt_sha256(),
        credits,
        planned: None,
        job,
        outputs: a.outs.clone(),
        inputs,
        seconds,
        error: None,
        by: by.to_owned(),
        backend: None,
        license: None,
    };
    log::append(&world.log_path(), &rec)?;
    Ok(rec)
}

/// The theme directory of `world`: `explicit` if given; else the nearest
/// `themes/<world>/` with an `art.toml` above `cwd` (a checkout); else the
/// user's themes, then the system's.
pub fn find_world(
    world: &str,
    explicit: Option<&Path>,
    cwd: &Path,
    user_themes: &Path,
    system_themes: &Path,
) -> Result<PathBuf, Error> {
    if let Some(d) = explicit {
        return if World::art_toml(d).is_file() {
            Ok(d.to_path_buf())
        } else {
            Err(Error::Spec(format!("{}: no art.toml", d.display())))
        };
    }
    let candidates = cwd
        .ancestors()
        .map(|d| d.join("themes").join(world))
        .chain([user_themes.join(world), system_themes.join(world)]);
    for d in candidates {
        if World::art_toml(&d).is_file() {
            return Ok(d);
        }
    }
    Err(Error::Spec(format!(
        "no art.toml for {world:?} (looked in themes/{world}/ above {}, {}, {})",
        cwd.display(),
        user_themes.join(world).display(),
        system_themes.join(world).display()
    )))
}
