//! `targets.toml`: where bromigOS's AI work runs (docs/targets.md). Three targets,
//! `homelab`, `local` and `cloud`, and the services that pick among them: the five
//! creation capabilities (create.toml's), VECTOR's voice (`voice.tts`, `voice.stt`) and
//! his brain (`llm`). A service tries its targets in order (`[targets] order`, or the
//! service's own `[service."<name>"] order`), skipping a target that doesn't have it.
//!
//! Files, merged key by key: the packaged default
//! (`$BROMIGOS_SHARE_DIR/default/targets.toml`, else the copy built into this crate),
//! then the user's (`$XDG_CONFIG_HOME/bromigos/targets.toml`), which
//! `$BROMIGOS_TARGETS_CONFIG` replaces. Endpoints are URLs or references, resolved as in
//! create.toml ([`crate::create::resolve`]), so the file can sit in a public repo.
//!
//! The resolver only says what is configured, in order. Whether a target answers is
//! [`probe`]'s job (and each caller's: `bromigos art make` moves on from a ComfyUI that
//! doesn't answer; VECTOR's voice server from a lab that doesn't).

use std::path::PathBuf;
use std::time::Duration;

use serde::Serialize;
use toml::{Table, Value};

use crate::Error;
use crate::create::{self, Capability};

/// The packaged default, built in for a checkout or a machine without the share dir.
pub const DEFAULT: &str = include_str!("../targets.default.toml");

/// Where work runs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Target {
    Homelab,
    Local,
    Cloud,
}

impl Target {
    pub const ALL: [Target; 3] = [Target::Homelab, Target::Local, Target::Cloud];

    pub fn as_str(self) -> &'static str {
        match self {
            Target::Homelab => "homelab",
            Target::Local => "local",
            Target::Cloud => "cloud",
        }
    }

    pub fn parse(s: &str) -> Option<Target> {
        Self::ALL.into_iter().find(|t| t.as_str() == s)
    }

    /// The target a creation provider id belongs to: `comfyui:homelab` and
    /// `comfyui:local` are theirs, `nolgia` is the cloud; another named ComfyUI has none.
    pub fn of_provider(id: &str) -> Option<Target> {
        match id {
            "nolgia" => Some(Target::Cloud),
            _ => Target::parse(id.strip_prefix("comfyui:")?).filter(|t| *t != Target::Cloud),
        }
    }
}

impl std::fmt::Display for Target {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Every service, in display order.
pub const SERVICES: [&str; 10] = [
    "image.generate",
    "image.edit",
    "image.cutout",
    "image.upscale",
    "video.loop",
    "video.upscale",
    "model3d.generate",
    "voice.tts",
    "voice.stt",
    "llm",
];

pub fn is_service(s: &str) -> bool {
    SERVICES.contains(&s)
}

/// One way a service can run: a target, what runs there (a creation provider id such
/// as `comfyui:homelab` or `nolgia`; a voice engine `lab`, `qwen`, `kokoro`, `local`;
/// `openai` for the brain), and its address when it has one.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Entry {
    pub target: Target,
    pub engine: String,
    /// Resolved; `None` for what runs in-process (local voice, nolgia).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub endpoint: Option<String>,
    /// The API key's file (a path, never the key), for the brain.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key_file: Option<String>,
    /// The workflow a ComfyUI runs for a creation service (its model files are checked
    /// when probed).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub workflow: Option<String>,
}

/// The merged `targets.toml`.
#[derive(Debug, Clone)]
pub struct Targets {
    table: Table,
    /// The files read, in order (for messages).
    pub files: Vec<PathBuf>,
    /// Whether the user has a targets.toml of their own (VECTOR follows targets only then;
    /// without one, his voice.json and vector.toml decide, as before).
    pub user: bool,
}

/// The user's `targets.toml` (where `bromigos target` and setup write).
pub fn user_path() -> PathBuf {
    std::env::var_os("BROMIGOS_TARGETS_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|| create::config_home().join("bromigos/targets.toml"))
}

fn parse(text: &str, what: &str) -> Result<Table, Error> {
    let t: Table = toml::from_str(text).map_err(|e| Error::Spec(format!("{what}: {e}")))?;
    match t.get("format").and_then(Value::as_integer) {
        None | Some(1) => Ok(t),
        Some(n) => Err(Error::Spec(format!(
            "{what}: format {n} is newer than this bromigos (it reads format 1)"
        ))),
    }
}

/// An OpenAI-compatible base URL with `/v1` when it has no path (a LiteLLM's bare host).
fn with_v1(url: &str) -> String {
    let u = url.trim_end_matches('/');
    let path = u.split_once("://").map_or(u, |(_, rest)| rest);
    if path.contains('/') {
        u.to_string()
    } else {
        format!("{u}/v1")
    }
}

fn expand(p: &str) -> String {
    match p.strip_prefix("~/") {
        Some(rest) => std::env::var_os("HOME")
            .map(|h| PathBuf::from(h).join(rest).display().to_string())
            .unwrap_or_else(|| p.to_string()),
        None => p.to_string(),
    }
}

impl Targets {
    /// The packaged default, then the user's file.
    pub fn load() -> Result<Targets, Error> {
        let mut files = Vec::new();
        let share = create::share_dir().join("default/targets.toml");
        let mut table = match std::fs::read_to_string(&share) {
            Ok(t) => {
                files.push(share.clone());
                parse(&t, &share.display().to_string())?
            }
            Err(_) => parse(DEFAULT, "the built-in targets.toml")?,
        };
        let path = user_path();
        let user = match std::fs::read_to_string(&path) {
            Ok(t) => {
                create::merge(&mut table, parse(&t, &path.display().to_string())?);
                files.push(path);
                true
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => false,
            Err(e) => return Err(Error::io(&path, e)),
        };
        Ok(Targets { table, files, user })
    }

    /// Targets from text over the built-in default (tests).
    pub fn from_toml(text: &str) -> Result<Targets, Error> {
        let mut table = parse(DEFAULT, "the built-in targets.toml")?;
        create::merge(&mut table, parse(text, "targets.toml")?);
        Ok(Targets {
            table,
            files: Vec::new(),
            user: !text.trim().is_empty(),
        })
    }

    fn order_in(t: Option<&Table>) -> Option<Result<Vec<Target>, Error>> {
        let a = t?.get("order")?;
        Some(match a.as_array() {
            None => Err(Error::Spec("targets.toml: order must be a list".into())),
            Some(a) => a
                .iter()
                .map(|v| {
                    v.as_str().and_then(Target::parse).ok_or_else(|| {
                        Error::Spec(format!(
                            "targets.toml: {v} is not a target (homelab, local or cloud)"
                        ))
                    })
                })
                .collect(),
        })
    }

    /// The order everything uses unless a service has its own.
    pub fn global_order(&self) -> Result<Vec<Target>, Error> {
        Self::order_in(self.table.get("targets").and_then(Value::as_table))
            .unwrap_or_else(|| Ok(Target::ALL.to_vec()))
    }

    /// The service's own order, when it has one.
    pub fn service_order(&self, service: &str) -> Option<Result<Vec<Target>, Error>> {
        Self::order_in(
            self.table
                .get("service")
                .and_then(Value::as_table)
                .and_then(|s| s.get(service))
                .and_then(Value::as_table),
        )
    }

    /// The targets `service` tries, in order.
    pub fn order(&self, service: &str) -> Result<Vec<Target>, Error> {
        self.service_order(service)
            .unwrap_or_else(|| self.global_order())
    }

    /// A target's setting, as written (a URL, a reference, a word).
    pub fn field(&self, target: Target, key: &str) -> Option<&Value> {
        self.table
            .get("targets")?
            .as_table()?
            .get(target.as_str())?
            .as_table()?
            .get(key)
    }

    fn str_field(&self, target: Target, key: &str) -> Option<&str> {
        self.field(target, key)
            .and_then(Value::as_str)
            .filter(|s| !s.trim().is_empty())
    }

    /// A target's address for `key`, references resolved; `None` when unset or it
    /// doesn't resolve.
    pub fn endpoint(&self, target: Target, key: &str) -> Option<String> {
        let r = self.str_field(target, key)?;
        let url = create::resolve(r);
        let url = url.trim().trim_end_matches('/');
        (!url.is_empty()).then(|| url.to_string())
    }

    /// What each of the service's targets offers, in order. A target without the
    /// service (no address set, an address that doesn't resolve, nolgia off) is left out.
    pub fn entries(&self, service: &str) -> Result<Vec<Entry>, Error> {
        if !is_service(service) {
            return Err(Error::Spec(format!(
                "unknown service {service:?} ({})",
                SERVICES.join(", ")
            )));
        }
        let mut out = Vec::new();
        for t in self.order(service)? {
            out.extend(self.offers(t, service));
        }
        Ok(out)
    }

    fn offers(&self, t: Target, service: &str) -> Vec<Entry> {
        let e = |engine: &str, endpoint: Option<String>| Entry {
            target: t,
            engine: engine.to_string(),
            endpoint,
            key_file: None,
            workflow: None,
        };
        if let Some(cap) = Capability::parse(service) {
            return match t {
                // upscaling has no cloud model: a ComfyUI's only
                Target::Cloud
                    if matches!(cap, Capability::ImageUpscale | Capability::VideoUpscale) =>
                {
                    vec![]
                }
                Target::Cloud => {
                    if self
                        .field(t, "nolgia")
                        .and_then(Value::as_bool)
                        .unwrap_or(false)
                    {
                        vec![e("nolgia", None)]
                    } else {
                        vec![]
                    }
                }
                _ => self
                    .endpoint(t, "comfyui")
                    .map(|u| vec![e(&format!("comfyui:{t}"), Some(u))])
                    .unwrap_or_default(),
            };
        }
        match (service, t) {
            ("voice.tts" | "voice.stt", Target::Homelab) => self
                .endpoint(t, "voice")
                .map(|u| vec![e("lab", Some(u))])
                .unwrap_or_default(),
            ("voice.tts", Target::Local) => match self.str_field(t, "voice") {
                Some("builtin") => vec![e("qwen", None), e("kokoro", None)],
                Some("kokoro") => vec![e("kokoro", None)],
                _ => vec![],
            },
            ("voice.stt", Target::Local) => match self.str_field(t, "voice") {
                Some("builtin" | "kokoro") => vec![e("local", None)],
                _ => vec![],
            },
            ("llm", _) => self
                .endpoint(t, "llm")
                .map(|u| {
                    let mut x = e("openai", Some(with_v1(&u)));
                    x.key_file = self.str_field(t, "llm_key_file").map(expand);
                    vec![x]
                })
                .unwrap_or_default(),
            _ => vec![],
        }
    }

    /// The creation providers a capability gets from the targets (create.toml uses them
    /// when a capability lists no providers of its own).
    pub fn providers(&self, cap: Capability) -> Result<Vec<String>, Error> {
        Ok(self
            .entries(cap.as_str())?
            .into_iter()
            .map(|e| e.engine)
            .collect())
    }

    /// The ComfyUI endpoint a target names, for `comfyui:homelab` / `comfyui:local` when
    /// create.toml has no table of that name.
    pub fn comfyui(&self, name: &str) -> Option<String> {
        match Target::parse(name)? {
            Target::Cloud => None,
            t => self.endpoint(t, "comfyui"),
        }
    }
}

// ------------------------------------------------------------------ probing

/// Whether an entry answers, and what it said.
#[derive(Debug, Clone, Serialize)]
pub struct Probe {
    pub ok: bool,
    pub detail: String,
}

fn ok(detail: impl Into<String>) -> Probe {
    Probe {
        ok: true,
        detail: detail.into(),
    }
}

fn no(detail: impl Into<String>) -> Probe {
    Probe {
        ok: false,
        detail: detail.into(),
    }
}

/// The lab voice service's base URL (an older Breeze-style address loses its path).
fn voice_base(url: &str) -> String {
    let mut u = url.trim_end_matches('/').to_string();
    for tail in ["/v1/audio/speech", "/v1/tts/stream", "/health"] {
        if let Some(s) = u.strip_suffix(tail) {
            u = s.to_string();
        }
    }
    u
}

/// Asks the entry's service whether it's there (a few seconds at most; the address is
/// never part of the answer).
pub async fn probe(client: &reqwest::Client, e: &Entry) -> Probe {
    let quick = Duration::from_secs(3);
    let get = |url: String| client.get(url).timeout(quick).send();
    match (e.engine.as_str(), e.endpoint.as_deref()) {
        (eng, Some(u)) if eng.starts_with("comfyui:") => {
            // with a workflow: whether this ComfyUI has its model files and nodes too
            let w = e.workflow.as_deref().map(crate::comfy::workflow);
            match w {
                Some(Ok(w)) => match crate::comfy::missing(client, u, &w).await {
                    Ok(m) => {
                        let line = format!(
                            "ComfyUI {}, {:.1} of {:.1} GiB VRAM free; {}",
                            m.version,
                            m.vram_free_gib,
                            m.vram_total_gib,
                            m.describe(&w)
                        );
                        if m.ready() && m.fits(&w) {
                            ok(line)
                        } else {
                            no(line)
                        }
                    }
                    Err(err) => no(format!("doesn't answer ({err})")),
                },
                Some(Err(err)) => no(err),
                None => match crate::comfy::probe(client, u).await {
                    Ok((v, free)) => ok(format!("ComfyUI {v}, {free:.1} GiB VRAM free")),
                    Err(err) => no(format!("doesn't answer ({err})")),
                },
            }
        }
        ("lab", Some(u)) => match get(format!("{}/health", voice_base(u))).await {
            Ok(r) if r.status().is_success() => ok("the lab's voice service answers"),
            Ok(r) => no(format!("HTTP {}", r.status().as_u16())),
            Err(err) => no(format!("doesn't answer ({})", err.without_url())),
        },
        ("openai", Some(u)) => match get(format!("{u}/models")).await {
            // a 401 is still a server there (the key is VECTOR's, never sent from here)
            Ok(r) if r.status().as_u16() < 500 => ok(format!(
                "an OpenAI-compatible server answers (HTTP {})",
                r.status().as_u16()
            )),
            Ok(r) => no(format!("HTTP {}", r.status().as_u16())),
            Err(err) => no(format!("doesn't answer ({})", err.without_url())),
        },
        ("nolgia", _) => match crate::auth::source() {
            Some(s) => ok(format!("signed in ({}); it costs credits", s.describe())),
            None => no("not signed in (nolgia auth login)"),
        },
        ("qwen", _) => {
            let venv = std::env::var_os("HOME")
                .map(|h| PathBuf::from(h).join(".local/share/bromigos/venv-tts"));
            if venv.is_some_and(|v| v.exists()) {
                ok("VECTOR's cast voice on this machine's GPU (loads when used)")
            } else {
                no("not built (bromigos-holo setup voice)")
            }
        }
        ("kokoro", _) => ok("Kokoro on this machine's CPU"),
        ("local", _) => ok("Whisper on this machine"),
        _ => no("nothing to ask"),
    }
}

/// Probes every entry (in parallel, a few seconds at most), answers in the same order.
pub fn probe_many(entries: &[Entry]) -> Vec<Probe> {
    let rt = match nolgia::tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => {
            return entries
                .iter()
                .map(|_| no(format!("no runtime: {e}")))
                .collect();
        }
    };
    let client = match crate::comfy::client() {
        Ok(c) => c,
        Err(e) => return entries.iter().map(|_| no(e.to_string())).collect(),
    };
    rt.block_on(async {
        let hs: Vec<_> = entries
            .iter()
            .map(|e| {
                let (c, e) = (client.clone(), e.clone());
                nolgia::tokio::spawn(async move { probe(&c, &e).await })
            })
            .collect();
        let mut out = Vec::with_capacity(hs.len());
        for h in hs {
            out.push(h.await.unwrap_or_else(|_| no("probe failed")));
        }
        out
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// No homelab: its references blanked, so no test depends on this machine's files.
    pub(crate) const NO_HOMELAB: &str =
        "[targets.homelab]\ncomfyui = \"\"\nvoice = \"\"\nllm = \"\"\n";

    #[test]
    fn the_default_order_and_what_each_target_offers() {
        let t = Targets::from_toml(NO_HOMELAB).unwrap();
        assert_eq!(t.global_order().unwrap(), Target::ALL.to_vec());
        // no homelab sources: the homelab offers nothing; this machine's ComfyUI, then nolgia
        let e = t.entries("image.cutout").unwrap();
        assert_eq!(
            e.iter().map(|x| x.engine.as_str()).collect::<Vec<_>>(),
            ["comfyui:local", "nolgia"]
        );
        assert_eq!(e[0].endpoint.as_deref(), Some("http://127.0.0.1:8188"));
        let v = t.entries("voice.tts").unwrap();
        assert_eq!(
            v.iter().map(|x| x.engine.as_str()).collect::<Vec<_>>(),
            ["qwen", "kokoro"]
        );
        let l = t.entries("llm").unwrap();
        assert_eq!(l.len(), 1);
        assert_eq!(l[0].endpoint.as_deref(), Some("http://localhost:11434/v1"));
        assert!(t.entries("nope").is_err());
    }

    #[test]
    fn orders_overrides_and_the_cloud_only_when_listed() {
        let t = Targets::from_toml(
            r#"
            [targets]
            order = ["homelab", "local"]
            [targets.homelab]
            comfyui = "http://lab:8188"
            voice = "https://tts.lab/v1/audio/speech"
            llm = "https://litellm.lab"
            [service."video.loop"]
            order = ["homelab", "local", "cloud"]
            "#,
        )
        .unwrap();
        let ids = |s: &str| {
            t.entries(s)
                .unwrap()
                .into_iter()
                .map(|e| e.engine)
                .collect::<Vec<_>>()
        };
        assert_eq!(ids("image.generate"), ["comfyui:homelab", "comfyui:local"]);
        assert_eq!(
            ids("video.loop"),
            ["comfyui:homelab", "comfyui:local", "nolgia"]
        );
        assert_eq!(ids("voice.tts"), ["lab", "qwen", "kokoro"]);
        assert_eq!(ids("voice.stt"), ["lab", "local"]);
        let llm = t.entries("llm").unwrap();
        assert_eq!(llm[0].endpoint.as_deref(), Some("https://litellm.lab/v1"));
        assert_eq!(
            llm[1].endpoint.as_deref(),
            Some("http://localhost:11434/v1")
        );
        assert_eq!(
            t.providers(Capability::ImageCutout).unwrap(),
            ["comfyui:homelab", "comfyui:local"]
        );
        assert_eq!(t.comfyui("homelab").as_deref(), Some("http://lab:8188"));
        assert!(
            Targets::from_toml("[targets]\norder = [\"moon\"]\n")
                .unwrap()
                .global_order()
                .is_err()
        );
    }

    #[test]
    fn local_voice_off_and_nolgia_off() {
        let t = Targets::from_toml(
            "[targets.homelab]\ncomfyui = \"\"\nvoice = \"\"\nllm = \"\"\n[targets.local]\nvoice = \"off\"\n[targets.cloud]\nnolgia = false\n",
        )
        .unwrap();
        assert!(t.entries("voice.tts").unwrap().is_empty());
        assert!(
            !t.entries("image.edit")
                .unwrap()
                .iter()
                .any(|e| e.engine == "nolgia")
        );
    }

    #[test]
    fn helpers() {
        assert_eq!(with_v1("https://x.lab"), "https://x.lab/v1");
        assert_eq!(
            with_v1("http://localhost:11434/v1/"),
            "http://localhost:11434/v1"
        );
        assert_eq!(
            voice_base("https://tts.lab/v1/audio/speech"),
            "https://tts.lab"
        );
        assert_eq!(
            Target::of_provider("comfyui:homelab"),
            Some(Target::Homelab)
        );
        assert_eq!(Target::of_provider("nolgia"), Some(Target::Cloud));
        assert_eq!(Target::of_provider("comfyui:studio"), None);
    }
}
