//! Accessibility (docs/accessibility.md): how much the desktop moves, and how strongly its
//! colours contrast.
//!
//! The settings are the user's, in `~/.config/bromigos/accessibility.toml` (an update never
//! touches it; `bromigos accessibility` and `bromigos setup accessibility` write it):
//!
//! ```toml
//! motion = "reduced"   # "full" (default) | "reduced" | "still"
//! contrast = "high"    # "normal" (default) | "high"
//! ```
//!
//! - **motion** is read by the live layer (it calms or stills its worlds, the den and its
//!   overlays) and rendered into the theme's `hyprland.lua` and `palette.json` (Hyprland's own
//!   animations, the widgets, VECTOR).
//! - **contrast** is applied by the theme system: `bromigos theme set` renders every template
//!   and `palette.json` from [`high_contrast`]'s colours instead of the theme's, so the bar,
//!   the menus, the notifications, the terminal, the widgets and the holograms all follow.
//!   The targets are WCAG 2.1's: text 7:1 (AAA), quiet text 4.5:1, borders and selection 3:1.
//!   Colour maths (OKLCH, relative luminance and contrast) is the `palette` crate's.

use std::fs;
use std::path::PathBuf;

use palette::color_difference::Wcag21RelativeContrast;
use palette::convert::FromColorUnclamped;
use palette::{FromColor, IsWithinBounds, Oklch, Srgb};
use serde::Serialize;

use crate::paths::Paths;
use crate::theme::Colors;

/// The motion settings, calmest last.
pub const MOTIONS: &[&str] = &["full", "reduced", "still"];
/// The contrast settings.
pub const CONTRASTS: &[&str] = &["normal", "high"];

/// What the user chose (the defaults when the file says nothing).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Settings {
    /// `full`, `reduced` or `still`.
    pub motion: String,
    /// `normal` or `high`.
    pub contrast: String,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            motion: "full".into(),
            contrast: "normal".into(),
        }
    }
}

impl Settings {
    pub fn high_contrast(&self) -> bool {
        self.contrast == "high"
    }
}

/// The settings and how they were read.
#[derive(Debug, Clone, Serialize)]
pub struct Loaded {
    pub settings: Settings,
    pub path: PathBuf,
    /// The file exists (else everything is the default).
    pub exists: bool,
    /// Values the file has that aren't settings (each read as the default), or why it
    /// couldn't be read.
    pub problems: Vec<String>,
}

/// `~/.config/bromigos/accessibility.toml`.
pub fn path(paths: &Paths) -> PathBuf {
    paths.user_config_dir().join("accessibility.toml")
}

/// Reads the settings. A missing file is the defaults; a value that isn't one of the
/// choices reads as the default for that key (and is reported).
pub fn load(paths: &Paths) -> Loaded {
    let p = path(paths);
    let mut out = Loaded {
        settings: Settings::default(),
        path: p.clone(),
        exists: false,
        problems: vec![],
    };
    let text = match fs::read_to_string(&p) {
        Ok(t) => t,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return out,
        Err(e) => {
            out.problems.push(format!("{}: {e}", p.display()));
            return out;
        }
    };
    out.exists = true;
    let doc: toml::Table = match text.parse() {
        Ok(d) => d,
        Err(e) => {
            out.problems.push(format!("{}: {e}", p.display()));
            return out;
        }
    };
    for (key, choices) in [("motion", MOTIONS), ("contrast", CONTRASTS)] {
        match doc.get(key) {
            None => {}
            Some(toml::Value::String(v)) if choices.contains(&v.as_str()) => {
                if key == "motion" {
                    out.settings.motion = v.clone();
                } else {
                    out.settings.contrast = v.clone();
                }
            }
            Some(v) => out.problems.push(format!(
                "{key} = {v}: not one of {} (read as {:?})",
                choices.join(", "),
                choices[0]
            )),
        }
    }
    out
}

/// The settings in force (the defaults when the file is missing or unreadable).
pub fn read(paths: &Paths) -> Settings {
    load(paths).settings
}

const HEADER: &str = "\
# Accessibility: yours (`bromigos accessibility`, `bromigos setup accessibility` write it;
# an update never touches it). docs/accessibility.md, the manual's Accessibility page.
#   motion   = \"full\" | \"reduced\" (calmer and slower: no parallax, flicker or flashes)
#              | \"still\" (the live background holds a still frame)
#   contrast = \"normal\" | \"high\" (every colour the theme renders, raised to WCAG AAA)
";

/// Sets `motion` and/or `contrast` (None leaves one as it is) and returns the settings
/// now in force. Comments and other keys in the file are kept; the write is atomic and
/// goes through a symlink (a dotfiles checkout) to its target.
pub fn write(
    paths: &Paths,
    motion: Option<&str>,
    contrast: Option<&str>,
) -> Result<Settings, String> {
    if let Some(m) = motion
        && !MOTIONS.contains(&m)
    {
        return Err(format!("motion {m:?}: one of {}", MOTIONS.join(", ")));
    }
    if let Some(c) = contrast
        && !CONTRASTS.contains(&c)
    {
        return Err(format!("contrast {c:?}: one of {}", CONTRASTS.join(", ")));
    }
    let p = path(paths);
    let existing = match fs::read_to_string(&p) {
        Ok(t) => Some(t),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
        Err(e) => return Err(format!("{}: {e}", p.display())),
    };
    let mut doc: toml_edit::DocumentMut = match &existing {
        Some(t) => t
            .parse()
            .map_err(|e| format!("{}: {e} (fix or remove it; nothing written)", p.display()))?,
        None => toml_edit::DocumentMut::new(),
    };
    if let Some(m) = motion {
        doc["motion"] = toml_edit::value(m);
    }
    if let Some(c) = contrast {
        doc["contrast"] = toml_edit::value(c);
    }
    let target = fs::canonicalize(&p).unwrap_or_else(|_| p.clone());
    if let Some(d) = target.parent() {
        fs::create_dir_all(d).map_err(|e| format!("{}: {e}", d.display()))?;
    }
    let tmp = target.with_extension("toml.tmp");
    // a new file starts with what the keys mean (toml_edit would put a parsed header last)
    let text = match existing {
        Some(_) => doc.to_string(),
        None => format!("{HEADER}{doc}"),
    };
    fs::write(&tmp, text).map_err(|e| format!("{}: {e}", tmp.display()))?;
    fs::rename(&tmp, &target).map_err(|e| format!("{}: {e}", target.display()))?;
    Ok(read(paths))
}

// ------------------------------------------------------------------ contrast

/// Text: body text, live values, labels (WCAG 2.1 AAA, 1.4.6).
pub const TEXT: f64 = 7.0;
/// Quiet text (dim, muted, faint), accents, terminal colours, and text on the selection
/// (AA, 1.4.3).
pub const QUIET: f64 = 4.5;
/// Borders, rules, graphs and the selection against what's around them (1.4.11).
pub const UI: f64 = 3.0;

fn srgb(hex: &str) -> Srgb<f32> {
    let h = hex.trim_start_matches('#');
    let c = |i: usize| u8::from_str_radix(h.get(i..i + 2).unwrap_or("00"), 16).unwrap_or(0);
    Srgb::new(c(0), c(2), c(4)).into_format()
}

fn hex(c: Srgb<f32>) -> String {
    let c: Srgb<u8> = c.into_format();
    format!("#{:02x}{:02x}{:02x}", c.red, c.green, c.blue)
}

/// The WCAG 2.1 contrast ratio of two `#rrggbb` colours (1 to 21).
pub fn ratio(a: &str, b: &str) -> f64 {
    srgb(a).relative_contrast(srgb(b)) as f64
}

/// A colour's relative luminance (WCAG 2.1), 0 to 1.
pub fn luminance(c: &str) -> f64 {
    srgb(c).relative_luminance().luma as f64
}

/// The colour at OKLCH lightness `l` with `c`'s hue, its chroma lowered only as far as
/// sRGB needs (so the hue never shifts).
fn at_lightness(c: Oklch<f32>, l: f32) -> Srgb<f32> {
    // unclamped: `from_color` would clamp into sRGB, which shifts the hue
    let try_chroma = |chroma: f32| Srgb::from_color_unclamped(Oklch::new(l, chroma, c.hue));
    let full = try_chroma(c.chroma);
    if full.is_within_bounds() {
        return full;
    }
    let (mut lo, mut hi) = (0.0f32, c.chroma);
    for _ in 0..24 {
        let mid = (lo + hi) / 2.0;
        if try_chroma(mid).is_within_bounds() {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    let s = try_chroma(lo);
    Srgb::new(
        s.red.clamp(0.0, 1.0),
        s.green.clamp(0.0, 1.0),
        s.blue.clamp(0.0, 1.0),
    )
}

/// `fg` moved lighter (or darker) in OKLCH, hue kept, just far enough to reach `min`
/// against every colour in `against`; unchanged when it already does. White (or black)
/// when nothing short of that reaches it.
fn fit(fg: &str, against: &[String], min: f64, lighter: bool) -> String {
    let ok = |h: &str| against.iter().all(|b| ratio(h, b) >= min);
    if ok(fg) {
        return fg.to_owned();
    }
    let c = Oklch::from_color(srgb(fg));
    let end = if lighter { 1.0 } else { 0.0 };
    // the least change that works: bisect the lightness between the colour's and the end
    let (mut lo, mut hi) = (c.l, end);
    if !ok(&hex(at_lightness(c, hi))) {
        return hex(at_lightness(c, end));
    }
    for _ in 0..32 {
        let mid = (lo + hi) / 2.0;
        if ok(&hex(at_lightness(c, mid))) {
            hi = mid;
        } else {
            lo = mid;
        }
    }
    // rounding to 8 bits can land just short: step on until it holds
    let step = if lighter { 0.002 } else { -0.002 };
    let mut l = hi;
    for _ in 0..600 {
        let h = hex(at_lightness(c, l));
        if ok(&h) {
            return h;
        }
        l = (l + step).clamp(0.0, 1.0);
    }
    hex(at_lightness(c, end))
}

/// A surface pushed toward the theme's own end (darker on a dark theme): lightness scaled
/// by `keep`, hue kept and chroma eased off a little, so text on it has room.
fn deepen(bg: &str, dark: bool, keep: f32) -> String {
    let c = Oklch::from_color(srgb(bg));
    let l = if dark {
        c.l * keep
    } else {
        1.0 - (1.0 - c.l) * keep
    };
    hex(at_lightness(Oklch::new(c.l, c.chroma * 0.85, c.hue), l))
}

/// How a colour is used, which says what it must contrast with.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Role {
    /// A background: deepened.
    Surface,
    /// The selected row and inactive borders: 3:1 against the surfaces, with room for
    /// text on it.
    Selection,
    /// 7:1 against the surfaces, 4.5:1 on the selection.
    Text,
    /// 4.5:1 against the surfaces.
    Quiet,
    /// warn, danger: 7:1 against the surfaces.
    Signal,
    /// danger_text: 7:1 on danger_surface.
    OnDanger,
    /// Lines, frames, graphs: 3:1 against the surfaces.
    Ui,
    /// A meter's empty track: 3:1 against the panel.
    Track,
    /// Named hues and accents: 4.5:1 against the surfaces.
    Accent,
    /// The terminal's foreground: 7:1 against its background.
    TermText,
    /// The terminal's colours 1-15: 4.5:1 against its background.
    TermColor,
    /// Left as the theme has it (the live layer's intercept, drawn over a captured screen).
    Keep,
}

fn role_of(table: Option<&str>, key: &str) -> Option<Role> {
    use Role::*;
    Some(match (table, key) {
        (None, "background" | "void" | "panel" | "warn_surface" | "danger_surface") => Surface,
        (None, "selection") => Selection,
        (None, "primary" | "soft" | "text") => Text,
        (None, "dim" | "muted" | "faint") => Quiet,
        (None, "warn" | "danger") => Signal,
        (None, "danger_text") => OnDanger,
        (None, "white") => Text,
        (Some("holo"), "label" | "highlight") => Text,
        (Some("holo"), "line" | "glow") => Ui,
        (Some("widgets"), "header" | "value") => Text,
        (Some("widgets"), "frame" | "graph") => Ui,
        (Some("widgets"), "track") => Track,
        (Some("terminal"), "background" | "color0") => Surface,
        (Some("terminal"), "foreground") => TermText,
        (Some("terminal"), k) if k.starts_with("color") => TermColor,
        (Some("qt"), _) => Surface,
        (Some("intercept"), _) => Keep,
        _ => return None,
    })
}

/// The theme's colours made high-contrast (see the module docs and docs/accessibility.md).
/// Every colour keeps its hue; only its lightness moves (its chroma only where sRGB needs),
/// and a colour that already contrasts enough is left exactly as it was.
pub fn high_contrast(colors: &Colors) -> Colors {
    let get = |k: &str| colors.get(k).unwrap_or("#000000").to_owned();
    let bg0 = get("background");
    let dark = luminance(&bg0) < 0.18;
    let lighter = dark;
    // surfaces first: everything else is fitted against them
    let surf = |c: &str| deepen(c, dark, 0.45);
    let background = surf(&bg0);
    let void = colors.get("void").map_or_else(|| background.clone(), surf);
    let panel = colors.get("panel").map_or_else(|| background.clone(), surf);
    let surfaces = vec![background.clone(), void.clone(), panel.clone()];
    // the selection: 3:1 against the surfaces, but never so light (dark) that text on it
    // can't reach 4.5:1
    let selection = {
        let s = fit(
            colors.get("selection").unwrap_or(&panel),
            &surfaces,
            UI,
            lighter,
        );
        let best = if dark { "#ffffff" } else { "#000000" };
        if ratio(best, &s) >= QUIET + 0.6 {
            s
        } else {
            // back off toward the surfaces until text fits again
            let c = Oklch::from_color(srgb(&s));
            let mut l = c.l;
            let mut out = s.clone();
            for _ in 0..400 {
                l += if dark { -0.002 } else { 0.002 };
                out = hex(at_lightness(c, l));
                if ratio(best, &out) >= QUIET + 0.6 {
                    break;
                }
            }
            out
        }
    };
    let danger_surface = colors
        .get("danger_surface")
        .map_or_else(|| background.clone(), surf);
    let warn_surface = colors
        .get("warn_surface")
        .map_or_else(|| background.clone(), surf);
    let term_bg = colors
        .tables
        .get("terminal")
        .and_then(|t| t.get("background"))
        .map_or_else(|| background.clone(), |c| surf(c));
    let on_rows = [selection.clone(), warn_surface.clone()];

    let apply = |table: Option<&str>, key: &str, value: &str| -> String {
        let role = role_of(table, key).unwrap_or_else(|| {
            // a name the roles don't know: a background if it sits close to one
            if ratio(value, &bg0) < 1.6 {
                Role::Surface
            } else {
                Role::Accent
            }
        });
        let with_rows = |c: String, min_rows: f64| -> String {
            // text that's also drawn on the selection: lift it further if it must
            if on_rows.iter().all(|r| ratio(&c, r) >= min_rows) {
                c
            } else {
                let mut all = surfaces.clone();
                all.extend(on_rows.iter().cloned());
                fit(&c, &all, min_rows.max(TEXT), lighter)
            }
        };
        match role {
            Role::Surface => match (table, key) {
                (None, "background") => background.clone(),
                (None, "void") => void.clone(),
                (None, "panel") => panel.clone(),
                (None, "danger_surface") => danger_surface.clone(),
                (None, "warn_surface") => warn_surface.clone(),
                (Some("terminal"), "background") => term_bg.clone(),
                // colour 0 is the terminal's black: a surface, kept as dark as its background
                (Some("terminal"), "color0") => {
                    if ratio(value, &term_bg) < 1.6 {
                        surf(value)
                    } else {
                        fit(value, std::slice::from_ref(&term_bg), UI, lighter)
                    }
                }
                _ => surf(value),
            },
            Role::Selection => selection.clone(),
            Role::Text => with_rows(fit(value, &surfaces, TEXT, lighter), QUIET),
            Role::Quiet => fit(value, &surfaces, QUIET, lighter),
            Role::Signal => fit(value, &surfaces, TEXT, lighter),
            Role::OnDanger => {
                let mut against = vec![danger_surface.clone()];
                against.extend(surfaces.iter().cloned());
                fit(value, &against, TEXT, lighter)
            }
            Role::Ui => fit(value, &surfaces, UI + 0.5, lighter),
            Role::Track => fit(value, std::slice::from_ref(&panel), UI, lighter),
            Role::Accent => fit(value, &surfaces, QUIET, lighter),
            Role::TermText => fit(value, std::slice::from_ref(&term_bg), TEXT, lighter),
            Role::TermColor => fit(value, std::slice::from_ref(&term_bg), QUIET, lighter),
            Role::Keep => value.to_owned(),
        }
    };

    let mut out = Colors::default();
    for (k, v) in &colors.palette {
        out.palette.push((k.clone(), apply(None, k, v)));
    }
    for (t, m) in &colors.tables {
        let mut mm = std::collections::BTreeMap::new();
        for (k, v) in m {
            mm.insert(k.clone(), apply(Some(t), k, v));
        }
        out.tables.insert(t.clone(), mm);
    }
    // a meter's fill against its own track, not only the panel
    if let Some(w) = out.tables.get_mut("widgets")
        && let (Some(track), Some(graph)) = (w.get("track").cloned(), w.get("graph").cloned())
    {
        let mut against = vec![track];
        against.extend(surfaces.iter().cloned());
        w.insert("graph".into(), fit(&graph, &against, UI + 0.5, lighter));
    }
    out
}

/// One measured pair.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Check {
    /// The colour drawn (a role, or `table.key`).
    pub fg: String,
    /// What it's drawn on.
    pub bg: String,
    /// WCAG 2.1 contrast ratio, rounded to 2 places.
    pub ratio: f64,
    /// What high contrast promises for this pair.
    pub min: f64,
    pub ok: bool,
}

/// How the rendered colours contrast: the pairs that matter, measured against what high
/// contrast promises (so a normal theme shows where it falls short).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Report {
    /// `normal` or `high`.
    pub mode: String,
    /// Every pair meets its minimum.
    pub ok: bool,
    /// The pair with the least margin over its minimum.
    pub lowest: Option<Check>,
    pub checks: Vec<Check>,
}

/// The checks for `colors` (the ones a theme defines; missing ones are skipped).
pub fn checks(colors: &Colors) -> Vec<Check> {
    let get = |k: &str| -> Option<String> {
        match k.split_once('.') {
            Some((t, kk)) => colors.tables.get(t).and_then(|m| m.get(kk)).cloned(),
            None => colors.get(k).map(str::to_owned),
        }
    };
    let mut out = vec![];
    let mut pair = |fg: &str, bg: &str, min: f64| {
        if let (Some(f), Some(b)) = (get(fg), get(bg)) {
            let r = (ratio(&f, &b) * 100.0).floor() / 100.0;
            out.push(Check {
                fg: fg.into(),
                bg: bg.into(),
                ratio: r,
                min,
                ok: r >= min,
            });
        }
    };
    for bg in ["background", "panel", "void"] {
        for fg in ["text", "soft", "primary", "warn", "danger"] {
            pair(fg, bg, TEXT);
        }
        for fg in ["dim", "muted", "faint"] {
            pair(fg, bg, QUIET);
        }
        pair("selection", bg, UI);
    }
    for fg in ["text", "soft", "primary"] {
        pair(fg, "selection", QUIET);
    }
    pair("danger_text", "danger_surface", TEXT);
    pair("widgets.value", "panel", TEXT);
    pair("widgets.header", "panel", TEXT);
    pair("widgets.frame", "panel", UI);
    pair("widgets.graph", "widgets.track", UI);
    pair("holo.label", "background", TEXT);
    pair("terminal.foreground", "terminal.background", TEXT);
    for i in (1..16).filter(|i| *i != 8) {
        pair(&format!("terminal.color{i}"), "terminal.background", QUIET);
    }
    pair("terminal.color8", "terminal.background", QUIET);
    out
}

/// The report for colours rendered in `mode`.
pub fn report(colors: &Colors, mode: &str) -> Report {
    let checks = checks(colors);
    let lowest = checks
        .iter()
        .min_by(|a, b| (a.ratio / a.min).total_cmp(&(b.ratio / b.min)))
        .cloned();
    Report {
        mode: mode.to_owned(),
        ok: checks.iter().all(|c| c.ok),
        lowest,
        checks,
    }
}

/// The hue of `#rrggbb` in OKLCH degrees, and its chroma (for the tests: high contrast
/// keeps hues).
pub fn hue_chroma(c: &str) -> (f64, f64) {
    let o = Oklch::from_color(srgb(c));
    (o.hue.into_positive_degrees() as f64, o.chroma as f64)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn colors(pairs: &[(&str, &str)], terminal: &[(&str, &str)]) -> Colors {
        let mut c = Colors::default();
        for (k, v) in pairs {
            c.palette.push((k.to_string(), v.to_string()));
        }
        if !terminal.is_empty() {
            c.tables.insert(
                "terminal".into(),
                terminal
                    .iter()
                    .map(|(k, v)| (k.to_string(), v.to_string()))
                    .collect(),
            );
        }
        c
    }

    #[test]
    fn ratios_are_wcags() {
        assert!((ratio("#000000", "#ffffff") - 21.0).abs() < 0.01);
        assert!((ratio("#777777", "#ffffff") - 4.48).abs() < 0.02);
        assert_eq!(ratio("#123456", "#123456"), 1.0);
    }

    #[test]
    fn a_colour_that_already_contrasts_is_left_alone() {
        let c = colors(
            &[
                ("background", "#000000"),
                ("panel", "#000000"),
                ("text", "#ffffff"),
            ],
            &[],
        );
        let h = high_contrast(&c);
        assert_eq!(h.get("text"), Some("#ffffff"));
    }

    #[test]
    fn dark_and_light_themes_reach_the_targets() {
        for (bg, panel, sel, text, dim) in [
            ("#202428", "#2a2f35", "#3a4048", "#8a929a", "#4a5058"),
            ("#f4f1e8", "#ebe6d6", "#d8d2bf", "#6a6458", "#b0a890"),
        ] {
            let c = colors(
                &[
                    ("background", bg),
                    ("void", bg),
                    ("panel", panel),
                    ("selection", sel),
                    ("primary", "#4a90d9"),
                    ("soft", text),
                    ("text", text),
                    ("dim", dim),
                    ("muted", dim),
                    ("faint", dim),
                    ("warn", "#c8a040"),
                    ("danger", "#d04a40"),
                ],
                &[
                    ("background", bg),
                    ("foreground", text),
                    ("color4", "#3060a0"),
                ],
            );
            let h = high_contrast(&c);
            let r = report(&h, "high");
            assert!(
                r.ok,
                "{bg}: {:?}",
                r.checks.iter().filter(|c| !c.ok).collect::<Vec<_>>()
            );
            // hues kept where there was colour to keep
            for k in ["primary", "warn", "danger"] {
                let (h0, c0) = hue_chroma(c.get(k).unwrap());
                let (h1, c1) = hue_chroma(h.get(k).unwrap());
                if c0 > 0.05 && c1 > 0.03 {
                    let d = ((h0 - h1 + 540.0) % 360.0 - 180.0).abs();
                    assert!(d < 25.0, "{k}: hue {h0:.0} -> {h1:.0}");
                }
            }
        }
    }

    #[test]
    fn settings_round_trip_and_keep_comments() {
        let d = tempfile::tempdir().unwrap();
        let home = d.path().to_path_buf();
        let paths = Paths::from_lookup(|k| (k == "HOME").then(|| home.clone()));
        assert_eq!(read(&paths), Settings::default());
        let s = write(&paths, Some("reduced"), None).unwrap();
        assert_eq!(s.motion, "reduced");
        assert_eq!(s.contrast, "normal");
        let p = path(&paths);
        let mut text = fs::read_to_string(&p).unwrap();
        assert!(text.starts_with("# Accessibility"));
        text.push_str("# mine\nother = 1\n");
        fs::write(&p, text).unwrap();
        let s = write(&paths, None, Some("high")).unwrap();
        assert_eq!(
            (s.motion.as_str(), s.contrast.as_str()),
            ("reduced", "high")
        );
        let text = fs::read_to_string(&p).unwrap();
        assert!(text.contains("# mine") && text.contains("other = 1"));
        assert!(write(&paths, Some("fast"), None).is_err());
        fs::write(&p, "motion = \"wobbly\"\ncontrast = \"high\"\n").unwrap();
        let l = load(&paths);
        assert_eq!(l.settings.motion, "full");
        assert_eq!(l.settings.contrast, "high");
        assert_eq!(l.problems.len(), 1);
    }
}
