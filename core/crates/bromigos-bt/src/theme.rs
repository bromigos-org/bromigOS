//! The theme in force, for the terminal: its colours (`palette.json`, which `bromigos theme
//! set` writes) and the user's motion setting. Without the file, the Wick's.

use std::path::{Path, PathBuf};

use ratatui::style::Color;
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Pal {
    pub void: Color,
    pub panel: Color,
    pub selection: Color,
    pub primary: Color,
    pub soft: Color,
    pub dim: Color,
    pub text: Color,
    pub muted: Color,
    pub faint: Color,
    pub warn: Color,
    pub danger: Color,
    pub white: Color,
}

fn hex(s: &str) -> Option<Color> {
    let s = s.strip_prefix('#')?;
    if s.len() != 6 {
        return None;
    }
    let v = u32::from_str_radix(s, 16).ok()?;
    Some(Color::Rgb((v >> 16) as u8, (v >> 8) as u8, v as u8))
}

impl Pal {
    /// The Wick's colours (themes/wick), for a desktop with no theme set.
    pub fn wick() -> Pal {
        Pal::from_json(
            r##"{"colors": {"void": "#000500", "panel": "#001300", "selection": "#003b00",
            "primary": "#39ff14", "soft": "#9cff8a", "dim": "#159b09", "text": "#c4f5bb",
            "muted": "#7e927e", "faint": "#4e6b4e", "warn": "#d4af37", "danger": "#ff766f",
            "white": "#e8ffe0"}}"##,
        )
        .0
    }

    /// (the colours, the motion: "full", "reduced" or "still") from palette.json's text.
    pub fn from_json(text: &str) -> (Pal, String) {
        let v: Value = serde_json::from_str(text).unwrap_or(Value::Null);
        let c = |k: &str, d: Color| v["colors"][k].as_str().and_then(hex).unwrap_or(d);
        let g = Color::Rgb(57, 255, 20);
        let pal = Pal {
            void: c("void", Color::Black),
            panel: c("panel", Color::Black),
            selection: c("selection", Color::DarkGray),
            primary: c("primary", g),
            soft: c("soft", g),
            dim: c("dim", Color::Green),
            text: c("text", Color::White),
            muted: c("muted", Color::Gray),
            faint: c("faint", Color::DarkGray),
            warn: c("warn", Color::Yellow),
            danger: c("danger", Color::Red),
            white: c("white", Color::White),
        };
        let motion = v["motion"].as_str().unwrap_or("full").to_string();
        (pal, motion)
    }
}

/// `$XDG_STATE_HOME/bromigos/theme/current/palette.json`.
pub fn palette_path() -> PathBuf {
    let state = std::env::var_os("XDG_STATE_HOME")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
        .unwrap_or_else(|| {
            Path::new(&std::env::var_os("HOME").unwrap_or_default()).join(".local/state")
        });
    state.join("bromigos/theme/current/palette.json")
}

/// The theme in force: (colours, motion).
pub fn load() -> (Pal, String) {
    match std::fs::read_to_string(palette_path()) {
        Ok(t) => Pal::from_json(&t),
        Err(_) => (Pal::wick(), "full".into()),
    }
}
