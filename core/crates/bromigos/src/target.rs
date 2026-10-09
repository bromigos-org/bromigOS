//! `bromigos target`: where AI work runs (docs/targets.md). Shows each service and the
//! target it would use right now (probed: a ComfyUI also for its workflow's model files
//! and nodes, and its VRAM), switches the order, and resolves one service for VECTOR
//! (`resolve SERVICE --json`, no probing: he asks every time it may change).

use anyhow::{Result, bail};
use bromigos_art::create::{Config, Provider};
use bromigos_art::targets::{self as tg, Entry, Probe, Target, Targets};
use bromigos_core::paths::Paths;
use bromigos_core::targets as tw;
use clap::Args;
use serde_json::{Value, json};

use crate::SCHEMA;

#[derive(Args, Debug)]
#[command(after_help = "\
Words:
  (none), show          each service, what it would use now, and whether that answers
  check                 every target of every service, probed
  probe [SERVICE…]      the same for these services (a ComfyUI: its workflow's models, its VRAM)
  homelab|local|cloud   put that target first (the cloud is never added by another one)
  order T [T…]          the exact order, e.g. `order homelab local`
  reset                 services follow the global order again
  resolve SERVICE       what SERVICE tries, in order (JSON; for VECTOR; no probing)

Services: image.generate image.edit image.cutout image.upscale video.loop video.upscale
model3d.generate voice.tts voice.stt llm. Your file: ~/.config/bromigos/targets.toml (docs/targets.md).")]
pub struct TargetArgs {
    /// show, check, probe [SERVICE…], homelab, local, cloud, order T…, reset, resolve SERVICE
    words: Vec<String>,
    /// Only these services (repeat), for homelab|local|cloud, order and reset
    #[arg(long = "only", value_name = "SERVICE")]
    only: Vec<String>,
    /// With homelab|local|cloud: that target alone, no fallback
    #[arg(long)]
    exclusive: bool,
    /// Print the JSON document
    #[arg(long)]
    json: bool,
}

/// What `service` tries, in order: creation services through create.toml (its own
/// lists win; otherwise the targets), the rest straight from the targets.
fn entries(cfg: &Config, t: &Targets, service: &str) -> Result<Vec<Entry>> {
    let Some(cap) = bromigos_art::create::Capability::parse(service) else {
        return Ok(t.entries(service)?);
    };
    let mut out = vec![];
    for c in cfg.candidates(cap)? {
        let id = c.provider.id();
        let (target, endpoint) = match &c.provider {
            Provider::Comfyui(n) => (Target::of_provider(&id), cfg.comfyui_endpoint(n).ok()),
            _ => (Some(Target::Cloud), None),
        };
        let workflow = matches!(c.provider, Provider::Comfyui(_)).then(|| c.model.clone());
        out.push(Entry {
            // another named ComfyUI from create.toml: shown under the homelab's flag
            target: target.unwrap_or(Target::Homelab),
            engine: format!("{id} ({})", c.model),
            endpoint,
            key_file: None,
            workflow,
        });
    }
    Ok(out)
}

fn engine_id(e: &Entry) -> &str {
    e.engine.split(' ').next().unwrap_or(&e.engine)
}

/// Probes every entry once (in parallel), in the order given.
fn probe_all(all: &[Entry]) -> Vec<Probe> {
    let bare: Vec<Entry> = all
        .iter()
        .map(|e| Entry {
            engine: engine_id(e).to_string(),
            ..e.clone()
        })
        .collect();
    tg::probe_many(&bare)
}

fn order_str(o: &[Target]) -> String {
    o.iter().map(|t| t.as_str()).collect::<Vec<_>>().join(" → ")
}

fn show(paths: &Paths, all_entries: bool, as_json: bool, only: &[&str]) -> Result<i32> {
    let cfg = Config::load()?;
    let t = cfg.targets().clone();
    if let Some(s) = only.iter().find(|s| !tg::is_service(s)) {
        bail!("unknown service {s:?} ({})", tg::SERVICES.join(", "));
    }
    let mut rows: Vec<(String, Vec<Target>, Vec<Entry>)> = vec![];
    for s in tg::SERVICES {
        if only.is_empty() || only.contains(&s) {
            rows.push((s.to_string(), t.order(s)?, entries(&cfg, &t, s)?));
        }
    }
    let flat: Vec<Entry> = rows.iter().flat_map(|r| r.2.clone()).collect();
    let probes = probe_all(&flat);
    let mut i = 0;
    let mut doc = vec![];
    let file = tw::user_path(paths);
    if !as_json {
        println!(
            "order: {}   ({})",
            order_str(&t.global_order()?),
            if t.user {
                file.display().to_string()
            } else {
                "the default: no targets.toml of yours yet".into()
            }
        );
        println!();
    }
    for (s, order, es) in &rows {
        let ps = &probes[i..i + es.len()];
        i += es.len();
        let used = ps.iter().position(|p| p.ok);
        let own = t.service_order(s).is_some();
        if as_json {
            doc.push(json!({
                "service": s,
                "order": order.iter().map(|x| x.as_str()).collect::<Vec<_>>(),
                "own_order": own,
                "uses": used.map(|u| json!({"target": es[u].target, "engine": es[u].engine})),
                "entries": es.iter().zip(ps).map(|(e, p)| json!({
                    "target": e.target, "engine": e.engine, "ok": p.ok, "detail": p.detail,
                })).collect::<Vec<_>>(),
            }));
            continue;
        }
        let head = match used {
            Some(u) => format!("{:<9} {}", es[u].target.as_str(), es[u].engine),
            None if es.is_empty() => "—         nothing configured in its targets".into(),
            None => "—         nothing answers".into(),
        };
        let note = match used {
            Some(u) => ps[u].detail.clone(),
            None => es
                .first()
                .zip(ps.first())
                .map(|(e, p)| format!("{}: {}", e.target, p.detail))
                .unwrap_or_default(),
        };
        println!(
            "  {:<17} {:<44} {}{}",
            s,
            head,
            note,
            if own {
                format!("   [own order: {}]", order_str(order))
            } else {
                String::new()
            }
        );
        if all_entries {
            for (e, p) in es.iter().zip(ps) {
                println!(
                    "      {} {:<8} {:<34} {}",
                    if p.ok { "ok " } else { "no " },
                    e.target.as_str(),
                    e.engine,
                    p.detail
                );
            }
        }
    }
    if as_json {
        println!(
            "{}",
            json!({
                "schema": SCHEMA,
                "file": file,
                "yours": t.user,
                "order": t.global_order()?.iter().map(|x| x.as_str()).collect::<Vec<_>>(),
                "services": doc,
            })
        );
    } else if !t.user {
        println!(
            "\nVECTOR's voice and brain follow targets.toml once you have one (bromigos target homelab|local|cloud\nwrites it); until then his voice.json and vector.toml decide."
        );
    }
    Ok(0)
}

fn resolve(service: &str) -> Result<i32> {
    let cfg = Config::load()?;
    let t = cfg.targets();
    if !tg::is_service(service) {
        bail!("unknown service {service:?} ({})", tg::SERVICES.join(", "));
    }
    let es = entries(&cfg, t, service)?;
    println!(
        "{}",
        json!({
            "schema": SCHEMA,
            "service": service,
            "configured": t.user,
            "order": t.order(service)?.iter().map(|x| x.as_str()).collect::<Vec<_>>(),
            "entries": es.iter().map(|e| {
                let mut v = serde_json::to_value(e).unwrap_or(Value::Null);
                v["engine"] = json!(engine_id(e));
                v
            }).collect::<Vec<_>>(),
        })
    );
    Ok(0)
}

fn write(paths: &Paths, text: &str) -> Result<()> {
    tw::write(paths, text).map_err(|e| anyhow::anyhow!("{}: {e}", tw::user_path(paths).display()))
}

fn existing(paths: &Paths) -> String {
    std::fs::read_to_string(tw::user_path(paths)).unwrap_or_default()
}

pub fn target_cmd(paths: &Paths, a: TargetArgs) -> Result<i32> {
    let words: Vec<&str> = a.words.iter().map(String::as_str).collect();
    match words.as_slice() {
        [] | ["show"] => show(paths, false, a.json, &[]),
        ["check"] => {
            let r = show(paths, true, a.json, &[])?;
            if !a.json {
                catalog_note();
            }
            Ok(r)
        }
        ["probe", services @ ..] => {
            let r = show(paths, true, a.json, services)?;
            if !a.json {
                catalog_note();
            }
            Ok(r)
        }
        ["resolve", s] => resolve(s),
        ["resolve"] => bail!("resolve which service? ({})", tg::SERVICES.join(", ")),
        ["reset"] => {
            write(
                paths,
                &tw::without_overrides(&existing(paths), &a.only).map_err(anyhow::Error::msg)?,
            )?;
            after(paths, a.json)
        }
        ["order", rest @ ..] => {
            let order: Vec<String> = rest.iter().map(|s| s.to_string()).collect();
            write(
                paths,
                &tw::with_order(&existing(paths), &order, &a.only).map_err(anyhow::Error::msg)?,
            )?;
            after(paths, a.json)
        }
        [first] if Target::parse(first).is_some() => {
            let t = Targets::load()?;
            let mut text = existing(paths);
            if a.only.is_empty() {
                let cur: Vec<String> = t.global_order()?.iter().map(|x| x.to_string()).collect();
                let order = tw::with_first(&cur, first, a.exclusive);
                text = tw::with_order(&text, &order, &[]).map_err(anyhow::Error::msg)?;
            } else {
                for s in &a.only {
                    let cur: Vec<String> = t.order(s)?.iter().map(|x| x.to_string()).collect();
                    let order = tw::with_first(&cur, first, a.exclusive);
                    text = tw::with_order(&text, &order, std::slice::from_ref(s))
                        .map_err(anyhow::Error::msg)?;
                }
            }
            write(paths, &text)?;
            after(paths, a.json)
        }
        _ => bail!(
            "bromigos target [show|check|probe [SERVICE…]|homelab|local|cloud|order T…|reset|resolve SERVICE] (see --help)"
        ),
    }
}

/// After a switch: what's in force now, and who picks it up when.
fn after(paths: &Paths, as_json: bool) -> Result<i32> {
    let r = show(paths, false, as_json, &[])?;
    if !as_json {
        println!(
            "\nIn force now: bromigos art reads it on every run, VECTOR's voice on his next line and his\nbrain on his next turn; nothing needs a restart."
        );
    }
    Ok(r)
}

/// Under `check` and `probe`: the lab model catalog's upgrades, when a better model would fit
/// one of the lab's GPUs (`bromigos lab models recommend --json`, docs/lab-models.md). Quiet
/// when the catalog isn't installed, there's no lab, or it doesn't answer within 25 s.
fn catalog_note() {
    use std::io::Read;
    use std::process::{Command, Stdio};
    use std::time::{Duration, Instant};
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    let Ok(mut child) = Command::new(exe)
        .args(["lab", "models", "recommend", "--json"])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    else {
        return;
    };
    // read on a thread: the document can be bigger than a pipe holds
    let mut out = child.stdout.take();
    let reader = std::thread::spawn(move || {
        let mut s = String::new();
        if let Some(o) = out.as_mut() {
            let _ = o.read_to_string(&mut s);
        }
        s
    });
    let deadline = Instant::now() + Duration::from_secs(25);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(100)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return;
            }
        }
    }
    let Ok(text) = reader.join() else {
        return;
    };
    let Ok(doc) = serde_json::from_str::<Value>(&text) else {
        return;
    };
    let ups = doc["upgrades"].as_array().cloned().unwrap_or_default();
    if ups.is_empty() {
        return;
    }
    println!("\nA better model would fit (bromigos lab models recommend; docs/lab-models.md):");
    for u in ups {
        println!(
            "  {} {}: {} -> {} (+{} quality, {} GiB, {})",
            u["device"].as_str().unwrap_or("?"),
            u["capability"].as_str().unwrap_or("?"),
            u["from"].as_str().unwrap_or("?"),
            u["to"].as_str().unwrap_or("?"),
            u["gain"],
            u["vram_gib"],
            u["licence_plain"].as_str().unwrap_or("")
        );
    }
}
