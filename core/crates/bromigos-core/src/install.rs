//! `bromigos install`: everything after the repository is set up (install.sh adds the
//! repository and its key, installs bromigos-core, then runs this).
//!
//! 1. preflight: a regular user with sudo, on Arch, with the `[bromigos]` repository;
//! 2. packages: `sudo pacman -S --needed bromigos <extras>`; then bromigOS's paru, the AUR
//!    helper, unless the AUR is off here (`--no-aur`) or a helper is installed
//!    ([`crate::aur`]: from bromigOS's repository, never the AUR; never fatal); then the
//!    `<extras>` no synced repository has (1password, which the public mirror leaves out)
//!    from the AUR with that helper ([`split_extras`]);
//! 3. system services: NetworkManager, SDDM (unless another display manager is enabled),
//!    Bluetooth when bluez is installed; user services: PipeWire and WirePlumber;
//!    then snapshots and the boot menu for rolling an update back, where / is btrfs
//!    ([`crate::snapshot`]);
//!    then the hardware: the GPU's drivers, early KMS, a hybrid laptop's render GPU, a
//!    laptop's power profiles ([`crate::hw`]; docs/hardware.md);
//! 4. the user's configs: the pending migrations (they seed the thin `~/.config` files);
//! 5. the desktop settings: GTK, icon and cursor theme, the UI font (only where unset);
//! 6. the theme: the current one again, or the chosen one (default wick);
//! 7. the boot menu: bromigOS's GRUB theme in its colours, where GRUB boots the machine
//!    ([`crate::boot`]; unless `bromigos boot theme off` turned it off here).
//!
//! Every step checks first and changes only what differs, so running it again is safe.
//! Commands go through a [`Runner`], so `--dry-run` prints them and tests record them.
//! The first-run questions are `bromigos setup` (it runs after this unless told not to).

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use serde::Serialize;

use crate::paths::Paths;
use crate::theme;

/// The meta-package that pulls in the whole of bromigOS.
pub const META: &str = "bromigos";

/// Files a hand install (before the packages existed) left in `/usr/share`, unowned:
/// pacman refuses to overwrite them unless told, so the package step names them.
pub const PRE_PACKAGE_PATHS: &[&str] = &[
    "/usr/share/sddm/themes/bromigos",
    "/usr/share/icons/Bromigos",
    "/usr/share/icons/Bromigos-cursor",
    "/usr/share/themes/Bromigos",
];

/// Network managers bromigOS won't fight: when one is enabled, NetworkManager isn't.
pub const OTHER_NETWORK: &[&str] = &[
    "systemd-networkd.service",
    "iwd.service",
    "connman.service",
    "dhcpcd.service",
    "netctl.service",
    "wicd.service",
];

/// How a step went.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    /// It changed something.
    Done,
    /// Nothing to do: already as it should be.
    Ok,
    /// Left alone on purpose (the detail says why).
    Skipped,
    /// --dry-run: what it would run is in `commands`.
    Planned,
    Failed,
}

/// One step's outcome.
#[derive(Debug, Clone, Serialize)]
pub struct Step {
    pub name: &'static str,
    pub status: Status,
    pub detail: String,
    /// The commands it ran (or, with --dry-run, would run).
    pub commands: Vec<String>,
}

/// The whole run.
#[derive(Debug, Clone, Serialize)]
pub struct Report {
    pub dry_run: bool,
    pub steps: Vec<Step>,
    pub ok: bool,
    pub log: PathBuf,
}

/// What `bromigos install` was asked to do.
#[derive(Debug, Clone)]
pub struct Options {
    pub dry_run: bool,
    /// Optional packages too (e.g. bromigos-homelab, herdr, ollama).
    pub extras: Vec<String>,
    /// Answer pacman's questions with their defaults (unattended installs, the VM test).
    pub yes: bool,
    /// Don't touch services.
    pub no_services: bool,
    /// Enable SDDM even when another display manager is enabled.
    pub force_dm: bool,
    /// The theme to set when none is set yet.
    pub theme: String,
    /// Leave the hardware alone (no drivers, no system files; `bromigos hw setup` later).
    pub no_hardware: bool,
    /// No AUR helper (`--no-aur`, or setup's answers `[aur] mode = "off"`): the AUR is
    /// turned off here before anything runs, so the migrations see it too (docs/aur.md).
    pub no_aur: bool,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            dry_run: false,
            extras: vec![],
            yes: false,
            no_services: false,
            force_dm: false,
            theme: "wick".into(),
            no_hardware: false,
            no_aur: false,
        }
    }
}

/// Runs commands (or doesn't). `interactive` commands keep the terminal (pacman's
/// prompts, sudo's password); the others are captured.
pub trait Runner {
    /// Exit code and combined output (empty for interactive ones).
    fn run(&mut self, argv: &[String], interactive: bool) -> std::io::Result<(i32, String)>;
    /// A read-only query (always runs, even in a dry run): exit code and stdout.
    fn query(&mut self, argv: &[&str]) -> (i32, String) {
        match Command::new(argv[0])
            .args(&argv[1..])
            .stderr(Stdio::null())
            .output()
        {
            Ok(o) => (
                o.status.code().unwrap_or(-1),
                String::from_utf8_lossy(&o.stdout).into_owned(),
            ),
            Err(_) => (127, String::new()),
        }
    }
}

/// Runs them for real.
pub struct System;

impl Runner for System {
    fn run(&mut self, argv: &[String], interactive: bool) -> std::io::Result<(i32, String)> {
        let mut c = Command::new(&argv[0]);
        c.args(&argv[1..]);
        if interactive {
            let s = c.status()?;
            return Ok((s.code().unwrap_or(-1), String::new()));
        }
        let o = c.stdin(Stdio::null()).output()?;
        let mut out = String::from_utf8_lossy(&o.stdout).into_owned();
        out.push_str(&String::from_utf8_lossy(&o.stderr));
        Ok((o.status.code().unwrap_or(-1), out))
    }
}

pub fn shell_line(argv: &[String]) -> String {
    argv.iter()
        .map(|a| {
            if a.chars()
                .all(|c| c.is_ascii_alphanumeric() || "-_./=:+@,".contains(c))
            {
                a.clone()
            } else {
                format!("'{}'", a.replace('\'', "'\\''"))
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn argv(parts: &[&str]) -> Vec<String> {
    parts.iter().map(|s| s.to_string()).collect()
}

/// The log: `~/.local/state/bromigos/install.log`.
pub fn log_path(paths: &Paths) -> PathBuf {
    paths.state_home.join("bromigos/install.log")
}

struct Log(Option<fs::File>);

impl Log {
    fn open(p: &Path) -> Self {
        let _ = fs::create_dir_all(p.parent().unwrap_or(Path::new("/")));
        Log(fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(p)
            .ok())
    }
    fn line(&mut self, s: &str) {
        if let Some(f) = &mut self.0 {
            let _ = writeln!(
                f,
                "{} {s}",
                chrono::Local::now().format("%Y-%m-%dT%H:%M:%S")
            );
        }
    }
}

/// One step's context: runs or plans commands and keeps the log.
struct Ctx<'a> {
    dry: bool,
    runner: &'a mut dyn Runner,
    log: Log,
}

impl Ctx<'_> {
    /// Runs (or plans) one command; Err(detail) when it fails.
    fn exec(
        &mut self,
        cmds: &mut Vec<String>,
        a: Vec<String>,
        interactive: bool,
    ) -> Result<(), String> {
        let line = shell_line(&a);
        cmds.push(line.clone());
        if self.dry {
            self.log.line(&format!("would run: {line}"));
            return Ok(());
        }
        self.log.line(&format!("run: {line}"));
        match self.runner.run(&a, interactive) {
            Ok((0, out)) => {
                for l in out.lines() {
                    self.log.line(&format!("  {l}"));
                }
                Ok(())
            }
            Ok((code, out)) => {
                for l in out.lines() {
                    self.log.line(&format!("  {l}"));
                }
                let last = out.lines().last().unwrap_or("").to_string();
                Err(format!(
                    "`{line}` exited {code}{}",
                    if last.is_empty() {
                        String::new()
                    } else {
                        format!(": {last}")
                    }
                ))
            }
            Err(e) => Err(format!("`{line}`: {e}")),
        }
    }
}

fn step(
    name: &'static str,
    status: Status,
    detail: impl Into<String>,
    commands: Vec<String>,
) -> Step {
    Step {
        name,
        status,
        detail: detail.into(),
        commands,
    }
}

/// Whether pacman.conf has a `[bromigos]` section.
pub fn has_repo(pacman_conf: &str) -> bool {
    pacman_conf.lines().any(|l| l.trim() == "[bromigos]")
}

/// The `--overwrite` globs for pre-package files: paths that exist and no package owns.
pub fn overwrite_globs(runner: &mut dyn Runner, existing: impl Fn(&str) -> bool) -> Vec<String> {
    PRE_PACKAGE_PATHS
        .iter()
        .filter(|p| existing(p))
        .filter(|p| runner.query(&["pacman", "-Qqo", p]).0 != 0)
        .map(|p| format!("{p}/*"))
        .collect()
}

/// The package step's command.
pub fn package_command(opts: &Options, overwrite: &[String]) -> Vec<String> {
    let mut a = argv(&["sudo", "pacman", "-S", "--needed"]);
    if opts.yes {
        a.push("--noconfirm".into());
    }
    for g in overwrite {
        a.push("--overwrite".into());
        a.push(g.clone());
    }
    a.push(META.into());
    a.extend(opts.extras.iter().cloned());
    a
}

/// The `--with` packages split by where they come from: (in the synced repositories, a
/// package or a group; not in them). The second lot is the AUR's: the public mirror of
/// `[bromigos]` leaves out what may not be redistributed (1password), so a public install
/// gets that from the AUR through the helper, as Arch users do (docs/aur.md).
pub fn split_extras(runner: &mut dyn Runner, extras: &[String]) -> (Vec<String>, Vec<String>) {
    extras.iter().cloned().partition(|x| {
        runner.query(&["pacman", "-Si", x]).0 == 0 || runner.query(&["pacman", "-Sg", x]).0 == 0
    })
}

/// The AUR step's command: the helper builds and installs them as this user.
pub fn aur_command(helper: crate::aur::Helper, yes: bool, pkgs: &[String]) -> Vec<String> {
    let mut a = argv(&[helper.bin(), "-S", "--needed"]);
    if yes {
        a.push("--noconfirm".into());
    }
    a.extend(pkgs.iter().cloned());
    a
}

/// Which display manager is enabled (the target of display-manager.service), if any.
pub fn enabled_dm(runner: &mut dyn Runner) -> Option<String> {
    let (_, out) = runner.query(&["systemctl", "show", "-P", "Id", "display-manager.service"]);
    let id = out.trim().trim_end_matches(".service").to_string();
    (!id.is_empty() && id != "display-manager").then_some(id)
}

fn installed(runner: &mut dyn Runner, pkg: &str) -> bool {
    runner.query(&["pacman", "-Qq", pkg]).0 == 0
}

/// The desktop settings bromigOS sets when they're still GNOME's defaults:
/// (gsettings key, value, the defaults it replaces).
pub const GSETTINGS: &[(&str, &str, &[&str])] = &[
    ("gtk-theme", "Bromigos", &["Adwaita", "Adwaita-dark", ""]),
    ("icon-theme", "Bromigos", &["Adwaita", "hicolor", ""]),
    (
        "cursor-theme",
        "Bromigos-cursor",
        &["Adwaita", "default", ""],
    ),
    (
        "font-name",
        "Geist Mono 11",
        &["Cantarell 11", "Adwaita Sans 11", ""],
    ),
    (
        "monospace-font-name",
        "Geist Mono 11",
        &["Source Code Pro 10", "Adwaita Mono 11", "Monospace 11", ""],
    ),
    ("color-scheme", "prefer-dark", &["default", ""]),
];

/// Runs `bromigos install` (steps 1-6 above).
pub fn run(paths: &Paths, opts: &Options, runner: &mut dyn Runner) -> Report {
    let log_file = log_path(paths);
    let mut cx = Ctx {
        dry: opts.dry_run,
        runner,
        log: Log::open(&log_file),
    };
    cx.log.line(&format!(
        "== bromigos install{}",
        if opts.dry_run { " --dry-run" } else { "" }
    ));
    let mut steps = vec![];

    // 1. preflight
    let root = rustix::process::geteuid().is_root();
    let conf_path = std::env::var_os("BROMIGOS_PACMAN_CONF")
        .map(PathBuf::from)
        .unwrap_or_else(|| "/etc/pacman.conf".into());
    let conf = fs::read_to_string(&conf_path).unwrap_or_default();
    let have_pacman = cx.runner.query(&["pacman", "--version"]).0 == 0;
    let have_sudo = cx.runner.query(&["sudo", "--version"]).0 == 0;
    let problem = if root {
        Some("run it as your own user (it uses sudo for the system steps), not as root")
    } else if !have_pacman {
        Some("pacman isn't here: bromigOS installs on Arch Linux")
    } else if !have_sudo {
        Some("sudo isn't installed: `pacman -S sudo` and allow your user")
    } else if !has_repo(&conf) {
        Some(
            "/etc/pacman.conf has no [bromigos] repository: run install.sh first (docs/install.md)",
        )
    } else {
        None
    };
    if let Some(p) = problem {
        steps.push(step("preflight", Status::Failed, p, vec![]));
        cx.log.line(&format!("preflight: {p}"));
        return Report {
            dry_run: opts.dry_run,
            ok: false,
            steps,
            log: log_file,
        };
    }
    steps.push(step(
        "preflight",
        Status::Ok,
        "Arch, sudo, the [bromigos] repository",
        vec![],
    ));

    // 2. packages
    let mut cmds = vec![];
    let overwrite = overwrite_globs(cx.runner, |p| Path::new(p).exists());
    let (repo_extras, aur_extras) = split_extras(cx.runner, &opts.extras);
    let pkg = package_command(
        &Options {
            extras: repo_extras.clone(),
            ..opts.clone()
        },
        &overwrite,
    );
    match cx.exec(&mut cmds, pkg, true) {
        Ok(()) => steps.push(step(
            "packages",
            if opts.dry_run {
                Status::Planned
            } else {
                Status::Done
            },
            if overwrite.is_empty() {
                format!("{META} {}", repo_extras.join(" "))
                    .trim()
                    .to_string()
            } else {
                format!(
                    "{META}; replacing the hand-installed {}",
                    overwrite.join(", ")
                )
            },
            cmds,
        )),
        Err(e) => {
            steps.push(step("packages", Status::Failed, e, cmds));
            return finish(cx, steps, opts, log_file);
        }
    }

    // 2b. the AUR helper (docs/aur.md): bromigOS's paru, from its own repository, unless the
    // AUR is off here or a helper is installed already. Never the AUR itself, and never in
    // the way: it isn't there yet (an older medium's offline copy) or pacman fails, and the
    // update's migration installs it later
    let mut cmds = vec![];
    let (status, detail) = if opts.no_aur {
        if !opts.dry_run
            && let Err(e) = crate::aur::set_enabled(paths, false)
        {
            cx.log.line(&format!("aur: {e}"));
        }
        (
            Status::Skipped,
            "left out (--no-aur, or the answers' [aur] mode = \"off\"): no AUR helper, and \
             bromigos update leaves the AUR alone (bromigos aur on)"
                .to_string(),
        )
    } else {
        match crate::aur::ensure(paths, cx.runner, opts.yes, opts.dry_run) {
            Ok(r) => {
                cmds = r.commands.clone();
                let status = match (r.ok, cmds.is_empty(), opts.dry_run) {
                    (false, _, _) => Status::Skipped,
                    (true, true, _) => Status::Ok,
                    (true, false, true) => Status::Planned,
                    (true, false, false) => Status::Done,
                };
                (status, r.detail)
            }
            Err(e) => (
                Status::Skipped,
                format!("couldn't install paru ({e}); the next bromigos update tries again"),
            ),
        }
    };
    for c in &cmds {
        cx.log.line(&format!(
            "{}: {c}",
            if opts.dry_run { "would run" } else { "run" }
        ));
    }
    cx.log.line(&format!("aur: {detail}"));
    let helper_planned = status == Status::Planned;
    steps.push(step("aur", status, detail, cmds));

    // 2c. the `--with` packages the repositories don't have (1password on the public
    // mirror), from the AUR with the helper. A failure shows, and the install goes on: the
    // desktop doesn't need them
    if !aur_extras.is_empty() {
        let names = aur_extras.join(" ");
        let helper = crate::aur::found(cx.runner)
            .helper
            .or(helper_planned.then_some(crate::aur::Helper::Paru));
        let mut cmds = vec![];
        let (status, detail) = if opts.no_aur || !crate::aur::enabled(paths) {
            (
                Status::Skipped,
                format!(
                    "{names}: not in the repositories, and the AUR is off here (bromigos aur on, \
                     then paru -S {names})"
                ),
            )
        } else if let Some(h) = helper {
            match cx.exec(&mut cmds, aur_command(h, opts.yes, &aur_extras), true) {
                Ok(()) if opts.dry_run => (Status::Planned, format!("{names}, from the AUR")),
                Ok(()) => (Status::Done, format!("{names}, from the AUR")),
                Err(e) => (Status::Failed, format!("{names} from the AUR: {e}")),
            }
        } else {
            (
                Status::Skipped,
                format!("{names}: not in the repositories, and no AUR helper here to get them"),
            )
        };
        cx.log.line(&format!("aur packages: {detail}"));
        steps.push(step("aur packages", status, detail, cmds));
    }

    // 3. services
    if opts.no_services {
        steps.push(step("services", Status::Skipped, "--no-services", vec![]));
    } else {
        let mut cmds = vec![];
        let mut notes = vec![];
        let mut failed = None;
        let mut system = vec![];
        // the network: NetworkManager, unless the machine already runs another manager
        let others: Vec<&str> = OTHER_NETWORK
            .iter()
            .copied()
            .filter(|u| cx.runner.query(&["systemctl", "is-enabled", u]).1.trim() == "enabled")
            .collect();
        if others.is_empty() {
            system.push("NetworkManager.service");
        } else {
            notes.push(format!(
                "networking stays with {} (NetworkManager is installed, not enabled)",
                others
                    .iter()
                    .map(|u| u.trim_end_matches(".service"))
                    .collect::<Vec<_>>()
                    .join(" and ")
            ));
        }
        match enabled_dm(cx.runner) {
            Some(dm) if dm != "sddm" && !opts.force_dm => {
                notes.push(format!(
                    "{dm} is the display manager; left as is (bromigos install --force-dm switches to SDDM)"
                ));
            }
            _ => system.push("sddm.service"),
        }
        // after a fresh `pacman -S` in a dry run bluez may not be there yet: only if installed
        if installed(cx.runner, "bluez") {
            system.push("bluetooth.service");
        }
        let need: Vec<&str> = system
            .into_iter()
            .filter(|u| cx.runner.query(&["systemctl", "is-enabled", u]).1.trim() != "enabled")
            .collect();
        if !need.is_empty() {
            let mut a = argv(&["sudo", "systemctl", "enable"]);
            if opts.force_dm && need.contains(&"sddm.service") {
                a.push("--force".into());
            }
            a.extend(need.iter().map(|s| s.to_string()));
            if let Err(e) = cx.exec(&mut cmds, a, true) {
                failed = Some(e);
            }
        }
        let user = [
            "pipewire.socket",
            "pipewire-pulse.socket",
            "wireplumber.service",
        ];
        let need_user: Vec<&str> = user
            .into_iter()
            .filter(|u| {
                cx.runner
                    .query(&["systemctl", "--user", "is-enabled", u])
                    .1
                    .trim()
                    != "enabled"
            })
            .collect();
        if failed.is_none() && !need_user.is_empty() {
            let mut a = argv(&["systemctl", "--user", "enable"]);
            a.extend(need_user.iter().map(|s| s.to_string()));
            if let Err(e) = cx.exec(&mut cmds, a, false) {
                failed = Some(e);
            }
        }
        let status = match (&failed, cmds.is_empty(), opts.dry_run) {
            (Some(_), _, _) => Status::Failed,
            (None, true, _) => Status::Ok,
            (None, false, true) => Status::Planned,
            (None, false, false) => Status::Done,
        };
        let mut detail = failed.unwrap_or_else(|| {
            if cmds.is_empty() {
                "all enabled".into()
            } else {
                "enabled (they start at the next boot)".into()
            }
        });
        if !notes.is_empty() {
            detail = format!("{detail}; {}", notes.join("; "));
        }
        let bad = status == Status::Failed;
        steps.push(step("services", status, detail, cmds));
        if bad {
            return finish(cx, steps, opts, log_file);
        }
    }

    // 3b. snapshots and the boot menu (docs/update.md): snap-pac around pacman, grub-btrfs
    // on GRUB (limine-snapper-sync on limine, when a repository has it); only where / is btrfs
    if opts.no_services {
        steps.push(step("rollback", Status::Skipped, "--no-services", vec![]));
    } else {
        let env = crate::snapshot::detect(cx.runner, &crate::snapshot::RootFs);
        let who = crate::snapshot::who(cx.runner);
        let mut plan = crate::snapshot::setup_plan(&env, cx.runner, &crate::snapshot::RootFs, &who);
        if opts.yes {
            // unattended: pacman must not stop to ask (it waited forever in the VM test)
            plan.noconfirm();
        }
        let mut cmds = vec![];
        let mut failed = None;
        for a in &plan.commands {
            if let Err(e) = cx.exec(&mut cmds, a.clone(), true) {
                failed = Some(e);
                break;
            }
        }
        // a configuration that exists but doesn't let the user list it: wheel allowed
        if failed.is_none() && plan.allow {
            cmds.push("bromigos rollback allow".into());
            if !cx.dry {
                match crate::snapshot::allow(&env, cx.runner, &who) {
                    Ok(Some(set)) => cx.log.line(&format!("run: {}", shell_line(&set))),
                    Ok(None) => cx.log.line("rollback allow: nothing to change"),
                    Err(e) => failed = Some(format!("bromigos rollback allow: {e}")),
                }
            }
        }
        let mut detail = plan.notes.join("; ");
        if cmds.is_empty() && detail.is_empty() {
            detail = format!("already set up: {}", env.summary());
        } else if detail.is_empty() {
            detail = env.summary();
        }
        let status = match (&failed, cmds.is_empty(), opts.dry_run) {
            (Some(_), _, _) => Status::Failed,
            (None, true, _) => Status::Ok,
            (None, false, true) => Status::Planned,
            (None, false, false) => Status::Done,
        };
        steps.push(step("rollback", status, failed.unwrap_or(detail), cmds));
    }

    // 3c. the hardware (docs/hardware.md): the GPU's drivers, NVIDIA's early KMS, a hybrid
    // laptop's render GPU, a laptop's power profiles; a machine that has its driver keeps it.
    // A failure here is reported and the install goes on: the desktop runs without them.
    if opts.no_hardware {
        steps.push(step(
            "hardware",
            Status::Skipped,
            "--no-hardware (bromigos hw setup, any time)",
            vec![],
        ));
    } else {
        let d = crate::hw::detect(&crate::snapshot::RootFs);
        let plan = crate::hw::plan(paths, &d, cx.runner, &crate::snapshot::RootFs);
        for n in &plan.notes {
            cx.log.line(&format!("hardware: {n}"));
        }
        let hw_opts = crate::hw::ApplyOpts {
            yes: opts.yes,
            user_only: false,
            no_services: opts.no_services,
            now: false,
            // the installer never builds from the AUR: a driver only the AUR has is a note
            // (`bromigos hw setup` offers it, and asks)
            aur_driver: false,
        };
        let dry = cx.dry;
        let applied = crate::hw::apply(paths, &plan, &hw_opts, dry, &mut |a, interactive| {
            let mut ignored = vec![];
            cx.exec(&mut ignored, a, interactive)
        });
        let status = match (applied.ok, plan.done(), opts.dry_run) {
            (false, _, _) => Status::Failed,
            (true, true, _) => Status::Ok,
            (true, false, true) => Status::Planned,
            (true, false, false) => Status::Done,
        };
        let mut detail = format!("{}: {}", crate::hw::summary(&d), applied.detail);
        if !plan.notes.is_empty() {
            detail.push_str(&format!(" (note: {})", plan.notes.join("; ")));
        }
        if applied.reboot && applied.ok && !opts.dry_run {
            detail.push_str("; takes effect at the next boot");
        }
        steps.push(step("hardware", status, detail, applied.commands));
    }

    // 4. the user's configs: the migrations (they seed ~/.config's thin files)
    if opts.dry_run {
        let pending: Vec<String> = crate::migrate::pending(paths)
            .into_iter()
            .map(|m| m.id)
            .collect();
        steps.push(step(
            "configs",
            if pending.is_empty() {
                Status::Ok
            } else {
                Status::Planned
            },
            if pending.is_empty() {
                "no migrations pending (the packages' own may add some)".to_string()
            } else {
                format!("migrations: {}", pending.join(", "))
            },
            vec![],
        ));
    } else {
        let (ran, ok) = crate::migrate::run_pending(paths, &[]);
        for r in &ran {
            cx.log.line(&format!("migration {}: {:?}", r.id, r.outcome));
        }
        let names: Vec<&str> = ran.iter().map(|r| r.id.as_str()).collect();
        steps.push(step(
            "configs",
            if !ok {
                Status::Failed
            } else if ran.is_empty() {
                Status::Ok
            } else {
                Status::Done
            },
            if ran.is_empty() {
                "nothing pending".to_string()
            } else {
                format!("migrations: {}", names.join(", "))
            },
            vec![],
        ));
        if !ok {
            return finish(cx, steps, opts, log_file);
        }
    }

    // 5. desktop settings (GTK, icons, cursor, font), where they're still the defaults
    let mut cmds = vec![];
    let mut failed = None;
    if cx.runner.query(&["gsettings", "--version"]).0 == 0 {
        for (key, want, defaults) in GSETTINGS {
            let (_, now) =
                cx.runner
                    .query(&["gsettings", "get", "org.gnome.desktop.interface", key]);
            let now = now.trim().trim_matches('\'');
            if now == *want || !defaults.contains(&now) {
                continue;
            }
            let a = argv(&["gsettings", "set", "org.gnome.desktop.interface", key, want]);
            if let Err(e) = cx.exec(&mut cmds, a, false) {
                failed = Some(e);
                break;
            }
        }
        steps.push(step(
            "desktop settings",
            match (&failed, cmds.is_empty(), opts.dry_run) {
                (Some(_), _, _) => Status::Failed,
                (None, true, _) => Status::Ok,
                (None, false, true) => Status::Planned,
                (None, false, false) => Status::Done,
            },
            failed.clone().unwrap_or_else(|| {
                if cmds.is_empty() {
                    "already set (or the user's own)".into()
                } else {
                    "GTK, icons, cursor, font".into()
                }
            }),
            cmds,
        ));
    } else {
        steps.push(step(
            "desktop settings",
            Status::Skipped,
            "gsettings isn't installed",
            vec![],
        ));
    }

    // 6. the theme
    let cur = theme::current(paths);
    let name = if cur.set {
        cur.name.clone()
    } else {
        opts.theme.clone()
    };
    if opts.dry_run {
        steps.push(step(
            "theme",
            Status::Planned,
            format!("bromigos theme set {name}"),
            vec![format!("bromigos theme set {name}")],
        ));
    } else {
        match theme::set(paths, &name) {
            Ok(_) => {
                let _ = theme::run_hooks(paths);
                cx.log.line(&format!("theme: {name}"));
                steps.push(step("theme", Status::Done, name, vec![]));
            }
            Err(e) => steps.push(step("theme", Status::Failed, e.to_string(), vec![])),
        }
    }

    // 7. the boot menu (docs/boot.md): GRUB's theme on, in the theme's colours
    let o = crate::boot::sync(
        paths,
        cx.runner,
        &crate::snapshot::RootFs,
        crate::boot::Enable::Auto,
        true,
        opts.dry_run,
    );
    for c in &o.commands {
        cx.log.line(&format!("boot menu: {c}"));
    }
    cx.log
        .line(&format!("boot menu: {}: {}", o.status, o.detail));
    let status = match o.status {
        "done" => Status::Done,
        "ok" => Status::Ok,
        "planned" => Status::Planned,
        "failed" => Status::Failed,
        _ => Status::Skipped,
    };
    steps.push(step("boot menu", status, o.detail, o.commands));
    finish(cx, steps, opts, log_file)
}

fn finish(mut cx: Ctx<'_>, steps: Vec<Step>, opts: &Options, log: PathBuf) -> Report {
    let ok = steps.iter().all(|s| s.status != Status::Failed);
    cx.log
        .line(&format!("== {}", if ok { "done" } else { "stopped" }));
    Report {
        dry_run: opts.dry_run,
        steps,
        ok,
        log,
    }
}
