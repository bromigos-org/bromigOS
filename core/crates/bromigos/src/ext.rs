//! `bromigos ext`: extensions from git (docs/extensions.md). The rules live in
//! bromigos_core::ext; this is the command line: the questions, the tables, `--json`.
//!
//! An extension that is more than themes asks a person at a terminal before it installs
//! or updates (its permissions, and for an update what changed). There is no `--yes`:
//! the one way to approve without a terminal is a setup answers file
//! (`bromigos setup --answers FILE`, `[extensions]`), and the ledger records which.

use std::io::{BufRead, IsTerminal, Write};
use std::path::{Path, PathBuf};

use anyhow::{Result, bail};
use bromigos_core::ext::{self, Approval, InstallOpts, Kind, Plan, UpdateOpts};
use bromigos_core::paths::Paths;
use clap::{Args, Subcommand};
use serde_json::json;

use crate::SCHEMA;

#[derive(Args)]
#[command(after_help = "\
Sources: a git URL (https://, ssh://, git@host:path, file://) or a folder, with
@tag, @branch or @commit to pin it (or --ref); or a name from the catalogs
(bromigos ext search). A theme repository without a bromigos-ext.toml installs as a
theme. Installed: ~/.local/share/bromigos/ext/src/<name> (a git checkout), linked into
~/.local/share/bromigos/ext/active/; the ledger: ~/.local/state/bromigos/ext/ledger.json.

Themes install at once. Anything else (code, or something VECTOR uses) shows its
permissions and asks you at a terminal; an update shows what changed first.")]
pub struct ExtArgs {
    /// Print the JSON document
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    verb: Option<Verb>,
}

#[derive(Subcommand)]
enum Verb {
    /// Install from a git URL, a folder or a catalog name: SOURCE[@tag|@branch|@commit]
    Install {
        source: String,
        /// A branch, tag or commit (instead of @ref)
        #[arg(long = "ref", value_name = "REF")]
        git_ref: Option<String>,
        /// The extension's folder inside the repository
        #[arg(long, value_name = "DIR")]
        path: Option<String>,
        /// A theme repository without a manifest: install it under this name
        #[arg(long)]
        name: Option<String>,
        /// A folder that's a git repository: install its files as they are (uncommitted
        /// changes too) instead of its last commit
        #[arg(long)]
        copy: bool,
        /// A theme of yours with the same name (an old `theme install`): move it aside
        /// (kept in ~/.local/state/bromigos/ext/adopted) and install this one
        #[arg(long)]
        adopt: bool,
    },
    /// The installed extensions (and themes of yours not from one)
    List {
        /// Also check every file against the ledger
        #[arg(long)]
        verify: bool,
    },
    /// One extension: installed (its ledger entry, files checked), or what a source
    /// would install (fetched and checked; nothing installed)
    Info {
        what: String,
        #[arg(long = "ref", value_name = "REF")]
        git_ref: Option<String>,
        #[arg(long, value_name = "DIR")]
        path: Option<String>,
        #[arg(long)]
        name: Option<String>,
    },
    /// Update one extension (or --all): shows what changed and any new permissions first
    Update {
        name: Option<String>,
        /// Every installed extension
        #[arg(long)]
        all: bool,
        /// Move to this branch, tag or commit
        #[arg(long = "ref", value_name = "REF")]
        git_ref: Option<String>,
        /// Only say what would change
        #[arg(long)]
        check: bool,
    },
    /// Remove an extension: its links, its checkout (the ledger keeps a line)
    Remove { name: String },
    /// Link a disabled extension's parts again (its files are checked first)
    Enable { name: String },
    /// Unlink an extension's parts; its checkout stays
    Disable { name: String },
    /// A working starter of KIND in ./NAME: theme, live-deck, live-layer, widget,
    /// vector-tool, vector-memory, vector-skill, homelab-adapter, command, hook
    New {
        kind: String,
        name: String,
        /// Where (default ./NAME)
        #[arg(long)]
        dir: Option<PathBuf>,
    },
    /// The catalogs' extensions (bromigOS's own, or catalogs = […] in ~/.config/bromigos/ext.toml)
    Search {
        term: Option<String>,
        /// Only this kind (theme, live-deck, widget, …)
        #[arg(long)]
        kind: Option<String>,
        /// Fetch the catalogs now (they are kept six hours)
        #[arg(long)]
        refresh: bool,
    },
    /// Check an extension folder (default .): its manifest, parts and permissions
    Validate { dir: Option<PathBuf> },
    /// Themes installed before extensions (copied into ~/.config/bromigos/themes): each
    /// one a catalog has, file for file, becomes an extension that updates
    Migrate {
        /// Only say which
        #[arg(long)]
        dry_run: bool,
    },
}

/// Asks a person at a terminal (stderr for the words, stdin for the answer).
pub fn ask(plan: &Plan) -> Option<Approval> {
    eprint!("{}", plan.describe());
    if !std::io::stdin().is_terminal() || !std::io::stderr().is_terminal() {
        eprintln!(
            "{}: it runs code or reaches VECTOR, so it needs a yes from a person at a terminal \
             (or a setup answers file: bromigos setup --answers FILE, [extensions])",
            plan.name
        );
        return None;
    }
    let verb = if plan.op == "update" {
        "Update"
    } else {
        "Install"
    };
    eprint!("{verb} {}? [y/N] ", plan.name);
    let _ = std::io::stderr().flush();
    let mut line = String::new();
    std::io::stdin().lock().read_line(&mut line).ok()?;
    matches!(line.trim().to_lowercase().as_str(), "y" | "yes").then_some(Approval::Interactive)
}

fn kind_arg(s: &str) -> Result<Kind> {
    Kind::parse(s).ok_or_else(|| {
        anyhow::anyhow!(
            "unknown kind {s:?}; kinds: {}",
            Kind::ALL
                .iter()
                .map(|k| k.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        )
    })
}

fn report_out(json_out: bool, r: &ext::Report) {
    if json_out {
        println!("{}", json!({"schema": SCHEMA, "result": r}));
        return;
    }
    println!("{}", r.detail);
    for n in &r.next {
        println!("  {n}");
    }
}

/// The themes an installed extension carries (its ledger entry's theme parts).
fn theme_parts(paths: &Paths, name: &str) -> Vec<String> {
    ext::load_ledger(paths)
        .ok()
        .and_then(|l| {
            l.extensions.get(name).map(|e| {
                e.parts
                    .iter()
                    .filter(|p| p.kind == Kind::Theme)
                    .map(|p| p.name.clone())
                    .collect()
            })
        })
        .unwrap_or_default()
}

/// A theme installed or updated: its switcher preview drawn again, in the background.
fn previews_for(paths: &Paths, name: &str, json_out: bool) {
    let themes = theme_parts(paths, name);
    if themes.is_empty() {
        return;
    }
    if let Some(p) = bromigos_core::previews::render_in_background(&themes, None)
        && !json_out
    {
        println!("  ({p})");
    }
}

fn fail(json_out: bool, verb: &str, e: impl std::fmt::Display) -> i32 {
    if json_out {
        println!(
            "{}",
            json!({"schema": SCHEMA, "ok": false, "error": e.to_string()})
        );
    }
    eprintln!("bromigos ext {verb}: {e}");
    1
}

pub fn ext_cmd(paths: &Paths, a: ExtArgs) -> Result<i32> {
    let j = a.json;
    let Some(verb) = a.verb else {
        return list(paths, j, false);
    };
    match verb {
        Verb::Install {
            source,
            git_ref,
            path,
            name,
            copy,
            adopt,
        } => {
            let opts = InstallOpts {
                git_ref,
                path,
                name,
                copy,
                adopt,
            };
            Ok(install(paths, &source, &opts, j))
        }
        Verb::List { verify } => list(paths, j, verify),
        Verb::Info {
            what,
            git_ref,
            path,
            name,
        } => {
            let opts = InstallOpts {
                git_ref,
                path,
                name,
                ..InstallOpts::default()
            };
            match ext::info(paths, &what, &opts) {
                Ok(i) if j => {
                    println!("{}", json!({"schema": SCHEMA, "info": i}));
                    Ok(0)
                }
                Ok(i) => {
                    print_info(&i);
                    Ok(0)
                }
                Err(e) => Ok(fail(j, "info", e)),
            }
        }
        Verb::Update {
            name,
            all,
            git_ref,
            check,
        } => {
            let names: Vec<String> = match (name, all) {
                (Some(n), false) => vec![n],
                (None, true) => ext::load_ledger(paths)?
                    .extensions
                    .keys()
                    .cloned()
                    .collect(),
                (Some(_), true) => bail!("a name or --all, not both"),
                (None, false) => bail!("which? bromigos ext update NAME, or --all"),
            };
            if all && git_ref.is_some() {
                bail!("--ref moves one extension: name it");
            }
            let opts = UpdateOpts {
                git_ref,
                check_only: check,
            };
            let mut code = 0;
            let mut out = vec![];
            for n in &names {
                match ext::update(paths, n, &opts, &mut ask) {
                    Ok(r) => {
                        if !j {
                            if check && let Some(p) = &r.plan {
                                print!("{}", p.describe());
                            }
                            report_out(false, &r);
                        }
                        if !check {
                            previews_for(paths, n, j);
                        }
                        out.push(json!({"name": n, "ok": true, "result": r}));
                    }
                    Err(e) => {
                        code = 1;
                        if !j {
                            eprintln!("bromigos ext update {n}: {e}");
                        }
                        out.push(json!({"name": n, "ok": false, "error": e.to_string()}));
                    }
                }
            }
            if names.is_empty() && !j {
                println!("no extensions installed");
            }
            if j {
                println!("{}", json!({"schema": SCHEMA, "updates": out}));
            }
            Ok(code)
        }
        Verb::Remove { name } => Ok(match ext::remove(paths, &name) {
            Ok(r) => {
                report_out(j, &r);
                0
            }
            Err(e) => fail(j, "remove", e),
        }),
        Verb::Enable { name } => Ok(match ext::set_enabled(paths, &name, true) {
            Ok(r) => {
                report_out(j, &r);
                0
            }
            Err(e) => fail(j, "enable", e),
        }),
        Verb::Disable { name } => Ok(match ext::set_enabled(paths, &name, false) {
            Ok(r) => {
                report_out(j, &r);
                0
            }
            Err(e) => fail(j, "disable", e),
        }),
        Verb::New { kind, name, dir } => {
            let kind = kind_arg(&kind)?;
            let dir = dir.unwrap_or_else(|| PathBuf::from(&name));
            Ok(match ext::new_starter(kind, &name, &dir) {
                Ok(files) => {
                    new_out(j, kind, &name, &dir, &files);
                    if kind == Kind::Theme {
                        let full = std::fs::canonicalize(&dir).unwrap_or_else(|_| dir.clone());
                        if let Some(p) =
                            bromigos_core::previews::render_in_background(&[], Some(full.as_path()))
                            && !j
                        {
                            println!("  ({p})");
                        }
                    }
                    0
                }
                Err(e) => fail(j, "new", e),
            })
        }
        Verb::Search {
            term,
            kind,
            refresh,
        } => {
            let kind = kind.as_deref().map(kind_arg).transpose()?;
            match ext::search(paths, term.as_deref(), kind, refresh) {
                Ok(s) if j => {
                    println!(
                        "{}",
                        json!({"schema": SCHEMA, "catalogs": s.catalogs, "results": s.results,
                               "errors": s.errors})
                    );
                    Ok(0)
                }
                Ok(s) => {
                    for e in &s.errors {
                        eprintln!("bromigos ext search: {e}");
                    }
                    for h in &s.results {
                        let kinds: Vec<&str> = h.entry.kinds.iter().map(|k| k.as_str()).collect();
                        let tag = if h.entry.bundled {
                            " (ships with bromigOS)"
                        } else if h.installed {
                            " (installed)"
                        } else {
                            ""
                        };
                        println!(
                            "{:<20} {:<24} {}{tag}",
                            h.entry.name,
                            kinds.join(","),
                            h.entry.description
                        );
                    }
                    if s.results.is_empty() {
                        println!("nothing found in {}", s.catalogs.join(", "));
                    }
                    Ok(if s.results.is_empty() && !s.errors.is_empty() {
                        1
                    } else {
                        0
                    })
                }
                Err(e) => Ok(fail(j, "search", e)),
            }
        }
        Verb::Validate { dir } => {
            let dir = dir.unwrap_or_else(|| PathBuf::from("."));
            Ok(match ext::check(&dir, None) {
                Ok(c) => {
                    if j {
                        println!(
                            "{}",
                            json!({"schema": SCHEMA, "ok": true, "manifest": c.manifest,
                                   "parts": c.parts, "files": c.files.len(),
                                   "data_only": c.data_only(), "warnings": c.warnings})
                        );
                    } else {
                        let m = &c.manifest.extension;
                        println!("{} {}: valid", m.name, m.version);
                        for p in &c.parts {
                            for (l, t) in &p.links {
                                println!(
                                    "  {:<16} {} -> active/{}",
                                    p.kind.as_str(),
                                    t.display(),
                                    l.display()
                                );
                            }
                        }
                        for l in c.manifest.permissions.lines() {
                            println!("  {l}");
                        }
                        println!(
                            "  {}",
                            if c.data_only() {
                                "installs without a question (themes only)"
                            } else {
                                "asks before it installs (shows these permissions)"
                            }
                        );
                        for w in &c.warnings {
                            println!("  note: {w}");
                        }
                    }
                    0
                }
                Err(e) => fail(j, "validate", e),
            })
        }
        Verb::Migrate { dry_run } => match ext::migrate(paths, dry_run) {
            Ok(m) if j => {
                println!("{}", json!({"schema": SCHEMA, "migration": m}));
                Ok(i32::from(!m.errors.is_empty()))
            }
            Ok(m) => {
                let verb = if dry_run { "would migrate" } else { "migrated" };
                for t in &m.migrated {
                    println!("{verb} {t}: now an extension (bromigos ext update {t} updates it)");
                }
                for t in &m.left {
                    println!("left {t}: yours (no catalog has it file for file)");
                }
                for e in &m.errors {
                    eprintln!("bromigos ext migrate: {e}");
                }
                if m.migrated.is_empty() && m.left.is_empty() && m.errors.is_empty() {
                    println!("nothing to migrate");
                }
                Ok(i32::from(!m.errors.is_empty()))
            }
            Err(e) => Ok(fail(j, "migrate", e)),
        },
    }
}

/// `bromigos ext install` (and `bromigos theme install`, its alias).
pub fn install(paths: &Paths, source: &str, opts: &InstallOpts, j: bool) -> i32 {
    let mut asked = false;
    let r = ext::install(paths, source, opts, &mut |p| {
        asked = true;
        ask(p)
    });
    match r {
        Ok(r) => {
            if !j
                && !asked
                && let Some(p) = &r.plan
            {
                print!("{}", p.describe());
            }
            report_out(j, &r);
            previews_for(paths, &r.name, j);
            0
        }
        Err(e) => fail(j, "install", e),
    }
}

fn list(paths: &Paths, j: bool, verify: bool) -> Result<i32> {
    let l = match ext::list(paths, verify) {
        Ok(l) => l,
        Err(e) => return Ok(fail(j, "list", e)),
    };
    if j {
        println!("{}", json!({"schema": SCHEMA, "list": l}));
        return Ok(0);
    }
    for r in &l.extensions {
        let kinds: Vec<&str> = r.kinds.iter().map(|k| k.as_str()).collect();
        let commit = r
            .commit
            .as_deref()
            .map(|c| &c[..c.len().min(10)])
            .unwrap_or("-");
        println!(
            "{:<20} {:<10} {:<24} {:<10} {:<13} {}",
            r.name,
            r.version,
            kinds.join(","),
            commit,
            r.status,
            r.source
        );
        for p in &r.problems {
            println!("    {p}");
        }
    }
    if l.extensions.is_empty() {
        println!("no extensions installed (bromigos ext search, bromigos ext install <git url>)");
    }
    if !l.unmanaged_themes.is_empty() {
        println!(
            "\nthemes of yours in ~/.config/bromigos/themes, not from an extension: {}",
            l.unmanaged_themes.join(", ")
        );
        println!(
            "  (installed before extensions? bromigos ext migrate, or bromigos ext install <url> --adopt)"
        );
    }
    if let Some(u) = &l.unfinished {
        println!("\nunfinished: {u} (run it again)");
    }
    Ok(0)
}

fn print_info(i: &ext::Info) {
    if let (Some(e), Some(r)) = (&i.entry, &i.row) {
        println!("{} {} — {}", e.name, e.version, e.description);
        println!("  status     {}", r.status);
        println!("  from       {}", e.source.describe());
        if let Some(c) = &e.commit {
            println!("  commit     {c}");
        }
        println!("  checkout   {}", e.dir.display());
        println!("  installed  {} (updated {})", e.installed, e.updated);
        println!(
            "  approved   {}{} at {}",
            e.approved.how,
            if e.approved.detail.is_empty() {
                String::new()
            } else {
                format!(" ({})", e.approved.detail)
            },
            e.approved.when
        );
        println!("  parts");
        for p in &e.parts {
            for l in &p.links {
                println!(
                    "    {:<16} {:<18} {}",
                    p.kind.as_str(),
                    p.name,
                    l.link.display()
                );
            }
        }
        println!("  permissions");
        for l in e.permissions.lines() {
            println!("    {l}");
        }
        println!("  files      {} (sha256 in the ledger)", e.files.len());
        for p in &r.problems {
            println!("  ! {p}");
        }
    } else if let Some(p) = &i.plan {
        print!("{}", p.describe());
        println!("(not installed: bromigos ext install to install it)");
    }
}

fn new_out(j: bool, kind: Kind, name: &str, dir: &Path, files: &[PathBuf]) {
    if j {
        println!(
            "{}",
            json!({"schema": SCHEMA, "kind": kind, "name": name, "dir": dir, "files": files})
        );
        return;
    }
    println!("a {} starter in {}:", kind.as_str(), dir.display());
    for f in files {
        println!("  {}", f.display());
    }
    let d = dir.display();
    println!("next:");
    println!("  bromigos ext validate {d}");
    println!("  bromigos ext install --copy {d}     (try it as it is)");
    println!("  cd {d} && git init && git add -A && git commit -m \"{name} 0.1.0\"");
    println!("  push it, tag a release (git tag v0.1.0), then: bromigos ext install <url>@v0.1.0");
}
