//! bromigOS core: the rules the `bromigos` CLI and the Python tools share.
//!
//! - [`accessibility`]: reduced motion and high contrast (the user's settings, the contrast transform).
//! - [`aur`]: the AUR: bromigOS's paru, the setting, the update's AUR step (docs/aur.md).
//! - [`boot`]: the boot menu: bromigOS's GRUB theme in the current theme's colours.
//! - [`session`]: find the live Hyprland session, import it, exec under it.
//! - [`hypr_hold`]: Hyprland's auto-reload held off while pacman replaces its config.
//! - [`config`]: the live layer's config and the user's animation switches.
//! - [`anim`]: the switchable animations.
//! - [`lock`]: the lock launcher (keeps the screen locked if the locker crashes).
//! - [`ipc`]: the live layer's and VECTOR's control sockets.
//! - [`profile`]: who the user is and what VECTOR calls them.
//! - [`commands`]: the `bromigos <group> <name>` router for external commands.
//! - [`theme`]: themes as data: list, render and set the look.
//! - [`previews`]: the theme switcher's previews, drawn in the background when a theme may have changed.
//! - [`ext`]: `bromigos ext`: extensions (themes, decks, widgets, VECTOR plugins, …) from git.
//! - [`idle`]: the idle policy as data: idle.toml, the rendered hypridle config, stay awake.
//! - [`migrate`]: the scripts `bromigos update` runs to bring an install forward.
//! - [`update`]: `bromigos update` and `bromigos restart`: packages, migrations, restarts.
//! - [`reboot`]: what waits for the computer to restart: a new kernel, or NVIDIA's driver.
//! - [`whats_new`]: `bromigos whats-new`: the release notes installed with bromigOS.
//! - [`install`]: `bromigos install`: packages, services, configs, settings, the theme.
//! - [`peripheral`]: `bromigos peripheral`: optional device modules (a keyboard's macro keys, dial, lighting).
//! - [`hw`]: `bromigos hw`: the GPUs and the machine's kind, and what bromigOS sets up for them.
//! - [`create`]: the creation tools setup finds (ComfyUI servers, nolgia) and picks.
//! - [`setup`]: `bromigos setup`: the first-run questions (monitors, theme, VECTOR, voice, homelab).
//! - [`paths`]: XDG locations.

pub mod accessibility;
pub mod anim;
pub mod aur;
pub mod boot;
pub mod channel;
pub mod commands;
pub mod config;
pub mod create;
pub mod ext;
pub mod hw;
pub mod hypr_hold;
pub mod idle;
pub mod install;
pub mod ipc;
pub mod lock;
pub mod migrate;
pub mod paths;
pub mod peripheral;
pub mod previews;
pub mod profile;
pub mod reboot;
pub mod restartd;
pub mod secureboot;
pub mod session;
pub mod setup;
pub mod snapshot;
pub mod targets;
pub mod theme;
pub mod update;
pub mod whats_new;

use std::process::{Command, Stdio};

/// Logs to the journal (`logger -t <tag> <message>`); failures are ignored.
pub fn log(tag: &str, message: &str) {
    let _ = Command::new("logger")
        .args(["-t", tag, "--", message])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}
