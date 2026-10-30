//! `bromigos hw display use|keep|cancel|reset`, `hw games`, `hw run`, `hw vfio` and `hw
//! graphics` through the real CLI against a fixture machine: a writable fake root stands in
//! for /var/lib (so no sudo or pkexec is needed), and a stand-in `sudo` only records what
//! it was asked. Nothing touches the real machine.
use std::fs;
use std::path::Path;
use std::process::{Command, Output};

fn write(root: &Path, path: &str, value: &str) {
    let path = root.join(path);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, value).unwrap();
}

/// An RX 550 with the monitor, an RTX 5070 with one too, each with its HDMI audio.
fn machine(root: &Path) {
    for (slot, card, id, driver, boot, status) in [
        (
            "0000:03:00.0",
            "card1",
            "1002:699F",
            "amdgpu",
            "0",
            "connected",
        ),
        (
            "0000:0a:00.0",
            "card0",
            "10DE:2F04",
            "nvidia",
            "1",
            "connected",
        ),
    ] {
        let event =
            format!("PCI_CLASS=30000\nPCI_ID={id}\nPCI_SLOT_NAME={slot}\nDRIVER={driver}\n");
        write(root, &format!("sys/bus/pci/devices/{slot}/uevent"), &event);
        write(root, &format!("sys/bus/pci/devices/{slot}/boot_vga"), boot);
        write(root, &format!("sys/class/drm/{card}/device/uevent"), &event);
        write(root, &format!("sys/class/drm/{card}-DP-1/status"), status);
        write(root, &format!("dev/dri/{card}"), "");
        let audio = slot.replace(".0", ".1");
        write(
            root,
            &format!("sys/bus/pci/devices/{audio}/uevent"),
            &format!(
                "PCI_CLASS=40300\nPCI_ID=1002:AAE0\nPCI_SLOT_NAME={audio}\nDRIVER=snd_hda_intel\n"
            ),
        );
        let group = if slot.starts_with("0000:03") {
            "14"
        } else {
            "20"
        };
        for s in [slot.to_string(), audio] {
            fs::create_dir_all(root.join(format!("sys/kernel/iommu_groups/{group}/devices/{s}")))
                .unwrap();
        }
    }
    write(root, "proc/sys/kernel/random/boot_id", "boot-a\n");
    write(root, "proc/cpuinfo", "vendor_id\t: AuthenticAMD\n");
    write(
        root,
        "etc/mkinitcpio.conf",
        "MODULES=()\nHOOKS=(base systemd autodetect microcode modconf kms block filesystems)\n",
    );
}

fn run(root: &Path, args: &[&str], env: &[(&str, &str)]) -> Output {
    let mut c = Command::new(env!("CARGO_BIN_EXE_bromigos"));
    c.arg("hw")
        .args(args)
        .env_clear()
        .env("HOME", root.join("home"))
        .env("XDG_RUNTIME_DIR", root.join("run"))
        .env("BROMIGOS_FS_ROOT", root)
        .env("PATH", root.join("bin"));
    for (k, v) in env {
        c.env(k, v);
    }
    c.output().unwrap()
}

fn json(o: &Output) -> serde_json::Value {
    assert!(o.status.success(), "{o:?}");
    serde_json::from_slice(&o.stdout).unwrap()
}

fn chosen(root: &Path) -> String {
    String::from_utf8(run(root, &["display", "--hyprland-chosen"], &[]).stdout).unwrap()
}

#[test]
fn a_new_desktop_card_is_tried_kept_or_dropped_and_reset_from_a_console() {
    let t = tempfile::tempdir().unwrap();
    let root = t.path();
    machine(root);
    // both cards have monitors: Automatic has no clear choice, nothing chosen
    assert_eq!(chosen(root), "");
    let v = json(&run(root, &["display", "use", "0a:00.0", "--json"], &[]));
    assert_eq!(v["ok"], true);
    assert_eq!(v["trial"], true);
    assert!(v["said"].as_str().unwrap().starts_with("Trying NVIDIA"));
    let saved: serde_json::Value = serde_json::from_str(
        &fs::read_to_string(root.join("var/lib/bromigos/hw/graphics.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(saved["trial"]["card"]["slot"], "0000:0a:00.0");
    assert_eq!(saved["trial"]["boot_id"], "boot-a");
    assert!(saved["desktop"].is_null());
    // the login screen and Hyprland get it while this boot lasts
    assert_eq!(chosen(root), "trial /dev/dri/card0:/dev/dri/card1\n");
    let d = json(&run(root, &["display", "--json"], &[]));
    assert_eq!(
        (d["reason_code"].as_str(), d["primary_card"].as_str()),
        (Some("trial_gpu"), Some("card0"))
    );
    // a restart (another boot ID) goes back by itself
    write(root, "proc/sys/kernel/random/boot_id", "boot-b\n");
    assert_eq!(chosen(root), "");
    let o = run(root, &["display", "keep", "--json"], &[]);
    assert_eq!(o.status.code(), Some(1));
    assert!(json_err(&o).contains("no card is being tried now"));
    // tried again and kept
    json(&run(root, &["display", "use", "card0", "--json"], &[]));
    let v = json(&run(root, &["display", "keep", "--json"], &[]));
    assert_eq!(v["said"], "Kept NVIDIA 10de:2f04 for the desktop");
    write(root, "proc/sys/kernel/random/boot_id", "boot-c\n");
    assert_eq!(chosen(root), "chosen /dev/dri/card0:/dev/dri/card1\n");
    // trying the other one, then dropping the try
    json(&run(
        root,
        &["display", "use", "0000:03:00.0", "--json"],
        &[],
    ));
    assert_eq!(chosen(root), "trial /dev/dri/card1:/dev/dri/card0\n");
    json(&run(root, &["display", "cancel", "--json"], &[]));
    assert_eq!(chosen(root), "chosen /dev/dri/card0:/dev/dri/card1\n");
    // the console's way back: Automatic
    let o = run(root, &["display", "reset"], &[]);
    assert!(o.status.success());
    assert!(String::from_utf8_lossy(&o.stdout).contains("Automatic"));
    assert_eq!(chosen(root), "");
}

fn json_err(o: &Output) -> String {
    let v: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(v["ok"], false);
    v["error"].as_str().unwrap().to_string()
}

#[test]
fn a_card_without_a_monitor_or_a_gone_card_is_refused_and_falls_back() {
    let t = tempfile::tempdir().unwrap();
    let root = t.path();
    machine(root);
    write(root, "sys/class/drm/card0-DP-1/status", "disconnected");
    let o = run(root, &["display", "use", "card0", "--json"], &[]);
    assert!(json_err(&o).contains("no monitor is connected to it"));
    let o = run(root, &["display", "use", "0000:0b:00.0", "--json"], &[]);
    assert!(json_err(&o).contains("no card 0000:0b:00.0 here"));
    // what Automatic uses now is saved straight away: nothing to try
    let v = json(&run(root, &["display", "use", "card1", "--json"], &[]));
    assert!(v["trial"].is_null());
    assert_eq!(chosen(root), "chosen /dev/dri/card1:/dev/dri/card0\n");
    // that card pulled: Automatic again, and the report says why
    fs::remove_dir_all(root.join("sys/bus/pci/devices/0000:03:00.0")).unwrap();
    write(root, "sys/class/drm/card0-DP-1/status", "connected");
    assert_eq!(chosen(root), "");
    let d = json(&run(root, &["display", "--json"], &[]));
    assert_eq!(d["source"], "automatic");
    assert!(
        d["note"]
            .as_str()
            .unwrap()
            .contains("isn't at 0000:03:00.0 any more")
    );
}

#[test]
fn games_follow_the_choice_and_hw_run_sets_each_vendors_switches() {
    let t = tempfile::tempdir().unwrap();
    let root = t.path();
    machine(root);
    // the desktop on the RX 550 (this session's device list): games on the strongest, NVIDIA
    let aq = [("AQ_DRM_DEVICES", "/dev/dri/card1:/dev/dri/card0")];
    let o = run(root, &["run", "--print"], &aq);
    assert_eq!(
        String::from_utf8(o.stdout).unwrap(),
        "MESA_VK_DEVICE_SELECT=10de:2f04\n__GLX_VENDOR_LIBRARY_NAME=nvidia\n\
         __NV_PRIME_RENDER_OFFLOAD=1\n__VK_LAYER_NV_optimus=NVIDIA_only\n"
    );
    // chosen: the RX 550, which draws the desktop: nothing to set
    let v = json(&run(root, &["games", "use", "card1", "--json"], &aq));
    assert_eq!(v["ok"], true);
    assert!(run(root, &["run", "--print"], &aq).stdout.is_empty());
    let v = json(&run(root, &["games", "--json"], &aq));
    assert_eq!(
        (v["source"].as_str(), v["slot"].as_str()),
        (Some("chosen"), Some("0000:03:00.0"))
    );
    // the program runs with them (a stand-in program prints its environment)
    json(&run(root, &["games", "use", "auto", "--json"], &aq));
    let bin = root.join("bin");
    fs::create_dir_all(&bin).unwrap();
    let env_bin = ["/usr/bin/env", "/bin/env"]
        .into_iter()
        .find(|p| Path::new(p).exists())
        .unwrap();
    let o = run(root, &["run", "--", env_bin], &aq);
    let out = String::from_utf8(o.stdout).unwrap();
    assert!(out.contains("__NV_PRIME_RENDER_OFFLOAD=1\n"), "{out}");
    // Steam's launcher: only with Steam there, and only ours is removed
    let o = run(root, &["games", "steam", "on", "--json"], &[]);
    assert!(json_err(&o).contains("Steam isn't installed"));
    write(
        root,
        "usr/share/applications/steam.desktop",
        "[Desktop Entry]\nExec=/usr/bin/steam %U\n",
    );
    json(&run(root, &["games", "steam", "on", "--json"], &[]));
    let mine =
        fs::read_to_string(root.join("home/.local/share/applications/steam.desktop")).unwrap();
    assert!(mine.contains(" hw run -- /usr/bin/steam %U\n"), "{mine}");
    json(&run(root, &["games", "steam", "off", "--json"], &[]));
    assert!(
        !root
            .join("home/.local/share/applications/steam.desktop")
            .exists()
    );
    write(
        root,
        "home/.local/share/applications/steam.desktop",
        "[Desktop Entry]\nExec=mine\n",
    );
    assert!(json_err(&run(root, &["games", "steam", "off", "--json"], &[])).contains("your own"));
}

#[test]
fn vfio_reserves_by_address_through_sudo_and_releases() {
    let t = tempfile::tempdir().unwrap();
    let root = t.path();
    machine(root);
    // the monitor card is refused, with its reasons
    let o = run(root, &["vfio", "reserve", "card1", "--json"], &[]);
    assert!(json_err(&o).contains("A monitor is connected to it"));
    // the RTX: its monitor moved away, but the firmware starts on it
    write(root, "sys/class/drm/card0-DP-1/status", "disconnected");
    let o = run(root, &["vfio", "reserve", "card0", "--json"], &[]);
    assert!(json_err(&o).contains("firmware starts on this card"));
    write(root, "sys/bus/pci/devices/0000:0a:00.0/boot_vga", "0");
    let v = json(&run(root, &["vfio", "--json"], &[]));
    let rtx = v["cards"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["slot"] == "0000:0a:00.0")
        .unwrap();
    assert_eq!(rtx["vfio"]["ready"], true, "{rtx}");
    // a dry run lists the commands
    let v = json(&run(
        root,
        &["vfio", "reserve", "card0", "--dry-run", "--json"],
        &[],
    ));
    let cmds: Vec<&str> = v["commands"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| c.as_str().unwrap())
        .collect();
    assert!(
        cmds.iter()
            .any(|c| c.ends_with(" /etc/bromigos/hw/vfio-pci-override.sh")
                && c.starts_with("sudo install -Dm755 "))
    );
    assert_eq!(cmds.last().unwrap(), &"sudo mkinitcpio -P");
    assert!(!root.join("home/.local/state/bromigos/hw/staged").exists());
    // for real, with a stand-in sudo that records what it was asked
    let bin = root.join("bin");
    fs::create_dir_all(&bin).unwrap();
    let log = root.join("sudo.log");
    // it records, and for `install` keeps a copy of what it would install under installed/
    fs::write(
        bin.join("sudo"),
        format!(
            "#!/bin/sh\necho \"$*\" >> {log}\nif [ \"$1\" = install ]; then\n  \
             /usr/bin/mkdir -p \"{dst}$(/usr/bin/dirname \"$4\")\" && /usr/bin/cp \"$3\" \"{dst}$4\"\nfi\n",
            log = log.display(),
            dst = root.join("installed").display()
        ),
    )
    .unwrap();
    Command::new("/bin/chmod")
        .arg("+x")
        .arg(bin.join("sudo"))
        .status()
        .unwrap();
    let v = json(&run(root, &["vfio", "reserve", "0a:00.0", "--json"], &[]));
    assert_eq!(v["reboot"], true);
    let asked = fs::read_to_string(&log).unwrap();
    assert!(
        asked.contains("/etc/modprobe.d/bromigos-vfio.conf\n"),
        "{asked}"
    );
    assert!(asked.contains("/etc/mkinitcpio.conf.d/bromigos-vfio.conf\n"));
    assert!(asked.contains("/var/lib/bromigos/hw/graphics.json\n"));
    assert!(asked.ends_with("mkinitcpio -P\n"));
    // each file arrived whole, the two bromigos-vfio.conf files apart
    let got = |p: &str| {
        fs::read_to_string(root.join("installed").join(p.trim_start_matches('/'))).unwrap()
    };
    assert!(got("/etc/modprobe.d/bromigos-vfio.conf").contains("install vfio-pci /bin/sh"));
    assert!(got("/etc/mkinitcpio.conf.d/bromigos-vfio.conf").contains("MODULES+=(vfio_pci"));
    assert!(
        got("/etc/bromigos/hw/vfio-pci-override.sh")
            .contains("reserve 0000:0a:00.0 0x10de:0x2f04 0000:0a:00.1")
    );
    assert!(got("/var/lib/bromigos/hw/graphics.json").contains("\"0000:0a:00.0\""));
    // the stand-in installed nothing: the system file is written the same way, so put it
    // where sudo would have, and release
    let staged_gone = !root
        .join("home/.local/state/bromigos/hw/staged/graphics.json")
        .exists();
    assert!(staged_gone, "the staged files are cleaned up");
    let saved = serde_json::json!({"vfio": [{"card": {"slot": "0000:0a:00.0", "id": "10de:2f04", "name": "x"},
                                             "functions": ["0000:0a:00.1"], "modules": ["snd_hda_intel"]}]});
    write(
        root,
        "var/lib/bromigos/hw/graphics.json",
        &saved.to_string(),
    );
    let v = json(&run(root, &["vfio", "--json"], &[]));
    assert_eq!(v["reserved"][0]["card"]["slot"], "0000:0a:00.0");
    fs::write(&log, "").unwrap();
    json(&run(root, &["vfio", "release", "all", "--json"], &[]));
    let asked = fs::read_to_string(&log).unwrap();
    assert!(asked.starts_with("rm -f /etc/bromigos/hw/vfio-pci-override.sh /etc/modprobe.d/bromigos-vfio.conf /etc/mkinitcpio.conf.d/bromigos-vfio.conf\n"), "{asked}");
    assert!(
        json_err(&run(root, &["vfio", "release", "card1", "--json"], &[]))
            .contains("isn't reserved")
    );
}

#[test]
fn the_graphics_report_has_every_card_and_use() {
    let t = tempfile::tempdir().unwrap();
    let root = t.path();
    machine(root);
    let v = json(&run(
        root,
        &["graphics", "--json"],
        &[("AQ_DRM_DEVICES", "/dev/dri/card1")],
    ));
    assert_eq!(v["ok"], true);
    let cards = v["cards"].as_array().unwrap();
    assert_eq!(cards.len(), 2);
    assert_eq!(v["desktop"]["running"], "0000:03:00.0");
    assert_eq!(v["games"]["slot"], "0000:0a:00.0");
    assert_eq!(v["games"]["source"], "automatic");
    assert_eq!(v["iommu"]["on"], true);
    for c in cards {
        assert!(c["vfio"]["checks"].as_array().unwrap().len() >= 6);
        assert!(c["title"].is_string());
    }
    let text = run(root, &["graphics"], &[]);
    assert!(text.status.success());
    assert!(String::from_utf8_lossy(&text.stdout).contains("Games"));
}
