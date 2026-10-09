//! `bromigos peripheral` and setup's peripherals section end to end, in a sandbox: a temp
//! HOME and runtime dir (no session: nothing reloads), a fake /proc and /sys with the
//! operator's Razer keyboard and mouse (`BROMIGOS_PERIPHERAL_ROOT`), the repository's own
//! razer-keyboard module, and a PATH without pacman, systemctl or Hyprland.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use serde_json::Value;

const MANIFEST: &str = include_str!("../../../../peripherals/razer-keyboard/peripheral.toml");

// /proc/bus/input/devices as his machine lists them (trimmed): the BlackWidow V4 Pro's
// interfaces (razerkbd) and the Naga Hex V2's (razermouse; its third interface is a full
// keyboard too).
const DEVICES: &str = "\
I: Bus=0003 Vendor=1532 Product=0050 Version=0111
N: Name=\"Razer Razer Naga Hex V2\"
P: Phys=usb-0000:0c:00.3-2.4/input0
S: Sysfs=/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb5/5-2/5-2.4/5-2.4:1.0/0003:1532:0050.000D/input/input16
H: Handlers=event5 mouse0
B: KEY=1f0000 0 0 0 0
B: REL=903

I: Bus=0003 Vendor=1532 Product=028d Version=0111
N: Name=\"Razer Razer BlackWidow V4 Pro\"
P: Phys=usb-0000:0c:00.3-2.2/input0
S: Sysfs=/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb5/5-2/5-2.2/5-2.2:1.0/0003:1532:028D.0006/input/input19
H: Handlers=sysrq kbd leds event13
B: KEY=3c0000000000 0 0 0 0 0 0 1000000000007 ff9f207ac14057ff febeffdfffefffff fffffffffffffffe

I: Bus=0003 Vendor=1532 Product=0050 Version=0111
N: Name=\"Razer Razer Naga Hex V2\"
P: Phys=usb-0000:0c:00.3-2.4/input2
S: Sysfs=/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb5/5-2/5-2.4/5-2.4:1.2/0003:1532:0050.000F/input/input32
H: Handlers=sysrq kbd leds event18
B: KEY=1000000000007 ff9f207ac14057ff febeffdfffefffff fffffffffffffffe

I: Bus=0003 Vendor=1532 Product=028d Version=0111
N: Name=\"Razer Razer BlackWidow V4 Pro\"
P: Phys=usb-0000:0c:00.3-2.2/input2
S: Sysfs=/devices/pci0000:00/0000:00:08.1/0000:0c:00.3/usb5/5-2/5-2.2/5-2.2:1.2/0003:1532:028D.0008/input/input34
H: Handlers=kbd event25 mouse1
B: KEY=3c0000000000 0 0 0 0 0 1f0000 0 0 c000000000000 0
B: REL=1043
";

struct Sandbox {
    dir: tempfile::TempDir,
}

impl Sandbox {
    fn new() -> Sandbox {
        let s = Sandbox {
            dir: tempfile::tempdir().unwrap(),
        };
        for d in ["home", "run", "bin", "share/peripherals/razer-keyboard"] {
            fs::create_dir_all(s.p(d)).unwrap();
        }
        fs::write(
            s.p("share/peripherals/razer-keyboard/peripheral.toml"),
            MANIFEST,
        )
        .unwrap();
        s.plug(true);
        s
    }
    fn p(&self, rel: &str) -> PathBuf {
        self.dir.path().join(rel)
    }
    /// The keyboard and mouse connected (with openrazer's drivers bound), or neither.
    fn plug(&self, on: bool) {
        let root = self.p("root");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("proc/bus/input")).unwrap();
        fs::write(
            root.join("proc/bus/input/devices"),
            if on { DEVICES } else { "" },
        )
        .unwrap();
        for (hid, drv) in [
            ("0003:1532:028D.0006", "razerkbd"),
            ("0003:1532:028D.0008", "razerkbd"),
            ("0003:1532:0050.000D", "razermouse"),
            ("0003:1532:0050.000F", "razermouse"),
        ] {
            let d = root.join("sys/bus/hid/devices").join(hid);
            fs::create_dir_all(&d).unwrap();
            std::os::unix::fs::symlink(
                format!("../../../../bus/hid/drivers/{drv}"),
                d.join("driver"),
            )
            .unwrap();
        }
    }
    fn cmd(&self, args: &[&str]) -> Command {
        let mut c = Command::new(env!("CARGO_BIN_EXE_bromigos"));
        c.args(args)
            .env_clear()
            .env("HOME", self.p("home"))
            .env("USER", "tester")
            .env("XDG_RUNTIME_DIR", self.p("run"))
            .env("BROMIGOS_SHARE_DIR", self.p("share"))
            .env("BROMIGOS_PERIPHERAL_ROOT", self.p("root"))
            .env("BROMIGOS_HOLO_BIN", "/nonexistent/bromigos-holo")
            .env("PATH", self.p("bin"));
        c
    }
    fn run(&self, args: &[&str]) -> Output {
        self.cmd(args).output().unwrap()
    }
    fn json(&self, args: &[&str]) -> Value {
        let o = self.run(args);
        serde_json::from_slice(&o.stdout).unwrap_or_else(|e| {
            panic!(
                "{args:?}: {e}: {}{}",
                String::from_utf8_lossy(&o.stdout),
                String::from_utf8_lossy(&o.stderr)
            )
        })
    }
    fn config(&self) -> PathBuf {
        self.p("home/.config/bromigos/peripherals.toml")
    }
    fn hypr(&self) -> PathBuf {
        self.p("home/.local/state/bromigos/peripherals/hypr.lua")
    }
}

fn text(o: &Output) -> String {
    format!(
        "{}{}",
        String::from_utf8_lossy(&o.stdout),
        String::from_utf8_lossy(&o.stderr)
    )
}

#[test]
fn lists_the_module_and_finds_the_keyboard_not_the_mouse() {
    let s = Sandbox::new();
    let d = s.json(&["peripheral", "list", "--json"]);
    let m = &d["modules"][0];
    assert_eq!(m["id"], "razer-keyboard");
    assert_eq!(m["enabled"], false);
    let found = m["found"].as_array().unwrap();
    assert_eq!(found.len(), 1, "{found:?}");
    assert_eq!(found[0]["name"], "Razer Razer BlackWidow V4 Pro");
    assert_eq!(found[0]["how"], "driver");
    assert_eq!(found[0]["dial"], "/dev/input/event25");
    // no pacman here: nothing counts as installed
    assert!(
        m["needs"]["packages"]
            .as_array()
            .unwrap()
            .iter()
            .all(|p| p["installed"] == false)
    );
    let o = s.run(&["peripheral"]);
    assert!(o.status.success());
    assert!(
        text(&o).contains("found: Razer Razer BlackWidow V4 Pro (1532:028d, razerkbd; a dial)")
    );
    assert!(text(&o).contains("bromigos peripheral enable razer-keyboard"));
}

#[test]
fn a_dry_run_changes_nothing() {
    let s = Sandbox::new();
    let o = s.run(&[
        "peripheral",
        "enable",
        "razer-keyboard",
        "--dry-run",
        "--yes",
    ]);
    assert!(o.status.success(), "{}", text(&o));
    let t = text(&o);
    assert!(
        t.contains("sudo pacman -S --needed --noconfirm openrazer-driver-dkms openrazer-daemon python-openrazer python-evdev"),
        "{t}"
    );
    assert!(t.contains("sudo gpasswd -a tester openrazer"));
    assert!(t.contains("systemctl --user enable --now openrazer-daemon.service"));
    assert!(t.contains("systemctl --user enable --now bromigos-peripherals.service"));
    assert!(!s.config().exists() && !s.hypr().exists());
}

#[test]
fn enable_refresh_and_disable() {
    let s = Sandbox::new();
    let d = s.json(&[
        "peripheral",
        "enable",
        "razer-keyboard",
        "--no-system",
        "--json",
    ]);
    let r = &d["result"];
    assert_eq!(r["ok"], true, "{d}");
    assert_eq!(r["hypr"]["reload"], "no running session");
    assert!(r["commands"].as_array().unwrap().is_empty());
    // VECTOR isn't installed here: his three keys wait for him, the rest are bound
    let binds: Vec<&str> = r["module"]["binds"]
        .as_array()
        .unwrap()
        .iter()
        .map(|b| b["id"].as_str().unwrap())
        .collect();
    assert_eq!(binds, ["m4", "m5", "side1", "side2", "side3", "dial"]);
    assert_eq!(r["module"]["skipped"].as_array().unwrap().len(), 3);
    let cfg = fs::read_to_string(s.config()).unwrap();
    assert!(cfg.contains("[razer-keyboard]\nenabled = true"), "{cfg}");
    let lua = fs::read_to_string(s.hypr()).unwrap();
    assert!(lua.contains("tag = \"bromigos-razer-keyboard\""));
    assert!(lua.contains("\"razer-razer-blackwidow-v4-pro-5\""));
    assert!(!lua.contains("naga"));
    assert!(lua.contains("{ keys = \"code:202\", cmd = \"bromigos mute\""));

    // the daemon's view
    let st = s.json(&["peripheral", "status", "--json"]);
    assert_eq!(st["ok"], true);
    assert_eq!(st["hypr_current"], true);
    assert_eq!(st["modules"][0]["dials"][0], "/dev/input/event25");
    assert_eq!(st["modules"][0]["rgb_scope"], "all");

    // a key of the user's: status says the keys are stale until refresh writes them
    fs::write(
        s.config(),
        format!("{cfg}\n[razer-keyboard.keys]\nside1 = \"my-deck --open\"\nm5 = \"\"\n"),
    )
    .unwrap();
    assert_eq!(
        s.json(&["peripheral", "status", "--json"])["hypr_current"],
        false
    );
    let o = s.run(&["peripheral", "refresh"]);
    assert!(o.status.success(), "{}", text(&o));
    let lua = fs::read_to_string(s.hypr()).unwrap();
    assert!(lua.contains("cmd = \"my-deck --open\""));
    assert!(!lua.contains("code:195"), "m5 unbound");
    assert_eq!(
        s.json(&["peripheral", "status", "--json"])["hypr_current"],
        true
    );
    let o = s.run(&["peripheral", "status"]);
    assert!(
        text(&o).contains("side 1      the desktop menu (yours)  [my-deck --open]"),
        "{}",
        text(&o)
    );

    // unplugged: the keys stay as they are (no rewrite, no reload)
    s.plug(false);
    let st = s.json(&["peripheral", "status", "--json"]);
    assert_eq!(st["hypr_current"], true, "{st}");
    assert!(st["modules"][0]["found"].as_array().unwrap().is_empty());
    assert!(st["modules"][0]["dials"].as_array().unwrap().is_empty());

    let d = s.json(&[
        "peripheral",
        "disable",
        "razer-keyboard",
        "--no-system",
        "--json",
    ]);
    assert_eq!(d["result"]["ok"], true, "{d}");
    assert!(!s.hypr().exists());
    assert!(
        fs::read_to_string(s.config())
            .unwrap()
            .contains("enabled = false")
    );
    // the user's keys stay for next time
    assert!(
        fs::read_to_string(s.config())
            .unwrap()
            .contains("my-deck --open")
    );
    let d = s.json(&["peripheral", "disable", "razer-keyboard", "--json"]);
    assert!(d["result"].is_null());
}

#[test]
fn not_connected_needs_force_and_bad_input_is_refused() {
    let s = Sandbox::new();
    s.plug(false);
    let o = s.run(&["peripheral", "enable", "razer-keyboard", "--no-system"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(
        text(&o).contains("no Razer keyboard is connected"),
        "{}",
        text(&o)
    );
    assert!(!s.config().exists());
    let o = s.run(&[
        "peripheral",
        "enable",
        "razer-keyboard",
        "--no-system",
        "--force",
    ]);
    assert!(o.status.success(), "{}", text(&o));
    assert!(text(&o).contains("Razer keyboard is on."));

    let o = s.run(&["peripheral", "enable", "nope", "--no-system"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(text(&o).contains("no module \"nope\""));

    // a typo in the user's file: an error, not a silent default
    fs::write(s.config(), "[razer-keyboard]\nenabeld = true\n").unwrap();
    let o = s.run(&["peripheral", "status"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(text(&o).contains("enabeld"), "{}", text(&o));
}

#[test]
fn a_users_own_module_and_a_broken_one() {
    let s = Sandbox::new();
    let mine = s.p("home/.config/bromigos/peripherals/macro-pad");
    fs::create_dir_all(&mine).unwrap();
    fs::write(
        mine.join("peripheral.toml"),
        "format = 1\nname = \"My macro pad\"\ndescription = \"F13-F24 on a QMK pad\"\n\
         [match]\nusb_vendor = \"1532\"\nname_hints = [\"BlackWidow\"]\n\
         [keymap]\noptions = [\"fkeys:basic_13-24\"]\n\
         [[keys]]\nid = \"f13\"\ncode = 191\nlabel = \"F13\"\npress = \"kitty\"\nhint = \"a terminal\"\n",
    )
    .unwrap();
    let bad = s.p("home/.config/bromigos/peripherals/broken");
    fs::create_dir_all(&bad).unwrap();
    fs::write(bad.join("peripheral.toml"), "format = 1\nname = \"x\"\n").unwrap();
    let d = s.json(&["peripheral", "list", "--json"]);
    let ids: Vec<&str> = d["modules"]
        .as_array()
        .unwrap()
        .iter()
        .map(|m| m["id"].as_str().unwrap())
        .collect();
    assert_eq!(ids, ["macro-pad", "razer-keyboard"]);
    assert_eq!(d["modules"][0]["source"], "user");
    assert_eq!(d["broken"][0]["id"], "broken");
    let o = s.run(&["peripheral", "list"]);
    assert!(text(&o).contains("(yours)") && text(&o).contains("BROKEN"));
}

#[test]
fn setup_turns_one_on_from_an_answers_file() {
    let s = Sandbox::new();
    let answers = s.p("answers.toml");
    fs::write(
        &answers,
        "[peripherals]\nenable = [\"razer-keyboard\"]\nsystem = false\n",
    )
    .unwrap();
    let d = s.json(&[
        "setup",
        "peripherals",
        "--answers",
        answers.to_str().unwrap(),
        "--json",
    ]);
    let a = &d["setup"][0];
    assert_eq!(a["section"], "peripherals");
    assert_eq!(a["ok"], true, "{d}");
    assert_eq!(a["detail"], "razer-keyboard on");
    assert!(s.hypr().exists());
    let rec = fs::read_to_string(s.p("home/.local/state/bromigos/setup.toml")).unwrap();
    assert!(
        rec.contains("[peripherals]") && rec.contains("razer-keyboard"),
        "{rec}"
    );
    // a misspelled key in the answers is an error
    fs::write(&answers, "[peripherals]\nenabel = [\"razer-keyboard\"]\n").unwrap();
    let o = s.run(&[
        "setup",
        "peripherals",
        "--answers",
        answers.to_str().unwrap(),
    ]);
    assert!(!o.status.success());
    let _ = Path::new("");
}
