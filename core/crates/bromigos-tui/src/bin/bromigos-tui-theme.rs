//! `bromigos-tui-theme`: the theme in force as the other TUIs need it (docs/DRIFTGLASS.md).
//!
//!   bromigos-tui-theme --textual     a Textual theme (textual.theme.Theme's arguments, JSON),
//!                                    so the Python consoles (the lab's) match the Rust ones
//!   bromigos-tui-theme --look        what this terminal gets: the colour mode, ASCII, motion

use bromigos_tui::{Look, palette};

fn main() {
    let arg = std::env::args().nth(1).unwrap_or_default();
    match arg.as_str() {
        "--textual" => {
            let (pal, _) = palette::load();
            println!("{}", pal.textual_theme("driftglass"));
        }
        "--look" => {
            let l = Look::detect();
            println!("mode={:?} ascii={} motion={}", l.mode, l.ascii, l.motion);
        }
        _ => {
            eprintln!("bromigos-tui-theme --textual | --look");
            std::process::exit(2);
        }
    }
}
