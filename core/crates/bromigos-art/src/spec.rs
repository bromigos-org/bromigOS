//! `art.toml`: a world's assets, how each is made, and the content hash of that
//! recipe (the "spec"), which is what decides whether an asset is up to date.

use std::collections::{BTreeMap, HashMap};
use std::fmt;
use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::Error;

/// The `format` this build reads.
pub const FORMAT: u32 = 1;

/// What an asset is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    /// A new image from a prompt, with optional reference images.
    Image,
    /// An edit of one image, with an optional mask (transparent = may change).
    Edit,
    /// A video clip from a start frame; `loop = true` ends on the start frame.
    Video,
    /// Background removal (a transparent PNG).
    Cutout,
    /// A 3D model (GLB) from a concept image.
    Model3d,
    /// An image or a video clip made larger and sharper (a PNG from an image, an MP4
    /// from a clip): `extra.scale`, 2 by default.
    Upscale,
    /// A local command (the layer split, a converter): no credits.
    Command,
}

impl Kind {
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Image => "image",
            Kind::Edit => "edit",
            Kind::Video => "video",
            Kind::Cutout => "cutout",
            Kind::Model3d => "model3d",
            Kind::Upscale => "upscale",
            Kind::Command => "command",
        }
    }

    /// Whether it is submitted to nolgia (and costs credits).
    pub fn remote(self) -> bool {
        self != Kind::Command
    }
}

impl fmt::Display for Kind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// One `[[assets]]` table, or `[defaults]`, as written.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RawAsset {
    pub id: Option<String>,
    pub version: Option<u32>,
    pub kind: Option<Kind>,
    pub note: Option<String>,
    pub model: Option<String>,
    /// Who makes it (`comfyui:<name>`, `nolgia`); create.toml decides when unset.
    pub provider: Option<String>,
    pub prompt: Option<String>,
    pub prompt_file: Option<String>,
    pub inputs: Option<Vec<String>>,
    pub input: Option<String>,
    pub mask: Option<String>,
    pub aspect: Option<String>,
    pub quality: Option<String>,
    pub render_quality: Option<String>,
    pub images: Option<u32>,
    pub aura: Option<bool>,
    pub start: Option<String>,
    pub end: Option<String>,
    #[serde(rename = "loop")]
    pub looped: Option<bool>,
    pub duration: Option<u32>,
    pub resolution: Option<String>,
    pub audio: Option<bool>,
    pub run: Option<Vec<String>>,
    pub out: Option<String>,
    pub outs: Option<Vec<String>>,
    pub extra: Option<toml::Table>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawFile {
    format: u32,
    #[serde(default)]
    defaults: RawAsset,
    #[serde(default)]
    assets: Vec<RawAsset>,
}

/// An input: another asset's output (`@id`) or a file in the theme directory.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Input {
    Asset(String),
    File(String),
}

impl Input {
    fn parse(s: &str, field: &str) -> Result<Self, String> {
        if let Some(rest) = s.strip_prefix('@') {
            if !valid_id(rest) {
                return Err(format!("{field}: {s:?} is not an asset reference (@id)"));
            }
            Ok(Input::Asset(rest.to_owned()))
        } else {
            rel_path(s).map_err(|e| format!("{field}: {e}"))?;
            Ok(Input::File(s.to_owned()))
        }
    }
}

impl fmt::Display for Input {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Input::Asset(id) => write!(f, "@{id}"),
            Input::File(p) => f.write_str(p),
        }
    }
}

/// One asset, with `[defaults]` applied and checked for its kind.
#[derive(Debug, Clone)]
pub struct Asset {
    pub id: String,
    pub version: u32,
    pub kind: Kind,
    pub note: Option<String>,
    /// The model: a nolgia model id, `homelab:<workflow>`, or a workflow on the
    /// pinned provider. None: create.toml's providers for the kind decide.
    pub model: Option<String>,
    /// A pinned provider (`comfyui:<name>`, `nolgia`).
    pub provider: Option<String>,
    /// The prompt as sent: trimmed of surrounding whitespace.
    pub prompt: Option<String>,
    /// Reference images (image), the image (edit, cutout), the start frame (video),
    /// what the command reads (command).
    pub inputs: Vec<Input>,
    pub mask: Option<Input>,
    /// A video's end frame: the start frame when `loop = true`.
    pub end: Option<Input>,
    pub looped: bool,
    pub aspect: Option<String>,
    pub quality: Option<String>,
    pub render_quality: Option<String>,
    pub images: u32,
    pub aura: Option<bool>,
    pub duration: Option<u32>,
    pub resolution: Option<String>,
    pub audio: Option<bool>,
    pub run: Vec<String>,
    pub extra: serde_json::Map<String, Value>,
    /// Output paths, relative to the theme directory.
    pub outs: Vec<String>,
    /// The content hash of the recipe ("sha256:…"); see [`World::load`].
    pub spec: String,
}

impl Asset {
    /// Every asset this one reads.
    pub fn needs(&self) -> Vec<&str> {
        let mut v: Vec<&str> = Vec::new();
        for i in self.inputs.iter().chain(&self.mask).chain(&self.end) {
            if let Input::Asset(id) = i
                && !v.contains(&id.as_str())
            {
                v.push(id);
            }
        }
        v
    }

    /// Every file input (paths relative to the theme directory).
    pub fn files(&self) -> Vec<&str> {
        let mut v: Vec<&str> = Vec::new();
        for i in self.inputs.iter().chain(&self.mask).chain(&self.end) {
            if let Input::File(p) = i
                && !v.contains(&p.as_str())
            {
                v.push(p);
            }
        }
        v
    }

    /// The number of input images nolgia sees (references, start and end frames;
    /// a mask is not one).
    pub fn input_images(&self) -> u64 {
        match self.kind {
            Kind::Command => 0,
            _ => (self.inputs.len() + usize::from(self.end.is_some())) as u64,
        }
    }

    pub fn prompt_sha256(&self) -> Option<String> {
        self.prompt.as_deref().map(sha256_hex)
    }
}

/// A world's `art.toml`, loaded.
#[derive(Debug, Clone)]
pub struct World {
    pub name: String,
    /// The theme directory (`themes/<name>/`).
    pub dir: PathBuf,
    /// The assets, in an order where every asset comes after what it reads.
    pub assets: Vec<Asset>,
}

impl World {
    pub fn art_toml(dir: &Path) -> PathBuf {
        dir.join("art.toml")
    }

    pub fn log_path(&self) -> PathBuf {
        self.dir.join("art.log.jsonl")
    }

    pub fn get(&self, id: &str) -> Option<&Asset> {
        self.assets.iter().find(|a| a.id == id)
    }

    /// Reads `<dir>/art.toml`.
    pub fn load(name: &str, dir: &Path) -> Result<World, Error> {
        let path = Self::art_toml(dir);
        let text = std::fs::read_to_string(&path).map_err(|e| Error::io(&path, e))?;
        Self::parse(name, dir, &text)
    }

    /// Parses an `art.toml` (prompt files are read relative to `dir`).
    ///
    /// The spec of an asset is the SHA-256 of a canonical JSON document of its
    /// recipe: kind, version, model, the prompt text, the inputs (another asset's
    /// input by that asset's spec, a file by its path), the mask, every request
    /// option and `extra`. Its `id`, `note` and output paths are not part of it,
    /// so renaming or moving an output does not make it stale; `version` is there
    /// to regenerate on purpose. File inputs are checked by content separately
    /// (the log records each one's SHA-256).
    pub fn parse(name: &str, dir: &Path, text: &str) -> Result<World, Error> {
        let bad = |msg: String| Error::Spec(format!("{}: {msg}", Self::art_toml(dir).display()));
        let raw: RawFile = toml::from_str(text).map_err(|e| bad(e.to_string()))?;
        if raw.format != FORMAT {
            return Err(bad(format!(
                "format {} is not supported (this bromigos reads format {FORMAT})",
                raw.format
            )));
        }
        let d = &raw.defaults;
        if d.id.is_some()
            || d.version.is_some()
            || d.out.is_some()
            || d.outs.is_some()
            || d.run.is_some()
            || d.kind.is_some()
        {
            return Err(bad(
                "[defaults] takes request options only (not id, version, kind, run, out, outs)"
                    .into(),
            ));
        }
        let mut assets = Vec::new();
        let mut seen_outs: HashMap<String, String> = HashMap::new();
        for (i, a) in raw.assets.iter().enumerate() {
            let asset = resolve(a, d, dir).map_err(|m| {
                let who = a.id.clone().unwrap_or_else(|| format!("#{}", i + 1));
                bad(format!("asset {who}: {m}"))
            })?;
            if assets.iter().any(|x: &Asset| x.id == asset.id) {
                return Err(bad(format!("asset {}: the id is used twice", asset.id)));
            }
            for o in &asset.outs {
                if let Some(other) = seen_outs.insert(o.clone(), asset.id.clone()) {
                    return Err(bad(format!(
                        "asset {}: output {o} is also asset {other}'s",
                        asset.id
                    )));
                }
            }
            assets.push(asset);
        }
        let ordered = order(assets).map_err(bad)?;
        let mut world = World {
            name: name.to_owned(),
            dir: dir.to_path_buf(),
            assets: ordered,
        };
        world.hash_all();
        Ok(world)
    }

    fn hash_all(&mut self) {
        let mut specs: HashMap<String, String> = HashMap::new();
        for a in &mut self.assets {
            let spec = spec_hash(a, &specs);
            specs.insert(a.id.clone(), spec.clone());
            a.spec = spec;
        }
    }
}

fn valid_id(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 64
        && s.starts_with(|c: char| c.is_ascii_lowercase() || c.is_ascii_digit())
        && s.chars().all(|c| {
            c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_' || c == '.'
        })
}

/// A path relative to the theme directory that stays inside it.
fn rel_path(s: &str) -> Result<(), String> {
    let p = Path::new(s);
    if s.is_empty() || p.is_absolute() {
        return Err(format!(
            "{s:?} must be a path relative to the theme directory"
        ));
    }
    if p.components().any(|c| !matches!(c, Component::Normal(_))) {
        return Err(format!(
            "{s:?} must stay inside the theme directory (no .., no ./)"
        ));
    }
    Ok(())
}

fn pick<T: Clone>(a: &Option<T>, d: &Option<T>) -> Option<T> {
    a.clone().or_else(|| d.clone())
}

fn resolve(a: &RawAsset, d: &RawAsset, dir: &Path) -> Result<Asset, String> {
    let id = a.id.clone().ok_or("no id")?;
    if !valid_id(&id) {
        return Err(format!(
            "id {id:?}: lowercase letters, digits, '-', '_' and '.', at most 64"
        ));
    }
    let kind = a
        .kind
        .ok_or("no kind (image, edit, video, cutout, model3d, upscale or command)")?;
    let version = a.version.unwrap_or(1);
    let model = pick(&a.model, &d.model);
    let provider = pick(&a.provider, &d.provider);
    if let Some(p) = &provider {
        let parsed = crate::create::Provider::parse(p).map_err(|e| e.to_string())?;
        if parsed == crate::create::Provider::None {
            return Err("provider = \"none\": leave the asset out instead".into());
        }
        if model.is_none() {
            return Err(format!(
                "provider = {p:?} needs a model (a workflow or a model id)"
            ));
        }
    }
    let prompt = match (&a.prompt, &a.prompt_file) {
        (Some(_), Some(_)) => return Err("both prompt and prompt_file".into()),
        (Some(p), None) => Some(p.trim().to_owned()),
        (None, Some(f)) => {
            rel_path(f).map_err(|e| format!("prompt_file: {e}"))?;
            let path = dir.join(f);
            let text = std::fs::read_to_string(&path)
                .map_err(|e| format!("prompt_file {}: {e}", path.display()))?;
            Some(text.trim().to_owned())
        }
        (None, None) => d.prompt.as_ref().map(|p| p.trim().to_owned()),
    };
    let parse_list = |v: &Option<Vec<String>>, field: &str| -> Result<Vec<Input>, String> {
        v.iter().flatten().map(|s| Input::parse(s, field)).collect()
    };
    let one = |v: &Option<String>, field: &str| -> Result<Option<Input>, String> {
        v.as_deref().map(|s| Input::parse(s, field)).transpose()
    };
    let mut inputs = parse_list(&a.inputs, "inputs")?;
    let mask = one(&a.mask, "mask")?;
    let looped = a.looped.unwrap_or(false);
    let mut end = None;
    let need = |cond: bool, what: &str| -> Result<(), String> {
        if cond {
            Ok(())
        } else {
            Err(format!("a {kind} needs {what}"))
        }
    };
    let forbid = |cond: bool, what: &str| -> Result<(), String> {
        if cond {
            Err(format!("a {kind} takes no {what}"))
        } else {
            Ok(())
        }
    };
    match kind {
        Kind::Image => {
            forbid(
                a.input.is_some(),
                "input (use inputs = [...] for references)",
            )?;
            forbid(mask.is_some(), "mask (use kind = \"edit\")")?;
        }
        Kind::Edit | Kind::Cutout | Kind::Model3d | Kind::Upscale => {
            forbid(a.inputs.is_some(), "inputs (use input = \"...\")")?;
            let input = one(&a.input, "input")?;
            need(input.is_some(), "input")?;
            inputs = input.into_iter().collect();
            if matches!(kind, Kind::Cutout | Kind::Model3d | Kind::Upscale) {
                forbid(mask.is_some(), "mask")?;
                forbid(prompt.is_some() && a.prompt.is_some(), "prompt")?;
            }
        }
        Kind::Video => {
            forbid(
                a.inputs.is_some() || a.input.is_some(),
                "inputs (use start = \"...\")",
            )?;
            forbid(mask.is_some(), "mask")?;
            let start = one(&a.start, "start")?;
            need(start.is_some(), "start (the first frame)")?;
            end = one(&a.end, "end")?;
            if looped {
                if end.is_some() {
                    return Err("loop = true ends on the start frame; drop end".into());
                }
                end = start.clone();
            }
            inputs = start.into_iter().collect();
        }
        Kind::Command => {
            forbid(a.input.is_some(), "input (use inputs = [...])")?;
            forbid(mask.is_some(), "mask")?;
            need(
                a.run.as_ref().is_some_and(|r| !r.is_empty()),
                "run = [program, args...]",
            )?;
        }
    }
    if kind.remote() {
        forbid(a.run.is_some(), "run")?;
        if matches!(kind, Kind::Image | Kind::Edit | Kind::Video) {
            need(
                prompt.as_deref().is_some_and(|p| !p.is_empty()),
                "prompt or prompt_file",
            )?;
        }
    }
    if kind == Kind::Video {
        need(
            pick(&a.duration, &d.duration).is_some(),
            "duration (seconds)",
        )?;
    }
    let images = pick(&a.images, &d.images).unwrap_or(1);
    if images == 0 || (images > 1 && kind != Kind::Image) {
        return Err("images: 1 or more, and more than 1 only for kind = \"image\"".into());
    }
    let outs: Vec<String> = match (&a.out, &a.outs) {
        (Some(_), Some(_)) => return Err("both out and outs".into()),
        (Some(o), None) => {
            if images > 1 {
                numbered(o, images)
            } else {
                vec![o.clone()]
            }
        }
        (None, Some(v)) if kind == Kind::Command && !v.is_empty() => v.clone(),
        (None, Some(_)) => return Err("outs is for commands; use out".into()),
        (None, None) => return Err("no out".into()),
    };
    for o in &outs {
        rel_path(o).map_err(|e| format!("out: {e}"))?;
    }
    if kind == Kind::Model3d
        && !outs
            .iter()
            .all(|o| o.to_ascii_lowercase().ends_with(".glb"))
    {
        return Err("a model3d writes GLB: out must end in .glb".into());
    }
    if kind == Kind::Upscale
        && !outs.iter().all(|o| {
            let o = o.to_ascii_lowercase();
            o.ends_with(".png") || o.ends_with(".mp4")
        })
    {
        return Err(
            "an upscale writes a PNG (from an image) or an MP4 (from a clip): out must end in .png or .mp4"
                .into(),
        );
    }
    let extra = match pick(&a.extra, &d.extra) {
        None => serde_json::Map::new(),
        Some(t) => match serde_json::to_value(t).map_err(|e| format!("extra: {e}"))? {
            Value::Object(m) => m,
            _ => serde_json::Map::new(),
        },
    };
    let (is_img, is_vid) = (
        matches!(kind, Kind::Image | Kind::Edit),
        kind == Kind::Video,
    );
    let only = |cond: bool, v: Option<String>| if cond { v } else { None };
    Ok(Asset {
        id: id.clone(),
        version,
        kind,
        note: a.note.clone(),
        model: if kind.remote() { model } else { None },
        provider: if kind.remote() { provider } else { None },
        prompt: if kind == Kind::Command { None } else { prompt },
        inputs,
        mask,
        end,
        looped: is_vid && looped,
        aspect: only(is_img || is_vid, pick(&a.aspect, &d.aspect)),
        quality: only(is_img, pick(&a.quality, &d.quality)),
        render_quality: only(is_img, pick(&a.render_quality, &d.render_quality)),
        images,
        aura: if is_img { pick(&a.aura, &d.aura) } else { None },
        duration: if is_vid {
            pick(&a.duration, &d.duration)
        } else {
            None
        },
        resolution: only(is_vid, pick(&a.resolution, &d.resolution)),
        audio: if is_vid {
            pick(&a.audio, &d.audio)
        } else {
            None
        },
        run: a.run.clone().unwrap_or_default(),
        extra: if kind.remote() {
            extra
        } else {
            serde_json::Map::new()
        },
        outs,
        spec: String::new(),
    })
}

/// `x.png` with 3 images: `x-a.png`, `x-b.png`, `x-c.png` (the nolgia CLI's naming).
fn numbered(out: &str, n: u32) -> Vec<String> {
    let (stem, ext) = match out.rfind('.') {
        Some(i) if !out[i..].contains('/') => (&out[..i], &out[i..]),
        _ => (out, ""),
    };
    (0..n)
        .map(|i| {
            let letter = char::from(b'a' + (i % 26) as u8);
            format!("{stem}-{letter}{ext}")
        })
        .collect()
}

/// Orders assets so each comes after what it reads; fails on an unknown
/// reference or a cycle.
fn order(assets: Vec<Asset>) -> Result<Vec<Asset>, String> {
    let ids: Vec<String> = assets.iter().map(|a| a.id.clone()).collect();
    for a in &assets {
        for n in a.needs() {
            if !ids.iter().any(|i| i == n) {
                return Err(format!("asset {}: @{n} is not an asset in this file", a.id));
            }
            if n == a.id {
                return Err(format!("asset {}: reads its own output", a.id));
            }
        }
    }
    let mut pending: Vec<Asset> = assets;
    let mut done: Vec<Asset> = Vec::new();
    while !pending.is_empty() {
        let before = pending.len();
        let mut rest = Vec::new();
        for a in pending {
            if a.needs().iter().all(|n| done.iter().any(|d| d.id == *n)) {
                done.push(a);
            } else {
                rest.push(a);
            }
        }
        if rest.len() == before {
            let names: Vec<&str> = rest.iter().map(|a| a.id.as_str()).collect();
            return Err(format!("a cycle between assets {}", names.join(", ")));
        }
        pending = rest;
    }
    Ok(done)
}

fn spec_hash(a: &Asset, specs: &HashMap<String, String>) -> String {
    let input = |i: &Input| -> Value {
        match i {
            Input::Asset(id) => json!(format!(
                "@{}",
                specs.get(id).map(String::as_str).unwrap_or("")
            )),
            Input::File(p) => json!(format!("file:{p}")),
        }
    };
    let mut doc = json!({
        "kind": a.kind.as_str(),
        "version": a.version,
        "model": a.model,
        "prompt": a.prompt,
        "inputs": a.inputs.iter().map(input).collect::<Vec<_>>(),
        "mask": a.mask.as_ref().map(input),
        "end": a.end.as_ref().map(input),
        "loop": a.looped,
        "aspect": a.aspect,
        "quality": a.quality,
        "render_quality": a.render_quality,
        "images": a.images,
        "aura": a.aura,
        "duration": a.duration,
        "resolution": a.resolution,
        "audio": a.audio,
        "run": a.run,
        "extra": Value::Object(a.extra.clone()),
    });
    // only when pinned, so every recipe from before providers keeps its hash
    if let Some(p) = &a.provider {
        doc["provider"] = json!(p);
    }
    let mut s = String::new();
    canonical(&doc, &mut s);
    format!("sha256:{}", sha256_hex(&s))
}

/// JSON with object keys sorted at every level and no whitespace: the same
/// document always gives the same bytes.
pub fn canonical(v: &Value, out: &mut String) {
    match v {
        Value::Object(m) => {
            let sorted: BTreeMap<&String, &Value> = m.iter().collect();
            out.push('{');
            for (i, (k, v)) in sorted.into_iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push_str(&Value::String(k.clone()).to_string());
                out.push(':');
                canonical(v, out);
            }
            out.push('}');
        }
        Value::Array(a) => {
            out.push('[');
            for (i, v) in a.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                canonical(v, out);
            }
            out.push(']');
        }
        other => out.push_str(&other.to_string()),
    }
}

pub fn sha256_hex(s: impl AsRef<[u8]>) -> String {
    hex(&Sha256::digest(s.as_ref()))
}

pub fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        let _ = write!(s, "{b:02x}");
    }
    s
}

/// The SHA-256 of a file's bytes, streamed.
pub fn file_sha256(path: &Path) -> std::io::Result<String> {
    use std::io::Read;
    let mut f = std::fs::File::open(path)?;
    let mut h = Sha256::new();
    let mut buf = vec![0u8; 1 << 16];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(hex(&h.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn world(text: &str) -> Result<World, Error> {
        World::parse("w", Path::new("/nonexistent"), text)
    }

    const BASE: &str = r#"
format = 1
[defaults]
model = "m"
aura = false
[[assets]]
id = "comp"
kind = "image"
prompt = "  a bayou  "
aspect = "16:9"
out = "art/comp.png"
[[assets]]
id = "fix"
kind = "edit"
input = "@comp"
mask = "art/mask.png"
prompt = "fix it"
out = "art/fix.png"
"#;

    #[test]
    fn defaults_apply_and_order_follows_inputs() {
        let text = BASE.replace(
            "[[assets]]\nid = \"comp\"",
            "[[assets]]\nid = \"late\"\nkind = \"cutout\"\nmodel = \"remove-background\"\ninput = \"@fix\"\nout = \"art/late.png\"\n[[assets]]\nid = \"comp\"",
        );
        let w = world(&text).unwrap();
        let ids: Vec<&str> = w.assets.iter().map(|a| a.id.as_str()).collect();
        assert_eq!(ids, ["comp", "fix", "late"]);
        let comp = w.get("comp").unwrap();
        assert_eq!(comp.model.as_deref(), Some("m"));
        assert_eq!(comp.prompt.as_deref(), Some("a bayou"));
        assert_eq!(comp.aura, Some(false));
        assert_eq!(
            w.get("late").unwrap().model.as_deref(),
            Some("remove-background")
        );
        assert_eq!(w.get("fix").unwrap().needs(), ["comp"]);
        assert_eq!(w.get("fix").unwrap().files(), ["art/mask.png"]);
    }

    #[test]
    fn spec_ignores_id_note_and_out_but_follows_the_recipe() {
        let a = world(BASE).unwrap();
        let moved = world(&BASE.replace(
            "out = \"art/comp.png\"",
            "out = \"art/elsewhere.png\"\nnote = \"hi\"",
        ))
        .unwrap();
        assert_eq!(a.get("comp").unwrap().spec, moved.get("comp").unwrap().spec);
        // A prompt change changes the asset and everything that reads it.
        let reworded = world(&BASE.replace("a bayou", "a swamp")).unwrap();
        assert_ne!(
            a.get("comp").unwrap().spec,
            reworded.get("comp").unwrap().spec
        );
        assert_ne!(
            a.get("fix").unwrap().spec,
            reworded.get("fix").unwrap().spec
        );
        // Whitespace around the prompt is not part of it.
        let spaced = world(&BASE.replace("\"  a bayou  \"", "\"a bayou\"")).unwrap();
        assert_eq!(
            a.get("comp").unwrap().spec,
            spaced.get("comp").unwrap().spec
        );
        // A version bump regenerates on purpose.
        let bumped = world(&BASE.replace("id = \"comp\"", "id = \"comp\"\nversion = 2")).unwrap();
        assert_ne!(
            a.get("comp").unwrap().spec,
            bumped.get("comp").unwrap().spec
        );
        assert!(a.get("comp").unwrap().spec.starts_with("sha256:"));
    }

    #[test]
    fn video_loops_end_on_the_start_frame() {
        let w = world(
            r#"
format = 1
[[assets]]
id = "still"
kind = "image"
model = "m"
prompt = "p"
out = "a.png"
[[assets]]
id = "water"
kind = "video"
model = "v"
prompt = "ripples"
start = "@still"
loop = true
duration = 5
resolution = "720p"
out = "live/water.mp4"
"#,
        )
        .unwrap();
        let v = w.get("water").unwrap();
        assert_eq!(v.end, Some(Input::Asset("still".into())));
        assert_eq!(v.input_images(), 2);
        assert!(v.looped);
    }

    #[test]
    fn mistakes_are_refused_with_the_asset_named() {
        let cases = [
            (
                BASE.replace("kind = \"edit\"", "kind = \"edit\"\nbogus = 1"),
                "bogus",
            ),
            (BASE.replace("@comp", "@nope"), "@nope"),
            (
                BASE.replace("out = \"art/fix.png\"", "out = \"art/comp.png\""),
                "also asset comp",
            ),
            (
                BASE.replace("art/mask.png", "../mask.png"),
                "inside the theme",
            ),
            (BASE.replace("id = \"fix\"", "id = \"comp\""), "used twice"),
            (BASE.replace("format = 1", "format = 2"), "format 2"),
            // no model is fine (create.toml decides); a pinned provider needs one
            (
                BASE.replace("model = \"m\"\n", "provider = \"nolgia\"\n"),
                "needs a model",
            ),
            (
                BASE.replace("model = \"m\"\n", "provider = \"comfyui\"\nmodel = \"m\"\n"),
                "comfyui:<name>",
            ),
            (BASE.replace("input = \"@comp\"\n", ""), "needs input"),
        ];
        for (text, want) in cases {
            let err = world(&text).unwrap_err().to_string();
            assert!(err.contains(want), "{want:?} not in {err:?}");
        }
    }

    #[test]
    fn several_images_get_lettered_outputs() {
        assert_eq!(numbered("art/x.png", 2), ["art/x-a.png", "art/x-b.png"]);
        assert_eq!(numbered("art.d/x", 2), ["art.d/x-a", "art.d/x-b"]);
    }

    #[test]
    fn canonical_json_sorts_keys() {
        let mut s = String::new();
        canonical(
            &json!({"b": 1, "a": {"d": [1, {"z": 0, "y": null}], "c": "x"}}),
            &mut s,
        );
        assert_eq!(s, r#"{"a":{"c":"x","d":[1,{"y":null,"z":0}]},"b":1}"#);
    }
}
