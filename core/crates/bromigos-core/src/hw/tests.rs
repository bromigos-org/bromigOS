//! The detection tables and plans against whole machines made of files: real PCI IDs,
//! DMI chassis types, power supplies, backlights, input devices and initramfs configs, as
//! sysfs and procfs show them.

use super::*;
use std::collections::BTreeMap;

/// A machine's file system in memory.
#[derive(Default, Clone)]
pub(crate) struct Mem(pub(crate) BTreeMap<String, String>);

impl Mem {
    pub(crate) fn with(mut self, path: &str, text: &str) -> Self {
        self.0.insert(path.to_string(), text.to_string());
        self
    }
    pub(crate) fn dir(self, path: &str) -> Self {
        self.with(&format!("{path}/.dir"), "")
    }
}

impl Files for Mem {
    fn exists(&self, path: &str) -> bool {
        let pre = format!("{}/", path.trim_end_matches('/'));
        self.0.contains_key(path) || self.0.keys().any(|k| k.starts_with(&pre))
    }
    fn read(&self, path: &str) -> Option<String> {
        self.0.get(path).cloned()
    }
    fn list(&self, dir: &str) -> Vec<String> {
        let pre = format!("{}/", dir.trim_end_matches('/'));
        let mut v: Vec<String> = self
            .0
            .keys()
            .filter_map(|k| k.strip_prefix(&pre))
            .map(|r| r.split('/').next().unwrap_or("").to_string())
            .filter(|n| !n.is_empty() && n != ".dir")
            .collect();
        v.sort();
        v.dedup();
        v
    }
}

const PCI_IDS_SNIPPET: &str = "\
# a few of pci.ids' lines
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t1681  Rembrandt [Radeon 680M]
\t744c  Navi 31 [Radeon RX 7900 XT/7900 XTX/7900 GRE/7900M]
10de  NVIDIA Corporation
\t1b80  GP104 [GeForce GTX 1080]
\t1f91  TU117M [GeForce GTX 1650 Mobile / Max-Q]
\t2560  GA106M [GeForce RTX 3060 Mobile / Max-Q]
\t2f04  GB205 [GeForce RTX 5070]
\t\t10de 205a  a subsystem line, skipped
1af4  Red Hat, Inc.
\t1050  Virtio 1.0 GPU
8086  Intel Corporation
\t0416  4th Gen Core Processor Integrated Graphics Controller
\t3e9b  CoffeeLake-H GT2 [UHD Graphics 630]
\t5917  Kaby Lake-R GT2 [UHD Graphics 620]
";

/// A PCI display device, its DRM card and connectors.
pub(crate) fn gpu(
    m: Mem,
    slot: &str,
    id: &str,
    driver: Option<&str>,
    boot_vga: bool,
    card: Option<(&str, &[&str])>,
) -> Mem {
    let base = format!("/sys/bus/pci/devices/{slot}");
    let ue = format!(
        "{}PCI_CLASS=30000\nPCI_ID={}\nPCI_SUBSYS_ID=1028:097D\nPCI_SLOT_NAME={slot}\n",
        driver.map(|d| format!("DRIVER={d}\n")).unwrap_or_default(),
        id.to_uppercase()
    );
    let mut m = m.with(&format!("{base}/uevent"), &ue).with(
        &format!("{base}/boot_vga"),
        if boot_vga { "1\n" } else { "0\n" },
    );
    if let Some((c, conns)) = card {
        m = m
            .with(&format!("/sys/class/drm/{c}/device/uevent"), &ue)
            .with(&format!("/dev/dri/{c}"), "")
            .dir(&format!("/sys/class/drm/{c}"));
        for conn in conns {
            m = m.dir(&format!("/sys/class/drm/{c}-{conn}"));
        }
    }
    m
}

/// Something else on the PCI bus (a USB controller): never a GPU.
fn not_gpu(m: Mem) -> Mem {
    m.with(
        "/sys/bus/pci/devices/0000:00:14.0/uevent",
        "DRIVER=xhci_hcd\nPCI_CLASS=C0330\nPCI_ID=8086:A36D\nPCI_SLOT_NAME=0000:00:14.0\n",
    )
}

fn dmi(m: Mem, chassis: u32, vendor: &str, product: &str) -> Mem {
    m.with("/sys/class/dmi/id/chassis_type", &format!("{chassis}\n"))
        .with("/sys/class/dmi/id/sys_vendor", &format!("{vendor}\n"))
        .with("/sys/class/dmi/id/product_name", &format!("{product}\n"))
}

fn battery(m: Mem, name: &str) -> Mem {
    let b = format!("/sys/class/power_supply/{name}");
    m.with(&format!("{b}/type"), "Battery\n")
        .with(&format!("{b}/present"), "1\n")
        .with(&format!("{b}/capacity"), "82\n")
        .with(&format!("{b}/status"), "Discharging\n")
        .with("/sys/class/power_supply/AC/type", "Mains\n")
        .with("/sys/class/power_supply/AC/online", "0\n")
}

const TOUCHPAD: &str = "\
I: Bus=0018 Vendor=06cb Product=7e7e Version=0100
N: Name=\"SYNA2393:00 06CB:7E7E Touchpad\"
P: Phys=i2c-SYNA2393:00
H: Handlers=mouse0 event7
B: PROP=5
B: EV=1b
B: KEY=e520 10000 0 0 0 0
B: ABS=2e0800000000003
B: MSC=20

I: Bus=0018 Vendor=04f3 Product=2b7c Version=0100
N: Name=\"ELAN2514:00 04F3:2B7C\"
H: Handlers=mouse1 event8
B: PROP=2
B: EV=1b
B: KEY=400 0 0 0 0 0
B: ABS=3273800000000003

I: Bus=0003 Vendor=046d Product=c08b Version=0111
N: Name=\"Logitech G502 HERO Gaming Mouse\"
H: Handlers=mouse2 event9
B: PROP=0
B: EV=17
B: KEY=1f0000 0 0 0 0
B: REL=1943
";

fn kernels(m: Mem, ks: &[&str]) -> Mem {
    let mut m = m.dir("/usr/lib/modules/6.10.5-arch1-1"); // a leftover: no pkgbase
    for (i, k) in ks.iter().enumerate() {
        m = m.with(
            &format!("/usr/lib/modules/7.2.{i}-{k}/pkgbase"),
            &format!("{k}\n"),
        );
    }
    m
}

fn base(chassis: u32, vendor: &str, product: &str) -> Mem {
    let m = Mem::default().with(PCI_IDS, PCI_IDS_SNIPPET);
    let m = dmi(m, chassis, vendor, product);
    let m = kernels(m, &["linux"]);
    not_gpu(m)
        .with("/etc/pacman.conf", "[options]\nArchitecture = auto\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n")
        .with("/etc/mkinitcpio.conf", "MODULES=()\nHOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block filesystems fsck)\n")
        .with("/proc/cmdline", "BOOT_IMAGE=/vmlinuz-linux root=UUID=x rw quiet\n")
        .with("/proc/cpuinfo", "processor\t: 0\nflags\t\t: fpu vme de pse\n")
}

/// The operator's desktop as it is: an RTX 5070 on the open modules, loaded, with early
/// KMS already in /etc/mkinitcpio.conf (and the package's name among the modules).
fn operator_desktop() -> Mem {
    let m = base(3, "System manufacturer", "System Product Name");
    let m = gpu(
        m,
        "0000:0a:00.0",
        "10de:2f04",
        Some("nvidia"),
        true,
        Some(("card1", &["DP-1", "DP-2", "DP-3", "HDMI-A-1"])),
    );
    let m = kernels(m, &["linux"]);
    m.with("/etc/pacman.conf", "[options]\n[core]\n[extra]\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n")
        .with("/etc/mkinitcpio.conf", "MODULES=(btrfs nvidia-open nvidia_modeset nvidia_uvm nvidia_drm)\nHOOKS=(base udev autodetect keyboard keymap modconf block filesystems fsck)\n")
        .with("/sys/module/nvidia/version", "615.71.09\n")
        .with("/sys/module/nvidia_drm/parameters/modeset", "Y\n")
        .with("/sys/module/nvidia_drm/parameters/fbdev", "Y\n")
        .with("/proc/driver/nvidia/version", "NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  615.71.09  Release Build  (root@)\n")
        .with("/proc/cmdline", "BOOT_IMAGE=/vmlinuz-linux root=UUID=c rw rootflags=subvol=@ quiet nvidia_drm.modeset=1 nvidia_drm.fbdev=1\n")
        .with("/proc/bus/input/devices", "I: Bus=0019\nN: Name=\"Power Button\"\nB: PROP=0\nB: EV=3\nB: KEY=8000 10000000000000 0\n")
}

/// A Dell XPS-like laptop: Intel UHD 630 on the panel, a GTX 1650 Mobile (Turing) beside it,
/// before any driver: nouveau holds the NVIDIA GPU.
fn turing_laptop() -> Mem {
    let m = base(10, "Dell Inc.", "XPS 15 7590");
    let m = gpu(
        m,
        "0000:00:02.0",
        "8086:3e9b",
        Some("i915"),
        true,
        Some(("card0", &["eDP-1", "DP-1"])),
    );
    let m = gpu(
        m,
        "0000:01:00.0",
        "10de:1f91",
        Some("nouveau"),
        false,
        Some(("card1", &[])),
    );
    battery(m, "BAT0")
        .dir("/proc/acpi/button/lid/LID0")
        .dir("/sys/class/backlight/intel_backlight")
        .dir("/sys/class/leds/dell::kbd_backlight")
        .with("/proc/bus/input/devices", TOUCHPAD)
}

/// An ASUS ROG-like laptop: AMD Radeon 680M on the panel, an RTX 3060 Mobile (Ampere),
/// NVIDIA's driver installed and loaded.
fn ampere_laptop() -> Mem {
    let m = base(10, "ASUSTeK COMPUTER INC.", "ROG Zephyrus G14");
    let m = gpu(
        m,
        "0000:01:00.0",
        "10de:2560",
        Some("nvidia"),
        false,
        Some(("card0", &["HDMI-A-1"])),
    );
    let m = gpu(
        m,
        "0000:65:00.0",
        "1002:1681",
        Some("amdgpu"),
        true,
        Some(("card1", &["eDP-1"])),
    );
    battery(m, "BAT0")
        .dir("/proc/acpi/button/lid/LID")
        .dir("/sys/class/backlight/amdgpu_bl1")
        .with("/proc/bus/input/devices", TOUCHPAD)
        .with("/sys/module/nvidia/version", "615.71.09\n")
        .with("/sys/module/nvidia_drm/parameters/modeset", "Y\n")
        .with(
            "/proc/driver/nvidia/version",
            "NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  615.71.09\n",
        )
}

fn qemu_vm() -> Mem {
    let m = base(1, "QEMU", "Standard PC (Q35 + ICH9, 2009)");
    gpu(
        m,
        "0000:00:01.0",
        "1af4:1050",
        Some("virtio-pci"),
        true,
        Some(("card0", &["Virtual-1"])),
    )
    .with(
        "/proc/cpuinfo",
        "processor\t: 0\nflags\t\t: fpu vme hypervisor\n",
    )
}

/// Records the queries a plan makes and answers them from a table (prefix match).
struct Fake {
    answers: Vec<(String, (i32, String))>,
    asked: Vec<String>,
}

impl Fake {
    fn new(answers: &[(&str, i32, &str)]) -> Self {
        Fake {
            answers: answers
                .iter()
                .map(|(q, c, o)| (q.to_string(), (*c, o.to_string())))
                .collect(),
            asked: vec![],
        }
    }
}

impl Runner for Fake {
    fn run(&mut self, argv: &[String], _interactive: bool) -> std::io::Result<(i32, String)> {
        self.asked.push(format!("RUN {}", argv.join(" ")));
        Ok((0, String::new()))
    }
    fn query(&mut self, argv: &[&str]) -> (i32, String) {
        let q = argv.join(" ");
        self.asked.push(q.clone());
        self.answers
            .iter()
            .find(|(p, _)| q.starts_with(p.as_str()))
            .map(|(_, a)| a.clone())
            .unwrap_or((1, String::new()))
    }
}

fn test_paths() -> (tempfile::TempDir, Paths) {
    let t = tempfile::tempdir().unwrap();
    let p = Paths::from_lookup(|k| match k {
        "HOME" => Some(t.path().join("home")),
        "XDG_RUNTIME_DIR" => Some(t.path().join("run")),
        _ => None,
    });
    (t, p)
}

// ------------------------------------------------------------------------------ tables

#[test]
fn the_table_has_nvidias_and_mesas_lists() {
    let t = parse_table(GPU_IDS);
    assert_eq!(t.get(&(NVIDIA, 0x2f04)), Some(&Stack::NvidiaOpen)); // RTX 5070, Blackwell
    assert_eq!(t.get(&(NVIDIA, 0x2684)), Some(&Stack::NvidiaOpen)); // RTX 4090, Ada
    assert_eq!(t.get(&(NVIDIA, 0x2560)), Some(&Stack::NvidiaOpen)); // RTX 3060 Mobile, Ampere
    assert_eq!(t.get(&(NVIDIA, 0x1f91)), Some(&Stack::NvidiaOpen)); // GTX 1650 Mobile, Turing
    assert_eq!(t.get(&(NVIDIA, 0x2182)), Some(&Stack::NvidiaOpen)); // GTX 1660 Ti, Turing (TU116)
    assert_eq!(t.get(&(NVIDIA, 0x1d81)), Some(&Stack::Nvidia580xx)); // TITAN V, Volta
    assert_eq!(t.get(&(NVIDIA, 0x1b80)), Some(&Stack::Nvidia580xx)); // GTX 1080, Pascal
    assert_eq!(t.get(&(NVIDIA, 0x13c2)), Some(&Stack::Nvidia580xx)); // GTX 970, Maxwell
    assert_eq!(t.get(&(NVIDIA, 0x1180)), Some(&Stack::Nvidia470xx)); // GTX 680, Kepler
    assert_eq!(t.get(&(NVIDIA, 0x06c0)), Some(&Stack::NvidiaOld)); // GTX 480, Fermi
    assert_eq!(t.get(&(INTEL, 0x0416)), Some(&Stack::IntelCrocus)); // Haswell GT2
    assert_eq!(t.get(&(INTEL, 0x0166)), Some(&Stack::IntelCrocus)); // Ivy Bridge GT2
    assert_eq!(t.get(&(INTEL, 0x2a42)), Some(&Stack::IntelCrocus)); // GM45
    assert_eq!(t.get(&(INTEL, 0x27a2)), Some(&Stack::IntelI915)); // 945GM
    assert_eq!(t.get(&(INTEL, 0x5917)), None); // Kaby Lake: iris, by vendor
    assert!(t.len() > 1000, "{} entries", t.len());
}

#[test]
fn devices_not_in_the_table_go_by_vendor() {
    assert_eq!(stack_for(NVIDIA, 0x3100, None), Stack::NvidiaOpen); // newer than the table
    assert_eq!(stack_for(NVIDIA, 0x0001, None), Stack::NvidiaOld);
    assert_eq!(stack_for(INTEL, 0x5917, Some("i915")), Stack::Intel); // Kaby Lake
    assert_eq!(stack_for(INTEL, 0xa7a0, Some("xe")), Stack::Intel); // Raptor Lake
    assert_eq!(stack_for(INTEL, 0xe20b, Some("xe")), Stack::Intel); // Battlemage
    assert_eq!(stack_for(AMD, 0x744c, Some("amdgpu")), Stack::Amdgpu);
    assert_eq!(stack_for(AMD, 0x6779, Some("radeon")), Stack::Radeon); // a TeraScale card
    assert_eq!(stack_for(AMD, 0x6779, None), Stack::Amdgpu);
    assert_eq!(
        stack_for(0x1af4, 0x1050, Some("virtio-pci")),
        Stack::Virtual
    );
    assert_eq!(stack_for(0x1b36, 0x0100, None), Stack::Virtual); // QXL
    assert_eq!(stack_for(0x1234, 0x1111, None), Stack::Virtual); // bochs
    assert_eq!(stack_for(0x15ad, 0x0405, None), Stack::Virtual); // VMware
    assert_eq!(stack_for(0x80ee, 0xbeef, None), Stack::Virtual); // VirtualBox
    assert_eq!(stack_for(0x1414, 0x5353, None), Stack::Virtual); // Hyper-V
    assert_eq!(stack_for(0x1a03, 0x2000, Some("ast")), Stack::Other); // a server's BMC
}

#[test]
fn nvidias_families_come_from_the_chip_name() {
    assert_eq!(nvidia_family("GB205 [GeForce RTX 5070]"), Some("Blackwell"));
    assert_eq!(
        nvidia_family("AD102 [GeForce RTX 4090]"),
        Some("Ada Lovelace")
    );
    assert_eq!(
        nvidia_family("GA106M [GeForce RTX 3060 Mobile / Max-Q]"),
        Some("Ampere")
    );
    assert_eq!(
        nvidia_family("TU117M [GeForce GTX 1650 Mobile / Max-Q]"),
        Some("Turing")
    );
    assert_eq!(nvidia_family("GP104 [GeForce GTX 1080]"), Some("Pascal"));
    assert_eq!(nvidia_family("GK104 [GeForce GTX 680]"), Some("Kepler"));
    assert_eq!(nvidia_family("GT218 [ION]"), None);
    assert_eq!(nvidia_family("GAMING card"), None);
}

#[test]
fn pci_ids_names_devices_under_their_vendor_only() {
    assert_eq!(
        pci_name(PCI_IDS_SNIPPET, NVIDIA, 0x2f04).as_deref(),
        Some("GB205 [GeForce RTX 5070]")
    );
    assert_eq!(
        pci_name(PCI_IDS_SNIPPET, 0x1af4, 0x1050).as_deref(),
        Some("Virtio 1.0 GPU")
    );
    assert_eq!(pci_name(PCI_IDS_SNIPPET, NVIDIA, 0x1681), None); // that's AMD's
    assert_eq!(pci_name(PCI_IDS_SNIPPET, NVIDIA, 0x205a), None); // a subsystem line
    assert_eq!(pci_name("", NVIDIA, 0x2f04), None);
}

#[test]
fn chassis_types_and_hypervisors() {
    assert_eq!(chassis_kind(Some(3)), "desktop");
    assert_eq!(chassis_kind(Some(9)), "laptop");
    assert_eq!(chassis_kind(Some(10)), "laptop");
    assert_eq!(chassis_kind(Some(31)), "laptop"); // convertible
    assert_eq!(chassis_kind(Some(30)), "tablet");
    assert_eq!(chassis_kind(Some(23)), "server");
    assert_eq!(chassis_kind(Some(1)), "other");
    assert_eq!(chassis_kind(None), "other");
    assert_eq!(
        virt("QEMU", "Standard PC (Q35 + ICH9, 2009)", true).as_deref(),
        Some("qemu")
    );
    assert_eq!(
        virt("VMware, Inc.", "VMware Virtual Platform", true).as_deref(),
        Some("vmware")
    );
    assert_eq!(
        virt("innotek GmbH", "VirtualBox", true).as_deref(),
        Some("virtualbox")
    );
    assert_eq!(
        virt("Microsoft Corporation", "Virtual Machine", true).as_deref(),
        Some("hyper-v")
    );
    assert_eq!(
        virt("Microsoft Corporation", "Surface Laptop 5", false),
        None
    );
    assert_eq!(virt("Dell Inc.", "XPS 15 7590", false), None);
    assert_eq!(
        virt("Some Vendor", "Some Board", true).as_deref(),
        Some("vm")
    );
}

#[test]
fn touchpads_are_found_as_udev_finds_them() {
    assert_eq!(
        touchpads(TOUCHPAD),
        vec!["SYNA2393:00 06CB:7E7E Touchpad".to_string()]
    );
    assert!(touchpads("").is_empty());
}

#[test]
fn mkinitcpio_modules_add_up_across_files() {
    let f = |p: &str, t: &str| (p.to_string(), t.to_string());
    let (m, from) = modules_in_force(&[
        f(
            "/etc/mkinitcpio.conf",
            "# MODULES=(nope)\nMODULES=(btrfs \"i915\")\nHOOKS=(base)\n",
        ),
        f(
            "/etc/mkinitcpio.conf.d/a.conf",
            "MODULES+=(\n  nvidia\n  nvidia_drm\n)\n",
        ),
    ]);
    assert_eq!(m, vec!["btrfs", "i915", "nvidia", "nvidia_drm"]);
    assert_eq!(
        from,
        vec!["/etc/mkinitcpio.conf", "/etc/mkinitcpio.conf.d/a.conf"]
    );
    let (m, _) = modules_in_force(&[
        f("/etc/mkinitcpio.conf", "MODULES=(a)\n"),
        f("/etc/mkinitcpio.conf.d/b.conf", "MODULES=(b)\n"),
    ]);
    assert_eq!(m, vec!["b"]);
    let (m, from) = modules_in_force(&[f("/etc/mkinitcpio.conf", "MODULES=()\n")]);
    assert!(m.is_empty() && from.is_empty());
}

#[test]
fn nvidias_module_packages_follow_the_kernels() {
    let k = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
    assert_eq!(nvidia_module_packages(&k(&["linux"])), vec!["nvidia-open"]);
    assert_eq!(
        nvidia_module_packages(&k(&["linux", "linux-lts"])),
        vec!["nvidia-open", "nvidia-open-lts"]
    );
    assert_eq!(
        nvidia_module_packages(&k(&["linux-lts"])),
        vec!["nvidia-open-lts"]
    );
    assert_eq!(
        nvidia_module_packages(&k(&["linux", "linux-zen"])),
        vec!["nvidia-open-dkms", "linux-headers", "linux-zen-headers"]
    );
    assert_eq!(nvidia_module_packages(&[]), vec!["nvidia-open"]);
}

// --------------------------------------------------------------------------- machines

#[test]
fn the_operators_desktop() {
    let d = detect(&operator_desktop());
    assert_eq!(d.machine.kind, "desktop");
    assert!(!d.machine.laptop);
    assert_eq!(d.machine.virt, None);
    assert_eq!(d.gpus.len(), 1);
    let g = &d.gpus[0];
    assert_eq!(g.id, "10de:2f04");
    assert_eq!(g.name, "GB205 [GeForce RTX 5070]");
    assert_eq!(g.stack, Stack::NvidiaOpen);
    assert_eq!(g.family.as_deref(), Some("Blackwell"));
    assert_eq!(g.driver.as_deref(), Some("nvidia"));
    assert_eq!(g.card.as_deref(), Some("card1"));
    assert_eq!(g.connectors, vec!["DP-1", "DP-2", "DP-3", "HDMI-A-1"]);
    assert!(g.boot_vga && !g.panel);
    assert_eq!(d.kernels, vec!["linux"]);
    assert!(d.multilib);
    assert!(d.nvidia.loaded);
    assert_eq!(d.nvidia.open, Some(true));
    assert_eq!(d.nvidia.version.as_deref(), Some("615.71.09"));
    assert_eq!((d.nvidia.modeset, d.nvidia.fbdev), (Some(true), Some(true)));
    assert!(!d.hibernation);
    assert_eq!(d.hybrid, None);
    assert!(d.machine.touchpads.is_empty());

    let w = wanted(&d);
    assert_eq!(
        w.packages,
        vec![
            "nvidia-open",
            "nvidia-utils",
            "libva-nvidia-driver",
            "lib32-nvidia-utils"
        ]
    );
    assert!(w.services.is_empty());
    assert!(
        w.files.is_empty(),
        "early KMS is in mkinitcpio.conf already: {:?}",
        w.files
    );
    // the driver needs no variables; Proton games get NVAPI while the module is loaded
    assert_eq!(w.env.len(), 1, "{:?}", w.env);
    assert_eq!(
        (w.env[0].name.as_str(), w.env[0].value.as_str()),
        ("PROTON_ENABLE_NVAPI", "1")
    );
    assert_eq!(w.env[0].when, vec!["/sys/module/nvidia"]);
    assert!(
        w.notes
            .iter()
            .any(|n| n.contains("names nvidia-open, which is a package")),
        "{:?}",
        w.notes
    );

    // what `hw setup` would do there: the driver kept, only VA-API's piece added
    let (_t, paths) = test_paths();
    let mut r = Fake::new(&[
        ("pacman -T NVIDIA-MODULE", 0, ""),
        ("pacman -T", 127, "libva-nvidia-driver\n"),
    ]);
    let p = plan(&paths, &d, &mut r, &operator_desktop());
    assert_eq!(p.install, vec!["libva-nvidia-driver"]);
    assert!(p.enable.is_empty() && p.write.is_empty() && !p.initramfs);
    assert!(p.keep.iter().any(|k| k.contains("never swapped")));
    assert!(p.keep.iter().any(|k| k.contains("load early")));
    assert!(
        !r.asked
            .iter()
            .any(|q| q.contains("nvidia-open ") || q.ends_with("nvidia-open")),
        "{:?}",
        r.asked
    );
    assert!(p.hyprland_changed);
    assert!(
        p.hyprland.contains(
            "env = {\n        { \"PROTON_ENABLE_NVAPI\", \"1\", when = { \"/sys/module/nvidia\" } },"
        ),
        "{}",
        p.hyprland
    );
    assert!(generated_hyprland_lua(&p.hyprland));
}

#[test]
fn a_turing_laptop_with_intel_graphics() {
    let fs = turing_laptop();
    let d = detect(&fs);
    assert_eq!(d.machine.kind, "laptop");
    assert!(d.machine.laptop && d.machine.lid);
    assert_eq!(d.machine.batteries.len(), 1);
    assert_eq!(d.machine.batteries[0].capacity, Some(82));
    assert_eq!(d.machine.backlight, vec!["intel_backlight"]);
    assert_eq!(d.machine.kbd_backlight, vec!["dell::kbd_backlight"]);
    assert_eq!(d.machine.touchpads, vec!["SYNA2393:00 06CB:7E7E Touchpad"]);
    assert_eq!(d.gpus.len(), 2);
    assert_eq!(d.gpus[0].stack, Stack::Intel);
    assert!(d.gpus[0].panel);
    assert_eq!(d.gpus[1].stack, Stack::NvidiaOpen);
    assert_eq!(d.gpus[1].family.as_deref(), Some("Turing"));
    assert_eq!(
        d.hybrid,
        Some(Hybrid {
            integrated: "0000:00:02.0".into(),
            discrete: "0000:01:00.0".into()
        })
    );
    assert!(!d.nvidia.loaded);

    let w = wanted(&d);
    for p in [
        "nvidia-open",
        "nvidia-utils",
        "libva-nvidia-driver",
        "mesa",
        "vulkan-intel",
        "intel-media-driver",
        "linux-firmware-intel",
        "nvidia-prime",
        "brightnessctl",
        "power-profiles-daemon",
    ] {
        assert!(
            w.packages.iter().any(|x| x == p),
            "{p} missing from {:?}",
            w.packages
        );
    }
    assert!(
        !w.packages.iter().any(|x| x.starts_with("lib32")),
        "no multilib here"
    );
    assert_eq!(w.services, vec!["power-profiles-daemon.service"]);
    let paths: Vec<&str> = w.files.iter().map(|f| f.path.as_str()).collect();
    assert_eq!(
        paths,
        vec![NVIDIA_INITRAMFS, GPU_RULES, NVIDIA_PM_RULES, NVIDIA_PM_CONF]
    );
    let rules = &w.files[1].content;
    assert!(rules.contains(
        "KERNELS==\"0000:00:02.0\", SUBSYSTEMS==\"pci\", SYMLINK+=\"dri/bromigos-igpu\""
    ));
    assert!(rules.contains(
        "KERNELS==\"0000:01:00.0\", SUBSYSTEMS==\"pci\", SYMLINK+=\"dri/bromigos-dgpu\""
    ));
    assert!(
        w.files[0]
            .content
            .contains("MODULES+=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)")
    );
    assert!(
        w.files[3]
            .content
            .contains("NVreg_DynamicPowerManagement=0x02")
    );
    assert_eq!(w.initramfs_files, vec![NVIDIA_INITRAMFS, NVIDIA_PM_CONF]);
    assert_eq!(w.env.len(), 2);
    assert_eq!(w.env[0].name, "AQ_DRM_DEVICES");
    assert_eq!(w.env[1].name, "PROTON_ENABLE_NVAPI");
    assert_eq!(
        w.env[0].value,
        "/dev/dri/bromigos-igpu:/dev/dri/bromigos-dgpu"
    );
    assert!(w.notes.iter().any(|n| n.contains("prime-run")));

    // nothing installed yet: everything in the plan, then applied in order (dry)
    let (_t, paths) = test_paths();
    let mut r = Fake::new(&[
        ("pacman -T NVIDIA-MODULE", 127, "NVIDIA-MODULE\n"),
        ("pacman -Qq tlp", 1, ""),
        (
            "pacman -T",
            127,
            "nvidia-open\nnvidia-utils\nlibva-nvidia-driver\nintel-media-driver\nnvidia-prime\nbrightnessctl\npower-profiles-daemon\n",
        ),
        ("systemctl is-enabled", 1, "disabled\n"),
    ]);
    let p = plan(&paths, &d, &mut r, &fs);
    assert_eq!(
        p.install,
        vec![
            "intel-media-driver",
            "nvidia-open",
            "nvidia-utils",
            "libva-nvidia-driver",
            "nvidia-prime",
            "brightnessctl",
            "power-profiles-daemon"
        ]
    );
    assert_eq!(p.enable, vec!["power-profiles-daemon.service"]);
    assert_eq!(p.write.len(), 4);
    assert!(p.initramfs);
    let mut ran: Vec<(Vec<String>, bool)> = vec![];
    let out = apply(
        &paths,
        &p,
        &ApplyOpts {
            yes: true,
            now: true,
            ..Default::default()
        },
        true,
        &mut |a, i| {
            ran.push((a, i));
            Ok(())
        },
    );
    assert!(out.ok && out.reboot, "{out:?}");
    let lines: Vec<String> = ran.iter().map(|(a, _)| a.join(" ")).collect();
    assert!(lines[0].starts_with(
        "sudo pacman -S --needed --noconfirm intel-media-driver nvidia-open nvidia-utils"
    ));
    assert!(lines[1].starts_with("sudo install -Dm644 ") && lines[1].ends_with(NVIDIA_INITRAMFS));
    assert!(lines[4].ends_with(NVIDIA_PM_CONF));
    assert_eq!(lines[5], "sudo mkinitcpio -P");
    assert_eq!(
        lines[6],
        "sudo systemctl enable --now power-profiles-daemon.service"
    );
    assert_eq!(lines.len(), 7);
    assert!(out.commands.last().unwrap().starts_with("write "));
    assert!(!p.hyprland_path.exists(), "a dry run writes nothing");
}

#[test]
fn an_ampere_laptop_with_amd_graphics_and_the_driver_in() {
    let fs = ampere_laptop();
    let d = detect(&fs);
    // the AMD iGPU drives the panel, though NVIDIA's sorts first on the bus
    assert_eq!(
        d.hybrid,
        Some(Hybrid {
            integrated: "0000:65:00.0".into(),
            discrete: "0000:01:00.0".into()
        })
    );
    let w = wanted(&d);
    let paths: Vec<&str> = w.files.iter().map(|f| f.path.as_str()).collect();
    // Ampere notebooks power down by default: no NVreg setting, the udev rules still
    assert_eq!(paths, vec![NVIDIA_INITRAMFS, GPU_RULES, NVIDIA_PM_RULES]);
    assert!(w.packages.contains(&"vulkan-radeon".to_string()));
    assert!(w.packages.contains(&"linux-firmware-amdgpu".to_string()));
    assert!(w.env[0].why.contains("Rembrandt"), "{}", w.env[0].why);

    // the driver installed (any NVIDIA-MODULE): kept, and what's written already isn't again
    let fs = fs.with(NVIDIA_INITRAMFS, &w.files[0].content);
    let d = detect(&fs);
    assert_eq!(
        d.initramfs_modules,
        Vec::<String>::new(),
        "bromigOS's own drop-in isn't counted"
    );
    let (_t, paths) = test_paths();
    let mut r = Fake::new(&[
        ("pacman -T NVIDIA-MODULE", 0, ""),
        ("pacman -Qq tlp", 1, ""),
        ("pacman -T", 0, ""),
        ("systemctl is-enabled", 0, "enabled\n"),
    ]);
    let p = plan(&paths, &d, &mut r, &fs);
    assert!(p.install.is_empty() && p.enable.is_empty());
    assert_eq!(p.write, vec![GPU_RULES, NVIDIA_PM_RULES]);
    assert!(!p.initramfs, "the initramfs drop-in is as written");
}

#[test]
fn a_hybrid_laptops_hyprland_file_is_lua_with_guards() {
    let d = detect(&turing_laptop());
    let w = wanted(&d);
    let lua = hyprland_lua(&d, &w.env);
    assert!(lua.contains("return {\n"));
    assert!(lua.contains(
        "{ \"AQ_DRM_DEVICES\", \"/dev/dri/bromigos-igpu:/dev/dri/bromigos-dgpu\", when = { \"/dev/dri/bromigos-igpu\" } },"
    ));
    assert!(lua.contains("laptop = true,"));
    assert!(lua.contains("Intel CoffeeLake-H GT2 [UHD Graphics 630] (Intel Gen8 or newer"));
}

#[test]
fn a_qemu_virtual_machine() {
    let d = detect(&qemu_vm());
    assert_eq!(d.machine.virt.as_deref(), Some("qemu"));
    assert_eq!(d.machine.kind, "other");
    assert!(!d.machine.laptop);
    assert_eq!(d.gpus.len(), 1);
    assert_eq!(d.gpus[0].stack, Stack::Virtual);
    assert_eq!(d.gpus[0].vendor, "virtio");
    assert_eq!(d.gpus[0].name, "Virtio 1.0 GPU");
    let w = wanted(&d);
    assert_eq!(w.packages, vec!["mesa"]);
    assert!(w.files.is_empty() && w.env.is_empty() && w.services.is_empty());
    assert_eq!(summary(&d), "a qemu virtual machine; virtio Virtio 1.0 GPU");
}

#[test]
fn a_vm_faked_into_a_laptop_by_its_chassis_or_a_battery() {
    // QEMU's -smbios file= with a type 3 table saying "Notebook"
    let d = detect(&qemu_vm().with("/sys/class/dmi/id/chassis_type", "10\n"));
    assert!(d.machine.laptop);
    assert_eq!(d.machine.kind, "laptop");
    // the kernel's test_power module: a battery, an AC adapter, no lid
    let fs = qemu_vm()
        .with("/sys/class/power_supply/test_battery/type", "Battery\n")
        .with("/sys/class/power_supply/test_battery/present", "1\n")
        .with("/sys/class/power_supply/test_battery/capacity", "50\n")
        .with("/sys/class/power_supply/test_ac/type", "Mains\n")
        .with("/sys/class/power_supply/test_usb/type", "USB\n");
    let d = detect(&fs);
    assert!(d.machine.laptop);
    assert_eq!(d.machine.batteries.len(), 1);
    let w = wanted(&d);
    assert_eq!(
        w.packages,
        vec!["mesa", "brightnessctl", "power-profiles-daemon"]
    );
    assert_eq!(w.services, vec!["power-profiles-daemon.service"]);
    assert_eq!(d.hybrid, None, "one GPU");
}

#[test]
fn a_mouses_battery_or_an_absent_one_is_not_the_machines() {
    let fs = operator_desktop()
        .with("/sys/class/power_supply/hidpp_battery_0/type", "Battery\n")
        .with("/sys/class/power_supply/hidpp_battery_0/scope", "Device\n")
        .with("/sys/class/power_supply/BAT0/type", "Battery\n")
        .with("/sys/class/power_supply/BAT0/present", "0\n");
    let d = detect(&fs);
    assert!(d.machine.batteries.is_empty());
    assert!(!d.machine.laptop);
    // and a server with a battery backup stays a server
    let d = detect(&battery(base(23, "Supermicro", "SYS-1029"), "BAT0"));
    assert!(!d.machine.laptop);
    assert_eq!(d.machine.kind, "server");
}

#[test]
fn an_amd_desktop_with_multilib() {
    let m = base(3, "Micro-Star International Co., Ltd.", "MS-7D70");
    let m = gpu(
        m,
        "0000:03:00.0",
        "1002:744c",
        Some("amdgpu"),
        true,
        Some(("card0", &["DP-1"])),
    );
    let m = m.with("/etc/pacman.conf", "[core]\n[extra]\n[multilib]\n");
    let d = detect(&m);
    let w = wanted(&d);
    assert_eq!(
        w.packages,
        vec![
            "mesa",
            "vulkan-radeon",
            "linux-firmware-amdgpu",
            "lib32-mesa",
            "lib32-vulkan-radeon"
        ]
    );
    assert!(w.files.is_empty() && w.env.is_empty() && w.notes.is_empty());
}

#[test]
fn nvapi_is_only_for_nvidias_own_driver_and_old_generated_files_stay_ours() {
    // nouveau (a Pascal card before its AUR driver): no NVAPI
    let m = base(3, "x", "y");
    let m = gpu(
        m,
        "0000:01:00.0",
        "10de:1b80",
        Some("nouveau"),
        true,
        Some(("card0", &["DP-1"])),
    );
    let d = detect(&m);
    assert!(wanted(&d).env.is_empty(), "{:?}", wanted(&d).env);

    // a file written before PROTON_ENABLE_NVAPI (the old header, no env) is refreshed
    let d = detect(&operator_desktop());
    let old = format!(
        "{HYPRLAND_HEADER_V1}return {{\n    gpus = {},\n    laptop = false,\n    env = {{\n    }},\n}}\n",
        lua_str(
            &d.gpus
                .iter()
                .map(|g| format!("{} ({})", g.title(), g.stack.describe()))
                .collect::<Vec<_>>()
                .join("; ")
        )
    );
    assert!(generated_hyprland_lua(&old));
    let (_t, paths) = test_paths();
    let target = hyprland_path(&paths);
    fs::create_dir_all(target.parent().unwrap()).unwrap();
    fs::write(&target, &old).unwrap();
    let p = plan(&paths, &d, &mut Fake::new(&[]), &operator_desktop());
    assert!(p.hyprland_changed);
    assert!(p.hyprland.contains("PROTON_ENABLE_NVAPI"));

    // the hybrid laptop's file, AQ_DRM_DEVICES then NVAPI, is recognised as ours too; an
    // edited NVAPI line is the user's
    let d = detect(&turing_laptop());
    let lua = hyprland_lua(&d, &wanted(&d).env);
    assert!(generated_hyprland_lua(&lua));
    assert!(!generated_hyprland_lua(
        &lua.replace("\"1\", when", "\"0\", when")
    ));
}

#[test]
fn intel_generations() {
    let m = base(10, "LENOVO", "20KH006M");
    let m = gpu(
        m,
        "0000:00:02.0",
        "8086:5917",
        Some("i915"),
        true,
        Some(("card0", &["eDP-1"])),
    );
    let w = wanted(&detect(&m));
    assert!(w.packages.contains(&"intel-media-driver".to_string()));
    assert!(!w.packages.contains(&"libva-intel-driver".to_string()));
    let m = base(9, "LENOVO", "ThinkPad T440p");
    let m = gpu(m, "0000:00:02.0", "8086:0416", Some("i915"), true, None);
    let d = detect(&m);
    assert_eq!(d.gpus[0].stack, Stack::IntelCrocus);
    let w = wanted(&d);
    assert!(w.packages.contains(&"libva-intel-driver".to_string()));
    assert!(!w.packages.contains(&"intel-media-driver".to_string()));
}

#[test]
fn a_pascal_card_runs_nouveau_until_its_aur_driver_is_in() {
    let m = base(3, "ASUS", "PRIME B450");
    let m = gpu(
        m,
        "0000:01:00.0",
        "10de:1b80",
        Some("nouveau"),
        true,
        Some(("card0", &["DP-1"])),
    );
    let d = detect(&m);
    assert_eq!(d.gpus[0].stack, Stack::Nvidia580xx);
    let w = wanted(&d);
    assert_eq!(
        w.packages,
        vec!["mesa", "vulkan-nouveau", "linux-firmware-nvidia"]
    );
    assert!(
        w.files.is_empty(),
        "nouveau needs no early KMS file (mkinitcpio's kms hook)"
    );
    assert!(
        w.notes.iter().any(|n| n.contains("nvidia-580xx-dkms")),
        "{:?}",
        w.notes
    );

    // the user installed it from the AUR, and it doesn't set modeset: bromigOS does
    let m = m
        .with("/sys/module/nvidia/version", "580.105.08\n")
        .with("/sys/module/nvidia_drm/parameters/modeset", "N\n")
        .with("/sys/module/nvidia_drm/parameters/fbdev", "N\n")
        .with(
            "/proc/driver/nvidia/version",
            "NVRM version: NVIDIA UNIX x86_64 Kernel Module  580.105.08\n",
        );
    let d = detect(&m);
    assert_eq!(d.nvidia.open, Some(false));
    let w = wanted(&d);
    assert!(w.packages.is_empty(), "{:?}", w.packages);
    let paths: Vec<&str> = w.files.iter().map(|f| f.path.as_str()).collect();
    assert_eq!(paths, vec![NVIDIA_INITRAMFS, NVIDIA_KMS_CONF]);
    assert_eq!(w.initramfs_files, vec![NVIDIA_INITRAMFS, NVIDIA_KMS_CONF]);
}

#[test]
fn a_driver_only_the_aur_has_is_offered_through_paru_and_built_only_after_a_yes() {
    let m = base(3, "ASUS", "PRIME B450");
    let m = gpu(m, "0000:01:00.0", "10de:1b80", Some("nouveau"), true, None);
    let m = kernels(m, &["linux", "linux-lts"]).with("/etc/pacman.conf", "[multilib]\n");
    let d = detect(&m);
    let w = wanted(&d);
    assert_eq!(
        w.aur,
        vec![
            "linux-headers",
            "linux-lts-headers",
            "nvidia-580xx-dkms",
            "nvidia-580xx-utils",
            "lib32-nvidia-580xx-utils"
        ]
    );
    assert!(
        w.packages.iter().all(|p| !p.contains("580")),
        "never from pacman"
    );
    // the AUR on (the default) and paru here: offered
    let (_t, paths) = test_paths();
    let mut r = Fake::new(&[
        ("pacman -T NVIDIA-MODULE", 1, ""),
        (
            "pacman -T",
            127,
            "vulkan-nouveau\nnvidia-580xx-dkms\nnvidia-580xx-utils\nlib32-nvidia-580xx-utils\nlinux-headers\nlinux-lts-headers\n",
        ),
        ("paru --version", 0, "paru v2.1.0 - libalpm v16.0.1\n"),
    ]);
    let p = plan(&paths, &d, &mut r, &m);
    assert_eq!(p.aur_helper, Some(crate::aur::Helper::Paru));
    assert_eq!(p.aur.len(), 5);
    let q = aur_question(&p).unwrap();
    assert!(q.contains("nvidia-580xx-dkms") && q.contains("[y/N]") && !q.contains("headers"));
    // no yes: the repositories' packages only
    let mut ran = vec![];
    let out = apply(&paths, &p, &ApplyOpts::default(), true, &mut |a, _| {
        ran.push(a.join(" "));
        Ok(())
    });
    assert!(out.ok);
    assert!(!ran.iter().any(|c| c.contains("paru")), "{ran:?}");
    // a yes: paru builds it after the repositories' packages; --yes skips its review
    let mut ran = vec![];
    let opts = ApplyOpts {
        aur_driver: true,
        yes: true,
        ..Default::default()
    };
    let out = apply(&paths, &p, &opts, true, &mut |a, _| {
        ran.push(a.join(" "));
        Ok(())
    });
    assert!(out.ok && out.reboot);
    assert!(
        ran[0].starts_with("sudo pacman -S --needed --noconfirm "),
        "{ran:?}"
    );
    assert_eq!(
        ran[1],
        "paru -S --needed --noconfirm --skipreview linux-headers linux-lts-headers \
         nvidia-580xx-dkms nvidia-580xx-utils lib32-nvidia-580xx-utils"
    );
    // the AUR off: not offered, and the note says how
    crate::aur::set_enabled(&paths, false).unwrap();
    let mut r = Fake::new(&[
        ("pacman -T", 127, "nvidia-580xx-dkms\nnvidia-580xx-utils\n"),
        ("paru --version", 0, "paru v2.1.0\n"),
    ]);
    let p = plan(&paths, &d, &mut r, &m);
    assert!(p.aur.is_empty() && aur_question(&p).is_none());
    assert!(
        p.notes.iter().any(|n| n.contains("bromigos aur on")),
        "{:?}",
        p.notes
    );
    // on, but no helper: the note says how to get one
    crate::aur::set_enabled(&paths, true).unwrap();
    let mut r = Fake::new(&[("pacman -T", 127, "nvidia-580xx-dkms\n")]);
    let p = plan(&paths, &d, &mut r, &m);
    assert!(p.aur.is_empty());
    assert!(
        p.notes.iter().any(|n| n.contains("no AUR helper")),
        "{:?}",
        p.notes
    );
    // a Kepler card: the 470.xx branch
    let k = gpu(
        base(3, "x", "y"),
        "0000:01:00.0",
        "10de:1180",
        Some("nouveau"),
        true,
        None,
    );
    let w = wanted(&detect(&k));
    assert_eq!(
        w.aur,
        vec!["linux-headers", "nvidia-470xx-dkms", "nvidia-470xx-utils"]
    );
}

#[test]
fn hibernation_keeps_nvidias_modules_out_of_the_initramfs() {
    let m = base(3, "x", "y");
    let m = gpu(m, "0000:01:00.0", "10de:2f04", None, true, None)
        .with("/proc/cmdline", "root=UUID=x rw resume=UUID=swap\n");
    let d = detect(&m);
    assert!(d.hibernation);
    let w = wanted(&d);
    assert!(w.files.is_empty());
    assert!(w.notes.iter().any(|n| n.contains("hibernation")));
    let m = base(3, "x", "y");
    let m = gpu(m, "0000:01:00.0", "10de:2f04", None, true, None).with(
        "/etc/mkinitcpio.conf",
        "MODULES=()\nHOOKS=(base udev autodetect modconf block filesystems resume fsck)\n",
    );
    assert!(detect(&m).hibernation);
}

#[test]
fn a_desktop_with_two_gpus_isnt_a_hybrid() {
    let m = base(3, "x", "y");
    let m = gpu(m, "0000:00:02.0", "8086:a7a0", Some("i915"), false, None);
    let m = gpu(
        m,
        "0000:01:00.0",
        "10de:2f04",
        Some("nvidia"),
        true,
        Some(("card1", &["DP-1"])),
    );
    let d = detect(&m);
    assert_eq!(d.hybrid, None);
    let w = wanted(&d);
    assert!(
        w.env.iter().all(|e| e.name != "AQ_DRM_DEVICES"),
        "{:?}",
        w.env
    );
    assert!(
        w.notes
            .iter()
            .any(|n| n.contains("several GPUs on a desktop"))
    );
}

fn two_desktop_gpus(first: &str, second: &str) -> Mem {
    let m = gpu(
        base(3, "Example", "Desktop"),
        "0000:01:00.0",
        "10de:2f04",
        Some("nvidia"),
        true,
        Some((first, &["DP-1", "HDMI-A-1"])),
    );
    gpu(
        m,
        "0000:02:00.0",
        "1002:699f",
        Some("amdgpu"),
        false,
        Some((second, &["DP-2", "HDMI-A-2"])),
    )
}

#[test]
fn display_choice_follows_the_cable_without_persisting_card_numbers() {
    let m = two_desktop_gpus("card1", "card0")
        .with("/sys/class/drm/card1-DP-1/status", "connected\n")
        .with("/sys/class/drm/card0-DP-2/status", "disconnected\n");
    let d = detect(&m);
    let selected = display_selection(&d);
    assert_eq!(selected.primary_card.as_deref(), Some("card1"));
    assert_eq!(selected.reason_code, "single_connected_gpu");
    assert_eq!(selected.drm_devices, ["/dev/dri/card1", "/dev/dri/card0"]);

    // The firmware still prefers NVIDIA, but the cable moved to AMD.
    let m = m
        .with("/sys/class/drm/card1-DP-1/status", "disconnected\n")
        .with("/sys/class/drm/card0-DP-2/status", "connected\n")
        .with("/sys/class/drm/card0-HDMI-A-2/status", "connected\n");
    let before = m.0.clone();
    let moved = detect(&m);
    let selected = display_selection(&moved);
    assert_eq!(selected.primary_card.as_deref(), Some("card0"));
    assert_eq!(selected.drm_devices, ["/dev/dri/card0", "/dev/dri/card1"]);
    assert_eq!(moved.gpus[1].connected_connectors, ["DP-2", "HDMI-A-2"]);
    assert_eq!(m.0, before, "selection only reads its fixture");
    assert!(
        wanted(&moved)
            .env
            .iter()
            .all(|e| e.name != "AQ_DRM_DEVICES")
    );
    assert_eq!(hyprland_lua(&d, &[]), hyprland_lua(&moved, &[]));

    // DRM enumeration changes on another boot. Resolve the live nodes again.
    let renumbered =
        two_desktop_gpus("card0", "card3").with("/sys/class/drm/card3-DP-2/status", "connected\n");
    let selected = display_selection(&detect(&renumbered));
    assert_eq!(selected.primary_card.as_deref(), Some("card3"));
    assert_eq!(selected.drm_devices, ["/dev/dri/card3", "/dev/dri/card0"]);
}

#[test]
fn multiple_connected_gpus_leave_native_selection_in_charge() {
    let m = two_desktop_gpus("card0", "card1")
        .with("/sys/class/drm/card0-DP-1/status", "connected\n")
        .with("/sys/class/drm/card1-DP-2/status", "connected\n");
    let selected = display_selection(&detect(&m));
    assert_eq!(selected.primary_card, None);
    assert_eq!(selected.reason_code, "multiple_connected_gpus");
    assert_eq!(selected.drm_devices, ["/dev/dri/card0", "/dev/dri/card1"]);
}

#[test]
fn connector_presence_or_unknown_status_is_not_a_connected_monitor() {
    let m = two_desktop_gpus("card0", "card1")
        .with("/sys/class/drm/card0-DP-1/status", "disconnected\n")
        .with("/sys/class/drm/card0-HDMI-A-1/status", "unknown\n")
        .with("/sys/class/drm/card1-DP-2/status", "not connected\n")
        .with("/sys/class/drm/card1-Writeback-1/status", "connected\n");
    // HDMI-A-2 has no readable status; writeback is not a monitor.
    let d = detect(&m);
    assert!(d.gpus.iter().all(|g| g.connected_connectors.is_empty()));
    let selected = display_selection(&d);
    assert_eq!(selected.primary_card, None);
    assert_eq!(selected.reason_code, "no_connected_monitors");
    assert_eq!(selected.drm_devices.len(), 2);
}

#[test]
fn vfio_bound_reserved_and_unbound_gpus_are_excluded() {
    for (driver, override_driver) in [
        (Some("vfio-pci"), None),
        (Some("vfio_pci"), None),
        (Some("nvidia"), Some("vfio-pci\n")),
        (Some("nvidia"), Some("vfio_pci\n")),
        (None, None),
    ] {
        let mut m = gpu(
            two_desktop_gpus("card0", "card1"),
            "0000:01:00.0",
            "10de:2f04",
            driver,
            true,
            Some(("card0", &["DP-1"])),
        )
        .with("/sys/class/drm/card0-DP-1/status", "connected\n")
        .with("/sys/class/drm/card1-DP-2/status", "connected\n");
        if let Some(value) = override_driver {
            m = m.with("/sys/bus/pci/devices/0000:01:00.0/driver_override", value);
        }
        let selected = display_selection(&detect(&m));
        assert_eq!(selected.primary_card.as_deref(), Some("card1"));
        assert_eq!(selected.drm_devices, ["/dev/dri/card1"]);
    }
    let m = two_desktop_gpus("card0", "card1")
        .with(
            "/sys/bus/pci/devices/0000:01:00.0/driver_override",
            "(null)\n",
        )
        .with("/sys/class/drm/card0-DP-1/status", "connected\n");
    assert_eq!(
        display_selection(&detect(&m)).primary_card.as_deref(),
        Some("card0")
    );
}

#[test]
fn a_drm_node_must_be_ready_and_known_before_it_is_selected() {
    let mut m = two_desktop_gpus("card0", "card1")
        .with("/sys/class/drm/card0-DP-1/status", "connected\n")
        .with("/sys/class/drm/card1-DP-2/status", "connected\n");
    m.0.remove("/dev/dri/card0");
    let selected = display_selection(&detect(&m));
    assert_eq!(selected.primary_card.as_deref(), Some("card1"));
    assert_eq!(selected.drm_devices, ["/dev/dri/card1"]);
    m.0.remove("/dev/dri/card1");
    let selected = display_selection(&detect(&m));
    assert_eq!(selected.primary_card, None);
    assert_eq!(selected.reason_code, "no_usable_gpus");
    assert!(selected.drm_devices.is_empty());
    let m = gpu(
        base(3, "Example", "Desktop"),
        "0000:01:00.0",
        "1002:699f",
        Some("amdgpu"),
        true,
        Some(("card-not-a-device", &["DP-1"])),
    )
    .with(
        "/sys/class/drm/card-not-a-device-DP-1/status",
        "connected\n",
    );
    assert_eq!(display_selection(&detect(&m)).reason_code, "no_usable_gpus");
}

#[test]
fn display_selection_does_not_claim_another_seats_gpu() {
    let m = two_desktop_gpus("card0", "card1")
        .with("/sys/class/drm/card0-DP-1/status", "connected\n")
        .with("/sys/class/drm/card1-DP-2/status", "connected\n")
        .with("/sys/class/drm/card1/dev", "226:1\n")
        .with(
            "/run/udev/data/c226:1",
            "E:ID_SEAT=seat1\nE:ID_FOR_SEAT=example\n",
        );
    let d = detect(&m);
    let primary = display_selection(&d);
    assert_eq!(primary.primary_card.as_deref(), Some("card0"));
    assert_eq!(primary.drm_devices, ["/dev/dri/card0"]);
    assert_eq!(display_selection_for_seat(&d, ""), primary);
    let other = display_selection_for_seat(&d, "seat1");
    assert_eq!(other.primary_card.as_deref(), Some("card1"));
    assert_eq!(other.drm_devices, ["/dev/dri/card1"]);
}

#[test]
fn another_kernel_takes_the_dkms_modules() {
    let m = base(3, "x", "y");
    let m = gpu(m, "0000:01:00.0", "10de:2f04", None, true, None);
    let m = kernels(m, &["linux", "linux-zen"]);
    let w = wanted(&detect(&m));
    assert_eq!(
        &w.packages[..3],
        &["nvidia-open-dkms", "linux-headers", "linux-zen-headers"]
    );
    assert_eq!(
        w.module_packages,
        vec!["nvidia-open-dkms", "linux-headers", "linux-zen-headers"]
    );
}

#[test]
fn a_power_manager_of_the_users_own_keeps_power_profiles_out() {
    let fs = turing_laptop();
    let d = detect(&fs);
    let (_t, paths) = test_paths();
    let mut r = Fake::new(&[
        ("pacman -T NVIDIA-MODULE", 0, ""),
        ("pacman -Qq tlp", 1, "tlp\n"),
        ("pacman -T", 0, ""),
        ("systemctl is-enabled", 1, "disabled\n"),
    ]);
    let p = plan(&paths, &d, &mut r, &fs);
    assert!(p.enable.is_empty());
    assert!(p.notes.iter().any(|n| n.contains("tlp manages power here")));
}

#[test]
fn user_only_writes_the_hyprland_file_and_nothing_else() {
    let fs = turing_laptop();
    let d = detect(&fs);
    let (_t, paths) = test_paths();
    let mut r = Fake::new(&[
        ("pacman -T", 127, "nvidia-open\n"),
        ("systemctl is-enabled", 1, ""),
    ]);
    let p = plan(&paths, &d, &mut r, &fs);
    let mut ran = vec![];
    let out = apply(
        &paths,
        &p,
        &ApplyOpts {
            user_only: true,
            ..Default::default()
        },
        false,
        &mut |a, _| {
            ran.push(a);
            Ok(())
        },
    );
    assert!(out.ok, "{out:?}");
    assert!(ran.is_empty(), "no sudo: {ran:?}");
    let text = std::fs::read_to_string(&p.hyprland_path).unwrap();
    assert_eq!(text, p.hyprland);
    // run again: unchanged
    let mut r = Fake::new(&[
        ("pacman -T", 0, ""),
        ("systemctl is-enabled", 0, "enabled\n"),
    ]);
    let p2 = plan(&paths, &d, &mut r, &fs);
    assert!(!p2.hyprland_changed);
}

#[test]
fn hardware_setup_keeps_custom_hyprland_preferences() {
    let m = turing_laptop();
    let d = detect(&m);
    let generated = hyprland_lua(&d, &wanted(&d).env);
    let files = [
        "-- My display configuration\nreturn { env = { { 'AQ_DRM_DEVICES', '/dev/dri/my-display' } } }\n".to_string(),
        generated.replace(
            "/dev/dri/bromigos-igpu:/dev/dri/bromigos-dgpu",
            "/dev/dri/my-display",
        ),
        format!("{generated}-- My extra setting\n"),
        generated.replace("when = { \"/dev/dri/bromigos-igpu\" }", "when = {}"),
    ];
    for custom in files {
        let (_t, paths) = test_paths();
        let target = hyprland_path(&paths);
        fs::create_dir_all(target.parent().unwrap()).unwrap();
        fs::write(&target, &custom).unwrap();
        let mut runner = Fake::new(&[]);
        let p = plan(&paths, &d, &mut runner, &m);
        assert!(!p.hyprland_changed, "preserve custom file: {custom}");
        assert_eq!(p.hyprland, custom);
        assert!(
            p.notes
                .iter()
                .any(|note| note.contains("your own GPU configuration"))
        );
        let out = apply(
            &paths,
            &p,
            &ApplyOpts {
                user_only: true,
                ..Default::default()
            },
            false,
            &mut |_, _| panic!("user-only must not run system commands"),
        );
        assert!(out.ok);
        assert_eq!(fs::read_to_string(target).unwrap(), custom);
    }
}

#[test]
fn hardware_setup_refreshes_only_unchanged_generated_files_after_a_gpu_change() {
    for original in [turing_laptop(), operator_desktop()] {
        let original = detect(&original);
        let text = hyprland_lua(&original, &wanted(&original).env);
        assert!(generated_hyprland_lua(&text));
        let (_t, paths) = test_paths();
        let target = hyprland_path(&paths);
        fs::create_dir_all(target.parent().unwrap()).unwrap();
        fs::write(&target, &text).unwrap();
        let m = qemu_vm();
        let d = detect(&m);
        let mut runner = Fake::new(&[]);
        let p = plan(&paths, &d, &mut runner, &m);
        assert!(p.hyprland_changed);
        assert_eq!(p.hyprland, hyprland_lua(&d, &wanted(&d).env));
    }
}

#[cfg(unix)]
#[test]
fn hardware_setup_keeps_symlinked_and_unreadable_hyprland_files() {
    let (_t, paths) = test_paths();
    let target = hyprland_path(&paths);
    fs::create_dir_all(target.parent().unwrap()).unwrap();
    let elsewhere = target.with_extension("custom.lua");
    let old = detect(&turing_laptop());
    fs::write(&elsewhere, hyprland_lua(&old, &wanted(&old).env)).unwrap();
    std::os::unix::fs::symlink(&elsewhere, &target).unwrap();
    let m = qemu_vm();
    let d = detect(&m);
    for dangling in [false, true] {
        if dangling {
            fs::remove_file(&elsewhere).unwrap();
        }
        let mut runner = Fake::new(&[]);
        let p = plan(&paths, &d, &mut runner, &m);
        assert!(!p.hyprland_changed, "never replace a user-owned symlink");
    }
    fs::remove_file(&target).unwrap();
    fs::write(&target, [0xff, 0xfe]).unwrap();
    let mut runner = Fake::new(&[]);
    let p = plan(&paths, &d, &mut runner, &m);
    assert!(!p.hyprland_changed, "an unreadable file is preserved");
}

#[test]
fn a_failing_step_stops_the_rest() {
    let fs = turing_laptop();
    let d = detect(&fs);
    let (_t, paths) = test_paths();
    let mut r = Fake::new(&[
        ("pacman -T NVIDIA-MODULE", 127, ""),
        ("pacman -T", 127, "nvidia-open\n"),
        ("systemctl is-enabled", 1, ""),
    ]);
    let p = plan(&paths, &d, &mut r, &fs);
    let out = apply(&paths, &p, &ApplyOpts::default(), true, &mut |a, _| {
        if a.contains(&"pacman".to_string()) {
            Err("pacman exited 1".into())
        } else {
            Ok(())
        }
    });
    assert!(!out.ok);
    assert_eq!(out.detail, "pacman exited 1");
    assert_eq!(out.commands.len(), 1);
}

#[test]
fn every_package_a_plan_can_want_is_known_and_on_the_iso() {
    let machines = [
        operator_desktop(),
        turing_laptop(),
        ampere_laptop(),
        qemu_vm(),
    ];
    let mut seen = std::collections::BTreeSet::new();
    for m in machines {
        let m = m.with("/etc/pacman.conf", "[multilib]\n");
        for p in wanted(&detect(&m)).packages {
            seen.insert(p);
        }
    }
    for p in &seen {
        assert!(
            ALL_PACKAGES.contains(&p.as_str()),
            "{p} isn't in ALL_PACKAGES"
        );
    }
    // the ISO's offline repository carries every one (but lib32: the medium has no multilib;
    // and -lts, -dkms: it installs the stock kernel)
    let iso = include_str!("../../../../../iso/build-in-container.sh");
    let at = iso.find("# bromigos hw:").expect(
        "build-in-container.sh lists the hardware packages after a `# bromigos hw:` comment",
    );
    let rest = &iso[at..];
    let open = rest.find("want+=(").expect("a want+=( list") + "want+=(".len();
    let close = rest[open..].find(')').unwrap() + open;
    let listed: Vec<&str> = rest[open..close].split_whitespace().collect();
    for p in ALL_PACKAGES.iter().filter(|p| {
        !p.starts_with("lib32-") && !matches!(**p, "nvidia-open-lts" | "nvidia-open-dkms")
    }) {
        assert!(
            listed.contains(p),
            "{p} isn't in the ISO's hardware list: {listed:?}"
        );
    }
    for p in &listed {
        assert!(
            ALL_PACKAGES.contains(p),
            "the ISO lists {p}, which no plan installs"
        );
    }
}

#[test]
fn stacks_serialize_as_the_tables_kinds() {
    let j = |s: Stack| serde_json::to_string(&s).unwrap();
    assert_eq!(j(Stack::NvidiaOpen), "\"nvidia-open\"");
    assert_eq!(j(Stack::Nvidia580xx), "\"nvidia-580xx\"");
    assert_eq!(j(Stack::Nvidia470xx), "\"nvidia-470xx\"");
    assert_eq!(j(Stack::IntelCrocus), "\"intel-crocus\"");
}
