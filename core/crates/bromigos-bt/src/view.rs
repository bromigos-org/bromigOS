//! Drawing the TUI: DRIFTGLASS GLOW in the terminal (docs/DRIFTGLASS.md). Box frames in the
//! theme's colours; small device glyphs that brighten when connected; segmented battery
//! bars; a braille radar Sweep while scanning, devices blipping in. Motion only for a state,
//! and none under reduced motion (`App::still`).

use std::f64::consts::PI;

use ratatui::Frame;
use ratatui::layout::{Alignment, Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::symbols::Marker;
use ratatui::text::{Line, Span};
use ratatui::widgets::canvas::{Canvas, Circle, Line as CLine, Points};
use ratatui::widgets::{Block, BorderType, Borders, Clear, Paragraph, Wrap};

use crate::app::{App, Edit, KINDS, Screen, Step, plain_kind};
use crate::proto::Device;
use crate::theme::Pal;

const LOW: u8 = 15;
const CRITICAL: u8 = 5;

fn st(fg: Color) -> Style {
    Style::new().fg(fg)
}

fn frame<'a>(title: &'a str, pal: &Pal) -> Block<'a> {
    Block::new()
        .borders(Borders::ALL)
        .border_type(BorderType::Plain)
        .border_style(st(pal.dim))
        .title(Span::styled(
            format!(" {title} "),
            st(pal.primary).add_modifier(Modifier::BOLD),
        ))
        .style(Style::new().bg(pal.panel).fg(pal.text))
}

/// A short word for the list's kind column.
pub fn tag(glyph: &str) -> &'static str {
    match glyph {
        "controller" => "PAD",
        "headset" => "HEADSET",
        "earbuds" => "EARBUDS",
        "keyboard" => "KEYBOARD",
        "mouse" => "MOUSE",
        "phone" => "PHONE",
        "speaker" => "SPEAKER",
        _ => "DEVICE",
    }
}

/// A device's glyph, a few lines of block characters.
pub fn art(glyph: &str) -> &'static [&'static str] {
    match glyph {
        "controller" => &[
            " ▄▄▄▄▄▄▄▄▄▄▄▄▄ ",
            "█ ○  ▪ ▪   ∘  █",
            "█ ┼      ○ ∘ ∘█",
            " ▀▀▀▘     ▝▀▀▀ ",
        ],
        "headset" => &[
            "  ▄▀▀▀▀▀▀▀▄  ",
            " █         █ ",
            "▐█▌       ▐█▌",
            "▐█▌       ▐█▌",
        ],
        "earbuds" => &[
            "  ▄▄     ▄▄  ",
            " █  █   █  █ ",
            "  ▀█▀   ▀█▀  ",
            "   █     █   ",
        ],
        "keyboard" => &[
            "▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄",
            "█ ▪▪▪▪▪▪▪▪▪▪ █",
            "█ ▪▪▪▪▪▪▪▪▪▪ █",
            "█   ▄▄▄▄▄▄▄   █",
            "▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀",
        ],
        "mouse" => &[
            "  ▄▀▀▀▄  ",
            " █  █  █ ",
            " █▄▄▄▄▄█ ",
            " █     █ ",
            "  ▀▄▄▄▀  ",
        ],
        "phone" => &[
            " ▄▄▄▄▄▄▄ ",
            " █ ▀▀▀ █ ",
            " █     █ ",
            " █     █ ",
            " █▄▄○▄▄█ ",
        ],
        "speaker" => &[
            " ▄▄▄▄▄▄▄ ",
            " █  ○  █ ",
            " █ ▄▀▄ █ ",
            " █ ▀▄▀ █ ",
            " ▀▀▀▀▀▀▀ ",
        ],
        _ => &["   ▄    ", "  █▀▄   ", "▀▄█▄▀   ", "▄▀█▀▄   ", "  █▄▀   "],
    }
}

/// Battery cells: n segments in the level's colour.
pub fn cells(pct: Option<u8>, n: usize, pal: &Pal) -> Vec<Span<'static>> {
    let Some(p) = pct else {
        return vec![Span::styled("·".repeat(n), st(pal.faint))];
    };
    let lit = ((p as usize * n + 50) / 100).clamp(if p > 0 { 1 } else { 0 }, n);
    let c = if p <= CRITICAL {
        pal.danger
    } else if p <= LOW {
        pal.warn
    } else {
        pal.primary
    };
    vec![
        Span::styled("▮".repeat(lit), st(c)),
        Span::styled("▯".repeat(n - lit), st(pal.faint)),
        Span::styled(format!(" {p:>3}%"), st(c)),
    ]
}

/// Signal strength, four rising bars.
pub fn signal(rssi: Option<i32>, pal: &Pal) -> Span<'static> {
    let Some(r) = rssi else {
        return Span::styled("    ", st(pal.faint));
    };
    let got = ((r + 100) as f32 / 12.0).round().clamp(1.0, 4.0) as usize;
    let bars = ["▂", "▄", "▆", "█"];
    let s: String = bars
        .iter()
        .enumerate()
        .map(|(i, b)| if i < got { *b } else { "·" })
        .collect();
    Span::styled(s, st(pal.soft))
}

fn state_word(app: &App, d: &Device) -> (String, Color) {
    let p = &app.pal;
    if let Some(op) = app.busy.get(&d.mac) {
        return (format!("{}…", op.to_uppercase()), p.warn);
    }
    if !d.paired {
        return ("NEARBY".into(), p.soft);
    }
    if d.connected {
        ("CONNECTED".into(), p.primary)
    } else {
        ("PAIRED".into(), p.muted)
    }
}

pub fn draw(f: &mut Frame, app: &mut App) {
    let pal = app.pal;
    let area = f.area();
    f.render_widget(Block::new().style(Style::new().bg(pal.void)), area);
    let [head, body, msg, foot] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Min(8),
        Constraint::Length(1),
        Constraint::Length(1),
    ])
    .areas(area);
    header(f, head, app);
    match app.screen.clone() {
        Screen::Devices => devices(f, body, app),
        Screen::Device(mac) => device(f, body, app, &mac),
        Screen::Wizard(_) => wizard(f, body, app),
        Screen::Trouble => trouble(f, body, app),
    }
    if let Some((text, error)) = &app.msg {
        f.render_widget(
            Paragraph::new(Span::styled(
                format!(" {text}"),
                st(if *error { pal.danger } else { pal.primary }),
            )),
            msg,
        );
    }
    footer(f, foot, app);
    if app.help {
        help(f, area, app);
    }
    if app.prompt.is_some() {
        prompt(f, area, app);
    }
}

fn header(f: &mut Frame, r: Rect, app: &App) {
    let p = &app.pal;
    let mut spans = vec![Span::styled(
        " BLUETOOTH ",
        Style::new()
            .fg(p.void)
            .bg(p.primary)
            .add_modifier(Modifier::BOLD),
    )];
    match &app.state.adapter {
        None => spans.push(Span::styled(
            if app.state.available {
                "  no adapter"
            } else {
                "  bluetoothd isn't running"
            },
            st(p.danger),
        )),
        Some(a) => {
            spans.push(Span::styled(
                format!(
                    "  {}",
                    if a.alias.is_empty() {
                        &a.name
                    } else {
                        &a.alias
                    }
                ),
                st(p.soft),
            ));
            spans.push(Span::styled(
                if a.powered { "  ON" } else { "  OFF" },
                st(if a.powered { p.primary } else { p.muted }).add_modifier(Modifier::BOLD),
            ));
            if a.discovering {
                let blink = app.still || app.tick % 10 < 6;
                spans.push(Span::styled(
                    "  SCANNING",
                    st(if blink { p.warn } else { p.dim }),
                ));
            }
            let n = app.state.devices.iter().filter(|d| d.connected).count();
            if n > 0 {
                spans.push(Span::styled(format!("  {n} connected"), st(p.muted)));
            }
        }
    }
    if !app.filter.is_empty() || matches!(app.edit, Some((Edit::Search, _))) {
        spans.push(Span::styled(format!("  /{}", app.filter), st(p.warn)));
    }
    f.render_widget(
        Paragraph::new(Line::from(spans)).style(Style::new().bg(p.panel)),
        r,
    );
}

fn footer(f: &mut Frame, r: Rect, app: &App) {
    let p = &app.pal;
    let keys: &[(&str, &str)] = match (&app.screen, &app.edit) {
        (_, Some((Edit::Search, _))) => &[("type", "filter"), ("enter", "keep"), ("esc", "clear")],
        (_, Some((Edit::Rename(_), _))) => &[
            ("type", "the new name"),
            ("enter", "save"),
            ("esc", "cancel"),
        ],
        (Screen::Devices, _) => &[
            ("j/k", "move"),
            ("enter", "open"),
            ("c", "connect"),
            ("s", "scan"),
            ("p", "pair"),
            ("/", "search"),
            ("?", "help"),
            ("q", "quit"),
            ("o", "on/off"),
            ("x", "trouble"),
        ],
        (Screen::Device(_), _) => &[
            ("c", "connect"),
            ("t", "auto"),
            ("r", "rename"),
            ("f", "forget"),
            ("R", "re-pair"),
            ("esc", "back"),
            ("?", "help"),
        ],
        (Screen::Wizard(_), _) => &[
            ("j/k", "choose"),
            ("enter", "next"),
            ("s", "scan"),
            ("esc", "back"),
        ],
        (Screen::Trouble, _) => &[
            ("a", "reset adapter"),
            ("o", "on/off"),
            ("e", "clear errors"),
            ("esc", "back"),
        ],
    };
    let mut spans = vec![];
    for (k, w) in keys {
        spans.push(Span::styled(
            format!(" {k} "),
            Style::new().fg(p.void).bg(p.dim),
        ));
        spans.push(Span::styled(format!(" {w}  "), st(p.muted)));
    }
    f.render_widget(
        Paragraph::new(Line::from(spans)).style(Style::new().bg(p.void)),
        r,
    );
}

fn devices(f: &mut Frame, r: Rect, app: &mut App) {
    let p = app.pal;
    let [left, right] =
        Layout::horizontal([Constraint::Percentage(60), Constraint::Percentage(40)]).areas(r);
    let block = frame("DEVICES", &p);
    let inner = block.inner(left);
    f.render_widget(block, left);
    let list = app.listed();
    let mut lines: Vec<Line> = vec![];
    let mut macs = vec![];
    let mut nearby_head = false;
    if !app.state.devices.iter().any(|d| d.paired) {
        lines.push(Line::from(Span::styled(
            " Nothing paired yet: p pairs a device",
            st(p.muted),
        )));
        macs.push(String::new());
    }
    for (i, d) in list.iter().enumerate() {
        if !d.paired && !nearby_head {
            nearby_head = true;
            lines.push(Line::from(Span::styled(
                " NEARBY",
                st(p.muted).add_modifier(Modifier::BOLD),
            )));
            macs.push(String::new());
        }
        let selected = i == app.sel;
        let (word, wc) = state_word(app, d);
        let name_c = if d.connected {
            p.white
        } else if d.paired {
            p.text
        } else {
            p.soft
        };
        let mut spans = vec![
            Span::styled(if selected { "▌" } else { " " }, st(p.primary)),
            Span::styled(
                format!("{:<9}", tag(&d.glyph)),
                st(if d.connected { p.primary } else { p.dim }),
            ),
            Span::styled(
                format!("{:<24.24}", d.name),
                st(name_c).add_modifier(if selected {
                    Modifier::BOLD
                } else {
                    Modifier::empty()
                }),
            ),
            Span::styled(format!(" {word:<13.13}"), st(wc)),
        ];
        if d.paired {
            spans.extend(cells(d.battery, 5, &p));
        } else {
            spans.push(signal(d.rssi, &p));
        }
        let mut line = Line::from(spans);
        if selected {
            line = line.style(Style::new().bg(p.selection));
        }
        lines.push(line);
        macs.push(d.mac.clone());
    }
    // the rows' screen positions, for the mouse (scrolled so the selection shows)
    let h = inner.height as usize;
    let sel_line = macs
        .iter()
        .position(|m| list.get(app.sel).is_some_and(|d| &d.mac == m))
        .unwrap_or(0);
    let top = sel_line.saturating_sub(h.saturating_sub(1));
    app.rows_at = (inner, macs.iter().skip(top).take(h).cloned().collect());
    f.render_widget(Paragraph::new(lines).scroll((top as u16, 0)), inner);
    // the right: the radar while scanning, then the selected device
    let block = frame(
        if app.state.scanning() {
            "SCAN"
        } else {
            "DEVICE"
        },
        &p,
    );
    let inner = block.inner(right);
    f.render_widget(block, right);
    let sel = app.selected();
    if app.state.scanning() {
        let [scope, words, rest] = Layout::vertical([
            Constraint::Length(9),
            Constraint::Length(3),
            Constraint::Min(1),
        ])
        .areas(inner);
        radar(f, scope, app);
        f.render_widget(
            Paragraph::new(scan_words(app)).wrap(Wrap { trim: true }),
            words,
        );
        if let Some(d) = sel {
            summary(f, rest, app, &d);
        }
    } else if let Some(d) = sel {
        summary(f, inner, app, &d);
    } else {
        f.render_widget(
            Paragraph::new("No devices yet.\n\np starts pairing: it says how to put\nthe device in pairing mode, then scans.")
                .style(st(p.muted))
                .wrap(Wrap { trim: false }),
            inner,
        );
    }
}

fn glyph_lines(app: &App, d: &Device) -> Vec<Line<'static>> {
    let p = &app.pal;
    let busy = app.busy.contains_key(&d.mac);
    let pulse = busy && !app.still && app.tick % 8 < 4;
    let c = if busy {
        if pulse { p.white } else { p.warn }
    } else if d.connected {
        p.primary
    } else {
        p.dim
    };
    let m = if d.connected {
        Modifier::BOLD
    } else {
        Modifier::empty()
    };
    art(&d.glyph)
        .iter()
        .map(|l| Line::from(Span::styled(l.to_string(), st(c).add_modifier(m))))
        .collect()
}

fn facts(app: &App, d: &Device) -> Vec<Line<'static>> {
    let p = &app.pal;
    let (word, wc) = state_word(app, d);
    let mut v = vec![
        Line::from(Span::styled(
            d.name.clone(),
            st(p.white).add_modifier(Modifier::BOLD),
        )),
        Line::from(vec![
            Span::styled(format!("{} · ", plain_kind(&d.kind)), st(p.muted)),
            Span::styled(word, st(wc)),
        ]),
    ];
    if d.battery.is_some() {
        let mut s = vec![Span::styled("battery ", st(p.muted))];
        s.extend(cells(d.battery, 10, p));
        v.push(Line::from(s));
    }
    if d.rssi.is_some() {
        v.push(Line::from(vec![
            Span::styled("signal  ", st(p.muted)),
            signal(d.rssi, p),
        ]));
    }
    if let Some(c) = app.state.audio.get(&d.mac) {
        let mode = match c.mode.as_deref() {
            Some("hifi") => "HI-FI",
            Some("headset") => "HEADSET + MIC",
            Some("off") => "NO SOUND",
            _ => "",
        };
        v.push(Line::from(vec![
            Span::styled("sound   ", st(p.muted)),
            Span::styled(mode.to_string(), st(p.soft)),
            Span::styled(
                c.codec
                    .as_deref()
                    .map(|x| format!(" · {x}"))
                    .unwrap_or_default(),
                st(p.soft),
            ),
        ]));
    }
    if d.paired {
        v.push(Line::from(Span::styled(
            if d.trusted {
                "auto-reconnect: on"
            } else {
                "auto-reconnect: off (it asks first)"
            },
            st(p.muted),
        )));
    }
    if d.xbox && d.paired && !app.state.xpadneo {
        v.push(Line::from(Span::styled(
            "basic driver: rumble and battery need xpadneo",
            st(p.warn),
        )));
        v.push(Line::from(Span::styled(
            "  bromigos peripheral enable xbox-controller",
            st(p.soft),
        )));
    }
    v.push(Line::from(Span::styled(d.mac.clone(), st(p.faint))));
    v
}

fn summary(f: &mut Frame, r: Rect, app: &App, d: &Device) {
    let mut lines = glyph_lines(app, d);
    lines.push(Line::from(""));
    lines.extend(facts(app, d));
    f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), r);
}

/// Where a nearby device sits on the radar: its angle from its address, its distance from
/// its signal.
pub fn blip_at(mac: &str, rssi: Option<i32>) -> (f64, f64) {
    let h = mac
        .bytes()
        .fold(2166136261u32, |h, b| (h ^ b as u32).wrapping_mul(16777619));
    let a = (h % 3600) as f64 / 3600.0 * 2.0 * PI;
    let r = match rssi {
        Some(v) => (((-v) as f64 - 35.0) / 60.0).clamp(0.22, 0.92),
        None => 0.9,
    };
    (r * a.cos(), r * a.sin())
}

fn radar(f: &mut Frame, r: Rect, app: &App) {
    let p = app.pal;
    let sweep = (app.tick as f64 * 0.18) % (2.0 * PI);
    let nearby: Vec<(String, Option<i32>, u64)> = app
        .state
        .devices
        .iter()
        .filter(|d| !d.paired && (!d.alias.is_empty() || d.rssi.is_some()))
        .map(|d| (d.mac.clone(), d.rssi, *app.seen.get(&d.mac).unwrap_or(&0)))
        .collect();
    let still = app.still;
    let tick = app.tick;
    let n = nearby.len();
    let side = (r.height * 2).min(r.width);
    let area = Rect {
        x: r.x,
        y: r.y,
        width: side,
        height: r.height,
    };
    let canvas = Canvas::default()
        .marker(Marker::Braille)
        .x_bounds([-1.05, 1.05])
        .y_bounds([-1.05, 1.05])
        .background_color(p.panel)
        .paint(move |ctx| {
            for (rad, c) in [(1.0, p.dim), (0.66, p.faint), (0.33, p.faint)] {
                ctx.draw(&Circle {
                    x: 0.0,
                    y: 0.0,
                    radius: rad,
                    color: c,
                });
            }
            ctx.draw(&CLine {
                x1: -1.0,
                y1: 0.0,
                x2: 1.0,
                y2: 0.0,
                color: p.faint,
            });
            ctx.draw(&CLine {
                x1: 0.0,
                y1: -1.0,
                x2: 0.0,
                y2: 1.0,
                color: p.faint,
            });
            if !still {
                for i in 0..6 {
                    let a = sweep - i as f64 * 0.06;
                    let c = if i == 0 { p.primary } else { p.dim };
                    ctx.draw(&CLine {
                        x1: 0.0,
                        y1: 0.0,
                        x2: a.cos(),
                        y2: a.sin(),
                        color: c,
                    });
                }
            }
            ctx.layer();
            for (mac, rssi, first) in &nearby {
                let (x, y) = blip_at(mac, *rssi);
                let fresh = !still && tick.saturating_sub(*first) < 12;
                ctx.draw(&Points {
                    coords: &[(x, y)],
                    color: if fresh { p.white } else { p.primary },
                });
                if fresh {
                    let rr = 0.04 + tick.saturating_sub(*first) as f64 * 0.01;
                    ctx.draw(&Circle {
                        x,
                        y,
                        radius: rr,
                        color: p.soft,
                    });
                }
            }
        });
    f.render_widget(canvas, area);
    let _ = n;
}

/// How many the scan found, and what to do.
fn scan_words(app: &App) -> Vec<Line<'static>> {
    let p = &app.pal;
    let n = app
        .state
        .devices
        .iter()
        .filter(|d| !d.paired && (!d.alias.is_empty() || d.rssi.is_some()))
        .count();
    vec![
        Line::from(Span::styled(
            format!("SCANNING · {n} FOUND"),
            st(p.soft).add_modifier(Modifier::BOLD),
        )),
        Line::from(Span::styled(
            "Put the device in pairing mode, then pick it.",
            st(p.muted),
        )),
    ]
}

fn device(f: &mut Frame, r: Rect, app: &App, mac: &str) {
    let p = app.pal;
    let Some(d) = app.state.find(mac).cloned() else {
        f.render_widget(Paragraph::new("That device is gone.").style(st(p.muted)), r);
        return;
    };
    let [left, right] =
        Layout::horizontal([Constraint::Percentage(42), Constraint::Percentage(58)]).areas(r);
    let block = frame("DEVICE", &p);
    let inner = block.inner(left);
    f.render_widget(block, left);
    let mut lines = glyph_lines(app, &d);
    lines.push(Line::from(""));
    lines.extend(facts(app, &d));
    if app.forget.as_deref() == Some(mac) {
        lines.push(Line::from(""));
        lines.push(Line::from(Span::styled(
            "Forget it? y forgets, any other key keeps it",
            st(p.danger),
        )));
    }
    if let Some((Edit::Rename(_), text)) = &app.edit {
        lines.push(Line::from(""));
        lines.push(Line::from(vec![
            Span::styled("new name: ", st(p.muted)),
            Span::styled(format!("{text}▏"), st(p.white)),
        ]));
    }
    f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), inner);

    let title = match d.glyph.as_str() {
        "controller" => "INPUT TEST",
        "headset" | "earbuds" | "speaker" => "SOUND",
        _ => "ACTIONS",
    };
    let block = frame(title, &p);
    let inner = block.inner(right);
    f.render_widget(block, right);
    let mut acts: Vec<(&str, String)> = vec![
        (
            "c",
            if d.connected {
                "disconnect".into()
            } else {
                "connect".into()
            },
        ),
        (
            "t",
            format!(
                "auto-reconnect: {}",
                if d.trusted {
                    "on → off"
                } else {
                    "off → on"
                }
            ),
        ),
        ("r", "rename".into()),
        ("f", "forget (unpair)".into()),
        ("R", "re-pair: forget it, then pair again".into()),
    ];
    let card = app.state.audio.get(mac);
    if d.glyph == "controller" {
        acts.insert(1, ("u", "rumble".into()));
    }
    if card.is_some() {
        let next = if card.and_then(|c| c.mode.as_deref()) == Some("headset") {
            "HI-FI (music, no mic)"
        } else {
            "HEADSET + MIC (calls: lower quality)"
        };
        acts.insert(1, ("m", format!("switch to {next}")));
        acts.insert(2, ("o", "make it the sound output".into()));
        acts.insert(3, ("i", "make it the microphone".into()));
        acts.insert(
            4,
            (
                "v",
                if app.mic.is_some() {
                    "stop the mic test".into()
                } else {
                    "test the mic".into()
                },
            ),
        );
    }
    let mut lines: Vec<Line> = acts
        .iter()
        .map(|(k, w)| {
            Line::from(vec![
                Span::styled(format!(" {k} "), Style::new().fg(p.void).bg(p.dim)),
                Span::styled(format!(" {w}"), st(p.text)),
            ])
        })
        .collect();
    let [top, bottom] = Layout::vertical([
        Constraint::Length(lines.len() as u16 + 1),
        Constraint::Min(1),
    ])
    .areas(inner);
    lines.push(Line::from(""));
    f.render_widget(Paragraph::new(lines), top);
    if d.glyph == "controller" {
        tester(f, bottom, app, &d);
    } else if let Some(level) = app.mic {
        let w = bottom.width.saturating_sub(12) as usize;
        let lit = (level.clamp(0.0, 1.0) * w as f32).round() as usize;
        let c = if level > 0.9 {
            p.danger
        } else if level > 0.75 {
            p.warn
        } else {
            p.primary
        };
        f.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled("MIC LEVEL · speak into it", st(p.muted))),
                Line::from(vec![
                    Span::styled("▮".repeat(lit), st(c)),
                    Span::styled("▯".repeat(w - lit), st(p.faint)),
                ]),
            ]),
            bottom,
        );
    }
}

fn tester(f: &mut Frame, r: Rect, app: &App, d: &Device) {
    let p = app.pal;
    let Some(inp) = app.input.as_ref().filter(|i| i.mac == d.mac) else {
        f.render_widget(
            Paragraph::new("Connect it to test its buttons and sticks.").style(st(p.muted)),
            r,
        );
        return;
    };
    if let Some(e) = &inp.error {
        f.render_widget(
            Paragraph::new(e.as_str())
                .style(st(p.warn))
                .wrap(Wrap { trim: true }),
            r,
        );
        return;
    }
    let on = |b: &str| inp.buttons.iter().any(|x| x == b);
    let key = |b: &'static str| -> Span<'static> {
        if on(b) {
            Span::styled(
                format!(" {b} "),
                Style::new()
                    .fg(p.void)
                    .bg(p.primary)
                    .add_modifier(Modifier::BOLD),
            )
        } else {
            Span::styled(format!(" {b} "), st(p.dim))
        }
    };
    let bar = |v: f32, w: usize| -> Vec<Span<'static>> {
        let lit = (v.clamp(0.0, 1.0) * w as f32).round() as usize;
        vec![
            Span::styled("▮".repeat(lit), st(p.primary)),
            Span::styled("▯".repeat(w - lit), st(p.faint)),
        ]
    };
    let a = &inp.axes;
    let mut l1 = vec![Span::styled("LT ", st(p.muted))];
    l1.extend(bar(a.lt, 8));
    l1.push(Span::raw("   "));
    l1.push(Span::styled("RT ", st(p.muted)));
    l1.extend(bar(a.rt, 8));
    let lines = vec![
        Line::from("Press anything: it lights up here."),
        Line::from(l1),
        Line::from(vec![
            key("LB"),
            Span::raw("  "),
            key("VIEW"),
            key("XBOX"),
            key("MENU"),
            Span::raw("  "),
            key("RB"),
        ]),
        Line::from(vec![
            key("UP"),
            Span::raw("         "),
            key("Y"),
            Span::raw("   "),
            key("SHARE"),
        ]),
        Line::from(vec![
            key("LEFT"),
            key("RIGHT"),
            Span::raw("  "),
            key("X"),
            key("B"),
        ]),
        Line::from(vec![key("DOWN"), Span::raw("         "), key("A")]),
        Line::from(vec![
            key("LS"),
            Span::styled(format!(" {:+.2} {:+.2}", a.lx, a.ly), st(p.soft)),
            Span::raw("   "),
            key("RS"),
            Span::styled(format!(" {:+.2} {:+.2}", a.rx, a.ry), st(p.soft)),
        ]),
    ];
    let [words, sticks] =
        Layout::vertical([Constraint::Length(lines.len() as u16), Constraint::Min(4)]).areas(r);
    f.render_widget(Paragraph::new(lines).style(st(p.text)), words);
    let [ls, rs] = Layout::horizontal([
        Constraint::Length(sticks.height.min(8) * 2),
        Constraint::Length(sticks.height.min(8) * 2),
    ])
    .spacing(2)
    .areas(sticks);
    for (area, x, y) in [(ls, a.lx, a.ly), (rs, a.rx, a.ry)] {
        let (x, y) = (x as f64, -(y as f64));
        f.render_widget(
            Canvas::default()
                .marker(Marker::Braille)
                .x_bounds([-1.1, 1.1])
                .y_bounds([-1.1, 1.1])
                .paint(move |ctx| {
                    ctx.draw(&Circle {
                        x: 0.0,
                        y: 0.0,
                        radius: 1.0,
                        color: p.dim,
                    });
                    ctx.draw(&CLine {
                        x1: 0.0,
                        y1: 0.0,
                        x2: x,
                        y2: y,
                        color: p.soft,
                    });
                    ctx.draw(&Circle {
                        x,
                        y,
                        radius: 0.12,
                        color: p.primary,
                    });
                }),
            area,
        );
    }
}

fn wizard(f: &mut Frame, r: Rect, app: &App) {
    let p = app.pal;
    let Screen::Wizard(w) = &app.screen else {
        return;
    };
    let steps = ["1 KIND", "2 PAIRING MODE + SCAN", "3 PAIR", "4 READY"];
    let at = match w.step {
        Step::Kind => 0,
        Step::Scan => 1,
        Step::Pairing | Step::Failed(_) => 2,
        Step::Ready => 3,
    };
    let block = frame("PAIR A DEVICE", &p);
    let inner = block.inner(r);
    f.render_widget(block, r);
    let [crumbs, body] = Layout::vertical([Constraint::Length(2), Constraint::Min(4)]).areas(inner);
    let mut s = vec![];
    for (i, name) in steps.iter().enumerate() {
        let c = if i == at {
            p.primary
        } else if i < at {
            p.soft
        } else {
            p.faint
        };
        s.push(Span::styled(
            format!(" {name} "),
            st(c).add_modifier(if i == at {
                Modifier::BOLD
            } else {
                Modifier::empty()
            }),
        ));
        if i + 1 < steps.len() {
            s.push(Span::styled("›", st(p.faint)));
        }
    }
    f.render_widget(Paragraph::new(Line::from(s)), crumbs);
    let (_, glyph, how) = KINDS[w.kind.min(KINDS.len() - 1)];
    match &w.step {
        Step::Kind => {
            let mut lines = vec![
                Line::from(Span::styled(
                    "What are you pairing?",
                    st(p.white).add_modifier(Modifier::BOLD),
                )),
                Line::from(""),
            ];
            for (i, (name, _, _)) in KINDS.iter().enumerate() {
                let sel = i == w.kind;
                lines.push(Line::from(vec![
                    Span::styled(if sel { " ▌ " } else { "   " }, st(p.primary)),
                    Span::styled(
                        name.to_string(),
                        st(if sel { p.white } else { p.text }).add_modifier(if sel {
                            Modifier::BOLD
                        } else {
                            Modifier::empty()
                        }),
                    ),
                ]));
            }
            lines.push(Line::from(""));
            lines.push(Line::from(Span::styled(
                "How to put it in pairing mode:",
                st(p.muted),
            )));
            lines.extend(
                how.iter()
                    .map(|l| Line::from(Span::styled(l.to_string(), st(p.soft)))),
            );
            f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), body);
        }
        Step::Scan => {
            let [top, list] =
                Layout::vertical([Constraint::Length(10), Constraint::Min(3)]).areas(body);
            let [rad, how_r] = Layout::horizontal([Constraint::Length(20), Constraint::Min(10)])
                .spacing(2)
                .areas(top);
            radar(f, rad, app);
            let mut hl: Vec<Line> = scan_words(app);
            hl.push(Line::from(""));
            hl.push(Line::from(Span::styled("Pairing mode:", st(p.muted))));
            hl.extend(
                how.iter()
                    .map(|l| Line::from(Span::styled(l.to_string(), st(p.soft)))),
            );
            f.render_widget(Paragraph::new(hl).wrap(Wrap { trim: false }), how_r);
            let found = app.found(w.kind);
            let mut lines = vec![Line::from(Span::styled(
                if found.is_empty() {
                    "Looking… nothing yet. Is it in pairing mode?".to_string()
                } else {
                    format!("Found {}: pick it, then enter", found.len())
                },
                st(p.muted),
            ))];
            for (i, d) in found.iter().enumerate() {
                let sel = i == w.pick;
                let fits = d.glyph == glyph || (glyph == "headset" && d.glyph == "earbuds");
                let mut line = Line::from(vec![
                    Span::styled(if sel { "▌" } else { " " }, st(p.primary)),
                    Span::styled(
                        format!("{:<9}", tag(&d.glyph)),
                        st(if fits { p.primary } else { p.dim }),
                    ),
                    Span::styled(
                        format!("{:<28.28}", d.name),
                        st(if sel { p.white } else { p.text }),
                    ),
                    signal(d.rssi, &p),
                ]);
                if sel {
                    line = line.style(Style::new().bg(p.selection));
                }
                lines.push(line);
            }
            f.render_widget(Paragraph::new(lines), list);
        }
        Step::Pairing => {
            let name = w
                .mac
                .as_deref()
                .and_then(|m| app.state.find(m))
                .map(|d| d.name.clone())
                .unwrap_or_default();
            let dots = if app.still {
                "…".to_string()
            } else {
                ".".repeat((app.tick as usize / 3) % 4)
            };
            let lines = vec![
                Line::from(Span::styled(
                    format!("Pairing with {name}"),
                    st(p.white).add_modifier(Modifier::BOLD),
                )),
                Line::from(""),
                Line::from(Span::styled(
                    format!(
                        "{}{dots}",
                        match w.doing.as_str() {
                            "trusting" => "Saving it, so it reconnects by itself",
                            "connecting" => "Connecting",
                            _ => "Pairing",
                        }
                    ),
                    st(p.warn),
                )),
                Line::from(""),
                Line::from(Span::styled(
                    "If it asks for a code, a box opens here. esc stops.",
                    st(p.muted),
                )),
            ];
            f.render_widget(Paragraph::new(lines), body);
        }
        Step::Ready => {
            let name = w
                .mac
                .as_deref()
                .and_then(|m| app.state.find(m))
                .map(|d| d.name.clone())
                .unwrap_or_default();
            let mut lines: Vec<Line> = w
                .mac
                .as_deref()
                .and_then(|m| app.state.find(m))
                .map(|d| glyph_lines(app, d))
                .unwrap_or_default();
            lines.push(Line::from(""));
            lines.push(Line::from(Span::styled(
                format!("READY · {name} is paired and connected"),
                st(p.primary).add_modifier(Modifier::BOLD),
            )));
            lines.push(Line::from(Span::styled(
                "It reconnects by itself when it's switched on. enter opens it.",
                st(p.soft),
            )));
            f.render_widget(Paragraph::new(lines), body);
        }
        Step::Failed(e) => {
            let lines = vec![
                Line::from(Span::styled(
                    "NOT PAIRED",
                    st(p.danger).add_modifier(Modifier::BOLD),
                )),
                Line::from(""),
                Line::from(Span::styled(e.clone(), st(p.text))),
                Line::from(""),
                Line::from(Span::styled(
                    "enter: scan and try again · esc: back",
                    st(p.muted),
                )),
            ];
            f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), body);
        }
    }
}

fn trouble(f: &mut Frame, r: Rect, app: &App) {
    let p = app.pal;
    let block = frame("TROUBLESHOOT", &p);
    let inner = block.inner(r);
    f.render_widget(block, r);
    let s = &app.state;
    let yes = |b: bool, good: bool| -> Span<'static> {
        Span::styled(
            if b { "yes" } else { "no" },
            st(if b == good { p.primary } else { p.warn }),
        )
    };
    let mut lines = vec![
        Line::from(vec![
            Span::styled("bluetoothd running      ", st(p.muted)),
            yes(s.available, true),
        ]),
        Line::from(vec![
            Span::styled("an adapter              ", st(p.muted)),
            yes(s.adapter.is_some(), true),
        ]),
        Line::from(vec![
            Span::styled("switched on             ", st(p.muted)),
            yes(s.powered(), true),
        ]),
        Line::from(vec![
            Span::styled("blocked (rfkill)        ", st(p.muted)),
            yes(s.blocked, false),
        ]),
        Line::from(vec![
            Span::styled("hardware switch off     ", st(p.muted)),
            yes(s.hard_blocked, false),
        ]),
        Line::from(vec![
            Span::styled("xpadneo (Xbox driver)   ", st(p.muted)),
            yes(s.xpadneo, true),
        ]),
        Line::from(""),
    ];
    if !s.available {
        lines.push(Line::from(Span::styled(
            "Start the service: sudo systemctl enable --now bluetooth",
            st(p.soft),
        )));
    }
    lines.push(Line::from(Span::styled(
        "a  reset the adapter: off, the rfkill block lifted, on again",
        st(p.text),
    )));
    lines.push(Line::from(Span::styled(
        "R  on a device's page: forget it and pair it again",
        st(p.text),
    )));
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "WHAT WENT WRONG LATELY",
        st(p.muted).add_modifier(Modifier::BOLD),
    )));
    if app.errors.is_empty() {
        lines.push(Line::from(Span::styled("nothing", st(p.faint))));
    }
    for e in app.errors.iter().rev().take(8) {
        lines.push(Line::from(Span::styled(format!("· {e}"), st(p.danger))));
    }
    f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), inner);
}

fn centred(area: Rect, w: u16, h: u16) -> Rect {
    let w = w.min(area.width);
    let h = h.min(area.height);
    Rect {
        x: area.x + (area.width - w) / 2,
        y: area.y + (area.height - h) / 2,
        width: w,
        height: h,
    }
}

fn help(f: &mut Frame, area: Rect, app: &App) {
    let p = app.pal;
    let r = centred(area, 64, 22);
    f.render_widget(Clear, r);
    let rows: &[(&str, &str)] = &[
        ("j k  ↑ ↓", "move"),
        ("enter  l", "open a device (pair one that's nearby)"),
        ("esc  h  q", "back; q on the list quits"),
        ("/", "search by name or kind"),
        ("s", "scan for devices nearby"),
        ("p  a", "pair: step by step"),
        ("c", "connect or disconnect"),
        ("o", "Bluetooth on or off"),
        ("x", "troubleshoot"),
        (
            "t  r  f  R",
            "on a device: auto-reconnect, rename, forget, re-pair",
        ),
        ("u", "a controller: rumble"),
        (
            "m  o  i  v",
            "headphones: profile, output, microphone, mic test",
        ),
        ("mouse", "click selects, a second click opens; scroll moves"),
        ("?", "this help (any key closes it)"),
    ];
    let mut lines = vec![];
    for (k, w) in rows {
        lines.push(Line::from(vec![
            Span::styled(format!("{k:<12}"), st(p.primary)),
            Span::styled(w.to_string(), st(p.text)),
        ]));
    }
    f.render_widget(Paragraph::new(lines).block(frame("KEYS", &p)), r);
}

fn prompt(f: &mut Frame, area: Rect, app: &App) {
    let p = app.pal;
    let Some(q) = &app.prompt else { return };
    let name = if q.name.is_empty() {
        q.mac.clone()
    } else {
        q.name.clone()
    };
    let code = |v: &str| {
        if v.len() == 6 {
            format!("{} {}", &v[..3], &v[3..])
        } else {
            v.to_string()
        }
    };
    let (title, lines): (String, Vec<Line>) = match q.what.as_str() {
        "confirm" => (
            format!("PAIR {name}"),
            vec![
                Line::from(Span::styled(format!("Does {name} show"), st(p.text))),
                Line::from(Span::styled(
                    code(q.value.as_str().unwrap_or("")),
                    st(p.white).add_modifier(Modifier::BOLD),
                )),
                Line::from(""),
                Line::from(Span::styled(
                    "y: yes, pair · n: no · esc: stop",
                    st(p.muted),
                )),
            ],
        ),
        "pin" | "passkey" => (
            format!("CODE FOR {name}"),
            vec![
                Line::from(Span::styled(
                    if q.what == "pin" {
                        "Type the PIN it asks for (often 0000 or 1234)"
                    } else {
                        "Type the 6-digit number it shows"
                    },
                    st(p.text),
                )),
                Line::from(Span::styled(
                    format!("{}▏", q.typed),
                    st(p.white).add_modifier(Modifier::BOLD),
                )),
                Line::from(""),
                Line::from(Span::styled("enter: send · esc: stop", st(p.muted))),
            ],
        ),
        "type" => {
            let v = q
                .value
                .get(0)
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string();
            (
                format!("TYPE ON {name}"),
                vec![
                    Line::from(Span::styled(format!("On {name}, type"), st(p.text))),
                    Line::from(Span::styled(
                        code(&v),
                        st(p.white).add_modifier(Modifier::BOLD),
                    )),
                    Line::from(Span::styled("then press Enter on it.", st(p.text))),
                    Line::from(Span::styled("esc: stop", st(p.muted))),
                ],
            )
        }
        "show-pin" => (
            format!("PIN FOR {name}"),
            vec![
                Line::from(Span::styled(
                    format!("On {name}, enter the PIN"),
                    st(p.text),
                )),
                Line::from(Span::styled(
                    q.value.as_str().unwrap_or("").to_string(),
                    st(p.white).add_modifier(Modifier::BOLD),
                )),
            ],
        ),
        _ => (
            format!("ALLOW {name}?"),
            vec![
                Line::from(Span::styled(format!("{name} asks to pair."), st(p.text))),
                Line::from(Span::styled("y: allow · n: deny", st(p.muted))),
            ],
        ),
    };
    let r = centred(area, 52, lines.len() as u16 + 2);
    f.render_widget(Clear, r);
    f.render_widget(
        Paragraph::new(lines)
            .alignment(Alignment::Center)
            .block(frame(&title, &p).border_style(st(p.primary))),
        r,
    );
}
