//! `bromigos install` and `bromigos setup`: the plan a dry run makes (commands recorded by a
//! fake runner, nothing run), and setup's writers.

use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

use bromigos_core::create;
use bromigos_core::install::{self, Options, Runner, Status};
use bromigos_core::paths::Paths;
use bromigos_core::setup::{self, HomelabAnswer, Monitor, VectorAnswer};

/// Answers queries from a table (argv joined by spaces -> (code, stdout)); records runs.
struct Fake {
    answers: HashMap<String, (i32, String)>,
    ran: Vec<String>,
}

impl Fake {
    fn new(pairs: &[(&str, i32, &str)]) -> Self {
        Fake {
            answers: pairs
                .iter()
                .map(|(k, c, o)| (k.to_string(), (*c, o.to_string())))
                .collect(),
            ran: vec![],
        }
    }
}

impl Runner for Fake {
    fn run(&mut self, argv: &[String], _interactive: bool) -> std::io::Result<(i32, String)> {
        self.ran.push(argv.join(" "));
        Ok((0, String::new()))
    }
    fn query(&mut self, argv: &[&str]) -> (i32, String) {
        self.answers
            .get(&argv.join(" "))
            .cloned()
            .unwrap_or((1, String::new()))
    }
}

fn sandbox() -> (tempfile::TempDir, Paths) {
    let d = tempfile::tempdir().unwrap();
    let root = d.path().to_path_buf();
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let m: HashMap<&str, PathBuf> = [
        ("HOME", root.join("home")),
        ("XDG_CONFIG_HOME", root.join("config")),
        ("XDG_STATE_HOME", root.join("state")),
        ("XDG_RUNTIME_DIR", root.join("run")),
        ("BROMIGOS_SHARE_DIR", repo.canonicalize().unwrap()),
        ("BROMIGOS_PACMAN_LOCAL", root.join("pacman")),
    ]
    .into_iter()
    .collect();
    let paths = Paths::from_lookup(|k| m.get(k).cloned());
    (d, paths)
}

#[test]
fn preflight_wants_the_repository() {
    assert!(install::has_repo("[options]\n\n[bromigos]\nServer = x\n"));
    assert!(!install::has_repo("[options]\n#[bromigos]\n"));
}

#[test]
fn the_package_step_names_only_unowned_hand_installed_paths() {
    let mut f = Fake::new(&[(
        "pacman -Qqo /usr/share/icons/Bromigos",
        0,
        "bromigos-settings\n",
    )]);
    let globs = install::overwrite_globs(&mut f, |p| {
        p == "/usr/share/sddm/themes/bromigos" || p == "/usr/share/icons/Bromigos"
    });
    assert_eq!(globs, vec!["/usr/share/sddm/themes/bromigos/*".to_string()]);
    let opts = Options {
        yes: true,
        extras: vec!["herdr".into()],
        ..Options::default()
    };
    assert_eq!(
        install::package_command(&opts, &globs).join(" "),
        "sudo pacman -S --needed --noconfirm --overwrite /usr/share/sddm/themes/bromigos/* bromigos herdr"
    );
}

#[test]
fn a_dry_run_plans_and_leaves_other_network_and_display_managers_alone() {
    let (d, paths) = sandbox();
    let conf = d.path().join("pacman.conf");
    fs::write(
        &conf,
        "[options]\n[bromigos]\nServer = https://example/$repo/$arch\n",
    )
    .unwrap();
    // SAFETY: tests in this file don't read it concurrently with a change
    unsafe { std::env::set_var("BROMIGOS_PACMAN_CONF", &conf) };
    let mut f = Fake::new(&[
        ("pacman --version", 0, "Pacman v7"),
        ("sudo --version", 0, "Sudo 1.9"),
        (
            "systemctl is-enabled systemd-networkd.service",
            0,
            "enabled\n",
        ),
        (
            "systemctl show -P Id display-manager.service",
            0,
            "gdm.service\n",
        ),
        ("pacman -Qq bluez", 0, "bluez\n"),
        ("systemctl is-enabled bluetooth.service", 1, "disabled\n"),
        (
            "systemctl --user is-enabled pipewire.socket",
            0,
            "enabled\n",
        ),
        (
            "systemctl --user is-enabled pipewire-pulse.socket",
            0,
            "enabled\n",
        ),
        (
            "systemctl --user is-enabled wireplumber.service",
            1,
            "disabled\n",
        ),
        ("gsettings --version", 0, "2.84"),
        (
            "gsettings get org.gnome.desktop.interface gtk-theme",
            0,
            "'Adwaita'\n",
        ),
        (
            "gsettings get org.gnome.desktop.interface icon-theme",
            0,
            "'Papirus'\n",
        ),
    ]);
    let r = install::run(
        &paths,
        &Options {
            dry_run: true,
            ..Options::default()
        },
        &mut f,
    );
    assert!(r.ok, "{r:#?}");
    assert!(f.ran.is_empty(), "a dry run runs nothing: {:?}", f.ran);
    let s = |n: &str| r.steps.iter().find(|s| s.name == n).unwrap().clone();
    assert_eq!(s("packages").status, Status::Planned);
    let svc = s("services");
    assert_eq!(
        svc.commands,
        vec![
            "sudo systemctl enable bluetooth.service".to_string(),
            "systemctl --user enable wireplumber.service".to_string(),
        ]
    );
    assert!(
        svc.detail.contains("systemd-networkd") && svc.detail.contains("gdm"),
        "{}",
        svc.detail
    );
    // only GNOME's defaults are replaced; a user's own icon theme stays
    let ds = s("desktop settings");
    assert!(ds.commands.iter().any(|c| c.contains("gtk-theme Bromigos")));
    assert!(!ds.commands.iter().any(|c| c.contains("icon-theme")));
    assert_eq!(s("theme").status, Status::Planned);
    unsafe { std::env::remove_var("BROMIGOS_PACMAN_CONF") };
}

fn mon(output: &str, w: u32, h: u32, hz: f64, pw: u32) -> Monitor {
    Monitor {
        output: output.into(),
        make: "Acme".into(),
        model: "P1".into(),
        width: w,
        height: h,
        refresh: hz,
        phys_w: pw,
        phys_h: pw * 9 / 16,
        x: 0,
        focused: false,
        scale: setup::auto_scale(w, h, pw),
    }
}

#[test]
fn scale_comes_from_pixel_density() {
    assert_eq!(
        setup::auto_scale(2560, 1440, 597),
        1.0,
        "27\" 1440p desktop"
    );
    assert_eq!(setup::auto_scale(3840, 2160, 344), 2.0, "15.6\" 4K laptop");
    assert_eq!(setup::auto_scale(3840, 2160, 597), 1.5, "27\" 4K");
    assert_eq!(
        setup::auto_scale(3840, 2160, 0),
        1.5,
        "no EDID size: by height"
    );
    assert_eq!(setup::auto_scale(1920, 1080, 0), 1.0);
}

#[test]
fn monitors_are_laid_out_left_to_right_in_the_users_order() {
    let ms = vec![
        mon("A", 2560, 1440, 59.951, 597),
        mon("B", 3840, 2160, 0.0, 597),
    ];
    let a = setup::MonitorsAnswer {
        mode: "auto".into(),
        primary: None,
        order: vec!["B".into()],
        scale: [("A".to_string(), 1.25)].into(),
        refresh: [("B".to_string(), 120.0)].into(),
    };
    let lay = setup::arrange(&ms, &a);
    let block = setup::monitors_block(&lay, "now");
    assert!(
        block.contains(
            r#"{ output = "B", mode = "3840x2160@120", position = "0x0", scale = 1.5 },"#
        ),
        "{block}"
    );
    assert!(
        block.contains(
            r#"{ output = "A", mode = "2560x1440@59.95", position = "2560x0", scale = 1.25 },"#
        ),
        "{block}"
    );
    assert!(block.contains("-- Acme P1, 27\""), "{block}");
}

#[test]
fn the_block_goes_before_the_defaults_and_replaces_itself() {
    let lua = "bromigos = {\n    -- mod = \"ALT\",\n}\ndofile(\"/usr/share/bromigos/default/hypr/hyprland.lua\")\n-- mine\n";
    let lay = setup::arrange(
        &[mon("A", 1920, 1080, 60.0, 0)],
        &setup::MonitorsAnswer {
            mode: "auto".into(),
            primary: None,
            order: vec![],
            scale: Default::default(),
            refresh: Default::default(),
        },
    );
    let once = setup::with_monitors_block(lua, &setup::monitors_block(&lay, "t1")).unwrap();
    assert!(once.find(setup::BLOCK_BEGIN).unwrap() < once.find("dofile(").unwrap());
    let twice = setup::with_monitors_block(&once, &setup::monitors_block(&lay, "t2")).unwrap();
    assert_eq!(twice.matches(setup::BLOCK_BEGIN).count(), 1);
    assert!(twice.contains("(t2)") && !twice.contains("(t1)") && twice.ends_with("-- mine\n"));
    assert!(
        setup::with_monitors_block("hl.monitor({})\n", "x").is_err(),
        "no defaults line: refuse"
    );
}

#[test]
fn setup_monitors_writes_the_block_and_the_primary() {
    let (_d, paths) = sandbox();
    let lua = paths.config_home.join("hypr/hyprland.lua");
    fs::create_dir_all(lua.parent().unwrap()).unwrap();
    fs::write(
        &lua,
        "bromigos = {}\ndofile(\"/usr/share/bromigos/default/hypr/hyprland.lua\")\n",
    )
    .unwrap();
    let found = vec![
        mon("A", 1920, 1080, 60.0, 0),
        mon("B", 2560, 1440, 144.0, 597),
    ];
    let a = setup::MonitorsAnswer {
        mode: "auto".into(),
        primary: Some("B".into()),
        order: vec![],
        scale: Default::default(),
        refresh: Default::default(),
    };
    let r = setup::apply_monitors(&paths, &a, &found);
    assert!(r.ok, "{}", r.detail);
    assert!(
        fs::read_to_string(&lua)
            .unwrap()
            .contains("bromigos.monitors = {")
    );
    assert_eq!(
        fs::read_to_string(setup::monitors_toml(&paths))
            .unwrap()
            .lines()
            .last()
            .unwrap(),
        "primary = \"B\""
    );
    let bad = setup::MonitorsAnswer {
        primary: Some("HDMI-A-9".into()),
        ..a
    };
    assert!(
        !setup::apply_monitors(&paths, &bad, &found).ok,
        "an output that isn't here"
    );
}

#[test]
fn create_prefers_lucida_pixal3d_and_finds_seedvr2() {
    let names: Vec<String> = [
        "BiRefNet-general.safetensors",
        "lucida_v7.safetensors",
        "hunyuan_3d_v2.1.safetensors",
        "pixal3d_int8_convrot.safetensors",
        "seedvr2_7b_int8_convrot.safetensors",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    let caps = create::capabilities(&names);
    assert_eq!(caps.get("image.cutout").map(String::as_str), Some("lucida"));
    assert_eq!(
        caps.get("model3d.generate").map(String::as_str),
        Some("pixal3d")
    );
    assert_eq!(
        caps.get("image.upscale").map(String::as_str),
        Some("seedvr2-7b")
    );
    assert_eq!(
        caps.get("video.upscale").map(String::as_str),
        Some("seedvr2-7b-video")
    );
    // no cloud model for upscaling: a pinned choice doesn't add nolgia there
    assert_eq!(create::nolgia_model("image.upscale"), "");
}

#[test]
fn create_finds_capabilities_from_what_an_instance_has() {
    let names: Vec<String> = [
        "qwen_image_2.1_fp8.safetensors",
        "BiRefNet-general.safetensors",
        "wan2.2_ti2v_5B.safetensors",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    let caps = create::capabilities(&names);
    assert_eq!(
        caps.get("image.generate").map(String::as_str),
        Some("qwen-image-2.1")
    );
    assert_eq!(
        caps.get("image.edit").map(String::as_str),
        Some("qwen-image-2.1")
    );
    assert_eq!(
        caps.get("image.cutout").map(String::as_str),
        Some("birefnet")
    );
    assert_eq!(
        caps.get("video.loop").map(String::as_str),
        Some("wan2.2-ti2v-5b"),
        "Wan 2.2's 5B makes loops"
    );
    assert!(!caps.contains_key("model3d.generate"));
    // with the A14B's experts too, loops go to the A14B
    let names: Vec<String> = [
        "wan2.2_ti2v_5B_fp16.safetensors",
        "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    assert_eq!(
        create::capabilities(&names)
            .get("video.loop")
            .map(String::as_str),
        Some("wan2.2-i2v-a14b")
    );
}

#[test]
fn create_toml_is_format_1_and_keeps_the_users_keys() {
    let srv = create::Server {
        name: "homelab".into(),
        endpoint: "@homelab:comfyui".into(),
        url: "http://x:8188".into(),
        gpu: Some("RTX".into()),
        caps: [("image.generate".to_string(), "qwen-image-2.1".to_string())].into(),
    };
    let a = create::CreateAnswer {
        providers: [
            (
                "image.generate".to_string(),
                vec!["comfyui:homelab".to_string(), "nolgia".to_string()],
            ),
            ("video.loop".to_string(), vec!["none".to_string()]),
        ]
        .into(),
        nolgia_login: false,
        nolgia_token_file: None,
    };
    assert!(create::validate(&a, std::slice::from_ref(&srv)).is_ok());
    let existing = "# mine\n[comfyui.homelab]\ntimeout_s = 900\n";
    let t = create::create_toml_text(existing, &a, std::slice::from_ref(&srv)).unwrap();
    let v: toml::Table = t.parse().unwrap();
    assert_eq!(v["format"].as_integer(), Some(1));
    assert_eq!(
        v["comfyui"]["homelab"]["endpoint"].as_str(),
        Some("@homelab:comfyui")
    );
    assert_eq!(
        v["comfyui"]["homelab"]["timeout_s"].as_integer(),
        Some(900),
        "kept"
    );
    assert_eq!(v["nolgia"]["enabled"].as_bool(), Some(true));
    assert_eq!(
        v["image"]["generate"]["comfyui"].as_str(),
        Some("qwen-image-2.1")
    );
    assert_eq!(
        v["image"]["generate"]["nolgia"].as_str(),
        Some("gpt-image-2.5-flare")
    );
    assert_eq!(v["video"]["loop"]["providers"].as_array().unwrap().len(), 1);
    assert!(t.contains("# mine"), "the user's comment is kept");
    let bad = create::CreateAnswer {
        providers: [(
            "video.loop".to_string(),
            vec!["comfyui:homelab".to_string()],
        )]
        .into(),
        nolgia_login: false,
        nolgia_token_file: None,
    };
    assert!(
        create::validate(&bad, &[srv]).is_err(),
        "homelab has no video workflow"
    );
}

#[test]
fn create_resolves_endpoint_references() {
    let (_d, paths) = sandbox();
    let priv_ = paths.user_config_dir().join("private/config.json");
    fs::create_dir_all(priv_.parent().unwrap()).unwrap();
    fs::write(
        &priv_,
        r#"{"env":{"BROMIGOS_COMFYUI_URL":"http://lab:8188"}}"#,
    )
    .unwrap();
    let hl = [(
        "comfyui".to_string(),
        "@private:env.BROMIGOS_COMFYUI_URL".to_string(),
    )]
    .into();
    assert_eq!(
        create::resolve(&paths, "@homelab:comfyui", &hl).as_deref(),
        Some("http://lab:8188")
    );
    assert_eq!(
        create::resolve(&paths, "http://a", &hl).as_deref(),
        Some("http://a")
    );
    assert_eq!(create::resolve(&paths, "@vault:kv/x#y", &hl), None);
}

#[test]
fn the_kernel_lists_connected_outputs() {
    let d = tempfile::tempdir().unwrap();
    for (name, status, modes) in [
        ("card1-DP-1", "connected", "2560x1440\n1920x1080\n"),
        ("card1-DP-2", "disconnected", ""),
        ("card1-eDP-1", "connected", "1920x1200\n"),
        ("card1-Writeback-1", "connected", "1x1\n"),
        ("version", "", ""),
    ] {
        let p = d.path().join(name);
        fs::create_dir_all(&p).unwrap();
        fs::write(p.join("status"), status).unwrap();
        fs::write(p.join("modes"), modes).unwrap();
    }
    let got: Vec<(String, u32, u32)> = setup::drm_monitors(d.path())
        .into_iter()
        .map(|m| (m.output, m.width, m.height))
        .collect();
    assert_eq!(
        got,
        vec![("DP-1".into(), 2560, 1440), ("eDP-1".into(), 1920, 1200)]
    );
    let h = setup::parse_hyprctl_monitors(
        r#"[{"name":"DP-1","width":2560,"height":1440,"refreshRate":59.951,"disabled":false},{"name":"DP-2","width":1,"height":1,"disabled":true}]"#,
    );
    assert_eq!(h.len(), 1);
    assert_eq!(h[0].mode(), "2560x1440@59.95");
}

#[test]
fn vectors_endpoint_is_merged_into_its_config() {
    let existing =
        "# mine\n[tools]\nhomelab = \"off\"\n\n[llm]\nmodel = \"old\"\napi_key_file = \"/k\"\n";
    let a = VectorAnswer {
        backend: "ollama".into(),
        base_url: None,
        api_key_file: None,
        model: Some("qwen3".into()),
    };
    let t = setup::vector_toml_text(existing, &a).unwrap();
    assert!(t.contains("# mine") && t.contains("homelab = \"off\""));
    assert!(t.contains(&format!("base_url = \"{}\"", setup::OLLAMA_URL)));
    assert!(t.contains("model = \"qwen3\"") && !t.contains("api_key_file"));
    let bad = VectorAnswer {
        backend: "openai".into(),
        base_url: Some("ftp://x".into()),
        api_key_file: None,
        model: None,
    };
    assert!(setup::vector_toml_text("", &bad).is_err());
    let none = VectorAnswer {
        backend: "none".into(),
        base_url: None,
        api_key_file: None,
        model: None,
    };
    assert!(
        !setup::vector_toml_text(&t, &none)
            .unwrap()
            .contains("base_url")
    );
}

#[test]
fn a_users_homelab_toml_is_kept_unless_replaced() {
    let (d, paths) = sandbox();
    let src = d.path().join("lab.toml");
    fs::write(&src, "[prometheus]\nurl = \"http://prom:9090\"\n").unwrap();
    let a = HomelabAnswer {
        file: Some(src.display().to_string()),
    };
    assert!(setup::apply_homelab(&paths, &a, false).ok);
    let dst = setup::homelab_toml(&paths);
    assert!(fs::read_to_string(&dst).unwrap().contains("prom:9090"));
    fs::write(&dst, "# mine\n").unwrap();
    assert!(
        setup::apply_homelab(&paths, &a, false)
            .detail
            .contains("kept")
    );
    assert_eq!(fs::read_to_string(&dst).unwrap(), "# mine\n");
    fs::write(&src, "not = [toml").unwrap();
    assert!(!setup::apply_homelab(&paths, &a, true).ok);
}

#[test]
fn answers_files_are_strict() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("a.toml");
    fs::write(
        &p,
        "[monitors]\nmode = \"auto\"\n[voice]\ntier = \"off\"\n[vector]\nbackend = \"none\"\n",
    )
    .unwrap();
    let a = setup::load_answers(&p).unwrap();
    assert_eq!(a.voice.unwrap().tier, "off");
    fs::write(&p, "[monitor]\nmode = \"auto\"\n").unwrap();
    assert!(
        setup::load_answers(&p).is_err(),
        "a misspelled section is an error, not ignored"
    );
}

#[test]
fn setup_accessibility_writes_the_settings_and_renders_the_theme() {
    let (_d, paths) = sandbox();
    let a = setup::Answers {
        accessibility: Some(setup::AccessibilityAnswer {
            motion: Some("still".into()),
            contrast: Some("high".into()),
        }),
        ..Default::default()
    };
    // no session in the sandbox: nothing is told, but the theme is rendered
    let done = setup::apply(&paths, &a, &[], &[], false, false);
    assert!(done[0].ok, "{}", done[0].detail);
    assert_eq!(done[0].section, "accessibility");
    let s = bromigos_core::accessibility::read(&paths);
    assert_eq!((s.motion.as_str(), s.contrast.as_str()), ("still", "high"));
    let pal =
        fs::read_to_string(paths.state_home.join("bromigos/theme/current/palette.json")).unwrap();
    let p: serde_json::Value = serde_json::from_str(&pal).unwrap();
    assert_eq!(p["contrast"]["mode"], "high");
    assert_eq!(p["motion"], "still");
    // recorded with the other answers; a bad value is refused and nothing written
    let rec = fs::read_to_string(setup::state_file(&paths)).unwrap();
    assert!(rec.contains("[accessibility]") && rec.contains("motion = \"still\""));
    let bad = setup::Answers {
        accessibility: Some(setup::AccessibilityAnswer {
            motion: Some("fast".into()),
            contrast: None,
        }),
        ..Default::default()
    };
    let done = setup::apply(&paths, &bad, &[], &[], false, false);
    assert!(!done[0].ok);
    assert_eq!(bromigos_core::accessibility::read(&paths).motion, "still");
}

#[test]
fn an_answers_file_takes_an_accessibility_section() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("a.toml");
    fs::write(&p, "[accessibility]\nmotion = \"reduced\"\n").unwrap();
    let a = setup::load_answers(&p).unwrap().accessibility.unwrap();
    assert_eq!(a.motion.as_deref(), Some("reduced"));
    assert_eq!(a.contrast, None);
    fs::write(&p, "[accessibility]\nmotions = \"reduced\"\n").unwrap();
    assert!(setup::load_answers(&p).is_err());
}
