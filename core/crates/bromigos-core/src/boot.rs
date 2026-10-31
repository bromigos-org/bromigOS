//! The boot menu: bromigOS's GRUB theme, in the current theme's colours (docs/boot.md).
//!
//! "Tuning into the relay": GRUB shows the Wick's console, the burn-in exactly where the
//! Plymouth splash puts it, a signal meter for the timeout and the channel list under it;
//! grub-btrfs's snapshots read like the rollback list (`10/09 00:28 · before bromigos
//! update`). The pieces, in `bromigos-boot`:
//!
//! - `/usr/share/bromigos/boot/grub/themes/<theme>/`: a boot theme per shipped theme,
//!   rendered when the package is built (its colours, its lock-screen image, its emblem);
//! - `/usr/lib/bromigos/boot/build-grub-theme.py`: the generator, which renders the user's
//!   theme in force when there's no packaged one (a theme of their own, an overlay, high
//!   contrast) into `~/.local/state/bromigos/boot/grub/`;
//! - `/usr/lib/bromigos/boot/bromigos-boot-theme`: the root helper. It copies a theme into
//!   `/boot/grub/themes/bromigos` (a packaged one by name; a user's render only after
//!   checking every picture, writing theme.txt itself), keeps bromigOS's block in
//!   `/etc/default/grub` (GRUB_THEME, GRUB_GFXMODE=auto, GRUB_TERMINAL_OUTPUT=gfxterm,
//!   GRUB_DISTRIBUTOR=bromigOS, grub-btrfs's titles) and makes grub.cfg again only through
//!   grub-mkconfig and grub-script-check, putting `/etc/default/grub` back if that fails.
//!   Its state is `/var/lib/bromigos/boot/state.json`, which anyone may read.
//!
//! This module decides: whether GRUB boots this machine ([`crate::snapshot::bootloader`];
//! systemd-boot and limine are left alone), what the current theme wants in /boot, whether
//! /boot has it, and runs the helper with sudo when it doesn't. `bromigos install`,
//! `bromigos setup` and a migration turn it on (unless `bromigos boot theme off` turned it
//! off here); `bromigos update` keeps /boot on the current theme; `bromigos theme set` does
//! too when sudo needn't ask (its `boot` hook), else the next update does and says so.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

use serde::{Deserialize, Serialize};

use crate::install::Runner;
use crate::paths::Paths;
use crate::snapshot::{self, Bootloader, Files};

/// The root helper (bromigos-boot).
pub const HELPER: &str = "/usr/lib/bromigos/boot/bromigos-boot-theme";
/// The generator (bromigos-boot).
pub const GENERATOR: &str = "/usr/lib/bromigos/boot/build-grub-theme.py";
/// What the helper last did, readable by anyone.
pub const STATE: &str = "/var/lib/bromigos/boot/state.json";
pub const DEFAULT_GRUB: &str = "/etc/default/grub";
pub const GRUB_CFG: &str = "/boot/grub/grub.cfg";
/// The first line of bromigOS's block in /etc/default/grub (the helper writes it).
pub const BLOCK: &str = "# >>> bromigOS boot menu";

/// What the helper last did (`state.json`).
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default)]
pub struct Applied {
    /// The theme is on (the block is in /etc/default/grub).
    pub enabled: bool,
    /// `bromigos boot theme off` was run here: install, setup and the migration leave it off.
    pub opted_out: bool,
    /// The theme in /boot.
    pub theme: Option<String>,
    /// `package` (pre-rendered) or `user` (rendered from the user's theme).
    pub source: Option<String>,
    /// What identifies its pictures and colours (the generator's manifest's `digest`).
    pub digest: Option<String>,
    pub at: Option<String>,
}

/// What the current theme wants in /boot.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Want {
    /// The theme bromigos-boot rendered for it.
    Package { theme: String, digest: String },
    /// A render of the user's theme in force (why there's no packaged one).
    Render { theme: String, why: String },
}

impl Want {
    pub fn theme(&self) -> &str {
        match self {
            Want::Package { theme, .. } | Want::Render { theme, .. } => theme,
        }
    }
}

/// Where the boot menu stands (`bromigos boot theme status`).
#[derive(Debug, Clone, Serialize)]
pub struct Status {
    pub bootloader: Bootloader,
    /// GRUB's grub.cfg is in /boot (None: /boot can't be read as this user, archinstall's
    /// 0700 ESP: the helper looks as root).
    pub grub_installed: Option<bool>,
    /// The theme is on: bromigOS's block is in /etc/default/grub.
    pub on: bool,
    pub applied: Applied,
    pub want: Want,
    /// /boot has what the theme wants (None: a render's, known once it's rendered).
    pub current: Option<bool>,
    /// The helper is installed (bromigos-boot).
    pub helper: bool,
    /// Why it's left alone, or what keeps it from showing.
    pub note: Option<String>,
}

impl Status {
    /// GRUB boots this machine, as far as can be seen from here.
    pub fn grub(&self) -> bool {
        self.bootloader == Bootloader::Grub && self.grub_installed != Some(false)
    }

    /// One line: `bromigos boot theme status`, `bromigos update --check`.
    pub fn summary(&self) -> String {
        match self.bootloader {
            Bootloader::SystemdBoot => {
                return "systemd-boot: left alone (the boot theme is GRUB's)".into();
            }
            Bootloader::Limine => return "limine: left alone (the boot theme is GRUB's)".into(),
            Bootloader::Unknown => {
                return "the boot loader wasn't recognised: nothing themed".into();
            }
            Bootloader::Grub => {}
        }
        if self.grub_installed == Some(false) {
            return format!("GRUB isn't installed in /boot (no {GRUB_CFG}): nothing themed");
        }
        if !self.helper {
            return "GRUB: bromigos-boot isn't installed (no boot themes)".into();
        }
        if !self.on {
            return if self.applied.opted_out {
                "GRUB: its own menu, turned off here (bromigos boot theme on)".into()
            } else {
                "GRUB: its own menu (bromigos boot theme on)".into()
            };
        }
        let have = self.applied.theme.as_deref().unwrap_or("?");
        let mut s = match (&self.want, self.current) {
            (_, Some(true)) => format!(
                "GRUB: {have} ({}), up to date",
                if self.applied.source.as_deref() == Some("user") {
                    "rendered from yours"
                } else {
                    "the package's"
                }
            ),
            (w, Some(false)) => format!(
                "GRUB: {have} in /boot, {} wanted (bromigos boot theme apply, or the next \
                 bromigos update)",
                w.theme()
            ),
            (Want::Render { theme, why }, None) => {
                format!("GRUB: {have} in /boot; {theme} is rendered for it ({why}) when applied")
            }
            (Want::Package { .. }, None) => format!("GRUB: {have}"),
        };
        if let Some(n) = &self.note {
            s.push_str(&format!("; {n}"));
        }
        s
    }
}

fn lib_dir() -> PathBuf {
    std::env::var_os("BROMIGOS_BOOT_LIB")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/usr/lib/bromigos/boot"))
}

fn helper_path() -> PathBuf {
    lib_dir().join("bromigos-boot-theme")
}

fn generator_path() -> PathBuf {
    lib_dir().join("build-grub-theme.py")
}

/// The packaged boot themes: `<share>/boot/grub/themes`.
pub fn packaged(paths: &Paths) -> PathBuf {
    paths.share_dir.join("boot/grub/themes")
}

/// Where the user's render goes: `~/.local/state/bromigos/boot/grub`.
pub fn render_dir(paths: &Paths) -> PathBuf {
    paths.user_state_dir().join("boot/grub")
}

/// `state.json`, as the helper wrote it (default when it hasn't).
pub fn applied(files: &dyn Files) -> Applied {
    files
        .read(STATE)
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

/// Whether bromigOS's block is in /etc/default/grub.
pub fn block_in(default_grub: &str) -> bool {
    default_grub.lines().any(|l| l.trim().starts_with(BLOCK))
}

/// `GRUB_TERMINAL=console` (or serial) outside the block keeps GRUB in text.
pub fn terminal_note(default_grub: &str) -> Option<String> {
    let mut inside = false;
    for l in default_grub.lines() {
        let t = l.trim();
        if t.starts_with(BLOCK) {
            inside = true;
        } else if t.starts_with("# <<< bromigOS boot menu") {
            inside = false;
        } else if !inside && let Some(v) = t.strip_prefix("GRUB_TERMINAL=") {
            let v = v.trim_matches(|c| c == '"' || c == '\'');
            if !v.contains("gfxterm") {
                return Some(format!(
                    "/etc/default/grub sets GRUB_TERMINAL={v}, which keeps GRUB in text"
                ));
            }
        }
    }
    None
}

fn manifest_digest(text: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(text).ok()?;
    v.get("digest")?.as_str().map(str::to_owned)
}

/// What the current theme wants in /boot: the package's render of it, unless the colours
/// are the user's own (their theme, their overlay of a shipped one, high contrast).
pub fn want(paths: &Paths) -> Want {
    let name = crate::theme::current(paths).name;
    let loc = crate::theme::Locations::new(paths);
    let render = |why: &str| Want::Render {
        theme: name.clone(),
        why: why.to_owned(),
    };
    if crate::accessibility::read(paths).high_contrast() {
        return render("high contrast");
    }
    if loc.user_themes.join(&name).is_dir() {
        return render("your overlay of it");
    }
    let manifest = packaged(paths).join(&name).join("manifest.json");
    match fs::read_to_string(&manifest)
        .ok()
        .as_deref()
        .and_then(manifest_digest)
    {
        Some(digest) => Want::Package {
            theme: name,
            digest,
        },
        None if loc.ext_themes.join(&name).exists() => render("an extension's theme"),
        None => render("not a theme bromigOS ships"),
    }
}

/// Looks at the machine.
pub fn status(paths: &Paths, runner: &mut dyn Runner, files: &dyn Files) -> Status {
    let offline = snapshot::chrooted(files);
    let bootloader = snapshot::bootloader(runner, files, offline);
    let grub_installed = if files.list("/boot").is_empty() {
        None
    } else {
        Some(files.exists(GRUB_CFG))
    };
    let default_grub = files.read(DEFAULT_GRUB).unwrap_or_default();
    let applied = applied(files);
    let want = want(paths);
    let on = block_in(&default_grub);
    // a render's digest is known once it's rendered (sync renders it, when its inputs changed)
    let current = match &want {
        Want::Package { theme, digest } => Some(
            on && applied.theme.as_deref() == Some(theme)
                && applied.digest.as_deref() == Some(digest),
        ),
        Want::Render { .. } => None,
    };
    Status {
        bootloader,
        grub_installed,
        on,
        applied,
        want,
        current,
        helper: files.exists(&helper_path().to_string_lossy()),
        note: terminal_note(&default_grub),
    }
}

/// How [`sync`] may change the machine.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Enable {
    /// Turn it on (`bromigos boot theme on`): also where it was turned off before.
    On,
    /// Turn it on unless it was turned off here (install, setup, the migration).
    Auto,
    /// Only keep /boot on the current theme where it's on (update, the theme-set hook).
    Keep,
}

/// What [`sync`] did.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct Outcome {
    /// done, ok (nothing to do), skipped (not here: the detail says why), deferred (sudo
    /// would have asked: the next update does it), failed
    pub status: &'static str,
    pub detail: String,
    pub commands: Vec<String>,
}

fn outcome(status: &'static str, detail: impl Into<String>, commands: Vec<String>) -> Outcome {
    Outcome {
        status,
        detail: detail.into(),
        commands,
    }
}

/// The user's theme in force, rendered for the boot menu (only when its colours, picture or
/// emblem changed since the last render): its directory and digest.
pub fn render(paths: &Paths) -> Result<(PathBuf, String), String> {
    let out = render_dir(paths);
    let o = Command::new("python3")
        .arg("-I")
        .arg(generator_path())
        .args(["--current", "--no-fonts", "--if-changed", "--json", "--out"])
        .arg(&out)
        .env("XDG_STATE_HOME", &paths.state_home)
        .env("BROMIGOS_SHARE_DIR", &paths.share_dir)
        .output()
        .map_err(|e| format!("{}: {e}", generator_path().display()))?;
    if !o.status.success() {
        let err = String::from_utf8_lossy(&o.stderr);
        return Err(format!(
            "the boot theme didn't render: {}",
            err.trim().lines().last().unwrap_or("")
        ));
    }
    let digest = manifest_digest(&String::from_utf8_lossy(&o.stdout))
        .ok_or("the generator printed no digest")?;
    Ok((out, digest))
}

/// Brings /boot to the current theme (and, with [`Enable::On`] or [`Enable::Auto`], turns
/// the theme on): the helper with sudo, `sudo -n` without `prompt` (then a password
/// needed means the next update does it). `dry` says what it would run.
pub fn sync(
    paths: &Paths,
    runner: &mut dyn Runner,
    files: &dyn Files,
    enable: Enable,
    prompt: bool,
    dry: bool,
) -> Outcome {
    let st = status(paths, runner, files);
    if !st.grub() || !st.helper {
        return outcome("skipped", st.summary(), vec![]);
    }
    match enable {
        Enable::Keep if !st.on => return outcome("skipped", st.summary(), vec![]),
        Enable::Auto if st.applied.opted_out && !st.on => {
            return outcome("skipped", st.summary(), vec![]);
        }
        _ => {}
    }
    if st.on && st.current == Some(true) {
        return outcome("ok", st.summary(), vec![]);
    }
    let (source, digest, what): (Vec<String>, String, String) = match &st.want {
        Want::Package { theme, digest } => (
            vec!["--theme".into(), theme.clone()],
            digest.clone(),
            format!("{theme} (the package's)"),
        ),
        Want::Render { theme, why } => {
            if dry {
                (
                    vec!["--from".into(), render_dir(paths).display().to_string()],
                    String::new(),
                    format!("{theme} (rendered: {why})"),
                )
            } else {
                match render(paths) {
                    Ok((dir, d)) => (
                        vec!["--from".into(), dir.display().to_string()],
                        d,
                        format!("{theme} (rendered: {why})"),
                    ),
                    Err(e) => return outcome("failed", e, vec![]),
                }
            }
        }
    };
    if st.on && !digest.is_empty() && st.applied.digest.as_deref() == Some(digest.as_str()) {
        return outcome("ok", format!("{what}, up to date"), vec![]);
    }
    let verb = if st.on { "apply" } else { "on" };
    let mut argv: Vec<String> = vec!["sudo".into()];
    if !prompt {
        argv.push("-n".into());
    }
    argv.push(helper_path().display().to_string());
    argv.push(verb.into());
    argv.extend(source);
    if enable == Enable::Auto && verb == "on" {
        argv.push("--auto".into());
    }
    let line = crate::install::shell_line(&argv);
    if dry {
        return outcome("planned", what, vec![line]);
    }
    match runner.run(&argv, prompt) {
        Ok((0, out)) => {
            if out.contains("turned off") {
                return outcome("skipped", out.trim().to_owned(), vec![line]);
            }
            outcome(
                "done",
                if verb == "on" {
                    format!("on: {what}")
                } else {
                    format!("{what} in /boot")
                },
                vec![line],
            )
        }
        Ok((4, out)) => outcome(
            "skipped",
            out.trim()
                .lines()
                .last()
                .unwrap_or("GRUB doesn't boot this machine")
                .trim_start_matches("bromigos-boot-theme: ")
                .to_owned(),
            vec![line],
        ),
        Ok((1, out)) if !prompt && out.contains("password") => outcome(
            "deferred",
            format!(
                "the boot menu takes {} at the next bromigos update (sudo would ask for your password)",
                st.want.theme()
            ),
            vec![line],
        ),
        Ok((code, out)) => outcome(
            "failed",
            format!(
                "`{line}` exited {code}: {}",
                out.trim()
                    .lines()
                    .last()
                    .unwrap_or("")
                    .trim_start_matches("bromigos-boot-theme: ")
            ),
            vec![line],
        ),
        Err(e) => outcome("failed", format!("`{line}`: {e}"), vec![line]),
    }
}

/// `bromigos boot theme off`: GRUB's own menu, and this machine stays off until `on`.
pub fn off(runner: &mut dyn Runner, files: &dyn Files, dry: bool) -> Outcome {
    if !files.exists(&helper_path().to_string_lossy()) {
        return outcome(
            "skipped",
            "bromigos-boot isn't installed: there's no boot theme to turn off",
            vec![],
        );
    }
    let argv: Vec<String> = vec![
        "sudo".into(),
        helper_path().display().to_string(),
        "off".into(),
    ];
    let line = crate::install::shell_line(&argv);
    if dry {
        return outcome("planned", "off", vec![line]);
    }
    match runner.run(&argv, true) {
        Ok((0, _)) => outcome(
            "done",
            "off: GRUB's own menu (bromigos boot theme on turns it back on)",
            vec![line],
        ),
        Ok((code, out)) => outcome(
            "failed",
            format!("`{line}` exited {code}: {}", out.trim()),
            vec![line],
        ),
        Err(e) => outcome("failed", format!("`{line}`: {e}"), vec![line]),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    struct FakeFs(BTreeMap<String, String>);

    impl FakeFs {
        fn with(mut self, path: &str, text: &str) -> Self {
            self.0.insert(path.to_owned(), text.to_owned());
            self
        }
    }

    impl Files for FakeFs {
        fn exists(&self, path: &str) -> bool {
            self.0.contains_key(path) || self.0.keys().any(|k| k.starts_with(&format!("{path}/")))
        }
        fn read(&self, path: &str) -> Option<String> {
            self.0.get(path).cloned()
        }
        fn list(&self, dir: &str) -> Vec<String> {
            let p = format!("{dir}/");
            let mut v: Vec<String> = self
                .0
                .keys()
                .filter_map(|k| k.strip_prefix(&p))
                .map(|r| r.split('/').next().unwrap().to_owned())
                .collect();
            v.dedup();
            v
        }
    }

    #[derive(Default)]
    struct FakeRun {
        answers: BTreeMap<String, (i32, String)>,
        ran: Vec<String>,
        result: (i32, String),
    }

    impl Runner for FakeRun {
        fn run(&mut self, argv: &[String], _interactive: bool) -> std::io::Result<(i32, String)> {
            self.ran.push(argv.join(" "));
            Ok(self.result.clone())
        }
        fn query(&mut self, argv: &[&str]) -> (i32, String) {
            self.answers
                .get(&argv.join(" "))
                .cloned()
                .unwrap_or((1, String::new()))
        }
    }

    fn grub_run() -> FakeRun {
        let mut r = FakeRun::default();
        r.answers
            .insert("pacman -Qq grub".into(), (0, "grub\n".into()));
        r.result = (0, String::new());
        r
    }

    fn paths(dir: &std::path::Path) -> Paths {
        let mut p = Paths::from_lookup(|k| match k {
            "HOME" => Some(dir.to_path_buf()),
            _ => None,
        });
        p.share_dir = dir.join("share");
        p
    }

    fn package(dir: &std::path::Path, theme: &str, digest: &str) {
        let d = dir.join("share/boot/grub/themes").join(theme);
        fs::create_dir_all(&d).unwrap();
        fs::write(
            d.join("manifest.json"),
            format!("{{\"digest\": \"{digest}\"}}"),
        )
        .unwrap();
    }

    fn set_theme(p: &Paths, name: &str) {
        let cur = crate::theme::Locations::new(p).current();
        fs::create_dir_all(&cur).unwrap();
        fs::write(cur.join("name"), name).unwrap();
    }

    const BLOCKED: &str = "GRUB_TIMEOUT=5\n# >>> bromigOS boot menu (bromigos boot theme; ...)\nGRUB_THEME=x\n# <<< bromigOS boot menu\n";

    #[test]
    fn the_block_and_the_terminal() {
        assert!(block_in(BLOCKED));
        assert!(!block_in("GRUB_TIMEOUT=5\n"));
        assert!(terminal_note("GRUB_TERMINAL=console\n").is_some());
        assert!(terminal_note("GRUB_TERMINAL=\"gfxterm serial\"\n").is_none());
        assert!(terminal_note("#GRUB_TERMINAL=console\n").is_none());
    }

    #[test]
    fn wants_the_packaged_theme_or_a_render() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        package(t.path(), "wick", "d-wick");
        set_theme(&p, "wick");
        assert_eq!(
            want(&p),
            Want::Package {
                theme: "wick".into(),
                digest: "d-wick".into()
            }
        );
        set_theme(&p, "mine");
        assert!(matches!(want(&p), Want::Render { why, .. } if why.contains("not a theme")));
        set_theme(&p, "wick");
        fs::create_dir_all(p.user_config_dir().join("themes/wick")).unwrap();
        assert!(matches!(want(&p), Want::Render { why, .. } if why.contains("overlay")));
    }

    #[test]
    fn grub_off_is_turned_on_and_systemd_boot_left_alone() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        package(t.path(), "wick", "d-wick");
        set_theme(&p, "wick");
        let fs_ = FakeFs(BTreeMap::new())
            .with("/boot/grub/grub.cfg", "")
            .with("/etc/default/grub", "GRUB_TIMEOUT=5\n")
            .with(HELPER, "");
        let mut r = grub_run();
        let o = sync(&p, &mut r, &fs_, Enable::Auto, true, false);
        assert_eq!(o.status, "done", "{o:?}");
        assert_eq!(
            r.ran,
            vec!["sudo /usr/lib/bromigos/boot/bromigos-boot-theme on --theme wick --auto"]
        );
        // Keep (update) leaves a machine where it's off alone
        let mut r = grub_run();
        assert_eq!(
            sync(&p, &mut r, &fs_, Enable::Keep, true, false).status,
            "skipped"
        );
        assert!(r.ran.is_empty());
        // systemd-boot: never
        let sd = FakeFs(BTreeMap::new())
            .with("/boot/loader/loader.conf", "")
            .with(HELPER, "");
        let mut r = FakeRun::default();
        let o = sync(&p, &mut r, &sd, Enable::On, true, false);
        assert_eq!(o.status, "skipped");
        assert!(o.detail.contains("systemd-boot"), "{}", o.detail);
        assert!(r.ran.is_empty());
    }

    #[test]
    fn on_and_current_does_nothing_and_a_new_theme_is_applied() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        package(t.path(), "wick", "d-wick");
        package(t.path(), "mire", "d-mire");
        set_theme(&p, "wick");
        let fs_ = FakeFs(BTreeMap::new())
            .with("/boot/grub/grub.cfg", "")
            .with("/etc/default/grub", BLOCKED)
            .with(HELPER, "")
            .with(
                STATE,
                r#"{"enabled": true, "theme": "wick", "source": "package", "digest": "d-wick"}"#,
            );
        let mut r = grub_run();
        let o = sync(&p, &mut r, &fs_, Enable::Keep, true, false);
        assert_eq!(o.status, "ok");
        assert!(r.ran.is_empty());
        set_theme(&p, "mire");
        let mut r = grub_run();
        let o = sync(&p, &mut r, &fs_, Enable::Keep, false, false);
        assert_eq!(o.status, "done");
        assert_eq!(
            r.ran,
            vec!["sudo -n /usr/lib/bromigos/boot/bromigos-boot-theme apply --theme mire"]
        );
        // the theme-set hook: sudo would ask, so the next update does it
        let mut r = grub_run();
        r.result = (1, "sudo: a password is required\n".into());
        let o = sync(&p, &mut r, &fs_, Enable::Keep, false, false);
        assert_eq!(o.status, "deferred");
        assert!(o.detail.contains("next bromigos update"));
    }

    #[test]
    fn turned_off_stays_off_for_auto() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        package(t.path(), "wick", "d-wick");
        set_theme(&p, "wick");
        let fs_ = FakeFs(BTreeMap::new())
            .with("/boot/grub/grub.cfg", "")
            .with("/etc/default/grub", "GRUB_TIMEOUT=5\n")
            .with(HELPER, "")
            .with(STATE, r#"{"enabled": false, "opted_out": true}"#);
        let mut r = grub_run();
        let o = sync(&p, &mut r, &fs_, Enable::Auto, true, false);
        assert_eq!(o.status, "skipped");
        assert!(o.detail.contains("turned off"), "{}", o.detail);
        let mut r = grub_run();
        assert_eq!(
            sync(&p, &mut r, &fs_, Enable::On, true, false).status,
            "done"
        );
        assert_eq!(
            r.ran,
            vec!["sudo /usr/lib/bromigos/boot/bromigos-boot-theme on --theme wick"]
        );
    }

    #[test]
    fn grub_not_installed_in_a_readable_boot() {
        let t = tempfile::tempdir().unwrap();
        let p = paths(t.path());
        package(t.path(), "wick", "d-wick");
        set_theme(&p, "wick");
        // the live medium's image: /boot has the kernel, no GRUB; /etc/default/grub is there
        let fs_ = FakeFs(BTreeMap::new())
            .with("/boot/vmlinuz-linux", "")
            .with("/etc/default/grub", "GRUB_TIMEOUT=5\n")
            .with(HELPER, "");
        let mut r = grub_run();
        let o = sync(&p, &mut r, &fs_, Enable::Auto, true, false);
        assert_eq!(o.status, "skipped");
        assert!(
            o.detail.contains("isn't installed in /boot"),
            "{}",
            o.detail
        );
        assert!(r.ran.is_empty());
    }
}
