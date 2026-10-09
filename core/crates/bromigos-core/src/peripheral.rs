//! `bromigos peripheral`: optional modules for peripherals (docs/peripherals.md).
//!
//! A module is a folder with a `peripheral.toml`: how its device is found (a USB vendor,
//! the kernel driver that says what the device is, name hints for before that driver is
//! installed), what it needs (packages, groups, user services), its keys (macro keys bound
//! by keycode to commands), keymap options, a dial and lighting. Packaged modules are in
//! `$BROMIGOS_SHARE_DIR/peripherals/<id>/`; a user's own (a similar keyboard) in
//! `~/.config/bromigos/peripherals/<id>/`, which replaces a packaged one of the same id.
//!
//! Which modules are on, and the user's changes to their keys, live in
//! `~/.config/bromigos/peripherals.toml` (theirs). This module turns that and the devices
//! found into `~/.local/state/bromigos/peripherals/hypr.lua` (read by the default Hyprland
//! config: desktop/hypr/bromigos/peripherals.lua) and into `status --json` (read by the
//! daemon that runs the dials and the lighting, bromigos-peripherals). Nothing is on until
//! the user turns it on (`bromigos peripheral enable`, or `bromigos setup peripherals`).

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde::{Deserialize, Serialize};

use crate::install::Runner;
use crate::paths::Paths;

/// The manifest format this core reads.
pub const FORMAT: u32 = 1;

/// The user unit that runs the modules' dials and lighting (package bromigos-desktop).
pub const DAEMON_UNIT: &str = "bromigos-peripherals.service";

/// How many Hyprland names a device's interfaces may take: Hyprland names the second
/// input device with the same name `<name>-1`, the next `<name>-2` (keyboards and
/// pointers counted together), so a keyboard with five interfaces uses up to `-5`.
pub const NAME_SUFFIXES: u32 = 9;

/// HID drivers that say nothing about what a device is.
const GENERIC_DRIVERS: &[&str] = &["hid-generic", "usbhid", "hid-multitouch"];

/// What `dial.turn` can do.
pub const DIAL_TURNS: &[&str] = &["vector-voice"];
/// What `dial.roller` can do.
pub const DIAL_ROLLERS: &[&str] = &["volume"];
/// Lighting backends.
pub const RGB_BACKENDS: &[&str] = &["openrazer"];
/// What the lighting follows: VECTOR (his voice's colour and mood) or the theme's primary.
pub const RGB_FOLLOWS: &[&str] = &["vector", "theme"];

/// A module's `peripheral.toml`.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: u32,
    pub name: String,
    pub description: String,
    /// What it is: "keyboard" (its keyboard interfaces get the keymap and the binds).
    #[serde(default = "default_kind")]
    pub kind: String,
    #[serde(rename = "match")]
    pub matcher: Match,
    #[serde(default)]
    pub needs: Needs,
    #[serde(default)]
    pub keymap: Keymap,
    #[serde(default)]
    pub keys: Vec<Key>,
    #[serde(default)]
    pub dial: Option<Dial>,
    #[serde(default)]
    pub rgb: Option<Rgb>,
    /// The folder's name.
    #[serde(skip_deserializing)]
    pub id: String,
    #[serde(skip_deserializing)]
    pub dir: PathBuf,
    /// "system" (packaged) or "user".
    #[serde(skip_deserializing)]
    pub source: String,
}

fn default_kind() -> String {
    "keyboard".into()
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Match {
    /// The USB vendor id, 4 hex digits ("1532").
    pub usb_vendor: String,
    /// Kernel HID drivers that say a device is this module's (openrazer's `razerkbd`).
    /// A device bound to one of them matches; one bound to another vendor driver (a mouse's)
    /// doesn't. Empty: the vendor alone decides.
    #[serde(default)]
    pub hid_drivers: Vec<String>,
    /// While the device has only a generic driver (before the module's driver is
    /// installed): words in its name that say it is one ("BlackWidow"), case-insensitive.
    #[serde(default)]
    pub name_hints: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Needs {
    /// Packages `enable` installs (pacman --needed).
    #[serde(default)]
    pub packages: Vec<String>,
    /// Groups the user joins (the device nodes' and the driver's).
    #[serde(default)]
    pub groups: Vec<String>,
    /// User services `enable` enables and starts.
    #[serde(default)]
    pub user_services: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Keymap {
    /// XKB options added for the device only, after the user's own (`fkeys:basic_13-24`:
    /// its F13-F24 stay F13-F24 instead of XF86Tools, XF86AudioMicMute …).
    #[serde(default)]
    pub options: Vec<String>,
    /// Keys whose other binds ignore this device (a macro key the default layout reads as
    /// XF86AudioMicMute must not mute the microphone).
    #[serde(default)]
    pub exclusive: Vec<String>,
}

/// A macro key, bound by keycode to a command (only on the module's devices).
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Key {
    /// Its name in peripherals.toml (`m1`, `side1`, `dial`).
    pub id: String,
    /// The keycode Hyprland sees: the kernel's evdev code + 8 (KEY_F13 = 183 is 191).
    pub code: u32,
    /// What's printed on it ("M1").
    pub label: String,
    /// The command it runs (`sh -c`); `{holo}` is VECTOR's launcher.
    pub press: String,
    /// A command on release (push to talk).
    #[serde(default)]
    pub release: Option<String>,
    /// What it does, in a few words (the SHORTCUTS panel, `status`).
    pub hint: String,
    /// "vector": bound only when VECTOR is installed.
    #[serde(default)]
    pub needs: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Dial {
    /// What turning it does: "vector-voice" (VECTOR's voice: auto, then each of his voices).
    pub turn: String,
    /// A volume roller on the same interface (it is grabbed with the dial): "volume".
    #[serde(default)]
    pub roller: Option<String>,
    pub hint: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Rgb {
    /// "openrazer" (its daemon, over D-Bus).
    pub backend: String,
    /// "vector": the colour of the voice in use, his mood over it, the theme's at rest;
    /// "theme": the theme's primary, always. The user's `rgb_follow` overrides it.
    pub follow: String,
    pub hint: String,
}

impl Manifest {
    /// Checks what serde can't. Err(the first problem).
    pub fn validate(&self) -> Result<(), String> {
        if self.format != FORMAT {
            return Err(format!(
                "format {} (this bromigos reads {FORMAT})",
                self.format
            ));
        }
        if self.kind != "keyboard" {
            return Err(format!("kind {:?} (only \"keyboard\")", self.kind));
        }
        let v = &self.matcher.usb_vendor;
        if v.len() != 4 || !v.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(format!("match.usb_vendor {v:?} isn't 4 hex digits"));
        }
        let mut seen = std::collections::BTreeSet::new();
        for k in &self.keys {
            if !valid_id(&k.id) {
                return Err(format!(
                    "key id {:?}: lowercase letters, digits and -",
                    k.id
                ));
            }
            if !seen.insert(k.id.as_str()) {
                return Err(format!("key {:?} twice", k.id));
            }
            if !(9..=767).contains(&k.code) {
                return Err(format!("key {}: code {} isn't a keycode", k.id, k.code));
            }
            if k.press.trim().is_empty() {
                return Err(format!("key {}: no press command", k.id));
            }
            if let Some(n) = &k.needs
                && n != "vector"
            {
                return Err(format!("key {}: needs {n:?} (only \"vector\")", k.id));
            }
        }
        if let Some(d) = &self.dial {
            if !DIAL_TURNS.contains(&d.turn.as_str()) {
                return Err(format!(
                    "dial.turn {:?} ({})",
                    d.turn,
                    DIAL_TURNS.join(", ")
                ));
            }
            if let Some(r) = &d.roller
                && !DIAL_ROLLERS.contains(&r.as_str())
            {
                return Err(format!("dial.roller {r:?} ({})", DIAL_ROLLERS.join(", ")));
            }
        }
        if let Some(r) = &self.rgb {
            if !RGB_BACKENDS.contains(&r.backend.as_str()) {
                return Err(format!(
                    "rgb.backend {:?} ({})",
                    r.backend,
                    RGB_BACKENDS.join(", ")
                ));
            }
            if !RGB_FOLLOWS.contains(&r.follow.as_str()) {
                return Err(format!(
                    "rgb.follow {:?} ({})",
                    r.follow,
                    RGB_FOLLOWS.join(", ")
                ));
            }
        }
        for o in &self.keymap.options {
            if o.is_empty() || o.contains(',') || o.contains(char::is_whitespace) {
                return Err(format!("keymap option {o:?}"));
            }
        }
        Ok(())
    }

    /// The tag Hyprland gives the module's devices (binds listen to it).
    pub fn tag(&self) -> String {
        format!("bromigos-{}", self.id)
    }
}

fn valid_id(s: &str) -> bool {
    !s.is_empty()
        && s.chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

/// Where packaged modules are.
pub fn system_dir(paths: &Paths) -> PathBuf {
    paths.share_dir.join("peripherals")
}

/// Where the user's own modules are.
pub fn user_dir(paths: &Paths) -> PathBuf {
    paths.user_config_dir().join("peripherals")
}

/// The user's choices: `~/.config/bromigos/peripherals.toml`.
pub fn config_file(paths: &Paths) -> PathBuf {
    paths.user_config_dir().join("peripherals.toml")
}

/// What `bromigos peripheral` generates: `~/.local/state/bromigos/peripherals/`.
pub fn state_dir(paths: &Paths) -> PathBuf {
    paths.user_state_dir().join("peripherals")
}

/// The Hyprland part, read by the default config.
pub fn hypr_file(paths: &Paths) -> PathBuf {
    state_dir(paths).join("hypr.lua")
}

/// Loads one module folder.
pub fn load_dir(dir: &Path, source: &str) -> Result<Manifest, String> {
    let id = dir
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    if !valid_id(&id) {
        return Err(format!(
            "{}: a module's folder is named with lowercase letters, digits and -",
            dir.display()
        ));
    }
    let file = dir.join("peripheral.toml");
    let text = fs::read_to_string(&file).map_err(|e| format!("{}: {e}", file.display()))?;
    let mut m: Manifest = toml::from_str(&text).map_err(|e| format!("{}: {e}", file.display()))?;
    m.id = id;
    m.dir = dir.to_path_buf();
    m.source = source.into();
    m.validate()
        .map_err(|e| format!("{}: {e}", file.display()))?;
    Ok(m)
}

/// Every module, by id: packaged, then the user's (which replace packaged ones of the same
/// id). Broken ones come back as (id, error).
pub fn modules(paths: &Paths) -> (Vec<Manifest>, Vec<(String, String)>) {
    let mut by_id: BTreeMap<String, Result<Manifest, String>> = BTreeMap::new();
    for (dir, source) in [(system_dir(paths), "system"), (user_dir(paths), "user")] {
        let Ok(rd) = fs::read_dir(&dir) else { continue };
        let mut entries: Vec<PathBuf> = rd
            .flatten()
            .map(|e| e.path())
            .filter(|p| p.join("peripheral.toml").is_file())
            .collect();
        entries.sort();
        for p in entries {
            let id = p
                .file_name()
                .map(|s| s.to_string_lossy().into_owned())
                .unwrap_or_default();
            by_id.insert(id, load_dir(&p, source));
        }
    }
    let (mut ok, mut bad) = (vec![], vec![]);
    for (id, r) in by_id {
        match r {
            Ok(m) => ok.push(m),
            Err(e) => bad.push((id, e)),
        }
    }
    (ok, bad)
}

// ------------------------------------------------------------------ the user's file

/// A key's command in peripherals.toml: a string (on press; "" unbinds it) or both.
#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
#[serde(untagged)]
pub enum KeyChoice {
    Press(String),
    Both {
        press: String,
        #[serde(default)]
        release: Option<String>,
    },
}

/// Which devices the lighting reaches.
#[derive(Debug, Clone, Copy, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum RgbScope {
    /// Every device the backend lights (a Razer keyboard and mouse together).
    #[default]
    All,
    /// The module's own devices.
    Device,
    /// Leave the lighting alone.
    Off,
}

/// One module's table in peripherals.toml.
#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Choice {
    #[serde(default)]
    pub enabled: bool,
    /// The keys changed: id -> command.
    #[serde(default)]
    pub keys: BTreeMap<String, KeyChoice>,
    /// The dial (false: left to the system: it scrolls sideways).
    #[serde(default = "yes")]
    pub dial: bool,
    #[serde(default)]
    pub rgb: RgbScope,
    /// What the lighting follows, over the module's own: "vector" or "theme".
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rgb_follow: Option<String>,
    /// More Hyprland device names (`hyprctl devices`), for a keyboard detection misses.
    #[serde(default)]
    pub devices: Vec<String>,
}

fn yes() -> bool {
    true
}

/// peripherals.toml, read. A missing file is no choices; a broken one is an error.
pub fn read_choices(paths: &Paths) -> Result<BTreeMap<String, Choice>, String> {
    let p = config_file(paths);
    match fs::read_to_string(&p) {
        Ok(t) => toml::from_str(&t).map_err(|e| format!("{}: {e}", p.display())),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(BTreeMap::new()),
        Err(e) => Err(format!("{}: {e}", p.display())),
    }
}

/// peripherals.toml with `[<id>] enabled` set, everything else (comments, keys) kept.
pub fn with_enabled(existing: &str, id: &str, on: bool) -> Result<String, String> {
    with_value(existing, id, "enabled", toml_edit::value(on))
}

/// peripherals.toml with `[<id>] <key>` set to `value`, everything else kept.
pub fn with_value(
    existing: &str,
    id: &str,
    key: &str,
    value: toml_edit::Item,
) -> Result<String, String> {
    let mut doc: toml_edit::DocumentMut = existing
        .parse()
        .map_err(|e| format!("peripherals.toml: {e}"))?;
    if doc.as_table().is_empty() && !existing.contains('#') {
        doc.decor_mut().set_prefix(
            "# bromigos peripheral: the device modules this machine uses (docs/peripherals.md).\n\
             # Yours: updates never touch it. `bromigos peripheral refresh` applies an edit.\n",
        );
    }
    if !doc.contains_table(id) {
        let mut t = toml_edit::Table::new();
        t.set_implicit(false);
        doc[id] = toml_edit::Item::Table(t);
    }
    let t = doc[id]
        .as_table_mut()
        .ok_or_else(|| format!("peripherals.toml: [{id}] isn't a table"))?;
    if t.is_implicit() {
        // only `[id.keys]` so far: `[id]` goes right before it, with its leading comments
        t.set_implicit(false);
        let first = t
            .iter()
            .filter_map(|(k, v)| {
                v.as_table()
                    .and_then(|x| x.position())
                    .map(|p| (p, k.to_string()))
            })
            .min();
        if let Some((pos, key)) = first {
            let lead = t[key.as_str()]
                .as_table()
                .and_then(|x| x.decor().prefix())
                .and_then(|r| r.as_str())
                .unwrap_or("")
                .to_string();
            if let Some(sub) = t[key.as_str()].as_table_mut() {
                sub.decor_mut().set_prefix("\n");
            }
            t.decor_mut().set_prefix(lead);
            t.set_position(Some(pos));
        }
    }
    t[key] = value;
    Ok(doc.to_string())
}

fn write_atomic(p: &Path, text: &str) -> std::io::Result<()> {
    if let Some(d) = p.parent() {
        fs::create_dir_all(d)?;
    }
    // through a symlink (a dotfiles checkout): write its target
    let target = fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf());
    let tmp = target.with_extension("tmp");
    fs::write(&tmp, text)?;
    fs::rename(&tmp, &target)
}

/// Sets `[<id>] rgb_follow` in the user's file: what the module's lighting follows,
/// "vector" (his voice and mood) or "theme" (the theme's primary, always). The daemon
/// reads it again within its 10 s poll; nothing needs restarting.
pub fn set_follow(paths: &Paths, id: &str, follow: &str) -> Result<(), String> {
    if !RGB_FOLLOWS.contains(&follow) {
        return Err(format!(
            "{follow:?}: the lighting follows {}",
            RGB_FOLLOWS.join(" or ")
        ));
    }
    let p = config_file(paths);
    let existing = fs::read_to_string(&p).unwrap_or_default();
    let text = with_value(&existing, id, "rgb_follow", toml_edit::value(follow))?;
    write_atomic(&p, &text).map_err(|e| format!("{}: {e}", p.display()))
}

/// Sets `[<id>] enabled` in the user's file.
pub fn set_enabled(paths: &Paths, id: &str, on: bool) -> Result<(), String> {
    let p = config_file(paths);
    let existing = fs::read_to_string(&p).unwrap_or_default();
    let text = with_enabled(&existing, id, on)?;
    write_atomic(&p, &text).map_err(|e| format!("{}: {e}", p.display()))
}

// ------------------------------------------------------------------ input devices

/// One entry of `/proc/bus/input/devices`.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct InputDev {
    pub name: String,
    /// USB vendor and product, lowercase hex ("1532", "028d").
    pub vendor: String,
    pub product: String,
    pub phys: String,
    /// Its sysfs path (`/devices/…/input/input19`).
    pub sysfs: String,
    pub handlers: Vec<String>,
    #[serde(skip)]
    pub key: Vec<u64>,
    #[serde(skip)]
    pub rel: Vec<u64>,
}

/// Linux input codes the detection reads.
pub const REL_X: u32 = 0;
pub const REL_HWHEEL: u32 = 6;

/// `B: KEY=3c0000000000 0 … fffe` -> 64-bit words, least significant first.
fn bitmap(s: &str) -> Vec<u64> {
    s.split_whitespace()
        .rev()
        .map(|w| u64::from_str_radix(w, 16).unwrap_or(0))
        .collect()
}

fn bit(words: &[u64], n: u32) -> bool {
    words
        .get((n / 64) as usize)
        .is_some_and(|w| w & (1u64 << (n % 64)) != 0)
}

impl InputDev {
    pub fn has_rel(&self, code: u32) -> bool {
        bit(&self.rel, code)
    }
    pub fn has_key(&self, code: u32) -> bool {
        bit(&self.key, code)
    }
    /// Its event node's name (`event13`).
    pub fn event(&self) -> Option<&str> {
        self.handlers
            .iter()
            .map(String::as_str)
            .find(|h| h.starts_with("event"))
    }
    pub fn is_keyboard(&self) -> bool {
        self.handlers.iter().any(|h| h == "kbd")
    }
    /// The HID device it belongs to (`0003:1532:028D.0006`), from its sysfs path.
    pub fn hid(&self) -> Option<&str> {
        self.sysfs.split('/').find(|seg| {
            let p: Vec<&str> = seg.split(':').collect();
            p.len() == 3 && p[0].len() == 4 && p[1].len() == 4 && p[2].contains('.')
        })
    }
    /// The USB device it belongs to (the sysfs path up to it), so a keyboard's
    /// interfaces group together; else its `phys` up to the interface.
    pub fn usb_device(&self) -> String {
        let segs: Vec<&str> = self.sysfs.split('/').collect();
        // the interface is `<bus>-<port…>:<config>.<interface>`; its parent is the device
        if let Some(i) = segs.iter().position(|s| {
            s.contains(':') && s.contains('-') && !s.starts_with("0000") && s.contains('.')
        }) {
            return segs[..i].join("/");
        }
        self.phys
            .split_once("/input")
            .map(|(a, _)| a.to_string())
            .unwrap_or_else(|| self.phys.clone())
    }
}

/// `/proc/bus/input/devices`.
pub fn parse_input_devices(text: &str) -> Vec<InputDev> {
    let mut out = vec![];
    for block in text.split("\n\n") {
        let mut d = InputDev::default();
        let mut any = false;
        for line in block.lines() {
            let Some((tag, rest)) = line.split_once(": ") else {
                continue;
            };
            any = true;
            match tag {
                "I" => {
                    for kv in rest.split_whitespace() {
                        match kv.split_once('=') {
                            Some(("Vendor", v)) => d.vendor = v.to_lowercase(),
                            Some(("Product", v)) => d.product = v.to_lowercase(),
                            _ => {}
                        }
                    }
                }
                "N" => {
                    d.name = rest
                        .strip_prefix("Name=")
                        .unwrap_or(rest)
                        .trim_matches('"')
                        .to_string();
                }
                "P" => d.phys = rest.strip_prefix("Phys=").unwrap_or(rest).to_string(),
                "S" => d.sysfs = rest.strip_prefix("Sysfs=").unwrap_or(rest).to_string(),
                "H" => {
                    d.handlers = rest
                        .strip_prefix("Handlers=")
                        .unwrap_or(rest)
                        .split_whitespace()
                        .map(str::to_string)
                        .collect();
                }
                "B" => {
                    if let Some(v) = rest.strip_prefix("KEY=") {
                        d.key = bitmap(v);
                    } else if let Some(v) = rest.strip_prefix("REL=") {
                        d.rel = bitmap(v);
                    }
                }
                _ => {}
            }
        }
        if any && !d.name.is_empty() {
            out.push(d);
        }
    }
    out
}

/// Hyprland's name for an input device: lowercase, spaces as `-`.
pub fn hypr_name(kernel_name: &str) -> String {
    kernel_name
        .trim()
        .chars()
        .map(|c| {
            if c == ' ' || c == '\n' {
                '-'
            } else {
                c.to_ascii_lowercase()
            }
        })
        .collect()
}

/// A device a module found.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Found {
    /// The kernel's name ("Razer Razer BlackWidow V4 Pro").
    pub name: String,
    /// "1532:028d".
    pub usb: String,
    /// How it was recognised: "driver" (bound to the module's HID driver) or "name" (a
    /// name hint; the driver isn't installed yet).
    pub how: String,
    /// The HID driver bound, when not generic.
    pub driver: Option<String>,
    /// Hyprland's names for its interfaces: the name, then `-1` … `-9`.
    pub hypr_names: Vec<String>,
    /// Its keyboard interfaces' event nodes.
    pub keyboards: Vec<String>,
    /// The dial's event node: an interface with a horizontal wheel and a pointer (the
    /// keyboard's own mouse interface).
    pub dial: Option<String>,
}

/// The devices `m` matches among `devs`. `driver(hid)` is the kernel driver bound to a HID
/// device (`/sys/bus/hid/devices/<hid>/driver`).
pub fn detect(
    m: &Manifest,
    devs: &[InputDev],
    driver: &dyn Fn(&str) -> Option<String>,
) -> Vec<Found> {
    let vendor = m.matcher.usb_vendor.to_lowercase();
    let mut groups: BTreeMap<String, Vec<&InputDev>> = BTreeMap::new();
    for d in devs.iter().filter(|d| d.vendor == vendor) {
        groups.entry(d.usb_device()).or_default().push(d);
    }
    let mut out = vec![];
    for (_, ifaces) in groups {
        let drivers: Vec<String> = ifaces
            .iter()
            .filter_map(|d| d.hid().and_then(driver))
            .filter(|d| !GENERIC_DRIVERS.contains(&d.as_str()))
            .collect();
        let name = ifaces[0].name.clone();
        let how = if m.matcher.hid_drivers.is_empty() {
            Some("vendor")
        } else if drivers.iter().any(|d| m.matcher.hid_drivers.contains(d)) {
            Some("driver")
        } else if drivers.is_empty() {
            let low = name.to_lowercase();
            m.matcher
                .name_hints
                .iter()
                .any(|h| low.contains(&h.to_lowercase()))
                .then_some("name")
        } else {
            None // another vendor driver claims it (openrazer's mouse driver: a mouse)
        };
        let Some(how) = how else { continue };
        let keyboards: Vec<String> = ifaces
            .iter()
            .filter(|d| d.is_keyboard())
            .filter_map(|d| d.event().map(|e| format!("/dev/input/{e}")))
            .collect();
        if m.kind == "keyboard" && keyboards.is_empty() {
            continue;
        }
        let dial = ifaces
            .iter()
            .find(|d| d.has_rel(REL_HWHEEL) && d.has_rel(REL_X))
            .and_then(|d| d.event().map(|e| format!("/dev/input/{e}")));
        let base = hypr_name(&name);
        let mut hypr_names = vec![base.clone()];
        hypr_names.extend((1..=NAME_SUFFIXES).map(|i| format!("{base}-{i}")));
        out.push(Found {
            name,
            usb: format!("{}:{}", ifaces[0].vendor, ifaces[0].product),
            how: how.into(),
            driver: drivers.first().cloned(),
            hypr_names,
            keyboards,
            dial,
        });
    }
    out
}

/// A fake root for tests (`BROMIGOS_PERIPHERAL_ROOT`): `<root>/proc/bus/input/devices` and
/// `<root>/sys/bus/hid/devices/<hid>/driver`. Default `/`.
pub fn root() -> PathBuf {
    std::env::var_os("BROMIGOS_PERIPHERAL_ROOT")
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/"))
}

/// This machine's input devices.
pub fn input_devices(root: &Path) -> Vec<InputDev> {
    fs::read_to_string(root.join("proc/bus/input/devices"))
        .map(|t| parse_input_devices(&t))
        .unwrap_or_default()
}

/// The driver bound to a HID device, by the name of its driver link.
pub fn hid_driver(root: &Path, hid: &str) -> Option<String> {
    fs::read_link(root.join("sys/bus/hid/devices").join(hid).join("driver"))
        .ok()
        .and_then(|p| p.file_name().map(|s| s.to_string_lossy().into_owned()))
}

/// What `m` finds on this machine.
pub fn found_here(m: &Manifest, root: &Path) -> Vec<Found> {
    let devs = input_devices(root);
    detect(m, &devs, &|hid| hid_driver(root, hid))
}

// ------------------------------------------------------------------ resolved for the desktop

/// A bind the desktop makes.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Bind {
    pub id: String,
    pub label: String,
    /// `code:191`.
    pub keys: String,
    pub press: String,
    pub release: Option<String>,
    pub hint: String,
    /// Changed in peripherals.toml.
    pub changed: bool,
}

/// An enabled module as the desktop runs it.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Resolved {
    pub id: String,
    pub name: String,
    pub tag: String,
    pub found: Vec<Found>,
    /// Hyprland device names: the found devices' and the user's.
    pub devices: Vec<String>,
    pub kb_options: Vec<String>,
    pub exclusive: Vec<String>,
    pub binds: Vec<Bind>,
    /// Keys left out, and why.
    pub skipped: Vec<String>,
    /// The dial's event nodes, when the dial is on.
    pub dials: Vec<String>,
    pub dial: Option<Dial>,
    pub rgb: Option<Rgb>,
    pub rgb_scope: RgbScope,
}

/// A module with the user's choice, for this machine. `holo`: VECTOR's launcher, when he's
/// installed.
pub fn resolve(m: &Manifest, c: &Choice, found: Vec<Found>, holo: Option<&str>) -> Resolved {
    let mut binds = vec![];
    let mut skipped = vec![];
    for k in &m.keys {
        let (press, release, changed) = match c.keys.get(&k.id) {
            None => (k.press.clone(), k.release.clone(), false),
            Some(KeyChoice::Press(p)) => (p.clone(), None, true),
            Some(KeyChoice::Both { press, release }) => (press.clone(), release.clone(), true),
        };
        if press.trim().is_empty() {
            skipped.push(format!(
                "{} ({}): unbound in peripherals.toml",
                k.id, k.label
            ));
            continue;
        }
        let uses_holo = press.contains("{holo}")
            || release.as_deref().is_some_and(|r| r.contains("{holo}"))
            || k.needs.as_deref() == Some("vector");
        if uses_holo && holo.is_none() {
            skipped.push(format!("{} ({}): VECTOR isn't installed", k.id, k.label));
            continue;
        }
        let fill = |s: &str| s.replace("{holo}", holo.unwrap_or("bromigos-holo"));
        binds.push(Bind {
            id: k.id.clone(),
            label: k.label.clone(),
            keys: format!("code:{}", k.code),
            press: fill(&press),
            release: release
                .as_deref()
                .map(fill)
                .filter(|r| !r.trim().is_empty()),
            hint: k.hint.clone(),
            changed,
        });
    }
    for id in c.keys.keys() {
        if !m.keys.iter().any(|k| &k.id == id) {
            skipped.push(format!("{id}: no such key on {}", m.id));
        }
    }
    if let Some(f) = c.rgb_follow.as_deref().filter(|f| !RGB_FOLLOWS.contains(f)) {
        skipped.push(format!(
            "rgb_follow {f:?}: not {}",
            RGB_FOLLOWS.join(" or ")
        ));
    }
    let mut devices: Vec<String> = found.iter().flat_map(|f| f.hypr_names.clone()).collect();
    for d in &c.devices {
        if !devices.contains(d) {
            devices.push(d.clone());
        }
    }
    let dials = if c.dial && m.dial.is_some() {
        found.iter().filter_map(|f| f.dial.clone()).collect()
    } else {
        vec![]
    };
    Resolved {
        id: m.id.clone(),
        name: m.name.clone(),
        tag: m.tag(),
        devices,
        kb_options: m.keymap.options.clone(),
        exclusive: m.keymap.exclusive.clone(),
        binds,
        skipped,
        dials,
        dial: m.dial.clone().filter(|_| c.dial),
        rgb: m
            .rgb
            .clone()
            .filter(|_| c.rgb != RgbScope::Off)
            .map(|mut r| {
                if let Some(f) = c.rgb_follow.as_deref().filter(|f| RGB_FOLLOWS.contains(f)) {
                    r.follow = f.to_string();
                }
                r
            }),
        rgb_scope: c.rgb,
        found,
    }
}

fn lua_str(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    o.push('"');
    for c in s.chars() {
        match c {
            '\\' => o.push_str("\\\\"),
            '"' => o.push_str("\\\""),
            '\n' => o.push_str("\\n"),
            '\r' => o.push_str("\\r"),
            '\t' => o.push_str("\\t"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\{}", c as u32)),
            c => o.push(c),
        }
    }
    o.push('"');
    o
}

fn lua_list(v: &[String]) -> String {
    format!(
        "{{ {} }}",
        v.iter().map(|s| lua_str(s)).collect::<Vec<_>>().join(", ")
    )
}

/// The Hyprland part: a Lua table the default config's peripherals.lua applies.
pub fn hypr_lua(mods: &[Resolved]) -> String {
    let mut s = String::from(
        "-- Generated by `bromigos peripheral` from ~/.config/bromigos/peripherals.toml and the\n\
         -- modules (docs/peripherals.md); don't edit: `bromigos peripheral refresh` rewrites it.\n\
         -- Read by bromigOS's default Hyprland config (bromigos/peripherals.lua).\n\
         return {\n",
    );
    for m in mods {
        s.push_str(&format!(
            "    {{\n        id = {},\n        tag = {},\n        devices = {},\n        kb_options = {},\n        exclusive = {},\n        binds = {{\n",
            lua_str(&m.id),
            lua_str(&m.tag),
            lua_list(&m.devices),
            lua_list(&m.kb_options),
            lua_list(&m.exclusive),
        ));
        for b in &m.binds {
            s.push_str(&format!(
                "            {{ keys = {}, cmd = {}, hint = {} }},\n",
                lua_str(&b.keys),
                lua_str(&b.press),
                lua_str(&format!("{} ({}): {}", b.label, m.name, b.hint)),
            ));
            if let Some(r) = &b.release {
                s.push_str(&format!(
                    "            {{ keys = {}, cmd = {}, release = true, hint = {} }},\n",
                    lua_str(&b.keys),
                    lua_str(r),
                    lua_str(&format!("{} ({}): {}, released", b.label, m.name, b.hint)),
                ));
            }
        }
        s.push_str("        },\n    },\n");
    }
    s.push_str("}\n");
    s
}

/// Device names seen before, per module: `~/.local/state/bromigos/peripherals/devices.json`.
/// A keyboard unplugged keeps its names (and Hyprland its config), so plugging it in and
/// out never rewrites the keys; a new keyboard adds its own.
pub fn known_file(paths: &Paths) -> PathBuf {
    state_dir(paths).join("devices.json")
}

fn known(paths: &Paths) -> BTreeMap<String, Vec<String>> {
    fs::read_to_string(known_file(paths))
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

/// Records the names the enabled modules use now (written with the Hyprland part).
pub fn remember(paths: &Paths, mods: &[Resolved]) -> std::io::Result<()> {
    let mut k = known(paths);
    for m in mods {
        k.insert(m.id.clone(), m.devices.clone());
    }
    k.retain(|id, _| mods.iter().any(|m| &m.id == id));
    let text = serde_json::to_string_pretty(&k).unwrap_or_default();
    if mods.is_empty() {
        return match fs::remove_file(known_file(paths)) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e),
            _ => Ok(()),
        };
    }
    write_atomic(&known_file(paths), &text)
}

/// The enabled modules, resolved for this machine. Err when peripherals.toml is broken;
/// problems with single modules (unknown, broken) are in the second list.
pub fn enabled(paths: &Paths, root: &Path) -> Result<(Vec<Resolved>, Vec<String>), String> {
    let choices = read_choices(paths)?;
    let (mods, bad) = modules(paths);
    let holo = paths
        .holo_bin
        .exists()
        .then(|| paths.holo_bin.to_string_lossy().into_owned());
    let seen = known(paths);
    let mut out = vec![];
    let mut problems: Vec<String> = vec![];
    for (id, c) in choices.iter().filter(|(_, c)| c.enabled) {
        match mods.iter().find(|m| &m.id == id) {
            Some(m) => {
                let mut r = resolve(m, c, found_here(m, root), holo.as_deref());
                for n in seen.get(id).into_iter().flatten() {
                    if !r.devices.contains(n) {
                        r.devices.push(n.clone());
                    }
                }
                out.push(r)
            }
            None => problems.push(match bad.iter().find(|(b, _)| b == id) {
                Some((_, e)) => format!("{id}: {e}"),
                None => format!("{id}: no such module (bromigos peripheral list)"),
            }),
        }
    }
    Ok((out, problems))
}

// ------------------------------------------------------------------ applying it

/// What writing the Hyprland part did.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Written {
    pub file: PathBuf,
    /// The text changed (false: the same as before, nothing reloaded).
    pub changed: bool,
    /// "reloaded", "no running session", "not reloaded (--no-reload)", "unchanged", or why
    /// the reload failed (then the previous file was put back).
    pub reload: String,
    pub ok: bool,
}

/// Writes hypr.lua (removed when no module is on) and makes the running Hyprland take it
/// the safe way: auto-reload off, the new file, `Hyprland --verify-config` on the user's
/// config, one `hyprctl reload`, `hyprctl configerrors`; a config that doesn't verify gets
/// the previous file back. `reload: false` only writes.
pub fn write_hypr(paths: &Paths, mods: &[Resolved], reload: bool) -> Written {
    let w = write_hypr_file(paths, mods, reload);
    if w.ok {
        let _ = remember(paths, mods);
    }
    w
}

fn write_hypr_file(paths: &Paths, mods: &[Resolved], reload: bool) -> Written {
    let file = hypr_file(paths);
    let old = fs::read_to_string(&file).ok();
    let new = (!mods.is_empty()).then(|| hypr_lua(mods));
    let changed = old != new;
    let done = |reload: &str, ok: bool| Written {
        file: file.clone(),
        changed,
        reload: reload.into(),
        ok,
    };
    if !changed {
        return done("unchanged", true);
    }
    let put = |text: &Option<String>| -> std::io::Result<()> {
        match text {
            Some(t) => write_atomic(&file, t),
            None => match fs::remove_file(&file) {
                Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e),
                _ => Ok(()),
            },
        }
    };
    let session = if reload {
        crate::session::discover(paths).session
    } else {
        None
    };
    let Some(s) = session else {
        return match put(&new) {
            Ok(()) => done(
                if reload {
                    "no running session"
                } else {
                    "not reloaded (--no-reload)"
                },
                true,
            ),
            Err(e) => done(&format!("{}: {e}", file.display()), false),
        };
    };
    let hyprctl = |args: &[&str]| -> String {
        Command::new("hyprctl")
            .args(args)
            .envs(s.env())
            .stdin(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
            .unwrap_or_default()
    };
    let autoreload = |off: bool| {
        hyprctl(&[
            "eval",
            &format!("hl.config({{ misc = {{ disable_autoreload = {off} }} }})"),
        ])
    };
    autoreload(true);
    if let Err(e) = put(&new) {
        autoreload(false);
        return done(&format!("{}: {e}", file.display()), false);
    }
    let user_conf = paths.config_home.join("hypr/hyprland.lua");
    let verify = Command::new("Hyprland")
        .arg("--verify-config")
        .arg("-c")
        .arg(&user_conf)
        .envs(s.env())
        .stdin(std::process::Stdio::null())
        .output();
    let verified = match &verify {
        Ok(o) => {
            let out = format!(
                "{}{}",
                String::from_utf8_lossy(&o.stdout),
                String::from_utf8_lossy(&o.stderr)
            );
            if o.status.success() && out.contains("config ok") {
                Ok(())
            } else {
                Err(out.lines().rev().take(3).collect::<Vec<_>>().join(" | "))
            }
        }
        Err(e) => Err(format!("Hyprland --verify-config: {e}")),
    };
    if let Err(why) = verified {
        let _ = put(&old);
        autoreload(false);
        return done(
            &format!("the config didn't verify, the previous file is back: {why}"),
            false,
        );
    }
    hyprctl(&["reload"]);
    let errs = hyprctl(&["configerrors"]);
    if errs.is_empty() {
        done("reloaded", true)
    } else {
        done(&format!("reloaded with config errors: {errs}"), false)
    }
}

/// `enable`'s system steps for a module: the packages missing, the groups the user isn't
/// in, its user services and the daemon. (commands, notes)
pub fn enable_plan(
    m: &Manifest,
    user: &str,
    yes: bool,
    runner: &mut dyn Runner,
) -> (Vec<Vec<String>>, Vec<String>) {
    let mut cmds: Vec<Vec<String>> = vec![];
    let mut notes = vec![];
    let missing: Vec<String> = m
        .needs
        .packages
        .iter()
        .filter(|p| runner.query(&["pacman", "-Qq", p.as_str()]).0 != 0)
        .cloned()
        .collect();
    if !missing.is_empty() {
        let mut c: Vec<String> = ["sudo", "pacman", "-S", "--needed"]
            .iter()
            .map(|s| s.to_string())
            .collect();
        if yes {
            c.push("--noconfirm".into());
        }
        c.extend(missing.iter().cloned());
        cmds.push(c);
        if missing.iter().any(|p| p.ends_with("-dkms")) {
            notes.push(
                "a kernel driver was installed (DKMS): it loads after a reboot, or `sudo modprobe` now"
                    .into(),
            );
        }
    }
    let (_, ids) = runner.query(&["id", "-nG", user]);
    let mine: Vec<&str> = ids.split_whitespace().collect();
    for g in &m.needs.groups {
        if !mine.contains(&g.as_str()) {
            cmds.push(
                ["sudo", "gpasswd", "-a", user, g.as_str()]
                    .iter()
                    .map(|s| s.to_string())
                    .collect(),
            );
            notes.push(format!(
                "you joined the {g} group: it applies after you log out and back in"
            ));
        }
    }
    for u in m
        .needs
        .user_services
        .iter()
        .map(String::as_str)
        .chain([DAEMON_UNIT])
    {
        let enabled = runner
            .query(&["systemctl", "--user", "is-enabled", u])
            .1
            .trim()
            == "enabled";
        let active = runner
            .query(&["systemctl", "--user", "is-active", u])
            .1
            .trim()
            == "active";
        if u == DAEMON_UNIT && active {
            // the daemon reads the modules when it starts: a new one needs a restart
            cmds.push(
                ["systemctl", "--user", "restart", u]
                    .iter()
                    .map(|s| s.to_string())
                    .collect(),
            );
        } else if !enabled || !active {
            cmds.push(
                ["systemctl", "--user", "enable", "--now", u]
                    .iter()
                    .map(|s| s.to_string())
                    .collect(),
            );
        }
    }
    (cmds, notes)
}

/// The user's login name (for the group step).
pub fn user_name(runner: &mut dyn Runner) -> String {
    ["USER", "LOGNAME"]
        .iter()
        .find_map(|k| std::env::var(k).ok().filter(|u| !u.is_empty()))
        .unwrap_or_else(|| runner.query(&["id", "-un"]).1.trim().to_string())
}

/// Runs commands in order; `sudo` ones keep the terminal (pacman's questions, the password).
pub fn run_commands(cmds: &[Vec<String>], runner: &mut dyn Runner) -> Result<(), String> {
    for c in cmds {
        let interactive = c.first().is_some_and(|w| w == "sudo");
        match runner.run(c, interactive) {
            Ok((0, _)) => {}
            Ok((code, out)) => {
                return Err(format!(
                    "`{}` exited {code}{}",
                    c.join(" "),
                    out.lines()
                        .last()
                        .map(|l| format!(": {l}"))
                        .unwrap_or_default()
                ));
            }
            Err(e) => return Err(format!("`{}`: {e}", c.join(" "))),
        }
    }
    Ok(())
}

/// How to turn a module on.
#[derive(Debug, Clone, Copy)]
pub struct EnableOpts {
    /// pacman's questions answered with their defaults.
    pub yes: bool,
    /// On even when its device isn't connected now.
    pub force: bool,
    /// Make the running Hyprland take the keys (a verified reload).
    pub reload: bool,
    /// Install what it needs, join its groups, start its services and the daemon.
    pub system: bool,
}

/// What turning a module on (or off) did.
#[derive(Debug, Clone, Serialize)]
pub struct Changed {
    pub ok: bool,
    pub id: String,
    pub name: String,
    pub found: Vec<Found>,
    /// The system commands run (packages, groups, services, the daemon).
    pub commands: Vec<Vec<String>>,
    pub notes: Vec<String>,
    pub hypr: Option<Written>,
    /// Why a command failed.
    pub error: Option<String>,
    pub problems: Vec<String>,
    /// The module as it runs now (on enable).
    pub module: Option<Resolved>,
}

/// Turns module `id` on: its packages and groups (sudo), the choice in peripherals.toml,
/// the Hyprland part (a verified reload), then its user services and the daemon (started,
/// or restarted to read the new module). Err: no such module, a broken peripherals.toml,
/// or its device isn't here (without `force`).
pub fn enable(
    paths: &Paths,
    root: &Path,
    id: &str,
    o: EnableOpts,
    runner: &mut dyn Runner,
) -> Result<Changed, String> {
    let (mods, bad) = modules(paths);
    let Some(m) = mods.iter().find(|m| m.id == id) else {
        if let Some((_, e)) = bad.iter().find(|(b, _)| b == id) {
            return Err(format!("{id}: {e}"));
        }
        return Err(format!(
            "no module {id:?} ({})",
            mods.iter()
                .map(|m| m.id.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        ));
    };
    read_choices(paths)?;
    let found = found_here(m, root);
    if found.is_empty() && !o.force {
        return Err(format!(
            "no {} is connected (bromigos peripheral list); --force turns it on anyway",
            m.name
        ));
    }
    let (cmds, notes) = if o.system {
        let user = user_name(runner);
        enable_plan(m, &user, o.yes, runner)
    } else {
        (vec![], vec![])
    };
    // packages and groups first; the services (the daemon reads the choice) after the file
    let (first, services): (Vec<Vec<String>>, Vec<Vec<String>>) = cmds
        .into_iter()
        .partition(|c| c.first().is_some_and(|w| w == "sudo"));
    let mut out = Changed {
        ok: false,
        id: id.into(),
        name: m.name.clone(),
        found,
        commands: first.clone(),
        notes,
        hypr: None,
        error: None,
        problems: vec![],
        module: None,
    };
    if let Err(e) = run_commands(&first, runner) {
        out.error = Some(e);
        return Ok(out);
    }
    set_enabled(paths, id, true)?;
    let (resolved, problems) = enabled(paths, root)?;
    let w = write_hypr(paths, &resolved, o.reload);
    out.commands.extend(services.iter().cloned());
    out.error = run_commands(&services, runner).err();
    out.ok = w.ok && out.error.is_none();
    out.hypr = Some(w);
    out.problems = problems;
    out.module = resolved.into_iter().find(|r| r.id == id);
    Ok(out)
}

/// Turns module `id` off (its packages stay): the choice, the Hyprland part, and the daemon
/// stopped when no module is left (else restarted without it).
pub fn disable(
    paths: &Paths,
    root: &Path,
    id: &str,
    reload: bool,
    system: bool,
    runner: &mut dyn Runner,
) -> Result<Option<Changed>, String> {
    let choices = read_choices(paths)?;
    if !choices.get(id).is_some_and(|c| c.enabled) {
        return Ok(None);
    }
    set_enabled(paths, id, false)?;
    let (resolved, problems) = enabled(paths, root)?;
    let w = write_hypr(paths, &resolved, reload);
    let verb = if resolved.is_empty() {
        "disable"
    } else {
        "try-restart"
    };
    let daemon: Vec<Vec<String>> = if !system {
        vec![]
    } else {
        let mut c: Vec<String> = ["systemctl", "--user", verb]
            .iter()
            .map(|s| s.to_string())
            .collect();
        if verb == "disable" {
            c.push("--now".into());
        }
        c.push(DAEMON_UNIT.into());
        vec![c]
    };
    let error = run_commands(&daemon, runner).err();
    Ok(Some(Changed {
        ok: w.ok && error.is_none(),
        id: id.into(),
        name: id.into(),
        found: vec![],
        commands: daemon,
        notes: vec![],
        hypr: Some(w),
        error,
        problems,
        module: None,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    // His keyboard and mouse as /proc/bus/input/devices lists them (trimmed to what the
    // detection reads): a BlackWidow V4 Pro (razerkbd) and a Naga Hex V2 (razermouse),
    // whose third interface is a full keyboard too.
    pub const DEVICES: &str = "\
I: Bus=0003 Vendor=1532 Product=0050 Version=0111
N: Name=\"Razer Razer Naga Hex V2\"
P: Phys=usb-0000:0c:00.3-2.4/input0
S: Sysfs=/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb5/5-2/5-2.4/5-2.4:1.0/0003:1532:0050.000D/input/input16
H: Handlers=event5 mouse0
B: EV=17
B: KEY=1f0000 0 0 0 0
B: REL=903

I: Bus=0003 Vendor=1532 Product=028d Version=0111
N: Name=\"Razer Razer BlackWidow V4 Pro\"
P: Phys=usb-0000:0c:00.3-2.2/input0
S: Sysfs=/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb5/5-2/5-2.2/5-2.2:1.0/0003:1532:028D.0006/input/input19
H: Handlers=sysrq kbd leds event13
B: EV=120013
B: KEY=3c0000000000 0 0 0 0 0 0 1000000000007 ff9f207ac14057ff febeffdfffefffff fffffffffffffffe

I: Bus=0003 Vendor=1532 Product=0050 Version=0111
N: Name=\"Razer Razer Naga Hex V2\"
P: Phys=usb-0000:0c:00.3-2.4/input2
S: Sysfs=/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb5/5-2/5-2.4/5-2.4:1.2/0003:1532:0050.000F/input/input32
H: Handlers=sysrq kbd leds event18
B: KEY=1000000000007 ff9f207ac14057ff febeffdfffefffff fffffffffffffffe

I: Bus=0003 Vendor=1532 Product=028d Version=0111
N: Name=\"Razer Razer BlackWidow V4 Pro\"
P: Phys=usb-0000:0c:00.3-2.2/input1
S: Sysfs=/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb5/5-2/5-2.2/5-2.2:1.1/0003:1532:028D.0007/input/input33
H: Handlers=sysrq kbd leds event22
B: KEY=3c0000000000 733eff 0 0 483ffff17aff32d bfd4444600000000 1 130c730b17c007 ffa67bfad941dfff febeffdfffefffff fffffffffffffffe
B: REL=1040

I: Bus=0003 Vendor=1532 Product=028d Version=0111
N: Name=\"Razer Razer BlackWidow V4 Pro\"
P: Phys=usb-0000:0c:00.3-2.2/input2
S: Sysfs=/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb5/5-2/5-2.2/5-2.2:1.2/0003:1532:028D.0008/input/input34
H: Handlers=kbd event25 mouse1
B: KEY=3c0000000000 0 0 0 0 0 1f0000 0 0 c000000000000 0
B: REL=1043

I: Bus=0003 Vendor=046d Product=c52b Version=0111
N: Name=\"Logitech USB Receiver\"
P: Phys=usb-0000:00:14.0-1/input0
S: Sysfs=/devices/pci0000:00/0000:00:14.0/usb1/1-1/1-1:1.0/0003:046D:C52B.0001/input/input3
H: Handlers=sysrq kbd event3
B: KEY=1000000000007 ff9f207ac14057ff febeffdfffefffff fffffffffffffffe
";

    fn manifest() -> Manifest {
        let mut m: Manifest = toml::from_str(
            r#"
format = 1
name = "Razer keyboard"
description = "test"
[match]
usb_vendor = "1532"
hid_drivers = ["razerkbd"]
name_hints = ["BlackWidow"]
[keymap]
options = ["fkeys:basic_13-24"]
exclusive = ["XF86AudioMicMute"]
[[keys]]
id = "m1"
code = 191
label = "M1"
press = "{holo} vector"
hint = "VECTOR"
[[keys]]
id = "m2"
code = 192
label = "M2"
press = "{holo} ptt on"
release = "{holo} ptt off"
hint = "push to talk"
[[keys]]
id = "side1"
code = 196
label = "side 1"
press = "bromigos-menu"
hint = "the menu"
[dial]
turn = "vector-voice"
roller = "volume"
hint = "voices"
[rgb]
backend = "openrazer"
follow = "vector"
hint = "lighting"
"#,
        )
        .unwrap();
        m.id = "razer-keyboard".into();
        m.validate().unwrap();
        m
    }

    fn drivers(hid: &str) -> Option<String> {
        if hid.contains(":028D.") {
            Some("razerkbd".into())
        } else if hid.contains(":0050.") {
            Some("razermouse".into())
        } else {
            Some("hid-generic".into())
        }
    }

    #[test]
    fn parses_the_devices_and_their_bits() {
        let d = parse_input_devices(DEVICES);
        assert_eq!(d.len(), 6);
        let dial = &d[4];
        assert_eq!(dial.name, "Razer Razer BlackWidow V4 Pro");
        assert_eq!(
            (dial.vendor.as_str(), dial.product.as_str()),
            ("1532", "028d")
        );
        assert!(dial.has_rel(REL_X) && dial.has_rel(REL_HWHEEL));
        assert_eq!(dial.event(), Some("event25"));
        assert_eq!(dial.hid(), Some("0003:1532:028D.0008"));
        assert!(dial.usb_device().ends_with("/usb5/5-2/5-2.2"));
        // the consumer interface has a horizontal wheel but no pointer: not the dial
        assert!(d[3].has_rel(REL_HWHEEL) && !d[3].has_rel(REL_X));
        // KEY_A (30) on the main interface
        assert!(d[1].has_key(30) && d[1].is_keyboard());
    }

    #[test]
    fn finds_the_keyboard_not_the_mouse_or_other_vendors() {
        let devs = parse_input_devices(DEVICES);
        let f = detect(&manifest(), &devs, &drivers);
        assert_eq!(f.len(), 1, "{f:?}");
        let k = &f[0];
        assert_eq!(k.name, "Razer Razer BlackWidow V4 Pro");
        assert_eq!(k.usb, "1532:028d");
        assert_eq!(k.how, "driver");
        assert_eq!(k.driver.as_deref(), Some("razerkbd"));
        assert_eq!(k.dial.as_deref(), Some("/dev/input/event25"));
        assert_eq!(
            k.keyboards,
            [
                "/dev/input/event13",
                "/dev/input/event22",
                "/dev/input/event25"
            ]
        );
        assert_eq!(k.hypr_names[0], "razer-razer-blackwidow-v4-pro");
        assert_eq!(k.hypr_names[5], "razer-razer-blackwidow-v4-pro-5");
        assert_eq!(k.hypr_names.len(), 1 + NAME_SUFFIXES as usize);
    }

    #[test]
    fn before_openrazer_a_name_hint_finds_it() {
        let devs = parse_input_devices(DEVICES);
        let generic = |_: &str| Some("hid-generic".to_string());
        let f = detect(&manifest(), &devs, &generic);
        // the BlackWidow by its name; the Naga has no hint
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].how, "name");
        assert!(f[0].driver.is_none());
        let none = |_: &str| -> Option<String> { None };
        assert_eq!(detect(&manifest(), &devs, &none).len(), 1);
    }

    #[test]
    fn resolves_keys_with_the_users_changes() {
        let devs = parse_input_devices(DEVICES);
        let found = detect(&manifest(), &devs, &drivers);
        let mut c = Choice {
            enabled: true,
            dial: true,
            ..Default::default()
        };
        c.keys.insert(
            "side1".into(),
            KeyChoice::Press("bromigos-live timeline".into()),
        );
        c.keys.insert("nope".into(), KeyChoice::Press("x".into()));
        c.devices.push("my-extra-name".into());
        let r = resolve(&manifest(), &c, found, Some("/usr/bin/bromigos-holo"));
        assert_eq!(r.tag, "bromigos-razer-keyboard");
        assert_eq!(r.binds.len(), 3);
        assert_eq!(r.binds[0].press, "/usr/bin/bromigos-holo vector");
        assert_eq!(
            r.binds[1].release.as_deref(),
            Some("/usr/bin/bromigos-holo ptt off")
        );
        assert_eq!(r.binds[2].press, "bromigos-live timeline");
        assert!(r.binds[2].changed && !r.binds[0].changed);
        assert!(r.skipped.iter().any(|s| s.starts_with("nope")));
        assert_eq!(r.devices.last().map(String::as_str), Some("my-extra-name"));
        assert_eq!(r.dials, ["/dev/input/event25"]);
        // no VECTOR: his keys are left out, the rest stay
        let r = resolve(&manifest(), &c, detect(&manifest(), &devs, &drivers), None);
        assert_eq!(r.binds.len(), 1);
        assert_eq!(r.skipped.len(), 3);
        // a key unbound, the dial and the lighting off
        c.keys
            .insert("side1".into(), KeyChoice::Press(String::new()));
        c.dial = false;
        c.rgb = RgbScope::Off;
        let r = resolve(&manifest(), &c, vec![], Some("h"));
        assert_eq!(r.binds.len(), 2);
        assert!(r.dial.is_none() && r.rgb.is_none() && r.dials.is_empty());
    }

    #[test]
    fn the_lighting_can_follow_the_theme() {
        let mut c = Choice {
            enabled: true,
            ..Default::default()
        };
        let r = resolve(&manifest(), &c, vec![], None);
        assert_eq!(r.rgb.map(|r| r.follow).as_deref(), Some("vector"));
        c.rgb_follow = Some("theme".into());
        let r = resolve(&manifest(), &c, vec![], None);
        assert_eq!(r.rgb.map(|r| r.follow).as_deref(), Some("theme"));
        // an unknown value keeps the module's, and says so
        c.rgb_follow = Some("disco".into());
        let r = resolve(&manifest(), &c, vec![], None);
        assert_eq!(r.rgb.map(|r| r.follow).as_deref(), Some("vector"));
        assert!(r.skipped.iter().any(|s| s.starts_with("rgb_follow")));
        let toml_in = "enabled = true\nrgb_follow = \"theme\"\n";
        let parsed: Choice = toml::from_str(toml_in).unwrap();
        assert_eq!(parsed.rgb_follow.as_deref(), Some("theme"));
    }

    #[test]
    fn the_lua_is_a_table_of_binds() {
        let devs = parse_input_devices(DEVICES);
        let found = detect(&manifest(), &devs, &drivers);
        let c = Choice {
            enabled: true,
            dial: true,
            ..Default::default()
        };
        let mut r = resolve(&manifest(), &c, found, Some("/usr/bin/bromigos-holo"));
        r.binds[2].press = "sh -c 'echo \"hi\\there\"'".into();
        let lua = hypr_lua(&[r]);
        assert!(lua.contains("tag = \"bromigos-razer-keyboard\""));
        assert!(lua.contains("kb_options = { \"fkeys:basic_13-24\" }"));
        assert!(lua.contains("exclusive = { \"XF86AudioMicMute\" }"));
        assert!(lua.contains(
            "{ keys = \"code:192\", cmd = \"/usr/bin/bromigos-holo ptt off\", release = true,"
        ));
        assert!(
            lua.contains(r#"cmd = "sh -c 'echo \"hi\\there\"'""#),
            "{lua}"
        );
        assert!(lua.trim_end().ends_with('}'));
        assert_eq!(hypr_lua(&[]).matches("return {").count(), 1);
    }

    #[test]
    fn enabling_keeps_the_rest_of_the_file() {
        let t = with_enabled("", "razer-keyboard", true).unwrap();
        assert!(t.starts_with("# bromigos peripheral"));
        let parsed: BTreeMap<String, Choice> = toml::from_str(&t).unwrap();
        assert!(parsed["razer-keyboard"].enabled);
        let mine = "# mine\n[razer-keyboard.keys]\nside1 = \"x\" # the deck\n";
        let t = with_enabled(mine, "razer-keyboard", true).unwrap();
        assert!(t.contains("# the deck"));
        assert!(
            t.starts_with("# mine\n[razer-keyboard]\nenabled = true\n"),
            "{t}"
        );
        let parsed: BTreeMap<String, Choice> = toml::from_str(&t).unwrap();
        assert!(parsed["razer-keyboard"].enabled);
        assert_eq!(
            parsed["razer-keyboard"].keys["side1"],
            KeyChoice::Press("x".into())
        );
        let t = with_enabled(&t, "razer-keyboard", false).unwrap();
        assert!(!toml::from_str::<BTreeMap<String, Choice>>(&t).unwrap()["razer-keyboard"].enabled);
    }

    #[test]
    fn the_lighting_follow_is_written_beside_the_rest() {
        let mine =
            "# mine\n[razer-keyboard]\nenabled = true # on\n[razer-keyboard.keys]\nside1 = \"x\"\n";
        let t = with_value(
            mine,
            "razer-keyboard",
            "rgb_follow",
            toml_edit::value("theme"),
        )
        .unwrap();
        assert!(
            t.contains("enabled = true # on") && t.contains("side1 = \"x\""),
            "{t}"
        );
        let parsed: BTreeMap<String, Choice> = toml::from_str(&t).unwrap();
        assert_eq!(
            parsed["razer-keyboard"].rgb_follow.as_deref(),
            Some("theme")
        );
        let t = with_value(
            &t,
            "razer-keyboard",
            "rgb_follow",
            toml_edit::value("vector"),
        )
        .unwrap();
        let parsed: BTreeMap<String, Choice> = toml::from_str(&t).unwrap();
        assert_eq!(
            parsed["razer-keyboard"].rgb_follow.as_deref(),
            Some("vector")
        );
        assert!(parsed["razer-keyboard"].enabled);
    }

    #[test]
    fn a_follow_that_isnt_one_is_refused() {
        let d = tempfile::tempdir().unwrap();
        let home = d.path().join("home");
        let paths = Paths::from_lookup(move |k| match k {
            "HOME" => Some(home.clone()),
            _ => None,
        });
        assert!(set_follow(&paths, "razer-keyboard", "disco").is_err());
        assert!(!config_file(&paths).exists());
        set_follow(&paths, "razer-keyboard", "theme").unwrap();
        let parsed: BTreeMap<String, Choice> =
            toml::from_str(&fs::read_to_string(config_file(&paths)).unwrap()).unwrap();
        assert_eq!(
            parsed["razer-keyboard"].rgb_follow.as_deref(),
            Some("theme")
        );
    }

    #[test]
    fn a_typo_in_the_users_file_is_an_error() {
        assert!(toml::from_str::<BTreeMap<String, Choice>>("[k]\nenabeld = true\n").is_err());
        let both: BTreeMap<String, Choice> =
            toml::from_str("[k.keys]\nm2 = { press = \"a\", release = \"b\" }\n").unwrap();
        assert_eq!(
            both["k"].keys["m2"],
            KeyChoice::Both {
                press: "a".into(),
                release: Some("b".into())
            }
        );
        assert!(both["k"].dial && !both["k"].enabled);
    }

    #[test]
    fn manifests_are_checked() {
        let mut m = manifest();
        m.keys[0].code = 3;
        assert!(m.validate().unwrap_err().contains("keycode"));
        let mut m = manifest();
        m.keys[1].id = "m1".into();
        assert!(m.validate().unwrap_err().contains("twice"));
        let mut m = manifest();
        m.matcher.usb_vendor = "razer".into();
        assert!(m.validate().is_err());
        let mut m = manifest();
        m.dial.as_mut().unwrap().turn = "zoom".into();
        assert!(m.validate().is_err());
        let mut m = manifest();
        m.keymap.options.push("a,b".into());
        assert!(m.validate().is_err());
    }

    #[test]
    fn hyprland_names() {
        assert_eq!(
            hypr_name("Razer Razer BlackWidow V4 Pro"),
            "razer-razer-blackwidow-v4-pro"
        );
        assert_eq!(
            hypr_name("AT Translated Set 2 keyboard"),
            "at-translated-set-2-keyboard"
        );
    }
}
