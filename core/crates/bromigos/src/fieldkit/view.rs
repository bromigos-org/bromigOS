//! Field Kit's screens, drawn (docs/fieldkit.md), after the operator's mock-up: the frame (a
//! top bar with the breadcrumb and the chips, a bottom bar with the keys and the highlighted
//! thing's hint), Home (this computer, what's on it, the seven sections), and each section
//! with what's there on the left and what to do on the right, badges on the actions. The
//! dialogs go over the space between the bars. DRIFTGLASS: Glass panels, one FLARE (Home's
//! orb, a hologram), Reading glows on the chips and badges, the highlighted tile glowing; the
//! console and ASCII looks fall back.

use ratatui::layout::Margin;

use super::*;

const LEFT_W: u16 = 48;

/// The frame: the top bar (2 rows), the body, the bottom bar (2 rows).
fn frame_parts(area: Rect) -> (Rect, Rect, Rect) {
    let [top, body, bottom] = Layout::vertical([
        Constraint::Length(2),
        Constraint::Min(4),
        Constraint::Length(2),
    ])
    .areas(area);
    (top, body, bottom)
}

/// A Glass panel with its title in capitals and its icon; returns the space inside.
fn boxed(f: &mut Frame, area: Rect, look: &Look, icon: Icon, title: &str, active: bool) -> Rect {
    let t = if title.is_empty() {
        String::new()
    } else {
        format!("{} {}", icon.of(look), title.to_uppercase())
    };
    let block = widgets::glass(look, &t, active);
    let inner = block.inner(area).inner(Margin::new(1, 0));
    f.render_widget(block, area);
    inner
}

/// A state dot and its words: ● fine, ▲ needs you, ✕ broken, ○ off (ASCII: + ! x -).
fn state_line(look: &Look, tone: Tone, name: &str, extra: &str) -> Line<'static> {
    let p = &look.pal;
    let (dot, c) = match (tone, look.ascii) {
        (Tone::Good, false) => ("●", p.primary),
        (Tone::Warn, false) => ("▲", p.warn),
        (Tone::Bad, false) => ("✕", p.danger),
        (Tone::Calm, false) => ("○", p.faint),
        (Tone::Good, true) => ("+", p.primary),
        (Tone::Warn, true) => ("!", p.warn),
        (Tone::Bad, true) => ("x", p.danger),
        (Tone::Calm, true) => ("-", p.faint),
    };
    Line::from(vec![
        Span::styled(format!("{dot} "), st(c)),
        Span::styled(name.to_string(), st(p.soft)),
        Span::styled(extra.to_string(), st(p.muted)),
    ])
}

fn icon_line(look: &Look, icon: Icon, text: &str, rest: &str, width: u16) -> Vec<Line<'static>> {
    let p = &look.pal;
    let mut l = widgets::wrap_hanging(
        &format!("{text}{rest}"),
        width,
        &format!("{} ", icon.of(look)),
        "  ",
        st(p.soft),
    );
    if let Some(first) = l.first_mut()
        && let Some(m) = first.spans.first_mut()
    {
        m.style = st(p.primary);
    }
    l
}

// ------------------------------------------------------------------ the bars

fn crumb(app: &App) -> String {
    let sep = if app.look.ascii { " > " } else { " › " };
    let mut c = vec!["Home".to_string()];
    match app.screen {
        Screen::Home => {}
        Screen::Section => c.push(SECTIONS[app.section].to_string()),
    }
    if let Some(Overlay::Findings { title, .. }) = app.overlays.last() {
        c.push(title.clone());
    }
    c.join(sep)
}

fn top_bar(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let p = &look.pal;
    let [row, rule] = Layout::vertical([Constraint::Length(1), Constraint::Length(1)]).areas(area);
    let chips = chips(app);
    let title = if app.server_home() {
        format!(
            "BROMIGOS // SERVER {}",
            s(&app.server, "hostname").to_uppercase()
        )
    } else {
        "BROMIGOS // FIELD KIT".to_string()
    };
    let mark = widgets::mark(look);
    if Breakpoint::of_area(area) == Breakpoint::Tiny {
        // a phone: the edition's short name, where you are, the chips as icons only
        let here = crumb(app).rsplit([' ']).next().unwrap_or("").to_string();
        let left = vec![
            Span::styled(
                format!(" {mark} FIELD KIT"),
                st(p.primary).add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                if app.screen == Screen::Home {
                    String::new()
                } else {
                    format!("  {here}")
                },
                st(p.muted),
            ),
        ];
        let icons: Vec<Span> = chips
            .iter()
            .map(|(icon, _, tone)| {
                let c = match tone {
                    Tone::Good => p.primary,
                    Tone::Warn => p.warn,
                    Tone::Bad => p.danger,
                    Tone::Calm => p.muted,
                };
                Span::styled(format!("{} ", icon.of(look)), st(c))
            })
            .collect();
        let iw = (icons.len() * 2) as u16 + 1;
        let [l, r] = Layout::horizontal([
            Constraint::Min(1),
            Constraint::Length(iw.min(row.width / 2)),
        ])
        .areas(row);
        f.render_widget(Paragraph::new(Line::from(left)), l);
        f.render_widget(Paragraph::new(Line::from(icons)), r);
        let ch = if look.ascii { "=" } else { "━" };
        f.render_widget(
            Paragraph::new(Span::styled(ch.repeat(rule.width as usize), st(p.dim))),
            rule,
        );
        return;
    }
    let mut left = vec![Span::styled(
        format!(" {mark} {title}"),
        st(p.primary).add_modifier(Modifier::BOLD),
    )];
    let version = s(&app.overview, "version");
    if !version.is_empty() {
        left.push(Span::styled(format!("  {version}"), st(p.faint)));
    }
    left.push(Span::styled(format!("   {}", crumb(app)), st(p.muted)));
    // the chips that fit beside the title and breadcrumb: the stick's, then the clock, go first
    let lw: u16 = left
        .iter()
        .map(|s| s.content.chars().count() as u16)
        .sum::<u16>()
        + 2;
    let mut chips = chips;
    for drop in [Icon::Usb, Icon::Clock, Icon::Key] {
        if lw + chips_width(look, &chips) < row.width {
            break;
        }
        chips.retain(|c| c.0 != drop);
    }
    let cw = (chips_width(look, &chips) + 1).min(row.width.saturating_sub(lw));
    let [l, r] = Layout::horizontal([Constraint::Min(10), Constraint::Length(cw)]).areas(row);
    f.render_widget(Paragraph::new(Line::from(left)), l);
    f.render_widget(Paragraph::new(Line::from(chip_spans(look, &chips))), r);
    let ch = if look.ascii { "=" } else { "━" };
    f.render_widget(
        Paragraph::new(Span::styled(ch.repeat(rule.width as usize), st(p.dim))),
        rule,
    );
}

/// The keys this screen takes, and what the highlighted thing does (its hint).
fn bottom_bar(f: &mut Frame, area: Rect, app: &App, keys: &[(&str, &str)], hint: &str) {
    let look = &app.look;
    let p = &look.pal;
    let [rule, row] = Layout::vertical([Constraint::Length(1), Constraint::Length(1)]).areas(area);
    let ch = if look.ascii { "-" } else { "─" };
    f.render_widget(
        Paragraph::new(Span::styled(ch.repeat(rule.width as usize), st(p.dim))),
        rule,
    );
    let keys: &[(&str, &str)] = if Breakpoint::of_area(area) == Breakpoint::Tiny {
        &[("?", "help")]
    } else {
        keys
    };
    let mut spans = vec![Span::raw(" ")];
    for (k, what) in keys {
        spans.push(Span::styled(k.to_string(), st(p.soft)));
        spans.push(Span::styled(format!(" {what}  "), st(p.muted)));
    }
    let kw: u16 = spans.iter().map(|s| s.content.chars().count() as u16).sum();
    let tip = if hint.is_empty() {
        String::new()
    } else {
        format!("{} {hint} ", Icon::Info.of(look))
    };
    let room = row.width.saturating_sub(kw + 1) as usize;
    let ell = if look.ascii { "." } else { "…" };
    // too long: the description gives way; a shortcut at its end always stays readable
    let tip: String = if tip.chars().count() > room {
        let (head, tail) = match tip.rfind("shortcut ") {
            Some(at) => (tip[..at].to_string(), tip[at..].to_string()),
            None => (tip.clone(), String::new()),
        };
        let keep = room.saturating_sub(tail.chars().count() + 4);
        let cut: String = head.chars().take(keep).collect();
        let sep = if tail.is_empty() { "" } else { dot(look) };
        format!(
            "{}{ell}{sep}{tail}",
            cut.trim_end().trim_end_matches(['·', '-']).trim_end()
        )
    } else {
        tip
    };
    let tw = tip.chars().count() as u16;
    let [l, r] = Layout::horizontal([Constraint::Min(1), Constraint::Length(tw)]).areas(row);
    f.render_widget(Paragraph::new(Line::from(spans)), l);
    f.render_widget(Paragraph::new(Span::styled(tip, st(p.accent))), r);
}

fn keys_for(app: &App) -> Vec<(&'static str, &'static str)> {
    let a = app.look.ascii;
    let mv = if a { "arrows" } else { "↑↓←→" };
    match app.screen {
        Screen::Home => {
            let mut k = vec![(mv, "move"), ("Enter", "open")];
            if !app.suggestions().is_empty() {
                k.push(("f", "suggested fix"));
            }
            k.push(("?", "keys and help"));
            k.push(("q", "quit"));
            k
        }
        _ => vec![
            (mv, "move"),
            ("Enter", "open"),
            ("Esc", "back"),
            ("?", "keys and help"),
        ],
    }
}

// ------------------------------------------------------------------ Home

/// The Home screen's parts, for a screen this size: drawing and mouse clicks share it. Everything
/// is anchored under the top bar, in this order: the orb, this computer and what's on it, the
/// lab, the seven sections, the suggestion, the recent repairs. When rows are short, the sections
/// come first, then the suggestion, the lab and the recent repairs, then the boxes, then the orb;
/// rows still left make the tiles bigger.
pub struct HomeLayout {
    pub head: Rect,
    pub computer: Rect,
    pub found: Rect,
    pub lab: Option<Rect>,
    pub suggest: Option<Rect>,
    pub recent: Option<Rect>,
    pub tiles: [Rect; 7],
    /// a tile's height: 5 or more (an icon line, the name, its line about it on the rows
    /// left), 4 (name and a line about it), 3 (the name), 2 (a list row and its line about it,
    /// on a tiny screen) or 1 (a list row)
    pub tile_h: u16,
    pub body: Rect,
    pub top: Rect,
    pub bottom: Rect,
}

/// The orb's size in the head for a head this tall: braille (w, h) cells where it shows,
/// else the plain ring; (0, 0) for none (the wordmark instead).
fn head_orb(look: &Look, rows: u16) -> (usize, usize) {
    match (bromigos_tui::orb::fine(look), rows) {
        (true, 11..) => (22, 11),
        (true, 5..) => (10, 5),
        (true, 3..) => (6, 3),
        (false, 5..) => bromigos_tui::orb::PLAIN,
        _ => (0, 0),
    }
}

/// The orb's time: still under reduced motion.
fn orb_t(app: &App) -> f64 {
    if app.look.motion {
        app.tick as f64 * 0.12
    } else {
        0.0
    }
}

/// The lab strip's words, when Field Kit knows a lab (its homelab.toml).
fn lab_text(app: &App) -> Option<String> {
    let lab = &app.overview["lab"];
    if !lab.is_object() {
        return None;
    }
    let n = lab["sources"].as_u64().unwrap_or(0);
    let kinds: Vec<&str> = lab["kinds"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|k| k.as_str())
        .collect();
    let mut t = format!("Lab: {}", s(lab, "name"));
    if n > 0 {
        t.push_str(&format!(
            "{}{n} service{}",
            dot(&app.look),
            if n == 1 { "" } else { "s" }
        ));
    }
    if !kinds.is_empty() {
        t.push_str(&format!(" ({})", kinds.join(", ")));
    }
    let net = app.overview["network"]["kind"].as_str().unwrap_or("none");
    t.push_str(&format!(
        "{}{}",
        dot(&app.look),
        if net == "none" {
            "no network link here yet"
        } else {
            "network link up"
        }
    ));
    Some(t)
}

/// The recent row's words: Field Kit's last repairs on the opened install.
fn recent_text(app: &App) -> Option<String> {
    let v: Vec<String> = app.overview["recent"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|r| format!("{} {}", s(r, "what"), s(r, "when")))
        .collect();
    (!v.is_empty()).then(|| format!("Recent: {}", v.join(dot(&app.look))))
}

/// A section's line about it in `width` columns, the same kind for every section on a screen:
/// the whole lines when all of them fit, else the short ones; never cut mid-word (None: they
/// don't fit).
fn tile_about(name: &str, server_home: bool, width: usize) -> Option<&'static str> {
    let fits = |f: fn(&str, bool) -> &'static str| {
        SECTIONS
            .iter()
            .all(|n| f(n, server_home).chars().count() <= width)
    };
    if fits(|n, h| section_tile(n, h).1) {
        Some(section_tile(name, server_home).1)
    } else if fits(section_tagline) {
        Some(section_tagline(name, server_home))
    } else {
        None
    }
}

/// The same on up to `rows` rows: the whole lines, wrapped by words, when every section's fits
/// in them; else tile_about's one line.
fn tile_about_rows(name: &str, server_home: bool, width: usize, rows: usize) -> Vec<String> {
    let long = |n: &str| bromigos_tui::layout::wrap(section_tile(n, server_home).1, width);
    if rows > 1 && SECTIONS.iter().all(|n| long(n).len() <= rows) {
        return long(name);
    }
    tile_about(name, server_home, width)
        .map(|t| vec![t.to_string()])
        .unwrap_or_default()
}

pub fn home_layout(app: &App, area: Rect) -> HomeLayout {
    let (top, body, bottom) = frame_parts(area);
    let inner = body.inner(Margin::new(1, 0));
    let bp = Breakpoint::of_area(area);
    let cols = home_cols_for(area.width);
    let n = SECTIONS.len();
    let rows = n.div_ceil(cols) as u16;
    let lab_h = u16::from(lab_text(app).is_some());
    let sugg_h = u16::from(!app.suggestions().is_empty());
    let recent_h = u16::from(recent_text(app).is_some());
    // the sections first: tiles with a line about each when there's room, else their names; on
    // a tiny screen a list, with its line about each under it when there's room
    let mut room = inner.height;
    let mut tile_h: u16 = if cols == 1 {
        let wide = inner.width.saturating_sub(4) as usize;
        let fits_one = SECTIONS.iter().all(|nm| {
            section_tile(nm, app.server_home()).1.chars().count() + nm.chars().count() + 6
                <= inner.width as usize
        });
        let fits_two = SECTIONS
            .iter()
            .all(|nm| tile_about(nm, app.server_home(), wide).is_some());
        if !fits_one && fits_two && room >= 2 * n as u16 + sugg_h + lab_h {
            2
        } else {
            1
        }
    } else if room >= 4 * rows + 6 {
        4
    } else {
        3
    };
    room = room.saturating_sub(tile_h * rows);
    // then the suggestion, the lab and the recent repairs: a line each, a blank line before them
    let mut take = |h: u16| {
        if h > 0 && room > h {
            room -= h + 1;
            h
        } else {
            0
        }
    };
    let sugg_h = take(sugg_h);
    let lab_h = take(lab_h);
    let recent_h = take(recent_h);
    // this computer and what's on it: side by side on wide screens, else stacked; each box
    // needs 3 rows (its border and a line), and grows with what it has to say
    let side = bp.side_by_side();
    let (cw, fw) = if side {
        let [c, f] = Layout::horizontal([Constraint::Percentage(45), Constraint::Percentage(55)])
            .areas(Rect::new(0, 0, inner.width, 1));
        (c.width, f.width)
    } else {
        (inner.width, inner.width)
    };
    let c_lines = computer_view(app, cw.saturating_sub(4)).len() as u16;
    let f_lines = found_view(app, fw.saturating_sub(4)).len() as u16;
    let (mut c_h, mut f_h) = if side {
        let h = (c_lines.max(f_lines) + 2).clamp(3, 14);
        (h, h)
    } else {
        ((c_lines + 2).clamp(3, 10), (f_lines + 2).clamp(3, 7))
    };
    let info_h = if side {
        if room > c_h {
            c_h
        } else if room > 3 {
            room - 1
        } else {
            0
        }
    } else if room > c_h + f_h {
        c_h + f_h
    } else if room > 6 {
        room - 1
    } else {
        0
    };
    if !side && info_h < c_h + f_h {
        // short of rows: the two boxes share what there is
        c_h = info_h / 2;
        f_h = info_h - c_h;
    }
    room = room.saturating_sub(info_h + u16::from(info_h > 0));
    // then the orb and the edition's name, when there's room for them
    let fine = bromigos_tui::orb::fine(&app.look);
    let head_h = if bp == Breakpoint::Tiny {
        0
    } else if fine && area.height >= 44 && room > 12 {
        11
    } else if room > 6 {
        5
    } else if room > 3 {
        3
    } else {
        0
    };
    room = room.saturating_sub(head_h + u16::from(head_h > 0));
    // last, rows still left make the tiles bigger: an icon line over the name, then the whole
    // line about each section on up to four rows
    if cols > 1 && tile_h == 4 {
        let tw = (inner.width / cols as u16).saturating_sub(4) as usize;
        let long = SECTIONS
            .iter()
            .map(|nm| bromigos_tui::layout::wrap(section_tile(nm, app.server_home()).1, tw).len())
            .max()
            .unwrap_or(0) as u16;
        for extra in [long, 1] {
            if (1..=4).contains(&extra) && extra * rows <= room {
                tile_h += extra;
                break;
            }
        }
    }
    let tiles_h = tile_h * rows;
    let gap = |h: u16| u16::from(h > 0);
    let [head, _, info, _, lab, _, grid, _, sugg, _, recent] = Layout::vertical([
        Constraint::Length(head_h),
        Constraint::Length(gap(head_h)),
        Constraint::Length(info_h),
        Constraint::Length(gap(info_h)),
        Constraint::Length(lab_h),
        Constraint::Length(gap(lab_h)),
        Constraint::Length(tiles_h),
        Constraint::Length(gap(sugg_h)),
        Constraint::Length(sugg_h),
        Constraint::Length(gap(recent_h)),
        Constraint::Length(recent_h),
    ])
    .flex(ratatui::layout::Flex::Start)
    .areas(inner);
    let (computer, found) = if info.height < 3 {
        (Rect::default(), Rect::default())
    } else if side {
        let [c, f] = Layout::horizontal([Constraint::Percentage(45), Constraint::Percentage(55)])
            .areas(info);
        (c, f)
    } else {
        let [c, f] =
            Layout::vertical([Constraint::Length(c_h), Constraint::Length(f_h)]).areas(info);
        (c, f)
    };
    let cells = bromigos_tui::layout::grid(grid, n, cols, tile_h, 0, 0, 0);
    let mut tiles = [Rect::default(); 7];
    for (i, r) in cells.into_iter().enumerate().take(7) {
        tiles[i] = r;
    }
    HomeLayout {
        head,
        computer,
        found,
        lab: (lab_h > 0).then_some(lab),
        suggest: (sugg_h > 0).then_some(sugg),
        recent: (recent_h > 0).then_some(recent),
        tiles,
        tile_h,
        body,
        top,
        bottom,
    }
}

/// Home's FLARE: the orb (a hologram, the same as VECTOR's) beside the edition's name; the
/// wordmark where a head is too short for the plain ring.
fn draw_head(f: &mut Frame, app: &App, head: Rect) {
    let look = &app.look;
    let p = &look.pal;
    let size = head_orb(look, head.height);
    let art: Vec<Line> = if size.1 > 0 {
        bromigos_tui::orb::lines(look, orb_t(app), size)
    } else {
        let rows: Vec<&str> = if look.ascii {
            bromigos_tui::emblem::WORDMARK_ASCII.to_vec()
        } else {
            bromigos_tui::emblem::WORDMARK.to_vec()
        };
        rows.iter()
            .map(|r| Line::from(Span::styled(r.to_string(), st(p.primary))))
            .collect()
    };
    let mut aw = art.iter().map(|l| l.width()).max().unwrap_or(0) as u16 + 3;
    if aw + 30 > head.width {
        aw = 0; // too narrow for the art beside the words: the words alone
    }
    let [a, w] = Layout::horizontal([Constraint::Length(aw), Constraint::Min(10)]).areas(head);
    let art: Vec<Line> = art
        .into_iter()
        .map(|mut l| {
            l.spans.insert(0, Span::raw(" "));
            l
        })
        .collect();
    f.render_widget(Paragraph::new(art), a);
    let mid = w.height.saturating_sub(3) / 2;
    let mut words: Vec<Line> = (0..mid).map(|_| Line::from("")).collect();
    words.push(Line::from(Span::styled(
        "FIELD KIT",
        st(p.primary).add_modifier(Modifier::BOLD),
    )));
    words.push(Line::from(Span::styled(
        "bromigOS without the desktop",
        st(p.soft),
    )));
    words.push(Line::from(Span::styled(
        format!("repair{d}lab{d}server{d}works offline", d = dot(look)),
        st(p.muted),
    )));
    f.render_widget(Paragraph::new(words), w);
}

/// A Home tile: Glass, the highlighted one glowing. Five rows and more: an icon line, the name,
/// its line about it; four: the icon and name, its line; three: the icon and name.
fn draw_tile(f: &mut Frame, app: &App, r: Rect, i: usize, tile_h: u16) {
    let look = &app.look;
    let p = &look.pal;
    let sel = app.home == HomeSel::Tile(i);
    let name = SECTIONS[i];
    let (icon, _) = section_tile(name, app.server_home());
    let style = if sel {
        widgets::sel_text(look)
    } else {
        st(p.soft)
    };
    // the name bold, except selected on the console (bold black shows as grey there)
    let name_style = if sel && look.mode == bromigos_tui::Mode::Ansi16 {
        style
    } else {
        style.add_modifier(Modifier::BOLD)
    };
    let block = widgets::glow(look, "", sel);
    let inner = block.inner(r).inner(Margin::new(1, 0));
    f.render_widget(block, r);
    let w = inner.width as usize;
    if tile_h < 5 {
        let mut lines = vec![Line::from(vec![
            Span::styled(format!("{}  ", icon.of(look)), style),
            Span::styled(name.to_string(), name_style),
        ])];
        if tile_h >= 4
            && let Some(t) = tile_about(name, app.server_home(), w)
        {
            lines.push(Line::from(Span::styled(
                t.to_string(),
                if sel { style } else { st(p.muted) },
            )));
        }
        f.render_widget(Paragraph::new(lines), inner);
        return;
    }
    // the icon between two short rules, the name, then its line about it: centred
    let rule = if look.ascii { "-" } else { "─" };
    let side = (w.saturating_sub(3) / 2).min(6);
    let edge = if sel && look.mode == bromigos_tui::Mode::Truecolor {
        st(p.primary)
    } else if sel {
        style
    } else {
        st(p.dim)
    };
    let icon_style = if sel { style } else { st(p.primary) };
    let mut lines = vec![
        Line::from(vec![
            Span::styled(format!("{} ", rule.repeat(side)), edge),
            Span::styled(icon.of(look).to_string(), icon_style),
            Span::styled(format!(" {}", rule.repeat(side)), edge),
        ]),
        Line::from(Span::styled(name.to_string(), name_style)),
    ];
    let about = tile_about_rows(
        name,
        app.server_home(),
        w,
        tile_h.saturating_sub(4).max(1) as usize,
    );
    for t in about {
        lines.push(Line::from(Span::styled(
            t,
            if sel { style } else { st(p.muted) },
        )));
    }
    f.render_widget(
        Paragraph::new(lines).alignment(ratatui::layout::Alignment::Center),
        inner,
    );
}

fn draw_home(f: &mut Frame, app: &App, area: Rect) -> Rect {
    let look = &app.look;
    let p = &look.pal;
    let l = home_layout(app, area);
    top_bar(f, l.top, app);
    // the screen's one FLARE: the orb beside the edition's name
    if l.head.height > 0 {
        draw_head(f, app, l.head);
    }
    // this computer, and what's on its drives (when there's room for them)
    if l.computer.height >= 3 {
        let inner = boxed(f, l.computer, look, Icon::Computer, "This computer", false);
        bromigos_tui::layout::scroll_view(f, inner, look, computer_view(app, inner.width), 0);
    }
    if l.found.height >= 3 {
        let inner = boxed(
            f,
            l.found,
            look,
            Icon::Disk,
            "Found on this computer",
            false,
        );
        bromigos_tui::layout::scroll_view(f, inner, look, found_view(app, inner.width), 0);
    }
    // the lab Field Kit knows (from the stick's folder), on one line
    if let (Some(r), Some(text)) = (l.lab, lab_text(app)) {
        let words =
            bromigos_tui::layout::truncate(&text, (r.width as usize).saturating_sub(3), look.ascii);
        f.render_widget(
            Paragraph::new(Line::from(vec![
                Span::styled(format!(" {} ", Icon::Lab.of(look)), st(p.primary)),
                Span::styled(words, st(p.soft)),
            ])),
            r,
        );
    }
    // the seven sections: tiles, or on a tiny screen a list
    let list = home_cols_for(area.width) == 1;
    for (i, r) in l.tiles.iter().enumerate() {
        if r.height == 0 {
            continue;
        }
        if !list {
            draw_tile(f, app, *r, i, l.tile_h);
            continue;
        }
        let sel = app.home == HomeSel::Tile(i);
        let name = SECTIONS[i];
        let (icon, about) = section_tile(name, app.server_home());
        let style = if sel {
            widgets::sel_text(look)
        } else {
            st(p.soft)
        };
        let mark = if look.ascii { ">" } else { "▌" };
        let line = format!("{}  {name}", icon.of(look));
        let mut first = vec![
            Span::styled(if sel { mark } else { " " }, st(p.primary)),
            Span::styled(line.clone(), style),
        ];
        let one = (r.width as usize).saturating_sub(line.chars().count() + 3);
        let mut lines = Vec::new();
        if l.tile_h == 1 {
            // the lines about them only when all of them fit; the hint bar has them anyway
            let all = SECTIONS.iter().all(|nm| {
                section_tile(nm, app.server_home()).1.chars().count() + nm.chars().count() + 6
                    <= r.width as usize
            });
            if all && about.chars().count() <= one {
                first.push(Span::styled(format!("  {about}"), st(p.muted)));
            }
            lines.push(Line::from(first));
        } else {
            lines.push(Line::from(first));
            if let Some(t) = tile_about(
                name,
                app.server_home(),
                (r.width as usize).saturating_sub(4),
            ) {
                lines.push(Line::from(vec![
                    Span::styled(if sel { mark } else { " " }, st(p.primary)),
                    Span::styled(format!("   {t}"), st(p.faint)),
                ]));
            }
        }
        f.render_widget(Paragraph::new(lines), *r);
    }
    // a suggestion, only when the engine found one
    if let (Some(r), Some((text, _))) = (l.suggest, app.suggestions().first()) {
        let sel = matches!(app.home, HomeSel::Suggestion(_));
        let style = if sel {
            Style::new()
                .bg(p.warn)
                .fg(p.void)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::new().fg(p.warn)
        };
        f.render_widget(
            Paragraph::new(Line::from(vec![
                Span::styled(format!(" {} Suggested: ", Icon::Alert.of(look)), style),
                Span::styled(format!("{text} "), if sel { style } else { st(p.text) }),
                Span::styled("  (press f)", st(p.faint)),
            ])),
            r,
        );
    }
    // the last repairs on the opened install, each with its backup
    if let (Some(r), Some(text)) = (l.recent, recent_text(app)) {
        let words =
            bromigos_tui::layout::truncate(&text, (r.width as usize).saturating_sub(3), look.ascii);
        f.render_widget(
            Paragraph::new(Line::from(vec![
                Span::styled(format!(" {} ", Icon::Update.of(look)), st(p.muted)),
                Span::styled(words, st(p.muted)),
            ])),
            r,
        );
    }
    // the tile under the pointer, else the highlighted one: what it is, and its shortcut
    let tile = app.hover.or(match app.home {
        HomeSel::Tile(t) => Some(t),
        HomeSel::Suggestion(_) => None,
    });
    let hint = match tile {
        Some(t) => format!(
            "{}{}shortcut {}",
            section_tile(SECTIONS[t], app.server_home()).1,
            dot(look),
            SHORTCUTS[t].to_ascii_uppercase()
        ),
        None => "Enter does the suggested fix (or press f)".to_string(),
    };
    bottom_bar(f, l.bottom, app, &keys_for(app), &hint);
    l.body
}

// ------------------------------------------------------------------ the sections

/// A section's screen: its left panels (what's there) and its actions (what to do).
pub struct SectionLayout {
    pub left: Option<Rect>,
    /// Narrow and Tiny: the left side's gist on one line, above the actions
    pub summary: Option<Rect>,
    pub list: Rect,
    pub body: Rect,
    pub top: Rect,
    pub bottom: Rect,
}

pub fn section_layout(app: &App, area: Rect) -> SectionLayout {
    let (top, body, bottom) = frame_parts(area);
    let inner = body.inner(Margin::new(1, 0));
    let name = SECTIONS[app.section];
    let bp = Breakpoint::of_area(area);
    if name == "Tools" || name == "Install" {
        return SectionLayout {
            left: None,
            summary: None,
            list: inner,
            body,
            top,
            bottom,
        };
    }
    if !bp.side_by_side() {
        let [summary, _, list] = Layout::vertical([
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Min(3),
        ])
        .areas(inner);
        return SectionLayout {
            left: None,
            summary: Some(summary),
            list,
            body,
            top,
            bottom,
        };
    }
    let left_w = if bp == Breakpoint::Wide { LEFT_W } else { 38 };
    let (left, list) = bromigos_tui::layout::columns(inner, left_w, 2);
    SectionLayout {
        left: Some(left),
        summary: None,
        list,
        body,
        top,
        bottom,
    }
}

/// The left side's gist, for a screen too narrow for it (one line).
fn summary_text(app: &App) -> String {
    let d = dot(&app.look);
    match SECTIONS[app.section] {
        "Repair" => {
            let install = match app.target() {
                Some(t) if s(t, "root") != "/" => {
                    format!("{} unlocked, at {}", s(t, "hostname"), s(t, "root"))
                }
                Some(t) => format!("this system, {}", s(t, "hostname")),
                None => "install not mounted".to_string(),
            };
            let disks: Vec<Value> = app.disks["disks"].as_array().cloned().unwrap_or_default();
            let failing = disks
                .iter()
                .filter(|x| x["failing"].as_bool().unwrap_or(false))
                .count();
            if disks.is_empty() {
                install
            } else if failing > 0 {
                format!("{install}{d}{failing} disk(s) failing")
            } else {
                format!("{install}{d}{} disk(s), none failing", disks.len())
            }
        }
        "Lab" => {
            if !app.lab.is_object() {
                if app.net() == "none" {
                    "no network: the lab is over your local network".into()
                } else {
                    "asking the lab…".into()
                }
            } else {
                let cards = app.lab["cards"].as_array().cloned().unwrap_or_default();
                let bad = cards
                    .iter()
                    .filter(|c| {
                        matches!(
                            c["state"].as_str(),
                            Some("warn" | "error" | "unreachable" | "critical")
                        )
                    })
                    .count();
                format!("{} parts{d}{bad} need you", cards.len())
            }
        }
        "Server" if app.server_home() => format!(
            "{}{d}SSH {}",
            s(&app.server, "hostname"),
            if app.server["ssh"].as_bool().unwrap_or(false) {
                "on"
            } else {
                "off"
            }
        ),
        "Server" => "bromigOS Server: no desktop, for servers and lab machines".into(),
        _ => {
            let remote = s(&app.status, "remote_words");
            if remote.is_empty() {
                "a command line; tldr NAME for examples".into()
            } else {
                remote
            }
        }
    }
}

/// Whether the actions list has room for a blank row between its items.
fn gaps(app: &App, list: Rect) -> bool {
    (app.items().len() * 2) as u16 <= list.height.saturating_sub(2)
}

/// The item under a click on a section's screen, if any.
pub fn item_at(app: &App, size: Rect, at: ratatui::layout::Position) -> Option<usize> {
    let l = section_layout(app, size);
    match SECTIONS[app.section] {
        "Tools" => tool_cards(app, l.list).iter().position(|r| r.contains(at)),
        "Install" => {
            let (cards, rows, _) = install_parts(app, l.list);
            if let Some(i) = cards.iter().position(|r| r.contains(at)) {
                return Some(i);
            }
            rows.iter()
                .position(|r| r.contains(at))
                .map(|i| i + cards.len())
        }
        _ => {
            if !l.list.contains(at) || at.y <= l.list.y {
                return None;
            }
            let y = (at.y - l.list.y - 1) as usize;
            let i = if gaps(app, l.list) {
                y.is_multiple_of(2).then_some(y / 2)?
            } else {
                y
            };
            (i < app.items().len()).then_some(i)
        }
    }
}

/// The actions: an icon, the label, a badge on the right; the chosen one marked and bright.
fn actions(f: &mut Frame, area: Rect, app: &App, title: &str, icon: Icon) {
    let look = &app.look;
    let p = &look.pal;
    let spark = app.spark_until.is_some_and(|t| Instant::now() < t);
    let t = format!("{} {}", icon.of(look), title.to_uppercase());
    let block = widgets::spark(look, widgets::glass(look, &t, true), spark);
    let inner = block.inner(area).inner(Margin::new(1, 0));
    f.render_widget(block, area);
    let items = app.items();
    let gap = gaps(app, area);
    let mut lines = Vec::new();
    let mark = if look.ascii { ">" } else { "▌" };
    let mut at = 0;
    for (i, it) in items.iter().enumerate() {
        let sel = i == app.sel;
        if sel {
            at = lines.len();
        }
        let style = if sel {
            st(p.primary).add_modifier(Modifier::BOLD)
        } else {
            st(p.soft)
        };
        let mut badge = app.badge(it);
        // narrow screens: the label comes first. Calm badges go, warnings get their short form,
        // and if even that crowds the label, just the alert mark
        if !Breakpoint::of(f.area().width).side_by_side() {
            badge = badge.and_then(|(b, t)| match t {
                Tone::Calm | Tone::Good => None,
                _ => Some((short_badge(&b), t)),
            });
            if let Some((b, t)) = &badge
                && it.label.chars().count() + b.chars().count() + 8 > inner.width as usize
            {
                badge = Some((Icon::Alert.of(look).to_string(), *t));
            }
        }
        // when the label and its badge don't both fit, a calm badge goes; a warning stays
        if let Some((b, tone)) = &badge
            && it.label.chars().count() + b.chars().count() + 7 > inner.width as usize
            && matches!(tone, Tone::Calm | Tone::Good)
        {
            badge = None;
        }
        // a long label gives way to its badge: cut short, never pushing the badge off the panel
        let room = inner.width.saturating_sub(
            4 + badge
                .as_ref()
                .map(|(b, _)| b.chars().count() as u16 + 3)
                .unwrap_or(0),
        ) as usize;
        let label = if it.label.chars().count() > room {
            let cut: String = it.label.chars().take(room.saturating_sub(1)).collect();
            format!("{}{}", cut.trim_end(), if look.ascii { "." } else { "…" })
        } else {
            it.label.to_string()
        };
        let mut spans = vec![
            Span::styled(if sel { mark } else { " " }, st(p.primary)),
            Span::styled(format!("{}  ", act_icon(&it.act).of(look)), style),
            Span::styled(label, style),
        ];
        if let Some((b, tone)) = badge {
            let used: u16 = spans.iter().map(|s| s.content.chars().count() as u16).sum();
            let bw = b.chars().count() as u16 + 2;
            let pad = inner.width.saturating_sub(used + bw);
            spans.push(Span::raw(" ".repeat(pad as usize)));
            spans.push(match tone {
                Tone::Warn => Span::styled(
                    format!(" {b} "),
                    Style::new().fg(p.warn).bg(warn_surface(look)),
                ),
                Tone::Bad => Span::styled(format!(" {b} "), st(p.danger)),
                Tone::Good => Span::styled(format!(" {b} "), st(p.primary)),
                Tone::Calm => Span::styled(format!(" {b} "), st(p.muted)),
            });
        }
        lines.push(Line::from(spans));
        if gap && i + 1 < items.len() {
            lines.push(Line::from(""));
        }
    }
    let scroll = (at + 2).saturating_sub(inner.height as usize);
    bromigos_tui::layout::scroll_view(f, inner, look, lines, scroll);
}

/// A badge's short form, for narrow screens.
fn short_badge(b: &str) -> String {
    match b {
        "mount your install first" => "mount first".into(),
        "needs your local network" => "no network".into(),
        "needs the internet" | "needs internet" => "offline".into(),
        _ => b.split_whitespace().take(2).collect::<Vec<_>>().join(" "),
    }
}

fn warn_surface(look: &Look) -> ratatui::style::Color {
    if look.mode == bromigos_tui::Mode::Truecolor {
        ratatui::style::Color::Rgb(0x4a, 0x3a, 0x0a)
    } else {
        look.pal.void
    }
}

/// The left side: what's there, for each section.
fn left_panels(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let p = &look.pal;
    let w = area.width.saturating_sub(4);
    let mut panels: Vec<(Icon, &str, Vec<Line<'static>>)> = Vec::new();
    match SECTIONS[app.section] {
        "Repair" => {
            let mut l = Vec::new();
            match app.target() {
                Some(t) if s(t, "root") != "/" => {
                    l.extend(icon_line(
                        look,
                        Icon::Bromigos,
                        &format!("bromigOS {}", s(t, "hostname")),
                        "",
                        w,
                    ));
                    l.push(state_line(
                        look,
                        Tone::Good,
                        "unlocked",
                        &format!("{}mounted at {}", dot(look), s(t, "root")),
                    ));
                }
                Some(t) => {
                    l.extend(icon_line(
                        look,
                        Icon::Bromigos,
                        &format!("this system{}{}", dot(look), s(t, "hostname")),
                        "",
                        w,
                    ));
                }
                None => {
                    for f in app.overview["found"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter(|f| f["kind"] == "bromigos")
                    {
                        l.extend(icon_line(
                            look,
                            Icon::Bromigos,
                            &format!("{} on {}", s(f, "title"), s(f, "device")),
                            &format!("{}{}", dot(look), s(f, "state")),
                            w,
                        ));
                    }
                    l.push(state_line(
                        look,
                        Tone::Calm,
                        "not mounted",
                        &format!("{}Mount my bromigOS install", dot(look)),
                    ));
                }
            }
            for f in app.overview["found"]
                .as_array()
                .into_iter()
                .flatten()
                .filter(|f| f["kind"] == "bromigos")
            {
                let d = s(f, "detail");
                if !d.is_empty() {
                    l.push(state_line(look, Tone::Warn, &d, ""));
                }
            }
            for (text, _) in app.suggestions().iter().take(1) {
                l.extend(widgets::wrap_hanging(
                    text,
                    w,
                    &format!("{} ", Icon::Alert.of(look)),
                    "  ",
                    st(p.warn),
                ));
            }
            panels.push((Icon::Disk, "Your install", l));
            let mut d = Vec::new();
            for x in app.disks["disks"].as_array().into_iter().flatten() {
                let failing = x["failing"].as_bool().unwrap_or(false);
                let verdict = s(x, "verdict");
                let (tone, word) = if failing {
                    (Tone::Bad, "failing")
                } else if verdict.contains("healthy") {
                    (Tone::Good, "healthy")
                } else {
                    (Tone::Calm, "no health report")
                };
                d.push(state_line(
                    look,
                    tone,
                    &format!("{:<8}", dev_name(&s(x, "path"))),
                    &format!(
                        " {word}{}{}{}",
                        dot(look),
                        s(x, "size"),
                        if s(x, "model").is_empty() {
                            String::new()
                        } else {
                            format!("{}{}", dot(look), s(x, "model"))
                        }
                    ),
                ));
            }
            if d.is_empty() {
                d.push(Line::from(Span::styled("reading the drives…", st(p.muted))));
            }
            panels.push((Icon::Disk, "Disks", d));
        }
        "Lab" => {
            let mut l = Vec::new();
            let lab = &app.lab;
            if !lab.is_object() {
                l.push(state_line(
                    look,
                    Tone::Calm,
                    "no lab connection read yet",
                    "",
                ));
                l.push(Line::from(Span::styled(
                    if app.net() == "none" {
                        "no network: the lab is reached over your local network".to_string()
                    } else {
                        "asking the lab…".to_string()
                    },
                    st(p.muted),
                )));
            } else if !lab["configured"].as_bool().unwrap_or(true) {
                l.push(state_line(look, Tone::Calm, "no lab set up here", ""));
                l.push(Line::from(Span::styled(
                    "connect to one from the stick's settings, or Open the lab console",
                    st(p.muted),
                )));
            } else {
                let cards = lab["cards"].as_array().cloned().unwrap_or_default();
                let bad = cards
                    .iter()
                    .filter(|c| {
                        matches!(
                            c["state"].as_str(),
                            Some("warn" | "error" | "unreachable" | "critical")
                        )
                    })
                    .count();
                l.push(state_line(
                    look,
                    if bad > 0 { Tone::Warn } else { Tone::Good },
                    &format!("{} parts", cards.len()),
                    &format!("{}{} need you", dot(look), bad),
                ));
                l.push(Line::from(Span::styled(
                    format!(
                        "reached over {}",
                        if app.net() == "internet" {
                            "the network"
                        } else {
                            "this network"
                        }
                    ),
                    st(p.muted),
                )));
            }
            let your_h = l.len() as u16 + 2;
            panels.push((Icon::Lab, "Your lab", l));
            let mut m = Vec::new();
            let mut nodes = Vec::new();
            for c in app.lab["cards"].as_array().into_iter().flatten().take(8) {
                let tone = match c["state"].as_str().unwrap_or("") {
                    "ok" | "healthy" | "good" => Tone::Good,
                    "warn" | "degraded" => Tone::Warn,
                    "error" | "critical" | "unreachable" => Tone::Bad,
                    _ => Tone::Calm,
                };
                m.push(state_line(
                    look,
                    tone,
                    &format!("{:<12}", s(c, "title")),
                    &format!(" {}", s(c, "summary")),
                ));
                nodes.push((s(c, "title"), tone));
            }
            // on a wide screen, where braille shows: the parts round the lab as a small radar,
            // the list under it when there's room for both
            let map_h = 11u16;
            let wide = Breakpoint::of(f.area().width) == Breakpoint::Wide;
            if wide && bromigos_tui::orb::fine(look) && !nodes.is_empty() {
                let room = area.height.saturating_sub(your_h + 1);
                if room >= map_h + 2 {
                    let hub = s(&app.overview["lab"], "name");
                    let hub = if hub.is_empty() { "lab".into() } else { hub };
                    let map = bromigos_tui::starmap::constellation(
                        look,
                        &hub,
                        &nodes,
                        w as usize,
                        map_h as usize,
                        orb_t(app),
                    );
                    panels.push((Icon::Network, "The lab's map", map));
                    if room < map_h + 2 + 1 + m.len() as u16 + 2 {
                        m.clear();
                    }
                }
            }
            if !m.is_empty() {
                panels.push((Icon::Server, "Machines and services", m));
            }
        }
        "Server" if app.server_home() => {
            let sv = &app.server;
            let mut l = vec![];
            l.extend(icon_line(
                look,
                Icon::Server,
                &format!("bromigOS Server{}{}", dot(look), s(sv, "hostname")),
                "",
                w,
            ));
            let addrs: Vec<String> = sv["addresses"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|a| a.as_str().map(String::from))
                .collect();
            if !addrs.is_empty() {
                l.push(Line::from(vec![
                    Span::styled("reach it ", st(p.soft)),
                    Span::styled(format!("{}ssh {}", dot(look), addrs.join(" ")), st(p.muted)),
                ]));
            }
            panels.push((Icon::Server, "This server", l));
            let mut svc = vec![state_line(
                look,
                if sv["ssh"].as_bool().unwrap_or(false) {
                    Tone::Good
                } else {
                    Tone::Calm
                },
                "SSH        ",
                if sv["ssh"].as_bool().unwrap_or(false) {
                    " on, keys only"
                } else {
                    " off"
                },
            )];
            for (icon, text) in server_status_lines(app) {
                let _ = icon;
                svc.push(state_line(look, Tone::Good, &text, ""));
            }
            panels.push((Icon::Settings, "Services", svc));
        }
        "Server" => {
            let l = widgets::wrap_hanging(
                "bromigOS Server is bromigOS without the desktop, for servers and lab machines: SSH with your key, a firewall, updates that snapshot first and roll back if the server doesn't come back, Podman, the lab's cluster and monitoring, herdr.",
                w,
                "",
                "",
                st(p.text),
            );
            panels.push((Icon::Server, "bromigOS Server", l));
            let note = widgets::wrap_hanging(
                "On an installed bromigOS Server, this screen runs it: its services, updates, firewall and SSH.",
                w,
                &format!("{} ", Icon::Info.of(look)),
                "  ",
                st(p.faint),
            );
            panels.push((Icon::Info, "", note));
        }
        _ => {
            // Shell: what's going on, and the commands that help here
            let mut l = Vec::new();
            for (label, value, tone) in facts(app) {
                let text = if label.is_empty() {
                    value
                } else {
                    format!("{label}: {value}")
                };
                l.extend(widgets::wrap_hanging(
                    &text,
                    w,
                    "",
                    "  ",
                    st(if tone == Tone::Warn { p.warn } else { p.text }),
                ));
            }
            panels.push((Icon::Info, "Right now", l));
            let tips = [
                ("fieldkit", "the menu"),
                ("bromigos hw", "the hardware"),
                ("bromigos lab", "the lab"),
                ("herdr", "share a terminal"),
                ("btop, nvtop", "monitors"),
                ("nvim", "edit"),
            ];
            let t = tips
                .iter()
                .map(|(c, w)| {
                    Line::from(vec![
                        Span::styled(format!("{c:<14}"), st(p.soft)),
                        Span::styled(w.to_string(), st(p.muted)),
                    ])
                })
                .collect();
            panels.push((Icon::Book, "Handy here", t));
        }
    }
    let heights: Vec<Constraint> = panels
        .iter()
        .map(|(_, _, l)| Constraint::Length(l.len() as u16 + 2))
        .chain(std::iter::once(Constraint::Min(0)))
        .collect();
    let rects = Layout::vertical(heights).spacing(1).split(area);
    for (i, (icon, title, lines)) in panels.into_iter().enumerate() {
        let inner = boxed(f, rects[i], look, icon, title, false);
        f.render_widget(Paragraph::new(lines), inner);
    }
}

/// The Tools screen's cards: three a row.
fn tool_cards(app: &App, area: Rect) -> Vec<Rect> {
    // cards five rows tall with a gap, three a row (two on a narrow screen, one on a tiny one);
    // rows past the screen scroll in, so the highlighted card's row is always on it
    let cols = tool_cols(area.width);
    let visible = (area.height / 6).max(1) as usize;
    let first = bromigos_tui::layout::grid_first_row(app.sel, cols, visible);
    bromigos_tui::layout::grid(area, app.items().len(), cols, 5, 2, 1, first)
}

fn draw_tools(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let p = &look.pal;
    let items = app.items();
    let cards = tool_cards(app, area);
    for (i, (it, r)) in items.iter().zip(cards.iter()).enumerate() {
        let r = *r;
        if r.height == 0 || r.bottom() > area.bottom() {
            continue;
        }
        let sel = i == app.sel;
        let mut block = widgets::glass(look, "", sel);
        // the highlighted card: filled in 24-bit colour; on the console its frame lights and its
        // name is black on green (a filled card would put green text on green)
        if sel && look.mode == bromigos_tui::Mode::Truecolor {
            block = block.style(widgets::sel_surface(look));
        }
        let inner = block.inner(r).inner(Margin::new(1, 0));
        f.render_widget(block, r);
        let style = if sel {
            widgets::sel_text(look)
        } else {
            st(p.soft)
        };
        let mut lines = vec![Line::from(vec![
            Span::styled(format!("{}  ", act_icon(&it.act).of(look)), style),
            Span::styled(it.label.to_string(), style),
        ])];
        lines.extend(
            widgets::wrap_hanging(it.hint, inner.width, "", "", st(p.muted))
                .into_iter()
                .take(2),
        );
        f.render_widget(Paragraph::new(lines), inner);
    }
}

/// The Install screen's parts: the edition cards, the rows under them, the checks.
fn install_parts(app: &App, area: Rect) -> (Vec<Rect>, Vec<Rect>, Rect) {
    let items = app.items();
    let n_cards = items
        .iter()
        .filter(|i| matches!(i.act, Act::InstallEdition(_)))
        .count();
    let n_rows = items.len() - n_cards;
    // side by side on a wide screen; one above the other, shorter, on a narrow one
    let side = Breakpoint::of_area(area).side_by_side();
    let card_h: u16 = if side { 8 } else { 6 };
    let cards_h = if n_cards == 0 {
        0
    } else if side {
        card_h
    } else {
        card_h * n_cards as u16
    };
    let [cards, _, rows, _, checks] = Layout::vertical([
        Constraint::Length(cards_h),
        Constraint::Length(1),
        Constraint::Length(n_rows as u16),
        Constraint::Length(1),
        Constraint::Min(0),
    ])
    .areas(area);
    let card_rects = if side {
        Layout::horizontal(vec![
            Constraint::Ratio(1, n_cards.max(1) as u32);
            n_cards.max(1)
        ])
        .spacing(2)
        .split(cards)
        .iter()
        .take(n_cards)
        .copied()
        .collect()
    } else {
        Layout::vertical(vec![Constraint::Length(card_h); n_cards])
            .split(cards)
            .to_vec()
    };
    let row_rects = Layout::vertical(vec![Constraint::Length(1); n_rows])
        .split(rows)
        .to_vec();
    (card_rects, row_rects, checks)
}

/// "Before installing": what's known about this computer that matters to an install.
fn checks(app: &App) -> Vec<(Tone, String, String)> {
    let mut v = Vec::new();
    let disks: Vec<Value> = app.disks["disks"].as_array().cloned().unwrap_or_default();
    if !disks.is_empty() {
        let failing: Vec<String> = disks
            .iter()
            .filter(|d| d["failing"].as_bool().unwrap_or(false))
            .map(|d| dev_name(&s(d, "path")))
            .collect();
        v.push(if failing.is_empty() {
            (
                Tone::Good,
                "Disks".into(),
                format!("{} found, none failing", disks.len()),
            )
        } else {
            (
                Tone::Bad,
                "Disks".into(),
                format!(
                    "{} says it's failing: don't install on it",
                    failing.join(", ")
                ),
            )
        });
    }
    let ram = s(&app.overview["computer"], "ram");
    if !ram.is_empty() {
        v.push((Tone::Good, "Memory".into(), ram));
    }
    v.push((
        Tone::Good,
        "Start-up".into(),
        if Path::new("/sys/firmware/efi").is_dir() {
            "UEFI".into()
        } else {
            "BIOS (legacy)".into()
        },
    ));
    for f in app.overview["found"].as_array().into_iter().flatten() {
        if f["kind"] == "windows" && s(f, "state").contains("BitLocker") {
            v.push((
                Tone::Warn,
                "Windows".into(),
                "BitLocker is on: installing alongside it is off until it's turned off in Windows"
                    .into(),
            ));
        }
    }
    v.push(match app.net().as_str() {
        "internet" => (
            Tone::Good,
            "Network".into(),
            "online: the desktop can be downloaded".into(),
        ),
        _ => (
            Tone::Calm,
            "Network".into(),
            "offline: bromigOS Server installs from this stick".into(),
        ),
    });
    v
}

fn draw_install(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let p = &look.pal;
    let items = app.items();
    let (cards, rows, check_area) = install_parts(app, area);
    let ed = &app.edition;
    let mut ci = 0;
    let mut ri = 0;
    for (i, it) in items.iter().enumerate() {
        let sel = i == app.sel;
        match it.act {
            Act::InstallEdition(e) => {
                let Some(r) = cards.get(ci).copied() else {
                    continue;
                };
                ci += 1;
                let mut block = widgets::glass(look, "", sel);
                if sel && look.mode == bromigos_tui::Mode::Truecolor {
                    block = block.style(widgets::sel_surface(look));
                }
                let inner = block.inner(r).inner(Margin::new(1, 0));
                f.render_widget(block, r);
                let (icon, title, about, need, needs_ok) = if e == "server" {
                    let summary = if s(ed, "summary").is_empty() {
                        "No desktop, for servers and lab machines.".to_string()
                    } else {
                        s(ed, "summary")
                    };
                    (
                        Icon::Server,
                        if s(ed, "title").is_empty() {
                            "bromigOS Server".to_string()
                        } else {
                            s(ed, "title")
                        },
                        summary,
                        "installs from this stick; no internet needed".to_string(),
                        true,
                    )
                } else {
                    (Icon::Computer, "bromigOS desktop".to_string(), "The full desktop: worlds, VECTOR, games, apps. For the computer you use every day.".to_string(),
                     if app.net() == "internet" { "downloads about 2 GB".to_string() } else { "downloads about 2 GB: needs the internet".to_string() },
                     app.net() == "internet")
                };
                let style = if sel {
                    st(p.primary).add_modifier(Modifier::BOLD)
                } else {
                    st(p.soft).add_modifier(Modifier::BOLD)
                };
                let mut lines = vec![
                    Line::from(vec![
                        Span::styled(format!("{}  ", icon.of(look)), style),
                        Span::styled(title, style),
                    ]),
                    Line::from(""),
                ];
                lines.extend(
                    widgets::wrap_hanging(&about, inner.width, "", "", st(p.text))
                        .into_iter()
                        .take(3),
                );
                lines.push(Line::from(vec![
                    Span::styled(
                        format!(
                            "{} ",
                            if needs_ok {
                                Icon::Check.of(look)
                            } else {
                                Icon::Alert.of(look)
                            }
                        ),
                        st(if needs_ok { p.primary } else { p.warn }),
                    ),
                    Span::styled(need, st(if needs_ok { p.primary } else { p.warn })),
                ]));
                f.render_widget(Paragraph::new(lines), inner);
            }
            _ => {
                let Some(r) = rows.get(ri).copied() else {
                    continue;
                };
                ri += 1;
                let mark = if look.ascii { ">" } else { "▌" };
                let style = if sel {
                    st(p.primary).add_modifier(Modifier::BOLD)
                } else {
                    st(p.soft)
                };
                f.render_widget(
                    Paragraph::new(Line::from(vec![
                        Span::styled(if sel { mark } else { " " }, st(p.primary)),
                        Span::styled(format!("{}  ", act_icon(&it.act).of(look)), style),
                        Span::styled(it.label.to_string(), style),
                        Span::styled(format!("{}{}", dot(look), it.hint), st(p.muted)),
                    ])),
                    r,
                );
            }
        }
    }
    if check_area.height >= 3 {
        let list = checks(app);
        let h = (list.len() as u16 + 2).min(check_area.height);
        let r = Rect {
            height: h,
            ..check_area
        };
        let inner = boxed(f, r, look, Icon::Check, "Before installing", false);
        let lines: Vec<Line> = list
            .iter()
            .map(|(t, n, x)| state_line(look, *t, &format!("{n:<11}"), &format!(" {x}")))
            .collect();
        f.render_widget(Paragraph::new(lines), inner);
    }
}

fn draw_section(f: &mut Frame, app: &App, area: Rect) -> Rect {
    let l = section_layout(app, area);
    top_bar(f, l.top, app);
    let name = SECTIONS[app.section];
    let (icon, _) = section_tile(name, app.server_home());
    match name {
        "Tools" => draw_tools(f, l.list, app),
        "Install" => draw_install(f, l.list, app),
        _ => {
            if let Some(left) = l.left {
                left_panels(f, left, app);
            }
            if let Some(r) = l.summary {
                let p = &app.look.pal;
                let text = bromigos_tui::layout::truncate(
                    &summary_text(app),
                    r.width as usize - 2,
                    app.look.ascii,
                );
                f.render_widget(
                    Paragraph::new(Line::from(vec![
                        Span::styled(format!("{} ", Icon::Info.of(&app.look)), st(p.primary)),
                        Span::styled(text, st(p.soft)),
                    ])),
                    r,
                );
            }
            actions(f, l.list, app, name, icon);
        }
    }
    let hint = app
        .items()
        .get(app.sel)
        .map(|i| {
            let why = app.blocked(i);
            let mut h = if why.is_empty() {
                i.hint.to_string()
            } else if i.hint.is_empty() {
                why
            } else {
                format!("{}{}{why}", i.hint, dot(&app.look))
            };
            let t = act_touches(&i.act);
            if !t.is_empty() {
                h = format!("{h}{}touches: {t}", dot(&app.look));
            }
            h
        })
        .unwrap_or_default();
    bottom_bar(f, l.bottom, app, &keys_for(app), &hint);
    l.body
}

pub fn draw(f: &mut Frame, app: &App) {
    let look = &app.look;
    let area = f.area();
    if bromigos_tui::layout::too_small(area) {
        bromigos_tui::layout::too_small_screen(f, area, look);
        return;
    }
    f.render_widget(
        Paragraph::new("").style(Style::new().bg(look.pal.void)),
        area,
    );
    let body = match app.screen {
        Screen::Home => draw_home(f, app, area),
        Screen::Section => draw_section(f, app, area),
    };
    for o in &app.overlays {
        draw_overlay(f, body, app, o);
    }
}

/// The separator between short facts: a middle dot, or a dash in ASCII.
fn dot(look: &Look) -> &'static str {
    if look.ascii { " - " } else { " · " }
}

/// The clock, HH:MM in local time.
fn clock() -> String {
    // SAFETY: time and localtime_r with valid pointers; tm is plain data.
    unsafe {
        let t = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        if libc::localtime_r(&t, &mut tm).is_null() {
            return String::new();
        }
        format!("{:02}:{:02}", tm.tm_hour, tm.tm_min)
    }
}

/// The status chips: the network, SSH, the stick's settings, remote help, the clock (Reading:
/// a chip glows only when it means something).
pub fn chips(app: &App) -> Vec<(Icon, String, Tone)> {
    let mut o = app.overview.clone();
    if !o["network"]["state"].is_string() {
        o["network"]["state"] = Value::from(app.net());
    }
    if let Some(on) = app.server["ssh"].as_bool() {
        o["ssh"]["on"] = Value::from(on);
    }
    if o["remote"]["on"].as_bool().is_none() {
        o["remote"] = app.status["remote"].clone();
    }
    if s(&o, "stick").is_empty() {
        o["stick"] = app.status["stick"].clone();
    }
    bar_chips(&app.look, &o)
}

/// The chips from the engine's facts (overview's, or VECTOR's status "bar"): every Field Kit
/// screen shows the same ones.
pub fn bar_chips(look: &Look, o: &Value) -> Vec<(Icon, String, Tone)> {
    let mut v = Vec::new();
    let kind = o["network"]["kind"].as_str().unwrap_or("");
    let state = o["network"]["state"].as_str().unwrap_or("").to_string();
    let name = s(&o["network"], "name");
    let (icon, base) = match kind {
        "wifi" => (
            Icon::Wifi,
            if name.is_empty() {
                "Wi-Fi".to_string()
            } else {
                name
            },
        ),
        "wired" => (Icon::Wired, "wired".to_string()),
        _ if state == "none" || state.is_empty() => (Icon::NoNetwork, "no network".to_string()),
        _ => (Icon::Network, "network".to_string()),
    };
    let (word, tone) = match state.as_str() {
        "internet" => (format!("{base}{}online", dot(look)), Tone::Good),
        "lan" => (format!("{base}{}local only", dot(look)), Tone::Calm),
        _ => (base, Tone::Calm),
    };
    v.push((icon, word, tone));
    let ssh = o["ssh"]["on"].as_bool().unwrap_or(false);
    v.push((
        Icon::Key,
        if ssh {
            "SSH on".into()
        } else {
            "SSH off".into()
        },
        if ssh { Tone::Good } else { Tone::Calm },
    ));
    if o["remote"]["on"].as_bool().unwrap_or(false) {
        v.push((Icon::Remote, "REMOTE HELP ON".into(), Tone::Warn));
    }
    let stick = s(o, "stick");
    if !stick.is_empty() {
        v.push((
            Icon::Usb,
            stick.trim_start_matches("stick settings: ").to_string(),
            Tone::Calm,
        ));
    }
    let c = clock();
    if !c.is_empty() {
        v.push((Icon::Clock, c, Tone::Calm));
    }
    v
}

pub fn chip_spans(look: &Look, chips: &[(Icon, String, Tone)]) -> Vec<Span<'static>> {
    let p = &look.pal;
    let mut spans = Vec::new();
    for (i, (icon, text, tone)) in chips.iter().enumerate() {
        if i > 0 {
            spans.push(Span::styled("  ", st(p.faint)));
        }
        let c = match tone {
            Tone::Good => p.primary,
            Tone::Warn => p.warn,
            Tone::Bad => p.danger,
            Tone::Calm => p.muted,
        };
        let mut style = st(c);
        if *tone == Tone::Warn {
            style = style.add_modifier(Modifier::BOLD);
        }
        spans.push(Span::styled(format!("{} ", icon.of(look)), st(c)));
        spans.push(Span::styled(text.clone(), style));
    }
    spans
}

pub fn chips_width(look: &Look, chips: &[(Icon, String, Tone)]) -> u16 {
    chip_spans(look, chips)
        .iter()
        .map(|s| s.content.chars().count() as u16)
        .sum()
}

/// A size in bytes, the way a person reads it: 512 MB, 64 GB, 2.0 TB.
fn human(bytes: u64) -> String {
    let b = bytes as f64;
    let (gb, tb) = (1e9, 1e12);
    if b >= tb {
        format!("{:.1} TB", b / tb)
    } else if b >= gb {
        format!("{:.0} GB", b / gb)
    } else {
        format!("{:.0} MB", b / 1e6)
    }
}

/// A share's Reading tone: calm, a warning from `warn` up.
fn share_tone(pct: f64, warn: f64) -> Tone {
    if pct >= warn { Tone::Warn } else { Tone::Calm }
}

/// The readings line: how busy the processor is and how much memory is in use, each a small
/// meter and its share; meters shrink to fit, and on a short line it's only the shares.
fn readings_line(look: &Look, load: &Value, width: u16) -> Option<Line<'static>> {
    let p = &look.pal;
    let parts: Vec<(&str, f64)> = [("busy", "cpu_pct"), ("memory", "mem_pct")]
        .into_iter()
        .filter_map(|(label, k)| Some((label, load[k].as_f64()?)))
        .collect();
    if parts.is_empty() {
        return None;
    }
    // "  busy ████░░ 31%   memory ██████░ 62%": the words and shares take about 16 a part
    let words: usize = 2 + parts.iter().map(|(l, _)| l.len() + 9).sum::<usize>();
    let mw = ((width as usize).saturating_sub(words) / parts.len()).min(14);
    let mut spans = vec![Span::raw("  ")];
    for (i, (label, pct)) in parts.iter().enumerate() {
        if i > 0 {
            spans.push(Span::raw("   "));
        }
        let tone = share_tone(*pct, 90.0);
        spans.push(Span::styled(format!("{label} "), st(p.muted)));
        if mw >= 4 {
            spans.extend(widgets::meter(look, pct / 100.0, mw as u16, tone));
            spans.push(Span::raw(" "));
        }
        let c = if tone == Tone::Warn { p.warn } else { p.soft };
        spans.push(Span::styled(format!("{pct:.0}%"), st(c)));
    }
    Some(Line::from(spans))
}

/// The temperatures line: each sensor's reading and, once there are a few, its recent ones as
/// a sparkline (a warning from 90 °C). Too long for the line: the readings alone, wrapped.
fn temps_line(app: &App, width: u16) -> Vec<Line<'static>> {
    let look = &app.look;
    let p = &look.pal;
    let deg = if look.ascii { " C" } else { "°C" };
    let temps: Vec<(String, f64)> = app.overview["computer"]["temps"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|t| Some((s(t, "label"), t["celsius"].as_f64()?)))
        .collect();
    if temps.is_empty() {
        return vec![];
    }
    let hist = |label: &str| -> &[f64] {
        app.temps
            .iter()
            .find(|(l, _)| l == label)
            .map(|(_, h)| h.as_slice())
            .unwrap_or(&[])
    };
    let mut spans = vec![Span::styled(
        format!("{} ", Icon::Thermometer.of(look)),
        st(p.primary),
    )];
    for (i, (label, c)) in temps.iter().enumerate() {
        if i > 0 {
            spans.push(Span::styled(dot(look), st(p.faint)));
        }
        let warn = *c >= 90.0;
        spans.push(Span::styled(format!("{label} "), st(p.soft)));
        spans.push(Span::styled(
            format!("{c:.0}{deg}"),
            if warn {
                st(p.warn).add_modifier(Modifier::BOLD)
            } else {
                st(p.text)
            },
        ));
        let h = hist(label);
        if h.len() >= 2 {
            spans.push(Span::styled(
                format!(" {}", widgets::sparkline(look, h, 25.0, 100.0, 8)),
                st(if warn { p.warn } else { p.dim }),
            ));
        }
    }
    let line = Line::from(spans);
    if line.width() <= width as usize {
        return vec![line];
    }
    let text: Vec<String> = temps
        .iter()
        .map(|(l, c)| format!("{l} {c:.0}{deg}"))
        .collect();
    icon_line(look, Icon::Thermometer, &text.join(dot(look)), "", width)
}

/// A disk's line: its name and size, then its partitions as a disk map (bromigos-tui's
/// diskmap), the rest of the line wide.
fn disk_line(look: &Look, d: &Value, width: u16) -> Line<'static> {
    let p = &look.pal;
    let failing = s(d, "health") == "failing";
    let head = format!(
        "{} {:<8}{:>7}  ",
        Icon::Disk.of(look),
        s(d, "name"),
        human(d["size"].as_u64().unwrap_or(0))
    );
    let hw = bromigos_tui::layout::display_width(&head) as u16;
    let mut spans = vec![Span::styled(
        head,
        st(if failing { p.danger } else { p.soft }),
    )];
    if width > hw + 8 {
        spans.extend(bromigos_tui::diskmap::bar(look, d, width - hw));
    }
    Line::from(spans)
}

/// "This computer" as lines `width` wide: the board, the processor and memory with how busy
/// and full they are, the graphics, the temperatures with their recent readings, and each
/// disk as a map of its partitions.
fn computer_view(app: &App, width: u16) -> Vec<Line<'static>> {
    let look = &app.look;
    let c = &app.overview["computer"];
    let mut v = Vec::new();
    for (icon, key) in [
        (Icon::Computer, "board"),
        (Icon::Chip, "cpu"),
        (Icon::Memory, "ram"),
    ] {
        let x = s(c, key);
        if !x.is_empty() {
            v.extend(icon_line(look, icon, &x, "", width));
        }
    }
    v.extend(readings_line(look, &app.overview["load"], width));
    for g in c["gpus"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|g| g.as_str())
    {
        v.extend(icon_line(look, Icon::Gpu, g, "", width));
    }
    v.extend(temps_line(app, width));
    for d in app.overview["disks"].as_array().into_iter().flatten() {
        v.push(disk_line(look, d, width));
    }
    if v.is_empty() {
        v.extend(icon_line(
            look,
            Icon::Info,
            "reading this computer…",
            "",
            width,
        ));
    }
    v
}

/// "Found on this computer": each install, Windows, other Linux, USB sticks, the Field Kit
/// stick, each with its system's logo, and its drive's own health verdict when it gave one.
fn found_view(app: &App, width: u16) -> Vec<Line<'static>> {
    let look = &app.look;
    let p = &look.pal;
    let mut out = Vec::new();
    for x in app.overview["found"].as_array().into_iter().flatten() {
        let (icon, colour) = match x["kind"].as_str().unwrap_or("") {
            "bromigos" => (Icon::Arch, p.primary),
            "windows" => (Icon::Windows, p.accent),
            "linux" => (Icon::Linux, p.soft),
            "usb" => (Icon::Usb, p.muted),
            "fieldkit" => (Icon::FieldKit, p.primary),
            _ => (Icon::Disk, p.muted),
        };
        // the engine's titles name the device already ("bromigOS on sda2"); else it's added
        let mut title = s(x, "title");
        let dev = dev_name(&s(x, "device"));
        if !dev.is_empty() && !title.contains(&dev) {
            title = format!("{title} on {dev}");
        }
        let state = [s(x, "state"), s(x, "detail")]
            .into_iter()
            .filter(|w| !w.is_empty())
            .collect::<Vec<_>>()
            .join(", ");
        let rest = if state.is_empty() {
            String::new()
        } else {
            format!("{}{state}", dot(look))
        };
        let mut lines = icon_line(look, icon, &title, &rest, width);
        if let Some(first) = lines.first_mut()
            && let Some(m) = first.spans.first_mut()
        {
            m.style = st(colour).add_modifier(Modifier::BOLD);
        }
        // the drive's verdict, a Reading: it glows only when it's failing
        let badge = match (s(x, "health").as_str(), look.ascii) {
            ("ok", false) => Some(("● healthy", st(p.primary))),
            ("ok", true) => Some(("+ healthy", st(p.primary))),
            ("failing", false) => Some(("✕ FAILING", st(p.danger).add_modifier(Modifier::BOLD))),
            ("failing", true) => Some(("x FAILING", st(p.danger).add_modifier(Modifier::BOLD))),
            _ => None,
        };
        if let Some((b, style)) = badge {
            let bw = bromigos_tui::layout::display_width(b) + 2;
            match lines.last_mut() {
                Some(last) if last.width() + bw <= width as usize => {
                    last.spans.push(Span::styled(format!("  {b}"), style));
                }
                _ => lines.push(Line::from(Span::styled(format!("   {b}"), style))),
            }
        }
        out.extend(lines);
    }
    if out.is_empty() {
        let text = if app.overview.is_object() {
            "No installed system and no USB drives found."
        } else {
            "looking at the drives…"
        };
        out.push(Line::from(Span::styled(text, st(p.muted))));
    }
    out
}

/// A server's own facts (bromigos-server status --json), for the Server section.
fn server_status_lines(app: &App) -> Vec<(Icon, String)> {
    let st = &app.server["status"];
    let mut v = Vec::new();
    for (icon, key, label) in [
        (Icon::Shield, "firewall", "firewall"),
        (Icon::Update, "updates", "updates"),
        (Icon::Containers, "containers", "containers"),
        (Icon::Network, "cluster", "lab cluster"),
        (Icon::Key, "ssh", "SSH"),
    ] {
        if let Some(x) = st.get(key) {
            let text = x
                .as_str()
                .map(String::from)
                .unwrap_or_else(|| x.to_string());
            v.push((icon, format!("{label}: {text}")));
        }
    }
    v
}

/// Each item's icon.
pub fn act_icon(a: &Act) -> Icon {
    match a {
        Act::Mount | Act::Unmount => Icon::Lock,
        Act::Why => Icon::Search,
        Act::Black => Icon::Alert,
        Act::Rollback => Icon::Rollback,
        Act::Grub | Act::BootOptions => Icon::Boot,
        Act::Edit => Icon::Edit,
        Act::Disks => Icon::Disk,
        Act::Backup => Icon::Backup,
        Act::Image => Icon::Image,
        Act::Erase => Icon::Erase,
        Act::Windows => Icon::Windows,
        Act::Graphics => Icon::Gpu,
        Act::Remote => Icon::Remote,
        Act::MakeStick => Icon::Usb,
        Act::Manual => Icon::Book,
        Act::InstallEdition(_) => Icon::Install,
        Act::Shell | Act::Chroot => Icon::Shell,
        Act::Power(_) => Icon::Power,
        Act::AboutServer => Icon::Info,
        Act::PairBrodec => Icon::Remote,
        Act::ServerUpdate => Icon::Update,
        Act::Firewall(..) => Icon::Shield,
        Act::ServerSsh => Icon::Key,
        Act::Containers => Icon::Containers,
        Act::Cluster => Icon::Network,
        Act::Card(icon, _, _) => *icon,
        Act::Tool(argv) => match argv.first().copied().unwrap_or("") {
            "nmtui" => Icon::Wifi,
            "bromigos" if argv.get(1) == Some(&"media") => Icon::Media,
            "bromigos" if argv.get(1) == Some(&"lab") => Icon::Lab,
            "bromigos" => Icon::Settings,
            _ => Icon::Tools,
        },
    }
}

/// The status line: the network, the install, remote help (warn, while it's on), the stick,
/// and on a server its own facts.
pub fn facts(app: &App) -> Vec<(&'static str, String, Tone)> {
    let mut v = Vec::new();
    let net = app.net();
    let (words, tone) = match net.as_str() {
        "internet" => ("online", Tone::Good),
        "lan" => ("local network only", Tone::Calm),
        "none" => ("no network", Tone::Calm),
        _ => ("…", Tone::Calm),
    };
    // the header's chips say it once the overview is in
    if !app.overview["network"].is_object() {
        v.push(("network", words.to_string(), tone));
    }
    if app.server_home() {
        let sv = &app.server;
        let addrs = sv["addresses"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|x| x.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
            })
            .unwrap_or_default();
        if !addrs.is_empty() {
            v.push(("address", addrs, Tone::Calm));
        }
        v.push((
            "SSH",
            if sv["ssh"].as_bool().unwrap_or(false) {
                "on".into()
            } else {
                "off".into()
            },
            Tone::Calm,
        ));
        for (k, label) in [
            ("firewall", "firewall"),
            ("updates", "updates"),
            ("containers", "containers"),
            ("cluster", "cluster"),
        ] {
            if let Some(x) = sv["status"].get(k) {
                let txt = x
                    .as_str()
                    .map(String::from)
                    .unwrap_or_else(|| x.to_string());
                v.push((label, txt, Tone::Calm));
            }
        }
    } else if let Some(t) = app.target() {
        if s(t, "root") == "/" {
            v.push((
                "working on",
                format!("this system ({})", s(t, "hostname")),
                Tone::Calm,
            ));
        } else {
            v.push((
                "install",
                format!("{} at {}", s(t, "hostname"), s(t, "root")),
                Tone::Good,
            ));
        }
    } else if app.live() {
        v.push(("install", "not mounted".into(), Tone::Calm));
    }
    let remote = s(&app.status, "remote_words");
    if !remote.is_empty() {
        v.push(("", remote, Tone::Warn));
    }
    let stick = s(&app.status, "stick");
    if !stick.is_empty() {
        v.push(("", stick, Tone::Calm));
    }
    if !app.look.motion {
        v.push(("", "reduced motion".into(), Tone::Calm));
    }
    v
}

/// Every overlay takes the whole space between the header and the status line, everything
/// under it cleared, with a one-cell margin inside its frame (widgets::panel). Text wraps by
/// words with a hanging indent (widgets::wrap_hanging).
fn draw_overlay(f: &mut Frame, area: Rect, app: &App, o: &Overlay) {
    let look = &app.look;
    let p = &look.pal;
    let spark = app.spark_until.is_some_and(|t| Instant::now() < t);
    match o {
        Overlay::Commands {
            title,
            commands,
            touches,
            cli,
            note,
            sel,
        } => {
            let inner = widgets::panel(
                f,
                area,
                look,
                &format!("{} {title}", Icon::Shell.of(look)),
                None,
            );
            let [body, _, row] = Layout::vertical([
                Constraint::Min(1),
                Constraint::Length(1),
                Constraint::Length(if Breakpoint::of_area(area) == Breakpoint::Tiny {
                    3
                } else {
                    1
                }),
            ])
            .areas(inner);
            let w = body.width;
            let mut lines = vec![Line::from(Span::styled(
                "THE COMMANDS",
                st(p.primary).add_modifier(Modifier::BOLD),
            ))];
            if commands.is_empty() {
                lines.push(Line::from(Span::styled(
                    "(none: nothing here runs a command of its own)",
                    st(p.muted),
                )));
            }
            // ❯ where the font has it (24-bit terminals, kmscon); $ on the console and in ASCII
            let prompt = if look.mode == bromigos_tui::Mode::Truecolor && !look.ascii {
                "❯ "
            } else {
                "$ "
            };
            for c in commands {
                lines.extend(widgets::wrap_hanging(c, w, prompt, "    ", st(p.white)));
            }
            lines.push(Line::from(""));
            lines.push(Line::from(Span::styled(
                "WHAT IT TOUCHES",
                st(p.primary).add_modifier(Modifier::BOLD),
            )));
            if touches.is_empty() {
                lines.push(Line::from(Span::styled("nothing it changes", st(p.muted))));
            }
            for t in touches {
                lines.extend(widgets::wrap_hanging(
                    t,
                    w,
                    &format!("{} ", if look.ascii { "-" } else { "•" }),
                    "  ",
                    st(p.text),
                ));
            }
            lines.push(Line::from(""));
            lines.push(Line::from(Span::styled(
                "FROM THE COMMAND LINE",
                st(p.primary).add_modifier(Modifier::BOLD),
            )));
            lines.extend(widgets::wrap_hanging(cli, w, prompt, "    ", st(p.accent)));
            if !note.is_empty() {
                lines.push(Line::from(""));
                lines.extend(widgets::wrap_hanging(note, w, "", "", st(p.warn)));
            }
            bromigos_tui::layout::scroll_view(f, body, look, lines, 0);
            let labels = ["Copy", "Run step by step in the shell", "Close"];
            let line = |i: usize, l: &str| {
                let s = if i == *sel {
                    widgets::sel_text(look)
                } else {
                    st(p.text)
                };
                Span::styled(format!("[ {l} ]"), s)
            };
            if row.height >= 3 {
                let ls: Vec<Line> = labels
                    .iter()
                    .enumerate()
                    .map(|(i, l)| Line::from(line(i, l)))
                    .collect();
                f.render_widget(Paragraph::new(ls), row);
            } else {
                let mut spans = Vec::new();
                for (i, l) in labels.iter().enumerate() {
                    spans.push(line(i, l));
                    spans.push(Span::raw("  "));
                }
                f.render_widget(Paragraph::new(Line::from(spans)), row);
            }
        }
        Overlay::Keys {
            title,
            rows,
            scroll,
        } => {
            let inner = widgets::panel(f, area, look, title, None);
            let kw = rows
                .iter()
                .map(|(k, _)| k.chars().count())
                .max()
                .unwrap_or(0)
                + 3;
            let mut lines = Vec::new();
            for (k, what) in rows {
                // "# Group": a heading for the rows under it
                if let Some(head) = k.strip_prefix("# ") {
                    lines.push(Line::from(""));
                    let mut spans = vec![Span::styled(
                        head.to_uppercase(),
                        st(p.primary).add_modifier(Modifier::BOLD),
                    )];
                    if !what.is_empty() {
                        spans.push(Span::styled(format!("  {what}"), st(p.accent)));
                    }
                    lines.push(Line::from(spans));
                    continue;
                }
                if k.is_empty() && what.is_empty() {
                    continue;
                }
                let mut l = widgets::wrap_hanging(
                    what,
                    inner.width.saturating_sub(kw as u16),
                    "",
                    "",
                    st(p.text),
                );
                for (i, line) in l.iter_mut().enumerate() {
                    let key = if i == 0 {
                        format!("{k:<kw$}")
                    } else {
                        " ".repeat(kw)
                    };
                    line.spans.insert(
                        0,
                        Span::styled(key, st(p.soft).add_modifier(Modifier::BOLD)),
                    );
                }
                lines.extend(l);
            }
            lines.push(Line::from(""));
            lines.push(Line::from(Span::styled("Esc closes", st(p.muted))));
            let more = lines.len() > inner.height as usize;
            if more {
                lines.push(Line::from(Span::styled(
                    if look.ascii {
                        "up, down, PgUp, PgDn scroll"
                    } else {
                        "↑↓ PgUp PgDn scroll"
                    },
                    st(p.muted),
                )));
            }
            f.render_widget(Paragraph::new(lines).scroll((*scroll as u16, 0)), inner);
        }
        Overlay::Message { title, text, ok } => {
            let border = (*ok && spark && look.motion).then_some(p.soft);
            let inner = widgets::panel(f, area, look, title, border);
            let mut lines = widgets::wrap_hanging(text, inner.width, "", "", st(p.text));
            lines.push(Line::from(""));
            lines.push(Line::from(Span::styled("ENTER closes", st(p.muted))));
            f.render_widget(Paragraph::new(lines), inner);
        }
        Overlay::Busy { title } => {
            let inner = widgets::panel(f, area, look, title, None);
            f.render_widget(
                Paragraph::new(widgets::sweep(
                    look,
                    None,
                    app.tick,
                    inner.width.saturating_sub(2),
                )),
                inner,
            );
        }
        Overlay::Progress {
            title,
            lines,
            pct,
            done,
        } => {
            let inner = widgets::panel(f, area, look, title, None);
            let end_h = done
                .as_ref()
                .map(|(_, m)| {
                    widgets::wrap_hanging(m, inner.width, "", "", Style::new()).len() as u16 + 1
                })
                .unwrap_or(0);
            let [bar, log, end] = Layout::vertical([
                Constraint::Length(1),
                Constraint::Min(3),
                Constraint::Length(end_h),
            ])
            .areas(inner);
            let pc = if done.as_ref().is_some_and(|d| d.0) {
                Some(100)
            } else {
                *pct
            };
            f.render_widget(
                Paragraph::new(widgets::sweep(
                    look,
                    pc,
                    app.tick,
                    bar.width.saturating_sub(6),
                )),
                bar,
            );
            widgets::log_view(f, log, look, "what it's doing", lines, 0);
            if let Some((ok, msg)) = done {
                let mut out = widgets::wrap_hanging(
                    msg,
                    end.width,
                    "",
                    "",
                    st(if *ok { p.primary } else { p.danger }).add_modifier(Modifier::BOLD),
                );
                out.push(Line::from(Span::styled("ENTER closes", st(p.muted))));
                f.render_widget(Paragraph::new(out), end);
            }
        }
        Overlay::Findings {
            title, items, sel, ..
        } => {
            // a fix that just worked: the panel's edge and its ✓ flash (the Spark)
            let flash = |it: &Finding| {
                look.motion
                    && it
                        .fixed_at
                        .is_some_and(|t| t.elapsed() < Duration::from_secs(1))
            };
            let inner = widgets::panel(f, area, look, title, None);
            if items.iter().any(flash) {
                f.render_widget(
                    widgets::spark(look, widgets::glass(look, title, true), true),
                    area,
                );
            }
            let w = inner.width;
            let mut lines = Vec::new();
            let mut at = 0;
            let pad = if look.ascii { "   " } else { "  " };
            for (i, it) in items.iter().enumerate() {
                if i == *sel {
                    at = lines.len();
                }
                // its severity: ✓ fine or fixed, ▲ a problem with a fix, ✕ one without
                let problem = st(p.white).add_modifier(Modifier::BOLD);
                let ((mark, ascii), colour, style) = if it.ok {
                    (("✓ ", "ok "), p.primary, st(p.muted))
                } else if it.fixed_at.is_some() {
                    (("✓ ", "ok "), p.primary, st(p.soft))
                } else if !it.fix.is_empty() {
                    (("▲ ", "!  "), p.warn, problem)
                } else {
                    (("✕ ", "x  "), p.danger, problem)
                };
                let mark = if look.ascii { ascii } else { mark };
                let mut title_lines = widgets::wrap_hanging(&it.title, w, mark, pad, style);
                if let Some(first) = title_lines.first_mut()
                    && let Some(m) = first.spans.first_mut()
                {
                    m.style = if flash(it) {
                        st(p.white).add_modifier(Modifier::BOLD)
                    } else {
                        st(colour).add_modifier(Modifier::BOLD)
                    };
                }
                lines.extend(title_lines);
                if !it.detail.is_empty() && !it.ok {
                    lines.extend(widgets::wrap_hanging(&it.detail, w, pad, pad, st(p.text)));
                }
                if !it.fix.is_empty() && !it.ok {
                    if !it.result.is_empty() {
                        lines.extend(widgets::wrap_hanging(&it.result, w, pad, pad, st(p.soft)));
                    } else {
                        let style = if i == *sel {
                            Style::new()
                                .bg(p.primary)
                                .fg(p.void)
                                .add_modifier(Modifier::BOLD)
                        } else {
                            st(p.primary)
                        };
                        lines.push(Line::from(vec![
                            Span::raw(pad),
                            Span::styled(format!("[ {} ]", it.fix), style),
                        ]));
                        if !it.touches.is_empty() {
                            lines.extend(widgets::wrap_hanging(
                                &format!("touches: {}", it.touches.join(", ")),
                                w,
                                pad,
                                pad,
                                st(p.muted),
                            ));
                        }
                    }
                }
                lines.push(Line::from(""));
            }
            if !items.iter().any(|f| !f.ok) {
                lines.push(Line::from(Span::styled(
                    "Nothing wrong found here.",
                    st(p.soft),
                )));
            }
            lines.push(Line::from(Span::styled(
                "↑↓ choose a fix · ENTER fix it (a backup first) · c its commands · ESC back",
                st(p.muted),
            )));
            let h = inner.height as usize;
            let scroll = (at + 6).saturating_sub(h);
            f.render_widget(Paragraph::new(lines).scroll((scroll as u16, 0)), inner);
        }
        Overlay::Pick {
            title,
            options,
            sel,
            ..
        } => {
            let inner = widgets::panel(f, area, look, title, None);
            // "label · what it does": the label on the bar, the rest as its hint
            let items: Vec<MenuItem> = options
                .iter()
                .map(|(_, l)| match l.split_once(" · ") {
                    Some((a, b)) => MenuItem::new(a, b),
                    None => MenuItem::new(l, ""),
                })
                .collect();
            let (lines, at) = widgets::menu_lines(look, &items, *sel, true, inner.width);
            let h = inner.height as usize;
            let scroll = (at + 2).saturating_sub(h);
            f.render_widget(Paragraph::new(lines).scroll((scroll as u16, 0)), inner);
        }
        Overlay::Input {
            title,
            prompt,
            value,
            hidden,
            ..
        } => widgets::input(f, area, look, title, prompt, value, *hidden),
        Overlay::Confirm {
            question,
            detail,
            yes,
            sel,
            then,
        } => {
            let labels = confirm_labels(yes, then);
            let labels: Vec<&str> = labels.iter().map(String::as_str).collect();
            widgets::confirm(f, area, look, question, detail, &labels, *sel)
        }
        Overlay::Typed {
            question,
            detail,
            want,
            typed,
            ..
        } => widgets::typed_confirm(f, area, look, question, detail, want, typed),
        Overlay::BootOptions {
            presets,
            on,
            sel,
            other,
            ..
        } => {
            let inner = widgets::panel(f, area, look, "Change the boot options", None);
            let mut lines = vec![Line::from(Span::styled(
                "Ticked settings are used at every start, after a restart.",
                st(p.muted),
            ))];
            let (yes, no) = if look.ascii {
                ("[x] ", "[ ] ")
            } else if look.mode == bromigos_tui::Mode::Truecolor {
                ("▣ ", "□ ")
            } else {
                ("■ ", "· ")
            };
            for (i, (_, label, hint)) in presets.iter().enumerate() {
                let style = if i == *sel {
                    Style::new()
                        .bg(p.primary)
                        .fg(p.void)
                        .add_modifier(Modifier::BOLD)
                } else {
                    st(p.text)
                };
                let mut l = widgets::wrap_hanging(
                    &format!("{label} · {hint}"),
                    inner.width,
                    if on[i] { yes } else { no },
                    "    ",
                    style,
                );
                if let Some(first) = l.first_mut()
                    && let Some(m) = first.spans.first_mut()
                {
                    m.style = st(p.primary);
                }
                lines.extend(l);
            }
            let style = if *sel == presets.len() {
                Style::new().bg(p.selection).fg(p.white)
            } else {
                st(p.text)
            };
            lines.push(Line::from(vec![
                Span::styled("other settings: ", st(p.muted)),
                Span::styled(format!("{other}▏"), style),
            ]));
            lines.push(Line::from(""));
            let save = if *sel == presets.len() + 1 {
                Style::new()
                    .bg(p.primary)
                    .fg(p.void)
                    .add_modifier(Modifier::BOLD)
            } else {
                st(p.primary)
            };
            lines.push(Line::from(Span::styled("[ Save ]", save)));
            lines.push(Line::from(Span::styled(
                "SPACE tick · ENTER on Save saves · ESC cancels",
                st(p.muted),
            )));
            f.render_widget(Paragraph::new(lines), inner);
        }
    }
}
