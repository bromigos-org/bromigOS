//! `bromigos hw display | graphics | games | run | vfio`: what each graphics card is for
//! (Settings › Graphics; docs/hardware.md, bromigos_core::hw::graphics).
//!
//! The desktop's card and the VFIO reservation are the system's (root writes them: the
//! desktop's through pkexec or sudo, since Settings has no terminal; VFIO's through sudo in
//! a terminal, like `hw setup`, with the initramfs made again). The games card is yours.

use std::fs;
use std::io::IsTerminal;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Command;

use anyhow::Result;
use bromigos_core::hw::graphics::{self as gx, CardRef, Desktop, SystemChoice, Trial};
use bromigos_core::hw::{self, Detection};
use bromigos_core::install::{self, Runner, shell_line};
use bromigos_core::paths::Paths;
use bromigos_core::snapshot::{self, Files, RootFs};
use clap::{Args, Subcommand, ValueEnum};
use serde_json::{Value, json};

use crate::SCHEMA;

#[derive(Args)]
pub struct DisplayArgs {
    #[command(subcommand)]
    action: Option<DisplayAction>,
    /// Print the GPU order for Hyprland (the chosen card's, else the automatic one), or
    /// nothing when there is no clear choice
    #[arg(long, conflicts_with = "json")]
    hyprland: bool,
    /// Print "trial DEVICES" or "chosen DEVICES" for a card chosen in Settings, else nothing
    /// (Hyprland's startup asks this first)
    #[arg(long, conflicts_with_all = ["json", "hyprland"])]
    hyprland_chosen: bool,
}

#[derive(Subcommand)]
enum DisplayAction {
    /// Draw the desktop on CARD (a PCI address such as 0000:03:00.0, or card1), or `auto`.
    /// A new card is tried first: log out and in, then `keep` it; a restart goes back
    Use { card: String },
    /// Keep the card being tried (after a login on it worked)
    Keep,
    /// Stop trying a card: the desktop stays where it was
    Cancel,
    /// Back to Automatic, from a text console too (sudo); then restart the login screen
    Reset,
}

#[derive(Subcommand)]
pub enum GamesAction {
    /// Run games and heavy apps on CARD (a PCI address, or card1), or `auto` (the strongest)
    Use { card: String },
    /// Start Steam on the games card (your copy of Steam's launcher), or stop
    Steam { state: OnOff },
}

#[derive(Clone, Copy, ValueEnum)]
pub enum OnOff {
    On,
    Off,
}

#[derive(Subcommand)]
pub enum VfioAction {
    /// Reserve CARD for virtual machines (vfio-pci, by PCI address, from the next start):
    /// writes three files, makes the initramfs again (sudo)
    Reserve {
        card: String,
        /// Only say what it would do
        #[arg(long)]
        dry_run: bool,
    },
    /// Give CARD (or `all`) back to its own driver, from the next start (sudo)
    Release {
        card: String,
        #[arg(long)]
        dry_run: bool,
    },
}

/// `BROMIGOS_FS_ROOT` moves `/` (tests, fixtures), as for reading.
fn root_path(p: &str) -> PathBuf {
    std::env::var_os("BROMIGOS_FS_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/"))
        .join(p.trim_start_matches('/'))
}

fn seat() -> String {
    std::env::var("XDG_SEAT")
        .ok()
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "seat0".into())
}

fn aq() -> Option<String> {
    std::env::var("AQ_DRM_DEVICES")
        .ok()
        .filter(|s| !s.is_empty())
}

fn hooks(files: &dyn Files) -> Vec<String> {
    snapshot::hooks_in_force(&snapshot::hooks_files(files))
}

fn say(json: bool, doc: Value, text: &str) {
    if json {
        let mut doc = doc;
        doc["schema"] = json!(SCHEMA);
        println!("{doc}");
    } else {
        println!("{text}");
    }
}

fn fail(json: bool, e: &str) -> Result<i32> {
    if json {
        println!("{}", json!({"schema": SCHEMA, "ok": false, "error": e}));
    } else {
        eprintln!("bromigos hw: {e}");
    }
    Ok(1)
}

// ---------------------------------------------------------------------------- desktop

fn display_doc(sel: &Desktop) -> Value {
    json!({"schema": SCHEMA, "primary_card": sel.selection.primary_card,
           "drm_devices": sel.selection.drm_devices, "reason": sel.selection.reason,
           "reason_code": sel.selection.reason_code, "source": sel.source, "slot": sel.slot,
           "note": sel.note})
}

/// Writes the system's choice: directly as root (or into a fixture root), else the same
/// command again as root (sudo at a terminal, pkexec from Settings). None: written here.
fn write_system(c: &SystemChoice) -> std::io::Result<()> {
    let p = root_path(gx::SYSTEM_FILE);
    fs::create_dir_all(p.parent().unwrap_or(&p))?;
    let tmp = p.with_extension("tmp");
    fs::write(&tmp, c.to_text())?;
    fs::rename(&tmp, &p)
}

/// The same command as root: sudo at a terminal, pkexec otherwise (the session's polkit
/// agent asks for the password). Its exit status and output are this command's.
fn elevate() -> Result<i32> {
    let exe = std::env::current_exe()?;
    let args: Vec<String> = std::env::args().skip(1).collect();
    let tty = std::io::stdin().is_terminal();
    let mut c = Command::new(if tty { "sudo" } else { "pkexec" });
    c.arg(&exe).args(&args);
    let s = c.status()?;
    match s.code() {
        Some(126) | Some(127) if !tty => {
            let json = args.iter().any(|a| a == "--json");
            fail(
                json,
                "not changed: the password prompt was dismissed or refused",
            )
        }
        Some(code) => Ok(code),
        None => Ok(1),
    }
}

fn save_or_elevate(c: &SystemChoice, json: bool, doc: Value, text: &str) -> Result<i32> {
    match write_system(c) {
        Ok(()) => {
            say(json, doc, text);
            Ok(0)
        }
        Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied && !is_root() => elevate(),
        Err(e) => fail(json, &format!("{}: {e}", gx::SYSTEM_FILE)),
    }
}

fn is_root() -> bool {
    // SAFETY: geteuid has no preconditions and can't fail
    unsafe { libc::geteuid() == 0 }
}

fn name_of(c: Option<&CardRef>, d: &Detection) -> String {
    match c {
        Some(c) => c
            .find(d)
            .map(|g| g.title())
            .unwrap_or_else(|| c.name.clone()),
        None => "Automatic".into(),
    }
}

pub fn display_cmd(a: DisplayArgs, json: bool) -> Result<i32> {
    let files = RootFs;
    let d = hw::detect(&files);
    let choice = gx::read_system(&files);
    let boot = gx::boot_id(&files);
    let seat = seat();
    let Some(action) = a.action else {
        // the startup probe: reads only, runs nothing (the login screen waits on it)
        let sel = gx::desktop(&d, &seat, &choice, &boot);
        if json {
            println!("{}", display_doc(&sel));
        } else if a.hyprland {
            if sel.selection.primary_card.is_some() {
                println!("{}", sel.selection.drm_devices.join(":"));
            }
        } else if a.hyprland_chosen {
            if sel.source != "automatic" && sel.selection.primary_card.is_some() {
                println!("{} {}", sel.source, sel.selection.drm_devices.join(":"));
            }
        } else {
            let card = sel
                .slot
                .as_ref()
                .and_then(|s| d.gpus.iter().find(|g| &g.slot == s));
            match (&sel.selection.primary_card, card) {
                (Some(c), Some(g)) => {
                    println!("Desktop card: {} (/dev/dri/{c}, {})", g.title(), g.slot)
                }
                _ => println!("Desktop card: the compositor's own choice"),
            }
            println!(
                "{} ({})",
                sel.selection.reason,
                match sel.source.as_str() {
                    "trial" => "being tried",
                    "chosen" => "chosen in Settings › Graphics",
                    _ => "automatic",
                }
            );
            if let Some(n) = &sel.note {
                println!("{n}");
            }
            println!(
                "Change it with Settings › Graphics or bromigos hw display use CARD; back to \
                 Automatic with bromigos hw display reset. This check changes nothing."
            );
        }
        return Ok(0);
    };
    let now = gx::desktop(&d, "seat0", &choice, &boot);
    let now_name = now
        .slot
        .as_ref()
        .and_then(|s| d.gpus.iter().find(|g| &g.slot == s))
        .map(|g| g.title())
        .unwrap_or_else(|| "the automatic choice".into());
    let mut new = choice.clone();
    match action {
        DisplayAction::Reset => {
            new.desktop = None;
            new.trial = None;
            let text = "The desktop's card: Automatic, from the next login screen. To get the \
                        login screen back now, run sudo systemctl restart display-manager (it ends \
                        any open session), or restart the computer.";
            save_or_elevate(
                &new,
                json,
                json!({"ok": true, "said": "Desktop card: Automatic",
                                               "note": "from the next login screen"}),
                text,
            )
        }
        DisplayAction::Cancel => {
            let Some(t) = choice.trial.as_ref() else {
                return fail(json, "no card is being tried");
            };
            new.trial = None;
            let said = format!("Not trying {}", t.card.name);
            let text = format!(
                "{said}: the desktop stays on {} from the next login.",
                name_of(choice.desktop.as_ref(), &d)
            );
            save_or_elevate(&new, json, json!({"ok": true, "said": said}), &text)
        }
        DisplayAction::Keep => {
            let Some(t) = choice.trial_in_force(&boot) else {
                return fail(
                    json,
                    "no card is being tried now (a trial ends when the computer restarts)",
                );
            };
            new.desktop = Some(t.card.clone());
            new.trial = None;
            let said = format!("Kept {} for the desktop", t.card.name);
            save_or_elevate(
                &new,
                json,
                json!({"ok": true, "said": said}),
                &format!("{said}."),
            )
        }
        DisplayAction::Use { card } => {
            if card == "auto" || card == "automatic" {
                new.desktop = None;
                new.trial = None;
                return save_or_elevate(
                    &new,
                    json,
                    json!({"ok": true, "said": "Desktop card: Automatic", "note": "from the next login"}),
                    "The desktop's card: Automatic, from the next login.",
                );
            }
            let Some(g) = gx::find_card(&d, &card) else {
                return fail(
                    json,
                    &format!("no card {card} here (bromigos hw graphics lists them)"),
                );
            };
            if choice.reserved(g) {
                return fail(
                    json,
                    &format!("{} is reserved for virtual machines", g.title()),
                );
            }
            if !gx::desktop_ready(g, &g.seat) {
                return fail(
                    json,
                    &format!(
                        "{} can't draw the desktop: {}",
                        g.title(),
                        if hw::usable_on(g, &g.seat) {
                            "no monitor is connected to it"
                        } else {
                            "its driver isn't working"
                        }
                    ),
                );
            }
            let r = CardRef::of(g);
            let kept = choice
                .desktop
                .as_ref()
                .is_some_and(|c| c.slot == g.slot && c.id == g.id);
            if kept || (now.slot.as_deref() == Some(g.slot.as_str()) && now.source != "trial") {
                // what the next login uses already, or the kept card while another is
                // tried: saved as it is, nothing to try
                new.desktop = Some(r);
                new.trial = None;
                let said = format!("{} draws the desktop", g.title());
                return save_or_elevate(
                    &new,
                    json,
                    json!({"ok": true, "said": said}),
                    &format!("{said}."),
                );
            }
            if boot.is_empty() {
                return fail(
                    json,
                    "this boot's ID can't be read, so a trial can't be set up; not changed",
                );
            }
            new.trial = Some(Trial {
                card: r,
                boot_id: boot.clone(),
            });
            let said = format!("Trying {} for the desktop", g.title());
            let note = format!(
                "log out and back in to try it, then keep it in Settings › Graphics (bromigos hw \
                 display keep). Restarting before that goes back to {now_name}"
            );
            save_or_elevate(
                &new,
                json,
                json!({"ok": true, "said": said, "note": note, "trial": true}),
                &format!("{said}: {note}."),
            )
        }
    }
}

// ---------------------------------------------------------------------------- the page

fn report(paths: &Paths) -> gx::Report {
    let files = RootFs;
    let d = hw::detect(&files);
    let choice = gx::read_system(&files);
    let boot = gx::boot_id(&files);
    let boot_loader = snapshot::bootloader(&mut install::System, &files, false);
    let io = gx::iommu(&files, boot_loader);
    gx::report(
        &files,
        paths,
        &d,
        &choice,
        &gx::read_user(paths),
        &boot,
        aq().as_deref(),
        io,
        &hooks(&files),
    )
}

pub fn graphics_cmd(paths: &Paths, json: bool) -> Result<i32> {
    let r = report(paths);
    if json {
        let mut v = serde_json::to_value(&r)?;
        v["schema"] = json!(SCHEMA);
        v["ok"] = json!(true);
        println!("{v}");
        return Ok(0);
    }
    let title = |slot: &Option<String>| {
        slot.as_ref()
            .and_then(|s| r.cards.iter().find(|c| &c.gpu.slot == s))
            .map(|c| c.title.clone())
            .unwrap_or_else(|| "none".into())
    };
    for c in &r.cards {
        let mut uses = vec![];
        if c.desktop_next {
            uses.push("desktop");
        }
        if c.games {
            uses.push("games and heavy apps");
        }
        if c.vfio.reserved {
            uses.push("virtual machines");
        }
        println!(
            "{}  {} at {}{}",
            if uses.is_empty() { "  " } else { "* " },
            c.title,
            c.gpu.slot,
            if uses.is_empty() {
                String::new()
            } else {
                format!(": {}", uses.join(", "))
            }
        );
        println!(
            "     driver {}; {}",
            c.gpu.driver.as_deref().unwrap_or("none"),
            if c.gpu.connected_connectors.is_empty() {
                "no monitor".to_string()
            } else {
                format!("monitor on {}", c.gpu.connected_connectors.join(", "))
            }
        );
    }
    println!(
        "Desktop  {} ({})",
        title(&r.desktop.next.slot.clone().or(r.desktop.automatic.clone())),
        r.desktop.next.source
    );
    if let Some(t) = &r.desktop.trial {
        println!(
            "         trying {}{}",
            t.name,
            if r.desktop.trial_in_force {
                ": keep it with bromigos hw display keep"
            } else {
                " (ended with the last restart; not kept)"
            }
        );
    }
    println!(
        "Games    {} ({})",
        title(&r.games.now.slot),
        r.games.now.source
    );
    for n in &r.games.now.notes {
        println!("         {n}");
    }
    println!(
        "VMs      IOMMU {}; reserved: {}",
        if r.iommu.on { "on" } else { "off" },
        if r.reserved.is_empty() {
            "none".to_string()
        } else {
            r.reserved
                .iter()
                .map(|x| x.card.name.clone())
                .collect::<Vec<_>>()
                .join(", ")
        }
    );
    println!("bromigos hw vfio checks each card for virtual machines.");
    Ok(0)
}

// ------------------------------------------------------------------------------ games

fn desktop_card<'a>(d: &'a Detection, files: &dyn Files) -> Option<&'a hw::Gpu> {
    gx::running_desktop(d, aq().as_deref()).or_else(|| {
        let sel = gx::desktop(d, "seat0", &gx::read_system(files), &gx::boot_id(files));
        sel.slot
            .and_then(|s| d.gpus.iter().find(|g| g.slot == s))
            .or_else(|| gx::automatic_desktop(d, "seat0"))
    })
}

pub fn games_cmd(paths: &Paths, action: Option<GamesAction>, json: bool) -> Result<i32> {
    let files = RootFs;
    let d = hw::detect(&files);
    let mut user = gx::read_user(paths);
    match action {
        None => {
            let g = gx::games(&files, &d, &user, desktop_card(&d, &files));
            let name = g
                .slot
                .as_ref()
                .and_then(|s| d.gpus.iter().find(|x| &x.slot == s))
                .map(|x| x.title())
                .unwrap_or_else(|| "none".into());
            if json {
                let mut v = serde_json::to_value(&g)?;
                v["schema"] = json!(SCHEMA);
                v["ok"] = json!(true);
                v["steam"] = json!(gx::steam_on(paths));
                println!("{v}");
            } else {
                println!("Games and heavy apps: {name} ({})", g.source);
                if g.env.is_empty() {
                    println!("It draws the desktop too: programs need nothing extra.");
                } else {
                    println!("bromigos hw run PROGRAM starts a program on it, with:");
                    for (k, v) in &g.env {
                        println!("  {k}={v}");
                    }
                }
                for n in &g.notes {
                    println!("Note: {n}");
                }
            }
            Ok(0)
        }
        Some(GamesAction::Use { card }) => {
            let said = if card == "auto" || card == "automatic" {
                user.games = None;
                "Games and heavy apps: Automatic (the strongest card)".to_string()
            } else {
                let Some(g) = gx::find_card(&d, &card) else {
                    return fail(
                        json,
                        &format!("no card {card} here (bromigos hw graphics lists them)"),
                    );
                };
                if !gx::game_ready(g) {
                    return fail(
                        json,
                        &format!("{} has no working driver for programs", g.title()),
                    );
                }
                user.games = Some(CardRef::of(g));
                format!("Games and heavy apps: {}", g.title())
            };
            if let Err(e) = gx::write_user(paths, &user) {
                return fail(json, &format!("{}: {e}", gx::user_file(paths).display()));
            }
            let note = "for programs started from now on";
            say(
                json,
                json!({"ok": true, "said": said, "note": note}),
                &format!("{said} ({note})."),
            );
            Ok(0)
        }
        Some(GamesAction::Steam { state }) => {
            let p = gx::steam_override(paths);
            match state {
                OnOff::On => {
                    let Some(orig) = files.read(gx::STEAM_DESKTOP) else {
                        return fail(
                            json,
                            "Steam isn't installed (bromigos game setup installs it)",
                        );
                    };
                    if p.exists() && !gx::steam_on(paths) {
                        return fail(
                            json,
                            &format!("{} is your own: left alone (remove it first)", p.display()),
                        );
                    }
                    let exe = std::env::current_exe()
                        .ok()
                        .filter(|e| e.starts_with("/usr/"))
                        .map(|e| e.display().to_string())
                        .unwrap_or_else(|| "/usr/bin/bromigos".into());
                    let r = fs::create_dir_all(p.parent().unwrap_or(&p))
                        .and_then(|_| fs::write(&p, gx::steam_launcher(&orig, &exe)));
                    if let Err(e) = r {
                        return fail(json, &format!("{}: {e}", p.display()));
                    }
                    let said = "Steam starts on the games card";
                    say(
                        json,
                        json!({"ok": true, "said": said, "note": "from Steam's next start"}),
                        &format!("{said}, from its next start ({}).", p.display()),
                    );
                }
                OnOff::Off => {
                    if p.exists() {
                        if !gx::steam_on(paths) {
                            return fail(json, &format!("{} is your own: left alone", p.display()));
                        }
                        if let Err(e) = fs::remove_file(&p) {
                            return fail(json, &format!("{}: {e}", p.display()));
                        }
                    }
                    let said = "Steam starts as usual";
                    say(
                        json,
                        json!({"ok": true, "said": said, "note": "from Steam's next start"}),
                        &format!("{said}, from its next start."),
                    );
                }
            }
            Ok(0)
        }
    }
}

/// `bromigos hw run [--print] -- PROGRAM …`: the program on the games card. Anything
/// unclear starts it as it is: never in the way of a game starting.
pub fn run_cmd(paths: &Paths, print: bool, command: Vec<String>) -> Result<i32> {
    let files = RootFs;
    let d = hw::detect(&files);
    let g = gx::games(&files, &d, &gx::read_user(paths), desktop_card(&d, &files));
    if print {
        for (k, v) in &g.env {
            println!("{k}={v}");
        }
        if command.is_empty() {
            return Ok(0);
        }
    }
    let Some((prog, args)) = command.split_first() else {
        eprintln!("bromigos hw run: name a program: bromigos hw run -- PROGRAM [ARGS]");
        return Ok(2);
    };
    let err = Command::new(prog).args(args).envs(&g.env).exec();
    eprintln!("bromigos hw run: {prog}: {err}");
    Ok(127)
}

// ------------------------------------------------------------------------------- VFIO

pub fn vfio_cmd(paths: &Paths, action: Option<VfioAction>, json: bool) -> Result<i32> {
    let files = RootFs;
    let d = hw::detect(&files);
    let choice = gx::read_system(&files);
    let boot = gx::boot_id(&files);
    let mut runner = install::System;
    let io = gx::iommu(&files, snapshot::bootloader(&mut runner, &files, false));
    let hk = hooks(&files);
    let state = |g: &hw::Gpu| gx::vfio_state(&files, &d, g, &choice, &boot, &io, &hk);
    let Some(action) = action else {
        if json {
            let cards: Vec<Value> = d
                .gpus
                .iter()
                .map(|g| json!({"slot": g.slot, "title": g.title(), "vfio": state(g)}))
                .collect();
            println!(
                "{}",
                json!({"schema": SCHEMA, "ok": true, "iommu": io, "cards": cards, "reserved": choice.vfio})
            );
            return Ok(0);
        }
        println!("IOMMU {}", if io.on { "on" } else { "off" });
        for s in &io.steps {
            println!("  {s}");
        }
        for g in &d.gpus {
            let v = state(g);
            println!(
                "{}  {}{}",
                g.title(),
                g.slot,
                if v.reserved {
                    " (reserved for VMs)"
                } else if v.ready {
                    " (can be reserved)"
                } else {
                    ""
                }
            );
            for c in &v.checks {
                println!("  {} {}", if c.ok { "ok " } else { "NO " }, c.text);
            }
            if let Some(r) = &v.reset {
                println!("  note {r}");
            }
        }
        return Ok(0);
    };
    let (mut list, dry, said) = match action {
        VfioAction::Reserve { card, dry_run } => {
            let Some(g) = gx::find_card(&d, &card) else {
                return fail(
                    json,
                    &format!("no card {card} here (bromigos hw vfio lists them)"),
                );
            };
            let v = state(g);
            if v.reserved {
                return fail(json, &format!("{} is reserved already", g.title()));
            }
            if !v.ready {
                let why: Vec<String> = v
                    .checks
                    .iter()
                    .filter(|c| !c.ok)
                    .map(|c| format!("{}. {}", c.text, c.hint))
                    .collect();
                return fail(
                    json,
                    &format!("{} can't be reserved: {}", g.title(), why.join(" ")),
                );
            }
            let mut list = choice.vfio.clone();
            list.push(gx::reservation(&files, g));
            (
                list,
                dry_run,
                format!("{} is reserved for virtual machines", g.title()),
            )
        }
        VfioAction::Release { card, dry_run } => {
            let list: Vec<gx::Reserved> = if card == "all" {
                vec![]
            } else {
                let found = choice.vfio.iter().find(|r| {
                    r.card.slot == card
                        || r.card.slot.strip_prefix("0000:") == Some(card.as_str())
                        || gx::find_card(&d, &card).is_some_and(|g| g.slot == r.card.slot)
                });
                let Some(f) = found else {
                    return fail(json, &format!("{card} isn't reserved"));
                };
                choice
                    .vfio
                    .iter()
                    .filter(|r| r.card.slot != f.card.slot)
                    .cloned()
                    .collect()
            };
            (list, dry_run, "Given back to its own driver".to_string())
        }
    };
    list.dedup_by(|a, b| a.card.slot == b.card.slot);
    let mut new = choice.clone();
    new.vfio = list.clone();
    // the commands: the files staged, installed with sudo (or removed), the initramfs again
    let staged = paths.state_home.join("bromigos/hw/staged");
    let mut commands: Vec<Vec<String>> = vec![];
    let mut writes: Vec<(PathBuf, String)> = vec![];
    let want = gx::vfio_files(&list);
    for (n, (path, content, mode)) in want.iter().enumerate() {
        // two of the files share a name (modprobe.d's and mkinitcpio.conf.d's)
        let tmp = staged.join(format!("{n}-{}", path.rsplit('/').next().unwrap_or("file")));
        writes.push((tmp.clone(), content.clone()));
        commands.push(vec![
            "sudo".into(),
            "install".into(),
            format!("-Dm{mode:o}"),
            tmp.display().to_string(),
            path.clone(),
        ]);
    }
    if want.is_empty() {
        let mut rm: Vec<String> = vec!["sudo".into(), "rm".into(), "-f".into()];
        rm.extend(
            [gx::VFIO_SCRIPT, gx::VFIO_MODPROBE, gx::VFIO_INITRAMFS]
                .iter()
                .map(|s| s.to_string()),
        );
        commands.push(rm);
    }
    let tmp = staged.join("graphics.json");
    writes.push((tmp.clone(), new.to_text()));
    commands.push(vec![
        "sudo".into(),
        "install".into(),
        "-Dm644".into(),
        tmp.display().to_string(),
        gx::SYSTEM_FILE.into(),
    ]);
    commands.push(["sudo", "mkinitcpio", "-P"].map(String::from).to_vec());
    let lines: Vec<String> = commands.iter().map(|c| shell_line(c)).collect();
    if dry {
        say(
            json,
            json!({"ok": true, "dry_run": true, "commands": lines, "files": want.iter().map(|(p, c, _)| json!({"path": p, "content": c})).collect::<Vec<_>>()}),
            &format!(
                "It would run:\n{}",
                lines
                    .iter()
                    .map(|l| format!("  $ {l}"))
                    .collect::<Vec<_>>()
                    .join("\n")
            ),
        );
        return Ok(0);
    }
    for (p, c) in &writes {
        if let Err(e) = fs::create_dir_all(&staged).and_then(|_| fs::write(p, c)) {
            return fail(json, &format!("{}: {e}", p.display()));
        }
    }
    for (c, line) in commands.iter().zip(&lines) {
        if !json {
            println!("$ {line}");
        }
        match runner.run(c, !json) {
            Ok((0, _)) => {}
            Ok((code, out)) => {
                return fail(
                    json,
                    &format!(
                        "`{line}` exited {code}{}",
                        out.lines()
                            .last()
                            .map(|l| format!(": {l}"))
                            .unwrap_or_default()
                    ),
                );
            }
            Err(e) => return fail(json, &format!("`{line}`: {e}")),
        }
    }
    for (p, _) in &writes {
        let _ = fs::remove_file(p);
    }
    let note = "restart the computer for it to take effect";
    say(
        json,
        json!({"ok": true, "said": said, "note": note, "reboot": true}),
        &format!("{said}: {note}."),
    );
    Ok(0)
}
