//! The AUR (docs/aur.md): the Arch User Repository, build recipes (PKGBUILDs) that Arch
//! users share. Anyone can submit one, so an AUR package is built on this machine from a
//! recipe nobody vetted; an AUR helper (paru, yay) fetches the recipe, shows it for review,
//! builds it as the user and installs the result with `sudo pacman`.
//!
//! bromigOS never needs the AUR: everything it installs comes from Arch's repositories and
//! its own (`[bromigos]`, where its build of paru is too). It does keep the AUR easy:
//!
//! - **the setting**: `~/.config/bromigos/aur.toml`, `enabled = true` (the default) or
//!   `false`. On, bromigOS keeps an AUR helper here (its own paru, unless the machine has
//!   paru or yay already) and `bromigos update` updates AUR packages with it. Off, neither.
//!   `bromigos aur on|off` and `bromigos setup aur` write it; `bromigos install --no-aur`
//!   writes it off before anything is installed;
//! - **the helper**: paru when it's here (bromigOS's build or the user's own), else yay;
//!   the user's own is used as it is, never replaced or reconfigured;
//! - **the update's AUR step**: after the repositories' transaction and before the post
//!   snapshot, `paru -Sua` with snap-pac told to skip its transactions (`SNAP_PAC_SKIP`
//!   passed through sudo with `--sudoflags --preserve-env=SNAP_PAC_SKIP`), so the AUR's
//!   changes land in the update's own snapshot pair and `--rollback` undoes them too. A
//!   person at a terminal gets paru's review of every recipe; `--yes` skips it. A package
//!   that doesn't build is reported, with how to retry; the update goes on.
//!
//! Everything that runs goes through the installer's [`Runner`], so tests record it.

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use serde::Serialize;

use crate::install::Runner;
use crate::paths::Paths;
use crate::update::{Available, Changed, Installed};

/// bromigOS's build of paru, in `[bromigos]` (packaging/paru).
pub const PACKAGE: &str = "paru";

/// An AUR helper bromigOS can drive.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Helper {
    Paru,
    Yay,
}

impl Helper {
    pub fn bin(self) -> &'static str {
        match self {
            Helper::Paru => "paru",
            Helper::Yay => "yay",
        }
    }
}

// ------------------------------------------------------------------ the setting

/// `~/.config/bromigos/aur.toml`.
pub fn path(paths: &Paths) -> PathBuf {
    paths.user_config_dir().join("aur.toml")
}

/// The setting as read: on unless the file says `enabled = false`. A file that can't be
/// read, or a value that isn't a boolean, reads as on (and is reported).
#[derive(Debug, Clone, Serialize)]
pub struct Setting {
    pub enabled: bool,
    pub path: PathBuf,
    /// The file exists (else it's the default).
    pub exists: bool,
    pub problems: Vec<String>,
}

pub fn setting(paths: &Paths) -> Setting {
    let p = path(paths);
    let mut out = Setting {
        enabled: true,
        path: p.clone(),
        exists: false,
        problems: vec![],
    };
    let text = match fs::read_to_string(&p) {
        Ok(t) => t,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return out,
        Err(e) => {
            out.problems.push(format!("{}: {e}", p.display()));
            return out;
        }
    };
    out.exists = true;
    match text.parse::<toml::Table>() {
        Ok(t) => match t.get("enabled") {
            None => {}
            Some(toml::Value::Boolean(b)) => out.enabled = *b,
            Some(v) => out
                .problems
                .push(format!("enabled = {v}: true or false (read as true)")),
        },
        Err(e) => out.problems.push(format!("{}: {e}", p.display())),
    }
    out
}

pub fn enabled(paths: &Paths) -> bool {
    setting(paths).enabled
}

const HEADER: &str = "\
# The AUR and bromigOS (docs/aur.md): yours (`bromigos aur on|off` and `bromigos setup aur`
# write it; an update never touches it).
#   enabled = true    bromigOS keeps an AUR helper here (its own paru, unless you have paru
#                     or yay) and `bromigos update` updates your AUR packages with it, inside
#                     the update's snapshot pair
#   enabled = false   neither: no AUR helper from bromigOS, and updates leave the AUR alone
";

/// Writes `enabled`, keeping the file's comments and other keys (atomic, through a symlink).
pub fn set_enabled(paths: &Paths, on: bool) -> Result<(), String> {
    let p = path(paths);
    let existing = match fs::read_to_string(&p) {
        Ok(t) => Some(t),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
        Err(e) => return Err(format!("{}: {e}", p.display())),
    };
    let mut doc: toml_edit::DocumentMut = match &existing {
        Some(t) => t
            .parse()
            .map_err(|e| format!("{}: {e} (fix or remove it; nothing written)", p.display()))?,
        None => toml_edit::DocumentMut::new(),
    };
    doc["enabled"] = toml_edit::value(on);
    let target = fs::canonicalize(&p).unwrap_or_else(|_| p.clone());
    if let Some(d) = target.parent() {
        fs::create_dir_all(d).map_err(|e| format!("{}: {e}", d.display()))?;
    }
    let tmp = target.with_extension("toml.tmp");
    let text = match existing {
        Some(_) => doc.to_string(),
        None => format!("{HEADER}{doc}"),
    };
    fs::write(&tmp, text).map_err(|e| format!("{}: {e}", tmp.display()))?;
    fs::rename(&tmp, &target).map_err(|e| format!("{}: {e}", target.display()))
}

// ------------------------------------------------------------------ what's here

/// `~/.local/state/bromigos/aur.toml`: bromigOS installed its paru here (so `bromigos aur
/// off` may take it out again; a paru the user installed is never removed).
fn state_path(paths: &Paths) -> PathBuf {
    paths.user_state_dir().join("aur.toml")
}

pub fn installed_by_bromigos(paths: &Paths) -> bool {
    fs::read_to_string(state_path(paths))
        .ok()
        .and_then(|t| t.parse::<toml::Table>().ok())
        .and_then(|t| t.get("installed_paru").map(|v| v.as_str().is_some()))
        .unwrap_or(false)
}

fn record_installed(paths: &Paths, yes: bool) {
    let p = state_path(paths);
    if !yes {
        let _ = fs::remove_file(&p);
        return;
    }
    let _ = fs::create_dir_all(paths.user_state_dir());
    let _ = fs::write(
        &p,
        format!(
            "# bromigOS installed its paru here (bromigos aur off takes it out again)\n\
             installed_paru = {:?}\n",
            chrono::Local::now().to_rfc3339()
        ),
    );
}

/// The AUR helper on this machine, and where it came from.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Found {
    /// paru when it runs here, else yay.
    pub helper: Option<Helper>,
    /// Its version, as it says (`paru v2.1.0 - libalpm v16.0.1`: `2.1.0`).
    pub version: Option<String>,
    /// The package that installed it is bromigOS's build (signed, from `[bromigos]`).
    pub bromigos_build: bool,
    /// A package provides `paru` (paru, paru-bin, paru-git), even when it doesn't run.
    pub paru_provided: bool,
    /// The other helper is here too (paru and yay both: paru is used).
    pub also: Option<Helper>,
}

impl Found {
    /// One line: "paru 2.1.0 (bromigOS's build)", "yay 13.0.1 (yours)", "none".
    pub fn describe(&self) -> String {
        let Some(h) = self.helper else {
            return "none".into();
        };
        let mut s = format!(
            "{}{}",
            h.bin(),
            self.version
                .as_deref()
                .map(|v| format!(" {v}"))
                .unwrap_or_default()
        );
        s.push_str(if self.bromigos_build && h == Helper::Paru {
            " (bromigOS's build)"
        } else {
            " (yours)"
        });
        if let Some(a) = self.also {
            s.push_str(&format!("; {} is here too", a.bin()));
        }
        s
    }
}

/// `paru v2.1.0 - libalpm v16.0.1` / `yay v13.0.1 - libalpm v16.0.1`: the version.
pub fn parse_version(out: &str) -> Option<String> {
    out.split_whitespace()
        .nth(1)
        .map(|v| v.trim_start_matches('v').to_string())
}

/// What's here: each helper asked for its version (it runs, or it isn't here), pacman for
/// the package that installed paru.
pub fn found(runner: &mut dyn Runner) -> Found {
    let mut ver = |h: Helper| {
        let (code, out) = runner.query(&[h.bin(), "--version"]);
        (code == 0).then(|| parse_version(&out).unwrap_or_default())
    };
    let paru = ver(Helper::Paru);
    let yay = ver(Helper::Yay);
    let (helper, version, also) = match (paru, yay) {
        (Some(p), y) => (Some(Helper::Paru), Some(p), y.map(|_| Helper::Yay)),
        (None, Some(y)) => (Some(Helper::Yay), Some(y), None),
        (None, None) => (None, None, None),
    };
    let (code, info) = runner.query(&["pacman", "-Qi", PACKAGE]);
    let bromigos_build = code == 0
        && info
            .lines()
            .any(|l| l.starts_with("Packager") && l.contains("bromigOS"));
    let paru_provided = runner.query(&["pacman", "-T", PACKAGE]).0 == 0;
    Found {
        helper,
        version: version.filter(|v| !v.is_empty()),
        bromigos_build,
        paru_provided,
        also,
    }
}

// ------------------------------------------------------------------ the updates waiting

/// The AUR updates waiting (`paru -Qua`: no root, the AUR's web API): `name old -> new`,
/// `new` is `latest-commit` for a development package paru checks upstream (its Devel
/// option). Err: it couldn't tell (why).
pub fn pending(runner: &mut dyn Runner, helper: Helper) -> Result<Vec<Available>, String> {
    // run, not query: stderr says why it failed (the query drops it); nothing interactive
    let argv: Vec<String> = [helper.bin(), "-Qua", "--color", "never"]
        .map(String::from)
        .to_vec();
    match runner.run(&argv, false) {
        Ok((code, out)) => parse_pending(helper, code, &out),
        Err(e) => Err(format!("{} -Qua: {e}", helper.bin())),
    }
}

/// `-Qua`'s exit code and output (stdout and stderr together): 0 and the lines, or 1 and
/// nothing (up to date), or anything else: it couldn't tell.
pub fn parse_pending(helper: Helper, code: i32, out: &str) -> Result<Vec<Available>, String> {
    // IgnorePkg's (`name old -> new [ignored]`) aren't waiting: the helper won't build them
    let kept: String = out
        .lines()
        .filter(|l| !l.trim_end().ends_with("[ignored]"))
        .map(|l| format!("{l}\n"))
        .collect();
    let ups = crate::update::parse_checkupdates(&kept);
    let error = out
        .lines()
        .find(|l| l.trim_start().starts_with("error"))
        .map(str::trim);
    match (code, error) {
        (0, _) => Ok(ups),
        (1, None) if ups.is_empty() => Ok(vec![]),
        (_, Some(e)) => Err(format!("{} -Qua: {e}", helper.bin())),
        (c, None) => Err(format!("{} -Qua exited {c}", helper.bin())),
    }
}

// ------------------------------------------------------------------ the update's step

/// Whether the update runs its AUR step, and how.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase", tag = "aur")]
pub enum Plan {
    /// Runs it with this helper; `unattended`: no questions, no review (`--yes`).
    Run { helper: Helper, unattended: bool },
    /// Left out, and why.
    Skip { why: String },
}

/// What decides it: the setting, `--no-aur`, who runs the update, the helper, a person at
/// a terminal, `--yes`.
#[derive(Debug, Clone, Copy)]
pub struct When {
    pub enabled: bool,
    pub no_aur: bool,
    pub root: bool,
    pub helper: Option<Helper>,
    /// A person at a terminal to answer the helper's review (and not `--json`).
    pub interactive: bool,
    pub yes: bool,
}

impl When {
    /// This machine's: the setting, the helper found, who runs it.
    pub fn here(
        paths: &Paths,
        runner: &mut dyn Runner,
        no_aur: bool,
        interactive: bool,
        yes: bool,
    ) -> When {
        When {
            enabled: enabled(paths),
            no_aur,
            root: rustix::process::geteuid().is_root(),
            helper: found(runner).helper,
            interactive,
            yes,
        }
    }
}

/// The update's AUR step: run with the helper (its review for a person at a terminal, none
/// with `--yes`), or left out, saying why. Never as root (paru won't build as root), never
/// unreviewed unless `--yes` asked for it.
pub fn plan(w: When) -> Plan {
    let skip = |why: &str| Plan::Skip { why: why.into() };
    if w.no_aur {
        return skip("--no-aur");
    }
    if !w.enabled {
        return skip("the AUR is off here (bromigos aur on)");
    }
    let Some(helper) = w.helper else {
        return skip("no AUR helper here (bromigos aur on installs bromigOS's paru)");
    };
    if w.root {
        return skip(
            "running as root: AUR packages are built as your user (run bromigos update as yourself)",
        );
    }
    if w.yes {
        return Plan::Run {
            helper,
            unattended: true,
        };
    }
    if !w.interactive {
        return skip(
            "no terminal to review the AUR's recipes in: run bromigos update in a terminal, or \
             with --yes to build them without the review",
        );
    }
    Plan::Run {
        helper,
        unattended: false,
    }
}

/// One command the step runs, with the environment it adds.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Step {
    pub argv: Vec<String>,
    pub env: Vec<(String, String)>,
}

impl Step {
    pub fn line(&self) -> String {
        let env: String = self.env.iter().map(|(k, v)| format!("{k}={v} ")).collect();
        format!("{env}{}", crate::install::shell_line(&self.argv))
    }
}

/// The step's command: `paru -Sua` (AUR packages only; the repositories' were just done).
/// `skip_snap_pac`: the update made its own pre snapshot, so snap-pac must skip the
/// helper's pacman transactions too: `SNAP_PAC_SKIP=y` in its environment and sudo told to
/// keep it (`--sudoflags --preserve-env=SNAP_PAC_SKIP`, which the helper adds to its own
/// SudoFlags; sudo allows it where it allows `sudo SNAP_PAC_SKIP=y pacman`, as the update's
/// own transaction does). `unattended`: no questions, and no review of the recipes.
pub fn step(helper: Helper, unattended: bool, skip_snap_pac: bool) -> Step {
    let mut argv: Vec<String> = vec![helper.bin().into(), "-Sua".into()];
    let mut env = vec![];
    if skip_snap_pac {
        argv.extend(["--sudoflags".into(), "--preserve-env=SNAP_PAC_SKIP".into()]);
        env.push(("SNAP_PAC_SKIP".into(), "y".into()));
    }
    if unattended {
        argv.push("--noconfirm".into());
        match helper {
            Helper::Paru => argv.push("--skipreview".into()),
            Helper::Yay => argv.extend(
                [
                    "--answerdiff",
                    "None",
                    "--answeredit",
                    "None",
                    "--answerclean",
                    "None",
                ]
                .map(String::from),
            ),
        }
    }
    Step { argv, env }
}

/// What the step did (the update's report and `--json`).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Outcome {
    pub helper: Option<Helper>,
    /// `done` (everything due was updated), `none` (nothing was due), `skipped` (the step
    /// was left out: `detail` says why), `failed` (the helper failed, or some packages
    /// weren't updated).
    pub status: &'static str,
    pub detail: String,
    /// The command it ran.
    pub command: Option<String>,
    /// The helper's exit code.
    pub code: Option<i32>,
    /// The AUR updates that were due (None: the helper couldn't say).
    pub due: Option<Vec<Available>>,
    /// What the step changed (the AUR packages, and anything they pulled in).
    pub changed: Vec<Changed>,
    /// Due, and still at the old version: their build failed, or the update was declined.
    pub not_updated: Vec<String>,
    /// How to try again.
    pub retry: Option<String>,
}

impl Outcome {
    pub fn skipped(why: impl Into<String>) -> Outcome {
        Outcome {
            helper: None,
            status: "skipped",
            detail: why.into(),
            command: None,
            code: None,
            due: None,
            changed: vec![],
            not_updated: vec![],
            retry: None,
        }
    }

    pub fn failed(&self) -> bool {
        self.status == "failed"
    }

    /// Nothing was due: the helper wasn't run.
    pub fn up_to_date(helper: Helper) -> Outcome {
        Outcome {
            helper: Some(helper),
            status: "none",
            detail: "up to date".into(),
            due: Some(vec![]),
            ..Outcome::skipped("")
        }
    }
}

/// What a step that ran did: what was due, the helper's exit code, the packages before and
/// after it.
pub fn outcome(
    helper: Helper,
    step: &Step,
    due: Result<Vec<Available>, String>,
    code: i32,
    before: &BTreeMap<String, Installed>,
    after: &BTreeMap<String, Installed>,
) -> Outcome {
    let changed = crate::update::changes(before, after);
    let (due, unknown) = match due {
        Ok(d) => (Some(d), None),
        Err(e) => (None, Some(e)),
    };
    let not_updated: Vec<String> = due
        .iter()
        .flatten()
        .filter(|a| after.get(&a.name).is_some_and(|i| i.version == a.from))
        .map(|a| a.name.clone())
        .collect();
    let ok = code == 0 && not_updated.is_empty();
    let n = changed.len();
    let mut detail = if ok {
        format!("{n} package{} changed", if n == 1 { "" } else { "s" })
    } else if not_updated.is_empty() {
        format!("{} exited {code}", helper.bin())
    } else {
        format!(
            "not updated: {} (its build failed, or it was declined at the review: {}'s \
             messages above say which)",
            not_updated.join(", "),
            helper.bin()
        )
    };
    if let Some(u) = unknown {
        detail.push_str(&format!(" (what was due is unknown: {u})"));
    }
    let retry = (!ok).then(|| {
        if not_updated.is_empty() {
            format!(
                "bromigos update again (or the AUR alone: {} -Sua)",
                helper.bin()
            )
        } else {
            format!(
                "bromigos update again, or {} -S {} to see why; leave the AUR out of one \
                 update with bromigos update --no-aur",
                helper.bin(),
                not_updated.join(" ")
            )
        }
    });
    Outcome {
        helper: Some(helper),
        status: if ok { "done" } else { "failed" },
        detail,
        command: Some(step.line()),
        code: Some(code),
        due,
        changed,
        not_updated,
        retry,
    }
}

// ------------------------------------------------------------------ on, off, ensure

/// What `ensure`, `on` or `off` did.
#[derive(Debug, Clone, Serialize)]
pub struct Applied {
    /// The setting now.
    pub enabled: bool,
    /// The helper here now.
    pub found: Found,
    /// The commands run (or, in a dry run, that would run).
    pub commands: Vec<String>,
    pub detail: String,
    pub ok: bool,
}

/// Runs or plans one command.
fn exec(
    runner: &mut dyn Runner,
    dry: bool,
    cmds: &mut Vec<String>,
    argv: Vec<String>,
) -> Result<(), String> {
    let line = crate::install::shell_line(&argv);
    cmds.push(line.clone());
    if dry {
        return Ok(());
    }
    match runner.run(&argv, true) {
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
}

/// bromigOS's paru, when the setting is on and there's no helper here (nor a package that
/// provides paru, which ours would conflict with): `sudo pacman -S --needed paru`. Nothing
/// otherwise. What `bromigos install` and the update's migration run. `yes`: pacman doesn't
/// ask (a migration has no terminal to ask on). Err only when pacman failed.
pub fn ensure(
    paths: &Paths,
    runner: &mut dyn Runner,
    yes: bool,
    dry: bool,
) -> Result<Applied, String> {
    let s = setting(paths);
    let f = found(runner);
    let mut out = Applied {
        enabled: s.enabled,
        found: f.clone(),
        commands: vec![],
        detail: String::new(),
        ok: true,
    };
    if !s.enabled {
        out.detail = "the AUR is off here: no helper from bromigOS (bromigos aur on)".into();
        return Ok(out);
    }
    if f.helper.is_some() {
        out.detail = format!(
            "{}: bromigos update updates AUR packages with it",
            f.describe()
        );
        return Ok(out);
    }
    if f.paru_provided {
        out.detail = "a package provides paru but `paru` doesn't run: left as it is (pacman -Qi paru-bin paru-git)".into();
        return Ok(out);
    }
    if runner.query(&["pacman", "-Si", PACKAGE]).0 != 0 {
        out.detail = "paru isn't in the repositories pacman has synced yet (bromigOS's [bromigos] \
                      carries it; the next bromigos update syncs them and installs it)"
            .into();
        out.ok = false;
        return Ok(out);
    }
    let mut a: Vec<String> = ["sudo", "pacman", "-S", "--needed"]
        .map(String::from)
        .to_vec();
    if yes {
        a.push("--noconfirm".into());
    }
    a.push(PACKAGE.into());
    exec(runner, dry, &mut out.commands, a)?;
    if !dry {
        record_installed(paths, true);
        out.found = found(runner);
    }
    out.detail = if dry {
        "would install bromigOS's paru".into()
    } else {
        format!("installed {}", out.found.describe())
    };
    Ok(out)
}

/// The setting on, then [`ensure`].
pub fn on(paths: &Paths, runner: &mut dyn Runner, yes: bool, dry: bool) -> Result<Applied, String> {
    if !dry {
        set_enabled(paths, true)?;
    }
    let mut r = ensure(paths, runner, yes, dry)?;
    r.enabled = true;
    if dry && !enabled(paths) && r.found.helper.is_none() {
        r.detail = "would turn the AUR on and install bromigOS's paru".into();
    }
    Ok(r)
}

/// The setting off; the paru bromigOS installed here is removed (`sudo pacman -R paru`,
/// not its dependencies); a helper the user installed stays, unused by bromigOS.
pub fn off(
    paths: &Paths,
    runner: &mut dyn Runner,
    yes: bool,
    dry: bool,
) -> Result<Applied, String> {
    if !dry {
        set_enabled(paths, false)?;
    }
    let f = found(runner);
    let mut out = Applied {
        enabled: false,
        found: f.clone(),
        commands: vec![],
        detail: String::new(),
        ok: true,
    };
    let ours = installed_by_bromigos(paths) && runner.query(&["pacman", "-Qq", PACKAGE]).0 == 0;
    if ours {
        let mut a: Vec<String> = ["sudo", "pacman", "-R"].map(String::from).to_vec();
        if yes {
            a.push("--noconfirm".into());
        }
        a.push(PACKAGE.into());
        exec(runner, dry, &mut out.commands, a)?;
        if !dry {
            record_installed(paths, false);
            out.found = found(runner);
        }
        out.detail =
            "the AUR is off: bromigOS's paru removed; bromigos update leaves AUR packages alone"
                .into();
    } else if let Some(h) = f.helper {
        out.detail = format!(
            "the AUR is off: bromigos update leaves AUR packages alone; {} stays (yours: \
             bromigOS didn't install it)",
            h.bin()
        );
    } else {
        out.detail = "the AUR is off: no helper from bromigOS, and bromigos update leaves AUR packages alone".into();
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inst(v: &str) -> Installed {
        Installed {
            version: v.into(),
            installed: 0,
        }
    }

    #[test]
    fn versions_from_the_helpers() {
        assert_eq!(
            parse_version("paru v2.1.0 - libalpm v16.0.1\n").as_deref(),
            Some("2.1.0")
        );
        assert_eq!(
            parse_version("yay v13.0.1 - libalpm v16.0.1").as_deref(),
            Some("13.0.1")
        );
    }

    #[test]
    fn pending_lines_and_exit_codes() {
        let r = parse_pending(
            Helper::Paru,
            0,
            "cowsay 3.7.0-1 -> 3.8.4-1\nfoo-git 1.r3-1 -> latest-commit\nbar 1-1 -> 2-1 [ignored]\n",
        )
        .unwrap();
        let names: Vec<_> = r.iter().map(|a| (a.name.as_str(), a.to.as_str())).collect();
        assert_eq!(
            names,
            vec![("cowsay", "3.8.4-1"), ("foo-git", "latest-commit")],
            "IgnorePkg's aren't waiting"
        );
        assert_eq!(parse_pending(Helper::Paru, 1, "").unwrap(), vec![]);
        assert!(
            parse_pending(
                Helper::Paru,
                1,
                "error: failed to get current pkgs: Connection refused\n"
            )
            .unwrap_err()
            .contains("Connection refused")
        );
        assert!(parse_pending(Helper::Yay, 2, "").is_err());
    }

    fn when() -> When {
        When {
            enabled: true,
            no_aur: false,
            root: false,
            helper: Some(Helper::Paru),
            interactive: true,
            yes: false,
        }
    }

    #[test]
    fn the_step_runs_reviewed_at_a_terminal_unreviewed_only_with_yes() {
        assert_eq!(
            plan(when()),
            Plan::Run {
                helper: Helper::Paru,
                unattended: false
            }
        );
        assert_eq!(
            plan(When {
                yes: true,
                interactive: false,
                ..when()
            }),
            Plan::Run {
                helper: Helper::Paru,
                unattended: true
            }
        );
        // no terminal and no --yes: left out, never built unreviewed by accident
        let p = plan(When {
            interactive: false,
            ..when()
        });
        assert!(
            matches!(&p, Plan::Skip { why } if why.contains("--yes")),
            "{p:?}"
        );
        for (w, says) in [
            (
                When {
                    no_aur: true,
                    ..when()
                },
                "--no-aur",
            ),
            (
                When {
                    enabled: false,
                    ..when()
                },
                "bromigos aur on",
            ),
            (
                When {
                    helper: None,
                    ..when()
                },
                "no AUR helper",
            ),
            (
                When {
                    root: true,
                    yes: true,
                    ..when()
                },
                "root",
            ),
        ] {
            let p = plan(w);
            assert!(
                matches!(&p, Plan::Skip { why } if why.contains(says)),
                "{p:?}"
            );
        }
    }

    #[test]
    fn the_step_keeps_snap_pac_out_through_sudo() {
        let s = step(Helper::Paru, false, true);
        assert_eq!(
            s.argv,
            vec![
                "paru",
                "-Sua",
                "--sudoflags",
                "--preserve-env=SNAP_PAC_SKIP"
            ]
        );
        assert_eq!(s.env, vec![("SNAP_PAC_SKIP".to_string(), "y".to_string())]);
        assert_eq!(
            s.line(),
            "SNAP_PAC_SKIP=y paru -Sua --sudoflags --preserve-env=SNAP_PAC_SKIP"
        );
        // no pair of the update's own (no snapshots here): snap-pac, if any, does its job
        let s = step(Helper::Paru, true, false);
        assert_eq!(s.argv, vec!["paru", "-Sua", "--noconfirm", "--skipreview"]);
        assert!(s.env.is_empty());
        let s = step(Helper::Yay, true, true);
        assert!(s.argv.starts_with(&["yay".into(), "-Sua".into()]));
        assert!(s.argv.contains(&"--answerdiff".into()));
    }

    #[test]
    fn a_failed_build_is_named_and_a_retry_given() {
        let s = step(Helper::Paru, false, true);
        let due = vec![
            Available {
                name: "cowsay".into(),
                from: "3.7.0-1".into(),
                to: "3.8.4-1".into(),
            },
            Available {
                name: "broken".into(),
                from: "1-1".into(),
                to: "2-1".into(),
            },
        ];
        let before = BTreeMap::from([
            ("cowsay".to_string(), inst("3.7.0-1")),
            ("broken".to_string(), inst("1-1")),
        ]);
        let after = BTreeMap::from([
            ("cowsay".to_string(), inst("3.8.4-1")),
            ("broken".to_string(), inst("1-1")),
        ]);
        let o = outcome(Helper::Paru, &s, Ok(due.clone()), 1, &before, &after);
        assert!(o.failed());
        assert_eq!(o.not_updated, vec!["broken"]);
        assert_eq!(o.changed.len(), 1);
        assert!(o.retry.as_deref().unwrap().contains("paru -S broken"));
        assert!(o.detail.contains("not updated: broken"));
        // both built
        let after2 = BTreeMap::from([
            ("cowsay".to_string(), inst("3.8.4-1")),
            ("broken".to_string(), inst("2-1")),
        ]);
        let o = outcome(Helper::Paru, &s, Ok(due), 0, &before, &after2);
        assert_eq!(o.status, "done");
        assert_eq!(o.detail, "2 packages changed");
        assert!(o.retry.is_none());
        // the helper failed before building anything, and couldn't say what was due
        let o = outcome(
            Helper::Paru,
            &s,
            Err("paru -Qua exited 1".into()),
            1,
            &before,
            &before,
        );
        assert!(o.failed());
        assert!(o.detail.contains("paru exited 1"));
        assert!(o.retry.is_some());
    }

    /// Answers queries by prefix; records what runs.
    struct Fake {
        answers: Vec<(&'static str, i32, &'static str)>,
        ran: Vec<String>,
    }

    impl Runner for Fake {
        fn run(&mut self, argv: &[String], _interactive: bool) -> std::io::Result<(i32, String)> {
            self.ran.push(argv.join(" "));
            Ok((0, String::new()))
        }
        fn query(&mut self, argv: &[&str]) -> (i32, String) {
            let q = argv.join(" ");
            self.answers
                .iter()
                .find(|(p, _, _)| q.starts_with(p))
                .map(|(_, c, o)| (*c, o.to_string()))
                .unwrap_or((1, String::new()))
        }
    }

    fn sandbox() -> (tempfile::TempDir, Paths) {
        let d = tempfile::tempdir().unwrap();
        let home = d.path().to_path_buf();
        (
            d,
            Paths::from_lookup(move |k| (k == "HOME").then(|| home.clone())),
        )
    }

    #[test]
    fn ensure_installs_bromigos_paru_only_where_there_is_no_helper() {
        let (_d, paths) = sandbox();
        // nothing here, ours in the synced repositories: installed, and remembered
        let mut f = Fake {
            answers: vec![("pacman -Si paru", 0, "Repository : bromigos\n")],
            ran: vec![],
        };
        let r = ensure(&paths, &mut f, true, false).unwrap();
        assert_eq!(f.ran, vec!["sudo pacman -S --needed --noconfirm paru"]);
        assert!(r.ok);
        assert!(installed_by_bromigos(&paths));
        // a dry run only says it
        let (_d2, p2) = sandbox();
        let mut f = Fake {
            answers: vec![("pacman -Si paru", 0, "")],
            ran: vec![],
        };
        let r = ensure(&p2, &mut f, false, true).unwrap();
        assert!(f.ran.is_empty());
        assert_eq!(r.commands, vec!["sudo pacman -S --needed paru"]);
        assert!(!installed_by_bromigos(&p2));
        // the user's own paru (the AUR's, built here), or yay: used as it is, nothing installed
        for (q, out) in [
            ("paru --version", "paru v2.1.0 - libalpm v16.0.1"),
            ("yay --version", "yay v13.0.1 - libalpm v16.0.1"),
        ] {
            let mut f = Fake {
                answers: vec![(q, 0, out), ("pacman -Si paru", 0, "")],
                ran: vec![],
            };
            let r = ensure(&p2, &mut f, true, false).unwrap();
            assert!(f.ran.is_empty(), "{:?}", f.ran);
            assert!(r.detail.contains("(yours)"), "{}", r.detail);
        }
        // paru-bin or paru-git installed (they provide paru, and conflict with ours)
        let mut f = Fake {
            answers: vec![("pacman -T paru", 0, ""), ("pacman -Si paru", 0, "")],
            ran: vec![],
        };
        ensure(&p2, &mut f, true, false).unwrap();
        assert!(f.ran.is_empty());
        // not in the synced repositories yet: not ok (the migration tries again)
        let mut f = Fake {
            answers: vec![],
            ran: vec![],
        };
        let r = ensure(&p2, &mut f, true, false).unwrap();
        assert!(!r.ok && f.ran.is_empty());
        // the AUR off here: nothing, ever
        set_enabled(&p2, false).unwrap();
        let mut f = Fake {
            answers: vec![("pacman -Si paru", 0, "")],
            ran: vec![],
        };
        let r = ensure(&p2, &mut f, true, false).unwrap();
        assert!(r.ok && f.ran.is_empty() && !r.enabled);
    }

    #[test]
    fn off_removes_only_the_paru_bromigos_installed() {
        let (_d, paths) = sandbox();
        let mut f = Fake {
            answers: vec![
                ("paru --version", 0, "paru v2.1.0"),
                ("pacman -Qq paru", 0, "paru"),
            ],
            ran: vec![],
        };
        // the user's own: stays
        let r = off(&paths, &mut f, true, false).unwrap();
        assert!(f.ran.is_empty());
        assert!(r.detail.contains("paru stays"), "{}", r.detail);
        assert!(!enabled(&paths));
        // bromigOS's: removed (not its dependencies), and forgotten
        record_installed(&paths, true);
        let r = off(&paths, &mut f, true, false).unwrap();
        assert_eq!(f.ran, vec!["sudo pacman -R --noconfirm paru"]);
        assert!(r.detail.contains("removed"));
        assert!(!installed_by_bromigos(&paths));
        // on again: the setting, and paru back when there's no helper
        let mut f = Fake {
            answers: vec![("pacman -Si paru", 0, "")],
            ran: vec![],
        };
        on(&paths, &mut f, false, false).unwrap();
        assert!(enabled(&paths));
        assert_eq!(f.ran, vec!["sudo pacman -S --needed paru"]);
    }

    #[test]
    fn the_setting_defaults_on_and_keeps_its_comments() {
        let d = tempfile::tempdir().unwrap();
        let paths = Paths::from_lookup(|k| match k {
            "HOME" => Some(d.path().to_path_buf()),
            _ => None,
        });
        assert!(setting(&paths).enabled);
        assert!(!setting(&paths).exists);
        set_enabled(&paths, false).unwrap();
        let text = fs::read_to_string(path(&paths)).unwrap();
        assert!(text.starts_with("# The AUR and bromigOS"), "{text}");
        assert!(!enabled(&paths));
        fs::write(path(&paths), "# mine\nenabled = false\nother = 1\n").unwrap();
        set_enabled(&paths, true).unwrap();
        let text = fs::read_to_string(path(&paths)).unwrap();
        assert_eq!(text, "# mine\nenabled = true\nother = 1\n");
        fs::write(path(&paths), "enabled = \"no\"\n").unwrap();
        let s = setting(&paths);
        assert!(s.enabled && !s.problems.is_empty());
    }
}
