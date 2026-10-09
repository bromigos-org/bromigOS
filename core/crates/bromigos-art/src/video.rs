//! The `video` fill: a ComfyUI video workflow (`_meta.fill = "video"`) filled from a
//! `kind = "video"` asset. Nothing here names a model: what is model-specific lives in the
//! workflow's `_meta` (docs/art.md, "Video loops on a ComfyUI"), so the lab's model catalog
//! can rank and swap them:
//!
//! - `_meta.video`: `fps` (what the model was trained at), `frame_step` (a clip is
//!   `1 + frame_step × k` frames), `max_frames`, `grid` (width and height multiples), `sizes`
//!   (each resolution tier's pixel count), `resolution` (the default tier) and `end_frame`:
//!   how the model ends on a frame: `"native"` (an end-image input), `"latent"` (the end
//!   image's latent chunk placed last, clean; its decoded frames dropped) or `"none"`.
//! - `_meta.bind`: where each value goes, `[node, input]` (or a list of them): `image`,
//!   `prompt`, `negative`, `seed`, `steps`, `cfg`, `width`, `height`, `length`, `fps`,
//!   `prefix`, `end_input` (native end frames); and the links the loop is spliced into,
//!   `[node, output]`: `vae`, `latent` (the video latent) with `latent_input` (where the
//!   sampler reads it), `frames` (the decoded images) with `frames_input` (where the video
//!   is made from them).
//!
//! A loop (`loop = true`) ends on its start frame where the model can (`end_frame`), like
//! nolgia's end-frame loops: the clip's last frame lands next to its first, and the world's
//! post step (theme/tools/glow-loop.py) cuts at the wrap. `extra.loop_mode = "crossfade"`
//! (the default for a model with `end_frame = "none"`) instead generates `seam` frames more
//! and crossfades the tail into the head, then repeats the first frame at the end, so the
//! same post step finds the wrap there.

use serde_json::{Map, Value, json};

use crate::Error;
use crate::comfy::{self, Workflow};
use crate::spec::Asset;

/// The `extra` keys the video fill reads; any other is a mistake (a typo would otherwise
/// change the spec and nothing else).
pub const EXTRA_KEYS: &[&str] = &[
    "fps",
    "seed",
    "steps",
    "cfg",
    "negative",
    "loop_mode",
    "seam",
];

/// How a clip comes back to where it started.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// A plain clip from its start frame.
    Open,
    /// It ends on its end frame (the start frame, for a loop).
    EndFrame,
    /// Its tail is crossfaded into its head.
    Crossfade,
}

/// How a model ends on a frame.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EndFrame {
    Native,
    Latent,
    None,
}

/// A workflow's `_meta.video`.
#[derive(Debug, Clone)]
pub struct Settings {
    pub fps: u32,
    pub frame_step: u32,
    pub max_frames: u32,
    pub grid: u32,
    /// (tier, pixel count), the largest first.
    pub sizes: Vec<(String, u32)>,
    pub resolution: String,
    pub end_frame: EndFrame,
}

impl Settings {
    pub fn of(w: &Workflow) -> Result<Settings, String> {
        let v = w
            .meta
            .get("video")
            .and_then(Value::as_object)
            .ok_or_else(|| format!("workflow {}: no _meta.video", w.id))?;
        let num = |k: &str, d: u64| -> Result<u32, String> {
            match v.get(k) {
                None => Ok(d as u32),
                Some(x) => x
                    .as_u64()
                    .filter(|n| *n > 0 && *n < 100_000)
                    .map(|n| n as u32)
                    .ok_or_else(|| format!("workflow {}: _meta.video.{k} is not a count", w.id)),
            }
        };
        let mut sizes: Vec<(String, u32)> = v
            .get("sizes")
            .and_then(Value::as_object)
            .map(|m| {
                m.iter()
                    .filter_map(|(k, n)| Some((k.clone(), n.as_u64()? as u32)))
                    .collect()
            })
            .unwrap_or_default();
        if sizes.is_empty() {
            return Err(format!("workflow {}: _meta.video.sizes is empty", w.id));
        }
        sizes.sort_by_key(|s| std::cmp::Reverse(s.1)); // the largest first
        let resolution = v
            .get("resolution")
            .and_then(Value::as_str)
            .map(String::from)
            .unwrap_or_else(|| sizes[0].0.clone());
        let end_frame = match v.get("end_frame").and_then(Value::as_str).unwrap_or("none") {
            "native" => EndFrame::Native,
            "latent" => EndFrame::Latent,
            "none" => EndFrame::None,
            o => return Err(format!("workflow {}: _meta.video.end_frame {o:?}", w.id)),
        };
        Ok(Settings {
            fps: num("fps", 24)?,
            frame_step: num("frame_step", 4)?,
            max_frames: num("max_frames", 121)?,
            grid: num("grid", 16)?,
            sizes,
            resolution,
            end_frame,
        })
    }
}

/// What one job makes.
#[derive(Debug, Clone, PartialEq)]
pub struct Plan {
    pub width: u32,
    pub height: u32,
    pub fps: u32,
    /// Frames the model generates (`1 + frame_step × k`).
    pub frames: u32,
    /// Frames the video is made from, after the loop's splice.
    pub keep: u32,
    pub mode: Mode,
    /// Crossfaded frames (crossfade mode).
    pub seam: u32,
    pub seed: u64,
}

fn extra_u32(a: &Asset, k: &str, lo: u32, hi: u32) -> Result<Option<u32>, String> {
    match a.extra.get(k) {
        None => Ok(None),
        Some(v) => v
            .as_u64()
            .filter(|n| (u64::from(lo)..=u64::from(hi)).contains(n))
            .map(|n| Some(n as u32))
            .ok_or_else(|| format!("extra.{k} must be a whole number from {lo} to {hi}")),
    }
}

/// The aspect `W:H` as a ratio.
fn ratio(s: &str) -> Result<f64, String> {
    let bad = || format!("aspect {s:?} is not W:H");
    let (w, h) = s.split_once(':').ok_or_else(bad)?;
    let w: f64 = w.trim().parse().map_err(|_| bad())?;
    let h: f64 = h.trim().parse().map_err(|_| bad())?;
    if !(w > 0.0 && h > 0.0) {
        return Err(bad());
    }
    Ok(w / h)
}

/// What `a` makes on `w`. `src` is the start frame's size, when known: without an aspect
/// the clip keeps the still's (16:9 when neither is known).
pub fn plan(w: &Workflow, a: &Asset, src: Option<(u32, u32)>) -> Result<Plan, String> {
    let s = Settings::of(w)?;
    if let Some(k) = a.extra.keys().find(|k| !EXTRA_KEYS.contains(&k.as_str())) {
        return Err(format!(
            "{}: extra.{k} isn't a video option ({})",
            w.id,
            EXTRA_KEYS.join(", ")
        ));
    }
    let fps = extra_u32(a, "fps", 1, 60)?.unwrap_or(s.fps);
    let tier = a.resolution.clone().unwrap_or_else(|| s.resolution.clone());
    let px = s
        .sizes
        .iter()
        .find(|(t, _)| *t == tier)
        .map(|(_, n)| f64::from(*n))
        .ok_or_else(|| {
            format!(
                "{} makes {} (resolution = \"{tier}\" isn't one)",
                w.id,
                s.sizes
                    .iter()
                    .map(|(t, _)| t.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        })?;
    let r = match (&a.aspect, src) {
        (Some(asp), _) => ratio(asp)?,
        (None, Some((sw, sh))) if sw > 0 && sh > 0 => f64::from(sw) / f64::from(sh),
        _ => 16.0 / 9.0,
    };
    let g = f64::from(s.grid);
    let snap = |v: f64| ((v / g).round() as u32).max(1) * s.grid;
    let (width, height) = (snap((px * r).sqrt()), snap((px / r).sqrt()));
    let duration = a.duration.ok_or("a video needs duration (seconds)")?;
    let base = duration * fps;
    if base == 0 {
        return Err("duration must be at least 1 second".into());
    }
    let has_end = a.end.is_some();
    let mode = match a.extra.get("loop_mode").map(|v| v.as_str()) {
        None if a.looped && s.end_frame == EndFrame::None => Mode::Crossfade,
        None if has_end => Mode::EndFrame,
        None => Mode::Open,
        Some(Some("end-frame")) => Mode::EndFrame,
        Some(Some("crossfade")) => Mode::Crossfade,
        Some(_) => return Err("extra.loop_mode is \"end-frame\" or \"crossfade\"".into()),
    };
    if mode == Mode::EndFrame && !has_end {
        return Err("loop_mode = \"end-frame\" needs loop = true or an end frame".into());
    }
    if mode == Mode::EndFrame && s.end_frame == EndFrame::None {
        return Err(format!(
            "{} can't end on a frame: use extra.loop_mode = \"crossfade\" for a loop",
            w.id
        ));
    }
    if mode == Mode::Crossfade && !a.looped {
        return Err("loop_mode = \"crossfade\" makes a loop: it needs loop = true".into());
    }
    let seam = match mode {
        Mode::Crossfade => extra_u32(a, "seam", 1, (base / 3).max(1))?
            .unwrap_or_else(|| (fps / 2).clamp(1, (base / 3).max(1))),
        _ => {
            if a.extra.contains_key("seam") {
                return Err("extra.seam is for loop_mode = \"crossfade\"".into());
            }
            0
        }
    };
    let step = s.frame_step;
    let want = match (mode, s.end_frame) {
        (Mode::EndFrame, EndFrame::Latent) => base + step + 1,
        (Mode::Crossfade, _) => base + seam + 1,
        _ => base + 1,
    };
    let frames = 1 + step * (want - 1).div_ceil(step);
    if frames > s.max_frames {
        return Err(format!(
            "{} makes at most {} frames: {duration} s at {fps} fps is {frames}",
            w.id, s.max_frames
        ));
    }
    let keep = match (mode, s.end_frame) {
        (Mode::EndFrame, EndFrame::Latent) => frames - step,
        (Mode::Crossfade, _) => frames - seam + 1,
        _ => frames,
    };
    let seed = match a.extra.get("seed") {
        None => comfy::seed(a),
        Some(v) => v.as_u64().ok_or("extra.seed must be a whole number")?,
    };
    Ok(Plan {
        width,
        height,
        fps,
        frames,
        keep,
        mode,
        seam,
        seed,
    })
}

/// A bind's places (`[node, input]`, or a list of them).
fn places(at: &Value) -> Vec<(String, String)> {
    let one = |v: &Value| -> Option<(String, String)> {
        Some((
            v.get(0)?.as_str()?.to_owned(),
            v.get(1)?.as_str()?.to_owned(),
        ))
    };
    match at.get(0) {
        Some(Value::Array(_)) => at
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(one)
            .collect(),
        _ => one(at).into_iter().collect(),
    }
}

struct Fill<'a> {
    w: &'a Workflow,
    g: Map<String, Value>,
}

impl Fill<'_> {
    /// Sets the value at every place `name` is bound; an unbound name is skipped.
    fn set(&mut self, name: &str, v: Value) -> Result<(), Error> {
        let Some(at) = self.w.bind.get(name) else {
            return Ok(());
        };
        let ps = places(at);
        if ps.is_empty() {
            return Err(Error::Spec(format!(
                "workflow {}: bind.{name} is not [node, input]",
                self.w.id
            )));
        }
        for (node, key) in ps {
            match self
                .g
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
                        self.w.id
                    )));
                }
            }
        }
        Ok(())
    }

    /// A node output the workflow names (`[node, output]`).
    fn link(&self, name: &str) -> Result<Value, Error> {
        let at = self.w.bind.get(name);
        match at.and_then(|v| Some((v.get(0)?.as_str()?, v.get(1)?.as_u64()?))) {
            Some((node, out)) if self.g.contains_key(node) => Ok(json!([node, out])),
            _ => Err(Error::Spec(format!(
                "workflow {}: a loop needs bind.{name} = [node, output]",
                self.w.id
            ))),
        }
    }

    fn need(&self, name: &str) -> Result<(), Error> {
        if self.w.bind.contains_key(name) {
            Ok(())
        } else {
            Err(Error::Spec(format!(
                "workflow {}: a loop needs bind.{name}",
                self.w.id
            )))
        }
    }

    fn node(&mut self, id: &str, class: &str, inputs: Value) {
        self.g
            .insert(id.into(), json!({"class_type": class, "inputs": inputs}));
    }
}

/// The filled graph for `a`: `images` are the server-side names of its start frame and, when
/// it has a different one, its end frame; `src` the start frame's size.
pub fn graph(
    w: &Workflow,
    a: &Asset,
    images: &[String],
    src: Option<(u32, u32)>,
) -> Result<Value, Error> {
    let p = plan(w, a, src).map_err(Error::Spec)?;
    let s = Settings::of(w).map_err(Error::Spec)?;
    let mut f = Fill {
        w,
        g: w.graph.clone(),
    };
    let start = images
        .first()
        .ok_or_else(|| Error::Spec("a video needs its start frame".into()))?;
    f.set("image", json!(start))?;
    if let Some(prompt) = &a.prompt {
        f.set("prompt", json!(prompt))?;
    }
    if let Some(n) = a.extra.get("negative") {
        f.set("negative", n.clone())?;
    }
    f.set("seed", json!(p.seed))?;
    if let Some(n) = a.extra.get("steps") {
        let n = n
            .as_u64()
            .filter(|n| (1..=200).contains(n))
            .ok_or_else(|| Error::Spec("extra.steps must be 1 to 200".into()))?;
        f.set("steps", json!(n))?;
    }
    if let Some(c) = a.extra.get("cfg") {
        let c = c
            .as_f64()
            .filter(|c| (0.0..=30.0).contains(c))
            .ok_or_else(|| Error::Spec("extra.cfg must be a number from 0 to 30".into()))?;
        f.set("cfg", json!(c))?;
    }
    f.set("width", json!(p.width))?;
    f.set("height", json!(p.height))?;
    f.set("length", json!(p.frames))?;
    f.set("fps", json!(f64::from(p.fps)))?;
    f.set("prefix", json!(format!("bromigos-art/{}", a.id)))?;
    // the start frame's loader: the end frame reuses it when they're the same image
    let loader = w
        .bind
        .get("image")
        .map(places)
        .and_then(|v| v.into_iter().next())
        .map(|(n, _)| n)
        .ok_or_else(|| Error::Spec(format!("workflow {}: no bind.image", w.id)))?;
    let end_link = |f: &mut Fill| -> Value {
        match images.get(1) {
            Some(end) if end != start => {
                f.node("bv_end", "LoadImage", json!({"image": end}));
                json!(["bv_end", 0])
            }
            _ => json!([loader, 0]),
        }
    };
    match (p.mode, s.end_frame) {
        (Mode::EndFrame, EndFrame::Native) => {
            f.need("end_input")?;
            let end = end_link(&mut f);
            f.set("end_input", end)?;
        }
        (Mode::EndFrame, EndFrame::Latent) => {
            for k in ["latent_input", "frames_input"] {
                f.need(k)?;
            }
            let (vae, latent, frames) = (f.link("vae")?, f.link("latent")?, f.link("frames")?);
            let end = end_link(&mut f);
            let t = (p.frames - 1) / s.frame_step + 1;
            // the end image held for frame_step + 1 frames: its second latent is a whole
            // chunk of it, placed last and kept clean (noise mask 0 there and at the start)
            f.node(
                "bv_scale",
                "ImageScale",
                json!({"image": end, "upscale_method": "bilinear", "width": p.width,
                       "height": p.height, "crop": "center"}),
            );
            f.node(
                "bv_hold",
                "RepeatImageBatch",
                json!({"image": ["bv_scale", 0], "amount": s.frame_step + 1}),
            );
            f.node(
                "bv_enc",
                "VAEEncode",
                json!({"pixels": ["bv_hold", 0], "vae": vae}),
            );
            f.node(
                "bv_chunk",
                "LatentCut",
                json!({"samples": ["bv_enc", 0], "dim": "t", "index": 1, "amount": 1}),
            );
            f.node(
                "bv_place",
                "ReplaceVideoLatentFrames",
                json!({"destination": latent, "source": ["bv_chunk", 0], "index": -1}),
            );
            f.node(
                "bv_m0",
                "EmptyImage",
                json!({"width": 8, "height": 8, "batch_size": 1, "color": 0}),
            );
            f.node(
                "bv_m1",
                "EmptyImage",
                json!({"width": 8, "height": 8, "batch_size": t - 2, "color": 0xFF_FFFF}),
            );
            f.node(
                "bv_m2",
                "ImageBatch",
                json!({"image1": ["bv_m0", 0], "image2": ["bv_m1", 0]}),
            );
            f.node(
                "bv_m3",
                "ImageBatch",
                json!({"image1": ["bv_m2", 0], "image2": ["bv_m0", 0]}),
            );
            f.node(
                "bv_mask",
                "ImageToMask",
                json!({"image": ["bv_m3", 0], "channel": "red"}),
            );
            f.node(
                "bv_noise",
                "SetLatentNoiseMask",
                json!({"samples": ["bv_place", 0], "mask": ["bv_mask", 0]}),
            );
            f.set("latent_input", json!(["bv_noise", 0]))?;
            // the frames that chunk decodes to are the still, not the motion: dropped
            f.node(
                "bv_keep",
                "ImageFromBatch",
                json!({"image": frames, "batch_index": 0, "length": p.keep}),
            );
            f.set("frames_input", json!(["bv_keep", 0]))?;
        }
        (Mode::Crossfade, _) => {
            f.need("frames_input")?;
            let frames = f.link("frames")?;
            let k = p.seam;
            f.node(
                "bv_tail",
                "ImageFromBatch",
                json!({"image": frames, "batch_index": k, "length": 4096}),
            );
            f.node(
                "bv_head",
                "ImageFromBatch",
                json!({"image": frames, "batch_index": 0, "length": k}),
            );
            // f[k..N-k], then f[N-k+i] fading into f[i]: it ends next to f[k], where it began
            f.node(
                "bv_seam",
                "CrossFadeImages",
                json!({"images_1": ["bv_tail", 0], "images_2": ["bv_head", 0],
                       "interpolation": "linear", "transition_start_index": -i64::from(k),
                       "transitioning_frames": k, "start_level": 0.0, "end_level": 1.0}),
            );
            f.node(
                "bv_first",
                "ImageFromBatch",
                json!({"image": ["bv_seam", 0], "batch_index": 0, "length": 1}),
            );
            f.node(
                "bv_loop",
                "ImageBatch",
                json!({"image1": ["bv_seam", 0], "image2": ["bv_first", 0]}),
            );
            f.set("frames_input", json!(["bv_loop", 0]))?;
        }
        _ => {}
    }
    Ok(Value::Object(f.g))
}

/// The pixel size of a PNG, JPEG or WebP (its header only), for a start frame's aspect.
pub fn image_size(path: &std::path::Path) -> Option<(u32, u32)> {
    use std::io::Read;
    let mut head = Vec::new();
    std::fs::File::open(path)
        .ok()?
        .take(1 << 20)
        .read_to_end(&mut head)
        .ok()?;
    let be32 = |b: &[u8]| u32::from_be_bytes([b[0], b[1], b[2], b[3]]);
    let be16 = |b: &[u8]| u32::from(u16::from_be_bytes([b[0], b[1]]));
    let le16 = |b: &[u8]| u32::from(u16::from_le_bytes([b[0], b[1]]));
    if head.len() >= 24 && head.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Some((be32(&head[16..20]), be32(&head[20..24])));
    }
    if head.len() >= 30 && head.starts_with(b"RIFF") && &head[8..12] == b"WEBP" {
        return match &head[12..16] {
            b"VP8X" => Some((
                1 + (le16(&head[24..26]) | (u32::from(head[26]) << 16)),
                1 + (le16(&head[27..29]) | (u32::from(head[29]) << 16)),
            )),
            b"VP8 " => Some((le16(&head[26..28]) & 0x3fff, le16(&head[28..30]) & 0x3fff)),
            b"VP8L" => {
                let b = &head[21..25];
                let bits = u32::from_le_bytes([b[0], b[1], b[2], b[3]]);
                Some((1 + (bits & 0x3fff), 1 + ((bits >> 14) & 0x3fff)))
            }
            _ => None,
        };
    }
    if head.starts_with(&[0xFF, 0xD8]) {
        let mut i = 2;
        while i + 9 < head.len() {
            if head[i] != 0xFF {
                i += 1;
                continue;
            }
            let marker = head[i + 1];
            let len = be16(&head[i + 2..i + 4]) as usize;
            // SOF0..SOF15, except DHT (C4), JPG (C8) and DAC (CC)
            if (0xC0..=0xCF).contains(&marker) && ![0xC4, 0xC8, 0xCC].contains(&marker) {
                return Some((be16(&head[i + 7..i + 9]), be16(&head[i + 5..i + 7])));
            }
            i += 2 + len;
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
        std::fs::write(dir.path().join("art/end.png"), b"png").unwrap();
        std::fs::write(dir.path().join("art.toml"), format!("format = 1\n{body}")).unwrap();
        let w = World::load("t", dir.path()).unwrap();
        std::mem::forget(dir);
        w
    }

    fn asset(model: &str, more: &str) -> (Workflow, Asset) {
        let duration = if more.contains("duration") {
            ""
        } else {
            "duration = 5\n"
        };
        let w = world(&format!(
            "[[assets]]\nid = \"v\"\nkind = \"video\"\nmodel = \"homelab:{model}\"\nprompt = \"it pulses\"\nstart = \"art/in.png\"\n{duration}out = \"art/v.mp4\"\n{more}"
        ));
        let a = w.get("v").unwrap().clone();
        (comfy::lookup(model).unwrap(), a)
    }

    fn class(g: &Value, id: &str) -> String {
        g[id]["class_type"].as_str().unwrap_or("").to_string()
    }

    #[test]
    fn a_5b_loop_ends_on_its_start_frame_through_the_latent() {
        let (w, a) = asset("wan2.2-ti2v-5b", "loop = true\naspect = \"2:3\"\n");
        assert_eq!(w.catalog.as_deref(), Some("wan2.2-ti2v-5b/fp16"));
        assert!(w.features.iter().any(|f| f == "flf2v"));
        let p = plan(&w, &a, None).unwrap();
        // 5 s at 24 fps, plus the end chunk's 4 frames (dropped) and the start frame
        assert_eq!((p.frames, p.keep, p.mode), (125, 121, Mode::EndFrame));
        assert_eq!((p.width, p.height), (768, 1152));
        assert_eq!((p.width % 32, p.height % 32), (0, 0));
        let g = graph(&w, &a, &["bromigos-art/in.png".into()], None).unwrap();
        assert_eq!(g["7"]["inputs"]["image"], "bromigos-art/in.png");
        assert_eq!(g["4"]["inputs"]["text"], "it pulses");
        assert_eq!(g["8"]["inputs"]["length"], 125);
        assert_eq!(g["9"]["inputs"]["seed"], json!(comfy::seed(&a)));
        // the end frame is the start frame's own loader, held, encoded, its chunk placed last
        assert_eq!(g["bv_scale"]["inputs"]["image"], json!(["7", 0]));
        assert!(g.get("bv_end").is_none());
        assert_eq!(g["bv_hold"]["inputs"]["amount"], 5);
        assert_eq!(g["bv_chunk"]["inputs"]["index"], 1);
        assert_eq!(g["bv_place"]["inputs"]["destination"], json!(["8", 0]));
        assert_eq!(g["bv_place"]["inputs"]["index"], -1);
        // 32 latent frames: clean first and last, the 30 between generated
        assert_eq!(g["bv_m1"]["inputs"]["batch_size"], 30);
        assert_eq!(g["9"]["inputs"]["latent_image"], json!(["bv_noise", 0]));
        assert_eq!(g["bv_keep"]["inputs"]["length"], 121);
        assert_eq!(g["11"]["inputs"]["images"], json!(["bv_keep", 0]));
        assert_eq!(g["11"]["inputs"]["fps"], json!(24.0));
        assert_eq!(g["12"]["inputs"]["filename_prefix"], "bromigos-art/v");
        assert!(g.get("_meta").is_none() && g.get("_comment").is_none());
    }

    #[test]
    fn the_still_sets_the_aspect_and_options_reach_their_nodes() {
        let (w, a) = asset(
            "wan2.2-ti2v-5b",
            "loop = true\nresolution = \"480p\"\nextra = { fps = 16, seed = 7, steps = 30, cfg = 6.0 }\n",
        );
        let p = plan(&w, &a, Some((1536, 2304))).unwrap();
        assert_eq!((p.width, p.height), (512, 768));
        assert_eq!((p.fps, p.frames, p.seed), (16, 85, 7));
        let g = graph(&w, &a, &["s.png".into()], Some((2560, 1440))).unwrap();
        assert_eq!(
            (&g["8"]["inputs"]["width"], &g["8"]["inputs"]["height"]),
            (&json!(832), &json!(480))
        );
        assert_eq!(g["9"]["inputs"]["steps"], 30);
        assert_eq!(g["9"]["inputs"]["cfg"], 6.0);
        assert_eq!(g["9"]["inputs"]["seed"], 7);
        assert_eq!(g["11"]["inputs"]["fps"], json!(16.0));
    }

    #[test]
    fn an_open_clip_and_a_crossfaded_loop() {
        let (w, a) = asset("wan2.2-ti2v-5b", "");
        let p = plan(&w, &a, None).unwrap();
        assert_eq!((p.frames, p.keep, p.mode), (121, 121, Mode::Open));
        let g = graph(&w, &a, &["s.png".into()], None).unwrap();
        assert_eq!(g["9"]["inputs"]["latent_image"], json!(["8", 0]));
        assert_eq!(g["11"]["inputs"]["images"], json!(["10", 0]));
        assert!(!g.as_object().unwrap().keys().any(|k| k.starts_with("bv_")));

        let (w, a) = asset(
            "wan2.2-ti2v-5b",
            "loop = true\nextra = { loop_mode = \"crossfade\", seam = 12 }\n",
        );
        let p = plan(&w, &a, None).unwrap();
        // 120 frames of loop + 12 to fade + 1, on the 4k + 1 grid; then the first frame again
        assert_eq!((p.frames, p.seam, p.keep), (133, 12, 122));
        let g = graph(&w, &a, &["s.png".into()], None).unwrap();
        assert_eq!(class(&g, "bv_seam"), "CrossFadeImages");
        assert_eq!(g["bv_tail"]["inputs"]["batch_index"], 12);
        assert_eq!(g["bv_seam"]["inputs"]["transition_start_index"], -12);
        assert_eq!(g["11"]["inputs"]["images"], json!(["bv_loop", 0]));
        assert_eq!(g["9"]["inputs"]["latent_image"], json!(["8", 0]));
    }

    #[test]
    fn the_14b_ends_on_a_frame_natively() {
        let (w, a) = asset("wan2.2-i2v-a14b", "loop = true\n");
        let p = plan(&w, &a, Some((1280, 720))).unwrap();
        assert_eq!((p.fps, p.frames, p.keep), (16, 81, 81));
        assert_eq!((p.width % 16, p.height % 16), (0, 0));
        let g = graph(&w, &a, &["s.png".into()], Some((1280, 720))).unwrap();
        assert_eq!(g["10"]["inputs"]["end_image"], json!(["9", 0]));
        assert_eq!(
            g["11"]["inputs"]["noise_seed"],
            g["12"]["inputs"]["noise_seed"]
        );
        assert_eq!(g["10"]["inputs"]["length"], 81);
        // a different end frame gets its own loader
        let (w, a) = asset("wan2.2-i2v-a14b", "end = \"art/end.png\"\n");
        let g = graph(&w, &a, &["s.png".into(), "e.png".into()], None).unwrap();
        assert_eq!(g["bv_end"]["inputs"]["image"], "e.png");
        assert_eq!(g["10"]["inputs"]["end_image"], json!(["bv_end", 0]));
    }

    #[test]
    fn what_a_model_cannot_do_is_refused() {
        let (w, a) = asset("wan2.2-ti2v-5b", "loop = true\nduration = 9\n");
        assert!(
            plan(&w, &a, None)
                .unwrap_err()
                .contains("at most 193 frames")
        );
        // and before anything is uploaded: `bromigos art plan` says so
        assert!(comfy::check(&a).unwrap_err().contains("at most 193 frames"));
        let (w, a) = asset("wan2.2-ti2v-5b", "loop = true\nresolution = \"1080p\"\n");
        assert!(plan(&w, &a, None).unwrap_err().contains("720p, 480p"));
        let (w, a) = asset("wan2.2-ti2v-5b", "loop = true\nextra = { fsp = 24 }\n");
        assert!(plan(&w, &a, None).unwrap_err().contains("extra.fsp"));
        let (w, a) = asset("wan2.2-ti2v-5b", "extra = { loop_mode = \"crossfade\" }\n");
        assert!(plan(&w, &a, None).unwrap_err().contains("loop = true"));
        let (w, a) = asset("wan2.2-ti2v-5b", "extra = { loop_mode = \"end-frame\" }\n");
        assert!(plan(&w, &a, None).unwrap_err().contains("end frame"));
    }

    #[test]
    fn image_headers() {
        let dir = tempfile::tempdir().unwrap();
        let png = dir.path().join("a.png");
        let mut b = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR".to_vec();
        b.extend(1536u32.to_be_bytes());
        b.extend(2304u32.to_be_bytes());
        b.extend([8, 2, 0, 0, 0]);
        std::fs::write(&png, &b).unwrap();
        assert_eq!(image_size(&png), Some((1536, 2304)));
        let jpg = dir.path().join("a.jpg");
        let mut j = vec![0xFF, 0xD8, 0xFF, 0xE0, 0, 4, 0, 0];
        j.extend([0xFF, 0xC0, 0, 17, 8, 0x02, 0xD0, 0x05, 0x00, 3]);
        j.extend([0; 12]);
        std::fs::write(&jpg, &j).unwrap();
        assert_eq!(image_size(&jpg), Some((1280, 720)));
        std::fs::write(dir.path().join("x"), b"nope").unwrap();
        assert_eq!(image_size(&dir.path().join("x")), None);
    }
}
