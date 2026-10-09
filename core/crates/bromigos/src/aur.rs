//! `bromigos aur`: the AUR here (docs/aur.md, bromigos_core::aur): the helper, whether
//! bromigOS uses it, the AUR updates waiting; on, off, and what install and the update's
//! migration run.

use anyhow::Result;
use bromigos_core::aur::{self, Applied};
use bromigos_core::install;
use bromigos_core::paths::Paths;
use clap::{Args, Subcommand};
use serde_json::json;

use crate::SCHEMA;

#[derive(Args)]
#[command(after_help = "\
The AUR (Arch User Repository) holds build recipes that Arch users share; anyone can submit \
one, so nobody vets them. bromigOS never needs it: an install comes from Arch's repositories \
and bromigOS's own, where its build of paru is too. With the AUR on (the default), \
bromigos update updates your AUR packages after the repositories', inside the same snapshot \
pair, and paru shows each recipe's changes for you to review first (--yes skips the review). \
The setting: ~/.config/bromigos/aur.toml. docs/aur.md.")]
pub struct AurArgs {
    #[command(subcommand)]
    verb: Option<AurVerb>,
    /// Print the JSON document (schema in core/README.md)
    #[arg(long, global = true)]
    json: bool,
}

#[derive(Subcommand)]
enum AurVerb {
    /// The helper here (bromigOS's paru, or your own paru or yay), whether bromigos update
    /// uses it, and the AUR updates waiting (paru -Qua) (the default)
    Status,
    /// Use the AUR: bromigos update updates AUR packages, and bromigOS's paru is installed
    /// when there's no paru or yay here (sudo pacman -S paru)
    On {
        /// pacman doesn't ask
        #[arg(long)]
        yes: bool,
        /// Only say what it would do
        #[arg(long)]
        dry_run: bool,
    },
    /// Leave the AUR alone: bromigos update doesn't touch AUR packages, and the paru
    /// bromigOS installed is removed (sudo pacman -R paru); a helper you installed stays
    Off {
        /// pacman doesn't ask
        #[arg(long)]
        yes: bool,
        /// Only say what it would do
        #[arg(long)]
        dry_run: bool,
    },
    /// bromigOS's paru, unless the AUR is off here or a helper is installed: what bromigos
    /// install and the update's migration run. Exit 75 when paru isn't in the repositories
    /// pacman has synced yet
    Ensure {
        /// pacman doesn't ask
        #[arg(long)]
        yes: bool,
        /// Only say what it would do
        #[arg(long)]
        dry_run: bool,
    },
}

pub fn aur_cmd(paths: &Paths, a: AurArgs) -> Result<i32> {
    let mut sys = install::System;
    let (verb, yes, dry) = match a.verb.unwrap_or(AurVerb::Status) {
        AurVerb::Status => return status(paths, a.json),
        AurVerb::On { yes, dry_run } => ("on", yes, dry_run),
        AurVerb::Off { yes, dry_run } => ("off", yes, dry_run),
        AurVerb::Ensure { yes, dry_run } => ("ensure", yes, dry_run),
    };
    let r = match verb {
        "on" => aur::on(paths, &mut sys, yes, dry),
        "off" => aur::off(paths, &mut sys, yes, dry),
        _ => aur::ensure(paths, &mut sys, yes, dry),
    };
    let r: Applied = match r {
        Ok(r) => r,
        Err(e) => {
            if a.json {
                println!("{}", json!({"schema": SCHEMA, "ok": false, "error": e}));
            } else {
                eprintln!("bromigos aur {verb}: {e}");
            }
            return Ok(1);
        }
    };
    if a.json {
        println!("{}", json!({"schema": SCHEMA, "aur": r}));
    } else {
        for c in &r.commands {
            println!("{}$ {c}", if dry { "would run: " } else { "" });
        }
        println!("{}", r.detail);
    }
    // not yet (paru isn't in the synced repositories): EX_TEMPFAIL, as a migration's
    Ok(if r.ok { 0 } else { 75 })
}

fn status(paths: &Paths, json: bool) -> Result<i32> {
    let mut sys = install::System;
    let s = aur::setting(paths);
    let found = aur::found(&mut sys);
    let c = bromigos_core::update::aur_check(s.enabled, false, found, |h| {
        aur::pending(&mut install::System, h)
    });
    if json {
        println!(
            "{}",
            json!({"schema": SCHEMA, "setting": s, "installed_by_bromigos":
                aur::installed_by_bromigos(paths), "check": c})
        );
        return Ok(0);
    }
    println!(
        "setting: {} ({}{})",
        if s.enabled {
            "on: bromigos update updates AUR packages"
        } else {
            "off: bromigos update leaves AUR packages alone"
        },
        s.path.display(),
        if s.exists {
            ""
        } else {
            ", not written: the default"
        }
    );
    for p in &s.problems {
        println!("  problem: {p}");
    }
    println!("helper: {}", c.found.describe());
    for l in bromigos_core::update::aur_check_lines(&c) {
        println!("{l}");
    }
    Ok(0)
}

/// The setup page's text: what the AUR is, what's here; and whether it's on now.
pub fn page_text(paths: &Paths) -> (String, bool) {
    let on = aur::enabled(paths);
    let f = aur::found(&mut install::System);
    let here = match f.helper {
        Some(_) => format!("Here now: {}.", f.describe()),
        None => "Here now: no AUR helper.".to_string(),
    };
    (
        format!(
            "The AUR (Arch User Repository) holds build recipes that Arch users share. Anyone can \
             submit one and nobody vets them, so each is built on this machine from a recipe you \
             should read first. bromigOS never needs the AUR; this is for software only it has.\n\n\
             {here} The AUR is {} here.\n\n\
             On: bromigOS keeps an AUR helper (its own build of paru, unless you have paru or yay) \
             and `bromigos update` updates your AUR packages after the repositories', inside the \
             same snapshot pair (so `--rollback` undoes them too); paru shows each recipe's \
             changes for you to review first. `bromigos hw setup` can then offer a driver only \
             the AUR has.\n\
             Off: no helper from bromigOS (the paru it installed is removed; one you installed \
             stays), and updates leave AUR packages alone. `bromigos aur on|off` changes it any time.",
            if on { "on" } else { "off" }
        ),
        on,
    )
}
