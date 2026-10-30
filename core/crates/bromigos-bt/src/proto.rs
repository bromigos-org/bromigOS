//! The line protocol of `bromigos bluetooth session` (desktop/lib/bromigos_btsession.py):
//! one JSON document per line each way. The session is the desktop's one bluez core,
//! shared with the bar, its panel and Settings; this side only reads and asks.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
pub struct Device {
    pub path: String,
    pub mac: String,
    pub name: String,
    pub alias: String,
    pub icon: String,
    /// "headset", "game controller", "keyboard" …
    pub kind: String,
    /// The hologram: controller, headset, earbuds, keyboard, mouse, phone, speaker, device.
    pub glyph: String,
    pub paired: bool,
    pub connected: bool,
    pub trusted: bool,
    pub battery: Option<u8>,
    pub rssi: Option<i32>,
    /// It plays sound (A2DP, HFP, LE Audio).
    pub audio: bool,
    /// A phone: it sends sound here.
    pub audio_source: bool,
    pub xbox: bool,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
pub struct Adapter {
    pub path: String,
    pub mac: String,
    pub name: String,
    pub alias: String,
    pub powered: bool,
    pub discoverable: bool,
    pub discovering: bool,
}

/// PipeWire's card for a Bluetooth sound device.
#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
pub struct Card {
    pub card: String,
    pub active: String,
    /// "hifi", "headset", "off".
    pub mode: Option<String>,
    pub codec: Option<String>,
    pub hifi: Option<String>,
    pub headset: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
pub struct Sides {
    pub output: Option<String>,
    pub input: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
pub struct Sound {
    pub defaults: Sides,
    /// By address: the device's output and input.
    pub devices: BTreeMap<String, Sides>,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
pub struct State {
    pub available: bool,
    pub adapter: Option<Adapter>,
    pub blocked: bool,
    pub hard_blocked: bool,
    pub hardware: bool,
    pub devices: Vec<Device>,
    pub audio: BTreeMap<String, Card>,
    pub sound: Sound,
    pub xpadneo: bool,
}

impl State {
    pub fn find(&self, mac: &str) -> Option<&Device> {
        self.devices.iter().find(|d| d.mac == mac)
    }
    pub fn powered(&self) -> bool {
        self.adapter.as_ref().is_some_and(|a| a.powered)
    }
    pub fn scanning(&self) -> bool {
        self.adapter.as_ref().is_some_and(|a| a.discovering)
    }
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
pub struct Axes {
    pub lx: f32,
    pub ly: f32,
    pub rx: f32,
    pub ry: f32,
    pub lt: f32,
    pub rt: f32,
    pub dx: i32,
    pub dy: i32,
}

/// A kind of device the pairing wizard offers, and how to put it in pairing mode.
#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
pub struct Kind {
    pub name: String,
    pub glyph: String,
    pub steps: Vec<String>,
}

/// What the session says.
#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(tag = "t", rename_all = "kebab-case")]
pub enum Msg {
    Kinds {
        kinds: Vec<Kind>,
    },
    State {
        state: State,
    },
    Reply {
        id: Option<u64>,
        ok: bool,
        error: Option<String>,
        said: Option<String>,
    },
    Step {
        id: Option<u64>,
        step: String,
    },
    Prompt {
        pid: String,
        what: String,
        mac: String,
        #[serde(default)]
        name: String,
        #[serde(default)]
        value: Value,
    },
    Cancel,
    Input {
        mac: String,
        buttons: Vec<String>,
        axes: Axes,
        /// The controller's driver (xpadneo, hid-microsoft, xpad…), when sysfs says.
        #[serde(default)]
        driver: Option<String>,
        /// An Xbox controller on the kernel's basic driver: rumble and battery are limited.
        #[serde(default)]
        basic: bool,
        /// Where its layout came from: SDL GameControllerDB, or its axes.
        #[serde(default)]
        layout: Option<String>,
    },
    InputError {
        error: String,
    },
    Mic {
        level: f32,
    },
}

pub fn parse(line: &str) -> Option<Msg> {
    serde_json::from_str(line).ok()
}

/// A request line: `{"id": id, "do": what, …extra}`.
pub fn request(id: u64, what: &str, extra: Value) -> String {
    let mut v = json!({"id": id, "do": what});
    if let (Some(o), Value::Object(e)) = (v.as_object_mut(), extra) {
        o.extend(e);
    }
    v.to_string()
}

pub fn answer(pid: &str, value: Value) -> String {
    json!({"answer": pid, "value": value}).to_string()
}
