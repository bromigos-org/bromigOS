//! The constellation: machines around a hub as a small braille radar (rings, a spoke to each
//! machine, a scan line going round), each machine a state dot with its name. Field Kit's Lab
//! screen draws the lab's parts with it where there's room. Under reduced motion the scan
//! holds still (the caller keeps `t` at 0). Braille only: elsewhere callers keep their list.

use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};

use crate::orb::Canvas;
use crate::term::Look;
use crate::widgets::Tone;

/// The most of a name shown beside its node.
const NAME: usize = 10;

/// Where node `i` of `n` sits, in dots, on a canvas `w` by `h` cells: round an ellipse from
/// the top, clockwise, a row and a half in from the top and bottom and a name's width in
/// from the sides (room for its name beside it).
fn node_at(i: usize, n: usize, w: usize, h: usize) -> (f64, f64) {
    let (cx, cy) = (w as f64, (h * 2) as f64);
    let (rx, ry) = ((cx - 2.0 * (NAME + 3) as f64).max(4.0), (cy - 6.0).max(2.0));
    let a = -std::f64::consts::FRAC_PI_2 + i as f64 * std::f64::consts::TAU / n.max(1) as f64;
    (cx + rx * a.cos(), cy + ry * a.sin())
}

/// The map, `w` cells by `h` rows: `hub` in the middle, `nodes` (a name and its state) round
/// it, the scan at time `t` (seconds).
pub fn constellation(
    look: &Look,
    hub: &str,
    nodes: &[(String, Tone)],
    w: usize,
    h: usize,
    t: f64,
) -> Vec<Line<'static>> {
    let p = &look.pal;
    let mut c = Canvas::new(w, h);
    let (cx, cy) = (w as f64 - 0.5, (h * 2) as f64 - 0.5);
    // two rings: the outer one dashed, the inner one dotted
    for i in 0..360 {
        let a = (i as f64).to_radians();
        if i % 10 < 4 {
            c.put(cx + (cx - 1.0) * a.cos(), cy + (cy - 1.0) * a.sin(), false);
        }
        if i % 15 == 0 {
            c.put(cx + cx * 0.5 * a.cos(), cy + cy * 0.5 * a.sin(), false);
        }
    }
    let n = nodes.len();
    for i in 0..n {
        c.line((cx, cy), node_at(i, n, w, h), 3.0, false);
    }
    // the scan: a line from the hub to the outer ring, and a fainter one trailing it
    let sweep = (t * 40.0).to_radians();
    for (k, lag) in [(1.0, 0.0), (0.9, 0.12)] {
        let a = sweep - lag;
        c.line(
            (cx, cy),
            (cx + (cx - 1.0) * k * a.cos(), cy + (cy - 1.0) * k * a.sin()),
            1.0,
            true,
        );
    }
    let mut cells: Vec<Vec<(String, Style)>> = c
        .rows()
        .into_iter()
        .map(|row| {
            row.into_iter()
                .map(|(ch, hot)| {
                    let s = if hot {
                        Style::new().fg(p.primary)
                    } else {
                        Style::new().fg(p.dim)
                    };
                    (ch.to_string(), s)
                })
                .collect()
        })
        .collect();
    let mut put = |x: usize, y: usize, text: &str, s: Style| {
        if y >= h {
            return;
        }
        let len = text.chars().count();
        let x0 = x.min(w.saturating_sub(len));
        for (k, ch) in text.chars().enumerate() {
            if x0 + k < w {
                cells[y][x0 + k] = (ch.to_string(), s);
            }
        }
    };
    let (hx, hy) = (w / 2, h / 2);
    put(
        hx,
        hy,
        "◉",
        Style::new().fg(p.white).add_modifier(Modifier::BOLD),
    );
    let hub: String = hub.chars().take(w.saturating_sub(2)).collect();
    let hl = hub.chars().count();
    put(
        (hx + 1).saturating_sub(hl.div_ceil(2)),
        hy + 1,
        &hub,
        Style::new().fg(p.soft).add_modifier(Modifier::BOLD),
    );
    for (i, (name, tone)) in nodes.iter().enumerate() {
        let (x, y) = node_at(i, n, w, h);
        let (x, y) = ((x / 2.0) as usize, (y / 4.0) as usize);
        let (dot, col) = match tone {
            Tone::Good => ("●", p.primary),
            Tone::Warn => ("▲", p.warn),
            Tone::Bad => ("✕", p.danger),
            Tone::Calm => ("○", p.muted),
        };
        put(x, y, dot, Style::new().fg(col).add_modifier(Modifier::BOLD));
        let name: String = name.chars().take(NAME).collect();
        let len = name.chars().count();
        // the name beside its node: to the left of one on the left, else to the right
        let lx = if x + 2 < hx {
            x.saturating_sub(len + 1)
        } else {
            x + 2
        };
        let s = if *tone == Tone::Bad || *tone == Tone::Warn {
            Style::new().fg(col)
        } else {
            Style::new().fg(p.text)
        };
        put(lx, y, &name, s);
    }
    cells
        .into_iter()
        .map(|row| {
            let mut spans: Vec<Span<'static>> = Vec::new();
            let mut text = String::new();
            let mut style = None;
            for (ch, s) in row {
                if let Some(prev) = style
                    && prev != s
                {
                    spans.push(Span::styled(std::mem::take(&mut text), prev));
                }
                style = Some(s);
                text.push_str(&ch);
            }
            if let Some(s) = style {
                spans.push(Span::styled(text, s));
            }
            Line::from(spans)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn text(lines: &[Line]) -> String {
        lines
            .iter()
            .map(|l| l.to_string())
            .collect::<Vec<_>>()
            .join("\n")
    }

    #[test]
    fn nodes_round_a_hub_with_their_names() {
        let look = Look::wick();
        let nodes = vec![
            ("node-a".to_string(), Tone::Good),
            ("k3s".to_string(), Tone::Good),
            ("nas".to_string(), Tone::Warn),
            ("node-c".to_string(), Tone::Bad),
        ];
        let a = constellation(&look, "LAB", &nodes, 44, 11, 0.0);
        assert_eq!(a.len(), 11);
        assert!(a.iter().all(|l| l.width() == 44), "{}", text(&a));
        let s = text(&a);
        for want in ["LAB", "node-a", "k3s", "nas", "node-c", "◉", "✕", "▲"] {
            assert!(s.contains(want), "{want}:\n{s}");
        }
        // the scan moves; the same time draws the same map
        assert_ne!(s, text(&constellation(&look, "LAB", &nodes, 44, 11, 2.0)));
        assert_eq!(s, text(&constellation(&look, "LAB", &nodes, 44, 11, 0.0)));
    }
}
