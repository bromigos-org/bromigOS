//! `bromigos peripheral`: optional modules for peripherals (docs/peripherals.md). The rules
//! live in bromigos_core::peripheral; this is the command line.
//!
//! Turning a module on installs what it needs (its packages, a group, its user services),
//! records the choice in ~/.config/bromigos/peripherals.toml, writes the Hyprland part
//! (~/.local/state/bromigos/peripherals/hypr.lua; a verified reload) and starts the
//! daemon that runs the dials and the lighting (bromigos-peripherals.service).

use std::path::Path;

use anyhow::{Result, bail};
use bromigos_core::install::{self, Runner};
use bromigos_core::paths::Paths;
use bromigos_core::peripheral::{self as pm, Manifest};
use clap::{Args, Subcommand};
use serde_json::{Value, json};

use crate::SCHEMA;

#[derive(Args)]
#[command(after_help = "\
Modules: /usr/share/bromigos/peripherals/<id>/ (packaged), ~/.config/bromigos/peripherals/<id>/
(yours: a similar keyboard; docs/peripherals.md). Your choices and key changes:
~/.config/bromigos/peripherals.toml, e.g.

  [razer-keyboard]
  enabled = true
  rgb = \"all\"          # the lighting: all (every Razer device), device (the keyboard), off
  dial = true
  [razer-keyboard.keys]
  side1 = \"bromigos-live timeline\"   # \"\" leaves a key unbound

then `bromigos peripheral refresh`.")]
pub struct PeripheralArgs {
    /// Print the JSON document (schema in core/README.md)
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    verb: Option<Verb>,
}

#[derive(Subcommand)]
enum Verb {
    /// Every module: whether its device is here, whether it's on, what it needs
    List,
    /// The modules that are on, as the desktop runs them: devices, keys, dial, lighting
    Status,
    /// Turn a module on: its packages, group and services, your choice recorded, the keys
    /// bound (a verified Hyprland reload) and the dial and lighting started
    Enable {
        id: String,
        /// Only say what it would do
        #[arg(long)]
        dry_run: bool,
        /// Answer pacman's questions with their defaults
        #[arg(long)]
        yes: bool,
        /// Turn it on even when its device isn't connected now
        #[arg(long)]
        force: bool,
        /// Don't reload Hyprland (it takes the keys at its next reload)
        #[arg(long)]
        no_reload: bool,
        /// Don't install, join groups or start services (record the choice, write the keys)
        #[arg(long)]
        no_system: bool,
    },
    /// Turn a module off (its packages stay installed)
    Disable {
        id: String,
        /// Don't reload Hyprland
        #[arg(long)]
        no_reload: bool,
        /// Leave the daemon alone
        #[arg(long)]
        no_system: bool,
    },
    /// What a module's lighting follows: VECTOR (his voice and mood) or the theme (its
    /// primary, always); written to peripherals.toml, the daemon takes it within 10 s
    Follow {
        id: String,
        #[arg(value_parser = ["vector", "theme"])]
        follow: String,
    },
    /// Write the keys again from peripherals.toml and the devices here (after an edit, or
    /// another keyboard plugged in); Hyprland reloads only when they changed
    Refresh {
        /// Don't reload Hyprland
        #[arg(long)]
        no_reload: bool,
    },
}

pub fn peripheral_cmd(paths: &Paths, a: PeripheralArgs) -> Result<i32> {
    let root = pm::root();
    match a.verb.unwrap_or(Verb::List) {
        Verb::List => list(paths, &root, a.json),
        Verb::Status => status(paths, &root, a.json),
        Verb::Enable {
            id,
            dry_run,
            yes,
            force,
            no_reload,
            no_system,
        } => enable(
            paths,
            &root,
            &id,
            pm::EnableOpts {
                yes,
                force,
                reload: !no_reload,
                system: !no_system,
            },
            dry_run,
            a.json,
        ),
        Verb::Disable {
            id,
            no_reload,
            no_system,
        } => disable(paths, &root, &id, !no_reload, !no_system, a.json),
        Verb::Refresh { no_reload } => refresh(paths, &root, !no_reload, a.json),
        Verb::Follow { id, follow } => {
            let (mods, _) = pm::modules(paths);
            if !mods.iter().any(|m| m.id == id) {
                bail!("no peripheral module {id:?} (bromigos peripheral list)");
            }
            pm::set_follow(paths, &id, &follow).map_err(anyhow::Error::msg)?;
            report(
                a.json,
                json!({"schema": SCHEMA, "id": id, "rgb_follow": follow}),
                &[format!(
                    "{id}: the lighting follows {} (within 10 s)",
                    if follow == "theme" {
                        "the theme"
                    } else {
                        "VECTOR"
                    }
                )],
            )?;
            Ok(0)
        }
    }
}

fn found_line(f: &pm::Found) -> String {
    format!(
        "{} ({}, {}{})",
        f.name,
        f.usb,
        match f.how.as_str() {
            "driver" => f.driver.clone().unwrap_or_default(),
            "name" => "by its name: its driver isn't installed yet".into(),
            other => other.into(),
        },
        if f.dial.is_some() { "; a dial" } else { "" }
    )
}

fn needs_json(m: &Manifest, runner: &mut dyn Runner) -> Value {
    let user = pm::user_name(runner);
    let (_, ids) = runner.query(&["id", "-nG", &user]);
    let groups: Vec<&str> = ids.split_whitespace().collect();
    json!({
        "packages": m.needs.packages.iter().map(|p| json!({
            "name": p, "installed": runner.query(&["pacman", "-Qq", p]).0 == 0,
        })).collect::<Vec<_>>(),
        "groups": m.needs.groups.iter().map(|g| json!({
            "name": g, "member": groups.contains(&g.as_str()),
        })).collect::<Vec<_>>(),
        "user_services": m.needs.user_services.iter().map(|u| json!({
            "name": u,
            "enabled": runner.query(&["systemctl", "--user", "is-enabled", u]).1.trim() == "enabled",
        })).collect::<Vec<_>>(),
    })
}

fn list(paths: &Paths, root: &Path, json_out: bool) -> Result<i32> {
    let choices = pm::read_choices(paths);
    let (mods, bad) = pm::modules(paths);
    let enabled = |id: &str| {
        choices
            .as_ref()
            .ok()
            .and_then(|c| c.get(id))
            .is_some_and(|c| c.enabled)
    };
    let mut runner = install::System;
    if json_out {
        let doc = json!({
            "schema": SCHEMA,
            "config": pm::config_file(paths),
            "config_error": choices.as_ref().err(),
            "modules": mods.iter().map(|m| json!({
                "id": m.id, "name": m.name, "description": m.description, "kind": m.kind,
                "source": m.source, "dir": m.dir, "enabled": enabled(&m.id),
                "found": pm::found_here(m, root),
                "needs": needs_json(m, &mut runner),
                "keys": m.keys, "dial": m.dial, "rgb": m.rgb,
            })).collect::<Vec<_>>(),
            "broken": bad.iter().map(|(id, e)| json!({"id": id, "error": e})).collect::<Vec<_>>(),
        });
        println!("{}", serde_json::to_string_pretty(&doc)?);
        return Ok(0);
    }
    if mods.is_empty() && bad.is_empty() {
        println!(
            "no peripheral modules ({} is empty)",
            pm::system_dir(paths).display()
        );
    }
    for m in &mods {
        let found = pm::found_here(m, root);
        println!(
            "{:<18} {:<4} {}{}",
            m.id,
            if enabled(&m.id) { "on" } else { "off" },
            m.name,
            if m.source == "user" { "  (yours)" } else { "" }
        );
        println!("{:<23} {}", "", m.description);
        if found.is_empty() {
            println!("{:<23} found: nothing connected", "");
        }
        for f in &found {
            println!("{:<23} found: {}", "", found_line(f));
        }
        if !enabled(&m.id) && !found.is_empty() {
            println!("{:<23} turn it on: bromigos peripheral enable {}", "", m.id);
        }
    }
    for (id, e) in &bad {
        println!("{id:<18} BROKEN {e}");
    }
    if let Err(e) = &choices {
        println!("{e}");
        return Ok(1);
    }
    Ok(0)
}

fn daemon_json(runner: &mut dyn Runner) -> Value {
    let q = |r: &mut dyn Runner, v: &str| {
        r.query(&["systemctl", "--user", v, pm::DAEMON_UNIT])
            .1
            .trim()
            .to_string()
    };
    let or_unknown = |s: String| {
        if s.is_empty() {
            "unknown".to_string()
        } else {
            s
        }
    };
    json!({"unit": pm::DAEMON_UNIT,
           "enabled": or_unknown(q(runner, "is-enabled")),
           "active": or_unknown(q(runner, "is-active"))})
}

fn status(paths: &Paths, root: &Path, json_out: bool) -> Result<i32> {
    let (mods, problems) = match pm::enabled(paths, root) {
        Ok(x) => x,
        Err(e) => {
            if json_out {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "ok": false, "error": e, "modules": []})
                );
            } else {
                eprintln!("bromigos peripheral: {e}");
            }
            return Ok(1);
        }
    };
    let file = pm::hypr_file(paths);
    let written = std::fs::read_to_string(&file).ok();
    let want = (!mods.is_empty()).then(|| pm::hypr_lua(&mods));
    let current = written == want;
    let mut runner = install::System;
    if json_out {
        let doc = json!({
            "schema": SCHEMA,
            "ok": true,
            "config": pm::config_file(paths),
            "hypr": file,
            "hypr_current": current,
            "modules": mods,
            "problems": problems,
            "daemon": daemon_json(&mut runner),
        });
        println!("{}", serde_json::to_string(&doc)?);
        return Ok(0);
    }
    if mods.is_empty() {
        println!("no peripheral module is on (bromigos peripheral list)");
    }
    for m in &mods {
        println!("{} ({})", m.name, m.id);
        if m.found.is_empty() {
            println!("  not connected now: its keys wait for it");
        }
        for f in &m.found {
            println!("  {}", found_line(f));
        }
        for b in &m.binds {
            println!(
                "  {:<11} {}{}  [{}{}]",
                b.label,
                b.hint,
                if b.changed { " (yours)" } else { "" },
                b.press,
                b.release
                    .as_deref()
                    .map(|r| format!("; released: {r}"))
                    .unwrap_or_default()
            );
        }
        for s in &m.skipped {
            println!("  left out: {s}");
        }
        match (&m.dial, m.dials.is_empty()) {
            (Some(d), false) => println!("  dial       {}", d.hint),
            (Some(_), true) => println!("  dial       none connected"),
            (None, _) => {}
        }
        if let Some(r) = &m.rgb {
            println!(
                "  lighting   {} ({})",
                r.hint,
                match m.rgb_scope {
                    pm::RgbScope::All => "every device it lights",
                    pm::RgbScope::Device => "this keyboard",
                    pm::RgbScope::Off => "off",
                }
            );
        }
    }
    for p in &problems {
        println!("problem: {p}");
    }
    if !current {
        println!(
            "the keys Hyprland has are older than peripherals.toml: bromigos peripheral refresh"
        );
    }
    let d = daemon_json(&mut runner);
    if !mods.is_empty() {
        println!(
            "daemon ({}): {}, {}",
            pm::DAEMON_UNIT,
            d["active"].as_str().unwrap_or("?"),
            d["enabled"].as_str().unwrap_or("?")
        );
    }
    Ok(if problems.is_empty() { 0 } else { 1 })
}

fn report(json_out: bool, doc: Value, lines: &[String]) -> Result<()> {
    if json_out {
        println!("{}", serde_json::to_string_pretty(&doc)?);
    } else {
        for l in lines {
            println!("{l}");
        }
    }
    Ok(())
}

fn enable(
    paths: &Paths,
    root: &Path,
    id: &str,
    o: pm::EnableOpts,
    dry_run: bool,
    json_out: bool,
) -> Result<i32> {
    let mut runner = install::System;
    if dry_run {
        let (mods, _) = pm::modules(paths);
        let Some(m) = mods.iter().find(|m| m.id == id) else {
            bail!("no module {id:?} (bromigos peripheral list)");
        };
        let found = pm::found_here(m, root);
        let user = pm::user_name(&mut runner);
        let (cmds, notes) = if o.system {
            pm::enable_plan(m, &user, o.yes, &mut runner)
        } else {
            (vec![], vec![])
        };
        let shown = |c: &Vec<String>| format!("  {}", c.join(" "));
        let mut lines = vec![format!("would turn {} on:", m.name)];
        if found.is_empty() {
            lines.push("  (its device isn't connected: enable needs --force)".into());
        }
        lines.extend(cmds.iter().filter(|c| c[0] == "sudo").map(shown));
        lines.push(format!(
            "  [{id}] enabled = true in {}",
            pm::config_file(paths).display()
        ));
        lines.push(format!(
            "  write {}{}",
            pm::hypr_file(paths).display(),
            if o.reload { " and reload Hyprland" } else { "" }
        ));
        lines.extend(cmds.iter().filter(|c| c[0] != "sudo").map(shown));
        lines.extend(notes.iter().map(|n| format!("  note: {n}")));
        report(
            json_out,
            json!({"schema": SCHEMA, "dry_run": true, "id": id, "commands": cmds,
                   "notes": notes, "found": found}),
            &lines,
        )?;
        return Ok(0);
    }
    let r = pm::enable(paths, root, id, o, &mut runner).map_err(anyhow::Error::msg)?;
    let mut lines = vec![if r.ok || r.error.is_none() {
        format!("{} is on.", r.name)
    } else {
        format!("{}: {}", r.name, r.error.clone().unwrap_or_default())
    }];
    for f in &r.found {
        lines.push(format!("  {}", found_line(f)));
    }
    if let Some(m) = &r.module {
        lines.push(format!(
            "  keys: {}",
            m.binds
                .iter()
                .map(|b| if b.changed {
                    format!("{} `{}` (yours)", b.label, b.press)
                } else {
                    format!("{} {}", b.label, b.hint)
                })
                .collect::<Vec<_>>()
                .join("; ")
        ));
        lines.extend(m.skipped.iter().map(|s| format!("  left out: {s}")));
    }
    if let Some(w) = &r.hypr {
        lines.push(format!("  Hyprland: {}", w.reload));
    }
    if o.system && r.hypr.is_some() {
        lines.push(match &r.error {
            None => format!("  the dial and lighting: {} running", pm::DAEMON_UNIT),
            Some(e) => format!("  the services: {e}"),
        });
    }
    lines.extend(r.notes.iter().map(|n| format!("  note: {n}")));
    lines.extend(r.problems.iter().map(|p| format!("  problem: {p}")));
    report(json_out, json!({"schema": SCHEMA, "result": r}), &lines)?;
    Ok(if r.ok { 0 } else { 1 })
}

fn disable(
    paths: &Paths,
    root: &Path,
    id: &str,
    reload: bool,
    system: bool,
    json_out: bool,
) -> Result<i32> {
    let mut runner = install::System;
    match pm::disable(paths, root, id, reload, system, &mut runner).map_err(anyhow::Error::msg)? {
        None => {
            report(
                json_out,
                json!({"schema": SCHEMA, "result": null}),
                &[format!("{id} isn't on")],
            )?;
            Ok(0)
        }
        Some(r) => {
            let mut lines = vec![format!("{id} is off (its packages stay installed).")];
            if let Some(w) = &r.hypr {
                lines.push(format!("  Hyprland: {}", w.reload));
            }
            if let Some(e) = &r.error {
                lines.push(format!("  the daemon: {e}"));
            }
            report(json_out, json!({"schema": SCHEMA, "result": r}), &lines)?;
            Ok(if r.ok { 0 } else { 1 })
        }
    }
}

fn refresh(paths: &Paths, root: &Path, reload: bool, json_out: bool) -> Result<i32> {
    let (resolved, problems) = pm::enabled(paths, root).map_err(anyhow::Error::msg)?;
    let w = pm::write_hypr(paths, &resolved, reload);
    report(
        json_out,
        json!({"schema": SCHEMA, "ok": w.ok, "hypr": w, "problems": problems,
               "modules": resolved.iter().map(|r| &r.id).collect::<Vec<_>>()}),
        &std::iter::once(format!(
            "{}: {}",
            w.file.display(),
            if w.changed {
                w.reload.as_str()
            } else {
                "unchanged"
            }
        ))
        .chain(problems.iter().map(|p| format!("problem: {p}")))
        .collect::<Vec<_>>(),
    )?;
    Ok(if w.ok { 0 } else { 1 })
}
