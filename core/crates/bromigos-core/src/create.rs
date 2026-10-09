//! Creation tools for `bromigos setup create`: which ComfyUI servers this machine can
//! reach and what each can make, then which providers make each kind of art. It writes
//! `~/.config/bromigos/create.toml`, schema format 1 (docs/art.md, "Creation providers").
//!
//! Instances found, as the schema names them:
//! - `local`: this machine, `http://127.0.0.1:8188`;
//! - `homelab`: the homelab.toml `[[source]]` with `type = "comfyui"` (endpoint
//!   `@homelab:<its name>`), else `BROMIGOS_COMFYUI_URL` (`@env:BROMIGOS_COMFYUI_URL`);
//! - art.toml's `comfyui_url`: the instance whose URL it is, else `homelab` when that's free.
//!
//! Each is asked `/system_stats` (its GPU), `/models/<folder>` (its weights) and
//! `/object_info` (its nodes). A capability is offered on an instance only when a shipped
//! workflow for it has what it needs there ([`WORKFLOWS`]).

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::process::Command;

use serde::{Deserialize, Serialize};

use crate::paths::Paths;

pub const CAPABILITIES: &[&str] = &[
    "image.generate",
    "image.edit",
    "image.cutout",
    "image.upscale",
    "video.loop",
    "video.upscale",
    "model3d.generate",
];

/// nolgia's model per capability (docs/art.md).
pub const NOLGIA_MODELS: &[(&str, &str)] = &[
    ("image.generate", "gpt-image-2.5-flare"),
    ("image.edit", "gpt-image-2.5-flare"),
    ("image.cutout", "remove-background"),
    ("video.loop", "seedance-2.5"),
    ("model3d.generate", "trellis"),
];

/// A shipped workflow: its name, the capabilities it serves, and what an instance needs
/// for it (any of these, lowercased and without -_. , in a model file's or node's name).
pub struct Workflow {
    pub name: &'static str,
    pub caps: &'static [&'static str],
    pub needs: &'static [&'static str],
}

pub const WORKFLOWS: &[Workflow] = &[
    Workflow {
        name: "qwen-image-2.1",
        caps: &["image.generate", "image.edit"],
        needs: &["qwenimage21", "qwenimage2"],
    },
    // the native background-removal nodes' Lucida first, else BiRefNet (ComfyUI-RMBG)
    Workflow {
        name: "lucida",
        caps: &["image.cutout"],
        needs: &["lucida"],
    },
    Workflow {
        name: "birefnet",
        caps: &["image.cutout"],
        needs: &["birefnet", "rmbg"],
    },
    Workflow {
        name: "seedvr2-7b",
        caps: &["image.upscale"],
        needs: &["seedvr27b"],
    },
    Workflow {
        name: "seedvr2-7b-video",
        caps: &["video.upscale"],
        needs: &["seedvr27b"],
    },
    // Pixal3D (pixel-aligned geometry) before Hunyuan3D 2.1
    Workflow {
        name: "pixal3d",
        caps: &["model3d.generate"],
        needs: &["pixal3dint8", "pixal3dbf16"],
    },
    Workflow {
        name: "hunyuan3d-2.1",
        caps: &["model3d.generate"],
        needs: &["hunyuan3d21", "hy3d21", "hunyuan3dv21"],
    },
    Workflow {
        name: "trellis2",
        caps: &["model3d.generate"],
        needs: &["trellis2", "trellisv2"],
    },
    // Wan 2.2: the A14B's experts first (the better loop), else the TI2V-5B
    Workflow {
        name: "wan2.2-i2v-a14b",
        caps: &["video.loop"],
        needs: &["wan22i2vhighnoise14b"],
    },
    Workflow {
        name: "wan2.2-ti2v-5b",
        caps: &["video.loop"],
        needs: &["wan22ti2v5b"],
    },
];

/// One ComfyUI instance found.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Server {
    /// The instance name: provider `comfyui:<name>`.
    pub name: String,
    /// As create.toml records it (a URL or a reference).
    pub endpoint: String,
    /// Resolved, to ask it.
    pub url: String,
    /// Its GPU, from /system_stats (None: no GPU reported).
    pub gpu: Option<String>,
    /// capability -> the workflow that serves it there.
    pub caps: BTreeMap<String, String>,
}

fn norm(s: &str) -> String {
    s.to_ascii_lowercase()
        .replace(['-', '_', ' ', '.', '/'], "")
}

/// The capabilities an instance's weights and nodes allow: capability -> workflow.
pub fn capabilities(names: &[String]) -> BTreeMap<String, String> {
    let names: Vec<String> = names.iter().map(|n| norm(n)).collect();
    let mut caps = BTreeMap::new();
    for w in WORKFLOWS {
        if w.needs.iter().any(|n| names.iter().any(|x| x.contains(n))) {
            for c in w.caps {
                caps.entry(c.to_string())
                    .or_insert_with(|| w.name.to_string());
            }
        }
    }
    caps
}

/// GET `url` (3 s); None when it doesn't answer.
fn get(url: &str) -> Option<String> {
    let o = Command::new("curl")
        .args(["-fsS", "--max-time", "3", url])
        .output()
        .ok()?;
    o.status
        .success()
        .then(|| String::from_utf8_lossy(&o.stdout).into_owned())
}

/// Asks one instance what it has; None when it doesn't answer.
pub fn probe(name: &str, endpoint: &str, url: &str) -> Option<Server> {
    let base = url.trim_end_matches('/');
    let stats: serde_json::Value =
        serde_json::from_str(&get(&format!("{base}/system_stats"))?).ok()?;
    let gpu = stats["devices"]
        .as_array()
        .into_iter()
        .flatten()
        .find_map(|d| {
            let t = d["type"].as_str().unwrap_or("");
            (t != "cpu" && !t.is_empty()).then(|| d["name"].as_str().unwrap_or(t).to_string())
        });
    let mut names: Vec<String> = vec![];
    let folders: Vec<String> = get(&format!("{base}/models"))
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default();
    for f in &folders {
        let files: Vec<String> = get(&format!("{base}/models/{f}"))
            .and_then(|t| serde_json::from_str(&t).ok())
            .unwrap_or_default();
        names.extend(files);
    }
    if let Some(m) = get(&format!("{base}/object_info"))
        .and_then(|t| serde_json::from_str::<serde_json::Map<String, serde_json::Value>>(&t).ok())
    {
        names.extend(m.keys().cloned());
    }
    Some(Server {
        name: name.into(),
        endpoint: endpoint.into(),
        url: base.into(),
        gpu,
        caps: capabilities(&names),
    })
}

/// A reference's value (the ones setup can resolve: literal, @env:, @private:, @file:,
/// @homelab:). None for what it can't (@vault:, unknown).
pub fn resolve(paths: &Paths, r: &str, homelab: &BTreeMap<String, String>) -> Option<String> {
    if let Some(v) = r.strip_prefix("@env:") {
        return std::env::var(v).ok().filter(|s| !s.is_empty());
    }
    if let Some(key) = r.strip_prefix("@private:") {
        let p = paths.user_config_dir().join("private/config.json");
        let mut v: serde_json::Value = serde_json::from_str(&fs::read_to_string(p).ok()?).ok()?;
        for k in key.split('.') {
            v = v.get(k)?.clone();
        }
        return v.as_str().map(str::to_string);
    }
    if let Some(f) = r.strip_prefix("@file:") {
        let f = f
            .strip_prefix("~/")
            .map(|x| paths.home.join(x))
            .unwrap_or_else(|| PathBuf::from(f));
        return fs::read_to_string(f).ok().map(|s| s.trim().to_string());
    }
    if let Some(src) = r.strip_prefix("@homelab:") {
        let e = homelab.get(src)?;
        return if e.starts_with('@') {
            resolve(paths, e, &BTreeMap::new())
        } else {
            Some(e.clone())
        };
    }
    (!r.starts_with('@')).then(|| r.to_string())
}

/// homelab.toml's ComfyUI sources: name -> endpoint (as written).
pub fn homelab_comfyui(paths: &Paths) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    let Some(t) = fs::read_to_string(paths.user_config_dir().join("homelab.toml"))
        .ok()
        .and_then(|s| s.parse::<toml::Table>().ok())
    else {
        return out;
    };
    for s in t
        .get("source")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
    {
        if s.get("type").and_then(|v| v.as_str()) == Some("comfyui")
            && let (Some(n), Some(e)) = (
                s.get("name").and_then(|v| v.as_str()),
                s.get("endpoint").and_then(|v| v.as_str()),
            )
        {
            out.insert(n.to_string(), e.to_string());
        }
    }
    out
}

/// The instances to look at: (name, endpoint as recorded, resolved URL).
pub fn candidates(paths: &Paths) -> Vec<(String, String, String)> {
    let homelab = homelab_comfyui(paths);
    let mut out = vec![(
        "local".to_string(),
        "http://127.0.0.1:8188".to_string(),
        "http://127.0.0.1:8188".to_string(),
    )];
    if let Some((src, _)) = homelab.iter().next() {
        let r = format!("@homelab:{src}");
        if let Some(u) = resolve(paths, &r, &homelab) {
            out.push(("homelab".into(), r, u));
        }
    } else if let Some(u) = resolve(paths, "@env:BROMIGOS_COMFYUI_URL", &homelab) {
        out.push(("homelab".into(), "@env:BROMIGOS_COMFYUI_URL".into(), u));
    }
    let art = fs::read_to_string(paths.user_config_dir().join("art.toml"))
        .ok()
        .and_then(|s| s.parse::<toml::Table>().ok())
        .and_then(|t| {
            t.get("comfyui_url")
                .and_then(|v| v.as_str())
                .map(str::to_string)
        });
    if let Some(u) = art {
        let same = |a: &str, b: &str| a.trim_end_matches('/') == b.trim_end_matches('/');
        if !out.iter().any(|(_, _, x)| same(x, &u)) && !out.iter().any(|(n, _, _)| n == "homelab") {
            out.push(("homelab".into(), u.clone(), u));
        }
    }
    out
}

/// Every instance that answers.
pub fn detect(paths: &Paths) -> Vec<Server> {
    candidates(paths)
        .into_iter()
        .filter_map(|(n, e, u)| probe(&n, &e, &u))
        .collect()
}

/// The choices: capability -> providers in order (`comfyui:<name>`, `nolgia`, `none`), or
/// `["targets"]`: no list of its own, so it follows targets.toml (where AI work runs).
#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct CreateAnswer {
    pub providers: BTreeMap<String, Vec<String>>,
    /// Run `nolgia auth login` (interactive only).
    pub nolgia_login: bool,
    /// Unattended sign-in: a file holding a nolgia personal access token (`nol_…`). Its
    /// token is copied, never printed, to the file bromigos art reads
    /// (`$XDG_DATA_HOME/bromigos/nolgia-token`, mode 0600).
    pub nolgia_token_file: Option<String>,
}

pub fn create_toml(paths: &Paths) -> PathBuf {
    paths.user_config_dir().join("create.toml")
}

/// Checks a choice: known capabilities and providers, ComfyUI instances that answered
/// and have that capability's workflow.
pub fn validate(a: &CreateAnswer, servers: &[Server]) -> Result<(), String> {
    for (cap, provs) in &a.providers {
        if !CAPABILITIES.contains(&cap.as_str()) {
            return Err(format!(
                "unknown capability {cap:?} ({})",
                CAPABILITIES.join(", ")
            ));
        }
        if provs.len() == 1 && provs[0] == "targets" {
            continue;
        }
        for p in provs {
            match p.as_str() {
                "none" | "nolgia" => {}
                p if p.starts_with("comfyui:") => {
                    let name = &p["comfyui:".len()..];
                    let s = servers
                        .iter()
                        .find(|s| s.name == name)
                        .ok_or(format!("{cap}: no ComfyUI {name:?} answered"))?;
                    if !s.caps.contains_key(cap) {
                        return Err(format!(
                            "{cap}: ComfyUI {name} has no workflow's models for it"
                        ));
                    }
                }
                p => {
                    return Err(format!(
                        "{cap}: unknown provider {p:?} (comfyui:<name>, nolgia, none, or targets alone)"
                    ));
                }
            }
        }
    }
    Ok(())
}

/// nolgia's model for a capability, "" when it has none (upscaling).
pub fn nolgia_model(cap: &str) -> &'static str {
    NOLGIA_MODELS
        .iter()
        .find(|(c, _)| *c == cap)
        .map(|(_, m)| *m)
        .unwrap_or("")
}

/// create.toml with the answer applied, over the user's existing file (kept: their other
/// keys and comments).
pub fn create_toml_text(
    existing: &str,
    a: &CreateAnswer,
    servers: &[Server],
) -> Result<String, String> {
    use toml_edit::{Array, DocumentMut, Item, Table, value};
    let mut doc: DocumentMut = existing.parse().map_err(|e| format!("create.toml: {e}"))?;
    if existing.trim().is_empty() {
        doc.decor_mut().set_prefix("# What makes each kind of art (docs/art.md, \"Creation providers\").\n# `bromigos setup create` writes it; your other keys here are kept.\n");
    }
    doc["format"] = value(1);
    let used = |name: &str| {
        a.providers
            .values()
            .flatten()
            .any(|p| p == &format!("comfyui:{name}"))
    };
    for s in servers.iter().filter(|s| used(&s.name)) {
        if !doc.contains_table("comfyui") {
            let mut t = Table::new();
            t.set_implicit(true);
            doc["comfyui"] = Item::Table(t);
        }
        let c = doc["comfyui"]
            .as_table_mut()
            .ok_or("create.toml: comfyui isn't a table")?;
        if !c.contains_table(&s.name) {
            c[&s.name] = Item::Table(Table::new());
        }
        c[&s.name]["endpoint"] = value(s.endpoint.clone());
    }
    let any_nolgia = a.providers.values().flatten().any(|p| p == "nolgia");
    if any_nolgia || doc.contains_table("nolgia") {
        if !doc.contains_table("nolgia") {
            doc["nolgia"] = Item::Table(Table::new());
        }
        doc["nolgia"]["enabled"] = value(any_nolgia);
    }
    for (cap, provs) in &a.providers {
        let (group, leaf) = cap.split_once('.').ok_or("bad capability")?;
        if !doc.contains_table(group) {
            let mut t = Table::new();
            t.set_implicit(true);
            doc[group] = Item::Table(t);
        }
        let g = doc[group]
            .as_table_mut()
            .ok_or(format!("create.toml: {group} isn't a table"))?;
        if !g.contains_table(leaf) {
            g[leaf] = Item::Table(Table::new());
        }
        let t = &mut g[leaf];
        if provs.len() == 1 && provs[0] == "targets" {
            // follow targets.toml: no list of its own (its models stay)
            if let Some(tt) = t.as_table_mut() {
                tt.remove("providers");
            }
            continue;
        }
        let mut arr = Array::new();
        for p in provs {
            arr.push(p.as_str());
        }
        t["providers"] = value(arr);
        if let Some(wf) = provs
            .iter()
            .filter_map(|p| p.strip_prefix("comfyui:"))
            .find_map(|n| servers.iter().find(|s| s.name == n)?.caps.get(cap))
        {
            t["comfyui"] = value(wf.clone());
        }
        if provs.iter().any(|p| p == "nolgia") && !nolgia_model(cap).is_empty() {
            t["nolgia"] = value(nolgia_model(cap));
        }
    }
    Ok(doc.to_string())
}

/// The default per capability: follow targets.toml (where AI work runs), so
/// `bromigos target` moves the creation tools with everything else.
pub fn default_choice(_servers: &[Server], _nolgia: bool) -> CreateAnswer {
    CreateAnswer {
        providers: CAPABILITIES
            .iter()
            .map(|c| (c.to_string(), vec!["targets".to_string()]))
            .collect(),
        ..Default::default()
    }
}

/// A pinned choice per capability: a ComfyUI that can (this machine's first), then nolgia
/// when its CLI is here; nolgia alone; else none (the create pages' other options).
pub fn pinned_choice(servers: &[Server], nolgia: bool) -> CreateAnswer {
    let mut providers = BTreeMap::new();
    for cap in CAPABILITIES {
        let mut list: Vec<String> = vec![];
        if let Some(s) = servers
            .iter()
            .filter(|s| s.caps.contains_key(*cap))
            .min_by_key(|s| (s.name != "local") as u8)
        {
            list.push(format!("comfyui:{}", s.name));
        }
        // nolgia where it has a model for this (upscaling it hasn't)
        if nolgia && !nolgia_model(cap).is_empty() {
            list.push("nolgia".into());
        }
        if list.is_empty() {
            list.push("none".into());
        }
        providers.insert(cap.to_string(), list);
    }
    CreateAnswer {
        providers,
        nolgia_login: false,
        nolgia_token_file: None,
    }
}

pub fn write(paths: &Paths, text: &str) -> std::io::Result<()> {
    let p = create_toml(paths);
    if let Some(d) = p.parent() {
        fs::create_dir_all(d)?;
    }
    let tmp = p.with_extension("tmp");
    fs::write(&tmp, text)?;
    fs::rename(&tmp, &p)
}

/// Whether a nolgia CLI is here.
pub fn nolgia_installed() -> bool {
    Command::new("nolgia")
        .arg("--version")
        .output()
        .is_ok_and(|o| o.status.success())
}
