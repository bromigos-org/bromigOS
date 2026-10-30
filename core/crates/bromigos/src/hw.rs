//! `bromigos hw`: what this machine is (its GPUs, a laptop or a desktop, a VM) and what
//! bromigOS sets up for it; `hw setup` does it (docs/hardware.md, bromigos_core::hw).

use anyhow::Result;
use bromigos_core::hw::{self, ApplyOpts, Detection, Plan};
use bromigos_core::install::{self, Runner};
use bromigos_core::paths::Paths;
use bromigos_core::snapshot::RootFs;
use clap::{Args, Subcommand};
use serde_json::json;

use crate::SCHEMA;

#[derive(Args)]
#[command(after_help = "\
What it reads: the PCI display devices (NVIDIA's own supported-chips list and Mesa's tables \
say which driver), the DMI chassis type, batteries, the lid, backlights, touchpads, the \
kernels, mkinitcpio's MODULES. What setup does, only where it differs: the GPU's packages \
(never swapping an installed NVIDIA driver), NVIDIA's early KMS, a hybrid laptop's render GPU \
(udev names, AQ_DRM_DEVICES for Hyprland), runtime power management for its NVIDIA GPU, and \
on a laptop brightnessctl and power-profiles-daemon. A driver only the AUR has (NVIDIA's \
580.xx and 470.xx branches) is offered through paru, after a question. What each card is for \
(the desktop, games and heavy apps, virtual machines): hw graphics, hw display, hw games, hw \
run, hw vfio, and Settings › Graphics. docs/hardware.md.")]
pub struct HwArgs {
    #[command(subcommand)]
    verb: Option<HwVerb>,
    /// Print the JSON document (schema in core/README.md)
    #[arg(long, global = true)]
    json: bool,
}

#[derive(Subcommand)]
enum HwVerb {
    /// What this machine is and what `bromigos hw setup` would do (the default)
    Detect,
    /// Which card draws the login screen and the desktop (read-only), or change it: `use
    /// CARD|auto`, `keep`, `cancel`, `reset` (Settings › Graphics)
    Display(crate::hw_graphics::DisplayArgs),
    /// Set this machine's hardware up: drivers, early KMS, a hybrid laptop's GPUs, power
    /// profiles, Hyprland's GPU environment (sudo for the system's part)
    Setup {
        /// Only say what it would do
        #[arg(long)]
        dry_run: bool,
        /// Answer pacman's questions with their defaults (unattended)
        #[arg(long)]
        yes: bool,
        /// Only your own part: Hyprland's GPU environment (no sudo, no packages)
        #[arg(long)]
        user_only: bool,
        /// Build a driver only the AUR has (NVIDIA's 580.xx or 470.xx) with paru without
        /// asking first; paru still shows its recipe for review unless --yes (docs/aur.md)
        #[arg(long)]
        aur: bool,
    },
    /// Every graphics card and what it's for: the desktop, games and heavy apps, virtual
    /// machines (what Settings › Graphics shows)
    Graphics,
    /// The card games and heavy apps use (Automatic: the strongest), or change it
    Games {
        #[command(subcommand)]
        action: Option<crate::hw_graphics::GamesAction>,
    },
    /// Run a program on the games card: bromigos hw run -- PROGRAM [ARGS] (a Steam game's
    /// launch options: bromigos hw run -- %command%)
    Run {
        /// Print the environment it sets (NAME=VALUE lines), and run nothing without a program
        #[arg(long)]
        print: bool,
        /// The program and its arguments, after `--`
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        command: Vec<String>,
    },
    /// Virtual machines: each card's checks for VFIO passthrough, or `reserve CARD` and
    /// `release CARD|all` (by PCI address; sudo, then a restart)
    Vfio {
        #[command(subcommand)]
        action: Option<crate::hw_graphics::VfioAction>,
    },
}

pub fn hw_cmd(paths: &Paths, a: HwArgs) -> Result<i32> {
    // Startup probes only read hardware. Do not run pacman or systemd, or construct
    // an installation plan, while the login screen is deciding where to appear.
    match a.verb {
        Some(HwVerb::Display(d)) => return crate::hw_graphics::display_cmd(d, a.json),
        Some(HwVerb::Graphics) => return crate::hw_graphics::graphics_cmd(paths, a.json),
        Some(HwVerb::Games { action }) => {
            return crate::hw_graphics::games_cmd(paths, action, a.json);
        }
        Some(HwVerb::Run { print, command }) => {
            return crate::hw_graphics::run_cmd(paths, print, command);
        }
        Some(HwVerb::Vfio { action }) => {
            return crate::hw_graphics::vfio_cmd(paths, action, a.json);
        }
        _ => {}
    }
    let files = RootFs;
    let d = hw::detect(&files);
    let mut runner = install::System;
    let plan = hw::plan(paths, &d, &mut runner, &files);
    match a.verb {
        Some(
            HwVerb::Display(_)
            | HwVerb::Graphics
            | HwVerb::Games { .. }
            | HwVerb::Run { .. }
            | HwVerb::Vfio { .. },
        ) => unreachable!("answered above"),
        None | Some(HwVerb::Detect) => {
            if a.json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "detection": d, "plan": plan})
                );
            } else {
                print_detection(&d);
                print_plan(&plan, false);
            }
            Ok(0)
        }
        Some(HwVerb::Setup {
            dry_run,
            yes,
            user_only,
            aur,
        }) => {
            let booted = hw::booted(&files, &mut runner);
            if !a.json && !dry_run {
                println!("{}", hw::summary(&d));
            }
            // a driver only the AUR has: --aur, or a yes typed at the terminal; never by
            // default, never in a dry run (which shows the command), never with --json
            // unless --aur
            let aur_driver = !user_only
                && match hw::aur_question(&plan) {
                    None => false,
                    Some(_) if aur || dry_run => true,
                    Some(q) => !yes && !a.json && hw::ask(&q),
                };
            let opts = ApplyOpts {
                yes,
                user_only,
                no_services: false,
                now: booted,
                aur_driver,
            };
            let applied = hw::apply(paths, &plan, &opts, dry_run, &mut |argv, interactive| {
                let line = argv.join(" ");
                if dry_run {
                    return Ok(());
                }
                if !a.json {
                    println!("$ {line}");
                }
                // with --json the commands' own output would break the document: captured
                match runner.run(&argv, interactive && !a.json) {
                    Ok((0, _)) => Ok(()),
                    Ok((c, out)) => Err(format!(
                        "`{line}` exited {c}{}",
                        out.lines()
                            .last()
                            .map(|l| format!(": {l}"))
                            .unwrap_or_default()
                    )),
                    Err(e) => Err(format!("`{line}`: {e}")),
                }
            });
            if a.json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "detection": d, "plan": plan, "applied": applied})
                );
            } else if dry_run {
                print_detection(&d);
                print_plan(&plan, user_only);
                if !applied.commands.is_empty() {
                    println!("\nIt would run:");
                    for c in &applied.commands {
                        println!("  $ {c}");
                    }
                }
            } else {
                println!(
                    "{} {}",
                    if applied.ok { "done:" } else { "FAILED:" },
                    applied.detail
                );
                for n in &plan.notes {
                    println!("note: {n}");
                }
                if applied.ok && applied.reboot {
                    println!("Reboot for it to take effect.");
                }
            }
            Ok(if applied.ok { 0 } else { 1 })
        }
    }
}

fn yes_no(b: Option<bool>) -> &'static str {
    match b {
        Some(true) => "on",
        Some(false) => "OFF",
        None => "?",
    }
}

fn print_detection(d: &Detection) {
    let m = &d.machine;
    let model = format!("{} {}", m.vendor, m.product).trim().to_string();
    let mut why = vec![];
    if let Some(v) = &m.virt {
        why.push(format!("a {v} virtual machine"));
    }
    if let Some(t) = m.chassis_type {
        why.push(format!("chassis type {t}"));
    }
    if !m.batteries.is_empty() && !m.chassis_type.is_some_and(|t| hw::PORTABLE.contains(&t)) {
        why.push("it has a battery".into());
    }
    println!(
        "This machine: a {}{}{}",
        if m.kind == "other" {
            "machine"
        } else {
            m.kind.as_str()
        },
        if why.is_empty() {
            String::new()
        } else {
            format!(" ({})", why.join("; "))
        },
        if model.is_empty() {
            String::new()
        } else {
            format!(", {model}")
        }
    );
    if d.gpus.is_empty() {
        println!("GPU    none found");
    }
    for g in &d.gpus {
        println!("GPU    {}  {} at {}", g.title(), g.id, g.slot);
        println!(
            "       {}{}",
            g.family
                .as_deref()
                .map(|f| format!("{f}: "))
                .unwrap_or_default(),
            g.stack.describe()
        );
        let mut driver = match g.driver.as_deref() {
            Some("nvidia") => format!(
                "driver nvidia ({} {}; KMS {}, fbdev {})",
                match d.nvidia.open {
                    Some(true) => "open modules",
                    Some(false) => "proprietary modules",
                    None => "modules",
                },
                d.nvidia.version.as_deref().unwrap_or(""),
                yes_no(d.nvidia.modeset),
                yes_no(d.nvidia.fbdev)
            ),
            Some(dr) => format!("driver {dr}"),
            None => "no driver bound".to_string(),
        };
        if let Some(c) = &g.card {
            driver.push_str(&format!(
                "; {c}{}{}",
                if g.connectors.is_empty() {
                    String::new()
                } else {
                    format!(": {}", g.connectors.join(", "))
                },
                if g.panel { " (the built-in panel)" } else { "" }
            ));
        }
        println!("       {driver}");
    }
    if let Some(h) = &d.hybrid {
        println!(
            "Hybrid the desktop renders on {}, {} is for offload",
            h.integrated, h.discrete
        );
    }
    let bat = if m.batteries.is_empty() {
        "no battery".to_string()
    } else {
        m.batteries
            .iter()
            .map(|b| {
                format!(
                    "battery {} {}{}",
                    b.name,
                    b.capacity.map(|c| format!("{c}% ")).unwrap_or_default(),
                    b.status.to_lowercase()
                )
            })
            .collect::<Vec<_>>()
            .join(", ")
    };
    let list = |v: &[String], none: &str, what: &str| {
        if v.is_empty() {
            none.to_string()
        } else {
            format!("{what} {}", v.join(", "))
        }
    };
    println!(
        "Power  {bat} · {} · {}{} · {}",
        if m.lid { "a lid" } else { "no lid" },
        list(&m.backlight, "no backlight", "backlight"),
        if m.kbd_backlight.is_empty() {
            String::new()
        } else {
            " (and the keyboard's)".to_string()
        },
        list(&m.touchpads, "no touchpad", "touchpad")
    );
    println!(
        "System kernels {} · multilib {} · mkinitcpio MODULES ({}) · hibernation {}",
        if d.kernels.is_empty() {
            "?".to_string()
        } else {
            d.kernels.join(", ")
        },
        if d.multilib { "on" } else { "off" },
        if d.initramfs_modules.is_empty() {
            "none".to_string()
        } else {
            d.initramfs_modules.join(" ")
        },
        if d.hibernation {
            "set up"
        } else {
            "not set up"
        }
    );
}

fn print_plan(p: &Plan, user_only: bool) {
    println!();
    if p.done() {
        println!("`bromigos hw setup` has nothing to change here.");
    } else {
        println!("`bromigos hw setup` would:");
    }
    if !user_only {
        if !p.install.is_empty() {
            println!("  install   {}", p.install.join(" "));
        }
        for f in &p.write {
            let why = p
                .want
                .files
                .iter()
                .find(|x| &x.path == f)
                .map(|x| x.why.as_str())
                .unwrap_or("");
            println!("  write     {f}  ({why})");
        }
        if p.initramfs {
            println!("  run       mkinitcpio -P (the initramfs again)");
        }
        if !p.enable.is_empty() {
            println!("  enable    {}", p.enable.join(" "));
        }
        if let Some(h) = p.aur_helper.filter(|_| !p.aur.is_empty()) {
            println!(
                "  offer     {} from the AUR, built with {} (asks first; --aur: no question)",
                p.aur.join(" "),
                h.bin()
            );
        }
    }
    if p.hyprland_changed {
        println!(
            "  write     {}  (Hyprland's GPU environment: {})",
            p.hyprland_path.display(),
            if p.want.env.is_empty() {
                "none needed".to_string()
            } else {
                p.want
                    .env
                    .iter()
                    .map(|e| format!("{}={}", e.name, e.value))
                    .collect::<Vec<_>>()
                    .join(" ")
            }
        );
    }
    if !p.keep.is_empty() {
        println!("Already right:");
        for k in &p.keep {
            println!("  {k}");
        }
    }
    if !p.notes.is_empty() {
        println!("Notes:");
        for n in &p.notes {
            println!("  {n}");
        }
    }
}

/// The setup page's text: what was found and what setup would do; and whether it would.
pub fn page_text(paths: &Paths) -> (String, bool) {
    let files = RootFs;
    let d = hw::detect(&files);
    let plan = hw::plan(paths, &d, &mut install::System, &files);
    let mut lines = vec![format!("This machine: {}", hw::summary(&d))];
    for g in &d.gpus {
        lines.push(format!("  {}: {}", g.title(), g.stack.describe()));
    }
    if !plan.install.is_empty() {
        lines.push(format!("To install: {}", plan.install.join(" ")));
    }
    for f in &plan.write {
        lines.push(format!("To write: {f}"));
    }
    if !plan.enable.is_empty() {
        lines.push(format!("To enable: {}", plan.enable.join(" ")));
    }
    if let Some(h) = plan.aur_helper.filter(|_| !plan.aur.is_empty()) {
        lines.push(format!(
            "From the AUR, if you say yes after this page: {} (built with {})",
            plan.aur.join(" "),
            h.bin()
        ));
    }
    if !plan.want.env.is_empty() {
        lines.push(format!(
            "For Hyprland: {}",
            plan.want
                .env
                .iter()
                .map(|e| format!("{}={}", e.name, e.value))
                .collect::<Vec<_>>()
                .join(" ")
        ));
    }
    for n in &plan.notes {
        lines.push(format!("Note: {n}"));
    }
    (lines.join("\n"), !plan.done())
}
