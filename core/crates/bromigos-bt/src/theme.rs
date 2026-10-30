//! The theme in force, for the terminal: its colours (`palette.json`, which `bromigos theme
//! set` writes) and the user's motion setting. Without the file, the Wick's. The palette is
//! bromigos-tui's, shared by every bromigOS TUI.

pub use bromigos_tui::palette::{Pal, load, palette_path};
