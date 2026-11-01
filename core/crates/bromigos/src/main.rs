//! `bromigos`: one command for the bromigOS desktop.
//!
//! Built-in commands are below; any other `bromigos <group> <name> …` runs the
//! executable `bromigos-<group>-<name>` (or `bromigos-<group>`) from
//! `/usr/lib/bromigos/bin` or `PATH`. The `--json` outputs are the stable seam other
//! tools call; their schemas are in core/README.md.

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};

use anyhow::Result;
use bromigos_core::anim::{self, ANIMS};
use bromigos_core::commands::{self, Builtin, Route, Verbs};
use bromigos_core::config::{self, Overrides};
use bromigos_core::install;
use bromigos_core::ipc::{self, IpcError};
use bromigos_core::lock::{self, LockConfig};
use bromigos_core::migrate::Outcome;
use bromigos_core::paths::Paths;
use bromigos_core::profile::{Field, List, ProfileFile};
use bromigos_core::session::{self, Discovery};
use bromigos_core::setup;
use bromigos_core::theme;
use bromigos_core::update::{self, Need, Piece};
use clap::{CommandFactory, Parser, Subcommand, ValueEnum};
use serde_json::{Value, json};

mod accessibility;
mod art;
mod art_make;
mod aur;
mod ext;
mod fieldkit;
mod fieldkit_vector;
mod hw;
mod hw_graphics;
mod idle;
mod mute;
mod peripheral;
mod setup_tui;
mod target;

/// The version of every `--json` document; bumped only on incompatible changes.
pub(crate) const SCHEMA: u32 = 1;

/// Command groups, by purpose. Not all have commands yet; plugins add to them.
const GROUPS: &[&str] = &[
    "toggle",
    "restart",
    "launch",
    "capture",
    "setup",
    "install",
    "refresh",
    "theme",
    "anim",
    "hw",
    "update",
    "vector",
    "live",
    "session",
    "lock",
    "commands",
    "profile",
    "art",
    "channel",
    "rollback",
    "boot",
    "ext",
    "peripheral",
    "idle",
];

#[derive(Parser)]
#[command(
    name = "bromigos",
    version,
    about = "One command for the bromigOS desktop.",
    after_help = after_help()
)]
struct Cli {
    #[command(subcommand)]
    cmd: Option<Cmd>,
}

// clap's parsed command line, made once: its size doesn't matter
#[allow(clippy::large_enum_variant)]
#[derive(Subcommand)]
enum Cmd {
    /// Field Kit (Repair. Recon. Deploy.): the menu (Repair, Lab, Tools, Install,
    /// Shell), or one job: why, black-screen, status, make-stick, remote, usb (docs/fieldkit.md)
    #[command(disable_help_flag = true)]
    Fieldkit {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<OsString>,
    },
    /// The live Hyprland session (prints KEY=value; import, exec or adopt it; hold and
    /// release its config reloads around a package transaction)
    Session(SessionArgs),
    /// The look: list the themes, show the current one, set one (renders every app's colours)
    Theme(ThemeArgs),
    /// Extensions from git: themes, decks, widgets, VECTOR tools, homelab adapters,
    /// commands, hooks (install, list, info, update, remove, new, search)
    Ext(ext::ExtArgs),
    /// Every wallpaper animation and whether it's on; turn them on, off or reset
    Anim(AnimArgs),
    /// The whole animated background: on|off (runtime), or any bromigos-live command
    #[command(disable_help_flag = true)]
    Live {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<OsString>,
    },
    /// VECTOR (any bromigos-holo command: off, on, vector, ask, status, mute, …)
    #[command(disable_help_flag = true)]
    Vector {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<OsString>,
    },
    /// Who you are and what VECTOR calls you (show, set, address, alias)
    Profile(ProfileArgs),
    /// A world's art: plan (price it), run (make it through nolgia), status, mark
    Art(art::ArtArgs),
    /// Where AI work runs: homelab, local or cloud, per service (art, VECTOR's voice and
    /// brain); show it, probe it, switch it (`bromigos target local`)
    Target(target::TargetArgs),
    /// The desktop's one mute: the theme's sounds and VECTOR's voice together
    /// (on, off, toggle, status; SUPER+SHIFT+M)
    Mute(mute::MuteArgs),
    /// Optional peripheral modules: a Razer keyboard's macro keys, its dial as VECTOR's
    /// voice dial, lighting that follows VECTOR (list, status, enable, disable, refresh)
    Peripheral(peripheral::PeripheralArgs),
    /// Reduced motion and high contrast: show them, set them (`bromigos accessibility
    /// motion reduced`, `contrast high`), measure a theme's colours (`check`)
    #[command(visible_alias = "a11y")]
    Accessibility(accessibility::AccessibilityArgs),
    /// Idle and lock: when the screensaver starts, the screen locks, the displays go off and
    /// it suspends (status, set, preset, stay-awake, off, undo; docs/idle.md)
    Idle(idle::IdleArgs),
    /// Lock the screen now (loginctl lock-session)
    Lock,
    /// The lock launcher hypridle runs: keeps the screen locked if the locker crashes
    LockRun,
    /// The den wallpaper (any bromigos-wallpaper command)
    #[command(disable_help_flag = true)]
    Wallpaper {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<OsString>,
    },
    /// Update everything: packages (sudo pacman -Syu, then AUR packages with paru), then
    /// migrations, the theme, and restarts of whatever runs older code than is installed
    Update {
        /// Only say what it would do: upgrades waiting, migrations pending, restarts needed,
        /// how updates are snapshotted, the updates that can be rolled back
        #[arg(long)]
        check: bool,
        /// Skip the package step (migrations, the theme and restarts only)
        #[arg(long)]
        no_packages: bool,
        /// Undo an update: every file / had before it comes back (snapper undochange on the
        /// pre/post pair around it), after a summary and a question. PRE picks an older one.
        /// In a snapshot started from the boot menu: that snapshot becomes the root
        #[arg(long, value_name = "PRE", num_args = 0..=1)]
        rollback: Option<Option<u64>>,
        /// Don't ask: pacman takes its defaults, the AUR step builds without paru's review
        /// of each recipe (docs/aur.md), and a rollback goes ahead without a question
        #[arg(long)]
        yes: bool,
        /// Leave AUR packages alone this time (`bromigos aur off`: every time)
        #[arg(long)]
        no_aur: bool,
        /// Allow downgrades (pacman -Syuu): after a move to an older channel
        #[arg(long)]
        downgrade: bool,
        /// Follow this channel from now on (stable, rc, edge, dev), then update
        #[arg(long, value_name = "NAME")]
        channel: Option<String>,
        /// Print the JSON document (schema in core/README.md)
        #[arg(long)]
        json: bool,
    },
    /// The update channel this machine follows (stable, rc, edge, dev): show it, or switch
    Channel {
        /// Switch to this channel (rewrites the [bromigos] Server line with sudo)
        name: Option<String>,
        /// The repository's base URL, when it isn't known (after dev) or changes
        #[arg(long, value_name = "URL")]
        repo: Option<String>,
        /// dev: the local repository's directory (default ~/.local/share/bromigos/repo)
        #[arg(long, value_name = "DIR")]
        dev_dir: Option<std::path::PathBuf>,
        /// Print the JSON document (schema in core/README.md)
        #[arg(long)]
        json: bool,
    },
    /// Rolling updates back: `status` (how this machine snapshots updates, what can be
    /// undone), `setup` (snapper's root configuration, snap-pac, grub-btrfs with its overlay
    /// hook or limine-snapper-sync, where / is btrfs), `allow` (wheel may list root's
    /// snapshots, so updates are recorded). Undoing one is `bromigos update --rollback`
    Rollback {
        /// status (default), setup or allow
        action: Option<String>,
        /// setup, allow: only say what it would run
        #[arg(long)]
        dry_run: bool,
        /// setup: pacman doesn't ask (unattended installs)
        #[arg(long)]
        yes: bool,
        /// Print the JSON document (schema in core/README.md)
        #[arg(long)]
        json: bool,
    },
    /// The AUR (build recipes Arch users share; docs/aur.md): `status` (the helper here,
    /// whether bromigos update uses it, the AUR updates waiting), `on`, `off`, `ensure`
    Aur(aur::AurArgs),
    /// The boot menu: bromigOS's GRUB theme in your theme's colours (`bromigos boot theme
    /// status|on|off|apply`; docs/boot.md)
    Boot(BootArgs),
    /// Secure Boot (docs/secureboot.md): `status` (where it stands), `setup` (this computer's
    /// own key, GRUB and the kernels signed with it, shim first in the boot order, and the key's
    /// enrollment asked for at the next start, approved there with a code), `resign`
    /// (everything signed again: the pacman hooks do it after updates), `remove` (back as
    /// before setup). Needs the bromigos-secureboot package
    Secureboot {
        /// status (default), setup, resign or remove
        action: Option<String>,
        /// setup, resign, remove: only say what it would do
        #[arg(long)]
        dry_run: bool,
        /// setup: the 4 to 8 digits that approve the key at the next start (default: four
        /// made up, and shown)
        #[arg(long)]
        code: Option<String>,
        /// status: print the JSON document
        #[arg(long)]
        json: bool,
    },
    /// Restart what runs stale (its package is newer than the process), or the pieces named
    Restart {
        /// live, widgets, waybar, dunst, vector, hyprland (its config), osd, idle (hypridle),
        /// or a user unit a package's restart.d drop-in declares; none: whatever is stale.
        /// A named live, widgets, waybar or dunst that isn't running is started
        pieces: Vec<String>,
        /// Only say what would restart
        #[arg(long)]
        check: bool,
        /// Print the JSON document (schema in core/README.md)
        #[arg(long)]
        json: bool,
    },
    /// What's new in this release of bromigOS: the release notes installed with it (they
    /// read offline; the manual's "What's new" page)
    WhatsNew {
        /// A release's notes (e.g. 0.1.2); the newest by default
        release: Option<String>,
        /// Every release's notes, newest first
        #[arg(long)]
        all: bool,
    },
    /// Install bromigOS on this machine (after install.sh): the packages, services, the
    /// hardware, your configs, the desktop settings and the theme, then the first-run setup
    Install {
        /// Only say what it would do
        #[arg(long)]
        dry_run: bool,
        /// Optional packages too (e.g. --with bromigos-homelab --with herdr)
        #[arg(long = "with", value_name = "PACKAGE")]
        extras: Vec<String>,
        /// Answer pacman's questions with their defaults (unattended)
        #[arg(long)]
        yes: bool,
        /// Leave services alone
        #[arg(long)]
        no_services: bool,
        /// Enable SDDM even when another display manager is enabled
        #[arg(long)]
        force_dm: bool,
        /// The theme when none is set yet
        #[arg(long, default_value = "wick")]
        theme: String,
        /// Leave the hardware alone (drivers, early KMS, power profiles: bromigos hw setup later)
        #[arg(long)]
        no_hardware: bool,
        /// No AUR helper: paru isn't installed, and bromigos update leaves the AUR alone
        /// (bromigos aur on, any time; docs/aur.md)
        #[arg(long)]
        no_aur: bool,
        /// Don't run the first-run setup afterwards
        #[arg(long)]
        no_setup: bool,
        /// Setup's answers from a file (TOML; docs/install.md) instead of asking
        #[arg(long, value_name = "FILE")]
        answers: Option<std::path::PathBuf>,
        /// Print the JSON document (schema in core/README.md)
        #[arg(long)]
        json: bool,
    },
    /// This machine's hardware: its GPUs and their drivers, a laptop's battery, backlight,
    /// touchpad and power profiles; `hw setup` sets them up (docs/hardware.md)
    Hw(hw::HwArgs),
    /// The first-run questions (monitors, the AUR, hardware, accessibility, theme, VECTOR's
    /// brain and voice, homelab, where AI runs, the creation tools, peripheral modules);
    /// run again any time, or one section: `bromigos setup voice`. `bromigos setup homelab`
    /// detects your homelab's services (bromigos-homelab; --hosts, --url, --yes, --print)
    Setup {
        /// One section: monitors, aur, hardware, accessibility, theme, vector, voice,
        /// homelab, targets, create, peripherals (none: all)
        section: Option<String>,
        /// The answers from a file (TOML; docs/install.md) instead of asking
        #[arg(long, value_name = "FILE")]
        answers: Option<std::path::PathBuf>,
        /// Unattended answers: monitors auto|skip
        #[arg(long)]
        monitors: Option<String>,
        /// Unattended answers: the AUR (an AUR helper, AUR packages in bromigos update;
        /// bromigos aur) on|off
        #[arg(long)]
        aur: Option<String>,
        /// Unattended answers: the hardware (drivers, power profiles; bromigos hw setup) auto|skip
        #[arg(long)]
        hardware: Option<String>,
        /// Unattended answers: the primary output (the live background and the panels go on it)
        #[arg(long)]
        primary: Option<String>,
        /// Unattended answers: outputs left to right, comma-separated (e.g. DP-2,DP-1)
        #[arg(long, value_delimiter = ',')]
        order: Vec<String>,
        /// Unattended answers: an output's scale, OUTPUT=SCALE (repeat for more)
        #[arg(long = "scale", value_name = "OUTPUT=SCALE")]
        scales: Vec<String>,
        /// Unattended answers: an output's refresh rate, OUTPUT=HZ (repeat for more)
        #[arg(long = "refresh", value_name = "OUTPUT=HZ")]
        refreshes: Vec<String>,
        /// Unattended answers: where AI runs, the targets in order, comma-separated (e.g.
        /// homelab,local; the cloud costs money: leave it out to never use it)
        #[arg(long = "targets", value_delimiter = ',', value_name = "TARGETS")]
        targets: Vec<String>,
        /// Unattended answers: a service that may also use the cloud, last (e.g. video.loop;
        /// repeat for more)
        #[arg(long = "cloud-for", value_name = "SERVICE")]
        cloud_for: Vec<String>,
        /// Unattended answers: a capability's providers in order, CAPABILITY=P1,P2 (e.g.
        /// image.generate=comfyui:local,nolgia; none: off), or `none` for every capability
        #[arg(long = "create", value_name = "CAPABILITY=PROVIDERS")]
        create: Vec<String>,
        /// Unattended answers: sign in to nolgia with the personal access token in FILE
        /// (stored 0600 for bromigos art, never printed)
        #[arg(long = "nolgia-token-file", value_name = "FILE")]
        nolgia_token_file: Option<String>,
        /// Unattended answers: how much the desktop moves: full, reduced or still
        /// (bromigos accessibility)
        #[arg(long, value_name = "LEVEL")]
        motion: Option<String>,
        /// Unattended answers: the colours' contrast: normal or high
        #[arg(long, value_name = "LEVEL")]
        contrast: Option<String>,
        /// Unattended answers: the theme
        #[arg(long)]
        theme: Option<String>,
        /// Unattended answers: the Wick's den variant
        #[arg(long)]
        den: Option<String>,
        /// Unattended answers: VECTOR's brain: ollama, openai or none
        #[arg(long)]
        vector: Option<String>,
        /// Unattended answers: the OpenAI-compatible server's base URL
        #[arg(long)]
        base_url: Option<String>,
        /// Unattended answers: a file holding its API key
        #[arg(long)]
        api_key_file: Option<String>,
        /// Unattended answers: the model
        #[arg(long)]
        model: Option<String>,
        /// Unattended answers: VECTOR's voice: gpu, cpu or off
        #[arg(long)]
        voice: Option<String>,
        /// Unattended answers: a homelab.toml to use
        #[arg(long)]
        homelab: Option<String>,
        /// Unattended answers: turn a peripheral module on (e.g. razer-keyboard; repeat for
        /// more; bromigos peripheral list)
        #[arg(long = "peripheral", value_name = "MODULE")]
        peripherals: Vec<String>,
        /// Replace an existing homelab.toml
        #[arg(long)]
        replace: bool,
        /// Print the JSON document (schema in core/README.md)
        #[arg(long)]
        json: bool,
    },
    /// The live layer, VECTOR, the session and the animations
    Status {
        /// Print the JSON document (schema in core/README.md)
        #[arg(long)]
        json: bool,
    },
    /// Every command: the built-ins and the bromigos-<group>-<name> executables found
    Commands {
        #[arg(long)]
        json: bool,
        /// Report commands with no summary, and route collisions (exit 1 if any)
        #[arg(long)]
        check: bool,
        /// Include hidden commands
        #[arg(long)]
        all: bool,
    },
    #[command(external_subcommand)]
    External(Vec<OsString>),
}

#[derive(clap::Args)]
struct BootArgs {
    #[command(subcommand)]
    what: Option<BootWhat>,
}

#[derive(Subcommand)]
enum BootWhat {
    /// GRUB's theme: status (default), on (turn it on, in the current theme's colours), off
    /// (GRUB's own menu, and it stays off here), apply (/boot on the current theme)
    Theme {
        /// status, on, off or apply
        action: Option<String>,
        /// on, apply: never ask sudo for a password (then the next bromigos update does it)
        #[arg(long)]
        no_prompt: bool,
        /// on: not where `off` turned it off (bromigos install, setup, the migration)
        #[arg(long)]
        auto: bool,
        /// Only say what it would run
        #[arg(long)]
        dry_run: bool,
        /// Print the JSON document (schema in core/README.md)
        #[arg(long)]
        json: bool,
    },
}

#[derive(clap::Args)]
struct SessionArgs {
    /// Print the JSON document (schema in core/README.md)
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    mode: Option<SessionMode>,
}

#[derive(Subcommand)]
enum SessionMode {
    /// Print missing or stale local shell display settings; leave SSH and working displays alone
    ShellEnv,
    /// Also push WAYLAND_DISPLAY and HYPRLAND_INSTANCE_SIGNATURE to systemd --user and D-Bus
    Import,
    /// Import, then exec CMD with the session's values
    Exec {
        #[arg(
            required = true,
            trailing_var_arg = true,
            allow_hyphen_values = true,
            value_name = "CMD"
        )]
        cmd: Vec<OsString>,
    },
    /// At login: import, and stop VECTOR's daemon if it belongs to another session
    Adopt,
    /// Hold Hyprland's config reloads: auto-reload off in every running Hyprland (as root,
    /// every user's), what it was remembered. pacman runs it before a transaction that
    /// changes the desktop's default config (docs/update.md)
    Hold {
        /// As pacman's hook: quiet when no Hyprland runs, and a watcher releases what is
        /// still held if pacman exits without running the release hook
        #[arg(long)]
        pacman: bool,
    },
    /// Let go of a hold: each held Hyprland's config verified (Hyprland --verify-config),
    /// reloaded once when it verifies, auto-reload back as it was. pacman runs it after
    /// the transaction
    Release {
        /// As pacman's hook: every running Hyprland gets the verified reload, held or not;
        /// quiet when none runs
        #[arg(long)]
        pacman: bool,
        /// Wait for these processes (PID:START, comma-separated) to exit first (the hold's watcher)
        #[arg(long, value_name = "PID:START", hide = true)]
        after: Option<String>,
    },
}

#[derive(clap::Args)]
struct ThemeArgs {
    /// Print the JSON document (schema in core/README.md)
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    verb: Option<ThemeVerb>,
}

#[derive(Subcommand)]
enum ThemeVerb {
    /// Every theme, first-party and the user's (the default verb)
    List,
    /// The theme in force (the default, wick, when none was set)
    Current,
    /// Render NAME (default: the current theme) into ~/.local/state/bromigos/theme/current
    /// and tell the running apps
    Set {
        name: Option<String>,
        /// Don't signal waybar, kitty, Hyprland or dunst
        #[arg(long)]
        no_reload: bool,
    },
    /// Install a theme from a git URL, a folder or the catalog: `bromigos ext install`
    /// (a git checkout that `bromigos ext update` updates)
    Install {
        source: String,
        /// A theme repository without a manifest: the name to install it as
        #[arg(long)]
        name: Option<String>,
        /// A theme of yours with the same name: move it aside and install this one
        #[arg(long)]
        force: bool,
    },
    /// Remove a theme: an extension's (`bromigos ext remove`) or one of yours (never a
    /// first-party one, never the one in force)
    Remove { name: String },
    /// A new theme to make your own, as an extension in ./NAME: from the starter, or a
    /// copy of an installed theme (--from)
    New {
        name: String,
        /// The theme to start from (bromigos theme list)
        #[arg(long)]
        from: Option<String>,
        /// Where (default ./NAME)
        #[arg(long)]
        dir: Option<PathBuf>,
    },
}

#[derive(clap::Args)]
struct AnimArgs {
    /// Turn on, off, or back to the defaults (no verb: list them)
    verb: Option<AnimVerb>,
    /// Animation names, or "all" (reset with none: all)
    names: Vec<String>,
    /// Print the JSON document (after any change; schema in core/README.md)
    #[arg(long)]
    json: bool,
}

#[derive(Clone, Copy, ValueEnum)]
enum AnimVerb {
    On,
    Off,
    Reset,
}

#[derive(clap::Args)]
struct ProfileArgs {
    /// Print the JSON document (after any change; schema in core/README.md)
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    cmd: Option<ProfileCmd>,
}

#[derive(Subcommand)]
enum ProfileCmd {
    /// Show the profile (the default)
    Show,
    /// Set name, full_name or pronouns ("" clears it)
    Set { field: ProfileField, value: String },
    /// Forms of address, most preferred first: add, remove, or set the whole list
    Address {
        verb: ListVerb,
        #[arg(value_name = "VALUE")]
        values: Vec<String>,
    },
    /// Other names you go by: add or remove
    Alias {
        verb: AliasVerb,
        #[arg(required = true, value_name = "VALUE")]
        values: Vec<String>,
    },
}

#[derive(Clone, Copy, ValueEnum)]
enum ProfileField {
    Name,
    #[value(name = "full_name", alias = "full-name")]
    FullName,
    Pronouns,
}

#[derive(Clone, Copy, ValueEnum)]
enum ListVerb {
    Add,
    Remove,
    Set,
}

#[derive(Clone, Copy, ValueEnum)]
enum AliasVerb {
    Add,
    Remove,
}

fn after_help() -> String {
    format!(
        "Animations: {}\n\
         Groups: {}\n\n\
         Any other `bromigos <group> <name> [args…]` runs bromigos-<group>-<name> (or \
         bromigos-<group>) from /usr/lib/bromigos/bin or PATH; `bromigos commands` lists \
         them.\n\
         Animation switches are yours: they go in ~/.config/bromigos/live/overrides.toml, \
         merged over the live layer's config.toml.",
        anim::names().join(", "),
        GROUPS.join(", ")
    )
}

/// The built-ins as the router sees them.
fn builtins(paths: &Paths) -> Vec<Builtin> {
    let b = |name, verbs, target: Option<&Path>| Builtin {
        name,
        verbs,
        target: target.map(Path::to_path_buf),
    };
    vec![
        b(
            "session",
            Verbs::Only(&["import", "exec", "adopt", "help"]),
            None,
        ),
        b("anim", Verbs::Only(&["on", "off", "reset", "help"]), None),
        b(
            "theme",
            Verbs::Only(&["list", "current", "set", "install", "remove", "new", "help"]),
            None,
        ),
        b(
            "ext",
            Verbs::Only(&[
                "install", "list", "info", "update", "remove", "enable", "disable", "new",
                "search", "validate", "migrate", "help",
            ]),
            None,
        ),
        b("live", Verbs::All, Some(&paths.live_bin)),
        b("fieldkit", Verbs::All, None),
        b("vector", Verbs::All, Some(&paths.holo_bin)),
        b("wallpaper", Verbs::All, Some(&paths.wallpaper_bin)),
        b(
            "profile",
            Verbs::Only(&["show", "set", "address", "alias", "help"]),
            None,
        ),
        b(
            "art",
            Verbs::Only(&["plan", "run", "status", "mark", "help"]),
            None,
        ),
        b("target", Verbs::All, None),
        b(
            "mute",
            Verbs::Only(&["on", "off", "toggle", "status"]),
            None,
        ),
        b(
            "peripheral",
            Verbs::Only(&["list", "status", "enable", "disable", "refresh", "help"]),
            None,
        ),
        b(
            "accessibility",
            Verbs::Only(&["status", "motion", "contrast", "check", "help"]),
            None,
        ),
        b(
            "a11y",
            Verbs::Only(&["status", "motion", "contrast", "check", "help"]),
            None,
        ),
        b("update", Verbs::Only(&[]), None),
        b(
            "channel",
            Verbs::Only(&["stable", "rc", "edge", "dev"]),
            None,
        ),
        b("rollback", Verbs::Only(&["status", "setup", "allow"]), None),
        b(
            "aur",
            Verbs::Only(&["status", "on", "off", "ensure", "help"]),
            None,
        ),
        b("hw", Verbs::Only(&["detect", "setup", "help"]), None),
        b(
            "restart",
            Verbs::Only(&[
                "live", "widgets", "waybar", "dunst", "vector", "hyprland", "osd", "idle",
            ]),
            None,
        ),
        b(
            "idle",
            Verbs::Only(&[
                "status",
                "set",
                "preset",
                "stay-awake",
                "off",
                "undo",
                "apply",
                "hook",
                "render",
                "start",
                "help",
            ]),
            None,
        ),
        b("lock", Verbs::Only(&[]), None),
        b("lock-run", Verbs::Only(&[]), None),
        b("status", Verbs::Only(&[]), None),
        b("commands", Verbs::Only(&[]), None),
        b("help", Verbs::All, None),
    ]
}

fn main() -> ExitCode {
    // Rust ignores SIGPIPE, so `bromigos status | head` panicked on the closed pipe.
    // A CLI should end quietly instead, as every coreutils tool does.
    // SAFETY: called first, before any thread starts; restores the default disposition.
    unsafe {
        libc::signal(libc::SIGPIPE, libc::SIG_DFL);
    }
    let paths = Paths::from_env();
    let argv: Vec<OsString> = std::env::args_os().skip(1).collect();
    let dirs = commands::search_dirs(&paths, std::env::var_os("PATH").as_deref());
    // `bromigos setup homelab` without a file to copy is bromigos-homelab's detector
    // (bromigos-setup-homelab: probes the homelab's services and writes homelab.toml;
    // docs/homelab.md), with its own flags (--hosts, --url, --yes, …).
    if let Some((path, args)) = homelab_detector(&argv, &dirs) {
        return code(exec_or_report(&path, &args));
    }
    // ... and with one (--homelab FILE, --answers FILE) it's the built-in setup's section,
    // which copies that file into place: the router mustn't hand it to the detector.
    if !setup_homelab_with_file(&argv)
        && let Route::External { path, args, .. } =
            commands::route(&argv, &builtins(&paths), |n| commands::find(&dirs, n))
    {
        return code(exec_or_report(&path, &args));
    }
    let cli = Cli::parse();
    let r = match cli.cmd {
        None => {
            let _ = Cli::command().print_help();
            Ok(0)
        }
        Some(cmd) => run(&paths, &dirs, cmd),
    };
    match r {
        Ok(c) => code(c),
        Err(e) => {
            eprintln!("bromigos: {e:#}");
            ExitCode::from(1)
        }
    }
}

fn code(c: i32) -> ExitCode {
    ExitCode::from(u8::try_from(c).unwrap_or(1))
}

fn run(paths: &Paths, dirs: &[std::path::PathBuf], cmd: Cmd) -> Result<i32> {
    match cmd {
        Cmd::Session(a) => session_cmd(paths, a),
        Cmd::Theme(a) => theme_cmd(paths, a),
        Cmd::Ext(a) => ext::ext_cmd(paths, a),
        Cmd::Anim(a) => anim_cmd(paths, a),
        Cmd::Live { args } => live_cmd(paths, args),
        Cmd::Fieldkit { args } => fieldkit::fieldkit_cmd(args),
        Cmd::Vector { args } => Ok(exec_or_report(&paths.holo_bin, &args)),
        Cmd::Wallpaper { args } => Ok(exec_or_report(&paths.wallpaper_bin, &args)),
        Cmd::Profile(a) => profile_cmd(paths, a),
        Cmd::Art(a) => art::art_cmd(paths, a),
        Cmd::Target(a) => target::target_cmd(paths, a),
        Cmd::Mute(a) => mute::mute_cmd(paths, a),
        Cmd::Idle(a) => idle::idle_cmd(paths, a),
        Cmd::Peripheral(a) => peripheral::peripheral_cmd(paths, a),
        Cmd::Accessibility(a) => accessibility::accessibility_cmd(paths, a),
        Cmd::Lock => Ok(exec_or_report(
            Path::new("loginctl"),
            &[OsString::from("lock-session")],
        )),
        Cmd::LockRun => {
            let lockers = lock::lockers_from(std::env::var("BROMIGOS_LOCKER").ok().as_deref());
            let cfg = LockConfig::new(
                lockers,
                paths.lock_flock(),
                Box::new(|m: &str| bromigos_core::log("bromigos-lock", m)),
            );
            Ok(lock::run(cfg).exit_code())
        }
        Cmd::Update {
            check,
            no_packages,
            rollback,
            yes,
            no_aur,
            downgrade,
            channel,
            json,
        } => match rollback {
            Some(pre) => rollback_cmd(paths, pre, yes, json),
            None => update_cmd(
                paths,
                &UpdateFlags {
                    check,
                    no_packages,
                    downgrade,
                    yes,
                    no_aur,
                    json,
                },
                channel.as_deref(),
            ),
        },
        Cmd::Channel {
            name,
            repo,
            dev_dir,
            json,
        } => channel_cmd(
            paths,
            name.as_deref(),
            repo.as_deref(),
            dev_dir.as_deref(),
            json,
        ),
        Cmd::Rollback {
            action,
            dry_run,
            yes,
            json,
        } => rollback_tool_cmd(
            paths,
            action.as_deref().unwrap_or("status"),
            dry_run,
            yes,
            json,
        ),
        Cmd::Restart {
            pieces,
            check,
            json,
        } => restart_cmd(paths, &pieces, check, json),
        Cmd::Aur(a) => aur::aur_cmd(paths, a),
        Cmd::Boot(a) => boot_cmd(paths, a),
        Cmd::Secureboot {
            action,
            dry_run,
            code,
            json,
        } => bromigos_core::secureboot::run(
            action.as_deref().unwrap_or("status"),
            dry_run,
            code.as_deref(),
            json,
        )
        .map_err(anyhow::Error::msg),
        Cmd::WhatsNew { release, all } => whats_new_cmd(paths, release.as_deref(), all),
        Cmd::Install {
            dry_run,
            extras,
            yes,
            no_services,
            force_dm,
            theme,
            no_hardware,
            no_aur,
            no_setup,
            answers,
            json,
        } => {
            // an answers file's [aur] mode = "off" is read before anything is installed, so
            // paru never is
            let aur_off = match answers.as_deref() {
                Some(f) => setup::load_answers(f)
                    .map_err(anyhow::Error::msg)?
                    .aur
                    .is_some_and(|a| a.mode == "off"),
                None => false,
            };
            let opts = install::Options {
                dry_run,
                extras,
                yes,
                no_services,
                force_dm,
                theme,
                no_hardware,
                no_aur: no_aur || aur_off,
            };
            install_cmd(paths, &opts, no_setup, answers.as_deref(), json)
        }
        Cmd::Hw(a) => hw::hw_cmd(paths, a),
        Cmd::Setup {
            section,
            answers,
            monitors,
            aur,
            hardware,
            primary,
            order,
            scales,
            refreshes,
            targets,
            cloud_for,
            create,
            nolgia_token_file,
            motion,
            contrast,
            theme,
            den,
            vector,
            base_url,
            api_key_file,
            model,
            voice,
            homelab,
            peripherals,
            replace,
            json,
        } => {
            let pairs = |v: &[String], what: &str| -> Result<BTreeMap<String, f64>> {
                v.iter()
                    .map(|kv| {
                        let (k, n) = kv
                            .split_once('=')
                            .ok_or_else(|| anyhow::anyhow!("--{what} {kv:?}: OUTPUT=NUMBER"))?;
                        Ok((
                            k.to_string(),
                            n.parse::<f64>()
                                .map_err(|_| anyhow::anyhow!("--{what} {kv:?}: not a number"))?,
                        ))
                    })
                    .collect()
            };
            let create = if create.is_empty() && nolgia_token_file.is_none() {
                None
            } else {
                let mut providers = BTreeMap::new();
                for c in &create {
                    if c == "none" {
                        for cap in bromigos_core::create::CAPABILITIES {
                            providers.insert(cap.to_string(), vec!["none".to_string()]);
                        }
                        continue;
                    }
                    let (cap, ps) = c
                        .split_once('=')
                        .ok_or_else(|| anyhow::anyhow!("--create {c:?}: CAPABILITY=PROVIDERS"))?;
                    providers.insert(cap.to_string(), ps.split(',').map(str::to_string).collect());
                }
                Some(bromigos_core::create::CreateAnswer {
                    providers,
                    nolgia_login: false,
                    nolgia_token_file: nolgia_token_file.clone(),
                })
            };
            let scale = pairs(&scales, "scale")?;
            let refresh = pairs(&refreshes, "refresh")?;
            let flags = setup::Answers {
                monitors: monitors.map(|mode| setup::MonitorsAnswer {
                    mode,
                    primary,
                    order,
                    scale,
                    refresh,
                }),
                aur: aur.map(|mode| setup::AurAnswer { mode }),
                hardware: hardware.map(|mode| setup::HardwareAnswer { mode }),
                accessibility: (motion.is_some() || contrast.is_some()).then(|| {
                    setup::AccessibilityAnswer {
                        motion: motion.clone(),
                        contrast: contrast.clone(),
                    }
                }),
                // extensions come from an answers file only: it's what approves code
                extensions: None,
                theme: theme.map(|name| setup::ThemeAnswer {
                    name,
                    den: den.clone(),
                }),
                vector: vector.map(|backend| setup::VectorAnswer {
                    backend,
                    base_url,
                    api_key_file,
                    model,
                }),
                voice: voice.map(|tier| setup::VoiceAnswer { tier }),
                homelab: homelab.map(|f| setup::HomelabAnswer {
                    file: Some(f),
                    find: false,
                }),
                targets: (!targets.is_empty()).then(|| setup::TargetsAnswer {
                    order: targets.clone(),
                    cloud_for: cloud_for.clone(),
                }),
                create,
                peripherals: (!peripherals.is_empty()).then(|| setup::PeripheralsAnswer {
                    enable: peripherals.clone(),
                    disable: vec![],
                    force: false,
                    system: true,
                }),
            };
            setup_cmd(
                paths,
                section.as_deref(),
                answers.as_deref(),
                flags,
                replace,
                json,
            )
        }
        Cmd::Status { json } => status_cmd(paths, json),
        Cmd::Commands { json, check, all } => commands_cmd(paths, dirs, json, check, all),
        Cmd::External(args) => {
            let name = args
                .first()
                .map(|s| s.to_string_lossy().into_owned())
                .unwrap_or_default();
            eprintln!(
                "bromigos: unknown command: {name} (no built-in, and no bromigos-{name}… in \
                 /usr/lib/bromigos/bin or PATH; `bromigos commands` lists them)"
            );
            Ok(2)
        }
    }
}

/// Replaces this process with `prog args…`; returns only on failure (127).
/// `setup homelab [args…]` with neither `--homelab FILE` nor `--answers FILE`, when
/// bromigos-homelab's detector is installed: (its path, the args after `homelab`).
fn homelab_detector(argv: &[OsString], dirs: &[PathBuf]) -> Option<(PathBuf, Vec<OsString>)> {
    if argv.len() < 2 || argv[0] != "setup" || argv[1] != "homelab" || setup_homelab_with_file(argv)
    {
        return None;
    }
    let path = commands::find(dirs, "bromigos-setup-homelab")?;
    Some((path, argv[2..].to_vec()))
}

/// `setup homelab … --homelab FILE` or `--answers FILE`: the built-in section's file copy.
fn setup_homelab_with_file(argv: &[OsString]) -> bool {
    argv.len() >= 2
        && argv[0] == "setup"
        && argv[1] == "homelab"
        && argv[2..].iter().any(|a| {
            let a = a.to_string_lossy();
            a == "--homelab"
                || a.starts_with("--homelab=")
                || a == "--answers"
                || a.starts_with("--answers=")
        })
}

fn exec_or_report(prog: &Path, args: &[OsString]) -> i32 {
    let e = Command::new(prog).args(args).exec();
    eprintln!("bromigos: {}: {e}", prog.display());
    127
}

// ------------------------------------------------------------------ session

fn session_json(d: &Discovery) -> Value {
    let s = d.session.as_ref();
    let env: BTreeMap<&str, &str> = s.map(|s| s.env().into_iter().collect()).unwrap_or_default();
    json!({
        "schema": SCHEMA,
        "found": s.is_some(),
        "wayland_display": s.map(|s| &s.wayland_display),
        "hyprland_instance_signature": s.map(|s| &s.signature),
        "pid": s.map(|s| s.pid),
        "nested": s.map(|s| s.nested),
        "env": env,
        "runtime_dir": d.runtime_dir,
        "candidates": d.candidates.iter().map(|c| json!({
            "signature": c.signature,
            "pid": c.pid,
            "wayland_display": c.wayland_display,
            "running": c.running,
            "socket": c.socket,
            "nested": c.nested,
            "usable": c.usable(),
        })).collect::<Vec<_>>(),
    })
}

fn session_cmd(paths: &Paths, a: SessionArgs) -> Result<i32> {
    match a.mode {
        Some(SessionMode::ShellEnv) => {
            let env: BTreeMap<_, _> = session::shell_env(paths, |key| std::env::var(key).ok())
                .into_iter()
                .collect();
            if a.json {
                println!("{}", json!({"schema": SCHEMA, "env": env}));
            } else {
                for (key, value) in env {
                    println!("{key}={value}");
                }
            }
            return Ok(0);
        }
        Some(SessionMode::Hold { pacman }) => return hold_cmd(paths, pacman, a.json),
        Some(SessionMode::Release { pacman, after }) => {
            return release_cmd(paths, pacman, after.as_deref(), a.json);
        }
        _ => {}
    }
    let d = session::discover(paths);
    let Some(s) = d.session.as_ref() else {
        if a.json {
            println!("{}", session_json(&d));
        }
        eprintln!("bromigos session: no running Hyprland session found");
        // exec still runs the command, with the environment unchanged
        if let Some(SessionMode::Exec { cmd }) = a.mode {
            let e = session::exec(None, &cmd);
            eprintln!("bromigos session exec: {}: {e}", cmd[0].to_string_lossy());
            return Ok(127);
        }
        return Ok(1);
    };
    if a.mode.is_some() {
        match session::import(s) {
            Ok(_) => {}
            Err(e) => eprintln!("bromigos session: dbus-update-activation-environment: {e}"),
        }
    }
    let mut doc = session_json(&d);
    match a.mode {
        Some(SessionMode::Exec { cmd }) => {
            let e = session::exec(Some(s), &cmd);
            eprintln!("bromigos session exec: {}: {e}", cmd[0].to_string_lossy());
            return Ok(127);
        }
        Some(SessionMode::Adopt) => {
            let r = session::adopt(paths, s);
            doc["adopt"] = serde_json::to_value(&r)?;
            if !a.json {
                return Ok(0);
            }
        }
        Some(SessionMode::Import) | None => {}
        Some(SessionMode::ShellEnv | SessionMode::Hold { .. } | SessionMode::Release { .. }) => {
            unreachable!()
        }
    }
    if a.json {
        println!("{doc}");
    } else {
        for (k, v) in s.env() {
            println!("{k}={v}");
        }
    }
    Ok(0)
}

/// One line of a hook's output; a closed pipe (pacman killed) isn't worth a panic.
fn say(line: &str) {
    use std::io::Write;
    let _ = writeln!(std::io::stdout(), "{line}");
}

/// `bromigos session hold`: pacman's PreTransaction hook (bromigos-hypr-hold.hook). Never
/// fails a transaction: under pacman it always exits 0 and says what went wrong.
fn hold_cmd(paths: &Paths, pacman: bool, json_out: bool) -> Result<i32> {
    use bromigos_core::hypr_hold;
    let scope = hypr_hold::Scope::for_caller(paths);
    // under pacman the watcher comes first, so a transaction that dies mid-hold is covered
    let mut watcher = None;
    if pacman && !hypr_hold::compositors(&scope).is_empty() {
        match hypr_hold::spawn_watcher() {
            Ok(None) => return Ok(0), // pacman is gone: no transaction to hold for
            w => watcher = Some(w),
        }
    }
    let out = hypr_hold::hold(&scope);
    if json_out {
        say(&json!({"schema": SCHEMA, "held": out,
        "watcher": watcher.as_ref().map(|w| match w {
            Ok(Some([(pid, start), _])) => json!({"after": pid, "start": start}),
            Ok(None) => Value::Null,
            Err(e) => json!({"error": e}),
        })})
        .to_string());
    } else {
        if out.is_empty() && !pacman {
            say("no running Hyprland");
        }
        for o in &out {
            say(&o.line());
        }
        if let Some(Err(e)) = &watcher {
            say(&format!(
                "bromigOS: no watcher ({e}): if this transaction fails, run bromigos session release"
            ));
        }
    }
    Ok(if pacman || out.iter().all(|o| o.ok) {
        0
    } else {
        1
    })
}

/// `bromigos session release`: pacman's PostTransaction hook (bromigos-hypr-release.hook),
/// or the hold's watcher (`--after`).
fn release_cmd(paths: &Paths, pacman: bool, after: Option<&str>, json_out: bool) -> Result<i32> {
    use bromigos_core::hypr_hold;
    let scope = hypr_hold::Scope::for_caller(paths);
    let out = match after {
        Some(spec) => {
            let after = hypr_hold::parse_after(spec)
                .ok_or_else(|| anyhow::anyhow!("--after takes PID:START[,PID:START…]"))?;
            hypr_hold::watch_then_release(&scope, &after)
        }
        None => hypr_hold::release(&scope, pacman),
    };
    if json_out {
        say(&json!({"schema": SCHEMA, "released": out}).to_string());
    } else {
        if out.is_empty() && !pacman && after.is_none() {
            say("nothing held");
        }
        for o in &out {
            say(&o.line());
        }
    }
    Ok(if pacman || after.is_some() || out.iter().all(|o| o.ok) {
        0
    } else {
        1
    })
}

// ------------------------------------------------------------------ theme

fn theme_cmd(paths: &Paths, a: ThemeArgs) -> Result<i32> {
    let cur = theme::current(paths);
    match a.verb.unwrap_or(ThemeVerb::List) {
        ThemeVerb::List => {
            let themes = theme::list(paths);
            if a.json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "current": cur.name, "current_set": cur.set, "themes": themes})
                );
                return Ok(0);
            }
            for t in &themes {
                let mark = if t.name == cur.name { "*" } else { " " };
                let about = match &t.error {
                    Some(e) => format!("(broken: {e})"),
                    None => format!("{:<5} {}", t.mode, t.description),
                };
                println!("{mark} {:<14} {about}  [{}]", t.name, t.sources.join("+"));
            }
            if themes.is_empty() {
                println!(
                    "no themes in {}",
                    theme::Locations::new(paths).system_themes.display()
                );
            }
            Ok(0)
        }
        ThemeVerb::Current => {
            if a.json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "name": cur.name, "set": cur.set,
                           "default": theme::DEFAULT_THEME, "dir": cur.dir})
                );
            } else if cur.set {
                println!("{}", cur.name);
            } else {
                println!(
                    "{} (the default; not set yet: bromigos theme set {})",
                    cur.name, cur.name
                );
            }
            Ok(0)
        }
        ThemeVerb::Install {
            source,
            name,
            force,
        } => {
            // an alias: a theme is an extension (a git checkout bromigos ext update updates)
            let opts = bromigos_core::ext::InstallOpts {
                name,
                adopt: force,
                ..Default::default()
            };
            Ok(ext::install(paths, &source, &opts, a.json))
        }
        ThemeVerb::Remove { name } => {
            if let Some(owner) = bromigos_core::ext::theme_provider(paths, &name) {
                let only_theme = bromigos_core::ext::load_ledger(paths)
                    .ok()
                    .and_then(|l| l.extensions.get(&owner).map(|e| e.parts.len() == 1))
                    .unwrap_or(false);
                if !only_theme {
                    eprintln!(
                        "bromigos theme remove: {name} comes with the extension {owner}, which has \
                         more than this theme: bromigos ext remove {owner}"
                    );
                    return Ok(1);
                }
                return Ok(match bromigos_core::ext::remove(paths, &owner) {
                    Ok(r) => {
                        if a.json {
                            println!(
                                "{}",
                                json!({"schema": SCHEMA, "name": name, "extension": owner, "result": r})
                            );
                        } else {
                            println!("removed {name} (the extension {owner})");
                        }
                        0
                    }
                    Err(e) => {
                        eprintln!("bromigos theme remove: {e}");
                        1
                    }
                });
            }
            match theme::remove(paths, &name) {
                Ok(dir) => {
                    if a.json {
                        println!(
                            "{}",
                            json!({"schema": SCHEMA, "name": name, "removed": dir})
                        );
                    } else {
                        println!("removed {} ({})", name, dir.display());
                    }
                    Ok(0)
                }
                Err(e) => {
                    eprintln!("bromigos theme remove: {e}");
                    Ok(1)
                }
            }
        }
        ThemeVerb::New { name, from, dir } => {
            let dir = dir.unwrap_or_else(|| PathBuf::from(&name));
            let made = match &from {
                Some(f) => bromigos_core::ext::new_theme_from(paths, &name, f, &dir),
                None => {
                    bromigos_core::ext::new_starter(bromigos_core::ext::Kind::Theme, &name, &dir)
                }
            };
            match made {
                Ok(files) => {
                    // its preview, drawn now in the background: ready in the switcher once
                    // it's installed (the same files give the same picture)
                    let full = std::fs::canonicalize(&dir).unwrap_or_else(|_| dir.clone());
                    let previews =
                        bromigos_core::previews::render_in_background(&[], Some(full.as_path()));
                    if a.json {
                        println!(
                            "{}",
                            json!({"schema": SCHEMA, "name": name, "from": from, "dir": dir, "files": files,
                                   "previews": previews})
                        );
                    } else {
                        println!(
                            "a theme {name} in {}{}",
                            dir.display(),
                            from.as_deref()
                                .map(|f| format!(" (from {f})"))
                                .unwrap_or_default()
                        );
                        println!("  edit colors.toml and theme.toml (docs/theming.md), then:");
                        println!(
                            "  bromigos ext install --copy {}   (try it; bromigos ext update {name} after an edit)",
                            dir.display()
                        );
                        println!("  bromigos theme set {name}");
                        if let Some(p) = previews {
                            println!("  ({p})");
                        }
                    }
                    Ok(0)
                }
                Err(e) => {
                    eprintln!("bromigos theme new: {e}");
                    Ok(1)
                }
            }
        }
        ThemeVerb::Set { name, no_reload } => {
            let name = name.unwrap_or(cur.name);
            let report = match theme::set(paths, &name) {
                Ok(r) => r,
                Err(e) => {
                    eprintln!("bromigos theme: {e}");
                    return Ok(1);
                }
            };
            let reloads = if no_reload {
                Vec::new()
            } else {
                theme::reload(paths)
            };
            if a.json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "name": report.name, "display_name": report.display_name,
                           "dir": report.dir, "rendered": report.rendered,
                           "from_theme": report.from_theme, "icons": report.icons,
                           "motion": report.motion, "contrast": report.contrast,
                           "reloads": reloads})
                );
            } else {
                println!(
                    "theme: {} ({}) -> {}",
                    report.name,
                    report.display_name,
                    report.dir.display()
                );
                println!("  rendered: {}", report.rendered.join(", "));
                if !report.from_theme.is_empty() {
                    println!("  from the theme: {}", report.from_theme.join(", "));
                }
                if !report.icons.is_empty() {
                    println!(
                        "  icons: {} in the theme's colours (icons/)",
                        report.icons.len()
                    );
                }
                if report.contrast.mode == "high" || report.motion != "full" {
                    println!(
                        "  accessibility: contrast {}{}, motion {} (bromigos accessibility)",
                        report.contrast.mode,
                        if report.contrast.ok {
                            ""
                        } else {
                            " (some pairs short: bromigos accessibility check)"
                        },
                        report.motion
                    );
                }
                for r in &reloads {
                    let who = match r.pids.len() {
                        0 => String::new(),
                        1 => " (1 process)".to_owned(),
                        n => format!(" ({n} processes)"),
                    };
                    println!(
                        "  {:<9} {}{}{}{}",
                        r.app,
                        r.action,
                        who,
                        if r.ok { "" } else { ": FAILED" },
                        r.detail
                            .as_deref()
                            .map(|d| format!(" [{d}]"))
                            .unwrap_or_default()
                    );
                }
            }
            Ok(if reloads.iter().all(|r| r.ok) { 0 } else { 1 })
        }
    }
}

// ------------------------------------------------------------------ anim

fn anim_json(paths: &Paths) -> Result<Value> {
    let (merged, ov) = config::load_merged(paths)?;
    let on = |s: &str, k: &str| config::lookup(&merged, s, k).is_none_or(config::truthy);
    Ok(json!({
        "schema": SCHEMA,
        "background": on("background", "enabled"),
        "overrides": paths.live_overrides,
        "animations": ANIMS.iter().map(|a| json!({
            "name": a.name,
            "on": a.keys.iter().all(|(s, k)| on(s, k)),
            "overridden": a.keys.iter().any(|(s, k)| ov.contains(s, k)),
            "description": a.description,
            "keys": a.key_refs(),
        })).collect::<Vec<_>>(),
    }))
}

fn print_anim_list(doc: &Value) {
    let bg = doc["background"].as_bool().unwrap_or(true);
    println!(
        "background layer: {} (bromigos live on|off for the whole thing)\n",
        if bg { "on" } else { "OFF" }
    );
    for a in doc["animations"].as_array().into_iter().flatten() {
        println!(
            "  {:<12} {} {} {}",
            a["name"].as_str().unwrap_or_default(),
            if a["on"].as_bool() == Some(true) {
                "on "
            } else {
                "OFF"
            },
            if a["overridden"].as_bool() == Some(true) {
                "*"
            } else {
                " "
            },
            a["description"].as_str().unwrap_or_default()
        );
    }
    println!("\n  * = your switch (bromigos anim reset … returns to the default)");
}

fn anim_cmd(paths: &Paths, a: AnimArgs) -> Result<i32> {
    let message = match a.verb {
        None => {
            if !a.names.is_empty() {
                eprintln!("bromigos anim [on|off|reset] [name … | all]");
                return Ok(2);
            }
            None
        }
        Some(verb) => {
            let reset_all = matches!(verb, AnimVerb::Reset) && a.names.is_empty();
            let chosen = if reset_all {
                ANIMS.iter().collect()
            } else {
                match anim::resolve(&a.names) {
                    Ok(c) => c,
                    Err(e) => {
                        eprintln!("{e}");
                        return Ok(1);
                    }
                }
            };
            let mut ov = Overrides::load(paths)?;
            for an in &chosen {
                for (s, k) in an.keys {
                    match verb {
                        AnimVerb::On => ov.set(s, k, true)?,
                        AnimVerb::Off => ov.set(s, k, false)?,
                        AnimVerb::Reset => ov.remove(s, k),
                    }
                }
            }
            ov.save(paths)?;
            let names: Vec<&str> = chosen.iter().map(|a| a.name).collect();
            Some(match verb {
                AnimVerb::On | AnimVerb::Off => format!(
                    "{}: {} (applies within a few seconds)",
                    if matches!(verb, AnimVerb::On) {
                        "on"
                    } else {
                        "off"
                    },
                    names.join(", ")
                ),
                AnimVerb::Reset if a.names.is_empty() => "back to the defaults".to_owned(),
                AnimVerb::Reset => format!("back to the defaults: {}", a.names.join(", ")),
            })
        }
    };
    let doc = anim_json(paths)?;
    if a.json {
        println!("{doc}");
    } else if let Some(m) = message {
        println!("{m}");
    } else {
        print_anim_list(&doc);
    }
    Ok(0)
}

// ------------------------------------------------------------------ profile

fn profile_json(f: &ProfileFile) -> Value {
    let p = f.profile();
    json!({
        "schema": SCHEMA,
        "path": f.path,
        "exists": f.exists,
        "you": p,
        "addressed_as": p.addressed_as(),
    })
}

fn print_profile(f: &ProfileFile) {
    let p = f.profile();
    let one = |v: &Option<String>| v.clone().unwrap_or_else(|| "-".into());
    let many = |v: &[String]| {
        if v.is_empty() {
            "-".into()
        } else {
            v.join(", ")
        }
    };
    println!("name       {}", one(&p.name));
    println!("full_name  {}", one(&p.full_name));
    println!("aliases    {}", many(&p.aliases));
    println!("address    {}", many(&p.address));
    println!("pronouns   {}", one(&p.pronouns));
    println!(
        "\n{}{}",
        f.path.display(),
        if f.exists { "" } else { " (not created yet)" }
    );
}

fn profile_cmd(paths: &Paths, a: ProfileArgs) -> Result<i32> {
    let mut f = ProfileFile::load(paths)?;
    let message = match a.cmd {
        None | Some(ProfileCmd::Show) => None,
        Some(ProfileCmd::Set { field, value }) => {
            let field = match field {
                ProfileField::Name => Field::Name,
                ProfileField::FullName => Field::FullName,
                ProfileField::Pronouns => Field::Pronouns,
            };
            f.set(field, &value)?;
            Some(match value.trim() {
                "" => format!("{}: cleared", field.key()),
                v => format!("{}: {v}", field.key()),
            })
        }
        Some(ProfileCmd::Address { verb, values }) => {
            if values.is_empty() && !matches!(verb, ListVerb::Set) {
                eprintln!("bromigos profile address add|remove|set VALUE…");
                return Ok(2);
            }
            Some(list_edit(&mut f, List::Address, verb, &values)?)
        }
        Some(ProfileCmd::Alias { verb, values }) => {
            let verb = match verb {
                AliasVerb::Add => ListVerb::Add,
                AliasVerb::Remove => ListVerb::Remove,
            };
            Some(list_edit(&mut f, List::Aliases, verb, &values)?)
        }
    };
    if let Some(m) = &message {
        f.save()?;
        if !a.json {
            println!("{m}");
        }
    }
    if a.json {
        println!("{}", profile_json(&f));
    } else if message.is_none() {
        print_profile(&f);
    }
    Ok(0)
}

/// Applies a list edit; returns the line to print (the list as it is now).
fn list_edit(f: &mut ProfileFile, list: List, verb: ListVerb, values: &[String]) -> Result<String> {
    let removed = match verb {
        ListVerb::Add => f.add(list, values).map(|()| None)?,
        ListVerb::Remove => Some(f.remove(list, values)?),
        ListVerb::Set => f.replace(list, values).map(|()| None)?,
    };
    let now = f.profile();
    let items = match list {
        List::Address => now.address,
        List::Aliases => now.aliases,
    };
    Ok(format!(
        "{}: {}{}",
        list.key(),
        if items.is_empty() {
            "(none)".to_owned()
        } else {
            items.join(", ")
        },
        if removed == Some(0) {
            " (nothing matched)"
        } else {
            ""
        }
    ))
}

// ------------------------------------------------------------------ live

fn live_cmd(paths: &Paths, args: Vec<OsString>) -> Result<i32> {
    let sub = args.first().and_then(|s| s.to_str()).unwrap_or("status");
    if sub != "on" && sub != "off" {
        let args = if args.is_empty() {
            vec![OsString::from("status")]
        } else {
            args
        };
        return Ok(exec_or_report(&paths.live_bin, &args));
    }
    // the runtime toggle of the whole background (SUPER+SHIFT+B)
    let state = match ipc::live(paths, "state") {
        Ok(s) => s,
        Err(IpcError::NotRunning(_)) => {
            println!("not running (bromigos-live start)");
            return Ok(1);
        }
        Err(e) => return Err(e.into()),
    };
    let is_on = !state.contains("background off");
    if (sub == "on") != is_on {
        println!("{}", ipc::live(paths, "toggle")?);
    } else {
        println!("background already {sub}");
    }
    Ok(0)
}

// ------------------------------------------------------------------ status

/// The live layer's supervisor: `PID START` in its PID file (a bare PID from an older one).
fn supervisor_pid(paths: &Paths) -> Option<i32> {
    let pid = std::fs::read_to_string(paths.live_pid_file())
        .ok()?
        .split_whitespace()
        .next()?
        .parse::<i32>()
        .ok()?;
    session::pid_alive(pid).then_some(pid)
}

/// Whether a process runs in this user service (its cgroup's last part is the unit).
fn in_unit(pid: i32, unit: &str) -> bool {
    std::fs::read_to_string(format!("/proc/{pid}/cgroup"))
        .is_ok_and(|c| c.lines().any(|l| l.ends_with(&format!("/{unit}"))))
}

/// What brings the session's pieces back when one is missing (Settings › Startup's Fix):
/// `bromigos restart` with the missing ones' names starts them.
fn status_fix(bar: bool, live: bool) -> Option<String> {
    let missing: Vec<&str> = [("waybar", bar), ("live", live)]
        .iter()
        .filter(|(_, up)| !up)
        .map(|(n, _)| *n)
        .collect();
    (!missing.is_empty()).then(|| format!("bromigos restart {}", missing.join(" ")))
}

fn status_cmd(paths: &Paths, json_out: bool) -> Result<i32> {
    let d = session::discover(paths);
    let supervisor = supervisor_pid(paths);
    let live_state = ipc::live(paths, "state").ok();
    let bar_pids: Vec<i32> = update::running(Path::new("/proc"))
        .into_iter()
        .filter(|r| r.piece == Piece::Waybar)
        .flat_map(|r| r.pids)
        .collect();
    let bar_service = bar_pids.iter().any(|p| in_unit(*p, "bromigos-bar.service"));
    let live_service = supervisor.is_some_and(|p| in_unit(p, "bromigos-live.service"));
    let live_up = supervisor.is_some() || live_state.is_some();
    // only with a session to run them in
    let fix = d
        .session
        .as_ref()
        .and_then(|_| status_fix(!bar_pids.is_empty(), live_up));
    let muted = paths.live_muted().exists();
    let holo = ipc::holo(paths, "status").ok();
    let switched_off = paths.vector_switched_off();
    let anims = anim_json(paths)?;
    if json_out {
        let doc = json!({
            "schema": SCHEMA,
            "session": session_json(&d),
            "bar": {
                "running": !bar_pids.is_empty(),
                "pids": bar_pids,
                "service": bar_service,
            },
            "live": {
                "running": live_up,
                "service": live_service,
                "supervisor_pid": supervisor,
                "state": live_state,
                "background": live_state.as_deref().map(|s| !s.contains("background off")),
                "sounds": if muted { "muted" } else { "on" },
            },
            "vector": {
                "running": holo.is_some(),
                "status": holo.as_deref().map(|s| serde_json::from_str::<Value>(s)
                    .unwrap_or_else(|_| Value::String(s.to_owned()))),
                "terminal": !switched_off,
                "switch": if switched_off { "off" } else { "on" },
            },
            "animations": anims,
            "fix": fix,
        });
        println!("{doc}");
        return Ok(0);
    }
    println!("── session");
    match &d.session {
        Some(s) => println!(
            "{} on {}{}",
            s.signature,
            s.wayland_display,
            if s.nested { " (nested)" } else { "" }
        ),
        None => println!("no running Hyprland session found"),
    }
    println!("\n── the bar");
    match (bar_pids.first(), bar_service) {
        (Some(p), true) => {
            println!("running (pid {p}; bromigos-bar.service: back by itself if it stops)")
        }
        (Some(p), false) => println!("running (pid {p})"),
        (None, _) => println!("not running"),
    }
    println!("\n── live layer");
    match (supervisor, &live_state) {
        (Some(p), st) => {
            let how = if live_service {
                "; bromigos-live.service"
            } else {
                ""
            };
            println!("daemon up (supervisor {p}{how})");
            if let Some(st) = st {
                println!("{}", st.trim_end());
            }
        }
        (None, Some(st)) => println!("daemon up (no supervisor)\n{}", st.trim_end()),
        (None, None) => println!("stopped"),
    }
    println!("sounds: {}", if muted { "muted" } else { "on" });
    println!("\n── VECTOR");
    match holo.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        Some(st) => println!("{}", st.chars().take(300).collect::<String>()),
        None => println!("not running (starts when summoned)"),
    }
    println!(
        "emergency switch: {}",
        if switched_off {
            "OFF (bromigos vector on, or SUPER+CTRL+ESCAPE)"
        } else {
            "on"
        }
    );
    println!("\n── animations");
    print_anim_list(&anims);
    if let Some(f) = fix {
        println!("\nnot everything is running: {f} starts it again");
    }
    Ok(0)
}

// ------------------------------------------------------------------ commands

fn commands_cmd(
    paths: &Paths,
    dirs: &[std::path::PathBuf],
    json_out: bool,
    check: bool,
    all: bool,
) -> Result<i32> {
    let scan = commands::scan(dirs);
    let builtins = builtins(paths);
    if check {
        let issues = commands::check(&scan, &builtins);
        if json_out {
            println!(
                "{}",
                json!({"schema": SCHEMA, "ok": issues.is_empty(), "issues": issues})
            );
        } else if issues.is_empty() {
            println!("ok: {} external commands", scan.commands.len());
        } else {
            for i in &issues {
                println!(
                    "{}: {} ({}): {}",
                    i.kind,
                    i.command,
                    i.path.display(),
                    i.detail
                );
            }
        }
        return Ok(if issues.is_empty() { 0 } else { 1 });
    }
    let cli = Cli::command();
    let summaries: Vec<(String, String)> = cli
        .get_subcommands()
        .map(|c| {
            (
                c.get_name().to_owned(),
                c.get_about().map(|s| s.to_string()).unwrap_or_default(),
            )
        })
        .collect();
    if json_out {
        println!(
            "{}",
            json!({
                "schema": SCHEMA,
                "groups": GROUPS,
                "builtins": summaries.iter().map(|(n, s)| json!({"name": n, "summary": s})).collect::<Vec<_>>(),
                "commands": scan.commands,
            })
        );
        return Ok(0);
    }
    println!("built-in");
    for (n, s) in &summaries {
        println!("  bromigos {n:<22} {s}");
    }
    let mut group = "";
    for c in scan.commands.iter().filter(|c| all || !c.header.hidden) {
        if c.group != group {
            group = &c.group;
            println!("\n{group}");
        }
        let call = match &c.header.args {
            Some(a) => format!("{} {a}", c.route),
            None => c.route.clone(),
        };
        println!(
            "  {call:<31} {}{}",
            c.header.summary.as_deref().unwrap_or("(no summary)"),
            if c.header.hidden { " [hidden]" } else { "" }
        );
    }
    Ok(0)
}

// ------------------------------------------------------------------ update, restart

fn short_list(items: &[String], n: usize) -> String {
    let names: Vec<&str> = items
        .iter()
        .map(|p| p.split(' ').next().unwrap_or(p))
        .collect();
    if names.len() <= n {
        names.join(", ")
    } else {
        format!("{}, … ({} more)", names[..n].join(", "), names.len() - n)
    }
}

fn channel_cmd(
    paths: &Paths,
    name: Option<&str>,
    repo: Option<&str>,
    dev_dir: Option<&Path>,
    json: bool,
) -> Result<i32> {
    use bromigos_core::channel;
    if let Some(name) = name {
        let ch = channel::Channel::parse(name)
            .ok_or_else(|| anyhow::anyhow!("no such channel: {name} (stable, rc, edge, dev)"))?;
        if repo.is_none()
            && let Err(lack) = channel::ready(paths, ch)
        {
            let from = channel::current(paths).channel;
            channel::set_wanted(paths, Some(ch));
            let words = channel::waiting_words(from, ch, &lack);
            if json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "waiting": {"channel": ch, "lacks": lack, "words": words}})
                );
            } else {
                println!("{words}");
            }
            return Ok(0);
        }
        let c = channel::set(paths, ch, repo, dev_dir).map_err(anyhow::Error::msg)?;
        channel::set_wanted(paths, None);
        if json {
            println!("{}", json!({"schema": SCHEMA, "channel": c}));
            return Ok(0);
        }
        println!(
            "channel: {} (was {}); {}: Server = {}",
            c.to,
            c.from.map_or("unknown".to_owned(), |f| f.to_string()),
            c.conf.display(),
            c.server
        );
        if !c.dropped.is_empty() {
            println!("the old channel's database dropped: the next update fetches the new one's");
        }
        println!(
            "next: bromigos update{}",
            if c.downgrade {
                " --downgrade  (packages newer than the channel's go back)"
            } else {
                ""
            }
        );
        return Ok(0);
    }
    let cur = channel::current(paths);
    if json {
        println!(
            "{}",
            json!({"schema": SCHEMA, "channel": cur, "wanted": channel::wanted(paths).filter(|w| Some(*w) != cur.channel)})
        );
        return Ok(0);
    }
    match cur.channel {
        Some(ch) => println!("{ch}: {}", ch.describe()),
        None => println!(
            "unknown: {} has no [bromigos] Server line this command knows",
            cur.conf.display()
        ),
    }
    if let Some(s) = &cur.server {
        println!("  Server = {s}");
    }
    if let Some(w) = channel::wanted(paths).filter(|w| Some(*w) != cur.channel) {
        println!(
            "  moving to {w} by itself at an update, once it has every bromigOS package here (after its next release)"
        );
    }
    println!("channels:");
    for ch in channel::Channel::ALL {
        println!("  {:<7} {}", ch.as_str(), ch.describe());
    }
    println!("switch: bromigos channel <name> (then bromigos update)");
    Ok(0)
}

fn rollback_cmd(paths: &Paths, pre: Option<u64>, yes: bool, json: bool) -> Result<i32> {
    use bromigos_core::snapshot;
    let mut sys = install::System;
    let env = snapshot::detect(&mut sys, &snapshot::RootFs);
    if let Some(b) = &env.booted {
        return booted_rollback_cmd(paths, &mut sys, b, pre, yes, json);
    }
    if !env.snapshots() {
        anyhow::bail!("no snapshots here: {}", env.summary());
    }
    let t = snapshot::target(paths, &mut sys, pre).map_err(anyhow::Error::msg)?;
    if !json {
        println!(
            "rolling back the update of {} (snapshots {}..{}, channel {}):",
            t.record
                .at
                .get(..16)
                .unwrap_or(&t.record.at)
                .replace('T', " "),
            t.pair.pre,
            t.pair.post,
            t.record.channel.as_deref().unwrap_or("?")
        );
        if t.record.packages.is_empty() {
            println!("  no package changes were recorded");
        }
        for p in &t.record.packages {
            println!("  {p}");
        }
        println!(
            "  files on /: {} changed, {} created, {} deleted go back to how they were (pacman's database too)",
            t.changed, t.created, t.deleted
        );
    }
    if !yes {
        if json {
            anyhow::bail!("--rollback with --json needs --yes");
        }
        print!("undo it? [y/N] ");
        std::io::Write::flush(&mut std::io::stdout())?;
        let mut line = String::new();
        std::io::stdin().read_line(&mut line)?;
        if !matches!(line.trim(), "y" | "Y" | "yes") {
            println!("left as is");
            return Ok(1);
        }
    }
    let r = snapshot::undo(paths, &env, &mut sys, &t).map_err(anyhow::Error::msg)?;
    if json {
        println!("{}", json!({"schema": SCHEMA, "rollback": r}));
        return Ok(0);
    }
    println!(
        "rolled back: snapshots {}..{} undone",
        r.pair.pre, r.pair.post
    );
    for n in &r.notes {
        println!("  {n}");
    }
    Ok(0)
}

/// Asks "[y/N]" on the terminal: whether the answer was yes.
fn confirm(question: &str) -> Result<bool> {
    print!("{question} [y/N] ");
    std::io::Write::flush(&mut std::io::stdout())?;
    let mut line = String::new();
    std::io::stdin().read_line(&mut line)?;
    Ok(matches!(line.trim(), "y" | "Y" | "yes"))
}

/// `bromigos update --rollback` on a snapshot booted from the boot menu: that snapshot
/// becomes the root (a writable copy takes the root subvolume's name, the old root is kept),
/// so the next normal boot comes up on it.
fn booted_rollback_cmd(
    paths: &Paths,
    sys: &mut install::System,
    b: &bromigos_core::snapshot::Booted,
    pre: Option<u64>,
    yes: bool,
    json: bool,
) -> Result<i32> {
    use bromigos_core::snapshot;
    if let Some(p) = pre.filter(|p| *p != b.number) {
        anyhow::bail!(
            "this boot is snapshot {}, so --rollback here makes that snapshot the root. To roll \
             back to snapshot {p} instead, choose it in the boot menu; to undo an update in \
             place, boot normally",
            b.number
        );
    }
    let stamp = snapshot::stamp();
    let plan = snapshot::make_root_plan(paths, sys, &snapshot::RootFs, b, &stamp)
        .map_err(anyhow::Error::msg)?;
    if !json {
        let what = match (&plan.date, &plan.description) {
            (Some(d), Some(t)) => format!(" ({d} UTC, {t})"),
            (Some(d), None) => format!(" ({d} UTC)"),
            _ => String::new(),
        };
        println!(
            "this boot is snapshot {}{what}, from the boot menu. Rolling back to it makes it \
             the root, so the next normal boot comes up on it:",
            b.number
        );
        println!(
            "  a writable copy of the snapshot becomes {} (the root /etc/fstab mounts)",
            plan.root
        );
        println!("  the root it replaces is kept as {}", plan.kept);
        if plan.undoes.is_empty() {
            println!("  no recorded update came after it");
        }
        for r in &plan.undoes {
            println!(
                "  undoes the update of {}:",
                r.at.get(..16).unwrap_or(&r.at).replace('T', " ")
            );
            for p in &r.packages {
                println!("    {p}");
            }
        }
        for k in &plan.kernels {
            println!(
                "  /boot's kernel ({}) isn't the snapshot's: {} {} goes back into /boot",
                plan.running_kernel, k.pkgbase, k.release
            );
        }
        for n in &plan.notes {
            println!("  {n}");
        }
        println!("  it runs:");
        for (_, c) in &plan.steps {
            println!("    {}", c.join(" "));
        }
    }
    if !yes {
        if json {
            anyhow::bail!("--rollback with --json needs --yes");
        }
        if !confirm("make it the root?")? {
            println!("left as is");
            return Ok(1);
        }
    }
    let r = snapshot::make_root(paths, sys, &plan).map_err(anyhow::Error::msg)?;
    if json {
        println!("{}", json!({"schema": SCHEMA, "rollback": r}));
        return Ok(0);
    }
    println!(
        "rolled back: snapshot {} is the root ({}) now",
        r.snapshot, r.root
    );
    for n in &r.notes {
        println!("  {n}");
    }
    Ok(0)
}

fn boot_cmd(paths: &Paths, a: BootArgs) -> Result<i32> {
    use bromigos_core::boot;
    let (action, no_prompt, auto, dry_run, json) = match a.what {
        None => ("status".to_owned(), false, false, false, false),
        Some(BootWhat::Theme {
            action,
            no_prompt,
            auto,
            dry_run,
            json,
        }) => (
            action.unwrap_or_else(|| "status".to_owned()),
            no_prompt,
            auto,
            dry_run,
            json,
        ),
    };
    let mut sys = install::System;
    let files = bromigos_core::snapshot::RootFs;
    let outcome = match action.as_str() {
        "status" => {
            let st = boot::status(paths, &mut sys, &files);
            if json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "boot": st, "summary": st.summary()})
                );
            } else {
                println!("boot menu: {}", st.summary());
                if st.grub() && st.helper {
                    match &st.want {
                        boot::Want::Package { theme, .. } => {
                            println!("  theme: {theme}, rendered by bromigos-boot")
                        }
                        boot::Want::Render { theme, why } => {
                            println!("  theme: {theme}, rendered here ({why})")
                        }
                    }
                }
            }
            return Ok(0);
        }
        "on" => boot::sync(
            paths,
            &mut sys,
            &files,
            if auto {
                boot::Enable::Auto
            } else {
                boot::Enable::On
            },
            !no_prompt,
            dry_run,
        ),
        "apply" => boot::sync(
            paths,
            &mut sys,
            &files,
            boot::Enable::Keep,
            !no_prompt,
            dry_run,
        ),
        "off" => boot::off(&mut sys, &files, dry_run),
        other => anyhow::bail!("bromigos boot theme: {other}? (status, on, off, apply)"),
    };
    if json {
        println!("{}", json!({"schema": SCHEMA, "outcome": outcome}));
    } else {
        for c in &outcome.commands {
            if dry_run {
                println!("would run: {c}");
            }
        }
        println!("boot menu: {}", outcome.detail);
    }
    Ok(if outcome.status == "failed" { 1 } else { 0 })
}

fn rollback_tool_cmd(
    paths: &Paths,
    action: &str,
    dry_run: bool,
    yes: bool,
    json: bool,
) -> Result<i32> {
    use bromigos_core::snapshot;
    let mut sys = install::System;
    let files = snapshot::RootFs;
    let env = snapshot::detect(&mut sys, &files);
    match action {
        "status" => {
            // the rollbacks only: the AUR isn't asked (no_aur)
            let c = update::check(paths, true);
            if json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "snapshots": c.snapshots, "rollbacks": c.rollbacks})
                );
                return Ok(0);
            }
            println!("snapshots: {}", env.summary());
            if env.booted.is_some() {
                // the summary said what --rollback does here; the list is for a normal boot
            } else if c.rollbacks.is_empty() {
                println!("rollback: no recorded update with a snapshot pair");
            } else {
                println!("rollback (bromigos update --rollback [PRE]):");
                for r in &c.rollbacks {
                    let p = r.snapshot.unwrap();
                    println!(
                        "  pre {:<5} {}  {}",
                        p.pre,
                        r.at.get(..16).unwrap_or(&r.at).replace('T', " "),
                        short_list(&r.packages, 4)
                    );
                }
            }
            if env.needs_setup() {
                println!("setup: bromigos rollback setup");
            }
            Ok(0)
        }
        "setup" => {
            let who = snapshot::who(&mut sys);
            let mut plan = snapshot::setup_plan(&env, &mut sys, &files, &who);
            if yes {
                plan.noconfirm();
            }
            let mut ran = vec![];
            let mut failed = None;
            for a in &plan.commands {
                let line = a.join(" ");
                if dry_run {
                    ran.push(format!("would run: {line}"));
                    continue;
                }
                if !json {
                    println!("+ {line}");
                }
                match install::Runner::run(&mut sys, a, true) {
                    Ok((0, _)) => ran.push(line),
                    Ok((code, out)) => {
                        failed = Some(format!("`{line}` exited {code} {}", out.trim()));
                        break;
                    }
                    Err(e) => {
                        failed = Some(format!("`{line}`: {e}"));
                        break;
                    }
                }
            }
            if plan.allow && failed.is_none() {
                if dry_run {
                    ran.push(
                        "would run: bromigos rollback allow (you may not list root's snapshots)"
                            .to_owned(),
                    );
                } else {
                    match snapshot::allow(&env, &mut sys, &who) {
                        Ok(Some(set)) => {
                            let line = set.join(" ");
                            if !json {
                                println!("+ {line}");
                            }
                            ran.push(line);
                        }
                        Ok(None) => {}
                        Err(e) => failed = Some(format!("bromigos rollback allow: {e}")),
                    }
                }
            }
            let after = snapshot::detect(&mut sys, &files);
            if json {
                println!(
                    "{}",
                    json!({"schema": SCHEMA, "setup": {"ran": ran, "notes": plan.notes, "failed": failed, "after": after}})
                );
                return Ok(if failed.is_some() { 1 } else { 0 });
            }
            for l in &ran {
                if dry_run {
                    println!("{l}");
                }
            }
            for n in &plan.notes {
                println!("note: {n}");
            }
            if let Some(f) = failed {
                eprintln!("bromigos rollback setup: {f}");
                return Ok(1);
            }
            if plan.commands.is_empty() && !plan.allow {
                println!("nothing to do: {}", after.summary());
            } else if !dry_run {
                println!("done: {}", after.summary());
            }
            Ok(0)
        }
        "allow" => {
            let who = snapshot::who(&mut sys);
            let name = who.user.clone().unwrap_or_else(|| "root".to_owned());
            if dry_run {
                let line = format!(
                    "would run: sudo snapper -c {} get-config, then set-config with what's missing of \
                     ALLOW_GROUPS={} (the groups there stay), {name} in ALLOW_USERS unless a group \
                     allows them, SYNC_ACL=yes",
                    snapshot::CONFIG,
                    snapshot::ALLOW_GROUP
                );
                if json {
                    println!("{}", json!({"schema": SCHEMA, "allow": {"dry_run": line}}));
                } else {
                    println!("{line}");
                }
                return Ok(0);
            }
            match snapshot::allow(&env, &mut sys, &who) {
                Ok(set) => {
                    if json {
                        println!(
                            "{}",
                            json!({"schema": SCHEMA, "allow": {"user": who.user, "ran": set.as_ref().map(|s| s.join(" "))}})
                        );
                    } else if let Some(set) = set {
                        println!("+ {}", set.join(" "));
                        println!(
                            "allowed: {name} and {} may list root's snapshots (updates are recorded for --rollback)",
                            snapshot::ALLOW_GROUP
                        );
                    } else {
                        println!(
                            "nothing to change: {name} and {} may list root's snapshots",
                            snapshot::ALLOW_GROUP
                        );
                    }
                    Ok(0)
                }
                Err(e) => {
                    eprintln!("bromigos rollback allow: {e}");
                    Ok(1)
                }
            }
        }
        other => anyhow::bail!("bromigos rollback: status, setup or allow, not {other}"),
    }
}

fn print_plans(plans: &[update::Plan]) {
    if plans.is_empty() {
        println!("  nothing: everything running is as new as what's installed");
    }
    for p in plans {
        let need = match p.need {
            Need::Restart => "restart",
            Need::Reload => "reload",
            Need::Relogin => "log out and back in",
            Need::Reboot => "reboot",
            Need::Start => "start",
            Need::Notify => "ask (notification)",
            Need::Itself => "restarts itself",
            Need::Stale => "stale (restart it yourself)",
        };
        println!("  {:<9} {need}: {}", p.what, p.why);
    }
}

fn print_done(done: &[update::Done]) -> bool {
    if done.is_empty() {
        println!("  nothing to restart");
    }
    let mut ok = true;
    for d in done {
        ok &= d.ok;
        let mark = if d.ok { "" } else { "FAILED: " };
        match &d.detail {
            Some(x) => println!("  {:<9} {mark}{} ({x})", d.what, d.action),
            None => println!("  {:<9} {mark}{}", d.what, d.action),
        }
    }
    ok
}

/// `bromigos update`'s flags.
struct UpdateFlags {
    check: bool,
    no_packages: bool,
    downgrade: bool,
    yes: bool,
    no_aur: bool,
    json: bool,
}

fn update_cmd(paths: &Paths, f: &UpdateFlags, channel: Option<&str>) -> Result<i32> {
    let json = f.json;
    if f.check {
        let c = update::check(paths, f.no_aur);
        if json {
            println!("{}", json!({"schema": SCHEMA, "check": c}));
            return Ok(0);
        }
        println!(
            "channel: {}",
            c.channel.map_or(
                "unknown (no [bromigos] Server line)".to_owned(),
                |ch| format!("{ch} ({})", ch.describe())
            )
        );
        println!("packages:");
        match &c.packages {
            None => println!(
                "  can't tell (checkupdates, from pacman-contrib, isn't installed or failed)"
            ),
            Some(v) if v.is_empty() => println!("  up to date"),
            Some(v) => {
                for a in v {
                    println!("  {:<28} {} -> {}", a.name, a.from, a.to);
                }
            }
        }
        for l in update::aur_check_lines(&c.aur) {
            println!("{l}");
        }
        println!("migrations:");
        if c.migrations.is_empty() {
            println!("  none pending");
        }
        for m in &c.migrations {
            println!("  {m}");
        }
        println!("restarts (as things are now; an upgrade adds its own):");
        print_plans(&c.restarts);
        println!("snapshots: {}", c.snapshots.summary());
        println!("boot menu: {}", c.boot);
        if c.snapshots.booted.is_some() {
            // the summary said what --rollback does here; the list is for a normal boot
        } else if c.rollbacks.is_empty() {
            println!("rollback: no recorded update with a snapshot pair");
        } else {
            println!("rollback (bromigos update --rollback [PRE]):");
            for r in &c.rollbacks {
                let p = r.snapshot.unwrap();
                println!(
                    "  pre {:<5} {}  {} package{}{}",
                    p.pre,
                    r.at.get(..16).unwrap_or(&r.at).replace('T', " "),
                    r.packages.len(),
                    if r.packages.len() == 1 { "" } else { "s" },
                    if r.packages.is_empty() {
                        String::new()
                    } else {
                        format!(": {}", short_list(&r.packages, 4))
                    }
                );
            }
        }
        return Ok(0);
    }
    let mut downgrade = f.downgrade;
    use bromigos_core::channel as chan;
    let mut asked =
        match channel {
            Some(name) => Some(chan::Channel::parse(name).ok_or_else(|| {
                anyhow::anyhow!("no such channel: {name} (stable, rc, edge, dev)")
            })?),
            None => None,
        };
    // a channel asked for earlier that wasn't ready: the move happens now, once it is
    if asked.is_none()
        && let Some(w) = chan::wanted(paths)
    {
        if chan::current(paths).channel == Some(w) {
            chan::set_wanted(paths, None);
        } else if chan::ready(paths, w).is_ok() {
            if !json {
                println!("== channel: {w} has everything this computer needs now: moving to it");
            }
            asked = Some(w);
        }
    }
    if let Some(ch) = asked
        && let Err(lack) = chan::ready(paths, ch)
    {
        // a move to an older channel that lacks a package here would stop on a file conflict:
        // it waits instead, and happens by itself at a later update
        let from = chan::current(paths).channel;
        chan::set_wanted(paths, Some(ch));
        let words = chan::waiting_words(from, ch, &lack);
        if json {
            eprintln!("{words}");
        } else {
            println!("== channel: {words}");
        }
        asked = None;
    }
    if let Some(ch) = asked {
        let c = chan::set(paths, ch, None, None).map_err(anyhow::Error::msg)?;
        chan::set_wanted(paths, None);
        if !json {
            println!(
                "== channel: {} (was {}){}",
                c.to,
                c.from.map_or("unknown".to_owned(), |f| f.to_string()),
                if c.dropped.is_empty() {
                    ""
                } else {
                    "; the old channel's database dropped (fetched afresh)"
                }
            );
        }
        if c.downgrade {
            downgrade = true;
        }
    }
    let mut before = update::installed(paths);
    let mut sys = install::System;
    let env = bromigos_core::snapshot::detect(&mut sys, &bromigos_core::snapshot::RootFs);
    let mut pacman = None;
    let mut aur = None;
    let mut pair = None;
    if !f.no_packages {
        use bromigos_core::aur as aur_mod;
        let aur_plan = aur_mod::plan(aur_mod::When::here(
            paths,
            &mut sys,
            f.no_aur,
            !json && std::io::IsTerminal::is_terminal(&std::io::stdin()),
            f.yes,
        ));
        let o = update::PackageOpts {
            downgrade,
            yes: f.yes,
            snap_pac: env.snap_pac,
            snapshots: env.summary(),
            aur: aur_plan,
        };
        let mut io = update::SystemIo {
            paths,
            env: &env,
            print: !json,
            helper_to_stderr: json,
        };
        let r = update::packages(&mut io, &o).map_err(anyhow::Error::msg)?;
        if !json {
            for w in &r.warnings {
                eprintln!("bromigos update: {w}");
            }
        }
        before = r.before.clone();
        pacman = r.pacman;
        aur = r.aur.clone();
        pair = r.pair;
        if !r.goes_on() {
            let code = r.pacman.unwrap_or(1);
            if json {
                let r = update::Report {
                    pacman: Some(code),
                    aur: None,
                    packages: vec![],
                    migrations: vec![],
                    migrations_ok: true,
                    theme: None,
                    theme_error: None,
                    previews: None,
                    games: None,
                    boot: None,
                    restarts: vec![],
                    snapshot: pair,
                    channel: bromigos_core::channel::current(paths)
                        .channel
                        .map(|c| c.to_string()),
                    reboot: None,
                };
                println!("{}", json!({"schema": SCHEMA, "report": r}));
            } else {
                eprintln!("bromigos update: pacman exited {code}; stopping before migrations");
            }
            return Ok(code);
        }
    }
    let r = update::finish(paths, pacman, aur, &before, pair);
    let restarts_ok = r.restarts.iter().all(|d| d.ok);
    let aur_ok = !r.aur.as_ref().is_some_and(|a| a.failed());
    if json {
        println!("{}", json!({"schema": SCHEMA, "report": r}));
        return Ok(if r.migrations_ok && restarts_ok && aur_ok {
            0
        } else {
            1
        });
    }
    println!("== packages changed: {}", r.packages.len());
    if pacman.is_some() {
        match r.snapshot {
            Some(p) => println!(
                "== snapshot: pre {}, post {} (bromigos update --rollback undoes this update)",
                p.pre, p.post
            ),
            None => println!("== snapshot: none ({})", env.summary()),
        }
    }
    for c in &r.packages {
        println!(
            "  {:<28} {} -> {}",
            c.name,
            c.from.as_deref().unwrap_or("(new)"),
            c.to.as_deref().unwrap_or("(removed)")
        );
    }
    if let Some(a) = &r.aur {
        print_aur(a);
    }
    if r.migrations.is_empty() {
        println!("== migrations: none pending");
    } else {
        println!("== migrations:");
    }
    for m in &r.migrations {
        match m.outcome {
            Outcome::Done => println!("  {} done", m.id),
            Outcome::Deferred => println!("  {} not yet (runs again next update)", m.id),
            Outcome::Failed => {
                println!(
                    "  {} FAILED (exit {}); the log: {}",
                    m.id,
                    m.code.map_or("signal".to_owned(), |c| c.to_string()),
                    paths.migrations_state_dir().join("log").display()
                );
                for l in m.tail.lines() {
                    println!("    {l}");
                }
            }
        }
    }
    if !r.migrations_ok {
        eprintln!(
            "bromigos update: stopped at the failed migration; fix it and run bromigos update again"
        );
        return Ok(1);
    }
    match (&r.theme, &r.theme_error) {
        (Some(t), _) => println!("== theme: {t} rendered again"),
        (None, Some(e)) => println!("== theme: FAILED: {e}"),
        _ => println!("== theme: none set"),
    }
    if let Some(p) = &r.previews {
        println!("== previews: {p}");
    } else if r
        .reboot
        .as_ref()
        .is_some_and(|n| n.held.iter().any(|h| h == "previews"))
    {
        println!("== previews: not drawn until the computer restarts (they need the GPU)");
    }
    if let Some(b) = &r.boot {
        match b.status {
            "failed" => println!("== boot menu: FAILED: {}", b.detail),
            _ => println!("== boot menu: {}", b.detail),
        }
    }
    println!("== restarts:");
    let ok = print_done(&r.restarts);
    if let Some(g) = &r.games {
        println!("== games: {g}");
    }
    // a new release came with this update: say once where its notes are
    if let Some(n) = bromigos_core::whats_new::announce(paths) {
        println!("== what's new: bromigOS {} (bromigos whats-new)", n.version);
    }
    if !aur_ok {
        eprintln!(
            "bromigos update: done, but AUR packages weren't all updated (above: what and how to retry)"
        );
    }
    // a new kernel or graphics driver: the update's last word
    if let Some(n) = &r.reboot {
        println!("\n{}", n.message);
    }
    Ok(if ok && r.theme_error.is_none() && aur_ok {
        0
    } else {
        1
    })
}

/// The AUR step's summary in the update's report.
fn print_aur(a: &bromigos_core::aur::Outcome) {
    match a.status {
        "skipped" => println!("== AUR: left out: {}", a.detail),
        "none" => println!("== AUR: up to date"),
        "done" => println!("== AUR: {}", a.detail),
        _ => {
            println!("== AUR: FAILED: {}", a.detail);
            if let Some(r) = &a.retry {
                println!("  retry: {r}");
            }
        }
    }
}

fn whats_new_cmd(paths: &Paths, release: Option<&str>, all: bool) -> Result<i32> {
    use bromigos_core::whats_new;
    let releases = whats_new::installed(paths);
    if releases.is_empty() {
        eprintln!(
            "bromigos whats-new: no release notes installed ({} isn't there or has none yet)",
            whats_new::file(paths).display()
        );
        return Ok(1);
    }
    let shown: Vec<&whats_new::Release> = match release {
        _ if all => releases.iter().collect(),
        None => releases.iter().take(1).collect(),
        Some(v) => {
            let v = v.trim_start_matches('v');
            match releases.iter().find(|r| r.version == v || r.id == v) {
                Some(r) => vec![r],
                None => {
                    let known: Vec<&str> = releases.iter().map(|r| r.version.as_str()).collect();
                    eprintln!(
                        "bromigos whats-new: no notes for {v} (installed: {})",
                        known.join(", ")
                    );
                    return Ok(1);
                }
            }
        }
    };
    for (i, r) in shown.iter().enumerate() {
        if i > 0 {
            println!();
        }
        println!("bromigOS {}\n\n{}", r.version, r.text);
    }
    if !all && releases.len() > 1 {
        println!("\n(older releases: bromigos whats-new --all)");
    }
    let _ = whats_new::mark_seen(paths, &releases[0].id);
    Ok(0)
}

fn restart_cmd(paths: &Paths, pieces: &[String], check: bool, json: bool) -> Result<i32> {
    let mut only = Vec::new();
    let mut units = Vec::new();
    let declared = update::declared(paths);
    for p in pieces {
        match Piece::parse(p) {
            Some(x) => only.push(x),
            None if bromigos_core::restartd::find_unit(&declared, p).is_some() => {
                units.push(p.clone())
            }
            None => {
                let mut known: Vec<String> =
                    Piece::ALL.iter().map(|p| p.name().to_owned()).collect();
                known.extend(
                    declared
                        .iter()
                        .flat_map(|d| d.units.iter().map(|u| u.name.clone())),
                );
                eprintln!("bromigos restart: unknown: {p} ({})", known.join(", "));
                return Ok(2);
            }
        }
    }
    let plans = update::restart_plan_for(paths, &only, &units, &[]);
    if check {
        if json {
            println!("{}", json!({"schema": SCHEMA, "plan": plans}));
        } else {
            print_plans(&plans);
        }
        return Ok(0);
    }
    let done = update::execute(paths, &plans);
    if json {
        println!("{}", json!({"schema": SCHEMA, "plan": plans, "done": done}));
        return Ok(if done.iter().all(|d| d.ok) { 0 } else { 1 });
    }
    Ok(if print_done(&done) { 0 } else { 1 })
}

// ------------------------------------------------------------------ install, setup

fn install_cmd(
    paths: &Paths,
    opts: &install::Options,
    no_setup: bool,
    answers: Option<&Path>,
    json: bool,
) -> Result<i32> {
    let r = install::run(paths, opts, &mut install::System);
    let mut applied = vec![];
    // the first-run questions need a terminal: without one (install.sh with no terminal,
    // a script) they're left for `bromigos setup`, and the last line says so
    let mut unasked = no_setup && answers.is_none();
    if r.ok && !opts.dry_run && !no_setup {
        if let Some(f) = answers {
            let a = setup::load_answers(f).map_err(anyhow::Error::msg)?;
            applied = setup::apply(
                paths,
                &a,
                &setup::detect(paths),
                &bromigos_core::create::detect(paths),
                false,
                false,
            );
        } else if !json
            && std::io::IsTerminal::is_terminal(&std::io::stdin())
            && !setup::done_before(paths)
        {
            print_install(&r);
            println!("\n== setup");
            return setup_cmd(paths, None, None, setup::Answers::default(), false, false);
        } else {
            unasked = !setup::done_before(paths);
        }
    }
    let ok = r.ok && applied.iter().all(|a| a.ok);
    if json {
        println!(
            "{}",
            json!({"schema": SCHEMA, "install": r, "setup": applied})
        );
    } else {
        print_install(&r);
        print_applied(&applied);
        if r.ok && !opts.dry_run {
            println!(
                "\nbromigOS is installed. Reboot, sign in at the login screen, and you're in{}.",
                if unasked {
                    " (then: bromigos setup)"
                } else {
                    ""
                }
            );
        }
    }
    Ok(if ok { 0 } else { 1 })
}

fn print_install(r: &install::Report) {
    for s in &r.steps {
        let mark = match s.status {
            install::Status::Done => "done   ",
            install::Status::Ok => "ok     ",
            install::Status::Skipped => "skipped",
            install::Status::Planned => "would  ",
            install::Status::Failed => "FAILED ",
        };
        println!("{mark} {:<17} {}", s.name, s.detail);
        if r.dry_run {
            for c in &s.commands {
                println!("          $ {c}");
            }
        }
    }
    println!("log: {}", r.log.display());
}

fn print_applied(applied: &[setup::Applied]) {
    for a in applied {
        println!(
            "{} {:<9} {}",
            if a.ok { "set    " } else { "FAILED " },
            a.section,
            a.detail
        );
    }
}

/// The peripheral modules whose device is connected: (id, name, what was found, on).
fn peripherals_here(paths: &Paths) -> Vec<setup_tui::PeripheralHere> {
    use bromigos_core::peripheral as pm;
    let root = pm::root();
    let on = pm::read_choices(paths).unwrap_or_default();
    pm::modules(paths)
        .0
        .into_iter()
        .filter_map(|m| {
            let found = pm::found_here(&m, &root);
            (!found.is_empty()).then(|| setup_tui::PeripheralHere {
                found: found
                    .iter()
                    .map(|f| f.name.clone())
                    .collect::<Vec<_>>()
                    .join(", "),
                enabled: on.get(&m.id).is_some_and(|c| c.enabled),
                id: m.id,
                name: m.name,
                description: m.description,
            })
        })
        .collect()
}

fn setup_cmd(
    paths: &Paths,
    section: Option<&str>,
    answers: Option<&Path>,
    flags: setup::Answers,
    replace: bool,
    json: bool,
) -> Result<i32> {
    let sections: Vec<&str> = match section {
        Some(s) if setup::SECTIONS.contains(&s) => vec![s],
        Some(s) => {
            eprintln!(
                "bromigos setup: no section {s:?} ({})",
                setup::SECTIONS.join(", ")
            );
            return Ok(2);
        }
        None => setup::SECTIONS.to_vec(),
    };
    let found = setup::detect(paths);
    let servers = if sections.contains(&"create") {
        bromigos_core::create::detect(paths)
    } else {
        vec![]
    };
    let from_file = match answers {
        Some(f) => Some(setup::load_answers(f).map_err(anyhow::Error::msg)?),
        None => None,
    };
    let unattended = from_file.is_some() || flags != setup::Answers::default();
    let a = if let Some(a) = from_file {
        a
    } else if unattended {
        flags
    } else {
        if !std::io::IsTerminal::is_terminal(&std::io::stdin()) {
            eprintln!(
                "bromigos setup: no terminal to ask in; give --answers FILE or the flags (bromigos setup --help)"
            );
            return Ok(2);
        }
        let (hardware, hardware_todo) = if sections.contains(&"hardware") {
            hw::page_text(paths)
        } else {
            (String::new(), false)
        };
        let (aur, aur_on) = if sections.contains(&"aur") {
            aur::page_text(paths)
        } else {
            (String::new(), true)
        };
        let cx = setup_tui::Context {
            monitors: found.clone(),
            aur,
            aur_on,
            hardware,
            hardware_todo,
            themes: theme::names(&theme::Locations::new(paths)),
            current_theme: theme::current(paths).name,
            dens: dens(paths),
            homelab_installed: update::installed(paths).contains_key("bromigos-homelab"),
            homelab_ai: setup::homelab_has_ai(paths),
            nolgia_installed: bromigos_core::create::nolgia_installed(),
            servers: servers.clone(),
            gpu: Path::new("/dev/nvidia0").exists() || Path::new("/dev/dri/renderD128").exists(),
            peripherals: peripherals_here(paths),
            accessibility: bromigos_core::accessibility::read(paths),
        };
        match setup_tui::run(setup_tui::pages(&cx, &sections))? {
            Some(a) => a,
            None => {
                println!("setup: left; nothing changed");
                return Ok(0);
            }
        }
    };
    // only the sections asked for
    let a = setup::Answers {
        monitors: a.monitors.filter(|_| sections.contains(&"monitors")),
        aur: a.aur.filter(|_| sections.contains(&"aur")),
        hardware: a.hardware.filter(|_| sections.contains(&"hardware")),
        accessibility: a
            .accessibility
            .filter(|_| sections.contains(&"accessibility")),
        extensions: a.extensions.filter(|_| sections.contains(&"extensions")),
        theme: a.theme.filter(|_| sections.contains(&"theme")),
        vector: a.vector.filter(|_| sections.contains(&"vector")),
        voice: a.voice.filter(|_| sections.contains(&"voice")),
        homelab: a.homelab.filter(|_| sections.contains(&"homelab")),
        targets: a.targets.filter(|_| sections.contains(&"targets")),
        create: a.create.filter(|_| sections.contains(&"create")),
        peripherals: a.peripherals.filter(|_| sections.contains(&"peripherals")),
    };
    let applied = setup::apply(paths, &a, &found, &servers, !unattended, replace);
    let ok = applied.iter().all(|x| x.ok);
    if json {
        println!("{}", json!({"schema": SCHEMA, "setup": applied}));
    } else {
        print_applied(&applied);
    }
    Ok(if ok { 0 } else { 1 })
}

/// The Wick's den variants installed: bromigOS's empty one and the user's own art.
fn dens(paths: &Paths) -> Vec<String> {
    let mut out = vec![];
    for (v, file) in [
        ("empty", "bromigos-den-empty-2560x1440.jpg"),
        ("den", "bromigos-den-operator-2560x1440.jpg"),
        ("masked", "bromigos-den-masked-2560x1440.jpg"),
        ("v1", "bromigos-den-2560x1440-v1.jpg"),
    ] {
        if paths.home.join(".config/wallpaper").join(file).exists()
            || paths.share_dir.join("wallpaper").join(file).exists()
        {
            out.push(v.to_string());
        }
    }
    out
}
