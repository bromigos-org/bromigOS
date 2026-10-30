//! Icons for bromigOS's TUIs: a Nerd Font glyph where the terminal has one (kmscon carries
//! Symbols Nerd Font Mono as a fallback font; desktop terminals use a Nerd Font), and a plain
//! fallback that any console font draws (the Linux console's bromigos-geist PSF, ASCII).
//! [`Look::nerd`](crate::Look) chooses: Nerd glyphs in 24-bit colour, the fallback on the Linux
//! console's 16 colours, without colour, or in ASCII; BROMIGOS_ICONS=nerd|ascii forces one.
//!
//! The glyphs are Font Awesome's, in Nerd Fonts' nf-fa range (U+F000 to U+F2E0), which every
//! Nerd Font and Symbols Nerd Font carry.

use crate::term::Look;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Icon {
    Repair,
    Lab,
    Tools,
    Server,
    Install,
    Shell,
    Wired,
    Wifi,
    NoNetwork,
    Key,
    Usb,
    Disk,
    Chip,
    Memory,
    Gpu,
    Thermometer,
    Shield,
    Alert,
    Clock,
    Computer,
    Windows,
    Linux,
    Bromigos,
    FieldKit,
    Lock,
    Unlock,
    Check,
    Cross,
    Info,
    Power,
    Book,
    Rollback,
    Erase,
    Image,
    Edit,
    Backup,
    Remote,
    Search,
    Boot,
    Containers,
    Media,
    Network,
    Suggest,
    Back,
    Update,
    Settings,
    Vector,
    List,
    Folder,
    Gauge,
    Git,
    Exchange,
    Bluetooth,
}

impl Icon {
    /// (the Nerd Font glyph, the Linux console's: a symbol bromigOS's console font has, CP437
    /// and box drawing, else a letter; the ASCII one)
    pub const fn glyphs(self) -> (&'static str, &'static str, &'static str) {
        use Icon::*;
        match self {
            Repair => ("\u{f0ad}", "+", "+"),
            Lab => ("\u{f0c3}", "Φ", "%"),
            Tools => ("\u{f0b1}", "¤", "#"),
            Server => ("\u{f233}", "≡", "="),
            Install => ("\u{f019}", "↓", "v"),
            Shell => ("\u{f120}", "»", ">"),
            Wired => ("\u{f1e6}", "↔", "="),
            Wifi => ("\u{f1eb}", "≈", "~"),
            NoNetwork => ("\u{f05e}", "×", "x"),
            Key => ("\u{f084}", "§", "k"),
            Usb => ("\u{f287}", "▬", "u"),
            Disk => ("\u{f0a0}", "■", "o"),
            Chip => ("\u{f2db}", "∩", "c"),
            Memory => ("\u{f2db}", "▒", "m"),
            Gpu => ("\u{f26c}", "▓", "g"),
            Thermometer => ("\u{f2c9}", "☼", "t"),
            Shield => ("\u{f132}", "Θ", "s"),
            Alert => ("\u{f071}", "‼", "!"),
            Clock => ("\u{f017}", "°", ":"),
            Computer => ("\u{f108}", "◘", "@"),
            Windows => ("\u{f17a}", "W", "W"),
            Linux => ("\u{f17c}", "L", "L"),
            Bromigos => ("\u{f06d}", "▲", "*"),
            FieldKit => ("\u{f0b1}", "►", "*"),
            Lock => ("\u{f023}", "§", "L"),
            Unlock => ("\u{f09c}", "○", "U"),
            Check => ("\u{f00c}", "✓", "+"),
            Cross => ("\u{f00d}", "✗", "x"),
            Info => ("\u{f05a}", "•", "i"),
            Power => ("\u{f011}", "Ø", "0"),
            Book => ("\u{f02d}", "¶", "?"),
            Rollback => ("\u{f1da}", "←", "<"),
            Erase => ("\u{f12d}", "×", "e"),
            Image => ("\u{f24d}", "▒", "c"),
            Edit => ("\u{f040}", "±", "e"),
            Backup => ("\u{f0c7}", "▼", "b"),
            Remote => ("\u{f1cd}", "∞", "r"),
            Search => ("\u{f002}", "?", "?"),
            Boot => ("\u{f0e7}", "↑", "b"),
            Containers => ("\u{f1b3}", "▓", "c"),
            Media => ("\u{f008}", "♪", "m"),
            Network => ("\u{f0e8}", "↔", "n"),
            Suggest => ("\u{f0eb}", "‼", "!"),
            Back => ("\u{f060}", "←", "<"),
            Update => ("\u{f021}", "↕", "u"),
            Settings => ("\u{f013}", "*", "s"),
            Vector => ("\u{f27a}", "♦", "V"),
            List => ("\u{f03a}", "≡", "="),
            Folder => ("\u{f07c}", "■", "/"),
            Gauge => ("\u{f0e4}", "▒", "%"),
            Git => ("\u{f1d3}", "±", "g"),
            Exchange => ("\u{f0ec}", "↔", "~"),
            Bluetooth => ("\u{f293}", "ß", "b"),
        }
    }

    /// The glyph for this look.
    pub fn of(self, look: &Look) -> &'static str {
        let (nerd, console, plain) = self.glyphs();
        if look.nerd {
            nerd
        } else if look.ascii || look.mode == crate::Mode::Mono {
            plain
        } else {
            console
        }
    }
}

/// Nerd glyphs for this environment: forced by BROMIGOS_ICONS, else in 24-bit colour with
/// box drawing (kmscon, desktop terminals, SSH from them).
pub fn nerd_from(get: &dyn Fn(&str) -> Option<String>, mode: crate::Mode, ascii: bool) -> bool {
    match get("BROMIGOS_ICONS").as_deref() {
        Some("nerd") => true,
        Some("ascii") => false,
        _ => mode == crate::Mode::Truecolor && !ascii,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Mode;

    #[test]
    fn fallbacks_are_ascii_and_single_cell() {
        for i in [
            Icon::Repair,
            Icon::Lab,
            Icon::Tools,
            Icon::Server,
            Icon::Install,
            Icon::Shell,
            Icon::Wifi,
            Icon::Usb,
        ] {
            let (n, c, p) = i.glyphs();
            assert!(p.is_ascii() && p.chars().count() == 1, "{i:?}");
            assert_eq!(n.chars().count(), 1);
            assert_eq!(c.chars().count(), 1);
        }
    }

    #[test]
    fn choice_follows_the_terminal() {
        let none = |_: &str| None;
        assert!(nerd_from(&none, Mode::Truecolor, false));
        assert!(!nerd_from(&none, Mode::Ansi16, false));
        assert!(!nerd_from(&none, Mode::Truecolor, true));
        let force = |k: &str| (k == "BROMIGOS_ICONS").then(|| "nerd".to_string());
        assert!(nerd_from(&force, Mode::Ansi16, false));
        let plain = |k: &str| (k == "BROMIGOS_ICONS").then(|| "ascii".to_string());
        assert!(!nerd_from(&plain, Mode::Truecolor, false));
    }
}
