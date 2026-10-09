//! Themes: rendering, the overlay order, the atomic swap and unknown names, in a temp
//! dir. Also renders the repository's own themes with its own templates.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use bromigos_core::paths::Paths;
use bromigos_core::theme::{self, Locations, ThemeError};

/// The repository root (themes/ and theme/templates/ live there).
fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

struct Sandbox {
    dir: tempfile::TempDir,
    share: PathBuf,
}

impl Sandbox {
    /// An empty share dir.
    fn new() -> Sandbox {
        let dir = tempfile::tempdir().unwrap();
        let share = dir.path().join("share");
        fs::create_dir_all(&share).unwrap();
        Sandbox { dir, share }
    }
    /// The share dir is the repository (as with BROMIGOS_SHARE_DIR=<checkout>).
    fn repo() -> Sandbox {
        let mut s = Sandbox::new();
        s.share = repo();
        s
    }
    fn paths(&self) -> Paths {
        let m: HashMap<&str, PathBuf> = [
            ("HOME", self.dir.path().join("home")),
            ("XDG_RUNTIME_DIR", self.dir.path().join("run")),
            ("BROMIGOS_SHARE_DIR", self.share.clone()),
        ]
        .into_iter()
        .collect();
        Paths::from_lookup(|k| m.get(k).cloned())
    }
    fn loc(&self) -> Locations {
        Locations::new(&self.paths())
    }
    fn put(&self, path: &Path, text: &str) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }
    fn system_theme(&self, name: &str, file: &str, text: &str) {
        self.put(&self.loc().system_themes.join(name).join(file), text);
    }
    fn user_theme(&self, name: &str, file: &str, text: &str) {
        self.put(&self.loc().user_themes.join(name).join(file), text);
    }
    fn template(&self, name: &str, text: &str) {
        self.put(&self.loc().system_templates.join(name), text);
    }
    fn current(&self, file: &str) -> String {
        fs::read_to_string(self.loc().current().join(file)).unwrap()
    }
}

const COLORS: &str = r##"
background = "#000500"
void = "background"
primary = "#39ff14"
warn_surface = "#4a3a0a"

[colors]
cyan = "#3fe0c5"

[terminal]
color6 = "cyan"
color8 = "terminal.color6"
"##;

// ------------------------------------------------------------------ rendering

#[test]
fn renders_roles_references_tables_and_filters() {
    let s = Sandbox::new();
    s.system_theme("t", "colors.toml", COLORS);
    s.system_theme("t", "theme.toml", "name = \"Tee\"\nmode = \"dark\"\n");
    s.template(
        "a.txt.tpl",
        "{{ theme }} {{ meta.name }} {{ void }} {{ primary | strip }} {{ primary | rgb }} \
         {{ warn_surface | kebab }} {{ terminal.color8 }}\n\
         {% for n, v in palette %}{{ n | kebab }}={{ v }};{% endfor %}\n",
    );
    let t = theme::load(&s.loc(), "t").unwrap();
    let out = theme::render(&t, &theme::templates(&s.loc()).unwrap()).unwrap();
    assert_eq!(out.len(), 1);
    assert_eq!(out[0].0, "a.txt");
    assert_eq!(
        out[0].1,
        "t Tee #000500 39ff14 57,255,20 #4a3a0a #3fe0c5\n\
         background=#000500;void=#000500;primary=#39ff14;warn-surface=#4a3a0a;cyan=#3fe0c5;\n"
    );
}

#[test]
fn an_unknown_name_in_a_template_is_an_error() {
    let s = Sandbox::new();
    s.system_theme("t", "colors.toml", COLORS);
    s.template("a.tpl", "{{ nope }}");
    let t = theme::load(&s.loc(), "t").unwrap();
    let e = theme::render(&t, &theme::templates(&s.loc()).unwrap()).unwrap_err();
    assert!(matches!(e, ThemeError::Template { .. }), "{e}");
}

#[test]
fn bad_colours_are_errors() {
    for (colors, why) in [
        ("a = \"#12345\"", "not a #rrggbb colour"),
        ("a = \"b\"\nb = \"a\"", "loop"),
        ("a = \"nothing\"", "no colour named"),
        ("a = \"#000000\"\n[colors]\na = \"#111111\"", "both a role"),
        ("a = 3", "a colour is a string"),
    ] {
        let s = Sandbox::new();
        s.system_theme("t", "colors.toml", colors);
        let e = theme::load(&s.loc(), "t").unwrap_err().to_string();
        assert!(e.contains(why), "{colors:?}: {e}");
    }
}

#[test]
fn the_repository_themes_render_with_every_template() {
    let s = Sandbox::repo();
    let loc = s.loc();
    let templates = theme::templates(&loc).unwrap();
    for name in [
        "waybar.css",
        "gtklock.css",
        "rofi.rasi",
        "kitty.conf",
        "dunst.conf",
        "hyprland.lua",
        "kde.colors",
        // the apps past the desktop (the Omarchy parity batch)
        "btop.theme",
        "tmux.conf",
        "nvim.lua",
        "chromium.theme",
        "userChrome.css",
    ] {
        assert!(templates.contains_key(name), "no template for {name}");
    }
    let names = theme::names(&loc);
    assert!(names.contains(&theme::DEFAULT_THEME.to_owned()));
    for name in names {
        let t = theme::load(&loc, &name).unwrap();
        theme::render(&t, &templates).unwrap();
    }
}

#[test]
fn wick_renders_the_values_the_desktop_had() {
    let s = Sandbox::repo();
    let t = theme::load(&s.loc(), "wick").unwrap();
    let out: HashMap<String, String> = theme::render(&t, &theme::templates(&s.loc()).unwrap())
        .unwrap()
        .into_iter()
        .collect();
    assert_eq!(t.meta.name, "Wick");
    assert_eq!(t.meta.mode, "dark");
    assert!(out["waybar.css"].contains("@define-color primary #39ff14;"));
    assert!(out["gtklock.css"].contains("@define-color panel #001300;"));
    assert!(out["rofi.rasi"].contains("selected-urgent-background: #4a3a0acc;"));
    assert!(out["hyprland.lua"].contains("inactive_border = \"rgba(003b00ee)\""));
    assert!(out["kitty.conf"].contains("color11 #f0d36a"));
    assert!(out["dunst.conf"].contains("background = \"#1a0503\""));
    assert!(out["kde.colors"].contains("BackgroundNormal=0,9,0"));
    // the apps past the desktop
    assert!(out["btop.theme"].contains("theme[main_bg]=\"#000500\""));
    assert!(out["btop.theme"].contains("theme[hi_fg]=\"#39ff14\""));
    assert!(out["tmux.conf"].contains("set -g pane-active-border-style \"fg=#39ff14\""));
    assert!(out["nvim.lua"].contains("primary = \"#39ff14\""));
    assert!(out["nvim.lua"].contains("vim.g.terminal_color_11 = \"#f0d36a\""));
    assert_eq!(out["chromium.theme"].trim(), "0,19,0");
    assert!(out["userChrome.css"].contains("--toolbar-bgcolor: #001300 !important;"));
}

// ------------------------------------------------------------------ overlay order

#[test]
fn the_users_theme_overlays_the_first_party_one() {
    let s = Sandbox::new();
    s.system_theme("t", "colors.toml", COLORS);
    s.system_theme(
        "t",
        "theme.toml",
        "name = \"Tee\"\ndescription = \"first\"\n",
    );
    s.system_theme("t", "extra.txt", "system");
    s.system_theme("t", "only-system.txt", "system");
    // the user changes one role and one table entry, and the description
    s.user_theme(
        "t",
        "colors.toml",
        "primary = \"#ff0000\"\n[terminal]\ncolor6 = \"#00ff00\"\n",
    );
    s.user_theme("t", "theme.toml", "description = \"mine\"\n");
    s.user_theme("t", "extra.txt", "user");
    s.template(
        "p.tpl",
        "{{ primary }} {{ background }} {{ terminal.color6 }} {{ terminal.color8 }}",
    );

    let t = theme::load(&s.loc(), "t").unwrap();
    assert_eq!(t.meta.name, "Tee");
    assert_eq!(t.meta.description, "mine");
    assert_eq!(t.colors.get("primary"), Some("#ff0000"));
    assert_eq!(t.colors.get("background"), Some("#000500"));

    theme::set(&s.paths(), "t").unwrap();
    // color8 points at color6, so it follows the user's value
    assert_eq!(s.current("p"), "#ff0000 #000500 #00ff00 #00ff00");
    assert_eq!(s.current("extra.txt"), "user");
    assert_eq!(s.current("only-system.txt"), "system");
    // the merged colors.toml, not the user's fragment
    let merged = s.current("colors.toml");
    assert!(merged.contains("#ff0000") && merged.contains("background"));
}

#[test]
fn a_user_only_theme_is_listed_and_sets() {
    let s = Sandbox::new();
    s.system_theme("a", "colors.toml", COLORS);
    s.user_theme("b", "colors.toml", "primary = \"#123456\"\n");
    s.template("p.tpl", "{{ primary }}");
    let list = theme::list(&s.paths());
    let rows: Vec<(String, Vec<&str>)> = list
        .iter()
        .map(|t| (t.name.clone(), t.sources.clone()))
        .collect();
    assert_eq!(
        rows,
        vec![
            ("a".to_owned(), vec!["system"]),
            ("b".to_owned(), vec!["user"])
        ]
    );
    theme::set(&s.paths(), "b").unwrap();
    assert_eq!(s.current("p"), "#123456");
}

#[test]
fn user_templates_replace_first_party_ones_and_theme_files_win() {
    let s = Sandbox::new();
    s.system_theme("t", "colors.toml", COLORS);
    s.system_theme("t", "hand.conf", "written by hand");
    s.template("x.tpl", "system {{ primary }}");
    s.template("hand.conf.tpl", "from the template");
    s.put(&s.loc().user_templates.join("x.tpl"), "user {{ primary }}");
    let r = theme::set(&s.paths(), "t").unwrap();
    assert_eq!(s.current("x"), "user #39ff14");
    assert_eq!(s.current("hand.conf"), "written by hand");
    assert_eq!(r.rendered, vec!["x"]);
    assert_eq!(r.from_theme, vec!["hand.conf"]);
}

// ------------------------------------------------------------------ the swap

#[test]
fn set_swaps_the_whole_directory_and_names_the_theme() {
    let s = Sandbox::new();
    s.system_theme("one", "colors.toml", "primary = \"#111111\"");
    s.system_theme("one", "only-in-one.txt", "1");
    s.system_theme("two", "colors.toml", "primary = \"#222222\"");
    s.template("p.tpl", "{{ primary }}");
    let paths = s.paths();

    assert_eq!(
        theme::current(&paths),
        theme::Current {
            name: "wick".into(),
            set: false,
            dir: s.loc().current()
        }
    );
    theme::set(&paths, "one").unwrap();
    assert_eq!(s.current("p"), "#111111");
    assert_eq!(s.current("name"), "one\n");
    // the exchange path: current/ exists
    let r = theme::set(&paths, "two").unwrap();
    assert_eq!(r.dir, s.loc().current());
    assert_eq!(s.current("p"), "#222222");
    assert!(
        !s.loc().current().join("only-in-one.txt").exists(),
        "old files are gone"
    );
    let cur = theme::current(&paths);
    assert!(cur.set);
    assert_eq!(cur.name, "two");
    // nothing left over beside current/ and the lock
    let mut left: Vec<String> = fs::read_dir(&s.loc().state)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    left.sort();
    assert_eq!(left, vec![".lock", "current"]);
}

#[test]
fn swap_into_place_exchanges_and_handles_a_missing_or_odd_target() {
    let d = tempfile::tempdir().unwrap();
    let (staging, current) = (d.path().join(".staging-1"), d.path().join("current"));
    // nothing there yet
    fs::create_dir(&staging).unwrap();
    fs::write(staging.join("f"), "new").unwrap();
    theme::swap_into_place(&staging, &current).unwrap();
    assert_eq!(fs::read_to_string(current.join("f")).unwrap(), "new");
    assert!(!staging.exists());
    // a directory there: exchanged, the old one removed
    fs::create_dir(&staging).unwrap();
    fs::write(staging.join("g"), "newer").unwrap();
    theme::swap_into_place(&staging, &current).unwrap();
    assert_eq!(fs::read_to_string(current.join("g")).unwrap(), "newer");
    assert!(!current.join("f").exists());
    assert!(!staging.exists());
    // a stray file there
    fs::remove_dir_all(&current).unwrap();
    fs::write(&current, "stray").unwrap();
    fs::create_dir(&staging).unwrap();
    theme::swap_into_place(&staging, &current).unwrap();
    assert!(current.is_dir());
}

#[test]
fn a_failed_set_leaves_the_current_theme_alone() {
    let s = Sandbox::new();
    s.system_theme("good", "colors.toml", "primary = \"#111111\"");
    s.system_theme("bad", "colors.toml", "primary = \"#111111\"");
    s.template(
        "p.tpl",
        "{{ primary }}{% if theme == 'bad' %}{{ missing }}{% endif %}",
    );
    theme::set(&s.paths(), "good").unwrap();
    assert!(theme::set(&s.paths(), "bad").is_err());
    assert_eq!(s.current("p"), "#111111");
    assert_eq!(s.current("name"), "good\n");
}

// ------------------------------------------------------------------ unknown names

#[test]
fn unknown_and_bad_names_write_nothing() {
    let s = Sandbox::new();
    s.system_theme("wick", "colors.toml", COLORS);
    match theme::set(&s.paths(), "nope") {
        Err(ThemeError::Unknown { name, available }) => {
            assert_eq!(name, "nope");
            assert_eq!(available, vec!["wick"]);
        }
        other => panic!("{other:?}"),
    }
    for bad in ["../wick", "Wick", "", "-x", "a/b", "."] {
        assert!(
            matches!(theme::set(&s.paths(), bad), Err(ThemeError::BadName(_))),
            "{bad:?}"
        );
    }
    assert!(!s.loc().state.exists(), "nothing written");
}

// ------------------------------------------------------------------ worlds

#[test]
fn set_brings_a_worlds_art_and_live_files_into_current() {
    let s = Sandbox::new();
    s.system_theme("w", "colors.toml", COLORS);
    s.system_theme("w", "backgrounds/README.md", "about the art");
    s.system_theme("w", "backgrounds/layers/00-sky.webp", "sky");
    s.system_theme("w", "backgrounds/layers/30-water.webp", "water");
    s.system_theme("w", "live/world.toml", "name = \"w\"\n");
    s.system_theme("w", "live/actors/heron.webp", "heron");
    s.system_theme("w", "live/actors/sleeper/00.webp", "frame 0");
    s.system_theme("w", "live/actors/sleeper/01.webp", "frame 1");
    // the art pipeline's recipe, log and sources stay behind
    s.system_theme("w", "art.toml", "format = 1\n");
    s.system_theme("w", "art.log.jsonl", "");
    s.system_theme("w", "art/comps/comp.png", "source");
    s.system_theme("w", "live/art/keep.webp", "a folder named art deeper down");
    // the user repaints one actor frame and keeps the rest
    s.user_theme("w", "live/actors/sleeper/01.webp", "my frame 1");
    s.template("p.tpl", "{{ primary }}");
    theme::set(&s.paths(), "w").unwrap();
    assert_eq!(s.current("backgrounds/layers/00-sky.webp"), "sky");
    assert_eq!(s.current("backgrounds/layers/30-water.webp"), "water");
    assert_eq!(s.current("live/world.toml"), "name = \"w\"\n");
    assert_eq!(s.current("live/actors/heron.webp"), "heron");
    assert_eq!(s.current("live/actors/sleeper/00.webp"), "frame 0");
    assert_eq!(s.current("live/actors/sleeper/01.webp"), "my frame 1");
    assert!(!s.loc().current().join("backgrounds/README.md").exists());
    for f in ["art.toml", "art.log.jsonl", "art"] {
        assert!(!s.loc().current().join(f).exists(), "{f} was copied");
    }
    assert_eq!(
        s.current("live/art/keep.webp"),
        "a folder named art deeper down"
    );

    // back to a theme without a world: its live/ and backgrounds/ are gone
    s.system_theme("plain", "colors.toml", COLORS);
    s.system_theme("plain", "live/README.md", "reserved");
    theme::set(&s.paths(), "plain").unwrap();
    assert!(!s.loc().current().join("live").exists());
    assert!(!s.loc().current().join("backgrounds").exists());
}

#[test]
fn the_repository_worlds_ship_their_world_and_layers() {
    let root = repo().join("themes");
    for world in ["mire", "tidewell"] {
        let dir = root.join(world);
        let w = fs::read_to_string(dir.join("live/world.toml")).unwrap();
        let doc: toml_edit::DocumentMut = w.parse().unwrap();
        // every file the world names is in the theme
        let layers = doc["layers"].as_array_of_tables().unwrap();
        assert!(!layers.is_empty(), "{world}: no layers");
        for l in layers.iter() {
            let f = l["file"].as_str().unwrap();
            assert!(dir.join(f).is_file(), "{world}: missing {f}");
        }
        let actors = doc["actors"].as_array_of_tables().unwrap();
        assert!(
            actors.iter().any(|a| a["kind"].as_str() == Some("keeper")),
            "{world}: every world has a keeper"
        );
        for a in actors.iter() {
            // a flyby draws one of its craft each pass; every other actor has one sprite
            let sprites: Vec<&str> = match a.get("craft").and_then(|c| c.as_array_of_tables()) {
                Some(craft) => craft
                    .iter()
                    .map(|c| c["sprite"].as_str().unwrap())
                    .collect(),
                None => vec![a["sprite"].as_str().unwrap()],
            };
            assert!(!sprites.is_empty(), "{world}: an actor with no sprite");
            for sprite in sprites {
                let p = dir.join(sprite);
                assert!(
                    p.is_file() || p.with_extension("webp").is_file() || p.is_dir(),
                    "{world}: missing sprite {sprite}"
                );
            }
        }
    }
}

#[test]
fn the_live_layer_hears_about_a_new_theme() {
    use std::io::{Read, Write};
    use std::os::unix::net::UnixListener;
    let s = Sandbox::new();
    let paths = s.paths();
    // not running: fine, it notices by itself
    let r = theme::reload_live(&paths);
    assert!(r.ok);
    assert_eq!(r.detail.as_deref(), Some("not running"));

    fs::create_dir_all(&paths.runtime_dir).unwrap();
    let srv = UnixListener::bind(paths.live_socket()).unwrap();
    let t = std::thread::spawn(move || {
        let (mut c, _) = srv.accept().unwrap();
        let mut b = [0u8; 64];
        let n = c.read(&mut b).unwrap();
        let cmd = String::from_utf8_lossy(&b[..n]).into_owned();
        c.write_all(b"world mire").unwrap();
        cmd
    });
    let r = theme::reload_live(&paths);
    assert_eq!(t.join().unwrap(), "theme");
    assert!(r.ok);
    assert_eq!(r.detail.as_deref(), Some("world mire"));
}

// ------------------------------------------------------------------ palette.json

#[test]
fn set_writes_the_resolved_palette_for_runtime_readers() {
    let s = Sandbox::new();
    s.system_theme("one", "colors.toml", COLORS);
    s.system_theme(
        "one",
        "theme.toml",
        "name = \"One\"\ndescription = \"d\"\nmode = \"dark\"\n",
    );
    theme::set(&s.paths(), "one").unwrap();
    let p: serde_json::Value = serde_json::from_str(&s.current("palette.json")).unwrap();
    assert_eq!(p["schema"], 1);
    assert_eq!(p["theme"], "one");
    assert_eq!(p["name"], "One");
    assert_eq!(p["mode"], "dark");
    assert_eq!(p["colors"]["void"], "#000500", "references resolved");
    assert_eq!(
        p["colors"]["cyan"], "#3fe0c5",
        "[colors] names sit with the roles"
    );
    assert_eq!(p["tables"]["terminal"]["color8"], "#3fe0c5");
}

#[test]
fn every_repository_theme_has_the_runtime_roles() {
    // the widgets, VECTOR and the live layer's decks read these from palette.json
    let s = Sandbox::repo();
    for name in theme::names(&s.loc()) {
        let t = theme::load(&s.loc(), &name).unwrap();
        let p: serde_json::Value = serde_json::from_str(&theme::palette_json(&t)).unwrap();
        for role in [
            "background",
            "void",
            "panel",
            "selection",
            "primary",
            "soft",
            "dim",
            "text",
            "muted",
            "faint",
            "warn",
            "danger",
            "cyan",
            "gold",
            "white",
            "rust",
        ] {
            assert!(p["colors"][role].is_string(), "{name}: no {role}");
        }
        for (table, keys) in [
            ("holo", &["line", "glow", "label", "highlight"][..]),
            (
                "widgets",
                &["frame", "header", "value", "graph", "track"][..],
            ),
        ] {
            for k in keys {
                assert!(p["tables"][table][k].is_string(), "{name}: no {table}.{k}");
            }
        }
    }
}

// ------------------------------------------------------------------ accessibility

fn a11y(s: &Sandbox, text: &str) {
    s.put(
        &s.paths().user_config_dir().join("accessibility.toml"),
        text,
    );
}

#[test]
fn high_contrast_renders_every_repository_theme_to_its_targets() {
    use bromigos_core::accessibility::{self, QUIET, TEXT, UI};
    let s = Sandbox::repo();
    a11y(&s, "contrast = \"high\"\nmotion = \"reduced\"\n");
    for name in theme::names(&s.loc()) {
        let r = theme::set(&s.paths(), &name).unwrap();
        assert_eq!(r.contrast.mode, "high");
        assert!(
            r.contrast.ok,
            "{name}: {:?}",
            r.contrast
                .checks
                .iter()
                .filter(|c| !c.ok)
                .collect::<Vec<_>>()
        );
        let p: serde_json::Value = serde_json::from_str(&s.current("palette.json")).unwrap();
        assert_eq!(p["contrast"]["mode"], "high", "{name}");
        assert_eq!(p["contrast"]["ok"], true, "{name}");
        assert_eq!(p["motion"], "reduced", "{name}");
        // the pairs the apps draw, measured on what palette.json says
        let c = |k: &str| p["colors"][k].as_str().unwrap().to_owned();
        for fg in ["text", "soft", "primary", "warn", "danger"] {
            for bg in ["background", "panel"] {
                assert!(
                    accessibility::ratio(&c(fg), &c(bg)) >= TEXT,
                    "{name}: {fg} on {bg}"
                );
            }
        }
        for fg in ["dim", "muted", "faint"] {
            assert!(
                accessibility::ratio(&c(fg), &c("panel")) >= QUIET,
                "{name}: {fg}"
            );
        }
        assert!(
            accessibility::ratio(&c("selection"), &c("panel")) >= UI,
            "{name}: selection"
        );
        let term = &p["tables"]["terminal"];
        let tbg = term["background"].as_str().unwrap();
        for i in 1..16 {
            let fg = term[format!("color{i}")].as_str().unwrap();
            assert!(
                accessibility::ratio(fg, tbg) >= QUIET,
                "{name}: terminal color{i}"
            );
        }
        // hues are kept: warn stays amber-ish, danger red-ish
        let t = theme::load(&s.loc(), &name).unwrap();
        for k in ["warn", "danger", "primary"] {
            let (h0, c0) = accessibility::hue_chroma(t.colors.get(k).unwrap());
            let (h1, c1) = accessibility::hue_chroma(&c(k));
            if c0 > 0.05 && c1 > 0.03 {
                let d = ((h0 - h1 + 540.0) % 360.0 - 180.0).abs();
                assert!(d < 25.0, "{name}: {k} hue {h0:.0} -> {h1:.0}");
            }
        }
        // the outputs: opaque layers, solid borders, the settings for Hyprland
        let rofi = s.current("rofi.rasi");
        assert!(rofi.contains("high contrast"), "{name}");
        assert!(
            rofi.contains(&format!("selected-background: {};", c("selection"))),
            "{name}: opaque"
        );
        assert!(s.current("kitty.conf").contains("background_opacity 1.0"));
        assert!(s.current("dunst.conf").contains("frame_width = 2"));
        let hl = s.current("hyprland.lua");
        assert!(hl.contains("motion   = \"reduced\"") && hl.contains("contrast = \"high\""));
        assert!(hl.contains("border_size     = 3"));
        assert!(
            s.current("waybar.css")
                .contains("window#waybar:not(.bromigos-a11y)")
        );
    }
}

#[test]
fn normal_contrast_leaves_the_themes_colours_and_outputs_alone() {
    let s = Sandbox::repo();
    let t = theme::load(&s.loc(), "mire").unwrap();
    for text in ["", "contrast = \"normal\"\n"] {
        a11y(&s, text);
        let r = theme::set(&s.paths(), "mire").unwrap();
        assert_eq!(r.contrast.mode, "normal");
        assert_eq!(r.motion, "full");
        let p: serde_json::Value = serde_json::from_str(&s.current("palette.json")).unwrap();
        for (k, v) in &t.colors.palette {
            assert_eq!(p["colors"][k], v.as_str(), "{k}");
        }
        assert_eq!(p["contrast"]["mode"], "normal");
        assert_eq!(p["motion"], "full");
        let rofi = s.current("rofi.rasi");
        assert!(rofi.contains("translucent layers") && !rofi.contains("high contrast"));
        assert!(!s.current("kitty.conf").contains("background_opacity"));
        assert!(!s.current("waybar.css").contains(":not(.bromigos-a11y)"));
        assert!(s.current("hyprland.lua").contains("motion   = \"full\""));
    }
    // a bad value is the default, not an error: the theme still renders
    a11y(&s, "contrast = \"loud\"\n");
    assert_eq!(
        theme::set(&s.paths(), "mire").unwrap().contrast.mode,
        "normal"
    );
}

#[test]
fn high_contrast_maps_the_wicks_own_icon_colours() {
    // the bar's icons are drawn in the Wick's colours; under high contrast the Wick itself
    // maps them to its high-contrast ones (its icons happen to use only colours that already
    // contrast, so they come out the same)
    use bromigos_core::accessibility;
    let s = Sandbox::repo();
    let mut t = theme::load(&s.loc(), "wick").unwrap();
    let panel = t.colors.get("panel").unwrap().to_ascii_lowercase();
    t.colors = accessibility::high_contrast(&t.colors);
    let m = theme::wick_map(&s.loc(), &t);
    assert_eq!(m.get(&panel).map(String::as_str), t.colors.get("panel"));
    assert_ne!(m.get(&panel), Some(&panel));
}

// ------------------------------------------------------------------ icons

#[test]
fn recolour_swaps_only_the_mapped_colours() {
    let mut m = std::collections::BTreeMap::new();
    m.insert("#39ff14".to_owned(), "#b8e05a".to_owned());
    let svg = r##"<svg stroke="#39FF14" fill="#000000" color="#39ff14"/><a href="#x"/>#39ff1"##;
    assert_eq!(
        theme::recolour(svg, &m),
        r##"<svg stroke="#b8e05a" fill="#000000" color="#b8e05a"/><a href="#x"/>#39ff1"##
    );
    assert_eq!(theme::recolour(svg, &Default::default()), svg);
}

#[test]
fn set_draws_the_icons_in_the_themes_colours() {
    let s = Sandbox::new();
    s.system_theme(
        "wick",
        "colors.toml",
        "primary = \"#39ff14\"\nwarn = \"#d4af37\"",
    );
    s.system_theme(
        "one",
        "colors.toml",
        "primary = \"#111111\"\nwarn = \"#222222\"",
    );
    s.system_theme(
        "two",
        "colors.toml",
        "primary = \"#333333\"\nwarn = \"#444444\"",
    );
    s.system_theme("two", "icons/cpu.svg", "its own");
    let icons = s.loc().system_icons;
    s.put(&icons.join("cpu.svg"), "<svg stroke=\"#39ff14\"/>");
    s.put(&icons.join("cpu-amber.svg"), "<svg stroke=\"#d4af37\"/>");
    s.put(&icons.join("notes.txt"), "#39ff14");

    let r = theme::set(&s.paths(), "wick").unwrap();
    assert_eq!(r.icons, vec!["cpu-amber.svg", "cpu.svg"]);
    assert_eq!(
        s.current("icons/cpu.svg"),
        "<svg stroke=\"#39ff14\"/>",
        "the Wick: as drawn"
    );
    theme::set(&s.paths(), "one").unwrap();
    assert_eq!(s.current("icons/cpu.svg"), "<svg stroke=\"#111111\"/>");
    assert_eq!(
        s.current("icons/cpu-amber.svg"),
        "<svg stroke=\"#222222\"/>"
    );
    assert!(
        !s.loc().current().join("icons/notes.txt").exists(),
        "svg only"
    );
    let r = theme::set(&s.paths(), "two").unwrap();
    assert_eq!(
        s.current("icons/cpu.svg"),
        "its own",
        "a theme's own icon wins"
    );
    assert_eq!(r.icons, vec!["cpu-amber.svg"]);
}

#[test]
fn every_repository_theme_recolours_the_bar_icons() {
    let s = Sandbox::repo();
    let loc = s.loc();
    let icons = theme::icons(&loc).unwrap();
    assert!(icons.contains_key("cpu.svg") && icons.contains_key("emblem.svg"));
    for name in theme::names(&loc) {
        let t = theme::load(&loc, &name).unwrap();
        let map = theme::wick_map(&loc, &t);
        let cpu = theme::recolour(&fs::read_to_string(&icons["cpu.svg"]).unwrap(), &map);
        let primary = t.colors.get("primary").unwrap().to_ascii_lowercase();
        assert!(cpu.contains(&primary), "{name}: cpu.svg in {primary}");
    }
}

// ------------------------------------------------------------------ hooks

#[test]
fn theme_set_hooks_run_in_order_with_the_theme() {
    use std::os::unix::fs::PermissionsExt;
    let s = Sandbox::new();
    s.system_theme("one", "colors.toml", "primary = \"#111111\"");
    let paths = s.paths();
    assert!(
        theme::run_hooks(&paths).is_none(),
        "no hooks, nothing to report"
    );
    let dir = paths.user_config_dir().join("hooks/theme-set.d");
    let log = s.dir.path().join("log");
    let hook = |name: &str, body: &str, exec: bool| {
        let p = dir.join(name);
        s.put(&p, &format!("#!/bin/sh\n{body}\n"));
        let mode = if exec { 0o755 } else { 0o644 };
        fs::set_permissions(&p, fs::Permissions::from_mode(mode)).unwrap();
    };
    let l = log.display();
    hook("20-b", &format!("echo b $1 >> {l}"), true);
    hook(
        "10-a",
        &format!("echo a $BROMIGOS_THEME $(basename $BROMIGOS_THEME_DIR) >> {l}"),
        true,
    );
    hook("30-off", &format!("echo off >> {l}"), false);
    theme::set(&paths, "one").unwrap();
    let r = theme::run_hooks(&paths).unwrap();
    assert!(r.ok, "{:?}", r.detail);
    assert_eq!(fs::read_to_string(&log).unwrap(), "a one current\nb one\n");
    hook("40-fails", "echo nope >&2; exit 3", true);
    let r = theme::run_hooks(&paths).unwrap();
    assert!(!r.ok);
    assert_eq!(r.detail.as_deref(), Some("40-fails: nope"));
}

#[test]
fn packaged_hooks_run_and_a_users_hook_of_the_same_name_replaces_one() {
    use std::os::unix::fs::PermissionsExt;
    let s = Sandbox::new();
    s.system_theme("one", "colors.toml", "primary = \"#111111\"");
    let paths = s.paths();
    let log = s.dir.path().join("log");
    let l = log.display();
    let put = |dir: &std::path::Path, name: &str, body: &str, exec: bool| {
        let p = dir.join(name);
        s.put(&p, &format!("#!/bin/sh\n{body}\n"));
        let mode = if exec { 0o755 } else { 0o644 };
        fs::set_permissions(&p, fs::Permissions::from_mode(mode)).unwrap();
    };
    let system = paths.share_dir.join("hooks/theme-set.d");
    let user = paths.user_config_dir().join("hooks/theme-set.d");
    put(&system, "emblem", &format!("echo sys-emblem >> {l}"), true);
    put(&system, "gtk", &format!("echo sys-gtk >> {l}"), true);
    put(
        &system,
        "wallpaper",
        &format!("echo sys-wallpaper >> {l}"),
        true,
    );
    put(&user, "gtk", &format!("echo user-gtk >> {l}"), true); // replaces the packaged gtk
    put(&user, "wallpaper", "exit 0", false); // a non-executable file switches one off
    put(&user, "zz-mine", &format!("echo mine >> {l}"), true);
    theme::set(&paths, "one").unwrap();
    let r = theme::run_hooks(&paths).unwrap();
    assert!(r.ok, "{:?}", r.detail);
    assert_eq!(
        fs::read_to_string(&log).unwrap(),
        "sys-emblem\nuser-gtk\nmine\n"
    );
}

#[test]
fn the_bar_emblem_is_the_themes_own_when_it_has_one() {
    assert_eq!(
        theme::svg_size(
            "<?xml?>\n<svg\n   width=\"1000\"\n   height=\"1000\" stroke-width=\"2\" viewBox=\"0 0 9 9\"><g width=\"5\"/></svg>",
            48
        ),
        "<?xml?>\n<svg\n   width=\"48\"\n   height=\"48\" stroke-width=\"2\" viewBox=\"0 0 9 9\"><g width=\"5\"/></svg>"
    );
    assert_eq!(
        theme::svg_size("<svg viewBox=\"0 0 9 9\"/>", 48),
        "<svg height=\"48\" width=\"48\" viewBox=\"0 0 9 9\"/>"
    );
    let s = Sandbox::new();
    s.system_theme("wick", "colors.toml", "primary = \"#39ff14\"");
    s.system_theme("one", "colors.toml", "primary = \"#111111\"");
    s.system_theme("two", "colors.toml", "primary = \"#222222\"");
    s.system_theme(
        "two",
        "emblem/emblem-small.svg",
        "<svg width=\"1000\" height=\"1000\"><b/></svg>",
    );
    s.put(
        &s.loc().system_icons.join("emblem.svg"),
        "<svg width=\"48\" height=\"48\" fill=\"#39ff14\"/>",
    );
    theme::set(&s.paths(), "one").unwrap();
    assert_eq!(
        s.current("icons/emblem.svg"),
        "<svg width=\"48\" height=\"48\" fill=\"#111111\"/>",
        "the Wick's, tinted"
    );
    theme::set(&s.paths(), "two").unwrap();
    assert_eq!(
        s.current("icons/emblem.svg"),
        "<svg width=\"48\" height=\"48\"><b/></svg>",
        "its own, at bar size"
    );
    assert!(
        s.loc().current().join("emblem/emblem-small.svg").is_file(),
        "emblem/ comes along"
    );
}
