//! bromigOS's DRIFTGLASS in the terminal (docs/DRIFTGLASS.md): one palette and one set of
//! widgets for every bromigOS TUI (`bromigos bluetooth tui`, `bromigos fieldkit`, the
//! installer's TUI), so they look like one system on any terminal.
//!
//! - [`palette`]: the theme's colours (palette.json, the Wick's by default), and the same
//!   palette as a Textual theme, so the Python consoles (the lab's) match
//! - [`term`]: what the terminal can show (24-bit colour, the Linux console's 16 colours,
//!   plain ASCII) and whether motion is allowed (reduced motion)
//! - [`widgets`]: Glass panels, the Emitter header (a screen's one FLARE), Sweep progress,
//!   the Reading status line (EMBER), menus with hints, confirm dialogs (and confirm by typing
//!   a name), the log viewer
//! - [`emblem`]: the burn-in emblem and the banner, in text
//! - [`layout`]: breakpoints, columns, grids, scrolling, sheets: every size from a phone to a 4K terminal
//! - [`icons`]: Nerd Font icons, each with a plain fallback for the Linux console and ASCII
//!
//! The Linux console has 16 colours. bromigos-boot sets them to DRIFTGLASS's at boot
//! (settings/console/palette.vtrgb), so [`term::Mode::Ansi16`] names those indexes and the
//! console shows the theme's real colours, not stock VGA ones.

pub mod emblem;
pub mod icons;
pub mod layout;
pub mod palette;
pub mod term;
pub mod widgets;

pub use icons::Icon;
pub use layout::Breakpoint;
pub use palette::Pal;
pub use term::{Look, Mode};
