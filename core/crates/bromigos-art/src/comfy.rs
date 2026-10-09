//! The homelab backend: images, edits, cutouts, upscales, 3D models and video loops made by a
//! ComfyUI server instead of nolgia, for no credits. An asset picks it with its model:
//! `model = "homelab:qwen-image-2.1"`. The graph is a workflow template in this
//! crate (`workflows/`), filled by node id (a video workflow through [`crate::video`]);
//! inputs are uploaded to the server, the job is queued (`POST /prompt`), polled
//! (`GET /history/<id>`) and its PNG, GLB or MP4 downloaded (`GET /view`). An upscale's
//! input may be a clip: it goes up the same way and the workflow reads it with LoadVideo.
//!
//! The server is `BROMIGOS_COMFYUI_URL`, else `comfyui_url` in
//! `$XDG_CONFIG_HOME/bromigos/art.toml`. Neither is in this repo: the address
//! is the user's (the operator's private overlay sets the variable).

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use serde_json::{Map, Value, json};

use crate::Error;
use crate::spec::{Asset, Kind};

/// What marks an asset's model as the homelab's.
pub const PREFIX: &str = "homelab:";

/// The backend name written to the log.
pub const BACKEND: &str = "homelab-comfyui";

/// The workflows built in (`workflows/*.json`); a user's
/// `$XDG_CONFIG_HOME/bromigos/create/workflows/<name>.json` or the packaged
/// `$BROMIGOS_SHARE_DIR/art/workflows/<name>.json` of the same name wins.
pub const BUILTIN: &[(&str, &str)] = &[
    (
        "qwen-image-2.1",
        include_str!("../workflows/qwen-image-2.1.json"),
    ),
    ("lucida", include_str!("../workflows/lucida.json")),
    ("birefnet", include_str!("../workflows/birefnet.json")),
    ("pixal3d", include_str!("../workflows/pixal3d.json")),
    (
        "hunyuan3d-2.1",
        include_str!("../workflows/hunyuan3d-2.1.json"),
    ),
    ("seedvr2-7b", include_str!("../workflows/seedvr2-7b.json")),
    (
        "seedvr2-7b-video",
        include_str!("../workflows/seedvr2-7b-video.json"),
    ),
    (
        "wan2.2-ti2v-5b",
        include_str!("../workflows/wan2.2-ti2v-5b.json"),
    ),
    (
        "wan2.2-i2v-a14b",
        include_str!("../workflows/wan2.2-i2v-a14b.json"),
    ),
];

/// A ComfyUI workflow (API format) and what it declares in its `_meta`: the
/// capabilities it serves, its output, the weights' licence (logged with every
/// job: what may be done with the art depends on it), the model files and nodes it
/// needs, and where the job's values go (`bind`: name -> [node id, input], or a list of
/// them when one value feeds several nodes). The lab's
/// model catalog reads `catalog` (`<model id>/<variant>`), `vram_gib` (the measured peak
/// on its card) and `features` (`i2v`, `t2v`, `flf2v` for video) from the same `_meta`.
#[derive(Debug, Clone)]
pub struct Workflow {
    pub id: String,
    pub(crate) graph: Map<String, Value>,
    pub capabilities: Vec<crate::create::Capability>,
    /// "png", "glb" or "mp4".
    pub output: String,
    pub license: String,
    /// (folder, file) under the server's models dir.
    pub requires: Vec<(String, String)>,
    /// Node classes it needs beyond ComfyUI's own (or any it wants checked).
    pub nodes: Vec<String>,
    /// "qwen-image" (the Qwen-Image fill below), "video" ([`crate::video`]) or "bind".
    pub fill: String,
    /// The model catalog's id for it, `<model>/<variant>`.
    pub catalog: Option<String>,
    /// Its measured peak VRAM on its card (GiB).
    pub vram_gib: Option<f64>,
    /// What it can do beyond its capabilities (`i2v`, `t2v`, `flf2v`).
    pub features: Vec<String>,
    /// Its measured time for a typical job (seconds), when known.
    pub seconds: Option<f64>,
    pub(crate) bind: Map<String, Value>,
    /// The whole `_meta` (a fill's own settings, such as `video`).
    pub(crate) meta: Map<String, Value>,
}

impl Workflow {
    pub fn parse(id: &str, text: &str) -> Result<Workflow, String> {
        let mut graph: Map<String, Value> =
            serde_json::from_str(text).map_err(|e| format!("workflow {id}: {e}"))?;
        graph.remove("_comment");
        let meta = match graph.remove("_meta") {
            Some(Value::Object(m)) => m,
            _ => return Err(format!("workflow {id}: no _meta")),
        };
        let caps = meta
            .get("capabilities")
            .and_then(Value::as_array)
            .ok_or_else(|| format!("workflow {id}: _meta.capabilities is not a list"))?
            .iter()
            .map(|c| {
                c.as_str()
                    .and_then(crate::create::Capability::parse)
                    .ok_or_else(|| format!("workflow {id}: unknown capability {c}"))
            })
            .collect::<Result<Vec<_>, _>>()?;
        let text = |k: &str, d: &str| meta.get(k).and_then(Value::as_str).unwrap_or(d).to_owned();
        let requires = meta
            .get("requires")
            .and_then(Value::as_array)
            .map(|v| {
                v.iter()
                    .filter_map(|r| {
                        Some((
                            r.get("folder")?.as_str()?.to_owned(),
                            r.get("file")?.as_str()?.to_owned(),
                        ))
                    })
                    .collect()
            })
            .unwrap_or_default();
        let strings = |k: &str| -> Vec<String> {
            meta.get(k)
                .and_then(Value::as_array)
                .map(|v| {
                    v.iter()
                        .filter_map(|x| x.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default()
        };
        Ok(Workflow {
            id: id.to_owned(),
            graph,
            capabilities: caps,
            output: text("output", "png"),
            license: text("license", "unknown"),
            requires,
            nodes: strings("nodes"),
            fill: text("fill", "bind"),
            catalog: meta
                .get("catalog")
                .and_then(Value::as_str)
                .map(String::from),
            vram_gib: meta.get("vram_gib").and_then(Value::as_f64),
            features: strings("features"),
            seconds: meta.get("seconds").and_then(Value::as_f64),
            bind: meta
                .get("bind")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default(),
            meta,
        })
    }

    /// Whether an idle ComfyUI is asked to unload its models before the job
    /// (`_meta.unload_first`, see [`unload_if_idle`]).
    pub fn unload_first(&self) -> bool {
        self.meta.get("unload_first").and_then(Value::as_bool) == Some(true)
    }

    /// Whether it makes assets of `kind`.
    pub fn makes(&self, kind: Kind) -> bool {
        self.capabilities.iter().any(|c| c.kind() == kind)
    }
}

fn workflow_dirs() -> Vec<PathBuf> {
    let config = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")));
    let share = std::env::var_os("BROMIGOS_SHARE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/usr/share/bromigos"));
    let mut v = Vec::new();
    if let Some(c) = config {
        v.push(c.join("bromigos/create/workflows"));
    }
    v.push(share.join("art/workflows"));
    v
}

/// The workflow called `id`: the user's, the packaged one, or the built-in.
pub fn workflow(id: &str) -> Result<Workflow, String> {
    if id.is_empty() || id.contains('/') || id.contains("..") {
        return Err(format!("{id:?} is not a workflow name"));
    }
    for d in workflow_dirs() {
        let p = d.join(format!("{id}.json"));
        if let Ok(text) = std::fs::read_to_string(&p) {
            return Workflow::parse(id, &text).map_err(|e| format!("{}: {e}", p.display()));
        }
    }
    match BUILTIN.iter().find(|(n, _)| *n == id) {
        Some((n, t)) => Workflow::parse(n, t),
        None => {
            let known: Vec<&str> = BUILTIN.iter().map(|(n, _)| *n).collect();
            Err(format!(
                "{id} is not a workflow (built in: {}; or add one in {})",
                known.join(", "),
                workflow_dirs()[0].display()
            ))
        }
    }
}

/// Whether `model` names a workflow on the homelab ComfyUI (`homelab:<name>`).
pub fn is_homelab(model: Option<&str>) -> bool {
    model.is_some_and(|m| m.starts_with(PREFIX))
}

/// The workflow an asset names, with or without the `homelab:` prefix.
pub fn lookup(model: &str) -> Result<Workflow, String> {
    workflow(model.strip_prefix(PREFIX).unwrap_or(model))
}

/// Why `a` can't run on a ComfyUI, if it can't.
pub fn check(a: &Asset) -> Result<Workflow, String> {
    let name = a.model.as_deref().unwrap_or("");
    let w = lookup(name)?;
    if !w.makes(a.kind) {
        return Err(format!("{name} can't make a {} asset", a.kind));
    }
    if a.images > 1 || a.outs.len() != 1 {
        return Err(format!("{name} makes one output per asset"));
    }
    if !a.outs[0]
        .to_ascii_lowercase()
        .ends_with(&format!(".{}", w.output))
    {
        return Err(format!(
            "{name} writes {}: out must end in .{}",
            w.output.to_uppercase(),
            w.output
        ));
    }
    if matches!(a.kind, Kind::Image | Kind::Edit) && a.prompt.is_none() {
        return Err(format!("{name} needs a prompt"));
    }
    if matches!(
        a.kind,
        Kind::Edit | Kind::Cutout | Kind::Model3d | Kind::Upscale
    ) && a.inputs.is_empty()
    {
        return Err(format!("a {} needs its image as the first input", a.kind));
    }
    if a.kind == Kind::Upscale {
        // an image workflow (LoadImage) can't read a clip, nor a clip workflow an image
        if let Some(crate::spec::Input::File(f)) = a.inputs.first()
            && is_clip(f) != (w.output == "mp4")
        {
            return Err(if w.output == "mp4" {
                format!("{name} upscales clips: {f} is an image (out .png: image.upscale)")
            } else {
                format!("{name} upscales images: {f} is a clip (out .mp4: video.upscale)")
            });
        }
        upscale_factor(&w, a, None)?;
    }
    if w.fill == "qwen-image" {
        size(a)?;
    }
    if w.fill == "video" {
        crate::video::plan(&w, a, None)?;
    }
    Ok(w)
}

/// The resolution (edge of the square with the same pixel count) an asset is
/// made at: `extra.resolution`, default 1536 (~2.4 MP; the model is native to 2K).
fn resolution(a: &Asset) -> Result<u32, String> {
    match a.extra.get("resolution") {
        None => Ok(1536),
        Some(v) => v
            .as_u64()
            .filter(|r| (512..=2048).contains(r))
            .map(|r| r as u32)
            .ok_or_else(|| "extra.resolution must be a whole number from 512 to 2048".into()),
    }
}

/// Width and height for a new image: the aspect (`W:H`, default 1:1) at the
/// resolution's pixel count, on the 32 px grid the model's encoder uses.
pub fn size(a: &Asset) -> Result<(u32, u32), String> {
    let res = f64::from(resolution(a)?);
    let ratio = match a.aspect.as_deref() {
        None => 1.0,
        Some(s) => {
            let (w, h) = s
                .split_once(':')
                .ok_or_else(|| format!("aspect {s:?} is not W:H"))?;
            let w: f64 = w
                .trim()
                .parse()
                .map_err(|_| format!("aspect {s:?} is not W:H"))?;
            let h: f64 = h
                .trim()
                .parse()
                .map_err(|_| format!("aspect {s:?} is not W:H"))?;
            if !(w > 0.0 && h > 0.0) {
                return Err(format!("aspect {s:?} is not W:H"));
            }
            w / h
        }
    };
    let snap = |v: f64| ((v / 32.0).round() as u32).max(1) * 32;
    Ok((
        snap((res * res * ratio).sqrt()),
        snap((res * res / ratio).sqrt()),
    ))
}

/// Whether a file name is a video clip's (what LoadVideo reads).
pub fn is_clip(name: &str) -> bool {
    let n = name.to_ascii_lowercase();
    [".mp4", ".webm", ".mov", ".mkv", ".m4v"]
        .iter()
        .any(|e| n.ends_with(e))
}

/// A clip's frame size and frame count, from ffprobe (None for an image, or without
/// ffprobe).
fn clip_info(path: &Path) -> Option<(u32, u32, u32)> {
    if !is_clip(&path.to_string_lossy()) {
        return None;
    }
    let o = std::process::Command::new("ffprobe")
        .args(["-v", "error", "-select_streams", "v:0", "-count_packets"])
        .args([
            "-show_entries",
            "stream=width,height,nb_read_packets",
            "-of",
            "csv=p=0",
        ])
        .arg(path)
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&o.stdout);
    let mut f = text.trim().split(',').map(|x| x.trim().parse::<u32>().ok());
    Some((f.next()??, f.next()??, f.next()??))
}

/// A clip's factor within `_meta.upscale.max_megapixel_frames`: every frame of the clip is
/// held in ComfyUI's memory several times over (float RGB: resized, restored, colour-matched;
/// about 66 bytes a pixel-frame on the lab), so the clip's frames times their size is what
/// runs a server out of memory, not one frame's size. `want` lowered to fit, with a line
/// saying so, or why it can't be done at all.
pub fn clip_factor(
    w: &Workflow,
    want: f64,
    (sw, sh, frames): (u32, u32, u32),
) -> Result<(f64, Option<String>), String> {
    let Some(cap) = w
        .meta
        .get("upscale")
        .and_then(|u| u.get("max_megapixel_frames"))
        .and_then(Value::as_f64)
    else {
        return Ok((want, None));
    };
    let mpf = f64::from(sw) * f64::from(sh) * f64::from(frames) / 1e6;
    if mpf * want * want <= cap {
        return Ok((want, None));
    }
    let mut fit = (cap / mpf).sqrt().floor();
    // a whole factor that keeps the frames even-sized (H.264)
    while fit >= 1.0 && ((sw * fit as u32) % 2 == 1 || (sh * fit as u32) % 2 == 1) {
        fit -= 1.0;
    }
    if fit < 1.0 {
        return Err(format!(
            "{frames} frames of {sw}x{sh} are {mpf:.0} megapixel-frames before upscaling, more than {} holds at once ({cap:.0}): trim the clip or split it",
            w.id
        ));
    }
    Ok((
        fit,
        Some(format!(
            "{want}x of {frames} frames of {sw}x{sh} would be {:.0} megapixel-frames, over {}'s {cap:.0}: {fit}x",
            mpf * want * want,
            w.id
        )),
    ))
}

/// An upscale's factor: `extra.scale` (default `_meta.upscale.scale`, at most
/// `_meta.upscale.max_scale`), lowered when the output (a clip's frame) would pass
/// `_meta.upscale.max_megapixels` for an input of size `src`; with a line saying so.
/// A clip's factor is a whole number, and its frames stay even-sized (H.264).
pub fn upscale_factor(
    w: &Workflow,
    a: &Asset,
    src: Option<(u32, u32)>,
) -> Result<(f64, Option<String>), String> {
    let up = w.meta.get("upscale").and_then(Value::as_object);
    let num = |k: &str| up.and_then(|u| u.get(k)).and_then(Value::as_f64);
    let max = num("max_scale").unwrap_or(4.0);
    let clip = w.output == "mp4";
    let want = match a.extra.get("scale") {
        None => num("scale").unwrap_or(2.0),
        Some(v) => v
            .as_f64()
            .filter(|s| (1.0..=max).contains(s))
            .ok_or_else(|| format!("extra.scale must be a number from 1 to {max}"))?,
    };
    if clip && want.fract() != 0.0 {
        return Err(format!(
            "a clip's extra.scale is a whole number (2 to {max})"
        ));
    }
    let Some((sw, sh)) = src else {
        return Ok((want, None));
    };
    let px = f64::from(sw) * f64::from(sh);
    let mut scale = want;
    let mut note = None;
    if let Some(mp) = num("max_megapixels")
        && px * want * want / 1e6 > mp
    {
        let fit = (mp * 1e6 / px).sqrt();
        scale = if clip {
            fit.floor()
        } else {
            (fit * 100.0).floor() / 100.0
        };
        if scale < 1.0 {
            return Err(format!(
                "{sw}x{sh} is {:.1} MP already, more than {} makes ({mp} MP)",
                px / 1e6,
                w.id
            ));
        }
        note = Some(format!(
            "{want}x of {sw}x{sh} would be {:.1} MP, over {}'s {mp} MP: {scale}x",
            px * want * want / 1e6,
            w.id
        ));
    }
    if clip && (sw * scale as u32 % 2 == 1 || sh * scale as u32 % 2 == 1) {
        return Err(format!(
            "{sw}x{sh} at {scale}x is odd-sized, and H.264 wants even sizes: use extra.scale = 2 or 4"
        ));
    }
    Ok((scale, note))
}

/// A seed from the asset's spec, so the same recipe makes the same picture.
pub fn seed(a: &Asset) -> u64 {
    let hex = a.spec.trim_start_matches("sha256:");
    u64::from_str_radix(&hex[..hex.len().min(13)], 16).unwrap_or(0)
}

/// The filled graph for `a`. `images` are the server-side names of its inputs
/// in order (an edit's image first; a video's start frame, then its end frame when
/// it's another image), `mask` the mask's, `src` the first input's pixel size (a
/// video keeps its aspect).
pub fn graph(
    w: &Workflow,
    a: &Asset,
    images: &[String],
    mask: Option<&str>,
    src: Option<(u32, u32)>,
) -> Result<Value, Error> {
    if w.fill == "video" {
        return crate::video::graph(w, a, images, src);
    }
    if w.fill != "qwen-image" {
        return bound(w, a, images, src);
    }
    let mut g = w.graph.clone();
    let res = resolution(a).map_err(Error::Spec)?;
    let set = |g: &mut Map<String, Value>, node: &str, key: &str, v: Value| {
        g[node]["inputs"][key] = v;
    };
    set(
        &mut g,
        "5",
        "prompt",
        json!(a.prompt.clone().unwrap_or_default()),
    );
    set(&mut g, "5", "resolution", json!(res));
    set(&mut g, "7", "seed", json!(seed(a)));
    for (i, name) in images.iter().enumerate() {
        let id = format!("r{}", i + 1);
        g.insert(
            id.clone(),
            json!({"class_type": "LoadImage", "inputs": {"image": name}}),
        );
        set(
            &mut g,
            "5",
            &format!("images.image_{}", i + 1),
            json!([id, 0]),
        );
    }
    match a.kind {
        Kind::Edit => {
            // the encoder's latent is sized to the image being edited
            g.remove("6");
            set(&mut g, "7", "latent_image", json!(["5", 2]));
        }
        _ => {
            let (w, h) = size(a).map_err(Error::Spec)?;
            set(&mut g, "6", "width", json!(w));
            set(&mut g, "6", "height", json!(h));
        }
    }
    if let Some(mask) = mask {
        // transparent in the mask = may change: everywhere else the original
        // is put back, at its own size, so nothing outside the mask moves
        g.insert(
            "m".into(),
            json!({"class_type": "LoadImageMask", "inputs": {"image": mask, "channel": "alpha"}}),
        );
        g.insert(
            "c".into(),
            json!({"class_type": "ImageCompositeMasked", "inputs": {
                "destination": ["r1", 0], "source": ["8", 0], "x": 0, "y": 0,
                "resize_source": true, "mask": ["m", 0]}}),
        );
        set(&mut g, "9", "images", json!(["c", 0]));
    }
    set(
        &mut g,
        "9",
        "filename_prefix",
        json!(format!("bromigos-art/{}", a.id)),
    );
    Ok(Value::Object(g))
}

/// A workflow filled through its `_meta.bind`: `image` (the first input's
/// server-side name), `prompt`, `seed`, `width`/`height` (the asset's size),
/// `scale` (an upscale's factor, [`upscale_factor`] for an input of size `src`),
/// `prefix` (the output's filename prefix); each is `[node id, input name]`, or a
/// list of those when one value goes to several nodes.
fn bound(
    w: &Workflow,
    a: &Asset,
    images: &[String],
    src: Option<(u32, u32)>,
) -> Result<Value, Error> {
    let mut g = w.graph.clone();
    let mut set = |name: &str, v: Value| -> Result<(), Error> {
        let Some(at) = w.bind.get(name) else {
            return Ok(());
        };
        let pair = |x: &Value| {
            Some((
                x.get(0)?.as_str()?.to_owned(),
                x.get(1)?.as_str()?.to_owned(),
            ))
        };
        let targets: Vec<(String, String)> = match pair(at) {
            Some(p) => vec![p],
            None => at
                .as_array()
                .filter(|l| !l.is_empty())
                .and_then(|l| l.iter().map(pair).collect::<Option<Vec<_>>>())
                .ok_or_else(|| {
                    Error::Spec(format!(
                        "workflow {}: bind.{name} is not [node, input] or a list of them",
                        w.id
                    ))
                })?,
        };
        for (node, key) in targets {
            match g
                .get_mut(&node)
                .and_then(|n| n.get_mut("inputs"))
                .and_then(Value::as_object_mut)
            {
                Some(inputs) => {
                    inputs.insert(key, v.clone());
                }
                None => {
                    return Err(Error::Spec(format!(
                        "workflow {}: bind.{name}: no node {node}",
                        w.id
                    )));
                }
            }
        }
        Ok(())
    };
    if let Some(first) = images.first() {
        set("image", json!(first))?;
    }
    if let Some(p) = &a.prompt {
        set("prompt", json!(p))?;
    }
    set("seed", json!(seed(a)))?;
    if w.bind.contains_key("width") {
        let (wd, ht) = size(a).map_err(Error::Spec)?;
        set("width", json!(wd))?;
        set("height", json!(ht))?;
    }
    if w.bind.contains_key("scale") {
        let (scale, _) = upscale_factor(w, a, src).map_err(Error::Spec)?;
        set("scale", json!(scale))?;
    }
    set("prefix", json!(format!("bromigos-art/{}", a.id)))?;
    Ok(Value::Object(g))
}

/// The server's address, from the environment or the user's config.
pub fn endpoint() -> Result<String, Error> {
    if let Ok(u) = std::env::var("BROMIGOS_COMFYUI_URL")
        && !u.trim().is_empty()
    {
        return Ok(u.trim().trim_end_matches('/').to_owned());
    }
    let cfg = config_path();
    if let Some(p) = &cfg
        && let Ok(text) = std::fs::read_to_string(p)
    {
        let t: toml::Table = text
            .parse()
            .map_err(|e| Error::Spec(format!("{}: {e}", p.display())))?;
        if let Some(u) = t.get("comfyui_url").and_then(|v| v.as_str()) {
            return Ok(u.trim().trim_end_matches('/').to_owned());
        }
    }
    Err(Error::Spec(format!(
        "no homelab ComfyUI configured: set BROMIGOS_COMFYUI_URL, or comfyui_url in {}",
        cfg.map_or("~/.config/bromigos/art.toml".into(), |p| p
            .display()
            .to_string())
    )))
}

fn config_path() -> Option<PathBuf> {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("bromigos/art.toml"))
}

/// Whether something listens at the URL's host and port (a TCP connect, at most 1.5 s):
/// a ComfyUI that isn't running is passed over without waiting for an HTTP timeout.
pub fn reachable(url: &str) -> bool {
    use std::net::{TcpStream, ToSocketAddrs};
    let Some((scheme, rest)) = url.split_once("://") else {
        return false;
    };
    let hostport = rest.split('/').next().unwrap_or("");
    let default = if scheme == "https" { 443 } else { 80 };
    let target = if hostport
        .rsplit_once(':')
        .is_some_and(|(_, p)| p.parse::<u16>().is_ok())
    {
        hostport.to_string()
    } else {
        format!("{hostport}:{default}")
    };
    target
        .to_socket_addrs()
        .ok()
        .into_iter()
        .flatten()
        .any(|a| TcpStream::connect_timeout(&a, Duration::from_millis(1500)).is_ok())
}

/// An HTTP client for the server: a plain LAN service, a short connect timeout.
pub fn client() -> Result<reqwest::Client, Error> {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .build()
        .map_err(|e| Error::Homelab(format!("http client: {e}")))
}

fn http(e: reqwest::Error) -> Error {
    // the address is the user's, never logged: only what went wrong
    Error::Homelab(e.without_url().to_string())
}

/// The server's ComfyUI version and free VRAM (GiB), or why it can't be reached.
pub async fn probe(http_client: &reqwest::Client, url: &str) -> Result<(String, f64), Error> {
    let (version, free, _) = stats(http_client, url).await?;
    Ok((version, free))
}

/// The server's ComfyUI version and its first GPU's free and total VRAM (GiB).
pub async fn stats(http_client: &reqwest::Client, url: &str) -> Result<(String, f64, f64), Error> {
    let v = get_json(http_client, &format!("{url}/system_stats")).await?;
    let version = v["system"]["comfyui_version"]
        .as_str()
        .unwrap_or("?")
        .to_owned();
    let gib = |k: &str| v["devices"][0][k].as_f64().unwrap_or(0.0) / f64::from(1u32 << 30);
    Ok((version, gib("vram_free"), gib("vram_total")))
}

async fn get_json(http_client: &reqwest::Client, url: &str) -> Result<Value, Error> {
    http_client
        .get(url)
        .timeout(Duration::from_secs(6))
        .send()
        .await
        .map_err(http)?
        .error_for_status()
        .map_err(http)?
        .json()
        .await
        .map_err(http)
}

/// What a ComfyUI lacks to run a workflow, and its GPU's VRAM.
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct Missing {
    pub version: String,
    pub vram_free_gib: f64,
    pub vram_total_gib: f64,
    /// `folder/file` from `_meta.requires` that the server's model listing lacks. A folder
    /// the server doesn't list (a custom node's own) can't be checked and counts as there.
    pub files: Vec<String>,
    /// Node classes from `_meta.nodes` the server doesn't have.
    pub nodes: Vec<String>,
}

impl Missing {
    /// Everything the workflow needs is on the server.
    pub fn ready(&self) -> bool {
        self.files.is_empty() && self.nodes.is_empty()
    }

    /// Whether the workflow's measured peak fits the card (an unmeasured one does).
    pub fn fits(&self, w: &Workflow) -> bool {
        match w.vram_gib {
            Some(v) if self.vram_total_gib > 0.0 => v <= self.vram_total_gib,
            _ => true,
        }
    }

    /// One line: what's missing, or that it's ready (for `bromigos target probe`).
    pub fn describe(&self, w: &Workflow) -> String {
        let mut parts = Vec::new();
        if !self.files.is_empty() {
            parts.push(format!("missing {}", self.files.join(", ")));
        }
        if !self.nodes.is_empty() {
            parts.push(format!("missing nodes {}", self.nodes.join(", ")));
        }
        if !self.fits(w) {
            parts.push(format!(
                "needs {:.1} GiB, the card has {:.1}",
                w.vram_gib.unwrap_or(0.0),
                self.vram_total_gib
            ));
        }
        if parts.is_empty() {
            let mut s = format!("{} ready", w.id);
            if let Some(v) = w.vram_gib {
                s += &format!(", peak {v:.1} GiB");
            }
            if let Some(t) = w.seconds {
                s += &format!(", ~{t:.0} s a job");
            }
            s
        } else {
            format!("{}: {}", w.id, parts.join("; "))
        }
    }
}

/// Asks the server what it lacks to run `w`: its model folders (`GET /models/<folder>`), its
/// nodes (`GET /object_info/<class>`), its VRAM (`GET /system_stats`). Read-only.
pub async fn missing(
    http_client: &reqwest::Client,
    url: &str,
    w: &Workflow,
) -> Result<Missing, Error> {
    let (version, free, total) = stats(http_client, url).await?;
    let mut m = Missing {
        version,
        vram_free_gib: free,
        vram_total_gib: total,
        ..Default::default()
    };
    let mut listed: std::collections::HashMap<String, Option<Vec<String>>> =
        std::collections::HashMap::new();
    for (folder, file) in &w.requires {
        if !listed.contains_key(folder) {
            let have = get_json(http_client, &format!("{url}/models/{folder}"))
                .await
                .ok()
                .and_then(|v| {
                    v.as_array().map(|a| {
                        a.iter()
                            .filter_map(|x| x.as_str().map(String::from))
                            .collect::<Vec<_>>()
                    })
                });
            listed.insert(folder.clone(), have);
        }
        if let Some(Some(have)) = listed.get(folder)
            && !have.iter().any(|h| h == file)
        {
            m.files.push(format!("{folder}/{file}"));
        }
    }
    for node in &w.nodes {
        let v = get_json(http_client, &format!("{url}/object_info/{node}")).await?;
        if v.get(node).is_none() {
            m.nodes.push(node.clone());
        }
    }
    Ok(m)
}

/// How long [`unload_if_idle`] waits for the free VRAM to rise before it takes it that nothing
/// was loaded.
pub const UNLOAD_SETTLE: Duration = Duration::from_secs(3);

/// Asks an idle ComfyUI to unload its models and free its memory (`POST /free`) and waits until
/// it has; returns the VRAM freed (GiB). A workflow sets `_meta.unload_first` when it sizes
/// its work by the free VRAM: SeedVR2TemporalChunk's auto mode measures the card before the
/// model loads, so a SeedVR2 still resident from the last job left it 8.9 GiB instead of
/// 16.7 and it fell to one frame a chunk, with no temporal context (the lab, 2026-10-09).
///
/// ComfyUI applies `/free` between prompts, so it waits for an idle queue: when another job is
/// queued or running (Pulpo shares the server), nothing is asked and `None` comes back. The
/// worker applies it as soon as it wakes, but a prompt sent in the same instant could run
/// first, so this waits until the free VRAM has risen and held for one more look, or for
/// `settle` without a rise (nothing was loaded).
pub async fn unload_if_idle(
    http_client: &reqwest::Client,
    url: &str,
    settle: Duration,
) -> Result<Option<f64>, Error> {
    let q = get_json(http_client, &format!("{url}/queue")).await?;
    let busy = |k: &str| q[k].as_array().is_some_and(|v| !v.is_empty());
    if busy("queue_running") || busy("queue_pending") {
        return Ok(None);
    }
    let (_, before, _) = stats(http_client, url).await?;
    http_client
        .post(format!("{url}/free"))
        .timeout(Duration::from_secs(10))
        .json(&json!({"unload_models": true, "free_memory": true}))
        .send()
        .await
        .map_err(http)?
        .error_for_status()
        .map_err(http)?;
    let started = Instant::now();
    let mut last = before;
    loop {
        nolgia::tokio::time::sleep(Duration::from_millis(500)).await;
        let (_, free, _) = stats(http_client, url).await?;
        let risen = free > before + 0.25;
        if (risen && (free - last).abs() < 0.05)
            || (!risen && started.elapsed() >= settle)
            || started.elapsed() >= settle * 4
        {
            return Ok(Some((free - before).max(0.0)));
        }
        last = free;
    }
}

/// Uploads one input under `bromigos-art/` and returns its server-side name.
async fn upload(http_client: &reqwest::Client, url: &str, path: &Path) -> Result<String, Error> {
    let bytes = std::fs::read(path).map_err(|e| Error::io(path, e))?;
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "input.png".into());
    // the content's hash in the name: two inputs called the same never collide
    let tag = {
        use sha2::{Digest, Sha256};
        Sha256::digest(&bytes)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>()
    };
    let part = reqwest::multipart::Part::bytes(bytes).file_name(format!("{}-{name}", &tag[..12]));
    let form = reqwest::multipart::Form::new()
        .part("image", part)
        .text("subfolder", "bromigos-art")
        .text("type", "input")
        .text("overwrite", "true");
    let v: Value = http_client
        .post(format!("{url}/upload/image"))
        .multipart(form)
        .send()
        .await
        .map_err(http)?
        .error_for_status()
        .map_err(http)?
        .json()
        .await
        .map_err(http)?;
    let file = v["name"]
        .as_str()
        .ok_or_else(|| Error::Homelab("upload: no name".into()))?;
    Ok(match v["subfolder"].as_str() {
        Some(s) if !s.is_empty() => format!("{s}/{file}"),
        _ => file.to_owned(),
    })
}

/// Makes `a` on the server and writes its output; returns the prompt id.
#[allow(clippy::too_many_arguments)]
pub async fn make(
    http_client: &reqwest::Client,
    url: &str,
    a: &Asset,
    inputs: &[PathBuf],
    mask: Option<&Path>,
    out: &Path,
    wait: Duration,
    say: &dyn Fn(&str),
) -> Result<String, Error> {
    let w = check(a).map_err(Error::Spec)?;
    let mut names = Vec::new();
    for p in inputs {
        names.push(upload(http_client, url, p).await?);
    }
    let mask_name = match mask {
        Some(p) => Some(upload(http_client, url, p).await?),
        None => None,
    };
    let clip = inputs.first().and_then(|p| clip_info(p));
    let src = inputs
        .first()
        .and_then(|p| crate::video::image_size(p))
        .or(clip.map(|(cw, ch, _)| (cw, ch)));
    // an upscale's factor, lowered to what the workflow holds, said when it is
    let mut a = std::borrow::Cow::Borrowed(a);
    if a.kind == Kind::Upscale {
        let (mut scale, mut note) = upscale_factor(&w, &a, src).map_err(Error::Spec)?;
        if let Some(info) = clip {
            let (s2, n2) = clip_factor(&w, scale, info).map_err(Error::Spec)?;
            if n2.is_some() {
                (scale, note) = (s2, n2);
            }
        }
        if let Some(note) = note {
            say(&format!("{}: {note}", a.id));
        }
        a.to_mut().extra.insert("scale".into(), json!(scale));
    }
    let a = a.as_ref();
    let g = graph(&w, a, &names, mask_name.as_deref(), src)?;
    if w.unload_first() {
        match unload_if_idle(http_client, url, UNLOAD_SETTLE).await? {
            Some(gib) if gib >= 0.25 => say(&format!(
                "{}: ComfyUI unloaded its models first ({gib:.1} GiB of VRAM freed)",
                a.id
            )),
            Some(_) => {}
            None => say(&format!(
                "{}: ComfyUI is busy with another job, so its models stay loaded (the clip may \
                 be sampled in shorter chunks)",
                a.id
            )),
        }
    }
    let r: Value = http_client
        .post(format!("{url}/prompt"))
        .json(&json!({"prompt": g, "client_id": "bromigos-art"}))
        .send()
        .await
        .map_err(http)?
        .json()
        .await
        .map_err(http)?;
    if let Some(errs) = r.get("node_errors").and_then(|e| e.as_object())
        && !errs.is_empty()
    {
        return Err(Error::Homelab(format!(
            "the server refused the graph: {}",
            Value::Object(errs.clone())
        )));
    }
    if let Some(e) = r.get("error") {
        return Err(Error::Homelab(format!("the server refused the graph: {e}")));
    }
    let id = r["prompt_id"]
        .as_str()
        .ok_or_else(|| Error::Homelab("no prompt_id in the server's reply".into()))?
        .to_owned();
    say(&format!("{}: queued on ComfyUI ({id})", a.id));
    let started = Instant::now();
    let entry = loop {
        let h: Value = http_client
            .get(format!("{url}/history/{id}"))
            .send()
            .await
            .map_err(http)?
            .json()
            .await
            .map_err(http)?;
        if let Some(e) = h.get(&id)
            && (e["status"]["completed"].as_bool() == Some(true)
                || e["status"]["status_str"] == "error")
        {
            break e.clone();
        }
        if started.elapsed() > wait {
            return Err(Error::Homelab(format!(
                "still running after {} min ({id})",
                wait.as_secs() / 60
            )));
        }
        nolgia::tokio::time::sleep(Duration::from_secs(2)).await;
    };
    if entry["status"]["status_str"] == "error" {
        let msg = entry["status"]["messages"]
            .as_array()
            .and_then(|ms| ms.iter().find(|m| m[0] == "execution_error"))
            .map(|m| {
                m[1]["exception_message"]
                    .as_str()
                    .unwrap_or("")
                    .trim()
                    .to_owned()
            })
            .unwrap_or_else(|| "execution failed".into());
        return Err(Error::Homelab(format!("the job failed: {msg}")));
    }
    let img = output_file(&entry["outputs"], &w.output).ok_or_else(|| {
        Error::Homelab(format!("the job finished without a .{} output", w.output))
    })?;
    let file = img["filename"].as_str().unwrap_or("");
    let bytes = http_client
        .get(format!("{url}/view"))
        .query(&[
            ("filename", file),
            ("subfolder", img["subfolder"].as_str().unwrap_or("")),
            ("type", img["type"].as_str().unwrap_or("output")),
        ])
        .send()
        .await
        .map_err(http)?
        .error_for_status()
        .map_err(http)?
        .bytes()
        .await
        .map_err(http)?;
    if let Some(dir) = out.parent() {
        std::fs::create_dir_all(dir).map_err(|e| Error::io(dir, e))?;
    }
    let tmp = out.with_extension(format!("{}.part", w.output));
    std::fs::write(&tmp, &bytes).map_err(|e| Error::io(&tmp, e))?;
    std::fs::rename(&tmp, out).map_err(|e| Error::io(out, e))?;
    // a pixel-aligned mesh comes out posed as its concept was seen: stand it up
    if w.output == "glb" && w.meta.get("level").and_then(Value::as_bool) == Some(true) {
        match crate::glb::level(out) {
            Ok(Some(deg)) => say(&format!(
                "{}: levelled by {deg:+.1}° (the concept was seen from {})",
                a.id,
                if deg < 0.0 { "above" } else { "below" }
            )),
            Ok(None) => {}
            Err(e) => say(&format!("{}: not levelled ({e})", a.id)),
        }
    }
    Ok(id)
}

/// The first file a job wrote with the extension `ext`, wherever its output
/// node put it (`images` for SaveImage, `3d` and others for the mesh savers). A
/// loader's echo of its input (LoadVideo's preview) and temp previews don't count.
fn output_file<'a>(outputs: &'a Value, ext: &str) -> Option<&'a Value> {
    let want = format!(".{}", ext.to_ascii_lowercase());
    let mut nodes: Vec<(&String, &Value)> = outputs.as_object()?.iter().collect();
    nodes.sort_by(|a, b| a.0.cmp(b.0));
    for (_, node) in nodes {
        for (_, files) in node.as_object()?.iter() {
            for f in files.as_array().into_iter().flatten() {
                if f["filename"]
                    .as_str()
                    .is_some_and(|n| n.to_ascii_lowercase().ends_with(&want))
                    && !matches!(f["type"].as_str(), Some("input" | "temp"))
                {
                    return Some(f);
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spec::World;

    fn world(body: &str) -> World {
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(dir.path().join("art")).unwrap();
        std::fs::write(dir.path().join("art/in.png"), b"png").unwrap();
        std::fs::write(dir.path().join("art/mask.png"), b"png").unwrap();
        std::fs::write(dir.path().join("art.toml"), format!("format = 1\n{body}")).unwrap();
        let w = World::load("t", dir.path()).unwrap();
        std::mem::forget(dir);
        w
    }

    #[test]
    fn sizes_follow_the_aspect_on_the_32px_grid() {
        let w = world(
            "[[assets]]\nid = \"a\"\nkind = \"image\"\nmodel = \"homelab:qwen-image-2.1\"\nprompt = \"x\"\naspect = \"16:9\"\nout = \"art/a.png\"\n",
        );
        let (wd, ht) = size(w.get("a").unwrap()).unwrap();
        assert_eq!((wd % 32, ht % 32), (0, 0));
        assert!((f64::from(wd) / f64::from(ht) - 16.0 / 9.0).abs() < 0.03);
        assert!((f64::from(wd * ht) / (1536.0 * 1536.0) - 1.0).abs() < 0.05);
    }

    #[test]
    fn an_image_keeps_its_empty_latent_and_references_feed_the_encoder() {
        let w = world(
            "[[assets]]\nid = \"a\"\nkind = \"image\"\nmodel = \"homelab:qwen-image-2.1\"\nprompt = \"a lamp\"\ninputs = [\"art/in.png\"]\nout = \"art/a.png\"\n",
        );
        let a = w.get("a").unwrap();
        let g = graph(
            &check(a).unwrap(),
            a,
            &["bromigos-art/in.png".into()],
            None,
            None,
        )
        .unwrap();
        assert_eq!(g["5"]["inputs"]["prompt"], "a lamp");
        assert_eq!(g["5"]["inputs"]["images.image_1"], json!(["r1", 0]));
        assert_eq!(g["r1"]["inputs"]["image"], "bromigos-art/in.png");
        assert_eq!(g["7"]["inputs"]["latent_image"], json!(["6", 0]));
        assert_eq!(g["7"]["inputs"]["seed"], json!(seed(a)));
        assert!(g.get("_comment").is_none());
    }

    #[test]
    fn a_masked_edit_samples_on_the_image_and_puts_the_rest_back() {
        let w = world(
            "[[assets]]\nid = \"e\"\nkind = \"edit\"\nmodel = \"homelab:qwen-image-2.1\"\nprompt = \"remove the fish\"\ninput = \"art/in.png\"\nmask = \"art/mask.png\"\nout = \"art/e.png\"\n",
        );
        let a = w.get("e").unwrap();
        let g = graph(
            &check(a).unwrap(),
            a,
            &["i.png".into()],
            Some("m.png"),
            None,
        )
        .unwrap();
        assert!(g.get("6").is_none());
        assert_eq!(g["7"]["inputs"]["latent_image"], json!(["5", 2]));
        assert_eq!(g["c"]["inputs"]["destination"], json!(["r1", 0]));
        assert_eq!(g["m"]["inputs"]["channel"], "alpha");
        assert_eq!(g["9"]["inputs"]["images"], json!(["c", 0]));
    }

    #[test]
    fn every_builtin_workflow_parses_and_binds_what_it_names() {
        for (id, text) in BUILTIN {
            let w = Workflow::parse(id, text).unwrap();
            for (name, at) in &w.bind {
                let pairs: Vec<&Value> = match at.get(0) {
                    Some(Value::String(_)) => vec![at],
                    _ => at.as_array().unwrap().iter().collect(),
                };
                for p in pairs {
                    let node = p[0].as_str().unwrap();
                    assert!(
                        w.graph.contains_key(node),
                        "{id}: bind.{name} names node {node}, which isn't there"
                    );
                }
            }
            assert!(
                w.graph.values().all(|n| n["class_type"].is_string()),
                "{id}"
            );
        }
    }

    #[test]
    fn an_upscale_binds_its_factor_and_keeps_within_the_workflows_megapixels() {
        let w = world(concat!(
            "[[assets]]\nid = \"u\"\nkind = \"upscale\"\nmodel = \"homelab:seedvr2-7b\"\ninput = \"art/in.png\"\nout = \"art/u.png\"\n",
            "[[assets]]\nid = \"x\"\nkind = \"upscale\"\nmodel = \"homelab:seedvr2-7b\"\ninput = \"art/in.png\"\nout = \"art/x.png\"\nextra = { scale = 3 }\n",
            "[[assets]]\nid = \"bad\"\nkind = \"upscale\"\nmodel = \"homelab:seedvr2-7b\"\ninput = \"art/in.png\"\nout = \"art/b.png\"\nextra = { scale = 9 }\n",
        ));
        let a = w.get("u").unwrap();
        let wf = check(a).unwrap();
        let g = graph(&wf, a, &["in.png".into()], None, Some((640, 640))).unwrap();
        assert_eq!(g["3"]["inputs"]["resize_type.multiplier"], json!(2.0));
        assert_eq!(g["1"]["inputs"]["image"], "in.png");
        assert_eq!(g["9"]["inputs"]["seed"], json!(seed(a)));
        // 3x of 2048x1024 is 18.9 MP: lowered to the workflow's 8.4
        let x = w.get("x").unwrap();
        let (s, note) = upscale_factor(&wf, x, Some((2048, 1024))).unwrap();
        assert!((s - 2.0).abs() < 1e-9, "{s}");
        assert!(note.unwrap().contains("8.4 MP"));
        assert!(
            check(w.get("bad").unwrap())
                .unwrap_err()
                .contains("from 1 to 4")
        );
    }

    #[test]
    fn a_clip_goes_to_the_clip_workflow_and_an_image_to_the_image_one() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(dir.path().join("art")).unwrap();
        std::fs::write(dir.path().join("art/in.png"), b"png").unwrap();
        std::fs::write(dir.path().join("art/loop.mp4"), b"mp4").unwrap();
        std::fs::write(
            dir.path().join("art.toml"),
            concat!(
                "format = 1\n",
                "[[assets]]\nid = \"v\"\nkind = \"upscale\"\nmodel = \"homelab:seedvr2-7b-video\"\ninput = \"art/loop.mp4\"\nout = \"art/v.mp4\"\n",
                "[[assets]]\nid = \"w\"\nkind = \"upscale\"\nmodel = \"homelab:seedvr2-7b\"\ninput = \"art/loop.mp4\"\nout = \"art/w.png\"\n",
                "[[assets]]\nid = \"h\"\nkind = \"upscale\"\nmodel = \"homelab:seedvr2-7b-video\"\ninput = \"art/loop.mp4\"\nout = \"art/h.mp4\"\nextra = { scale = 1.5 }\n",
            ),
        )
        .unwrap();
        let w = World::load("t", dir.path()).unwrap();
        let v = w.get("v").unwrap();
        assert_eq!(
            crate::create::Capability::for_asset(v),
            Some(crate::create::Capability::VideoUpscale)
        );
        let wf = check(v).unwrap();
        let g = graph(
            &wf,
            v,
            &["bromigos-art/loop.mp4".into()],
            None,
            Some((200, 298)),
        )
        .unwrap();
        assert_eq!(g["1"]["inputs"]["file"], "bromigos-art/loop.mp4");
        assert_eq!(g["3"]["inputs"]["resize_type.multiplier"], json!(2.0));
        assert!(
            check(w.get("w").unwrap())
                .unwrap_err()
                .contains("is a clip")
        );
        assert!(
            check(w.get("h").unwrap())
                .unwrap_err()
                .contains("whole number")
        );
        // 3x of an odd-sized clip would be odd-sized
        assert!(upscale_factor(&wf, v, Some((201, 300))).map(|_| ()).is_ok());
        let h3 = {
            let mut a = v.clone();
            a.extra.insert("scale".into(), json!(3));
            a
        };
        assert!(
            upscale_factor(&wf, &h3, Some((201, 300)))
                .unwrap_err()
                .contains("odd")
        );
    }

    #[test]
    fn a_clip_is_held_to_the_workflows_megapixel_frames() {
        let w = workflow("seedvr2-7b-video").unwrap();
        // a small loop: 2x as asked
        assert_eq!(clip_factor(&w, 2.0, (200, 298, 120)).unwrap(), (2.0, None));
        // a 1280x548 loop of 113 frames: 317 megapixel-frames at 2x, too many at 1x already?
        // no: 79 at 1x fits, so it goes through at 1x and says why
        let (s, note) = clip_factor(&w, 2.0, (1280, 548, 113)).unwrap();
        assert_eq!(s, 1.0);
        assert!(note.unwrap().contains("megapixel-frames"));
        // a long 1080p clip can't be held at all
        assert!(
            clip_factor(&w, 2.0, (1920, 1080, 240))
                .unwrap_err()
                .contains("trim the clip")
        );
    }

    #[test]
    fn one_seed_can_feed_several_samplers() {
        let w = world(
            "[[assets]]\nid = \"m\"\nkind = \"model3d\"\nmodel = \"homelab:pixal3d\"\ninput = \"art/in.png\"\nout = \"art/m.glb\"\n",
        );
        let a = w.get("m").unwrap();
        let g = graph(&check(a).unwrap(), a, &["in.png".into()], None, None).unwrap();
        for n in ["15", "21", "23"] {
            assert_eq!(g[n]["inputs"]["seed"], json!(seed(a)), "{n}");
        }
        assert_eq!(g["26"]["inputs"]["filename_prefix"], "bromigos-art/m");
    }

    #[test]
    fn a_loaders_echo_of_its_input_is_not_the_output() {
        let outs = json!({
            "1": {"images": [{"filename": "loop.mp4", "subfolder": "bromigos-art", "type": "input"}]},
            "15": {"images": [{"filename": "bromigos-art_00001_.mp4", "subfolder": "", "type": "output"}]}
        });
        assert_eq!(
            output_file(&outs, "mp4").unwrap()["filename"],
            "bromigos-art_00001_.mp4"
        );
    }

    #[test]
    fn what_the_homelab_cannot_make_is_refused() {
        let w = world(concat!(
            "[[assets]]\nid = \"v\"\nkind = \"video\"\nmodel = \"homelab:qwen-image-2.1\"\nprompt = \"x\"\nstart = \"art/in.png\"\nduration = 5\nout = \"art/v.mp4\"\n",
            "[[assets]]\nid = \"j\"\nkind = \"image\"\nmodel = \"homelab:qwen-image-2.1\"\nprompt = \"x\"\nout = \"art/j.jpg\"\n",
            "[[assets]]\nid = \"u\"\nkind = \"image\"\nmodel = \"homelab:nope\"\nprompt = \"x\"\nout = \"art/u.png\"\n",
        ));
        assert!(
            check(w.get("v").unwrap())
                .unwrap_err()
                .contains("can't make a video")
        );
        assert!(check(w.get("j").unwrap()).unwrap_err().contains("PNG"));
        assert!(
            check(w.get("u").unwrap())
                .unwrap_err()
                .contains("not a workflow")
        );
    }
}
