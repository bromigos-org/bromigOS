//! Standing a pixel-aligned mesh upright. Pixal3D builds the object in the concept's
//! camera frame, so a concept seen from above comes out pitched by the camera's
//! elevation (a hut on a rock leaned back about 20°). A workflow that says so
//! (`_meta.level = true`) has its GLB levelled here: the pitch about the camera's
//! horizontal axis (glTF X; Y is up, the camera looks down -Z) that best stands the
//! surfaces square, faces upright or flat (area-weighted cos⁴ + sin⁴ of each normal's
//! angle to Y), searched within ±60°. It is applied only when it beats the mesh as it
//! is by 2% or more: an organic shape with no square surfaces keeps its pose.

use std::path::Path;

use serde_json::{Value, json};

const GLB: u32 = 0x4654_6C67; // "glTF"
const JSON: u32 = 0x4E4F_534A;
const BIN: u32 = 0x004E_4942;
const FLOAT: u64 = 5126;

struct Glb {
    json: Value,
    bin: Vec<u8>,
}

fn u32_at(b: &[u8], at: usize) -> Option<u32> {
    Some(u32::from_le_bytes(b.get(at..at + 4)?.try_into().ok()?))
}

fn read(bytes: &[u8]) -> Result<Glb, String> {
    if u32_at(bytes, 0) != Some(GLB) || u32_at(bytes, 4) != Some(2) {
        return Err("not a glTF 2.0 binary".into());
    }
    let (mut at, mut json, mut bin) = (12usize, None, Vec::new());
    while at + 8 <= bytes.len() {
        let len = u32_at(bytes, at).unwrap_or(0) as usize;
        let kind = u32_at(bytes, at + 4).unwrap_or(0);
        let body = bytes
            .get(at + 8..at + 8 + len)
            .ok_or("a chunk runs past the end")?;
        match kind {
            JSON => json = Some(serde_json::from_slice(body).map_err(|e| e.to_string())?),
            BIN => bin = body.to_vec(),
            _ => {}
        }
        at += 8 + len;
    }
    Ok(Glb {
        json: json.ok_or("no JSON chunk")?,
        bin,
    })
}

fn write(g: &Glb) -> Vec<u8> {
    let mut json = serde_json::to_vec(&g.json).unwrap_or_default();
    while !json.len().is_multiple_of(4) {
        json.push(b' ');
    }
    let mut bin = g.bin.clone();
    while !bin.len().is_multiple_of(4) {
        bin.push(0);
    }
    let total = 12 + 8 + json.len() + if bin.is_empty() { 0 } else { 8 + bin.len() };
    let mut out = Vec::with_capacity(total);
    for v in [GLB, 2, total as u32, json.len() as u32, JSON] {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out.extend_from_slice(&json);
    if !bin.is_empty() {
        out.extend_from_slice(&(bin.len() as u32).to_le_bytes());
        out.extend_from_slice(&BIN.to_le_bytes());
        out.extend_from_slice(&bin);
    }
    out
}

/// Where accessor `i`'s elements are in the BIN chunk: (offset, stride, count, components).
fn layout(g: &Glb, i: u64) -> Option<(usize, usize, usize, usize, u64)> {
    let a = g.json["accessors"].get(i as usize)?;
    let view = &g.json["bufferViews"][a["bufferView"].as_u64()? as usize];
    if view["buffer"].as_u64().unwrap_or(0) != 0 {
        return None;
    }
    let comps = match a["type"].as_str()? {
        "SCALAR" => 1,
        "VEC3" => 3,
        _ => return None,
    };
    let ctype = a["componentType"].as_u64()?;
    let size = match ctype {
        5121 => 1,
        5123 => 2,
        5125 | 5126 => 4,
        _ => return None,
    };
    let offset = view["byteOffset"].as_u64().unwrap_or(0) as usize
        + a["byteOffset"].as_u64().unwrap_or(0) as usize;
    let stride = view["byteStride"]
        .as_u64()
        .map_or(comps * size, |s| s as usize);
    Some((offset, stride, a["count"].as_u64()? as usize, comps, ctype))
}

fn vec3s(g: &Glb, i: u64) -> Option<Vec<[f32; 3]>> {
    let (off, stride, n, comps, ctype) = layout(g, i)?;
    if comps != 3 || ctype != FLOAT {
        return None;
    }
    (0..n)
        .map(|k| {
            let at = off + k * stride;
            let f = |j: usize| {
                Some(f32::from_le_bytes(
                    g.bin.get(at + 4 * j..at + 4 * j + 4)?.try_into().ok()?,
                ))
            };
            Some([f(0)?, f(1)?, f(2)?])
        })
        .collect()
}

fn indices(g: &Glb, i: u64) -> Option<Vec<usize>> {
    let (off, stride, n, comps, ctype) = layout(g, i)?;
    if comps != 1 {
        return None;
    }
    (0..n)
        .map(|k| {
            let at = off + k * stride;
            let b = &g.bin;
            Some(match ctype {
                5121 => *b.get(at)? as usize,
                5123 => u16::from_le_bytes(b.get(at..at + 2)?.try_into().ok()?) as usize,
                5125 => u32_at(b, at)? as usize,
                _ => return None,
            })
        })
        .collect()
}

/// Each triangle's unit normal's Y and Z, and its area, over every triangle primitive.
fn faces(g: &Glb) -> Option<Vec<(f64, f64, f64)>> {
    let mut out = Vec::new();
    for m in g.json["meshes"].as_array()? {
        for p in m["primitives"].as_array()? {
            if p["mode"].as_u64().unwrap_or(4) != 4 {
                continue;
            }
            let pos = vec3s(g, p["attributes"]["POSITION"].as_u64()?)?;
            let idx = match p["indices"].as_u64() {
                Some(i) => indices(g, i)?,
                None => (0..pos.len()).collect(),
            };
            for t in idx.as_chunks::<3>().0 {
                let v = |k: usize| pos.get(t[k]).map(|p| p.map(f64::from));
                let (a, b, c) = (v(0)?, v(1)?, v(2)?);
                let (u, w) = (
                    [b[0] - a[0], b[1] - a[1], b[2] - a[2]],
                    [c[0] - a[0], c[1] - a[1], c[2] - a[2]],
                );
                let n = [
                    u[1] * w[2] - u[2] * w[1],
                    u[2] * w[0] - u[0] * w[2],
                    u[0] * w[1] - u[1] * w[0],
                ];
                let len = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
                if len > 0.0 {
                    out.push((n[1] / len, n[2] / len, len / 2.0));
                }
            }
        }
    }
    Some(out)
}

/// How square the surfaces stand after a pitch of `deg` about X (1: all upright or flat).
fn score(faces: &[(f64, f64, f64)], deg: f64) -> f64 {
    let (s, c) = deg.to_radians().sin_cos();
    let (mut sum, mut area) = (0.0, 0.0);
    for &(ny, nz, a) in faces {
        let y = ny * c - nz * s;
        let h = 1.0 - y * y;
        sum += a * (y * y * y * y + h * h);
        area += a;
    }
    if area > 0.0 { sum / area } else { 0.0 }
}

/// The pitch (degrees about X) that stands the mesh up, when it's worth applying.
fn pitch(faces: &[(f64, f64, f64)]) -> Option<f64> {
    let level = score(faces, 0.0);
    let (mut best, mut at) = (level, 0.0);
    for k in -120..=120 {
        let deg = f64::from(k) / 2.0;
        let s = score(faces, deg);
        if s > best {
            (best, at) = (s, deg);
        }
    }
    (level > 0.0 && best / level >= 1.02 && at.abs() >= 1.0).then_some(at)
}

/// Rotates every POSITION and NORMAL by `deg` about X, keeping the accessors' bounds.
fn rotate(g: &mut Glb, deg: f64) -> Option<()> {
    let (s, c) = deg.to_radians().sin_cos();
    let mut done = Vec::new();
    let prims: Vec<(String, u64)> = g.json["meshes"]
        .as_array()?
        .iter()
        .flat_map(|m| m["primitives"].as_array().cloned().unwrap_or_default())
        .flat_map(|p| {
            ["POSITION", "NORMAL"]
                .into_iter()
                .filter_map(|k| Some((k.to_string(), p["attributes"][k].as_u64()?)))
                .collect::<Vec<_>>()
        })
        .collect();
    for (kind, i) in prims {
        if done.contains(&i) {
            continue;
        }
        done.push(i);
        let (off, stride, n, _, _) = layout(g, i)?;
        let v = vec3s(g, i)?;
        let (mut lo, mut hi) = ([f32::MAX; 3], [f32::MIN; 3]);
        for (k, p) in v.iter().enumerate() {
            let (y, z) = (f64::from(p[1]), f64::from(p[2]));
            let q = [p[0], (y * c - z * s) as f32, (y * s + z * c) as f32];
            let at = off + k * stride;
            for (j, x) in q.iter().enumerate() {
                g.bin[at + 4 * j..at + 4 * j + 4].copy_from_slice(&x.to_le_bytes());
                lo[j] = lo[j].min(*x);
                hi[j] = hi[j].max(*x);
            }
        }
        if kind == "POSITION" && n > 0 {
            let a = &mut g.json["accessors"][i as usize];
            a["min"] = json!(lo);
            a["max"] = json!(hi);
        }
    }
    Some(())
}

/// Levels the GLB at `path` in place (see the module's doc); the pitch it applied, if any.
pub fn level(path: &Path) -> Result<Option<f64>, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut g = read(&bytes)?;
    // a node that moves its mesh would put the faces somewhere else: leave such a file be
    let posed = g.json["nodes"].as_array().is_some_and(|ns| {
        ns.iter().any(|n| {
            ["matrix", "rotation", "scale", "translation"]
                .iter()
                .any(|k| n.get(*k).is_some())
        })
    });
    if posed {
        return Ok(None);
    }
    let Some(f) = faces(&g) else {
        return Ok(None);
    };
    let Some(deg) = pitch(&f) else {
        return Ok(None);
    };
    rotate(&mut g, deg).ok_or("the mesh's vertices aren't plain floats")?;
    if let Some(asset) = g.json.get_mut("asset").and_then(Value::as_object_mut) {
        let extras = asset.entry("extras").or_insert_with(|| json!({}));
        if let Some(e) = extras.as_object_mut() {
            e.insert("bromigos_levelled_deg".into(), json!(deg));
        }
    }
    let tmp = path.with_extension("glb.level");
    std::fs::write(&tmp, write(&g)).map_err(|e| format!("{}: {e}", tmp.display()))?;
    std::fs::rename(&tmp, path).map_err(|e| format!("{}: {e}", path.display()))?;
    Ok(Some(deg))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A unit box's 12 triangles, pitched by `deg` about X, as a GLB like ComfyUI's.
    fn box_glb(deg: f64) -> Vec<u8> {
        let mut v: Vec<[f32; 3]> = Vec::new();
        for x in [-0.5f32, 0.5] {
            for y in [-0.5f32, 0.5] {
                for z in [-0.5f32, 0.5] {
                    v.push([x, y, z]);
                }
            }
        }
        let (s, c) = deg.to_radians().sin_cos();
        for p in &mut v {
            let (y, z) = (f64::from(p[1]), f64::from(p[2]));
            p[1] = (y * c - z * s) as f32;
            p[2] = (y * s + z * c) as f32;
        }
        let idx: [u32; 36] = [
            0, 1, 3, 0, 3, 2, 4, 6, 7, 4, 7, 5, 0, 4, 5, 0, 5, 1, 2, 3, 7, 2, 7, 6, 0, 2, 6, 0, 6,
            4, 1, 5, 7, 1, 7, 3,
        ];
        let mut bin = Vec::new();
        for p in &v {
            for x in p {
                bin.extend_from_slice(&x.to_le_bytes());
            }
        }
        let pos_len = bin.len();
        for i in idx {
            bin.extend_from_slice(&i.to_le_bytes());
        }
        let g = Glb {
            json: json!({
                "asset": {"version": "2.0", "extras": {"prompt": "{}"}},
                "buffers": [{"byteLength": bin.len()}],
                "bufferViews": [
                    {"buffer": 0, "byteOffset": 0, "byteLength": pos_len},
                    {"buffer": 0, "byteOffset": pos_len, "byteLength": 144}
                ],
                "accessors": [
                    {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3", "min": [-1, -1, -1], "max": [1, 1, 1]},
                    {"bufferView": 1, "componentType": 5125, "count": 36, "type": "SCALAR"}
                ],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
                "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0
            }),
            bin,
        };
        write(&g)
    }

    #[test]
    fn a_pitched_box_stands_up_and_a_level_one_is_left_alone() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("b.glb");
        std::fs::write(&p, box_glb(20.0)).unwrap();
        let deg = level(&p).unwrap().unwrap();
        assert!((deg + 20.0).abs() <= 0.5, "{deg}");
        let g = read(&std::fs::read(&p).unwrap()).unwrap();
        let ys: Vec<f32> = vec3s(&g, 0).unwrap().iter().map(|v| v[1]).collect();
        // every corner back at y = ±0.5
        assert!(ys.iter().all(|y| (y.abs() - 0.5).abs() < 0.01), "{ys:?}");
        assert_eq!(g.json["asset"]["extras"]["prompt"], "{}");
        assert_eq!(
            g.json["asset"]["extras"]["bromigos_levelled_deg"],
            json!(deg)
        );
        let max = g.json["accessors"][0]["max"][1].as_f64().unwrap();
        assert!((max - 0.5).abs() < 0.01);
        // a level box: nothing to do, the file untouched
        std::fs::write(&p, box_glb(0.0)).unwrap();
        let before = std::fs::read(&p).unwrap();
        assert_eq!(level(&p).unwrap(), None);
        assert_eq!(std::fs::read(&p).unwrap(), before);
    }
}
