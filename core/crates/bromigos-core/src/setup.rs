//! `bromigos setup`: the first-run questions, each one also a section to run again later.
//!
//! - monitors: this machine's outputs, found (Hyprland's own list when it runs, else the
//!   kernel's connectors) and written as a `bromigos.monitors` block into the user's
//!   `~/.config/hypr/hyprland.lua`, just before the line that loads bromigOS's defaults
//!   (which read it), with the primary output in `~/.config/bromigos/monitors.toml`;
//! - aur: the AUR helper (`bromigos aur on|off`; crate::aur, docs/aur.md): bromigOS's paru
//!   and AUR packages in `bromigos update`, or neither;
//! - hardware: the GPU's drivers, early KMS, a hybrid laptop's render GPU, a laptop's
//!   power profiles (`bromigos hw setup`; crate::hw, docs/hardware.md);
//! - accessibility: reduced motion and high contrast (`~/.config/bromigos/accessibility.toml`,
//!   crate::accessibility), before the theme, which renders with them;
//! - extensions: extensions to install, as `bromigos ext install` takes them, and whether
//!   this answers file approves the ones that run code (crate::ext);
//! - theme: `bromigos theme set`, and for the Wick its den (bromigos-wallpaper); then the
//!   boot menu in its colours where GRUB boots the machine (crate::boot: on, unless
//!   `bromigos boot theme off` turned it off here);
//! - vector: VECTOR's brain, an OpenAI-compatible endpoint (a local Ollama, any other
//!   server, or none yet): `~/.config/bromigos/vector/vector.toml` [llm];
//! - voice: VECTOR's voice: gpu (the designed voice, Qwen3-TTS), cpu (Kokoro) or off;
//! - homelab: the homelab integrations' config (`~/.config/bromigos/homelab.toml`);
//! - targets: where AI work runs, homelab, this machine or the cloud, in order
//!   (`~/.config/bromigos/targets.toml`; docs/targets.md, crate::targets): the creation
//!   tools, VECTOR's voice and his brain follow it unless a file of theirs pins one;
//! - create: the creation tools: which ComfyUI (this machine's GPU, the homelab's) or
//!   nolgia makes each kind of art (images, edits, cutouts, video loops, 3D models), and
//!   nolgia's sign-in (crate::create; `~/.config/bromigos/create.toml`);
//! - peripherals: optional device modules to turn on (a Razer keyboard's macro keys, dial
//!   and lighting: crate::peripheral; `~/.config/bromigos/peripherals.toml`).
//!
//! The interactive form is the CLI's terminal UI; every answer can also come from a file
//! ([`Answers`], TOML) or flags, so installs and tests run unattended. What was answered is
//! kept in `~/.local/state/bromigos/setup.toml`.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde::{Deserialize, Serialize};

use crate::paths::Paths;

/// The sections, in the order the first run asks them.
pub const SECTIONS: &[&str] = &[
    "monitors",
    "aur",
    "hardware",
    "accessibility",
    "extensions",
    "theme",
    "vector",
    "voice",
    "homelab",
    "targets",
    "create",
    "peripherals",
];

/// Everything setup can be told (a TOML file, or the TUI's results).
#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct Answers {
    pub monitors: Option<MonitorsAnswer>,
    pub aur: Option<AurAnswer>,
    pub hardware: Option<HardwareAnswer>,
    pub accessibility: Option<AccessibilityAnswer>,
    pub extensions: Option<ExtensionsAnswer>,
    pub theme: Option<ThemeAnswer>,
    pub vector: Option<VectorAnswer>,
    pub voice: Option<VoiceAnswer>,
    pub homelab: Option<HomelabAnswer>,
    pub targets: Option<TargetsAnswer>,
    pub create: Option<crate::create::CreateAnswer>,
    pub peripherals: Option<PeripheralsAnswer>,
}

/// Peripheral modules to turn on or off (`bromigos peripheral`; docs/peripherals.md).
#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PeripheralsAnswer {
    /// Modules to turn on (`razer-keyboard`).
    #[serde(default)]
    pub enable: Vec<String>,
    /// Modules to turn off.
    #[serde(default)]
    pub disable: Vec<String>,
    /// On even when the device isn't connected now.
    #[serde(default)]
    pub force: bool,
    /// Install what they need (packages, a group) and start their services; false: only
    /// the choice and the keys.
    #[serde(default = "default_true")]
    pub system: bool,
}

fn default_true() -> bool {
    true
}

/// Reduced motion and high contrast (crate::accessibility; docs/accessibility.md). Either
/// may be left out (it stays as it is).
#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AccessibilityAnswer {
    /// "full", "reduced" or "still".
    #[serde(default)]
    pub motion: Option<String>,
    /// "normal" or "high".
    #[serde(default)]
    pub contrast: Option<String>,
}

/// Extensions to install (`bromigos ext`; docs/extensions.md), before the theme, which
/// may be one of theirs. Only an answers file can approve one that runs code or reaches
/// VECTOR (`approve`): the TUI never asks, and `bromigos ext install` has no `--yes`.
#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ExtensionsAnswer {
    /// Sources as `bromigos ext install` takes them: a git URL (with @tag to pin it), a
    /// folder, a catalog name; or a table, `{ source = "…", path = "…", ref = "…" }`, for
    /// an extension in a folder inside its repository.
    #[serde(default)]
    pub install: Vec<InstallItem>,
    /// Approve the ones that run code or reach VECTOR. The ledger records that this file
    /// approved them (its path and sha256), and the extensions' log has a line each.
    /// Without it they are refused; themes install either way.
    #[serde(default)]
    pub approve: bool,
    /// The answers file these came from (set when it's read).
    #[serde(skip)]
    pub from: String,
}

/// One `[extensions] install` entry: a source, or a source with its folder and ref.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(untagged)]
pub enum InstallItem {
    Source(String),
    Table {
        source: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        path: Option<String>,
        #[serde(default, rename = "ref", skip_serializing_if = "Option::is_none")]
        git_ref: Option<String>,
    },
}

impl InstallItem {
    /// (the source, `bromigos ext install`'s options for it).
    pub fn parts(&self) -> (String, crate::ext::InstallOpts) {
        match self {
            InstallItem::Source(s) => (s.clone(), crate::ext::InstallOpts::default()),
            InstallItem::Table {
                source,
                path,
                git_ref,
            } => (
                source.clone(),
                crate::ext::InstallOpts {
                    path: path.clone(),
                    git_ref: git_ref.clone(),
                    ..Default::default()
                },
            ),
        }
    }
}

impl From<&str> for InstallItem {
    fn from(s: &str) -> Self {
        InstallItem::Source(s.to_owned())
    }
}

/// Where AI work runs (targets.toml).
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct TargetsAnswer {
    /// The targets in order: homelab, local, cloud (the cloud costs money: leave it out
    /// to never use it).
    pub order: Vec<String>,
    /// Services that may also use the cloud when `order` leaves it out, last (e.g.
    /// video.loop, for a machine whose ComfyUI hasn't Wan 2.2). Only what the user picks:
    /// the default leaves the cloud out.
    #[serde(default)]
    pub cloud_for: Vec<String>,
}

/// The first-run default: the homelab when it has services, then this machine, never
/// the cloud: video loops too run on a ComfyUI now (Wan 2.2, docs/art.md), so the cloud
/// is only where the user picks it (a `cloud_for` choice). The cloud last when there's
/// neither a homelab nor a GPU here and nolgia is.
pub fn default_targets(homelab: bool, gpu: bool, nolgia: bool) -> TargetsAnswer {
    let mut order = vec![];
    if homelab {
        order.push("homelab".to_string());
    }
    order.push("local".to_string());
    if nolgia && !homelab && !gpu {
        order.push("cloud".to_string());
    }
    TargetsAnswer {
        order,
        cloud_for: vec![],
    }
}

/// Whether homelab.toml names services the targets use (a ComfyUI, a voice, a model server).
pub fn homelab_has_ai(paths: &Paths) -> bool {
    let Ok(text) = fs::read_to_string(homelab_toml(paths)) else {
        return false;
    };
    let Ok(t) = text.parse::<toml::Table>() else {
        return false;
    };
    t.get("source")
        .and_then(toml::Value::as_array)
        .is_some_and(|a| {
            a.iter().filter_map(toml::Value::as_table).any(|s| {
                matches!(
                    s.get("type").and_then(toml::Value::as_str),
                    Some("comfyui" | "bromigos-voice" | "litellm" | "openai" | "ollama")
                )
            })
        })
}

pub fn apply_targets(paths: &Paths, a: &TargetsAnswer) -> Applied {
    use crate::targets as tw;
    let file = tw::user_path(paths);
    let existing = fs::read_to_string(&file).unwrap_or_default();
    let mut text = match tw::with_order(&existing, &a.order, &[]) {
        Ok(t) => t,
        Err(e) => return err("targets", e),
    };
    for svc in &a.cloud_for {
        let mut o = a.order.clone();
        if !o.iter().any(|t| t == "cloud") {
            o.push("cloud".into());
        }
        text = match tw::with_order(&text, &o, std::slice::from_ref(svc)) {
            Ok(t) => t,
            Err(e) => return err("targets", e),
        };
    }
    match tw::write(paths, &text) {
        Ok(()) => ok(
            "targets",
            format!(
                "{}{} ({}; bromigos target shows and switches it)",
                a.order.join(" → "),
                if a.cloud_for.is_empty() {
                    String::new()
                } else {
                    format!("; the cloud also for {}", a.cloud_for.join(", "))
                },
                file.display()
            ),
        ),
        Err(e) => err("targets", format!("{}: {e}", file.display())),
    }
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MonitorsAnswer {
    /// "auto": write this machine's layout; "skip": leave it.
    pub mode: String,
    /// The output bromigOS's own surfaces go on (the live background, the panels);
    /// none: the focused, else the first.
    #[serde(default)]
    pub primary: Option<String>,
    /// Left to right; outputs not named follow, as found.
    #[serde(default)]
    pub order: Vec<String>,
    /// output -> scale (default: from its pixel density).
    #[serde(default)]
    pub scale: BTreeMap<String, f64>,
    /// output -> refresh rate in Hz (default: its current one).
    #[serde(default)]
    pub refresh: BTreeMap<String, f64>,
}

/// The AUR (docs/aur.md): "on" (the default) keeps an AUR helper here (bromigOS's paru,
/// unless the machine has paru or yay) and lets `bromigos update` update AUR packages with
/// it; "off" leaves the AUR out: no helper from bromigOS (the paru it installed is removed),
/// and updates leave AUR packages alone. `bromigos install` reads it from an answers file
/// before it installs anything, so "off" never installs paru.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AurAnswer {
    pub mode: String,
}

/// The hardware (`bromigos hw setup`): "auto" sets up what this machine needs, "skip"
/// leaves it.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct HardwareAnswer {
    pub mode: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ThemeAnswer {
    pub name: String,
    /// The Wick's den variant (bromigos-wallpaper): empty, or a user's own art's.
    #[serde(default)]
    pub den: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct VectorAnswer {
    /// "ollama", "openai" (any OpenAI-compatible server) or "none".
    pub backend: String,
    #[serde(default)]
    pub base_url: Option<String>,
    /// A file holding the API key (never the key itself in a config).
    #[serde(default)]
    pub api_key_file: Option<String>,
    #[serde(default)]
    pub model: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct VoiceAnswer {
    /// "gpu" (the designed voice), "cpu" (Kokoro) or "off".
    pub tier: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct HomelabAnswer {
    /// A homelab.toml to use (copied to ~/.config/bromigos/homelab.toml); none: skip.
    #[serde(default)]
    pub file: Option<String>,
    /// Find my lab: run bromigos-homelab's detector with `--find`, which asks before it
    /// reads anything (so it needs a terminal). Without a file only.
    #[serde(default)]
    pub find: bool,
}

pub const OLLAMA_URL: &str = "http://localhost:11434/v1";

/// One output.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Monitor {
    pub output: String,
    /// Its make and model (Hyprland's, from the EDID); empty when unknown.
    pub make: String,
    pub model: String,
    pub width: u32,
    pub height: u32,
    /// Hz; 0 when unknown (then the mode is the output's preferred one).
    pub refresh: f64,
    /// The panel's physical size in mm (EDID); 0 when unknown.
    pub phys_w: u32,
    pub phys_h: u32,
    /// Its x position now (Hyprland's), for the left-to-right order.
    pub x: i64,
    pub focused: bool,
    /// The scale bromigOS suggests (its pixel density; the defaults' rule).
    pub scale: f64,
}

impl Monitor {
    pub fn mode(&self) -> String {
        if self.refresh > 0.0 {
            format!(
                "{}x{}@{}",
                self.width,
                self.height,
                trim_float(self.refresh)
            )
        } else {
            format!("{}x{}", self.width, self.height)
        }
    }
    /// "Dell U2720Q, 27\" (597x336 mm)" or "".
    pub fn describe(&self) -> String {
        let name = format!("{} {}", self.make, self.model).trim().to_string();
        let size = if self.phys_w > 0 && self.phys_h > 0 {
            let diag = ((self.phys_w.pow(2) + self.phys_h.pow(2)) as f64).sqrt() / 25.4;
            format!("{diag:.0}\" ({}x{} mm)", self.phys_w, self.phys_h)
        } else {
            String::new()
        };
        [name, size]
            .into_iter()
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(", ")
    }
}

fn trim_float(f: f64) -> String {
    let s = format!("{f:.2}");
    s.trim_end_matches('0').trim_end_matches('.').to_string()
}

const SCALE_STEPS: &[f64] = &[1.0, 1.25, 1.5, 1.75, 2.0];

/// The scale for a panel from its pixel density (~110 ppi at 1x), in steps of .25: what
/// the default Hyprland config gives an output (desktop/hypr/hyprland.lua, B.auto_scale).
/// By its height when the EDID gives no size.
pub fn auto_scale(width: u32, height: u32, phys_w_mm: u32) -> f64 {
    let want = if phys_w_mm > 0 && width > 0 {
        (width as f64 / (phys_w_mm as f64 / 25.4)) / 110.0
    } else if height >= 2000 {
        1.5
    } else {
        1.0
    };
    *SCALE_STEPS
        .iter()
        .min_by(|a, b| (*a - want).abs().total_cmp(&(*b - want).abs()))
        .unwrap_or(&1.0)
}

/// Hyprland's monitors (`hyprctl monitors all -j`).
pub fn parse_hyprctl_monitors(json: &str) -> Vec<Monitor> {
    let v: serde_json::Value = serde_json::from_str(json).unwrap_or_default();
    let mut out: Vec<Monitor> = v
        .as_array()
        .into_iter()
        .flatten()
        .filter(|m| !m["disabled"].as_bool().unwrap_or(false))
        .filter_map(|m| {
            let (w, h) = (m["width"].as_u64()? as u32, m["height"].as_u64()? as u32);
            let pw = m["physicalWidth"].as_u64().unwrap_or(0) as u32;
            Some(Monitor {
                output: m["name"].as_str()?.to_string(),
                make: m["make"].as_str().unwrap_or("").to_string(),
                model: m["model"].as_str().unwrap_or("").to_string(),
                width: w,
                height: h,
                refresh: m["refreshRate"].as_f64().unwrap_or(0.0),
                phys_w: pw,
                phys_h: m["physicalHeight"].as_u64().unwrap_or(0) as u32,
                x: m["x"].as_i64().unwrap_or(0),
                focused: m["focused"].as_bool().unwrap_or(false),
                scale: auto_scale(w, h, pw),
            })
        })
        .collect();
    out.sort_by_key(|m| m.x);
    out
}

/// The kernel's connected outputs: `/sys/class/drm/card*-<OUTPUT>/{status,modes}` (the
/// first mode is the preferred one). Hyprland names them the same, minus "cardN-".
pub fn drm_monitors(drm: &Path) -> Vec<Monitor> {
    let mut out: Vec<Monitor> = fs::read_dir(drm)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().into_owned();
            let (card, output) = name.split_once('-')?;
            if !card.starts_with("card") || output.starts_with("Writeback") {
                return None;
            }
            if fs::read_to_string(e.path().join("status")).ok()?.trim() != "connected" {
                return None;
            }
            let modes = fs::read_to_string(e.path().join("modes")).ok()?;
            let (w, h) = modes.lines().next()?.trim().split_once('x')?;
            let w: u32 = w.parse().ok()?;
            let h: u32 = h
                .trim_end_matches(|c: char| !c.is_ascii_digit())
                .parse()
                .ok()?;
            Some(Monitor {
                output: output.to_string(),
                make: String::new(),
                model: String::new(),
                width: w,
                height: h,
                refresh: 0.0,
                phys_w: 0,
                phys_h: 0,
                x: 0,
                focused: false,
                scale: auto_scale(w, h, 0),
            })
        })
        .collect();
    out.sort_by(|a, b| a.output.cmp(&b.output));
    out
}

/// This machine's monitors, left to right: Hyprland's list when a session runs, else the
/// kernel's.
pub fn detect(paths: &Paths) -> Vec<Monitor> {
    if let Some(s) = crate::session::discover(paths).session
        && let Ok(o) = Command::new("hyprctl")
            .args(["monitors", "all", "-j"])
            .envs(s.env())
            .output()
    {
        let m = parse_hyprctl_monitors(&String::from_utf8_lossy(&o.stdout));
        if !m.is_empty() {
            return m;
        }
    }
    drm_monitors(Path::new("/sys/class/drm"))
}

/// The outputs as the answer arranges them: in its order (the rest after, as found), each
/// with its scale and refresh, placed left to right.
pub fn arrange(found: &[Monitor], a: &MonitorsAnswer) -> Vec<(Monitor, i64)> {
    let mut ms: Vec<Monitor> = vec![];
    for name in &a.order {
        if let Some(m) = found.iter().find(|m| &m.output == name) {
            ms.push(m.clone());
        }
    }
    for m in found {
        if !ms.iter().any(|x| x.output == m.output) {
            ms.push(m.clone());
        }
    }
    let mut x = 0.0f64;
    ms.into_iter()
        .map(|mut m| {
            if let Some(s) = a.scale.get(&m.output) {
                m.scale = *s;
            }
            if let Some(r) = a.refresh.get(&m.output) {
                m.refresh = *r;
            }
            let pos = x.round() as i64;
            x += m.width as f64 / m.scale;
            (m, pos)
        })
        .collect()
}

pub const BLOCK_BEGIN: &str = "-- >>> bromigos setup monitors";
pub const BLOCK_END: &str = "-- <<< bromigos setup monitors";

/// The block `bromigos setup monitors` keeps in the user's hyprland.lua.
pub fn monitors_block(layout: &[(Monitor, i64)], stamp: &str) -> String {
    let mut s = format!(
        "{BLOCK_BEGIN} ({stamp}): this machine's outputs, left to right. Run it again to\n\
         -- change them, or edit here; an output not listed still lights up on its own.\n\
         bromigos.monitors = {{\n"
    );
    for (m, x) in layout {
        s.push_str(&format!(
            "    {{ output = \"{}\", mode = \"{}\", position = \"{x}x0\", scale = {} }},{}\n",
            m.output,
            m.mode(),
            trim_float(m.scale),
            if m.describe().is_empty() {
                String::new()
            } else {
                format!("  -- {}", m.describe())
            }
        ));
    }
    s.push_str("}\n");
    s.push_str(BLOCK_END);
    s.push('\n');
    s
}

/// The user's hyprland.lua with the block put in: replacing the last one, else just before
/// the line that loads bromigOS's defaults (so it's set when they read it).
pub fn with_monitors_block(lua: &str, block: &str) -> Result<String, String> {
    if let (Some(b), Some(e)) = (lua.find(BLOCK_BEGIN), lua.find(BLOCK_END))
        && e > b
    {
        let end = lua[e..].find('\n').map(|i| e + i + 1).unwrap_or(lua.len());
        return Ok(format!("{}{}{}", &lua[..b], block, &lua[end..]));
    }
    let at = lua
        .lines()
        .scan(0usize, |off, l| {
            let start = *off;
            *off += l.len() + 1;
            Some((start, l))
        })
        .find(|(_, l)| l.trim_start().starts_with("dofile(") && l.contains("/default/hypr/hyprland.lua"))
        .map(|(start, _)| start)
        .ok_or("it doesn't load bromigOS's defaults (a dofile(\".../default/hypr/hyprland.lua\") line); set bromigos.monitors there yourself")?;
    Ok(format!("{}{}\n{}", &lua[..at], block, &lua[at..]))
}

pub fn hyprland_lua(paths: &Paths) -> PathBuf {
    paths.config_home.join("hypr/hyprland.lua")
}

/// Where the primary output is kept (lib/bromigos_monitors reads it).
pub fn monitors_toml(paths: &Paths) -> PathBuf {
    paths.user_config_dir().join("monitors.toml")
}

pub fn vector_toml(paths: &Paths) -> PathBuf {
    paths.user_config_dir().join("vector/vector.toml")
}

pub fn homelab_toml(paths: &Paths) -> PathBuf {
    paths.user_config_dir().join("homelab.toml")
}

pub fn state_file(paths: &Paths) -> PathBuf {
    paths.state_home.join("bromigos/setup.toml")
}

/// VECTOR's [llm] for an answer, merged into an existing vector.toml (its other tables and
/// keys, and comments, are kept). "none" removes base_url, so VECTOR uses its fallbacks.
pub fn vector_toml_text(existing: &str, a: &VectorAnswer) -> Result<String, String> {
    let mut doc: toml_edit::DocumentMut =
        existing.parse().map_err(|e| format!("vector.toml: {e}"))?;
    if !doc.contains_table("llm") {
        doc["llm"] = toml_edit::table();
    }
    let llm = doc["llm"]
        .as_table_mut()
        .ok_or("vector.toml: [llm] isn't a table")?;
    match a.backend.as_str() {
        "ollama" => {
            llm["base_url"] =
                toml_edit::value(a.base_url.clone().unwrap_or_else(|| OLLAMA_URL.into()));
            llm.remove("api_key_file");
        }
        "openai" => {
            let url = a
                .base_url
                .clone()
                .filter(|u| !u.is_empty())
                .ok_or("an OpenAI-compatible backend needs base_url")?;
            if !(url.starts_with("http://") || url.starts_with("https://")) {
                return Err(format!("base_url {url:?} isn't an http(s) URL"));
            }
            llm["base_url"] = toml_edit::value(url);
            match &a.api_key_file {
                Some(f) if !f.is_empty() => llm["api_key_file"] = toml_edit::value(f.clone()),
                _ => {
                    llm.remove("api_key_file");
                }
            }
        }
        "none" => {
            llm.remove("base_url");
            llm.remove("api_key_file");
        }
        other => {
            return Err(format!(
                "unknown backend {other:?} (ollama, openai or none)"
            ));
        }
    }
    match &a.model {
        Some(m) if !m.is_empty() => llm["model"] = toml_edit::value(m.clone()),
        _ => {}
    }
    Ok(doc.to_string())
}

/// What one section did.
#[derive(Debug, Clone, Serialize)]
pub struct Applied {
    pub section: &'static str,
    pub ok: bool,
    pub detail: String,
}

fn ok(section: &'static str, detail: impl Into<String>) -> Applied {
    Applied {
        section,
        ok: true,
        detail: detail.into(),
    }
}

fn err(section: &'static str, detail: impl Into<String>) -> Applied {
    Applied {
        section,
        ok: false,
        detail: detail.into(),
    }
}

fn write_file(p: &Path, text: &str) -> std::io::Result<()> {
    if let Some(d) = p.parent() {
        fs::create_dir_all(d)?;
    }
    let tmp = p.with_extension("tmp");
    fs::write(&tmp, text)?;
    fs::rename(&tmp, p)
}

fn now() -> String {
    chrono::Local::now().format("%Y-%m-%d %H:%M").to_string()
}

/// The monitors section: with `found` (from [`detect`]), writes the `bromigos.monitors`
/// block into the user's hyprland.lua and the primary output into monitors.toml.
pub fn apply_monitors(paths: &Paths, a: &MonitorsAnswer, found: &[Monitor]) -> Applied {
    match a.mode.as_str() {
        "skip" => return ok("monitors", "left as is"),
        "auto" => {}
        m => return err("monitors", format!("unknown mode {m:?} (auto or skip)")),
    }
    if found.is_empty() {
        return err(
            "monitors",
            "no connected outputs found; every output stays at its preferred mode",
        );
    }
    for name in a
        .order
        .iter()
        .chain(a.scale.keys())
        .chain(a.refresh.keys())
        .chain(a.primary.iter())
    {
        if !found.iter().any(|m| &m.output == name) {
            let have: Vec<&str> = found.iter().map(|m| m.output.as_str()).collect();
            return err(
                "monitors",
                format!("no output {name:?} here ({})", have.join(", ")),
            );
        }
    }
    if let Some(bad) = a.scale.values().find(|s| !(0.5..=4.0).contains(*s)) {
        return err("monitors", format!("scale {bad} is out of range (0.5-4)"));
    }
    let layout = arrange(found, a);
    let lua_path = hyprland_lua(paths);
    let lua = match fs::read_to_string(&lua_path) {
        Ok(t) => t,
        Err(e) => {
            return err(
                "monitors",
                format!("{}: {e} (bromigos update seeds it)", lua_path.display()),
            );
        }
    };
    let text = match with_monitors_block(&lua, &monitors_block(&layout, &now())) {
        Ok(t) => t,
        Err(e) => return err("monitors", format!("{}: {e}", lua_path.display())),
    };
    // a symlinked hyprland.lua (a dotfiles checkout): write through to its target
    let target = fs::canonicalize(&lua_path).unwrap_or(lua_path.clone());
    if let Err(e) = write_file(&target, &text) {
        return err("monitors", format!("{}: {e}", target.display()));
    }
    let primary = a
        .primary
        .clone()
        .or_else(|| found.iter().find(|m| m.focused).map(|m| m.output.clone()))
        .unwrap_or_else(|| layout[0].0.output.clone());
    if let Err(e) = write_file(
        &monitors_toml(paths),
        &format!(
            "# bromigos setup monitors: the output bromigOS's own surfaces go on\nprimary = \"{primary}\"\n"
        ),
    ) {
        return err(
            "monitors",
            format!("{}: {e}", monitors_toml(paths).display()),
        );
    }
    ok(
        "monitors",
        format!(
            "{} (primary {primary}; Hyprland re-reads its config by itself)",
            layout
                .iter()
                .map(|(m, _)| format!("{} {} @{}x", m.output, m.mode(), trim_float(m.scale)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    )
}

/// The AUR section: `bromigos aur on` or `off` (sudo for bromigOS's paru; pacman asks
/// unless `interactive` is false).
pub fn apply_aur(paths: &Paths, a: &AurAnswer, interactive: bool) -> Applied {
    let mut runner = crate::install::System;
    let r = match a.mode.as_str() {
        "on" => crate::aur::on(paths, &mut runner, !interactive, false),
        "off" => crate::aur::off(paths, &mut runner, !interactive, false),
        m => return err("aur", format!("unknown mode {m:?} (on or off)")),
    };
    match r {
        // on, but paru isn't in the synced repositories yet: the setting is written, and
        // the next update's migration installs it
        Ok(r) => ok("aur", r.detail),
        Err(e) => err("aur", e),
    }
}

/// The hardware section: `bromigos hw setup` (sudo for the system's part; pacman asks
/// unless `interactive` is false, then it takes its defaults).
pub fn apply_hardware(paths: &Paths, a: &HardwareAnswer, interactive: bool) -> Applied {
    use crate::install::Runner;
    match a.mode.as_str() {
        "skip" => return ok("hardware", "left as is (bromigos hw setup, any time)"),
        "auto" => {}
        m => return err("hardware", format!("unknown mode {m:?} (auto or skip)")),
    }
    let files = crate::snapshot::RootFs;
    let d = crate::hw::detect(&files);
    let mut runner = crate::install::System;
    let plan = crate::hw::plan(paths, &d, &mut runner, &files);
    let booted = crate::hw::booted(&files, &mut runner);
    // a driver only the AUR has: built only when someone at the terminal says yes
    let aur_driver =
        interactive && crate::hw::aur_question(&plan).is_some_and(|q| crate::hw::ask(&q));
    let opts = crate::hw::ApplyOpts {
        yes: !interactive,
        now: booted,
        aur_driver,
        ..Default::default()
    };
    let r = crate::hw::apply(paths, &plan, &opts, false, &mut |argv, interactive| {
        let line = crate::install::shell_line(&argv);
        match runner.run(&argv, interactive) {
            Ok((0, _)) => Ok(()),
            Ok((c, _)) => Err(format!("`{line}` exited {c}")),
            Err(e) => Err(format!("`{line}`: {e}")),
        }
    });
    let mut detail = format!("{}: {}", crate::hw::summary(&d), r.detail);
    if !plan.notes.is_empty() {
        detail.push_str(&format!(" (note: {})", plan.notes.join("; ")));
    }
    if r.ok && r.reboot {
        detail.push_str("; reboot for it to take effect");
    }
    if r.ok {
        ok("hardware", detail)
    } else {
        err("hardware", detail)
    }
}

/// The accessibility section: writes the settings, then (`render`) renders the current
/// theme again with them and, inside a live session only, tells the running apps (as
/// `bromigos theme set` does).
pub fn apply_accessibility(paths: &Paths, a: &AccessibilityAnswer, render: bool) -> Applied {
    let s = match crate::accessibility::write(paths, a.motion.as_deref(), a.contrast.as_deref()) {
        Ok(s) => s,
        Err(e) => return err("accessibility", e),
    };
    let what = format!("motion {}, contrast {}", s.motion, s.contrast);
    if !render {
        return ok("accessibility", what);
    }
    let cur = crate::theme::current(paths);
    if let Err(e) = crate::theme::set(paths, &cur.name) {
        return err(
            "accessibility",
            format!("{what}; the theme {} didn't render: {e}", cur.name),
        );
    }
    if crate::session::discover(paths).session.is_some() {
        let _ = crate::theme::reload(paths);
    }
    ok(
        "accessibility",
        format!("{what} (the theme {} rendered with them)", cur.name),
    )
}

pub fn apply_theme(paths: &Paths, a: &ThemeAnswer) -> Applied {
    if let Err(e) = crate::theme::set(paths, &a.name) {
        return err("theme", e.to_string());
    }
    let _ = crate::theme::reload(paths);
    let _ = crate::theme::run_hooks(paths);
    if let Some(den) = a.den.as_deref().filter(|d| !d.is_empty()) {
        let s = Command::new(&paths.wallpaper_bin).arg(den).output();
        if !matches!(&s, Ok(o) if o.status.success()) {
            return err(
                "theme",
                format!(
                    "{} set; the den {den:?} isn't installed (bromigos wallpaper status)",
                    a.name
                ),
            );
        }
        return ok("theme", format!("{} (den: {den})", a.name));
    }
    ok("theme", a.name.clone())
}

/// The boot menu in the theme's colours, turned on where GRUB boots the machine (unless it
/// was turned off here). Unattended, sudo never asks: then the next update does it. None
/// when there's nothing to say (not GRUB, no bromigos-settings).
pub fn apply_boot(paths: &Paths, interactive: bool) -> Option<Applied> {
    let o = crate::boot::sync(
        paths,
        &mut crate::install::System,
        &crate::snapshot::RootFs,
        crate::boot::Enable::Auto,
        interactive,
        false,
    );
    match o.status {
        "failed" => Some(err("boot", o.detail)),
        "skipped" if o.detail.contains("left alone") || o.detail.contains("isn't installed") => {
            None
        }
        _ => Some(ok("boot", o.detail)),
    }
}

pub fn apply_vector(paths: &Paths, a: &VectorAnswer) -> Applied {
    let p = vector_toml(paths);
    let existing = fs::read_to_string(&p).unwrap_or_default();
    match vector_toml_text(&existing, a) {
        Ok(text) => match write_file(&p, &text) {
            Ok(()) => ok(
                "vector",
                match a.backend.as_str() {
                    "none" => "no endpoint set yet: VECTOR tries a local Ollama".to_string(),
                    _ => format!(
                        "{} ({})",
                        a.backend,
                        a.base_url.as_deref().unwrap_or(OLLAMA_URL)
                    ),
                },
            ),
            Err(e) => err("vector", format!("{}: {e}", p.display())),
        },
        Err(e) => err("vector", e),
    }
}

/// The voice muted switch VECTOR reads.
pub fn voice_muted_file(paths: &Paths) -> PathBuf {
    paths.state_home.join("bromigos/vector-voice-muted")
}

/// The voice section. `run_setup`: build the voice environment now (`bromigos-holo setup
/// voice|voice-cpu`; minutes, downloads models); false leaves that to the user.
pub fn apply_voice(paths: &Paths, a: &VoiceAnswer, run_setup: bool) -> Applied {
    let muted = voice_muted_file(paths);
    match a.tier.as_str() {
        "off" => {
            let _ = fs::create_dir_all(muted.parent().unwrap_or(Path::new("/")));
            match fs::write(&muted, "") {
                Ok(()) => ok("voice", "off (vector unmute turns it on)"),
                Err(e) => err("voice", e.to_string()),
            }
        }
        "gpu" | "cpu" => {
            let _ = fs::remove_file(&muted);
            let what = if a.tier == "gpu" {
                "voice"
            } else {
                "voice-cpu"
            };
            if !run_setup {
                return ok(
                    "voice",
                    format!("{}: build it with `bromigos-holo setup {what}`", a.tier),
                );
            }
            let s = Command::new(&paths.holo_bin).args(["setup", what]).status();
            match s {
                Ok(s) if s.success() => {
                    ok("voice", format!("{} (bromigos-holo setup {what})", a.tier))
                }
                Ok(s) => err(
                    "voice",
                    format!(
                        "bromigos-holo setup {what} exited {}",
                        s.code().unwrap_or(-1)
                    ),
                ),
                Err(e) => err("voice", format!("{}: {e}", paths.holo_bin.display())),
            }
        }
        t => err("voice", format!("unknown tier {t:?} (gpu, cpu or off)")),
    }
}

/// The homelab section: copies the given homelab.toml into place (never over the user's
/// own without `replace`), or runs Find my lab.
pub fn apply_homelab(paths: &Paths, a: &HomelabAnswer, replace: bool) -> Applied {
    let Some(src) = a.file.as_deref().filter(|f| !f.is_empty()) else {
        if a.find {
            return find_my_lab(paths);
        }
        return ok("homelab", "skipped (bromigos setup homelab, any time)");
    };
    let dst = homelab_toml(paths);
    if dst.exists() && !replace {
        return ok("homelab", format!("{} kept (yours)", dst.display()));
    }
    match fs::read_to_string(src) {
        Ok(text) => match text.parse::<toml::Table>() {
            Ok(_) => match write_file(&dst, &text) {
                Ok(()) => ok("homelab", format!("{} from {src}", dst.display())),
                Err(e) => err("homelab", e.to_string()),
            },
            Err(e) => err("homelab", format!("{src}: not TOML: {e}")),
        },
        Err(e) => err("homelab", format!("{src}: {e}")),
    }
}

/// Find my lab: bromigos-homelab's detector (`bromigos setup homelab --find`), in this
/// terminal. It says which sources it reads and asks before reading any (docs/homelab.md),
/// then shows a checklist and only appends to homelab.toml.
fn find_my_lab(paths: &Paths) -> Applied {
    let exe = paths.lib_bin.join("bromigos-setup-homelab");
    if !exe.exists() {
        return err(
            "homelab",
            "Find my lab needs bromigos-homelab (sudo pacman -S bromigos-homelab)",
        );
    }
    if !std::io::IsTerminal::is_terminal(&std::io::stdin()) {
        return err(
            "homelab",
            "Find my lab asks first, so it needs a terminal: run bromigos setup homelab --find",
        );
    }
    match Command::new(&exe).arg("--find").status() {
        Ok(s) if s.success() => ok("homelab", "Find my lab (bromigos setup homelab --find)"),
        Ok(s) if s.code() == Some(1) => ok("homelab", "Find my lab: nothing added"),
        Ok(s) => err(
            "homelab",
            format!(
                "bromigos setup homelab --find exited {}",
                s.code().unwrap_or(-1)
            ),
        ),
        Err(e) => err("homelab", format!("{}: {e}", exe.display())),
    }
}

/// Copies a nolgia personal access token from `src` into the file bromigos art reads
/// (`$XDG_DATA_HOME/bromigos/nolgia-token`, created 0600). The token is never printed:
/// errors name the file, not its contents.
fn store_nolgia_token(src: &str) -> Result<std::path::PathBuf, String> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let text = fs::read_to_string(src).map_err(|e| format!("{src}: {e}"))?;
    let token = text.trim();
    if token.is_empty() || token.contains(char::is_whitespace) {
        return Err(format!("{src}: expected one token on one line"));
    }
    let data = std::env::var_os("XDG_DATA_HOME")
        .filter(|v| !v.is_empty())
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
                .join(".local/share")
        });
    let dst = data.join("bromigos/nolgia-token");
    fs::create_dir_all(dst.parent().unwrap()).map_err(|e| e.to_string())?;
    let tmp = dst.with_extension("tmp");
    let mut f = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(&tmp)
        .map_err(|e| format!("{}: {e}", tmp.display()))?;
    f.write_all(format!("{token}\n").as_bytes())
        .map_err(|e| e.to_string())?;
    fs::rename(&tmp, &dst).map_err(|e| format!("{}: {e}", dst.display()))?;
    Ok(dst)
}

/// The create section: checks the choice against the servers found, writes create.toml,
/// then nolgia's sign-in when asked (interactive only).
pub fn apply_create(
    paths: &Paths,
    a: &crate::create::CreateAnswer,
    servers: &[crate::create::Server],
    interactive: bool,
) -> Applied {
    use crate::create;
    if let Err(e) = create::validate(a, servers) {
        return err("create", e);
    }
    let existing = fs::read_to_string(create::create_toml(paths)).unwrap_or_default();
    let text = match create::create_toml_text(&existing, a, servers) {
        Ok(t) => t,
        Err(e) => return err("create", e),
    };
    if let Err(e) = create::write(paths, &text) {
        return err(
            "create",
            format!("{}: {e}", create::create_toml(paths).display()),
        );
    }
    let picked: Vec<String> = create::CAPABILITIES
        .iter()
        .filter_map(|c| {
            a.providers
                .get(*c)
                .map(|p| format!("{c} {}", p.join(" > ")))
        })
        .collect();
    let mut detail = picked.join(", ");
    if let Some(src) = a.nolgia_token_file.as_deref() {
        match store_nolgia_token(src) {
            Ok(dst) => detail.push_str(&format!(
                "; nolgia token stored in {} (from {src})",
                dst.display()
            )),
            Err(e) => return err("create", format!("{detail}; nolgia token: {e}")),
        }
    }
    if a.nolgia_login {
        if !interactive {
            detail.push_str("; nolgia sign-in skipped (needs a terminal: nolgia auth login)");
        } else {
            match Command::new("nolgia").args(["auth", "login"]).status() {
                Ok(s) if s.success() => detail.push_str("; nolgia signed in"),
                Ok(s) => {
                    return err(
                        "create",
                        format!(
                            "{detail}; nolgia auth login exited {}",
                            s.code().unwrap_or(-1)
                        ),
                    );
                }
                Err(_) => {
                    return err(
                        "create",
                        format!("{detail}; the nolgia CLI isn't installed"),
                    );
                }
            }
        }
    }
    ok("create", detail)
}

/// Applies every answered section, in [`SECTIONS`] order, and records them.
pub fn apply(
    paths: &Paths,
    a: &Answers,
    found: &[Monitor],
    servers: &[crate::create::Server],
    interactive: bool,
    replace: bool,
) -> Vec<Applied> {
    let mut out = vec![];
    if let Some(m) = &a.monitors {
        out.push(apply_monitors(paths, m, found));
    }
    // before the hardware: its AUR-only drivers are offered through the helper
    if let Some(x) = &a.aur {
        out.push(apply_aur(paths, x, interactive));
    }
    if let Some(h) = &a.hardware {
        out.push(apply_hardware(paths, h, interactive));
    }
    if let Some(x) = &a.accessibility {
        // the theme section, when it's answered too, renders with them
        out.push(apply_accessibility(paths, x, a.theme.is_none()));
    }
    if let Some(e) = &a.extensions {
        out.push(apply_extensions(paths, e));
    }
    if let Some(t) = &a.theme {
        out.push(apply_theme(paths, t));
        if let Some(b) = apply_boot(paths, interactive) {
            out.push(b);
        }
    }
    if let Some(v) = &a.vector {
        out.push(apply_vector(paths, v));
    }
    if let Some(v) = &a.voice {
        out.push(apply_voice(paths, v, interactive));
    }
    if let Some(h) = &a.homelab {
        out.push(apply_homelab(paths, h, replace));
    }
    if let Some(t) = &a.targets {
        out.push(apply_targets(paths, t));
    }
    if let Some(c) = &a.create {
        out.push(apply_create(paths, c, servers, interactive));
    }
    if let Some(p) = &a.peripherals {
        out.push(apply_peripherals(paths, p, interactive));
    }
    record(paths, a, &out);
    out
}

/// Keeps what was answered (and when) in setup.toml, merged with earlier runs.
fn record(paths: &Paths, a: &Answers, done: &[Applied]) {
    let p = state_file(paths);
    let mut prev: Answers = fs::read_to_string(&p)
        .ok()
        .and_then(|s| toml::from_str(&s).ok())
        .unwrap_or_default();
    let okd = |s: &str| done.iter().any(|d| d.section == s && d.ok);
    if okd("monitors") {
        prev.monitors = a.monitors.clone();
    }
    if okd("aur") {
        prev.aur = a.aur.clone();
    }
    if okd("hardware") {
        prev.hardware = a.hardware.clone();
    }
    if okd("accessibility") {
        prev.accessibility = a.accessibility.clone();
    }
    if okd("extensions") {
        prev.extensions = a.extensions.clone();
    }
    if okd("theme") {
        prev.theme = a.theme.clone();
    }
    if okd("vector") {
        prev.vector = a.vector.clone();
    }
    if okd("voice") {
        prev.voice = a.voice.clone();
    }
    if okd("homelab") {
        prev.homelab = a.homelab.clone();
    }
    if okd("targets") {
        prev.targets = a.targets.clone();
    }
    if okd("create") {
        prev.create = a.create.clone();
    }
    if okd("peripherals") {
        prev.peripherals = a.peripherals.clone();
    }
    if let Ok(text) = toml::to_string(&prev) {
        let _ = write_file(
            &p,
            &format!(
                "# bromigos setup's answers ({}); `bromigos setup` changes them\n{text}",
                now()
            ),
        );
    }
}

/// Whether the first run has happened (any answer recorded).
pub fn done_before(paths: &Paths) -> bool {
    state_file(paths).exists()
}

/// Answers from a TOML file.
pub fn load_answers(p: &Path) -> Result<Answers, String> {
    let text = fs::read_to_string(p).map_err(|e| format!("{}: {e}", p.display()))?;
    let mut a: Answers = toml::from_str(&text).map_err(|e| format!("{}: {e}", p.display()))?;
    if let Some(e) = a.extensions.as_mut() {
        let sha = crate::ext::sha256_file(p).unwrap_or_default();
        let abs = fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf());
        e.from = format!("answers file {} (sha256 {sha})", abs.display());
    }
    Ok(a)
}

/// The extensions section: each source installed as `bromigos ext install` would, the
/// ones that run code approved by this file only when it says `approve = true`.
pub fn apply_extensions(paths: &Paths, a: &ExtensionsAnswer) -> Applied {
    let (mut done, mut failed) = (vec![], vec![]);
    for item in &a.install {
        let (src, opts) = item.parts();
        let from = if a.from.is_empty() {
            "setup answers".to_owned()
        } else {
            a.from.clone()
        };
        let r = crate::ext::install(paths, &src, &opts, &mut |_| {
            a.approve
                .then(|| crate::ext::Approval::Answers(from.clone()))
        });
        match r {
            Ok(r) => done.push(r.name),
            Err(e) if e.0.contains("is already installed") => done.push(format!("{src} (already)")),
            Err(e) => failed.push(format!("{src}: {e}")),
        }
    }
    let detail = if done.is_empty() {
        "nothing installed".to_owned()
    } else {
        format!("installed {}", done.join(", "))
    };
    if failed.is_empty() {
        ok("extensions", detail)
    } else {
        err(
            "extensions",
            format!("{detail}; failed: {}", failed.join("; ")),
        )
    }
}

/// The peripherals section: each module turned on (`bromigos peripheral enable`: what it
/// needs, the choice, the keys, the daemon) or off. Unattended, pacman doesn't ask.
pub fn apply_peripherals(paths: &Paths, a: &PeripheralsAnswer, interactive: bool) -> Applied {
    use crate::peripheral as pm;
    let root = pm::root();
    let mut runner = crate::install::System;
    let (mut done, mut failed, mut notes) = (vec![], vec![], vec![]);
    for id in &a.enable {
        let o = pm::EnableOpts {
            yes: !interactive,
            force: a.force,
            reload: true,
            system: a.system,
        };
        match pm::enable(paths, &root, id, o, &mut runner) {
            Ok(r) if r.ok => {
                done.push(format!("{id} on"));
                notes.extend(r.notes);
            }
            Ok(r) => failed.push(format!(
                "{id}: {}",
                r.error
                    .or_else(|| r.hypr.map(|w| w.reload))
                    .unwrap_or_default()
            )),
            Err(e) => failed.push(e),
        }
    }
    for id in &a.disable {
        match pm::disable(paths, &root, id, true, a.system, &mut runner) {
            Ok(Some(r)) if !r.ok => failed.push(format!(
                "{id}: {}",
                r.error
                    .or_else(|| r.hypr.map(|w| w.reload))
                    .unwrap_or_default()
            )),
            Ok(_) => done.push(format!("{id} off")),
            Err(e) => failed.push(e),
        }
    }
    let mut detail = if done.is_empty() {
        "none turned on (bromigos peripheral list)".to_string()
    } else {
        done.join(", ")
    };
    if !notes.is_empty() {
        detail.push_str(&format!("; {}", notes.join("; ")));
    }
    if failed.is_empty() {
        ok("peripherals", detail)
    } else {
        err(
            "peripherals",
            format!("{detail}; failed: {}", failed.join("; ")),
        )
    }
}
