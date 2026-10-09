//! `create.toml`: which provider makes each kind of art (docs/art.md, "Creation
//! providers"). Seven capabilities, each with an ordered list of providers: a
//! ComfyUI instance (`comfyui:<name>`, a `[comfyui.<name>]` table), `nolgia`, or
//! `none`. The first provider that is configured and reachable makes the job.
//!
//! A capability that lists no providers follows `targets.toml` (docs/targets.md,
//! [`crate::targets`]): its targets in order, `homelab` and `local` as the ComfyUIs
//! `comfyui:homelab` and `comfyui:local` (their endpoints from targets.toml unless a
//! `[comfyui.<name>]` table here says otherwise), `cloud` as nolgia. The packaged
//! default lists none, so `bromigos target` moves everything; a list here wins.
//!
//! Files, merged key by key (the later wins): the packaged default
//! (`$BROMIGOS_SHARE_DIR/default/create.toml`, else the copy built into this
//! crate), then the user's (`$XDG_CONFIG_HOME/bromigos/create.toml`), which
//! `$BROMIGOS_CREATE_CONFIG` replaces.
//!
//! Endpoints are a URL or a reference, as in `homelab.toml`, so the file can sit
//! in a public repo: `@env:NAME`, `@private:dotted.key` (the private overlay's
//! `config.json`), `@file:~/path`, `@vault:kv/path#field`, and
//! `@homelab:<source>` (the endpoint of that `homelab.toml` `[[source]]`).

use std::path::{Path, PathBuf};

use toml::{Table, Value};

use crate::Error;
use crate::spec::Kind;
use crate::targets::Targets;

/// The packaged default, built in for a checkout or a machine without the share dir.
pub const DEFAULT: &str = include_str!("../create.default.toml");

/// What can be made.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Capability {
    ImageGenerate,
    ImageEdit,
    ImageCutout,
    VideoLoop,
    Model3dGenerate,
    /// An image made larger and sharper (an `upscale` asset with a .png out).
    ImageUpscale,
    /// A video clip made larger and sharper (an `upscale` asset with an .mp4 out).
    VideoUpscale,
}

impl Capability {
    pub const ALL: [Capability; 7] = [
        Capability::ImageGenerate,
        Capability::ImageEdit,
        Capability::ImageCutout,
        Capability::ImageUpscale,
        Capability::VideoLoop,
        Capability::VideoUpscale,
        Capability::Model3dGenerate,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Capability::ImageGenerate => "image.generate",
            Capability::ImageEdit => "image.edit",
            Capability::ImageCutout => "image.cutout",
            Capability::VideoLoop => "video.loop",
            Capability::Model3dGenerate => "model3d.generate",
            Capability::ImageUpscale => "image.upscale",
            Capability::VideoUpscale => "video.upscale",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|c| c.as_str() == s)
    }

    /// The capability an asset of `kind` needs (a local command needs none). An
    /// upscale's is the image one here: [`Capability::for_asset`] tells a clip's.
    pub fn of(kind: Kind) -> Option<Self> {
        match kind {
            Kind::Image => Some(Capability::ImageGenerate),
            Kind::Edit => Some(Capability::ImageEdit),
            Kind::Cutout => Some(Capability::ImageCutout),
            Kind::Video => Some(Capability::VideoLoop),
            Kind::Model3d => Some(Capability::Model3dGenerate),
            Kind::Upscale => Some(Capability::ImageUpscale),
            Kind::Command => None,
        }
    }

    /// The capability that makes `a`: its kind's, and for an upscale whether it writes a
    /// clip (an .mp4 out: video.upscale) or an image.
    pub fn for_asset(a: &crate::spec::Asset) -> Option<Self> {
        match a.kind {
            Kind::Upscale
                if a.outs
                    .first()
                    .is_some_and(|o| o.to_ascii_lowercase().ends_with(".mp4")) =>
            {
                Some(Capability::VideoUpscale)
            }
            k => Self::of(k),
        }
    }

    /// The asset kind that makes this capability.
    pub fn kind(self) -> Kind {
        match self {
            Capability::ImageGenerate => Kind::Image,
            Capability::ImageEdit => Kind::Edit,
            Capability::ImageCutout => Kind::Cutout,
            Capability::VideoLoop => Kind::Video,
            Capability::Model3dGenerate => Kind::Model3d,
            Capability::ImageUpscale | Capability::VideoUpscale => Kind::Upscale,
        }
    }

    fn table_path(self) -> (&'static str, &'static str) {
        let s = self.as_str();
        let (a, b) = s.split_once('.').expect("capability names are group.name");
        (a, b)
    }
}

impl std::fmt::Display for Capability {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Who makes a job.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Provider {
    /// A `[comfyui.<name>]` instance.
    Comfyui(String),
    Nolgia,
    /// The end of the list: the capability is off past this point.
    None,
}

impl Provider {
    pub fn parse(s: &str) -> Result<Self, Error> {
        match s {
            "nolgia" => Ok(Provider::Nolgia),
            "none" => Ok(Provider::None),
            _ => match s.strip_prefix("comfyui:") {
                Some(n) if !n.is_empty() => Ok(Provider::Comfyui(n.to_string())),
                _ => Err(Error::Spec(format!(
                    "provider {s:?}: expected \"comfyui:<name>\", \"nolgia\" or \"none\""
                ))),
            },
        }
    }

    pub fn id(&self) -> String {
        match self {
            Provider::Comfyui(n) => format!("comfyui:{n}"),
            Provider::Nolgia => "nolgia".into(),
            Provider::None => "none".into(),
        }
    }
}

/// One provider in a capability's list, with what it runs there.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Candidate {
    pub provider: Provider,
    /// A workflow name on a ComfyUI, a model id on nolgia.
    pub model: String,
}

/// The merged `create.toml`.
#[derive(Debug, Clone)]
pub struct Config {
    table: Table,
    /// The files read, in order (for messages).
    pub files: Vec<PathBuf>,
    /// Where work runs, for capabilities without providers of their own.
    targets: Targets,
}

pub(crate) fn config_home() -> PathBuf {
    std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
        .unwrap_or_else(|| PathBuf::from(".config"))
}

pub(crate) fn share_dir() -> PathBuf {
    std::env::var_os("BROMIGOS_SHARE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/usr/share/bromigos"))
}

/// The user's `create.toml` (where `bromigos setup create` writes).
pub fn user_path() -> PathBuf {
    std::env::var_os("BROMIGOS_CREATE_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|| config_home().join("bromigos/create.toml"))
}

/// Deep merge: tables merge key by key, anything else is replaced.
pub(crate) fn merge(base: &mut Table, over: Table) {
    for (k, v) in over {
        match (base.get_mut(&k), v) {
            (Some(Value::Table(b)), Value::Table(o)) => merge(b, o),
            (_, v) => {
                base.insert(k, v);
            }
        }
    }
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

impl Config {
    /// The packaged default, then the user's file.
    pub fn load() -> Result<Config, Error> {
        let mut files = Vec::new();
        let share = share_dir().join("default/create.toml");
        let mut table = match std::fs::read_to_string(&share) {
            Ok(t) => {
                files.push(share.clone());
                parse(&t, &share.display().to_string())?
            }
            Err(_) => parse(DEFAULT, "the built-in create.toml")?,
        };
        let user = user_path();
        match std::fs::read_to_string(&user) {
            Ok(t) => {
                merge(&mut table, parse(&t, &user.display().to_string())?);
                files.push(user);
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(Error::io(&user, e)),
        }
        Ok(Config {
            table,
            files,
            targets: Targets::load()?,
        })
    }

    /// A config from text over the built-in default (tests, `--config`), with the
    /// targets in force.
    pub fn from_toml(text: &str) -> Result<Config, Error> {
        Self::with_targets(text, Targets::load()?)
    }

    /// A config from text over the built-in default, with these targets.
    pub fn with_targets(text: &str, targets: Targets) -> Result<Config, Error> {
        let mut table = parse(DEFAULT, "the built-in create.toml")?;
        merge(&mut table, parse(text, "create.toml")?);
        Ok(Config {
            table,
            files: Vec::new(),
            targets,
        })
    }

    /// Where work runs (targets.toml).
    pub fn targets(&self) -> &Targets {
        &self.targets
    }

    fn capability(&self, cap: Capability) -> Option<&Table> {
        let (a, b) = cap.table_path();
        self.table.get(a)?.as_table()?.get(b)?.as_table()
    }

    /// The providers to try for `cap`, in order, each with what it runs: an
    /// entry without a model for its kind of provider, an unknown provider, a
    /// disabled nolgia, and everything after `"none"` are left out. A provider
    /// kind's model may be a list in preference order (`comfyui = ["wan2.2-i2v-a14b",
    /// "wan2.2-ti2v-5b"]`, the lab model catalog's ranking): each is a candidate on
    /// that provider, tried in turn (docs/lab-models.md, "The model-selection contract").
    pub fn candidates(&self, cap: Capability) -> Result<Vec<Candidate>, Error> {
        let Some(t) = self.capability(cap) else {
            return Ok(Vec::new());
        };
        let list: Vec<String> = match t.get("providers") {
            // none of its own: where targets.toml says work runs
            None => self.targets.providers(cap)?,
            Some(Value::Array(a)) => a
                .iter()
                .map(|v| {
                    v.as_str().map(String::from).ok_or_else(|| {
                        Error::Spec(format!(
                            "create.toml [{cap}] providers: {v} is not a string"
                        ))
                    })
                })
                .collect::<Result<_, _>>()?,
            Some(_) => {
                return Err(Error::Spec(format!(
                    "create.toml [{cap}] providers must be a list"
                )));
            }
        };
        let mut out = Vec::new();
        for s in &list {
            let provider = Provider::parse(s)?;
            let model = match &provider {
                Provider::None => break,
                Provider::Nolgia if !self.nolgia_enabled() => continue,
                Provider::Nolgia => t.get("nolgia"),
                Provider::Comfyui(name) => {
                    if !self.comfyui_names().contains(name) {
                        continue;
                    }
                    t.get("comfyui")
                }
            };
            for m in models(model, cap, &provider)? {
                out.push(Candidate {
                    provider: provider.clone(),
                    model: m,
                });
            }
        }
        Ok(out)
    }

    /// The `[comfyui.<name>]` instances, and `homelab` / `local` when targets.toml names
    /// a ComfyUI for them.
    pub fn comfyui_names(&self) -> Vec<String> {
        let mut names: Vec<String> = self
            .table
            .get("comfyui")
            .and_then(Value::as_table)
            .map(|t| t.keys().cloned().collect())
            .unwrap_or_default();
        for n in ["homelab", "local"] {
            if !names.iter().any(|x| x == n) && self.targets.comfyui(n).is_some() {
                names.push(n.to_string());
            }
        }
        names
    }

    fn comfyui(&self, name: &str) -> Option<&Table> {
        self.table.get("comfyui")?.as_table()?.get(name)?.as_table()
    }

    /// The instance's URL, references resolved. Without a `[comfyui.homelab]`
    /// table, `comfyui:homelab` falls back to the older settings
    /// (`BROMIGOS_COMFYUI_URL`, `comfyui_url` in art.toml).
    pub fn comfyui_endpoint(&self, name: &str) -> Result<String, Error> {
        match self
            .comfyui(name)
            .and_then(|t| t.get("endpoint"))
            .and_then(Value::as_str)
        {
            Some(r) => {
                let url = resolve(r);
                if url.is_empty() {
                    Err(Error::Homelab(format!(
                        "comfyui:{name}: its endpoint {r:?} doesn't resolve to an address"
                    )))
                } else {
                    Ok(url.trim_end_matches('/').to_string())
                }
            }
            None => match self.targets.comfyui(name) {
                Some(url) => Ok(url),
                None if name == "homelab" => crate::comfy::endpoint(),
                None => Err(Error::Spec(format!(
                    "comfyui:{name} has no [comfyui.{name}] endpoint in create.toml, and targets.toml names none"
                ))),
            },
        }
    }

    /// A job's time limit on the instance, if set.
    pub fn comfyui_timeout(&self, name: &str) -> Option<u64> {
        self.comfyui(name)?
            .get("timeout_s")?
            .as_integer()
            .and_then(|n| u64::try_from(n).ok())
    }

    pub fn nolgia_enabled(&self) -> bool {
        self.table
            .get("nolgia")
            .and_then(Value::as_table)
            .and_then(|t| t.get("enabled"))
            .and_then(Value::as_bool)
            .unwrap_or(true)
    }

    /// The most one nolgia job may cost before the next provider is tried.
    pub fn nolgia_max_credits(&self) -> Option<u64> {
        self.table
            .get("nolgia")?
            .as_table()?
            .get("max_credits_per_job")?
            .as_integer()
            .and_then(|n| u64::try_from(n).ok())
    }
}

// ---------------------------------------------------------------- references

/// A value with its reference resolved; `""` when it doesn't resolve. Literal
/// values come back as they are.
/// A capability's model for one kind of provider: a name, or a list of names in
/// preference order (empty strings and duplicates dropped).
fn models(v: Option<&Value>, cap: Capability, provider: &Provider) -> Result<Vec<String>, Error> {
    let key = match provider {
        Provider::Comfyui(_) => "comfyui",
        _ => "nolgia",
    };
    let mut out: Vec<String> = Vec::new();
    match v {
        None => {}
        Some(Value::String(s)) if !s.trim().is_empty() => out.push(s.trim().to_string()),
        Some(Value::String(_)) => {}
        Some(Value::Array(a)) => {
            for x in a {
                let s = x.as_str().map(str::trim).ok_or_else(|| {
                    Error::Spec(format!("create.toml [{cap}] {key}: {x} is not a string"))
                })?;
                if !s.is_empty() && !out.iter().any(|o| o == s) {
                    out.push(s.to_string());
                }
            }
        }
        Some(other) => {
            return Err(Error::Spec(format!(
                "create.toml [{cap}] {key}: {other} is neither a name nor a list of names"
            )));
        }
    }
    Ok(out)
}

pub fn resolve(v: &str) -> String {
    resolve_depth(v, 0)
}

fn resolve_depth(v: &str, depth: u32) -> String {
    if depth > 4 {
        return String::new();
    }
    if let Some(name) = v.strip_prefix("@env:") {
        return std::env::var(name).unwrap_or_default();
    }
    if let Some(key) = v.strip_prefix("@private:") {
        return private_get(key)
            .map(|s| resolve_depth(&s, depth + 1))
            .unwrap_or_default();
    }
    if let Some(p) = v.strip_prefix("@file:") {
        return std::fs::read_to_string(expand(p))
            .map(|s| s.trim().to_string())
            .unwrap_or_default();
    }
    if let Some(r) = v.strip_prefix("@vault:") {
        return vault_field(r);
    }
    if let Some(name) = v.strip_prefix("@homelab:") {
        return homelab_endpoint(name)
            .map(|s| resolve_depth(&s, depth + 1))
            .unwrap_or_default();
    }
    v.to_string()
}

fn expand(p: &str) -> PathBuf {
    match p.strip_prefix("~/") {
        Some(rest) => std::env::var_os("HOME")
            .map(|h| PathBuf::from(h).join(rest))
            .unwrap_or_else(|| PathBuf::from(p)),
        None => PathBuf::from(p),
    }
}

/// A dotted key from the private overlay's decrypted `config.json`.
fn private_get(key: &str) -> Option<String> {
    let path = std::env::var_os("BROMIGOS_PRIVATE_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|| config_home().join("bromigos/private/config.json"));
    let text = std::fs::read_to_string(path).ok()?;
    let mut v: serde_json::Value = serde_json::from_str(&text).ok()?;
    for part in key.split('.') {
        v = v.get(part)?.clone();
    }
    match v {
        serde_json::Value::String(s) => Some(s),
        serde_json::Value::Number(n) => Some(n.to_string()),
        serde_json::Value::Bool(b) => Some(b.to_string()),
        _ => None,
    }
}

/// `kv/path#field` through the vault CLI (its login, its address).
fn vault_field(r: &str) -> String {
    let Some((path, field)) = r.split_once('#') else {
        return String::new();
    };
    std::process::Command::new("vault")
        .args(["kv", "get", &format!("-field={field}"), path])
        .stderr(std::process::Stdio::null())
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_default()
}

/// The `endpoint` of the `homelab.toml` source named `name` (a source without a
/// name is named after its type). The packaged default, then the user's file.
fn homelab_endpoint(name: &str) -> Option<String> {
    let user = std::env::var_os("BROMIGOS_HOMELAB_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|| config_home().join("bromigos/homelab.toml"));
    let files = [share_dir().join("default/homelab.toml"), user];
    let mut found = None;
    for f in &files {
        if let Some(e) = source_endpoint(f, name) {
            found = Some(e);
        }
    }
    found
}

fn source_endpoint(file: &Path, name: &str) -> Option<String> {
    let text = std::fs::read_to_string(file).ok()?;
    let t: Table = toml::from_str(&text).ok()?;
    let sources = t.get("source")?.as_array()?;
    sources.iter().filter_map(Value::as_table).find_map(|s| {
        let n = s
            .get("name")
            .or_else(|| s.get("type"))
            .and_then(Value::as_str)?;
        if n != name {
            return None;
        }
        s.get("endpoint").and_then(Value::as_str).map(String::from)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Targets with no homelab and no local ComfyUI: only the cloud offers creation.
    fn cloud_only() -> Targets {
        Targets::from_toml(
            "[targets.homelab]\ncomfyui = \"\"\nvoice = \"\"\nllm = \"\"\n[targets.local]\ncomfyui = \"\"\n",
        )
        .unwrap()
    }

    fn cfg(text: &str) -> Config {
        Config::with_targets(text, cloud_only()).unwrap()
    }

    #[test]
    fn the_default_follows_targets() {
        // nothing but the cloud configured: nolgia for every capability it makes;
        // upscaling has no cloud model (a ComfyUI's only)
        let c = cfg("");
        for cap in Capability::ALL {
            let cs = c.candidates(cap).unwrap();
            if matches!(cap, Capability::ImageUpscale | Capability::VideoUpscale) {
                assert!(cs.is_empty(), "{cap}");
                continue;
            }
            assert_eq!(cs.len(), 1, "{cap}");
            assert_eq!(cs[0].provider, Provider::Nolgia);
        }
        assert_eq!(
            c.candidates(Capability::ImageCutout).unwrap()[0].model,
            "remove-background"
        );
        // a homelab and this machine, never the cloud except for video loops
        let t = Targets::from_toml(
            "[targets]\norder = [\"homelab\", \"local\"]\n[targets.homelab]\ncomfyui = \"http://lab:8188\"\n[service.\"video.loop\"]\norder = [\"homelab\", \"local\", \"cloud\"]\n",
        )
        .unwrap();
        let c = Config::with_targets("", t).unwrap();
        let ids = |cap| {
            c.candidates(cap)
                .unwrap()
                .into_iter()
                .map(|x| x.provider.id())
                .collect::<Vec<_>>()
        };
        assert_eq!(
            ids(Capability::ImageEdit),
            ["comfyui:homelab", "comfyui:local"]
        );
        // 3D: Pixal3D, else Hunyuan3D 2.1, on each ComfyUI in turn
        assert_eq!(
            ids(Capability::Model3dGenerate),
            [
                "comfyui:homelab",
                "comfyui:homelab",
                "comfyui:local",
                "comfyui:local"
            ]
        );
        let models: Vec<String> = c
            .candidates(Capability::Model3dGenerate)
            .unwrap()
            .into_iter()
            .map(|x| x.model)
            .collect();
        assert_eq!(
            models[..2],
            ["pixal3d".to_string(), "hunyuan3d-2.1".to_string()]
        );
        // upscaling: the lab's and this machine's ComfyUI, no cloud model
        assert_eq!(
            ids(Capability::VideoUpscale),
            ["comfyui:homelab", "comfyui:local"]
        );
        // video loops follow the same order (Wan 2.2 on a ComfyUI, the A14B before the
        // TI2V-5B), the cloud only where it's listed
        assert_eq!(
            ids(Capability::VideoLoop),
            [
                "comfyui:homelab",
                "comfyui:homelab",
                "comfyui:local",
                "comfyui:local",
                "nolgia"
            ]
        );
        let models: Vec<String> = c
            .candidates(Capability::VideoLoop)
            .unwrap()
            .into_iter()
            .map(|x| x.model)
            .collect();
        assert_eq!(
            models[..2],
            ["wan2.2-i2v-a14b".to_string(), "wan2.2-ti2v-5b".to_string()]
        );
        assert_eq!(c.comfyui_endpoint("homelab").unwrap(), "http://lab:8188");
        assert_eq!(
            c.comfyui_endpoint("local").unwrap(),
            "http://127.0.0.1:8188"
        );
        // a list of its own wins over the targets
        let t = Targets::from_toml("[targets.homelab]\ncomfyui = \"http://lab:8188\"\n").unwrap();
        let c = Config::with_targets("[image.edit]\nproviders = [\"nolgia\"]\n", t).unwrap();
        assert_eq!(
            c.candidates(Capability::ImageEdit).unwrap()[0].provider,
            Provider::Nolgia
        );
    }

    #[test]
    fn providers_in_order_unknown_skipped_none_stops() {
        let c = Config::with_targets(
            r#"
            [comfyui.homelab]
            endpoint = "http://lab:8188"
            [image.generate]
            providers = ["comfyui:local", "comfyui:homelab", "none", "nolgia"]
            "#,
            cloud_only(),
        )
        .unwrap();
        let cs = c.candidates(Capability::ImageGenerate).unwrap();
        assert_eq!(
            cs,
            vec![Candidate {
                provider: Provider::Comfyui("homelab".into()),
                model: "qwen-image-2.1".into()
            }]
        );
        // video.loop has a ComfyUI workflow now: a comfyui provider in its list is kept
        let c = Config::with_targets(
            "[comfyui.homelab]\nendpoint = \"http://x\"\n[video.loop]\nproviders = [\"comfyui:homelab\", \"nolgia\"]\n",
            cloud_only(),
        )
        .unwrap();
        let cs = c.candidates(Capability::VideoLoop).unwrap();
        assert_eq!(cs[0].provider, Provider::Comfyui("homelab".into()));
        assert_eq!(cs[1].model, "wan2.2-ti2v-5b");
    }

    #[test]
    fn a_list_of_workflows_is_tried_in_order() {
        // the lab model catalog's ranking: each workflow a candidate on that ComfyUI
        let c = cfg(r#"
            [comfyui.homelab]
            endpoint = "http://lab:8188"
            [model3d.generate]
            providers = ["comfyui:homelab", "nolgia"]
            comfyui = ["hunyuan3d-2.1", " trellis-2 ", "", "hunyuan3d-2.1"]
            nolgia = "trellis"
            "#);
        let cs = c.candidates(Capability::Model3dGenerate).unwrap();
        let got: Vec<(String, String)> = cs
            .iter()
            .map(|x| (x.provider.id(), x.model.clone()))
            .collect();
        assert_eq!(
            got,
            [
                ("comfyui:homelab".to_string(), "hunyuan3d-2.1".to_string()),
                ("comfyui:homelab".to_string(), "trellis-2".to_string()),
                ("nolgia".to_string(), "trellis".to_string()),
            ]
        );
        // a list of something else is refused, in plain words
        let c = cfg(
            "[comfyui.homelab]\nendpoint = \"x\"\n[image.cutout]\nproviders = [\"comfyui:homelab\"]\ncomfyui = [1]\n",
        );
        let e = c
            .candidates(Capability::ImageCutout)
            .unwrap_err()
            .to_string();
        assert!(e.contains("is not a string"), "{e}");
        let c = cfg(
            "[comfyui.homelab]\nendpoint = \"x\"\n[image.cutout]\nproviders = [\"comfyui:homelab\"]\ncomfyui = 3\n",
        );
        assert!(c.candidates(Capability::ImageCutout).is_err());
    }

    #[test]
    fn nolgia_can_be_switched_off_and_bad_ids_refused() {
        let c = cfg("[nolgia]\nenabled = false\n");
        assert!(c.candidates(Capability::ImageGenerate).unwrap().is_empty());
        let c = cfg("[image.generate]\nproviders = [\"comfyui\"]\n");
        assert!(c.candidates(Capability::ImageGenerate).is_err());
        assert!(Config::with_targets("format = 2\n", cloud_only()).is_err());
    }

    #[test]
    fn references_resolve() {
        let dir = tempfile::tempdir().unwrap();
        let private = dir.path().join("config.json");
        std::fs::write(
            &private,
            r#"{"env": {"BROMIGOS_COMFYUI_URL": "http://from-private:8188"}}"#,
        )
        .unwrap();
        let homelab = dir.path().join("homelab.toml");
        std::fs::write(
            &homelab,
            "[[source]]\nname = \"comfyui\"\ntype = \"comfyui\"\nendpoint = \"@private:env.BROMIGOS_COMFYUI_URL\"\n",
        )
        .unwrap();
        let file = dir.path().join("url");
        std::fs::write(&file, "http://from-file:8188\n").unwrap();
        // SAFETY: this test owns these variables; no other test reads them.
        unsafe {
            std::env::set_var("BROMIGOS_PRIVATE_CONFIG", &private);
            std::env::set_var("BROMIGOS_HOMELAB_CONFIG", &homelab);
            std::env::set_var("BROMIGOS_SHARE_DIR", dir.path().join("none"));
            std::env::set_var("BROMIGOS_TEST_URL", "http://from-env:8188");
        }
        assert_eq!(resolve("@env:BROMIGOS_TEST_URL"), "http://from-env:8188");
        assert_eq!(
            resolve("@private:env.BROMIGOS_COMFYUI_URL"),
            "http://from-private:8188"
        );
        assert_eq!(
            resolve(&format!("@file:{}", file.display())),
            "http://from-file:8188"
        );
        assert_eq!(resolve("@homelab:comfyui"), "http://from-private:8188");
        assert_eq!(resolve("@homelab:nope"), "");
        assert_eq!(resolve("@private:no.such.key"), "");
        assert_eq!(resolve("http://literal:1"), "http://literal:1");
        let c = cfg("[comfyui.homelab]\nendpoint = \"@homelab:comfyui\"\n");
        assert_eq!(
            c.comfyui_endpoint("homelab").unwrap(),
            "http://from-private:8188"
        );
        let c = cfg("[comfyui.local]\nendpoint = \"@env:BROMIGOS_UNSET_X\"\n");
        assert!(c.comfyui_endpoint("local").is_err());
    }
}
