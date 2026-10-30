//! Layouts that fit any terminal (docs/DRIFTGLASS.md): from a 200-column desktop terminal to
//! an 80×24 console or serial line and a phone over SSH at 45 columns. Every bromigOS TUI
//! picks its arrangement by [`Breakpoint`] and re-lays itself out on every frame, so a resize
//! re-flows it live (the selection and scroll stay).
//!
//! - [`Breakpoint`]: Wide ≥150, Medium 110–149, Narrow 80–109, Tiny <80 columns
//! - [`columns`], [`stack`], [`grid`]: the arrangements
//! - [`display_width`], [`truncate`], [`wrap`]: text measured as it shows (wide glyphs count two,
//!   ANSI escapes count none)
//! - [`Scroll`] and [`scroll_view`]: a list taller than its space, PgUp/PgDn, the wheel, j/k,
//!   keeping the selection in view, "↓ more" when there's more
//! - [`dialog`]: a dialog's rectangle, or the whole space (a sheet) where it doesn't fit
//! - [`too_small`] / [`too_small_screen`]: under 40×15, "make the window bigger"

use ratatui::Frame;
use ratatui::layout::{Alignment, Constraint, Layout, Rect};
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

use crate::term::Look;
use crate::widgets::st;

/// The smallest screen a bromigOS TUI draws on; under it, [`too_small_screen`].
pub const MIN_W: u16 = 40;
pub const MIN_H: u16 = 15;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Breakpoint {
    /// under 80 columns: a phone over SSH, a split pane. Lists instead of tiles, icons for
    /// chips, dialogs as full sheets with their buttons stacked
    Tiny,
    /// 80–109: the classic console and serial line. One column
    Narrow,
    /// 110–149: two columns, the left one narrower
    Medium,
    /// 150 and more: the layout as designed
    Wide,
}

impl Breakpoint {
    pub fn of(width: u16) -> Breakpoint {
        match width {
            0..=79 => Breakpoint::Tiny,
            80..=109 => Breakpoint::Narrow,
            110..=149 => Breakpoint::Medium,
            _ => Breakpoint::Wide,
        }
    }

    pub fn of_area(area: Rect) -> Breakpoint {
        Breakpoint::of(area.width)
    }

    /// Two columns side by side (Medium and Wide).
    pub fn side_by_side(self) -> bool {
        self >= Breakpoint::Medium
    }
}

/// Under 40×15: too small to draw anything well.
pub fn too_small(area: Rect) -> bool {
    area.width < MIN_W || area.height < MIN_H
}

/// The "make the window bigger" screen, for whatever space there is.
pub fn too_small_screen(f: &mut Frame, area: Rect, look: &Look) {
    let p = &look.pal;
    f.render_widget(Paragraph::new("").style(Style::new().bg(p.void)), area);
    let lines = vec![
        Line::from(Span::styled(
            "◢ BROMIGOS",
            st(p.primary).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        Line::from(Span::styled("Make the window bigger:", st(p.text))),
        Line::from(Span::styled(
            format!(
                "{MIN_W}×{MIN_H} at least, it's {}×{}.",
                area.width, area.height
            ),
            st(p.muted),
        )),
    ];
    let h = (lines.len() as u16).min(area.height);
    let r = Rect::new(
        area.x,
        area.y + area.height.saturating_sub(h) / 2,
        area.width,
        h,
    );
    f.render_widget(Paragraph::new(lines).alignment(Alignment::Center), r);
}

/// Two columns: `left` wide (capped to half), a gap, the rest.
pub fn columns(area: Rect, left: u16, gap: u16) -> (Rect, Rect) {
    let left = left.min(area.width.saturating_sub(gap) / 2).max(1);
    let [l, _, r] = Layout::horizontal([
        Constraint::Length(left),
        Constraint::Length(gap),
        Constraint::Min(1),
    ])
    .areas(area);
    (l, r)
}

/// One above the other: `top` tall (capped to the area), the rest below.
pub fn stack(area: Rect, top: u16, gap: u16) -> (Rect, Rect) {
    let top = top.min(area.height);
    let [t, _, b] = Layout::vertical([
        Constraint::Length(top),
        Constraint::Length(gap),
        Constraint::Min(0),
    ])
    .areas(area);
    (t, b)
}

/// `n` cells in rows of `cols`, each `cell_h` tall with gaps, starting at row `first_row`
/// (rows above it scroll out: their cells are empty rectangles, height 0); cells past the
/// bottom are empty too. The widths share the area exactly.
pub fn grid(
    area: Rect,
    n: usize,
    cols: usize,
    cell_h: u16,
    gap_x: u16,
    gap_y: u16,
    first_row: usize,
) -> Vec<Rect> {
    let cols = cols.max(1);
    let gaps = gap_x * (cols as u16 - 1);
    let w = area.width.saturating_sub(gaps) / cols as u16;
    let extra = area.width.saturating_sub(gaps) - w * cols as u16;
    (0..n)
        .map(|i| {
            let (row, col) = (i / cols, i % cols);
            if row < first_row {
                return Rect::new(area.x, area.y, 0, 0);
            }
            let y = area.y + (row - first_row) as u16 * (cell_h + gap_y);
            if y + cell_h > area.bottom() {
                return Rect::new(area.x, area.y, 0, 0);
            }
            let x = area.x + col as u16 * (w + gap_x);
            // the last column takes what's left over, so the grid fills the width
            let cw = if col == cols - 1 { w + extra } else { w };
            Rect::new(x, y, cw, cell_h)
        })
        .collect()
}

/// The first grid row to show so that `sel`'s row is visible.
pub fn grid_first_row(sel: usize, cols: usize, visible_rows: usize) -> usize {
    (sel / cols.max(1)).saturating_sub(visible_rows.max(1) - 1)
}

/// How wide a text shows: wide glyphs (CJK, emoji) count two, ANSI escapes none.
pub fn display_width(s: &str) -> usize {
    let mut w = 0;
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\x1b' {
            // CSI: ESC [ … final byte in @..~
            if chars.peek() == Some(&'[') {
                chars.next();
                for d in chars.by_ref() {
                    if ('@'..='~').contains(&d) {
                        break;
                    }
                }
            }
            continue;
        }
        w += c.width().unwrap_or(0);
    }
    w
}

/// The text cut to `width` columns, ending in "…" ("." in ASCII) when it was cut.
pub fn truncate(s: &str, width: usize, ascii: bool) -> String {
    if UnicodeWidthStr::width(s) <= width {
        return s.to_string();
    }
    let ell = if ascii { "." } else { "…" };
    let room = width.saturating_sub(1);
    let mut out = String::new();
    let mut w = 0;
    for c in s.chars() {
        let cw = c.width().unwrap_or(0);
        if w + cw > room {
            break;
        }
        out.push(c);
        w += cw;
    }
    let mut out = out.trim_end().to_string();
    if width > 0 {
        out.push_str(ell);
    }
    out
}

/// Word-wrapped lines, each at most `width` columns as shown; a word longer than a line is
/// split. (widgets::wrap_hanging adds the indent and the styles.)
pub fn wrap(text: &str, width: usize) -> Vec<String> {
    let width = width.max(1);
    let mut out = Vec::new();
    for para in text.split('\n') {
        let mut line = String::new();
        let mut lw = 0;
        for word in para.split_whitespace() {
            let mut word = word.to_string();
            loop {
                let ww = UnicodeWidthStr::width(word.as_str());
                if lw == 0 && ww <= width {
                    line.push_str(&word);
                    lw = ww;
                    break;
                }
                if lw > 0 && lw + 1 + ww <= width {
                    line.push(' ');
                    line.push_str(&word);
                    lw += 1 + ww;
                    break;
                }
                if lw > 0 {
                    out.push(std::mem::take(&mut line));
                    lw = 0;
                    continue;
                }
                let mut head = String::new();
                let mut hw = 0;
                let mut rest = String::new();
                for c in word.chars() {
                    let cw = c.width().unwrap_or(0);
                    if hw + cw > width || !rest.is_empty() {
                        rest.push(c);
                    } else {
                        head.push(c);
                        hw += cw;
                    }
                }
                out.push(head);
                word = rest;
                if word.is_empty() {
                    break;
                }
            }
        }
        out.push(line);
    }
    out
}

/// A list's scroll: the first row shown.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Scroll {
    pub offset: usize,
}

impl Scroll {
    /// Keeps the rows `at..at+len` in a view `height` rows tall (the selection stays visible
    /// when the list grows, shrinks or the window is resized).
    pub fn keep_visible(&mut self, at: usize, len: usize, height: usize) {
        let height = height.max(1);
        if at < self.offset {
            self.offset = at;
        } else if at + len > self.offset + height {
            self.offset = (at + len).saturating_sub(height);
        }
    }

    /// The scroll keys: PgUp/PgDn a page, j/k and the arrows a row, Home/End. True when the
    /// key was one of them.
    pub fn key(
        &mut self,
        code: ratatui::crossterm::event::KeyCode,
        total: usize,
        height: usize,
    ) -> bool {
        use ratatui::crossterm::event::KeyCode as K;
        let max = total.saturating_sub(height.max(1));
        match code {
            K::PageDown | K::Char(' ') => self.offset = (self.offset + height.max(1)).min(max),
            K::PageUp => self.offset = self.offset.saturating_sub(height.max(1)),
            K::Down | K::Char('j') => self.offset = (self.offset + 1).min(max),
            K::Up | K::Char('k') => self.offset = self.offset.saturating_sub(1),
            K::Home => self.offset = 0,
            K::End => self.offset = max,
            _ => return false,
        }
        true
    }

    /// The mouse wheel: three rows a notch.
    pub fn wheel(&mut self, down: bool, total: usize, height: usize) {
        let max = total.saturating_sub(height.max(1));
        self.offset = if down {
            (self.offset + 3).min(max)
        } else {
            self.offset.saturating_sub(3)
        };
    }

    /// The offset, kept in range for a list of `total` rows in `height`.
    pub fn clamped(&self, total: usize, height: usize) -> usize {
        self.offset.min(total.saturating_sub(height.max(1)))
    }
}

/// Lines in an area, from `offset`, with "↑ more" / "↓ more" (ASCII ^/v) when there's more
/// above / below. The marks go on the panel's frame (the border row just above or below the
/// area) when there is one; without a frame the view gives up a row for them. Never over
/// the content.
pub fn scroll_view(
    f: &mut Frame,
    area: Rect,
    look: &Look,
    lines: Vec<Line<'static>>,
    offset: usize,
) {
    let total = lines.len();
    let full = f.area();
    let is_rule = |f: &mut Frame, y: u16| {
        if y < full.y || y >= full.bottom() || area.width < 3 {
            return false;
        }
        let x = area.right().saturating_sub(2);
        matches!(f.buffer_mut()[(x, y)].symbol(), "─" | "━" | "-" | "=" | "═")
    };
    let top_rule = area.y > full.y && is_rule(f, area.y - 1);
    let bottom_rule = is_rule(f, area.bottom());
    let mut view = area;
    let h0 = area.height as usize;
    let offset = offset.min(total.saturating_sub(h0));
    let more_up = offset > 0;
    let more_down = offset + h0 < total;
    // no frame to carry a mark: a row of the view carries it instead (never drawn over text)
    if more_up && !top_rule && view.height > 2 {
        view.y += 1;
        view.height -= 1;
    }
    if more_down && !bottom_rule && view.height > 2 {
        view.height -= 1;
    }
    let h = view.height as usize;
    let offset = offset.min(total.saturating_sub(h));
    f.render_widget(Paragraph::new(lines).scroll((offset as u16, 0)), view);
    let (up, down) = if look.ascii {
        ("^ more", "v more")
    } else {
        ("↑ more", "↓ more")
    };
    let mark = |f: &mut Frame, y: u16, text: &str| {
        let w = text.chars().count() as u16 + 2;
        if area.width > w + 2 {
            let r = Rect::new(area.right() - w - 1, y, w, 1);
            f.render_widget(
                Paragraph::new(Span::styled(format!(" {text} "), st(look.pal.accent))),
                r,
            );
        }
    };
    if offset > 0 {
        mark(f, if top_rule { area.y - 1 } else { area.y }, up);
    }
    if offset + h < total {
        mark(
            f,
            if bottom_rule {
                area.bottom()
            } else {
                area.bottom() - 1
            },
            down,
        );
    }
}

/// A dialog's rectangle: `w`×`h` in the middle of `area` when it fits with room round it (on
/// Medium and Wide), else the whole area (a sheet).
pub fn dialog(area: Rect, w: u16, h: u16) -> Rect {
    if Breakpoint::of_area(area).side_by_side() && w + 4 <= area.width && h + 2 <= area.height {
        Rect::new(
            area.x + (area.width - w) / 2,
            area.y + (area.height - h) / 2,
            w,
            h,
        )
    } else {
        area
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn breakpoints() {
        assert_eq!(Breakpoint::of(200), Breakpoint::Wide);
        assert_eq!(Breakpoint::of(150), Breakpoint::Wide);
        assert_eq!(Breakpoint::of(149), Breakpoint::Medium);
        assert_eq!(Breakpoint::of(110), Breakpoint::Medium);
        assert_eq!(Breakpoint::of(109), Breakpoint::Narrow);
        assert_eq!(Breakpoint::of(80), Breakpoint::Narrow);
        assert_eq!(Breakpoint::of(79), Breakpoint::Tiny);
        assert!(too_small(Rect::new(0, 0, 39, 20)) && too_small(Rect::new(0, 0, 80, 14)));
        assert!(!too_small(Rect::new(0, 0, 40, 15)));
    }

    #[test]
    fn widths_and_cuts() {
        assert_eq!(display_width("\x1b[38;2;1;2;3mab\x1b[0m"), 2);
        assert_eq!(display_width("日本"), 4);
        assert_eq!(truncate("bromigOS Field Kit", 10, false), "bromigOS…");
        assert_eq!(
            UnicodeWidthStr::width(truncate("日本語のテキスト", 7, false).as_str()),
            7
        );
        assert_eq!(truncate("short", 10, true), "short");
        let w = wrap("one two three four five", 9);
        assert!(
            w.iter().all(|l| UnicodeWidthStr::width(l.as_str()) <= 9),
            "{w:?}"
        );
        assert_eq!(w.join(" "), "one two three four five");
        assert_eq!(wrap("abcdefghij", 4), vec!["abcd", "efgh", "ij"]);
    }

    #[test]
    fn grids_and_scrolls() {
        let a = Rect::new(0, 0, 100, 20);
        let g = grid(a, 7, 3, 4, 2, 1, 0);
        assert_eq!(g[0].width + g[1].width + g[2].width + 4, 100);
        assert_eq!(g[3].y, 5);
        assert!(g.iter().all(|r| r.bottom() <= a.bottom()));
        let g = grid(a, 12, 3, 4, 2, 1, grid_first_row(10, 3, 4));
        assert!(g[10].height > 0, "the selected card is on the screen");
        let mut s = Scroll::default();
        s.keep_visible(30, 2, 10);
        assert_eq!(s.offset, 22);
        s.keep_visible(5, 1, 10);
        assert_eq!(s.offset, 5);
        assert!(s.key(ratatui::crossterm::event::KeyCode::PageDown, 100, 10));
        assert_eq!(s.offset, 15);
        assert_eq!(
            dialog(Rect::new(0, 0, 60, 20), 50, 10),
            Rect::new(0, 0, 60, 20),
            "a sheet when narrow"
        );
        assert_eq!(dialog(Rect::new(0, 0, 160, 40), 50, 10).width, 50);
    }
}
