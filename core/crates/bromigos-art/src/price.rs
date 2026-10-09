//! What an asset costs, from the model's entry in nolgia's live catalog
//! (`GET /models`, `nolgia models get <id>`), and whether the catalog says the
//! model can do what the asset asks.
//!
//! The maths is the server's (the catalog documents it, and `POST /jobs/cost`
//! is the same pricer):
//!
//! - `per_image`: the quality tier's credits (or the model's `credits`), plus the
//!   render quality's `credits_added`, times the number of images;
//! - `per_clip`: `ceil(rate × duration / baseline_seconds)`, the rate being the
//!   resolution tier's credits, less `audio_surcharge` when audio is off;
//! - `per_generation`: `credits`, flat;
//! - all three: plus `max(0, input images − free_input_images) ×
//!   input_image_credits` once per request.

use nolgia::types::Model;
use serde::Serialize;

use crate::spec::{Asset, Kind};

/// An asset's price.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Price {
    pub credits: u64,
    /// How it adds up, for people: `8 (native) + 0 (render high) × 1 image`.
    pub basis: String,
}

/// Prices `asset` with its model's catalog entry, or says why it can't run.
pub fn price(asset: &Asset, model: &Model) -> Result<Price, String> {
    if let Some(why) = &model.unavailable_reason {
        return Err(format!("{} is unavailable: {why}", model.id));
    }
    let cost = model
        .cost
        .as_ref()
        .ok_or_else(|| format!("{}: pricing not published yet", model.id))?;
    check(asset, model)?;
    let tier = |name: Option<&str>| -> Result<(u64, Option<u64>, String), String> {
        match name {
            None => Ok((
                cost.credits.get(),
                cost.audio_surcharge.map(|n| n.get()),
                "base".into(),
            )),
            Some(t) => {
                let q = model.quality.as_ref().ok_or_else(|| {
                    format!("{} has no quality tiers; drop quality/resolution", model.id)
                })?;
                let o = q.options.iter().find(|o| o.id == t).ok_or_else(|| {
                    let ids: Vec<&str> = q.options.iter().map(|o| o.id.as_str()).collect();
                    format!("{}: no tier {t:?} (has {})", model.id, ids.join(", "))
                })?;
                Ok((
                    o.credits.get(),
                    o.audio_surcharge.map(|n| n.get()),
                    t.to_owned(),
                ))
            }
        }
    };
    let n_inputs = asset.input_images();
    let surcharge = match cost.input_image_credits {
        Some(per) => n_inputs.saturating_sub(cost.free_input_images.unwrap_or(0)) * per.get(),
        None => 0,
    };
    let with_inputs = |credits: u64, basis: String| -> Price {
        if surcharge > 0 {
            Price {
                credits: credits + surcharge,
                basis: format!("{basis} + {surcharge} (input images)"),
            }
        } else {
            Price { credits, basis }
        }
    };
    match cost.unit.as_str() {
        "per_image" => {
            let (base, _, tier_name) = tier(asset.quality.as_deref())?;
            let (added, rq) = match asset.render_quality.as_deref() {
                None => (0, None),
                Some(r) => {
                    let ladder = model
                        .image
                        .as_ref()
                        .and_then(|i| i.render_quality.as_ref())
                        .ok_or_else(|| format!("{} has no render quality ladder", model.id))?;
                    let o = ladder.options.iter().find(|o| o.id == r).ok_or_else(|| {
                        let ids: Vec<&str> = ladder.options.iter().map(|o| o.id.as_str()).collect();
                        format!(
                            "{}: no render quality {r:?} (has {})",
                            model.id,
                            ids.join(", ")
                        )
                    })?;
                    (o.credits_added, Some(r))
                }
            };
            let n = u64::from(asset.images);
            let mut basis = format!("{base} ({tier_name})");
            if let Some(r) = rq {
                basis.push_str(&format!(" + {added} (render {r})"));
            }
            basis.push_str(&format!(" × {n} image{}", if n == 1 { "" } else { "s" }));
            Ok(with_inputs((base + added) * n, basis))
        }
        "per_clip" => {
            let secs = u64::from(asset.duration.ok_or("a clip needs a duration")?);
            let baseline = cost
                .baseline_seconds
                .ok_or_else(|| format!("{}: per_clip without baseline_seconds", model.id))?
                .get();
            let (rate, audio_surcharge, tier_name) = tier(asset.resolution.as_deref())?;
            let (rate, silent) = if asset.audio == Some(false) {
                (rate.saturating_sub(audio_surcharge.unwrap_or(0)), true)
            } else {
                (rate, false)
            };
            let credits = (rate * secs).div_ceil(baseline);
            let basis = format!(
                "ceil({rate} ({tier_name}{}) × {secs}s / {baseline}s)",
                if silent { ", silent" } else { "" }
            );
            Ok(with_inputs(credits, basis))
        }
        "per_generation" => Ok(with_inputs(
            cost.credits.get(),
            format!("{} flat", cost.credits),
        )),
        other => Err(format!(
            "{}: unit {other:?} is not priced by bromigos art",
            model.id
        )),
    }
}

/// What the catalog says the model can't do for this asset.
fn check(asset: &Asset, model: &Model) -> Result<(), String> {
    let id = &model.id;
    let want = match asset.kind {
        Kind::Image | Kind::Edit | Kind::Cutout => "image",
        Kind::Video => "video",
        Kind::Model3d => "3d",
        Kind::Upscale => {
            return Err(format!(
                "{id}: bromigos art upscales on a ComfyUI only (create.toml [image.upscale], [video.upscale])"
            ));
        }
        Kind::Command => return Ok(()),
    };
    if model.modality != want {
        return Err(format!("{id} makes {}, not {want}", model.modality));
    }
    let removes = model.remove_background == Some(true);
    if asset.kind == Kind::Cutout && !removes {
        return Err(format!("{id} is not a background-removal model"));
    }
    if asset.kind != Kind::Cutout && removes {
        return Err(format!(
            "{id} only removes backgrounds; use kind = \"cutout\""
        ));
    }
    if let Some(img) = &model.image {
        if let Some(a) = &asset.aspect
            && !img.aspect_ratios.is_empty()
            && !img.aspect_ratios.contains(a)
        {
            return Err(format!(
                "{id}: aspect {a} not offered (has {})",
                img.aspect_ratios.join(", ")
            ));
        }
        if asset.mask.is_some() && img.inpaint_mask != Some(true) {
            return Err(format!("{id} takes no inpaint mask"));
        }
        let refs = asset.inputs.len() as u64;
        if let Some(max) = img.reference_images_max
            && refs > max
        {
            return Err(format!(
                "{id} takes at most {max} reference images, not {refs}"
            ));
        }
        if let Some(max) = img.num_images_max
            && u64::from(asset.images) > max.get()
        {
            return Err(format!("{id} makes at most {max} images per request"));
        }
    }
    if let Some(v) = &model.video {
        if let Some(a) = &asset.aspect
            && !v.aspect_ratios.is_empty()
            && !v.aspect_ratios.contains(a)
        {
            return Err(format!(
                "{id}: aspect {a} not offered (has {})",
                v.aspect_ratios.join(", ")
            ));
        }
        if let Some(d) = asset.duration.map(i64::from)
            && (v.min_duration.is_some_and(|m| d < m) || v.max_duration.is_some_and(|m| d > m))
        {
            return Err(format!(
                "{id}: duration {d}s outside {}..{}s",
                v.min_duration.unwrap_or(0),
                v.max_duration.map_or("".into(), |m| m.to_string())
            ));
        }
        if v.image_input == Some(false) {
            return Err(format!("{id} takes no start frame"));
        }
    }
    if asset.kind == Kind::Video
        && asset.end.is_some()
        && let Some(r) = &model.references
        && !r.end_frame
    {
        return Err(format!("{id} takes no end frame, so it can't loop"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spec::World;
    use serde_json::json;
    use std::path::Path;

    pub fn catalog() -> Vec<Model> {
        serde_json::from_value(json!([
            {"id": "flare", "modality": "image", "recommended": true, "capabilities": [],
             "cost": {"credits": 8, "unit": "per_image"},
             "image": {"aspect_ratios": ["16:9", "1:1"], "inpaint_mask": true, "num_images_max": 4,
                       "reference_images_max": 4,
                       "render_quality": {"default": "auto", "options": [
                           {"id": "auto", "credits_added": 0, "premium": false},
                           {"id": "high", "credits_added": 0, "premium": false},
                           {"id": "max", "credits_added": 24, "premium": true}]}},
             "quality": {"default": "native", "options": [
                 {"id": "native", "credits": 8, "premium": false, "aspect_ratios": []},
                 {"id": "2k", "credits": 21, "premium": true, "aspect_ratios": []}]}},
            {"id": "seedream", "modality": "image", "recommended": false, "capabilities": [],
             "cost": {"credits": 3, "unit": "per_image", "input_image_credits": 2, "free_input_images": 1},
             "image": {"aspect_ratios": ["16:9"], "inpaint_mask": false, "reference_images_max": 4}},
            {"id": "remove-background", "modality": "image", "recommended": false, "capabilities": [],
             "remove_background": true, "cost": {"credits": 1, "unit": "per_image"},
             "image": {"aspect_ratios": [], "reference_images_max": 1}},
            {"id": "clip", "modality": "video", "recommended": true, "capabilities": [],
             "cost": {"credits": 47, "unit": "per_clip", "baseline_seconds": 5, "audio_surcharge": 15},
             "quality": {"default": "1080p", "options": [
                 {"id": "720p", "credits": 35, "audio_surcharge": 11, "premium": false, "aspect_ratios": []},
                 {"id": "1080p", "credits": 47, "audio_surcharge": 15, "premium": false, "aspect_ratios": []}]},
             "references": {"end_frame": true, "start_frame": true, "audio_refs_max": 0,
                            "element_refs_max": 0, "video_refs_max": 0, "start_frame_required": true},
             "video": {"aspect_ratios": ["16:9"], "image_input": true, "min_duration": 3, "max_duration": 15}},
            {"id": "noend", "modality": "video", "recommended": false, "capabilities": [],
             "cost": {"credits": 10, "unit": "per_clip", "baseline_seconds": 5},
             "references": {"end_frame": false, "start_frame": true, "audio_refs_max": 0,
                            "element_refs_max": 0, "video_refs_max": 0, "start_frame_required": true},
             "video": {"aspect_ratios": [], "image_input": true}}
        ]))
        .expect("catalog fixture")
    }

    fn asset(toml_body: &str) -> Asset {
        let text = format!(
            "format = 1\n[[assets]]\nid = \"src\"\nkind = \"image\"\nmodel = \"flare\"\nprompt = \"p\"\nout = \"s.png\"\n[[assets]]\nid = \"x\"\n{toml_body}"
        );
        World::parse("w", Path::new("/nonexistent"), &text)
            .unwrap()
            .get("x")
            .unwrap()
            .clone()
    }

    fn cost(body: &str) -> Result<u64, String> {
        let a = asset(body);
        let models = catalog();
        let m = models
            .iter()
            .find(|m| Some(&m.id) == a.model.as_ref())
            .unwrap();
        price(&a, m).map(|p| p.credits)
    }

    #[test]
    fn images_price_tier_plus_render_quality_times_count() {
        let img = "kind = \"image\"\nmodel = \"flare\"\nprompt = \"p\"\nout = \"x.png\"\n";
        assert_eq!(cost(img), Ok(8));
        assert_eq!(cost(&format!("{img}render_quality = \"high\"\n")), Ok(8));
        assert_eq!(cost(&format!("{img}render_quality = \"max\"\n")), Ok(32));
        assert_eq!(
            cost(&format!(
                "{img}quality = \"2k\"\nrender_quality = \"max\"\nimages = 2\n"
            )),
            Ok(90)
        );
        let p = price(
            &asset(&format!(
                "{img}quality = \"2k\"\nrender_quality = \"max\"\nimages = 2\n"
            )),
            &catalog()[0],
        )
        .unwrap();
        assert_eq!(p.basis, "21 (2k) + 24 (render max) × 2 images");
    }

    #[test]
    fn input_images_past_the_free_ones_are_surcharged_once() {
        let s = "kind = \"image\"\nmodel = \"seedream\"\nprompt = \"p\"\nout = \"x.png\"\n";
        assert_eq!(cost(s), Ok(3));
        assert_eq!(cost(&format!("{s}inputs = [\"@src\"]\n")), Ok(3));
        assert_eq!(
            cost(&format!("{s}inputs = [\"@src\", \"r1.png\", \"r2.png\"]\n")),
            Ok(3 + 2 * 2)
        );
    }

    #[test]
    fn clips_scale_with_duration_and_drop_the_audio_surcharge_when_silent() {
        let v = "kind = \"video\"\nmodel = \"clip\"\nprompt = \"p\"\nstart = \"@src\"\nout = \"x.mp4\"\n";
        assert_eq!(cost(&format!("{v}duration = 5\n")), Ok(47));
        assert_eq!(cost(&format!("{v}duration = 8\n")), Ok(76)); // ceil(47*8/5) = ceil(75.2)
        assert_eq!(
            cost(&format!(
                "{v}duration = 8\nresolution = \"720p\"\naudio = false\n"
            )),
            Ok(39)
        ); // ceil(24*8/5)
        assert_eq!(cost(&format!("{v}duration = 5\nloop = true\n")), Ok(47));
    }

    #[test]
    fn cutouts_cost_the_flat_model_price() {
        assert_eq!(
            cost(
                "kind = \"cutout\"\nmodel = \"remove-background\"\ninput = \"@src\"\nout = \"c.png\"\n"
            ),
            Ok(1)
        );
    }

    #[test]
    fn the_catalog_refuses_what_the_model_cannot_do() {
        let cases = [
            (
                "kind = \"image\"\nmodel = \"flare\"\nprompt = \"p\"\naspect = \"21:9\"\nout = \"x.png\"\n",
                "aspect 21:9",
            ),
            (
                "kind = \"image\"\nmodel = \"flare\"\nprompt = \"p\"\nquality = \"8k\"\nout = \"x.png\"\n",
                "no tier \"8k\"",
            ),
            (
                "kind = \"image\"\nmodel = \"seedream\"\nprompt = \"p\"\nrender_quality = \"high\"\nout = \"x.png\"\n",
                "render quality ladder",
            ),
            (
                "kind = \"edit\"\nmodel = \"seedream\"\nprompt = \"p\"\ninput = \"@src\"\nmask = \"m.png\"\nout = \"x.png\"\n",
                "no inpaint mask",
            ),
            (
                "kind = \"image\"\nmodel = \"remove-background\"\nprompt = \"p\"\nout = \"x.png\"\n",
                "only removes backgrounds",
            ),
            (
                "kind = \"cutout\"\nmodel = \"flare\"\ninput = \"@src\"\nout = \"x.png\"\n",
                "not a background-removal",
            ),
            (
                "kind = \"video\"\nmodel = \"clip\"\nprompt = \"p\"\nstart = \"@src\"\nduration = 20\nout = \"x.mp4\"\n",
                "outside 3..15s",
            ),
            (
                "kind = \"video\"\nmodel = \"noend\"\nprompt = \"p\"\nstart = \"@src\"\nloop = true\nduration = 5\nout = \"x.mp4\"\n",
                "can't loop",
            ),
            (
                "kind = \"video\"\nmodel = \"flare\"\nprompt = \"p\"\nstart = \"@src\"\nduration = 5\nout = \"x.mp4\"\n",
                "makes image",
            ),
        ];
        for (body, want) in cases {
            let err = cost(body).unwrap_err();
            assert!(err.contains(want), "{want:?} not in {err:?}");
        }
    }
}
