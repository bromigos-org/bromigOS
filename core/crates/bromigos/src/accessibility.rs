//! `bromigos accessibility` (alias `a11y`): reduced motion and high contrast
//! (docs/accessibility.md). The settings are the user's, in
//! `~/.config/bromigos/accessibility.toml`; this writes them and makes them take effect:
//! the current theme is rendered again (high contrast is a transform of its colours; the
//! motion setting goes into its `hyprland.lua` and `palette.json`), then the running pieces
//! are told, as `bromigos theme set` tells them, but only inside a live session: with no
//! session found nothing is signalled or restarted.

use anyhow::Result;
use bromigos_core::accessibility::{self, Settings};
use bromigos_core::ipc::{self, IpcError};
use bromigos_core::paths::Paths;
use bromigos_core::session;
use bromigos_core::theme::{self, Reload};
use clap::{Args, Subcommand, ValueEnum};
use serde_json::{Value, json};

use crate::SCHEMA;

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum Motion {
    /// Everything moves as designed
    Full,
    /// Calmer and slower: no parallax, flicker, flashes or static; window animations fade
    Reduced,
    /// The live background holds a still frame; no window animations
    Still,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum Contrast {
    /// The theme's own colours
    Normal,
    /// Every colour the theme renders raised to WCAG AAA (text 7:1), panels opaque
    High,
}

#[derive(Subcommand, Debug)]
pub enum Verb {
    /// The settings and how the current theme's colours measure (the default)
    Status,
    /// How much the desktop moves: full, reduced or still
    Motion {
        #[arg(value_enum)]
        level: Motion,
        /// Write the setting and render the theme, but tell no running app
        #[arg(long)]
        no_reload: bool,
    },
    /// The colours' contrast: normal or high
    Contrast {
        #[arg(value_enum)]
        level: Contrast,
        /// Write the setting and render the theme, but tell no running app
        #[arg(long)]
        no_reload: bool,
    },
    /// Measure a theme's colours, normal and high contrast, against high contrast's targets
    Check {
        /// The theme (default: the current one)
        theme: Option<String>,
    },
}

#[derive(Args, Debug)]
pub struct AccessibilityArgs {
    #[command(subcommand)]
    verb: Option<Verb>,
    /// Print the JSON document (schema in core/README.md)
    #[arg(long, global = true)]
    json: bool,
}

fn settings_json(paths: &Paths) -> Value {
    let l = accessibility::load(paths);
    json!({"motion": l.settings.motion, "contrast": l.settings.contrast, "path": l.path,
           "exists": l.exists, "problems": l.problems})
}

/// The current theme rendered again with the settings, then (in a live session, unless
/// `no_reload`) the apps told: everything `theme set` tells for contrast; Hyprland, the
/// live layer and GTK's animation switch for motion.
fn apply(paths: &Paths, contrast_changed: bool, no_reload: bool) -> (Value, Vec<Reload>, bool) {
    let cur = theme::current(paths);
    let rendered = match theme::set(paths, &cur.name) {
        Ok(r) => json!({"name": r.name, "motion": r.motion, "contrast": r.contrast}),
        Err(e) => {
            return (
                json!({"name": cur.name, "error": e.to_string()}),
                vec![],
                false,
            );
        }
    };
    let mut reloads = vec![];
    if no_reload {
        return (rendered, reloads, true);
    }
    let Some(sess) = session::discover(paths).session else {
        reloads.push(Reload {
            app: "desktop",
            action: "nothing told",
            pids: vec![],
            ok: true,
            detail: Some("no running session: it takes effect at the next login".into()),
        });
        return (rendered, reloads, true);
    };
    if contrast_changed {
        reloads = theme::reload(paths);
    } else {
        let r = std::process::Command::new("hyprctl")
            .arg("reload")
            .envs(sess.env())
            .stdin(std::process::Stdio::null())
            .output();
        let out = r
            .as_ref()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_owned())
            .unwrap_or_default();
        reloads.push(Reload {
            app: "hyprland",
            action: "hyprctl reload",
            pids: vec![sess.pid],
            ok: out == "ok",
            detail: (out != "ok").then(|| {
                r.err()
                    .map(|e| e.to_string())
                    .unwrap_or_else(|| out.clone())
            }),
        });
        reloads.push(live_reload(paths));
    }
    let motion = accessibility::read(paths).motion;
    reloads.push(gtk_animations(&sess, motion == "full"));
    let ok = reloads.iter().all(|r| r.ok);
    (rendered, reloads, ok)
}

/// The live layer reads the setting again now (it also notices the file by itself within
/// a few seconds).
fn live_reload(paths: &Paths) -> Reload {
    let mut r = Reload {
        app: "live",
        action: "reload (its motion)",
        pids: vec![],
        ok: true,
        detail: None,
    };
    match ipc::live(paths, "reload") {
        Ok(_) => {}
        Err(IpcError::NotRunning(_)) => r.detail = Some("not running".into()),
        Err(e) => {
            r.ok = false;
            r.detail = Some(e.to_string());
        }
    }
    r
}

/// GTK apps' own animations follow the setting (org.gnome.desktop.interface
/// enable-animations, which GTK reads through the settings portal).
fn gtk_animations(sess: &session::Session, on: bool) -> Reload {
    let r = std::process::Command::new("gsettings")
        .args([
            "set",
            "org.gnome.desktop.interface",
            "enable-animations",
            if on { "true" } else { "false" },
        ])
        .envs(sess.env())
        .stdin(std::process::Stdio::null())
        .output();
    Reload {
        app: "gtk",
        action: "enable-animations",
        pids: vec![],
        ok: true,
        detail: match r {
            Ok(o) if o.status.success() => None,
            Ok(o) => Some(String::from_utf8_lossy(&o.stderr).trim().to_owned()),
            Err(_) => Some("gsettings isn't installed".into()),
        },
    }
}

fn print_reloads(reloads: &[Reload]) {
    for r in reloads {
        println!(
            "  {:<9} {}{}{}",
            r.app,
            r.action,
            if r.ok { "" } else { ": FAILED" },
            r.detail
                .as_deref()
                .map(|d| format!(" [{d}]"))
                .unwrap_or_default()
        );
    }
}

fn print_report(label: &str, r: &accessibility::Report) {
    let low = r
        .lowest
        .as_ref()
        .map(|c| {
            format!(
                "lowest {} on {} {:.2}:1 (wants {:.1})",
                c.fg, c.bg, c.ratio, c.min
            )
        })
        .unwrap_or_default();
    let fails = r.checks.iter().filter(|c| !c.ok).count();
    println!(
        "  {label:<7} {}  {low}",
        if r.ok {
            "meets every target".to_owned()
        } else {
            format!("{fails} of {} pairs short", r.checks.len())
        }
    );
}

pub fn accessibility_cmd(paths: &Paths, a: AccessibilityArgs) -> Result<i32> {
    match a.verb.unwrap_or(Verb::Status) {
        Verb::Status => {
            let cur = theme::current(paths);
            let loc = theme::Locations::new(paths);
            let measured = theme::load(&loc, &cur.name).ok().map(|t| {
                let s = accessibility::read(paths);
                let colors = if s.high_contrast() {
                    accessibility::high_contrast(&t.colors)
                } else {
                    t.colors
                };
                accessibility::report(&colors, &s.contrast)
            });
            if a.json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "accessibility": settings_json(paths),
                           "theme": cur.name, "contrast": measured})
                );
            } else {
                let l = accessibility::load(paths);
                println!("motion    {}", l.settings.motion);
                println!("contrast  {}", l.settings.contrast);
                println!(
                    "file      {}{}",
                    l.path.display(),
                    if l.exists {
                        ""
                    } else {
                        " (not yet: the defaults)"
                    }
                );
                for p in &l.problems {
                    println!("problem   {p}");
                }
                if let Some(r) = &measured {
                    println!("theme     {}", cur.name);
                    print_report("colours", r);
                }
            }
            Ok(0)
        }
        Verb::Check { theme: name } => {
            let loc = theme::Locations::new(paths);
            let name = name.unwrap_or_else(|| theme::current(paths).name);
            let t = match theme::load(&loc, &name) {
                Ok(t) => t,
                Err(e) => {
                    eprintln!("bromigos accessibility: {e}");
                    return Ok(1);
                }
            };
            let normal = accessibility::report(&t.colors, "normal");
            let high = accessibility::report(&accessibility::high_contrast(&t.colors), "high");
            if a.json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "theme": name, "normal": normal, "high": high})
                );
            } else {
                println!("{name}");
                print_report("normal", &normal);
                print_report("high", &high);
                for c in high.checks.iter().filter(|c| !c.ok) {
                    println!(
                        "    high: {} on {} {:.2}:1 < {:.1}",
                        c.fg, c.bg, c.ratio, c.min
                    );
                }
            }
            Ok(if high.ok { 0 } else { 1 })
        }
        Verb::Motion { level, no_reload } => {
            let v = match level {
                Motion::Full => "full",
                Motion::Reduced => "reduced",
                Motion::Still => "still",
            };
            change(paths, Some(v), None, no_reload, a.json)
        }
        Verb::Contrast { level, no_reload } => {
            let v = match level {
                Contrast::Normal => "normal",
                Contrast::High => "high",
            };
            change(paths, None, Some(v), no_reload, a.json)
        }
    }
}

/// Writes a setting and applies it (also `bromigos setup accessibility`'s path, through
/// bromigos_core::setup).
fn change(
    paths: &Paths,
    motion: Option<&str>,
    contrast: Option<&str>,
    no_reload: bool,
    json_out: bool,
) -> Result<i32> {
    let before: Settings = accessibility::read(paths);
    let after = match accessibility::write(paths, motion, contrast) {
        Ok(s) => s,
        Err(e) => {
            if json_out {
                println!("{}", json!({"schema": SCHEMA, "ok": false, "error": e}));
            } else {
                eprintln!("bromigos accessibility: {e}");
            }
            return Ok(1);
        }
    };
    let (rendered, reloads, ok) = apply(paths, before.contrast != after.contrast, no_reload);
    if json_out {
        println!(
            "{}",
            json!({"schema": SCHEMA, "ok": ok, "accessibility": settings_json(paths),
                   "theme": rendered, "reloads": reloads})
        );
    } else {
        println!("motion {}, contrast {}", after.motion, after.contrast);
        match rendered.get("error") {
            Some(e) => println!("  theme: {} not rendered: {}", rendered["name"], e),
            None => println!("  theme {} rendered again", rendered["name"]),
        }
        print_reloads(&reloads);
    }
    Ok(if ok { 0 } else { 1 })
}
