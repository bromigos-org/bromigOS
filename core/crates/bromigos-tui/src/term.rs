//! What the terminal can show, and whether motion is allowed.
//!
//! - 24-bit colour: COLORTERM says truecolor or 24bit (kmscon, kitty, foot, ghostty and most
//!   SSH clients from them set it), or TERM names a terminal known to have it.
//! - The Linux console (TERM=linux): 16 colours, which bromigos-boot sets to DRIFTGLASS's.
//! - Plain: TERM=dumb or vt100, or BROMIGOS_ASCII=1, and NO_COLOR: ASCII borders, no colour.
//!
//! Reduced motion (DRIFTGLASS rule 3) turns every Sweep, Pulse and Spark off:
//! `bromigos.motion=reduced` on the kernel's command line, BROMIGOS_REDUCED_MOTION, or the
//! theme's palette.json motion ("reduced" or "still").

use crate::palette::Pal;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// 24-bit colour: the theme's own colours
    Truecolor,
    /// the Linux console's 16 colours (set to DRIFTGLASS's by bromigos-boot)
    Ansi16,
    /// no colour (NO_COLOR, a dumb terminal)
    Mono,
}

/// What a TUI draws with: the colours for this terminal, its borders, and motion.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Look {
    pub pal: Pal,
    pub mode: Mode,
    /// ASCII borders and marks (+-|), for terminals without box drawing
    pub ascii: bool,
    /// Sweep, Pulse and Spark allowed
    pub motion: bool,
    /// Nerd Font icons (else each icon's plain fallback; crate::icons)
    pub nerd: bool,
}

/// The colour mode for this environment (`get` reads a variable).
pub fn mode_from(get: &dyn Fn(&str) -> Option<String>) -> Mode {
    if get("NO_COLOR").is_some_and(|v| !v.is_empty()) {
        return Mode::Mono;
    }
    let term = get("TERM").unwrap_or_default();
    if matches!(term.as_str(), "dumb" | "vt100" | "vt102" | "vt220") {
        return Mode::Mono;
    }
    let ct = get("COLORTERM").unwrap_or_default().to_ascii_lowercase();
    if ct == "truecolor" || ct == "24bit" {
        return Mode::Truecolor;
    }
    if term == "linux" {
        return Mode::Ansi16;
    }
    if term.starts_with("xterm-kitty")
        || term.starts_with("foot")
        || term.starts_with("xterm-ghostty")
        || term.contains("direct")
        || term == "alacritty"
        || term == "wezterm"
    {
        return Mode::Truecolor;
    }
    if term.contains("256color") {
        // most 256-colour terminals take 24-bit too; an SSH session from one keeps TERM
        return Mode::Truecolor;
    }
    Mode::Ansi16
}

/// ASCII borders for this environment.
pub fn ascii_from(get: &dyn Fn(&str) -> Option<String>) -> bool {
    if get("BROMIGOS_ASCII").is_some_and(|v| v == "1") {
        return true;
    }
    let term = get("TERM").unwrap_or_default();
    matches!(term.as_str(), "dumb" | "vt100" | "vt102" | "vt220")
}

/// Motion allowed: nothing asks for reduced motion.
pub fn motion_from(
    get: &dyn Fn(&str) -> Option<String>,
    cmdline: &str,
    theme_motion: &str,
) -> bool {
    if cmdline
        .split_whitespace()
        .any(|w| w == "bromigos.motion=reduced")
    {
        return false;
    }
    if get("BROMIGOS_REDUCED_MOTION").is_some_and(|v| !v.is_empty() && v != "0") {
        return false;
    }
    theme_motion == "full"
}

impl Look {
    /// The look for this process's terminal: the theme's palette (or the Wick's), the colour
    /// mode, borders and motion.
    pub fn detect() -> Look {
        let get = |k: &str| std::env::var(k).ok();
        let (pal, motion) = crate::palette::load();
        let cmdline = std::fs::read_to_string("/proc/cmdline").unwrap_or_default();
        Look::from_parts(pal, &motion, &get, &cmdline)
    }

    pub fn from_parts(
        pal: Pal,
        theme_motion: &str,
        get: &dyn Fn(&str) -> Option<String>,
        cmdline: &str,
    ) -> Look {
        let mode = mode_from(get);
        let ascii = ascii_from(get) || mode == Mode::Mono;
        Look {
            pal: pal.for_mode(mode),
            mode,
            ascii,
            motion: motion_from(get, cmdline, theme_motion),
            nerd: crate::icons::nerd_from(get, mode, ascii),
        }
    }

    /// The Wick in 24-bit colour with motion: for tests and previews.
    pub fn wick() -> Look {
        Look {
            pal: Pal::wick(),
            mode: Mode::Truecolor,
            ascii: false,
            motion: true,
            nerd: true,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let v: Vec<(String, String)> = pairs
            .iter()
            .map(|(a, b)| (a.to_string(), b.to_string()))
            .collect();
        move |k| v.iter().find(|(a, _)| a == k).map(|(_, b)| b.clone())
    }

    #[test]
    fn modes() {
        assert_eq!(mode_from(&env(&[("TERM", "linux")])), Mode::Ansi16);
        assert_eq!(
            mode_from(&env(&[("TERM", "linux"), ("COLORTERM", "truecolor")])),
            Mode::Truecolor
        );
        assert_eq!(mode_from(&env(&[("TERM", "xterm-kitty")])), Mode::Truecolor);
        assert_eq!(mode_from(&env(&[("TERM", "dumb")])), Mode::Mono);
        assert_eq!(
            mode_from(&env(&[("TERM", "xterm-256color"), ("NO_COLOR", "1")])),
            Mode::Mono
        );
        assert_eq!(mode_from(&env(&[("TERM", "screen")])), Mode::Ansi16);
    }

    #[test]
    fn ascii_and_motion() {
        assert!(ascii_from(&env(&[("TERM", "vt100")])));
        assert!(ascii_from(&env(&[
            ("TERM", "linux"),
            ("BROMIGOS_ASCII", "1")
        ])));
        assert!(!ascii_from(&env(&[("TERM", "linux")])));
        assert!(motion_from(&env(&[]), "quiet", "full"));
        assert!(!motion_from(
            &env(&[]),
            "quiet bromigos.motion=reduced",
            "full"
        ));
        assert!(!motion_from(
            &env(&[("BROMIGOS_REDUCED_MOTION", "1")]),
            "",
            "full"
        ));
        assert!(!motion_from(&env(&[]), "", "reduced"));
    }

    #[test]
    fn console_uses_the_sixteen() {
        let l = Look::from_parts(Pal::wick(), "full", &env(&[("TERM", "linux")]), "");
        assert_eq!(l.pal.primary, ratatui::style::Color::Green);
        assert_eq!(l.mode, Mode::Ansi16);
    }
}
