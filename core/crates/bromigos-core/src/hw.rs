//! `bromigos hw`: what this machine is (its GPUs, a laptop or a desktop, a VM) and what
//! bromigOS sets up for it (docs/hardware.md).
//!
//! - [`detect`] reads the kernel's view of the machine through [`Files`] (sysfs, procfs,
//!   pacman's and mkinitcpio's files; `BROMIGOS_FS_ROOT` moves `/` for tests and a faked
//!   machine), never a command, so a fixture tree is a whole machine;
//! - [`wanted`] turns that into what the machine should have (pure: the tables below);
//! - [`plan`] checks it against what's installed, enabled and written (pacman, systemctl,
//!   the files), through the installer's [`Runner`], so a dry run prints and tests record;
//! - [`apply`] runs the plan: packages, system files, the initramfs, services, then the
//!   user's `~/.local/state/bromigos/hw/hyprland.lua` (the GPU environment bromigOS's
//!   default Hyprland config reads); a driver only the AUR has (NVIDIA's legacy branches)
//!   is built through the AUR helper only after a yes ([`aur_question`]; docs/aur.md).
//!
//! Which stack drives a GPU comes from its makers' own lists (`data/gpu-ids.tsv`, made by
//! `tools/hw/gpu-tables.py` from NVIDIA's supported-chips appendix and Mesa's PCI ID
//! tables); its name from pci.ids (hwdata), as lspci shows it.
//!
//! A machine whose NVIDIA driver is already installed keeps it: the plan never swaps or
//! removes a kernel module package, and it adds nothing to an initramfs that already loads
//! the driver early.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;
use std::sync::OnceLock;

use serde::Serialize;

use crate::install::Runner;
use crate::paths::Paths;
use crate::snapshot::Files;

/// The device table (see the module docs).
const GPU_IDS: &str = include_str!("../data/gpu-ids.tsv");

/// Where pci.ids lives (package hwdata).
pub const PCI_IDS: &str = "/usr/share/hwdata/pci.ids";

/// Every package any plan may install: the ISO's offline repository carries them all
/// (iso/build-in-container.sh; a test keeps the two in step).
pub const ALL_PACKAGES: &[&str] = &[
    "nvidia-open",
    "nvidia-open-lts",
    "nvidia-open-dkms",
    "nvidia-utils",
    "lib32-nvidia-utils",
    "libva-nvidia-driver",
    "nvidia-prime",
    "mesa",
    "lib32-mesa",
    "vulkan-radeon",
    "lib32-vulkan-radeon",
    "vulkan-intel",
    "lib32-vulkan-intel",
    "vulkan-nouveau",
    "intel-media-driver",
    "libva-intel-driver",
    "linux-firmware-nvidia",
    "linux-firmware-amdgpu",
    "linux-firmware-radeon",
    "linux-firmware-intel",
    "brightnessctl",
    "power-profiles-daemon",
];

// ---------------------------------------------------------------------------- the tables

/// What drives a GPU.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum Stack {
    /// NVIDIA, Turing and newer: the open kernel modules (nvidia-open), NVIDIA's userspace.
    NvidiaOpen,
    /// NVIDIA Maxwell, Pascal, Volta: the 580.xx branch, only in the AUR now; nouveau here.
    #[serde(rename = "nvidia-580xx")]
    Nvidia580xx,
    /// NVIDIA Kepler: the 470.xx branch (AUR, unsupported upstream); nouveau here.
    #[serde(rename = "nvidia-470xx")]
    Nvidia470xx,
    /// NVIDIA Fermi and older: nouveau only.
    NvidiaOld,
    /// AMD GCN and newer: amdgpu, Mesa's radeonsi and RADV.
    Amdgpu,
    /// AMD/ATI TeraScale and older: radeon, Mesa's r600/r300 (no Vulkan).
    Radeon,
    /// Intel Gen8 (Broadwell) and newer: Mesa's iris and ANV, intel-media-driver.
    Intel,
    /// Intel Gen4 to Gen7.5: Mesa's crocus, libva-intel-driver.
    IntelCrocus,
    /// Intel Gen3: Mesa's i915 (no VA-API, no Vulkan).
    IntelI915,
    /// A virtual machine's display (virtio, QXL, bochs, VMware, VirtualBox, Hyper-V, Cirrus).
    Virtual,
    /// Anything else (a server's BMC, a Matrox): Mesa's software renderer.
    Other,
}

impl Stack {
    pub fn describe(self) -> &'static str {
        match self {
            Stack::NvidiaOpen => "NVIDIA's open kernel modules (Turing or newer)",
            Stack::Nvidia580xx => {
                "NVIDIA's 580.xx legacy branch (Maxwell, Pascal, Volta): only in the AUR; nouveau meanwhile"
            }
            Stack::Nvidia470xx => {
                "NVIDIA's 470.xx legacy branch (Kepler): AUR only, unsupported upstream; nouveau"
            }
            Stack::NvidiaOld => "too old for any packaged NVIDIA driver: nouveau",
            Stack::Amdgpu => "amdgpu with Mesa (radeonsi, RADV)",
            Stack::Radeon => "radeon with Mesa (no Vulkan)",
            Stack::Intel => "Intel Gen8 or newer with Mesa (iris, ANV) and intel-media-driver",
            Stack::IntelCrocus => "Intel Gen4-7.5 with Mesa (crocus) and libva-intel-driver",
            Stack::IntelI915 => "Intel Gen3 with Mesa (i915): no video decoding, no Vulkan",
            Stack::Virtual => "a virtual GPU: Mesa (virgl with 3D, else its software renderer)",
            Stack::Other => "Mesa's software renderer",
        }
    }
    pub fn nvidia(self) -> bool {
        matches!(
            self,
            Stack::NvidiaOpen | Stack::Nvidia580xx | Stack::Nvidia470xx | Stack::NvidiaOld
        )
    }
}

fn table() -> &'static BTreeMap<(u16, u16), Stack> {
    static T: OnceLock<BTreeMap<(u16, u16), Stack>> = OnceLock::new();
    T.get_or_init(|| parse_table(GPU_IDS))
}

/// `data/gpu-ids.tsv`: "vendor device kind" per line, hex.
pub fn parse_table(text: &str) -> BTreeMap<(u16, u16), Stack> {
    let mut out = BTreeMap::new();
    for l in text.lines() {
        let l = l.trim();
        if l.is_empty() || l.starts_with('#') {
            continue;
        }
        let mut w = l.split_whitespace();
        let (Some(v), Some(d), Some(k)) = (w.next(), w.next(), w.next()) else {
            continue;
        };
        let (Ok(v), Ok(d)) = (u16::from_str_radix(v, 16), u16::from_str_radix(d, 16)) else {
            continue;
        };
        let s = match k {
            "nvidia-open" => Stack::NvidiaOpen,
            "nvidia-580xx" => Stack::Nvidia580xx,
            "nvidia-470xx" => Stack::Nvidia470xx,
            "nvidia-old" => Stack::NvidiaOld,
            "intel-crocus" => Stack::IntelCrocus,
            "intel-i915" => Stack::IntelI915,
            _ => continue,
        };
        out.insert((v, d), s);
    }
    out
}

pub const NVIDIA: u16 = 0x10de;
pub const AMD: u16 = 0x1002;
pub const INTEL: u16 = 0x8086;

/// A virtual machine's display adapter, by PCI vendor (and device, for Red Hat's).
fn virtual_vendor(vendor: u16, device: u16) -> Option<&'static str> {
    match (vendor, device) {
        (0x1af4, _) => Some("virtio"),
        (0x1b36, 0x0100) => Some("QXL"),
        (0x1b36, _) => Some("Red Hat (QEMU)"),
        (0x1234, _) => Some("bochs/std-vga"),
        (0x15ad, _) => Some("VMware SVGA"),
        (0x80ee, _) => Some("VirtualBox"),
        (0x1414, _) => Some("Hyper-V"),
        (0x1013, _) => Some("Cirrus"),
        _ => None,
    }
}

/// The stack for a device: the table, else by vendor (the kernel driver bound to it tells
/// AMD's two generations apart).
pub fn stack_for(vendor: u16, device: u16, driver: Option<&str>) -> Stack {
    if let Some(s) = table().get(&(vendor, device)) {
        return *s;
    }
    if virtual_vendor(vendor, device).is_some() {
        return Stack::Virtual;
    }
    match vendor {
        // newer than the table (it lists every current one): NVIDIA's current driver
        NVIDIA if device >= 0x1e00 => Stack::NvidiaOpen,
        NVIDIA => Stack::NvidiaOld,
        AMD | 0x1022 => match driver {
            Some("radeon") => Stack::Radeon,
            _ => Stack::Amdgpu,
        },
        INTEL => Stack::Intel,
        _ => Stack::Other,
    }
}

/// The chip family from pci.ids' name ("GB205 [GeForce RTX 5070]" → Blackwell), for
/// NVIDIA: what the report says and what decides the runtime power setting on hybrids.
pub fn nvidia_family(name: &str) -> Option<&'static str> {
    let chip = name.split_whitespace().next()?;
    let p =
        |s: &str| chip.starts_with(s) && chip[s.len()..].starts_with(|c: char| c.is_ascii_digit());
    Some(if p("GB") {
        "Blackwell"
    } else if p("GH") {
        "Hopper"
    } else if p("AD") {
        "Ada Lovelace"
    } else if p("GA") {
        "Ampere"
    } else if p("TU") {
        "Turing"
    } else if p("GV") {
        "Volta"
    } else if p("GP") {
        "Pascal"
    } else if p("GM") {
        "Maxwell"
    } else if p("GK") {
        "Kepler"
    } else if p("GF") {
        "Fermi"
    } else {
        return None;
    })
}

/// A device's name from pci.ids (`vendor`, then tab-indented `device` lines under it).
pub fn pci_name(pci_ids: &str, vendor: u16, device: u16) -> Option<String> {
    let v = format!("{vendor:04x}");
    let d = format!("\t{device:04x}");
    let mut in_vendor = false;
    for l in pci_ids.lines() {
        if l.starts_with('#') || l.is_empty() {
            continue;
        }
        if !l.starts_with('\t') {
            if in_vendor {
                return None;
            }
            in_vendor = l.starts_with(&v) && l[v.len()..].starts_with(' ');
            continue;
        }
        if in_vendor && l.starts_with(&d) && l[d.len()..].starts_with(' ') {
            return Some(l[d.len()..].trim().to_string());
        }
    }
    None
}

// ------------------------------------------------------------------------- detection

/// One display adapter.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Gpu {
    /// The PCI address, "0000:0a:00.0".
    pub slot: String,
    /// "10de:2f04".
    pub id: String,
    pub vendor: String,
    /// pci.ids' name ("GB205 [GeForce RTX 5070]"); empty when unknown.
    pub name: String,
    pub stack: Stack,
    /// NVIDIA's chip family (from the name), when known.
    pub family: Option<String>,
    /// The kernel driver bound to it now (nvidia, nouveau, amdgpu, i915, xe, virtio-pci …).
    pub driver: Option<String>,
    /// The firmware booted on it.
    pub boot_vga: bool,
    /// Its DRM card ("card1") and connectors ("DP-1", "eDP-1").
    pub card: Option<String>,
    pub connectors: Vec<String>,
    /// It drives a built-in panel (an eDP, LVDS or DSI connector): a laptop's iGPU.
    pub panel: bool,
}

impl Gpu {
    fn vendor_id(&self) -> u16 {
        u16::from_str_radix(self.id.split(':').next().unwrap_or("0"), 16).unwrap_or(0)
    }
    /// What `bromigos hw` prints for it.
    pub fn title(&self) -> String {
        if self.name.is_empty() {
            format!("{} {}", self.vendor, self.id)
        } else {
            format!("{} {}", self.vendor, self.name)
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Battery {
    pub name: String,
    pub capacity: Option<u8>,
    pub status: String,
}

/// What kind of machine.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Machine {
    /// The DMI chassis type (SMBIOS: 3 desktop, 9 laptop, 10 notebook, …), when there is one.
    pub chassis_type: Option<u32>,
    /// laptop, desktop, server, tablet, other (from the chassis type, and a battery).
    pub kind: String,
    pub laptop: bool,
    pub vendor: String,
    pub product: String,
    /// The hypervisor, when this is a virtual machine (qemu, vmware, virtualbox, hyper-v, xen, vm).
    pub virt: Option<String>,
    pub batteries: Vec<Battery>,
    pub lid: bool,
    /// /sys/class/backlight's devices (the screen's), and a keyboard backlight's LEDs.
    pub backlight: Vec<String>,
    pub kbd_backlight: Vec<String>,
    /// Touchpads by name (/proc/bus/input/devices).
    pub touchpads: Vec<String>,
}

/// NVIDIA's driver as it runs now.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct NvidiaState {
    /// nvidia.ko is loaded.
    pub loaded: bool,
    /// The open kernel modules (true), the proprietary ones (false); None when not loaded.
    pub open: Option<bool>,
    pub version: Option<String>,
    /// nvidia_drm's modeset and fbdev parameters (Y/N), when loaded.
    pub modeset: Option<bool>,
    pub fbdev: Option<bool>,
}

/// Everything detection found.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Detection {
    pub machine: Machine,
    pub gpus: Vec<Gpu>,
    /// The kernels installed (their pkgbase: linux, linux-lts, linux-zen …).
    pub kernels: Vec<String>,
    /// pacman.conf has [multilib].
    pub multilib: bool,
    pub nvidia: NvidiaState,
    /// mkinitcpio's MODULES as the files set them, without bromigOS's own drop-in.
    pub initramfs_modules: Vec<String>,
    /// Where those come from, for the report ("/etc/mkinitcpio.conf").
    pub initramfs_modules_from: Vec<String>,
    /// Hibernation is set up (a resume= on the kernel line, or the resume hook): early
    /// loading NVIDIA's modules would break it, so it isn't done.
    pub hibernation: bool,
    /// Several GPUs on a laptop: the one rendering the desktop (the panel's) and the other.
    pub hybrid: Option<Hybrid>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Hybrid {
    /// The integrated GPU's slot (it drives the panel; Hyprland renders on it).
    pub integrated: String,
    /// The discrete GPU's slot (offload: prime-run, DRI_PRIME).
    pub discrete: String,
}

/// PCI display controllers: class 0x03xxxx.
fn is_display(class: &str) -> bool {
    u32::from_str_radix(class.trim().trim_start_matches("0x"), 16)
        .map(|c| c >> 16 == 0x03)
        .unwrap_or(false)
}

/// A sysfs uevent file as key=value.
fn uevent(text: &str) -> BTreeMap<String, String> {
    text.lines()
        .filter_map(|l| l.split_once('='))
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

fn read_trim(files: &dyn Files, p: &str) -> Option<String> {
    files
        .read(p)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

/// SMBIOS chassis types that are carried: portable, laptop, notebook, hand held,
/// sub notebook, tablet, convertible, detachable.
pub const PORTABLE: &[u32] = &[8, 9, 10, 11, 14, 30, 31, 32];
const SERVER: &[u32] = &[17, 23, 25, 28, 29];

pub fn chassis_kind(t: Option<u32>) -> &'static str {
    match t {
        Some(30 | 32) => "tablet",
        Some(t) if PORTABLE.contains(&t) => "laptop",
        Some(3..=7 | 13 | 15 | 16 | 24 | 35 | 36) => "desktop",
        Some(t) if SERVER.contains(&t) => "server",
        _ => "other",
    }
}

/// The hypervisor from DMI (and the CPU's hypervisor flag).
pub fn virt(sys_vendor: &str, product: &str, cpu_hypervisor: bool) -> Option<String> {
    let v = sys_vendor.to_ascii_lowercase();
    let p = product.to_ascii_lowercase();
    let name = if v.contains("qemu") || p.contains("qemu") {
        "qemu"
    } else if v.contains("vmware") {
        "vmware"
    } else if v.contains("innotek") || p.contains("virtualbox") {
        "virtualbox"
    } else if v.contains("microsoft") && p.contains("virtual machine") {
        "hyper-v"
    } else if v.contains("xen") {
        "xen"
    } else if p.contains("kvm") || v.contains("red hat") {
        "kvm"
    } else if cpu_hypervisor {
        "vm"
    } else {
        return None;
    };
    Some(name.to_string())
}

/// A bitmap from /proc/bus/input/devices ("B: KEY=…"): hex words, most significant first,
/// each as wide as a C long (64 bits here).
fn has_bit(words: &str, bit: usize) -> bool {
    let ws: Vec<&str> = words.split_whitespace().collect();
    let i = bit / 64;
    if i >= ws.len() {
        return false;
    }
    u64::from_str_radix(ws[ws.len() - 1 - i], 16)
        .map(|w| w >> (bit % 64) & 1 == 1)
        .unwrap_or(false)
}

const BTN_TOOL_PEN: usize = 0x140;
const BTN_TOOL_FINGER: usize = 0x145;
const INPUT_PROP_DIRECT: usize = 1;
const ABS_X: usize = 0;

/// Touchpads in /proc/bus/input/devices, as udev's input_id finds them: absolute X, a
/// finger tool, no pen, not a direct-touch screen.
pub fn touchpads(devices: &str) -> Vec<String> {
    let mut out = vec![];
    for block in devices.split("\n\n") {
        let mut name = String::new();
        let (mut key, mut abs, mut prop) = (String::new(), String::new(), String::new());
        for l in block.lines() {
            if let Some(n) = l.strip_prefix("N: Name=") {
                name = n.trim_matches('"').trim().to_string();
            } else if let Some(k) = l.strip_prefix("B: KEY=") {
                key = k.to_string();
            } else if let Some(a) = l.strip_prefix("B: ABS=") {
                abs = a.to_string();
            } else if let Some(p) = l.strip_prefix("B: PROP=") {
                prop = p.to_string();
            }
        }
        if has_bit(&key, BTN_TOOL_FINGER)
            && !has_bit(&key, BTN_TOOL_PEN)
            && has_bit(&abs, ABS_X)
            && !has_bit(&prop, INPUT_PROP_DIRECT)
            && !out.contains(&name)
        {
            out.push(name);
        }
    }
    out
}

/// mkinitcpio's MODULES in force over `files` (path, text), in reading order: the last
/// plain assignment, plus what `+=` added after it. Single- or multi-line arrays.
pub fn modules_in_force(files: &[(String, String)]) -> (Vec<String>, Vec<String>) {
    let mut out: Vec<String> = vec![];
    let mut from: Vec<String> = vec![];
    for (path, text) in files {
        let mut it = text.lines();
        while let Some(l) = it.next() {
            let l = l.trim();
            let (add, rest) = if let Some(r) = l.strip_prefix("MODULES+=(") {
                (true, r)
            } else if let Some(r) = l.strip_prefix("MODULES=(") {
                (false, r)
            } else {
                continue;
            };
            let mut body = rest.to_string();
            while !body.contains(')') {
                match it.next() {
                    Some(n) => {
                        body.push(' ');
                        body.push_str(n.trim());
                    }
                    None => break,
                }
            }
            let body = body.split(')').next().unwrap_or("");
            let items: Vec<String> = body
                .split_whitespace()
                .map(|w| w.trim_matches(|c| c == '"' || c == '\'').to_string())
                .filter(|w| !w.is_empty() && !w.starts_with('#'))
                .collect();
            if !add {
                out.clear();
                from.retain(|f| f != path);
            }
            if !items.is_empty() && !from.contains(path) {
                from.push(path.clone());
            }
            out.extend(items);
        }
    }
    (out, from)
}

/// bromigOS's early-KMS drop-in.
pub const NVIDIA_INITRAMFS: &str = "/etc/mkinitcpio.conf.d/bromigos-nvidia.conf";
/// The stable names of a hybrid laptop's GPUs, and NVIDIA's runtime power rules.
pub const GPU_RULES: &str = "/etc/udev/rules.d/61-bromigos-gpu.rules";
pub const NVIDIA_PM_RULES: &str = "/etc/udev/rules.d/80-bromigos-nvidia-pm.rules";
pub const NVIDIA_PM_CONF: &str = "/etc/modprobe.d/bromigos-nvidia-pm.conf";
pub const NVIDIA_KMS_CONF: &str = "/etc/modprobe.d/bromigos-nvidia-kms.conf";
pub const IGPU_LINK: &str = "/dev/dri/bromigos-igpu";
pub const DGPU_LINK: &str = "/dev/dri/bromigos-dgpu";

/// The files that set MODULES, in mkinitcpio's reading order, but bromigOS's drop-in.
fn initramfs_files(files: &dyn Files) -> Vec<(String, String)> {
    let mut paths = vec!["/etc/mkinitcpio.conf".to_string()];
    paths.extend(
        files
            .list("/etc/mkinitcpio.conf.d")
            .into_iter()
            .filter(|n| n.ends_with(".conf"))
            .map(|n| format!("/etc/mkinitcpio.conf.d/{n}"))
            .filter(|p| p != NVIDIA_INITRAMFS),
    );
    paths
        .into_iter()
        .filter_map(|p| files.read(&p).map(|t| (p, t)))
        .collect()
}

/// Reads the machine (see the module docs). Never runs a command.
pub fn detect(files: &dyn Files) -> Detection {
    let pci_ids = files.read(PCI_IDS).unwrap_or_default();
    // the DRM cards by PCI slot, with their connectors
    let mut cards: BTreeMap<String, (String, Vec<String>)> = BTreeMap::new();
    let drm = files.list("/sys/class/drm");
    for n in &drm {
        if !n.starts_with("card") || n.contains('-') {
            continue;
        }
        let Some(ue) = files.read(&format!("/sys/class/drm/{n}/device/uevent")) else {
            continue;
        };
        let Some(slot) = uevent(&ue).get("PCI_SLOT_NAME").cloned() else {
            continue;
        };
        let conns: Vec<String> = drm
            .iter()
            .filter_map(|c| c.strip_prefix(&format!("{n}-")).map(str::to_string))
            .filter(|c| !c.starts_with("Writeback"))
            .collect();
        cards.insert(slot, (n.clone(), conns));
    }
    let mut gpus = vec![];
    for dev in files.list("/sys/bus/pci/devices") {
        let base = format!("/sys/bus/pci/devices/{dev}");
        let Some(ue) = files.read(&format!("{base}/uevent")) else {
            continue;
        };
        let ue = uevent(&ue);
        let class = ue.get("PCI_CLASS").cloned().unwrap_or_default();
        if !is_display(&class) {
            continue;
        }
        let Some((v, d)) = ue.get("PCI_ID").and_then(|i| i.split_once(':')) else {
            continue;
        };
        let (Ok(vendor), Ok(device)) = (u16::from_str_radix(v, 16), u16::from_str_radix(d, 16))
        else {
            continue;
        };
        let driver = ue.get("DRIVER").cloned();
        let name = pci_name(&pci_ids, vendor, device).unwrap_or_default();
        let stack = stack_for(vendor, device, driver.as_deref());
        let slot = ue.get("PCI_SLOT_NAME").cloned().unwrap_or(dev.clone());
        let (card, connectors) = cards
            .get(&slot)
            .map(|(c, cs)| (Some(c.clone()), cs.clone()))
            .unwrap_or((None, vec![]));
        let panel = connectors
            .iter()
            .any(|c| c.starts_with("eDP") || c.starts_with("LVDS") || c.starts_with("DSI"));
        gpus.push(Gpu {
            id: format!("{vendor:04x}:{device:04x}"),
            vendor: match vendor {
                NVIDIA => "NVIDIA".to_string(),
                AMD | 0x1022 => "AMD".to_string(),
                INTEL => "Intel".to_string(),
                _ => virtual_vendor(vendor, device)
                    .map(str::to_string)
                    .unwrap_or_else(|| format!("{vendor:04x}")),
            },
            family: if vendor == NVIDIA {
                nvidia_family(&name).map(str::to_string)
            } else {
                None
            },
            name,
            stack,
            driver,
            boot_vga: read_trim(files, &format!("{base}/boot_vga")).as_deref() == Some("1"),
            card,
            connectors,
            panel,
            slot,
        });
    }
    gpus.sort_by(|a, b| a.slot.cmp(&b.slot));

    // the machine
    let dmi = |k: &str| read_trim(files, &format!("/sys/class/dmi/id/{k}")).unwrap_or_default();
    let chassis_type: Option<u32> = dmi("chassis_type").parse().ok();
    let mut batteries = vec![];
    for ps in files.list("/sys/class/power_supply") {
        let b = format!("/sys/class/power_supply/{ps}");
        if read_trim(files, &format!("{b}/type")).as_deref() != Some("Battery") {
            continue;
        }
        // a mouse's or a headset's battery is the device's, not the machine's
        if read_trim(files, &format!("{b}/scope")).as_deref() == Some("Device") {
            continue;
        }
        if read_trim(files, &format!("{b}/present")).as_deref() == Some("0") {
            continue;
        }
        batteries.push(Battery {
            capacity: read_trim(files, &format!("{b}/capacity")).and_then(|c| c.parse().ok()),
            status: read_trim(files, &format!("{b}/status")).unwrap_or_default(),
            name: ps,
        });
    }
    let lid = !files.list("/proc/acpi/button/lid").is_empty();
    let backlight = files.list("/sys/class/backlight");
    let kbd_backlight: Vec<String> = files
        .list("/sys/class/leds")
        .into_iter()
        .filter(|l| l.ends_with("::kbd_backlight"))
        .collect();
    let mut kind = chassis_kind(chassis_type).to_string();
    let portable = chassis_type.is_some_and(|t| PORTABLE.contains(&t));
    let server = chassis_type.is_some_and(|t| SERVER.contains(&t));
    // a battery the machine runs on makes it a laptop whatever the firmware says (a VM's
    // faked one, a convertible that calls itself "other"), but never a server
    let laptop = portable || (!batteries.is_empty() && !server);
    if laptop && kind != "tablet" {
        kind = "laptop".into();
    }
    let cpu_hv = files.read("/proc/cpuinfo").is_some_and(|c| {
        c.lines()
            .any(|l| l.starts_with("flags") && l.split_whitespace().any(|w| w == "hypervisor"))
    });
    let machine = Machine {
        chassis_type,
        kind,
        laptop,
        virt: virt(&dmi("sys_vendor"), &dmi("product_name"), cpu_hv),
        vendor: dmi("sys_vendor"),
        product: dmi("product_name"),
        batteries,
        lid,
        backlight,
        kbd_backlight,
        touchpads: touchpads(&files.read("/proc/bus/input/devices").unwrap_or_default()),
    };

    // kernels, multilib, NVIDIA's state, the initramfs, hibernation
    let mut kernels: Vec<String> = files
        .list("/usr/lib/modules")
        .into_iter()
        .filter_map(|k| read_trim(files, &format!("/usr/lib/modules/{k}/pkgbase")))
        .collect();
    kernels.sort();
    kernels.dedup();
    let multilib = files
        .read("/etc/pacman.conf")
        .is_some_and(|c| c.lines().any(|l| l.trim() == "[multilib]"));
    let yn = |p: &str| read_trim(files, p).map(|v| v == "Y" || v == "1");
    let nv_loaded = files.exists("/sys/module/nvidia");
    let nvidia = NvidiaState {
        loaded: nv_loaded,
        open: if nv_loaded {
            files
                .read("/proc/driver/nvidia/version")
                .map(|v| v.contains("Open Kernel Module"))
        } else {
            None
        },
        version: if nv_loaded {
            read_trim(files, "/sys/module/nvidia/version")
        } else {
            None
        },
        modeset: yn("/sys/module/nvidia_drm/parameters/modeset"),
        fbdev: yn("/sys/module/nvidia_drm/parameters/fbdev"),
    };
    let (initramfs_modules, initramfs_modules_from) = modules_in_force(&initramfs_files(files));
    let hooks = crate::snapshot::hooks_in_force(&crate::snapshot::hooks_files(files));
    let cmdline = files.read("/proc/cmdline").unwrap_or_default();
    let hibernation = cmdline.split_whitespace().any(|w| w.starts_with("resume="))
        || hooks.iter().any(|h| h == "resume");
    let hybrid = hybrid(&machine, &gpus);
    Detection {
        machine,
        gpus,
        kernels,
        multilib,
        nvidia,
        initramfs_modules,
        initramfs_modules_from,
        hibernation,
        hybrid,
    }
}

/// A laptop with two real GPUs: the one driving the panel (else Intel's, else the one
/// the firmware booted on) renders the desktop; the other is for offload.
pub fn hybrid(m: &Machine, gpus: &[Gpu]) -> Option<Hybrid> {
    let real: Vec<&Gpu> = gpus
        .iter()
        .filter(|g| !matches!(g.stack, Stack::Virtual | Stack::Other))
        .collect();
    if !m.laptop || real.len() < 2 {
        return None;
    }
    let integrated = real
        .iter()
        .find(|g| g.panel)
        .or_else(|| real.iter().find(|g| g.vendor_id() == INTEL))
        .or_else(|| real.iter().find(|g| g.boot_vga))
        .or_else(|| real.iter().find(|g| !g.stack.nvidia()))?;
    let discrete = real.iter().find(|g| g.slot != integrated.slot)?;
    Some(Hybrid {
        integrated: integrated.slot.clone(),
        discrete: discrete.slot.clone(),
    })
}

// ---------------------------------------------------------------------------- the plan

/// A system file the setup writes (root-owned).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SysFile {
    pub path: String,
    pub content: String,
    pub why: String,
}

/// An environment variable for Hyprland, set only while every `when` path exists.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct EnvVar {
    pub name: String,
    pub value: String,
    pub when: Vec<String>,
    pub why: String,
}

/// What this machine should have (pure: from the detection alone).
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Want {
    /// Packages, in order (pacman installs only those missing).
    pub packages: Vec<String>,
    /// NVIDIA's kernel module packages among them: left out when one is installed already.
    pub module_packages: Vec<String>,
    /// System services to enable.
    pub services: Vec<String>,
    pub files: Vec<SysFile>,
    /// A file among them changes what the initramfs holds (mkinitcpio -P after).
    pub initramfs_files: Vec<String>,
    pub env: Vec<EnvVar>,
    pub notes: Vec<String>,
    /// A driver only the AUR has (NVIDIA's 580.xx or 470.xx branch), and the kernel headers
    /// its DKMS module builds against: offered through the AUR helper, never installed
    /// without a yes (`bromigos hw setup` asks; the installer never builds it).
    pub aur: Vec<String>,
}

fn push(v: &mut Vec<String>, items: &[&str]) {
    for i in items {
        if !v.iter().any(|x| x == i) {
            v.push(i.to_string());
        }
    }
}

/// The NVIDIA kernel module packages for these kernels: prebuilt for Arch's two stock
/// kernels, DKMS (with each kernel's headers) as soon as there's any other.
pub fn nvidia_module_packages(kernels: &[String]) -> Vec<String> {
    let stock = |k: &str| k == "linux" || k == "linux-lts";
    if kernels.is_empty() {
        return vec!["nvidia-open".into()];
    }
    if kernels.iter().all(|k| stock(k)) {
        kernels
            .iter()
            .map(|k| {
                if k == "linux" {
                    "nvidia-open".to_string()
                } else {
                    "nvidia-open-lts".to_string()
                }
            })
            .collect()
    } else {
        let mut v = vec!["nvidia-open-dkms".to_string()];
        v.extend(kernels.iter().map(|k| format!("{k}-headers")));
        v
    }
}

const EARLY_KMS: &[&str] = &["nvidia", "nvidia_modeset", "nvidia_uvm", "nvidia_drm"];

/// What the machine should have.
pub fn wanted(d: &Detection) -> Want {
    let mut w = Want::default();
    let m = &d.machine;
    let lib32 = |w: &mut Want, p: &[&str]| {
        if d.multilib {
            push(&mut w.packages, p);
        }
    };
    let nvidia_gpus: Vec<&Gpu> = d.gpus.iter().filter(|g| g.stack.nvidia()).collect();
    // NVIDIA's driver runs (or will once its packages are in): the open modules' GPUs,
    // or an older one whose legacy driver the user installed (from the AUR) and loaded
    let open = nvidia_gpus.iter().any(|g| g.stack == Stack::NvidiaOpen);
    let proprietary = open || (!nvidia_gpus.is_empty() && d.nvidia.loaded);
    for g in &d.gpus {
        match g.stack {
            Stack::NvidiaOpen => {
                let mods = nvidia_module_packages(&d.kernels);
                for p in &mods {
                    push(&mut w.packages, &[p]);
                    push(&mut w.module_packages, &[p]);
                }
                push(&mut w.packages, &["nvidia-utils", "libva-nvidia-driver"]);
                lib32(&mut w, &["lib32-nvidia-utils"]);
            }
            Stack::Nvidia580xx | Stack::Nvidia470xx | Stack::NvidiaOld => {
                if d.nvidia.loaded {
                    w.notes.push(format!(
                        "{}: NVIDIA's driver {} is loaded (installed by you); bromigOS keeps it",
                        g.title(),
                        d.nvidia.version.as_deref().unwrap_or("")
                    ));
                } else {
                    push(
                        &mut w.packages,
                        &["mesa", "vulkan-nouveau", "linux-firmware-nvidia"],
                    );
                    let branch = match g.stack {
                        Stack::Nvidia580xx => Some("580xx"),
                        Stack::Nvidia470xx => Some("470xx"),
                        _ => None,
                    };
                    w.notes.push(match branch {
                        Some(b) => {
                            let aur = [format!("nvidia-{b}-dkms"), format!("nvidia-{b}-utils")];
                            for p in aur.iter().chain(
                                d.multilib
                                    .then(|| format!("lib32-nvidia-{b}-utils"))
                                    .iter(),
                            ) {
                                push(&mut w.aur, &[p]);
                            }
                            format!(
                                "{}: {} — it runs on nouveau (Mesa) for now. NVIDIA's driver for it is in the \
                                 AUR only ({}): `bromigos hw setup` offers to build it with paru, and asks \
                                 first (the AUR's recipes are user-submitted); then reboot and run \
                                 `bromigos hw setup` again",
                                g.title(),
                                g.stack.describe(),
                                aur.join(", ")
                            )
                        }
                        None => format!("{}: {}", g.title(), g.stack.describe()),
                    });
                }
            }
            Stack::Amdgpu => {
                push(
                    &mut w.packages,
                    &["mesa", "vulkan-radeon", "linux-firmware-amdgpu"],
                );
                lib32(&mut w, &["lib32-mesa", "lib32-vulkan-radeon"]);
            }
            Stack::Radeon => {
                push(&mut w.packages, &["mesa", "linux-firmware-radeon"]);
                lib32(&mut w, &["lib32-mesa"]);
            }
            Stack::Intel => {
                push(
                    &mut w.packages,
                    &[
                        "mesa",
                        "vulkan-intel",
                        "intel-media-driver",
                        "linux-firmware-intel",
                    ],
                );
                lib32(&mut w, &["lib32-mesa", "lib32-vulkan-intel"]);
            }
            Stack::IntelCrocus => {
                push(
                    &mut w.packages,
                    &["mesa", "vulkan-intel", "libva-intel-driver"],
                );
                lib32(&mut w, &["lib32-mesa"]);
            }
            Stack::IntelI915 => push(&mut w.packages, &["mesa"]),
            Stack::Virtual | Stack::Other => push(&mut w.packages, &["mesa"]),
        }
    }
    if !w.aur.is_empty() {
        // the DKMS module builds against each installed kernel's headers (repositories')
        let headers: Vec<String> = if d.kernels.is_empty() {
            vec!["linux-headers".into()]
        } else {
            d.kernels.iter().map(|k| format!("{k}-headers")).collect()
        };
        let mut aur = headers;
        aur.append(&mut w.aur);
        w.aur = aur;
    }
    if d.gpus.is_empty() {
        w.notes.push(
            "no display adapter found (a headless machine, or /sys isn't the machine's)".into(),
        );
    }

    // NVIDIA: the modules in the initramfs (early KMS), so the driver has the screen before
    // the splash and the login screen start; not where hibernation is set up (early loading
    // can't reach NVreg_TemporaryFilePath: the Arch wiki), nor twice
    if proprietary {
        let have = &d.initramfs_modules;
        let early = have.iter().any(|m| m == "nvidia_drm" || m == "nvidia-drm");
        if d.hibernation {
            w.notes.push(
                "hibernation is set up here, so NVIDIA's modules aren't loaded early (that would \
                 break resuming); the driver loads after the initramfs, as Arch's default"
                    .into(),
            );
        } else if !early {
            w.files.push(SysFile {
                path: NVIDIA_INITRAMFS.into(),
                content: format!(
                    "# bromigos hw setup: NVIDIA's modules in the initramfs (early KMS), so the driver has\n\
                     # the screen before the splash and the login screen start (docs/hardware.md). Remove\n\
                     # this file if you set up hibernation: early loading breaks resuming (Arch wiki,\n\
                     # NVIDIA/Tips and tricks), then run mkinitcpio -P.\n\
                     MODULES+=({})\n",
                    EARLY_KMS.join(" ")
                ),
                why: "NVIDIA's modules loaded early (early KMS)".into(),
            });
            w.initramfs_files.push(NVIDIA_INITRAMFS.into());
        }
        let bogus: Vec<&String> = have
            .iter()
            .filter(|m| {
                matches!(
                    m.as_str(),
                    "nvidia-open" | "nvidia-open-dkms" | "nvidia-dkms"
                )
            })
            .collect();
        for b in bogus {
            w.notes.push(format!(
                "mkinitcpio's MODULES ({}) names {b}, which is a package, not a kernel module (the \
                 module is nvidia): mkinitcpio warns about it, and nvidia_drm brings nvidia in \
                 anyway. Replace it with nvidia when convenient, then sudo mkinitcpio -P",
                d.initramfs_modules_from.join(", ")
            ));
        }
        // nvidia-utils turns modeset and fbdev on (Arch's defaults since 560); a legacy driver
        // that doesn't gets them here
        if d.nvidia.loaded && (d.nvidia.modeset == Some(false) || d.nvidia.fbdev == Some(false)) {
            w.files.push(SysFile {
                path: NVIDIA_KMS_CONF.into(),
                content: "# bromigos hw setup: NVIDIA's DRM kernel mode setting and its framebuffer, which\n\
                          # Wayland needs (Arch's nvidia-utils sets them; this driver didn't).\n\
                          options nvidia_drm modeset=1 fbdev=1\n"
                    .into(),
                why: "nvidia_drm's modeset and fbdev on".into(),
            });
            if early || !d.hibernation {
                w.initramfs_files.push(NVIDIA_KMS_CONF.into());
            }
        }
    }

    // a hybrid laptop: Hyprland renders on the integrated GPU (battery), the discrete one
    // is there for what asks for it (prime-run, DRI_PRIME=1) and for an output wired to it
    if let Some(h) = &d.hybrid {
        let ig = d.gpus.iter().find(|g| g.slot == h.integrated);
        let dg = d.gpus.iter().find(|g| g.slot == h.discrete);
        if let (Some(ig), Some(dg)) = (ig, dg) {
            w.files.push(SysFile {
                path: GPU_RULES.into(),
                content: format!(
                    "# bromigos hw setup: stable names for this laptop's GPUs (Hyprland's AQ_DRM_DEVICES\n\
                     # can't take /dev/dri/by-path names: they hold colons; the cardN numbers change).\n\
                     # {} renders the desktop, {} is for offload (docs/hardware.md).\n\
                     KERNEL==\"card*\", SUBSYSTEM==\"drm\", KERNELS==\"{}\", SUBSYSTEMS==\"pci\", SYMLINK+=\"dri/bromigos-igpu\"\n\
                     KERNEL==\"card*\", SUBSYSTEM==\"drm\", KERNELS==\"{}\", SUBSYSTEMS==\"pci\", SYMLINK+=\"dri/bromigos-dgpu\"\n",
                    ig.title(),
                    dg.title(),
                    ig.slot,
                    dg.slot
                ),
                why: "stable names for the two GPUs".into(),
            });
            w.env.push(EnvVar {
                name: "AQ_DRM_DEVICES".into(),
                value: format!("{IGPU_LINK}:{DGPU_LINK}"),
                when: vec![IGPU_LINK.into()],
                why: format!(
                    "render on {} (it drives the panel), {} for outputs wired to it",
                    ig.title(),
                    dg.title()
                ),
            });
            if dg.stack == Stack::NvidiaOpen || (dg.stack.nvidia() && d.nvidia.loaded) {
                push(&mut w.packages, &["nvidia-prime"]);
                w.files.push(SysFile {
                    path: NVIDIA_PM_RULES.into(),
                    content: "# bromigos hw setup: the NVIDIA GPU powers down when nothing uses it (runtime D3; the\n\
                              # rules from NVIDIA's README, \"PCI-Express Runtime D3 Power Management\").\n\
                              ACTION==\"bind\", SUBSYSTEM==\"pci\", ATTR{vendor}==\"0x10de\", ATTR{class}==\"0x030000\", TEST==\"power/control\", ATTR{power/control}=\"auto\"\n\
                              ACTION==\"bind\", SUBSYSTEM==\"pci\", ATTR{vendor}==\"0x10de\", ATTR{class}==\"0x030200\", TEST==\"power/control\", ATTR{power/control}=\"auto\"\n\
                              ACTION==\"unbind\", SUBSYSTEM==\"pci\", ATTR{vendor}==\"0x10de\", ATTR{class}==\"0x030000\", TEST==\"power/control\", ATTR{power/control}=\"on\"\n\
                              ACTION==\"unbind\", SUBSYSTEM==\"pci\", ATTR{vendor}==\"0x10de\", ATTR{class}==\"0x030200\", TEST==\"power/control\", ATTR{power/control}=\"on\"\n"
                        .into(),
                    why: "the NVIDIA GPU sleeps when idle".into(),
                });
                // Ampere and newer notebooks get fine-grained power control by default; Turing
                // needs asking (NVIDIA's README: NVreg_DynamicPowerManagement=0x02)
                if dg.family.as_deref() == Some("Turing") {
                    w.files.push(SysFile {
                        path: NVIDIA_PM_CONF.into(),
                        content: "# bromigos hw setup: fine-grained runtime power management for a Turing GPU in a\n\
                                  # laptop (Ampere and newer have it by default; NVIDIA's README).\n\
                                  options nvidia NVreg_DynamicPowerManagement=0x02\n"
                            .into(),
                        why: "runtime power management on a Turing laptop GPU".into(),
                    });
                    if !d.hibernation {
                        w.initramfs_files.push(NVIDIA_PM_CONF.into());
                    }
                }
                w.notes.push(format!(
                    "hybrid: the desktop renders on {}; run a program on {} with `prime-run <program>`",
                    ig.title(),
                    dg.title()
                ));
            } else {
                w.notes.push(format!(
                    "hybrid: the desktop renders on {}; run a program on {} with `DRI_PRIME=1 <program>`",
                    ig.title(),
                    dg.title()
                ));
            }
        }
    } else if d
        .gpus
        .iter()
        .filter(|g| !matches!(g.stack, Stack::Virtual | Stack::Other))
        .count()
        > 1
    {
        w.notes.push(
            "several GPUs on a desktop: Hyprland renders on the one the firmware booted on (the \
             monitors' cable decides); set AQ_DRM_DEVICES in your hyprland.lua to change it"
                .into(),
        );
    }

    // laptops: the brightness keys' tool, the battery in the bar (waybar finds it), power
    // profiles; a touchpad is libinput's in Hyprland already (tap, gestures: the defaults)
    if m.laptop {
        push(&mut w.packages, &["brightnessctl", "power-profiles-daemon"]);
        push(&mut w.services, &["power-profiles-daemon.service"]);
    }
    w
}

/// What `apply` will do, checked against the machine.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Plan {
    pub want: Want,
    /// Packages to install (wanted, missing).
    pub install: Vec<String>,
    /// Services to enable (wanted, not enabled).
    pub enable: Vec<String>,
    /// Files to write (missing or different).
    pub write: Vec<String>,
    /// mkinitcpio -P afterwards.
    pub initramfs: bool,
    /// The user's GPU environment for Hyprland (`~/.local/state/bromigos/hw/hyprland.lua`).
    pub hyprland: String,
    pub hyprland_path: PathBuf,
    /// It differs from what's there.
    pub hyprland_changed: bool,
    /// What's right already.
    pub keep: Vec<String>,
    /// Why some of it isn't done, and what to do by hand.
    pub notes: Vec<String>,
    /// The driver only the AUR has, still missing (with its kernel headers), when the AUR
    /// is on here and a helper can build it: [`apply`] builds it only with
    /// [`ApplyOpts::aur_driver`] (a yes). Not part of [`Plan::done`].
    pub aur: Vec<String>,
    /// The helper that would build it.
    pub aur_helper: Option<crate::aur::Helper>,
}

impl Plan {
    /// Nothing to change.
    pub fn done(&self) -> bool {
        self.install.is_empty()
            && self.enable.is_empty()
            && self.write.is_empty()
            && !self.initramfs
            && !self.hyprland_changed
    }
}

/// The generated file Hyprland's default config reads.
pub fn hyprland_path(paths: &Paths) -> PathBuf {
    paths.state_home.join("bromigos/hw/hyprland.lua")
}

fn lua_str(s: &str) -> String {
    format!("{s:?}")
}

/// The user's GPU environment for Hyprland, as Lua (a table; the default config reads it).
pub fn hyprland_lua(d: &Detection, env: &[EnvVar]) -> String {
    let gpus = d
        .gpus
        .iter()
        .map(|g| format!("{} ({})", g.title(), g.stack.describe()))
        .collect::<Vec<_>>()
        .join("; ");
    let mut s = String::from(
        "-- This machine's GPU environment for Hyprland, written by `bromigos hw setup`\n\
         -- (docs/hardware.md). bromigOS's default hyprland.lua reads it; don't edit it, run\n\
         -- `bromigos hw setup` again after changing GPUs. A variable is set only while every\n\
         -- path in its `when` exists, so a GPU swapped since can't break the session.\n\
         -- (NVIDIA alone needs none: libva maps nvidia-drm to its driver, Xwayland picks the\n\
         -- GLX vendor, Hyprland's cursor settings default to what NVIDIA needs.)\n",
    );
    s.push_str("return {\n");
    s.push_str(&format!("    gpus = {},\n", lua_str(&gpus)));
    s.push_str(&format!("    laptop = {},\n", d.machine.laptop));
    s.push_str("    env = {\n");
    for e in env {
        s.push_str(&format!(
            "        {{ {}, {}, when = {{ {} }} }},   -- {}\n",
            lua_str(&e.name),
            lua_str(&e.value),
            e.when
                .iter()
                .map(|w| lua_str(w))
                .collect::<Vec<_>>()
                .join(", "),
            e.why
        ));
    }
    s.push_str("    },\n}\n");
    s
}

/// `pacman -T` over the names: the ones not satisfied (not installed, nor provided).
fn missing(runner: &mut dyn Runner, pkgs: &[String]) -> Vec<String> {
    if pkgs.is_empty() {
        return vec![];
    }
    let mut a = vec!["pacman", "-T"];
    a.extend(pkgs.iter().map(String::as_str));
    let (code, out) = runner.query(&a);
    if code == 0 {
        return vec![];
    }
    let miss: BTreeSet<&str> = out
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .collect();
    pkgs.iter()
        .filter(|p| miss.contains(p.as_str()))
        .cloned()
        .collect()
}

/// Checks what's wanted against the machine (packages, services, files, the user's file).
pub fn plan(paths: &Paths, d: &Detection, runner: &mut dyn Runner, files: &dyn Files) -> Plan {
    let want = wanted(d);
    let mut notes = want.notes.clone();
    let mut keep = vec![];
    // never swap NVIDIA's kernel modules: any package providing them counts
    let mut pkgs = want.packages.clone();
    if !want.module_packages.is_empty() && runner.query(&["pacman", "-T", "NVIDIA-MODULE"]).0 == 0 {
        pkgs.retain(|p| !want.module_packages.contains(p));
        keep.push("NVIDIA's kernel modules (installed; never swapped)".into());
        if !d.nvidia.loaded && d.gpus.iter().any(|g| g.stack == Stack::NvidiaOpen) {
            notes.push(
                "NVIDIA's kernel modules are installed but not loaded: reboot (or check that \
                 they match the kernel: dkms status, pacman -Qs nvidia)"
                    .into(),
            );
        }
    }
    // a power manager of the user's own: power-profiles-daemon would fight it
    let mut services = want.services.clone();
    if pkgs.iter().any(|p| p == "power-profiles-daemon") {
        let (_, have) =
            runner.query(&["pacman", "-Qq", "tlp", "tuned", "auto-cpufreq", "tuned-ppd"]);
        let others: Vec<&str> = have
            .lines()
            .map(str::trim)
            .filter(|l| !l.is_empty())
            .collect();
        if !others.is_empty() {
            pkgs.retain(|p| p != "power-profiles-daemon");
            services.retain(|s| s != "power-profiles-daemon.service");
            notes.push(format!(
                "power profiles: {} manages power here, so power-profiles-daemon isn't added (the \
                 bar's profile switch shows only with it)",
                others.join(", ")
            ));
        }
    }
    let install = missing(runner, &pkgs);
    let installed: Vec<String> = pkgs
        .iter()
        .filter(|p| !install.contains(p))
        .cloned()
        .collect();
    if !installed.is_empty() {
        keep.push(format!("installed: {}", installed.join(", ")));
    }
    let enable: Vec<String> = services
        .iter()
        .filter(|s| runner.query(&["systemctl", "is-enabled", s]).1.trim() != "enabled")
        .cloned()
        .collect();
    for s in services.iter().filter(|s| !enable.contains(s)) {
        keep.push(format!("enabled: {s}"));
    }
    let mut write = vec![];
    for f in &want.files {
        if files.read(&f.path).as_deref() == Some(f.content.as_str()) {
            keep.push(format!("{} (as written)", f.path));
        } else {
            write.push(f.path.clone());
        }
    }
    if d.machine_has_early_nvidia() {
        keep.push(format!(
            "NVIDIA's modules load early (MODULES in {})",
            d.initramfs_modules_from.join(", ")
        ));
    }
    // a driver only the AUR has: offered through the helper when the AUR is on here
    let mut aur = vec![];
    let mut aur_helper = None;
    let aur_missing = missing(runner, &want.aur);
    if aur_missing.iter().any(|p| p.starts_with("nvidia-")) {
        let helper = crate::aur::found(runner).helper;
        let on = crate::aur::enabled(paths);
        match (on, helper) {
            (true, Some(h)) => {
                aur = aur_missing;
                aur_helper = Some(h);
            }
            (false, _) => notes.push(
                "the AUR is off here, so the driver isn't offered: bromigos aur on, then \
                 bromigos hw setup again (or install it yourself)"
                    .into(),
            ),
            (true, None) => notes.push(
                "no AUR helper to build the driver with: bromigos aur on installs bromigOS's \
                 paru, then bromigos hw setup again"
                    .into(),
            ),
        }
    } else if !want.aur.is_empty() {
        notes.push(
            "NVIDIA's driver is installed but not loaded: reboot, then bromigos hw setup again \
             (early KMS for it)"
                .into(),
        );
    }
    let initramfs = write.iter().any(|p| want.initramfs_files.contains(p));
    let hyprland = hyprland_lua(d, &want.env);
    let hyprland_path = hyprland_path(paths);
    let hyprland_changed =
        fs::read_to_string(&hyprland_path).ok().as_deref() != Some(hyprland.as_str());
    Plan {
        want,
        install,
        enable,
        write,
        initramfs,
        hyprland,
        hyprland_path,
        hyprland_changed,
        keep,
        notes,
        aur,
        aur_helper,
    }
}

impl Detection {
    fn machine_has_early_nvidia(&self) -> bool {
        self.gpus.iter().any(|g| g.stack.nvidia())
            && self
                .initramfs_modules
                .iter()
                .any(|m| m == "nvidia_drm" || m == "nvidia-drm")
    }
}

// ---------------------------------------------------------------------------- applying

/// A booted system, not a chroot (an install's): services can start now.
pub fn booted(files: &dyn Files, runner: &mut dyn Runner) -> bool {
    files.exists("/run/systemd/system") && runner.query(&["systemd-detect-virt", "--chroot"]).0 != 0
}

/// How `apply` runs.
#[derive(Debug, Clone, Copy, Default)]
pub struct ApplyOpts {
    /// pacman doesn't stop to ask (--noconfirm).
    pub yes: bool,
    /// Only the user's file (no sudo: packages, files, services are left).
    pub user_only: bool,
    /// Leave services alone (`bromigos install --no-services`).
    pub no_services: bool,
    /// Start the services now too (a booted system, not a chroot).
    pub now: bool,
    /// Build the plan's AUR driver with the helper (someone said yes: [`aur_question`]).
    /// With `yes`, the helper doesn't ask and skips its review of the recipes.
    pub aur_driver: bool,
}

/// What `apply` did.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Applied {
    pub ok: bool,
    /// Commands run (or, in a dry run, that would run).
    pub commands: Vec<String>,
    pub detail: String,
    /// A reboot makes it take effect (a driver, the initramfs, udev's names).
    pub reboot: bool,
}

/// Runs the plan. `exec(argv, interactive)` runs (or plans) one command; with `dry` the
/// staged files and the user's file aren't written either.
pub fn apply(
    paths: &Paths,
    plan: &Plan,
    opts: &ApplyOpts,
    dry: bool,
    exec: &mut dyn FnMut(Vec<String>, bool) -> Result<(), String>,
) -> Applied {
    let mut out = Applied {
        ok: true,
        ..Default::default()
    };
    let mut did = vec![];
    let fail = |out: &mut Applied, e: String| {
        out.ok = false;
        out.detail = e;
    };
    let line = |a: &[String]| crate::install::shell_line(a);
    if !opts.user_only {
        if !plan.install.is_empty() {
            let mut a: Vec<String> = ["sudo", "pacman", "-S", "--needed"]
                .map(String::from)
                .to_vec();
            if opts.yes {
                a.push("--noconfirm".into());
            }
            a.extend(plan.install.iter().cloned());
            out.commands.push(line(&a));
            if let Err(e) = exec(a, true) {
                fail(&mut out, e);
                return out;
            }
            did.push(format!("installed {}", plan.install.join(", ")));
            if plan
                .install
                .iter()
                .any(|p| p.starts_with("nvidia-open") || p == "nvidia-utils")
            {
                out.reboot = true;
            }
        }
        // the driver only the AUR has, after the repositories' packages (a yes asked for it)
        if opts.aur_driver
            && let Some(h) = plan.aur_helper.filter(|_| !plan.aur.is_empty())
        {
            let mut a: Vec<String> = vec![h.bin().into(), "-S".into(), "--needed".into()];
            if opts.yes {
                a.push("--noconfirm".into());
                if h == crate::aur::Helper::Paru {
                    a.push("--skipreview".into());
                }
            }
            a.extend(plan.aur.iter().cloned());
            out.commands.push(line(&a));
            if let Err(e) = exec(a, true) {
                fail(&mut out, e);
                return out;
            }
            did.push(format!(
                "built and installed {} from the AUR (reboot, then bromigos hw setup again)",
                plan.aur
                    .iter()
                    .filter(|p| !p.ends_with("-headers"))
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
            out.reboot = true;
        }
        let staged = paths.state_home.join("bromigos/hw/staged");
        for path in &plan.write {
            let Some(f) = plan.want.files.iter().find(|f| &f.path == path) else {
                continue;
            };
            let name = path.rsplit('/').next().unwrap_or("file");
            let tmp = staged.join(name);
            if !dry
                && let Err(e) =
                    fs::create_dir_all(&staged).and_then(|_| fs::write(&tmp, &f.content))
            {
                fail(&mut out, format!("{}: {e}", tmp.display()));
                return out;
            }
            let a: Vec<String> = vec![
                "sudo".into(),
                "install".into(),
                "-Dm644".into(),
                tmp.display().to_string(),
                path.clone(),
            ];
            out.commands.push(line(&a));
            if let Err(e) = exec(a, true) {
                fail(&mut out, e);
                return out;
            }
            if !dry {
                let _ = fs::remove_file(&tmp);
            }
            did.push(format!("wrote {path} ({})", f.why));
            out.reboot = true;
        }
        if plan.initramfs {
            let a: Vec<String> = ["sudo", "mkinitcpio", "-P"].map(String::from).to_vec();
            out.commands.push(line(&a));
            if let Err(e) = exec(a, true) {
                fail(&mut out, e);
                return out;
            }
            did.push("made the initramfs again".into());
        }
        if !plan.enable.is_empty() {
            if opts.no_services {
                did.push(format!(
                    "left {} alone (--no-services)",
                    plan.enable.join(", ")
                ));
            } else {
                let mut a: Vec<String> = ["sudo", "systemctl", "enable"].map(String::from).to_vec();
                if opts.now {
                    a.push("--now".into());
                }
                a.extend(plan.enable.iter().cloned());
                out.commands.push(line(&a));
                if let Err(e) = exec(a, true) {
                    fail(&mut out, e);
                    return out;
                }
                did.push(format!(
                    "enabled {}{}",
                    plan.enable.join(", "),
                    if opts.now {
                        ""
                    } else {
                        " (from the next boot)"
                    }
                ));
            }
        }
    }
    if plan.hyprland_changed {
        out.commands
            .push(format!("write {}", plan.hyprland_path.display()));
        if !dry {
            let p = &plan.hyprland_path;
            let r = fs::create_dir_all(p.parent().unwrap_or(p))
                .and_then(|_| fs::write(p.with_extension("tmp"), &plan.hyprland))
                .and_then(|_| fs::rename(p.with_extension("tmp"), p));
            if let Err(e) = r {
                fail(&mut out, format!("{}: {e}", p.display()));
                return out;
            }
        }
        did.push(format!(
            "Hyprland's GPU environment in {} ({}; from the next login)",
            plan.hyprland_path.display(),
            if plan.want.env.is_empty() {
                "none needed".to_string()
            } else {
                plan.want
                    .env
                    .iter()
                    .map(|e| e.name.clone())
                    .collect::<Vec<_>>()
                    .join(", ")
            }
        ));
    }
    out.detail = if did.is_empty() {
        "nothing to change".into()
    } else {
        did.join("; ")
    };
    out
}

/// The question before building the plan's AUR driver (None: there's none to build).
pub fn aur_question(plan: &Plan) -> Option<String> {
    let h = plan.aur_helper.filter(|_| !plan.aur.is_empty())?;
    let pkgs: Vec<&str> = plan
        .aur
        .iter()
        .map(String::as_str)
        .filter(|p| !p.ends_with("-headers"))
        .collect();
    Some(format!(
        "NVIDIA's driver for this GPU is in the AUR only ({}). The AUR's recipes are \
         user-submitted, not vetted by Arch or bromigOS; {} builds it here and shows you the \
         recipe to review first. Build and install it now? [y/N] ",
        pkgs.join(", "),
        h.bin()
    ))
}

/// Asks a person at a terminal (the words on stderr, the answer from stdin); no terminal is
/// a no.
pub fn ask(question: &str) -> bool {
    use std::io::{BufRead, IsTerminal, Write};
    if !std::io::stdin().is_terminal() {
        return false;
    }
    eprint!("{question}");
    let _ = std::io::stderr().flush();
    let mut line = String::new();
    if std::io::stdin().lock().read_line(&mut line).is_err() {
        return false;
    }
    matches!(line.trim().to_lowercase().as_str(), "y" | "yes")
}

/// The machine in a few words ("a laptop; Intel … + NVIDIA …"), for `bromigos hw`, setup's
/// page and install's step.
pub fn summary(d: &Detection) -> String {
    let m = &d.machine;
    let what = match (&m.virt, m.kind.as_str()) {
        (Some(v), "laptop") => format!("a laptop (a {v} virtual machine)"),
        (Some(v), _) => format!("a {v} virtual machine"),
        (None, "other") => match m.chassis_type {
            Some(t) => format!("a machine of chassis type {t}"),
            None => "a machine".to_string(),
        },
        (None, k) => format!("a {k}"),
    };
    let gpus = d
        .gpus
        .iter()
        .map(|g| g.title())
        .collect::<Vec<_>>()
        .join(" + ");
    format!(
        "{what}; {}",
        if gpus.is_empty() {
            "no GPU found".to_string()
        } else {
            gpus
        }
    )
}

#[cfg(test)]
mod tests;
