//! The TUI's screens drawn into ratatui's TestBackend, in three worlds (the Wick, Mire,
//! Tidewell: their colours from this checkout's themes, as `bromigos theme set` resolves
//! them). The text of each screen is compared with tests/snapshots/<screen>.txt (it's the
//! same in every world); the colours are checked against each world's palette.
//! UPDATE_SNAPSHOTS=1 rewrites the snapshots.
//!
//! The state is a real `bromigos bluetooth session` document (tests/fixtures/state.json),
//! recorded against the stand-in bluez (desktop/tests/fake_bluez.py) while it scanned.

use std::path::{Path, PathBuf};

use bromigos_bt::app::{App, Screen, Step};
use bromigos_bt::proto::{self, Msg};
use bromigos_bt::theme::Pal;
use bromigos_bt::view;
use bromigos_core::theme::{self, Locations};
use ratatui::Terminal;
use ratatui::backend::TestBackend;
use ratatui::buffer::Buffer;
use ratatui::crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::style::Color;

const WORLDS: &[&str] = &["wick", "mire", "tidewell"];

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn palette(world: &str) -> Pal {
    let none = PathBuf::from("/nonexistent");
    let loc = Locations {
        system_themes: repo().join("themes"),
        ext_themes: none.clone(),
        user_themes: none.clone(),
        system_templates: repo().join("theme/templates"),
        user_templates: none.clone(),
        system_icons: repo().join("theme/icons"),
        user_icons: none.clone(),
        state: none,
    };
    let t = theme::load(&loc, world).unwrap_or_else(|e| panic!("{world}: {e}"));
    Pal::from_json(&theme::palette_json(&t)).0
}

fn app(world: &str, scanning: bool) -> App {
    WORLD.with(|w| *w.borrow_mut() = world.to_string());
    let mut a = App::new(palette(world), "full");
    let text = std::fs::read_to_string(
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/state.json"),
    )
    .unwrap();
    let mut doc: serde_json::Value = serde_json::from_str(&text).unwrap();
    if !scanning {
        doc["adapter"]["discovering"] = false.into();
        let devs: Vec<serde_json::Value> = doc["devices"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|d| d["paired"] == true)
            .cloned()
            .collect();
        doc["devices"] = devs.into();
    }
    a.handle(Msg::State {
        state: serde_json::from_value(doc).unwrap(),
    });
    a.tick = 40; // nearby devices found a while ago: no rings
    a
}

fn key(a: &mut App, c: KeyCode) {
    a.key(KeyEvent::new(c, KeyModifiers::NONE));
}

fn draw(a: &mut App) -> Buffer {
    let mut t = Terminal::new(TestBackend::new(100, 30)).unwrap();
    t.draw(|f| view::draw(f, a)).unwrap();
    t.backend().buffer().clone()
}

fn text(b: &Buffer) -> String {
    let mut s = String::new();
    for y in 0..b.area.height {
        let mut line = String::new();
        for x in 0..b.area.width {
            line.push_str(b[(x, y)].symbol());
        }
        s.push_str(line.trim_end());
        s.push('\n');
    }
    s
}

/// SNAPSHOT_CELLS_DIR=DIR: each screen's cells as JSON lines (text, fg, bg), for pictures.
fn cells_out(name: &str, b: &Buffer) {
    let Some(dir) = std::env::var_os("SNAPSHOT_CELLS_DIR") else { return };
    let col = |c: Color| match c {
        Color::Rgb(r, g, b) => format!("#{r:02x}{g:02x}{b:02x}"),
        _ => String::new(),
    };
    let mut out = String::new();
    for y in 0..b.area.height {
        let row: Vec<serde_json::Value> = (0..b.area.width)
            .map(|x| {
                let c = &b[(x, y)];
                serde_json::json!([c.symbol(), col(c.fg), col(c.bg), c.modifier.contains(ratatui::style::Modifier::BOLD)])
            })
            .collect();
        out.push_str(&serde_json::to_string(&row).unwrap());
        out.push('\n');
    }
    let world = WORLD.with(|w| w.borrow().clone());
    std::fs::write(Path::new(&dir).join(format!("{world}-{name}.jsonl")), out).unwrap();
}

thread_local! {
    static WORLD: std::cell::RefCell<String> = std::cell::RefCell::new(String::from("wick"));
}

fn check(name: &str, b: &Buffer) {
    cells_out(name, b);
    let got = text(b);
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/snapshots")
        .join(format!("{name}.txt"));
    if std::env::var_os("UPDATE_SNAPSHOTS").is_some() {
        std::fs::write(&path, &got).unwrap();
        return;
    }
    let want = std::fs::read_to_string(&path)
        .unwrap_or_else(|_| panic!("no snapshot {path:?}: UPDATE_SNAPSHOTS=1"));
    assert_eq!(got, want, "{name} differs from its snapshot");
}

/// The first cell whose text starts `word` on the screen.
fn at(b: &Buffer, word: &str) -> (u16, u16) {
    let t = text(b);
    for (y, line) in t.lines().enumerate() {
        if let Some(i) = line.find(word) {
            let x = line[..i].chars().count() as u16;
            return (x, y as u16);
        }
    }
    panic!("{word:?} isn't on the screen:\n{t}");
}

fn fg(b: &Buffer, word: &str) -> Color {
    let (x, y) = at(b, word);
    b[(x, y)].fg
}

#[test]
fn the_device_list_in_three_worlds() {
    for w in WORLDS {
        let pal = palette(w);
        let mut a = app(w, false);
        let b = draw(&mut a);
        check("devices", &b);
        // the header in the world's primary; a connected device's tag lit; a low battery amber
        let (x, y) = at(&b, "BLUETOOTH");
        assert_eq!(b[(x, y)].bg, pal.primary, "{w}");
        assert_eq!(fg(&b, "HEADSET"), pal.primary, "{w}: a connected device");
        assert_eq!(
            fg(&b, "EARBUDS"),
            pal.dim,
            "{w}: a paired one, not connected"
        );
        let (x, y) = at(&b, "12%");
        assert_eq!(b[(x, y)].fg, pal.warn, "{w}: 12% is low");
    }
}

#[test]
fn scanning_shows_the_sweep_and_what_it_found() {
    for w in WORLDS {
        let mut a = app(w, true);
        let b = draw(&mut a);
        check("scanning", &b);
        assert!(text(&b).contains("SCANNING · 4 FOUND"));
    }
}

#[test]
fn reduced_motion_holds_still() {
    let mut a = app("wick", true);
    a.still = true;
    let one = text(&draw(&mut a));
    a.tick += 7;
    assert_eq!(
        one,
        text(&draw(&mut a)),
        "nothing moves under reduced motion"
    );
    let mut b = app("wick", true);
    let one = text(&draw(&mut b));
    b.tick += 7;
    assert_ne!(one, text(&draw(&mut b)), "the sweep turns otherwise");
}

#[test]
fn a_headset_page() {
    for w in WORLDS {
        let mut a = app(w, false);
        a.open("00:00:5E:00:53:10");
        let b = draw(&mut a);
        check("headset", &b);
    }
}

#[test]
fn a_controller_page_with_its_input() {
    for w in WORLDS {
        let pal = palette(w);
        let mut a = app(w, false);
        a.open("00:00:5E:00:53:12");
        assert!(
            a.out.iter().any(|l| l.contains("\"do\":\"input\"")),
            "the tester starts"
        );
        a.handle(proto::parse(r#"{"t":"input","mac":"00:00:5E:00:53:12","buttons":["A","LB"],"axes":{"lx":0.5,"ly":-0.25,"rx":0,"ry":0,"lt":0.75,"rt":0,"dx":0,"dy":0}}"#).unwrap());
        let b = draw(&mut a);
        check("controller", &b);
        let (x, y) = at(&b, " A ");
        assert_eq!(b[(x + 1, y)].bg, pal.primary, "{w}: A is held");
        assert!(
            text(&b).contains("basic driver"),
            "xpadneo isn't loaded in the fixture"
        );
    }
}

#[test]
fn the_pairing_wizard() {
    for w in WORLDS {
        let mut a = app(w, true);
        key(&mut a, KeyCode::Char('a'));
        check("wizard-kind", &draw(&mut a));
        key(&mut a, KeyCode::Enter);
        let Screen::Wizard(wz) = &a.screen else {
            panic!()
        };
        assert_eq!(wz.step, Step::Scan);
        check("wizard-scan", &draw(&mut a));
        // the agent's question, then ready
        key(&mut a, KeyCode::Enter);
        let id = a
            .out
            .iter()
            .rev()
            .find(|l| l.contains("\"do\":\"pair\""))
            .map(|l| {
                serde_json::from_str::<serde_json::Value>(l).unwrap()["id"]
                    .as_u64()
                    .unwrap()
            })
            .unwrap();
        a.handle(proto::parse(r#"{"t":"prompt","pid":"p1","what":"confirm","mac":"00:00:5E:00:53:21","name":"Pixel 9","value":"123456"}"#).unwrap());
        check("wizard-prompt", &draw(&mut a));
        key(&mut a, KeyCode::Char('y'));
        assert!(a.out.iter().any(|l| l == r#"{"answer":"p1","value":true}"#));
        a.handle(Msg::Reply {
            id: Some(id),
            ok: true,
            error: None,
            said: None,
        });
        let Screen::Wizard(wz) = &a.screen else {
            panic!()
        };
        assert_eq!(wz.step, Step::Ready);
    }
}

#[test]
fn troubleshooting_and_help() {
    for w in WORLDS {
        let mut a = app(w, false);
        a.handle(Msg::Reply {
            id: None,
            ok: false,
            error: Some("x".into()),
            said: None,
        });
        let id = a.req("connect", Some("00:00:5E:00:53:11"), serde_json::json!({}));
        a.handle(Msg::Reply {
            id: Some(id),
            ok: false,
            error: Some("Couldn't reach it: is it switched on and nearby?".into()),
            said: None,
        });
        key(&mut a, KeyCode::Char('x'));
        check("trouble", &draw(&mut a));
        key(&mut a, KeyCode::Esc);
        key(&mut a, KeyCode::Char('?'));
        check("help", &draw(&mut a));
    }
}

#[test]
fn search_filters_the_list() {
    let mut a = app("wick", false);
    key(&mut a, KeyCode::Char('/'));
    for c in "pad".chars() {
        key(&mut a, KeyCode::Char(c));
    }
    key(&mut a, KeyCode::Enter);
    let names: Vec<String> = a.listed().iter().map(|d| d.name.clone()).collect();
    assert!(names.is_empty() || names.iter().all(|n| n.to_lowercase().contains("pad")));
    a.filter = "controller".into();
    assert_eq!(a.listed().len(), 1);
    assert_eq!(a.listed()[0].name, "Xbox Wireless Controller");
}

fn sent(a: &App) -> Vec<serde_json::Value> {
    a.out
        .iter()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}

#[test]
fn keys_ask_the_session() {
    let mut a = app("wick", false);
    // the list: c on the selected (connected) headset disconnects it
    key(&mut a, KeyCode::Char('c'));
    let last = sent(&a).pop().unwrap();
    assert_eq!(
        (last["do"].as_str(), last["mac"].as_str()),
        (Some("disconnect"), Some("00:00:5E:00:53:10"))
    );
    assert_eq!(
        a.busy.get("00:00:5E:00:53:10").map(String::as_str),
        Some("disconnecting")
    );
    key(&mut a, KeyCode::Char('o'));
    assert_eq!(
        sent(&a).pop().unwrap()["on"],
        false,
        "o switches Bluetooth off"
    );
    // a headset's page: the profile, the output, forget only after a yes
    a.open("00:00:5E:00:53:10");
    key(&mut a, KeyCode::Char('m'));
    let m = sent(&a).pop().unwrap();
    assert_eq!(
        (m["do"].as_str(), m["mode"].as_str()),
        (Some("profile"), Some("headset"))
    );
    key(&mut a, KeyCode::Char('o'));
    let m = sent(&a).pop().unwrap();
    assert_eq!(
        (m["do"].as_str(), m["name"].as_str()),
        (
            Some("sound-default"),
            Some("bluez_output.00_00_5E_00_53_10.1")
        )
    );
    let n = a.out.len();
    key(&mut a, KeyCode::Char('f'));
    key(&mut a, KeyCode::Char('n'));
    assert_eq!(a.out.len(), n, "n keeps it");
    key(&mut a, KeyCode::Char('f'));
    key(&mut a, KeyCode::Char('y'));
    assert_eq!(sent(&a).pop().unwrap()["do"], "forget");
    assert_eq!(a.screen, Screen::Devices);
    // a controller's rumble
    a.open("00:00:5E:00:53:12");
    key(&mut a, KeyCode::Char('u'));
    assert_eq!(sent(&a).pop().unwrap()["do"], "rumble");
    key(&mut a, KeyCode::Esc);
    assert_eq!(
        sent(&a).pop().unwrap()["do"],
        "input-stop",
        "leaving stops the tester"
    );
}

#[test]
fn a_pin_is_typed_then_sent() {
    let mut a = app("wick", false);
    a.handle(proto::parse(r#"{"t":"prompt","pid":"p7","what":"pin","mac":"00:00:5E:00:53:23","name":"Car kit","value":null}"#).unwrap());
    for c in "0000".chars() {
        key(&mut a, KeyCode::Char(c));
    }
    key(&mut a, KeyCode::Backspace);
    key(&mut a, KeyCode::Char('1'));
    key(&mut a, KeyCode::Enter);
    assert_eq!(a.out.last().unwrap(), r#"{"answer":"p7","value":"0001"}"#);
    assert!(a.prompt.is_none());
    a.handle(
        proto::parse(
            r#"{"t":"prompt","pid":"p8","what":"confirm","mac":"x","name":"x","value":"123456"}"#,
        )
        .unwrap(),
    );
    key(&mut a, KeyCode::Esc);
    assert_eq!(
        a.out.last().unwrap(),
        r#"{"answer":"p8","value":null}"#,
        "esc says no"
    );
}

#[test]
fn the_palette_and_motion_come_from_palette_json() {
    let (pal, motion) =
        Pal::from_json(r##"{"colors": {"primary": "#ff7a1a"}, "motion": "reduced"}"##);
    assert_eq!(pal.primary, Color::Rgb(0xff, 0x7a, 0x1a));
    assert_eq!(motion, "reduced");
    let (wick, m) = Pal::from_json("not json");
    assert_eq!(m, "full");
    assert_eq!(wick.primary, Color::Rgb(57, 255, 20));
}
