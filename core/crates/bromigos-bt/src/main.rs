//! bromigos-bt, the binary behind `bromigos bluetooth tui` (bin/bromigos-bluetooth-tui runs it):
//! see the library's documentation.
//!
//!   bromigos bluetooth tui            in this terminal
//!   bromigos bluetooth tui --window   in a floating terminal window of its own (the launcher's
//!                                     entry, the bar panel's MORE): `bromigos terminal` with
//!                                     the class bromigos-bluetooth, which Hyprland floats
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, ExitCode, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use bromigos_bt::app::App;
use bromigos_bt::{proto, theme, view};
use ratatui::crossterm::event::{
    self, DisableMouseCapture, EnableMouseCapture, Event, KeyEventKind,
};
use ratatui::crossterm::execute;

const HELP: &str = "bromigos bluetooth tui [--window]\n\
  Bluetooth in the terminal: pair step by step, connect, a controller's input test, a\n\
  headset's sound. ? in it lists the keys. --window opens it in a floating terminal.";

enum Ev {
    Line(String),
    Gone,
    Term(Event),
}

fn session() -> std::io::Result<Child> {
    let cmd = std::env::var("BROMIGOS_BT_SESSION")
        .unwrap_or_else(|_| "bromigos bluetooth session".into());
    let mut words = cmd.split_whitespace();
    let prog = words.next().unwrap_or("bromigos");
    Command::new(prog)
        .args(words)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
}

/// The TUI in a floating terminal of its own, the way bromigOS opens its terminal tools:
/// `bromigos terminal` (kitty, else $TERMINAL), with the class Hyprland floats.
fn window() -> ExitCode {
    let r = Command::new("bromigos")
        .args(["terminal", "--class", "bromigos-bluetooth", "--title", "Bluetooth", "--"])
        .args(["bromigos", "bluetooth", "tui"])
        .spawn();
    match r {
        Ok(_) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("bromigos bluetooth tui: bromigos terminal: {e}");
            ExitCode::from(1)
        }
    }
}

fn send(stdin: &mut Option<ChildStdin>, app: &mut App) {
    if let Some(s) = stdin.as_mut() {
        for l in app.out.drain(..) {
            if writeln!(s, "{l}").is_err() {
                break;
            }
        }
        let _ = s.flush();
    } else {
        app.out.clear();
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "-h" || a == "--help") {
        println!("{HELP}");
        return ExitCode::SUCCESS;
    }
    if args.iter().any(|a| a == "--window") {
        return window();
    }
    let (pal, motion) = theme::load();
    let mut app = App::new(pal, &motion);
    let (tx, rx) = mpsc::channel::<Ev>();
    let mut child = match session() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("bromigos bluetooth tui: can't start `bromigos bluetooth session`: {e}");
            return ExitCode::from(1);
        }
    };
    let mut stdin = child.stdin.take();
    if let Some(out) = child.stdout.take() {
        let tx = tx.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(out).lines() {
                match line {
                    Ok(l) => {
                        if tx.send(Ev::Line(l)).is_err() {
                            return;
                        }
                    }
                    Err(_) => break,
                }
            }
            let _ = tx.send(Ev::Gone);
        });
    }
    {
        let tx = tx.clone();
        std::thread::spawn(move || {
            while let Ok(e) = event::read() {
                if tx.send(Ev::Term(e)).is_err() {
                    return;
                }
            }
        });
    }
    let mut terminal = ratatui::init();
    let _ = execute!(std::io::stdout(), EnableMouseCapture);
    let mut last = Instant::now();
    let result = loop {
        if let Err(e) = terminal.draw(|f| view::draw(f, &mut app)) {
            break Err(e);
        }
        let wait = if app.moving() {
            Duration::from_millis(80)
        } else {
            Duration::from_millis(1000)
        };
        match rx.recv_timeout(wait) {
            Ok(Ev::Line(l)) => {
                if let Some(m) = proto::parse(&l) {
                    app.handle(m);
                }
            }
            Ok(Ev::Gone) => {
                app.handle(proto::Msg::Reply {
                    id: None,
                    ok: false,
                    error: None,
                    said: None,
                });
                app.msg = Some((
                    "The Bluetooth session ended: is bromigos-desktop installed?".into(),
                    true,
                ));
                stdin = None;
            }
            Ok(Ev::Term(Event::Key(k))) if k.kind == KeyEventKind::Press => app.key(k),
            Ok(Ev::Term(Event::Mouse(m))) => app.mouse(m),
            Ok(Ev::Term(_)) => {}
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => break Ok(()),
        }
        if last.elapsed() >= Duration::from_millis(80) {
            app.tick += (last.elapsed().as_millis() / 80) as u64;
            last = Instant::now();
        }
        send(&mut stdin, &mut app);
        if app.quit {
            break Ok(());
        }
    };
    let _ = execute!(std::io::stdout(), DisableMouseCapture);
    ratatui::restore();
    drop(stdin);
    let _ = child.kill();
    let _ = child.wait();
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("bromigos bluetooth tui: {e}");
            ExitCode::from(1)
        }
    }
}
