//! Themes as data (docs/theming.md).
//!
//! A theme is a directory, `themes/<name>/`: `theme.toml` (its name, description,
//! light or dark), `colors.toml` (semantic colour roles), `backgrounds/` and `live/`
//! (a world for the live layer: layered art, `live/world.toml` and its actors; copied
//! into `current/` like every other file, where the live layer reads them) and,
//! reserved for later, the rest of the environment (`holo/`, `widgets/`, `icons/`,
//! `sounds/`, `lock/`). `bromigos theme set <name>` renders every app's colours from
//! the templates in `theme/templates/*.tpl` (minijinja) into a staging directory and
//! swaps it atomically into `~/.local/state/bromigos/theme/current/`.
//!
//! Search path, later wins: the first-party theme in `$BROMIGOS_SHARE_DIR/themes/<name>/`
//! (`/usr/share/bromigos`), then the user's `~/.config/bromigos/themes/<name>/`. Their
//! `colors.toml` and `theme.toml` merge table by table; any other file the user has
//! replaces the first-party one. A file a theme ships under a template's output name
//! (say `kitty.conf`) is used as is, and that template is skipped. User templates in
//! `~/.config/bromigos/theme/templates/` replace first-party ones of the same name.

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use minijinja::{AutoEscape, Environment, UndefinedBehavior};
use serde::Serialize;

use crate::accessibility::{self, Settings};
use crate::ipc::{self, IpcError};
use crate::paths::Paths;
use crate::session;

/// The theme in force when none has been set.
pub const DEFAULT_THEME: &str = "wick";

/// The file in `current/` that names the theme it was rendered from.
const NAME_FILE: &str = "name";
/// The resolved palette for the apps that read colours at runtime (the widgets,
/// VECTOR, the live layer's decks, the waybar scripts): see [`palette_json`].
pub const PALETTE_FILE: &str = "palette.json";
/// A theme's own emblem kit (its `emblem/` folder, the Wick's brand/ kit by the same
/// names: emblem.svg, emblem-ring.svg, emblem-flame.svg, emblem-small.svg, the PNG
/// sizes, emblem.braille). The bar's `icons/emblem.svg` is made from its emblem-small.svg.
pub const EMBLEM_FILE: &str = "emblem/emblem-small.svg";

#[derive(Debug, thiserror::Error)]
pub enum ThemeError {
    #[error("unknown theme: {name} (themes: {})", .available.join(", "))]
    Unknown {
        name: String,
        available: Vec<String>,
    },
    #[error("not a theme name: {0:?} (lowercase letters, digits, - and _)")]
    BadName(String),
    #[error("{}: {message}", .path.display())]
    Invalid { path: PathBuf, message: String },
    #[error("{}: {source}", .path.display())]
    Io { path: PathBuf, source: io::Error },
    #[error("template {name}: {message}")]
    Template { name: String, message: String },
}

fn io_err(path: &Path) -> impl FnOnce(io::Error) -> ThemeError + '_ {
    move |source| ThemeError::Io {
        path: path.to_path_buf(),
        source,
    }
}

fn invalid(path: &Path, message: impl Into<String>) -> ThemeError {
    ThemeError::Invalid {
        path: path.to_path_buf(),
        message: message.into(),
    }
}

// ------------------------------------------------------------------ locations

/// Where themes, templates and the rendered theme live.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Locations {
    /// First-party themes: `/usr/share/bromigos/themes`.
    pub system_themes: PathBuf,
    /// Installed extensions' themes (`bromigos ext`; links into their checkouts):
    /// `~/.local/share/bromigos/ext/active/themes`.
    pub ext_themes: PathBuf,
    /// The user's themes and overlays: `~/.config/bromigos/themes`.
    pub user_themes: PathBuf,
    /// First-party templates: `/usr/share/bromigos/theme/templates`.
    pub system_templates: PathBuf,
    /// The user's templates: `~/.config/bromigos/theme/templates`.
    pub user_templates: PathBuf,
    /// First-party icons, drawn in the Wick's colours: `/usr/share/bromigos/theme/icons`.
    pub system_icons: PathBuf,
    /// The user's icons (same name wins): `~/.config/bromigos/theme/icons`.
    pub user_icons: PathBuf,
    /// Generated state: `~/.local/state/bromigos/theme`.
    pub state: PathBuf,
}

impl Locations {
    pub fn new(paths: &Paths) -> Self {
        let user = paths.user_config_dir();
        Locations {
            system_themes: paths.share_dir.join("themes"),
            ext_themes: paths.ext_active("themes"),
            user_themes: user.join("themes"),
            system_templates: paths.share_dir.join("theme/templates"),
            user_templates: user.join("theme/templates"),
            system_icons: paths.share_dir.join("theme/icons"),
            user_icons: user.join("theme/icons"),
            state: paths.user_state_dir().join("theme"),
        }
    }

    /// The rendered theme every app reads: `~/.local/state/bromigos/theme/current`.
    pub fn current(&self) -> PathBuf {
        self.state.join("current")
    }

    fn lock_file(&self) -> PathBuf {
        self.state.join(".lock")
    }
}

/// Lowercase letters, digits, `-` and `_`, starting with a letter or digit.
pub fn valid_name(name: &str) -> bool {
    let mut chars = name.chars();
    matches!(chars.next(), Some(c) if c.is_ascii_lowercase() || c.is_ascii_digit())
        && name.len() <= 64
        && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_')
}

// ------------------------------------------------------------------ the theme

/// `theme.toml`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Meta {
    /// Display name (`Wick`); the directory name is the theme's id.
    pub name: String,
    pub description: String,
    /// `dark` or `light`.
    pub mode: String,
    /// Where the theme sits in the lore.
    pub canon: Option<String>,
}

/// `colors.toml`, every reference resolved to `#rrggbb`.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Colors {
    /// The top-level roles, then `[colors]`, in file order.
    pub palette: Vec<(String, String)>,
    /// Every other table (`terminal`, `holo`, `widgets`, `qt`, …).
    pub tables: BTreeMap<String, BTreeMap<String, String>>,
}

impl Colors {
    /// A top-level role or named colour.
    pub fn get(&self, name: &str) -> Option<&str> {
        self.palette
            .iter()
            .find(|(k, _)| k == name)
            .map(|(_, v)| v.as_str())
    }
}

/// A theme, loaded from its directories (first-party first, the user's over it).
#[derive(Debug, Clone)]
pub struct Theme {
    pub name: String,
    pub dirs: Vec<PathBuf>,
    pub meta: Meta,
    pub colors: Colors,
    colors_doc: toml_edit::DocumentMut,
    meta_doc: toml_edit::DocumentMut,
}

/// The directories of theme `name`, in overlay order: first-party, an extension's, the
/// user's (`bromigos ext` refuses an extension theme with a first-party theme's name, so
/// the first two never stack).
fn theme_dirs(loc: &Locations, name: &str) -> Vec<PathBuf> {
    [&loc.system_themes, &loc.ext_themes, &loc.user_themes]
        .iter()
        .map(|d| d.join(name))
        .filter(|d| d.is_dir())
        .collect()
}

/// Every theme name in any of the directories, sorted.
pub fn names(loc: &Locations) -> Vec<String> {
    let mut names: Vec<String> = [&loc.system_themes, &loc.ext_themes, &loc.user_themes]
        .iter()
        .filter_map(|d| fs::read_dir(d).ok())
        .flatten()
        .flatten()
        .filter(|e| e.path().is_dir())
        .filter_map(|e| e.file_name().into_string().ok())
        .filter(|n| valid_name(n))
        .collect();
    names.sort();
    names.dedup();
    names
}

/// Merges `over` into `base`, table by table (a key in `over` wins).
fn overlay(base: &mut toml_edit::Table, over: &toml_edit::Table) {
    for (k, v) in over.iter() {
        match (base.get_mut(k), v) {
            (Some(toml_edit::Item::Table(b)), toml_edit::Item::Table(o)) => overlay(b, o),
            _ => {
                base.insert(k, v.clone());
            }
        }
    }
}

/// `file` from every dir that has it, merged in order. `None` when no dir has it.
fn merged_toml(dirs: &[PathBuf], file: &str) -> Result<Option<toml_edit::DocumentMut>, ThemeError> {
    let mut doc: Option<toml_edit::DocumentMut> = None;
    for d in dirs {
        let p = d.join(file);
        let text = match fs::read_to_string(&p) {
            Ok(t) => t,
            Err(e) if e.kind() == io::ErrorKind::NotFound => continue,
            Err(e) => return Err(io_err(&p)(e)),
        };
        let over: toml_edit::DocumentMut = text.parse().map_err(|e| invalid(&p, format!("{e}")))?;
        match doc.as_mut() {
            None => doc = Some(over),
            Some(base) => overlay(base.as_table_mut(), over.as_table()),
        }
    }
    Ok(doc)
}

fn parse_meta(name: &str, doc: &toml_edit::DocumentMut, path: &Path) -> Result<Meta, ThemeError> {
    let s = |k: &str| -> Result<Option<String>, ThemeError> {
        match doc.get(k) {
            None => Ok(None),
            Some(i) => i
                .as_str()
                .map(|s| Some(s.to_owned()))
                .ok_or_else(|| invalid(path, format!("{k} must be a string"))),
        }
    };
    let mode = s("mode")?.unwrap_or_else(|| "dark".to_owned());
    if mode != "dark" && mode != "light" {
        return Err(invalid(
            path,
            format!("mode must be \"dark\" or \"light\", not {mode:?}"),
        ));
    }
    Ok(Meta {
        name: s("name")?.unwrap_or_else(|| name.to_owned()),
        description: s("description")?.unwrap_or_default(),
        mode,
        canon: s("canon")?,
    })
}

fn is_hex(v: &str) -> bool {
    v.len() == 7 && v.starts_with('#') && v[1..].chars().all(|c| c.is_ascii_hexdigit())
}

/// Reads `colors.toml` (already merged) and resolves every reference.
pub fn parse_colors(doc: &toml_edit::DocumentMut, path: &Path) -> Result<Colors, ThemeError> {
    let string = |k: &str, i: &toml_edit::Item| -> Result<String, ThemeError> {
        i.as_str().map(str::to_owned).ok_or_else(|| {
            invalid(
                path,
                format!("{k}: a colour is a string: \"#rrggbb\" or another colour's name"),
            )
        })
    };
    let mut raw_root: Vec<(String, String)> = Vec::new();
    let mut raw_tables: BTreeMap<String, Vec<(String, String)>> = BTreeMap::new();
    let mut root_tables: Vec<(&str, &toml_edit::Table)> = Vec::new();
    for (k, item) in doc.iter() {
        match item {
            toml_edit::Item::Table(t) => root_tables.push((k, t)),
            _ => raw_root.push((k.to_owned(), string(k, item)?)),
        }
    }
    for (k, t) in root_tables {
        let mut entries = Vec::new();
        for (kk, item) in t.iter() {
            entries.push((kk.to_owned(), string(&format!("{k}.{kk}"), item)?));
        }
        if k == "colors" {
            for (kk, v) in entries {
                if raw_root.iter().any(|(r, _)| *r == kk) {
                    return Err(invalid(
                        path,
                        format!("{kk} is both a role and a [colors] name"),
                    ));
                }
                raw_root.push((kk, v));
            }
        } else {
            raw_tables.insert(k.to_owned(), entries);
        }
    }

    let lookup = |reference: &str| -> Option<&str> {
        match reference.split_once('.') {
            Some((t, k)) => raw_tables
                .get(t)?
                .iter()
                .find(|(kk, _)| kk == k)
                .map(|(_, v)| v.as_str()),
            None => raw_root
                .iter()
                .find(|(kk, _)| kk == reference)
                .map(|(_, v)| v.as_str()),
        }
    };
    let resolve = |key: &str, value: &str| -> Result<String, ThemeError> {
        let mut v = value;
        for _ in 0..32 {
            if v.starts_with('#') {
                return if is_hex(v) {
                    Ok(v.to_owned())
                } else {
                    Err(invalid(
                        path,
                        format!("{key}: {v:?} is not a #rrggbb colour"),
                    ))
                };
            }
            v = lookup(v).ok_or_else(|| invalid(path, format!("{key}: no colour named {v:?}")))?;
        }
        Err(invalid(
            path,
            format!("{key}: the names refer to each other in a loop"),
        ))
    };

    let mut colors = Colors::default();
    for (k, v) in &raw_root {
        colors.palette.push((k.clone(), resolve(k, v)?));
    }
    for (t, entries) in &raw_tables {
        let mut m = BTreeMap::new();
        for (k, v) in entries {
            m.insert(k.clone(), resolve(&format!("{t}.{k}"), v)?);
        }
        colors.tables.insert(t.clone(), m);
    }
    Ok(colors)
}

/// Loads theme `name`. Unknown names and names that aren't names are errors.
pub fn load(loc: &Locations, name: &str) -> Result<Theme, ThemeError> {
    if !valid_name(name) {
        return Err(ThemeError::BadName(name.to_owned()));
    }
    let dirs = theme_dirs(loc, name);
    if dirs.is_empty() {
        return Err(ThemeError::Unknown {
            name: name.to_owned(),
            available: names(loc),
        });
    }
    let last = dirs.last().cloned().unwrap_or_default();
    let colors_doc = merged_toml(&dirs, "colors.toml")?
        .ok_or_else(|| invalid(&last, "no colors.toml in the theme"))?;
    let colors = parse_colors(&colors_doc, &last.join("colors.toml"))?;
    let meta_doc = merged_toml(&dirs, "theme.toml")?.unwrap_or_default();
    let meta = parse_meta(name, &meta_doc, &last.join("theme.toml"))?;
    Ok(Theme {
        name: name.to_owned(),
        dirs,
        meta,
        colors,
        colors_doc,
        meta_doc,
    })
}

// ------------------------------------------------------------------ rendering

/// The templates, by output name (`waybar.css` from `waybar.css.tpl`): first-party,
/// replaced by the user's of the same name. Sorted.
pub fn templates(loc: &Locations) -> Result<BTreeMap<String, PathBuf>, ThemeError> {
    let mut out = BTreeMap::new();
    for dir in [&loc.system_templates, &loc.user_templates] {
        let rd = match fs::read_dir(dir) {
            Ok(rd) => rd,
            Err(e) if e.kind() == io::ErrorKind::NotFound => continue,
            Err(e) => return Err(io_err(dir)(e)),
        };
        for e in rd.flatten() {
            let file = e.file_name().to_string_lossy().into_owned();
            if let Some(output) = file.strip_suffix(".tpl")
                && !output.is_empty()
                && e.path().is_file()
            {
                out.insert(output.to_owned(), e.path());
            }
        }
    }
    Ok(out)
}

fn hex_of(value: &str) -> Result<&str, minijinja::Error> {
    if is_hex(value) {
        Ok(&value[1..])
    } else {
        Err(minijinja::Error::new(
            minijinja::ErrorKind::InvalidOperation,
            format!("{value:?} is not a #rrggbb colour"),
        ))
    }
}

/// The template environment: strict (an unknown name is an error, never empty), no
/// escaping, and the colour filters `strip` (`39ff14`), `rgb` (`57,255,20`) and
/// `kebab` (`warn_surface` to `warn-surface`).
fn environment() -> Environment<'static> {
    let mut env = Environment::new();
    env.set_undefined_behavior(UndefinedBehavior::Strict);
    env.set_keep_trailing_newline(true);
    env.set_auto_escape_callback(|_| AutoEscape::None);
    env.add_filter("strip", |v: String| hex_of(&v).map(str::to_owned));
    env.add_filter("rgb", |v: String| {
        let h = hex_of(&v)?;
        let c = |i: usize| u8::from_str_radix(&h[i..i + 2], 16).unwrap_or(0);
        Ok::<_, minijinja::Error>(format!("{},{},{}", c(0), c(2), c(4)))
    });
    env.add_filter("kebab", |v: String| v.replace('_', "-"));
    env
}

/// What a template sees: every role and named colour at the top level, `palette`
/// (`[name, value]` pairs in file order), each other table as a map, `meta`, `theme`
/// (the id) and `a11y` (the user's accessibility settings: `a11y.motion` is `full`,
/// `reduced` or `still`, `a11y.contrast` `normal` or `high`; the colours are already the
/// high-contrast ones when it's `high`).
fn context(theme: &Theme, a11y: &Settings) -> minijinja::Value {
    let mut ctx = context_0_1(theme);
    ctx.insert("a11y".to_owned(), minijinja::Value::from_serialize(a11y));
    minijinja::Value::from_serialize(&ctx)
}

/// What bromigOS 0.1.0 and 0.1.1 gave a template: everything but `a11y`. An update from
/// one of them renders the new templates with that renderer (its process goes on after
/// pacman replaced it), so a template defaults what's newer (`a11y is defined`).
fn context_0_1(theme: &Theme) -> BTreeMap<String, minijinja::Value> {
    let mut ctx: BTreeMap<String, minijinja::Value> = BTreeMap::new();
    for (k, v) in &theme.colors.palette {
        ctx.insert(k.clone(), minijinja::Value::from(v.as_str()));
    }
    for (t, m) in &theme.colors.tables {
        ctx.insert(t.clone(), minijinja::Value::from_serialize(m));
    }
    ctx.insert(
        "palette".to_owned(),
        minijinja::Value::from_serialize(&theme.colors.palette),
    );
    ctx.insert(
        "meta".to_owned(),
        minijinja::Value::from_serialize(&theme.meta),
    );
    ctx.insert(
        "theme".to_owned(),
        minijinja::Value::from(theme.name.as_str()),
    );
    ctx
}

/// Renders each template with the theme; returns (output name, text). The accessibility
/// settings are the defaults (full motion, normal contrast): [`render_with`] takes them.
pub fn render(
    theme: &Theme,
    templates: &BTreeMap<String, PathBuf>,
) -> Result<Vec<(String, String)>, ThemeError> {
    render_with(theme, templates, &Settings::default())
}

/// [`render`] with the user's accessibility settings in the templates' `a11y`.
pub fn render_with(
    theme: &Theme,
    templates: &BTreeMap<String, PathBuf>,
    a11y: &Settings,
) -> Result<Vec<(String, String)>, ThemeError> {
    let env = environment();
    let ctx = context(theme, a11y);
    let mut out = Vec::new();
    for (output, path) in templates {
        let source = fs::read_to_string(path).map_err(io_err(path))?;
        let name = format!("{output}.tpl");
        let text =
            env.render_named_str(&name, &source, &ctx)
                .map_err(|e| ThemeError::Template {
                    name: path.display().to_string(),
                    message: format!("{e:#}"),
                })?;
        out.push((output.clone(), text));
    }
    Ok(out)
}

/// `palette.json`: the theme's colours with every reference resolved, for apps that
/// read them at runtime and reload when the file changes. `colors` is the roles and
/// `[colors]` names; `tables` is every other table (`holo`, `widgets`, `terminal`, …).
/// Schema in core/README.md. The accessibility settings are the defaults:
/// [`palette_json_with`] takes them.
pub fn palette_json(theme: &Theme) -> String {
    palette_json_with(
        theme,
        &Settings::default(),
        &accessibility::report(&theme.colors, "normal"),
    )
}

/// `palette.json` with `motion` (the user's motion setting, for apps that animate: the
/// widgets, VECTOR, the decks) and `contrast` (`mode`, `normal` or `high`, and how the
/// colours measure against high contrast's targets: `ok`, the `lowest` pair).
pub fn palette_json_with(
    theme: &Theme,
    a11y: &Settings,
    contrast: &accessibility::Report,
) -> String {
    let colors: serde_json::Map<String, serde_json::Value> = theme
        .colors
        .palette
        .iter()
        .map(|(k, v)| (k.clone(), serde_json::Value::from(v.as_str())))
        .collect();
    let doc = serde_json::json!({
        "schema": 1,
        "theme": theme.name,
        "name": theme.meta.name,
        "mode": theme.meta.mode,
        "colors": colors,
        "tables": theme.colors.tables,
        "motion": a11y.motion,
        "contrast": {"mode": contrast.mode, "ok": contrast.ok, "lowest": contrast.lowest},
    });
    let mut text = serde_json::to_string_pretty(&doc).unwrap_or_default();
    text.push('\n');
    text
}

/// The icons (`theme/icons/*.svg`), first-party then the user's: file name -> path.
pub fn icons(loc: &Locations) -> Result<BTreeMap<String, PathBuf>, ThemeError> {
    let mut out = BTreeMap::new();
    for dir in [&loc.system_icons, &loc.user_icons] {
        let Ok(rd) = fs::read_dir(dir) else { continue };
        for e in rd {
            let e = e.map_err(io_err(dir))?;
            let name = e.file_name().to_string_lossy().into_owned();
            if name.ends_with(".svg") && e.path().is_file() {
                out.insert(name, e.path());
            }
        }
    }
    Ok(out)
}

/// The Wick's colour of each role -> the theme's colour of that role (lowercase
/// `#rrggbb`), for the icons, which are drawn in the Wick's colours. Empty when the Wick
/// isn't installed; for the Wick itself it maps each colour to itself, unless the colours
/// were made high-contrast.
pub fn wick_map(loc: &Locations, theme: &Theme) -> BTreeMap<String, String> {
    let mut map = BTreeMap::new();
    let Ok(wick) = load(loc, DEFAULT_THEME) else {
        return map;
    };
    for (role, w) in &wick.colors.palette {
        if let Some(t) = theme.colors.get(role) {
            map.entry(w.to_ascii_lowercase())
                .or_insert_with(|| t.to_ascii_lowercase());
        }
    }
    map
}

/// `svg` with its root element's `width` and `height` set to `px`, so a toolkit that
/// rasterises an SVG at its own size (GTK, for the bar) draws it at that size.
pub fn svg_size(svg: &str, px: u32) -> String {
    let Some(start) = svg.find("<svg") else {
        return svg.to_owned();
    };
    let Some(len) = svg[start..].find('>') else {
        return svg.to_owned();
    };
    let mut tag = svg[start..start + len].to_owned();
    for attr in ["width", "height"] {
        let key = format!(" {attr}=\"");
        let (mut found, mut i) = (None, 0);
        // the attribute itself, not stroke-width or a viewBox
        while let Some(j) = tag[i..].find(&key[1..]) {
            let at = i + j;
            if at > 0 && tag[..at].ends_with(char::is_whitespace) {
                found = Some(at);
                break;
            }
            i = at + 1;
        }
        let value = format!("{attr}=\"{px}\"");
        match found {
            Some(at) => {
                let vstart = at + attr.len() + 2;
                let vend = tag[vstart..]
                    .find('"')
                    .map_or(tag.len(), |e| vstart + e + 1);
                tag.replace_range(at..vend, &value);
            }
            None => tag.insert_str(4, &format!(" {value}")),
        }
    }
    format!("{}{}{}", &svg[..start], tag, &svg[start + len..])
}

/// Swaps each `#rrggbb` in `text` found in `map` (any case) for its value; everything
/// else is left exactly as it was.
pub fn recolour(text: &str, map: &BTreeMap<String, String>) -> String {
    if map.is_empty() {
        return text.to_owned();
    }
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(i) = rest.find('#') {
        out.push_str(&rest[..i]);
        let cand = rest.get(i..i + 7).filter(|c| is_hex(c));
        match cand.and_then(|c| map.get(&c.to_ascii_lowercase())) {
            Some(v) => {
                out.push_str(v);
                rest = &rest[i + 7..];
            }
            None => {
                out.push('#');
                rest = &rest[i + 1..];
            }
        }
    }
    out.push_str(rest);
    out
}

// ------------------------------------------------------------------ set

/// What `set` did.
#[derive(Debug, Clone, Serialize)]
pub struct SetReport {
    pub name: String,
    pub display_name: String,
    /// The rendered theme: `~/.local/state/bromigos/theme/current`.
    pub dir: PathBuf,
    /// Files rendered from templates.
    pub rendered: Vec<String>,
    /// Files the theme ships under a template's output name (used instead).
    pub from_theme: Vec<String>,
    /// Icons recoloured into `icons/` (see [`recolour`]); a theme's own `icons/<name>` wins.
    pub icons: Vec<String>,
    /// The user's motion setting, as rendered (`full`, `reduced`, `still`).
    pub motion: String,
    /// The contrast rendered (`normal` or `high`) and how the colours measure.
    pub contrast: accessibility::Report,
}

/// What a theme keeps for making its art (`bromigos art`), at its root: never
/// part of the rendered theme.
const ART_FILES: [&str; 3] = ["art.toml", "art.log.jsonl", "art"];

/// Copies a theme directory into `dst` (see [`copy_dir`]), leaving out its
/// art pipeline's files.
fn copy_tree(src: &Path, dst: &Path) -> Result<(), ThemeError> {
    copy_dir(src, dst, &ART_FILES)
}

/// Copies `src` into `dst` recursively (files replace files), skipping READMEs,
/// `.git` and `skip` (names at this level only); a folder with nothing else (a
/// reserved one) isn't created. Symlinks are copied as what they point at.
fn copy_dir(src: &Path, dst: &Path, skip: &[&str]) -> Result<(), ThemeError> {
    for e in fs::read_dir(src).map_err(io_err(src))?.flatten() {
        let name = e.file_name();
        if name == "README.md" || name == ".git" || skip.iter().any(|s| name == *s) {
            continue;
        }
        let (from, to) = (e.path(), dst.join(&name));
        if from.is_dir() {
            copy_dir(&from, &to, &[])?;
        } else if from.is_file() {
            fs::create_dir_all(dst).map_err(io_err(dst))?;
            fs::copy(&from, &to).map_err(io_err(&from))?;
        }
    }
    Ok(())
}

fn write(path: &Path, text: &str) -> Result<(), ThemeError> {
    fs::write(path, text).map_err(io_err(path))
}

/// Removes what an interrupted `set` left behind.
fn clean_leftovers(state: &Path) {
    for e in fs::read_dir(state).into_iter().flatten().flatten() {
        let n = e.file_name().to_string_lossy().into_owned();
        if n.starts_with(".staging-") || n.starts_with(".old-") {
            let _ = fs::remove_dir_all(e.path());
        }
    }
}

/// Puts `staging` at `current` in one step: `renameat2(RENAME_EXCHANGE)` swaps the two
/// directories atomically, then the old one (now at `staging`) is removed. A reader
/// sees the old theme or the new one, never a mix or nothing. Where the filesystem
/// can't exchange, the old directory is moved aside first (a moment without one).
pub fn swap_into_place(staging: &Path, current: &Path) -> Result<(), ThemeError> {
    match fs::symlink_metadata(current) {
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            return fs::rename(staging, current).map_err(io_err(current));
        }
        Err(e) => return Err(io_err(current)(e)),
        Ok(m) if !m.is_dir() => {
            fs::remove_file(current).map_err(io_err(current))?;
            return fs::rename(staging, current).map_err(io_err(current));
        }
        Ok(_) => {}
    }
    use rustix::fs::{CWD, RenameFlags, renameat_with};
    match renameat_with(CWD, staging, CWD, current, RenameFlags::EXCHANGE) {
        Ok(()) => {}
        Err(_) => {
            let aside = staging.with_file_name(format!(".old-{}", std::process::id()));
            fs::rename(current, &aside).map_err(io_err(current))?;
            fs::rename(staging, current).map_err(io_err(current))?;
            let _ = fs::remove_dir_all(&aside);
            return Ok(());
        }
    }
    fs::remove_dir_all(staging).map_err(io_err(staging))
}

/// Renders theme `name` and swaps it into `current/`. Everything that can fail
/// (an unknown name, a bad colour, a template error) fails before anything is
/// written. One `set` at a time (an flock on `theme/.lock`).
pub fn set(paths: &Paths, name: &str) -> Result<SetReport, ThemeError> {
    let loc = Locations::new(paths);
    let mut theme = load(&loc, name)?;
    // the user's accessibility settings: high contrast renders every output from the
    // theme's colours made high-contrast (docs/accessibility.md)
    let a11y = accessibility::read(paths);
    if a11y.high_contrast() {
        theme.colors = accessibility::high_contrast(&theme.colors);
    }
    let contrast = accessibility::report(&theme.colors, &a11y.contrast);
    let templates = templates(&loc)?;
    let rendered = render_with(&theme, &templates, &a11y)?;

    fs::create_dir_all(&loc.state).map_err(io_err(&loc.state))?;
    let lock_path = loc.lock_file();
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(&lock_path)
        .map_err(io_err(&lock_path))?;
    rustix::fs::flock(&lock, rustix::fs::FlockOperation::LockExclusive)
        .map_err(|e| io_err(&lock_path)(e.into()))?;
    clean_leftovers(&loc.state);

    let staging = loc.state.join(format!(".staging-{}", std::process::id()));
    let result = (|| {
        fs::create_dir_all(&staging).map_err(io_err(&staging))?;
        for d in &theme.dirs {
            copy_tree(d, &staging)?;
        }
        // the merged files, not the last copy
        write(&staging.join("colors.toml"), &theme.colors_doc.to_string())?;
        if !theme.meta_doc.is_empty() {
            write(&staging.join("theme.toml"), &theme.meta_doc.to_string())?;
        }
        let mut report = SetReport {
            name: theme.name.clone(),
            display_name: theme.meta.name.clone(),
            dir: loc.current(),
            rendered: Vec::new(),
            from_theme: Vec::new(),
            icons: Vec::new(),
            motion: a11y.motion.clone(),
            contrast: contrast.clone(),
        };
        for (output, text) in &rendered {
            let p = staging.join(output);
            if p.exists() {
                report.from_theme.push(output.clone());
            } else {
                write(&p, text)?;
                report.rendered.push(output.clone());
            }
        }
        write(
            &staging.join(PALETTE_FILE),
            &palette_json_with(&theme, &a11y, &contrast),
        )?;
        let map = wick_map(&loc, &theme);
        for (file, path) in icons(&loc)? {
            let out = staging.join("icons").join(&file);
            if out.exists() {
                continue;
            }
            // the bar's emblem: the theme's own small one (emblem/emblem-small.svg) when it has one
            let own = staging.join(EMBLEM_FILE);
            let text = if file == "emblem.svg" && own.is_file() {
                svg_size(&fs::read_to_string(&own).map_err(io_err(&own))?, 48)
            } else {
                recolour(&fs::read_to_string(&path).map_err(io_err(&path))?, &map)
            };
            fs::create_dir_all(staging.join("icons")).map_err(io_err(&staging))?;
            write(&out, &text)?;
            report.icons.push(file);
        }
        write(&staging.join(NAME_FILE), &format!("{}\n", theme.name))?;
        swap_into_place(&staging, &loc.current())?;
        Ok(report)
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&staging);
    }
    result
}

// ------------------------------------------------------------------ current, list

/// The theme in force.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Current {
    pub name: String,
    /// False when no theme was ever set: `name` is then the default.
    pub set: bool,
    pub dir: PathBuf,
}

pub fn current(paths: &Paths) -> Current {
    let dir = Locations::new(paths).current();
    let named = fs::read_to_string(dir.join(NAME_FILE))
        .ok()
        .map(|s| s.trim().to_owned())
        .filter(|s| valid_name(s));
    Current {
        set: named.is_some(),
        name: named.unwrap_or_else(|| DEFAULT_THEME.to_owned()),
        dir,
    }
}

/// One row of `theme list`.
#[derive(Debug, Clone, Serialize)]
pub struct ThemeInfo {
    pub name: String,
    pub display_name: String,
    pub description: String,
    pub mode: String,
    /// `system` (first-party), `ext` (an installed extension's), `user`, or more than
    /// one: a user overlay over a first-party or an extension's theme.
    pub sources: Vec<&'static str>,
    /// Why it doesn't load, if it doesn't.
    pub error: Option<String>,
}

pub fn list(paths: &Paths) -> Vec<ThemeInfo> {
    let loc = Locations::new(paths);
    names(&loc)
        .into_iter()
        .map(|name| {
            let mut sources = Vec::new();
            if loc.system_themes.join(&name).is_dir() {
                sources.push("system");
            }
            if loc.ext_themes.join(&name).is_dir() {
                sources.push("ext");
            }
            if loc.user_themes.join(&name).is_dir() {
                sources.push("user");
            }
            match load(&loc, &name) {
                Ok(t) => ThemeInfo {
                    display_name: t.meta.name,
                    description: t.meta.description,
                    mode: t.meta.mode,
                    name,
                    sources,
                    error: None,
                },
                Err(e) => ThemeInfo {
                    display_name: name.clone(),
                    description: String::new(),
                    mode: String::new(),
                    name,
                    sources,
                    error: Some(e.to_string()),
                },
            }
        })
        .collect()
}

// ------------------------------------------------------------------ reload

/// How one app was told about the new colours.
#[derive(Debug, Clone, Serialize)]
pub struct Reload {
    pub app: &'static str,
    /// `SIGUSR2`, `hyprctl reload`, `next start`, …
    pub action: &'static str,
    /// The processes signalled.
    pub pids: Vec<i32>,
    pub ok: bool,
    pub detail: Option<String>,
}

/// This user's live processes whose name (`/proc/<pid>/comm`) is `comm`.
pub fn user_processes(comm: &str) -> Vec<i32> {
    let uid = rustix::process::getuid().as_raw();
    let me = std::process::id() as i32;
    let mut pids: Vec<i32> = fs::read_dir("/proc")
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let pid: i32 = e.file_name().to_str()?.parse().ok()?;
            (pid != me && e.metadata().ok()?.uid() == uid).then_some(pid)
        })
        .filter(|pid| {
            fs::read_to_string(format!("/proc/{pid}/comm")).is_ok_and(|c| c.trim_end() == comm)
        })
        // not zombies (a waybar reload leaves its old children unreaped for a while)
        .filter(|pid| {
            fs::read_to_string(format!("/proc/{pid}/stat")).is_ok_and(|s| {
                s.rsplit_once(") ")
                    .is_some_and(|(_, r)| !r.starts_with('Z'))
            })
        })
        .collect();
    pids.sort_unstable();
    pids
}

fn signal_all(
    app: &'static str,
    comm: &str,
    sig: rustix::process::Signal,
    action: &'static str,
) -> Reload {
    let pids = user_processes(comm);
    let mut failed = Vec::new();
    for &pid in &pids {
        let ok = rustix::process::Pid::from_raw(pid)
            .is_some_and(|p| rustix::process::kill_process(p, sig).is_ok());
        if !ok {
            failed.push(pid.to_string());
        }
    }
    Reload {
        app,
        action,
        ok: failed.is_empty(),
        detail: if pids.is_empty() {
            Some("not running".to_owned())
        } else if failed.is_empty() {
            None
        } else {
            Some(format!("could not signal {}", failed.join(", ")))
        },
        pids,
    }
}

fn run_quiet(cmd: &mut Command) -> Result<String, String> {
    match cmd
        .stdin(Stdio::null())
        .stderr(Stdio::piped())
        .stdout(Stdio::piped())
        .output()
    {
        Ok(o) => {
            let out = String::from_utf8_lossy(&o.stdout).trim().to_owned();
            let err = String::from_utf8_lossy(&o.stderr).trim().to_owned();
            if o.status.success() {
                Ok(out)
            } else {
                Err(if err.is_empty() { out } else { err })
            }
        }
        Err(e) => Err(e.to_string()),
    }
}

/// Tells the live layer the theme changed (`theme` on its socket): it swaps to the
/// theme's world (`current/live/world.toml`) or back to the Wick's den. It also notices
/// by itself within a few seconds; this makes the switch immediate.
pub fn reload_live(paths: &Paths) -> Reload {
    let mut r = Reload {
        app: "live",
        action: "theme (its world)",
        pids: vec![],
        ok: true,
        detail: None,
    };
    match ipc::live(paths, "theme") {
        Ok(reply) if reply.trim() == "unknown command" => {
            r.detail = Some("an older live layer: bromigos-live restart".to_owned());
        }
        Ok(reply) => {
            let reply = reply.trim();
            if !reply.is_empty() && reply != "ok" {
                r.detail = Some(reply.to_owned());
            }
        }
        Err(IpcError::NotRunning(_)) => r.detail = Some("not running".to_owned()),
        Err(e) => {
            r.ok = false;
            r.detail = Some(e.to_string());
        }
    }
    r
}

/// Tells the running apps to pick up `current/`: waybar restarted (an in-place reload can crash it) and kitty SIGUSR1 to
/// each of this user's instances, `hyprctl reload` in the live session, `dunstctl
/// reload` when dunst runs, `theme` to the live layer's socket. gtklock, rofi and Qt
/// read their file at next start.
/// The theme-set hooks: the packaged ones (`/usr/share/bromigos/hooks/theme-set.d/*`,
/// package bromigos-desktop), installed extensions' (`bromigos ext`: linked as
/// `<extension>--<file>` in `~/.local/share/bromigos/ext/active/hooks/theme-set.d/`)
/// and the user's (`~/.config/bromigos/hooks/theme-set.d/*`), each executable file, in
/// name order. A user hook with a packaged or an extension's hook's name replaces it, so
/// a user can change or switch off (an empty, non-executable file) any of them.
pub fn hooks(paths: &Paths) -> Vec<PathBuf> {
    use std::collections::BTreeMap;
    use std::os::unix::fs::PermissionsExt;
    let mut by_name: BTreeMap<std::ffi::OsString, PathBuf> = BTreeMap::new();
    for dir in [
        paths.share_dir.join("hooks/theme-set.d"),
        paths.ext_active("hooks/theme-set.d"),
        paths.user_config_dir().join("hooks/theme-set.d"),
    ] {
        for e in fs::read_dir(&dir).into_iter().flatten().flatten() {
            by_name.insert(e.file_name(), e.path());
        }
    }
    by_name
        .into_values()
        .filter(|p| {
            fs::metadata(p).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
        })
        .collect()
}

/// Runs the theme-set hooks, for what a template can't do (rebuild a GTK theme, switch
/// a gsetting, …): each gets the theme's name as its argument, `BROMIGOS_THEME` and
/// `BROMIGOS_THEME_DIR` (the rendered theme), and the live session's environment.
/// They run one after another and `theme set` waits, so they should be quick. None
/// when there are no hooks.
pub fn run_hooks(paths: &Paths) -> Option<Reload> {
    let hooks = hooks(paths);
    if hooks.is_empty() {
        return None;
    }
    let cur = current(paths);
    let sess = session::discover(paths).session;
    let (mut ran, mut failed) = (Vec::new(), Vec::new());
    for h in &hooks {
        let name = h
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default();
        let mut cmd = Command::new(h);
        cmd.arg(&cur.name)
            .env("BROMIGOS_THEME", &cur.name)
            .env("BROMIGOS_THEME_DIR", &cur.dir);
        if let Some(s) = &sess {
            cmd.envs(s.env());
        }
        let r = run_quiet(&mut cmd);
        match r {
            Ok(_) => ran.push(name),
            Err(e) => failed.push(format!("{name}: {}", e.lines().last().unwrap_or("failed"))),
        }
    }
    Some(Reload {
        app: "hooks",
        action: "theme-set.d",
        pids: vec![],
        ok: failed.is_empty(),
        detail: Some(if failed.is_empty() {
            format!("ran {}", ran.join(", "))
        } else {
            failed.join("; ")
        }),
    })
}

/// Waybar picks the new theme up by restarting, not by SIGUSR2: an in-place reload can
/// crash waybar 0.15 (its mpris module's dispatcher is torn down by the reload and then
/// gets a playerctl signal: SIGSEGV, and the bar is gone). A fresh one starts in well under
/// a second, detached, with the live session's environment.
fn restart_waybar(paths: &Paths) -> Reload {
    let pids = user_processes("waybar");
    if pids.is_empty() {
        return Reload {
            app: "waybar",
            action: "restart",
            pids,
            ok: true,
            detail: Some("not running".to_owned()),
        };
    }
    let env = crate::update::session_env(paths);
    let r = crate::update::stop(&pids).and_then(|_| crate::update::spawn(&env, "waybar"));
    Reload {
        app: "waybar",
        action: "restart",
        ok: r.is_ok(),
        detail: r.err(),
        pids,
    }
}

pub fn reload(paths: &Paths) -> Vec<Reload> {
    use rustix::process::Signal;
    let mut out = vec![
        restart_waybar(paths),
        signal_all("kitty", "kitty", Signal::USR1, "SIGUSR1"),
    ];

    let hypr = match session::discover(paths).session {
        None => Reload {
            app: "hyprland",
            action: "hyprctl reload",
            pids: vec![],
            ok: true,
            detail: Some("no running session".to_owned()),
        },
        Some(s) => {
            let r = run_quiet(Command::new("hyprctl").arg("reload").envs(s.env()));
            Reload {
                app: "hyprland",
                action: "hyprctl reload",
                pids: vec![s.pid],
                ok: matches!(&r, Ok(o) if o == "ok"),
                detail: match r {
                    Ok(o) if o == "ok" => None,
                    Ok(o) | Err(o) => Some(o),
                },
            }
        }
    };
    out.push(hypr);

    let dunst = user_processes("dunst");
    out.push(if dunst.is_empty() {
        Reload {
            app: "dunst",
            action: "dunstctl reload",
            pids: dunst,
            ok: true,
            detail: Some("not running".to_owned()),
        }
    } else {
        let r = run_quiet(Command::new("dunstctl").arg("reload"));
        Reload {
            app: "dunst",
            action: "dunstctl reload",
            pids: dunst,
            ok: r.is_ok(),
            detail: r.err(),
        }
    });

    out.push(reload_live(paths));
    out.push(Reload {
        app: "widgets, vector, decks",
        action: "palette.json (they watch it)",
        pids: vec![],
        ok: true,
        detail: None,
    });
    if let Some(r) = run_hooks(paths) {
        out.push(r);
    }

    for app in ["gtklock", "rofi", "qt"] {
        out.push(Reload {
            app,
            action: "next start",
            pids: vec![],
            ok: true,
            detail: None,
        });
    }
    out
}

// ------------------------------------------------------------ install, remove

/// `bromigos theme install`'s result.
#[derive(Debug, Clone, Serialize)]
pub struct InstallReport {
    pub name: String,
    pub display_name: String,
    pub dir: PathBuf,
    pub source: String,
}

/// The theme name a source gets: `--name`, else the repository's or directory's basename
/// without `.git` and a `bromigos-theme-` prefix, lowercased, other characters as `-`.
pub fn name_for(source: &str, name: Option<&str>) -> Result<String, ThemeError> {
    let n = match name {
        Some(n) => n.to_owned(),
        None => {
            let base = source
                .trim_end_matches('/')
                .rsplit(['/', ':'])
                .next()
                .unwrap_or("")
                .trim_end_matches(".git");
            let base = base.strip_prefix("bromigos-theme-").unwrap_or(base);
            base.chars()
                .map(|c| {
                    let c = c.to_ascii_lowercase();
                    if c.is_ascii_alphanumeric() || c == '_' {
                        c
                    } else {
                        '-'
                    }
                })
                .collect::<String>()
                .trim_matches('-')
                .to_owned()
        }
    };
    if valid_name(&n) {
        Ok(n)
    } else {
        Err(ThemeError::BadName(n))
    }
}

/// Copies a theme's files (`colors.toml`, `theme.toml`, the reserved folders), never a
/// symlink or a `.git` folder, so a repository can't reach outside its own directory.
fn copy_theme(from: &Path, to: &Path) -> Result<(), ThemeError> {
    fs::create_dir_all(to).map_err(io_err(to))?;
    for e in fs::read_dir(from).map_err(io_err(from))? {
        let e = e.map_err(io_err(from))?;
        let name = e.file_name();
        let name_s = name.to_string_lossy();
        if name_s == ".git" || name_s.starts_with('.') {
            continue;
        }
        let src = e.path();
        let meta = fs::symlink_metadata(&src).map_err(io_err(&src))?;
        if meta.file_type().is_symlink() {
            continue;
        }
        let dst = to.join(&name);
        if meta.is_dir() {
            copy_theme(&src, &dst)?;
        } else if meta.is_file() {
            fs::copy(&src, &dst).map_err(io_err(&src))?;
        }
    }
    Ok(())
}

/// Installs a theme into the user's themes from a git URL (cloned, depth 1) or a local
/// directory. The result must load as a theme (a `colors.toml` at least), or nothing is
/// kept. An installed theme of the same name is replaced only with `force`.
pub fn install_into(
    loc: &Locations,
    source: &str,
    name: Option<&str>,
    force: bool,
) -> Result<InstallReport, ThemeError> {
    let name = name_for(source, name)?;
    let dest = loc.user_themes.join(&name);
    if dest.exists() && !force {
        return Err(invalid(
            &dest,
            "already installed (bromigos theme install --force replaces it)",
        ));
    }
    if loc.system_themes.join(&name).is_dir() && !force {
        return Err(invalid(
            &dest,
            "a first-party theme has that name (an overlay of it needs --force, or --name)",
        ));
    }
    fs::create_dir_all(&loc.user_themes).map_err(io_err(&loc.user_themes))?;
    let stage = loc
        .user_themes
        .join(format!(".install-{}-{}", name, std::process::id()));
    let _ = fs::remove_dir_all(&stage);
    let src = Path::new(source);
    let result = (|| {
        if src.is_dir() {
            copy_theme(src, &stage)?;
        } else {
            let clone = loc
                .user_themes
                .join(format!(".clone-{}-{}", name, std::process::id()));
            let _ = fs::remove_dir_all(&clone);
            let out = Command::new("git")
                .args(["clone", "--depth", "1", "--quiet", "--", source])
                .arg(&clone)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::piped())
                .output()
                .map_err(|e| invalid(&clone, format!("git clone: {e}")))?;
            if !out.status.success() {
                let _ = fs::remove_dir_all(&clone);
                return Err(invalid(
                    Path::new(source),
                    format!(
                        "git clone failed: {}",
                        String::from_utf8_lossy(&out.stderr).trim()
                    ),
                ));
            }
            let r = copy_theme(&clone, &stage);
            let _ = fs::remove_dir_all(&clone);
            r?;
        }
        if !stage.join("colors.toml").is_file() {
            return Err(invalid(
                &stage,
                "no colors.toml: not a bromigOS theme (docs/theming.md)",
            ));
        }
        // it must load, as the user's theme would (first-party dirs don't apply to a new name)
        let probe = Locations {
            system_themes: PathBuf::from("/nonexistent"),
            ext_themes: PathBuf::from("/nonexistent"),
            user_themes: loc.user_themes.clone(),
            ..loc.clone()
        };
        let probe_name = stage
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_owned();
        let _ = probe_name;
        let staged = load_dir(&probe, &stage)?;
        if dest.exists() {
            fs::remove_dir_all(&dest).map_err(io_err(&dest))?;
        }
        fs::rename(&stage, &dest).map_err(io_err(&dest))?;
        Ok(InstallReport {
            name: name.clone(),
            display_name: staged.meta.name,
            dir: dest.clone(),
            source: source.to_owned(),
        })
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&stage);
    }
    result
}

/// Checks that `dir` alone is a theme that loads (an extension's theme, before it's
/// installed): its `theme.toml` metadata, named after the directory.
pub fn check_dir(dir: &Path) -> Result<Meta, ThemeError> {
    let loc = Locations {
        system_themes: PathBuf::from("/nonexistent"),
        ext_themes: PathBuf::from("/nonexistent"),
        user_themes: PathBuf::from("/nonexistent"),
        system_templates: PathBuf::from("/nonexistent"),
        user_templates: PathBuf::from("/nonexistent"),
        system_icons: PathBuf::from("/nonexistent"),
        user_icons: PathBuf::from("/nonexistent"),
        state: PathBuf::from("/nonexistent"),
    };
    if !dir.join("colors.toml").is_file() {
        return Err(invalid(
            dir,
            "no colors.toml: not a bromigOS theme (docs/theming.md)",
        ));
    }
    load_dir(&loc, dir).map(|t| t.meta)
}

/// Loads the theme in one directory alone (an install's staging folder).
fn load_dir(loc: &Locations, dir: &Path) -> Result<Theme, ThemeError> {
    let dirs = vec![dir.to_path_buf()];
    let colors_doc = merged_toml(&dirs, "colors.toml")?
        .ok_or_else(|| invalid(dir, "no colors.toml in the theme"))?;
    let colors = parse_colors(&colors_doc, &dir.join("colors.toml"))?;
    let meta_doc = merged_toml(&dirs, "theme.toml")?.unwrap_or_default();
    let name = dir.file_name().and_then(|n| n.to_str()).unwrap_or("theme");
    let meta = parse_meta(name, &meta_doc, &dir.join("theme.toml"))?;
    let _ = loc;
    Ok(Theme {
        name: name.to_owned(),
        dirs,
        meta,
        colors,
        colors_doc,
        meta_doc,
    })
}

pub fn install(
    paths: &Paths,
    source: &str,
    name: Option<&str>,
    force: bool,
) -> Result<InstallReport, ThemeError> {
    install_into(&Locations::new(paths), source, name, force)
}

/// Removes one of the user's themes (never a first-party one, never the theme in force).
pub fn remove_from(
    loc: &Locations,
    name: &str,
    current: Option<&str>,
) -> Result<PathBuf, ThemeError> {
    if !valid_name(name) {
        return Err(ThemeError::BadName(name.to_owned()));
    }
    let dir = loc.user_themes.join(name);
    if !dir.is_dir() {
        return Err(if loc.system_themes.join(name).is_dir() {
            invalid(
                &dir,
                "a first-party theme: it isn't removed, only yours are",
            )
        } else {
            ThemeError::Unknown {
                name: name.to_owned(),
                available: names(loc),
            }
        });
    }
    if current == Some(name) {
        return Err(invalid(&dir, "it's the theme in force: set another first"));
    }
    fs::remove_dir_all(&dir).map_err(io_err(&dir))?;
    Ok(dir)
}

pub fn remove(paths: &Paths, name: &str) -> Result<PathBuf, ThemeError> {
    let cur = current(paths);
    remove_from(
        &Locations::new(paths),
        name,
        if cur.set {
            Some(cur.name.as_str())
        } else {
            None
        },
    )
}

#[cfg(test)]
mod install_tests {
    use super::*;

    fn loc(root: &Path) -> Locations {
        Locations {
            system_themes: root.join("sys"),
            ext_themes: root.join("ext"),
            user_themes: root.join("user"),
            system_templates: root.join("tpl"),
            user_templates: root.join("utpl"),
            system_icons: root.join("icons"),
            user_icons: root.join("uicons"),
            state: root.join("state"),
        }
    }

    fn a_theme(dir: &Path, name: &str) {
        fs::create_dir_all(dir).unwrap();
        fs::write(
            dir.join("colors.toml"),
            "background = \"#000000\"\nprimary = \"#39ff14\"\n",
        )
        .unwrap();
        fs::write(
            dir.join("theme.toml"),
            format!("name = \"{name}\"\nmode = \"dark\"\n"),
        )
        .unwrap();
    }

    #[test]
    fn names_come_from_the_source() {
        assert_eq!(
            name_for("https://github.com/x/bromigos-theme-Deep-Sea.git", None).unwrap(),
            "deep-sea"
        );
        assert_eq!(
            name_for("git@github.com:x/night.git", None).unwrap(),
            "night"
        );
        assert_eq!(
            name_for("/tmp/themes/Dusk Light/", None).unwrap(),
            "dusk-light"
        );
        assert_eq!(name_for("anything", Some("mine")).unwrap(), "mine");
        assert!(name_for("anything", Some("../up")).is_err());
        assert!(name_for("https://x/.git", None).is_err());
    }

    #[test]
    fn installs_a_local_directory_and_refuses_a_second_time() {
        let t = tempfile::tempdir().unwrap();
        let l = loc(t.path());
        let src = t.path().join("src/Night Reef");
        a_theme(&src, "Night Reef");
        fs::create_dir_all(src.join(".git")).unwrap();
        fs::write(src.join(".git/HEAD"), "ref").unwrap();
        std::os::unix::fs::symlink("/etc/passwd", src.join("escape")).unwrap();
        let r = install_into(&l, src.to_str().unwrap(), None, false).unwrap();
        assert_eq!(r.name, "night-reef");
        assert_eq!(r.display_name, "Night Reef");
        assert!(r.dir.join("colors.toml").is_file());
        assert!(!r.dir.join(".git").exists(), "no .git copied");
        assert!(!r.dir.join("escape").exists(), "no symlink copied");
        assert!(install_into(&l, src.to_str().unwrap(), None, false).is_err());
        assert!(install_into(&l, src.to_str().unwrap(), None, true).is_ok());
        assert_eq!(names(&l), vec!["night-reef".to_owned()]);
    }

    #[test]
    fn a_folder_that_is_not_a_theme_leaves_nothing_behind() {
        let t = tempfile::tempdir().unwrap();
        let l = loc(t.path());
        let src = t.path().join("junk");
        fs::create_dir_all(&src).unwrap();
        fs::write(src.join("README.md"), "hi").unwrap();
        assert!(install_into(&l, src.to_str().unwrap(), Some("junk"), false).is_err());
        assert!(!l.user_themes.join("junk").exists());
        assert!(fs::read_dir(&l.user_themes).map(|d| d.count()).unwrap_or(0) == 0);
    }

    #[test]
    fn remove_only_the_users_and_never_the_current() {
        let t = tempfile::tempdir().unwrap();
        let l = loc(t.path());
        a_theme(&l.system_themes.join("wick"), "Wick");
        a_theme(&l.user_themes.join("mine"), "Mine");
        assert!(remove_from(&l, "wick", None).is_err());
        assert!(remove_from(&l, "mine", Some("mine")).is_err());
        assert!(remove_from(&l, "mine", Some("wick")).is_ok());
        assert!(!l.user_themes.join("mine").exists());
    }
}

#[cfg(test)]
mod older_renderer {
    use super::*;

    /// An update from bromigOS 0.1.1 renders the theme with 0.1.1's renderer and the
    /// new templates: every repository theme's every output must come out as the current
    /// renderer draws it with the default settings.
    #[test]
    fn the_templates_render_the_same_for_the_0_1_renderer() {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let paths = Paths::from_lookup(|k| match k {
            "HOME" => Some(PathBuf::from("/nonexistent-home")),
            "BROMIGOS_SHARE_DIR" => Some(repo.clone()),
            _ => None,
        });
        let loc = Locations::new(&paths);
        let templates = templates(&loc).unwrap();
        let env = environment();
        let names = names(&loc);
        assert!(names.len() > 1);
        for name in names {
            let t = load(&loc, &name).unwrap();
            let now: BTreeMap<_, _> = render(&t, &templates).unwrap().into_iter().collect();
            let old_ctx = minijinja::Value::from_serialize(context_0_1(&t));
            for (output, path) in &templates {
                let source = fs::read_to_string(path).unwrap();
                let text = env
                    .render_named_str(&format!("{output}.tpl"), &source, &old_ctx)
                    .unwrap_or_else(|e| panic!("{name}: {output} with the 0.1 renderer: {e:#}"));
                assert_eq!(text, now[output], "{name}: {output}");
            }
        }
    }
}
