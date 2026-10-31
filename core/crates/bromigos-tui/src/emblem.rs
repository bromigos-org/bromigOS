//! The burn-in emblem and the bromigOS banner, in text.
//!
//! The emblem is the Wick's `emblem.braille` (themes/wick/emblem; lib/emblem_braille.py makes
//! it), without its escapes: braille needs a font that has it (kmscon's Geist Mono with its
//! fallbacks, any desktop terminal). The Linux console's font has none of it, so there the
//! banner is the wordmark in block characters instead.

/// The emblem as braille, 11 rows by 22 columns.
pub const EMBLEM_BRAILLE: &str = include_str!("emblem.txt");

/// The wordmark in block characters, for any console font (the bromigOS PSF has them).
pub const WORDMARK: [&str; 3] = [
    "█▀▄ █▀▄ █▀█ █▀▄▀█ █ █▀▀ █▀█ █▀▀",
    "█▀▄ █▀▄ █ █ █ ▀ █ █ █ █ █ █ ▀▀█",
    "▀▀  ▀ ▀ ▀▀▀ ▀   ▀ ▀ ▀▀▀ ▀▀▀ ▀▀▀",
];

/// The wordmark in plain ASCII, for terminals without block characters.
pub const WORDMARK_ASCII: [&str; 1] = ["B R O M I G O S"];

/// The emblem's rows (trailing blanks kept off).
pub fn emblem_rows() -> Vec<&'static str> {
    EMBLEM_BRAILLE
        .lines()
        .map(|l| l.trim_end())
        .filter(|l| !l.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    #[test]
    fn emblem_is_there() {
        let rows = super::emblem_rows();
        assert!(rows.len() >= 8, "{rows:?}");
        assert!(rows.iter().all(|r| !r.contains('\x1b')));
    }
}
