//! `art plan` and `art run` against a mock of the nolgia API (wiremock): the
//! catalog, uploads, the quote, the submit, the long-poll, the asset listing
//! and the download. No network, no credentials, nothing billable.

use std::path::Path;
use std::sync::Mutex;

use bromigos_art::log::{self, Record};
use bromigos_art::{Error, RunOptions, State, World, plan, run, status};
use nolgia::{Client, RetryPolicy, Uuid};
use serde_json::{Value, json};
use wiremock::matchers::{body_partial_json, header_exists, method, path, query_param};
use wiremock::{Mock, MockServer, Request, ResponseTemplate};

const ART: &str = r#"
format = 1

[defaults]
model = "flare"
aura = false
render_quality = "high"

[[assets]]
id = "comp"
kind = "image"
prompt = "a bayou at night"
inputs = ["art/refs/den.jpg"]
aspect = "16:9"
out = "art/comps/comp.png"

[[assets]]
id = "fix"
kind = "edit"
prompt = "move the keeper"
input = "@comp"
mask = "art/masks/mask.png"
out = "art/comps/fix.png"

[[assets]]
id = "split"
kind = "command"
run = ["cp", "{in}", "{out}"]
inputs = ["@fix"]
outs = ["backgrounds/layers/00-sky.png"]
"#;

fn catalog() -> Value {
    json!({"models": [
        {"id": "flare", "modality": "image", "recommended": true, "capabilities": [],
         "cost": {"credits": 8, "unit": "per_image"},
         "image": {"aspect_ratios": ["16:9"], "inpaint_mask": true, "reference_images_max": 4,
                   "render_quality": {"default": "auto", "options": [
                       {"id": "high", "credits_added": 0, "premium": false}]}}}
    ]})
}

fn job(id: Uuid, status: &str) -> Value {
    json!({"id": id, "user_id": Uuid::nil(), "modality": "image", "model": "flare", "status": status,
           "created_at": "2026-10-08T00:00:00Z", "updated_at": "2026-10-08T00:00:00Z"})
}

fn asset(id: Uuid, url: &str) -> Value {
    json!({"id": id, "user_id": Uuid::nil(), "modality": "image", "model": "flare",
           "signed_url": url, "mime_type": "image/png", "expires_at": "2026-10-09T00:00:00Z",
           "created_at": "2026-10-08T00:00:00Z", "mirrors": [], "projects": [], "tags": []})
}

fn client(server: &MockServer) -> Client {
    Client::builder()
        .api_key("nol_test")
        .base_url(server.uri())
        .retry(RetryPolicy::none())
        .build()
        .unwrap()
}

fn theme() -> tempfile::TempDir {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("art.toml"), ART).unwrap();
    for (f, bytes) in [
        ("art/refs/den.jpg", &b"den"[..]),
        ("art/masks/mask.png", b"\x89PNGmask"),
    ] {
        let p = d.path().join(f);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, bytes).unwrap();
    }
    d
}

/// The API: every upload becomes a new asset, every submit a job that
/// succeeds on the first wait with one image whose bytes name the job.
async fn api(server: &MockServer, quote: u64, outcome: &'static str) {
    Mock::given(method("GET"))
        .and(path("/v1/models"))
        .respond_with(ResponseTemplate::new(200).set_body_json(catalog()))
        .mount(server)
        .await;
    let uri = server.uri();
    Mock::given(method("POST"))
        .and(path("/v1/assets/uploads"))
        .respond_with(move |_: &Request| {
            let id = Uuid::new_v4();
            ResponseTemplate::new(201).set_body_json(json!({
                "upload_id": id, "asset_id": id,
                "upload_url": format!("{uri}/bucket/{id}?X-Sig=secret"),
                "expires_at": "2026-10-08T00:30:00Z"}))
        })
        .mount(server)
        .await;
    Mock::given(method("PUT"))
        .respond_with(ResponseTemplate::new(200))
        .mount(server)
        .await;
    let uri = server.uri();
    Mock::given(method("POST"))
        .and(wiremock::matchers::path_regex(
            r"^/v1/assets/uploads/[0-9a-f-]+/complete$",
        ))
        .respond_with(move |r: &Request| {
            let id: Uuid = r.url.path().split('/').nth(4).unwrap().parse().unwrap();
            ResponseTemplate::new(200)
                .set_body_json(asset(id, &format!("{uri}/in/{id}?X-Sig=secret")))
        })
        .mount(server)
        .await;
    Mock::given(method("POST"))
        .and(path("/v1/jobs/cost"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "kind": "image", "model": "flare", "credits": quote, "basis": "one_generation",
            "settings": [], "confirmation_token": "confirm-me", "expires_at": "2026-10-08T00:10:00Z",
            "sufficient_credits": true})))
        .mount(server)
        .await;
    Mock::given(method("POST"))
        .and(path("/v1/generate/image"))
        .and(body_partial_json(
            json!({"confirmation_token": "confirm-me", "aura": false}),
        ))
        .and(header_exists("idempotency-key"))
        .respond_with(|_: &Request| {
            ResponseTemplate::new(202).set_body_json(job(Uuid::new_v4(), "queued"))
        })
        .mount(server)
        .await;
    let uri = server.uri();
    Mock::given(method("GET"))
        .and(wiremock::matchers::path_regex(r"^/v1/jobs/[0-9a-f-]+/wait$"))
        .respond_with(move |r: &Request| {
            let id: Uuid = r.url.path().split('/').nth(3).unwrap().parse().unwrap();
            let mut j = job(id, outcome);
            if outcome == "failed" {
                j["failure"] = json!({"kind": "provider", "code": "job_failed", "message": "upstream 502", "credits_refunded": true});
            } else {
                j["asset"] = asset(id, &format!("{uri}/out/{id}.png?X-Sig=secret"));
            }
            ResponseTemplate::new(200).set_body_json(j)
        })
        .mount(server)
        .await;
    Mock::given(method("GET"))
        .and(path("/v1/assets"))
        .and(query_param("limit", "100"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"items": []})))
        .mount(server)
        .await;
    Mock::given(method("GET"))
        .and(wiremock::matchers::path_regex(r"^/out/"))
        .respond_with(|r: &Request| {
            ResponseTemplate::new(200).set_body_bytes(format!("png of {}", r.url.path()))
        })
        .mount(server)
        .await;
}

async fn plan_and_run(
    server: &MockServer,
    dir: &Path,
    targets: &[String],
    opts: &RunOptions,
) -> Result<(bromigos_art::Plan, bromigos_art::Report), Error> {
    let c = client(server);
    let w = World::load("mire", dir)?;
    let recs = log::read(&w.log_path())?;
    let st = status(&w, &recs);
    let cat = bromigos_art::run::catalog(&c).await?;
    let p = plan(&w, &st, targets, false, &cat)?;
    let said = Mutex::new(Vec::new());
    let r = run(&c, &w, &p, &recs, opts, &|s| {
        said.lock().unwrap().push(s.to_owned())
    })
    .await?;
    Ok((p, r))
}

fn records(dir: &Path) -> Vec<Record> {
    log::read(&dir.join("art.log.jsonl")).unwrap()
}

#[tokio::test]
async fn a_world_is_planned_run_logged_and_then_left_alone() {
    let server = MockServer::start().await;
    api(&server, 8, "succeeded").await;
    let d = theme();
    let spend = d.path().join("spend.jsonl");
    let opts = RunOptions {
        spend_ledger: Some(spend.clone()),
        ..Default::default()
    };

    let (p, r) = plan_and_run(&server, d.path(), &[], &opts).await.unwrap();
    // Plan: two flare jobs at 8, a free local step, in input order.
    let ids: Vec<&str> = p.assets.iter().map(|a| a.id.as_str()).collect();
    assert_eq!(ids, ["comp", "fix", "split"]);
    assert_eq!(p.credits, 16);
    assert_eq!(
        p.assets[0].basis.as_deref(),
        Some("8 (base) + 0 (render high) × 1 image")
    );
    assert!(r.ok, "{r:?}");
    assert_eq!(r.spent, 16);

    // Outputs are written; the command read the edit and wrote the layer.
    let fix = std::fs::read_to_string(d.path().join("art/comps/fix.png")).unwrap();
    assert!(fix.starts_with("png of /out/"));
    assert_eq!(
        std::fs::read_to_string(d.path().join("backgrounds/layers/00-sky.png")).unwrap(),
        fix
    );

    // The log: submitted + succeeded per job, then the command; no URL anywhere.
    let text = std::fs::read_to_string(d.path().join("art.log.jsonl")).unwrap();
    assert!(!text.contains("http"), "a URL leaked into the log");
    assert!(!text.contains("X-Sig") && !text.contains("nol_test"));
    let recs = records(d.path());
    let seq: Vec<(&str, &str)> = recs
        .iter()
        .map(|r| (r.asset.as_str(), r.status.as_str()))
        .collect();
    assert_eq!(
        seq,
        [
            ("comp", "submitted"),
            ("comp", "succeeded"),
            ("fix", "submitted"),
            ("fix", "succeeded"),
            ("split", "succeeded")
        ]
    );
    let comp = &recs[1];
    assert_eq!(comp.credits, Some(8));
    assert_eq!(comp.planned, Some(8));
    assert_eq!(comp.model.as_deref(), Some("flare"));
    assert!(comp.job.as_deref().unwrap().parse::<Uuid>().is_ok());
    assert_eq!(
        comp.prompt_sha256.as_deref(),
        Some(bromigos_art::spec::sha256_hex("a bayou at night").as_str())
    );
    assert_eq!(comp.inputs.keys().collect::<Vec<_>>(), ["art/refs/den.jpg"]);
    assert_eq!(log::spent(&recs), 16);
    // The spend ledger got each job once.
    assert_eq!(std::fs::read_to_string(&spend).unwrap().lines().count(), 2);

    // The edit uploaded its input and mask and sent them as ids.
    let reqs = server.received_requests().await.unwrap();
    let edit: Value = reqs
        .iter()
        .filter(|r| r.url.path() == "/v1/generate/image")
        .map(|r| serde_json::from_slice(&r.body).unwrap())
        .nth(1)
        .unwrap();
    assert_eq!(edit["reference_asset_ids"].as_array().unwrap().len(), 1);
    assert!(edit["mask_asset_id"].is_string());
    assert_eq!(edit["prompt"], "move the keeper");
    assert_eq!(edit["render_quality"], "high");

    // Again: nothing to do, nothing submitted.
    let before = server.received_requests().await.unwrap().len();
    let (p, r) = plan_and_run(&server, d.path(), &[], &opts).await.unwrap();
    assert!(p.assets.is_empty() && r.ran.is_empty());
    assert_eq!(p.skipped, ["comp", "fix", "split"]);
    let after = server.received_requests().await.unwrap();
    assert!(after[before..].iter().all(|r| r.url.path() == "/v1/models"));

    // A changed prompt reruns the edit and the step that reads it, not the comp.
    std::fs::write(
        d.path().join("art.toml"),
        ART.replace("move the keeper", "move him left"),
    )
    .unwrap();
    let (p, r) = plan_and_run(&server, d.path(), &[], &opts).await.unwrap();
    let ids: Vec<&str> = p.assets.iter().map(|a| a.id.as_str()).collect();
    assert_eq!(ids, ["fix", "split"]);
    assert_eq!((p.credits, r.spent), (8, 8));
    let w = World::load("mire", d.path()).unwrap();
    assert!(
        status(&w, &records(d.path()))
            .iter()
            .all(|s| s.state == State::Done)
    );
}

#[tokio::test]
async fn max_credits_refuses_before_anything_is_spent() {
    let server = MockServer::start().await;
    api(&server, 8, "succeeded").await;
    let d = theme();
    let opts = RunOptions {
        max_credits: Some(15),
        ..Default::default()
    };
    let err = plan_and_run(&server, d.path(), &[], &opts)
        .await
        .unwrap_err();
    assert!(
        matches!(
            err,
            Error::OverBudget {
                planned: 16,
                max: 15
            }
        ),
        "{err}"
    );
    let reqs = server.received_requests().await.unwrap();
    assert!(
        reqs.iter().all(|r| r.method.as_str() == "GET"),
        "something was sent"
    );
    assert!(!d.path().join("art.log.jsonl").exists());
}

#[tokio::test]
async fn a_quote_over_the_cap_stops_before_the_submit() {
    let server = MockServer::start().await;
    // The catalog says 8 a job, the server quotes 12: the second job would pass 16.
    api(&server, 12, "succeeded").await;
    let d = theme();
    let opts = RunOptions {
        max_credits: Some(16),
        ..Default::default()
    };
    let (_, r) = plan_and_run(&server, d.path(), &[], &opts).await.unwrap();
    assert!(!r.ok);
    assert_eq!(r.spent, 12);
    assert_eq!(r.ran.len(), 2);
    assert!(
        r.ran[1]
            .error
            .as_deref()
            .unwrap()
            .contains("over --max-credits 16")
    );
    let submits = server
        .received_requests()
        .await
        .unwrap()
        .iter()
        .filter(|r| r.url.path() == "/v1/generate/image")
        .count();
    assert_eq!(submits, 1);
}

#[tokio::test]
async fn a_failed_job_is_logged_with_its_refund_and_stops_the_run() {
    let server = MockServer::start().await;
    api(&server, 8, "failed").await;
    let d = theme();
    let (_, r) = plan_and_run(&server, d.path(), &[], &RunOptions::default())
        .await
        .unwrap();
    assert!(!r.ok);
    assert_eq!(r.ran.len(), 1);
    assert_eq!(r.ran[0].status, "failed");
    assert_eq!(r.spent, 0);
    let recs = records(d.path());
    assert_eq!(recs.last().unwrap().status, "failed");
    assert_eq!(recs.last().unwrap().credits, Some(0));
    assert!(
        recs.last()
            .unwrap()
            .error
            .as_deref()
            .unwrap()
            .contains("upstream 502")
    );
    // Not produced, so the next run tries again.
    let w = World::load("mire", d.path()).unwrap();
    assert_eq!(status(&w, &recs)[0].state, State::New);
}

#[tokio::test]
async fn a_job_left_running_is_waited_for_not_paid_twice() {
    let server = MockServer::start().await;
    api(&server, 8, "succeeded").await;
    let d = theme();
    let w = World::load("mire", d.path()).unwrap();
    let comp = w.get("comp").unwrap();
    let job = Uuid::new_v4();
    // An earlier run submitted it and was interrupted.
    log::append(
        &w.log_path(),
        &Record {
            schema: 1,
            t: "2026-10-08T02:00:00-07:00".into(),
            world: "mire".into(),
            asset: "comp".into(),
            version: 1,
            kind: "image".into(),
            spec: comp.spec.clone(),
            status: "submitted".into(),
            model: Some("flare".into()),
            prompt_sha256: comp.prompt_sha256(),
            credits: Some(8),
            planned: Some(8),
            job: Some(job.to_string()),
            outputs: vec![],
            inputs: Default::default(),
            seconds: Some(1),
            error: None,
            by: "test".into(),
            backend: None,
            license: None,
        },
    )
    .unwrap();
    Mock::given(method("GET"))
        .and(path(format!("/v1/jobs/{job}")))
        .respond_with(ResponseTemplate::new(200).set_body_json(job_value(job)))
        .mount(&server)
        .await;
    let (p, r) = plan_and_run(
        &server,
        d.path(),
        &["comp".to_string()],
        &RunOptions::default(),
    )
    .await
    .unwrap();
    assert_eq!(p.assets[0].state, State::Pending);
    assert_eq!(p.credits, 0);
    assert!(r.ok, "{r:?}");
    assert_eq!(r.spent, 0);
    let submits = server
        .received_requests()
        .await
        .unwrap()
        .iter()
        .filter(|r| r.url.path() == "/v1/generate/image")
        .count();
    assert_eq!(submits, 0);
    let recs = records(d.path());
    assert_eq!(recs.last().unwrap().status, "succeeded");
    assert_eq!(
        recs.last().unwrap().job.as_deref(),
        Some(job.to_string().as_str())
    );
    assert_eq!(log::spent(&recs), 8);
}

fn job_value(id: Uuid) -> Value {
    job(id, "running")
}
