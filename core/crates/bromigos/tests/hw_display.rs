//! The startup probe's real CLI against fake sysfs, with no desktop or system tools.
use std::fs;
use std::path::Path;
use std::process::{Command, Output};

fn write(root: &Path, path: &str, value: &str) {
    let path = root.join(path);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, value).unwrap();
}

fn machine(root: &Path) {
    for (slot, card, id, driver, boot, status) in [
        (
            "0000:01:00.0",
            "card3",
            "10DE:2F04",
            "nvidia",
            "1",
            "disconnected",
        ),
        (
            "0000:02:00.0",
            "card8",
            "1002:699F",
            "amdgpu",
            "0",
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
    }
}

fn run(root: &Path, flags: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_bromigos"))
        .args(["hw", "display"])
        .args(flags)
        .env_clear()
        .env("HOME", root.join("home"))
        .env("XDG_RUNTIME_DIR", root.join("run"))
        .env("BROMIGOS_FS_ROOT", root)
        .env("PATH", root.join("no-external-tools"))
        .output()
        .unwrap()
}

#[test]
fn display_query_exposes_connected_card_to_both_startup_consumers() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    machine(root);
    let output = run(root, &["--json"]);
    assert!(output.status.success(), "{:?}", output);
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["schema"], 1);
    assert_eq!(value["primary_card"], "card8");
    assert_eq!(value["reason_code"], "single_connected_gpu");
    assert_eq!(
        value["drm_devices"],
        serde_json::json!(["/dev/dri/card8", "/dev/dri/card3"])
    );
    let output = run(root, &["--hyprland"]);
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8(output.stdout).unwrap(),
        "/dev/dri/card8:/dev/dri/card3\n"
    );
    assert!(
        !root
            .join("home/.local/state/bromigos/hw/hyprland.lua")
            .exists()
    );
}

#[test]
fn ambiguous_connections_do_not_emit_a_hyprland_override() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    machine(root);
    write(root, "sys/class/drm/card3-DP-1/status", "connected");
    let output = run(root, &["--hyprland"]);
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
    let output = run(root, &["--json"]);
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(value["primary_card"].is_null());
    assert_eq!(value["reason_code"], "multiple_connected_gpus");
}

#[test]
fn startup_output_formats_cannot_be_mixed() {
    let temp = tempfile::tempdir().unwrap();
    let output = run(temp.path(), &["--json", "--hyprland"]);
    assert_eq!(output.status.code(), Some(2));
}
