//! The TUI's state and what keys, the mouse and the session's messages do to it. No
//! terminal here: `view` draws an `App`, `main` feeds it.

use std::collections::BTreeMap;

use ratatui::crossterm::event::{
    KeyCode, KeyEvent, KeyModifiers, MouseButton, MouseEvent, MouseEventKind,
};
use ratatui::layout::{Position, Rect};
use serde_json::{Value, json};

use crate::proto::{self, Axes, Device, Kind, Msg, State};
use crate::theme::Pal;

#[derive(Debug, Clone, PartialEq)]
pub enum Step {
    /// Which kind of device.
    Kind,
    /// Scanning, picking it.
    Scan,
    /// Pairing, trusting, connecting.
    Pairing,
    Ready,
    Failed(String),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Wizard {
    pub step: Step,
    pub kind: usize,
    pub pick: usize,
    pub mac: Option<String>,
    pub doing: String,
    /// The pairing request's id.
    pub id: Option<u64>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Screen {
    Devices,
    Device(String),
    Wizard(Wizard),
    Trouble,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Prompt {
    pub pid: String,
    pub what: String,
    pub mac: String,
    pub name: String,
    pub value: Value,
    pub typed: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Edit {
    Search,
    Rename(String),
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Input {
    pub mac: String,
    pub buttons: Vec<String>,
    pub axes: Axes,
    pub error: Option<String>,
}

pub struct App {
    pub state: State,
    /// What the pairing wizard offers (the session's `kinds`).
    pub kinds: Vec<Kind>,
    pub screen: Screen,
    pub sel: usize,
    pub filter: String,
    pub edit: Option<(Edit, String)>,
    pub help: bool,
    pub prompt: Option<Prompt>,
    pub busy: BTreeMap<String, String>,
    pending: BTreeMap<u64, (String, Option<String>)>,
    next: u64,
    pub msg: Option<(String, bool)>,
    pub errors: Vec<String>,
    pub input: Option<Input>,
    pub mic: Option<f32>,
    pub forget: Option<String>,
    pub tick: u64,
    pub still: bool,
    pub pal: Pal,
    /// When each nearby device was first seen (in ticks): new ones blip.
    pub seen: BTreeMap<String, u64>,
    /// Requests for the session, as lines.
    pub out: Vec<String>,
    /// Where the last frame put the rows of the list: (area, the macs top to bottom).
    pub rows_at: (Rect, Vec<String>),
    pub quit: bool,
}

/// A found device is of the kind asked for (earbuds and speakers count as headphones),
/// as bromigos_bluez.fits says.
pub fn fits(device: &str, kind: &str) -> bool {
    device == kind || (kind == "headset" && (device == "earbuds" || device == "speaker"))
}

pub fn plain_kind(k: &str) -> &str {
    if k.is_empty() { "device" } else { k }
}

impl App {
    pub fn new(pal: Pal, motion: &str) -> App {
        App {
            state: State::default(),
            kinds: vec![],
            screen: Screen::Devices,
            sel: 0,
            filter: String::new(),
            edit: None,
            help: false,
            prompt: None,
            busy: BTreeMap::new(),
            pending: BTreeMap::new(),
            next: 1,
            msg: None,
            errors: vec![],
            input: None,
            mic: None,
            forget: None,
            tick: 0,
            still: motion != "full",
            pal,
            seen: BTreeMap::new(),
            out: vec![],
            rows_at: (Rect::default(), vec![]),
            quit: false,
        }
    }

    /// Something moves on screen now (so the loop redraws on its own).
    pub fn moving(&self) -> bool {
        !self.still
            && (self.state.scanning()
                || !self.busy.is_empty()
                || self.state.devices.iter().any(|d| d.connected))
    }

    pub fn req(&mut self, what: &str, mac: Option<&str>, extra: Value) -> u64 {
        let id = self.next;
        self.next += 1;
        let mut e = extra;
        if let (Some(m), Value::Object(o)) = (mac, &mut e) {
            o.insert("mac".into(), json!(m));
        }
        self.out.push(proto::request(id, what, e));
        self.pending
            .insert(id, (what.to_string(), mac.map(str::to_string)));
        id
    }

    fn say(&mut self, text: impl Into<String>, error: bool) {
        let t = text.into();
        if error {
            self.errors.push(t.clone());
            if self.errors.len() > 20 {
                self.errors.remove(0);
            }
        }
        self.msg = Some((t, error));
    }

    // ------------------------------------------------------------ the list
    /// The devices shown: paired first (connected first), then nearby, by the filter.
    pub fn listed(&self) -> Vec<Device> {
        let f = self.filter.to_lowercase();
        let mut v: Vec<Device> = self
            .state
            .devices
            .iter()
            .filter(|d| d.paired || !d.alias.is_empty() || d.rssi.is_some())
            .filter(|d| {
                f.is_empty()
                    || d.name.to_lowercase().contains(&f)
                    || d.kind.to_lowercase().contains(&f)
                    || d.mac.to_lowercase().contains(&f)
            })
            .cloned()
            .collect();
        v.sort_by(|a, b| {
            (!a.paired, !a.connected, a.name.to_lowercase()).cmp(&(
                !b.paired,
                !b.connected,
                b.name.to_lowercase(),
            ))
        });
        v
    }

    pub fn selected(&self) -> Option<Device> {
        self.listed().get(self.sel).cloned()
    }

    /// The nearby devices the wizard offers, the chosen kind first, strongest first.
    pub fn found(&self, kind: usize) -> Vec<Device> {
        let want = self
            .kinds
            .get(kind)
            .map(|k| k.glyph.as_str())
            .unwrap_or("device");
        let mut v: Vec<Device> = self
            .state
            .devices
            .iter()
            .filter(|d| !d.paired && (!d.alias.is_empty() || d.rssi.is_some()))
            .cloned()
            .collect();
        v.sort_by_key(|d| (!fits(&d.glyph, want), -(d.rssi.unwrap_or(-200))));
        v
    }

    // ------------------------------------------------------------ the session's messages
    pub fn handle(&mut self, m: Msg) {
        match m {
            Msg::Kinds { kinds } => self.kinds = kinds,
            Msg::State { state } => {
                for d in state.devices.iter().filter(|d| !d.paired) {
                    self.seen.entry(d.mac.clone()).or_insert(self.tick);
                }
                self.state = state;
                let n = self.listed().len();
                if self.sel >= n {
                    self.sel = n.saturating_sub(1);
                }
            }
            Msg::Reply {
                id,
                ok,
                error,
                said,
            } => {
                let Some((what, mac)) = id.and_then(|i| self.pending.remove(&i)) else {
                    return;
                };
                if let Some(m) = &mac {
                    self.busy.remove(m);
                }
                if let Screen::Wizard(w) = &mut self.screen
                    && w.id == id
                {
                    w.step = if ok {
                        Step::Ready
                    } else {
                        Step::Failed(error.clone().unwrap_or_default())
                    };
                }
                if ok {
                    if let Some(s) = said {
                        self.say(s, false);
                    } else if what != "input" && what != "mic" && what != "scan" {
                        let name = mac
                            .as_deref()
                            .and_then(|m| self.state.find(m))
                            .map(|d| d.name.clone())
                            .unwrap_or_default();
                        self.say(done_words(&what, &name), false);
                    }
                } else {
                    let e = error.unwrap_or_else(|| "it didn't work".into());
                    if what == "input"
                        && let Some(i) = &mut self.input
                    {
                        i.error = Some(e.clone());
                    }
                    self.say(e, true);
                }
            }
            Msg::Step { id, step } => {
                if let Some((_, Some(mac))) = id.and_then(|i| self.pending.get(&i)).cloned() {
                    self.busy.insert(mac, step.clone());
                }
                if let Screen::Wizard(w) = &mut self.screen {
                    w.doing = step;
                }
            }
            Msg::Prompt {
                pid,
                what,
                mac,
                name,
                value,
            } => {
                self.prompt = Some(Prompt {
                    pid,
                    what,
                    mac,
                    name,
                    value,
                    typed: String::new(),
                });
            }
            Msg::Cancel => {
                self.prompt = None;
                self.say(
                    "The device stopped pairing (cancelled, or it took too long)",
                    true,
                );
            }
            Msg::Input { mac, buttons, axes } => {
                self.input = Some(Input {
                    mac,
                    buttons,
                    axes,
                    error: None,
                });
            }
            Msg::InputError { error } => {
                if let Some(i) = &mut self.input {
                    i.error = Some(error.clone());
                }
                self.say(error, true);
            }
            Msg::Mic { level } => self.mic = Some(level),
        }
    }

    // ------------------------------------------------------------ keys
    pub fn key(&mut self, k: KeyEvent) {
        if k.code == KeyCode::Char('c') && k.modifiers.contains(KeyModifiers::CONTROL) {
            self.quit = true;
            return;
        }
        if self.prompt.is_some() {
            self.prompt_key(k);
            return;
        }
        if let Some((kind, mut text)) = self.edit.take() {
            match k.code {
                KeyCode::Esc => {
                    if kind == Edit::Search {
                        self.filter.clear();
                    }
                }
                KeyCode::Enter => match &kind {
                    Edit::Search => self.filter = text,
                    Edit::Rename(mac) => {
                        let mac = mac.clone();
                        self.req("rename", Some(&mac), json!({"name": text}));
                    }
                },
                KeyCode::Backspace => {
                    text.pop();
                    if kind == Edit::Search {
                        self.filter = text.clone();
                    }
                    self.edit = Some((kind, text));
                }
                KeyCode::Char(c) => {
                    text.push(c);
                    if kind == Edit::Search {
                        self.filter = text.clone();
                        self.sel = 0;
                    }
                    self.edit = Some((kind, text));
                }
                _ => self.edit = Some((kind, text)),
            }
            return;
        }
        if self.help {
            self.help = false;
            return;
        }
        match k.code {
            KeyCode::Char('?') => {
                self.help = true;
                return;
            }
            KeyCode::Char('q') => {
                if self.screen == Screen::Devices {
                    self.quit = true;
                } else {
                    self.back();
                }
                return;
            }
            _ => {}
        }
        match self.screen.clone() {
            Screen::Devices => self.devices_key(k),
            Screen::Device(mac) => self.device_key(k, &mac),
            Screen::Wizard(w) => self.wizard_key(k, w),
            Screen::Trouble => self.trouble_key(k),
        }
    }

    fn back(&mut self) {
        if let Screen::Device(_) = self.screen {
            self.stop_tests();
        }
        if let Screen::Wizard(w) = &self.screen
            && w.step == Step::Scan
            && self.state.scanning()
        {
            self.req("scan", None, json!({"on": false}));
        }
        self.forget = None;
        self.screen = Screen::Devices;
    }

    fn stop_tests(&mut self) {
        if self.input.take().is_some() {
            self.out.push(proto::request(0, "input-stop", json!({})));
        }
        if self.mic.take().is_some() {
            self.out.push(proto::request(0, "mic-stop", json!({})));
        }
    }

    fn up(&mut self) {
        self.sel = self.sel.saturating_sub(1);
    }
    fn down(&mut self, n: usize) {
        if self.sel + 1 < n {
            self.sel += 1;
        }
    }

    pub fn open(&mut self, mac: &str) {
        let Some(d) = self.state.find(mac).cloned() else {
            return;
        };
        if !d.paired {
            self.pair(&d);
            return;
        }
        self.screen = Screen::Device(mac.to_string());
        self.forget = None;
        if d.glyph == "controller" && d.connected {
            self.input = Some(Input {
                mac: mac.into(),
                ..Default::default()
            });
            self.req("input", Some(mac), json!({}));
        }
    }

    fn pair(&mut self, d: &Device) {
        let kind = self.kind_of(&d.glyph);
        let mut w = Wizard {
            step: Step::Pairing,
            kind,
            pick: 0,
            mac: Some(d.mac.clone()),
            doing: "pairing".into(),
            id: None,
        };
        self.busy.insert(d.mac.clone(), "pairing".into());
        w.id = Some(self.req("pair", Some(&d.mac), json!({})));
        self.screen = Screen::Wizard(w);
    }

    fn toggle(&mut self, d: &Device) {
        if !d.paired {
            self.pair(d);
        } else if d.connected {
            self.busy.insert(d.mac.clone(), "disconnecting".into());
            self.req("disconnect", Some(&d.mac), json!({}));
        } else {
            self.busy.insert(d.mac.clone(), "connecting".into());
            self.req("connect", Some(&d.mac), json!({}));
        }
    }

    fn scan(&mut self) {
        let on = !self.state.scanning();
        self.req("scan", None, json!({"on": on}));
    }

    fn devices_key(&mut self, k: KeyEvent) {
        let n = self.listed().len();
        match k.code {
            KeyCode::Up | KeyCode::Char('k') => self.up(),
            KeyCode::Down | KeyCode::Char('j') => self.down(n),
            KeyCode::Home | KeyCode::Char('g') => self.sel = 0,
            KeyCode::End | KeyCode::Char('G') => self.sel = n.saturating_sub(1),
            KeyCode::Enter | KeyCode::Right | KeyCode::Char('l') => {
                if let Some(d) = self.selected() {
                    self.open(&d.mac);
                }
            }
            KeyCode::Char('/') => self.edit = Some((Edit::Search, self.filter.clone())),
            KeyCode::Esc => self.filter.clear(),
            KeyCode::Char('s') => self.scan(),
            KeyCode::Char('p') => match self.selected() {
                Some(d) if !d.paired => self.pair(&d),
                _ => self.start_wizard(),
            },
            KeyCode::Char('a') => self.start_wizard(),
            KeyCode::Char('c') => {
                if let Some(d) = self.selected() {
                    self.toggle(&d);
                }
            }
            KeyCode::Char('o') => {
                let on = !self.state.powered();
                self.req("power", None, json!({"on": on}));
            }
            KeyCode::Char('x') => self.screen = Screen::Trouble,
            _ => {}
        }
    }

    /// The wizard's kind for a device's glyph (else the last: something else).
    fn kind_of(&self, glyph: &str) -> usize {
        self.kinds
            .iter()
            .position(|k| fits(glyph, &k.glyph))
            .unwrap_or(self.kinds.len().saturating_sub(1))
    }

    pub fn start_wizard(&mut self) {
        self.screen = Screen::Wizard(Wizard {
            step: Step::Kind,
            kind: 0,
            pick: 0,
            mac: None,
            doing: String::new(),
            id: None,
        });
    }

    fn device_key(&mut self, k: KeyEvent, mac: &str) {
        let Some(d) = self.state.find(mac).cloned() else {
            self.back();
            return;
        };
        if let Some(f) = &self.forget {
            if f == mac && matches!(k.code, KeyCode::Char('y') | KeyCode::Char('f')) {
                self.forget = None;
                self.busy.insert(mac.into(), "forgetting".into());
                self.req("forget", Some(mac), json!({}));
                self.back();
                return;
            }
            self.forget = None;
            return;
        }
        let card = self.state.audio.get(mac).cloned();
        let sound = self
            .state
            .sound
            .devices
            .get(mac)
            .cloned()
            .unwrap_or_default();
        match k.code {
            KeyCode::Esc | KeyCode::Left | KeyCode::Char('h') => self.back(),
            KeyCode::Char('c') => self.toggle(&d),
            KeyCode::Char('t') => {
                self.req("trust", Some(mac), json!({"on": !d.trusted}));
            }
            KeyCode::Char('r') => self.edit = Some((Edit::Rename(mac.into()), d.name.clone())),
            KeyCode::Char('f') => self.forget = Some(mac.into()),
            KeyCode::Char('R') => {
                // re-pair: forget it, then pair it again from the wizard
                self.req("forget", Some(mac), json!({}));
                self.stop_tests();
                let kind = self.kind_of(&d.glyph);
                self.screen = Screen::Wizard(Wizard {
                    step: Step::Kind,
                    kind,
                    pick: 0,
                    mac: None,
                    doing: String::new(),
                    id: None,
                });
            }
            KeyCode::Char('u') if d.glyph == "controller" => {
                self.req("rumble", Some(mac), json!({}));
            }
            KeyCode::Char('m') if card.is_some() => {
                let c = card.unwrap_or_default();
                let to = if c.mode.as_deref() == Some("headset") {
                    "hifi"
                } else {
                    "headset"
                };
                self.req("profile", Some(mac), json!({"mode": to}));
            }
            KeyCode::Char('o') => match sound.output {
                Some(name) => {
                    self.req(
                        "sound-default",
                        None,
                        json!({"side": "output", "name": name}),
                    );
                }
                None => self.say("It has no sound output now: is it connected?", true),
            },
            KeyCode::Char('i') => match sound.input {
                Some(name) => {
                    self.req(
                        "sound-default",
                        None,
                        json!({"side": "input", "name": name}),
                    );
                }
                None => self.say(
                    "It has no microphone now: switch it to HEADSET + MIC (m)",
                    true,
                ),
            },
            KeyCode::Char('v') => {
                if self.mic.is_some() {
                    self.mic = None;
                    self.out.push(proto::request(0, "mic-stop", json!({})));
                } else {
                    match sound.input {
                        Some(name) => {
                            self.mic = Some(0.0);
                            self.req("mic", None, json!({"source": name}));
                        }
                        None => self.say(
                            "It has no microphone now: switch it to HEADSET + MIC (m)",
                            true,
                        ),
                    }
                }
            }
            _ => {}
        }
    }

    fn wizard_key(&mut self, k: KeyEvent, mut w: Wizard) {
        match (&w.step, k.code) {
            (_, KeyCode::Esc) => {
                if w.step == Step::Pairing
                    && let Some(m) = &w.mac
                {
                    let m = m.clone();
                    self.req("cancel-pair", Some(&m), json!({}));
                }
                self.back();
                return;
            }
            (Step::Kind, KeyCode::Up | KeyCode::Char('k')) => w.kind = w.kind.saturating_sub(1),
            (Step::Kind, KeyCode::Down | KeyCode::Char('j')) => {
                w.kind = (w.kind + 1).min(self.kinds.len().saturating_sub(1))
            }
            (Step::Kind, KeyCode::Enter | KeyCode::Char('l') | KeyCode::Right) => {
                w.step = Step::Scan;
                w.pick = 0;
                if !self.state.scanning() {
                    self.req("scan", None, json!({"on": true}));
                }
            }
            (Step::Scan, KeyCode::Up | KeyCode::Char('k')) => w.pick = w.pick.saturating_sub(1),
            (Step::Scan, KeyCode::Down | KeyCode::Char('j')) => {
                w.pick = (w.pick + 1).min(self.found(w.kind).len().saturating_sub(1))
            }
            (Step::Scan, KeyCode::Char('s')) => self.scan(),
            (Step::Scan, KeyCode::Enter | KeyCode::Char('p')) => {
                if let Some(d) = self.found(w.kind).get(w.pick).cloned() {
                    w.step = Step::Pairing;
                    w.mac = Some(d.mac.clone());
                    w.doing = "pairing".into();
                    self.busy.insert(d.mac.clone(), "pairing".into());
                    w.id = Some(self.req("pair", Some(&d.mac), json!({})));
                }
            }
            (Step::Ready, KeyCode::Enter) => {
                let mac = w.mac.clone();
                self.screen = Screen::Devices;
                if let Some(m) = mac {
                    self.open(&m);
                }
                return;
            }
            (Step::Failed(_), KeyCode::Enter) => {
                w.step = Step::Scan;
                w.pick = 0;
                if !self.state.scanning() {
                    self.req("scan", None, json!({"on": true}));
                }
            }
            _ => {}
        }
        if matches!(self.screen, Screen::Wizard(_)) {
            self.screen = Screen::Wizard(w);
        }
    }

    fn trouble_key(&mut self, k: KeyEvent) {
        match k.code {
            KeyCode::Esc | KeyCode::Left | KeyCode::Char('h') => self.back(),
            KeyCode::Char('a') => {
                self.req("reset", None, json!({}));
                self.say("Switching the adapter off and on again…", false);
            }
            KeyCode::Char('o') => {
                let on = !self.state.powered();
                self.req("power", None, json!({"on": on}));
            }
            KeyCode::Char('e') => self.errors.clear(),
            _ => {}
        }
    }

    fn prompt_key(&mut self, k: KeyEvent) {
        let Some(p) = self.prompt.as_mut() else {
            return;
        };
        let answer = |v: Value| proto::answer(&p.pid, v);
        let line = match (p.what.as_str(), k.code) {
            (_, KeyCode::Esc) => Some(answer(Value::Null)),
            ("confirm" | "authorize", KeyCode::Char('y') | KeyCode::Enter) => {
                Some(answer(json!(true)))
            }
            ("confirm" | "authorize", KeyCode::Char('n')) => Some(answer(json!(false))),
            ("pin" | "passkey", KeyCode::Enter) => {
                let t = p.typed.trim().to_string();
                Some(if p.what == "passkey" {
                    answer(t.parse::<u32>().map(Value::from).unwrap_or(Value::Null))
                } else {
                    answer(if t.is_empty() { Value::Null } else { json!(t) })
                })
            }
            ("pin" | "passkey", KeyCode::Backspace) => {
                p.typed.pop();
                None
            }
            ("pin" | "passkey", KeyCode::Char(c))
                if c.is_ascii_alphanumeric() && p.typed.len() < 16 =>
            {
                p.typed.push(c);
                None
            }
            ("type" | "show-pin", KeyCode::Enter) => {
                self.prompt = None;
                return;
            }
            _ => None,
        };
        if let Some(l) = line {
            self.out.push(l);
            self.prompt = None;
        }
    }

    // ------------------------------------------------------------ the mouse
    pub fn mouse(&mut self, m: MouseEvent) {
        let at = Position::new(m.column, m.row);
        let (area, macs) = self.rows_at.clone();
        match m.kind {
            MouseEventKind::ScrollDown => {
                let n = self.listed().len();
                self.down(n);
            }
            MouseEventKind::ScrollUp => self.up(),
            MouseEventKind::Down(MouseButton::Left)
                if area.contains(at) && self.screen == Screen::Devices =>
            {
                let i = (m.row - area.y) as usize;
                if let Some(mac) = macs.get(i) {
                    let list = self.listed();
                    if let Some(pos) = list.iter().position(|d| &d.mac == mac) {
                        if self.sel == pos {
                            let mac = mac.clone();
                            self.open(&mac);
                        } else {
                            self.sel = pos;
                        }
                    }
                }
            }
            _ => {}
        }
    }
}

fn done_words(what: &str, name: &str) -> String {
    match what {
        "connect" => format!("{name} connected"),
        "disconnect" => format!("{name} disconnected"),
        "pair" => format!("Paired with {name}: it reconnects by itself when it's switched on"),
        "forget" => format!("Forgot {name}"),
        "trust" => format!("{name}: auto-reconnect changed"),
        "rename" => "Renamed".into(),
        "power" => "Bluetooth switched".into(),
        "sound-default" => "The sound now goes there".into(),
        _ => "Done".into(),
    }
}
