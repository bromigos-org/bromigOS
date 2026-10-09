//! The user's profile: who they are and what VECTOR calls them.
//!
//! `~/.config/bromigos/profile.toml` is the user's own file (updates never touch it):
//!
//! ```toml
//! [you]
//! name = "Sam"
//! full_name = "Sam Example"
//! aliases = ["sammy"]
//! address = ["Captain", "Sam"]   # forms of address, most preferred first
//! pronouns = "they/them"
//! ```
//!
//! Edits go through `toml_edit`, so comments, ordering and keys this module does not
//! know are kept. Values are short single lines (they reach VECTOR's prompt): no control
//! characters, at most [`MAX_LEN`] characters.

use std::fs;
use std::io;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

use serde::Serialize;
use thiserror::Error;
use toml_edit::{Array, DocumentMut, Item, Table, Value};

use crate::paths::Paths;

/// The table holding the profile.
pub const SECTION: &str = "you";

/// The longest value accepted, in characters.
pub const MAX_LEN: usize = 80;

/// A new profile file starts as this.
pub const TEMPLATE: &str = "\
# Your bromigOS profile: who you are and what VECTOR calls you.
# Yours to edit, by hand, with `bromigos profile …`, or by telling VECTOR (\"call me …\").
# Updates never touch it.
#
#   name       what you're usually called
#   full_name  your full name
#   aliases    other names you go by (handles, callsigns)
#   address    forms of address, most preferred first; VECTOR mostly uses the first
#   pronouns   e.g. \"he/him\", \"she/her\", \"they/them\"

[you]
";

/// The single-value fields.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Field {
    Name,
    FullName,
    Pronouns,
}

impl Field {
    pub fn key(self) -> &'static str {
        match self {
            Field::Name => "name",
            Field::FullName => "full_name",
            Field::Pronouns => "pronouns",
        }
    }
}

/// The list fields.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum List {
    Aliases,
    Address,
}

impl List {
    pub fn key(self) -> &'static str {
        match self {
            List::Aliases => "aliases",
            List::Address => "address",
        }
    }
}

/// The profile as plain data.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Profile {
    pub name: Option<String>,
    pub full_name: Option<String>,
    pub aliases: Vec<String>,
    pub address: Vec<String>,
    pub pronouns: Option<String>,
}

impl Profile {
    /// How VECTOR addresses the user by default: the first form of address, else the
    /// name, else nothing.
    pub fn addressed_as(&self) -> Option<&str> {
        self.address
            .first()
            .map(String::as_str)
            .or(self.name.as_deref())
    }

    pub fn is_empty(&self) -> bool {
        *self == Profile::default()
    }
}

#[derive(Debug, Error)]
pub enum ProfileError {
    #[error("{}: {source}", path.display())]
    Io { path: PathBuf, source: io::Error },
    #[error("{}: {source}", path.display())]
    Parse {
        path: PathBuf,
        source: Box<toml_edit::TomlError>,
    },
    #[error("{}: {what} is not a {expected}", path.display())]
    Shape {
        path: PathBuf,
        what: String,
        expected: &'static str,
    },
    #[error("{0}")]
    Invalid(String),
}

fn io_err(path: &Path) -> impl FnOnce(io::Error) -> ProfileError + '_ {
    move |source| ProfileError::Io {
        path: path.to_owned(),
        source,
    }
}

/// Trims a value and checks it: non-empty, one line, no control characters, at most
/// [`MAX_LEN`] characters.
pub fn clean(value: &str) -> Result<String, ProfileError> {
    let v = value.trim();
    if v.is_empty() {
        return Err(ProfileError::Invalid("empty value".into()));
    }
    if v.chars().any(char::is_control) {
        return Err(ProfileError::Invalid(
            "a value is one line, with no control characters".into(),
        ));
    }
    if v.chars().count() > MAX_LEN {
        return Err(ProfileError::Invalid(format!(
            "too long (at most {MAX_LEN} characters)"
        )));
    }
    Ok(v.to_owned())
}

/// The profile file, loaded for reading or editing.
#[derive(Debug, Clone)]
pub struct ProfileFile {
    doc: DocumentMut,
    /// Where it lives (whether or not it exists yet).
    pub path: PathBuf,
    /// Whether it was read from disk.
    pub exists: bool,
}

impl ProfileFile {
    /// Reads `~/.config/bromigos/profile.toml`; a missing file is the empty template.
    pub fn load(paths: &Paths) -> Result<Self, ProfileError> {
        let path = paths.profile_file();
        match fs::read_to_string(&path) {
            Ok(text) => Self::parse(&text, path, true),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Self::parse(TEMPLATE, path, false),
            Err(e) => Err(io_err(&path)(e)),
        }
    }

    /// Parses profile text.
    pub fn parse(text: &str, path: PathBuf, exists: bool) -> Result<Self, ProfileError> {
        let doc = text
            .parse::<DocumentMut>()
            .map_err(|e| ProfileError::Parse {
                path: path.clone(),
                source: Box::new(e),
            })?;
        Ok(ProfileFile { doc, path, exists })
    }

    /// The profile as plain data. A value of the wrong type, or one [`clean`] refuses
    /// (a hand edit), reads as absent.
    pub fn profile(&self) -> Profile {
        let you = self.doc.get(SECTION).and_then(Item::as_table_like);
        let get = |k: &str| you.and_then(|t| t.get(k));
        let string = |k: &str| get(k).and_then(Item::as_str).and_then(|s| clean(s).ok());
        let list = |k: &str| -> Vec<String> {
            get(k)
                .and_then(Item::as_array)
                .map(|a| {
                    a.iter()
                        .filter_map(Value::as_str)
                        .filter_map(|s| clean(s).ok())
                        .collect()
                })
                .unwrap_or_default()
        };
        Profile {
            name: string("name"),
            full_name: string("full_name"),
            aliases: list("aliases"),
            address: list("address"),
            pronouns: string("pronouns"),
        }
    }

    fn you(&mut self) -> Result<&mut dyn toml_edit::TableLike, ProfileError> {
        let path = self.path.clone();
        let item = self.doc.entry(SECTION).or_insert_with(|| {
            let mut t = Table::new();
            t.decor_mut().set_prefix("\n");
            Item::Table(t)
        });
        item.as_table_like_mut().ok_or(ProfileError::Shape {
            path,
            what: format!("[{SECTION}]"),
            expected: "table",
        })
    }

    /// Sets a single-value field; an empty value removes it. Keeps the key's comments.
    pub fn set(&mut self, field: Field, value: &str) -> Result<(), ProfileError> {
        let you = self.you()?;
        if value.trim().is_empty() {
            you.remove(field.key());
            return Ok(());
        }
        let v = clean(value)?;
        match you.get_mut(field.key()) {
            Some(Item::Value(old)) => {
                let decor = old.decor().clone();
                *old = Value::from(v);
                *old.decor_mut() = decor;
            }
            _ => {
                you.insert(field.key(), toml_edit::value(v));
            }
        }
        Ok(())
    }

    fn array(&mut self, list: List) -> Result<&mut Array, ProfileError> {
        let path = self.path.clone();
        let you = self.you()?;
        if !matches!(you.get(list.key()), Some(i) if i.is_array()) {
            if you.get(list.key()).is_some_and(|i| !i.is_none()) {
                return Err(ProfileError::Shape {
                    path,
                    what: format!("{SECTION}.{}", list.key()),
                    expected: "list",
                });
            }
            you.insert(list.key(), toml_edit::value(Array::new()));
        }
        Ok(you
            .get_mut(list.key())
            .and_then(Item::as_array_mut)
            .expect("just made sure it is an array"))
    }

    /// Appends values not already in the list (compared case-insensitively).
    pub fn add(&mut self, list: List, values: &[String]) -> Result<(), ProfileError> {
        let values = values
            .iter()
            .map(|v| clean(v))
            .collect::<Result<Vec<_>, _>>()?;
        let arr = self.array(list)?;
        for v in values {
            let present = arr
                .iter()
                .filter_map(Value::as_str)
                .any(|x| x.trim().eq_ignore_ascii_case(&v));
            if !present {
                arr.push(v);
            }
        }
        arr.fmt();
        Ok(())
    }

    /// Removes values from the list (compared case-insensitively). Returns how many
    /// went; a list left empty goes too.
    pub fn remove(&mut self, list: List, values: &[String]) -> Result<usize, ProfileError> {
        let wanted: Vec<String> = values.iter().map(|v| v.trim().to_lowercase()).collect();
        let arr = self.array(list)?;
        let before = arr.len();
        arr.retain(|x| {
            x.as_str()
                .is_none_or(|s| !wanted.contains(&s.trim().to_lowercase()))
        });
        let removed = before - arr.len();
        arr.fmt();
        if arr.is_empty() {
            self.you()?.remove(list.key());
        }
        Ok(removed)
    }

    /// Replaces the whole list, in this order (duplicates dropped); no values removes it.
    pub fn replace(&mut self, list: List, values: &[String]) -> Result<(), ProfileError> {
        let values = values
            .iter()
            .map(|v| clean(v))
            .collect::<Result<Vec<_>, _>>()?;
        if values.is_empty() {
            self.you()?.remove(list.key());
            return Ok(());
        }
        let arr = self.array(list)?;
        arr.clear();
        self.add(list, &values)
    }

    /// The file's text.
    pub fn render(&self) -> String {
        self.doc.to_string()
    }

    /// Writes the profile atomically (through a symlinked file to its target), keeping
    /// an existing file's permissions.
    pub fn save(&mut self) -> Result<(), ProfileError> {
        let path = match fs::symlink_metadata(&self.path) {
            Ok(m) if m.file_type().is_symlink() => {
                fs::canonicalize(&self.path).map_err(io_err(&self.path))?
            }
            _ => self.path.clone(),
        };
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir).map_err(io_err(dir))?;
        }
        let mode = fs::metadata(&path)
            .map(|m| m.permissions().mode() & 0o7777)
            .unwrap_or(0o644);
        let mut tmp = path.clone().into_os_string();
        tmp.push(".tmp");
        let tmp = PathBuf::from(tmp);
        fs::write(&tmp, self.render()).map_err(io_err(&tmp))?;
        fs::set_permissions(&tmp, fs::Permissions::from_mode(mode)).map_err(io_err(&tmp))?;
        fs::rename(&tmp, &path).map_err(io_err(&path))?;
        self.exists = true;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn file(text: &str) -> ProfileFile {
        ProfileFile::parse(text, PathBuf::from("/x/profile.toml"), true).unwrap()
    }

    #[test]
    fn empty_template_reads_as_empty() {
        let f = file(TEMPLATE);
        assert!(f.profile().is_empty());
        assert_eq!(f.profile().addressed_as(), None);
    }

    #[test]
    fn set_keeps_comments_and_unknown_keys() {
        let mut f = file("# mine\n[you]\nname = \"Al\" # short\ncolour = \"blue\"\n");
        f.set(Field::Name, "  Alex ").unwrap();
        f.set(Field::Pronouns, "they/them").unwrap();
        assert_eq!(
            f.render(),
            "# mine\n[you]\nname = \"Alex\" # short\ncolour = \"blue\"\npronouns = \"they/them\"\n"
        );
        f.set(Field::Name, "").unwrap();
        assert!(!f.render().contains("name ="));
        assert_eq!(f.profile().name, None);
    }

    #[test]
    fn lists_add_remove_replace() {
        let mut f = file(TEMPLATE);
        f.add(List::Address, &["Captain".into(), "Sam".into()])
            .unwrap();
        f.add(List::Address, &["captain".into()]).unwrap();
        assert_eq!(f.profile().address, ["Captain", "Sam"]);
        assert_eq!(f.profile().addressed_as(), Some("Captain"));
        assert!(f.render().contains("address = [\"Captain\", \"Sam\"]"));
        assert_eq!(f.remove(List::Address, &["CAPTAIN".into()]).unwrap(), 1);
        assert_eq!(f.profile().address, ["Sam"]);
        f.replace(List::Address, &["Boss".into(), "Sam".into(), "boss".into()])
            .unwrap();
        assert_eq!(f.profile().address, ["Boss", "Sam"]);
        assert_eq!(
            f.remove(List::Address, &["Boss".into(), "Sam".into()])
                .unwrap(),
            2
        );
        assert!(!f.render().contains("address ="), "an empty list goes");
        assert!(f.render().starts_with("# Your bromigOS profile"));
    }

    #[test]
    fn falls_back_to_the_name() {
        let mut f = file("");
        f.set(Field::Name, "Sam").unwrap();
        assert_eq!(f.profile().addressed_as(), Some("Sam"));
        assert_eq!(f.render(), "\n[you]\nname = \"Sam\"\n");
    }

    #[test]
    fn rejects_bad_values_and_shapes() {
        let mut f = file(TEMPLATE);
        assert!(matches!(
            f.set(Field::Name, "a\nb"),
            Err(ProfileError::Invalid(_))
        ));
        assert!(matches!(
            f.add(List::Aliases, &["x".repeat(MAX_LEN + 1)]),
            Err(ProfileError::Invalid(_))
        ));
        let mut f = file("you = 3\n");
        assert!(matches!(
            f.set(Field::Name, "x"),
            Err(ProfileError::Shape { .. })
        ));
        let f = file("[you]\nname = \"a\\nb\"\naliases = [\"ok\", \"\", \"x\\ty\"]\n");
        assert_eq!(
            f.profile().name,
            None,
            "a hand-edited bad value reads as absent"
        );
        assert_eq!(f.profile().aliases, ["ok"]);
        let mut f = file("[you]\naddress = \"Sir\"\n");
        assert!(f.profile().address.is_empty(), "wrong type reads as absent");
        assert!(matches!(
            f.add(List::Address, &["Sir".into()]),
            Err(ProfileError::Shape { .. })
        ));
    }

    #[test]
    fn save_is_atomic_and_keeps_the_mode() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("sub/profile.toml");
        let mut f = ProfileFile::parse(TEMPLATE, path.clone(), false).unwrap();
        f.set(Field::Name, "Sam").unwrap();
        f.save().unwrap();
        assert!(f.exists);
        assert!(
            fs::read_to_string(&path)
                .unwrap()
                .ends_with("[you]\nname = \"Sam\"\n")
        );
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        f.set(Field::Pronouns, "she/her").unwrap();
        f.save().unwrap();
        let mode = fs::metadata(&path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        // a symlinked profile is written through to its target
        let link = dir.path().join("link.toml");
        std::os::unix::fs::symlink(&path, &link).unwrap();
        let mut g = ProfileFile::parse(&f.render(), link.clone(), true).unwrap();
        g.set(Field::Name, "Samantha").unwrap();
        g.save().unwrap();
        assert!(
            fs::symlink_metadata(&link)
                .unwrap()
                .file_type()
                .is_symlink()
        );
        assert!(fs::read_to_string(&path).unwrap().contains("Samantha"));
    }
}
