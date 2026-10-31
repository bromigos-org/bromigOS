//! The theme in force, for the terminal: its colours (`palette.json`, which `bromigos theme
//! set` writes) and the user's motion setting. Without the file, the Wick's. This is the one
//! place a terminal UI gets its colours from; [`Pal::textual_theme`] gives the Python consoles
//! (Textual) the same ones.

use std::path::{Path, PathBuf};

use ratatui::style::Color;
use serde_json::{Value, json};

/// The roles a terminal UI uses (docs/theming.md's names).
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
    /// links and the accent (the Wick's cyan)
    pub accent: Color,
}

/// "#rrggbb" as a colour.
pub fn hex(s: &str) -> Option<Color> {
    let s = s.strip_prefix('#')?;
    if s.len() != 6 {
        return None;
    }
    let v = u32::from_str_radix(s, 16).ok()?;
    Some(Color::Rgb((v >> 16) as u8, (v >> 8) as u8, v as u8))
}

/// A colour as "#rrggbb" (named and indexed colours as their usual hex).
pub fn to_hex(c: Color) -> String {
    match c {
        Color::Rgb(r, g, b) => format!("#{r:02x}{g:02x}{b:02x}"),
        Color::Black => "#000000".into(),
        Color::White => "#ffffff".into(),
        _ => "#808080".into(),
    }
}

/// `a` moved `k` of the way (0 to 1) towards `b`: a glow's soft surface. Only 24-bit colours
/// mix; anything else stays `a`.
pub fn mix(a: Color, b: Color, k: f32) -> Color {
    match (a, b) {
        (Color::Rgb(r1, g1, b1), Color::Rgb(r2, g2, b2)) => {
            let m =
                |x: u8, y: u8| (x as f32 + (y as f32 - x as f32) * k.clamp(0.0, 1.0)).round() as u8;
            Color::Rgb(m(r1, r2), m(g1, g2), m(b1, b2))
        }
        _ => a,
    }
}

/// The Wick's palette.json (themes/wick).
pub const WICK_JSON: &str = r##"{"colors": {"void": "#000500", "panel": "#001300", "selection": "#003b00",
"primary": "#39ff14", "soft": "#9cff8a", "dim": "#159b09", "text": "#c4f5bb",
"muted": "#7e927e", "faint": "#4e6b4e", "warn": "#d4af37", "danger": "#ff766f",
"white": "#e8ffe0", "cyan": "#3fe0c5"}}"##;

impl Pal {
    /// The Wick's colours (themes/wick), for a machine with no theme set.
    pub fn wick() -> Pal {
        Pal::from_json(WICK_JSON).0
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
            accent: c("cyan", Color::Rgb(63, 224, 197)),
        };
        let motion = v["motion"].as_str().unwrap_or("full").to_string();
        (pal, motion)
    }

    /// The same roles on the Linux console: its 16 colours, which bromigos-boot sets to the
    /// theme's terminal colours at boot (palette.vtrgb: 0 background, 1 danger, 2 primary,
    /// 3 warn, 6 cyan, 7 text, 8 faint, 10 soft, 15 white).
    pub fn ansi16() -> Pal {
        Pal {
            void: Color::Black,
            panel: Color::Black,
            selection: Color::Green,
            primary: Color::Green,
            soft: Color::LightGreen,
            dim: Color::Green,
            text: Color::Gray,
            muted: Color::DarkGray,
            faint: Color::DarkGray,
            warn: Color::Yellow,
            danger: Color::Red,
            white: Color::White,
            accent: Color::Cyan,
        }
    }

    /// The colours for what the terminal can show.
    pub fn for_mode(self, mode: crate::term::Mode) -> Pal {
        match mode {
            crate::term::Mode::Truecolor => self,
            crate::term::Mode::Ansi16 => Pal::ansi16(),
            crate::term::Mode::Mono => Pal {
                void: Color::Reset,
                panel: Color::Reset,
                selection: Color::Reset,
                primary: Color::Reset,
                soft: Color::Reset,
                dim: Color::Reset,
                text: Color::Reset,
                muted: Color::Reset,
                faint: Color::Reset,
                warn: Color::Reset,
                danger: Color::Reset,
                white: Color::Reset,
                accent: Color::Reset,
            },
        }
    }

    /// Each role as "#rrggbb" (shapes for the Python TUIs: `bromigos fieldkit shapes`).
    pub fn roles_json(&self) -> Value {
        json!({
            "void": to_hex(self.void), "panel": to_hex(self.panel),
            "selection": to_hex(self.selection), "primary": to_hex(self.primary),
            "soft": to_hex(self.soft), "dim": to_hex(self.dim), "text": to_hex(self.text),
            "muted": to_hex(self.muted), "faint": to_hex(self.faint), "warn": to_hex(self.warn),
            "danger": to_hex(self.danger), "white": to_hex(self.white),
            "accent": to_hex(self.accent),
        })
    }

    /// A role by its name (the names [`Pal::roles_json`] gives).
    pub fn role(&self, name: &str) -> Color {
        match name {
            "void" => self.void,
            "panel" => self.panel,
            "selection" => self.selection,
            "primary" => self.primary,
            "soft" => self.soft,
            "dim" => self.dim,
            "muted" => self.muted,
            "faint" => self.faint,
            "warn" => self.warn,
            "danger" => self.danger,
            "white" => self.white,
            "accent" => self.accent,
            _ => self.text,
        }
    }

    /// The palette as a Textual theme (textual.theme.Theme's arguments, as JSON): the lab
    /// console and any Python TUI register it to match (`bromigos-tui-theme --textual`).
    pub fn textual_theme(&self, name: &str) -> Value {
        json!({
            "name": name,
            "primary": to_hex(self.primary),
            "secondary": to_hex(self.soft),
            "accent": to_hex(self.accent),
            "foreground": to_hex(self.text),
            "background": to_hex(self.void),
            "surface": to_hex(self.panel),
            "panel": to_hex(self.selection),
            "warning": to_hex(self.warn),
            "error": to_hex(self.danger),
            "success": to_hex(self.primary),
            "dark": true,
            "variables": {
                "text-muted": to_hex(self.muted),
                "border": to_hex(self.dim),
                "block-cursor-background": to_hex(self.primary),
                "block-cursor-foreground": to_hex(self.void),
                "footer-key-foreground": to_hex(self.primary),
            },
            "ansi_console": {
                "_comment": "the same roles on the Linux console (TERM=linux): Theme(..., ansi=True)",
                "primary": "ansi_green", "secondary": "ansi_bright_green", "accent": "ansi_cyan",
                "foreground": "ansi_white", "background": "ansi_black", "surface": "ansi_black",
                "panel": "ansi_black", "warning": "ansi_yellow", "error": "ansi_red",
                "success": "ansi_green", "text-muted": "ansi_bright_black", "border": "ansi_green",
            },
        })
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
