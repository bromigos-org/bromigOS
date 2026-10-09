//! The live layer's config and the user's animation switches.
//!
//! The live layer reads its config (`config.toml`) and merges the user's switches over
//! it, table by table. The switches are the user's own settings, so they live in
//! `~/.config/bromigos/live/overrides.toml`; the old location
//! (`~/.local/state/bromigos-live/overrides.toml`) is read while the new one does not
//! exist and is moved on the first write. Edits go through `toml_edit`, so comments,
//! ordering and any keys this tool does not know are kept.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use thiserror::Error;
use toml_edit::{DocumentMut, Item, Table, Value};

use crate::paths::Paths;

/// Written at the top of a new overrides file.
pub const DEFAULT_HEADER: &str = "# Your animation switches (bromigos anim …), merged over the live layer's config.toml. Safe to delete.";

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("{}: {source}", path.display())]
    Io { path: PathBuf, source: io::Error },
    #[error("{}: {source}", path.display())]
    Parse {
        path: PathBuf,
        source: Box<toml_edit::TomlError>,
    },
    #[error("{}: {source}", path.display())]
    Toml {
        path: PathBuf,
        source: Box<toml::de::Error>,
    },
    #[error("{}: [{section}] is not a table", path.display())]
    NotATable { path: PathBuf, section: String },
}

fn io_err(path: &Path) -> impl FnOnce(io::Error) -> ConfigError + '_ {
    move |source| ConfigError::Io {
        path: path.to_owned(),
        source,
    }
}

fn read_optional(path: &Path) -> Result<Option<String>, ConfigError> {
    match fs::read_to_string(path) {
        Ok(s) => Ok(Some(s)),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(io_err(path)(e)),
    }
}

fn parse_table(path: &Path, text: &str) -> Result<toml::Table, ConfigError> {
    toml::from_str(text).map_err(|e| ConfigError::Toml {
        path: path.to_owned(),
        source: Box::new(e),
    })
}

/// The live config the live layer would use: `$BROMIGOS_LIVE_CONFIG`, else
/// `~/.config/bromigos-live/config.toml`, else `/usr/share/bromigos/live/config.toml`.
/// `None` when none exists.
pub fn live_config_path(paths: &Paths) -> Option<PathBuf> {
    [paths.live_config.clone(), paths.live_config_default()]
        .into_iter()
        .find(|p| p.exists())
}

/// The live config's data (empty when there is none).
pub fn load_base(paths: &Paths) -> Result<toml::Table, ConfigError> {
    let Some(path) = live_config_path(paths) else {
        return Ok(toml::Table::new());
    };
    match read_optional(&path)? {
        Some(text) => parse_table(&path, &text),
        None => Ok(toml::Table::new()),
    }
}

/// Merges `over` into `base` the way the live layer does: tables recursively, any
/// other value replaced.
pub fn merge(base: &mut toml::Table, over: &toml::Table) {
    for (k, v) in over {
        match (base.get_mut(k), v) {
            (Some(toml::Value::Table(b)), toml::Value::Table(o)) => merge(b, o),
            _ => {
                base.insert(k.clone(), v.clone());
            }
        }
    }
}

/// Python truthiness of a TOML value (the live layer and the old CLI test `if value`).
pub fn truthy(v: &toml::Value) -> bool {
    match v {
        toml::Value::Boolean(b) => *b,
        toml::Value::Integer(i) => *i != 0,
        toml::Value::Float(f) => *f != 0.0,
        toml::Value::String(s) => !s.is_empty(),
        toml::Value::Array(a) => !a.is_empty(),
        toml::Value::Table(t) => !t.is_empty(),
        toml::Value::Datetime(_) => true,
    }
}

/// `table[section][key]`, if present.
pub fn lookup<'a>(t: &'a toml::Table, section: &str, key: &str) -> Option<&'a toml::Value> {
    t.get(section)?.as_table()?.get(key)
}

/// The user's switches file, loaded for reading or editing.
#[derive(Debug, Clone)]
pub struct Overrides {
    /// The leading comment block, kept verbatim.
    header: String,
    /// Everything after the header.
    doc: DocumentMut,
    /// Where it was read from (`None`: no file yet).
    pub source: Option<PathBuf>,
}

impl Overrides {
    /// Reads the switches: the new location, else the old one, else empty.
    pub fn load(paths: &Paths) -> Result<Self, ConfigError> {
        for path in [&paths.live_overrides, &paths.live_overrides_legacy] {
            if let Some(text) = read_optional(path)? {
                return Self::parse(&text, Some(path.clone()));
            }
        }
        Self::parse("", None)
    }

    /// Parses overrides text.
    pub fn parse(text: &str, source: Option<PathBuf>) -> Result<Self, ConfigError> {
        let (header, body) = split_header(text);
        let doc = body
            .parse::<DocumentMut>()
            .map_err(|e| ConfigError::Parse {
                path: source.clone().unwrap_or_default(),
                source: Box::new(e),
            })?;
        let header = if header.trim().is_empty() {
            DEFAULT_HEADER.to_owned()
        } else {
            header.trim_end().to_owned()
        };
        Ok(Overrides {
            header,
            doc,
            source,
        })
    }

    /// The switches as plain data.
    pub fn table(&self) -> toml::Table {
        toml::from_str(&self.doc.to_string()).unwrap_or_default()
    }

    /// Whether `[section] key` is set here.
    pub fn contains(&self, section: &str, key: &str) -> bool {
        self.doc
            .get(section)
            .and_then(Item::as_table_like)
            .is_some_and(|t| t.contains_key(key))
    }

    /// Sets `[section] key = value`, keeping the key's comments if it exists.
    pub fn set(&mut self, section: &str, key: &str, value: bool) -> Result<(), ConfigError> {
        let first = self.doc.as_table().is_empty();
        let item = self.doc.entry(section).or_insert_with(|| {
            let mut t = Table::new();
            if !first {
                t.decor_mut().set_prefix("\n");
            }
            Item::Table(t)
        });
        let Some(t) = item.as_table_like_mut() else {
            return Err(ConfigError::NotATable {
                path: self.source.clone().unwrap_or_default(),
                section: section.to_owned(),
            });
        };
        match t.get_mut(key) {
            Some(Item::Value(v)) => {
                let decor = v.decor().clone();
                *v = Value::from(value);
                *v.decor_mut() = decor;
            }
            _ => {
                t.insert(key, toml_edit::value(value));
            }
        }
        Ok(())
    }

    /// Removes `[section] key`; a section left empty goes too.
    pub fn remove(&mut self, section: &str, key: &str) {
        let empty = match self.doc.get_mut(section).and_then(Item::as_table_like_mut) {
            Some(t) => {
                t.remove(key);
                t.is_empty()
            }
            None => false,
        };
        if empty {
            self.doc.remove(section);
        }
    }

    /// The file's text: the header, a blank line, the switches.
    pub fn render(&self) -> String {
        let body = self.doc.to_string();
        let body = body.trim_start_matches(['\n', '\r']);
        if body.trim().is_empty() {
            format!("{}\n", self.header)
        } else {
            format!("{}\n\n{}", self.header, body)
        }
    }

    /// Writes the switches to the new location (atomically) and removes the old file,
    /// so a move from the old location leaves nothing behind.
    pub fn save(&mut self, paths: &Paths) -> Result<(), ConfigError> {
        let path = &paths.live_overrides;
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir).map_err(io_err(dir))?;
        }
        let mut tmp = path.clone().into_os_string();
        tmp.push(".tmp");
        let tmp = PathBuf::from(tmp);
        fs::write(&tmp, self.render()).map_err(io_err(&tmp))?;
        fs::rename(&tmp, path).map_err(io_err(path))?;
        let legacy = &paths.live_overrides_legacy;
        match fs::remove_file(legacy) {
            Ok(()) => {}
            Err(e) if e.kind() == io::ErrorKind::NotFound => {}
            Err(e) => return Err(io_err(legacy)(e)),
        }
        self.source = Some(path.clone());
        Ok(())
    }
}

/// Splits off the leading block of comment and blank lines.
fn split_header(text: &str) -> (&str, &str) {
    let mut end = 0;
    for line in text.split_inclusive('\n') {
        let t = line.trim();
        if t.is_empty() || t.starts_with('#') {
            end += line.len();
        } else {
            break;
        }
    }
    text.split_at(end)
}

/// The live config with the user's switches merged over it.
pub fn load_merged(paths: &Paths) -> Result<(toml::Table, Overrides), ConfigError> {
    let mut base = load_base(paths)?;
    let ov = Overrides::load(paths)?;
    merge(&mut base, &ov.table());
    Ok((base, ov))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn header_kept_and_keys_round_trip() {
        let text = "# my header\n# second line\n\n[events]\nworkspace_wipe = false # mine\n\n[general]\nfps = 10\n";
        let mut ov = Overrides::parse(text, None).unwrap();
        assert_eq!(ov.render(), text);
        ov.set("events", "workspace_wipe", true).unwrap();
        ov.set("rain", "enabled", false).unwrap();
        let out = ov.render();
        assert!(out.starts_with("# my header\n# second line\n\n[events]\n"));
        assert!(out.contains("workspace_wipe = true # mine"));
        assert!(
            out.contains("fps = 10"),
            "non-switch keys are kept as they are"
        );
        assert!(out.contains("\n\n[rain]\nenabled = false\n"));
        // removing the first table keeps the header
        ov.remove("events", "workspace_wipe");
        let out = ov.render();
        assert!(out.starts_with("# my header\n# second line\n\n[general]\nfps = 10\n"));
        assert!(!out.contains("[events]"));
    }

    #[test]
    fn new_file_gets_the_default_header() {
        let mut ov = Overrides::parse("", None).unwrap();
        assert_eq!(ov.render(), format!("{DEFAULT_HEADER}\n"));
        ov.set("space", "traffic", false).unwrap();
        ov.set("rain", "enabled", true).unwrap();
        assert_eq!(
            ov.render(),
            format!("{DEFAULT_HEADER}\n\n[space]\ntraffic = false\n\n[rain]\nenabled = true\n")
        );
        ov.remove("space", "traffic");
        ov.remove("rain", "enabled");
        assert_eq!(ov.render(), format!("{DEFAULT_HEADER}\n"));
    }

    #[test]
    fn dotted_keys_and_non_tables() {
        let mut ov = Overrides::parse("rain.enabled = false\nsounds = 3\n", None).unwrap();
        assert!(ov.contains("rain", "enabled"));
        ov.set("rain", "bursts", false).unwrap();
        assert_eq!(
            lookup(&ov.table(), "rain", "bursts"),
            Some(&toml::Value::Boolean(false))
        );
        assert!(matches!(
            ov.set("sounds", "enabled", true),
            Err(ConfigError::NotATable { .. })
        ));
    }

    #[test]
    fn merge_like_the_live_layer() {
        let mut base: toml::Table =
            toml::from_str("[rain]\nenabled = true\nbrightness = 0.5\n[space]\nstars = true\n")
                .unwrap();
        let over: toml::Table = toml::from_str("[rain]\nenabled = false\n").unwrap();
        merge(&mut base, &over);
        assert_eq!(
            lookup(&base, "rain", "enabled"),
            Some(&toml::Value::Boolean(false))
        );
        assert_eq!(
            lookup(&base, "rain", "brightness"),
            Some(&toml::Value::Float(0.5))
        );
        assert_eq!(
            lookup(&base, "space", "stars"),
            Some(&toml::Value::Boolean(true))
        );
    }

    #[test]
    fn bad_toml_is_an_error_not_a_rewrite() {
        assert!(matches!(
            Overrides::parse("# h\n[rain\n", None),
            Err(ConfigError::Parse { .. })
        ));
    }
}
