//! The hologram orb: VECTOR's presence and Field Kit Home's FLARE, drawn in braille (a ring
//! with a dashed inner ring and ticks, a scan arc going round, a pulsing core), after the
//! operator's mock-up. Under reduced motion it holds still (the caller keeps `t` at 0). The
//! console and ASCII looks get a small ring in plain characters, with the same scan and core.

use crate::{Look, Mode};
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};

/// Dots on a braille canvas `w` cells by `h` (2 by 4 dots each); `hot` cells glow. The orb,
/// the lab's map and anything else drawn in dots share it.
pub struct Canvas {
    pub w: usize,
    pub h: usize,
    pub dots: Vec<u8>,
    pub hot: Vec<bool>,
}

impl Canvas {
    pub fn new(w: usize, h: usize) -> Canvas {
        Canvas {
            w,
            h,
            dots: vec![0; w * h],
            hot: vec![false; w * h],
        }
    }

    /// A dot at (x, y) in dots; off the canvas, nothing.
    pub fn put(&mut self, x: f64, y: f64, glow: bool) {
        let (x, y) = (x.round(), y.round());
        if x < 0.0 || y < 0.0 || x >= (self.w * 2) as f64 || y >= (self.h * 4) as f64 {
            return;
        }
        let (x, y) = (x as usize, y as usize);
        let bit = match (x % 2, y % 4) {
            (0, 0) => 1,
            (0, 1) => 2,
            (0, 2) => 4,
            (1, 0) => 8,
            (1, 1) => 16,
            (1, 2) => 32,
            (0, 3) => 64,
            _ => 128,
        };
        let i = (y / 4) * self.w + x / 2;
        self.dots[i] |= bit;
        self.hot[i] |= glow;
    }

    /// A dotted line from (x0, y0) to (x1, y1), a dot every `step` dots.
    pub fn line(&mut self, (x0, y0): (f64, f64), (x1, y1): (f64, f64), step: f64, glow: bool) {
        let n = ((x1 - x0).hypot(y1 - y0) / step.max(0.5)).ceil().max(1.0) as usize;
        for i in 0..=n {
            let k = i as f64 / n as f64;
            self.put(x0 + (x1 - x0) * k, y0 + (y1 - y0) * k, glow);
        }
    }

    /// The canvas as rows of (character, glowing).
    pub fn rows(&self) -> Vec<Vec<(char, bool)>> {
        (0..self.h)
            .map(|y| {
                (0..self.w)
                    .map(|x| {
                        let i = y * self.w + x;
                        let ch = if self.dots[i] == 0 {
                            ' '
                        } else {
                            char::from_u32(0x2800 + self.dots[i] as u32).unwrap_or(' ')
                        };
                        (ch, self.hot[i])
                    })
                    .collect()
            })
            .collect()
    }
}

/// The braille orb at time `t` (seconds): rows of (character, glowing).
pub fn braille(t: f64, w: usize, h: usize) -> Vec<Vec<(char, bool)>> {
    let mut c = Canvas::new(w, h);
    let (cx, cy) = ((w * 2) as f64 / 2.0 - 0.5, (h * 4) as f64 / 2.0 - 0.5);
    let rad = cx.min(cy);
    // the mock-up's sizes are for a 21.5-dot radius; smaller orbs scale them
    let k = rad / 21.5;
    let at = |r: f64, a: f64| (cx + r * a.cos(), cy + r * a.sin());
    for i in 0..360 {
        let a = (i as f64).to_radians();
        let (x, y) = at(rad, a);
        c.put(x, y, false);
        if i % 6 < 3 {
            let (x, y) = at(rad - 6.0 * k, a);
            c.put(x, y, false);
        }
        if i % 30 == 0 {
            for d in [1.0, 2.0] {
                let (x, y) = at(rad - d, a);
                c.put(x, y, false);
            }
        }
    }
    let sweep = (t * 40.0) % 360.0;
    for i in 0..70 {
        let a = (sweep + i as f64).to_radians();
        for d in [0.0, 1.0, 2.0] {
            let (x, y) = at(rad - d, a);
            c.put(x, y, true);
        }
    }
    let pulse = (6.0 + 1.5 * (t * 3.0).sin()) * k;
    for yy in 0..h * 4 {
        for xx in 0..w * 2 {
            let r = ((xx as f64 - cx).powi(2) + (yy as f64 - cy).powi(2)).sqrt();
            if r > 2.2 * k && r < pulse {
                c.put(xx as f64, yy as f64, r > pulse - 1.2 * k);
            }
        }
    }
    c.rows()
}

/// The plain ring: the outer ring's characters glow where the scan is; the core breathes.
const RING: [&str; 5] = [
    "  .-'''''-.  ",
    " /  .---.  \\ ",
    "|  ( (@) )  |",
    " \\  '---'  / ",
    "  '-.....-'  ",
];

pub fn plain(t: f64) -> Vec<Vec<(char, bool)>> {
    let sweep = (t * 40.0) % 360.0;
    let big = (t * 3.0).sin() >= 0.0;
    RING.iter()
        .enumerate()
        .map(|(y, row)| {
            row.chars()
                .enumerate()
                .map(|(x, ch)| {
                    let (dx, dy) = (x as f64 - 6.0, (y as f64 - 2.0) * 2.4);
                    if ch == '@' {
                        return (if big { '@' } else { 'o' }, big);
                    }
                    let outer = (dx * dx + dy * dy).sqrt() > 4.6;
                    let a = dy.atan2(dx).to_degrees().rem_euclid(360.0);
                    let into = (a - sweep).rem_euclid(360.0);
                    (ch, outer && ch != ' ' && into < 70.0)
                })
                .collect()
        })
        .collect()
}

/// Whether braille shows on this look: 24-bit colour terminals' fonts have it; the Linux
/// console's font and ASCII don't.
pub fn fine(look: &Look) -> bool {
    look.mode == Mode::Truecolor && !look.ascii
}

/// The orb's rows for this look: braille where it shows, the plain ring elsewhere.
pub fn rows(look: &Look, t: f64, size: (usize, usize)) -> Vec<Vec<(char, bool)>> {
    if fine(look) {
        braille(t, size.0, size.1)
    } else {
        plain(t)
    }
}

/// The orb as lines for this look: braille where it shows (truecolour), the plain ring
/// elsewhere. `size` is the braille size in cells (w, h); the plain ring is always 13 by 5.
pub fn lines(look: &Look, t: f64, size: (usize, usize)) -> Vec<Line<'static>> {
    let rows = rows(look, t, size);
    let p = &look.pal;
    rows.into_iter()
        .map(|row| {
            Line::from(
                row.into_iter()
                    .map(|(ch, hot)| {
                        let s = if hot {
                            Style::new().fg(p.white).add_modifier(Modifier::BOLD)
                        } else {
                            Style::new().fg(p.primary)
                        };
                        Span::styled(ch.to_string(), s)
                    })
                    .collect::<Vec<_>>(),
            )
        })
        .collect()
}

/// The plain ring's size, for laying it out.
pub const PLAIN: (usize, usize) = (13, 5);

#[cfg(test)]
mod tests {
    use super::*;

    fn text(rows: &[Vec<(char, bool)>]) -> String {
        rows.iter()
            .map(|r| r.iter().map(|c| c.0).collect::<String>())
            .collect::<Vec<_>>()
            .join("\n")
    }

    #[test]
    fn the_scan_goes_round_and_the_core_breathes() {
        let a = braille(0.0, 22, 11);
        let b = braille(1.0, 22, 11);
        assert_eq!(a.len(), 11);
        assert!(a.iter().all(|r| r.len() == 22));
        assert_ne!(text(&a), text(&b));
        let hot = |rows: &[Vec<(char, bool)>]| -> Vec<(usize, usize)> {
            let mut v = Vec::new();
            for (y, r) in rows.iter().enumerate() {
                for (x, c) in r.iter().enumerate() {
                    if c.1 {
                        v.push((x, y));
                    }
                }
            }
            v
        };
        assert_ne!(hot(&a), hot(&b), "the scan arc moved");
        // the same time draws the same orb (reduced motion holds t still)
        assert_eq!(text(&a), text(&braille(0.0, 22, 11)));
        // a small one still has its ring and core
        let s = braille(0.0, 14, 7);
        assert!(text(&s).chars().filter(|c| *c != ' ' && *c != '\n').count() > 20);
    }

    #[test]
    fn the_plain_ring_is_ascii_and_scans_too() {
        let a = plain(0.0);
        assert!(text(&a).is_ascii());
        assert_eq!(a.len(), PLAIN.1);
        assert!(a.iter().all(|r| r.len() == PLAIN.0));
        let glow = |rows: &[Vec<(char, bool)>]| rows.iter().flatten().filter(|c| c.1).count();
        assert!(glow(&a) > 0);
        assert_ne!(
            a.iter().flatten().map(|c| c.1).collect::<Vec<_>>(),
            plain(3.0).iter().flatten().map(|c| c.1).collect::<Vec<_>>()
        );
    }
}
