//! What each card is for, against whole machines made of files: two discrete cards from
//! different vendors, identical twins, a hybrid laptop, IOMMU groups, a swapped card.

use super::*;
use crate::hw::tests::{Mem, gpu};
use crate::hw::{PCI_IDS, detect};

const IDS: &str = "\
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t699f  Lexa PRO [Radeon 540/540X/550/550X / RX 540X/550/550X]
\taaf0  Ellesmere HDMI Audio [Radeon RX 470/480 / 570/580/590]
\t744c  Navi 31 [Radeon RX 7900 XT/7900 XTX/7900 GRE/7900M]
10de  NVIDIA Corporation
\t2f04  GB205 [GeForce RTX 5070]
\t22eb  GB205 High Definition Audio Controller
8086  Intel Corporation
\t3e9b  CoffeeLake-H GT2 [UHD Graphics 630]
\t56a0  DG2 [Arc A770]
\ta36d  Cannon Lake PCH USB 3.1 xHCI Host Controller
";

/// A card with its connectors' status (true: a monitor is connected).
fn card(
    m: Mem,
    slot: &str,
    id: &str,
    driver: &str,
    boot: bool,
    drm: &str,
    conns: &[(&str, bool)],
) -> Mem {
    let names: Vec<&str> = conns.iter().map(|(c, _)| *c).collect();
    let mut m = gpu(m, slot, id, Some(driver), boot, Some((drm, &names)));
    for (c, on) in conns {
        m = m.with(
            &format!("/sys/class/drm/{drm}-{c}/status"),
            if *on { "connected\n" } else { "disconnected\n" },
        );
    }
    m
}

fn pci(m: Mem, slot: &str, class: &str, id: &str, driver: &str) -> Mem {
    m.with(
        &format!("/sys/bus/pci/devices/{slot}/uevent"),
        &format!("DRIVER={driver}\nPCI_CLASS={class}\nPCI_ID={id}\nPCI_SLOT_NAME={slot}\n"),
    )
}

/// A desktop: an RX 550 with the monitor, an RTX 5070 without, each with its HDMI audio;
/// IOMMU groups of their own (the NVIDIA card's group has a PCI bridge too).
fn desktop_machine() -> Mem {
    let m = Mem::default()
        .with(PCI_IDS, IDS)
        .with("/sys/class/dmi/id/chassis_type", "3\n")
        .with("/proc/cpuinfo", "vendor_id\t: AuthenticAMD\nflags\t: fpu\n")
        .with("/proc/sys/kernel/random/boot_id", "boot-a\n");
    let m = card(
        m,
        "0000:03:00.0",
        "1002:699f",
        "amdgpu",
        false,
        "card1",
        &[("DP-1", true), ("HDMI-A-1", false)],
    );
    let m = pci(m, "0000:03:00.1", "40300", "1002:AAF0", "snd_hda_intel");
    let m = card(
        m,
        "0000:0a:00.0",
        "10de:2f04",
        "nvidia",
        true,
        "card0",
        &[("DP-2", false)],
    );
    let m = pci(m, "0000:0a:00.1", "40300", "10DE:22EB", "snd_hda_intel");
    let m = pci(m, "0000:00:01.1", "60400", "1022:1483", "pcieport");
    m.dir("/sys/kernel/iommu_groups/14/devices/0000:03:00.0")
        .dir("/sys/kernel/iommu_groups/14/devices/0000:03:00.1")
        .dir("/sys/kernel/iommu_groups/20/devices/0000:0a:00.0")
        .dir("/sys/kernel/iommu_groups/20/devices/0000:0a:00.1")
        .dir("/sys/kernel/iommu_groups/20/devices/0000:00:01.1")
}

fn rtx(d: &Detection) -> &Gpu {
    d.gpus.iter().find(|g| g.id == "10de:2f04").unwrap()
}
fn rx(d: &Detection) -> &Gpu {
    d.gpus.iter().find(|g| g.id == "1002:699f").unwrap()
}

fn chose(g: &Gpu) -> SystemChoice {
    SystemChoice {
        desktop: Some(CardRef::of(g)),
        ..Default::default()
    }
}

#[test]
fn automatic_is_the_card_with_the_monitor() {
    let d = detect(&desktop_machine());
    let s = desktop(&d, "seat0", &SystemChoice::default(), "boot-a");
    assert_eq!(s.source, "automatic");
    assert_eq!(s.slot.as_deref(), Some("0000:03:00.0"));
    assert_eq!(
        s.selection.drm_devices,
        ["/dev/dri/card1", "/dev/dri/card0"]
    );
    assert!(s.note.is_none());
}

#[test]
fn a_chosen_card_wins_only_while_it_has_a_monitor() {
    let m = desktop_machine().with("/sys/class/drm/card0-DP-2/status", "connected\n");
    let d = detect(&m);
    // both connected: Automatic has no clear choice; the chosen card decides
    assert_eq!(
        desktop(&d, "seat0", &SystemChoice::default(), "")
            .selection
            .primary_card,
        None
    );
    let s = desktop(&d, "seat0", &chose(rtx(&d)), "boot-a");
    assert_eq!(s.source, "chosen");
    assert_eq!(s.selection.reason_code, "chosen_gpu");
    assert_eq!(s.selection.primary_card.as_deref(), Some("card0"));
    assert_eq!(
        s.selection.drm_devices,
        ["/dev/dri/card0", "/dev/dri/card1"]
    );
    // its monitor unplugged: Automatic, and a note says why
    let d2 = detect(&desktop_machine());
    let s = desktop(&d2, "seat0", &chose(rtx(&d2)), "boot-a");
    assert_eq!(s.source, "automatic");
    assert_eq!(s.slot.as_deref(), Some("0000:03:00.0"));
    assert!(s.note.unwrap().contains("no monitor connected"));
}

#[test]
fn a_swapped_card_in_the_same_slot_is_not_the_chosen_one() {
    let m = desktop_machine().with("/sys/class/drm/card0-DP-2/status", "connected\n");
    let d = detect(&m);
    let mut c = chose(rtx(&d));
    c.desktop.as_mut().unwrap().id = "10de:2684".into(); // the card chosen was a 4090
    let s = desktop(&d, "seat0", &c, "boot-a");
    assert_eq!(s.source, "automatic");
    assert!(s.note.unwrap().contains("isn't at 0000:0a:00.0 any more"));
}

#[test]
fn a_trial_counts_only_during_the_boot_it_was_made_in() {
    let m = desktop_machine().with("/sys/class/drm/card0-DP-2/status", "connected\n");
    let d = detect(&m);
    let c = SystemChoice {
        desktop: Some(CardRef::of(rx(&d))),
        trial: Some(Trial {
            card: CardRef::of(rtx(&d)),
            boot_id: "boot-a".into(),
        }),
        vfio: vec![],
    };
    let s = desktop(&d, "seat0", &c, "boot-a");
    assert_eq!(
        (s.source.as_str(), s.selection.reason_code.as_str()),
        ("trial", "trial_gpu")
    );
    assert_eq!(s.slot.as_deref(), Some("0000:0a:00.0"));
    // after a restart the kept choice is back, by itself
    let s = desktop(&d, "seat0", &c, "boot-b");
    assert_eq!(s.source, "chosen");
    assert_eq!(s.slot.as_deref(), Some("0000:03:00.0"));
    // no boot ID to compare: never a trial
    assert_eq!(desktop(&d, "seat0", &c, "").source, "chosen");
}

#[test]
fn a_card_reserved_for_vms_is_never_the_desktop() {
    let m = desktop_machine()
        .with("/sys/class/drm/card0-DP-2/status", "connected\n")
        .with(
            "/sys/bus/pci/devices/0000:0a:00.0/driver_override",
            "vfio-pci\n",
        );
    let d = detect(&m);
    let s = desktop(&d, "seat0", &chose(rtx(&d)), "boot-a");
    assert_eq!(s.source, "automatic");
    assert!(s.note.unwrap().contains("no working driver"));
}

#[test]
fn the_strongest_card_runs_games() {
    let d = detect(&desktop_machine());
    // Blackwell over Polaris, whichever draws the desktop
    assert_eq!(
        strongest(&d, Some("0000:03:00.0")).unwrap().slot,
        "0000:0a:00.0"
    );
    let g = games(&desktop_machine(), &d, &UserChoice::default(), Some(rx(&d)));
    assert_eq!(
        (g.source.as_str(), g.slot.as_deref()),
        ("automatic", Some("0000:0a:00.0"))
    );
    // the user's choice wins while the card is there
    let u = UserChoice {
        games: Some(CardRef::of(rx(&d))),
    };
    let g = games(&desktop_machine(), &d, &u, Some(rx(&d)));
    assert_eq!(
        (g.source.as_str(), g.slot.as_deref()),
        ("chosen", Some("0000:03:00.0"))
    );
    assert!(
        g.env.is_empty(),
        "the desktop's own card needs nothing: {:?}",
        g.env
    );
    // gone: Automatic, with a note
    let mut gone = u.clone();
    gone.games.as_mut().unwrap().slot = "0000:05:00.0".into();
    let g = games(&desktop_machine(), &d, &gone, Some(rx(&d)));
    assert_eq!(g.source, "automatic");
    assert!(g.notes[0].contains("Automatic instead"));
}

#[test]
fn a_card_of_its_own_beats_a_built_in_one() {
    let m = Mem::default().with(PCI_IDS, IDS);
    let m = card(
        m,
        "0000:00:02.0",
        "8086:3e9b",
        "i915",
        true,
        "card0",
        &[("DP-1", true)],
    );
    let m = card(
        m,
        "0000:03:00.0",
        "8086:56a0",
        "i915",
        false,
        "card1",
        &[("DP-2", false)],
    );
    let d = detect(&m);
    assert!(integrated(&d.gpus[0], &d));
    assert!(!integrated(&d.gpus[1], &d));
    assert_eq!(
        strongest(&d, Some("0000:00:02.0")).unwrap().slot,
        "0000:03:00.0"
    );
}

#[test]
fn identical_cards_tie_to_the_desktops_and_differ_by_address() {
    let m = Mem::default().with(PCI_IDS, IDS);
    let m = card(
        m,
        "0000:03:00.0",
        "1002:744c",
        "amdgpu",
        false,
        "card1",
        &[("DP-1", false)],
    );
    let m = card(
        m,
        "0000:0a:00.0",
        "1002:744c",
        "amdgpu",
        true,
        "card0",
        &[("DP-2", true)],
    );
    let d = detect(&m);
    assert_eq!(
        strongest(&d, Some("0000:0a:00.0")).unwrap().slot,
        "0000:0a:00.0"
    );
    assert_eq!(
        strongest(&d, Some("0000:03:00.0")).unwrap().slot,
        "0000:03:00.0"
    );
    // the other twin for games: only its address tells it apart
    let env = run_env(&d, &d.gpus[0], Some(&d.gpus[1]));
    assert_eq!(
        env,
        BTreeMap::from([("DRI_PRIME".to_string(), "pci-0000_03_00_0".to_string())])
    );
}

#[test]
fn each_vendor_gets_its_own_switches() {
    let d = detect(&desktop_machine());
    // the desktop on AMD, games on NVIDIA: PRIME render offload, as prime-run, and Vulkan's order
    let env = run_env(&d, rtx(&d), Some(rx(&d)));
    let want: BTreeMap<String, String> = [
        ("MESA_VK_DEVICE_SELECT", "10de:2f04"),
        ("__GLX_VENDOR_LIBRARY_NAME", "nvidia"),
        ("__NV_PRIME_RENDER_OFFLOAD", "1"),
        ("__VK_LAYER_NV_optimus", "NVIDIA_only"),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v.to_string()))
    .collect();
    assert_eq!(env, want);
    // the desktop on NVIDIA, games on AMD: Mesa by its address, and GLVND pointed at Mesa
    let env = run_env(&d, rx(&d), Some(rtx(&d)));
    assert_eq!(env["DRI_PRIME"], "pci-0000_03_00_0");
    assert_eq!(env["MESA_VK_DEVICE_SELECT"], "1002:699f");
    assert_eq!(env["__GLX_VENDOR_LIBRARY_NAME"], "mesa");
    assert_eq!(env["__EGL_VENDOR_LIBRARY_FILENAMES"], MESA_EGL);
    assert!(!env.contains_key("__NV_PRIME_RENDER_OFFLOAD"));
    // the same card: nothing
    assert!(run_env(&d, rx(&d), Some(rx(&d))).is_empty());
}

#[test]
fn games_say_when_vulkan_cant_be_pointed_at_the_card() {
    let m = desktop_machine();
    let d = detect(&m);
    let g = games(&m, &d, &UserChoice::default(), Some(rx(&d)));
    assert!(g.notes.iter().any(|n| n.contains("device-select layer")));
    let m = m.with(DEVICE_SELECT_LAYER, "{}");
    let g = games(&m, &d, &UserChoice::default(), Some(rx(&d)));
    assert!(g.notes.is_empty(), "{:?}", g.notes);
}

#[test]
fn the_running_session_is_read_from_its_device_list() {
    let d = detect(&desktop_machine());
    assert_eq!(
        running_desktop(&d, Some("/dev/dri/card0:/dev/dri/card1"))
            .unwrap()
            .slot,
        "0000:0a:00.0"
    );
    assert!(running_desktop(&d, None).is_none());
    assert!(running_desktop(&d, Some("/dev/dri/card9")).is_none());
    assert_eq!(find_card(&d, "03:00.0").unwrap().id, "1002:699f");
    assert_eq!(find_card(&d, "card0").unwrap().id, "10de:2f04");
    assert_eq!(find_card(&d, "0000:0a:00.0").unwrap().id, "10de:2f04");
    assert!(find_card(&d, "0000:0b:00.0").is_none());
}

fn hooks() -> Vec<String> {
    [
        "base",
        "systemd",
        "autodetect",
        "microcode",
        "modconf",
        "kms",
        "block",
        "filesystems",
    ]
    .map(String::from)
    .to_vec()
}

#[test]
fn a_spare_card_passes_every_check() {
    let m = desktop_machine();
    let d = detect(&m);
    let io = iommu(&m, Bootloader::Grub);
    assert!(io.on);
    let v = vfio_state(
        &m,
        &d,
        rtx(&d),
        &SystemChoice::default(),
        "boot-a",
        &io,
        &hooks(),
    );
    let failed: Vec<&Check> = v
        .checks
        .iter()
        .filter(|c| !c.ok && c.id != "boot")
        .collect();
    assert!(failed.is_empty(), "{failed:?}");
    // the bridge in its group is fine; its audio goes with it
    assert_eq!(v.group.as_deref(), Some("20"));
    assert_eq!(v.functions, ["0000:0a:00.1"]);
    // but the firmware starts on it here: that one check stops it
    assert!(!v.ready);
    assert_eq!(
        v.checks.iter().find(|c| c.id == "boot").map(|c| c.ok),
        Some(false)
    );
    let m = m.with("/sys/bus/pci/devices/0000:0a:00.0/boot_vga", "0\n");
    let d = detect(&m);
    let v = vfio_state(
        &m,
        &d,
        rtx(&d),
        &SystemChoice::default(),
        "boot-a",
        &io,
        &hooks(),
    );
    assert!(v.ready, "{:?}", v.checks);
    assert!(v.reset.is_none());
}

#[test]
fn the_monitor_card_and_the_only_card_are_never_reserved() {
    let m = desktop_machine();
    let d = detect(&m);
    let io = iommu(&m, Bootloader::Grub);
    let v = vfio_state(
        &m,
        &d,
        rx(&d),
        &SystemChoice::default(),
        "boot-a",
        &io,
        &hooks(),
    );
    let bad: Vec<&str> = v
        .checks
        .iter()
        .filter(|c| !c.ok)
        .map(|c| c.id.as_str())
        .collect();
    // a monitor on it, the desktop on it, and no other card with a monitor
    assert_eq!(bad, ["monitor", "desktop", "other"]);
    // Polaris: the AMD reset bug
    assert!(v.reset.unwrap().contains("vendor-reset"));
}

#[test]
fn a_shared_iommu_group_or_no_iommu_stops_it() {
    let m = desktop_machine()
        .with("/sys/bus/pci/devices/0000:0a:00.0/boot_vga", "0\n")
        .dir("/sys/kernel/iommu_groups/20/devices/0000:00:14.0");
    let m = pci(m, "0000:00:14.0", "C0330", "8086:A36D", "xhci_hcd");
    let d = detect(&m);
    let io = iommu(&m, Bootloader::Grub);
    let v = vfio_state(&m, &d, rtx(&d), &SystemChoice::default(), "", &io, &hooks());
    let g = v.checks.iter().find(|c| c.id == "group").unwrap();
    assert!(!g.ok);
    assert!(
        g.text.contains(
            "a USB controller (Cannon Lake PCH USB 3.1 xHCI Host Controller) at 0000:00:14.0"
        ),
        "{}",
        g.text
    );

    // no groups: the IOMMU is off; Intel needs its parameter, on GRUB's line
    let mut off = Mem::default();
    for (k, v) in desktop_machine().0 {
        if !k.starts_with("/sys/kernel/iommu_groups") {
            off = off.with(&k, &v);
        }
    }
    let off = off.with("/proc/cpuinfo", "vendor_id\t: GenuineIntel\n");
    let io = iommu(&off, Bootloader::Grub);
    assert!(!io.on);
    assert_eq!(io.param.as_deref(), Some("intel_iommu=on"));
    assert!(
        io.steps
            .iter()
            .any(|s| s.contains("GRUB_CMDLINE_LINUX_DEFAULT"))
    );
    assert!(
        io.steps
            .iter()
            .any(|s| s == "sudo grub-mkconfig -o /boot/grub/grub.cfg")
    );
    let d = detect(&off);
    let v = vfio_state(
        &off,
        &d,
        rtx(&d),
        &SystemChoice::default(),
        "",
        &io,
        &hooks(),
    );
    assert!(!v.checks[0].ok && !v.checks[1].ok);
    // an initramfs without a shell can't run the script
    let v = vfio_state(
        &m,
        &d,
        rtx(&d),
        &SystemChoice::default(),
        "",
        &io,
        &["systemd".into(), "modconf".into()],
    );
    assert!(!v.checks.iter().find(|c| c.id == "initramfs").unwrap().ok);
}

#[test]
fn the_reservation_names_addresses_and_checks_the_card_at_boot() {
    let m = desktop_machine();
    let d = detect(&m);
    let r = reservation(&m, rtx(&d));
    assert_eq!(r.functions, ["0000:0a:00.1"]);
    assert_eq!(r.modules, ["snd_hda_intel"]);
    let files = vfio_files(&[r]);
    let get = |p: &str| files.iter().find(|f| f.0 == p).unwrap();
    let (_, script, mode) = get(VFIO_SCRIPT);
    assert_eq!(*mode, 0o755);
    assert!(script.contains("RESERVED=\"0000:0a:00.0\"\n"));
    assert!(script.contains("    reserve 0000:0a:00.0 0x10de:0x2f04 0000:0a:00.1   # NVIDIA GB205 [GeForce RTX 5070]\n"), "{script}");
    assert!(script.ends_with("fi\nmodprobe -i vfio-pci\nexit 0\n"));
    let (_, modprobe, _) = get(VFIO_MODPROBE);
    assert!(modprobe.contains(&format!("install vfio-pci /bin/sh {VFIO_SCRIPT}\n")));
    for m in ["drm", "nvidia", "snd_hda_intel"] {
        assert!(
            modprobe.contains(&format!("softdep {m} pre: vfio-pci\n")),
            "{modprobe}"
        );
    }
    let (_, initramfs, _) = get(VFIO_INITRAMFS);
    assert!(initramfs.contains("MODULES+=(vfio_pci vfio vfio_iommu_type1)\n"));
    assert!(initramfs.contains(&format!("FILES+=({VFIO_SCRIPT})\n")));
    assert!(vfio_files(&[]).is_empty());
}

#[test]
fn the_vfio_script_runs_in_a_shell_against_a_fixture_sysfs() {
    // the script itself, in sh, with /sys moved into a temporary tree
    let Ok(sh) = which("sh") else { return };
    let t = tempfile::tempdir().unwrap();
    let root = t.path();
    let dev = |slot: &str, vendor: &str, device: &str, class: &str, boot: &str| {
        let p = root.join(format!("sys/bus/pci/devices/{slot}"));
        fs::create_dir_all(&p).unwrap();
        fs::write(p.join("vendor"), format!("{vendor}\n")).unwrap();
        fs::write(p.join("device"), format!("{device}\n")).unwrap();
        fs::write(p.join("class"), format!("{class}\n")).unwrap();
        fs::write(p.join("boot_vga"), format!("{boot}\n")).unwrap();
        fs::write(p.join("driver_override"), "(null)\n").unwrap();
    };
    dev("0000:03:00.0", "0x1002", "0x699f", "0x030000", "1");
    dev("0000:0a:00.0", "0x10de", "0x2f04", "0x030000", "0");
    dev("0000:0a:00.1", "0x10de", "0x22eb", "0x040300", "0");
    fs::create_dir_all(root.join("sys/class/iommu/ivhd0")).unwrap();
    let m = desktop_machine();
    let d = detect(&m);
    let files = vfio_files(&[reservation(&m, rtx(&d))]);
    let script = files[0]
        .1
        .replace("/sys/", &format!("{}/sys/", root.display()));
    // modprobe is a stand-in that records it was asked
    let bin = root.join("bin");
    fs::create_dir_all(&bin).unwrap();
    fs::write(
        bin.join("modprobe"),
        format!("#!/bin/sh\necho \"$@\" > {}/modprobe.log\n", root.display()),
    )
    .unwrap();
    std::process::Command::new("chmod")
        .arg("+x")
        .arg(bin.join("modprobe"))
        .status()
        .unwrap();
    let run = |script: &str| {
        let out = std::process::Command::new(&sh)
            .arg("-c")
            .arg(script)
            .env("PATH", format!("{}:/usr/bin:/bin", bin.display()))
            .output()
            .unwrap();
        assert!(out.status.success(), "{out:?}");
    };
    let read = |slot: &str| {
        fs::read_to_string(root.join(format!("sys/bus/pci/devices/{slot}/driver_override")))
            .unwrap()
    };
    run(&script);
    assert_eq!(read("0000:0a:00.0"), "vfio-pci\n");
    assert_eq!(read("0000:0a:00.1"), "vfio-pci\n");
    assert_eq!(read("0000:03:00.0"), "(null)\n");
    assert_eq!(
        fs::read_to_string(root.join("modprobe.log")).unwrap(),
        "-i vfio-pci\n"
    );
    // another card at that address now: left alone
    for s in ["0000:0a:00.0", "0000:0a:00.1"] {
        fs::write(
            root.join(format!("sys/bus/pci/devices/{s}/driver_override")),
            "(null)\n",
        )
        .unwrap();
    }
    fs::write(
        root.join("sys/bus/pci/devices/0000:0a:00.0/device"),
        "0x2684\n",
    )
    .unwrap();
    run(&script);
    assert_eq!(read("0000:0a:00.0"), "(null)\n");
    // the only display device left (the other card pulled): left alone
    fs::write(
        root.join("sys/bus/pci/devices/0000:0a:00.0/device"),
        "0x2f04\n",
    )
    .unwrap();
    fs::remove_dir_all(root.join("sys/bus/pci/devices/0000:03:00.0")).unwrap();
    run(&script);
    assert_eq!(read("0000:0a:00.0"), "(null)\n");
    // the IOMMU off: left alone
    dev("0000:03:00.0", "0x1002", "0x699f", "0x030000", "1");
    fs::remove_dir_all(root.join("sys/class/iommu/ivhd0")).unwrap();
    run(&script);
    assert_eq!(read("0000:0a:00.0"), "(null)\n");
}

fn which(name: &str) -> Result<PathBuf, ()> {
    std::env::var("PATH")
        .unwrap_or_default()
        .split(':')
        .map(|d| PathBuf::from(d).join(name))
        .find(|p| p.exists())
        .ok_or(())
}

#[test]
fn steam_starts_through_bromigos_hw_run() {
    let original = "[Desktop Entry]\nName=Steam\nExec=/usr/bin/steam %U\n\n[Desktop Action Store]\nExec=steam steam://store\n";
    let out = steam_launcher(original, "/usr/bin/bromigos");
    assert!(out.starts_with(STEAM_MARK));
    assert!(out.contains("Exec=/usr/bin/bromigos hw run -- /usr/bin/steam %U\n"));
    assert!(out.contains("Exec=/usr/bin/bromigos hw run -- steam steam://store\n"));
    assert!(out.contains("[Desktop Action Store]\n"));
}

#[test]
fn the_choice_files_round_trip_and_survive_damage() {
    let d = detect(&desktop_machine());
    let c = SystemChoice {
        desktop: Some(CardRef::of(rx(&d))),
        trial: Some(Trial {
            card: CardRef::of(rtx(&d)),
            boot_id: "boot-a".into(),
        }),
        vfio: vec![],
    };
    let m = Mem::default().with(SYSTEM_FILE, &c.to_text());
    assert_eq!(read_system(&m), c);
    assert_eq!(
        read_system(&Mem::default().with(SYSTEM_FILE, "{ broken")),
        SystemChoice::default()
    );
    assert_eq!(boot_id(&desktop_machine()), "boot-a");
}

#[test]
fn the_firmwares_tables_say_which_iommu_and_what_to_do() {
    // Intel's VT-d on in the firmware (its DMAR table), Linux not asked: only the parameter
    let m = Mem::default()
        .with("/proc/cpuinfo", "vendor_id\t: AuthenticAMD\n")
        .with("/sys/firmware/acpi/tables/DMAR", "")
        .with("/proc/cmdline", "root=UUID=x rw\n");
    let io = iommu(&m, Bootloader::SystemdBoot);
    assert!(!io.on);
    assert_eq!(io.param.as_deref(), Some("intel_iommu=on"));
    assert!(io.steps[0].contains("its DMAR table is there"));
    assert!(io.steps.iter().any(|s| s.contains("/etc/kernel/cmdline")));
    assert!(!io.steps.iter().any(|s| s.contains("firmware settings")));
    // AMD-Vi on in the firmware, off in Linux: something turned it off
    let m = Mem::default()
        .with("/proc/cpuinfo", "vendor_id\t: AuthenticAMD\n")
        .with("/sys/firmware/acpi/tables/IVRS", "");
    let io = iommu(&m, Bootloader::Grub);
    assert!(io.param.is_none());
    assert!(io.steps.iter().any(|s| s.contains("amd_iommu=off")));
    // already on: nothing to do
    let m = m.dir("/sys/kernel/iommu_groups/0/devices/0000:00:00.0");
    assert!(iommu(&m, Bootloader::Grub).steps.is_empty());
}
