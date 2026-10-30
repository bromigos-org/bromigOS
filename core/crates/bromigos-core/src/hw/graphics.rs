//! What each graphics card is for: Settings › Graphics and `bromigos hw display`, `hw
//! games`, `hw run` and `hw vfio` (docs/hardware.md, "What each card is for"). Any number
//! of cards, from any vendor, on desktops and laptops. Three uses:
//!
//! - **Desktop**: the card the login screen and Hyprland render on. Automatic is
//!   [`super::display_selection_for_seat`]'s rule (and a laptop's integrated-renders
//!   policy). A chosen card wins while it has a connected monitor. A new choice is a
//!   *trial* first: it's in force only during the boot it was made in, so a restart goes
//!   back by itself, and `bromigos hw display keep` keeps it once a login on it works.
//!   `bromigos hw display reset`, from a text console, goes back to Automatic.
//! - **Games and heavy apps**: the card `bromigos hw run` starts a program on, through
//!   each vendor's own switches ([`run_env`]). Automatic: the strongest card
//!   ([`strongest`]). It's the user's own choice, in their config.
//! - **Virtual machines**: a card reserved for VFIO passthrough by PCI address, never by
//!   vendor and device ID (two identical cards), after the checks in [`vfio_state`].
//!
//! A choice names a card by its PCI address and its ID together. Every start reads the
//! cards again: a saved card that's gone, or a different card in its slot, counts as
//! Automatic. Nothing here writes a system file; the command does, as root
//! (`bromigos hw`), from what these functions decide.

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use super::{
    AMD, Detection, DisplaySelection, Gpu, Hybrid, INTEL, NVIDIA, Stack,
    display_selection_for_seat, is_vfio, read_trim, usable_on,
};
use crate::paths::Paths;
use crate::snapshot::{Bootloader, Files};

/// The desktop's chosen card, a trial, and the cards reserved for VMs (root's; anyone
/// may read it: the login screen does).
pub const SYSTEM_FILE: &str = "/var/lib/bromigos/hw/graphics.json";
/// This boot's ID: a trial is in force only during the boot it was made in.
pub const BOOT_ID: &str = "/proc/sys/kernel/random/boot_id";
/// The VFIO reservation: the script that sets each card's driver_override in the
/// initramfs, modprobe's lines that run it before any graphics driver, and the initramfs
/// drop-in that carries both.
pub const VFIO_SCRIPT: &str = "/etc/bromigos/hw/vfio-pci-override.sh";
pub const VFIO_MODPROBE: &str = "/etc/modprobe.d/bromigos-vfio.conf";
pub const VFIO_INITRAMFS: &str = "/etc/mkinitcpio.conf.d/bromigos-vfio.conf";
/// Mesa's device-select layer: what orders Vulkan's devices (any vendor's).
pub const DEVICE_SELECT_LAYER: &str =
    "/usr/share/vulkan/implicit_layer.d/VkLayer_MESA_device_select.json";
/// Steam's launcher, and the first line of the user's copy that starts it on the games card.
pub const STEAM_DESKTOP: &str = "/usr/share/applications/steam.desktop";
const STEAM_MARK: &str = "# bromigos hw games steam:";
/// GLVND's Mesa EGL vendor file (an AMD or Intel games card while NVIDIA draws the desktop).
const MESA_EGL: &str = "/usr/share/glvnd/egl_vendor.d/50_mesa.json";

// ------------------------------------------------------------------------- the choices

/// A card, as a choice names it: its PCI address and its ID, and its name for messages.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct CardRef {
    pub slot: String,
    pub id: String,
    pub name: String,
}

impl CardRef {
    pub fn of(g: &Gpu) -> Self {
        CardRef {
            slot: g.slot.clone(),
            id: g.id.clone(),
            name: g.title(),
        }
    }
    /// The card, when it's still at its address (the same ID there: not a swapped one).
    pub fn find<'a>(&self, d: &'a Detection) -> Option<&'a Gpu> {
        d.gpus
            .iter()
            .find(|g| g.slot == self.slot && g.id == self.id)
    }
    fn is(&self, g: &Gpu) -> bool {
        self.slot == g.slot && self.id == g.id
    }
}

/// A desktop card being tried: in force only during the boot it was made in.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Trial {
    pub card: CardRef,
    pub boot_id: String,
}

/// A card reserved for virtual machines, with its other PCI functions (its audio, a USB-C
/// controller) and the kernel modules that drive those now.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Reserved {
    pub card: CardRef,
    pub functions: Vec<String>,
    pub modules: Vec<String>,
}

/// [`SYSTEM_FILE`].
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct SystemChoice {
    /// The desktop's card; None: Automatic.
    pub desktop: Option<CardRef>,
    pub trial: Option<Trial>,
    pub vfio: Vec<Reserved>,
}

impl SystemChoice {
    pub fn trial_in_force(&self, boot: &str) -> Option<&Trial> {
        self.trial
            .as_ref()
            .filter(|t| !boot.is_empty() && t.boot_id == boot)
    }
    pub fn reserved(&self, g: &Gpu) -> bool {
        self.vfio.iter().any(|r| r.card.is(g))
    }
    /// What the file holds (pretty JSON, a newline at the end).
    pub fn to_text(&self) -> String {
        serde_json::to_string_pretty(self).unwrap_or_default() + "\n"
    }
}

/// [`SYSTEM_FILE`] as it is; a missing or broken file is Automatic, nothing reserved.
pub fn read_system(files: &dyn Files) -> SystemChoice {
    files
        .read(SYSTEM_FILE)
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

pub fn boot_id(files: &dyn Files) -> String {
    read_trim(files, BOOT_ID).unwrap_or_default()
}

/// The user's own choice: `~/.config/bromigos/graphics.json`.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct UserChoice {
    /// The games card; None: Automatic (the strongest).
    pub games: Option<CardRef>,
}

pub fn user_file(paths: &Paths) -> PathBuf {
    paths.config_home.join("bromigos/graphics.json")
}

pub fn read_user(paths: &Paths) -> UserChoice {
    fs::read_to_string(user_file(paths))
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

pub fn write_user(paths: &Paths, c: &UserChoice) -> std::io::Result<()> {
    let p = user_file(paths);
    fs::create_dir_all(p.parent().unwrap_or(&p))?;
    let tmp = p.with_extension("tmp");
    fs::write(
        &tmp,
        serde_json::to_string_pretty(c).unwrap_or_default() + "\n",
    )?;
    fs::rename(tmp, p)
}

// ---------------------------------------------------------------------------- desktop

/// The desktop's card at the next start: the selection Hyprland and the login screen get.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Desktop {
    #[serde(flatten)]
    pub selection: DisplaySelection,
    /// trial, chosen or automatic.
    pub source: String,
    /// The preferred card's PCI address, when there is one.
    pub slot: Option<String>,
    /// Why a saved choice isn't in force (the card is gone, or has no monitor).
    pub note: Option<String>,
}

/// It can render the desktop now: a working host driver, on the seat, a monitor connected.
pub fn desktop_ready(g: &Gpu, seat: &str) -> bool {
    usable_on(g, seat) && !g.connected_connectors.is_empty()
}

fn preferring(d: &Detection, seat: &str, g: &Gpu, code: &str, reason: String) -> DisplaySelection {
    let mut usable: Vec<&Gpu> = d.gpus.iter().filter(|x| usable_on(x, seat)).collect();
    usable.sort_by(|a, b| a.slot.cmp(&b.slot));
    usable.sort_by_key(|x| x.slot != g.slot);
    DisplaySelection {
        primary_card: g.card.clone(),
        drm_devices: usable
            .iter()
            .filter_map(|x| x.card.as_ref().map(|c| format!("/dev/dri/{c}")))
            .collect(),
        reason_code: code.into(),
        reason,
    }
}

/// Why a saved card isn't used now.
fn unready(c: &CardRef, d: &Detection, seat: &str) -> String {
    let name = if c.name.is_empty() { &c.slot } else { &c.name };
    match c.find(d) {
        None => format!("{name} isn't at {} any more", c.slot),
        Some(g) if !usable_on(g, seat) => format!("{name} has no working driver for the desktop"),
        Some(_) => format!("{name} has no monitor connected"),
    }
}

/// The desktop's card for `seat` at this start: a trial in force, else the chosen card,
/// else Automatic. A saved card counts only while it's there with a monitor connected.
pub fn desktop(d: &Detection, seat: &str, choice: &SystemChoice, boot: &str) -> Desktop {
    let seat = if seat.is_empty() { "seat0" } else { seat };
    let mut notes = vec![];
    if let Some(t) = choice.trial_in_force(boot) {
        match t.card.find(d).filter(|g| desktop_ready(g, seat)) {
            Some(g) => {
                return Desktop {
                    selection: preferring(
                        d,
                        seat,
                        g,
                        "trial_gpu",
                        format!(
                            "Trying {} for the desktop: keep it, or restart to go back.",
                            g.title()
                        ),
                    ),
                    source: "trial".into(),
                    slot: Some(g.slot.clone()),
                    note: None,
                };
            }
            None => notes.push(format!(
                "The card being tried isn't used: {}.",
                unready(&t.card, d, seat)
            )),
        }
    }
    if let Some(c) = &choice.desktop {
        match c.find(d).filter(|g| desktop_ready(g, seat)) {
            Some(g) => {
                return Desktop {
                    selection: preferring(
                        d,
                        seat,
                        g,
                        "chosen_gpu",
                        format!("{} is chosen for the desktop.", g.title()),
                    ),
                    source: "chosen".into(),
                    slot: Some(g.slot.clone()),
                    note: (!notes.is_empty()).then(|| notes.join(" ")),
                };
            }
            None => notes.push(format!(
                "The chosen card isn't used: {}. Automatic instead.",
                unready(c, d, seat)
            )),
        }
    }
    let selection = display_selection_for_seat(d, seat);
    let slot = selection
        .primary_card
        .as_ref()
        .and_then(|c| d.gpus.iter().find(|g| g.card.as_ref() == Some(c)))
        .map(|g| g.slot.clone());
    Desktop {
        selection,
        source: "automatic".into(),
        slot,
        note: (!notes.is_empty()).then(|| notes.join(" ")),
    }
}

/// The card the desktop most likely renders on without a choice: the automatic rule's,
/// else a laptop's integrated card, else the one the firmware started on, else the first.
pub fn automatic_desktop<'a>(d: &'a Detection, seat: &str) -> Option<&'a Gpu> {
    let s = display_selection_for_seat(d, seat);
    if let Some(c) = &s.primary_card {
        return d.gpus.iter().find(|g| g.card.as_ref() == Some(c));
    }
    if let Some(h) = &d.hybrid {
        return d.gpus.iter().find(|g| g.slot == h.integrated);
    }
    let usable: Vec<&Gpu> = d.gpus.iter().filter(|g| usable_on(g, seat)).collect();
    usable
        .iter()
        .find(|g| g.boot_vga)
        .or_else(|| usable.first())
        .copied()
}

/// The card this session renders on, from its AQ_DRM_DEVICES (its first device), when set.
pub fn running_desktop<'a>(d: &'a Detection, aq: Option<&str>) -> Option<&'a Gpu> {
    let first = aq?.split(':').next()?.trim();
    let name = first.strip_prefix("/dev/dri/")?;
    if name == "bromigos-igpu" || name == "bromigos-dgpu" {
        let h = d.hybrid.as_ref()?;
        let slot = if name == "bromigos-igpu" {
            &h.integrated
        } else {
            &h.discrete
        };
        return d.gpus.iter().find(|g| &g.slot == slot);
    }
    d.gpus.iter().find(|g| g.card.as_deref() == Some(name))
}

/// A card named on the command line: its PCI address (`0000:03:00.0` or `03:00.0`) or its
/// DRM card (`card1`).
pub fn find_card<'a>(d: &'a Detection, name: &str) -> Option<&'a Gpu> {
    let n = name.trim().trim_start_matches("/dev/dri/");
    d.gpus.iter().find(|g| {
        g.slot == n || g.slot.strip_prefix("0000:") == Some(n) || g.card.as_deref() == Some(n)
    })
}

// ------------------------------------------------------------------------------ games

const AMD_APUS: &[&str] = &[
    "Rembrandt",
    "Phoenix",
    "Raphael",
    "Cezanne",
    "Renoir",
    "Picasso",
    "Raven",
    "Barcelo",
    "Lucienne",
    "Mendocino",
    "Strix",
    "Hawk Point",
    "Granite Ridge",
    "Van Gogh",
    "Krackan",
    "Dragon Range",
    "Kaveri",
    "Carrizo",
    "Stoney",
    "Kabini",
    "Mullins",
];

/// The chip part of pci.ids' name ("Navi 31" of "Navi 31 [Radeon RX 7900 XT]").
fn chip(g: &Gpu) -> &str {
    g.name.split(" [").next().unwrap_or("").trim()
}

fn vendor(g: &Gpu) -> u16 {
    u16::from_str_radix(g.id.split(':').next().unwrap_or("0"), 16).unwrap_or(0)
}

/// Built into the processor (or driving a laptop's panel), rather than a card of its own.
pub fn integrated(g: &Gpu, d: &Detection) -> bool {
    if g.panel || d.hybrid.as_ref().is_some_and(|h| h.integrated == g.slot) {
        return true;
    }
    match vendor(g) {
        INTEL => !["Arc", "DG1", "DG2", "Alchemist", "Battlemage"]
            .iter()
            .any(|w| g.name.contains(w)),
        AMD | 0x1022 => {
            g.vram.is_some_and(|v| v < 2 << 30) || AMD_APUS.iter().any(|a| chip(g).starts_with(a))
        }
        _ => false,
    }
}

/// Roughly when its architecture came out: what "strongest" compares first across vendors.
pub fn era(g: &Gpu) -> u16 {
    let c = chip(g);
    match vendor(g) {
        NVIDIA => match g.family.as_deref() {
            Some("Blackwell") => 2025,
            Some("Ada Lovelace") | Some("Hopper") => 2022,
            Some("Ampere") => 2020,
            Some("Turing") => 2018,
            Some("Volta") => 2017,
            Some("Pascal") => 2016,
            Some("Maxwell") => 2014,
            Some("Kepler") => 2012,
            Some("Fermi") => 2010,
            _ if g.stack == Stack::NvidiaOpen => 2018,
            _ => 2008,
        },
        AMD | 0x1022 => {
            if c.starts_with("Navi 4") {
                2025
            } else if c.starts_with("Navi 3") {
                2022
            } else if c.starts_with("Navi 2") {
                2020
            } else if c.starts_with("Navi 1") {
                2019
            } else if c.contains("Vega") {
                2017
            } else if ["Ellesmere", "Baffin", "Lexa", "Polaris"]
                .iter()
                .any(|p| c.starts_with(p))
            {
                2016
            } else if g.stack == Stack::Radeon {
                2010
            } else {
                2013
            }
        }
        INTEL => {
            if g.name.contains("Battlemage") {
                2024
            } else if g.name.contains("Arc")
                || g.name.contains("DG2")
                || g.name.contains("Alchemist")
            {
                2022
            } else {
                2015
            }
        }
        _ => 0,
    }
}

/// It can run games: a working host driver and a DRM device (any seat), a real GPU.
pub fn game_ready(g: &Gpu) -> bool {
    g.drm_ready
        && g.driver.as_deref().is_some_and(|x| !is_vfio(x))
        && !g.driver_override.as_deref().is_some_and(is_vfio)
        && !matches!(g.stack, Stack::Virtual | Stack::Other)
}

/// The strongest card for games: a card of its own over a built-in one, then the newer
/// architecture, then more video memory where the driver says; a tie goes to the card
/// drawing the desktop (nothing to copy between cards), then the first by address.
pub fn strongest<'a>(d: &'a Detection, desktop_slot: Option<&str>) -> Option<&'a Gpu> {
    let mut c: Vec<&Gpu> = d.gpus.iter().filter(|g| game_ready(g)).collect();
    let key = |g: &Gpu| (!integrated(g, d), era(g), g.vram.unwrap_or(0));
    c.sort_by(|a, b| {
        key(b)
            .cmp(&key(a))
            .then_with(|| {
                (Some(a.slot.as_str()) != desktop_slot)
                    .cmp(&(Some(b.slot.as_str()) != desktop_slot))
            })
            .then_with(|| a.slot.cmp(&b.slot))
    });
    c.first().copied()
}

/// What a program needs in its environment to run on `t` while the desktop draws on
/// `desk` (nothing when they're the same card): the vendors' own switches.
///
/// - Vulkan (native games, and Proton's DXVK and vkd3d-proton, which take the first
///   discrete device they're given): Mesa's device-select layer puts the card first, for
///   any vendor's driver. `MESA_VK_DEVICE_SELECT=vendor:device` when no other card has the
///   same ID; `DRI_PRIME=pci-…` (its PCI address) tells identical cards apart.
/// - OpenGL on Mesa (AMD, Intel, nouveau): `DRI_PRIME=pci-…`. While NVIDIA's driver draws
///   the desktop, GLVND is pointed at Mesa too (`__GLX_VENDOR_LIBRARY_NAME=mesa`,
///   `__EGL_VENDOR_LIBRARY_FILENAMES`).
/// - NVIDIA's driver while another card draws the desktop: PRIME render offload, what
///   `prime-run` sets (`__NV_PRIME_RENDER_OFFLOAD=1`, `__VK_LAYER_NV_optimus=NVIDIA_only`,
///   `__GLX_VENDOR_LIBRARY_NAME=nvidia`).
pub fn run_env(d: &Detection, t: &Gpu, desk: Option<&Gpu>) -> BTreeMap<String, String> {
    let mut env = BTreeMap::new();
    if desk.is_some_and(|x| x.slot == t.slot) {
        return env;
    }
    let mut set = |k: &str, v: &str| {
        env.insert(k.to_string(), v.to_string());
    };
    let pci = format!("pci-{}", t.slot.replace([':', '.'], "_"));
    let twin = d
        .gpus
        .iter()
        .any(|g| g.slot != t.slot && g.id == t.id && game_ready(g));
    let t_nvidia = t.driver.as_deref() == Some("nvidia");
    let desk_nvidia = desk.is_some_and(|x| x.driver.as_deref() == Some("nvidia"));
    if twin {
        set("DRI_PRIME", &pci);
    } else {
        set("MESA_VK_DEVICE_SELECT", &t.id);
    }
    if t_nvidia {
        if !desk_nvidia {
            set("__NV_PRIME_RENDER_OFFLOAD", "1");
            set("__VK_LAYER_NV_optimus", "NVIDIA_only");
            set("__GLX_VENDOR_LIBRARY_NAME", "nvidia");
        }
    } else {
        set("DRI_PRIME", &pci);
        if desk_nvidia {
            set("__GLX_VENDOR_LIBRARY_NAME", "mesa");
            set("__EGL_VENDOR_LIBRARY_FILENAMES", MESA_EGL);
        }
    }
    env
}

/// The games card now, and what a program started on it gets.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Games {
    /// chosen or automatic.
    pub source: String,
    /// The card games use: its PCI address.
    pub slot: Option<String>,
    /// What Automatic would pick.
    pub automatic: Option<String>,
    /// The desktop's card it's compared with.
    pub desktop: Option<String>,
    pub env: BTreeMap<String, String>,
    pub notes: Vec<String>,
}

/// The games card: the user's choice while it's there and working, else the strongest.
pub fn games(files: &dyn Files, d: &Detection, user: &UserChoice, desk: Option<&Gpu>) -> Games {
    let auto = strongest(d, desk.map(|g| g.slot.as_str()));
    let mut notes = vec![];
    let chosen = user.games.as_ref().and_then(|c| {
        let g = c.find(d).filter(|g| game_ready(g));
        if g.is_none() {
            notes.push(format!(
                "{} isn't there or has no working driver: Automatic instead",
                if c.name.is_empty() { &c.slot } else { &c.name }
            ));
        }
        g
    });
    let card = chosen.or(auto);
    let env = card.map(|t| run_env(d, t, desk)).unwrap_or_default();
    if let (Some(t), Some(k)) = (card, desk)
        && t.slot != k.slot
    {
        if (env.contains_key("MESA_VK_DEVICE_SELECT") || env.contains_key("DRI_PRIME"))
            && !files.exists(DEVICE_SELECT_LAYER)
        {
            notes.push(
                "Mesa's device-select layer isn't installed, so Vulkan can't be pointed at the \
                 card: bromigos hw setup installs it (vulkan-mesa-implicit-layers)"
                    .into(),
            );
        }
        if t.driver.as_deref() == Some("nvidia") && k.driver.as_deref() == Some("nvidia") {
            notes.push(
                "Both cards run NVIDIA's driver: Vulkan games (Proton's included) follow the \
                 choice; OpenGL programs draw on the desktop's card"
                    .into(),
            );
        }
    }
    Games {
        source: if chosen.is_some() {
            "chosen"
        } else {
            "automatic"
        }
        .into(),
        slot: card.map(|g| g.slot.clone()),
        automatic: auto.map(|g| g.slot.clone()),
        desktop: desk.map(|g| g.slot.clone()),
        env,
        notes,
    }
}

pub fn steam_override(paths: &Paths) -> PathBuf {
    paths.data_home.join("applications/steam.desktop")
}

/// The user's copy of Steam's launcher is bromigOS's (it starts Steam on the games card).
pub fn steam_on(paths: &Paths) -> bool {
    fs::read_to_string(steam_override(paths)).is_ok_and(|t| t.starts_with(STEAM_MARK))
}

/// Steam's launcher with each `Exec=` started through `bromigos hw run`, so Steam and
/// every game it starts (Proton's included) run on the games card.
pub fn steam_launcher(original: &str, bromigos: &str) -> String {
    let mut out = format!(
        "{STEAM_MARK} Steam starts on the games card (Settings › Graphics). `bromigos hw games\n\
         # steam off` removes this file; a copy of {STEAM_DESKTOP}.\n"
    );
    for l in original.lines() {
        match l.strip_prefix("Exec=") {
            Some(rest) => out.push_str(&format!("Exec={bromigos} hw run -- {rest}\n")),
            None => {
                out.push_str(l);
                out.push('\n');
            }
        }
    }
    out
}

// ------------------------------------------------------------------------------- VFIO

/// One check before a card can be reserved for virtual machines.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Check {
    pub id: String,
    pub ok: bool,
    /// What it found, in a line.
    pub text: String,
    /// Why it matters and what to do: the hover hint.
    pub hint: String,
}

fn check(id: &str, ok: bool, text: String, hint: &str) -> Check {
    Check {
        id: id.into(),
        ok,
        text,
        hint: hint.into(),
    }
}

/// The IOMMU, which keeps a VM's card to the VM's memory: on, and how to turn it on.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Iommu {
    pub on: bool,
    /// intel, amd or "" (from /proc/cpuinfo).
    pub cpu: String,
    pub bootloader: Bootloader,
    /// The kernel parameter to add, when one is needed (Intel).
    pub param: Option<String>,
    /// What to do, in order, when it's off.
    pub steps: Vec<String>,
}

pub fn iommu(files: &dyn Files, bootloader: Bootloader) -> Iommu {
    let on = !files.list("/sys/kernel/iommu_groups").is_empty();
    let info = files.read("/proc/cpuinfo").unwrap_or_default();
    let cpu = if info.contains("GenuineIntel") {
        "intel"
    } else if info.contains("AuthenticAMD") {
        "amd"
    } else {
        ""
    };
    // the firmware's ACPI tables say which IOMMU the machine has, and that it's on there:
    // DMAR is Intel's VT-d (Linux leaves it off unless asked), IVRS is AMD-Vi
    let dmar = files.exists("/sys/firmware/acpi/tables/DMAR");
    let ivrs = files.exists("/sys/firmware/acpi/tables/IVRS");
    let intel = dmar || (!ivrs && cpu == "intel");
    let cmdline = files.read("/proc/cmdline").unwrap_or_default();
    let param = (intel
        && !cmdline
            .split_whitespace()
            .any(|w| w.starts_with("intel_iommu=on")))
    .then(|| "intel_iommu=on".to_string());
    let mut steps = vec![];
    if !on {
        if dmar || ivrs {
            steps.push(format!(
                "The firmware has the IOMMU on (its {} table is there), but Linux doesn't use it.",
                if dmar { "DMAR" } else { "IVRS" }
            ));
            if ivrs && param.is_none() {
                steps.push(
                    "Check the kernel's command line (/proc/cmdline) for amd_iommu=off or                      iommu=off, and remove it."
                        .into(),
                );
            }
        } else {
            steps.push(if intel {
                "Turn on the IOMMU in the computer's firmware settings (often called VT-d, or \
                 Intel Virtualization Technology for Directed I/O)."
                    .to_string()
            } else {
                "Turn on the IOMMU in the computer's firmware settings (often called AMD-Vi, \
                 IOMMU or SVM). Linux turns it on by itself once the firmware has."
                    .to_string()
            });
        }
        if let Some(p) = &param {
            steps.push(format!("Add {p} to the kernel's command line:"));
            steps.extend(cmdline_steps(bootloader, p));
        }
        steps.push("Restart the computer, then check again here.".into());
    }
    Iommu {
        on,
        cpu: cpu.into(),
        bootloader,
        param,
        steps,
    }
}

/// How to add a kernel parameter with this boot loader (bromigOS doesn't edit it).
pub fn cmdline_steps(b: Bootloader, p: &str) -> Vec<String> {
    match b {
        Bootloader::Grub => vec![
            format!(
                "sudoedit /etc/default/grub, and add {p} inside the quotes of GRUB_CMDLINE_LINUX_DEFAULT"
            ),
            "sudo grub-mkconfig -o /boot/grub/grub.cfg".into(),
        ],
        Bootloader::SystemdBoot => vec![format!(
            "With unified kernel images: add {p} to /etc/kernel/cmdline, then sudo mkinitcpio -P. \
                 Otherwise: add {p} to the options line of each entry in /boot/loader/entries/"
        )],
        Bootloader::Limine => vec![format!(
            "Add {p} to KERNEL_CMDLINE in /etc/default/limine (limine-mkinitcpio-hook), or to \
                 each entry's cmdline in limine.conf"
        )],
        Bootloader::Unknown => vec![format!(
            "Add {p} to your boot loader's kernel command line (the Arch wiki's \"Kernel \
             parameters\" page covers each one)"
        )],
    }
}

/// A PCI device's class (0x030000 for a VGA card), from its uevent.
fn class_of(files: &dyn Files, slot: &str) -> u32 {
    files
        .read(&format!("/sys/bus/pci/devices/{slot}/uevent"))
        .and_then(|u| {
            u.lines()
                .find_map(|l| l.strip_prefix("PCI_CLASS=").map(str::to_string))
        })
        .and_then(|c| u32::from_str_radix(c.trim(), 16).ok())
        .unwrap_or(0)
}

fn uevent_value(files: &dyn Files, slot: &str, key: &str) -> Option<String> {
    files
        .read(&format!("/sys/bus/pci/devices/{slot}/uevent"))
        .and_then(|u| {
            u.lines()
                .find_map(|l| l.strip_prefix(&format!("{key}=")).map(str::to_string))
        })
}

/// "0000:03:00" of "0000:03:00.0": a card's functions share it.
fn device_part(slot: &str) -> &str {
    slot.rsplit_once('.').map(|(a, _)| a).unwrap_or(slot)
}

/// The card's other PCI functions (its HDMI audio, a USB-C controller …).
pub fn functions(files: &dyn Files, slot: &str) -> Vec<String> {
    let dev = device_part(slot);
    files
        .list("/sys/bus/pci/devices")
        .into_iter()
        .filter(|s| s != slot && device_part(s) == dev)
        .collect()
}

/// Its IOMMU group's number and every device in it.
pub fn group_of(files: &dyn Files, slot: &str) -> Option<(String, Vec<String>)> {
    for g in files.list("/sys/kernel/iommu_groups") {
        let devs = files.list(&format!("/sys/kernel/iommu_groups/{g}/devices"));
        if devs.iter().any(|x| x == slot) {
            return Some((g, devs));
        }
    }
    None
}

/// What a device is, for a message ("a USB controller at 0000:00:14.0").
fn what(files: &dyn Files, pci_ids: &str, slot: &str) -> String {
    let class = class_of(files, slot) >> 8;
    let kind = match class {
        0x0300 | 0x0302 | 0x0380 => "a graphics card",
        0x0403 => "an audio device",
        0x0c03 => "a USB controller",
        0x0106 => "a SATA controller",
        0x0108 => "an NVMe drive",
        0x0200 => "a network card",
        0x0280 => "a Wi-Fi card",
        0x0604 => "a PCI bridge",
        _ => "a device",
    };
    let name = uevent_value(files, slot, "PCI_ID")
        .and_then(|id| {
            let (v, d) = id.split_once(':')?;
            super::pci_name(
                pci_ids,
                u16::from_str_radix(v, 16).ok()?,
                u16::from_str_radix(d, 16).ok()?,
            )
        })
        .map(|n| format!(" ({n})"))
        .unwrap_or_default();
    format!("{kind}{name} at {slot}")
}

/// Modules that drive a card's other functions, for modprobe's soft dependencies.
fn module_for(driver: &str) -> Option<&'static str> {
    match driver {
        "snd_hda_intel" => Some("snd_hda_intel"),
        "xhci_hcd" => Some("xhci_pci"),
        "nvidia-gpu" => Some("i2c_nvidia_gpu"),
        "ucsi_ccg" => Some("ucsi_ccg"),
        _ => None,
    }
}

/// AMD cards with the reset bug: a VM restarting can't reset them without vendor-reset.
fn needs_vendor_reset(g: &Gpu) -> bool {
    matches!(vendor(g), AMD)
        && [
            "Ellesmere",
            "Baffin",
            "Lexa",
            "Polaris",
            "Vega 10",
            "Vega 20",
            "Navi 10",
            "Navi 12",
            "Navi 14",
        ]
        .iter()
        .any(|c| chip(g).starts_with(c))
}

/// One card's state for virtual machines.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Vfio {
    /// Every check passed: it can be reserved.
    pub ready: bool,
    pub checks: Vec<Check>,
    /// Its IOMMU group and what's in it.
    pub group: Option<String>,
    pub group_devices: Vec<String>,
    /// Its other functions (reserved with it).
    pub functions: Vec<String>,
    /// Reserved (the files say so): from the next start.
    pub reserved: bool,
    /// vfio-pci drives it now.
    pub bound: bool,
    /// A note about the AMD reset bug, for the cards that have it.
    pub reset: Option<String>,
}

/// The checks before reserving `g` for VMs, and its reservation now. `hooks`: the
/// initramfs's HOOKS in force.
pub fn vfio_state(
    files: &dyn Files,
    d: &Detection,
    g: &Gpu,
    choice: &SystemChoice,
    boot: &str,
    io: &Iommu,
    hooks: &[String],
) -> Vfio {
    let pci_ids = files.read(super::PCI_IDS).unwrap_or_default();
    let funcs = functions(files, &g.slot);
    let group = group_of(files, &g.slot);
    let mut checks = vec![];
    checks.push(check(
        "iommu",
        io.on,
        if io.on {
            "The IOMMU is on".into()
        } else {
            "The IOMMU is off".into()
        },
        &if io.on {
            "The IOMMU keeps a virtual machine's card to the VM's own memory. It's on, so the \
             kernel can hand a card to a VM."
                .to_string()
        } else {
            format!(
                "The IOMMU keeps a virtual machine's card to the VM's own memory; without it a \
                 card can't be handed to a VM. {}",
                io.steps.join(" ")
            )
        },
    ));
    let (group_ok, group_text) = match (&group, io.on) {
        (_, false) => (
            false,
            "Its IOMMU group can't be checked while the IOMMU is off".to_string(),
        ),
        (None, true) => (false, "It isn't in any IOMMU group".to_string()),
        (Some((n, devs)), true) => {
            let others: Vec<String> = devs
                .iter()
                .filter(|x| *x != &g.slot && !funcs.contains(x))
                .filter(|x| class_of(files, x) >> 8 != 0x0604)
                .map(|x| what(files, &pci_ids, x))
                .collect();
            if others.is_empty() {
                (
                    true,
                    format!("Its IOMMU group ({n}) holds only the card's own parts"),
                )
            } else {
                (
                    false,
                    format!("Its IOMMU group ({n}) also holds {}", others.join(", ")),
                )
            }
        }
    };
    checks.push(check(
        "group",
        group_ok,
        group_text,
        "A virtual machine gets a whole IOMMU group at once, so the card's group must hold only \
         the card itself (its graphics, audio and USB-C parts; PCI bridges are fine). Otherwise \
         try the card in another slot: the slots wired to the processor usually have groups \
         of their own.",
    ));
    let conns = g.connected_connectors.join(", ");
    checks.push(check(
        "monitor",
        g.connected_connectors.is_empty(),
        if conns.is_empty() {
            "No monitor is connected to it".into()
        } else {
            format!("A monitor is connected to it ({conns})")
        },
        "A reserved card shows nothing until a VM starts. Move its monitor to the card that \
         stays with the desktop first.",
    ));
    let next = desktop(d, &g.seat, choice, boot);
    let chosen = choice.desktop.as_ref().is_some_and(|c| c.is(g))
        || choice.trial_in_force(boot).is_some_and(|t| t.card.is(g))
        || next.slot.as_deref() == Some(g.slot.as_str());
    checks.push(check(
        "desktop",
        !chosen,
        if chosen {
            "The desktop is set to use it".into()
        } else {
            "The desktop doesn't use it".into()
        },
        "The desktop needs its own card. Choose another card for the desktop first.",
    ));
    let other = d
        .gpus
        .iter()
        .any(|o| o.slot != g.slot && desktop_ready(o, &o.seat) && !choice.reserved(o));
    checks.push(check(
        "other",
        other,
        if other {
            "Another card with a monitor stays with the desktop".into()
        } else {
            "No other card with a monitor would be left for the desktop".into()
        },
        "bromigOS never reserves the only card that can show the desktop: the computer would \
         start to a black screen.",
    ));
    checks.push(check(
        "boot",
        !g.boot_vga,
        if g.boot_vga {
            "The computer's firmware starts on this card".into()
        } else {
            "The firmware starts on another card".into()
        },
        "The card the firmware shows its start-up screen on isn't reserved: taking it from the \
         screen while the computer starts would freeze it. Choose the other card as the \
         primary display in the firmware settings, or swap the cards' slots.",
    ));
    let base = hooks.iter().any(|h| h == "base");
    let modconf = hooks.iter().any(|h| h == "modconf");
    checks.push(check(
        "initramfs",
        base && modconf,
        match (base, modconf) {
            (true, true) => {
                "The initramfs can reserve it early (its base and modconf hooks)".into()
            }
            (false, _) => "The initramfs has no base hook (its shell)".into(),
            (true, false) => "The initramfs has no modconf hook".into(),
        },
        "The reservation runs in the initramfs, before any graphics driver: it needs mkinitcpio's \
         base hook (a shell for its script) and modconf hook (modprobe's settings). Add them to \
         HOOKS in /etc/mkinitcpio.conf.",
    ));
    let reset = needs_vendor_reset(g).then(|| {
        format!(
            "This card has AMD's reset bug: after a VM shuts down it may not start again until \
             the computer restarts. vendor-reset fixes that (the AUR's vendor-reset-dkms-git, \
             loaded before the VM starts). It's {} now.",
            if files.exists("/sys/module/vendor_reset") {
                "loaded"
            } else {
                "not loaded"
            }
        )
    });
    let reserved = choice.reserved(g);
    let bound = g.driver.as_deref().is_some_and(is_vfio);
    Vfio {
        ready: checks.iter().all(|c| c.ok),
        checks,
        group: group.as_ref().map(|(n, _)| n.clone()),
        group_devices: group.map(|(_, d)| d).unwrap_or_default(),
        functions: funcs,
        reserved,
        bound,
        reset,
    }
}

/// The reservation for `g`: it and its functions, and their modules now.
pub fn reservation(files: &dyn Files, g: &Gpu) -> Reserved {
    let funcs = functions(files, &g.slot);
    let mut modules: Vec<String> = funcs
        .iter()
        .filter_map(|f| uevent_value(files, f, "DRIVER"))
        .filter_map(|drv| module_for(&drv).map(str::to_string))
        .collect();
    modules.sort();
    modules.dedup();
    Reserved {
        card: CardRef::of(g),
        functions: funcs,
        modules,
    }
}

/// The three VFIO files for these reservations (none when nothing's reserved): path,
/// content, mode.
pub fn vfio_files(list: &[Reserved]) -> Vec<(String, String, u32)> {
    if list.is_empty() {
        return vec![];
    }
    let all: Vec<&str> = list.iter().map(|r| r.card.slot.as_str()).collect();
    let mut script = format!(
        "#!/bin/sh\n\
         # bromigos hw vfio: cards reserved for virtual machines (vfio-pci), by PCI address,\n\
         # before their own drivers load. Written by `bromigos hw vfio reserve`; `bromigos hw\n\
         # vfio release` removes it (docs/hardware.md). A card is left to its own driver when\n\
         # the IOMMU is off, when another card now sits at its address, when the firmware\n\
         # started on it, or when no other display device would be left.\n\
         RESERVED=\"{}\"\n\
         reserve() {{\n\
         \x20   gpu=\"/sys/bus/pci/devices/$1\"\n\
         \x20   [ -d \"$gpu\" ] || return 0\n\
         \x20   [ \"$(cat \"$gpu/vendor\"):$(cat \"$gpu/device\")\" = \"$2\" ] || return 0\n\
         \x20   [ \"$(cat \"$gpu/boot_vga\" 2>/dev/null)\" = 1 ] && return 0\n\
         \x20   other=0\n\
         \x20   for c in /sys/bus/pci/devices/*/class; do\n\
         \x20       dev=\"${{c%/class}}\"\n\
         \x20       case \"$(cat \"$c\")\" in\n\
         \x20           0x03*) case \" $RESERVED \" in *\" ${{dev##*/}} \"*) ;; *) other=1 ;; esac ;;\n\
         \x20       esac\n\
         \x20   done\n\
         \x20   [ \"$other\" = 1 ] || return 0\n\
         \x20   shift 2\n\
         \x20   for dev in \"$gpu\" \"$@\"; do\n\
         \x20       dev=\"/sys/bus/pci/devices/${{dev##*/}}\"\n\
         \x20       [ -e \"$dev/driver_override\" ] && echo vfio-pci > \"$dev/driver_override\"\n\
         \x20   done\n\
         \x20   return 0\n\
         }}\n\
         if [ -n \"$(ls -A /sys/class/iommu 2>/dev/null)\" ]; then\n",
        all.join(" ")
    );
    for r in list {
        let (v, dv) = r.card.id.split_once(':').unwrap_or(("", ""));
        script.push_str(&format!(
            "    reserve {} 0x{v}:0x{dv}{}   # {}\n",
            r.card.slot,
            r.functions
                .iter()
                .map(|f| format!(" {f}"))
                .collect::<String>(),
            r.card.name.replace('\n', " ")
        ));
    }
    script.push_str("fi\nmodprobe -i vfio-pci\nexit 0\n");
    let mut modules = vec!["drm".to_string(), "nvidia".to_string()];
    for r in list {
        for m in &r.modules {
            if !modules.contains(m) {
                modules.push(m.clone());
            }
        }
    }
    let mut modprobe = format!(
        "# bromigos hw vfio: vfio-pci loads before any graphics driver, and first sets\n\
         # driver_override on the reserved cards ({VFIO_SCRIPT}). Written by `bromigos hw\n\
         # vfio reserve`; `bromigos hw vfio release` removes it.\n\
         install vfio-pci /bin/sh {VFIO_SCRIPT}\n"
    );
    for m in modules {
        modprobe.push_str(&format!("softdep {m} pre: vfio-pci\n"));
    }
    let initramfs = format!(
        "# bromigos hw vfio: the reservation in the initramfs, before the graphics drivers.\n\
         # Written by `bromigos hw vfio reserve`; `bromigos hw vfio release` removes it.\n\
         MODULES+=(vfio_pci vfio vfio_iommu_type1)\n\
         FILES+=({VFIO_SCRIPT})\n"
    );
    vec![
        (VFIO_SCRIPT.to_string(), script, 0o755),
        (VFIO_MODPROBE.to_string(), modprobe, 0o644),
        (VFIO_INITRAMFS.to_string(), initramfs, 0o644),
    ]
}

// ----------------------------------------------------------------------------- report

/// One card on the Graphics page.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Card {
    #[serde(flatten)]
    pub gpu: Gpu,
    pub title: String,
    pub integrated: bool,
    /// It can draw the desktop (a working driver, a monitor connected).
    pub desktop_ready: bool,
    pub game_ready: bool,
    /// The desktop renders on it from the next login.
    pub desktop_next: bool,
    /// This session renders on it.
    pub desktop_now: bool,
    /// Games and heavy apps run on it.
    pub games: bool,
    pub vfio: Vfio,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DesktopReport {
    /// The chosen card (None: Automatic).
    pub choice: Option<CardRef>,
    /// A trial, and whether it's in force (made during this boot).
    pub trial: Option<CardRef>,
    pub trial_in_force: bool,
    /// The card from the next login.
    pub next: Desktop,
    /// What Automatic picks now.
    pub automatic: Option<String>,
    /// This session's card (from its AQ_DRM_DEVICES).
    pub running: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GamesReport {
    pub choice: Option<CardRef>,
    #[serde(flatten)]
    pub now: Games,
    /// Steam starts on the games card (the user's copy of its launcher).
    pub steam: bool,
    pub steam_installed: bool,
}

/// Everything the Graphics page shows (`bromigos hw graphics --json`).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Report {
    pub cards: Vec<Card>,
    pub laptop: bool,
    pub hybrid: Option<Hybrid>,
    pub desktop: DesktopReport,
    pub games: GamesReport,
    pub iommu: Iommu,
    pub reserved: Vec<Reserved>,
    pub system_file: String,
    pub user_file: String,
}

/// The page's report. `aq`: this session's AQ_DRM_DEVICES; `hooks`: the initramfs's HOOKS.
#[allow(clippy::too_many_arguments)]
pub fn report(
    files: &dyn Files,
    paths: &Paths,
    d: &Detection,
    choice: &SystemChoice,
    user: &UserChoice,
    boot: &str,
    aq: Option<&str>,
    io: Iommu,
    hooks: &[String],
) -> Report {
    let next = desktop(d, "seat0", choice, boot);
    let running = running_desktop(d, aq);
    let auto = automatic_desktop(d, "seat0");
    // games compare with the card this session draws on, else the next login's
    let desk = running.or_else(|| {
        next.slot
            .as_ref()
            .and_then(|s| d.gpus.iter().find(|g| &g.slot == s))
            .or(auto)
    });
    let g = games(files, d, user, desk);
    let next_slot = next.slot.clone().or_else(|| auto.map(|a| a.slot.clone()));
    let cards = d
        .gpus
        .iter()
        .map(|x| Card {
            title: x.title(),
            integrated: integrated(x, d),
            desktop_ready: desktop_ready(x, &x.seat),
            game_ready: game_ready(x),
            desktop_next: next_slot.as_deref() == Some(x.slot.as_str()),
            desktop_now: running.is_some_and(|r| r.slot == x.slot),
            games: g.slot.as_deref() == Some(x.slot.as_str()),
            vfio: vfio_state(files, d, x, choice, boot, &io, hooks),
            gpu: x.clone(),
        })
        .collect();
    let trial = choice.trial.as_ref().map(|t| t.card.clone());
    Report {
        cards,
        laptop: d.machine.laptop,
        hybrid: d.hybrid.clone(),
        desktop: DesktopReport {
            choice: choice.desktop.clone(),
            trial_in_force: choice.trial_in_force(boot).is_some(),
            trial,
            next,
            automatic: auto.map(|a| a.slot.clone()),
            running: running.map(|r| r.slot.clone()),
        },
        games: GamesReport {
            choice: user.games.clone(),
            now: g,
            steam: steam_on(paths),
            steam_installed: files.exists(STEAM_DESKTOP),
        },
        iommu: io,
        reserved: choice.vfio.clone(),
        system_file: SYSTEM_FILE.into(),
        user_file: user_file(paths).display().to_string(),
    }
}

#[cfg(test)]
mod tests;
