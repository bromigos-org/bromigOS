//! Pair with BRODEC (docs/fieldkit-vector.md, "Pair with BRODEC"): this machine (a Field Kit
//! stick or bromigOS Server) as one of the owner's machines in BRODEC, through BRODEC's own
//! agent, `brodec-machine`. The agent pairs, keeps the end-to-end encrypted machine room and
//! enforces the owner and fingerprint rules; this screen shows its pairing code as a QR to scan
//! (LAB › MACHINES › ADD MACHINE), starts the agent once the person approves, and runs the
//! agent's `enroll` when the phone asks to be allowed.

use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::{Duration, Instant};

use bromigos_tui::widgets::{self, Tone, st};
use bromigos_tui::{Look, Mode};
use qrcode::{Color as QrColor, EcLevel, QrCode};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEventKind};
use ratatui::layout::{Alignment, Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use ratatui::{DefaultTerminal, Frame};
use serde_json::{Value, json};

use super::engine_call;

/// A QR code's modules, dark or not, with the four-module quiet zone the standard asks for:
/// (modules across, row by row).
pub fn qr_modules(text: &str) -> Option<(usize, Vec<bool>)> {
    let code = QrCode::with_error_correction_level(text.as_bytes(), EcLevel::M).ok()?;
    let n = code.width();
    let q = 4;
    let w = n + 2 * q;
    let mut out = vec![false; w * w];
    for (i, c) in code.to_colors().iter().enumerate() {
        let (x, y) = (i % n, i / n);
        out[(y + q) * w + x + q] = *c == QrColor::Dark;
    }
    Some((w, out))
}

/// How many cells across (and half-rows down) each module takes so the code fits `cols` x
/// `rows`: the largest of 1 to 3. A half-row is about as tall as a cell is wide, so modules are
/// square on any console font; 0 when even 1 doesn't fit.
pub fn qr_scale(modules: usize, cols: u16, rows: u16) -> usize {
    (1..=3)
        .rev()
        .find(|k| modules * k <= cols as usize && (modules * k).div_ceil(2) <= rows as usize)
        .unwrap_or(0)
}

/// The code as text lines: half blocks, dark modules on light, at `k` per module. High contrast
/// whatever the theme: black on white in 24-bit colour, the console's own black and bright
/// white on the Linux console.
pub fn qr_lines(look: &Look, w: usize, dark: &[bool], k: usize) -> Vec<Line<'static>> {
    let (fg, bg) = if look.mode == Mode::Truecolor {
        (Color::Rgb(0, 0, 0), Color::Rgb(255, 255, 255))
    } else {
        (Color::Black, Color::White)
    };
    let px = w * k;
    let at = |x: usize, y: usize| y < px && dark[(y / k) * w + x / k];
    (0..px.div_ceil(2))
        .map(|row| {
            let s: String = (0..px)
                .map(|x| match (at(x, 2 * row), at(x, 2 * row + 1)) {
                    (true, true) => '█',
                    (true, false) => '▀',
                    (false, true) => '▄',
                    (false, false) => ' ',
                })
                .collect();
            Line::from(Span::styled(s, Style::new().fg(fg).bg(bg)))
        })
        .collect()
}

/// `KPGGZFVT` as `KPGG-ZFVT`, as BRODEC shows it.
pub fn pretty_code(code: &str) -> String {
    let c: String = code.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
    if c.len() == 8 {
        format!("{}-{}", &c[..4], &c[4..])
    } else {
        c
    }
}

enum Reply {
    State(Value),
    Controls(Value),
    Proposed(Value),
    Ran(Value),
}

pub struct Pair {
    pub look: Look,
    engine: PathBuf,
    pub state: Value,
    pub controls: Value,
    /// "Start BRODEC's agent here?" waiting for an answer: the proposal.
    pub asking: Option<Value>,
    pub selected: usize,
    pub note: String,
    pub done: bool,
    pub tick: u64,
    tx: Sender<Reply>,
    rx: Receiver<Reply>,
    /// The person pressed E: the caller runs `brodec-machine enroll` in the terminal.
    pub enroll: bool,
}

impl Pair {
    pub fn new(look: Look, engine: &Path) -> Pair {
        let (tx, rx) = mpsc::channel();
        Pair {
            look,
            engine: engine.to_path_buf(),
            state: json!({}),
            controls: json!([]),
            asking: None,
            selected: 1,
            note: String::new(),
            done: false,
            tick: 0,
            tx,
            rx,
            enroll: false,
        }
    }

    fn call(&self, args: Vec<String>, wrap: fn(Value) -> Reply) {
        let (tx, engine) = (self.tx.clone(), self.engine.clone());
        thread::spawn(move || {
            let a: Vec<&str> = args.iter().map(|s| s.as_str()).collect();
            let _ = tx.send(wrap(engine_call(&engine, &a, None)));
        });
    }

    pub fn refresh(&self) {
        self.call(vec!["pair".into()], Reply::State);
        self.call(vec!["controls".into()], Reply::Controls);
    }

    pub fn pump(&mut self) {
        while let Ok(r) = self.rx.try_recv() {
            match r {
                Reply::State(v) => self.state = v,
                Reply::Controls(v) => self.controls = v["controls"].clone(),
                Reply::Proposed(v) => {
                    if v["ok"].as_bool() == Some(true) {
                        self.asking = Some(v["proposal"].clone());
                        self.selected = 1;
                    } else {
                        self.note = v["message"].as_str().unwrap_or("").to_string();
                    }
                }
                Reply::Ran(v) => {
                    self.note = v["message"].as_str().unwrap_or("").to_string();
                    self.refresh();
                }
            }
        }
    }

    pub fn key(&mut self, code: KeyCode) {
        if let Some(p) = self.asking.clone() {
            match code {
                KeyCode::Left | KeyCode::Right | KeyCode::Tab => self.selected = 1 - self.selected,
                KeyCode::Char('y') => self.approve(&p),
                KeyCode::Char('n') | KeyCode::Esc => {
                    self.asking = None;
                    self.note = "Not started. Nothing changed.".into();
                }
                KeyCode::Enter if self.selected == 0 => self.approve(&p),
                KeyCode::Enter => {
                    self.asking = None;
                    self.note = "Not started. Nothing changed.".into();
                }
                _ => {}
            }
            return;
        }
        let st = self.state["state"].as_str().unwrap_or("");
        match code {
            KeyCode::Esc | KeyCode::Char('q') => self.done = true,
            KeyCode::Char('p') | KeyCode::Enter if st == "stopped" => {
                self.call(vec!["pair-start".into()], Reply::Proposed)
            }
            KeyCode::Char('e') if st == "paired" || st == "waiting" => self.enroll = true,
            KeyCode::Char('r') => self.refresh(),
            _ => {}
        }
    }

    fn approve(&mut self, p: &Value) {
        let id = p["id"].as_str().unwrap_or("").to_string();
        self.asking = None;
        self.note = "Starting BRODEC's agent…".into();
        self.call(
            vec!["run".into(), id, "--by".into(), "local".into()],
            Reply::Ran,
        );
    }
}

/// The pairing screen.
pub fn draw(f: &mut Frame, app: &Pair) {
    let look = &app.look;
    let p = &look.pal;
    let area = f.area();
    f.render_widget(Paragraph::new("").style(Style::new().bg(p.void)), area);
    let [top, body, status, keys] = Layout::vertical([
        Constraint::Length(2),
        Constraint::Min(6),
        Constraint::Length(1),
        Constraint::Length(1),
    ])
    .areas(area);
    f.render_widget(
        Paragraph::new(vec![
            Line::from(Span::styled(
                " PAIR WITH BRODEC",
                st(p.primary).add_modifier(Modifier::BOLD),
            )),
            Line::from(Span::styled(
                " Home › VECTOR › Pair with BRODEC",
                st(p.muted),
            )),
        ]),
        top,
    );
    let state = app.state["state"].as_str().unwrap_or("");
    let msg = app.state["message"]
        .as_str()
        .unwrap_or("Looking…")
        .to_string();
    let wide = body.width >= 100;
    let [left, right] = if wide {
        Layout::horizontal([Constraint::Percentage(55), Constraint::Percentage(45)]).areas(body)
    } else {
        Layout::vertical([Constraint::Min(4), Constraint::Length(10)]).areas(body)
    };
    // the code, or why there isn't one
    let block = widgets::glass(look, "Scan it in BRODEC", state == "waiting");
    let inner = block.inner(left);
    f.render_widget(block, left);
    let qr_text = app.state["code"]["qr"].as_str().unwrap_or("");
    let mut shown = false;
    if state == "waiting"
        && !look.ascii
        && let Some((w, dark)) = qr_modules(qr_text)
    {
        {
            let k = qr_scale(w, inner.width, inner.height.saturating_sub(2));
            if k > 0 {
                let lines = qr_lines(look, w, &dark, k);
                let h = lines.len() as u16;
                let y = inner.y + (inner.height.saturating_sub(h + 2)) / 2;
                let x = inner.x + (inner.width.saturating_sub((w * k) as u16)) / 2;
                f.render_widget(
                    Paragraph::new(lines),
                    Rect::new(x, y, (w * k) as u16, h.min(inner.height)),
                );
                let code = pretty_code(app.state["code"]["user_code"].as_str().unwrap_or(""));
                f.render_widget(
                    Paragraph::new(Line::from(vec![
                        Span::styled("or type ", st(p.muted)),
                        Span::styled(code, st(p.white).add_modifier(Modifier::BOLD)),
                    ]))
                    .alignment(Alignment::Center),
                    Rect::new(
                        inner.x,
                        (y + h + 1).min(inner.bottom().saturating_sub(1)),
                        inner.width,
                        1,
                    ),
                );
                shown = true;
            }
        }
    }
    if !shown {
        let mut text = msg.clone();
        if state == "waiting" {
            text = format!(
                "{msg}\n\nThe code: {}\nAt {}\n\n(The QR needs a bigger screen{}.)",
                pretty_code(app.state["code"]["user_code"].as_str().unwrap_or("")),
                app.state["code"]["verification_uri"].as_str().unwrap_or(""),
                if look.ascii {
                    " and a terminal that draws blocks"
                } else {
                    ""
                }
            );
        }
        f.render_widget(
            Paragraph::new(widgets::wrap_hanging(
                &text,
                inner.width.saturating_sub(2),
                " ",
                " ",
                st(p.text),
            )),
            inner,
        );
    }
    // what pairing gives, and what the phone may do here
    let block = widgets::glass(look, "What pairing gives", false);
    let ri = block.inner(right);
    f.render_widget(block, right);
    let mut t = String::new();
    t.push_str(&format!("{msg}\n\n"));
    if state == "paired" {
        t.push_str("Next, in BRODEC: this machine › ALLOW THIS PHONE (a fingerprint). Then press E here to allow it.\n\n");
    } else {
        t.push_str("In BRODEC: LAB › MACHINES › ADD MACHINE, then scan the code. BRODEC's agent keeps an end-to-end encrypted room with your account; your phone signs every action with its fingerprint key, and STOP ALL ends it all.\n\n");
    }
    t.push_str("From the phone, once allowed:\n");
    for c in app.controls.as_array().into_iter().flatten() {
        let ok = c["available"].as_bool() == Some(true);
        let why = c["why"].as_str().unwrap_or("");
        t.push_str(&format!(
            "{} {}{}\n",
            if ok { "▸" } else { "·" },
            c["title"].as_str().unwrap_or(""),
            if why.is_empty() {
                String::new()
            } else {
                format!(": {why}")
            }
        ));
    }
    t.push_str("VECTOR's proposals and his chat, and the Field Kit console through Herdr.\nEach is approved: on the phone with its fingerprint, or here.");
    f.render_widget(
        Paragraph::new(widgets::wrap_hanging(
            &t,
            ri.width.saturating_sub(2),
            " ",
            " ",
            st(p.muted),
        )),
        ri,
    );
    let tone = match state {
        "paired" => Tone::Good,
        "waiting" | "starting" => Tone::Warn,
        "missing" => Tone::Bad,
        _ => Tone::Calm,
    };
    let mut facts = vec![("BRODEC", state.to_string(), tone)];
    if !app.note.is_empty() {
        facts.push(("", app.note.clone(), Tone::Calm));
    }
    f.render_widget(Paragraph::new(widgets::reading(look, &facts)), status);
    let k = match state {
        "stopped" => " P pair (starts BRODEC's agent, approved first) · ESC back",
        "paired" | "waiting" => " E allow the phone that asked · R refresh · ESC back",
        _ => " R refresh · ESC back",
    };
    f.render_widget(Paragraph::new(Span::styled(k, st(p.muted))), keys);
    if let Some(prop) = &app.asking {
        widgets::confirm(
            f,
            body,
            look,
            "Pair with BRODEC?",
            &format!(
                "{}\n\n{}",
                prop["title"].as_str().unwrap_or(""),
                prop["change"].as_str().unwrap_or("")
            ),
            &["Start it", "Not now"],
            app.selected,
        );
    }
}

/// The pairing screen in a terminal the caller already has (VECTOR's screen hands its own).
pub fn pair_in(terminal: &mut DefaultTerminal, look: &Look, engine: &Path) -> io::Result<()> {
    let mut app = Pair::new(*look, engine);
    app.refresh();
    let mut last = Instant::now();
    while !app.done {
        app.pump();
        if app.enroll {
            app.enroll = false;
            ratatui::restore();
            // BRODEC's own enrolment, at the machine: it shows the phone's key to compare. It
            // needs root: Field Kit's console is root's; anyone else goes through polkit
            // (pkexec asks for the password), never a command to type
            let root = unsafe { libc::geteuid() } == 0;
            let _ = if root {
                Command::new("brodec-machine").arg("enroll").status()
            } else {
                Command::new("pkexec")
                    .args(["brodec-machine", "enroll"])
                    .status()
            };
            *terminal = ratatui::init();
            app.refresh();
        }
        terminal.draw(|f| draw(f, &app))?;
        if event::poll(Duration::from_millis(150))? {
            if let Event::Key(k) = event::read()?
                && k.kind == KeyEventKind::Press
            {
                app.key(k.code);
            }
        } else if app.look.motion {
            app.tick = app.tick.wrapping_add(1);
        }
        if last.elapsed() > Duration::from_secs(3) {
            app.refresh();
            last = Instant::now();
        }
    }
    Ok(())
}

/// Pair with BRODEC: the whole screen until the person leaves it (Esc). The Server section
/// calls this; it takes the terminal itself, as an outside program would.
#[allow(dead_code)]
pub fn pair(look: &Look, engine: &Path) -> io::Result<()> {
    let mut terminal = ratatui::init();
    let r = pair_in(&mut terminal, look, engine);
    ratatui::restore();
    r
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::Terminal;
    use ratatui::backend::TestBackend;
    use std::os::unix::fs::PermissionsExt;

    const URL: &str =
        "https://auth.bromigos.org/device?user_code=KPGGZFVT#machine=k1.3f2a9c0d&n=fieldkit";

    #[test]
    fn the_code_decodes_to_its_url_and_has_a_quiet_zone() {
        let (w, dark) = qr_modules(URL).unwrap();
        assert_eq!(dark.len(), w * w);
        // four light modules all round
        for i in 0..w {
            for q in 0..4 {
                assert!(!dark[q * w + i] && !dark[(w - 1 - q) * w + i]);
                assert!(!dark[i * w + q] && !dark[i * w + w - 1 - q]);
            }
        }
        // the finder pattern's corner, inside the quiet zone
        assert!(dark[4 * w + 4]);
    }

    #[test]
    fn module_size_follows_the_screen() {
        let (w, _) = qr_modules(URL).unwrap();
        // a 1080p console (Geist Mono 24 px: 160 x 45) and a 4K one (32 px: 240 x 67)
        assert!(qr_scale(w, 80, 40) >= 1);
        assert!(qr_scale(w, 140, 60) >= qr_scale(w, 80, 40));
        assert_eq!(qr_scale(w, 20, 10), 0);
        let lines = qr_lines(&Look::wick(), w, &qr_modules(URL).unwrap().1, 2);
        assert_eq!(lines.len(), (w * 2).div_ceil(2));
        assert_eq!(lines[0].width(), w * 2);
    }

    #[test]
    fn pretty_code_like_brodec() {
        assert_eq!(pretty_code("KPGGZFVT"), "KPGG-ZFVT");
    }

    fn fake(dir: &Path, state: &str) -> PathBuf {
        let p = dir.join("fieldkit-engine");
        let exp = 4_102_444_800_000u64;
        let doc = match state {
            "waiting" => format!(
                r#"{{"ok": true, "installed": true, "state": "waiting", "code": {{"user_code": "KPGGZFVT", "verification_uri": "https://auth.bromigos.org/device", "qr": "{URL}", "fingerprint": "3f2a9c0d", "lab_name": "fieldkit", "expires_at_ms": {exp}}}, "message": "In BRODEC: LAB › MACHINES › ADD MACHINE, then scan this code."}}"#
            ),
            _ => r#"{"ok": true, "installed": true, "state": "stopped", "code": null, "message": "Not paired."}"#.into(),
        };
        std::fs::write(dir.join("pair.json"), doc).unwrap();
        std::fs::write(dir.join("controls.json"), r#"{"ok": true, "controls": [{"id": "reboot", "title": "Restart", "available": true, "why": ""}, {"id": "update", "title": "Update bromigOS", "available": false, "why": "a Field Kit stick doesn't update itself"}]}"#).unwrap();
        std::fs::write(dir.join("propose.json"), r#"{"ok": true, "proposal": {"id": "0123456789ab", "title": "Pair with BRODEC", "change": "Writes /etc/brodec-machine/machine.toml and starts BRODEC's machine agent."}}"#).unwrap();
        std::fs::write(
            &p,
            format!(
                "#!/bin/sh\ncase \"$3\" in\n  pair) cat {d}/pair.json ;;\n  controls) cat {d}/controls.json ;;\n  pair-start) cat {d}/propose.json ;;\n  run) echo \"$4\" >> {d}/ran; echo '{{\"ok\": true, \"message\": \"started\"}}' ;;\nesac\n",
                d = dir.display()
            ),
        )
        .unwrap();
        std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o755)).unwrap();
        p
    }

    fn settle(app: &mut Pair, want: &str) {
        for _ in 0..3000 {
            app.pump();
            if app.state["state"].as_str() == Some(want)
                && app.controls.is_array()
                && !app.controls.as_array().unwrap().is_empty()
            {
                return;
            }
            thread::sleep(Duration::from_millis(10));
        }
    }

    fn render(app: &Pair, w: u16, h: u16) -> String {
        let mut t = Terminal::new(TestBackend::new(w, h)).unwrap();
        t.draw(|f| draw(f, app)).unwrap();
        let b = t.backend().buffer().clone();
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
    fn waiting_shows_the_qr_and_the_code() {
        let d = tempfile::tempdir().unwrap();
        let mut app = Pair::new(Look::wick(), &fake(d.path(), "waiting"));
        app.refresh();
        settle(&mut app, "waiting");
        let s = render(&app, 160, 45);
        if let Some(dir) = std::env::var_os("BROMIGOS_FIELDKIT_SHOTS") {
            let _ = std::fs::write(Path::new(&dir).join("tui-vector-pair.txt"), &s);
        }
        assert!(s.contains("KPGG-ZFVT"), "{s}");
        assert!(s.contains('▀') || s.contains('▄'), "{s}");
        assert!(s.contains("ADD MACHINE"), "{s}");
        assert!(s.contains("a Field Kit stick doesn't update itself"), "{s}");
    }

    #[test]
    fn starting_the_agent_waits_for_approval() {
        let d = tempfile::tempdir().unwrap();
        let mut app = Pair::new(Look::wick(), &fake(d.path(), "stopped"));
        app.refresh();
        settle(&mut app, "stopped");
        app.key(KeyCode::Char('p'));
        for _ in 0..3000 {
            app.pump();
            if app.asking.is_some() {
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
        assert!(app.asking.is_some());
        assert!(!d.path().join("ran").exists());
        app.key(KeyCode::Enter); // the default: Not now
        assert!(app.asking.is_none());
        assert!(!d.path().join("ran").exists());
        app.key(KeyCode::Char('p'));
        for _ in 0..3000 {
            app.pump();
            if app.asking.is_some() {
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
        app.key(KeyCode::Char('y'));
        for _ in 0..3000 {
            app.pump();
            if d.path().join("ran").exists() {
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
        assert_eq!(
            std::fs::read_to_string(d.path().join("ran"))
                .unwrap()
                .trim(),
            "0123456789ab"
        );
    }
}
