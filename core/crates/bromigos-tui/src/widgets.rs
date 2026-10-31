//! DRIFTGLASS's blocks for the terminal (docs/DRIFTGLASS.md). Each takes a [`Look`], so the
//! same screen reads right in 24-bit colour, on the Linux console's 16 and in plain ASCII.
//!
//! - [`glass`]: a panel (GLOW): a rounded frame in the theme's colours
//! - [`emitter`]: a screen's header band, the emblem beside the title: its one FLARE
//! - [`sweep`]: progress. A share fills the bar; without one, a bright segment travels it,
//!   only while motion is allowed, else it says "working" and stays still
//! - [`reading`]: the status line (EMBER): short facts, a colour only when it means something
//! - [`menu`]: a list of items, each with a one-line hint and why it can't run now
//! - [`confirm`], [`typed_confirm`], [`input`]: dialogs, centred over the screen
//! - [`log_view`]: a command's output as it runs
//! - [`spark`]: the one-second glow on a panel's edge when something succeeds
//! - [`glow`]: a focused card's Emitter-style glow (a bright frame on a soft surface)
//! - [`meter`], [`sparkline`]: a share as a small bar, readings over time as a tiny line

use ratatui::Frame;
use ratatui::layout::{Alignment, Constraint, Layout, Margin, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::symbols::border;
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, BorderType, Borders, Clear, Paragraph};

use crate::emblem;
use crate::term::{Look, Mode};

/// ASCII borders: the frame where a terminal has no box drawing.
pub const ASCII_BORDER: border::Set = border::Set {
    top_left: "+",
    top_right: "+",
    bottom_left: "+",
    bottom_right: "+",
    vertical_left: "|",
    vertical_right: "|",
    horizontal_top: "-",
    horizontal_bottom: "-",
};

/// A highlighted card's or row's surface. On the Linux console's 16 colours the surface is
/// green (2) with black (0) text, set explicitly: a surface and text that resolve to the same
/// index would hide the text. Without colour, reversed.
pub fn sel_surface(look: &Look) -> Style {
    match look.mode {
        crate::term::Mode::Truecolor => Style::new().bg(look.pal.selection).fg(look.pal.text),
        crate::term::Mode::Ansi16 => Style::new().bg(Color::Green).fg(Color::Black),
        crate::term::Mode::Mono => Style::new().add_modifier(Modifier::REVERSED),
    }
}

/// Text on a highlighted surface: the primary colour, bold (black on green on the console, not
/// bold there: the Linux console shows bold black as its bright black, grey on green).
pub fn sel_text(look: &Look) -> Style {
    match look.mode {
        crate::term::Mode::Truecolor => Style::new()
            .fg(look.pal.primary)
            .add_modifier(Modifier::BOLD),
        crate::term::Mode::Ansi16 => Style::new().bg(Color::Green).fg(Color::Black),
        crate::term::Mode::Mono => Style::new().add_modifier(Modifier::REVERSED | Modifier::BOLD),
    }
}

/// The screen's corner mark: ◢, or ► where the console's font has no ◢, or / in ASCII.
pub fn mark(look: &Look) -> &'static str {
    if look.ascii {
        "/"
    } else if look.mode == crate::term::Mode::Truecolor {
        "◢"
    } else {
        "►"
    }
}

pub fn st(fg: Color) -> Style {
    Style::new().fg(fg)
}

/// What a fact in the status line means: its colour (Reading: a glow always means something).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tone {
    Calm,
    Good,
    Warn,
    Bad,
}

fn tone(look: &Look, t: Tone) -> Color {
    match t {
        Tone::Calm => look.pal.muted,
        Tone::Good => look.pal.primary,
        Tone::Warn => look.pal.warn,
        Tone::Bad => look.pal.danger,
    }
}

/// A Glass panel: a frame with its title, the panel's surface behind its text. `focused`
/// lights the frame in the primary colour.
pub fn glass<'a>(look: &Look, title: &'a str, focused: bool) -> Block<'a> {
    let p = &look.pal;
    let mut b = Block::new()
        .borders(Borders::ALL)
        .border_style(st(if focused { p.primary } else { p.dim }))
        .style(Style::new().bg(p.panel).fg(p.text));
    b = if look.ascii {
        b.border_set(ASCII_BORDER)
    } else {
        b.border_type(BorderType::Rounded)
    };
    if !title.is_empty() {
        b = b.title(Span::styled(
            format!(" {title} "),
            st(p.primary).add_modifier(Modifier::BOLD),
        ));
    }
    b
}

/// The Spark: a panel's frame in the soft glow, for about a second after a success (the
/// caller clears it; never under reduced motion).
pub fn spark<'a>(look: &Look, block: Block<'a>, on: bool) -> Block<'a> {
    if on && look.motion {
        block.border_style(st(look.pal.soft).add_modifier(Modifier::BOLD))
    } else {
        block
    }
}

/// A card that glows when it's focused, after the Emitter: its frame bright and bold in the
/// primary colour, its title in white, on a soft surface (the panel a little towards the
/// primary). Unfocused, it's plain Glass. The console keeps its green selection surface.
pub fn glow<'a>(look: &Look, title: &'a str, focused: bool) -> Block<'a> {
    let b = glass(look, title, focused);
    if !focused {
        return b;
    }
    let p = &look.pal;
    let b = b.border_style(st(p.primary).add_modifier(Modifier::BOLD));
    let b = if title.is_empty() {
        b
    } else {
        b.title(Span::styled(
            format!(" {title} "),
            st(p.white).add_modifier(Modifier::BOLD),
        ))
    };
    match look.mode {
        Mode::Truecolor => b.style(
            Style::new()
                .bg(crate::palette::mix(p.panel, p.primary, 0.14))
                .fg(p.text),
        ),
        _ => b.style(sel_surface(look)),
    }
}

/// A meter: `share` (0 to 1) of `width` cells filled, in `tone`'s colour (Reading: calm is the
/// soft colour, a warning glows). Eighth blocks where braille shows, whole blocks on the
/// console, `#` and `.` in ASCII.
pub fn meter(look: &Look, share: f64, width: u16, t: Tone) -> Vec<Span<'static>> {
    let p = &look.pal;
    let w = width.max(1) as usize;
    let share = if share.is_finite() {
        share.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let c = if t == Tone::Calm {
        p.soft
    } else {
        tone(look, t)
    };
    let eighths = (share * (w * 8) as f64).round() as usize;
    let (full, part) = (eighths / 8, eighths % 8);
    let (block, empty) = if look.ascii {
        ("#", ".")
    } else {
        ("█", "░")
    };
    let mut lit = block.repeat(full);
    let mut used = full;
    if part > 0 && used < w {
        // the last cell's share: an eighth block, or on the console a whole one from half up
        let ch = if look.mode == Mode::Truecolor && !look.ascii {
            Some(["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"][part])
        } else {
            (part >= 4).then_some(block)
        };
        if let Some(ch) = ch {
            lit.push_str(ch);
            used += 1;
        }
    }
    vec![
        Span::styled(lit, st(c)),
        Span::styled(empty.repeat(w - used.min(w)), st(p.faint)),
    ]
}

/// A sparkline: the readings `values` from `lo` to `hi`, oldest first, one cell each, the last
/// `width` of them. Eighth blocks where braille shows; elsewhere a plain ramp (`_.-=+*#`).
pub fn sparkline(look: &Look, values: &[f64], lo: f64, hi: f64, width: usize) -> String {
    const FINE: [char; 8] = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];
    const PLAIN: [char; 7] = ['_', '.', '-', '=', '+', '*', '#'];
    let ramp: &[char] = if look.mode == Mode::Truecolor && !look.ascii {
        &FINE
    } else {
        &PLAIN
    };
    let span = (hi - lo).max(f64::EPSILON);
    let skip = values.len().saturating_sub(width);
    values[skip..]
        .iter()
        .map(|v| {
            let k = ((v - lo) / span).clamp(0.0, 1.0);
            ramp[((k * (ramp.len() - 1) as f64).round() as usize).min(ramp.len() - 1)]
        })
        .collect()
}

/// The Emitter: the header band. The emblem (or the wordmark, where braille can't show) on
/// the left, the title in the primary colour and its line under it, a heavy rule below.
/// Rows it takes: [`emitter_height`].
pub fn emitter(f: &mut Frame, area: Rect, look: &Look, title: &str, subtitle: &str) {
    let p = &look.pal;
    let rows: Vec<&str> = if look.ascii {
        emblem::WORDMARK_ASCII.to_vec()
    } else if look.mode == Mode::Truecolor && area.height >= 8 {
        emblem::emblem_rows()
    } else {
        emblem::WORDMARK.to_vec()
    };
    let shown = rows.len().min(area.height.saturating_sub(1) as usize);
    let art_w = rows.iter().map(|r| r.chars().count()).max().unwrap_or(0) as u16 + 2;
    // a narrow screen keeps the title whole and leaves the art out
    let art_w = if art_w > area.width / 2 { 0 } else { art_w };
    let [band, rule] = Layout::vertical([Constraint::Min(1), Constraint::Length(1)]).areas(area);
    let [art, words] =
        Layout::horizontal([Constraint::Length(art_w), Constraint::Min(10)]).areas(band);
    let art_lines: Vec<Line> = rows
        .iter()
        .take(shown)
        .map(|r| Line::from(Span::styled(format!(" {r}"), st(p.primary))))
        .collect();
    f.render_widget(
        Paragraph::new(art_lines).style(Style::new().bg(p.void)),
        art,
    );
    let mid = words.height.saturating_sub(2) / 2;
    let mut text: Vec<Line> = (0..mid).map(|_| Line::from("")).collect();
    text.push(Line::from(Span::styled(
        title.to_string(),
        st(p.primary).add_modifier(Modifier::BOLD),
    )));
    text.push(Line::from(Span::styled(subtitle.to_string(), st(p.muted))));
    f.render_widget(Paragraph::new(text).style(Style::new().bg(p.void)), words);
    let ch = if look.ascii { "=" } else { "━" };
    f.render_widget(
        Paragraph::new(Span::styled(ch.repeat(rule.width as usize), st(p.primary)))
            .style(Style::new().bg(p.void)),
        rule,
    );
}

/// The Emitter's height for a screen this tall: the braille emblem when there's room.
pub fn emitter_height(look: &Look, screen_rows: u16) -> u16 {
    if look.ascii {
        3
    } else if look.mode == Mode::Truecolor && screen_rows >= 36 {
        emblem::emblem_rows().len() as u16 + 1
    } else {
        4
    }
}

/// Sweep: a progress bar `width` cells wide. `pct`: how far, when known. Without it, a
/// bright segment travels along with `tick` while motion is allowed; still, it reads
/// "working" instead.
pub fn sweep(look: &Look, pct: Option<u8>, tick: u64, width: u16) -> Line<'static> {
    let p = &look.pal;
    let w = width.max(4) as usize;
    let (full, empty) = if look.ascii {
        ("#", ".")
    } else {
        ("━", "─")
    };
    match pct {
        Some(v) => {
            let v = v.min(100) as usize;
            let n = (w * v) / 100;
            Line::from(vec![
                Span::styled(full.repeat(n), st(p.primary)),
                Span::styled(empty.repeat(w - n), st(p.faint)),
                Span::styled(format!(" {v:>3}%"), st(p.soft)),
            ])
        }
        None if look.motion => {
            let seg = (w / 6).max(2);
            let span = w + seg;
            let at = (tick as usize) % span;
            let mut spans = Vec::new();
            for i in 0..w {
                let lit = i + seg > at && i <= at;
                spans.push(Span::styled(
                    if lit { full } else { empty },
                    st(if lit { p.primary } else { p.faint }),
                ));
            }
            Line::from(spans)
        }
        None => Line::from(vec![
            Span::styled(empty.repeat(w), st(p.faint)),
            Span::styled(" working", st(p.muted)),
        ]),
    }
}

/// Reading: the status line. Each fact as "label: value", in its tone's colour, joined by
/// a middle dot.
pub fn reading(look: &Look, facts: &[(&str, String, Tone)]) -> Line<'static> {
    let p = &look.pal;
    let sep = if look.ascii { " | " } else { " · " };
    let mut spans = vec![Span::raw(" ")];
    for (i, (label, value, t)) in facts.iter().enumerate() {
        if i > 0 {
            spans.push(Span::styled(sep, st(p.faint)));
        }
        if !label.is_empty() {
            spans.push(Span::styled(format!("{label}: "), st(p.muted)));
        }
        let mut s = st(tone(look, *t));
        if *t == Tone::Warn || *t == Tone::Bad {
            s = s.add_modifier(Modifier::BOLD);
        }
        spans.push(Span::styled(value.clone(), s));
    }
    Line::from(spans)
}

/// One row of a menu.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MenuItem {
    pub label: String,
    pub hint: String,
    /// why it can't run now ("needs the internet"); empty when it can
    pub blocked: String,
}

impl MenuItem {
    pub fn new(label: &str, hint: &str) -> MenuItem {
        MenuItem {
            label: label.into(),
            hint: hint.into(),
            blocked: String::new(),
        }
    }
}

/// The menu's lines: each item's label, its hint under it, dim; the selected one on a bar of
/// the primary colour. Hints wider than `width` wrap under themselves (hanging indent; 0: no
/// wrapping). Returns (lines, the selected item's first row) for scrolling.
pub fn menu_lines(
    look: &Look,
    items: &[MenuItem],
    selected: usize,
    focused: bool,
    width: u16,
) -> (Vec<Line<'static>>, usize) {
    let p = &look.pal;
    let mut lines = Vec::new();
    let mut at = 0;
    let mark = if look.ascii { ">" } else { "▌" };
    for (i, it) in items.iter().enumerate() {
        let sel = i == selected;
        if sel {
            at = lines.len();
        }
        let (bar, fg) = if sel && focused {
            (
                Style::new()
                    .bg(p.primary)
                    .fg(p.void)
                    .add_modifier(Modifier::BOLD),
                p.void,
            )
        } else if sel {
            (sel_surface(look).add_modifier(Modifier::BOLD), p.text)
        } else {
            (Style::new().fg(p.text), p.text)
        };
        let _ = fg;
        lines.push(Line::from(vec![
            Span::styled(if sel { mark } else { " " }, st(p.primary)),
            Span::styled(format!(" {}", it.label), bar),
        ]));
        let mut hint = it.hint.clone();
        if !it.blocked.is_empty() {
            hint = if hint.is_empty() {
                it.blocked.clone()
            } else {
                format!(
                    "{hint}{}{}",
                    if look.ascii { " - " } else { " · " },
                    it.blocked
                )
            };
        }
        if !hint.is_empty() {
            let hs = if sel && focused {
                Style::new().bg(p.primary).fg(p.void)
            } else if !it.blocked.is_empty() {
                st(p.warn)
            } else {
                st(p.muted)
            };
            if width == 0 {
                lines.push(Line::from(vec![
                    Span::raw(" "),
                    Span::styled(format!("   {hint}"), hs),
                ]));
            } else {
                lines.extend(wrap_hanging(&hint, width, "    ", "    ", hs));
            }
        }
    }
    (lines, at)
}

/// A menu in a Glass panel, scrolled so the selected item shows.
pub fn menu(
    f: &mut Frame,
    area: Rect,
    look: &Look,
    title: &str,
    items: &[MenuItem],
    selected: usize,
    focused: bool,
) {
    let block = glass(look, title, focused);
    let inner = block.inner(area);
    let (lines, at) = menu_lines(look, items, selected, focused, inner.width);
    let h = inner.height as usize;
    let scroll = (at + 2).saturating_sub(h);
    f.render_widget(
        Paragraph::new(lines)
            .block(block)
            .scroll((scroll as u16, 0)),
        area,
    );
}

/// A rectangle `w` by `h` (capped to the area) in the middle of `area`.
pub fn centered(area: Rect, w: u16, h: u16) -> Rect {
    let w = w.min(area.width);
    let h = h.min(area.height);
    Rect::new(
        area.x + (area.width - w) / 2,
        area.y + (area.height - h) / 2,
        w,
        h,
    )
}

/// The height a text needs at a width (wrapped by words, roughly).
pub fn text_height(text: &str, width: u16) -> u16 {
    let w = width.max(1) as usize;
    text.lines()
        .map(|l| l.chars().count().max(1).div_ceil(w))
        .sum::<usize>() as u16
}

fn buttons(look: &Look, labels: &[&str], selected: usize) -> Line<'static> {
    let p = &look.pal;
    let mut spans = Vec::new();
    for (i, l) in labels.iter().enumerate() {
        let s = if i == selected {
            Style::new()
                .bg(p.primary)
                .fg(p.void)
                .add_modifier(Modifier::BOLD)
        } else if look.mode == crate::term::Mode::Truecolor {
            Style::new().fg(p.text).bg(p.selection)
        } else {
            // the console: an unselected button is plain text, the selected one green
            st(p.text)
        };
        let l = if look.mode == crate::term::Mode::Truecolor {
            format!(" {l} ")
        } else {
            format!("[ {l} ]")
        };
        spans.push(Span::styled(l, s));
        spans.push(Span::raw("  "));
    }
    Line::from(spans)
}

/// Word-wrapped lines with a hanging indent: the first line starts with `first` (a marker
/// such as "▸ ", or spaces), every line after it with `rest`, so a paragraph's continuation
/// lines up under its text, never under the marker or at the panel's edge. Words are kept
/// whole unless one is longer than a line. Each line of `text` (a hard break) wraps on its
/// own, with `rest` before it.
pub fn wrap_hanging(
    text: &str,
    width: u16,
    first: &str,
    rest: &str,
    style: Style,
) -> Vec<Line<'static>> {
    let mut out = Vec::new();
    let w = width as usize;
    for (n, para) in text.split('\n').enumerate() {
        let mut prefix = if n == 0 { first } else { rest }.to_string();
        let room = |p: &str| w.saturating_sub(crate::layout::display_width(p)).max(1);
        let mut line = String::new();
        let push = |prefix: &mut String, line: &mut String, out: &mut Vec<Line<'static>>| {
            out.push(Line::from(vec![
                Span::styled(prefix.clone(), style),
                Span::styled(std::mem::take(line), style),
            ]));
            *prefix = rest.to_string();
        };
        if para.trim().is_empty() {
            out.push(Line::from(""));
            continue;
        }
        for word in para.split_whitespace() {
            let mut word = word.to_string();
            loop {
                let have = crate::layout::display_width(&line);
                let wlen = crate::layout::display_width(&word);
                let cap = room(&prefix);
                if have == 0 && wlen <= cap {
                    line.push_str(&word);
                    break;
                }
                if have > 0 && have + 1 + wlen <= cap {
                    line.push(' ');
                    line.push_str(&word);
                    break;
                }
                if have > 0 {
                    push(&mut prefix, &mut line, &mut out);
                    continue;
                }
                // a word longer than a whole line: split it
                let mut head = String::new();
                let mut hw = 0;
                let mut rest = String::new();
                for c in word.chars() {
                    let cw = unicode_width::UnicodeWidthChar::width(c).unwrap_or(0);
                    if !rest.is_empty() || hw + cw > cap {
                        rest.push(c);
                    } else {
                        head.push(c);
                        hw += cw;
                    }
                }
                if head.is_empty() {
                    // a glyph wider than the line: show it anyway rather than loop
                    let mut cs = rest.chars();
                    head.extend(cs.next());
                    rest = cs.collect();
                }
                word = rest;
                line = head;
                push(&mut prefix, &mut line, &mut out);
                if word.is_empty() {
                    break;
                }
            }
        }
        if !line.is_empty() {
            push(&mut prefix, &mut line, &mut out);
        }
    }
    out
}

/// A dialog's panel: the whole `area` (everything under it cleared), its frame lit, and the
/// space inside with a one-cell margin at the sides.
pub fn panel(f: &mut Frame, area: Rect, look: &Look, title: &str, border: Option<Color>) -> Rect {
    f.render_widget(Clear, area);
    let mut block = glass(look, title, true);
    if let Some(c) = border {
        block = block.border_style(st(c));
    }
    let inner = block.inner(area);
    f.render_widget(block, area);
    inner.inner(Margin::new(1, 0))
}

/// A dialog with a question, its explanation and buttons (the selected one lit), filling
/// `area`.
pub fn confirm(
    f: &mut Frame,
    area: Rect,
    look: &Look,
    question: &str,
    detail: &str,
    labels: &[&str],
    selected: usize,
) {
    let inner = panel(f, area, look, question, None);
    // a narrow screen (a phone): the buttons one above the other
    let stacked = crate::layout::Breakpoint::of_area(area) == crate::layout::Breakpoint::Tiny;
    let rows = if stacked { labels.len() as u16 } else { 1 };
    let [body, _, row] = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(1),
        Constraint::Length(rows),
    ])
    .areas(inner);
    f.render_widget(
        Paragraph::new(wrap_hanging(detail, body.width, "", "", st(look.pal.text))),
        body,
    );
    if stacked {
        let lines: Vec<Line> = labels
            .iter()
            .enumerate()
            .map(|(i, l)| buttons(look, &[l], usize::from(i != selected)))
            .collect();
        f.render_widget(Paragraph::new(lines), row);
    } else {
        f.render_widget(
            Paragraph::new(buttons(look, labels, selected)).alignment(Alignment::Center),
            row,
        );
    }
}

/// A text field on one line: what's typed on the selection surface, the cursor after it,
/// between brackets in `edge` (no box inside the dialog's box).
fn field_line(look: &Look, text: &str, edge: Color) -> Line<'static> {
    let (l, r) = if look.ascii {
        ("[ ", " ]")
    } else {
        ("▕ ", " ▏")
    };
    Line::from(vec![
        Span::styled(l, st(edge)),
        Span::styled(
            format!("{text}▏"),
            Style::new().fg(look.pal.white).bg(look.pal.selection),
        ),
        Span::styled(r, st(edge)),
    ])
}

/// Whether a typed confirmation matches what it asks for (exactly, spaces round it aside).
pub fn typed_ok(want: &str, typed: &str) -> bool {
    !want.is_empty() && typed.trim() == want
}

/// A confirmation by typing, filling `area`: for what can't be undone (erasing a disk), the
/// person types its name. The field shows what's typed; it lights up only when it matches.
pub fn typed_confirm(
    f: &mut Frame,
    area: Rect,
    look: &Look,
    question: &str,
    detail: &str,
    want: &str,
    typed: &str,
) {
    let p = &look.pal;
    let inner = panel(f, area, look, question, Some(p.danger));
    let [body, ask, field, keys] = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(1),
        Constraint::Length(1),
        Constraint::Length(1),
    ])
    .areas(inner);
    f.render_widget(
        Paragraph::new(wrap_hanging(detail, body.width, "", "", st(p.text))),
        body,
    );
    f.render_widget(
        Paragraph::new(Line::from(vec![
            Span::styled("Type ", st(p.text)),
            Span::styled(want.to_string(), st(p.warn).add_modifier(Modifier::BOLD)),
            Span::styled(" to go ahead.", st(p.text)),
        ])),
        ask,
    );
    let ok = typed_ok(want, typed);
    f.render_widget(
        Paragraph::new(field_line(look, typed, if ok { p.danger } else { p.dim })),
        field,
    );
    f.render_widget(
        Paragraph::new(Span::styled(
            if ok {
                "ENTER goes ahead · ESC cancels"
            } else {
                "ESC cancels"
            },
            st(p.muted),
        )),
        keys,
    );
}

/// A field to type into (hidden: dots for a passphrase), filling `area`.
pub fn input(
    f: &mut Frame,
    area: Rect,
    look: &Look,
    title: &str,
    prompt: &str,
    value: &str,
    hidden: bool,
) {
    let p = &look.pal;
    let inner = panel(f, area, look, title, None);
    let [body, field, keys] = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(1),
        Constraint::Length(1),
    ])
    .areas(inner);
    f.render_widget(
        Paragraph::new(wrap_hanging(prompt, body.width, "", "", st(p.text))),
        body,
    );
    let dot = if look.ascii { "*" } else { "•" };
    let shown = if hidden {
        dot.repeat(value.chars().count())
    } else {
        value.to_string()
    };
    f.render_widget(Paragraph::new(field_line(look, &shown, p.primary)), field);
    f.render_widget(
        Paragraph::new(Span::styled("ENTER · ESC cancels", st(p.muted))),
        keys,
    );
}

/// A log: the last lines that fit (or from `scroll` back), in a Glass panel.
pub fn log_view(
    f: &mut Frame,
    area: Rect,
    look: &Look,
    title: &str,
    lines: &[String],
    scroll_back: usize,
) {
    let block = glass(look, title, false);
    let inner = block.inner(area).inner(Margin::new(1, 0));
    f.render_widget(block, area);
    let h = inner.height as usize;
    let end = lines.len().saturating_sub(scroll_back);
    let start = end.saturating_sub(h);
    let text: Vec<Line> = lines[start..end]
        .iter()
        .map(|l| Line::from(Span::styled(l.clone(), st(look.pal.text))))
        .collect();
    f.render_widget(Paragraph::new(Text::from(text)), inner);
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::Terminal;
    use ratatui::backend::TestBackend;

    fn text(t: &Terminal<TestBackend>) -> String {
        let b = t.backend().buffer();
        let mut s = String::new();
        for y in 0..b.area.height {
            for x in 0..b.area.width {
                s.push_str(b[(x, y)].symbol());
            }
            s.push('\n');
        }
        s
    }

    #[test]
    fn sweep_states() {
        let mut look = Look::wick();
        let l = sweep(&look, Some(50), 0, 10);
        assert!(l.to_string().contains("50%"));
        look.motion = false;
        assert!(sweep(&look, None, 3, 10).to_string().contains("working"));
        look.motion = true;
        let a = sweep(&look, None, 1, 10).to_string();
        let b = sweep(&look, None, 5, 10).to_string();
        assert_ne!(a, b, "the segment travels");
    }

    #[test]
    fn meters_and_sparklines() {
        let mut look = Look::wick();
        let text = |v: &[Span]| v.iter().map(|s| s.content.to_string()).collect::<String>();
        let m = text(&meter(&look, 0.5, 10, Tone::Calm));
        assert_eq!(m.chars().count(), 10, "{m}");
        assert_eq!(m.chars().filter(|c| *c == '█').count(), 5, "{m}");
        assert_eq!(text(&meter(&look, 2.0, 4, Tone::Warn)), "████");
        assert_eq!(text(&meter(&look, f64::NAN, 3, Tone::Calm)), "░░░");
        let s = sparkline(&look, &[40.0, 60.0, 80.0], 30.0, 90.0, 8);
        assert_eq!(s.chars().count(), 3);
        assert!(s.starts_with('▂') && s.ends_with('▇'), "{s}");
        assert_eq!(sparkline(&look, &[1.0; 20], 0.0, 1.0, 5).chars().count(), 5);
        look.ascii = true;
        assert!(text(&meter(&look, 0.33, 9, Tone::Calm)).is_ascii());
        assert!(sparkline(&look, &[40.0, 90.0], 30.0, 90.0, 8).is_ascii());
    }

    #[test]
    fn a_focused_card_glows() {
        let look = Look::wick();
        let on = glow(&look, "", true);
        let off = glow(&look, "", false);
        assert_ne!(on, off);
        assert_eq!(off, glass(&look, "", false));
    }

    #[test]
    fn hanging_indent() {
        let lines = wrap_hanging(
            "It's named 10-gpu.conf.disabled, which looks switched off, but SDDM reads every file in that folder.",
            30,
            "▸ ",
            "  ",
            Style::new(),
        );
        let text: Vec<String> = lines.iter().map(|l| l.to_string()).collect();
        assert!(text[0].starts_with("▸ It's"), "{text:?}");
        for l in &text[1..] {
            assert!(l.starts_with("  ") && !l.starts_with("   "), "{text:?}");
        }
        assert!(text.iter().all(|l| l.chars().count() <= 30), "{text:?}");
        // whole words: no line ends inside one
        let words: Vec<&str> = text
            .iter()
            .flat_map(|l| l.trim_start_matches("▸ ").split_whitespace())
            .collect();
        assert!(words.contains(&"switched") && words.contains(&"folder."));
        let long = wrap_hanging("abcdefghijklmnopqrstuvwxyz", 10, "", "", Style::new());
        assert_eq!(long.len(), 3);
    }

    #[test]
    fn typed_confirmation() {
        assert!(typed_ok("sdb", " sdb "));
        assert!(!typed_ok("sdb", "sda"));
        assert!(!typed_ok("", ""));
    }

    #[test]
    fn menu_shows_hints_and_blocks() {
        let look = Look::wick();
        let mut items = vec![MenuItem::new("Check disks", "the drives' own health")];
        items.push(MenuItem {
            label: "Lab console".into(),
            hint: "your homelab".into(),
            blocked: "needs your local network".into(),
        });
        let (lines, at) = menu_lines(&look, &items, 1, true, 0);
        assert_eq!(at, 2);
        let all: String = lines.iter().map(|l| l.to_string() + "\n").collect();
        assert!(all.contains("Check disks") && all.contains("needs your local network"));
    }

    #[test]
    fn ascii_frames() {
        let mut look = Look::wick();
        look.ascii = true;
        let mut t = Terminal::new(TestBackend::new(30, 5)).unwrap();
        t.draw(|f| f.render_widget(glass(&look, "Repair", true), f.area()))
            .unwrap();
        let s = text(&t);
        assert!(s.starts_with("+ Repair -"), "{s}");
        assert!(s.is_ascii());
    }

    #[test]
    fn emitter_draws_the_title() {
        let look = Look::wick();
        let mut t = Terminal::new(TestBackend::new(80, 12)).unwrap();
        t.draw(|f| {
            emitter(
                f,
                f.area(),
                &look,
                "BROMIGOS // FIELD KIT",
                "repair, lab and tools",
            )
        })
        .unwrap();
        let s = text(&t);
        assert!(s.contains("BROMIGOS // FIELD KIT"), "{s}");
        assert!(s.contains('━'));
    }

    #[test]
    fn textual_theme_matches() {
        let v = crate::Pal::wick().textual_theme("driftglass");
        assert_eq!(v["primary"], "#39ff14");
        assert_eq!(v["background"], "#000500");
        assert_eq!(v["ansi_console"]["primary"], "ansi_green");
    }
}
